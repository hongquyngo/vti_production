# utils/bom/dialogs/where_used.py
"""
Where Used Analysis Dialog - FIXED BUTTON KEYS
Find which BOMs use a specific product/material
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
    export_to_excel,
    create_download_button
)

logger = logging.getLogger(__name__)


@st.dialog("🔍 Where Used Analysis", width="large")
def show_where_used_dialog():
    """
    Where used analysis dialog
    Find which BOMs use a specific product/material
    """
    state = StateManager()
    manager = BOMManager()
    
    st.info("ℹ️ Find which BOMs use a specific product or material")
    
    # Product selection
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Check if pre-filled from view dialog
        default_product_id = state.get_where_used_product()
        
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
    
    # Perform search
    if search_clicked and product_id:
        _perform_search(product_id, state, manager)
    
    # Display cached results if available
    results = state.get_where_used_results()
    
    if results is not None:
        _render_results(results, state, manager)
    
    st.markdown("---")
    
    # Close button
    if st.button("✔ Close", use_container_width=True, key="where_used_close_btn"):
        state.close_dialog()
        st.rerun()


def _perform_search(product_id: int, state: StateManager, manager: BOMManager):
    """
    Perform where used search
    
    Args:
        product_id: Product ID to search
        state: State manager
        manager: BOM manager
    """
    try:
        state.set_loading(True)
        
        # Search
        results = manager.get_where_used(product_id)
        
        # Cache results
        state.set_where_used_product(product_id)
        state.set_where_used_results(results)
        
        state.set_loading(False)
    
    except Exception as e:
        logger.error(f"Error searching where used: {e}")
        state.set_loading(False)
        st.error(f"❌ Search error: {str(e)}")


def _render_results(results: pd.DataFrame, state: StateManager, manager: BOMManager):
    """
    Render search results
    
    Args:
        results: Search results DataFrame
        state: State manager
        manager: BOM manager
    """
    if results.empty:
        st.info("ℹ️ This product is not used in any BOM")
        return
    
    # Summary
    st.success(f"✅ Found in **{len(results)}** BOM(s)")
    
    # Statistics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total BOMs", len(results))
    
    with col2:
        active_count = len(results[results['bom_status'] == 'ACTIVE'])
        st.metric("Active BOMs", active_count)
    
    with col3:
        draft_count = len(results[results['bom_status'] == 'DRAFT'])
        st.metric("Draft BOMs", draft_count)
    
    with col4:
        total_qty = results['quantity'].sum()
        st.metric("Total Usage", format_number(total_qty, 2))
    
    st.markdown("---")
    
    # Results table
    st.markdown("### Search Results")
    
    # Format for display
    display_df = results.copy()
    display_df['bom_status'] = display_df['bom_status'].apply(create_status_indicator)
    display_df['quantity'] = display_df['quantity'].apply(lambda x: format_number(x, 4))
    display_df['scrap_rate'] = display_df['scrap_rate'].apply(lambda x: f"{format_number(x, 2)}%")
    
    # Column config
    column_config = {
        "bom_code": st.column_config.TextColumn("BOM Code", width="medium"),
        "bom_name": st.column_config.TextColumn("BOM Name", width="large"),
        "bom_type": st.column_config.TextColumn("Type", width="small"),
        "bom_status": st.column_config.TextColumn("Status", width="small"),
        "output_product_name": st.column_config.TextColumn("Output Product", width="large"),
        "quantity": st.column_config.TextColumn("Quantity", width="small"),
        "uom": st.column_config.TextColumn("UOM", width="small"),
        "scrap_rate": st.column_config.TextColumn("Scrap %", width="small"),
    }
    
    # Display table with selection
    event = st.dataframe(
        display_df[[
            'bom_code', 'bom_name', 'bom_type', 'bom_status',
            'output_product_name', 'quantity', 'uom', 'scrap_rate'
        ]],
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Handle row click - open view dialog
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_bom_id = results.iloc[selected_idx]['bom_id']
        
        st.info(f"💡 Click 'View BOM' to see details of selected BOM")
        
        col1, col2 = st.columns([1, 3])
        
        with col1:
            if st.button("👁️ View BOM", use_container_width=True, key=f"where_used_view_{selected_bom_id}"):
                # Close where used dialog and open view dialog
                state.close_dialog()
                state.open_dialog(state.DIALOG_VIEW, selected_bom_id)
                st.rerun()
    
    st.markdown("---")
    
    # Export option
    st.markdown("### Export Results")
    
    if st.button("📥 Export to Excel", use_container_width=True, key="where_used_export_btn"):
        _export_results(results, state)


def _export_results(results: pd.DataFrame, state: StateManager):
    """
    Export results to Excel
    
    Args:
        results: Results DataFrame
        state: State manager
    """
    try:
        # Prepare export data
        export_df = results[[
            'bom_code', 'bom_name', 'bom_type', 'bom_status',
            'output_product_name', 'material_type',
            'quantity', 'uom', 'scrap_rate'
        ]].copy()
        
        # Clean column names
        export_df.columns = [
            'BOM Code', 'BOM Name', 'BOM Type', 'Status',
            'Output Product', 'Material Type',
            'Quantity', 'UOM', 'Scrap Rate (%)'
        ]
        
        # Export to Excel
        excel_data = export_to_excel(
            export_df,
            sheet_name="Where Used"
        )
        
        # Download button
        create_download_button(
            excel_data,
            filename="where_used_analysis.xlsx",
            label="📥 Download Excel"
        )
        
        st.success("✅ Excel file ready for download!")
    
    except Exception as e:
        logger.error(f"Error exporting results: {e}")
        st.error(f"❌ Export error: {str(e)}")