# utils/supply_chain_planning/po_pricing_resolver.py

"""
PO Pricing Resolver — matches shortage products to vendor pricing.

For each product that needs purchasing:
1. Primary: Active costbook pricing (vendor_product_pricing_view)
2. Fallback: Last PO price (product_purchase_orders)
3. No match: Flag as VENDOR_NEEDED

Also resolves MOQ/SPQ rounding and multi-vendor selection.
"""

import pandas as pd
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .planning_constants import (
    PRICE_SOURCE, MOQ_SPQ_CONFIG, SHORTAGE_SOURCE
)

logger = logging.getLogger(__name__)


@dataclass
class VendorMatch:
    """Result of matching a product to a vendor"""
    product_id: int
    pt_code: str = ''
    product_name: str = ''
    brand: str = ''
    package_size: str = ''
    standard_uom: str = ''

    # Vendor
    vendor_id: Optional[int] = None
    vendor_name: str = ''
    vendor_code: str = ''
    vendor_type: str = ''
    vendor_location_type: str = ''

    # Pricing
    standard_unit_price: float = 0
    buying_unit_price: float = 0
    standard_unit_price_usd: float = 0
    buying_unit_price_usd: float = 0
    currency_code: str = ''
    buying_uom: str = ''
    uom_conversion: str = ''
    vat_percent: float = 0

    # MOQ / SPQ
    moq: float = 0
    spq: float = 0
    moq_value_usd: float = 0

    # Lead time (days, already converted)
    lead_time_max_days: Optional[int] = None
    lead_time_min_days: Optional[int] = None

    # Terms
    trade_term: str = ''
    payment_term: str = ''
    shipping_mode: str = ''

    # Source tracking
    price_source: str = 'NO_SOURCE'     # COSTBOOK, LAST_PO, NO_SOURCE
    costbook_detail_id: Optional[int] = None
    costbook_id: Optional[int] = None
    costbook_number: str = ''
    costbook_date: Optional[str] = None
    valid_to_date: Optional[str] = None
    last_po_number: str = ''
    last_po_date: Optional[str] = None

    # Matching status
    matched: bool = False
    match_notes: str = ''


@dataclass
class QuantitySuggestion:
    """Result of MOQ/SPQ rounding"""
    required_qty: float             # original shortage qty
    suggested_qty: float            # after MOQ/SPQ rounding
    moq_applied: bool = False       # was MOQ applied?
    spq_applied: bool = False       # was SPQ rounding applied?
    excess_qty: float = 0           # suggested - required (buffer)
    excess_ratio: float = 0         # excess / required
    notes: str = ''


class POPricingResolver:
    """
    Resolves vendor pricing for shortage products.
    
    Usage:
        resolver = POPricingResolver(pricing_df, last_po_df)
        match = resolver.resolve_product(product_id)
        qty = resolver.apply_moq_spq(required_qty, match.moq, match.spq)
    """

    def __init__(
        self,
        vendor_pricing_df: pd.DataFrame,
        last_po_prices_df: Optional[pd.DataFrame] = None,
        vendor_performance_df: Optional[pd.DataFrame] = None
    ):
        """
        Args:
            vendor_pricing_df: From planning_data_loader.load_vendor_pricing()
            last_po_prices_df: From planning_data_loader.load_last_po_prices()
            vendor_performance_df: From planning_data_loader.load_vendor_performance()
        """
        self._pricing = vendor_pricing_df if vendor_pricing_df is not None else pd.DataFrame()
        self._last_po = last_po_prices_df if last_po_prices_df is not None else pd.DataFrame()
        self._performance = vendor_performance_df if vendor_performance_df is not None else pd.DataFrame()

        # Build lookup indexes
        self._pricing_by_product = self._build_pricing_index()
        self._last_po_by_product = self._build_last_po_index()
        self._performance_by_vendor = self._build_performance_index()

        logger.info(
            f"POPricingResolver initialized: "
            f"{len(self._pricing)} costbook prices, "
            f"{len(self._last_po)} last PO prices, "
            f"{len(self._performance)} vendor performance records"
        )

    # =========================================================================
    # INDEX BUILDERS
    # =========================================================================

    def _build_pricing_index(self) -> Dict[int, pd.DataFrame]:
        """Index costbook pricing by product_id → list of vendor options"""
        if self._pricing.empty:
            return {}
        return {
            pid: group for pid, group in self._pricing.groupby('product_id')
        }

    def _build_last_po_index(self) -> Dict[int, pd.DataFrame]:
        """Index last PO prices by product_id"""
        if self._last_po.empty:
            return {}
        return {
            pid: group for pid, group in self._last_po.groupby('product_id')
        }

    def _build_performance_index(self) -> Dict[int, Dict[str, Any]]:
        """Index vendor performance by vendor_id"""
        if self._performance.empty:
            return {}
        return {
            int(row['vendor_id']): row.to_dict()
            for _, row in self._performance.iterrows()
        }

    # =========================================================================
    # CORE: RESOLVE PRODUCT → VENDOR MATCH
    # =========================================================================

    def resolve_product(
        self,
        product_id: int,
        preferred_vendor_id: Optional[int] = None,
        strategy: str = 'CHEAPEST'
    ) -> VendorMatch:
        """
        Match a product to the best vendor with pricing.

        Strategy:
            CHEAPEST: Lowest unit price (default for PLANNED urgency)
            FASTEST: Shortest lead time (for URGENT/OVERDUE)
            PREFERRED: Use preferred_vendor_id if available

        Returns:
            VendorMatch with vendor info, pricing, lead time
        """
        # Try costbook first
        match = self._try_costbook_match(product_id, preferred_vendor_id, strategy)
        if match.matched:
            return match

        # Fallback: last PO price
        match = self._try_last_po_match(product_id)
        if match.matched:
            return match

        # No match found
        return VendorMatch(
            product_id=product_id,
            price_source='NO_SOURCE',
            matched=False,
            match_notes='No costbook or PO history found for this product'
        )

    def _try_costbook_match(
        self,
        product_id: int,
        preferred_vendor_id: Optional[int],
        strategy: str
    ) -> VendorMatch:
        """Try matching from costbook pricing view"""

        options = self._pricing_by_product.get(product_id)
        if options is None or options.empty:
            return VendorMatch(product_id=product_id, matched=False)

        # If preferred vendor specified and available
        if preferred_vendor_id is not None:
            preferred = options[options['vendor_id'] == preferred_vendor_id]
            if not preferred.empty:
                return self._row_to_match(preferred.iloc[0], 'COSTBOOK',
                                          f'Preferred vendor #{preferred_vendor_id}')

        # Apply strategy
        if strategy == 'FASTEST' and 'lead_time_max_days' in options.columns:
            # Sort by lead time (shortest first), then price
            candidates = options[options['lead_time_max_days'].notna()]
            if not candidates.empty:
                best = candidates.sort_values(
                    ['lead_time_max_days', 'standard_unit_price_usd']
                ).iloc[0]
                return self._row_to_match(best, 'COSTBOOK', 'Fastest lead time')

        # Default: CHEAPEST (by USD price)
        if 'standard_unit_price_usd' in options.columns:
            candidates = options[options['standard_unit_price_usd'] > 0]
            if not candidates.empty:
                best = candidates.sort_values('standard_unit_price_usd').iloc[0]
                return self._row_to_match(best, 'COSTBOOK', 'Cheapest price')

        # Fallback: just take first available
        return self._row_to_match(options.iloc[0], 'COSTBOOK', 'First available costbook')

    def _try_last_po_match(self, product_id: int) -> VendorMatch:
        """Try matching from last PO history (returns most recent PO)"""

        options = self._last_po_by_product.get(product_id)
        if options is None or options.empty:
            return VendorMatch(product_id=product_id, matched=False)

        return self._last_po_row_to_match(options.iloc[0], product_id)

    def _last_po_row_to_match(self, row: pd.Series, product_id: int) -> VendorMatch:
        """Convert a single last-PO DataFrame row to VendorMatch"""
        return VendorMatch(
            product_id=product_id,
            pt_code=str(row.get('pt_code', '')),
            product_name=str(row.get('product_name', '')),
            standard_uom=str(row.get('standard_uom', '')),

            vendor_id=int(row['vendor_id']) if pd.notna(row.get('vendor_id')) else None,
            vendor_name=str(row.get('vendor_name', '')),

            standard_unit_price=float(row.get('standard_unit_price', 0) or 0),
            buying_unit_price=float(row.get('buying_unit_price', 0) or 0),
            standard_unit_price_usd=float(row.get('standard_unit_price_usd', 0) or 0),
            currency_code=str(row.get('currency_code', '')),
            buying_uom=str(row.get('buying_uom', '')),
            uom_conversion=str(row.get('uom_conversion', '')),

            # No MOQ/SPQ from PO history
            moq=0,
            spq=0,

            # No lead time from PO history
            lead_time_max_days=None,

            price_source='LAST_PO',
            last_po_number=str(row.get('po_number', '')),
            last_po_date=str(row.get('po_date', '')) if pd.notna(row.get('po_date')) else None,

            matched=True,
            match_notes=f"Fallback: last PO {row.get('po_number', '')} ({row.get('po_date', '')})"
        )

    def _row_to_match(self, row: pd.Series, source: str, notes: str) -> VendorMatch:
        """Convert a pricing DataFrame row to VendorMatch"""
        return VendorMatch(
            product_id=int(row['product_id']),
            pt_code=str(row.get('pt_code', '')),
            product_name=str(row.get('product_name', '')),
            brand=str(row.get('brand', '')) if pd.notna(row.get('brand')) else '',
            package_size=str(row.get('package_size', '')) if pd.notna(row.get('package_size')) else '',
            standard_uom=str(row.get('standard_uom', '')),

            vendor_id=int(row['vendor_id']) if pd.notna(row.get('vendor_id')) else None,
            vendor_name=str(row.get('vendor_name', '')),
            vendor_code=str(row.get('vendor_code', '')) if pd.notna(row.get('vendor_code')) else '',
            vendor_type=str(row.get('vendor_type', '')),
            vendor_location_type=str(row.get('vendor_location_type', '')),

            standard_unit_price=float(row.get('standard_unit_price', 0) or 0),
            buying_unit_price=float(row.get('buying_unit_price', 0) or 0),
            standard_unit_price_usd=float(row.get('standard_unit_price_usd', 0) or 0),
            buying_unit_price_usd=float(row.get('buying_unit_price_usd', 0) or 0),
            currency_code=str(row.get('currency_code', '')),
            buying_uom=str(row.get('buying_uom', '')) if pd.notna(row.get('buying_uom')) else '',
            uom_conversion=str(row.get('uom_conversion', '')) if pd.notna(row.get('uom_conversion')) else '',
            vat_percent=float(row.get('vat_percent', 0) or 0),

            moq=float(row.get('moq', 0) or 0),
            spq=float(row.get('spq', 0) or 0),
            moq_value_usd=float(row.get('moq_value_usd', 0) or 0),

            lead_time_max_days=int(row['lead_time_max_days']) if pd.notna(row.get('lead_time_max_days')) else None,
            lead_time_min_days=int(row['lead_time_min_days']) if pd.notna(row.get('lead_time_min_days')) else None,

            trade_term=str(row.get('trade_term', '')) if pd.notna(row.get('trade_term')) else '',
            payment_term=str(row.get('payment_term', '')) if pd.notna(row.get('payment_term')) else '',
            shipping_mode=str(row.get('shipping_mode_name', '')) if pd.notna(row.get('shipping_mode_name')) else '',

            price_source=source,
            costbook_detail_id=int(row['costbook_detail_id']) if pd.notna(row.get('costbook_detail_id')) else None,
            costbook_id=int(row['costbook_id']) if pd.notna(row.get('costbook_id')) else None,
            costbook_number=str(row.get('costbook_number', '')) if pd.notna(row.get('costbook_number')) else '',
            costbook_date=str(row.get('costbook_date', '')) if pd.notna(row.get('costbook_date')) else None,
            valid_to_date=str(row.get('valid_to_date', '')) if pd.notna(row.get('valid_to_date')) else None,

            matched=True,
            match_notes=notes,
        )

    # =========================================================================
    # RESOLVE BATCH (all shortage products at once)
    # =========================================================================

    def resolve_batch(
        self,
        product_ids: List[int],
        strategy: str = 'CHEAPEST'
    ) -> Dict[int, VendorMatch]:
        """
        Resolve vendor for a list of products.

        Returns:
            Dict mapping product_id → VendorMatch
        """
        results = {}
        for pid in product_ids:
            results[pid] = self.resolve_product(pid, strategy=strategy)

        matched = sum(1 for m in results.values() if m.matched)
        logger.info(
            f"Batch resolve: {matched}/{len(product_ids)} products matched to vendors"
        )
        return results

    # =========================================================================
    # GET ALL VENDOR OPTIONS FOR A PRODUCT (for multi-vendor comparison)
    # =========================================================================

    def get_vendor_options(self, product_id: int) -> List[VendorMatch]:
        """
        Get ALL vendor options for a product (not just the best one).
        Useful for UI: show user all vendors and let them choose.
        """
        options = []

        # Costbook options
        pricing = self._pricing_by_product.get(product_id)
        if pricing is not None and not pricing.empty:
            for _, row in pricing.iterrows():
                options.append(self._row_to_match(row, 'COSTBOOK', 'Costbook option'))

        # Last PO options (only if not already covered by costbook)
        costbook_vendors = {m.vendor_id for m in options}
        last_po = self._last_po_by_product.get(product_id)
        if last_po is not None and not last_po.empty:
            for _, row in last_po.iterrows():
                vid = int(row['vendor_id']) if pd.notna(row.get('vendor_id')) else None
                if vid not in costbook_vendors:
                    match = self._last_po_row_to_match(row, product_id)
                    if match.matched:
                        options.append(match)
                        costbook_vendors.add(vid)  # prevent duplicates

        return options

    # =========================================================================
    # MOQ / SPQ ROUNDING
    # =========================================================================

    @staticmethod
    def apply_moq_spq(
        required_qty: float,
        moq: float = 0,
        spq: float = 0
    ) -> QuantitySuggestion:
        """
        Apply MOQ and SPQ rounding to required quantity.

        Rules:
        1. If required_qty < MOQ → suggested = MOQ
        2. If required_qty >= MOQ → round UP to nearest SPQ
        3. If SPQ = 0 or None → no rounding
        """
        if required_qty <= 0:
            return QuantitySuggestion(
                required_qty=required_qty,
                suggested_qty=0,
                notes='Zero or negative required quantity'
            )

        suggested = required_qty
        moq_applied = False
        spq_applied = False
        notes_parts = []

        moq = moq or 0
        spq = spq or 0

        # Step 1: MOQ check
        if moq > 0 and suggested < moq:
            suggested = moq
            moq_applied = True
            notes_parts.append(f'Rounded up to MOQ ({moq:,.0f})')

        # Step 2: SPQ rounding (round UP to nearest multiple)
        if spq > 0 and suggested > 0:
            remainder = suggested % spq
            if remainder > 0:
                suggested = suggested + (spq - remainder)
                spq_applied = True
                notes_parts.append(f'Rounded up to SPQ multiple ({spq:,.0f})')

        # Calculate excess
        excess = suggested - required_qty
        excess_ratio = excess / required_qty if required_qty > 0 else 0

        # Warn if excessive
        if excess_ratio > MOQ_SPQ_CONFIG.get('max_excess_ratio', 3.0):
            notes_parts.append(
                f'⚠️ Excess {excess_ratio:.1f}x required — review MOQ/SPQ'
            )

        return QuantitySuggestion(
            required_qty=required_qty,
            suggested_qty=suggested,
            moq_applied=moq_applied,
            spq_applied=spq_applied,
            excess_qty=excess,
            excess_ratio=excess_ratio,
            notes='; '.join(notes_parts) if notes_parts else 'No rounding needed'
        )

    # =========================================================================
    # VENDOR PERFORMANCE LOOKUP
    # =========================================================================

    def get_vendor_performance(self, vendor_id: int) -> Optional[Dict[str, Any]]:
        """Get delivery performance metrics for a vendor"""
        return self._performance_by_vendor.get(vendor_id)

    def get_vendor_reliability_class(self, vendor_id: int) -> str:
        """
        Classify vendor reliability based on on-time rate.
        Returns: 'RELIABLE', 'AVERAGE', 'UNRELIABLE', 'UNKNOWN'
        """
        from .planning_constants import VENDOR_RELIABILITY

        perf = self._performance_by_vendor.get(vendor_id)
        if perf is None:
            return 'UNKNOWN'

        deliveries = perf.get('total_arrival_count', 0)
        if deliveries < VENDOR_RELIABILITY['MIN_DELIVERIES']:
            return 'UNKNOWN'

        rate = perf.get('on_time_rate_pct', 0) or 0
        if rate >= VENDOR_RELIABILITY['RELIABLE_THRESHOLD']:
            return 'RELIABLE'
        elif rate < VENDOR_RELIABILITY['UNRELIABLE_THRESHOLD']:
            return 'UNRELIABLE'
        else:
            return 'AVERAGE'

    # =========================================================================
    # SUMMARY STATS
    # =========================================================================

    def get_coverage_stats(self, product_ids: List[int]) -> Dict[str, Any]:
        """
        Get coverage statistics: how many products have vendor pricing?
        """
        total = len(product_ids)
        in_costbook = sum(1 for pid in product_ids if pid in self._pricing_by_product)
        in_last_po = sum(
            1 for pid in product_ids
            if pid not in self._pricing_by_product and pid in self._last_po_by_product
        )
        no_source = total - in_costbook - in_last_po

        return {
            'total_products': total,
            'costbook_coverage': in_costbook,
            'last_po_coverage': in_last_po,
            'no_source': no_source,
            'costbook_pct': round(in_costbook / max(total, 1) * 100, 1),
            'total_coverage_pct': round((in_costbook + in_last_po) / max(total, 1) * 100, 1),
        }
