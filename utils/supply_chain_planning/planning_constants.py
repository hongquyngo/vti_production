# utils/supply_chain_planning/planning_constants.py

"""
Constants for Supply Chain Planning module.
PO Planning (Phase 1) + Production Planning (Phase 2)
"""

# =============================================================================
# VERSION
# =============================================================================
VERSION = "1.2.0"

# =============================================================================
# URGENCY LEVELS — PO must-order-by date vs today
# =============================================================================
URGENCY_LEVELS = {
    'OVERDUE': {
        'label': 'Overdue',
        'icon': '🚨',
        'color': '#7F1D1D',
        'description': 'Must-order-by date has passed — order immediately',
        'priority': 1,
    },
    'CRITICAL': {
        'label': 'Critical',
        'icon': '🔴',
        'color': '#DC2626',
        'description': 'Must order within 3 days',
        'priority': 2,
    },
    'URGENT': {
        'label': 'Urgent',
        'icon': '🟠',
        'color': '#EA580C',
        'description': 'Must order within 7 days',
        'priority': 3,
    },
    'THIS_WEEK': {
        'label': 'This Week',
        'icon': '🟡',
        'color': '#CA8A04',
        'description': 'Must order within 14 days',
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

# Thresholds (days from today to must_order_by)
URGENCY_THRESHOLDS = {
    'OVERDUE': 0,       # must_order_by < today
    'CRITICAL': 3,      # within 3 days
    'URGENT': 7,        # within 7 days
    'THIS_WEEK': 14,    # within 14 days
    # else → PLANNED
}

# =============================================================================
# LEAD TIME DEFAULTS (fallback when costbook has no data)
# =============================================================================
LEAD_TIME_DEFAULTS = {
    'DOMESTIC': {
        'production_days': 3,
        'transit_days': 3,
        'customs_days': 0,
        'buffer_days': 3,
        'total_days': 9,
    },
    'INTERNATIONAL': {
        'production_days': 14,
        'transit_days': 21,
        'customs_days': 5,
        'buffer_days': 5,
        'total_days': 45,
    },
    'UNKNOWN': {
        'total_days': 21,  # conservative default
    },
}

# Buffer days added ON TOP of costbook lead time
# Based on vendor_delivery_performance: avg delay = 16.3 days
#
# v1.1: ADAPTIVE mode uses actual avg_delay_days from vendor performance
# instead of fixed values. Prevents urgency inflation where 60%+ items
# show OVERDUE because unreliable vendors get blanket +10d buffer.
LEAD_TIME_BUFFER_DAYS = {
    'DEFAULT': 5,
    'UNRELIABLE_VENDOR': 10,    # on_time_rate < 50%
    'RELIABLE_VENDOR': 3,       # on_time_rate >= 80%
}

# Adaptive buffer: use actual avg_delay_days capped at these limits
LEAD_TIME_BUFFER_ADAPTIVE = {
    'enabled': True,                # set False to revert to fixed buffer
    'min_buffer_days': 3,           # never go below 3 days even if vendor is perfect
    'max_buffer_days': 15,          # cap to prevent extreme inflation
    'reliable_multiplier': 0.5,     # RELIABLE: buffer = avg_delay × 0.5
    'average_multiplier': 0.75,     # AVERAGE: buffer = avg_delay × 0.75
    'unreliable_multiplier': 1.0,   # UNRELIABLE: buffer = avg_delay × 1.0
    'unknown_fixed': 5,             # UNKNOWN (no perf data): fixed 5 days
}

# Vendor reliability thresholds (from vendor_delivery_performance_view)
VENDOR_RELIABILITY = {
    'RELIABLE_THRESHOLD': 80,       # on_time_rate_pct >= 80 → reliable
    'UNRELIABLE_THRESHOLD': 50,     # on_time_rate_pct < 50 → unreliable
    'MIN_DELIVERIES': 3,            # need at least 3 deliveries to judge
}

# =============================================================================
# MOQ / SPQ ROUNDING
# =============================================================================
MOQ_SPQ_CONFIG = {
    'round_up': True,               # always round UP to nearest SPQ
    'allow_below_moq': False,       # if required < MOQ, suggest MOQ
    'max_excess_ratio': 3.0,        # warn if suggested > 3x required
}

# =============================================================================
# PRICE SOURCE PRIORITY
# =============================================================================
PRICE_SOURCE = {
    'COSTBOOK': {'label': 'Costbook', 'icon': '📗', 'priority': 1},
    'LAST_PO': {'label': 'Last PO', 'icon': '📝', 'priority': 2},
    'NO_SOURCE': {'label': 'No Source', 'icon': '❌', 'priority': 99},
}

# =============================================================================
# SHORTAGE SOURCE (what triggered the PO need)
# =============================================================================
SHORTAGE_SOURCE = {
    'FG_TRADING': {
        'label': 'Trading FG',
        'icon': '🛒',
        'description': 'Finished goods without BOM — must purchase directly',
    },
    'RAW_MATERIAL': {
        'label': 'Raw Material',
        'icon': '🧪',
        'description': 'Raw material for manufacturing — BOM component shortage',
    },
}

# =============================================================================
# PO SUGGESTION STATUS
# =============================================================================
PO_SUGGESTION_STATUS = {
    'DRAFT': {'label': 'Draft', 'icon': '📝'},
    'REVIEWED': {'label': 'Reviewed', 'icon': '👁'},
    'APPROVED': {'label': 'Approved', 'icon': '✅'},
    'PO_CREATED': {'label': 'PO Created', 'icon': '📦'},
    'DISMISSED': {'label': 'Dismissed', 'icon': '🚫'},
}

# =============================================================================
# UI CONFIGURATION
# =============================================================================
PO_PLANNING_UI = {
    'items_per_page_options': [10, 25, 50, 100],
    'default_items_per_page': 25,
    'chart_height': 350,
    'vendor_card_max_items': 10,
}