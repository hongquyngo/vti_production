# utils/production/orders/common.py
"""
Common utilities for Orders domain
Formatting, validation, UI helpers, and date utilities

Version: 1.1.0
Changes:
- v1.1.0: Enhanced date filter presets
          + get_date_filter_presets() with include_future param
          + get_default_date_range() for dynamic defaults based on date_type
          + Added future presets: Next 7/14/30 Days
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

class OrderConstants:
    """Order-specific constants"""
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    QUANTITY_DECIMALS = 4
    CURRENCY_DECIMALS = 0  # VND
    
    # Order statuses
    STATUS_DRAFT = 'DRAFT'
    STATUS_CONFIRMED = 'CONFIRMED'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CANCELLED = 'CANCELLED'
    
    # Priorities
    PRIORITY_LOW = 'LOW'
    PRIORITY_NORMAL = 'NORMAL'
    PRIORITY_HIGH = 'HIGH'
    PRIORITY_URGENT = 'URGENT'
    
    # Editable statuses
    EDITABLE_STATUSES = [STATUS_DRAFT, STATUS_CONFIRMED]
    CONFIRMABLE_STATUSES = [STATUS_DRAFT]
    CANCELLABLE_STATUSES = [STATUS_DRAFT, STATUS_CONFIRMED]


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


def format_currency(value: Union[int, float, Decimal, None],
                   currency: str = "VND") -> str:
    """Format currency value"""
    if pd.isna(value) or value is None:
        value = 0
    
    decimal_places = 0 if currency == "VND" else 2
    formatted = format_number(value, decimal_places)
    
    if currency == "VND":
        return f"{formatted} ₫"
    elif currency == "USD":
        return f"${formatted}"
    else:
        return f"{formatted} {currency}"


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
        'IN_PROGRESS': '🔄 In Progress',
        'COMPLETED': '✔️ Completed',
        'CANCELLED': '❌ Cancelled',
        'LOW': '🔵 Low',
        'NORMAL': '🟡 Normal',
        'HIGH': '🟠 High',
        'URGENT': '🔴 Urgent',
        'SUFFICIENT': '✅ Sufficient',
        'PARTIAL': '⚠️ Partial',
        'INSUFFICIENT': '❌ Insufficient',
        'PENDING': '⏳ Pending',
        'ISSUED': '✅ Issued',
    }
    
    return status_icons.get(status.upper(), f"⚪ {status}")


def get_status_color(status: str) -> str:
    """Get color for status badge"""
    colors = {
        'DRAFT': 'gray',
        'CONFIRMED': 'blue',
        'IN_PROGRESS': 'orange',
        'COMPLETED': 'green',
        'CANCELLED': 'red',
        'LOW': 'blue',
        'NORMAL': 'yellow',
        'HIGH': 'orange',
        'URGENT': 'red',
    }
    return colors.get(status.upper(), 'gray')


# ==================== Date Helpers ====================

def get_date_filter_presets(include_future: bool = True) -> Dict[str, Tuple[date, date]]:
    """
    Get common date filter presets
    
    Args:
        include_future: If True, include future date presets (for scheduled date filtering)
    
    Returns:
        Dictionary of preset name to (from_date, to_date) tuple
    """
    today = get_vietnam_today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    first_of_last_month = last_month_end.replace(day=1)
    
    # Calculate end of current month
    if today.month == 12:
        next_month_first = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_first = today.replace(month=today.month + 1, day=1)
    end_of_month = next_month_first - timedelta(days=1)
    
    # Calculate end of next week (Sunday)
    days_until_sunday = 6 - today.weekday()
    end_of_week = today + timedelta(days=days_until_sunday)
    
    presets = {
        "Today": (today, today),
        "This Week": (today - timedelta(days=today.weekday()), end_of_week),
        "This Month": (first_of_month, end_of_month),
    }
    
    if include_future:
        # Future presets (for scheduled date)
        presets.update({
            "Next 7 Days": (today, today + timedelta(days=6)),
            "Next 14 Days": (today, today + timedelta(days=13)),
            "Next 30 Days": (today, today + timedelta(days=29)),
        })
    
    # Past presets
    presets.update({
        "Yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "Last 7 Days": (today - timedelta(days=6), today),
        "Last 30 Days": (today - timedelta(days=29), today),
        "Last Week": (today - timedelta(days=today.weekday() + 7), 
                     today - timedelta(days=today.weekday() + 1)),
        "Last Month": (first_of_last_month, last_month_end),
    })
    
    return presets


def get_default_date_range(date_type: str = 'scheduled') -> Tuple[date, date]:
    """
    Get default date range based on date type
    
    Args:
        date_type: 'scheduled' or 'order'
        
    Returns:
        Tuple of (from_date, to_date)
    """
    today = get_vietnam_today()
    
    if date_type == 'scheduled':
        # For scheduled date: Today → +30 days (looking forward)
        return (today, today + timedelta(days=29))
    else:
        # For order date: First of last month → Today (looking back)
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        first_of_last_month = last_month_end.replace(day=1)
        return (first_of_last_month, today)


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

class OrderValidator:
    """Order form validation helpers"""
    
    @staticmethod
    def validate_create_order(order_data: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate create order form data
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        required_fields = [
            'bom_header_id', 'product_id', 'planned_qty',
            'warehouse_id', 'target_warehouse_id', 'scheduled_date'
        ]
        
        for field in required_fields:
            if field not in order_data or order_data[field] is None:
                return False, f"Missing required field: {field}"
        
        if order_data['planned_qty'] <= 0:
            return False, "Planned quantity must be positive"
        
        if order_data['warehouse_id'] == order_data['target_warehouse_id']:
            logger.warning("Source and target warehouse are the same")
        
        return True, None
    
    @staticmethod
    def validate_update_order(order_data: Dict, current_status: str) -> Tuple[bool, Optional[str]]:
        """Validate update order form data"""
        if current_status not in OrderConstants.EDITABLE_STATUSES:
            return False, f"Cannot edit order with status: {current_status}"
        
        if 'planned_qty' in order_data and order_data['planned_qty'] <= 0:
            return False, "Planned quantity must be positive"
        
        return True, None
    
    @staticmethod
    def can_confirm(status: str) -> bool:
        """Check if order can be confirmed"""
        return status in OrderConstants.CONFIRMABLE_STATUSES
    
    @staticmethod
    def can_cancel(status: str) -> bool:
        """Check if order can be cancelled"""
        return status in OrderConstants.CANCELLABLE_STATUSES
    
    @staticmethod
    def can_edit(status: str) -> bool:
        """Check if order can be edited"""
        return status in OrderConstants.EDITABLE_STATUSES


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


def format_product_display(row, bold_name: bool = False) -> str:
    """
    Format product/material display with unified format:
    PT_CODE (LEGACY_CODE or NEW) | NAME | PKG_SIZE (BRAND)
    
    Args:
        row: Dict or Series with product fields
        bold_name: If True, wrap name in ** for markdown bold
        
    Returns:
        Formatted string
        
    Example:
        PT001 (OLD001) | Sản phẩm A | 500g (BrandX)
        PT002 (NEW) | Sản phẩm B | 1kg (BrandY)
    """
    # Get fields - support both 'name' and 'material_name'/'product_name'
    pt_code = row.get('pt_code', '') or ''
    legacy_code = row.get('legacy_pt_code', '') or ''
    name = row.get('material_name') or row.get('product_name') or row.get('name', 'Unknown')
    package_size = row.get('package_size', '') or ''
    brand = row.get('brand_name', '') or ''
    
    parts = []
    
    # Part 1: PT_CODE (LEGACY_CODE or NEW)
    if pt_code:
        legacy_display = legacy_code if legacy_code else 'NEW'
        parts.append(f"{pt_code} ({legacy_display})")
    
    # Part 2: NAME (with optional bold)
    if bold_name:
        parts.append(f"**{name}**")
    else:
        parts.append(name)
    
    # Part 3: PKG_SIZE (BRAND)
    if package_size or brand:
        size_brand = package_size if package_size else ''
        if brand:
            size_brand = f"{size_brand} ({brand})" if size_brand else f"({brand})"
        if size_brand:
            parts.append(size_brand)
    
    return " | ".join(parts)


def format_material_display(row) -> str:
    """
    Format material display - wrapper for format_product_display
    Kept for backward compatibility
    """
    return format_product_display(row, bold_name=False)


def format_product_display_html(row) -> str:
    """
    Format product/material for HTML/PDF with line breaks:
    <b>NAME</b><br/>
    Code: PT_CODE (LEGACY)<br/>
    Size: PKG_SIZE | Brand: BRAND
    
    Args:
        row: Dict or Series with product fields
        
    Returns:
        HTML formatted string for PDF
    """
    pt_code = row.get('pt_code', '') or ''
    legacy_code = row.get('legacy_pt_code', '') or ''
    name = row.get('material_name') or row.get('product_name') or row.get('name', 'Unknown')
    package_size = row.get('package_size', '') or ''
    brand = row.get('brand_name', '') or ''
    
    lines = [f"<b>{name}</b>"]
    
    # Code line
    if pt_code:
        legacy_display = legacy_code if legacy_code else 'NEW'
        lines.append(f"Code: {pt_code} ({legacy_display})")
    
    # Size & Brand line
    size_brand_parts = []
    if package_size:
        size_brand_parts.append(f"Size: {package_size}")
    if brand:
        size_brand_parts.append(f"Brand: {brand}")
    if size_brand_parts:
        lines.append(" | ".join(size_brand_parts))
    
    return "<br/>".join(lines)