# utils/production/issues/dashboard.py
"""
Dashboard components for Issues domain
Metrics display and summary statistics

Version: 1.0.0
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import streamlit as st

from .queries import IssueQueries
from .common import format_number, get_vietnam_today

logger = logging.getLogger(__name__)


class IssueDashboard:
    """Dashboard metrics for Material Issues"""
    
    def __init__(self):
        self.queries = IssueQueries()
    
    def get_metrics(self, from_date: Optional[date] = None,
                   to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get issue metrics for dashboard"""
        return self.queries.get_issue_metrics(from_date, to_date)
    
    def render(self, from_date: Optional[date] = None,
              to_date: Optional[date] = None):
        """Render dashboard metrics section"""
        metrics = self.get_metrics(from_date, to_date)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="📦 Total Issues",
                value=format_number(metrics['total_issues'], 0),
                help="Total material issue transactions"
            )
        
        with col2:
            today = metrics['today_issues']
            st.metric(
                label="📅 Today",
                value=format_number(today, 0),
                delta=f"Today's issues",
                delta_color="off",
                help="Issues created today"
            )
        
        with col3:
            pending = metrics['pending_orders']
            delta_color = "inverse" if pending > 5 else "off"
            st.metric(
                label="⏳ Pending Orders",
                value=format_number(pending, 0),
                delta="Waiting for issue" if pending > 0 else None,
                delta_color=delta_color,
                help="Orders waiting for material issue"
            )
        
        with col4:
            st.metric(
                label="📊 Units Issued",
                value=format_number(metrics['total_units'], 2),
                help="Total material units issued"
            )


def render_dashboard(from_date: Optional[date] = None,
                    to_date: Optional[date] = None):
    """Convenience function to render issue dashboard"""
    dashboard = IssueDashboard()
    dashboard.render(from_date, to_date)
