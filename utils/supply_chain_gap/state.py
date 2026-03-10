# utils/supply_chain_gap/state.py

"""
Session State Management for Supply Chain GAP Analysis
"""

import streamlit as st
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SupplyChainState:
    """State container for Supply Chain GAP analysis"""
    
    # Filter state
    filters: Dict[str, Any] = None
    
    # Result state
    result: Any = None
    
    # Pagination
    fg_page: int = 1
    mfg_page: int = 1
    trading_page: int = 1
    raw_page: int = 1
    action_page: int = 1
    
    # UI state
    active_tab: str = 'overview'
    show_customer_dialog: bool = False
    
    def __post_init__(self):
        if self.filters is None:
            self.filters = {}


def get_state() -> 'SupplyChainStateManager':
    """Get or create state manager"""
    if 'supply_chain_state' not in st.session_state:
        st.session_state.supply_chain_state = SupplyChainStateManager()
    return st.session_state.supply_chain_state


class SupplyChainStateManager:
    """Manages session state for Supply Chain GAP analysis"""
    
    STATE_KEY = 'supply_chain_gap_data'
    
    def __init__(self):
        self._ensure_state()
    
    def _ensure_state(self):
        """Ensure state exists in session"""
        if self.STATE_KEY not in st.session_state:
            st.session_state[self.STATE_KEY] = {
                'filters': {},
                'result': None,
                'pages': {
                    'fg': 1, 'mfg': 1, 'trading': 1, 'raw': 1,
                    'action': 1, 'period': 1, 'fg_period': 1,
                    'mfg_period': 1, 'trd_period': 1, 'raw_period': 1
                },
                'active_tab': 'overview',
                'last_calculated': None
            }
    
    # =========================================================================
    # FILTER MANAGEMENT
    # =========================================================================
    
    def get_filters(self) -> Dict[str, Any]:
        """Get current filter values"""
        return st.session_state[self.STATE_KEY].get('filters', {})
    
    def set_filters(self, filters: Dict[str, Any]):
        """Set filter values"""
        st.session_state[self.STATE_KEY]['filters'] = filters
    
    def reset_filters(self):
        """Reset all filters to default"""
        st.session_state[self.STATE_KEY]['filters'] = {}
        st.session_state[self.STATE_KEY]['result'] = None
        self._reset_pages()
    
    # =========================================================================
    # RESULT MANAGEMENT
    # =========================================================================
    
    def get_result(self) -> Optional[Any]:
        """Get calculation result"""
        return st.session_state[self.STATE_KEY].get('result')
    
    def set_result(self, result: Any):
        """Set calculation result"""
        st.session_state[self.STATE_KEY]['result'] = result
        st.session_state[self.STATE_KEY]['last_calculated'] = datetime.now()
        self._reset_pages()
    
    def has_result(self) -> bool:
        """Check if result exists"""
        return st.session_state[self.STATE_KEY].get('result') is not None
    
    def clear_result(self):
        """Clear result"""
        st.session_state[self.STATE_KEY]['result'] = None
    
    def get_last_calculated(self) -> Optional[datetime]:
        """Get timestamp of last calculation"""
        return st.session_state[self.STATE_KEY].get('last_calculated')
    
    # =========================================================================
    # PAGINATION MANAGEMENT
    # =========================================================================
    
    def _reset_pages(self):
        """Reset all pages to 1"""
        st.session_state[self.STATE_KEY]['pages'] = {
            'fg': 1, 'mfg': 1, 'trading': 1, 'raw': 1, 'action': 1,
            'period': 1, 'fg_period': 1, 'mfg_period': 1,
            'trd_period': 1, 'raw_period': 1
        }
    
    def get_page(self, section: str = 'fg') -> int:
        """Get current page for a section"""
        return st.session_state[self.STATE_KEY]['pages'].get(section, 1)
    
    def set_page(self, page: int, section: str = 'fg', total_pages: int = 1):
        """Set page for a section"""
        page = max(1, min(page, total_pages))
        st.session_state[self.STATE_KEY]['pages'][section] = page
    
    # =========================================================================
    # TAB MANAGEMENT
    # =========================================================================
    
    def get_active_tab(self) -> str:
        """Get active tab"""
        return st.session_state[self.STATE_KEY].get('active_tab', 'overview')
    
    def set_active_tab(self, tab: str):
        """Set active tab"""
        st.session_state[self.STATE_KEY]['active_tab'] = tab
    
    # =========================================================================
    # DIALOG MANAGEMENT
    # =========================================================================
    
    def show_dialog(self, dialog_name: str):
        """Show a dialog"""
        st.session_state[f'{self.STATE_KEY}_{dialog_name}_dialog'] = True
    
    def hide_dialog(self, dialog_name: str):
        """Hide a dialog"""
        st.session_state[f'{self.STATE_KEY}_{dialog_name}_dialog'] = False
    
    def is_dialog_open(self, dialog_name: str) -> bool:
        """Check if dialog is open"""
        return st.session_state.get(f'{self.STATE_KEY}_{dialog_name}_dialog', False)
    
    # =========================================================================
    # DATA FRESHNESS
    # =========================================================================
    
    def get_data_age_seconds(self) -> Optional[int]:
        """Get age of data in seconds since last calculation"""
        last = self.get_last_calculated()
        if last is None:
            return None
        return int((datetime.now() - last).total_seconds())
    
    def get_data_age_display(self) -> str:
        """Get human-readable data age"""
        age = self.get_data_age_seconds()
        if age is None:
            return "No data"
        if age < 60:
            return "Just now"
        elif age < 3600:
            return f"{age // 60}m ago"
        elif age < 86400:
            hours = age // 3600
            return f"{hours}h ago"
        else:
            days = age // 86400
            return f"{days}d ago"
    
    def is_data_stale(self, threshold_minutes: int = 30) -> bool:
        """Check if data is older than threshold"""
        age = self.get_data_age_seconds()
        if age is None:
            return False
        return age > (threshold_minutes * 60)
    
    # =========================================================================
    # DRILL-DOWN STATE
    # =========================================================================
    
    def get_selected_product_id(self) -> Optional[int]:
        """Get currently selected product ID for drill-down"""
        return st.session_state.get(f'{self.STATE_KEY}_drilldown_product')
    
    def set_selected_product_id(self, product_id: Optional[int]):
        """Set selected product ID for drill-down"""
        st.session_state[f'{self.STATE_KEY}_drilldown_product'] = product_id
    
    def clear_drilldown(self):
        """Clear drill-down selection"""
        st.session_state[f'{self.STATE_KEY}_drilldown_product'] = None