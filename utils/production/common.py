# utils/production/common.py
"""
Common utilities for Production module
Formatting, validation, UI helpers, and date utilities
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union
from io import BytesIO

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)


# ==================== Constants ====================

class SystemConstants:
    """System constants"""
    DEFAULT_PAGE_SIZE = 100
    EXPIRY_WARNING_DAYS = 30
    MAX_SCRAP_RATE = 50.0
    QUANTITY_DECIMALS = 4
    CURRENCY_DECIMALS = 0  # VND


# ==================== Number Formatting ====================

def format_number(value: Union[int, float, Decimal, None],
                 decimal_places: int = 2,
                 use_thousands_separator: bool = True) -> str:
    """Format number with precision and separators"""
    if pd.isna(value) or value is None:
        return "0"
    
    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        
        quantize_str = '0.' + '0' * decimal_places if decimal_places > 0 else '0'
        value = value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
        
        if use_thousands_separator:
            return f"{value:,}"
        else:
            return str(value)
    
    except Exception as e:
        logger.error(f"Error formatting number {value}: {e}")
        return str(value)


def format_currency(value: Union[int, float, Decimal, None],
                   currency: str = "VND") -> str:
    """Format currency value"""
    if pd.isna(value) or value is None:
        value = 0
    
    decimal_places = 0 if currency == "VND" else 2
    formatted = format_number(value, decimal_places)
    
    if currency == "VND":
        return f"{formatted} ₫"
    elif currency == "USD":
        return f"${formatted}"
    else:
        return f"{formatted} {currency}"


def calculate_percentage(numerator: Union[int, float],
                        denominator: Union[int, float],
                        decimal_places: int = 1) -> float:
    """Calculate percentage safely"""
    if denominator == 0 or pd.isna(denominator) or pd.isna(numerator):
        return 0.0
    
    try:
        percentage = (float(numerator) / float(denominator)) * 100
        return round(percentage, decimal_places)
    except Exception as e:
        logger.error(f"Error calculating percentage: {e}")
        return 0.0


# ==================== Date Functions ====================

def get_date_filter_presets() -> Dict[str, Tuple[date, date]]:
    """Get common date filter presets"""
    today = date.today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    first_of_last_month = last_month_end.replace(day=1)
    
    return {
        "Today": (today, today),
        "Yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "This Week": (today - timedelta(days=today.weekday()), today),
        "Last Week": (today - timedelta(days=today.weekday() + 7), 
                     today - timedelta(days=today.weekday() + 1)),
        "This Month": (first_of_month, today),
        "Last Month": (first_of_last_month, last_month_end),
        "Last 7 Days": (today - timedelta(days=6), today),
        "Last 30 Days": (today - timedelta(days=29), today),
    }


# ==================== UI Helpers ====================

class UIHelpers:
    """Streamlit UI helper functions"""
    
    @staticmethod
    def show_message(message: str, type: str = "info"):
        """Show message in Streamlit"""
        message_functions = {
            "success": st.success,
            "error": st.error,
            "warning": st.warning,
            "info": st.info
        }
        
        show_func = message_functions.get(type, st.info)
        show_func(message)
    
    @staticmethod
    def confirm_action(message: str, key: str) -> bool:
        """
        Show confirmation dialog with proper Streamlit state handling
        Returns True only after user confirms
        """
        # Initialize confirmation state
        confirm_key = f"{key}_confirm_state"
        if confirm_key not in st.session_state:
            st.session_state[confirm_key] = False
        
        # If already confirmed, reset and return True
        if st.session_state[confirm_key]:
            st.session_state[confirm_key] = False
            return True
        
        # Show confirmation UI
        st.warning(f"⚠️ {message}")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✓ Confirm", key=f"{key}_yes", type="primary", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()
        
        with col2:
            if st.button("✗ Cancel", key=f"{key}_no", use_container_width=True):
                return False
        
        return False


def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        'DRAFT': '📝',
        'CONFIRMED': '✅',
        'IN_PROGRESS': '🔄',
        'COMPLETED': '✔️',
        'CANCELLED': '❌',
        'ACTIVE': '🟢',
        'INACTIVE': '⭕',
        'PENDING': '⏳',
        'ISSUED': '✅',
        'PARTIAL': '⚠️',
        'LOW': '🔵',
        'NORMAL': '🟡',
        'HIGH': '🟠',
        'URGENT': '🔴',
        'GOOD': '✅',
        'DAMAGED': '⚠️',
        'EXPIRED': '❌'
    }
    
    icon = status_icons.get(status.upper(), '⚪')
    return f"{icon} {status}"


# ==================== Excel Export ====================

def export_to_excel(dataframes: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
                   include_index: bool = False) -> bytes:
    """Export DataFrame(s) to Excel"""
    output = BytesIO()
    
    if isinstance(dataframes, pd.DataFrame):
        dataframes = {"Sheet1": dataframes}
    
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            for sheet_name, df in dataframes.items():
                # Sanitize sheet name (max 31 chars, no special chars)
                safe_name = sheet_name[:31].replace('[', '').replace(']', '')
                df.to_excel(writer, sheet_name=safe_name, index=include_index)
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


# ==================== Validation Helpers ====================

def validate_positive_number(value: Union[int, float], field_name: str) -> None:
    """Validate that a number is positive"""
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def validate_required_fields(data: Dict, required_fields: list) -> None:
    """Validate that required fields are present and not None"""
    missing = [field for field in required_fields 
               if field not in data or data[field] is None]
    
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")