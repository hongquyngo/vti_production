# utils/bom/common.py
"""
Common utilities for BOM module - ENHANCED VERSION
Formatting, UI helpers, and product queries with full product info
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Optional, Dict, Any
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


# ==================== Product Display Formatting ====================

def format_product_display(code: str, name: str, 
                          package_size: Optional[str] = None,
                          brand: Optional[str] = None,
                          max_name_length: int = 40) -> str:
    """
    Format product display string: code | name | package_size (brand)
    
    Args:
        code: Product code
        name: Product name
        package_size: Package size (optional)
        brand: Brand name (optional)
        max_name_length: Maximum length for product name before truncation
    
    Returns:
        Formatted string
    
    Examples:
        "PT-001 | Product ABC | 100g (Brand A)"
        "PT-002 | Product XYZ | 500ml"
        "PT-003 | Service Item (Brand C)"
        "PT-004 | Product Name"
    """
    # Truncate name if too long
    if len(name) > max_name_length:
        name = name[:max_name_length - 3] + "..."
    
    # Build format: code | name | package (brand)
    result = f"{code} | {name}"
    
    # Add package size and/or brand
    extra_parts = []
    
    if package_size and str(package_size).strip() and str(package_size).strip() != '-':
        extra_parts.append(str(package_size).strip())
    
    if brand and str(brand).strip() and str(brand).strip() != '-':
        if extra_parts:
            # Have package size, add brand in parentheses
            extra_parts[0] = f"{extra_parts[0]} ({str(brand).strip()})"
        else:
            # No package size, just brand in parentheses
            extra_parts.append(f"({str(brand).strip()})")
    
    if extra_parts:
        result += " | " + " ".join(extra_parts)
    
    return result


# ==================== Product Queries ====================

def get_products(active_only: bool = True, 
                exclude_services: bool = True) -> pd.DataFrame:
    """
    Get products for BOM material selection with full info
    
    Args:
        active_only: Only return approved/active products
        exclude_services: Exclude service items
    
    Returns:
        DataFrame of products with columns: id, name, code, uom, package_size, 
        brand, shelf_life, approval_status, is_service
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            p.id,
            p.name,
            p.pt_code as code,
            p.uom,
            p.package_size,
            b.brand_name as brand,
            p.shelf_life,
            p.approval_status,
            p.is_service
        FROM products p
        LEFT JOIN brands b ON p.brand_id = b.id
        WHERE p.delete_flag = 0
    """
    
    if active_only:
        query += " AND p.approval_status = 1"
    
    if exclude_services:
        query += " AND p.is_service = 0"
    
    query += " ORDER BY p.pt_code, p.name"
    
    try:
        return pd.read_sql(query, engine)
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return pd.DataFrame()


def get_product_by_id(product_id: int) -> Optional[dict]:
    """
    Get single product by ID with full info
    
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
            p.package_size,
            b.brand_name as brand,
            p.shelf_life,
            p.approval_status
        FROM products p
        LEFT JOIN brands b ON p.brand_id = b.id
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


# ==================== Dialog UI Helpers ====================

def render_material_selector(key: str, 
                             label: str = "Material",
                             default_index: int = 0) -> Optional[int]:
    """
    Render product/material selector dropdown with enhanced format
    Format: code | name | package_size (brand)
    
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
    
    # Build options with new format
    product_options = {}
    for _, row in products.iterrows():
        display_text = format_product_display(
            code=row['code'],
            name=row['name'],
            package_size=row.get('package_size'),
            brand=row.get('brand')
        )
        product_options[display_text] = row['id']
    
    selected = st.selectbox(
        label,
        options=list(product_options.keys()),
        index=default_index if default_index < len(product_options) else 0,
        key=key
    )
    
    return product_options.get(selected)


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


# ==================== Material Type Counter ====================

def count_materials_by_type(materials: list) -> Dict[str, int]:
    """
    Count materials by type
    
    Args:
        materials: List of material dictionaries with 'material_type' key
    
    Returns:
        Dictionary with counts: {'RAW_MATERIAL': n, 'PACKAGING': n, 'CONSUMABLE': n}
    """
    counts = {
        'RAW_MATERIAL': 0,
        'PACKAGING': 0,
        'CONSUMABLE': 0
    }
    
    for material in materials:
        mat_type = material.get('material_type', 'RAW_MATERIAL')
        if mat_type in counts:
            counts[mat_type] += 1
    
    return counts


def render_material_type_counter(materials: list, show_warning: bool = True):
    """
    Render material type counter with validation
    
    Args:
        materials: List of materials
        show_warning: Show warning if no RAW_MATERIAL
    """
    counts = count_materials_by_type(materials)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        raw_count = counts['RAW_MATERIAL']
        if raw_count > 0:
            st.success(f"🟢 RAW: {raw_count}")
        else:
            st.warning(f"⚠️ RAW: {raw_count}")
    
    with col2:
        st.info(f"📦 PKG: {counts['PACKAGING']}")
    
    with col3:
        st.info(f"🔧 CONS: {counts['CONSUMABLE']}")
    
    # Show validation warning
    if show_warning and counts['RAW_MATERIAL'] == 0:
        st.warning("⚠️ **At least 1 RAW_MATERIAL is required to create BOM**")


def validate_materials_for_bom(materials: list) -> tuple[bool, str]:
    """
    Validate materials list for BOM creation
    
    Args:
        materials: List of materials
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not materials:
        return False, "At least one material is required"
    
    counts = count_materials_by_type(materials)
    
    if counts['RAW_MATERIAL'] == 0:
        return False, "At least one RAW_MATERIAL is required"
    
    return True, ""


# ==================== Constants ====================

STATUS_WORKFLOW = {
    'DRAFT': ['ACTIVE', 'INACTIVE'],
    'ACTIVE': ['INACTIVE'],
    'INACTIVE': ['ACTIVE']
}