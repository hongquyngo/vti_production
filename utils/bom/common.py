# utils/bom/common.py
"""
Common utilities for BOM module
Formatting, UI helpers, and product queries
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Union
from io import BytesIO

import pandas as pd
import streamlit as st

from ..db import get_db_engine

logger = logging.getLogger(__name__)


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
        """Show confirmation dialog"""
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.warning(f"⚠️ {message}")
        with col2:
            confirm = st.button("✓ Confirm", key=f"{key}_yes", type="primary")
        with col3:
            cancel = st.button("✗ Cancel", key=f"{key}_no")
        
        return confirm and not cancel


def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        'DRAFT': '📝',
        'ACTIVE': '🟢',
        'INACTIVE': '⭕',
        'CONFIRMED': '✅',
        'PENDING': '⏳',
    }
    
    icon = status_icons.get(status.upper(), '⚪')
    return f"{icon} {status}"


# ==================== Excel Export ====================

def export_to_excel(dataframes: Union[pd.DataFrame, dict],
                   include_index: bool = False) -> bytes:
    """Export DataFrame(s) to Excel"""
    output = BytesIO()
    
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


# ==================== Product Queries ====================

def get_products(active_only: bool = True) -> pd.DataFrame:
    """Get products for BOM material selection"""
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
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return pd.DataFrame()