# modules/common.py - Enhanced Common Utility Functions
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Dict, Tuple, Any, Optional, Union, List
from io import BytesIO
import streamlit as st
import logging

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_products() -> pd.DataFrame:
    """Get all active products with enhanced filtering"""
    engine = get_db_engine()
    
    query = """
    SELECT 
        p.id,
        p.name,
        p.pt_code as code,
        p.legacy_pt_code,
        p.description,
        p.package_size,
        p.uom,
        p.shelf_life,
        p.storage_condition,
        b.brand_name as brand,
        p.approval_status,
        p.is_service,
        COALESCE(
            (SELECT SUM(ih.remain) 
             FROM inventory_histories ih 
             WHERE ih.product_id = p.id 
             AND ih.remain > 0 
             AND ih.delete_flag = 0), 
            0
        ) as total_stock
    FROM products p
    LEFT JOIN brands b ON p.brand_id = b.id
    WHERE p.delete_flag = 0
    AND p.approval_status = 1
    AND p.is_service = 0
    ORDER BY p.name
    """
    
    try:
        return pd.read_sql(query, engine)
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_warehouses() -> pd.DataFrame:
    """Get all active warehouses with company info"""
    engine = get_db_engine()
    
    query = """
    SELECT 
        w.id,
        w.name,
        w.address,
        w.company_id,
        c.english_name as company_name,
        CONCAT(e.first_name, ' ', e.last_name) as manager_name,
        w.warehouse_type,
        w.is_active
    FROM warehouses w
    LEFT JOIN companies c ON w.company_id = c.id
    LEFT JOIN employees e ON w.manager_id = e.id
    WHERE w.delete_flag = 0
    AND w.is_active = 1
    ORDER BY w.name
    """
    
    try:
        return pd.read_sql(query, engine)
    except Exception as e:
        logger.error(f"Error getting warehouses: {e}")
        return pd.DataFrame()


def format_number(value: Union[int, float, None], decimal_places: int = 2) -> str:
    """Format number with thousand separators"""
    if pd.isna(value) or value is None:
        return "0"
    
    # Handle very small numbers
    if abs(value) < 0.01 and value != 0:
        return f"{value:.4f}"
    
    return f"{value:,.{decimal_places}f}"


def format_currency(value: Union[int, float, None], currency: str = "VND") -> str:
    """Format currency value with proper symbol"""
    if pd.isna(value) or value is None:
        return f"0 {currency}"
    
    if currency == "VND":
        return f"{value:,.0f} ₫"
    elif currency == "USD":
        return f"${value:,.2f}"
    else:
        return f"{value:,.0f} {currency}"


def generate_order_number(prefix: str = "ORD") -> str:
    """Generate unique order number with timestamp"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"{prefix}-{timestamp}"


def generate_batch_number(prefix: str = "BATCH", product_type: str = None) -> str:
    """Generate batch number based on type and timestamp"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M')
    
    if product_type:
        # Use first 3 letters of product type
        prefix = product_type[:3].upper()
    
    return f"{prefix}-{timestamp}"


def calculate_date_range(period: str = "month") -> Tuple[date, date]:
    """Calculate common date ranges with more options"""
    today = date.today()
    
    period_map = {
        "today": (today, today),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "week": lambda: (today - timedelta(days=today.weekday()), 
                        today - timedelta(days=today.weekday()) + timedelta(days=6)),
        "last_week": lambda: (today - timedelta(days=today.weekday() + 7), 
                             today - timedelta(days=today.weekday() + 1)),
        "month": lambda: (today.replace(day=1), 
                         (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1))),
        "last_month": lambda: ((today.replace(day=1) - timedelta(days=1)).replace(day=1),
                              today.replace(day=1) - timedelta(days=1)),
        "quarter": lambda: _get_quarter_range(today),
        "year": (date(today.year, 1, 1), date(today.year, 12, 31)),
        "last_7_days": (today - timedelta(days=6), today),
        "last_30_days": (today - timedelta(days=29), today),
        "last_90_days": (today - timedelta(days=89), today)
    }
    
    if period in period_map:
        result = period_map[period]
        return result() if callable(result) else result
    
    return today, today


def _get_quarter_range(ref_date: date) -> Tuple[date, date]:
    """Helper to get quarter date range"""
    quarter = (ref_date.month - 1) // 3
    start = date(ref_date.year, quarter * 3 + 1, 1)
    if quarter == 3:
        end = date(ref_date.year, 12, 31)
    else:
        end = date(ref_date.year, (quarter + 1) * 3 + 1, 1) - timedelta(days=1)
    return start, end


def validate_quantity(value: Any, min_value: float = 0, 
                     max_value: Optional[float] = None) -> Tuple[bool, Union[float, str]]:
    """Validate quantity input with detailed error messages"""
    try:
        qty = float(value)
        
        if pd.isna(qty):
            return False, "Quantity cannot be empty"
        
        if qty < min_value:
            return False, f"Quantity must be at least {min_value}"
        
        if max_value is not None and qty > max_value:
            return False, f"Quantity cannot exceed {max_value}"
        
        # Check for reasonable precision
        if qty != int(qty) and len(str(qty).split('.')[-1]) > 4:
            return False, "Quantity precision cannot exceed 4 decimal places"
        
        return True, qty
        
    except (ValueError, TypeError) as e:
        return False, "Invalid quantity format"


def get_status_color(status: str) -> str:
    """Get color for status display"""
    status_colors = {
        # Order statuses
        'DRAFT': '#6C757D',
        'CONFIRMED': '#0D6EFD',
        'IN_PROGRESS': '#FD7E14',
        'COMPLETED': '#198754',
        'CANCELLED': '#DC3545',
        
        # General statuses
        'ACTIVE': '#198754',
        'INACTIVE': '#6C757D',
        'EXPIRED': '#DC3545',
        'CRITICAL': '#DC3545',
        'WARNING': '#FFC107',
        'OK': '#198754',
        'PASSED': '#198754',
        'FAILED': '#DC3545',
        'PENDING': '#FFC107',
        
        # Material statuses
        'ISSUED': '#198754',
        'PARTIAL': '#FFC107',
        'RETURNED': '#0DCAF0',
        
        # Quality statuses
        'GOOD': '#198754',
        'DAMAGED': '#DC3545',
        
        # Priority levels
        'LOW': '#6C757D',
        'NORMAL': '#0D6EFD',
        'HIGH': '#FD7E14',
        'URGENT': '#DC3545'
    }
    
    return status_colors.get(status.upper(), '#6C757D')


def create_status_badge(status: str, include_icon: bool = True) -> str:
    """Create styled status badge"""
    color = get_status_color(status)
    
    icon_map = {
        'DRAFT': '📝',
        'CONFIRMED': '✅',
        'IN_PROGRESS': '🔄',
        'COMPLETED': '✔️',
        'CANCELLED': '❌',
        'ACTIVE': '🟢',
        'INACTIVE': '⭕',
        'EXPIRED': '🔴',
        'CRITICAL': '🚨',
        'WARNING': '⚠️',
        'OK': '✅',
        'PASSED': '✅',
        'FAILED': '❌',
        'PENDING': '⏳'
    }
    
    icon = icon_map.get(status.upper(), '') if include_icon else ''
    
    return f'<span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">{icon} {status}</span>'


def create_status_indicator(status: str) -> str:
    """Create text-based status indicator with emoji"""
    status_emoji = {
        'DRAFT': '📝',
        'CONFIRMED': '✅',
        'IN_PROGRESS': '🔄',
        'COMPLETED': '✔️',
        'CANCELLED': '❌',
        'ACTIVE': '🟢',
        'INACTIVE': '⭕',
        'EXPIRED': '🔴',
        'CRITICAL': '🚨',
        'WARNING': '⚠️',
        'OK': '✅',
        'PASSED': '✅',
        'FAILED': '❌',
        'PENDING': '⏳'
    }
    
    emoji = status_emoji.get(status.upper(), '⚪')
    return f"{emoji} {status}"


def create_progress_bar(current: float, total: float, height: int = 20) -> str:
    """Create HTML progress bar"""
    if total <= 0:
        percentage = 0
    else:
        percentage = min(100, max(0, (current / total) * 100))
    
    color = '#198754' if percentage >= 100 else '#0D6EFD' if percentage >= 50 else '#FFC107'
    
    return f"""
    <div style="background-color: #e9ecef; border-radius: 4px; height: {height}px; position: relative;">
        <div style="background-color: {color}; width: {percentage}%; height: 100%; border-radius: 4px;"></div>
        <span style="position: absolute; top: 0; left: 50%; transform: translateX(-50%); line-height: {height}px; font-size: 12px;">
            {percentage:.1f}%
        </span>
    </div>
    """


@st.cache_data(ttl=60)
def get_product_info(product_id: int) -> Optional[Dict[str, Any]]:
    """Get comprehensive product information"""
    engine = get_db_engine()
    
    query = """
    SELECT 
        p.id,
        p.name,
        p.pt_code as code,
        p.legacy_pt_code,
        p.description,
        p.package_size,
        p.uom,
        p.shelf_life,
        p.shelf_life_uom,
        p.storage_condition,
        b.brand_name as brand,
        p.min_stock_level,
        p.max_stock_level,
        COALESCE(
            (SELECT SUM(ih.remain) 
             FROM inventory_histories ih 
             WHERE ih.product_id = p.id 
             AND ih.remain > 0 
             AND ih.delete_flag = 0), 
            0
        ) as current_stock,
        COALESCE(
            (SELECT COUNT(DISTINCT bom_header_id) 
             FROM bom_details 
             WHERE material_id = p.id), 
            0
        ) as used_in_boms
    FROM products p
    LEFT JOIN brands b ON p.brand_id = b.id
    WHERE p.id = %s
    """
    
    try:
        result = pd.read_sql(query, engine, params=(product_id,))
        return result.iloc[0].to_dict() if not result.empty else None
    except Exception as e:
        logger.error(f"Error getting product info: {e}")
        return None


def export_to_excel(dataframes_dict: Dict[str, pd.DataFrame], 
                   filename: str = "export.xlsx") -> bytes:
    """Export multiple dataframes to Excel with formatting"""
    output = BytesIO()
    
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            
            # Define formats
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D3D3D3',
                'border': 1
            })
            
            for sheet_name, df in dataframes_dict.items():
                # Ensure sheet name is valid
                safe_sheet_name = sheet_name[:31].replace('/', '-').replace('\\', '-')
                
                # Write dataframe
                df.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                
                # Get worksheet
                worksheet = writer.sheets[safe_sheet_name]
                
                # Format headers
                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(0, col_num, value, header_format)
                
                # Auto-adjust column widths
                for i, col in enumerate(df.columns):
                    column_width = max(
                        df[col].astype(str).str.len().max(),
                        len(col)
                    ) + 2
                    worksheet.set_column(i, i, min(column_width, 50))
        
        return output.getvalue()
        
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


def validate_date_range(start_date: date, end_date: date, 
                       max_days: int = 365) -> Tuple[bool, Optional[str]]:
    """Validate date range with custom max days"""
    if start_date > end_date:
        return False, "Start date cannot be after end date"
    
    if (end_date - start_date).days > max_days:
        return False, f"Date range cannot exceed {max_days} days"
    
    if end_date > date.today():
        return False, "End date cannot be in the future"
    
    return True, None


def get_date_filter_presets() -> Dict[str, Tuple[date, date]]:
    """Get enhanced date filter presets"""
    presets = {
        "Today": calculate_date_range("today"),
        "Yesterday": calculate_date_range("yesterday"),
        "This Week": calculate_date_range("week"),
        "Last Week": calculate_date_range("last_week"),
        "This Month": calculate_date_range("month"),
        "Last Month": calculate_date_range("last_month"),
        "This Quarter": calculate_date_range("quarter"),
        "This Year": calculate_date_range("year"),
        "Last 7 Days": calculate_date_range("last_7_days"),
        "Last 30 Days": calculate_date_range("last_30_days"),
        "Last 90 Days": calculate_date_range("last_90_days")
    }
    
    return presets


def create_metric_card(title: str, value: Any, delta: Optional[str] = None,
                      delta_color: str = "normal", help_text: Optional[str] = None) -> None:
    """Create custom metric card with better styling"""
    delta_html = ""
    if delta:
        color = "#198754" if delta_color == "normal" else "#DC3545" if delta_color == "inverse" else "#6C757D"
        delta_html = f'<div style="color: {color}; font-size: 0.8em;">{delta}</div>'
    
    help_html = ""
    if help_text:
        help_html = f'<div style="color: #6C757D; font-size: 0.7em; margin-top: 4px;">{help_text}</div>'
    
    st.markdown(f"""
        <div style="background-color: #f8f9fa; padding: 1rem; border-radius: 0.5rem; border: 1px solid #dee2e6;">
            <div style="color: #6C757D; font-size: 0.9em; margin-bottom: 0.25rem;">{title}</div>
            <div style="font-size: 2em; font-weight: bold; line-height: 1;">{value}</div>
            {delta_html}
            {help_html}
        </div>
    """, unsafe_allow_html=True)


def format_datetime(dt: Union[datetime, str, None], 
                   format_string: str = "%Y-%m-%d %H:%M") -> str:
    """Format datetime with timezone awareness"""
    if pd.isna(dt) or dt is None:
        return ""
    
    if isinstance(dt, str):
        try:
            dt = pd.to_datetime(dt)
        except Exception:
            return dt
    
    try:
        return dt.strftime(format_string)
    except Exception:
        return str(dt)


def calculate_percentage(numerator: Union[int, float], 
                       denominator: Union[int, float], 
                       decimal_places: int = 1) -> float:
    """Calculate percentage with safe division"""
    if denominator == 0 or pd.isna(denominator) or pd.isna(numerator):
        return 0.0
    
    percentage = (float(numerator) / float(denominator)) * 100
    return round(percentage, decimal_places)


def get_time_ago(dt: Union[datetime, str, None]) -> str:
    """Get human-readable time ago with more precision"""
    if pd.isna(dt) or dt is None:
        return "Unknown"
    
    if isinstance(dt, str):
        try:
            dt = pd.to_datetime(dt)
        except Exception:
            return "Unknown"
    
    now = datetime.now()
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        now = now.replace(tzinfo=dt.tzinfo)
    
    diff = now - dt
    
    if diff.days > 365:
        years = diff.days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
    elif diff.days > 30:
        months = diff.days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    elif diff.days > 7:
        weeks = diff.days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    elif diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"


def log_activity(activity_type: str, reference: str, user_id: int, 
                details: Optional[Dict] = None) -> None:
    """Enhanced activity logging"""
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'activity': activity_type,
        'reference': reference,
        'user_id': user_id,
        'details': details or {}
    }
    
    logger.info(f"Activity: {activity_type} - {reference} by user {user_id}")
    if details:
        logger.debug(f"Details: {details}")
    
    # TODO: Implement database logging
    # activity_logger.log(log_entry)


def show_data_table(df: pd.DataFrame, 
                   key: Optional[str] = None,
                   hide_index: bool = True,
                   use_container_width: bool = True,
                   column_config: Optional[Dict] = None) -> None:
    """Display enhanced data table"""
    if df.empty:
        st.info("No data to display")
        return
    
    # Apply default column configurations
    if column_config is None:
        column_config = {}
    
    # Auto-configure common column types
    for col in df.columns:
        if col not in column_config:
            if 'date' in col.lower():
                column_config[col] = st.column_config.DateColumn(col.title())
            elif 'qty' in col.lower() or 'quantity' in col.lower():
                column_config[col] = st.column_config.NumberColumn(
                    col.title(),
                    format="%.2f"
                )
            elif 'price' in col.lower() or 'cost' in col.lower():
                column_config[col] = st.column_config.NumberColumn(
                    col.title(),
                    format="%.2f"
                )
            elif 'status' in col.lower():
                column_config[col] = st.column_config.TextColumn(
                    col.title()
                )
    
    st.dataframe(
        df,
        use_container_width=use_container_width,
        hide_index=hide_index,
        column_config=column_config,
        key=key
    )


def create_download_button(data: Union[pd.DataFrame, Dict[str, pd.DataFrame], str, bytes], 
                         filename: str, 
                         label: str = "Download", 
                         file_type: str = "csv",
                         use_container_width: bool = True) -> None:
    """Enhanced download button with multiple formats"""
    try:
        if file_type == "csv":
            if isinstance(data, pd.DataFrame):
                csv_data = data.to_csv(index=False).encode('utf-8')
                mime = "text/csv"
            else:
                csv_data = data if isinstance(data, bytes) else data.encode('utf-8')
                mime = "text/csv"
            
            st.download_button(
                label=f"📥 {label}",
                data=csv_data,
                file_name=filename,
                mime=mime,
                use_container_width=use_container_width
            )
        
        elif file_type == "excel":
            if isinstance(data, dict):
                excel_data = export_to_excel(data, filename)
            elif isinstance(data, pd.DataFrame):
                excel_data = export_to_excel({"Sheet1": data}, filename)
            else:
                raise ValueError("Excel export requires DataFrame or dict of DataFrames")
            
            st.download_button(
                label=f"📥 {label}",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=use_container_width
            )
        
        elif file_type == "json":
            if isinstance(data, pd.DataFrame):
                json_data = data.to_json(orient='records', indent=2)
            else:
                import json
                json_data = json.dumps(data, indent=2)
            
            st.download_button(
                label=f"📥 {label}",
                data=json_data,
                file_name=filename,
                mime="application/json",
                use_container_width=use_container_width
            )
            
    except Exception as e:
        st.error(f"Error creating download: {str(e)}")
        logger.error(f"Download error: {e}")


def display_info_box(message: str, type: str = "info", icon: bool = True) -> None:
    """Display styled information box"""
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌"
    }
    
    colors = {
        "info": "#0DCAF0",
        "success": "#198754",
        "warning": "#FFC107",
        "error": "#DC3545"
    }
    
    icon_str = icons.get(type, "") if icon else ""
    color = colors.get(type, "#6C757D")
    
    st.markdown(f"""
        <div style="background-color: {color}20; border-left: 4px solid {color}; 
                    padding: 1rem; margin: 0.5rem 0; border-radius: 0.25rem;">
            <div style="color: {color}; font-weight: bold;">
                {icon_str} {message}
            </div>
        </div>
    """, unsafe_allow_html=True)


def show_success_message(message: str, duration: int = 3) -> None:
    """Show success message"""
    st.success(message)


def show_error_message(message: str, details: Optional[str] = None) -> None:
    """Show error message with optional details"""
    st.error(message)
    if details:
        with st.expander("Error Details"):
            st.code(details)


def confirm_action(message: str, key: Optional[str] = None) -> Tuple[bool, bool]:
    """Show confirmation dialog (simple version)"""
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.warning(message)
    with col2:
        confirm = st.button("✓ Confirm", key=f"{key}_confirm" if key else None, 
                          type="primary", use_container_width=True)
    with col3:
        cancel = st.button("✗ Cancel", key=f"{key}_cancel" if key else None, 
                         use_container_width=True)
    
    return confirm, cancel