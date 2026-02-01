# utils/bom/common.py
"""
Common utilities for BOM module - ENHANCED VERSION v2.4
Formatting, UI helpers, product queries, Edit Level system, and Active BOM Conflict Detection

Changes in v2.4:
- Added Output Product vs Materials Validation (circular dependency prevention)
- validate_output_not_in_materials(): Check output product not in materials list
- validate_material_not_output_product(): Validate single material addition
- filter_available_materials_excluding_output(): Filter with output product exclusion
- check_materials_conflict_with_new_output(): Check conflict when changing output product
- render_output_material_conflict_warning(): UI component for conflict display

Changes in v2.3:
- Added Active BOM Conflict Detection functions for Phase 1 & 2
- get_active_boms_for_product(): Find active BOMs for a product
- get_products_with_multiple_active_boms(): Dashboard conflict detection
- get_boms_with_active_conflict_check(): Efficient batch check for BOM list badges
- check_active_bom_conflict(): Pre-activation conflict check
- render_active_bom_conflict_warning(): UI component for conflict resolution

Changes in v2.2:
- Changed legacy code display from "N/A" to "NEW" for products without legacy code
- Format: code (legacy|NEW) | name | pkg (brand)

Changes in v2.1:
- Updated format_product_display() to include legacy_code
- New format: code (legacy_code | N/A) | name | pkg (brand)
- Added legacy_pt_code to product queries (get_products, get_product_by_id)

Changes in v2.0:
- Added Edit Level constants and get_edit_level() function
- Updated STATUS_WORKFLOW to support ACTIVE/INACTIVE → DRAFT
- Added validation helpers for status transitions
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Optional, Dict, Any, Tuple, List
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
                          legacy_code: Optional[str] = None,
                          max_name_length: int = 40) -> str:
    """
    Format product display string: code (legacy_code) | name | package_size (brand)
    
    Args:
        code: Product code (pt_code)
        name: Product name
        package_size: Package size (optional)
        brand: Brand name (optional)
        legacy_code: Legacy product code (optional), shows NEW if not provided
        max_name_length: Maximum length for product name before truncation
    
    Returns:
        Formatted string
    
    Examples:
        "PT-001 (OLD-001) | Product ABC | 100g (Brand A)"
        "PT-002 (NEW) | Product XYZ | 500ml"
        "PT-003 (NEW) | Service Item (Brand C)"
        "PT-004 (OLD-004) | Product Name"
    """
    # Truncate name if too long
    if name and len(name) > max_name_length:
        name = name[:max_name_length - 3] + "..."
    
    # Format legacy code - show NEW if not available
    legacy_display = "NEW"
    if legacy_code and str(legacy_code).strip() and str(legacy_code).strip() != '-':
        legacy_display = str(legacy_code).strip()
    
    # Build format: code (legacy) | name | package (brand)
    result = f"{code} ({legacy_display}) | {name}"
    
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
        brand, shelf_life, approval_status, is_service, legacy_code
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            p.id,
            p.name,
            p.pt_code as code,
            p.legacy_pt_code as legacy_code,
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
            p.legacy_pt_code as legacy_code,
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
            brand=row.get('brand'),
            legacy_code=row.get('legacy_code')
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
            brand=row.get('brand'),
            legacy_code=row.get('legacy_code')
        )
        product_options[display_text] = {
            'id': mat_id,
            'uom': row['uom'],
            'code': row['code'],
            'name': row['name'],
            'legacy_code': row.get('legacy_code')
        }
    
    return product_options


# ==================== Output Product vs Materials Validation ====================
# Circular dependency prevention: Output product cannot be used as input material

def validate_output_not_in_materials(output_product_id: int, materials: list) -> Tuple[bool, str, List[str]]:
    """
    Validate that output product is not used as any input material (primary or alternative)
    
    Business Rule: A BOM's output product cannot be one of its input materials
    (prevents circular dependency / self-referencing)
    
    Args:
        output_product_id: The output product ID of the BOM
        materials: List of material dicts with structure:
            {
                'material_id': int,
                'alternatives': [{'alternative_material_id': int}, ...]
            }
    
    Returns:
        Tuple of (is_valid, error_message, conflicting_positions)
    """
    if not output_product_id or not materials:
        return True, "", []
    
    output_product_id = int(output_product_id)
    conflicting = []
    
    for idx, mat in enumerate(materials):
        # Check primary material
        mat_id = mat.get('material_id')
        if mat_id and int(mat_id) == output_product_id:
            conflicting.append(f"Primary material #{idx + 1}")
        
        # Check alternatives
        alternatives = mat.get('alternatives', [])
        for alt_idx, alt in enumerate(alternatives):
            alt_id = alt.get('alternative_material_id') or alt.get('material_id')
            if alt_id and int(alt_id) == output_product_id:
                conflicting.append(f"Alternative P{alt.get('priority', alt_idx + 1)} of material #{idx + 1}")
    
    if conflicting:
        error_msg = f"Output product cannot be used as input material. Found in: {', '.join(conflicting)}"
        return False, error_msg, conflicting
    
    return True, "", []


def validate_material_not_output_product(material_id: int, output_product_id: int, 
                                          material_name: str = None) -> Tuple[bool, str]:
    """
    Validate that a material being added is not the output product
    
    Args:
        material_id: Material ID to check
        output_product_id: Output product ID of the BOM
        material_name: Optional material name for error message
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not material_id or not output_product_id:
        return True, ""
    
    if int(material_id) == int(output_product_id):
        if material_name:
            return False, f"Cannot add '{material_name}' as material - it is the output product of this BOM (circular dependency)"
        return False, "Cannot add output product as input material (circular dependency)"
    
    return True, ""


def filter_available_materials_excluding_output(products: pd.DataFrame, 
                                                  used_ids: set,
                                                  output_product_id: int = None,
                                                  exclude_id: int = None) -> Dict:
    """
    Filter products to exclude already used materials AND the output product
    Returns product options dict for selectbox
    
    Args:
        products: DataFrame of all products
        used_ids: Set of material IDs already used in BOM
        output_product_id: Output product ID to also exclude (prevents circular dependency)
        exclude_id: Optional single ID to also exclude (e.g., current primary material)
    
    Returns:
        Dict of {display_text: {'id': int, 'uom': str, 'code': str, 'name': str}}
    """
    product_options = {}
    
    # Build exclusion set
    exclude_set = set(used_ids) if used_ids else set()
    if output_product_id:
        exclude_set.add(int(output_product_id))
    if exclude_id:
        exclude_set.add(int(exclude_id))
    
    for _, row in products.iterrows():
        mat_id = int(row['id'])
        
        # Skip if in exclusion set
        if mat_id in exclude_set:
            continue
        
        display_text = format_product_display(
            code=row['code'],
            name=row['name'],
            package_size=row.get('package_size'),
            brand=row.get('brand'),
            legacy_code=row.get('legacy_code')
        )
        product_options[display_text] = {
            'id': mat_id,
            'uom': row['uom'],
            'code': row['code'],
            'name': row['name'],
            'legacy_code': row.get('legacy_code')
        }
    
    return product_options


def check_materials_conflict_with_new_output(materials: list, new_output_product_id: int) -> Tuple[bool, List[Dict]]:
    """
    Check if existing materials would conflict with a new output product
    Used when changing output product in clone/edit scenarios
    
    Args:
        materials: List of material dicts
        new_output_product_id: New output product ID being selected
    
    Returns:
        Tuple of (has_conflict, list of conflicting material info dicts)
    """
    if not new_output_product_id or not materials:
        return False, []
    
    new_output_id = int(new_output_product_id)
    conflicts = []
    
    for idx, mat in enumerate(materials):
        # Check primary material
        mat_id = mat.get('material_id')
        if mat_id and int(mat_id) == new_output_id:
            conflicts.append({
                'type': 'PRIMARY',
                'index': idx,
                'material_id': mat_id
            })
        
        # Check alternatives
        alternatives = mat.get('alternatives', [])
        for alt_idx, alt in enumerate(alternatives):
            alt_id = alt.get('alternative_material_id') or alt.get('material_id')
            if alt_id and int(alt_id) == new_output_id:
                conflicts.append({
                    'type': 'ALTERNATIVE',
                    'index': idx,
                    'alt_index': alt_idx,
                    'material_id': alt_id,
                    'priority': alt.get('priority', 1)
                })
    
    return len(conflicts) > 0, conflicts


def render_output_material_conflict_warning(conflicts: List[Dict], products: pd.DataFrame = None):
    """
    Render warning when output product conflicts with existing materials
    
    Args:
        conflicts: List of conflict dicts from check_materials_conflict_with_new_output
        products: Optional products DataFrame for looking up names
    """
    st.error("⚠️ **Circular Dependency Detected!**")
    st.markdown("The selected output product is already used as an input material:")
    
    for conflict in conflicts:
        if conflict['type'] == 'PRIMARY':
            st.markdown(f"- **Primary material** in row #{conflict['index'] + 1}")
        else:
            st.markdown(f"- **Alternative P{conflict['priority']}** in row #{conflict['index'] + 1}")
    
    st.markdown("**Please either:**")
    st.markdown("1. Choose a different output product, OR")
    st.markdown("2. Remove the conflicting material(s) first")


def get_boms_with_circular_dependency_check(bom_ids: List[int] = None) -> Dict[int, bool]:
    """
    Check multiple BOMs for circular dependency (output product = input material)
    Used for dashboard/list display
    
    Args:
        bom_ids: List of BOM IDs to check, or None for all BOMs
        
    Returns:
        Dict mapping bom_id to has_circular_dependency boolean
    """
    try:
        engine = get_db_engine()
        
        # Query to find BOMs where output product is also an input material
        query = """
            WITH circular_check AS (
                -- Check primary materials
                SELECT DISTINCT
                    h.id as bom_id,
                    h.product_id as output_product_id,
                    d.material_id as input_material_id,
                    'PRIMARY' as material_type
                FROM bom_headers h
                JOIN bom_details d ON h.id = d.bom_header_id
                WHERE h.delete_flag = 0
                  AND h.product_id = d.material_id
                
                UNION
                
                -- Check alternative materials
                SELECT DISTINCT
                    h.id as bom_id,
                    h.product_id as output_product_id,
                    a.alternative_material_id as input_material_id,
                    'ALTERNATIVE' as material_type
                FROM bom_headers h
                JOIN bom_details d ON h.id = d.bom_header_id
                JOIN bom_material_alternatives a ON d.id = a.bom_detail_id
                WHERE h.delete_flag = 0
                  AND h.product_id = a.alternative_material_id
            )
            SELECT DISTINCT bom_id FROM circular_check
        """
        
        df = pd.read_sql(query, engine)
        
        # Build result map
        circular_bom_ids = set(df['bom_id'].tolist()) if not df.empty else set()
        
        # If specific bom_ids requested, filter to those
        if bom_ids:
            return {bom_id: bom_id in circular_bom_ids for bom_id in bom_ids}
        
        # Return all circular dependencies found
        return {bom_id: True for bom_id in circular_bom_ids}
    
    except Exception as e:
        logger.error(f"Error checking circular dependencies: {e}")
        return {}


def detect_circular_dependency_in_bom(bom_id: int) -> Dict[str, Any]:
    """
    Detect circular dependency in a specific BOM
    Returns detailed information about the conflict
    
    Args:
        bom_id: BOM header ID
        
    Returns:
        {
            'has_circular': bool,
            'output_product_id': int,
            'output_product_code': str,
            'output_product_name': str,
            'conflicts': [
                {'type': 'PRIMARY'|'ALTERNATIVE', 'detail_info': str, 'priority': int}
            ]
        }
    """
    try:
        engine = get_db_engine()
        
        query = """
            SELECT 
                h.product_id as output_product_id,
                op.pt_code as output_product_code,
                op.name as output_product_name,
                CASE 
                    WHEN d.material_id = h.product_id THEN 'PRIMARY'
                    WHEN a.alternative_material_id = h.product_id THEN 'ALTERNATIVE'
                END as conflict_type,
                CASE 
                    WHEN d.material_id = h.product_id THEN 'Primary material'
                    WHEN a.alternative_material_id = h.product_id THEN CONCAT('Alternative P', a.priority, ' for ', pm.name)
                END as detail_info,
                COALESCE(a.priority, 0) as priority
            FROM bom_headers h
            JOIN products op ON h.product_id = op.id
            JOIN bom_details d ON h.id = d.bom_header_id
            LEFT JOIN bom_material_alternatives a ON d.id = a.bom_detail_id AND a.alternative_material_id = h.product_id
            LEFT JOIN products pm ON d.material_id = pm.id
            WHERE h.id = %s
              AND h.delete_flag = 0
              AND (d.material_id = h.product_id OR a.alternative_material_id = h.product_id)
        """
        
        df = pd.read_sql(query, engine, params=(bom_id,))
        
        if df.empty:
            return {
                'has_circular': False,
                'output_product_id': None,
                'output_product_code': None,
                'output_product_name': None,
                'conflicts': []
            }
        
        first_row = df.iloc[0]
        conflicts = []
        
        for _, row in df.iterrows():
            if pd.notna(row['conflict_type']):
                conflicts.append({
                    'type': row['conflict_type'],
                    'detail_info': row['detail_info'],
                    'priority': int(row['priority']) if pd.notna(row['priority']) else 0
                })
        
        return {
            'has_circular': len(conflicts) > 0,
            'output_product_id': int(first_row['output_product_id']),
            'output_product_code': first_row['output_product_code'],
            'output_product_name': first_row['output_product_name'],
            'conflicts': conflicts
        }
    
    except Exception as e:
        logger.error(f"Error detecting circular dependency: {e}")
        return {
            'has_circular': False,
            'output_product_id': None,
            'output_product_code': None,
            'output_product_name': None,
            'conflicts': [],
            'error': str(e)
        }


def render_circular_dependency_warning(circular_info: Dict[str, Any]):
    """
    Render warning for circular dependency in View/Edit dialogs
    
    Args:
        circular_info: Dict from detect_circular_dependency_in_bom
    """
    if not circular_info.get('has_circular'):
        return
    
    st.error("🔄 **Circular Dependency Detected!**")
    st.markdown(
        f"Output product **{circular_info['output_product_code']}** "
        f"({circular_info['output_product_name']}) is also used as input material:"
    )
    
    for conflict in circular_info.get('conflicts', []):
        if conflict['type'] == 'PRIMARY':
            st.markdown(f"- **{conflict['detail_info']}**")
        else:
            st.markdown(f"- {conflict['detail_info']}")
    
    st.markdown("**This BOM has a self-reference issue that should be fixed.**")


# ==================== BOM Duplicate Detection for UI Warning ====================

def detect_duplicate_materials_in_bom(bom_id: int) -> Dict[str, Any]:
    """
    Detect duplicate materials in a BOM (same material used as primary or alternative)
    
    Args:
        bom_id: BOM header ID
        
    Returns:
        {
            'has_duplicates': bool,
            'duplicate_count': int,
            'duplicates': [
                {
                    'material_id': int,
                    'material_code': str,
                    'material_name': str,
                    'occurrences': [
                        {'type': 'PRIMARY'|'ALTERNATIVE', 'detail_info': str}
                    ]
                }
            ]
        }
    """
    try:
        engine = get_db_engine()
        
        # Query all materials usage in BOM (both primary and alternatives)
        query = """
            SELECT 
                'PRIMARY' as usage_type,
                d.material_id,
                p.pt_code as material_code,
                p.name as material_name,
                CONCAT('Primary material in BOM') as detail_info
            FROM bom_details d
            JOIN products p ON d.material_id = p.id
            WHERE d.bom_header_id = %s
            
            UNION ALL
            
            SELECT 
                'ALTERNATIVE' as usage_type,
                a.alternative_material_id as material_id,
                p.pt_code as material_code,
                p.name as material_name,
                CONCAT('Alternative for ', pm.name, ' (P', a.priority, ')') as detail_info
            FROM bom_material_alternatives a
            JOIN bom_details d ON a.bom_detail_id = d.id
            JOIN products p ON a.alternative_material_id = p.id
            JOIN products pm ON d.material_id = pm.id
            WHERE d.bom_header_id = %s
        """
        
        df = pd.read_sql(query, engine, params=(bom_id, bom_id))
        
        if df.empty:
            return {
                'has_duplicates': False,
                'duplicate_count': 0,
                'duplicates': []
            }
        
        # Group by material_id and find duplicates
        material_counts = df.groupby('material_id').size()
        duplicate_ids = material_counts[material_counts > 1].index.tolist()
        
        if not duplicate_ids:
            return {
                'has_duplicates': False,
                'duplicate_count': 0,
                'duplicates': []
            }
        
        # Build duplicate details
        duplicates = []
        for mat_id in duplicate_ids:
            mat_rows = df[df['material_id'] == mat_id]
            first_row = mat_rows.iloc[0]
            
            occurrences = []
            for _, row in mat_rows.iterrows():
                occurrences.append({
                    'type': row['usage_type'],
                    'detail_info': row['detail_info']
                })
            
            duplicates.append({
                'material_id': int(mat_id),
                'material_code': first_row['material_code'],
                'material_name': first_row['material_name'],
                'occurrences': occurrences
            })
        
        return {
            'has_duplicates': True,
            'duplicate_count': len(duplicates),
            'duplicates': duplicates
        }
    
    except Exception as e:
        logger.error(f"Error detecting duplicate materials: {e}")
        return {
            'has_duplicates': False,
            'duplicate_count': 0,
            'duplicates': [],
            'error': str(e)
        }


def get_boms_with_duplicate_check(bom_ids: List[int] = None) -> Dict[int, bool]:
    """
    Check multiple BOMs for duplicates efficiently (for dashboard)
    
    Args:
        bom_ids: List of BOM IDs to check, or None for all BOMs
        
    Returns:
        Dict mapping bom_id to has_duplicates boolean
    """
    try:
        engine = get_db_engine()
        
        # Query to find all BOMs with duplicate materials
        query = """
            WITH all_materials AS (
                -- Primary materials
                SELECT 
                    d.bom_header_id,
                    d.material_id
                FROM bom_details d
                JOIN bom_headers h ON d.bom_header_id = h.id
                WHERE h.delete_flag = 0
                
                UNION ALL
                
                -- Alternative materials
                SELECT 
                    d.bom_header_id,
                    a.alternative_material_id as material_id
                FROM bom_material_alternatives a
                JOIN bom_details d ON a.bom_detail_id = d.id
                JOIN bom_headers h ON d.bom_header_id = h.id
                WHERE h.delete_flag = 0
            ),
            duplicates AS (
                SELECT 
                    bom_header_id,
                    material_id,
                    COUNT(*) as cnt
                FROM all_materials
                GROUP BY bom_header_id, material_id
                HAVING COUNT(*) > 1
            )
            SELECT DISTINCT bom_header_id
            FROM duplicates
        """
        
        df = pd.read_sql(query, engine)
        
        boms_with_duplicates = set(df['bom_header_id'].tolist()) if not df.empty else set()
        
        # If specific bom_ids provided, filter result
        if bom_ids:
            return {bom_id: (bom_id in boms_with_duplicates) for bom_id in bom_ids}
        
        return {bom_id: True for bom_id in boms_with_duplicates}
    
    except Exception as e:
        logger.error(f"Error checking BOMs for duplicates: {e}")
        return {}


def render_duplicate_warning_badge(has_duplicates: bool, duplicate_count: int = 0) -> str:
    """
    Return HTML/emoji badge for duplicate warning
    
    Args:
        has_duplicates: Whether BOM has duplicates
        duplicate_count: Number of duplicate materials
        
    Returns:
        Badge string for display
    """
    if not has_duplicates:
        return ""
    
    if duplicate_count > 0:
        return f"⚠️ {duplicate_count} dup"
    return "⚠️ Duplicate"


def render_duplicate_warning_section(duplicate_info: Dict[str, Any]):
    """
    Render duplicate warning section in Streamlit UI
    
    Args:
        duplicate_info: Result from detect_duplicate_materials_in_bom()
    """
    import streamlit as st
    
    if not duplicate_info.get('has_duplicates'):
        return
    
    duplicates = duplicate_info.get('duplicates', [])
    count = duplicate_info.get('duplicate_count', 0)
    
    st.warning(f"⚠️ **Warning: Found {count} duplicate material(s) in this BOM**")
    
    with st.expander("📋 Duplicate Materials Details", expanded=True):
        for dup in duplicates:
            st.markdown(f"**{dup['material_code']}** - {dup['material_name']}")
            
            for occ in dup['occurrences']:
                icon = "🔵" if occ['type'] == 'PRIMARY' else "🔀"
                st.markdown(f"   {icon} {occ['detail_info']}")
            
            st.markdown("")
        
        st.info("💡 **Recommendation:** Remove duplicate materials to ensure BOM accuracy.")


# ==================== Active BOM Conflict Detection ====================

def get_active_boms_for_product(product_id: int, exclude_bom_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get all active BOMs for a product
    
    Args:
        product_id: Product ID to check
        exclude_bom_id: BOM ID to exclude from results (e.g., current BOM being activated)
        
    Returns:
        List of dicts with active BOM info: id, bom_code, bom_name, bom_type, usage_count, created_date
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            h.id,
            h.bom_code,
            h.bom_name,
            h.bom_type,
            h.created_date,
            COALESCE(
                (SELECT COUNT(*) FROM manufacturing_orders mo 
                 WHERE mo.bom_header_id = h.id 
                 AND mo.delete_flag = 0), 
                0
            ) as usage_count
        FROM bom_headers h
        WHERE h.product_id = %s
        AND h.status = 'ACTIVE'
        AND h.delete_flag = 0
    """
    
    params = [product_id]
    
    if exclude_bom_id:
        query += " AND h.id != %s"
        params.append(exclude_bom_id)
    
    query += " ORDER BY h.created_date DESC"
    
    try:
        df = pd.read_sql(query, engine, params=tuple(params))
        return df.to_dict('records')
    except Exception as e:
        logger.error(f"Error getting active BOMs for product {product_id}: {e}")
        return []


def get_products_with_multiple_active_boms() -> Dict[int, List[Dict[str, Any]]]:
    """
    Get all products that have multiple active BOMs (conflict detection for dashboard)
    
    Returns:
        Dict mapping product_id to list of active BOM info dicts
    """
    engine = get_db_engine()
    
    query = """
        WITH active_bom_counts AS (
            SELECT 
                product_id,
                COUNT(*) as active_count
            FROM bom_headers
            WHERE status = 'ACTIVE'
            AND delete_flag = 0
            GROUP BY product_id
            HAVING COUNT(*) > 1
        )
        SELECT 
            h.product_id,
            h.id as bom_id,
            h.bom_code,
            h.bom_name,
            h.bom_type,
            h.created_date,
            COALESCE(
                (SELECT COUNT(*) FROM manufacturing_orders mo 
                 WHERE mo.bom_header_id = h.id 
                 AND mo.delete_flag = 0), 
                0
            ) as usage_count
        FROM bom_headers h
        JOIN active_bom_counts abc ON h.product_id = abc.product_id
        WHERE h.status = 'ACTIVE'
        AND h.delete_flag = 0
        ORDER BY h.product_id, h.created_date DESC
    """
    
    try:
        df = pd.read_sql(query, engine)
        
        if df.empty:
            return {}
        
        # Group by product_id
        result = {}
        for product_id in df['product_id'].unique():
            product_boms = df[df['product_id'] == product_id]
            result[int(product_id)] = product_boms.to_dict('records')
        
        return result
    except Exception as e:
        logger.error(f"Error getting products with multiple active BOMs: {e}")
        return {}


def get_boms_with_active_conflict_check(bom_ids: List[int] = None) -> Dict[int, int]:
    """
    Check multiple BOMs for active conflicts efficiently (for dashboard badge)
    
    A BOM has a conflict if its product has multiple active BOMs.
    
    Args:
        bom_ids: List of BOM IDs to check, or None for all BOMs
        
    Returns:
        Dict mapping bom_id to number of other active BOMs for same product (0 = no conflict)
    """
    engine = get_db_engine()
    
    query = """
        WITH product_active_counts AS (
            SELECT 
                product_id,
                COUNT(*) as active_count
            FROM bom_headers
            WHERE status = 'ACTIVE'
            AND delete_flag = 0
            GROUP BY product_id
        )
        SELECT 
            h.id as bom_id,
            h.product_id,
            COALESCE(pac.active_count, 0) as active_count
        FROM bom_headers h
        LEFT JOIN product_active_counts pac ON h.product_id = pac.product_id
        WHERE h.delete_flag = 0
        AND h.status = 'ACTIVE'
    """
    
    try:
        df = pd.read_sql(query, engine)
        
        if df.empty:
            return {}
        
        # Map bom_id to conflict count (active_count - 1 = other active BOMs)
        result = {}
        for _, row in df.iterrows():
            bom_id = int(row['bom_id'])
            # Conflict count is total active BOMs for product minus this one
            conflict_count = int(row['active_count']) - 1
            if bom_ids is None or bom_id in bom_ids:
                result[bom_id] = conflict_count
        
        return result
    except Exception as e:
        logger.error(f"Error checking BOMs for active conflicts: {e}")
        return {}


def check_active_bom_conflict(product_id: int, exclude_bom_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Check if activating a BOM would create a conflict (multiple active BOMs for same product)
    
    Args:
        product_id: Product ID of the BOM being activated
        exclude_bom_id: BOM ID being activated (to exclude from check)
        
    Returns:
        {
            'has_conflict': bool,
            'conflict_count': int,
            'conflicting_boms': List[Dict] with bom info
        }
    """
    active_boms = get_active_boms_for_product(product_id, exclude_bom_id)
    
    return {
        'has_conflict': len(active_boms) > 0,
        'conflict_count': len(active_boms),
        'conflicting_boms': active_boms
    }


def render_active_bom_conflict_warning(conflict_info: Dict[str, Any], bom_info: Dict[str, Any]) -> Optional[str]:
    """
    Render active BOM conflict warning section in Streamlit UI
    
    Args:
        conflict_info: Result from check_active_bom_conflict()
        bom_info: Current BOM information
        
    Returns:
        Selected action: 'deactivate_old', 'keep_both', or None if cancelled
    """
    import streamlit as st
    
    if not conflict_info.get('has_conflict'):
        return 'no_conflict'
    
    conflicting_boms = conflict_info.get('conflicting_boms', [])
    count = conflict_info.get('conflict_count', 0)
    
    st.warning(f"⚠️ **Warning: Product Already Has {count} Active BOM(s)**")
    
    st.markdown(f"**Product:** {bom_info.get('product_code', '')} - {bom_info.get('product_name', '')}")
    
    st.markdown("---")
    st.markdown("**📋 Current Active BOM(s):**")
    
    for bom in conflicting_boms:
        created_str = ""
        if bom.get('created_date'):
            try:
                created_str = bom['created_date'].strftime('%d/%m/%Y')
            except:
                created_str = str(bom['created_date'])[:10]
        
        usage_count = bom.get('usage_count', 0)
        usage_badge = f"🏭 {usage_count} orders" if usage_count > 0 else "No usage"
        
        st.info(
            f"**{bom['bom_code']}** | {bom['bom_name']}\n\n"
            f"Type: {bom['bom_type']} | Created: {created_str} | {usage_badge}"
        )
    
    st.markdown("---")
    st.markdown("**Choose an action:**")
    
    action = st.radio(
        "Conflict Resolution",
        options=['deactivate_old', 'keep_both', 'cancel'],
        format_func=lambda x: {
            'deactivate_old': '🔄 Deactivate old BOM(s) and activate this one (Recommended)',
            'keep_both': '⚠️ Keep both active (Not recommended - may cause confusion)',
            'cancel': '❌ Cancel - keep current state'
        }.get(x, x),
        key=f"conflict_action_{bom_info.get('id', 'new')}",
        index=0  # Default to deactivate_old
    )
    
    # Show additional warning for keep_both
    if action == 'keep_both':
        st.error(
            "⚠️ **Warning:** Having multiple active BOMs for the same product may cause:\n"
            "- Confusion when creating Manufacturing Orders\n"
            "- Inconsistent costing calculations\n"
            "- Difficulty tracking production history"
        )
    
    return action