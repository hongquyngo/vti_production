# pages/2___Production.py
"""
Production Management - Entry Point
Routes to domain-specific modules

Version: 3.0.0 - Renamed Completion → Production Receipts
Changes:
- v3.0.0: Renamed Completion tab → Production Receipts
- v2.1.0: Added Overview tab for comprehensive production monitoring
- v2.0.0: Refactored with Domain Isolation
"""

import streamlit as st
import logging

from utils.auth import AuthManager

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="Production Management",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Header ====================

def render_header():
    """Render page header"""
    col1, col2 = st.columns([4, 1])
    
    with col1:
        st.title("🏭 Production Management")
    
    with col2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    try:
        render_header()
        st.markdown("---")
        
        # Tab navigation
        tab_labels = [
            "📊 Overview",
            "📋 Orders", 
            "📦 Material Issue", 
            "↩️ Material Return", 
            "📦 Production Receipts"
        ]
        tabs = st.tabs(tab_labels)
        
        # Overview Tab (NEW)
        with tabs[0]:
            from utils.production.overview.page import render_overview_tab
            render_overview_tab()
        
        # Orders Tab
        with tabs[1]:
            from utils.production.orders.page import render_orders_tab
            render_orders_tab()
        
        # Issues Tab
        with tabs[2]:
            from utils.production.issues.page import render_issues_tab
            render_issues_tab()
        
        # Returns Tab
        with tabs[3]:
            from utils.production.returns.page import render_returns_tab
            render_returns_tab()
        
        # Completions Tab → Production Receipts
        with tabs[4]:
            from utils.production.completions.page import render_completions_tab
            render_completions_tab()
    
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("🔄 Reload"):
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v3.0 - Production Receipts Refactoring")


if __name__ == "__main__":
    main()