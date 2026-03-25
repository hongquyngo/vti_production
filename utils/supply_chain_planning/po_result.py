# utils/supply_chain_planning/po_result.py

"""
PO Suggestion Result — output container for PO Planner engine.

Holds:
- Vendor-grouped PO line items (ready for PO creation)
- Unmatched items (no vendor found)
- Summary metrics and urgency distribution
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import date, datetime


@dataclass
class POLineItem:
    """Single PO line item — one product from one vendor"""

    # Product
    product_id: int
    pt_code: str = ''
    product_name: str = ''
    brand: str = ''
    package_size: str = ''
    standard_uom: str = ''

    # Shortage source
    shortage_source: str = ''           # FG_TRADING or RAW_MATERIAL
    shortage_qty: float = 0             # original shortage from GAP
    pending_po_qty: float = 0           # existing pending PO qty
    net_shortage_qty: float = 0         # shortage - pending PO

    # Suggested order
    suggested_qty: float = 0            # after MOQ/SPQ rounding
    moq_applied: bool = False
    spq_applied: bool = False
    excess_qty: float = 0               # suggested - net_shortage

    # Vendor
    vendor_id: Optional[int] = None
    vendor_name: str = ''
    vendor_code: str = ''
    vendor_location_type: str = ''

    # Pricing
    unit_price: float = 0               # standard_unit_price
    unit_price_usd: float = 0           # standard_unit_price_usd
    currency_code: str = ''
    buying_uom: str = ''
    uom_conversion: str = ''
    vat_percent: float = 0
    line_value_usd: float = 0           # suggested_qty × unit_price_usd
    moq: float = 0
    spq: float = 0

    # Price source
    price_source: str = ''              # COSTBOOK, LAST_PO, NO_SOURCE
    costbook_number: str = ''
    last_po_number: str = ''

    # Lead time & timing
    lead_time_days: int = 0             # total (base + buffer)
    lead_time_source: str = ''          # COSTBOOK, LEADTIME_RULE, DEFAULT
    vendor_reliability: str = ''        # RELIABLE, AVERAGE, UNRELIABLE, UNKNOWN

    # Order timing
    demand_date: Optional[date] = None
    must_order_by: Optional[date] = None
    expected_arrival: Optional[date] = None
    days_until_must_order: int = 0
    urgency_level: str = 'PLANNED'      # OVERDUE, CRITICAL, URGENT, THIS_WEEK, PLANNED
    urgency_priority: int = 5
    is_overdue: bool = False

    # Terms
    trade_term: str = ''
    payment_term: str = ''
    shipping_mode: str = ''

    # Notes
    match_notes: str = ''
    quantity_notes: str = ''

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for DataFrame creation"""
        return {
            'product_id': self.product_id,
            'pt_code': self.pt_code,
            'product_name': self.product_name,
            'brand': self.brand,
            'package_size': self.package_size,
            'standard_uom': self.standard_uom,
            'shortage_source': self.shortage_source,
            'shortage_qty': self.shortage_qty,
            'pending_po_qty': self.pending_po_qty,
            'net_shortage_qty': self.net_shortage_qty,
            'suggested_qty': self.suggested_qty,
            'moq_applied': self.moq_applied,
            'spq_applied': self.spq_applied,
            'excess_qty': self.excess_qty,
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor_name,
            'vendor_code': self.vendor_code,
            'vendor_location_type': self.vendor_location_type,
            'unit_price': self.unit_price,
            'unit_price_usd': self.unit_price_usd,
            'currency_code': self.currency_code,
            'buying_uom': self.buying_uom,
            'uom_conversion': self.uom_conversion,
            'vat_percent': self.vat_percent,
            'line_value_usd': self.line_value_usd,
            'moq': self.moq,
            'spq': self.spq,
            'price_source': self.price_source,
            'costbook_number': self.costbook_number,
            'last_po_number': self.last_po_number,
            'lead_time_days': self.lead_time_days,
            'lead_time_source': self.lead_time_source,
            'vendor_reliability': self.vendor_reliability,
            'demand_date': self.demand_date,
            'must_order_by': self.must_order_by,
            'expected_arrival': self.expected_arrival,
            'days_until_must_order': self.days_until_must_order,
            'urgency_level': self.urgency_level,
            'urgency_priority': self.urgency_priority,
            'is_overdue': self.is_overdue,
            'trade_term': self.trade_term,
            'payment_term': self.payment_term,
            'shipping_mode': self.shipping_mode,
            'match_notes': self.match_notes,
            'quantity_notes': self.quantity_notes,
        }


@dataclass
class VendorPOGroup:
    """A group of PO lines for a single vendor — represents one draft PO"""

    vendor_id: int
    vendor_name: str = ''
    vendor_code: str = ''
    vendor_location_type: str = ''
    vendor_reliability: str = ''

    # Lines
    lines: List[POLineItem] = field(default_factory=list)

    # Aggregates (computed)
    total_lines: int = 0
    total_value_usd: float = 0
    currencies: List[str] = field(default_factory=list)
    max_urgency_level: str = 'PLANNED'
    max_urgency_priority: int = 5

    # Terms (from first line or most common)
    primary_currency: str = ''
    trade_term: str = ''
    payment_term: str = ''

    def compute_aggregates(self):
        """Recompute aggregates from lines"""
        self.total_lines = len(self.lines)
        self.total_value_usd = sum(l.line_value_usd for l in self.lines)
        self.currencies = list(set(l.currency_code for l in self.lines if l.currency_code))
        self.primary_currency = self.currencies[0] if len(self.currencies) == 1 else 'MULTI'

        if self.lines:
            best = min(self.lines, key=lambda l: l.urgency_priority)
            self.max_urgency_level = best.urgency_level
            self.max_urgency_priority = best.urgency_priority

            # Most common terms
            terms = [l.trade_term for l in self.lines if l.trade_term]
            self.trade_term = max(set(terms), key=terms.count) if terms else ''
            pays = [l.payment_term for l in self.lines if l.payment_term]
            self.payment_term = max(set(pays), key=pays.count) if pays else ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor_name,
            'vendor_code': self.vendor_code,
            'vendor_location_type': self.vendor_location_type,
            'vendor_reliability': self.vendor_reliability,
            'total_lines': self.total_lines,
            'total_value_usd': self.total_value_usd,
            'primary_currency': self.primary_currency,
            'max_urgency_level': self.max_urgency_level,
            'max_urgency_priority': self.max_urgency_priority,
            'trade_term': self.trade_term,
            'payment_term': self.payment_term,
        }


@dataclass
class POSuggestionResult:
    """
    Complete PO planning output.

    Contains:
    - all_lines: Every PO line item (matched to vendor)
    - vendor_groups: Lines grouped by vendor (one group = one draft PO)
    - unmatched_items: Products with no vendor found
    - metrics: Summary statistics
    """

    timestamp: datetime = field(default_factory=datetime.now)

    # All PO lines
    all_lines: List[POLineItem] = field(default_factory=list)

    # Grouped by vendor
    vendor_groups: Dict[int, VendorPOGroup] = field(default_factory=dict)

    # Unmatched (no vendor)
    unmatched_items: List[Dict[str, Any]] = field(default_factory=list)

    # Skipped items (vendor found but net shortage ≤ 0 after pending PO deduction)
    skipped_items: List[Dict[str, Any]] = field(default_factory=list)

    # Input tracking — what came in from GAP result
    input_summary: Dict[str, Any] = field(default_factory=dict)

    # Metrics
    metrics: Dict[str, Any] = field(default_factory=dict)

    # Input tracking
    strategy: str = 'CHEAPEST'
    default_demand_date: Optional[date] = None

    # =========================================================================
    # ACCESSORS
    # =========================================================================

    def get_all_lines_df(self) -> pd.DataFrame:
        """All PO line items as DataFrame"""
        if not self.all_lines:
            return pd.DataFrame()
        return pd.DataFrame([l.to_dict() for l in self.all_lines])

    def get_fg_lines(self) -> List[POLineItem]:
        """PO lines for trading FG products"""
        return [l for l in self.all_lines if l.shortage_source == 'FG_TRADING']

    def get_raw_lines(self) -> List[POLineItem]:
        """PO lines for raw materials"""
        return [l for l in self.all_lines if l.shortage_source == 'RAW_MATERIAL']

    def get_vendor_summary_df(self) -> pd.DataFrame:
        """Vendor groups as summary DataFrame"""
        if not self.vendor_groups:
            return pd.DataFrame()
        return pd.DataFrame([g.to_dict() for g in self.vendor_groups.values()])

    def get_unmatched_df(self) -> pd.DataFrame:
        """Unmatched items as DataFrame"""
        if not self.unmatched_items:
            return pd.DataFrame()
        return pd.DataFrame(self.unmatched_items)

    def get_skipped_df(self) -> pd.DataFrame:
        """Skipped items as DataFrame (pending PO covered shortage)"""
        if not self.skipped_items:
            return pd.DataFrame()
        return pd.DataFrame(self.skipped_items)

    def get_reconciliation(self) -> Dict[str, Any]:
        """
        Full data reconciliation: input = output + skipped + unmatched + errors.
        
        Shows exactly where every input item ended up — no items "disappear"
        without explanation.
        """
        inp = self.input_summary or {}
        total_input = inp.get('total_items', 0)
        input_fg = inp.get('fg_trading_count', 0)
        input_raw = inp.get('raw_material_count', 0)
        input_skipped_validation = inp.get('validation_skipped', 0)

        matched = len(self.all_lines)
        matched_fg = len(self.get_fg_lines())
        matched_raw = len(self.get_raw_lines())

        skipped = len(self.skipped_items)
        skipped_fg = sum(1 for s in self.skipped_items if s.get('shortage_source') == 'FG_TRADING')
        skipped_raw = sum(1 for s in self.skipped_items if s.get('shortage_source') == 'RAW_MATERIAL')

        unmatched = len(self.unmatched_items)
        unmatched_fg = sum(1 for u in self.unmatched_items if u.get('shortage_source') == 'FG_TRADING')
        unmatched_raw = sum(1 for u in self.unmatched_items if u.get('shortage_source') == 'RAW_MATERIAL')

        errors = len(self.metrics.get('processing_errors', []))

        accounted = matched + skipped + unmatched + errors + input_skipped_validation
        discrepancy = total_input - accounted

        return {
            'total_input': total_input,
            'input_fg': input_fg,
            'input_raw': input_raw,
            'input_skipped_validation': input_skipped_validation,
            'matched': matched,
            'matched_fg': matched_fg,
            'matched_raw': matched_raw,
            'skipped_pending_po': skipped,
            'skipped_fg': skipped_fg,
            'skipped_raw': skipped_raw,
            'unmatched': unmatched,
            'unmatched_fg': unmatched_fg,
            'unmatched_raw': unmatched_raw,
            'processing_errors': errors,
            'total_accounted': accounted,
            'discrepancy': discrepancy,
            'is_balanced': discrepancy == 0,
        }

    def get_urgency_distribution(self) -> Dict[str, int]:
        """Count of lines per urgency level"""
        dist = {}
        for line in self.all_lines:
            dist[line.urgency_level] = dist.get(line.urgency_level, 0) + 1
        return dist

    def get_overdue_lines(self) -> List[POLineItem]:
        """Lines where must-order-by date has passed"""
        return [l for l in self.all_lines if l.is_overdue]

    def get_critical_lines(self) -> List[POLineItem]:
        """Lines with OVERDUE or CRITICAL urgency"""
        return [l for l in self.all_lines if l.urgency_level in ('OVERDUE', 'CRITICAL')]

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def compute_metrics(self):
        """Compute summary metrics from lines"""
        total_lines = len(self.all_lines)
        fg_lines = len(self.get_fg_lines())
        raw_lines = len(self.get_raw_lines())

        total_value = sum(l.line_value_usd for l in self.all_lines)
        overdue_count = len(self.get_overdue_lines())
        critical_count = len(self.get_critical_lines())

        self.metrics = {
            'total_po_lines': total_lines,
            'fg_lines': fg_lines,
            'raw_lines': raw_lines,
            'total_vendors': len(self.vendor_groups),
            'total_value_usd': round(total_value, 2),
            'unmatched_count': len(self.unmatched_items),
            'skipped_count': len(self.skipped_items),
            'overdue_count': overdue_count,
            'critical_count': critical_count,
            'urgency_distribution': self.get_urgency_distribution(),
            'strategy': self.strategy,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M'),
            'reconciliation': self.get_reconciliation(),
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dict"""
        if not self.metrics:
            self.compute_metrics()
        return self.metrics

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def has_lines(self) -> bool:
        return len(self.all_lines) > 0

    def has_unmatched(self) -> bool:
        return len(self.unmatched_items) > 0

    def has_skipped(self) -> bool:
        return len(self.skipped_items) > 0

    def has_overdue(self) -> bool:
        return any(l.is_overdue for l in self.all_lines)