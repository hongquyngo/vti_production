# utils/bom_variance/__init__.py
"""
BOM Variance Analysis Module - VERSION 2.0 (Restructured)

Analyzes actual material consumption vs BOM theoretical values
to identify variances and suggest adjustments.

Location: utils/bom_variance/

Structure:
├── __init__.py              # This file - module exports
├── config.py                # Configuration, constants, helpers
├── queries.py               # SQL queries for data extraction
├── analyzer.py              # Core analysis logic
├── tab_dashboard.py         # Tab 1: Dashboard Overview (Phase 1)
├── tab_detail.py            # Tab 2: BOM Detail Analysis (Phase 2)
├── tab_recommendations.py   # Tab 3: Recommendations + Export (Phase 3)
└── actions.py               # Clone BOM, Apply changes (Phase 4)

Usage:
    from utils.bom_variance import VarianceAnalyzer, VarianceConfig
    from utils.bom_variance import tab_dashboard, tab_detail, tab_recommendations
"""

# Core classes
from .config import VarianceConfig, ApplyMode, UsageMode
from .config import (
    MATERIAL_TYPES, 
    BOM_TYPES, 
    VARIANCE_DIRECTIONS,
    init_session_state,
    get_config,
    clear_data_cache,
    reset_filters
)
from .queries import VarianceQueries
from .analyzer import VarianceAnalyzer

# Tab modules (imported as modules, not individual functions)
from . import tab_dashboard
from . import tab_detail
from . import tab_recommendations
from . import actions

__all__ = [
    # Core classes
    'VarianceConfig',
    'VarianceQueries',
    'VarianceAnalyzer',
    
    # Enums
    'ApplyMode',
    'UsageMode',
    
    # Constants
    'MATERIAL_TYPES',
    'BOM_TYPES',
    'VARIANCE_DIRECTIONS',
    
    # Session state helpers
    'init_session_state',
    'get_config',
    'clear_data_cache',
    'reset_filters',
    
    # Tab modules
    'tab_dashboard',
    'tab_detail',
    'tab_recommendations',
    'actions',
]
