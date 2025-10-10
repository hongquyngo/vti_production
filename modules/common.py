# modules/common.py - Simplified Common Utilities
"""
Common Utility Functions Module
Provides essential utilities for manufacturing module.
"""

import logging
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Any, Union
from io import BytesIO

import pandas as pd
import streamlit as st
from sqlalchemy.exc import DatabaseError

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== Constants ====================

class SystemConstants:
    """System constants"""
    DEFAULT_PAGE_SIZE = 100
    EXPIRY_WARNING_DAYS = 30
    MAX_DECIMAL_PLACES = 4


# ==================== Database Queries ====================

@st.cache_data(ttl=300)
def get_products(active_only: bool = True) -> pd.DataFrame:
    """Get products with caching"""
    engine = get_db_engine()
    
    query = """
        SELECT 
            p.id,
            p.name,
            p.pt_code as code,
            p.uom,
            p.shelf_life,
            COALESCE(
                (SELECT SUM(ih.remain) 
                 FROM inventory_histories ih 
                 WHERE ih.product_id = p.id 
                   AND ih.remain > 0 
                   AND ih.delete_flag = 0), 
                0
            ) as total_stock
        FROM products p
        WHERE p.delete_flag = 0
    """
    
    if active_only:
        query += " AND p.approval_status = 1 AND p.is_service = 0"
    
    query += " ORDER BY p.name"
    
    try:
        return pd.read_sql(query, engine)
    except DatabaseError as e:
        logger.error(f"Error getting products: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_warehouses(active_only: bool = True) -> pd.DataFrame:
    """Get warehouses with caching"""
    engine = get_db_engine()
    
    query = """
        SELECT 
            w.id,
            w.name,
            w.warehouse_type,
            w.is_active
        FROM warehouses w
        WHERE w.delete_flag = 0
    """
    
    if active_only:
        query += " AND w.is_active = 1"
    
    query += " ORDER BY w.name"
    
    try:
        return pd.read_sql(query, engine)
    except DatabaseError as e:
        logger.error(f"Error getting warehouses: {e}")
        return pd.DataFrame()


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
        
        # Round to specified decimal places
        quantize_str = '0.' + '0' * decimal_places if decimal_places > 0 else '0'
        value = value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
        
        # Format with or without thousands separator
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
    
    # VND doesn't use decimal places
    decimal_places = 0 if currency == "VND" else 2
    formatted = format_number(value, decimal_places)
    
    if currency == "VND":
        return f"{formatted} ₫"
    elif currency == "USD":
        return f"${formatted}"
    else:
        return f"{formatted} {currency}"


# ==================== Date Functions ====================

def get_date_filter_presets() -> Dict[str, Tuple[date, date]]:
    """Get common date filter presets"""
    today = date.today()
    
    # First day of current month
    first_of_month = today.replace(day=1)
    
    # Last day of last month
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


def format_datetime(dt: Union[datetime, date, str, None],
                   format_string: str = "%Y-%m-%d") -> str:
    """Format datetime flexibly"""
    if pd.isna(dt) or dt is None:
        return "-"
    
    try:
        if isinstance(dt, str):
            dt = pd.to_datetime(dt)
        
        if isinstance(dt, date) and not isinstance(dt, datetime):
            dt = datetime.combine(dt, datetime.min.time())
        
        return dt.strftime(format_string)
    
    except Exception as e:
        logger.error(f"Error formatting datetime {dt}: {e}")
        return str(dt)


# ==================== Validation ====================

def validate_quantity(value: Any, min_value: float = 0,
                     max_value: Optional[float] = None) -> Tuple[bool, Optional[str]]:
    """Validate quantity input"""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return False, "Quantity cannot be empty"
    
    try:
        qty = float(value)
        
        if pd.isna(qty):
            return False, "Invalid quantity value"
        
        if qty < min_value:
            return False, f"Quantity must be at least {min_value}"
        
        if max_value is not None and qty > max_value:
            return False, f"Quantity cannot exceed {max_value}"
        
        return True, None
        
    except (ValueError, TypeError) as e:
        return False, f"Invalid quantity format"


# ==================== UI Helpers ====================

class UIHelpers:
    """Streamlit UI helper functions"""
    
    @staticmethod
    def show_message(message: str, type: str = "info", duration: Optional[int] = None):
        """Show message in Streamlit"""
        message_functions = {
            "success": st.success,
            "error": st.error,
            "warning": st.warning,
            "info": st.info
        }
        
        show_func = message_functions.get(type, st.info)
        placeholder = st.empty()
        show_func(message)
        
        if duration and duration > 0:
            import time
            time.sleep(duration)
            placeholder.empty()
    
    @staticmethod
    def confirm_action(message: str, key: str) -> bool:
        """Show confirmation dialog"""
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.warning(f"⚠️ {message}")
        with col2:
            confirm = st.button("✔ Confirm", key=f"{key}_yes", type="primary")
        with col3:
            cancel = st.button("✗ Cancel", key=f"{key}_no")
        
        return confirm and not cancel


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
        'URGENT': '🔴'
    }
    
    icon = status_icons.get(status.upper(), '⚪')
    return f"{icon} {status}"


def export_to_excel(dataframes: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
                   include_index: bool = False) -> bytes:
    """Export DataFrame(s) to Excel"""
    output = BytesIO()
    
    # Convert single DataFrame to dict
    if isinstance(dataframes, pd.DataFrame):
        dataframes = {"Sheet1": dataframes}
    
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            for sheet_name, df in dataframes.items():
                df.to_excel(writer, sheet_name=sheet_name, index=include_index)
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


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