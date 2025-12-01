# utils/production/completions/dashboard.py
"""
Dashboard components for Completions domain
Metrics display and summary statistics

Version: 1.0.0
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import streamlit as st

from .queries import CompletionQueries
from .common import format_number, get_yield_indicator

logger = logging.getLogger(__name__)


class CompletionDashboard:
    """Dashboard metrics for Production Completions"""
    
    def __init__(self):
        self.queries = CompletionQueries()
    
    def get_metrics(self, from_date: Optional[date] = None,
                   to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get completion metrics for dashboard"""
        return self.queries.get_completion_metrics(from_date, to_date)
    
    def render(self, from_date: Optional[date] = None,
              to_date: Optional[date] = None):
        """Render dashboard metrics section"""
        metrics = self.get_metrics(from_date, to_date)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="📦 Total Receipts",
                value=format_number(metrics['total_receipts'], 0),
                help="Total production receipt transactions"
            )
        
        with col2:
            today = metrics['today_receipts']
            st.metric(
                label="📅 Today",
                value=format_number(today, 0),
                delta="Today's receipts",
                delta_color="off",
                help="Receipts created today"
            )
        
        with col3:
            in_progress = metrics['in_progress_orders']
            st.metric(
                label="🔄 In Progress",
                value=format_number(in_progress, 0),
                help="Orders currently in production"
            )
        
        with col4:
            pass_rate = metrics['pass_rate']
            indicator = get_yield_indicator(pass_rate)
            st.metric(
                label="✅ Pass Rate",
                value=f"{pass_rate}% {indicator}",
                help="Quality pass rate"
            )
        
        # Quality breakdown expander
        quality_breakdown = metrics.get('quality_breakdown', {})
        if quality_breakdown:
            with st.expander("📊 Quality Breakdown", expanded=False):
                qcol1, qcol2, qcol3 = st.columns(3)
                
                passed = quality_breakdown.get('PASSED', {'count': 0, 'quantity': 0})
                pending = quality_breakdown.get('PENDING', {'count': 0, 'quantity': 0})
                failed = quality_breakdown.get('FAILED', {'count': 0, 'quantity': 0})
                
                with qcol1:
                    st.metric(
                        "✅ PASSED",
                        f"{passed['count']} receipts",
                        f"{format_number(passed['quantity'], 0)} units"
                    )
                
                with qcol2:
                    st.metric(
                        "⏳ PENDING",
                        f"{pending['count']} receipts",
                        f"{format_number(pending['quantity'], 0)} units"
                    )
                
                with qcol3:
                    st.metric(
                        "❌ FAILED",
                        f"{failed['count']} receipts",
                        f"{format_number(failed['quantity'], 0)} units"
                    )


def render_dashboard(from_date: Optional[date] = None,
                    to_date: Optional[date] = None):
    """Convenience function to render completion dashboard"""
    dashboard = CompletionDashboard()
    dashboard.render(from_date, to_date)
