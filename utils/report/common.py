# utils/report/common.py
"""
Common utilities for Report module
Formatting, date utilities, and export helpers
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple, Union
from io import BytesIO

import pandas as pd

logger = logging.getLogger(__name__)


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
    """Get common date filter presets"""
    today = date.today()
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
                df.to_excel(writer, sheet_name=sheet_name, index=include_index)
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}")
        raise


# ==================== Data Preparation ====================

def prepare_status_summary(df: pd.DataFrame, status_column: str = 'status') -> pd.DataFrame:
    """Prepare status summary from dataframe"""
    if df.empty or status_column not in df.columns:
        return pd.DataFrame()
    
    summary = df[status_column].value_counts().reset_index()
    summary.columns = ['Status', 'Count']
    return summary


def prepare_time_series(df: pd.DataFrame, date_column: str, 
                       value_column: str, freq: str = 'D') -> pd.DataFrame:
    """Prepare time series data for charts"""
    if df.empty or date_column not in df.columns or value_column not in df.columns:
        return pd.DataFrame()
    
    try:
        df[date_column] = pd.to_datetime(df[date_column])
        ts_data = df.groupby(df[date_column].dt.to_period(freq))[value_column].sum()
        ts_data.index = ts_data.index.to_timestamp()
        return ts_data.reset_index()
    except Exception as e:
        logger.error(f"Error preparing time series: {e}")
        return pd.DataFrame()


def calculate_metrics_summary(df: pd.DataFrame, 
                             metrics: Dict[str, str]) -> Dict[str, float]:
    """Calculate summary metrics from dataframe"""
    summary = {}
    
    for metric_name, column_name in metrics.items():
        if column_name in df.columns:
            try:
                if df[column_name].dtype in ['int64', 'float64']:
                    summary[metric_name] = df[column_name].sum()
                else:
                    summary[metric_name] = len(df[column_name].dropna())
            except Exception as e:
                logger.error(f"Error calculating metric {metric_name}: {e}")
                summary[metric_name] = 0
        else:
            summary[metric_name] = 0
    
    return summary