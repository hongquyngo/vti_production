# utils/production/returns/dashboard.py
"""
Dashboard components for Returns domain
Metrics display and summary statistics

Version: 1.0.0
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import streamlit as st

from .queries import ReturnQueries
from .common import format_number, get_vietnam_today, create_reason_display

logger = logging.getLogger(__name__)


class ReturnDashboard:
    """Dashboard metrics for Material Returns"""
    
    def __init__(self):
        self.queries = ReturnQueries()
    
    def get_metrics(self, from_date: Optional[date] = None,
                   to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get return metrics for dashboard"""
        return self.queries.get_return_metrics(from_date, to_date)
    
    def render(self, from_date: Optional[date] = None,
              to_date: Optional[date] = None):
        """Render dashboard metrics section"""
        metrics = self.get_metrics(from_date, to_date)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="↩️ Total Returns",
                value=format_number(metrics['total_returns'], 0),
                help="Total material return transactions"
            )
        
        with col2:
            today = metrics['today_returns']
            st.metric(
                label="📅 Today",
                value=format_number(today, 0),
                delta=f"Today's returns",
                delta_color="off",
                help="Returns created today"
            )
        
        with col3:
            returnable = metrics['returnable_orders']
            st.metric(
                label="📦 Returnable Orders",
                value=format_number(returnable, 0),
                help="Orders with materials that can be returned"
            )
        
        with col4:
            st.metric(
                label="📊 Units Returned",
                value=format_number(metrics['total_units'], 2),
                help="Total material units returned"
            )
        
        # Reason breakdown
        reason_breakdown = metrics.get('reason_breakdown', {})
        if reason_breakdown:
            with st.expander("📋 Return Reasons Breakdown", expanded=False):
                for reason, count in reason_breakdown.items():
                    st.write(f"• {create_reason_display(reason)}: **{count}**")


def render_dashboard(from_date: Optional[date] = None,
                    to_date: Optional[date] = None):
    """Convenience function to render return dashboard"""
    dashboard = ReturnDashboard()
    dashboard.render(from_date, to_date)
