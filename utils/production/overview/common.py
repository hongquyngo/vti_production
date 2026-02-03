# utils/production/overview/common.py
"""
Common utilities for Production Overview domain
Constants, health calculation, formatters, date utilities, chart helpers

Version: 5.0.0
Changes:
- v5.0.0: Updated for new issue detail structure (1 row = 1 issue detail)
          - Removed unused formatters for old aggregated view
          - Kept health calculation, product display, and chart helpers
- v4.0.0: Simplified for single Production Data table
          - Removed format_material_stage_display (no longer needed)
          - Kept other formatters and chart helpers
- v3.0.0: Updated format_material_stage_display to use gross/net fields correctly
- v2.0.0: Added chart helpers for Plotly, lifecycle formatters
- v1.0.0: Initial version
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union, Optional, List, Any
from io import BytesIO
from enum import Enum

import pandas as pd
import streamlit as st

# Plotly for charts
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logging.warning("Plotly not available. Charts will be disabled.")

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


class DateType(Enum):
    """Date type for filtering and pivot grouping"""
    ORDER_DATE = "order_date"
    SCHEDULED_DATE = "scheduled_date"
    COMPLETION_DATE = "completion_date"
    RECEIPT_DATE = "receipt_date"


class PeriodType(Enum):
    """Time period for pivot grouping"""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class DimensionType(Enum):
    """Dimension (row) for pivot grouping"""
    MO_NUMBER = "mo_number"
    OUTPUT_PRODUCT = "output_product"
    BRAND = "brand"
    BOM_TYPE = "bom_type"
    SOURCE_WAREHOUSE = "source_warehouse"
    TARGET_WAREHOUSE = "target_warehouse"
    ORDER_STATUS = "order_status"
    PRIORITY = "priority"
    ENTITY = "entity"
    QC_STATUS = "qc_status"


class MeasureType(Enum):
    """Measure (value) for pivot aggregation"""
    MO_COUNT = "mo_count"
    PLANNED_QTY = "planned_qty"
    PRODUCED_QTY = "produced_qty"
    RECEIPT_QTY = "receipt_qty"
    QC_PASSED_QTY = "qc_passed_qty"
    QC_FAILED_QTY = "qc_failed_qty"
    QC_PENDING_QTY = "qc_pending_qty"
    YIELD_PCT = "yield_pct"
    PASS_RATE_PCT = "pass_rate_pct"


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


# ==================== Pivot / Date Type Helpers ====================

DATE_TYPE_LABELS = {
    DateType.ORDER_DATE: "📅 Order Date",
    DateType.SCHEDULED_DATE: "📆 Scheduled Date",
    DateType.COMPLETION_DATE: "✅ Completion Date",
    DateType.RECEIPT_DATE: "📦 Receipt Date",
}

PERIOD_LABELS = {
    PeriodType.DAY: "Day",
    PeriodType.WEEK: "Week",
    PeriodType.MONTH: "Month",
}

DIMENSION_LABELS = {
    DimensionType.MO_NUMBER: "MO Number",
    DimensionType.OUTPUT_PRODUCT: "Output Product",
    DimensionType.BRAND: "Brand",
    DimensionType.BOM_TYPE: "BOM Type",
    DimensionType.SOURCE_WAREHOUSE: "Source Warehouse",
    DimensionType.TARGET_WAREHOUSE: "Target Warehouse",
    DimensionType.ORDER_STATUS: "Order Status",
    DimensionType.PRIORITY: "Priority",
    DimensionType.ENTITY: "Entity (Company)",
    DimensionType.QC_STATUS: "QC Status",
}

MEASURE_LABELS = {
    MeasureType.MO_COUNT: "MO Count",
    MeasureType.PLANNED_QTY: "Planned Qty",
    MeasureType.PRODUCED_QTY: "Produced Qty",
    MeasureType.RECEIPT_QTY: "Receipt Qty",
    MeasureType.QC_PASSED_QTY: "QC Passed Qty",
    MeasureType.QC_FAILED_QTY: "QC Failed Qty",
    MeasureType.QC_PENDING_QTY: "QC Pending Qty",
    MeasureType.YIELD_PCT: "Yield %",
    MeasureType.PASS_RATE_PCT: "Pass Rate %",
}

# Measures available per date type category
MO_LEVEL_MEASURES = [
    MeasureType.MO_COUNT,
    MeasureType.PLANNED_QTY,
    MeasureType.PRODUCED_QTY,
    MeasureType.YIELD_PCT,
]

RECEIPT_LEVEL_MEASURES = [
    MeasureType.MO_COUNT,
    MeasureType.RECEIPT_QTY,
    MeasureType.QC_PASSED_QTY,
    MeasureType.QC_FAILED_QTY,
    MeasureType.QC_PENDING_QTY,
    MeasureType.PASS_RATE_PCT,
]

# Dimensions available per date type
MO_LEVEL_DIMENSIONS = [
    DimensionType.MO_NUMBER,
    DimensionType.OUTPUT_PRODUCT,
    DimensionType.BRAND,
    DimensionType.BOM_TYPE,
    DimensionType.SOURCE_WAREHOUSE,
    DimensionType.TARGET_WAREHOUSE,
    DimensionType.ORDER_STATUS,
    DimensionType.PRIORITY,
    DimensionType.ENTITY,
]

RECEIPT_LEVEL_DIMENSIONS = MO_LEVEL_DIMENSIONS + [DimensionType.QC_STATUS]


def get_date_type_label(dt: DateType) -> str:
    """Get display label for date type"""
    return DATE_TYPE_LABELS.get(dt, str(dt.value))


def get_measures_for_date_type(date_type: str) -> List[MeasureType]:
    """Get available measures for a given date type"""
    if date_type == DateType.RECEIPT_DATE.value:
        return RECEIPT_LEVEL_MEASURES
    return MO_LEVEL_MEASURES


def get_dimensions_for_date_type(date_type: str) -> List[DimensionType]:
    """Get available dimensions for a given date type"""
    if date_type == DateType.RECEIPT_DATE.value:
        return RECEIPT_LEVEL_DIMENSIONS
    return MO_LEVEL_DIMENSIONS


def get_date_type_info_note(date_type: str) -> Optional[str]:
    """Get info note for specific date types"""
    notes = {
        DateType.COMPLETION_DATE.value: "ℹ️ Showing only completed orders (orders without completion date are excluded)",
        DateType.RECEIPT_DATE.value: "ℹ️ Showing orders with production receipts in selected period",
    }
    return notes.get(date_type)


def format_period_label(period_key: str, period_type: str) -> str:
    """
    Format period key into display label
    
    Args:
        period_key: Raw period key from SQL (e.g. '2026-02', '2026-02-03', '2026-01-27')
        period_type: PeriodType value
    
    Returns:
        Formatted label
    """
    from datetime import datetime as dt_cls
    try:
        if period_type == PeriodType.MONTH.value:
            # '2026-02' → 'Feb 2026'
            d = dt_cls.strptime(period_key, '%Y-%m')
            return d.strftime('%b %Y')
        elif period_type == PeriodType.WEEK.value:
            # '2026-01-27' (Monday) → 'W05 (27 Jan)'
            d = dt_cls.strptime(period_key, '%Y-%m-%d')
            week_num = d.isocalendar()[1]
            return f"W{week_num:02d} ({d.strftime('%d %b')})"
        elif period_type == PeriodType.DAY.value:
            # '2026-02-03' → '03 Feb'
            d = dt_cls.strptime(period_key, '%Y-%m-%d')
            return d.strftime('%d %b')
    except (ValueError, TypeError):
        pass
    return str(period_key)


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


# ==================== Lifecycle Display Formatters ====================

def format_schedule_display(row) -> str:
    """
    Format schedule info for lifecycle table
    Returns: "25→28 Dec\n✅ On time" or "25→28 Dec\n⚠️ +2d"
    """
    order_date = row.get('order_date')
    scheduled_date = row.get('scheduled_date')
    completion_date = row.get('completion_date')
    status = row.get('status', '')
    variance = row.get('schedule_variance_days', 0) or 0
    
    # Format dates
    start = format_date(order_date, '%d-%b') if order_date else '?'
    end = format_date(scheduled_date, '%d-%b') if scheduled_date else '?'
    
    date_range = f"{start} → {end}"
    
    # Status indicator
    if status == 'COMPLETED':
        if completion_date:
            actual_end = format_date(completion_date, '%d-%b')
            indicator = f"✅ Done {actual_end}"
        else:
            indicator = "✅ Completed"
    elif status == 'CANCELLED':
        indicator = "❌ Cancelled"
    elif status in ['DRAFT', 'CONFIRMED']:
        days_to_start = calculate_days_variance(order_date)
        if days_to_start < 0:
            indicator = f"🕐 Starts in {abs(days_to_start)}d"
        else:
            indicator = "🕐 Not started"
    elif status == 'IN_PROGRESS':
        if variance <= 0:
            if variance == 0:
                indicator = "✅ On time"
            else:
                indicator = f"✅ {abs(variance)}d ahead"
        elif variance <= 2:
            indicator = f"⚠️ +{variance}d"
        else:
            indicator = f"🔴 +{variance}d behind"
    else:
        indicator = ""
    
    return f"{date_range}\n{indicator}"


def format_material_stage_display(row) -> str:
    """
    Format material stage info for lifecycle table
    Returns: "████ 95%\nNet:500/500\n↩️ 15 (actual)"
    
    SIMPLIFIED APPROACH (no conversion_ratio stored):
    - NET = issued_qty (equivalent, accurate)
    - RETURNED = actual quantity returned
    - material_percentage = NET / Required (accurate for fulfillment)
    """
    net_issued = row.get('total_material_net_issued', 0) or 0
    required = row.get('total_material_required', 0) or 0
    returned_actual = row.get('total_returned_actual', 0) or 0
    material_pct = row.get('material_percentage', 0) or 0  # Based on NET
    
    # Progress bar (text-based) - based on NET issue percentage
    filled = int(material_pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    # Detail line: Net/Required
    detail = f"Net:{format_number(net_issued, 0)}/{format_number(required, 0)}"
    
    # Return line (actual units returned)
    if returned_actual > 0:
        return_line = f"↩️{format_number(returned_actual, 0)}"
    else:
        return_line = ""
    
    lines = [f"{bar} {material_pct:.0f}%", detail]
    if return_line:
        lines.append(return_line)
    
    return "\n".join(lines)


def format_production_stage_display(row) -> str:
    """
    Format production stage info for lifecycle table
    Returns: "████░ 80%\n800/1000 PCS\n📦 3 receipts"
    """
    produced = row.get('produced_qty', 0) or 0
    planned = row.get('planned_qty', 0) or 0
    progress_pct = row.get('progress_percentage', 0) or 0
    total_receipts = row.get('total_receipts', 0) or 0
    uom = row.get('uom', '')
    status = row.get('status', '')
    
    # Progress bar (text-based)
    filled = int(progress_pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    # Detail line
    detail = f"{format_number(produced, 0)}/{format_number(planned, 0)} {uom}"
    
    # Receipt line
    if status in ['DRAFT', 'CONFIRMED']:
        receipt_line = "Not started"
    elif total_receipts > 0:
        receipt_line = f"📦 {total_receipts} receipt{'s' if total_receipts > 1 else ''}"
    else:
        receipt_line = "📦 No receipts"
    
    return f"{bar} {progress_pct:.0f}%\n{detail}\n{receipt_line}"


def format_qc_stage_display(row) -> str:
    """
    Format QC stage info for lifecycle table
    Returns: "✅ 95%\nP:760 F:40"
    """
    passed = row.get('passed_qty', 0) or 0
    failed = row.get('failed_qty', 0) or 0
    pending = row.get('pending_qty', 0) or 0
    quality_pct = row.get('quality_percentage')
    total_receipts = row.get('total_receipts', 0) or 0
    status = row.get('status', '')
    
    if status in ['DRAFT', 'CONFIRMED'] or total_receipts == 0:
        return "-\nNo QC yet"
    
    # QC indicator
    if quality_pct is None:
        indicator = "⏳ Pending"
        pct_display = ""
    elif quality_pct >= 95:
        indicator = "✅"
        pct_display = f"{quality_pct:.0f}%"
    elif quality_pct >= 80:
        indicator = "⚠️"
        pct_display = f"{quality_pct:.0f}%"
    else:
        indicator = "❌"
        pct_display = f"{quality_pct:.0f}%"
    
    # Breakdown line
    breakdown_parts = []
    if passed > 0:
        breakdown_parts.append(f"P:{format_number(passed, 0)}")
    if failed > 0:
        breakdown_parts.append(f"F:{format_number(failed, 0)}")
    if pending > 0:
        breakdown_parts.append(f"?:{format_number(pending, 0)}")
    
    breakdown = " ".join(breakdown_parts) if breakdown_parts else "-"
    
    return f"{indicator} {pct_display}\n{breakdown}"


# ==================== Chart Helpers (Plotly) ====================

def create_yield_by_product_chart(df: pd.DataFrame) -> Optional[go.Figure]:
    """
    Create bar chart showing yield rate by product
    
    Args:
        df: DataFrame with product_name, yield_rate columns
    
    Returns:
        Plotly figure or None if Plotly not available
    """
    if not PLOTLY_AVAILABLE or df.empty:
        return None
    
    # Aggregate by product
    product_yield = df.groupby('product_name').agg({
        'produced_qty': 'sum',
        'planned_qty': 'sum'
    }).reset_index()
    
    product_yield['yield_rate'] = (
        product_yield['produced_qty'] / product_yield['planned_qty'] * 100
    ).round(1)
    
    # Sort by yield rate
    product_yield = product_yield.sort_values('yield_rate', ascending=True).tail(10)
    
    # Create color based on yield
    colors = product_yield['yield_rate'].apply(
        lambda x: '#28a745' if x >= 95 else ('#ffc107' if x >= 80 else '#dc3545')
    )
    
    fig = go.Figure(data=[
        go.Bar(
            x=product_yield['yield_rate'],
            y=product_yield['product_name'],
            orientation='h',
            marker_color=colors,
            text=product_yield['yield_rate'].apply(lambda x: f'{x:.1f}%'),
            textposition='outside'
        )
    ])
    
    fig.update_layout(
        title='Yield Rate by Product',
        xaxis_title='Yield Rate (%)',
        yaxis_title='',
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(range=[0, 120]),
        showlegend=False
    )
    
    return fig


def create_schedule_performance_chart(df: pd.DataFrame) -> Optional[go.Figure]:
    """
    Create donut chart showing schedule performance
    
    Args:
        df: DataFrame with schedule_variance_days, status columns
    
    Returns:
        Plotly figure or None if Plotly not available
    """
    if not PLOTLY_AVAILABLE or df.empty:
        return None
    
    # Filter to IN_PROGRESS and COMPLETED only
    active_df = df[df['status'].isin(['IN_PROGRESS', 'COMPLETED'])]
    
    if active_df.empty:
        return None
    
    # Categorize
    on_time = len(active_df[active_df['schedule_variance_days'] <= 0])
    slight_delay = len(active_df[(active_df['schedule_variance_days'] > 0) & 
                                  (active_df['schedule_variance_days'] <= 2)])
    delayed = len(active_df[active_df['schedule_variance_days'] > 2])
    
    labels = ['On Time / Ahead', 'Slight Delay (1-2d)', 'Delayed (>2d)']
    values = [on_time, slight_delay, delayed]
    colors = ['#28a745', '#ffc107', '#dc3545']
    
    # Filter out zeros
    data = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not data:
        return None
    
    labels, values, colors = zip(*data)
    
    fig = go.Figure(data=[
        go.Pie(
            labels=labels,
            values=values,
            hole=0.5,
            marker_colors=colors,
            textinfo='value+percent',
            textposition='outside'
        )
    ])
    
    fig.update_layout(
        title='Schedule Performance',
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=-0.2)
    )
    
    return fig


def create_material_efficiency_chart(df: pd.DataFrame) -> Optional[go.Figure]:
    """
    Create gauge/indicator chart for material efficiency
    
    Args:
        df: DataFrame with material_percentage columns
    
    Returns:
        Plotly figure or None if Plotly not available
    """
    if not PLOTLY_AVAILABLE or df.empty:
        return None
    
    # Calculate average material efficiency for IN_PROGRESS/COMPLETED orders
    active_df = df[df['status'].isin(['IN_PROGRESS', 'COMPLETED'])]
    
    if active_df.empty or active_df['material_percentage'].isna().all():
        return None
    
    avg_efficiency = active_df['material_percentage'].mean()
    
    # Determine color
    if avg_efficiency >= 95:
        color = '#28a745'
    elif avg_efficiency >= 80:
        color = '#ffc107'
    else:
        color = '#dc3545'
    
    fig = go.Figure(data=[
        go.Indicator(
            mode="gauge+number",
            value=avg_efficiency,
            number={'suffix': '%', 'font': {'size': 40}},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': color},
                'steps': [
                    {'range': [0, 80], 'color': '#ffebee'},
                    {'range': [80, 95], 'color': '#fff3e0'},
                    {'range': [95, 100], 'color': '#e8f5e9'}
                ],
                'threshold': {
                    'line': {'color': 'black', 'width': 2},
                    'thickness': 0.75,
                    'value': 95
                }
            },
            title={'text': 'Avg Material Efficiency'}
        )
    ])
    
    fig.update_layout(
        height=250,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    return fig


def create_health_summary_chart(df: pd.DataFrame) -> Optional[go.Figure]:
    """
    Create horizontal stacked bar showing health distribution
    
    Args:
        df: DataFrame with health_status column
    
    Returns:
        Plotly figure or None if Plotly not available
    """
    if not PLOTLY_AVAILABLE or df.empty:
        return None
    
    # Count by health status
    health_counts = df['health_status'].value_counts()
    
    on_track = health_counts.get('ON_TRACK', 0)
    at_risk = health_counts.get('AT_RISK', 0)
    delayed = health_counts.get('DELAYED', 0)
    not_started = health_counts.get('NOT_STARTED', 0)
    
    total = on_track + at_risk + delayed + not_started
    if total == 0:
        return None
    
    fig = go.Figure()
    
    categories = [
        ('On Track', on_track, '#28a745'),
        ('At Risk', at_risk, '#ffc107'),
        ('Delayed', delayed, '#dc3545'),
        ('Not Started', not_started, '#6c757d')
    ]
    
    for name, value, color in categories:
        if value > 0:
            fig.add_trace(go.Bar(
                x=[value],
                y=['Health'],
                orientation='h',
                name=name,
                marker_color=color,
                text=[f'{name}: {value}'],
                textposition='inside'
            ))
    
    fig.update_layout(
        barmode='stack',
        height=100,
        margin=dict(l=20, r=20, t=10, b=10),
        showlegend=True,
        legend=dict(orientation='h', yanchor='top', y=-0.5),
        xaxis=dict(showticklabels=False),
        yaxis=dict(showticklabels=False)
    )
    
    return fig