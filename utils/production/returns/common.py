# utils/production/returns/common.py
"""
Common utilities for Returns domain
Formatting, validation, UI helpers, and date utilities

Version: 1.0.0
"""

import logging
from datetime import date, timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union, Optional, List, Any
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

class ReturnConstants:
    """Return-specific constants"""
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    QUANTITY_DECIMALS = 4
    
    # Return statuses
    STATUS_DRAFT = 'DRAFT'
    STATUS_CONFIRMED = 'CONFIRMED'
    STATUS_CANCELLED = 'CANCELLED'
    
    # Return reasons
    REASONS = [
        ('EXCESS', 'Excess Material / Thừa NVL'),
        ('DEFECT', 'Defective Material / NVL lỗi'),
        ('WRONG_MATERIAL', 'Wrong Material / Sai NVL'),
        ('PLAN_CHANGE', 'Plan Change / Thay đổi KH'),
        ('OTHER', 'Other / Khác')
    ]
    
    # Material conditions
    CONDITIONS = [
        ('GOOD', 'Good / Tốt'),
        ('DAMAGED', 'Damaged / Hư hỏng')
    ]


# ==================== Product Display Formatting ====================

def format_product_display(
    pt_code: str,
    name: str,
    legacy_pt_code: Optional[str] = None,
    package_size: Optional[str] = None,
    brand_name: Optional[str] = None,
    include_all: bool = True
) -> str:
    """
    Format product display string with standardized format.
    
    Format: PT_CODE (LEGACY|NEW) | NAME | PKG_SIZE (BRAND)
    
    Args:
        pt_code: Product code (required)
        name: Product name (required)
        legacy_pt_code: Legacy product code (optional, shows 'NEW' if None)
        package_size: Package size (optional)
        brand_name: Brand name (optional)
        include_all: If True, include all parts; if False, only code and name
    
    Returns:
        Formatted product display string
    
    Examples:
        - Full: "PT-001 (OLD-001) | Nguồn điện 24V | 100pcs (Samsung)"
        - No legacy: "PT-001 (NEW) | Nguồn điện 24V | 100pcs (Samsung)"
        - Minimal: "PT-001 (NEW) | Nguồn điện 24V"
    """
    # Part 1: PT_CODE (LEGACY|NEW)
    legacy_indicator = legacy_pt_code if legacy_pt_code else 'NEW'
    code_part = f"{pt_code} ({legacy_indicator})"
    
    # Part 2: NAME
    name_part = name or ''
    
    # Build display string
    parts = [code_part, name_part]
    
    # Part 3: PKG_SIZE (BRAND) - optional
    if include_all and (package_size or brand_name):
        size_brand_parts = []
        if package_size:
            size_brand_parts.append(package_size)
        if brand_name:
            size_brand_parts.append(f"({brand_name})")
        if size_brand_parts:
            parts.append(' '.join(size_brand_parts))
    
    return ' | '.join(parts)


def format_material_display(
    pt_code: str,
    name: str,
    legacy_pt_code: Optional[str] = None,
    package_size: Optional[str] = None,
    brand_name: Optional[str] = None,
    is_alternative: bool = False,
    original_name: Optional[str] = None,
    include_all: bool = True
) -> str:
    """
    Format material display string with alternative indicator.
    
    Format: PT_CODE (LEGACY|NEW) | NAME | PKG_SIZE (BRAND)
    For alternatives: (*) PT_CODE (LEGACY|NEW) | NAME [Alt: Original] | PKG_SIZE (BRAND)
    
    Args:
        pt_code: Product code
        name: Material name
        legacy_pt_code: Legacy product code
        package_size: Package size
        brand_name: Brand name
        is_alternative: Whether this is an alternative material
        original_name: Original material name (for alternatives)
        include_all: If True, include all parts
    
    Returns:
        Formatted material display string
    """
    # Build base display
    base_display = format_product_display(
        pt_code=pt_code,
        name=name,
        legacy_pt_code=legacy_pt_code,
        package_size=package_size,
        brand_name=brand_name,
        include_all=include_all
    )
    
    # Add alternative indicator
    if is_alternative:
        prefix = "(*) "
        if original_name:
            # Insert [Alt: Original] after name
            parts = base_display.split(' | ')
            if len(parts) >= 2:
                parts[1] = f"{parts[1]} [Alt: {original_name}]"
            base_display = ' | '.join(parts)
        return prefix + base_display
    
    return base_display


def format_product_display_html(
    pt_code: str,
    name: str,
    legacy_pt_code: Optional[str] = None,
    package_size: Optional[str] = None,
    brand_name: Optional[str] = None,
    is_alternative: bool = False,
    original_name: Optional[str] = None
) -> str:
    """
    Format product display for PDF/HTML with line breaks.
    
    Format (multi-line):
        PT_CODE (LEGACY|NEW)
        NAME [Alt: Original]
        PKG_SIZE (BRAND)
    
    Returns:
        HTML formatted string with <br/> tags
    """
    lines = []
    
    # Line 1: PT_CODE (LEGACY|NEW)
    legacy_indicator = legacy_pt_code if legacy_pt_code else 'NEW'
    code_line = f"<b>{pt_code}</b> ({legacy_indicator})"
    if is_alternative:
        code_line = "(*) " + code_line
    lines.append(code_line)
    
    # Line 2: NAME [Alt: Original]
    name_line = name or ''
    if is_alternative and original_name:
        name_line = f"{name_line} <i>[Alt: {original_name}]</i>"
    lines.append(name_line)
    
    # Line 3: PKG_SIZE (BRAND)
    if package_size or brand_name:
        size_brand_parts = []
        if package_size:
            size_brand_parts.append(package_size)
        if brand_name:
            size_brand_parts.append(f"({brand_name})")
        if size_brand_parts:
            lines.append(' '.join(size_brand_parts))
    
    return '<br/>'.join(lines)


def format_order_display(
    order_no: str,
    pt_code: str,
    product_name: str,
    legacy_pt_code: Optional[str] = None
) -> str:
    """
    Format order display for dropdown selection.
    
    Format: ORDER_NO | PT_CODE (LEGACY|NEW) | NAME
    
    Example: "MO-20241201-001 | PT-001 (NEW) | Nguồn điện 24V"
    """
    legacy_indicator = legacy_pt_code if legacy_pt_code else 'NEW'
    return f"{order_no} | {pt_code} ({legacy_indicator}) | {product_name}"


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


def convert_to_vietnam_tz(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """
    Convert datetime to Vietnam timezone (UTC+7)
    """
    if dt is None:
        return None
    
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(dt, '%Y-%m-%d')
            except ValueError:
                return None
    
    if not isinstance(dt, datetime):
        return None
    
    if VN_TIMEZONE:
        if dt.tzinfo is None:
            try:
                from zoneinfo import ZoneInfo
                utc = ZoneInfo('UTC')
                dt = dt.replace(tzinfo=utc)
            except ImportError:
                try:
                    import pytz
                    utc = pytz.UTC
                    dt = utc.localize(dt)
                except:
                    return dt
        try:
            return dt.astimezone(VN_TIMEZONE)
        except:
            return dt
    
    return dt


def format_datetime_vn(dt: Union[datetime, str, None], fmt: str = '%d/%m/%Y %H:%M') -> str:
    """Format datetime in Vietnam timezone"""
    vn_dt = convert_to_vietnam_tz(dt)
    if vn_dt is None:
        return 'N/A'
    return vn_dt.strftime(fmt)


# ==================== Number Formatting ====================

def format_number(value: Union[int, float, Decimal, None],
                 decimal_places: int = 4,
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


# ==================== Status Indicators ====================

def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        'DRAFT': '📝 Draft',
        'CONFIRMED': '✅ Confirmed',
        'CANCELLED': '❌ Cancelled',
        'GOOD': '✅ Good',
        'DAMAGED': '⚠️ Damaged',
    }
    
    return status_icons.get(status.upper(), f"⚪ {status}")


def create_reason_display(reason: str) -> str:
    """Create reason display"""
    reason_map = {
        'EXCESS': '📦 Excess Material',
        'DEFECT': '⚠️ Defective',
        'WRONG_MATERIAL': '❌ Wrong Material',
        'PLAN_CHANGE': '📋 Plan Change',
        'OTHER': '📝 Other'
    }
    return reason_map.get(reason.upper(), reason)


# ==================== Date Helpers ====================

def get_date_filter_presets() -> Dict[str, Tuple[date, date]]:
    """Get common date filter presets"""
    today = get_vietnam_today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    first_of_last_month = last_month_end.replace(day=1)
    
    return {
        "Today": (today, today),
        "Yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "This Week": (today - timedelta(days=today.weekday()), today),
        "This Month": (first_of_month, today),
        "Last Month": (first_of_last_month, last_month_end),
        "Last 7 Days": (today - timedelta(days=6), today),
        "Last 30 Days": (today - timedelta(days=29), today),
    }


def format_date(dt: Union[date, datetime, str, None], 
               fmt: str = '%d/%m/%Y') -> str:
    """Format date to string"""
    if dt is None:
        return ''
    
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d').date()
        except ValueError:
            return dt
    
    if isinstance(dt, datetime):
        dt = dt.date()
    
    return dt.strftime(fmt)


def format_datetime(dt: Union[datetime, str, None],
                   fmt: str = '%d/%m/%Y %H:%M') -> str:
    """Format datetime to string"""
    if dt is None:
        return ''
    
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(dt, '%Y-%m-%d')
            except ValueError:
                return dt
    
    return dt.strftime(fmt)


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
                safe_name = sheet_name[:31].replace('[', '').replace(']', '')
                df.to_excel(writer, sheet_name=safe_name, index=include_index)
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


# ==================== Validation Helpers ====================

class ReturnValidator:
    """Return form validation helpers"""
    
    @staticmethod
    def validate_return_quantities(returns: List[Dict],
                                   returnable: pd.DataFrame) -> Tuple[bool, List[str]]:
        """
        Validate return quantities
        
        Args:
            returns: List of return items
            returnable: DataFrame with returnable materials
            
        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []
        
        for ret in returns:
            issue_detail_id = ret['issue_detail_id']
            return_qty = ret['quantity']
            
            # Find in returnable
            match = returnable[returnable['issue_detail_id'] == issue_detail_id]
            if match.empty:
                errors.append(f"Material with issue detail {issue_detail_id} not found")
                continue
            
            returnable_qty = float(match.iloc[0]['returnable_qty'])
            if return_qty > returnable_qty:
                material_name = match.iloc[0]['material_name']
                errors.append(
                    f"{material_name}: cannot return {format_number(return_qty, 4)} > "
                    f"returnable {format_number(returnable_qty, 4)}"
                )
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    @staticmethod
    def validate_employees(returned_by: Optional[int],
                          received_by: Optional[int]) -> Tuple[bool, Optional[str]]:
        """Validate employee selections"""
        if returned_by is None:
            return False, "Please select production staff (Returned By)"
        if received_by is None:
            return False, "Please select warehouse staff (Received By)"
        return True, None


# ==================== UI Helpers ====================

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


def get_user_audit_info() -> Dict[str, Any]:
    """Get user audit info from session state"""
    return {
        'user_id': st.session_state.get('user_id', 1),
        'keycloak_id': st.session_state.get('user_keycloak_id', 'system'),
        'username': st.session_state.get('username', 'system')
    }