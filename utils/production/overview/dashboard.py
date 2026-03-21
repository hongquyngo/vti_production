# utils/production/overview/dashboard.py
"""
Dashboard components for Production Overview domain
Version: 6.0.0 — accept pre-computed metrics, zero DB on hot path
"""
import logging
from datetime import date
from typing import Dict, Any, Optional
import streamlit as st
from .common import format_number, format_percentage, get_vietnam_today, get_date_type_info_note, calculate_percentage

logger = logging.getLogger(__name__)


def _render_metrics_ui(metrics: Dict[str, Any], date_type: Optional[str] = None):
    """Pure UI renderer — no DB calls."""
    info_note = get_date_type_info_note(date_type)
    if info_note:
        st.info(info_note)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric(label="📋 Total MOs", value=format_number(metrics['total_orders'], 0))
    with col2:
        active_count = metrics['confirmed_count'] + metrics['in_progress_count']
        st.metric(label="🔄 Active", value=format_number(active_count, 0),
                  delta=f"{metrics['in_progress_count']} in progress")
    with col3:
        on_track = metrics['on_schedule_count']
        total_ip = metrics['in_progress_count']
        pct = round((on_track / total_ip * 100), 1) if total_ip > 0 else 0
        st.metric(label="🟢 On Track", value=format_number(on_track, 0),
                  delta=f"{pct}%" if total_ip > 0 else None, delta_color="normal")
    with col4:
        delayed = metrics['delayed_count']
        at_risk = metrics['at_risk_count']
        st.metric(label="🔴 Delayed", value=format_number(delayed, 0),
                  delta=f"+{at_risk} at risk" if at_risk > 0 else None, delta_color="inverse")
    with col5:
        yr = metrics['yield_rate']
        if yr >= 95: di, dc = "↑ Excellent", "normal"
        elif yr >= 85: di, dc = "→ Good", "off"
        else: di, dc = "↓ Below target", "inverse"
        st.metric(label="📈 Avg Yield", value=f"{yr}%", delta=di, delta_color=dc)
    
    with st.expander("📊 Status Breakdown", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: st.metric("📝 Draft", metrics['draft_count'])
        with c2: st.metric("✅ Confirmed", metrics['confirmed_count'])
        with c3: st.metric("🔄 In Progress", metrics['in_progress_count'])
        with c4: st.metric("✔️ Completed", metrics['completed_count'])
        with c5: st.metric("❌ Cancelled", metrics['cancelled_count'])
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: st.info(f"**Total Planned:** {format_number(metrics['total_planned_qty'], 0)} units")
        with c2: st.info(f"**Total Produced:** {format_number(metrics['total_produced_qty'], 0)} units")
        with c3: st.info(f"**Completion Rate:** {metrics['completion_rate']}%")


def render_dashboard_from_data(metrics: Dict[str, Any], date_type: Optional[str] = None):
    """Render from pre-computed data — ZERO DB queries."""
    _render_metrics_ui(metrics, date_type)


def render_dashboard(from_date=None, to_date=None, date_type=None):
    """Backward-compatible — queries DB directly."""
    from .queries import OverviewQueries
    metrics = OverviewQueries().get_overview_metrics(from_date, to_date, date_type=date_type)
    _render_metrics_ui(metrics, date_type)