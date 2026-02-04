# utils/production/completions/common.py
"""
Common utilities for Completions domain
Formatting, validation, UI helpers, and date utilities

Version: 1.2.0
Changes:
- v1.2.0: Added check_expiry_warning, check_overproduction_warning to CompletionValidator
- v1.1.0: Removed unused validator methods (validate_produced_qty, can_complete)
"""

import logging
from datetime import date, timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union, Optional, Any
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

class CompletionConstants:
    """Completion-specific constants"""
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    QUANTITY_DECIMALS = 2
    
    # Quality statuses
    STATUS_PENDING = 'PENDING'
    STATUS_PASSED = 'PASSED'
    STATUS_FAILED = 'FAILED'
    
    QUALITY_STATUSES = [
        ('PENDING', '⏳ Pending QC'),
        ('PASSED', '✅ Passed'),
        ('FAILED', '❌ Failed')
    ]
    
    # Completable order statuses
    COMPLETABLE_STATUSES = ['IN_PROGRESS']


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
    """Convert datetime to Vietnam timezone (UTC+7)"""
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


def calculate_percentage(numerator: Union[int, float, Decimal, None],
                        denominator: Union[int, float, Decimal, None],
                        decimal_places: int = 1) -> float:
    """Calculate percentage with safety checks"""
    if numerator is None or denominator is None:
        return 0.0
    
    if pd.isna(numerator) or pd.isna(denominator):
        return 0.0
    
    num = float(numerator)
    denom = float(denominator)
    
    if denom == 0:
        return 0.0
    
    percentage = (num / denom) * 100
    
    return round(percentage, decimal_places)


# ==================== Status Indicators ====================

def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        # Quality statuses
        'PENDING': '⏳ Pending',
        'PASSED': '✅ Passed',
        'FAILED': '❌ Failed',
        # Order statuses
        'DRAFT': '📝 Draft',
        'CONFIRMED': '✔️ Confirmed',
        'IN_PROGRESS': '🔄 In Progress',
        'COMPLETED': '✅ Completed',
        'CANCELLED': '❌ Cancelled',
    }
    
    return status_icons.get(status.upper() if status else '', f"⚪ {status}")


def get_yield_indicator(yield_rate: float) -> str:
    """Get yield rate indicator"""
    if yield_rate >= 95:
        return "✅"
    elif yield_rate >= 85:
        return "⚠️"
    else:
        return "❌"


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

class CompletionValidator:
    """Completion form validation helpers"""
    
    @staticmethod
    def validate_batch_no(batch_no: str) -> Tuple[bool, Optional[str]]:
        """Validate batch number"""
        if not batch_no or not batch_no.strip():
            return False, "Batch number is required"
        return True, None
    
    @staticmethod
    def check_expiry_warning(expiry_date: Union[date, None],
                              today: Optional[date] = None) -> Optional[str]:
        """
        Check if expiry date is in the past.
        Returns warning message or None.
        """
        if expiry_date is None:
            return None
        
        if today is None:
            today = date.today()
        
        if isinstance(expiry_date, datetime):
            expiry_date = expiry_date.date()
        
        if expiry_date < today:
            days_ago = (today - expiry_date).days
            return f"Expiry date is {days_ago} day(s) in the past ({expiry_date.strftime('%d/%m/%Y')})"
        
        return None
    
    @staticmethod
    def check_overproduction_warning(produced_qty: float,
                                       remaining_qty: float,
                                       uom: str = '') -> Optional[str]:
        """
        Check if production quantity exceeds remaining planned quantity.
        Returns warning message or None.
        """
        if remaining_qty <= 0:
            return None
        
        if produced_qty > remaining_qty:
            over_qty = produced_qty - remaining_qty
            over_pct = (over_qty / remaining_qty) * 100
            uom_str = f" {uom}" if uom else ""
            return (
                f"Over-production: {Decimal(str(over_qty)).quantize(Decimal('0.01'))}{uom_str} "
                f"above remaining ({over_pct:.0f}% over plan)"
            )
        
        return None


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


def generate_batch_no() -> str:
    """Generate default batch number"""
    return f"BATCH-{get_vietnam_now().strftime('%Y%m%d-%H%M')}"


# ==================== Product Display Formatting ====================

def format_product_display(row: Dict[str, Any], 
                          include_brand: bool = True,
                          multiline: bool = False,
                          language: str = 'en') -> str:
    """
    Format product display with standardized format across module.
    
    Format: PT_CODE (LEGACY or NEW) | NAME | PKG_SIZE (BRAND)
    
    Examples:
    - With legacy: VT001 (OLD001) | Vietape FP5309 Tape | 100m/roll (3M)
    - Without legacy (new product): VT001 (NEW) | Vietape FP5309 Tape | 100m/roll (3M)
    - No package_size: VT001 (NEW) | Vietape FP5309 Tape (3M)
    
    Args:
        row: Dict containing product fields (pt_code, legacy_pt_code, product_name/name, 
             package_size, brand_name)
        include_brand: Whether to include brand in output
        multiline: If True, use <br/> for PDF/HTML output
        language: 'vi' or 'en' for labels
    
    Returns:
        Formatted product display string
    """
    # Extract fields with fallbacks
    pt_code = row.get('pt_code', '') or ''
    legacy_pt_code = row.get('legacy_pt_code', '') or ''
    name = row.get('product_name') or row.get('name', '') or ''
    package_size = row.get('package_size', '') or ''
    brand_name = row.get('brand_name', '') or ''
    
    # Build PT code part: PT_CODE (LEGACY) or PT_CODE (NEW)
    if pt_code:
        if legacy_pt_code and legacy_pt_code != pt_code:
            # Has legacy code - show legacy only
            code_part = f"{pt_code} ({legacy_pt_code})"
        else:
            # No legacy code - new product
            code_part = f"{pt_code} (NEW)"
    else:
        code_part = ''
    
    # Build size and brand part
    size_brand_parts = []
    if package_size:
        size_brand_parts.append(package_size)
    if include_brand and brand_name:
        size_brand_parts.append(f"({brand_name})")
    
    size_brand = ' '.join(size_brand_parts)
    
    # Combine parts
    if multiline:
        # For PDF/HTML - use line breaks
        separator = '<br/>'
        parts = []
        if code_part:
            label = 'Mã VT' if language == 'vi' else 'Code'
            parts.append(f"<b>{label}:</b> {code_part}")
        if name:
            parts.append(f"<b>{'Tên' if language == 'vi' else 'Name'}:</b> {name}")
        if size_brand:
            parts.append(f"<b>{'Quy cách' if language == 'vi' else 'Spec'}:</b> {size_brand}")
        return separator.join(parts) if parts else name
    else:
        # For table display - single line with pipe separator
        parts = []
        if code_part:
            parts.append(code_part)
        if name:
            parts.append(name)
        if size_brand:
            parts.append(size_brand)
        
        return ' | '.join(parts) if parts else name


def format_material_display(row: Dict[str, Any], 
                           include_brand: bool = True,
                           show_type: bool = False) -> str:
    """
    Format material display (input materials for production).
    Uses same format as product display.
    
    Format: PT_CODE (LEGACY|NEW) | NAME | PKG_SIZE (BRAND) [TYPE]
    
    Args:
        row: Dict containing material fields
        include_brand: Whether to include brand
        show_type: Whether to show material_type (RAW_MATERIAL, PACKAGING, etc)
    
    Returns:
        Formatted material display string
    """
    base_display = format_product_display(row, include_brand=include_brand)
    
    if show_type:
        material_type = row.get('material_type', '') or ''
        if material_type:
            type_icons = {
                'RAW_MATERIAL': '🔧',
                'PACKAGING': '📦',
                'CONSUMABLE': '🔩'
            }
            icon = type_icons.get(material_type, '')
            return f"{base_display} {icon}[{material_type}]"
    
    return base_display