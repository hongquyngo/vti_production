# utils/production/completions/common.py
"""
Common utilities for Completions domain
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
    def validate_produced_qty(produced_qty: float, 
                             planned_qty: float,
                             current_produced: float) -> Tuple[bool, Optional[str]]:
        """Validate produced quantity"""
        if produced_qty <= 0:
            return False, "Produced quantity must be greater than 0"
        
        remaining = planned_qty - current_produced
        if produced_qty > remaining * 1.5:  # Allow 50% overproduction
            return False, f"Produced quantity ({produced_qty}) exceeds allowed limit"
        
        return True, None
    
    @staticmethod
    def validate_batch_no(batch_no: str) -> Tuple[bool, Optional[str]]:
        """Validate batch number"""
        if not batch_no or not batch_no.strip():
            return False, "Batch number is required"
        return True, None
    
    @staticmethod
    def can_complete(status: str) -> bool:
        """Check if order can be completed"""
        return status in CompletionConstants.COMPLETABLE_STATUSES


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
