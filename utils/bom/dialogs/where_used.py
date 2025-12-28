# utils/bom/dialogs/where_used.py
"""
Where Used Analysis Dialog with Alternatives Support - VERSION 2.1
Find which BOMs use a specific product/material (primary or alternative)

Changes in v2.1:
- Updated output product display to unified format with legacy_code
- Added format_product_display for consistent product display
"""

import logging
import streamlit as st
import pandas as pd

from utils.bom.manager import BOMManager, BOMException
from utils.bom.state import StateManager
from utils.bom.common import (
    render_material_selector,
    create_status_indicator,
    format_number,
    format_product_display,
    export_to_excel,
    create_download_button
)

logger = logging.getLogger(__name__)


@st.dialog("🔍 Where Used Analysis", width="large")
def show_where_used_dialog():
    """Where used analysis dialog"""
    state = StateManager()
    manager = BOMManager()
    
    st.info("ℹ️ Find which BOMs use a specific product or material (including alternatives)")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        product_id = render_material_selector(
            key="where_used_product",
            label="Select Product/Material to Search"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button(
            "🔍 Search",
            type="primary",
            use_container_width=True,
            key="where_used_search_btn"
        )
    
    st.markdown("---")
    
    if search_clicked and product_id:
        _perform_search(product_id, state, manager)
    
    results = state.get_where_used_results()
    
    if results is not None:
        _render_results(results, state, manager)
    
    st.markdown("---")
    
    if st.button("✔ Close", use_container_width=True, key="where_used_close_btn"):
        state.close_dialog()
        st.rerun()


def _perform_search(product_id: int, state: StateManager, manager: BOMManager):
    """Perform where used search"""
    try:
        state.set_loading(True)
        
        results = manager.get_where_used(product_id)
        
        state.set_where_used_product(product_id)
        state.set_where_used_results(results)
        
        state.set_loading(False)
    
    except Exception as e:
        logger.error(f"Error searching where used: {e}")
        state.set_loading(False)
        st.error(f"❌ Search error: {str(e)}")


def _render_results(results: pd.DataFrame, state: StateManager, manager: BOMManager):
    """Render search results with primary and alternative usage"""
    if results.empty:
        st.info("ℹ️ This product is not used in any BOM")
        return
    
    # Separate primary and alternative usage
    primary_results = results[results['usage_type'] == 'PRIMARY']
    alt_results = results[results['usage_type'] != 'PRIMARY']
    
    # Summary
    total_boms = results['bom_id'].nunique()
    st.success(f"✅ Found in **{total_boms}** BOM(s)")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total BOMs", total_boms)
    
    with col2:
        st.metric("As Primary", len(primary_results))
    
    with col3:
        st.metric("As Alternative", len(alt_results))
    
    with col4:
        active_count = results[results['bom_status'] == 'ACTIVE']['bom_id'].nunique()
        st.metric("Active BOMs", active_count)
    
    st.markdown("---")
    
    # Results table
    st.markdown("### Search Results")
    
    # Format for display
    display_df = results.copy()
    display_df['bom_status'] = display_df['bom_status'].apply(create_status_indicator)
    display_df['quantity'] = display_df['quantity'].apply(lambda x: format_number(x, 4))
    display_df['scrap_rate'] = display_df['scrap_rate'].apply(lambda x: f"{format_number(x, 2)}%")
    
    # Format output product with unified format
    display_df['output_product_display'] = display_df.apply(
        lambda row: format_product_display(
            code=row.get('output_product_code', ''),
            name=row.get('output_product_name', ''),
            package_size=row.get('output_package_size'),
            brand=row.get('output_brand'),
            legacy_code=row.get('output_legacy_code')
        ),
        axis=1
    )
    
    # Add usage type badge
    def format_usage_type(row):
        if row['usage_type'] == 'PRIMARY':
            return "🟢 PRIMARY"
        else:
            return f"🔀 {row['usage_type']}"
    
    display_df['usage_badge'] = display_df.apply(format_usage_type, axis=1)
    
    column_config = {
        "bom_code": st.column_config.TextColumn("BOM Code", width="small"),
        "bom_name": st.column_config.TextColumn("BOM Name", width="medium"),
        "bom_type": st.column_config.TextColumn("Type", width="small"),
        "bom_status": st.column_config.TextColumn("Status", width="small"),
        "usage_badge": st.column_config.TextColumn("Usage", width="small"),
        "output_product_display": st.column_config.TextColumn("Output Product", width="large"),
        "quantity": st.column_config.TextColumn("Qty", width="small"),
        "uom": st.column_config.TextColumn("UOM", width="small"),
        "scrap_rate": st.column_config.TextColumn("Scrap %", width="small"),
    }
    
    event = st.dataframe(
        display_df[[
            'bom_code', 'bom_name', 'bom_type', 'bom_status', 'usage_badge',
            'output_product_display', 'quantity', 'uom', 'scrap_rate'
        ]],
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_bom_id = results.iloc[selected_idx]['bom_id']
        
        st.info(f"💡 Click 'View BOM' to see details of selected BOM")
        
        col1, col2 = st.columns([1, 3])
        
        with col1:
            if st.button("👁️ View BOM", use_container_width=True, key=f"where_used_view_{selected_bom_id}"):
                state.close_dialog()
                state.open_dialog(state.DIALOG_VIEW, selected_bom_id)
                st.rerun()
    
    st.markdown("---")
    
    # Usage breakdown
    if not alt_results.empty:
        st.markdown("### Alternative Usage Breakdown")
        
        with st.expander("🔀 View Alternative Usage Details", expanded=False):
            for _, row in alt_results.iterrows():
                st.markdown(
                    f"- **{row['bom_code']}** - {row['bom_name']}: "
                    f"Used as {row['usage_type']} | "
                    f"Qty: {row['quantity']} {row['uom']} | "
                    f"Scrap: {row['scrap_rate']}%"
                )
    
    st.markdown("---")
    
    # Export option
    st.markdown("### Export Results")
    
    if st.button("📥 Export to Excel", use_container_width=True, key="where_used_export_btn"):
        _export_results(results, state)


def _export_results(results: pd.DataFrame, state: StateManager):
    """Export results to Excel"""
    try:
        # Create output product display column
        results_copy = results.copy()
        results_copy['output_product_display'] = results_copy.apply(
            lambda row: format_product_display(
                code=row.get('output_product_code', ''),
                name=row.get('output_product_name', ''),
                package_size=row.get('output_package_size'),
                brand=row.get('output_brand'),
                legacy_code=row.get('output_legacy_code')
            ),
            axis=1
        )
        
        export_df = results_copy[[
            'bom_code', 'bom_name', 'bom_type', 'bom_status',
            'usage_type', 'output_product_display', 'material_type',
            'quantity', 'uom', 'scrap_rate'
        ]].copy()
        
        export_df.columns = [
            'BOM Code', 'BOM Name', 'BOM Type', 'Status',
            'Usage Type', 'Output Product', 'Material Type',
            'Quantity', 'UOM', 'Scrap Rate (%)'
        ]
        
        excel_data = export_to_excel(
            export_df,
            sheet_name="Where Used"
        )
        
        create_download_button(
            excel_data,
            filename="where_used_analysis.xlsx",
            label="📥 Download Excel"
        )
        
        st.success("✅ Excel file ready for download!")
    
    except Exception as e:
        logger.error(f"Error exporting results: {e}")
        st.error(f"❌ Export error: {str(e)}")