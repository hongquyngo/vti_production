# utils/inventory_quality/common.py
"""
Common utilities for Inventory Quality module
Formatting, validation, UI helpers, and constants

Version: 1.0.0
"""

import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union, Any
from io import BytesIO

import pandas as pd
import streamlit as st

# Timezone support
try:
    from zoneinfo import ZoneInfo
    VN_TIMEZONE = ZoneInfo('Asia/Ho_Chi_Minh')
except ImportError:
    try:
        import pytz
        VN_TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')
    except ImportError:
        VN_TIMEZONE = None
        logging.warning("No timezone library available. Using system timezone.")

logger = logging.getLogger(__name__)


# ==================== Constants ====================

class InventoryQualityConstants:
    """Inventory Quality specific constants"""
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 500
    QUANTITY_DECIMALS = 4
    CURRENCY_DECIMALS = 2
    
    # Categories
    CATEGORY_GOOD = 'GOOD'
    CATEGORY_QUARANTINE = 'QUARANTINE'
    CATEGORY_DEFECTIVE = 'DEFECTIVE'
    
    # Category display
    CATEGORY_DISPLAY = {
        'GOOD': '📗 Good',
        'QUARANTINE': '📙 Quarantine',
        'DEFECTIVE': '📕 Defective'
    }
    
    CATEGORY_COLORS = {
        'GOOD': '#28a745',
        'QUARANTINE': '#ffc107', 
        'DEFECTIVE': '#dc3545'
    }
    
    # Defect types - includes new partial QC defect types
    DEFECT_TYPES = {
        # Legacy defect types
        'QC_PENDING': 'QC Pending',
        'QC_FAILED': 'QC Failed',
        'DAMAGED': 'Damaged',
        'EXPIRED': 'Expired',
        'CONTAMINATED': 'Contaminated',
        # New partial QC defect types
        'VISUAL': '🔍 Visual Defect',
        'DIMENSIONAL': '📏 Dimensional',
        'FUNCTIONAL': '⚙️ Functional',
        'CONTAMINATION': '🧪 Contamination',
        'PACKAGING': '📦 Packaging',
        'OTHER': '❓ Other'
    }
    
    # Source types - includes partial QC source
    SOURCE_TYPES = {
        'Opening Balance': 'Opening Balance',
        'Production': 'Production',
        'Production Return': 'Production Return',
        'Production (Pending QC)': 'Production (Pending QC)',
        'Production (Failed QC)': 'Production (Failed QC)',
        'Production (Partial QC Failed)': 'Production (Partial QC Failed)',  # NEW
        'Material Return (Damaged)': 'Material Return (Damaged)',
        'Direct Stock-In': 'Direct Stock-In'
    }


# ==================== Timezone Helpers ====================

def get_vietnam_now() -> datetime:
    """Get current datetime in Vietnam timezone (UTC+7)"""
    if VN_TIMEZONE:
        return datetime.now(VN_TIMEZONE)
    return datetime.now()


def get_vietnam_today() -> date:
    """Get current date in Vietnam timezone (UTC+7)"""
    if VN_TIMEZONE:
        return datetime.now(VN_TIMEZONE).date()
    return date.today()


# ==================== Formatting Helpers ====================

def format_quantity(value: Any, decimals: int = 4) -> str:
    """Format quantity with specified decimal places"""
    if value is None:
        return "-"
    try:
        num = float(value)
        if num == int(num):
            return f"{int(num):,}"
        return f"{num:,.{decimals}f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return str(value)


def format_currency(value: Any, currency: str = "USD", decimals: int = 2) -> str:
    """Format currency value"""
    if value is None:
        return "-"
    try:
        num = float(value)
        if currency == "VND":
            return f"{int(num):,} ₫"
        return f"${num:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def format_date(value: Any, fmt: str = "%Y-%m-%d") -> str:
    """Format date value"""
    if value is None:
        return "-"
    try:
        if isinstance(value, str):
            return value
        if isinstance(value, (date, datetime)):
            return value.strftime(fmt)
        return str(value)
    except Exception:
        return str(value)


def format_days(days: Any) -> str:
    """Format days with appropriate suffix"""
    if days is None:
        return "-"
    try:
        d = int(days)
        if d == 0:
            return "Today"
        elif d == 1:
            return "1 day"
        else:
            return f"{d} days"
    except (ValueError, TypeError):
        return str(days)


# ==================== UI Helpers ====================

def render_category_badge(category: str) -> str:
    """Render HTML badge for category"""
    display = InventoryQualityConstants.CATEGORY_DISPLAY.get(category, category)
    color = InventoryQualityConstants.CATEGORY_COLORS.get(category, '#6c757d')
    return f'<span style="background-color:{color};color:white;padding:2px 8px;border-radius:4px;font-size:0.85em;">{display}</span>'


def render_metric_card(label: str, value: Any, icon: str = "", delta: str = None, color: str = None):
    """Render a metric card with optional delta"""
    st.metric(
        label=f"{icon} {label}" if icon else label,
        value=value,
        delta=delta
    )


def create_excel_download(df: pd.DataFrame, filename: str = "export.xlsx") -> bytes:
    """Create Excel file from DataFrame"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
        
        # Auto-adjust column widths
        worksheet = writer.sheets['Data']
        for idx, col in enumerate(df.columns):
            max_length = max(
                df[col].astype(str).map(len).max(),
                len(str(col))
            ) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)
    
    return output.getvalue()


# ==================== Session State Helpers ====================

def init_session_state():
    """Initialize session state for Inventory Quality module"""
    defaults = {
        'iq_selected_row': None,
        'iq_show_detail_dialog': False,
        'iq_category_filter': 'All',
        'iq_warehouse_filter': None,
        'iq_product_search': '',
        'iq_data_loaded': False
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_selection():
    """Clear current selection"""
    st.session_state['iq_selected_row'] = None
    st.session_state['iq_show_detail_dialog'] = False


# ==================== Data Validation ====================

def safe_get(data: dict, key: str, default: Any = None) -> Any:
    """Safely get value from dictionary"""
    try:
        value = data.get(key, default)
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default