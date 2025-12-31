# utils/production/orders/dashboard.py
"""
Dashboard components for Orders domain
Metrics display and summary statistics

Version: 1.1.0
Changes:
- v1.1.0: Added BOM conflict metric to dashboard
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import streamlit as st

from .queries import OrderQueries
from .common import format_number, get_vietnam_today

logger = logging.getLogger(__name__)


class OrderDashboard:
    """Dashboard metrics for Orders"""
    
    def __init__(self):
        self.queries = OrderQueries()
    
    def get_metrics(self, from_date: Optional[date] = None,
                   to_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Get order metrics for dashboard
        
        Args:
            from_date: Filter from date
            to_date: Filter to date
            
        Returns:
            Dictionary with metrics
        """
        return self.queries.get_order_metrics(from_date, to_date)
    
    def get_conflict_summary(self, from_date: Optional[date] = None,
                            to_date: Optional[date] = None,
                            active_only: bool = True) -> Dict[str, Any]:
        """
        Get BOM conflict summary
        
        Args:
            from_date: Filter from date
            to_date: Filter to date
            active_only: If True, count only active BOMs for conflict
            
        Returns:
            Dictionary with conflict summary
        """
        return self.queries.get_bom_conflict_summary(active_only, from_date, to_date)
    
    def render(self, from_date: Optional[date] = None,
              to_date: Optional[date] = None,
              conflict_check_active_only: bool = True):
        """
        Render dashboard metrics section
        
        Args:
            from_date: Filter from date
            to_date: Filter to date
            conflict_check_active_only: If True, count only active BOMs for conflict
        """
        metrics = self.get_metrics(from_date, to_date)
        conflict_summary = self.get_conflict_summary(from_date, to_date, conflict_check_active_only)
        
        # First row - Main metrics (5 columns now including conflicts)
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric(
                label="📋 Total Orders",
                value=format_number(metrics['total_orders'], 0),
                help="Total number of production orders"
            )
        
        with col2:
            active = metrics['active_count']
            st.metric(
                label="🔄 Active",
                value=format_number(active, 0),
                delta=f"{metrics['in_progress_count']} in progress",
                help="Confirmed + In Progress orders"
            )
        
        with col3:
            urgent = metrics['urgent_count']
            delta_color = "inverse" if urgent > 0 else "off"
            st.metric(
                label="🔴 Urgent",
                value=format_number(urgent, 0),
                delta=f"+{metrics['high_priority_count']} high" if metrics['high_priority_count'] > 0 else None,
                delta_color=delta_color,
                help="Urgent priority orders"
            )
        
        with col4:
            completion_rate = metrics['completion_rate']
            st.metric(
                label="📈 Completion Rate",
                value=f"{completion_rate}%",
                help="Percentage of completed orders"
            )
        
        with col5:
            conflict_count = conflict_summary['total_conflict_orders']
            delta_color = "inverse" if conflict_count > 0 else "off"
            st.metric(
                label="⚠️ BOM Conflicts",
                value=format_number(conflict_count, 0),
                delta=f"{conflict_summary['affected_products']} products" if conflict_count > 0 else None,
                delta_color=delta_color,
                help="Orders with multiple active BOMs for the same product"
            )
        
        # Optional: Show status breakdown in expander
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
            
            # Show conflict breakdown if any
            if conflict_count > 0:
                st.markdown("---")
                st.markdown("**⚠️ Conflicts by Status:**")
                conflict_by_status = conflict_summary['conflict_by_status']
                
                cols = st.columns(4)
                status_labels = [
                    ("📝 Draft", conflict_by_status['DRAFT']),
                    ("✅ Confirmed", conflict_by_status['CONFIRMED']),
                    ("🔄 In Progress", conflict_by_status['IN_PROGRESS']),
                    ("✔️ Completed", conflict_by_status['COMPLETED'])
                ]
                
                for col, (label, count) in zip(cols, status_labels):
                    with col:
                        if count > 0:
                            st.warning(f"{label}: {count}")
                        else:
                            st.caption(f"{label}: {count}")


def render_dashboard(from_date: Optional[date] = None,
                    to_date: Optional[date] = None,
                    conflict_check_active_only: bool = True):
    """
    Convenience function to render order dashboard
    
    Args:
        from_date: Filter from date
        to_date: Filter to date
        conflict_check_active_only: If True, count only active BOMs for conflict
    """
    dashboard = OrderDashboard()
    dashboard.render(from_date, to_date, conflict_check_active_only)