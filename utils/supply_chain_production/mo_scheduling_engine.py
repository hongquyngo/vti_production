# utils/supply_chain_production/mo_scheduling_engine.py

"""
MO Scheduling Engine — backward scheduling, lead time resolution, priority scoring.

ZERO ASSUMPTION — 3-tier STRICT resolution:
  Tier 1: Config table value (REQUIRED — no config = STOP)
  Tier 2: Historical override (only when USE_HISTORICAL=true + data ≥ threshold)
  Tier 3: Neither exists → CANNOT SCHEDULE → flag product with reason

Core calculations:
  must_start_by     = demand_date − production_lead_time
  actual_start      = MAX(must_start_by, materials_ready_date)
  expected_complete  = actual_start + production_lead_time
  is_delayed         = actual_start > must_start_by

Priority scoring:
  Composite of 4 weighted factors (weights from config, must sum to 100):
  - Time urgency (days to demand)
  - Material readiness (READY/PARTIAL/BLOCKED)
  - At-risk value (USD)
  - Customer linkage (has sales order?)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .production_config import ProductionConfig
from .production_constants import MO_URGENCY_LEVELS, MO_URGENCY_THRESHOLDS
from .production_interfaces import (
    ProductionInputItem,
    ProductReadiness,
    UnschedulableItem,
)

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class ConfigMissingError(Exception):
    """Raised when a required config value is missing."""

    def __init__(self, config_key: str, message: str):
        self.config_key = config_key
        self.message = message
        super().__init__(message)


# =============================================================================
# RESULT DATACLASSES
# =============================================================================

@dataclass
class LeadTimeResolution:
    """Result of lead time resolution for one product."""
    lead_time_days: int
    source: str                     # CONFIG, HISTORICAL_PRODUCT, HISTORICAL_BOM_TYPE
    historical_info: Optional[Dict] = None   # avg, stddev, mo_count if historical


@dataclass
class YieldResolution:
    """Result of yield/scrap resolution for one product."""
    yield_multiplier: float         # 1.0 = no adjustment, 1.05 = 5% extra
    source: str                     # BOM_SCRAP, HISTORICAL, CONFIG_DEFAULT
    scrap_pct: float = 0.0         # effective scrap percentage used
    historical_info: Optional[Dict] = None


@dataclass
class SchedulingResult:
    """Complete scheduling result for one MO suggestion."""
    # Quantities
    shortage_qty: float
    suggested_qty: float            # after batch rounding + yield adjustment
    batches_needed: int
    yield_multiplier: float
    yield_source: str

    # Lead time
    lead_time_days: int
    lead_time_source: str
    lead_time_historical: Optional[Dict] = None

    # Dates
    demand_date: Optional[date] = None
    must_start_by: Optional[date] = None
    actual_start: Optional[date] = None
    expected_completion: Optional[date] = None

    # Delay analysis
    is_delayed: bool = False
    delay_days: int = 0
    delay_reason: str = 'ON_TIME'   # ON_TIME, MATERIAL_WAIT, MATERIAL_BLOCKED_NO_ETA

    # Urgency
    urgency_level: str = 'PLANNED'
    urgency_priority: int = 5

    # Priority
    priority_score: float = 999.0


class MOSchedulingEngine:
    """
    Scheduling engine with strict 3-tier lead time resolution.

    Usage:
        engine = MOSchedulingEngine(config, lead_time_stats_df)
        result = engine.schedule(item, readiness)
        # or
        unschedulable = engine.schedule(item, readiness)  # raises ConfigMissingError
    """

    def __init__(
        self,
        config: ProductionConfig,
        lead_time_stats_df: Optional[pd.DataFrame] = None,
    ):
        self._config = config
        self._lt_stats = lead_time_stats_df if lead_time_stats_df is not None else pd.DataFrame()

        # Pre-index historical stats
        self._lt_by_product: Dict[int, pd.Series] = {}
        self._lt_by_bom_type: Dict[str, Dict] = {}

        if not self._lt_stats.empty:
            self._build_historical_indexes()

    # =====================================================================
    # PUBLIC: Schedule one item
    # =====================================================================

    def schedule(
        self,
        item: ProductionInputItem,
        readiness: ProductReadiness,
        reference_date: Optional[date] = None,
    ) -> SchedulingResult:
        """
        Full scheduling for one production item.

        Steps:
        1. Resolve lead time (3-tier strict)
        2. Resolve yield adjustment
        3. Calculate quantity (batch rounding + yield)
        4. Backward scheduling (demand_date → must_start_by)
        5. Adjust for material readiness
        6. Classify urgency

        Raises:
            ConfigMissingError if lead time config missing for this BOM type
        """
        if reference_date is None:
            reference_date = date.today()

        # Step 1: Lead time
        lt = self.resolve_lead_time(item.product_id, item.bom_type)

        # Step 2: Yield
        yr = self.resolve_yield(item.product_id, item.bom_type)

        # Step 3: Quantity
        suggested_qty, batches = self._calculate_quantity(
            item.shortage_qty, item.bom_output_qty, yr.yield_multiplier,
        )

        # Step 4: Demand date
        demand_date = item.demand_date
        if demand_date is None:
            horizon = self._config.planning_horizon_days
            if horizon is not None:
                demand_date = reference_date + timedelta(days=horizon)
            else:
                demand_date = reference_date + timedelta(days=60)

        # Step 5: Backward scheduling
        must_start_by = demand_date - timedelta(days=lt.lead_time_days)

        # Step 6: Material readiness adjustment
        actual_start, is_delayed, delay_days, delay_reason = self._adjust_for_readiness(
            must_start_by, readiness, reference_date,
        )

        expected_completion = None
        if actual_start is not None:
            expected_completion = actual_start + timedelta(days=lt.lead_time_days)

        # Step 7: Urgency
        if actual_start is not None:
            days_until_start = (actual_start - reference_date).days
        else:
            days_until_start = (must_start_by - reference_date).days

        urgency = self._classify_urgency(days_until_start)
        urgency_priority = MO_URGENCY_LEVELS.get(urgency, {}).get('priority', 5)

        return SchedulingResult(
            shortage_qty=item.shortage_qty,
            suggested_qty=suggested_qty,
            batches_needed=batches,
            yield_multiplier=yr.yield_multiplier,
            yield_source=yr.source,
            lead_time_days=lt.lead_time_days,
            lead_time_source=lt.source,
            lead_time_historical=lt.historical_info,
            demand_date=demand_date,
            must_start_by=must_start_by,
            actual_start=actual_start,
            expected_completion=expected_completion,
            is_delayed=is_delayed,
            delay_days=delay_days,
            delay_reason=delay_reason,
            urgency_level=urgency,
            urgency_priority=urgency_priority,
        )

    # =====================================================================
    # PUBLIC: Try schedule (returns UnschedulableItem instead of raising)
    # =====================================================================

    def try_schedule(
        self,
        item: ProductionInputItem,
        readiness: ProductReadiness,
        reference_date: Optional[date] = None,
    ) -> Tuple[Optional[SchedulingResult], Optional[UnschedulableItem]]:
        """
        Try to schedule an item. Returns (result, None) on success
        or (None, unschedulable) if config missing.
        """
        try:
            result = self.schedule(item, readiness, reference_date)
            return result, None
        except ConfigMissingError as e:
            unschedulable = UnschedulableItem(
                product_id=item.product_id,
                pt_code=item.pt_code,
                product_name=item.product_name,
                brand=item.brand,
                shortage_qty=item.shortage_qty,
                uom=item.uom,
                reason_code='MISSING_LEAD_TIME_CONFIG',
                reason_detail=e.message,
                missing_config_key=e.config_key,
                action='Go to Settings → Lead Time Setup',
            )
            return None, unschedulable

    # =====================================================================
    # LEAD TIME RESOLUTION — 3-tier STRICT
    # =====================================================================

    def resolve_lead_time(
        self,
        product_id: int,
        bom_type: str,
    ) -> LeadTimeResolution:
        """
        Strict 3-tier lead time resolution.

        Tier 1: Config table value → REQUIRED
        Tier 2: Historical override → only when USE_HISTORICAL + data ≥ threshold
        Tier 3: No config → raise ConfigMissingError

        Returns: LeadTimeResolution
        Raises: ConfigMissingError if bom_type not configured
        """
        # Tier 1: Config must exist
        config_days = self._config.get_lead_time_days(bom_type)

        if config_days is None:
            raise ConfigMissingError(
                config_key=f'LEAD_TIME.{bom_type}.DAYS',
                message=(
                    f"Lead time not configured for BOM type '{bom_type}'. "
                    f"Go to Settings → Lead Time Setup."
                ),
            )

        # Tier 2: Historical override (only when enabled + data sufficient)
        if self._config.lead_time_use_historical:
            hist = self._try_historical_lead_time(product_id, bom_type)
            if hist is not None:
                return hist

        # Tier 1 value — config baseline
        return LeadTimeResolution(
            lead_time_days=config_days,
            source='CONFIG',
        )

    def _try_historical_lead_time(
        self,
        product_id: int,
        bom_type: str,
    ) -> Optional[LeadTimeResolution]:
        """
        Try historical lead time override.

        Level 1: Product-specific (if ≥ MIN_HISTORY_COUNT_PRODUCT completed MOs)
        Level 2: BOM-type average (if ≥ MIN_HISTORY_COUNT_BOM_TYPE completed MOs)
        """
        min_product = self._config.lead_time_min_history_product or 5
        min_bom = self._config.lead_time_min_history_bom_type or 10

        # Level 1: Product-specific
        product_stats = self._lt_by_product.get(product_id)
        if product_stats is not None:
            mo_count = int(product_stats.get('completed_mo_count', 0) or 0)
            if mo_count >= min_product:
                avg_days = product_stats.get('avg_lead_time_days')
                if avg_days is not None and not pd.isna(avg_days) and avg_days >= 0:
                    hist_days = max(1, int(round(float(avg_days))))
                    return LeadTimeResolution(
                        lead_time_days=hist_days,
                        source='HISTORICAL_PRODUCT',
                        historical_info={
                            'avg_days': round(float(avg_days), 1),
                            'mo_count': mo_count,
                            'stddev': product_stats.get('stddev_lead_time_days'),
                            'min_days': product_stats.get('min_lead_time_days'),
                            'max_days': product_stats.get('max_lead_time_days'),
                        },
                    )

        # Level 2: BOM-type average
        bom_stats = self._lt_by_bom_type.get(bom_type)
        if bom_stats is not None:
            total_mos = bom_stats.get('total_mos', 0)
            if total_mos >= min_bom:
                avg_days = bom_stats.get('weighted_avg_days')
                if avg_days is not None and avg_days >= 0:
                    hist_days = max(1, int(round(avg_days)))
                    return LeadTimeResolution(
                        lead_time_days=hist_days,
                        source='HISTORICAL_BOM_TYPE',
                        historical_info={
                            'avg_days': round(avg_days, 1),
                            'mo_count': total_mos,
                            'product_count': bom_stats.get('product_count', 0),
                        },
                    )

        return None

    # =====================================================================
    # YIELD RESOLUTION
    # =====================================================================

    def resolve_yield(
        self,
        product_id: int,
        bom_type: str,
    ) -> YieldResolution:
        """
        Resolve yield/scrap adjustment.

        Priority:
        1. Historical yield (if USE_HISTORICAL + data sufficient)
        2. Config default scrap % per BOM type (if set)
        3. BOM scrap_rate (handled in required_qty calculation already)
        4. No adjustment (multiplier = 1.0)

        Note: BOM-level scrap_rate is already included in required_qty
        calculation (in extract_material_requirements). This yield adjustment
        is an ADDITIONAL production-level adjustment for systematic losses.
        """
        # Try historical yield
        if self._config.yield_use_historical:
            hist = self._try_historical_yield(product_id)
            if hist is not None:
                return hist

        # Try config default scrap %
        config_scrap = self._config.get_yield_default_scrap_pct(bom_type)
        if config_scrap is not None and config_scrap > 0:
            multiplier = round(100 / (100 - config_scrap), 4)
            return YieldResolution(
                yield_multiplier=multiplier,
                source='CONFIG_DEFAULT',
                scrap_pct=config_scrap,
            )

        # No additional yield adjustment (BOM scrap already in required_qty)
        return YieldResolution(
            yield_multiplier=1.0,
            source='BOM_SCRAP',
            scrap_pct=0.0,
        )

    def _try_historical_yield(self, product_id: int) -> Optional[YieldResolution]:
        """Try historical yield override from completed MOs."""
        min_count = self._config.yield_min_history_count or 5

        product_stats = self._lt_by_product.get(product_id)
        if product_stats is None:
            return None

        mo_count = int(product_stats.get('completed_mo_count', 0) or 0)
        if mo_count < min_count:
            return None

        yield_pct = product_stats.get('avg_yield_pct')
        if yield_pct is None or pd.isna(yield_pct) or yield_pct <= 0:
            return None

        yield_pct_f = float(yield_pct)
        if yield_pct_f >= 100:
            # Yield ≥ 100% means no loss — no adjustment needed
            return YieldResolution(
                yield_multiplier=1.0,
                source='HISTORICAL',
                scrap_pct=0.0,
                historical_info={'yield_pct': yield_pct_f, 'mo_count': mo_count},
            )

        multiplier = round(100 / yield_pct_f, 4)
        scrap_pct = round(100 - yield_pct_f, 2)

        return YieldResolution(
            yield_multiplier=multiplier,
            source='HISTORICAL',
            scrap_pct=scrap_pct,
            historical_info={'yield_pct': yield_pct_f, 'mo_count': mo_count},
        )

    # =====================================================================
    # QUANTITY CALCULATION
    # =====================================================================

    def _calculate_quantity(
        self,
        shortage_qty: float,
        bom_output_qty: float,
        yield_multiplier: float,
    ) -> Tuple[float, int]:
        """
        Calculate suggested MO quantity with yield adjustment and batch rounding.

        suggested = shortage × yield_multiplier, rounded UP to bom_output_qty multiple.

        Returns: (suggested_qty, batches_needed)
        """
        if shortage_qty <= 0:
            return 0.0, 0

        adjusted = shortage_qty * yield_multiplier

        if bom_output_qty > 0:
            batches = int(-(-adjusted // bom_output_qty))  # ceiling division
            suggested = batches * bom_output_qty
        else:
            batches = 1
            suggested = adjusted

        return round(suggested, 2), batches

    # =====================================================================
    # MATERIAL READINESS ADJUSTMENT
    # =====================================================================

    def _adjust_for_readiness(
        self,
        must_start_by: date,
        readiness: ProductReadiness,
        reference_date: date,
    ) -> Tuple[Optional[date], bool, int, str]:
        """
        Adjust start date based on material readiness.

        Returns: (actual_start, is_delayed, delay_days, delay_reason)
        """
        if readiness.overall_status == 'READY':
            # All materials available — can start on time
            actual_start = max(must_start_by, reference_date)
            is_delayed = actual_start > must_start_by
            delay_days = (actual_start - must_start_by).days if is_delayed else 0
            return actual_start, is_delayed, delay_days, 'ON_TIME'

        if readiness.overall_status == 'USE_ALTERNATIVE':
            # Alternative covers — same as READY
            actual_start = max(must_start_by, reference_date)
            is_delayed = actual_start > must_start_by
            delay_days = (actual_start - must_start_by).days if is_delayed else 0
            return actual_start, is_delayed, delay_days, 'ON_TIME'

        if readiness.earliest_start_date is not None:
            # Materials have ETA — start when materials arrive
            actual_start = max(readiness.earliest_start_date, reference_date)
            is_delayed = actual_start > must_start_by
            delay_days = (actual_start - must_start_by).days if is_delayed else 0
            return actual_start, is_delayed, delay_days, 'MATERIAL_WAIT'

        # No ETA — cannot schedule
        return None, True, 0, 'MATERIAL_BLOCKED_NO_ETA'

    # =====================================================================
    # URGENCY CLASSIFICATION
    # =====================================================================

    @staticmethod
    def _classify_urgency(days_until_start: int) -> str:
        """
        Classify urgency based on days from today to must_start_by (or actual_start).

        < 0  → OVERDUE
        0-3  → CRITICAL
        4-7  → URGENT
        8-14 → THIS_WEEK
        > 14 → PLANNED
        """
        if days_until_start < MO_URGENCY_THRESHOLDS['OVERDUE']:
            return 'OVERDUE'
        if days_until_start <= MO_URGENCY_THRESHOLDS['CRITICAL']:
            return 'CRITICAL'
        if days_until_start <= MO_URGENCY_THRESHOLDS['URGENT']:
            return 'URGENT'
        if days_until_start <= MO_URGENCY_THRESHOLDS['THIS_WEEK']:
            return 'THIS_WEEK'
        return 'PLANNED'

    # =====================================================================
    # PRIORITY SCORING
    # =====================================================================

    def calculate_priority(
        self,
        item: ProductionInputItem,
        readiness: ProductReadiness,
        scheduling: SchedulingResult,
        max_at_risk_value: float = 1.0,
        reference_date: Optional[date] = None,
    ) -> float:
        """
        Multi-factor priority score (lower = more urgent).

        Factors (weights from config, sum to 100):
        1. Time urgency:       days to demand (fewer = more urgent)
        2. Material readiness:  READY < PARTIAL < BLOCKED
        3. At-risk value:       higher value = more urgent
        4. Customer linkage:    has sales order = more urgent
        """
        if reference_date is None:
            reference_date = date.today()

        w_time = (self._config.priority_weight_time or 0) / 100.0
        w_ready = (self._config.priority_weight_readiness or 0) / 100.0
        w_value = (self._config.priority_weight_value or 0) / 100.0
        w_cust = (self._config.priority_weight_customer or 0) / 100.0

        # Factor 1: Time urgency (0=overdue → 100=50+ days out)
        if scheduling.demand_date:
            days_to_demand = (scheduling.demand_date - reference_date).days
            time_score = min(100, max(0, days_to_demand * 2))
        else:
            time_score = 50  # unknown demand date → mid-priority

        # Factor 2: Material readiness
        readiness_map = {
            'READY': 0,
            'USE_ALTERNATIVE': 20,
            'PARTIAL_READY': 50,
            'BLOCKED': 90,
        }
        readiness_score = readiness_map.get(readiness.overall_status, 50)

        # Factor 3: At-risk value (higher value → lower score → higher priority)
        if max_at_risk_value > 0 and item.at_risk_value > 0:
            value_score = 100 - min(100, item.at_risk_value / max_at_risk_value * 100)
        else:
            value_score = 50

        # Factor 4: Customer linkage
        customer_score = 0 if item.has_sales_order else 60

        # Composite (lower = more urgent)
        score = (
            time_score * w_time
            + readiness_score * w_ready
            + value_score * w_value
            + customer_score * w_cust
        )

        return round(score, 2)

    # =====================================================================
    # BATCH: Schedule + prioritize all items
    # =====================================================================

    def schedule_and_prioritize(
        self,
        items: List[ProductionInputItem],
        readiness_map: Dict[int, ProductReadiness],
        reference_date: Optional[date] = None,
    ) -> Tuple[
        List[Tuple[ProductionInputItem, SchedulingResult, ProductReadiness]],
        List[UnschedulableItem],
    ]:
        """
        Schedule all items, compute priorities, sort.

        Returns:
          (scheduled_items, unschedulable_items)

        scheduled_items: List of (item, scheduling, readiness) sorted by priority
        unschedulable_items: List of UnschedulableItem (missing config)
        """
        if reference_date is None:
            reference_date = date.today()

        scheduled = []
        unschedulable = []

        # Phase 1: Schedule each item
        for item in items:
            readiness = readiness_map.get(item.product_id)
            if readiness is None:
                readiness = ProductReadiness(
                    product_id=item.product_id,
                    pt_code=item.pt_code,
                    product_name=item.product_name,
                    bom_code=item.bom_code,
                    bom_type=item.bom_type,
                    overall_status='BLOCKED',
                )

            sched_result, unsched = self.try_schedule(item, readiness, reference_date)
            if unsched is not None:
                unschedulable.append(unsched)
            elif sched_result is not None:
                scheduled.append((item, sched_result, readiness))

        # Phase 2: Calculate priorities
        max_arv = max((i.at_risk_value for i, _, _ in scheduled), default=1.0) or 1.0

        for item, sched, readiness in scheduled:
            score = self.calculate_priority(
                item, readiness, sched, max_arv, reference_date,
            )
            sched.priority_score = score
            readiness.priority_score = score

        # Phase 3: Sort by priority (ascending = most urgent first)
        scheduled.sort(key=lambda t: t[1].priority_score)

        logger.info(
            f"Scheduling complete: {len(scheduled)} scheduled, "
            f"{len(unschedulable)} unschedulable"
        )
        if unschedulable:
            for u in unschedulable:
                logger.warning(f"  Unschedulable: {u.pt_code} — {u.reason_detail}")

        return scheduled, unschedulable

    # =====================================================================
    # HISTORICAL INDEX BUILDERS
    # =====================================================================

    def _build_historical_indexes(self):
        """Pre-index historical stats from lead_time_stats_df."""
        if self._lt_stats.empty:
            return

        # Per-product index
        for _, row in self._lt_stats.iterrows():
            pid = row.get('product_id')
            if pid is not None and not pd.isna(pid):
                self._lt_by_product[int(pid)] = row

        # Per-BOM-type aggregation
        for bom_type in self._lt_stats['bom_type'].dropna().unique():
            bom_rows = self._lt_stats[self._lt_stats['bom_type'] == bom_type]
            total_mos = bom_rows['completed_mo_count'].sum()
            if total_mos > 0:
                weighted_avg = (
                    (bom_rows['avg_lead_time_days'] * bom_rows['completed_mo_count']).sum()
                    / total_mos
                )
            else:
                weighted_avg = 0

            self._lt_by_bom_type[bom_type] = {
                'weighted_avg_days': round(weighted_avg, 1),
                'total_mos': int(total_mos),
                'product_count': len(bom_rows),
            }

        logger.info(
            f"Historical indexes built: {len(self._lt_by_product)} products, "
            f"{len(self._lt_by_bom_type)} BOM types"
        )
