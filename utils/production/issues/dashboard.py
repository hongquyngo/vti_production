# utils/production/issues/dashboard.py
"""
Dashboard components for Issues domain

Version: 2.0.0
Changes:
- v2.0.0: Accept pre-computed metrics — zero DB queries on hot path
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import streamlit as st

from .common import format_number, get_vietnam_today

logger = logging.getLogger(__name__)


def _render_metrics_ui(metrics: Dict[str, Any]):
    """Pure UI renderer — no DB calls."""
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
            delta="Today's issues",
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


def render_dashboard_from_data(metrics: Dict[str, Any]):
    """Render dashboard from pre-computed data — ZERO DB queries."""
    _render_metrics_ui(metrics)


def render_dashboard(from_date: Optional[date] = None,
                    to_date: Optional[date] = None):
    """Backward-compatible function — queries DB directly."""
    from .queries import IssueQueries
    metrics = IssueQueries().get_issue_metrics(from_date, to_date)
    _render_metrics_ui(metrics)