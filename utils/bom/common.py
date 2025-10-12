# utils/bom/common.py
"""
Common utilities for BOM module
Formatting, UI helpers, and product queries
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Optional, Dict, List, Any, Tuple
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
        'DRAFT': '🔵',
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
            p.is_service
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


# ==================== NEW: Dialog UI Helpers ====================

def render_material_selector(key: str, 
                             label: str = "Material",
                             default_index: int = 0) -> Optional[int]:
    """
    Render product/material selector dropdown
    
    Args:
        key: Unique key for widget
        label: Label for dropdown
        default_index: Default selection index
    
    Returns:
        Selected product ID or None
    """
    products = get_products()
    
    if products.empty:
        st.error("❌ No products found")
        return None
    
    product_options = {
        f"{row['name']} ({row['code']})": row['id']
        for _, row in products.iterrows()
    }
    
    selected = st.selectbox(
        label,
        options=list(product_options.keys()),
        index=default_index,
        key=key
    )
    
    return product_options.get(selected)


def render_material_table(materials: pd.DataFrame,
                          show_stock: bool = True,
                          editable: bool = False) -> pd.DataFrame:
    """
    Render materials table (read-only or editable)
    
    Args:
        materials: DataFrame with material data
        show_stock: Whether to show stock column
        editable: Whether table is editable
    
    Returns:
        DataFrame (modified if editable)
    """
    if materials.empty:
        st.info("ℹ️ No materials")
        return materials
    
    # Prepare display columns
    display_cols = ['material_name', 'material_code', 'material_type', 
                   'quantity', 'uom', 'scrap_rate']
    
    if show_stock and 'current_stock' in materials.columns:
        display_cols.append('current_stock')
    
    # Format display
    display_df = materials[display_cols].copy()
    
    # Show table
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )
    
    return materials


def render_material_add_form(key_prefix: str,
                             on_add_callback=None) -> Optional[Dict[str, Any]]:
    """
    Render add material inline form
    
    Args:
        key_prefix: Prefix for widget keys
        on_add_callback: Optional callback when material added
    
    Returns:
        Material data dict if added, None otherwise
    """
    col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
    
    with col1:
        material_id = render_material_selector(
            key=f"{key_prefix}_material",
            label="Material"
        )
    
    with col2:
        material_type = st.selectbox(
            "Type",
            ["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key=f"{key_prefix}_type"
        )
    
    with col3:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key=f"{key_prefix}_qty"
        )
    
    with col4:
        if material_id:
            product = get_product_by_id(material_id)
            uom = product['uom'] if product else 'PCS'
        else:
            uom = 'PCS'
        st.text_input("UOM", value=uom, disabled=True, key=f"{key_prefix}_uom")
    
    with col5:
        scrap_rate = st.number_input(
            "Scrap %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key=f"{key_prefix}_scrap"
        )
    
    if st.button("➕ Add", key=f"{key_prefix}_add_btn", use_container_width=True):
        if material_id:
            material_data = {
                'material_id': material_id,
                'material_type': material_type,
                'quantity': quantity,
                'uom': uom,
                'scrap_rate': scrap_rate
            }
            
            if on_add_callback:
                on_add_callback(material_data)
            
            return material_data
    
    return None


def show_toast(message: str, 
               toast_type: str = "success",
               icon: Optional[str] = None):
    """
    Show toast message
    
    Args:
        message: Message to display
        toast_type: Type (success, error, warning, info)
        icon: Optional custom icon
    """
    if icon:
        message = f"{icon} {message}"
    
    if toast_type == "success":
        st.success(message)
    elif toast_type == "error":
        st.error(message)
    elif toast_type == "warning":
        st.warning(message)
    else:
        st.info(message)


def render_confirmation_checkbox(key: str,
                                 label: str = "I understand the consequences") -> bool:
    """
    Render confirmation checkbox
    
    Args:
        key: Unique key for checkbox
        label: Checkbox label
    
    Returns:
        True if checked
    """
    return st.checkbox(label, key=key)


def render_action_buttons(actions: List[Dict[str, Any]],
                          columns: Optional[int] = None):
    """
    Render action buttons in columns
    
    Args:
        actions: List of action dicts with {label, key, callback, type}
        columns: Number of columns (default: len(actions))
    """
    if not actions:
        return
    
    if columns is None:
        columns = len(actions)
    
    cols = st.columns(columns)
    
    for idx, action in enumerate(actions):
        with cols[idx % columns]:
            button_type = action.get('type', 'secondary')
            
            if st.button(
                action['label'],
                key=action['key'],
                type=button_type,
                use_container_width=True
            ):
                if 'callback' in action:
                    action['callback']()


def render_step_indicator(current_step: int, total_steps: int):
    """
    Render step indicator for wizard
    
    Args:
        current_step: Current step number (1-based)
        total_steps: Total number of steps
    """
    steps = []
    for i in range(1, total_steps + 1):
        if i < current_step:
            steps.append(f"✅ Step {i}")
        elif i == current_step:
            steps.append(f"🔵 **Step {i}**")
        else:
            steps.append(f"⭕ Step {i}")
    
    st.markdown(" → ".join(steps))


def render_bom_summary(bom_info: Dict[str, Any]):
    """
    Render BOM information summary
    
    Args:
        bom_info: Dictionary with BOM information
    """
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Basic Info**")
        st.write(f"Code: {bom_info.get('bom_code', 'N/A')}")
        st.write(f"Name: {bom_info.get('bom_name', 'N/A')}")
        st.write(f"Type: {bom_info.get('bom_type', 'N/A')}")
    
    with col2:
        st.markdown("**Product**")
        st.write(f"Product: {bom_info.get('product_name', 'N/A')}")
        st.write(f"Output: {bom_info.get('output_qty', 0)} {bom_info.get('uom', 'PCS')}")
        status = bom_info.get('status', 'N/A')
        st.write(f"Status: {create_status_indicator(status)}")
    
    with col3:
        st.markdown("**Details**")
        st.write(f"Effective: {bom_info.get('effective_date', 'N/A')}")
        st.write(f"Version: {bom_info.get('version', 1)}")
        st.write(f"Materials: {bom_info.get('material_count', 0)}")


def format_material_for_display(material: Dict[str, Any]) -> str:
    """
    Format material info for display
    
    Args:
        material: Material dictionary
    
    Returns:
        Formatted string
    """
    name = material.get('material_name', 'Unknown')
    code = material.get('material_code', '')
    qty = material.get('quantity', 0)
    uom = material.get('uom', 'PCS')
    
    return f"{name} ({code}) - {qty} {uom}"


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