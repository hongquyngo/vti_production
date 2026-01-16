# pages/4_📊_BOM_Variance.py
"""
BOM Variance Analysis - VERSION 2.0 (Restructured)

Dashboard for analyzing actual material consumption vs BOM theoretical values.
Identifies variances and suggests adjustments to improve BOM accuracy.

This is a thin orchestrator that delegates to tab modules:
- Tab 1 (Dashboard): utils.bom_variance.tab_dashboard
- Tab 2 (Detail): utils.bom_variance.tab_detail
- Tab 3 (Recommendations): utils.bom_variance.tab_recommendations

Changes in v2.0:
- Restructured: Code split into separate tab modules
- Thin orchestrator pattern (~150 lines vs 1651 lines)
- Better maintainability and team collaboration
- Prepared for Phase 2, 3, 4 development
"""

import streamlit as st
import logging
from datetime import date, timedelta

from utils.auth import AuthManager
from utils.bom_variance import (
    VarianceAnalyzer,
    VarianceConfig,
    init_session_state,
    get_config,
    clear_data_cache,
    tab_dashboard,
    tab_detail,
    tab_recommendations
)

logger = logging.getLogger(__name__)


# ==================== Page Configuration ====================

st.set_page_config(
    page_title="BOM Variance Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()


# ==================== Helper Functions ====================

def get_analyzer() -> VarianceAnalyzer:
    """Get analyzer instance with current config"""
    return VarianceAnalyzer(st.session_state['variance_config'])


# ==================== UI Components ====================

def render_header():
    """Render page header"""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.title("📊 BOM Variance Analysis")
        st.caption("Compare actual material consumption vs BOM theoretical values")
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh Data", use_container_width=True):
            clear_data_cache()
            st.rerun()


def render_sidebar():
    """Render sidebar with analysis configuration"""
    with st.sidebar:
        st.header("⚙️ Analysis Settings")
        
        config = get_config()
        
        # Date range
        st.subheader("📅 Date Range")
        
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input(
                "From",
                value=config.date_from,
                key="config_date_from"
            )
        with col2:
            date_to = st.date_input(
                "To",
                value=config.date_to,
                key="config_date_to"
            )
        
        # Quick date presets
        preset_col1, preset_col2, preset_col3 = st.columns(3)
        with preset_col1:
            if st.button("1M", use_container_width=True, help="Last 1 month"):
                config.date_to = date.today()
                config.date_from = config.date_to - timedelta(days=30)
                clear_data_cache()
                st.rerun()
        with preset_col2:
            if st.button("3M", use_container_width=True, help="Last 3 months"):
                config.date_to = date.today()
                config.date_from = config.date_to - timedelta(days=90)
                clear_data_cache()
                st.rerun()
        with preset_col3:
            if st.button("6M", use_container_width=True, help="Last 6 months"):
                config.date_to = date.today()
                config.date_from = config.date_to - timedelta(days=180)
                clear_data_cache()
                st.rerun()
        
        st.markdown("---")
        
        # Thresholds
        st.subheader("📏 Thresholds")
        
        variance_threshold = st.slider(
            "Variance Threshold (%)",
            min_value=1.0,
            max_value=20.0,
            value=config.variance_threshold,
            step=0.5,
            help="Flag materials with variance above this percentage"
        )
        
        min_mo_count = st.slider(
            "Min. MO Count",
            min_value=1,
            max_value=10,
            value=config.min_mo_count,
            help="Minimum completed MOs required for reliable statistics"
        )
        
        st.markdown("---")
        
        # Apply settings button
        if st.button("✅ Apply Settings", use_container_width=True, type="primary"):
            config.date_from = date_from
            config.date_to = date_to
            config.variance_threshold = variance_threshold
            config.min_mo_count = min_mo_count
            clear_data_cache()
            st.rerun()
        
        st.markdown("---")
        
        # Current settings display
        with st.expander("📋 Current Settings", expanded=False):
            st.json({
                'date_from': str(config.date_from),
                'date_to': str(config.date_to),
                'variance_threshold': config.variance_threshold,
                'min_mo_count': config.min_mo_count
            })


def render_footer():
    """Render page footer"""
    st.markdown("---")
    
    config = get_config()
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.caption(
            f"📊 BOM Variance Analysis v2.0 | "
            f"Period: {config.date_from} to {config.date_to} | "
            f"Threshold: {config.variance_threshold}%"
        )
    
    with col2:
        st.caption(f"Session: {st.session_state.get('user_name', 'Guest')}")


# ==================== Main Application ====================

def main():
    """Main application entry point"""
    # Initialize session state
    init_session_state()
    
    # Get analyzer instance
    analyzer = get_analyzer()
    
    # Render header
    render_header()
    
    # Render sidebar configuration
    render_sidebar()
    
    # Load data once for all tabs
    full_data = tab_dashboard.load_variance_data(analyzer)
    
    # Tab selection
    tab1, tab2, tab3 = st.tabs([
        "📊 Dashboard Overview",
        "🔍 BOM Detail Analysis",
        "💡 Recommendations"
    ])
    
    # Render tabs
    with tab1:
        tab_dashboard.render(analyzer)
    
    with tab2:
        tab_detail.render(full_data, analyzer)
    
    with tab3:
        tab_recommendations.render(full_data, analyzer)
    
    # Render footer
    render_footer()


# ==================== Entry Point ====================

if __name__ == "__main__":
    main()