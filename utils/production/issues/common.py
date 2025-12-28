# utils/production/issues/common.py
"""
Common utilities for Issues domain
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

class IssueConstants:
    """Issue-specific constants"""
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    QUANTITY_DECIMALS = 4
    
    # Issue statuses
    STATUS_DRAFT = 'DRAFT'
    STATUS_CONFIRMED = 'CONFIRMED'
    STATUS_CANCELLED = 'CANCELLED'
    
    # Material availability statuses
    AVAIL_SUFFICIENT = 'SUFFICIENT'
    AVAIL_PARTIAL = 'PARTIAL'
    AVAIL_INSUFFICIENT = 'INSUFFICIENT'
    
    # Order statuses that allow issuing
    ISSUEABLE_ORDER_STATUSES = ['DRAFT', 'CONFIRMED']


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
    Handles both timezone-aware and naive datetimes from database
    
    Args:
        dt: datetime object or string in format 'YYYY-MM-DD HH:MM:SS'
    
    Returns:
        datetime in Vietnam timezone
    """
    if dt is None:
        return None
    
    # Parse string if needed
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
        # If datetime is naive (no timezone), assume it's in UTC and convert
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
                    # Fallback: assume it's already in VN timezone
                    return dt
        
        # Convert to Vietnam timezone
        try:
            return dt.astimezone(VN_TIMEZONE)
        except:
            return dt
    
    return dt


def format_datetime_vn(dt: Union[datetime, str, None], fmt: str = '%d/%m/%Y %H:%M') -> str:
    """
    Format datetime in Vietnam timezone
    
    Args:
        dt: datetime object or string
        fmt: output format string (default: DD/MM/YYYY HH:MM)
    
    Returns:
        Formatted datetime string
    """
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


# ==================== Status Indicators ====================

def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        'DRAFT': '📝 Draft',
        'CONFIRMED': '✅ Confirmed',
        'CANCELLED': '❌ Cancelled',
        'SUFFICIENT': '✅ Sufficient',
        'PARTIAL': '⚠️ Partial',
        'INSUFFICIENT': '❌ Insufficient',
        'PENDING': '⏳ Pending',
        'ISSUED': '✅ Issued',
        'IN_PROGRESS': '🔄 In Progress',
    }
    
    return status_icons.get(status.upper(), f"⚪ {status}")


def get_availability_status_color(status: str) -> str:
    """Get color for availability status"""
    colors = {
        'SUFFICIENT': 'green',
        'PARTIAL': 'orange',
        'INSUFFICIENT': 'red',
    }
    return colors.get(status.upper(), 'gray')


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
        "Last Week": (today - timedelta(days=today.weekday() + 7), 
                     today - timedelta(days=today.weekday() + 1)),
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

class IssueValidator:
    """Issue form validation helpers"""
    
    @staticmethod
    def validate_issue_quantities(quantities: Dict[int, float],
                                  availability: pd.DataFrame,
                                  use_alternatives: Dict[int, bool] = None) -> Tuple[bool, List[str], List[str]]:
        """
        Validate issue quantities against availability
        
        Args:
            quantities: Dict of {material_id: issue_quantity}
            availability: DataFrame with availability info
            use_alternatives: Dict of {material_id: use_alternatives_flag}
            
        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        errors = []
        warnings = []
        
        for _, row in availability.iterrows():
            material_id = row['material_id']
            material_name = row['material_name']
            required_qty = float(row['required_qty'])
            available_qty = float(row['available_qty'])
            alt_total = float(row.get('alternative_total_qty', 0))
            
            issue_qty = quantities.get(material_id, 0)
            use_alt = use_alternatives.get(material_id, False) if use_alternatives else False
            
            # Determine max available
            max_available = available_qty + alt_total if use_alt else available_qty
            
            # Validation
            if issue_qty > max_available:
                errors.append(
                    f"{material_name}: cannot issue {format_number(issue_qty, 4)} > "
                    f"available {format_number(max_available, 4)}"
                )
            elif issue_qty < required_qty:
                warnings.append(
                    f"{material_name}: issuing {format_number(issue_qty, 4)} < "
                    f"required {format_number(required_qty, 4)}"
                )
        
        is_valid = len(errors) == 0
        return is_valid, errors, warnings
    
    @staticmethod
    def validate_employees(issued_by: Optional[int], 
                          received_by: Optional[int]) -> Tuple[bool, Optional[str]]:
        """Validate employee selections"""
        if issued_by is None:
            return False, "Please select warehouse staff (Issued By)"
        if received_by is None:
            return False, "Please select production staff (Received By)"
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


def format_material_display(row) -> str:
    """Format material display with PT code and package size"""
    name = row.get('material_name', 'Unknown')
    pt_code = row.get('pt_code', '')
    package_size = row.get('package_size', '')
    
    display = f"**{name}**"
    if pt_code:
        display += f" | {pt_code}"
    if package_size:
        display += f" | {package_size}"
    
    return display


def get_user_audit_info() -> Dict[str, Any]:
    """Get user audit info from session state"""
    return {
        'user_id': st.session_state.get('user_id', 1),
        'keycloak_id': st.session_state.get('user_keycloak_id', 'system'),
        'username': st.session_state.get('username', 'system')
    }


def format_product_display(pt_code: str = None, 
                          legacy_pt_code: str = None,
                          product_name: str = None,
                          package_size: str = None,
                          brand_name: str = None) -> str:
    """
    Format product display consistently across UI
    
    Format: code (legacy_code|NEW) | name | pkg size (brand)
    Example: VTI001000610 (1530000469) | Vietape FP5309 Tape | 500g (Vietape)
    Example: VTI001000610 (NEW) | Vietape FP5309 Tape | 500g (Vietape)
    
    Args:
        pt_code: VTI product code
        legacy_pt_code: Legacy/old product code (NEW if empty)
        product_name: Product name
        package_size: Package size
        brand_name: Brand name
    
    Returns:
        Formatted product display string
    """
    parts = []
    
    # Part 1: code (legacy_code|NEW)
    if pt_code:
        legacy_display = legacy_pt_code if legacy_pt_code else "NEW"
        parts.append(f"{pt_code} ({legacy_display})")
    
    # Part 2: name
    if product_name:
        parts.append(product_name)
    
    # Part 3: pkg size (brand)
    size_brand_parts = []
    if package_size:
        size_brand_parts.append(package_size)
    if brand_name:
        size_brand_parts.append(f"({brand_name})")
    
    if size_brand_parts:
        parts.append(" ".join(size_brand_parts))
    
    return " | ".join(parts) if parts else "Unknown"


def format_product_display_from_row(row: Union[pd.Series, Dict]) -> str:
    """
    Format product display from DataFrame row or dict
    
    Args:
        row: DataFrame row or dict with product fields
    
    Returns:
        Formatted product display string
    """
    if isinstance(row, pd.Series):
        row = row.to_dict()
    
    return format_product_display(
        pt_code=row.get('pt_code'),
        legacy_pt_code=row.get('legacy_pt_code'),
        product_name=row.get('product_name') or row.get('name'),
        package_size=row.get('package_size'),
        brand_name=row.get('brand_name')
    )