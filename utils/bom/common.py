# utils/bom/common.py
"""
Common utilities for BOM module - ENHANCED VERSION v2.0
Formatting, UI helpers, product queries, and Edit Level system

Changes in v2.0:
- Added Edit Level constants and get_edit_level() function
- Updated STATUS_WORKFLOW to support ACTIVE/INACTIVE → DRAFT
- Added validation helpers for status transitions
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Optional, Dict, Any, Tuple
from io import BytesIO

import pandas as pd
import streamlit as st

from ..db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== Edit Level Constants ====================

class EditLevel:
    """
    Edit permission levels for BOM based on status and usage
    
    Level 0: READ_ONLY - No edits allowed (has completed orders or inactive with history)
    Level 1: METADATA_ONLY - Name, notes, effective_date only (reserved for future use)
    Level 2: ALTERNATIVES_PLUS - Alternatives + metadata (has IN_PROGRESS orders)
    Level 4: FULL_EDIT - Everything editable (DRAFT or no usage)
    """
    READ_ONLY = 0
    METADATA_ONLY = 1
    ALTERNATIVES_PLUS = 2
    FULL_EDIT = 4
    
    LABELS = {
        0: "Read Only",
        1: "Metadata Only",
        2: "Alternatives + Metadata",
        4: "Full Edit"
    }
    
    ICONS = {
        0: "🔒",
        1: "📝",
        2: "🔀",
        4: "✏️"
    }


def get_edit_level(bom_info: Dict[str, Any]) -> int:
    """
    Determine edit level based on BOM status and usage context
    
    Business Rules:
    - DRAFT: Always full edit
    - ACTIVE with no usage: Full edit (never been used)
    - ACTIVE with IN_PROGRESS orders: Alternatives only (don't break running production)
    - ACTIVE with only COMPLETED orders: Read only (create new BOM instead)
    - INACTIVE with no usage: Full edit (can be edited freely)
    - INACTIVE with usage history: Read only (historical data, create new BOM)
    
    Args:
        bom_info: Dictionary containing status, active_orders, total_usage
        
    Returns:
        EditLevel constant (0, 1, 2, or 4)
    """
    status = bom_info.get('status', 'DRAFT')
    active_orders = int(bom_info.get('active_orders', 0))  # IN_PROGRESS orders
    total_usage = int(bom_info.get('total_usage', 0))      # All MOs ever created
    
    if status == 'DRAFT':
        return EditLevel.FULL_EDIT
    
    if status == 'ACTIVE':
        if total_usage == 0:
            # Never used - safe to fully edit
            return EditLevel.FULL_EDIT
        elif active_orders > 0:
            # Has running orders - only allow alternatives changes
            return EditLevel.ALTERNATIVES_PLUS
        else:
            # Has completed orders but no active - read only, create new BOM
            return EditLevel.READ_ONLY
    
    if status == 'INACTIVE':
        if total_usage == 0:
            # Never used - safe to fully edit
            return EditLevel.FULL_EDIT
        else:
            # Has usage history - read only for audit trail
            return EditLevel.READ_ONLY
    
    # Default fallback
    return EditLevel.READ_ONLY


def get_edit_level_description(level: int, bom_info: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Get human-readable description for edit level
    
    Args:
        level: EditLevel constant
        bom_info: BOM information dict
        
    Returns:
        Tuple of (title, description, help_text)
    """
    status = bom_info.get('status', 'DRAFT')
    active_orders = int(bom_info.get('active_orders', 0))
    total_usage = int(bom_info.get('total_usage', 0))
    completed_orders = total_usage - active_orders
    
    if level == EditLevel.FULL_EDIT:
        return (
            "✏️ Full Edit Mode",
            "You can modify all BOM information including header, materials, and alternatives.",
            "All changes will be saved immediately."
        )
    
    if level == EditLevel.ALTERNATIVES_PLUS:
        return (
            "🔀 Limited Edit Mode - Alternatives Only",
            f"BOM has {active_orders} active manufacturing order(s) in progress. "
            "Only alternatives and metadata can be modified to avoid disrupting production.",
            "💡 Complete or cancel active orders to enable full editing, or clone this BOM for modifications."
        )
    
    if level == EditLevel.METADATA_ONLY:
        return (
            "📝 Metadata Only Mode",
            "Only BOM name, notes, and effective date can be modified.",
            "💡 Clone this BOM if you need to make structural changes."
        )
    
    # READ_ONLY
    if status == 'ACTIVE' and completed_orders > 0:
        return (
            "🔒 Read Only - Has Completed Orders",
            f"BOM has been used in {completed_orders} completed manufacturing order(s). "
            "Editing is disabled to preserve production history and audit trail.",
            "💡 Use 'Clone' to create a new BOM based on this one if you need modifications."
        )
    
    if status == 'INACTIVE' and total_usage > 0:
        return (
            "🔒 Read Only - Historical BOM",
            f"This inactive BOM has been used in {total_usage} manufacturing order(s). "
            "Editing is disabled to preserve historical data.",
            "💡 Use 'Clone' to create a new BOM, or change status to ACTIVE first."
        )
    
    return (
        "🔒 Read Only",
        "This BOM cannot be edited in its current state.",
        "💡 Check BOM status and usage to determine available actions."
    )


def can_edit_field(level: int, field_type: str) -> bool:
    """
    Check if a specific field type can be edited at given level
    
    Args:
        level: EditLevel constant
        field_type: One of 'header', 'materials', 'alternatives', 'metadata'
        
    Returns:
        True if field can be edited
    """
    if level == EditLevel.FULL_EDIT:
        return True
    
    if level == EditLevel.ALTERNATIVES_PLUS:
        return field_type in ('alternatives', 'metadata')
    
    if level == EditLevel.METADATA_ONLY:
        return field_type == 'metadata'
    
    return False


# ==================== Status Workflow ====================

# Updated workflow to support returning to DRAFT
STATUS_WORKFLOW = {
    'DRAFT': ['ACTIVE', 'INACTIVE'],
    'ACTIVE': ['INACTIVE', 'DRAFT'],   # Added DRAFT transition
    'INACTIVE': ['ACTIVE', 'DRAFT']    # Added DRAFT transition
}


def get_allowed_status_transitions(bom_info: Dict[str, Any]) -> Dict[str, Tuple[bool, str]]:
    """
    Get allowed status transitions with validation
    
    Args:
        bom_info: BOM information dict
        
    Returns:
        Dict of {new_status: (is_allowed, reason)}
    """
    current_status = bom_info.get('status', 'DRAFT')
    active_orders = int(bom_info.get('active_orders', 0))
    total_usage = int(bom_info.get('total_usage', 0))
    material_count = int(bom_info.get('material_count', 0))
    
    possible_statuses = STATUS_WORKFLOW.get(current_status, [])
    result = {}
    
    for new_status in possible_statuses:
        if new_status == 'ACTIVE':
            # Activation requirements
            if material_count == 0:
                result[new_status] = (False, "Cannot activate BOM without materials")
            elif bom_info.get('output_qty', 0) <= 0:
                result[new_status] = (False, "Output quantity must be greater than 0")
            else:
                result[new_status] = (True, "BOM can be activated")
        
        elif new_status == 'INACTIVE':
            # Deactivation requirements
            if active_orders > 0:
                result[new_status] = (False, f"Cannot deactivate - {active_orders} active order(s) in progress")
            else:
                result[new_status] = (True, "BOM can be deactivated")
        
        elif new_status == 'DRAFT':
            # Return to DRAFT requirements - only if never used
            if total_usage > 0:
                result[new_status] = (False, f"Cannot return to DRAFT - BOM has been used in {total_usage} order(s)")
            else:
                result[new_status] = (True, "BOM can be returned to DRAFT for full editing")
    
    return result


def validate_status_transition(current_status: str, new_status: str, 
                                bom_info: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate if a status transition is allowed
    
    Args:
        current_status: Current BOM status
        new_status: Target status
        bom_info: BOM information dict
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if current_status == new_status:
        return False, "New status must be different from current status"
    
    allowed = STATUS_WORKFLOW.get(current_status, [])
    if new_status not in allowed:
        return False, f"Cannot transition from {current_status} to {new_status}"
    
    transitions = get_allowed_status_transitions(bom_info)
    if new_status in transitions:
        is_allowed, reason = transitions[new_status]
        if not is_allowed:
            return False, reason
    
    return True, ""


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

# ==================== Internal Companies Query ====================
# Add this section to utils/bom/common.py after the Product Queries section

def get_internal_companies() -> pd.DataFrame:
    """
    Get list of internal companies for BOM export selection
    
    Internal companies are identified by company_type.name = 'Internal'
    
    Returns:
        DataFrame with columns: id, english_name, local_name, company_code, address, registration_code, logo_path
    """
    engine = get_db_engine()
    
    query = """
        SELECT DISTINCT
            c.id,
            c.english_name,
            c.local_name,
            c.company_code,
            c.street as address,
            c.registration_code,
            m.path as logo_path
        FROM companies c
        JOIN companies_company_types cct ON c.id = cct.companies_id
        JOIN company_types ct ON cct.company_type_id = ct.id
        LEFT JOIN medias m ON c.logo_id = m.id
        WHERE ct.name = 'Internal'
        AND c.delete_flag = 0
        ORDER BY c.english_name
    """
    
    try:
        return pd.read_sql(query, engine)
    except Exception as e:
        logger.error(f"Error getting internal companies: {e}")
        return pd.DataFrame()


def format_company_display(english_name: str, 
                          local_name: Optional[str] = None,
                          company_code: Optional[str] = None) -> str:
    """
    Format company display string for dropdown
    
    Args:
        english_name: Company English name
        local_name: Company local name (Vietnamese)
        company_code: Company code
    
    Returns:
        Formatted string like: "PROSTECH ASIA (PTA) - CÔNG TY TNHH PROSTECH"
    
    Examples:
        "PROSTECH ASIA (PTA) - CÔNG TY TNHH PROSTECH VIỆT NAM"
        "ABC COMPANY (ABC)"
    """
    result = english_name
    
    if company_code and str(company_code).strip():
        result += f" ({company_code})"
    
    if local_name and str(local_name).strip():
        result += f" - {local_name}"
    
    return result


@st.cache_data(ttl=300)
def get_internal_companies_cached() -> pd.DataFrame:
    """Cached version of get_internal_companies for UI performance"""
    return get_internal_companies()

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


def render_edit_level_indicator(level: int, bom_info: Dict[str, Any]):
    """
    Render edit level indicator with description
    
    Args:
        level: EditLevel constant
        bom_info: BOM information dict
    """
    title, description, help_text = get_edit_level_description(level, bom_info)
    
    if level == EditLevel.FULL_EDIT:
        st.info(f"**{title}**\n\n{description}")
    elif level == EditLevel.ALTERNATIVES_PLUS:
        st.warning(f"**{title}**\n\n{description}")
        st.caption(help_text)
    elif level == EditLevel.METADATA_ONLY:
        st.warning(f"**{title}**\n\n{description}")
        st.caption(help_text)
    else:  # READ_ONLY
        st.error(f"**{title}**\n\n{description}")
        st.caption(help_text)


def render_usage_context(bom_info: Dict[str, Any]):
    """
    Render BOM usage context metrics
    
    Args:
        bom_info: BOM information dict
    """
    total_usage = int(bom_info.get('total_usage', 0))
    active_orders = int(bom_info.get('active_orders', 0))
    completed_orders = total_usage - active_orders
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if active_orders > 0:
            st.metric("🔄 Active Orders", active_orders, help="Manufacturing orders in progress")
        else:
            st.metric("🔄 Active Orders", 0)
    
    with col2:
        if completed_orders > 0:
            st.metric("✅ Completed Orders", completed_orders, help="Finished manufacturing orders")
        else:
            st.metric("✅ Completed Orders", 0)
    
    with col3:
        st.metric("📊 Total Usage", total_usage, help="All manufacturing orders using this BOM")


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


def validate_materials_for_bom(materials: list) -> Tuple[bool, str]:
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

# ==================== BOM Material Duplicate Validation ====================

def get_all_material_ids_in_bom_list(materials: list) -> set:
    """
    Get all material IDs used in BOM materials list (for Create wizard)
    Includes both primary materials and their alternatives
    
    Args:
        materials: List of material dicts with structure:
            {
                'material_id': int,
                'alternatives': [{'alternative_material_id': int}, ...]
            }
    
    Returns:
        Set of all material IDs used in the BOM
    """
    used_ids = set()
    
    for mat in materials:
        # Add primary material ID
        mat_id = mat.get('material_id')
        if mat_id:
            used_ids.add(int(mat_id))
        
        # Add alternative material IDs
        alternatives = mat.get('alternatives', [])
        for alt in alternatives:
            alt_id = alt.get('alternative_material_id') or alt.get('material_id')
            if alt_id:
                used_ids.add(int(alt_id))
    
    return used_ids


def get_all_material_ids_in_bom_db(bom_id: int) -> set:
    """
    Get all material IDs used in existing BOM from database (for Edit dialog)
    Includes both primary materials and their alternatives
    
    Args:
        bom_id: BOM header ID
    
    Returns:
        Set of all material IDs used in the BOM
    """
    try:
        engine = get_db_engine()
        
        # Query all primary materials
        primary_query = """
            SELECT DISTINCT material_id 
            FROM bom_details 
            WHERE bom_header_id = %s
        """
        
        # Query all alternative materials
        alternatives_query = """
            SELECT DISTINCT a.alternative_material_id
            FROM bom_material_alternatives a
            JOIN bom_details d ON a.bom_detail_id = d.id
            WHERE d.bom_header_id = %s
        """
        
        primary_df = pd.read_sql(primary_query, engine, params=(bom_id,))
        alt_df = pd.read_sql(alternatives_query, engine, params=(bom_id,))
        
        used_ids = set()
        
        if not primary_df.empty:
            used_ids.update(primary_df['material_id'].astype(int).tolist())
        
        if not alt_df.empty:
            used_ids.update(alt_df['alternative_material_id'].astype(int).tolist())
        
        return used_ids
    
    except Exception as e:
        logger.error(f"Error getting material IDs from BOM: {e}")
        return set()


def validate_material_not_duplicate(material_id: int, 
                                     used_ids: set, 
                                     material_name: str = None) -> Tuple[bool, str]:
    """
    Validate that a material is not already used in BOM
    
    Args:
        material_id: Material ID to check
        used_ids: Set of already used material IDs
        material_name: Optional material name for error message
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if int(material_id) in used_ids:
        if material_name:
            return False, f"Material '{material_name}' is already used in this BOM (as primary or alternative)"
        return False, "This material is already used in this BOM (as primary or alternative)"
    
    return True, ""


def filter_available_materials(products: pd.DataFrame, 
                               used_ids: set,
                               exclude_id: int = None) -> Dict:
    """
    Filter products to exclude already used materials in BOM
    Returns product options dict for selectbox
    
    Args:
        products: DataFrame of all products
        used_ids: Set of material IDs already used in BOM
        exclude_id: Optional single ID to also exclude (e.g., current primary material)
    
    Returns:
        Dict of {display_text: {'id': int, 'uom': str, 'code': str, 'name': str}}
    """
    product_options = {}
    
    for _, row in products.iterrows():
        mat_id = int(row['id'])
        
        # Skip if already used in BOM
        if mat_id in used_ids:
            continue
        
        # Skip if explicitly excluded
        if exclude_id and mat_id == exclude_id:
            continue
        
        display_text = format_product_display(
            code=row['code'],
            name=row['name'],
            package_size=row.get('package_size'),
            brand=row.get('brand')
        )
        product_options[display_text] = {
            'id': mat_id,
            'uom': row['uom'],
            'code': row['code'],
            'name': row['name']
        }
    
    return product_options