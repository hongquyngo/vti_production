# utils/supply_chain_production/production_interfaces.py

"""
Typed interfaces for GAP → Production Planning boundary.

ZERO ASSUMPTION: No implicit dependency on GAP module's internal structure.
Everything Production Planning needs from GAP is defined here as explicit
dataclasses. The conversion happens ONCE in production_validators.py.

These dataclasses serve as the SINGLE SOURCE OF TRUTH for what flows
between modules. If GAP changes a field name, only production_validators.py
needs updating — the rest of Production Planning is insulated.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import date


# =============================================================================
# INPUT: GAP → Production Planning
# =============================================================================

@dataclass
class ProductionInputItem:
    """
    One manufacturing product with shortage, flowing from GAP to Production Planning.

    This is the typed boundary contract. production_validators.py converts
    GAP's ActionRecommendation + classification_df + fg_gap_df into this.
    """
    # Product identity
    product_id: int
    pt_code: str
    product_name: str
    brand: str
    package_size: str
    uom: str

    # Shortage from GAP
    shortage_qty: float                      # abs(net_gap) from GAP fg_gap_df
    at_risk_value: float                     # net_gap × avg_unit_price_usd
    customer_count: int                      # affected customer count

    # BOM info (from product_classification_view via GAP)
    bom_id: int
    bom_code: str
    bom_type: str                            # CUTTING, REPACKING, KITTING
    bom_output_qty: float                    # batch size

    # Demand timing (from GAP period data, may be None)
    demand_date: Optional[date] = None

    # Sales order linkage (from existing MOs for this product)
    has_sales_order: bool = False

    # GAP production status (informational, from get_production_status)
    gap_production_status: str = ''          # SUFFICIENT, SHORTAGE, USE_ALTERNATIVE
    gap_limiting_materials: List[str] = field(default_factory=list)


@dataclass
class MaterialRequirement:
    """
    One BOM material needed for production of a ProductionInputItem.

    Derived from bom_explosion_view (via GAP result's bom_explosion_df).
    """
    material_id: int
    material_pt_code: str
    material_name: str
    material_uom: str
    material_type: str                       # RAW_MATERIAL, PACKAGING, CONSUMABLE
    is_primary: bool
    alternative_priority: int
    primary_material_id: Optional[int]       # if this is an alternative

    # BOM quantities
    quantity_per_output: float
    scrap_rate: float                        # from BOM detail (may be 0)
    effective_qty_per_output: float           # qty × (1 + scrap/100)
    bom_output_qty: float                    # from BOM header

    # Calculated for this MO suggestion
    required_qty: float = 0                  # (shortage / bom_output) × qty_per × (1+scrap)


# =============================================================================
# INTERNAL: Readiness results
# =============================================================================

@dataclass
class MaterialReadiness:
    """Readiness status for one BOM material of one FG product."""
    material_id: int
    material_pt_code: str
    material_name: str
    material_uom: str
    material_type: str
    is_primary: bool

    # Quantities
    required_qty: float
    available_now: float                     # current supply from raw_gap_df
    allocated_qty: float = 0                 # after contention resolution (pass 2)
    shortage_qty: float = 0
    coverage_pct: float = 0                  # (available or allocated) / required × 100

    # Status
    status: str = 'BLOCKED'                  # READY, PARTIAL, BLOCKED

    # ETA for full coverage
    earliest_full_coverage: Optional[date] = None
    coverage_source: str = 'UNKNOWN'         # IN_STOCK, PENDING_PO, PO_SUGGESTED, UNKNOWN

    # Alternative info
    has_alternative: bool = False
    alternative_can_cover: bool = False

    # Contention
    is_contested: bool = False
    contention_products: int = 0


@dataclass
class ProductReadiness:
    """Overall production readiness for one FG manufacturing product."""
    product_id: int
    pt_code: str
    product_name: str
    bom_code: str
    bom_type: str

    # Overall status
    overall_status: str = 'BLOCKED'          # READY, PARTIAL_READY, BLOCKED, USE_ALTERNATIVE
    can_start_production: bool = False

    # Material breakdown
    materials: List[MaterialReadiness] = field(default_factory=list)
    total_materials: int = 0
    ready_materials: int = 0
    partial_materials: int = 0
    blocked_materials: int = 0

    # Timing
    earliest_start_date: Optional[date] = None
    bottleneck_material_id: Optional[int] = None
    bottleneck_material_code: str = ''
    bottleneck_eta: Optional[date] = None

    # Partial production
    max_producible_now: float = 0
    max_producible_pct: float = 0            # max_producible / shortage_qty × 100

    # Contention info
    has_contention: bool = False
    contested_material_count: int = 0

    # Priority (set during scheduling)
    priority_score: float = 999.0

    def recompute_overall_status(self):
        """Recompute after contention resolution changes allocations."""
        self.ready_materials = sum(1 for m in self.materials if m.status == 'READY')
        self.partial_materials = sum(1 for m in self.materials if m.status == 'PARTIAL')
        self.blocked_materials = sum(1 for m in self.materials if m.status == 'BLOCKED')
        self.total_materials = len(self.materials)

        # Check alternatives for blocked primary materials
        all_blocked_covered_by_alt = True
        for mat in self.materials:
            if mat.status == 'BLOCKED' and mat.is_primary:
                if not mat.alternative_can_cover:
                    all_blocked_covered_by_alt = False
                    break

        if self.blocked_materials == 0 and self.partial_materials == 0:
            self.overall_status = 'READY'
            self.can_start_production = True
        elif self.blocked_materials > 0 and all_blocked_covered_by_alt:
            self.overall_status = 'USE_ALTERNATIVE'
            self.can_start_production = True
        elif self.blocked_materials == 0 and self.partial_materials > 0:
            self.overall_status = 'PARTIAL_READY'
            self.can_start_production = False
        else:
            self.overall_status = 'BLOCKED'
            self.can_start_production = False

        # Bottleneck: material with latest ETA or lowest coverage
        self.bottleneck_material_id = None
        self.bottleneck_material_code = ''
        self.bottleneck_eta = None

        worst_coverage = 999.0
        latest_eta = None
        for mat in self.materials:
            if mat.is_primary and mat.coverage_pct < worst_coverage:
                worst_coverage = mat.coverage_pct
                self.bottleneck_material_id = mat.material_id
                self.bottleneck_material_code = mat.material_pt_code
            if mat.earliest_full_coverage is not None:
                if latest_eta is None or mat.earliest_full_coverage > latest_eta:
                    latest_eta = mat.earliest_full_coverage
                    self.bottleneck_eta = latest_eta

        # Earliest start = latest ETA across all materials (all must be ready)
        if self.overall_status == 'READY':
            self.earliest_start_date = date.today()
        elif latest_eta is not None:
            self.earliest_start_date = latest_eta
        else:
            self.earliest_start_date = None

        # Contention
        self.contested_material_count = sum(1 for m in self.materials if m.is_contested)
        self.has_contention = self.contested_material_count > 0


@dataclass
class UnschedulableItem:
    """Product that cannot be scheduled — missing config or data."""
    product_id: int
    pt_code: str
    product_name: str
    brand: str
    shortage_qty: float
    uom: str
    reason_code: str                         # key into UNSCHEDULABLE_REASONS
    reason_detail: str                       # human-readable explanation
    missing_config_key: str = ''             # e.g. 'LEAD_TIME.CUTTING.DAYS'
    action: str = ''                         # 'Go to Settings → Lead Time Setup'
