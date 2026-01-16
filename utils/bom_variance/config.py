# utils/bom_variance/config.py
"""
BOM Variance Configuration - VERSION 2.0

Contains:
- VarianceConfig dataclass
- Constants (material types, BOM types, etc.)
- Session state initialization helpers
- Common formatting functions
"""

import streamlit as st
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum


# ==================== Constants ====================

MATERIAL_TYPES = ['RAW_MATERIAL', 'PACKAGING', 'CONSUMABLE']
BOM_TYPES = ['CUTTING', 'KITTING', 'REPACKING']
VARIANCE_DIRECTIONS = ['All', 'Under-used', 'On-target', 'Over-used', 'High Variance']


# ==================== Enums ====================

class ApplyMode(Enum):
    """How to apply recommendations"""
    CLONE = "clone"          # Clone BOM with adjusted values (creates DRAFT)
    DIRECT_UPDATE = "update" # Direct update if BOM has no usage


class UsageMode(Enum):
    """MO usage mode classification"""
    PRIMARY_ONLY = "PRIMARY_ONLY"
    ALTERNATIVE_ONLY = "ALTERNATIVE_ONLY"
    MIXED = "MIXED"


# ==================== Configuration Dataclass ====================

@dataclass
class VarianceConfig:
    """
    Configuration for variance analysis
    
    Attributes:
        variance_threshold: Flag materials with variance above this % (default: 5%)
        high_variance_threshold: Urgent attention threshold % (default: 10%)
        min_mo_count: Minimum completed MOs for reliable statistics (default: 3)
        cv_threshold: Coefficient of variation threshold for high variability flag (default: 15%)
        date_from: Start date for analysis window
        date_to: End date for analysis window
        default_months: Default analysis window in months (default: 3)
    """
    variance_threshold: float = 5.0
    high_variance_threshold: float = 10.0
    min_mo_count: int = 3
    cv_threshold: float = 15.0
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    default_months: int = 3
    
    def __post_init__(self):
        """Set default date range if not provided"""
        if self.date_to is None:
            self.date_to = date.today()
        
        if self.date_from is None:
            self.date_from = self.date_to - timedelta(days=self.default_months * 30)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            'variance_threshold': self.variance_threshold,
            'high_variance_threshold': self.high_variance_threshold,
            'min_mo_count': self.min_mo_count,
            'cv_threshold': self.cv_threshold,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'default_months': self.default_months
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VarianceConfig':
        """Create config from dictionary"""
        return cls(
            variance_threshold=data.get('variance_threshold', 5.0),
            high_variance_threshold=data.get('high_variance_threshold', 10.0),
            min_mo_count=data.get('min_mo_count', 3),
            cv_threshold=data.get('cv_threshold', 15.0),
            date_from=data.get('date_from'),
            date_to=data.get('date_to'),
            default_months=data.get('default_months', 3)
        )


# ==================== Session State Helpers ====================

def init_session_state():
    """Initialize session state for variance analysis"""
    
    # Configuration (for DB query parameters)
    if 'variance_config' not in st.session_state:
        st.session_state['variance_config'] = VarianceConfig()
    
    # Full data cache (loaded from DB)
    if 'variance_full_data' not in st.session_state:
        st.session_state['variance_full_data'] = None
    
    # Filter states - Category filters
    if 'filter_material_types' not in st.session_state:
        st.session_state['filter_material_types'] = []  # Empty = All
    
    if 'filter_bom_types' not in st.session_state:
        st.session_state['filter_bom_types'] = []  # Empty = All
    
    if 'filter_variance_direction' not in st.session_state:
        st.session_state['filter_variance_direction'] = 'All'
    
    # Filter states - Entity filters
    if 'filter_products' not in st.session_state:
        st.session_state['filter_products'] = []  # Empty = All
    
    if 'filter_boms' not in st.session_state:
        st.session_state['filter_boms'] = []  # Empty = All
    
    if 'filter_materials' not in st.session_state:
        st.session_state['filter_materials'] = []  # Empty = All
    
    # Quick filter toggles
    if 'filter_high_variance_only' not in st.session_state:
        st.session_state['filter_high_variance_only'] = False
    
    if 'filter_zero_actual_only' not in st.session_state:
        st.session_state['filter_zero_actual_only'] = False
    
    # Filter section expanded state
    if 'filters_expanded' not in st.session_state:
        st.session_state['filters_expanded'] = True


def get_config() -> VarianceConfig:
    """Get current variance config from session state"""
    return st.session_state.get('variance_config', VarianceConfig())


def clear_data_cache():
    """Clear data cache (triggers reload from DB)"""
    st.session_state['variance_full_data'] = None


def reset_filters():
    """Reset all filters to default (empty = all)"""
    st.session_state['filter_material_types'] = []
    st.session_state['filter_bom_types'] = []
    st.session_state['filter_variance_direction'] = 'All'
    st.session_state['filter_products'] = []
    st.session_state['filter_boms'] = []
    st.session_state['filter_materials'] = []
    st.session_state['filter_high_variance_only'] = False
    st.session_state['filter_zero_actual_only'] = False


# ==================== Formatting Helpers ====================

def format_product_display(
    code: str, 
    name: str, 
    package_size: Optional[str] = None,
    brand: Optional[str] = None,
    legacy_code: Optional[str] = None,
    max_name_length: int = 40
) -> str:
    """
    Format product display: code (legacy) | name | package_size (brand)
    
    Examples:
        "PT-001 (OLD-001) | Product ABC | 100g (Brand A)"
        "PT-002 (NEW) | Product XYZ | 500ml"
    """
    # Truncate name if too long
    if name and len(name) > max_name_length:
        name = name[:max_name_length - 3] + "..."
    
    # Format legacy code
    legacy_display = "NEW"
    if legacy_code and str(legacy_code).strip() and str(legacy_code).strip() not in ['-', 'None', '']:
        legacy_display = str(legacy_code).strip()
    
    result = f"{code} ({legacy_display}) | {name}"
    
    # Add package size and/or brand
    extra_parts = []
    
    if package_size and str(package_size).strip() and str(package_size).strip() not in ['-', 'None', '']:
        extra_parts.append(str(package_size).strip())
    
    if brand and str(brand).strip() and str(brand).strip() not in ['-', 'None', '']:
        if extra_parts:
            extra_parts[0] = f"{extra_parts[0]} ({str(brand).strip()})"
        else:
            extra_parts.append(f"({str(brand).strip()})")
    
    if extra_parts:
        result += " | " + " ".join(extra_parts)
    
    return result


def format_bom_display(bom_code: str, bom_name: str, bom_type: str = None) -> str:
    """
    Format BOM display: bom_code | bom_name [type]
    
    Examples:
        "BOM-CUT-001 | Main Product BOM [CUTTING]"
    """
    result = f"{bom_code} | {bom_name}"
    if bom_type:
        result += f" [{bom_type}]"
    return result


def format_variance_display(value: float) -> str:
    """Format variance for display with color indicator"""
    import pandas as pd
    
    if pd.isna(value):
        return "N/A"
    
    if value > 10:
        return f"🔴 +{value:.1f}%"
    elif value > 5:
        return f"🟠 +{value:.1f}%"
    elif value > 0:
        return f"🟡 +{value:.1f}%"
    elif value > -5:
        return f"🟢 {value:.1f}%"
    elif value > -10:
        return f"🔵 {value:.1f}%"
    else:
        return f"🔵 {value:.1f}%"


def format_quantity(value: float, decimals: int = 4) -> str:
    """Format quantity with appropriate decimals"""
    import pandas as pd
    
    if pd.isna(value):
        return "N/A"
    return f"{value:,.{decimals}f}"


def extract_code_from_option(option: str) -> str:
    """Extract code from formatted option string"""
    # Format: "CODE (legacy) | name | ..."
    if '|' in option:
        first_part = option.split('|')[0].strip()
        if '(' in first_part:
            return first_part.split('(')[0].strip()
        return first_part
    return option


def extract_bom_code_from_option(option: str) -> str:
    """Extract BOM code from formatted option string"""
    # Format: "BOM-CODE | name [TYPE]"
    if '|' in option:
        return option.split('|')[0].strip()
    return option
