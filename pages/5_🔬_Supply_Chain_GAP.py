# pages/3_🔬_Supply_Chain_GAP.py

"""
Supply Chain GAP Analysis Page
Full multi-level analysis: FG + Raw Materials

VERSION: 2.1.0
- v2.1: @st.fragment per tab — no full-page reruns on pagination/filter/selection
         @st.dialog drill-down — click row → View Details in modal
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import logging
from typing import Dict, Any
import os
from pathlib import Path

# Configure page
st.set_page_config(
    page_title="Supply Chain GAP",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import utilities
project_root = os.environ.get('PROJECT_ROOT', Path(__file__).parent.parent)
if str(project_root) not in os.sys.path:
    os.sys.path.insert(0, str(project_root))

from utils.auth import AuthManager
from utils.supply_chain_gap import (
    VERSION,
    get_state,
    get_data_loader,
    get_calculator,
    get_filters,
    get_charts,
    get_formatter,
    export_to_excel,
    get_export_filename,
    render_kpi_cards,
    render_data_freshness,
    render_help_popover,
    # Fragment functions for each tab — Net GAP
    fg_charts_fragment,
    fg_table_fragment,
    manufacturing_fragment,
    trading_fragment,
    raw_materials_fragment,
    actions_fragment,
    # Fragment functions — Period GAP per tab (v2.3)
    fg_period_fragment,
    manufacturing_period_fragment,
    trading_period_fragment,
    raw_period_fragment,
    UI_CONFIG
)


def initialize_system():
    """Initialize all components"""
    state = get_state()
    data_loader = get_data_loader()
    calculator = get_calculator()
    formatter = get_formatter()
    filters = get_filters(data_loader)
    charts = get_charts()
    
    return state, data_loader, calculator, formatter, filters, charts


def calculate_gap(
    data_loader,
    calculator,
    filter_values: Dict[str, Any]
):
    """Load all data and calculate full Supply Chain GAP"""
    
    with st.spinner("🔬 Calculating Supply Chain GAP..."):
        
        # Load FG Supply
        fg_supply = data_loader.load_fg_supply(
            entity_name=filter_values.get('entity'),
            product_ids=filter_values.get('products_tuple'),
            brands=filter_values.get('brands_tuple'),
            exclude_expired=filter_values.get('exclude_expired', True)
        )
        
        # Load FG Demand
        fg_demand = data_loader.load_fg_demand(
            entity_name=filter_values.get('entity'),
            product_ids=filter_values.get('products_tuple'),
            brands=filter_values.get('brands_tuple')
        )
        
        # Load FG Safety Stock
        fg_safety = None
        if filter_values.get('include_fg_safety', True):
            fg_safety = data_loader.load_fg_safety_stock(
                entity_name=filter_values.get('entity'),
                product_ids=filter_values.get('products_tuple')
            )
        
        # Validate FG data
        if fg_supply.empty and fg_demand.empty:
            st.warning("No FG data available for selected filters")
            return None
        
        # Load Classification
        classification = data_loader.load_product_classification(
            entity_name=filter_values.get('entity'),
            product_ids=filter_values.get('products_tuple')
        )
        
        # Load BOM Explosion
        bom_explosion = data_loader.load_bom_explosion(
            entity_name=filter_values.get('entity'),
            include_alternatives=filter_values.get('include_alternatives', True)
        )
        
        # Load Existing MO Demand
        existing_mo = None
        if filter_values.get('include_existing_mo', True):
            existing_mo = data_loader.load_existing_mo_demand(
                entity_name=filter_values.get('entity'),
                include_draft_mo=filter_values.get('include_draft_mo', False)
            )
        
        # Load Raw Material Supply (summary for net GAP, detail for period GAP)
        raw_supply = data_loader.load_raw_material_supply_summary(
            entity_name=filter_values.get('entity')
        )
        
        # Load Raw Material Supply Detail (has availability_date for period allocation)
        raw_supply_detail = data_loader.load_raw_material_supply(
            entity_name=filter_values.get('entity'),
            exclude_expired=filter_values.get('exclude_expired', True)
        )
        
        # Load Raw Safety Stock
        raw_safety = None
        if filter_values.get('include_raw_safety', True):
            raw_safety = data_loader.load_raw_material_safety_stock(
                entity_name=filter_values.get('entity')
            )
        
        # Calculate full GAP
        result = calculator.calculate(
            fg_supply_df=fg_supply,
            fg_demand_df=fg_demand,
            fg_safety_stock_df=fg_safety,
            classification_df=classification,
            bom_explosion_df=bom_explosion,
            existing_mo_demand_df=existing_mo,
            raw_supply_df=raw_supply,
            raw_supply_detail_df=raw_supply_detail,
            raw_safety_stock_df=raw_safety,
            selected_supply_sources=filter_values.get('supply_sources'),
            selected_demand_sources=filter_values.get('demand_sources'),
            include_fg_safety=filter_values.get('include_fg_safety', True),
            include_raw_safety=filter_values.get('include_raw_safety', True),
            include_alternatives=filter_values.get('include_alternatives', True),
            include_existing_mo=filter_values.get('include_existing_mo', True),
            include_draft_mo=filter_values.get('include_draft_mo', False),
            period_type=filter_values.get('period_type', 'Weekly'),
            track_backlog=filter_values.get('track_backlog', True)
        )
        
        logger.info(f"Supply Chain GAP calculated: {result.get_summary()}")
        return result


def main():
    """Main application"""
    
    # Authentication check
    auth_manager = AuthManager()
    if not auth_manager.check_session():
        st.warning("⚠️ Please login to access this page")
        st.stop()
    
    # Initialize
    state, data_loader, calculator, formatter, filters, charts = initialize_system()
    
    # Page header with help popover
    col_title, col_help = st.columns([10, 1])
    with col_title:
        st.title("🔬 Supply Chain GAP Analysis")
    with col_help:
        st.markdown("<div style='margin-top:16px;'>", unsafe_allow_html=True)
        render_help_popover()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("Full Multi-Level Analysis: FG + Raw Materials")
    
    # Sidebar
    with st.sidebar:
        st.markdown(f"👤 **User:** {auth_manager.get_user_display_name()}")
        if st.button("🚪 Logout", use_container_width=True):
            auth_manager.logout()
            st.rerun()
        
        st.divider()
        st.caption(f"Version {VERSION}")
    
    # =========================================================================
    # FILTERS (kept outside fragments — cascading selects need full reruns)
    # =========================================================================
    with st.expander("🔧 **Configuration**", expanded=True):
        filter_values = filters.render_filters()
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("🔄 Reset", use_container_width=True):
            state.reset_filters()
            st.rerun()
    
    with col2:
        calculate_clicked = st.button(
            "🔬 Analyze",
            type="primary",
            use_container_width=True
        )
    
    with col3:
        if state.has_result():
            st.success("✅ Results ready")
        else:
            st.info("👆 Click Analyze to start")
    
    # Calculate if needed
    if calculate_clicked:
        try:
            result = calculate_gap(data_loader, calculator, filter_values)
            if result:
                state.set_filters(filter_values)
                state.set_result(result)
                st.rerun()
        except Exception as e:
            logger.error(f"Calculation failed: {e}", exc_info=True)
            st.error(f"❌ Calculation failed: {str(e)}")
            st.stop()
    
    # Display results
    result = state.get_result()
    
    if not result:
        st.info("Configure filters and click 'Analyze' to begin")
        st.stop()
    
    # --- From here: result exists ---
    
    # Data Freshness Indicator + Refresh
    refresh_clicked = render_data_freshness(state)
    if refresh_clicked:
        saved_filters = state.get_filters()
        if saved_filters:
            try:
                new_result = calculate_gap(data_loader, calculator, saved_filters)
                if new_result:
                    state.set_result(new_result)
                    st.rerun()
            except Exception as e:
                logger.error(f"Refresh failed: {e}", exc_info=True)
                st.error(f"❌ Refresh failed: {str(e)}")
    
    # KPI Cards
    render_kpi_cards(result)
    
    st.divider()
    
    # =========================================================================
    # MAIN TABS — each tab body is a @st.fragment
    # Interactions inside a tab only rerun that fragment, not the full page.
    # =========================================================================
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 FG Overview",
        "🏭 Manufacturing",
        "🛒 Trading",
        "🧪 Raw Materials",
        "📋 Actions"
    ])
    
    # Tab 1: FG Overview — Net GAP + Period Timeline
    with tab1:
        st.subheader("📊 Finished Goods — Net GAP")
        fg_charts_fragment(result, charts)
        fg_table_fragment(result)
        
        st.divider()
        st.subheader("📅 Period Timeline — When Do Shortages Occur?")
        st.caption("Carry-forward: surplus/backlog from period N propagates to N+1")
        fg_period_fragment(result, charts)
    
    # Tab 2: Manufacturing — Net GAP + Period Timeline
    with tab2:
        st.subheader("🏭 Manufacturing — Net GAP")
        manufacturing_fragment(result, charts)
        
        st.divider()
        st.subheader("📅 Manufacturing Period Timeline")
        manufacturing_period_fragment(result, charts)
    
    # Tab 3: Trading — Net GAP + Period Timeline
    with tab3:
        st.subheader("🛒 Trading — Net GAP")
        trading_fragment(result)
        
        st.divider()
        st.subheader("📅 Trading Period Timeline")
        trading_period_fragment(result, charts)
    
    # Tab 4: Raw Materials — Net GAP + Period Timeline
    with tab4:
        st.subheader("🧪 Raw Material — Net GAP")
        raw_materials_fragment(result, charts)
        
        st.divider()
        st.subheader("📅 Raw Material Period Timeline")
        st.caption("Demand = BOM explosion of FG manufacturing shortage per period")
        raw_period_fragment(result, charts)
    
    # Tab 5: Actions
    with tab5:
        st.subheader("📋 Action Recommendations")
        actions_fragment(result, charts)
    
    # =========================================================================
    # EXPORT & FOOTER
    # =========================================================================
    st.divider()
    
    st.subheader("📥 Export")
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        try:
            # Cache export data by result timestamp
            cache_key = f"export_cache_{result.timestamp.isoformat()}"
            if cache_key not in st.session_state:
                st.session_state[cache_key] = export_to_excel(result, state.get_filters() or filter_values)
            
            excel_data = st.session_state[cache_key]
            filename = get_export_filename()
            
            st.download_button(
                label="📥 Export Excel",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
        except Exception as e:
            logger.error(f"Export failed: {e}")
            st.error("Export failed")
    
    st.divider()
    st.caption(
        f"Last calculated: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Supply Chain GAP Analysis v{VERSION}"
    )


if __name__ == "__main__":
    main()