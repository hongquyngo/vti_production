# utils/supply_chain_production/production_constants.py

"""
Constants for Production Planning module.

ZERO ASSUMPTION: This file contains ONLY labels, icons, enum values, and UI text.
All numeric parameters (lead times, thresholds, weights) are loaded from
production_planning_config table via production_config.py.
"""

# =============================================================================
# VERSION
# =============================================================================
VERSION = "1.1.0"

# =============================================================================
# BOM TYPES — matches bom_headers.bom_type enum
# =============================================================================
BOM_TYPES = {
    'CUTTING': {
        'label': 'Cutting',
        'icon': '✂️',
        'description': 'Cut 1 large input → N smaller outputs (e.g., tape rolls)',
    },
    'REPACKING': {
        'label': 'Repacking',
        'icon': '📦',
        'description': 'Repack 1 format → another format (e.g., bulk → retail)',
    },
    'KITTING': {
        'label': 'Kitting',
        'icon': '🔧',
        'description': 'Combine N inputs → 1 output (e.g., kit assembly)',
    },
}

VALID_BOM_TYPES = set(BOM_TYPES.keys())

# =============================================================================
# PRODUCTION READINESS STATUS
# =============================================================================
READINESS_STATUS = {
    'READY': {
        'label': 'Ready',
        'icon': '✅',
        'color': '#10B981',
        'description': 'All materials available — can create MO immediately',
        'priority': 1,
    },
    'PARTIAL_READY': {
        'label': 'Partial',
        'icon': '🟡',
        'color': '#F59E0B',
        'description': 'Some materials available — production possible at reduced qty',
        'priority': 2,
    },
    'USE_ALTERNATIVE': {
        'label': 'Alternative',
        'icon': '🔄',
        'color': '#06B6D4',
        'description': 'Primary material short but alternative covers shortage',
        'priority': 3,
    },
    'BLOCKED': {
        'label': 'Blocked',
        'icon': '🔴',
        'color': '#DC2626',
        'description': 'Critical materials unavailable — cannot produce',
        'priority': 4,
    },
}

# =============================================================================
# MATERIAL READINESS STATUS (per BOM line)
# =============================================================================
MATERIAL_STATUS = {
    'READY': {'label': 'Ready', 'icon': '✅', 'color': '#10B981'},
    'PARTIAL': {'label': 'Partial', 'icon': '🟡', 'color': '#F59E0B'},
    'BLOCKED': {'label': 'Blocked', 'icon': '🔴', 'color': '#DC2626'},
}

# =============================================================================
# MATERIAL COVERAGE SOURCE — where the supply comes from
# =============================================================================
COVERAGE_SOURCE = {
    'IN_STOCK': {'label': 'In Stock', 'icon': '📦'},
    'PENDING_PO': {'label': 'Pending PO', 'icon': '📝'},
    'PO_SUGGESTED': {'label': 'PO Suggested', 'icon': '🛒'},
    'UNKNOWN': {'label': 'Unknown', 'icon': '❓'},
}

# =============================================================================
# MO URGENCY — reuse same structure as PO Planning for consistency
# =============================================================================
MO_URGENCY_LEVELS = {
    'OVERDUE': {
        'label': 'Overdue',
        'icon': '🚨',
        'color': '#7F1D1D',
        'description': 'Must-start-by date has passed — production delayed',
        'priority': 1,
    },
    'CRITICAL': {
        'label': 'Critical',
        'icon': '🔴',
        'color': '#DC2626',
        'description': 'Must start within 3 days',
        'priority': 2,
    },
    'URGENT': {
        'label': 'Urgent',
        'icon': '🟠',
        'color': '#EA580C',
        'description': 'Must start within 7 days',
        'priority': 3,
    },
    'THIS_WEEK': {
        'label': 'This Week',
        'icon': '🟡',
        'color': '#CA8A04',
        'description': 'Must start within 14 days',
        'priority': 4,
    },
    'PLANNED': {
        'label': 'Planned',
        'icon': '🔵',
        'color': '#3B82F6',
        'description': 'More than 14 days — plan ahead',
        'priority': 5,
    },
}

# Thresholds for urgency classification (days from today to must_start_by)
MO_URGENCY_THRESHOLDS = {
    'OVERDUE': 0,
    'CRITICAL': 3,
    'URGENT': 7,
    'THIS_WEEK': 14,
}

# =============================================================================
# MO ACTION TYPES — what to do with the product
# =============================================================================
MO_ACTION_TYPES = {
    'CREATE_MO': {
        'label': 'Create MO',
        'icon': '🏭',
        'description': 'Materials ready — create manufacturing order',
    },
    'WAIT_MATERIAL': {
        'label': 'Wait for Material',
        'icon': '⏳',
        'description': 'Materials not yet available — schedule MO for later',
    },
    'USE_ALTERNATIVE': {
        'label': 'Use Alternative',
        'icon': '🔄',
        'description': 'Use alternative material to start production',
    },
}

# =============================================================================
# SCHEDULING — source labels
# =============================================================================
LEAD_TIME_SOURCE = {
    'BOM_PLANT': {'label': 'BOM (Plant)', 'icon': '🏭'},
    'BOM_GLOBAL': {'label': 'BOM (Global)', 'icon': '📋'},
    'CONFIG_DEFAULT': {'label': 'Config Default', 'icon': '⚙️'},
    'CONFIG': {'label': 'Config', 'icon': '⚙️'},              # backward compat alias
    'HISTORICAL_BOM': {'label': 'Historical (BOM)', 'icon': '📊'},
    'HISTORICAL_PRODUCT': {'label': 'Historical (Product)', 'icon': '📊'},
    'HISTORICAL_BOM_TYPE': {'label': 'Historical (BOM Type)', 'icon': '📈'},
}

YIELD_SOURCE = {
    'BOM_SCRAP': {'label': 'BOM Scrap Rate', 'icon': '📋'},
    'HISTORICAL': {'label': 'Historical Yield', 'icon': '📊'},
    'CONFIG_DEFAULT': {'label': 'Config Default', 'icon': '⚙️'},
}

# =============================================================================
# UNSCHEDULABLE REASONS — products that cannot be scheduled
# =============================================================================
UNSCHEDULABLE_REASONS = {
    'MISSING_LEAD_TIME_CONFIG': {
        'icon': '⚙️',
        'label': 'Missing Lead Time Config',
        'action': 'Go to Settings → Lead Time Setup',
    },
    'UNKNOWN_BOM_TYPE': {
        'icon': '❓',
        'label': 'Unknown BOM Type',
        'action': 'Check BOM header — type must be CUTTING, REPACKING, or KITTING',
    },
    'NO_BOM': {
        'icon': '📋',
        'label': 'No Active BOM',
        'action': 'Product has no active BOM — cannot determine production requirements',
    },
    'ZERO_SHORTAGE': {
        'icon': '✅',
        'label': 'Zero Shortage',
        'action': 'No shortage after existing MO coverage — no MO needed',
    },
}

# =============================================================================
# CONFIG GROUPS — for Settings UI rendering
# =============================================================================
CONFIG_GROUPS = {
    'LEAD_TIME': {
        'label': 'Lead Time Setup',
        'icon': '📅',
        'description': 'Production lead time per BOM type + historical override settings',
    },
    'YIELD': {
        'label': 'Yield Setup',
        'icon': '📊',
        'description': 'Scrap rate defaults + historical yield override',
    },
    'PRIORITY': {
        'label': 'Priority Weights',
        'icon': '⚖️',
        'description': 'Scoring weights for MO prioritization (must sum to 100%)',
    },
    'PLANNING': {
        'label': 'Planning Parameters',
        'icon': '📋',
        'description': 'General planning parameters',
    },
}

# =============================================================================
# RECOMMENDED DEFAULTS — for Quick-Start feature
# =============================================================================
# These are SUGGESTIONS shown to users, not auto-applied.
# User must explicitly click "Apply" then "Save". ZERO ASSUMPTION preserved.
RECOMMENDED_DEFAULTS = {
    'lead_time': {
        'CUTTING': 3,       # Based on historical avg 2.5d, rounded up for buffer
        'REPACKING': 1,     # Based on historical avg 0.0d, minimum 1d
        'KITTING': 2,       # Based on historical avg 1.8d, rounded up
    },
    'priority_weights': {
        'time': 40,
        'readiness': 25,
        'value': 20,
        'customer': 15,
    },
    'planning_horizon_days': 60,
    'historical_override': False,  # Conservative — user opts in
}

# =============================================================================
# UI CONFIG — layout settings (not business logic)
# =============================================================================
PRODUCTION_UI = {
    'items_per_page_options': [10, 25, 50, 100],
    'default_items_per_page': 25,
    'chart_height': 350,
    'timeline_max_items': 30,
    'readiness_matrix_max_items': 50,
}

# =============================================================================
# ALIASES — shorter names for UI components
# =============================================================================
URGENCY_LEVELS = MO_URGENCY_LEVELS
