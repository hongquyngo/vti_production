# utils/production/overview/dashboard.py
"""
Dashboard components for Production Overview domain
KPI metrics display strip

Version: 5.0.0 (no functional changes, version bump for consistency)
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import streamlit as st

from .queries import OverviewQueries
from .common import format_number, format_percentage, get_vietnam_today, get_date_type_info_note

logger = logging.getLogger(__name__)


class OverviewDashboard:
    """Dashboard metrics for Production Overview"""
    
    def __init__(self):
        self.queries = OverviewQueries()
    
    def get_metrics(self, from_date: Optional[date] = None,
                   to_date: Optional[date] = None,
                   date_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get overview metrics for dashboard
        
        Args:
            from_date: Filter from date
            to_date: Filter to date
            date_type: Date type for filtering
            
        Returns:
            Dictionary with metrics
        """
        return self.queries.get_overview_metrics(from_date, to_date, date_type=date_type)
    
    def render(self, from_date: Optional[date] = None,
              to_date: Optional[date] = None,
              date_type: Optional[str] = None):
        """
        Render dashboard metrics section
        
        Args:
            from_date: Filter from date
            to_date: Filter to date
            date_type: Date type for filtering
        """
        # Show info note for non-default date types
        info_note = get_date_type_info_note(date_type)
        if info_note:
            st.info(info_note)
        
        metrics = self.get_metrics(from_date, to_date, date_type=date_type)
        
        # Main metrics row
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric(
                label="📋 Total MOs",
                value=format_number(metrics['total_orders'], 0),
                help="Total manufacturing orders in selected period"
            )
        
        with col2:
            # Active = Confirmed + In Progress
            active_count = metrics['confirmed_count'] + metrics['in_progress_count']
            st.metric(
                label="🔄 Active",
                value=format_number(active_count, 0),
                delta=f"{metrics['in_progress_count']} in progress",
                help="Confirmed + In Progress orders"
            )
        
        with col3:
            on_track = metrics['on_schedule_count']
            total_in_progress = metrics['in_progress_count']
            on_track_pct = round((on_track / total_in_progress * 100), 1) if total_in_progress > 0 else 0
            
            st.metric(
                label="🟢 On Track",
                value=format_number(on_track, 0),
                delta=f"{on_track_pct}%" if total_in_progress > 0 else None,
                delta_color="normal",
                help="In-progress orders on or ahead of schedule"
            )
        
        with col4:
            delayed = metrics['delayed_count']
            at_risk = metrics['at_risk_count']
            
            # Show delayed as main, at_risk as delta
            st.metric(
                label="🔴 Delayed",
                value=format_number(delayed, 0),
                delta=f"+{at_risk} at risk" if at_risk > 0 else None,
                delta_color="inverse",
                help="Orders behind schedule (>2 days)"
            )
        
        with col5:
            yield_rate = metrics['yield_rate']
            # Determine delta color based on yield
            if yield_rate >= 95:
                delta_indicator = "↑ Excellent"
                delta_color = "normal"
            elif yield_rate >= 85:
                delta_indicator = "→ Good"
                delta_color = "off"
            else:
                delta_indicator = "↓ Below target"
                delta_color = "inverse"
            
            st.metric(
                label="📈 Avg Yield",
                value=f"{yield_rate}%",
                delta=delta_indicator,
                delta_color=delta_color,
                help="Overall yield rate (Produced / Planned)"
            )
        
        # Optional: Status breakdown in expander
        with st.expander("📊 Status Breakdown", expanded=False):
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("📝 Draft", metrics['draft_count'])
            with col2:
                st.metric("✅ Confirmed", metrics['confirmed_count'])
            with col3:
                st.metric("🔄 In Progress", metrics['in_progress_count'])
            with col4:
                st.metric("✔️ Completed", metrics['completed_count'])
            with col5:
                st.metric("❌ Cancelled", metrics['cancelled_count'])
            
            # Additional insights
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.info(f"**Total Planned:** {format_number(metrics['total_planned_qty'], 0)} units")
            with col2:
                st.info(f"**Total Produced:** {format_number(metrics['total_produced_qty'], 0)} units")
            with col3:
                completion_rate = metrics['completion_rate']
                st.info(f"**Completion Rate:** {completion_rate}%")


def render_dashboard(from_date: Optional[date] = None,
                    to_date: Optional[date] = None,
                    date_type: Optional[str] = None):
    """
    Convenience function to render overview dashboard
    
    Args:
        from_date: Filter from date
        to_date: Filter to date
        date_type: Date type for filtering
    """
    dashboard = OverviewDashboard()
    dashboard.render(from_date, to_date, date_type=date_type)