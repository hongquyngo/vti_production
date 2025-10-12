# utils/bom/common.py
"""
Common utilities for BOM module
Formatting, UI helpers, and product queries
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Optional
from io import BytesIO

import pandas as pd
import streamlit as st

from ..db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== Number Formatting ====================

def format_number(value: Union[int, float, Decimal, None],
                 decimal_places: int = 2,
                 use_thousands_separator: bool = True) -> str:
    """
    Format number with precision and separators
    
    Args:
        value: Number to format
        decimal_places: Number of decimal places
        use_thousands_separator: Use comma separator
    
    Returns:
        Formatted string
    """
    if pd.isna(value) or value is None:
        return "0"
    
    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        
        # Round to specified decimal places
        quantize_str = '0.' + '0' * decimal_places if decimal_places > 0 else '0'
        value = value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
        
        if use_thousands_separator:
            return f"{value:,}"
        else:
            return str(value)
    
    except Exception as e:
        logger.error(f"Error formatting number {value}: {e}")
        return str(value)


def format_percentage(value: Union[int, float, None], 
                      decimal_places: int = 2) -> str:
    """Format value as percentage"""
    if pd.isna(value) or value is None:
        return "0%"
    
    try:
        formatted = format_number(value, decimal_places, False)
        return f"{formatted}%"
    except Exception as e:
        logger.error(f"Error formatting percentage {value}: {e}")
        return f"{value}%"


# ==================== Status Indicators ====================

def create_status_indicator(status: str) -> str:
    """
    Create status indicator with emoji
    
    Args:
        status: Status string
    
    Returns:
        Status with emoji
    """
    status_icons = {
        'DRAFT': '📝',
        'ACTIVE': '🟢',
        'INACTIVE': '⭕',
        'CONFIRMED': '✅',
        'PENDING': '⏳',
        'IN_PROGRESS': '🔄',
        'COMPLETED': '✔️',
        'CANCELLED': '❌',
        'PASSED': '✅',
        'FAILED': '❌',
    }
    
    icon = status_icons.get(status.upper(), '⚪')
    return f"{icon} {status}"


def get_status_color(status: str) -> str:
    """
    Get color for status
    
    Args:
        status: Status string
    
    Returns:
        Color name or hex
    """
    status_colors = {
        'DRAFT': 'gray',
        'ACTIVE': 'green',
        'INACTIVE': 'red',
        'CONFIRMED': 'green',
        'PENDING': 'orange',
        'IN_PROGRESS': 'blue',
        'COMPLETED': 'green',
        'CANCELLED': 'red',
    }
    
    return status_colors.get(status.upper(), 'gray')


# ==================== UI Helper Class ====================

class UIHelpers:
    """Streamlit UI helper functions"""
    
    @staticmethod
    def show_message(message: str, type: str = "info", icon: Optional[str] = None):
        """
        Show message in Streamlit
        
        Args:
            message: Message text
            type: Message type (success, error, warning, info)
            icon: Optional icon
        """
        message_functions = {
            "success": st.success,
            "error": st.error,
            "warning": st.warning,
            "info": st.info
        }
        
        show_func = message_functions.get(type, st.info)
        
        if icon:
            message = f"{icon} {message}"
        
        show_func(message)
    
    @staticmethod
    def confirm_action(message: str, key: str) -> bool:
        """
        Show confirmation dialog
        
        Args:
            message: Confirmation message
            key: Unique key for buttons
        
        Returns:
            True if confirmed
        """
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            st.warning(f"⚠️ {message}")
        
        with col2:
            confirm = st.button(
                "✓ Confirm", 
                key=f"{key}_yes", 
                type="primary",
                use_container_width=True
            )
        
        with col3:
            cancel = st.button(
                "✗ Cancel", 
                key=f"{key}_no",
                use_container_width=True
            )
        
        return confirm and not cancel
    
    @staticmethod
    def show_loading(message: str = "Processing..."):
        """Show loading spinner"""
        return st.spinner(message)
    
    @staticmethod
    def show_success_animation():
        """Show success animation"""
        st.balloons()
    
    @staticmethod
    def create_info_box(title: str, items: dict):
        """
        Create info box with key-value pairs
        
        Args:
            title: Box title
            items: Dict of label: value pairs
        """
        with st.container():
            st.markdown(f"**{title}**")
            
            for label, value in items.items():
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.text(f"{label}:")
                with col2:
                    st.text(str(value))
    
    @staticmethod
    def create_metric_cards(metrics: dict, columns: int = 4):
        """
        Create metric cards in columns
        
        Args:
            metrics: Dict of label: value pairs
            columns: Number of columns
        """
        cols = st.columns(columns)
        
        for idx, (label, value) in enumerate(metrics.items()):
            with cols[idx % columns]:
                st.metric(label, value)
    
    @staticmethod
    def show_error_details(error: Exception, show_traceback: bool = False):
        """
        Show error details with expandable section
        
        Args:
            error: Exception object
            show_traceback: Whether to show full traceback
        """
        st.error(f"❌ **Error:** {str(error)}")
        
        if show_traceback:
            import traceback
            with st.expander("🔍 Error Details"):
                st.code(traceback.format_exc())


# ==================== Excel Export ====================

def export_to_excel(dataframes: Union[pd.DataFrame, dict],
                   include_index: bool = False,
                   sheet_name: str = "Sheet1") -> bytes:
    """
    Export DataFrame(s) to Excel
    
    Args:
        dataframes: Single DataFrame or dict of {sheet_name: DataFrame}
        include_index: Whether to include DataFrame index
        sheet_name: Sheet name for single DataFrame
    
    Returns:
        Excel file as bytes
    """
    output = BytesIO()
    
    # Convert single DataFrame to dict
    if isinstance(dataframes, pd.DataFrame):
        dataframes = {sheet_name: dataframes}
    
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            for name, df in dataframes.items():
                # Clean sheet name (Excel has restrictions)
                clean_name = name[:31]  # Max 31 chars
                clean_name = clean_name.replace('/', '-').replace('\\', '-')
                
                df.to_excel(
                    writer, 
                    sheet_name=clean_name, 
                    index=include_index
                )
                
                # Auto-adjust column width
                worksheet = writer.sheets[clean_name]
                for idx, col in enumerate(df.columns):
                    max_len = max(
                        df[col].astype(str).str.len().max(),
                        len(str(col))
                    )
                    worksheet.set_column(idx, idx, min(max_len + 2, 50))
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


def create_download_button(data: bytes, 
                           filename: str, 
                           label: str = "📥 Download",
                           mime: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
    """
    Create download button for file
    
    Args:
        data: File data as bytes
        filename: Download filename
        label: Button label
        mime: MIME type
    """
    st.download_button(
        label=label,
        data=data,
        file_name=filename,
        mime=mime,
        use_container_width=True
    )


# ==================== Product Queries ====================

def get_products(active_only: bool = True, 
                exclude_services: bool = True) -> pd.DataFrame:
    """
    Get products for BOM material selection
    
    Args:
        active_only: Only return approved/active products
        exclude_services: Exclude service items
    
    Returns:
        DataFrame of products
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            p.id,
            p.name,
            p.pt_code as code,
            p.uom,
            p.shelf_life,
            p.approval_status,
            p.is_service,
            COALESCE(
                (SELECT SUM(ih.remain) 
                 FROM inventory_histories ih 
                 WHERE ih.product_id = p.id 
                   AND ih.remain > 0 
                   AND ih.delete_flag = 0), 
                0
            ) as total_stock,
            COALESCE(
                (SELECT ih.landed_cost 
                 FROM inventory_histories ih 
                 WHERE ih.product_id = p.id 
                   AND ih.delete_flag = 0 
                 ORDER BY ih.created_date DESC 
                 LIMIT 1), 
                0
            ) as latest_cost
        FROM products p
        WHERE p.delete_flag = 0
    """
    
    if active_only:
        query += " AND p.approval_status = 1"
    
    if exclude_services:
        query += " AND p.is_service = 0"
    
    query += " ORDER BY p.name"
    
    try:
        return pd.read_sql(query, engine)
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return pd.DataFrame()


def get_product_by_id(product_id: int) -> Optional[dict]:
    """
    Get single product by ID
    
    Args:
        product_id: Product ID
    
    Returns:
        Product dict or None
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            p.id,
            p.name,
            p.pt_code as code,
            p.uom,
            p.shelf_life,
            p.approval_status
        FROM products p
        WHERE p.id = %s AND p.delete_flag = 0
    """
    
    try:
        result = pd.read_sql(query, engine, params=(product_id,))
        if not result.empty:
            return result.iloc[0].to_dict()
        return None
    except Exception as e:
        logger.error(f"Error getting product {product_id}: {e}")
        return None


def search_products(search_term: str, limit: int = 50) -> pd.DataFrame:
    """
    Search products by code or name
    
    Args:
        search_term: Search string
        limit: Maximum results
    
    Returns:
        DataFrame of matching products
    """
    engine = get_db_engine()
    
    query = f"""
        SELECT 
            p.id,
            p.name,
            p.pt_code as code,
            p.uom
        FROM products p
        WHERE p.delete_flag = 0
          AND p.approval_status = 1
          AND (
              p.name LIKE %s 
              OR p.pt_code LIKE %s
          )
        ORDER BY p.name
        LIMIT {limit}
    """
    
    try:
        search_pattern = f"%{search_term}%"
        return pd.read_sql(query, engine, params=(search_pattern, search_pattern))
    except Exception as e:
        logger.error(f"Error searching products: {e}")
        return pd.DataFrame()


# ==================== Validation Helpers ====================

def validate_quantity(qty: float, min_val: float = 0.0001) -> bool:
    """Validate quantity is positive"""
    try:
        return float(qty) >= min_val
    except (ValueError, TypeError):
        return False


def validate_percentage(value: float) -> bool:
    """Validate percentage is between 0-100"""
    try:
        val = float(value)
        return 0 <= val <= 100
    except (ValueError, TypeError):
        return False


def validate_date_range(start_date, end_date) -> bool:
    """Validate date range"""
    try:
        return start_date <= end_date
    except (TypeError, AttributeError):
        return False


# ==================== Data Transformation ====================

def prepare_display_dataframe(df: pd.DataFrame, 
                             format_columns: dict = None) -> pd.DataFrame:
    """
    Prepare DataFrame for display
    
    Args:
        df: Input DataFrame
        format_columns: Dict of {column: formatter_function}
    
    Returns:
        Formatted DataFrame
    """
    display_df = df.copy()
    
    if format_columns:
        for col, formatter in format_columns.items():
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(formatter)
    
    return display_df


def clean_dataframe_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean DataFrame for export
    
    Args:
        df: Input DataFrame
    
    Returns:
        Cleaned DataFrame
    """
    export_df = df.copy()
    
    # Remove internal columns
    internal_cols = ['id', 'delete_flag', 'created_by', 'updated_by']
    export_df = export_df.drop(columns=internal_cols, errors='ignore')
    
    # Clean column names
    export_df.columns = [col.replace('_', ' ').title() for col in export_df.columns]
    
    return export_df


# ==================== Cache Decorators ====================

def cache_product_data(ttl: int = 300):
    """Cache decorator for product data (5 min default)"""
    def decorator(func):
        return st.cache_data(ttl=ttl)(func)
    return decorator


def cache_resource_data(func):
    """Cache decorator for resource data"""
    return st.cache_resource(func)


# ==================== Constants ====================

BOM_TYPES = ['KITTING', 'CUTTING', 'REPACKING']
BOM_STATUSES = ['DRAFT', 'ACTIVE', 'INACTIVE']
MATERIAL_TYPES = ['RAW_MATERIAL', 'PACKAGING', 'CONSUMABLE']

STATUS_WORKFLOW = {
    'DRAFT': ['ACTIVE', 'INACTIVE'],
    'ACTIVE': ['INACTIVE'],
    'INACTIVE': ['ACTIVE']
}


# ==================== Logging Helper ====================

def log_user_action(action: str, entity: str, entity_id: int, 
                   user_id: int, details: Optional[str] = None):
    """
    Log user action for audit trail
    
    Args:
        action: Action type (CREATE, UPDATE, DELETE, etc.)
        entity: Entity type (BOM, MATERIAL, etc.)
        entity_id: Entity ID
        user_id: User ID
        details: Additional details
    """
    log_message = f"User {user_id} {action} {entity} {entity_id}"
    if details:
        log_message += f" - {details}"
    
    logger.info(log_message)