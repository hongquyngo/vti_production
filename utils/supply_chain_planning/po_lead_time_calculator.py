# utils/supply_chain_planning/po_lead_time_calculator.py

"""
PO Lead Time Calculator — determines when to order based on when product is needed.

Core formula:
    must_order_by = demand_date - total_procurement_lead_time

Total lead time = costbook_lead_time + buffer (adjusted by vendor reliability)

Fallback chain:
    1. costbook_details.lead_time_max_days (99.1% coverage — from view)
    2. quotation_leadtime_rules (transit + paperwork by region/ship_mode)
    3. Default: 9 days (domestic) / 45 days (international) / 21 days (unknown)
"""

import pandas as pd
import logging
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from .planning_constants import (
    URGENCY_LEVELS, URGENCY_THRESHOLDS,
    LEAD_TIME_DEFAULTS, LEAD_TIME_BUFFER_DAYS, VENDOR_RELIABILITY,
    LEAD_TIME_BUFFER_ADAPTIVE
)

logger = logging.getLogger(__name__)


@dataclass
class LeadTimeResult:
    """Calculated lead time for a single product × vendor"""

    # Components
    base_lead_time_days: int         # from costbook or fallback
    buffer_days: int                 # reliability-adjusted buffer
    total_lead_time_days: int        # base + buffer

    # Source tracking
    lead_time_source: str            # COSTBOOK, LEADTIME_RULE, DEFAULT
    lead_time_notes: str = ''

    # Vendor reliability (affects buffer)
    vendor_reliability: str = 'UNKNOWN'   # RELIABLE, AVERAGE, UNRELIABLE, UNKNOWN
    vendor_on_time_pct: Optional[float] = None
    vendor_avg_delay: Optional[float] = None


@dataclass
class OrderTimingResult:
    """Full timing calculation for a PO line item"""

    # Dates
    demand_date: date                     # when product is needed
    must_order_by: date                   # when PO must be placed
    expected_arrival: date                # if ordered today, when would it arrive?

    # Lead time
    lead_time: LeadTimeResult

    # Urgency
    days_until_must_order: int            # days from today to must_order_by
    urgency_level: str                    # OVERDUE, CRITICAL, URGENT, THIS_WEEK, PLANNED
    urgency_priority: int                 # 1 (most urgent) to 5

    # Flags
    is_overdue: bool                      # must_order_by < today
    ordered_today_arrives_on_time: bool   # if we order today, can we meet demand_date?


class POLeadTimeCalculator:
    """
    Calculates procurement lead time and order timing.

    Usage:
        calc = POLeadTimeCalculator(leadtime_rules_df, vendor_performance_df)
        timing = calc.calculate_timing(
            demand_date=date(2026, 5, 15),
            lead_time_max_days=21,        # from costbook
            vendor_location_type='International',
            vendor_id=123
        )
        print(f"Must order by: {timing.must_order_by}")
        print(f"Urgency: {timing.urgency_level}")
    """

    def __init__(
        self,
        leadtime_rules_df: Optional[pd.DataFrame] = None,
        vendor_performance_df: Optional[pd.DataFrame] = None
    ):
        self._rules = leadtime_rules_df if leadtime_rules_df is not None else pd.DataFrame()
        self._performance = vendor_performance_df if vendor_performance_df is not None else pd.DataFrame()

        # Build vendor performance lookup
        self._perf_by_vendor = {}
        if not self._performance.empty:
            for _, row in self._performance.iterrows():
                vid = row.get('vendor_id')
                if pd.notna(vid):
                    self._perf_by_vendor[int(vid)] = {
                        'on_time_rate_pct': float(row.get('on_time_rate_pct', 0) or 0),
                        'avg_delay_days': float(row.get('avg_delay_days', 0) or 0),
                        'total_arrival_count': int(row.get('total_arrival_count', 0) or 0),
                    }

        logger.info(
            f"POLeadTimeCalculator: {len(self._rules)} rules, "
            f"{len(self._perf_by_vendor)} vendors with performance data"
        )

    # =========================================================================
    # CORE: CALCULATE TIMING
    # =========================================================================

    def calculate_timing(
        self,
        demand_date: date,
        lead_time_max_days: Optional[int] = None,
        vendor_location_type: str = 'UNKNOWN',
        vendor_id: Optional[int] = None,
        trade_term: Optional[str] = None,
        shipping_mode: Optional[str] = None,
        reference_date: Optional[date] = None
    ) -> OrderTimingResult:
        """
        Calculate full ordering timeline for a product.

        Args:
            demand_date: When the product must be available
            lead_time_max_days: From costbook (vendor_product_pricing_view)
            vendor_location_type: 'Domestic' or 'International'
            vendor_id: For vendor reliability lookup
            trade_term: e.g., 'FOB', 'CIF' — for leadtime rules
            shipping_mode: e.g., 'SEA', 'AIR' — for leadtime rules
            reference_date: Today (default: date.today())
        """
        if reference_date is None:
            reference_date = date.today()

        # Ensure demand_date is a date object
        demand_date = self._to_date(demand_date)

        # Step 1: Resolve lead time
        lead_time = self._resolve_lead_time(
            lead_time_max_days=lead_time_max_days,
            vendor_location_type=vendor_location_type,
            vendor_id=vendor_id,
            trade_term=trade_term,
            shipping_mode=shipping_mode
        )

        # Step 2: Calculate dates
        must_order_by = demand_date - timedelta(days=lead_time.total_lead_time_days)
        expected_arrival_if_ordered_today = reference_date + timedelta(days=lead_time.total_lead_time_days)

        # Step 3: Urgency classification
        days_until = (must_order_by - reference_date).days
        urgency = self._classify_urgency(days_until)

        return OrderTimingResult(
            demand_date=demand_date,
            must_order_by=must_order_by,
            expected_arrival=expected_arrival_if_ordered_today,
            lead_time=lead_time,
            days_until_must_order=days_until,
            urgency_level=urgency,
            urgency_priority=URGENCY_LEVELS.get(urgency, {}).get('priority', 5),
            is_overdue=days_until < 0,
            ordered_today_arrives_on_time=expected_arrival_if_ordered_today <= demand_date,
        )

    # =========================================================================
    # LEAD TIME RESOLUTION (3-level fallback)
    # =========================================================================

    def _resolve_lead_time(
        self,
        lead_time_max_days: Optional[int],
        vendor_location_type: str,
        vendor_id: Optional[int],
        trade_term: Optional[str],
        shipping_mode: Optional[str]
    ) -> LeadTimeResult:
        """
        Resolve total lead time with 3-level fallback.
        """
        # Vendor reliability (affects buffer)
        reliability, on_time_pct, avg_delay = self._get_vendor_reliability(vendor_id)
        buffer = self._calculate_buffer(reliability, avg_delay)

        # Priority 1: Costbook lead time (99.1% of records)
        if lead_time_max_days is not None and lead_time_max_days > 0:
            return LeadTimeResult(
                base_lead_time_days=lead_time_max_days,
                buffer_days=buffer,
                total_lead_time_days=lead_time_max_days + buffer,
                lead_time_source='COSTBOOK',
                lead_time_notes=f'Costbook: {lead_time_max_days}d + buffer: {buffer}d',
                vendor_reliability=reliability,
                vendor_on_time_pct=on_time_pct,
                vendor_avg_delay=avg_delay,
            )

        # Priority 2: Leadtime rules (region + trade term + ship mode)
        rule_days = self._lookup_leadtime_rule(
            vendor_location_type, trade_term, shipping_mode
        )
        if rule_days is not None and rule_days > 0:
            return LeadTimeResult(
                base_lead_time_days=rule_days,
                buffer_days=buffer,
                total_lead_time_days=rule_days + buffer,
                lead_time_source='LEADTIME_RULE',
                lead_time_notes=f'Rule ({vendor_location_type}/{shipping_mode}): {rule_days}d + buffer: {buffer}d',
                vendor_reliability=reliability,
                vendor_on_time_pct=on_time_pct,
                vendor_avg_delay=avg_delay,
            )

        # Priority 3: Default based on location type
        loc_key = vendor_location_type.upper() if vendor_location_type else 'UNKNOWN'
        if loc_key == 'DOMESTIC':
            defaults = LEAD_TIME_DEFAULTS['DOMESTIC']
        elif loc_key == 'INTERNATIONAL':
            defaults = LEAD_TIME_DEFAULTS['INTERNATIONAL']
        else:
            defaults = LEAD_TIME_DEFAULTS['UNKNOWN']

        default_days = defaults.get('total_days', 21)

        return LeadTimeResult(
            base_lead_time_days=default_days,
            buffer_days=buffer,
            total_lead_time_days=default_days + buffer,
            lead_time_source='DEFAULT',
            lead_time_notes=f'Default ({loc_key}): {default_days}d + buffer: {buffer}d',
            vendor_reliability=reliability,
            vendor_on_time_pct=on_time_pct,
            vendor_avg_delay=avg_delay,
        )

    def _lookup_leadtime_rule(
        self,
        vendor_location_type: Optional[str],
        trade_term: Optional[str],
        shipping_mode: Optional[str]
    ) -> Optional[int]:
        """
        Lookup transit + paperwork days from quotation_leadtime_rules.

        Matching logic (most specific to least):
        1. Exact match: location_type + trade_term_prefix + ship_mode
        2. Partial: location_type + ship_mode
        3. Partial: location_type only
        """
        if self._rules.empty:
            return None

        rules = self._rules.copy()

        # Normalize inputs
        loc_type = vendor_location_type.upper() if vendor_location_type else None
        tt_prefix = trade_term[:3].upper() if trade_term and len(trade_term) >= 3 else None
        sm = shipping_mode.upper() if shipping_mode else None

        # Try exact match
        if loc_type and tt_prefix and sm:
            match = rules[
                (rules['vendor_location_type'].str.upper() == loc_type) &
                (rules['trade_term_prefix'].str.upper() == tt_prefix) &
                (rules['ship_mode'].str.upper() == sm)
            ]
            if not match.empty:
                return int(match.iloc[0]['total_days'])

        # Try location + ship mode
        if loc_type and sm:
            match = rules[
                (rules['vendor_location_type'].str.upper() == loc_type) &
                (rules['ship_mode'].str.upper() == sm)
            ]
            if not match.empty:
                return int(match.iloc[0]['total_days'])

        # Try location only
        if loc_type:
            match = rules[rules['vendor_location_type'].str.upper() == loc_type]
            if not match.empty:
                # Average of all matching rules for this location type
                return int(match['total_days'].mean())

        return None

    # =========================================================================
    # VENDOR RELIABILITY → BUFFER
    # =========================================================================

    def _get_vendor_reliability(
        self, vendor_id: Optional[int]
    ) -> Tuple[str, Optional[float], Optional[float]]:
        """
        Get vendor reliability class and metrics.

        Returns: (reliability_class, on_time_pct, avg_delay_days)
        """
        if vendor_id is None or vendor_id not in self._perf_by_vendor:
            return 'UNKNOWN', None, None

        perf = self._perf_by_vendor[vendor_id]
        deliveries = perf.get('total_arrival_count', 0)
        on_time_pct = perf.get('on_time_rate_pct', 0)
        avg_delay = perf.get('avg_delay_days', 0)

        if deliveries < VENDOR_RELIABILITY['MIN_DELIVERIES']:
            return 'UNKNOWN', on_time_pct, avg_delay

        if on_time_pct >= VENDOR_RELIABILITY['RELIABLE_THRESHOLD']:
            return 'RELIABLE', on_time_pct, avg_delay
        elif on_time_pct < VENDOR_RELIABILITY['UNRELIABLE_THRESHOLD']:
            return 'UNRELIABLE', on_time_pct, avg_delay
        else:
            return 'AVERAGE', on_time_pct, avg_delay

    @staticmethod
    def _calculate_buffer(reliability: str, avg_delay_days: float = None) -> int:
        """
        Calculate buffer days based on vendor reliability.
        
        v1.1 ADAPTIVE MODE: Uses actual avg_delay_days from vendor performance
        instead of fixed values. Prevents urgency inflation where 60%+ items
        show OVERDUE because unreliable vendors get blanket +10d buffer.
        
        Formula: buffer = avg_delay × multiplier, clamped to [min, max]
        
        Falls back to fixed buffer if adaptive mode disabled or no perf data.
        """
        cfg = LEAD_TIME_BUFFER_ADAPTIVE
        
        # Adaptive mode: use actual delay data
        if cfg.get('enabled', False) and avg_delay_days is not None and avg_delay_days > 0:
            if reliability == 'RELIABLE':
                multiplier = cfg.get('reliable_multiplier', 0.5)
            elif reliability == 'UNRELIABLE':
                multiplier = cfg.get('unreliable_multiplier', 1.0)
            elif reliability == 'AVERAGE':
                multiplier = cfg.get('average_multiplier', 0.75)
            else:
                # UNKNOWN — use fixed
                return cfg.get('unknown_fixed', 5)
            
            raw_buffer = avg_delay_days * multiplier
            clamped = max(cfg.get('min_buffer_days', 3),
                         min(int(round(raw_buffer)), cfg.get('max_buffer_days', 15)))
            return clamped
        
        # Fixed fallback (original behavior)
        if reliability == 'RELIABLE':
            return LEAD_TIME_BUFFER_DAYS['RELIABLE_VENDOR']
        elif reliability == 'UNRELIABLE':
            return LEAD_TIME_BUFFER_DAYS['UNRELIABLE_VENDOR']
        else:
            return LEAD_TIME_BUFFER_DAYS['DEFAULT']

    # =========================================================================
    # URGENCY CLASSIFICATION
    # =========================================================================

    @staticmethod
    def _classify_urgency(days_until_must_order: int) -> str:
        """
        Classify urgency based on days from today to must-order-by date.

        < 0 days  → OVERDUE (already past deadline)
        0-3 days  → CRITICAL
        4-7 days  → URGENT
        8-14 days → THIS_WEEK
        > 14 days → PLANNED
        """
        if days_until_must_order < URGENCY_THRESHOLDS['OVERDUE']:
            return 'OVERDUE'
        elif days_until_must_order <= URGENCY_THRESHOLDS['CRITICAL']:
            return 'CRITICAL'
        elif days_until_must_order <= URGENCY_THRESHOLDS['URGENT']:
            return 'URGENT'
        elif days_until_must_order <= URGENCY_THRESHOLDS['THIS_WEEK']:
            return 'THIS_WEEK'
        else:
            return 'PLANNED'

    # =========================================================================
    # BATCH CALCULATION
    # =========================================================================

    def calculate_batch(
        self,
        items: List[Dict[str, Any]],
        reference_date: Optional[date] = None
    ) -> List[OrderTimingResult]:
        """
        Calculate timing for a batch of items.

        Each item dict should have:
            demand_date, lead_time_max_days (optional),
            vendor_location_type, vendor_id (optional),
            trade_term (optional), shipping_mode (optional)
        """
        results = []
        for item in items:
            timing = self.calculate_timing(
                demand_date=item['demand_date'],
                lead_time_max_days=item.get('lead_time_max_days'),
                vendor_location_type=item.get('vendor_location_type', 'UNKNOWN'),
                vendor_id=item.get('vendor_id'),
                trade_term=item.get('trade_term'),
                shipping_mode=item.get('shipping_mode'),
                reference_date=reference_date,
            )
            results.append(timing)
        return results

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _to_date(value) -> date:
        """Convert various date types to date object"""
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, pd.Timestamp):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.strptime(value[:10], '%Y-%m-%d').date()
            except ValueError:
                pass
        return date.today()

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def get_urgency_summary(
        self, timings: List[OrderTimingResult]
    ) -> Dict[str, int]:
        """Count items per urgency level"""
        summary = {level: 0 for level in URGENCY_LEVELS}
        for t in timings:
            summary[t.urgency_level] = summary.get(t.urgency_level, 0) + 1
        return summary