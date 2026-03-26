# utils/supply_chain_production/mo_result.py

"""
MO Suggestion Result — output container for Production Planning engine.

Holds:
- Categorized MO line items (Ready / Waiting / Blocked)
- Unschedulable items (missing config)
- Material readiness matrix
- Data reconciliation (input = output + blocked + unschedulable + errors)
- Gantt data for timeline visualization
"""

import pandas as pd
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Any, List, Optional

from .production_interfaces import (
    MaterialReadiness,
    ProductReadiness,
    UnschedulableItem,
)
from .mo_scheduling_engine import SchedulingResult


# =============================================================================
# MO LINE ITEM
# =============================================================================

@dataclass
class MOLineItem:
    """Single MO suggestion — one manufacturing order for one product."""

    # Product identity
    product_id: int
    pt_code: str = ''
    product_name: str = ''
    brand: str = ''
    package_size: str = ''
    uom: str = ''

    # BOM info
    bom_id: int = 0
    bom_code: str = ''
    bom_type: str = ''
    bom_output_qty: float = 0

    # Quantities
    shortage_qty: float = 0              # from GAP |net_gap|
    suggested_qty: float = 0             # after batch rounding + yield
    batches_needed: int = 0
    yield_multiplier: float = 1.0
    yield_source: str = ''

    # Material readiness
    readiness_status: str = ''           # READY, PARTIAL_READY, BLOCKED, USE_ALTERNATIVE
    can_start_now: bool = False
    materials_ready_pct: float = 0       # % of materials available
    total_materials: int = 0
    ready_materials: int = 0
    partial_materials: int = 0
    blocked_materials: int = 0
    bottleneck_material: str = ''        # pt_code of bottleneck
    bottleneck_eta: Optional[date] = None
    max_producible_now: float = 0
    max_producible_pct: float = 0
    has_contention: bool = False

    # Scheduling
    demand_date: Optional[date] = None
    must_start_by: Optional[date] = None
    actual_start: Optional[date] = None
    expected_completion: Optional[date] = None
    lead_time_days: int = 0
    lead_time_source: str = ''

    # Delay
    is_delayed: bool = False
    delay_days: int = 0
    delay_reason: str = ''               # ON_TIME, MATERIAL_WAIT, MATERIAL_BLOCKED_NO_ETA

    # Urgency
    urgency_level: str = 'PLANNED'
    urgency_priority: int = 5

    # Priority
    priority_score: float = 999.0

    # Value & impact
    at_risk_value: float = 0
    customer_count: int = 0
    has_sales_order: bool = False

    # GAP context
    gap_production_status: str = ''
    gap_limiting_materials: List[str] = field(default_factory=list)

    # Existing MO context (informational — NOT deducted)
    existing_mo_count: int = 0
    existing_mo_remaining_qty: float = 0

    # Action
    action_type: str = ''                # CREATE_MO, WAIT_MATERIAL, USE_ALTERNATIVE
    action_description: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'product_id': self.product_id,
            'pt_code': self.pt_code,
            'product_name': self.product_name,
            'brand': self.brand,
            'package_size': self.package_size,
            'uom': self.uom,
            'bom_code': self.bom_code,
            'bom_type': self.bom_type,
            'bom_output_qty': self.bom_output_qty,
            'shortage_qty': self.shortage_qty,
            'suggested_qty': self.suggested_qty,
            'batches_needed': self.batches_needed,
            'yield_multiplier': self.yield_multiplier,
            'yield_source': self.yield_source,
            'readiness_status': self.readiness_status,
            'can_start_now': self.can_start_now,
            'materials_ready_pct': self.materials_ready_pct,
            'total_materials': self.total_materials,
            'ready_materials': self.ready_materials,
            'blocked_materials': self.blocked_materials,
            'bottleneck_material': self.bottleneck_material,
            'bottleneck_eta': self.bottleneck_eta,
            'max_producible_now': self.max_producible_now,
            'max_producible_pct': self.max_producible_pct,
            'has_contention': self.has_contention,
            'demand_date': self.demand_date,
            'must_start_by': self.must_start_by,
            'actual_start': self.actual_start,
            'expected_completion': self.expected_completion,
            'lead_time_days': self.lead_time_days,
            'lead_time_source': self.lead_time_source,
            'is_delayed': self.is_delayed,
            'delay_days': self.delay_days,
            'delay_reason': self.delay_reason,
            'urgency_level': self.urgency_level,
            'urgency_priority': self.urgency_priority,
            'priority_score': self.priority_score,
            'at_risk_value': self.at_risk_value,
            'customer_count': self.customer_count,
            'has_sales_order': self.has_sales_order,
            'existing_mo_count': self.existing_mo_count,
            'existing_mo_remaining_qty': self.existing_mo_remaining_qty,
            'action_type': self.action_type,
            'action_description': self.action_description,
        }


# =============================================================================
# MO SUGGESTION RESULT
# =============================================================================

@dataclass
class MOSuggestionResult:
    """Complete production planning output."""

    timestamp: datetime = field(default_factory=datetime.now)

    # All MO lines (categorized)
    all_lines: List[MOLineItem] = field(default_factory=list)

    # Categorized views (computed from all_lines)
    ready_lines: List[MOLineItem] = field(default_factory=list)
    waiting_lines: List[MOLineItem] = field(default_factory=list)
    blocked_lines: List[MOLineItem] = field(default_factory=list)

    # Unschedulable (missing config)
    unschedulable_items: List[UnschedulableItem] = field(default_factory=list)

    # Material readiness matrix
    readiness_map: Dict[int, ProductReadiness] = field(default_factory=dict)

    # Input tracking
    input_summary: Dict[str, Any] = field(default_factory=dict)

    # Metrics (computed)
    metrics: Dict[str, Any] = field(default_factory=dict)

    # Config used
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    # =====================================================================
    # CATEGORIZE
    # =====================================================================

    def categorize_lines(self):
        """Split all_lines into ready / waiting / blocked based on readiness."""
        self.ready_lines = []
        self.waiting_lines = []
        self.blocked_lines = []

        for line in self.all_lines:
            if line.readiness_status == 'READY' or line.readiness_status == 'USE_ALTERNATIVE':
                self.ready_lines.append(line)
            elif line.readiness_status == 'PARTIAL_READY':
                self.waiting_lines.append(line)
            elif line.readiness_status == 'BLOCKED':
                if line.delay_reason == 'MATERIAL_BLOCKED_NO_ETA':
                    self.blocked_lines.append(line)
                else:
                    self.waiting_lines.append(line)
            else:
                self.blocked_lines.append(line)

    # =====================================================================
    # DATAFRAME ACCESSORS
    # =====================================================================

    def get_all_lines_df(self) -> pd.DataFrame:
        if not self.all_lines:
            return pd.DataFrame()
        return pd.DataFrame([l.to_dict() for l in self.all_lines])

    def get_ready_lines_df(self) -> pd.DataFrame:
        if not self.ready_lines:
            return pd.DataFrame()
        return pd.DataFrame([l.to_dict() for l in self.ready_lines])

    def get_waiting_lines_df(self) -> pd.DataFrame:
        if not self.waiting_lines:
            return pd.DataFrame()
        return pd.DataFrame([l.to_dict() for l in self.waiting_lines])

    def get_blocked_lines_df(self) -> pd.DataFrame:
        if not self.blocked_lines:
            return pd.DataFrame()
        return pd.DataFrame([l.to_dict() for l in self.blocked_lines])

    def get_unschedulable_df(self) -> pd.DataFrame:
        if not self.unschedulable_items:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                'product_id': u.product_id, 'pt_code': u.pt_code,
                'product_name': u.product_name, 'brand': u.brand,
                'shortage_qty': u.shortage_qty, 'uom': u.uom,
                'reason_code': u.reason_code, 'reason_detail': u.reason_detail,
                'missing_config_key': u.missing_config_key, 'action': u.action,
            }
            for u in self.unschedulable_items
        ])

    def get_readiness_matrix_df(self) -> pd.DataFrame:
        """Material readiness as flat DataFrame: product × material × coverage."""
        rows = []
        for pid, pr in self.readiness_map.items():
            for mat in pr.materials:
                rows.append({
                    'product_id': pid,
                    'pt_code': pr.pt_code,
                    'product_name': pr.product_name,
                    'material_id': mat.material_id,
                    'material_pt_code': mat.material_pt_code,
                    'material_name': mat.material_name,
                    'required_qty': mat.required_qty,
                    'available_now': mat.available_now,
                    'allocated_qty': mat.allocated_qty,
                    'coverage_pct': mat.coverage_pct,
                    'status': mat.status,
                    'is_primary': mat.is_primary,
                    'is_contested': mat.is_contested,
                    'earliest_full_coverage': mat.earliest_full_coverage,
                    'coverage_source': mat.coverage_source,
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def get_gantt_data(self) -> List[Dict[str, Any]]:
        """Timeline data for Plotly Gantt chart."""
        data = []
        for line in self.all_lines:
            entry = {
                'product': f"{line.pt_code} — {line.product_name[:30]}",
                'pt_code': line.pt_code,
                'bom_type': line.bom_type,
                'readiness': line.readiness_status,
                'urgency': line.urgency_level,
            }

            if line.actual_start and line.expected_completion:
                # Production bar
                entry['start'] = line.actual_start.isoformat()
                entry['end'] = line.expected_completion.isoformat()
                entry['type'] = 'PRODUCTION'
            elif line.must_start_by:
                # Target bar (no actual start — blocked)
                entry['start'] = line.must_start_by.isoformat()
                entry['end'] = (
                    line.must_start_by + __import__('datetime').timedelta(days=line.lead_time_days)
                ).isoformat()
                entry['type'] = 'TARGET'

            if line.demand_date:
                entry['demand_date'] = line.demand_date.isoformat()

            if line.bottleneck_eta:
                entry['material_ready'] = line.bottleneck_eta.isoformat()

            data.append(entry)

        return data

    # =====================================================================
    # RECONCILIATION
    # =====================================================================

    def get_reconciliation(self) -> Dict[str, Any]:
        """
        Full reconciliation: input = ready + waiting + blocked + unschedulable + errors.
        Every input item must be accounted for.
        """
        inp = self.input_summary or {}
        total_input = inp.get('total_items', 0)
        input_skipped = inp.get('validation_skipped', 0)

        ready = len(self.ready_lines)
        waiting = len(self.waiting_lines)
        blocked = len(self.blocked_lines)
        unschedulable = len(self.unschedulable_items)
        errors = len(self.metrics.get('processing_errors', []))

        accounted = ready + waiting + blocked + unschedulable + errors + input_skipped
        discrepancy = total_input - accounted

        return {
            'total_input': total_input,
            'input_skipped_validation': input_skipped,
            'ready': ready,
            'waiting': waiting,
            'blocked': blocked,
            'unschedulable': unschedulable,
            'processing_errors': errors,
            'total_accounted': accounted,
            'discrepancy': discrepancy,
            'is_balanced': discrepancy == 0,
        }

    # =====================================================================
    # METRICS
    # =====================================================================

    def compute_metrics(self):
        """Compute summary metrics from lines."""
        total = len(self.all_lines)
        ready = len(self.ready_lines)
        waiting = len(self.waiting_lines)
        blocked = len(self.blocked_lines)

        total_shortage = sum(l.shortage_qty for l in self.all_lines)
        total_suggested = sum(l.suggested_qty for l in self.all_lines)
        total_at_risk = sum(l.at_risk_value for l in self.all_lines)

        ready_value = sum(l.at_risk_value for l in self.ready_lines)
        waiting_value = sum(l.at_risk_value for l in self.waiting_lines)
        blocked_value = sum(l.at_risk_value for l in self.blocked_lines)

        # Urgency distribution
        urgency_dist = {}
        for line in self.all_lines:
            urgency_dist[line.urgency_level] = urgency_dist.get(line.urgency_level, 0) + 1

        overdue_count = sum(1 for l in self.all_lines if l.urgency_level == 'OVERDUE')
        delayed_count = sum(1 for l in self.all_lines if l.is_delayed)

        # BOM type distribution
        bom_dist = {}
        for line in self.all_lines:
            bom_dist[line.bom_type] = bom_dist.get(line.bom_type, 0) + 1

        # Contention
        contention_count = sum(1 for l in self.all_lines if l.has_contention)

        self.metrics = {
            'total_mo_lines': total,
            'ready_count': ready,
            'waiting_count': waiting,
            'blocked_count': blocked,
            'unschedulable_count': len(self.unschedulable_items),
            'total_shortage_qty': round(total_shortage, 2),
            'total_suggested_qty': round(total_suggested, 2),
            'total_at_risk_value': round(total_at_risk, 2),
            'ready_at_risk_value': round(ready_value, 2),
            'waiting_at_risk_value': round(waiting_value, 2),
            'blocked_at_risk_value': round(blocked_value, 2),
            'urgency_distribution': urgency_dist,
            'overdue_count': overdue_count,
            'delayed_count': delayed_count,
            'bom_type_distribution': bom_dist,
            'contention_count': contention_count,
            'reconciliation': self.get_reconciliation(),
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M'),
        }

    def get_summary(self) -> Dict[str, Any]:
        if not self.metrics:
            self.compute_metrics()
        return self.metrics

    # =====================================================================
    # QUERIES
    # =====================================================================

    def get_overdue_lines(self) -> List[MOLineItem]:
        return [l for l in self.all_lines if l.urgency_level == 'OVERDUE']

    def get_delayed_lines(self) -> List[MOLineItem]:
        return [l for l in self.all_lines if l.is_delayed]

    def get_lines_by_bom_type(self, bom_type: str) -> List[MOLineItem]:
        return [l for l in self.all_lines if l.bom_type == bom_type]

    def get_urgency_distribution(self) -> Dict[str, int]:
        dist = {}
        for line in self.all_lines:
            dist[line.urgency_level] = dist.get(line.urgency_level, 0) + 1
        return dist

    # =====================================================================
    # VALIDATION
    # =====================================================================

    def has_lines(self) -> bool:
        return len(self.all_lines) > 0

    def has_ready(self) -> bool:
        return len(self.ready_lines) > 0

    def has_waiting(self) -> bool:
        return len(self.waiting_lines) > 0

    def has_blocked(self) -> bool:
        return len(self.blocked_lines) > 0

    def has_unschedulable(self) -> bool:
        return len(self.unschedulable_items) > 0

    def has_overdue(self) -> bool:
        return any(l.urgency_level == 'OVERDUE' for l in self.all_lines)
