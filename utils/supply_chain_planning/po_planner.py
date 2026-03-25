# utils/supply_chain_planning/po_planner.py

"""
Core PO Planner Engine — Layer 3 of SCM Planning Pipeline.

Takes SupplyChainGAPResult → produces vendor-grouped PO suggestions.

Pipeline:
1. Extract shortage items from GAP result (po_fg_suggestions + po_raw_suggestions)
2. Deduct existing pending POs → net shortage
3. Match each product to vendor (pricing resolver)
4. Apply MOQ/SPQ rounding → suggested quantity
5. Calculate order timing (lead time → must_order_by → urgency)
6. Group by vendor → VendorPOGroups
7. Output POSuggestionResult

Usage:
    planner = POPlanner(pricing_df, last_po_df, performance_df, leadtime_rules_df)
    result = planner.plan_from_gap_result(gap_result)
    # or
    result = planner.plan_from_shortages(shortage_items)
"""

import pandas as pd
import logging
from datetime import date, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from .planning_constants import (
    URGENCY_LEVELS, SHORTAGE_SOURCE, PRICE_SOURCE
)
from .po_pricing_resolver import POPricingResolver, VendorMatch, QuantitySuggestion
from .po_lead_time_calculator import POLeadTimeCalculator, OrderTimingResult
from .po_result import POLineItem, VendorPOGroup, POSuggestionResult
from .validators import (
    extract_all_shortages, validate_gap_result, validate_gap_filters,
    extract_demand_dates, extract_demand_composition,
    ValidationResult, safe_extract_field
)

logger = logging.getLogger(__name__)


@dataclass
class ShortageItem:
    """Normalized shortage item from GAP result"""
    product_id: int
    pt_code: str = ''
    product_name: str = ''
    brand: str = ''
    package_size: str = ''
    uom: str = ''
    shortage_qty: float = 0         # abs(net_gap)
    shortage_source: str = ''       # FG_TRADING or RAW_MATERIAL
    priority: int = 99
    demand_date: Optional[date] = None  # earliest demand date if available


class POPlanner:
    """
    Core PO Planning engine.

    Orchestrates: shortage extraction → vendor matching → quantity rounding
    → timing calculation → vendor grouping.
    """

    def __init__(
        self,
        vendor_pricing_df: pd.DataFrame,
        last_po_prices_df: Optional[pd.DataFrame] = None,
        vendor_performance_df: Optional[pd.DataFrame] = None,
        leadtime_rules_df: Optional[pd.DataFrame] = None,
        pending_po_df: Optional[pd.DataFrame] = None,
    ):
        """
        Args:
            vendor_pricing_df: From planning_data_loader.load_vendor_pricing()
            last_po_prices_df: From planning_data_loader.load_last_po_prices()
            vendor_performance_df: From planning_data_loader.load_vendor_performance()
            leadtime_rules_df: From planning_data_loader.load_leadtime_rules()
            pending_po_df: From planning_data_loader.load_pending_po_by_product()
        """
        # Initialize sub-engines
        self._resolver = POPricingResolver(
            vendor_pricing_df,
            last_po_prices_df,
            vendor_performance_df
        )
        self._timing_calc = POLeadTimeCalculator(
            leadtime_rules_df,
            vendor_performance_df
        )

        # Pending PO lookup: product_id → pending_po_qty
        self._pending_po = {}
        if pending_po_df is not None and not pending_po_df.empty:
            for _, row in pending_po_df.iterrows():
                pid = row.get('product_id')
                qty = row.get('pending_po_qty', 0) or 0
                if pid is not None and qty > 0:
                    self._pending_po[int(pid)] = float(qty)

        logger.info(
            f"POPlanner initialized: "
            f"resolver ready, "
            f"{len(self._pending_po)} products with pending POs"
        )

    # =========================================================================
    # MAIN ENTRY: FROM GAP RESULT
    # =========================================================================

    def plan_from_gap_result(
        self,
        gap_result,
        strategy: str = 'CHEAPEST',
        default_demand_date: Optional[date] = None,
        deduct_pending_po: bool = True,
        skip_zero_shortage: bool = True,
    ) -> POSuggestionResult:
        """
        Generate PO suggestions from SupplyChainGAPResult.

        Uses validated extraction (validators.py) to safely convert
        ActionRecommendation objects from GAP module into ShortageItems.

        Args:
            gap_result: SupplyChainGAPResult from supply_chain_gap module
            strategy: CHEAPEST, FASTEST, or PREFERRED
            default_demand_date: Fallback demand date if not derivable
            deduct_pending_po: Subtract existing pending POs from shortage
            skip_zero_shortage: Skip items where net shortage ≤ 0 after deduction
        """
        logger.info("POPlanner: extracting shortages from GAP result (with validation)...")

        # Step 0: Review GAP filters (informational — never blocks)
        # Blocking/confirmation is handled at the PAGE level before calling this method.
        filter_review = validate_gap_filters(gap_result)

        # Validated extraction — catches None fields, type mismatches, missing attrs
        shortage_dicts, validation = extract_all_shortages(gap_result)

        if not validation.is_valid:
            logger.error(f"GAP result validation FAILED: {validation.errors}")
            result = POSuggestionResult(
                strategy=strategy,
                default_demand_date=default_demand_date,
            )
            result.metrics['validation_errors'] = validation.errors
            result.input_summary = {
                'source_mode': 'GAP_RESULT',
                'filter_review': filter_review,
            }
            return result

        if not shortage_dicts:
            logger.info("POPlanner: no shortage items found in GAP result")
            result = POSuggestionResult(
                strategy=strategy,
                default_demand_date=default_demand_date,
            )
            result.input_summary = {
                'source_mode': 'GAP_RESULT',
                'filter_review': filter_review,
            }
            return result

        # Extract per-product demand dates from GAP period data
        # Replaces fixed "today + 30 days" with actual earliest shortage period
        demand_dates = extract_demand_dates(gap_result)
        dates_found = len(demand_dates)
        
        # Convert validated dicts → ShortageItem objects
        shortages = []
        for d in shortage_dicts:
            pid = d['product_id']
            shortages.append(ShortageItem(
                product_id=pid,
                pt_code=d['pt_code'],
                product_name=d['product_name'],
                brand=d['brand'],
                package_size=d['package_size'],
                uom=d['uom'],
                shortage_qty=d['shortage_qty'],
                shortage_source=d['shortage_source'],
                priority=d['priority'],
                demand_date=demand_dates.get(pid),  # None → fallback to default_demand_date
            ))

        logger.info(
            f"POPlanner: {len(shortages)} shortage items "
            f"({sum(1 for s in shortages if s.shortage_source == 'FG_TRADING')} FG, "
            f"{sum(1 for s in shortages if s.shortage_source == 'RAW_MATERIAL')} Raw)"
            f", {dates_found}/{len(shortages)} with demand dates from GAP period data"
            f"{f', {validation.items_skipped} skipped' if validation.items_skipped else ''}"
        )

        if validation.warnings:
            logger.warning(f"POPlanner: {len(validation.warnings)} extraction warnings")

        result = self.plan_from_shortages(
            shortages=shortages,
            strategy=strategy,
            default_demand_date=default_demand_date,
            # CRITICAL: Force deduct_pending_po=False when input comes from GAP result.
            # GAP module already includes PO in supply (unified_supply_view supply_source='PURCHASE_ORDER'
            # and raw_material_supply_summary_view.supply_purchase_order).
            # Deducting again here would be double-counting — items would be incorrectly skipped.
            deduct_pending_po=False,
            skip_zero_shortage=skip_zero_shortage,
        )

        if deduct_pending_po:
            logger.info(
                "POPlanner: 'Deduct pending POs' ignored for GAP-sourced data — "
                "GAP already includes PO quantities in supply calculation. "
                "Toggle only applies to manual/standalone shortage input."
            )

        # Tag PO lines with demand composition (confirmed vs forecast)
        demand_comp = extract_demand_composition(gap_result)
        comp_tagged = 0
        for line in result.all_lines:
            comp = demand_comp.get(line.product_id, {})
            tag = comp.get('demand_tag', '')
            if tag:
                # Append to match_notes (existing field, no schema change)
                prefix = f"[{tag}]"
                if line.match_notes:
                    line.match_notes = f"{prefix} {line.match_notes}"
                else:
                    line.match_notes = prefix
                comp_tagged += 1

        # Patch input_summary with GAP-level extraction info
        result.input_summary['validation_skipped'] = validation.items_skipped
        result.input_summary['validation_warnings'] = len(validation.warnings)
        result.input_summary['source_mode'] = 'GAP_RESULT'
        result.input_summary['deduct_pending_po_requested'] = deduct_pending_po
        result.input_summary['deduct_pending_po_applied'] = False
        result.input_summary['filter_review'] = filter_review
        result.input_summary['demand_dates_from_gap'] = dates_found
        result.input_summary['demand_dates_fallback'] = len(shortages) - dates_found
        result.input_summary['demand_composition_tagged'] = comp_tagged

        # Attach filter warnings (non-blocking) to metrics for UI display
        if filter_review.get('items'):
            result.metrics['filter_warnings'] = [
                i for i in filter_review['items'] if i.get('status') == 'OFF'
            ]

        # Recompute reconciliation with updated input_summary
        result.metrics['reconciliation'] = result.get_reconciliation()

        return result

    # =========================================================================
    # MAIN ENTRY: FROM SHORTAGE LIST
    # =========================================================================

    def plan_from_shortages(
        self,
        shortages: List[ShortageItem],
        strategy: str = 'CHEAPEST',
        default_demand_date: Optional[date] = None,
        deduct_pending_po: bool = True,
        skip_zero_shortage: bool = True,
    ) -> POSuggestionResult:
        """
        Full PO planning pipeline from a list of shortage items.

        Returns:
            POSuggestionResult with vendor-grouped PO suggestions
        """
        if default_demand_date is None:
            default_demand_date = date.today() + timedelta(days=30)

        all_lines: List[POLineItem] = []
        unmatched: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        processing_errors: List[str] = []

        for item in shortages:
            try:
                line = self._process_shortage_item(
                    item=item,
                    strategy=strategy,
                    default_demand_date=default_demand_date,
                    deduct_pending_po=deduct_pending_po,
                )

                if line is None:
                    # No vendor found
                    unmatched.append({
                        'product_id': item.product_id,
                        'pt_code': item.pt_code,
                        'product_name': item.product_name,
                        'brand': item.brand,
                        'shortage_source': item.shortage_source,
                        'shortage_qty': item.shortage_qty,
                        'uom': item.uom,
                        'reason': 'No vendor found (no costbook or PO history)',
                    })
                    continue

                # Skip if net shortage is zero after pending PO deduction
                if skip_zero_shortage and line.net_shortage_qty <= 0:
                    skipped.append({
                        'product_id': item.product_id,
                        'pt_code': item.pt_code or line.pt_code,
                        'product_name': item.product_name or line.product_name,
                        'brand': item.brand or line.brand,
                        'shortage_source': item.shortage_source,
                        'shortage_qty': item.shortage_qty,
                        'pending_po_qty': line.pending_po_qty,
                        'net_shortage_qty': line.net_shortage_qty,
                        'uom': item.uom,
                        'vendor_name': line.vendor_name,
                        'reason': (
                            f'Pending PO ({line.pending_po_qty:,.0f}) covers '
                            f'shortage ({item.shortage_qty:,.0f})'
                        ),
                    })
                    logger.debug(
                        f"  Skipping {item.pt_code}: net shortage ≤ 0 "
                        f"(shortage={item.shortage_qty:.0f}, pending={line.pending_po_qty:.0f})"
                    )
                    continue

                all_lines.append(line)

            except Exception as e:
                # Item-level error — log and continue, don't crash the whole run
                error_msg = f"Error processing {item.pt_code} (id={item.product_id}): {e}"
                logger.error(error_msg, exc_info=True)
                processing_errors.append(error_msg)
                unmatched.append({
                    'product_id': item.product_id,
                    'pt_code': item.pt_code,
                    'product_name': item.product_name,
                    'brand': getattr(item, 'brand', ''),
                    'shortage_source': getattr(item, 'shortage_source', ''),
                    'shortage_qty': getattr(item, 'shortage_qty', 0),
                    'uom': getattr(item, 'uom', ''),
                    'reason': f'Processing error: {str(e)[:100]}',
                })

        # Group by vendor
        vendor_groups = self._group_by_vendor(all_lines)

        # Build input summary for reconciliation
        input_summary = {
            'total_items': len(shortages),
            'fg_trading_count': sum(1 for s in shortages if s.shortage_source == 'FG_TRADING'),
            'raw_material_count': sum(1 for s in shortages if s.shortage_source == 'RAW_MATERIAL'),
            'validation_skipped': 0,  # set by plan_from_gap_result if validation skips items
        }

        # Build result
        result = POSuggestionResult(
            all_lines=all_lines,
            vendor_groups=vendor_groups,
            unmatched_items=unmatched,
            skipped_items=skipped,
            input_summary=input_summary,
            strategy=strategy,
            default_demand_date=default_demand_date,
        )
        result.compute_metrics()

        # Attach processing errors to metrics for UI reporting
        if processing_errors:
            result.metrics['processing_errors'] = processing_errors
            logger.warning(f"POPlanner: {len(processing_errors)} items failed processing")

        logger.info(
            f"POPlanner complete: "
            f"input={len(shortages)}, "
            f"matched={len(all_lines)}, "
            f"skipped={len(skipped)} (pending PO covers), "
            f"unmatched={len(unmatched)}, "
            f"total ${result.metrics.get('total_value_usd', 0):,.0f}"
            f"{f', {len(processing_errors)} errors' if processing_errors else ''}"
        )

        return result

    # =========================================================================
    # PROCESS SINGLE SHORTAGE ITEM
    # =========================================================================

    def _process_shortage_item(
        self,
        item: ShortageItem,
        strategy: str,
        default_demand_date: date,
        deduct_pending_po: bool,
    ) -> Optional[POLineItem]:
        """
        Process one shortage item through the full pipeline.

        Returns POLineItem if vendor found, None if no vendor.
        """
        # Step 1: Vendor matching
        match = self._resolver.resolve_product(
            product_id=item.product_id,
            strategy=strategy,
        )

        if not match.matched:
            return None

        # Step 2: Deduct pending POs
        pending_qty = 0.0
        if deduct_pending_po:
            pending_qty = self._pending_po.get(item.product_id, 0)

        net_shortage = max(0, item.shortage_qty - pending_qty)

        # Step 3: MOQ/SPQ rounding
        qty_result = self._resolver.apply_moq_spq(
            required_qty=net_shortage,
            moq=match.moq,
            spq=match.spq,
        )

        # Step 4: Calculate timing
        demand_dt = item.demand_date or default_demand_date

        timing = self._timing_calc.calculate_timing(
            demand_date=demand_dt,
            lead_time_max_days=match.lead_time_max_days,
            vendor_location_type=match.vendor_location_type,
            vendor_id=match.vendor_id,
            trade_term=match.trade_term,
            shipping_mode=match.shipping_mode,
        )

        # Step 5: Build line item — guard against None prices
        unit_price = match.standard_unit_price or 0.0
        unit_price_usd = match.standard_unit_price_usd or 0.0
        line_value_usd = round(qty_result.suggested_qty * unit_price_usd, 2)

        line = POLineItem(
            # Product
            product_id=item.product_id,
            pt_code=match.pt_code or item.pt_code,
            product_name=match.product_name or item.product_name,
            brand=match.brand or item.brand,
            package_size=match.package_size or item.package_size,
            standard_uom=match.standard_uom or item.uom,

            # Shortage
            shortage_source=item.shortage_source,
            shortage_qty=item.shortage_qty,
            pending_po_qty=pending_qty,
            net_shortage_qty=net_shortage,

            # Suggested order
            suggested_qty=qty_result.suggested_qty,
            moq_applied=qty_result.moq_applied,
            spq_applied=qty_result.spq_applied,
            excess_qty=qty_result.excess_qty,

            # Vendor
            vendor_id=match.vendor_id,
            vendor_name=match.vendor_name,
            vendor_code=match.vendor_code,
            vendor_location_type=match.vendor_location_type,

            # Pricing
            unit_price=unit_price,
            unit_price_usd=unit_price_usd,
            currency_code=match.currency_code,
            buying_uom=match.buying_uom,
            uom_conversion=match.uom_conversion,
            vat_percent=match.vat_percent,
            line_value_usd=round(line_value_usd, 2),
            moq=match.moq,
            spq=match.spq,

            # Price source
            price_source=match.price_source,
            costbook_number=match.costbook_number,
            last_po_number=match.last_po_number,

            # Lead time
            lead_time_days=timing.lead_time.total_lead_time_days,
            lead_time_source=timing.lead_time.lead_time_source,
            vendor_reliability=timing.lead_time.vendor_reliability,

            # Timing
            demand_date=timing.demand_date,
            must_order_by=timing.must_order_by,
            expected_arrival=timing.expected_arrival,
            days_until_must_order=timing.days_until_must_order,
            urgency_level=timing.urgency_level,
            urgency_priority=timing.urgency_priority,
            is_overdue=timing.is_overdue,

            # Terms
            trade_term=match.trade_term,
            payment_term=match.payment_term,
            shipping_mode=match.shipping_mode,

            # Notes
            match_notes=match.match_notes,
            quantity_notes=qty_result.notes,
        )

        return line

    # =========================================================================
    # EXTRACT SHORTAGES FROM GAP RESULT
    # =========================================================================

    def _extract_shortages_from_gap(self, gap_result) -> List[ShortageItem]:
        """
        DEPRECATED: Use plan_from_gap_result() which uses validators.extract_all_shortages().
        
        Kept for backward compatibility — now delegates to validated extraction.
        """
        import warnings
        warnings.warn(
            "_extract_shortages_from_gap is deprecated. "
            "plan_from_gap_result now uses validators.extract_all_shortages()",
            DeprecationWarning, stacklevel=2
        )
        shortage_dicts, _ = extract_all_shortages(gap_result)
        return [
            ShortageItem(
                product_id=d['product_id'],
                pt_code=d['pt_code'],
                product_name=d['product_name'],
                brand=d['brand'],
                package_size=d['package_size'],
                uom=d['uom'],
                shortage_qty=d['shortage_qty'],
                shortage_source=d['shortage_source'],
                priority=d['priority'],
            )
            for d in shortage_dicts
        ]

    # =========================================================================
    # GROUP BY VENDOR
    # =========================================================================

    def _group_by_vendor(
        self, lines: List[POLineItem]
    ) -> Dict[int, VendorPOGroup]:
        """Group PO lines by vendor → one VendorPOGroup per vendor"""
        groups: Dict[int, VendorPOGroup] = {}

        for line in lines:
            vid = line.vendor_id
            if vid is None:
                continue

            if vid not in groups:
                groups[vid] = VendorPOGroup(
                    vendor_id=vid,
                    vendor_name=line.vendor_name,
                    vendor_code=line.vendor_code,
                    vendor_location_type=line.vendor_location_type,
                    vendor_reliability=line.vendor_reliability,
                )

            groups[vid].lines.append(line)

        # Compute aggregates
        for group in groups.values():
            group.compute_aggregates()

        # Sort by urgency (most urgent vendor first)
        sorted_groups = dict(
            sorted(groups.items(), key=lambda kv: kv[1].max_urgency_priority)
        )

        return sorted_groups

    # =========================================================================
    # CONVENIENCE: PLAN WITH AUTO-LOADED DATA
    # =========================================================================

    @classmethod
    def create_with_data_loader(cls, data_loader=None) -> 'POPlanner':
        """
        Factory: create POPlanner with auto-loaded data from database.

        Usage:
            planner = POPlanner.create_with_data_loader()
            result = planner.plan_from_gap_result(gap_result)
        """
        if data_loader is None:
            from .planning_data_loader import get_planning_data_loader
            data_loader = get_planning_data_loader()

        logger.info("POPlanner: loading data from database...")

        pricing_df = data_loader.load_vendor_pricing()
        last_po_df = data_loader.load_last_po_prices()
        perf_df = data_loader.load_vendor_performance()
        rules_df = data_loader.load_leadtime_rules()
        pending_df = data_loader.load_pending_po_by_product()

        return cls(
            vendor_pricing_df=pricing_df,
            last_po_prices_df=last_po_df,
            vendor_performance_df=perf_df,
            leadtime_rules_df=rules_df,
            pending_po_df=pending_df,
        )

    # =========================================================================
    # RE-PLAN WITH DIFFERENT STRATEGY
    # =========================================================================

    def replan_item(
        self,
        product_id: int,
        shortage_qty: float,
        shortage_source: str = 'FG_TRADING',
        strategy: str = 'FASTEST',
        preferred_vendor_id: Optional[int] = None,
        demand_date: Optional[date] = None,
    ) -> Optional[POLineItem]:
        """
        Re-plan a single item with different strategy or vendor.
        Useful for UI: user selects a different vendor or strategy.
        """
        match = self._resolver.resolve_product(
            product_id=product_id,
            preferred_vendor_id=preferred_vendor_id,
            strategy=strategy,
        )

        if not match.matched:
            return None

        pending = self._pending_po.get(product_id, 0)
        net = max(0, shortage_qty - pending)
        qty = self._resolver.apply_moq_spq(net, match.moq, match.spq)

        if demand_date is None:
            demand_date = date.today() + timedelta(days=30)

        timing = self._timing_calc.calculate_timing(
            demand_date=demand_date,
            lead_time_max_days=match.lead_time_max_days,
            vendor_location_type=match.vendor_location_type,
            vendor_id=match.vendor_id,
            trade_term=match.trade_term,
            shipping_mode=match.shipping_mode,
        )

        return POLineItem(
            product_id=product_id,
            pt_code=match.pt_code,
            product_name=match.product_name,
            brand=match.brand,
            package_size=match.package_size,
            standard_uom=match.standard_uom,
            shortage_source=shortage_source,
            shortage_qty=shortage_qty,
            pending_po_qty=pending,
            net_shortage_qty=net,
            suggested_qty=qty.suggested_qty,
            moq_applied=qty.moq_applied,
            spq_applied=qty.spq_applied,
            excess_qty=qty.excess_qty,
            vendor_id=match.vendor_id,
            vendor_name=match.vendor_name,
            vendor_code=match.vendor_code,
            vendor_location_type=match.vendor_location_type,
            unit_price=match.standard_unit_price,
            unit_price_usd=match.standard_unit_price_usd,
            currency_code=match.currency_code,
            buying_uom=match.buying_uom,
            uom_conversion=match.uom_conversion,
            vat_percent=match.vat_percent,
            line_value_usd=round(qty.suggested_qty * match.standard_unit_price_usd, 2),
            moq=match.moq,
            spq=match.spq,
            price_source=match.price_source,
            costbook_number=match.costbook_number,
            last_po_number=match.last_po_number,
            lead_time_days=timing.lead_time.total_lead_time_days,
            lead_time_source=timing.lead_time.lead_time_source,
            vendor_reliability=timing.lead_time.vendor_reliability,
            demand_date=timing.demand_date,
            must_order_by=timing.must_order_by,
            expected_arrival=timing.expected_arrival,
            days_until_must_order=timing.days_until_must_order,
            urgency_level=timing.urgency_level,
            urgency_priority=timing.urgency_priority,
            is_overdue=timing.is_overdue,
            trade_term=match.trade_term,
            payment_term=match.payment_term,
            shipping_mode=match.shipping_mode,
            match_notes=match.match_notes,
            quantity_notes=qty.notes,
        )

    # =========================================================================
    # GET ALL VENDOR OPTIONS FOR A PRODUCT
    # =========================================================================

    def get_vendor_options(self, product_id: int) -> List[VendorMatch]:
        """Get all available vendors for a product (for UI comparison)"""
        return self._resolver.get_vendor_options(product_id)

    def get_coverage_stats(self, product_ids: List[int]) -> Dict[str, Any]:
        """Get vendor coverage statistics"""
        return self._resolver.get_coverage_stats(product_ids)