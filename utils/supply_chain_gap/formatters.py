# utils/supply_chain_gap/formatters.py

"""
Formatters for Supply Chain GAP Analysis
"""

import pandas as pd
from typing import Any, Optional
from .constants import STATUS_CONFIG


class SupplyChainFormatter:
    """Formatter for Supply Chain GAP data"""
    
    @staticmethod
    def format_number(value: Any, decimals: int = 0) -> str:
        """Format number with thousand separator"""
        if pd.isna(value):
            return '-'
        try:
            if decimals == 0:
                return f"{int(value):,}"
            return f"{float(value):,.{decimals}f}"
        except (ValueError, TypeError):
            return str(value)
    
    @staticmethod
    def format_currency(value: Any, symbol: str = "$") -> str:
        """Format currency value"""
        if pd.isna(value):
            return '-'
        try:
            return f"{symbol}{float(value):,.2f}"
        except (ValueError, TypeError):
            return str(value)
    
    @staticmethod
    def format_percentage(value: Any, decimals: int = 1) -> str:
        """Format percentage"""
        if pd.isna(value):
            return '-'
        try:
            return f"{float(value) * 100:.{decimals}f}%"
        except (ValueError, TypeError):
            return str(value)
    
    @staticmethod
    def format_status(status: str) -> str:
        """Format GAP status with icon"""
        config = STATUS_CONFIG.get(status, {})
        icon = config.get('icon', '❓')
        label = status.replace('_', ' ').title()
        return f"{icon} {label}"
    
    @staticmethod
    def format_gap(value: Any) -> str:
        """Format GAP value with color indicator"""
        if pd.isna(value):
            return '-'
        try:
            v = float(value)
            formatted = f"{v:,.0f}"
            if v < 0:
                return f"🔴 {formatted}"
            elif v > 0:
                return f"🟢 +{formatted}"
            else:
                return f"⚪ {formatted}"
        except (ValueError, TypeError):
            return str(value)
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 30) -> str:
        """Truncate text with ellipsis"""
        if pd.isna(text):
            return ''
        text = str(text)
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + '...'
    
    def format_df_for_display(
        self,
        df: pd.DataFrame,
        number_cols: Optional[list] = None,
        currency_cols: Optional[list] = None,
        percentage_cols: Optional[list] = None,
        status_cols: Optional[list] = None,
        text_cols: Optional[list] = None,
        max_text_length: int = 30
    ) -> pd.DataFrame:
        """Format dataframe for display"""
        
        result = df.copy()
        
        if number_cols:
            for col in number_cols:
                if col in result.columns:
                    result[col] = result[col].apply(self.format_number)
        
        if currency_cols:
            for col in currency_cols:
                if col in result.columns:
                    result[col] = result[col].apply(self.format_currency)
        
        if percentage_cols:
            for col in percentage_cols:
                if col in result.columns:
                    result[col] = result[col].apply(self.format_percentage)
        
        if status_cols:
            for col in status_cols:
                if col in result.columns:
                    result[col] = result[col].apply(self.format_status)
        
        if text_cols:
            for col in text_cols:
                if col in result.columns:
                    result[col] = result[col].apply(
                        lambda x: self.truncate_text(x, max_text_length)
                    )
        
        return result


def get_formatter() -> SupplyChainFormatter:
    """Get formatter instance"""
    return SupplyChainFormatter()
