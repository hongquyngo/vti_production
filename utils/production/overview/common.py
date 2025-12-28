# utils/production/overview/common.py
"""
Common utilities for Production Overview domain
Constants, health calculation, formatters, date utilities

Version: 1.0.0
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union, Optional, List, Any
from io import BytesIO
from enum import Enum

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

class OverviewConstants:
    """Overview-specific constants"""
    DEFAULT_PAGE_SIZE = 15
    MAX_PAGE_SIZE = 100
    QUANTITY_DECIMALS = 2
    PERCENTAGE_DECIMALS = 1
    
    # Health thresholds
    HEALTH_GOOD_THRESHOLD = 95  # >= 95% is good
    HEALTH_WARNING_THRESHOLD = 80  # >= 80% is warning, < 80% is critical
    
    # Date presets
    DATE_PRESET_THIS_WEEK = 'this_week'
    DATE_PRESET_THIS_MONTH = 'this_month'
    DATE_PRESET_CUSTOM = 'custom'


class HealthStatus(Enum):
    """Health status enumeration"""
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    DELAYED = "DELAYED"
    NOT_STARTED = "NOT_STARTED"


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


# ==================== Date Preset Helpers ====================

def get_date_presets() -> Dict[str, Tuple[date, date]]:
    """
    Get date range presets
    
    Returns:
        Dictionary with preset name -> (from_date, to_date)
    """
    today = get_vietnam_today()
    
    # This week (Monday to Sunday)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    # This month
    month_start = today.replace(day=1)
    # Last day of month
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    
    return {
        OverviewConstants.DATE_PRESET_THIS_WEEK: (week_start, week_end),
        OverviewConstants.DATE_PRESET_THIS_MONTH: (month_start, month_end),
    }


def get_preset_label(preset: str) -> str:
    """Get display label for date preset"""
    labels = {
        OverviewConstants.DATE_PRESET_THIS_WEEK: "📅 This Week",
        OverviewConstants.DATE_PRESET_THIS_MONTH: "📆 This Month",
        OverviewConstants.DATE_PRESET_CUSTOM: "🔧 Custom Range",
    }
    return labels.get(preset, preset)


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


def format_percentage(value: Union[int, float, None], decimal_places: int = 1) -> str:
    """Format percentage value"""
    if pd.isna(value) or value is None:
        return "0%"
    
    try:
        return f"{round(float(value), decimal_places)}%"
    except:
        return "0%"


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


# ==================== Health Calculation ====================

def calculate_health_status(
    material_percentage: float,
    schedule_variance_days: int,
    quality_percentage: Optional[float] = None,
    status: str = ''
) -> HealthStatus:
    """
    Calculate health status based on multiple factors
    
    Args:
        material_percentage: (issued_qty / required_qty) * 100
        schedule_variance_days: estimated_end - scheduled_date (negative = ahead, positive = behind)
        quality_percentage: (passed_qty / total_receipts) * 100, None if no receipts yet
        status: Order status (DRAFT, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED)
    
    Returns:
        HealthStatus enum value
    """
    # Not started yet
    if status in ['DRAFT', 'CONFIRMED']:
        return HealthStatus.NOT_STARTED
    
    # Completed orders
    if status == 'COMPLETED':
        return HealthStatus.ON_TRACK
    
    # Cancelled orders
    if status == 'CANCELLED':
        return HealthStatus.DELAYED
    
    # IN_PROGRESS - evaluate health
    threshold_good = OverviewConstants.HEALTH_GOOD_THRESHOLD
    threshold_warning = OverviewConstants.HEALTH_WARNING_THRESHOLD
    
    # Material score
    material_ok = material_percentage >= threshold_warning
    material_good = material_percentage >= threshold_good
    
    # Schedule score (allow 1 day buffer for "good")
    schedule_ok = schedule_variance_days <= 2
    schedule_good = schedule_variance_days <= 0
    
    # Quality score (if available)
    if quality_percentage is not None:
        quality_ok = quality_percentage >= threshold_warning
        quality_good = quality_percentage >= threshold_good
    else:
        quality_ok = True
        quality_good = True
    
    # Determine overall health
    if material_good and schedule_good and quality_good:
        return HealthStatus.ON_TRACK
    elif material_ok and schedule_ok and quality_ok:
        return HealthStatus.AT_RISK
    else:
        return HealthStatus.DELAYED


def get_health_indicator(health: Union[HealthStatus, str]) -> str:
    """Get health status indicator with emoji"""
    if isinstance(health, str):
        health = HealthStatus(health) if health in [h.value for h in HealthStatus] else HealthStatus.NOT_STARTED
    
    indicators = {
        HealthStatus.ON_TRACK: "🟢 On Track",
        HealthStatus.AT_RISK: "🟡 At Risk",
        HealthStatus.DELAYED: "🔴 Delayed",
        HealthStatus.NOT_STARTED: "⚪ Not Started",
    }
    return indicators.get(health, "⚪ Unknown")


def get_health_color(health: Union[HealthStatus, str]) -> str:
    """Get color for health status"""
    if isinstance(health, str):
        health = HealthStatus(health) if health in [h.value for h in HealthStatus] else HealthStatus.NOT_STARTED
    
    colors = {
        HealthStatus.ON_TRACK: "green",
        HealthStatus.AT_RISK: "orange",
        HealthStatus.DELAYED: "red",
        HealthStatus.NOT_STARTED: "gray",
    }
    return colors.get(health, "gray")


# ==================== Status Indicators ====================

def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        'DRAFT': '📝 Draft',
        'CONFIRMED': '✅ Confirmed',
        'IN_PROGRESS': '🔄 In Progress',
        'COMPLETED': '✔️ Completed',
        'CANCELLED': '❌ Cancelled',
        'PENDING': '⏳ Pending',
        'PASSED': '✅ Passed',
        'FAILED': '❌ Failed',
    }
    return status_icons.get(status.upper() if status else '', f"⚪ {status}")


def create_progress_bar_html(percentage: float, width: int = 100) -> str:
    """
    Create HTML progress bar
    
    Args:
        percentage: Progress percentage (0-100)
        width: Bar width in pixels
    
    Returns:
        HTML string for progress bar
    """
    percentage = min(100, max(0, percentage))
    
    # Color based on percentage
    if percentage >= 100:
        color = "#28a745"  # Green
    elif percentage >= 75:
        color = "#17a2b8"  # Blue
    elif percentage >= 50:
        color = "#ffc107"  # Yellow
    else:
        color = "#dc3545"  # Red
    
    return f"""
    <div style="background-color: #e9ecef; border-radius: 4px; width: {width}px; height: 20px; display: inline-block; vertical-align: middle;">
        <div style="background-color: {color}; width: {percentage}%; height: 100%; border-radius: 4px; text-align: center; color: white; font-size: 11px; line-height: 20px;">
            {percentage:.0f}%
        </div>
    </div>
    """


# ==================== Date Formatting ====================

def format_date(dt: Union[date, datetime, str, None], fmt: str = '%d/%m/%Y') -> str:
    """Format date to string"""
    if dt is None or pd.isna(dt):
        return '-'
    
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d').date()
        except ValueError:
            try:
                dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S').date()
            except ValueError:
                return dt
    
    if isinstance(dt, datetime):
        dt = dt.date()
    
    return dt.strftime(fmt)


def format_datetime_vn(dt: Union[datetime, str, None], fmt: str = '%d/%m/%Y %H:%M') -> str:
    """Format datetime in Vietnam timezone"""
    if dt is None or pd.isna(dt):
        return '-'
    
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(dt, '%Y-%m-%d')
            except ValueError:
                return dt
    
    return dt.strftime(fmt)


def calculate_days_variance(scheduled_date: Union[date, datetime, str, None],
                           estimated_date: Union[date, datetime, str, None] = None) -> int:
    """
    Calculate days variance between scheduled and estimated/actual date
    
    Args:
        scheduled_date: Original planned date
        estimated_date: Estimated completion date (default: today)
    
    Returns:
        Days variance (negative = ahead, positive = behind)
    """
    if scheduled_date is None or pd.isna(scheduled_date):
        return 0
    
    # Parse scheduled_date
    if isinstance(scheduled_date, str):
        try:
            scheduled_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        except ValueError:
            return 0
    elif isinstance(scheduled_date, datetime):
        scheduled_date = scheduled_date.date()
    
    # Parse estimated_date or use today
    if estimated_date is None or pd.isna(estimated_date):
        estimated_date = get_vietnam_today()
    elif isinstance(estimated_date, str):
        try:
            estimated_date = datetime.strptime(estimated_date, '%Y-%m-%d').date()
        except ValueError:
            estimated_date = get_vietnam_today()
    elif isinstance(estimated_date, datetime):
        estimated_date = estimated_date.date()
    
    return (estimated_date - scheduled_date).days


def get_variance_display(days: int) -> str:
    """Get display string for days variance"""
    if days == 0:
        return "On time"
    elif days < 0:
        return f"↑ {abs(days)}d ahead"
    else:
        return f"↓ {days}d behind"


# ==================== Product Display ====================

def format_product_display(row) -> str:
    """
    Format product display with unified format:
    PT_CODE (LEGACY_CODE or NEW) | NAME | PKG_SIZE (BRAND)
    
    Args:
        row: Dict or Series with product fields
        
    Returns:
        Formatted string
    """
    pt_code = row.get('pt_code', '') or ''
    legacy_code = row.get('legacy_pt_code', '') or ''
    name = row.get('product_name') or row.get('name', 'Unknown')
    package_size = row.get('package_size', '') or ''
    brand = row.get('brand_name', '') or ''
    
    parts = []
    
    # Part 1: PT_CODE (LEGACY_CODE or NEW)
    if pt_code:
        legacy_display = legacy_code if legacy_code else 'NEW'
        parts.append(f"{pt_code} ({legacy_display})")
    
    # Part 2: NAME
    parts.append(name)
    
    # Part 3: PKG_SIZE (BRAND)
    if package_size or brand:
        size_brand = package_size if package_size else ''
        if brand:
            size_brand = f"{size_brand} ({brand})" if size_brand else f"({brand})"
        if size_brand:
            parts.append(size_brand)
    
    return " | ".join(parts)


# ==================== Excel Export ====================

def export_to_excel(dataframes: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
                   include_index: bool = False) -> bytes:
    """Export DataFrame(s) to Excel"""
    output = BytesIO()
    
    if isinstance(dataframes, pd.DataFrame):
        dataframes = {"Overview": dataframes}
    
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            for sheet_name, df in dataframes.items():
                safe_name = sheet_name[:31].replace('[', '').replace(']', '')
                df.to_excel(writer, sheet_name=safe_name, index=include_index)
                
                # Auto-adjust column widths
                worksheet = writer.sheets[safe_name]
                for idx, col in enumerate(df.columns):
                    max_len = max(
                        df[col].astype(str).map(len).max() if len(df) > 0 else 0,
                        len(str(col))
                    ) + 2
                    worksheet.set_column(idx, idx, min(max_len, 50))
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


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
