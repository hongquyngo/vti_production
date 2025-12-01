# utils/production/common.py
"""
Common utilities for Production module - REFACTORED v2.1
Formatting, validation, UI helpers, and date utilities

CHANGES v2.1:
- Added Vietnam timezone support (Asia/Ho_Chi_Minh)
- Added get_vietnam_now(), get_vietnam_today() helpers
- All date/time functions now use Vietnam timezone

CHANGES v2.0:
- Removed old confirm_action that causes page refresh issues
- Added inline_confirmation for better UX
- Added show_success_with_details for better feedback
- Enhanced status indicators and formatting
"""

import logging
from datetime import date, timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union, Optional, List, Any
from io import BytesIO
import time

import pandas as pd
import streamlit as st

# Timezone support - try zoneinfo (Python 3.9+) first, fallback to pytz
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


# ==================== Timezone Helpers ====================

def get_vietnam_now() -> datetime:
    """
    Get current datetime in Vietnam timezone (Asia/Ho_Chi_Minh)
    
    Returns:
        datetime: Current datetime in Vietnam timezone (UTC+7)
    """
    if VN_TIMEZONE:
        return datetime.now(VN_TIMEZONE)
    return datetime.now()


def get_vietnam_today() -> date:
    """
    Get current date in Vietnam timezone (Asia/Ho_Chi_Minh)
    
    Returns:
        date: Current date in Vietnam timezone (UTC+7)
    """
    if VN_TIMEZONE:
        return datetime.now(VN_TIMEZONE).date()
    return date.today()


def format_vietnam_datetime(dt: datetime, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """
    Format datetime to string in Vietnam timezone
    
    Args:
        dt: datetime object (can be naive or aware)
        fmt: strftime format string
        
    Returns:
        Formatted datetime string
    """
    if dt is None:
        return ''
    
    # If naive datetime and we have VN timezone, localize it
    if VN_TIMEZONE and dt.tzinfo is None:
        if hasattr(VN_TIMEZONE, 'localize'):
            # pytz style
            dt = VN_TIMEZONE.localize(dt)
        else:
            # zoneinfo style
            dt = dt.replace(tzinfo=VN_TIMEZONE)
    
    return dt.strftime(fmt)


# ==================== Constants ====================

class SystemConstants:
    """System constants"""
    DEFAULT_PAGE_SIZE = 100
    EXPIRY_WARNING_DAYS = 30
    MAX_SCRAP_RATE = 50.0
    QUANTITY_DECIMALS = 4
    CURRENCY_DECIMALS = 0  # VND
    SUCCESS_MESSAGE_DELAY = 2  # seconds to show success message


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


# ==================== Date Functions ====================

def get_date_filter_presets() -> Dict[str, Tuple[date, date]]:
    """Get common date filter presets using Vietnam timezone"""
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


# ==================== Enhanced UI Helpers v2.0 ====================

class UIHelpers:
    """Streamlit UI helper functions - REFACTORED v2.0"""
    
    @staticmethod
    def show_message(message: str, type: str = "info", duration: Optional[int] = None):
        """
        Show message in Streamlit with optional auto-clear
        
        Args:
            message: Message to display
            type: Message type (success, error, warning, info)
            duration: Optional seconds to show message before clearing
        """
        message_functions = {
            "success": st.success,
            "error": st.error,
            "warning": st.warning,
            "info": st.info
        }
        
        show_func = message_functions.get(type, st.info)
        msg_container = show_func(message)
        
        if duration:
            time.sleep(duration)
            msg_container.empty()
    
    @staticmethod
    def show_success_with_details(title: str, details: Dict[str, Any], 
                                  substitutions: Optional[List[Dict]] = None,
                                  auto_clear: bool = False):
        """
        Show detailed success message with optional substitutions
        
        Args:
            title: Main success message
            details: Dictionary of detail items to show
            substitutions: Optional list of substitution details
            auto_clear: Whether to clear message after delay
        """
        # Build success message
        message_parts = [f"✅ **{title}**", ""]
        
        for key, value in details.items():
            message_parts.append(f"• {key}: **{value}**")
        
        success_msg = st.success("\n".join(message_parts))
        
        # Show substitutions if any
        if substitutions:
            with st.expander(f"ℹ️ {len(substitutions)} Material Substitutions Made", expanded=True):
                for sub in substitutions:
                    st.write(
                        f"• {sub['original_material']} → **{sub['substitute_material']}** "
                        f"({format_number(sub['quantity'], 2)} {sub.get('uom', '')})"
                    )
        
        if auto_clear:
            time.sleep(SystemConstants.SUCCESS_MESSAGE_DELAY)
            success_msg.empty()
    

    @staticmethod
    def show_alternative_materials(materials_df: pd.DataFrame):
        """
        Display materials with alternatives in a nice format
        
        Args:
            materials_df: DataFrame with material availability including alternative_details
        """
        materials_with_alts = materials_df[
            (materials_df['availability_status'] != 'SUFFICIENT') & 
            (materials_df.get('has_alternatives', False) == True)
        ]
        
        if materials_with_alts.empty:
            return
        
        st.markdown("### 🔄 Alternative Materials Available")
        
        for _, mat in materials_with_alts.iterrows():
            shortage = mat['required_qty'] - mat['available_qty']
            
            # Create expander with status indicator
            status_icon = "✅" if mat.get('alternatives_sufficient', False) else "⚠️"
            
            with st.expander(
                f"{status_icon} {mat['material_name']} "
                f"({mat.get('pt_code', 'N/A')}) - Short by {format_number(shortage, 2)} {mat['uom']}"
            ):
                # Show primary material status
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Required", f"{format_number(mat['required_qty'], 2)} {mat['uom']}")
                with col2:
                    st.metric("Available", f"{format_number(mat['available_qty'], 2)} {mat['uom']}")
                with col3:
                    st.metric("Shortage", f"{format_number(shortage, 2)} {mat['uom']}", delta_color="inverse")
                
                # Show alternatives table if available
                if 'alternative_details' in mat and mat['alternative_details']:
                    st.markdown("**Available Alternatives:**")
                    
                    alt_data = []
                    for alt in mat['alternative_details']:
                        alt_data.append({
                            'Priority': alt['priority'],
                            'Material': alt['name'],
                            'PT Code': alt.get('pt_code', 'N/A'),
                            'Available': f"{format_number(alt['available'], 2)} {alt['uom']}",
                            'Status': '✅' if alt['status'] == 'SUFFICIENT' else '⚠️ Partial'
                        })
                    
                    alt_df = pd.DataFrame(alt_data)
                    st.dataframe(alt_df, use_container_width=True, hide_index=True)
                    
                    # Summary - only show if there are actual alternatives
                    total_alt_available = mat.get('alternative_total_qty', 0)
                    if total_alt_available > 0:
                        if mat.get('alternatives_sufficient', False):
                            st.success(
                                f"✅ Total from alternatives: {format_number(total_alt_available, 2)} {mat['uom']} "
                                f"(Sufficient to cover shortage)"
                            )
                        else:
                            st.warning(
                                f"⚠️ Total from alternatives: {format_number(total_alt_available, 2)} {mat['uom']} "
                                f"(Not sufficient - short by {format_number(shortage - total_alt_available, 2)} {mat['uom']})"
                            )
                    else:
                        st.info("ℹ️ No alternative materials available in stock")


def create_status_indicator(status: str) -> str:
    """Create status indicator with emoji"""
    status_icons = {
        'DRAFT': '📝',
        'CONFIRMED': '✅',
        'IN_PROGRESS': '🔄',
        'COMPLETED': '✔️',
        'CANCELLED': '❌',
        'ACTIVE': '🟢',
        'INACTIVE': '⭕',
        'PENDING': '⏳',
        'ISSUED': '✅',
        'PARTIAL': '⚠️',
        'LOW': '🔵',
        'NORMAL': '🟡',
        'HIGH': '🟠',
        'URGENT': '🔴',
        'GOOD': '✅',
        'DAMAGED': '⚠️',
        'EXPIRED': '❌'
    }
    
    icon = status_icons.get(status.upper(), '⚪')
    return f"{icon} {status}"


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
                # Sanitize sheet name (max 31 chars, no special chars)
                safe_name = sheet_name[:31].replace('[', '').replace(']', '')
                df.to_excel(writer, sheet_name=safe_name, index=include_index)
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


# ==================== Validation Helpers ====================

def validate_positive_number(value: Union[int, float], field_name: str) -> None:
    """Validate that a number is positive"""
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def validate_required_fields(data: Dict, required_fields: list) -> None:
    """Validate that required fields are present and not None"""
    missing = [field for field in required_fields 
               if field not in data or data[field] is None]
    
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


class FormValidator:
    """Production form validation helpers"""
    
    @staticmethod
    def validate_create_order(order_data: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate create order form data
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check required fields
        required_fields = [
            'bom_header_id', 'product_id', 'planned_qty',
            'warehouse_id', 'target_warehouse_id', 'scheduled_date'
        ]
        
        for field in required_fields:
            if field not in order_data or order_data[field] is None:
                return False, f"Missing required field: {field}"
        
        # Validate quantities
        if order_data['planned_qty'] <= 0:
            return False, "Planned quantity must be positive"
        
        # Validate warehouses
        if order_data['warehouse_id'] == order_data['target_warehouse_id']:
            logger.warning("Source and target warehouse are the same")
            # This is a warning, not an error
        
        return True, None