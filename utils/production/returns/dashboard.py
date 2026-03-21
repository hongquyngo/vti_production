# utils/production/returns/dashboard.py
"""
Dashboard components for Returns domain
Version: 2.0.0 — accept pre-computed metrics
"""
import logging
from datetime import date
from typing import Dict, Any, Optional
import streamlit as st
from .common import format_number, get_vietnam_today, create_reason_display

logger = logging.getLogger(__name__)

def _render_metrics_ui(metrics: Dict[str, Any]):
    """Pure UI renderer — no DB calls."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="↩️ Total Returns", value=format_number(metrics['total_returns'], 0))
    with col2:
        st.metric(label="📅 Today", value=format_number(metrics['today_returns'], 0),
                  delta="Today's returns", delta_color="off")
    with col3:
        returnable = metrics['returnable_orders']
        st.metric(label="📦 Returnable Orders", value=format_number(returnable, 0))
    with col4:
        st.metric(label="📊 Units Returned", value=format_number(metrics['total_units'], 2))
    
    reason_breakdown = metrics.get('reason_breakdown', {})
    if reason_breakdown:
        with st.expander("📋 Return Reasons Breakdown", expanded=False):
            for reason, count in reason_breakdown.items():
                st.write(f"• {create_reason_display(reason)}: **{count}**")

def render_dashboard_from_data(metrics: Dict[str, Any]):
    """Render dashboard from pre-computed data — ZERO DB queries."""
    _render_metrics_ui(metrics)

def render_dashboard(from_date: Optional[date] = None, to_date: Optional[date] = None):
    """Backward-compatible — queries DB directly."""
    from .queries import ReturnQueries
    metrics = ReturnQueries().get_return_metrics(from_date, to_date)
    _render_metrics_ui(metrics)