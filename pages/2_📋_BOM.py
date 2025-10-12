# pages/2_📋_BOM.py - Complete BOM Management (Refactored)
"""
Bill of Materials (BOM) Management
Clean single-page UI with dialog-driven workflows
"""

import streamlit as st
import pandas as pd
import logging

from utils.auth import AuthManager
from utils.bom.manager import BOMManager
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_number
)

# Import dialogs
from utils.bom.dialogs.create import show_create_dialog
from utils.bom.dialogs.view import show_view_dialog
from utils.bom.dialogs.edit import show_edit_dialog
from utils.bom.dialogs.delete import show_delete_dialog
from utils.bom.dialogs.status import show_status_dialog
from utils.bom.dialogs.where_used import show_where_used_dialog

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="BOM Management",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Initialize Managers ====================

@st.cache_resource
def get_managers():
    """Initialize and cache managers"""
    return BOMManager(), StateManager()

bom_manager, state = get_managers()

# Initialize state
state.init_state()

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    
    # Header with create button
    render_header()
    
    # Show messages if any
    render_messages()
    
    # Filters and metrics
    render_filters_and_metrics()
    
    # BOM table
    render_bom_table()
    
    # Mount active dialog
    render_active_dialog()
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v2.0 - BOM Management | Dialog-driven UI")


def render_header():
    """Render page header with create button"""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.title("📋 BOM Management")
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Create BOM", type="primary", use_container_width=True):
            state.open_dialog(state.DIALOG_CREATE)
            st.rerun()


def render_messages():
    """Render success/error messages"""
    show_success, show_error, message = state.get_message()
    
    if show_success:
        st.success(message)
        state.clear_messages()
    elif show_error:
        st.error(message)
        state.clear_messages()


def render_filters_and_metrics():
    """Render filters and metrics"""
    st.markdown("### 🔍 Filters")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        filter_type = st.selectbox(
            "BOM Type",
            ["All", "KITTING", "CUTTING", "REPACKING"],
            key="filter_type"
        )
    
    with col2:
        filter_status = st.selectbox(
            "Status",
            ["All", "DRAFT", "ACTIVE", "INACTIVE"],
            key="filter_status"
        )
    
    with col3:
        filter_search = st.text_input(
            "Search",
            placeholder="Code or name...",
            key="filter_search"
        )
    
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button("🔍 Search", use_container_width=True)
    
    # Get BOMs with filters
    try:
        boms = bom_manager.get_boms(
            bom_type=filter_type if filter_type != "All" else None,
            status=filter_status if filter_status != "All" else None,
            search=filter_search if filter_search else None
        )
        
        # Store in session for table rendering
        st.session_state['filtered_boms'] = boms
        
        if boms.empty:
            st.info("ℹ️ No BOMs found")
            return
        
        # Metrics
        st.markdown("---")
        st.markdown("### 📊 Summary")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total", len(boms))
        
        with col2:
            active_count = len(boms[boms['status'] == 'ACTIVE'])
            st.metric("Active", active_count)
        
        with col3:
            draft_count = len(boms[boms['status'] == 'DRAFT'])
            st.metric("Draft", draft_count)
        
        with col4:
            inactive_count = len(boms[boms['status'] == 'INACTIVE'])
            st.metric("Inactive", inactive_count)
    
    except Exception as e:
        logger.error(f"Error loading BOMs: {e}")
        st.error(f"❌ Error loading BOMs: {str(e)}")
        st.session_state['filtered_boms'] = pd.DataFrame()


def render_bom_table():
    """Render BOM table with action buttons"""
    boms = st.session_state.get('filtered_boms', pd.DataFrame())
    
    if boms.empty:
        return
    
    st.markdown("---")
    st.markdown("### 📋 Bill of Materials List")
    
    # Format display
    display_df = boms.copy()
    display_df['status'] = display_df['status'].apply(create_status_indicator)
    display_df['output_qty'] = display_df['output_qty'].apply(
        lambda x: format_number(x, 2)
    )
    
    # Column config
    column_config = {
        "bom_code": st.column_config.TextColumn("BOM Code", width="medium"),
        "bom_name": st.column_config.TextColumn("BOM Name", width="large"),
        "bom_type": st.column_config.TextColumn("Type", width="small"),
        "product_name": st.column_config.TextColumn("Product", width="large"),
        "output_qty": st.column_config.TextColumn("Output Qty", width="small"),
        "uom": st.column_config.TextColumn("UOM", width="small"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "material_count": st.column_config.NumberColumn("Materials", width="small"),
    }
    
    # Selectable dataframe
    event = st.dataframe(
        display_df[[
            'bom_code', 'bom_name', 'bom_type', 'product_name',
            'output_qty', 'uom', 'status', 'material_count'
        ]],
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Handle row selection
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_bom_id = boms.iloc[selected_idx]['id']
        
        st.markdown("---")
        st.markdown("### 🎯 Actions")
        
        render_action_buttons(selected_bom_id, boms.iloc[selected_idx])


def render_action_buttons(bom_id: int, bom_data: pd.Series):
    """
    Render action buttons for selected BOM
    
    Args:
        bom_id: Selected BOM ID
        bom_data: Selected BOM data
    """
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        if st.button("👁️ View", use_container_width=True):
            state.open_dialog(state.DIALOG_VIEW, bom_id)
            st.rerun()
    
    with col2:
        # Edit only for DRAFT
        disabled = bom_data['status'] != 'DRAFT'
        if st.button(
            "✏️ Edit",
            disabled=disabled,
            use_container_width=True,
            help="Only DRAFT BOMs can be edited" if disabled else None
        ):
            state.open_dialog(state.DIALOG_EDIT, bom_id)
            st.rerun()
    
    with col3:
        if st.button("🔄 Status", use_container_width=True):
            state.open_dialog(state.DIALOG_STATUS, bom_id)
            st.rerun()
    
    with col4:
        if st.button("🔍 Where Used", use_container_width=True):
            # Pre-fill product for where used
            state.set_where_used_product(bom_data['product_id'])
            state.open_dialog(state.DIALOG_WHERE_USED)
            st.rerun()
    
    with col5:
        # Delete only non-ACTIVE with no usage
        can_delete = (
            bom_data['status'] != 'ACTIVE' and 
            bom_data.get('usage_count', 0) == 0
        )
        
        if st.button(
            "🗑️ Delete",
            type="secondary",
            disabled=not can_delete,
            use_container_width=True,
            help="Cannot delete ACTIVE BOMs or BOMs in use" if not can_delete else None
        ):
            state.open_dialog(state.DIALOG_DELETE, bom_id)
            st.rerun()
    
    with col6:
        if st.button("📥 Export", use_container_width=True):
            export_bom(bom_id, bom_data)


def export_bom(bom_id: int, bom_data: pd.Series):
    """
    Export BOM to Excel with complete information (MINIMAL template)
    
    Includes:
    - BOM header information (code, name, type, status, version)
    - Output product details
    - Materials table with formatting
    - Summary statistics
    - Notes section
    - Creator information
    - Generation timestamp
    
    Args:
        bom_id: BOM ID to export
        bom_data: BOM data series from main table
    """
    try:
        import pandas as pd
        from io import BytesIO
        from datetime import datetime
        from utils.db import get_db_engine
        
        # ==================== DATA COLLECTION ====================
        
        # Get full BOM data
        bom_info = bom_manager.get_bom_info(bom_id)
        bom_details = bom_manager.get_bom_details(bom_id)
        
        # Validation
        if not bom_info:
            st.error("❌ BOM not found")
            return
        
        if bom_details.empty:
            st.warning("⚠️ No materials to export")
            return
        
        # ==================== CREATOR INFORMATION ====================
        
        # Get creator name with proper fallbacks
        created_info = "N/A"
        created_date = str(bom_info.get('created_date', ''))[:10] if bom_info.get('created_date') else 'Unknown'
        
        if bom_info.get('created_by'):
            try:
                creator_query = f"""
                    SELECT 
                        COALESCE(
                            CONCAT(e.first_name, ' ', e.last_name),
                            u.username,
                            'Unknown User'
                        ) as full_name
                    FROM users u
                    LEFT JOIN employees e ON u.employee_id = e.id
                    WHERE u.id = {bom_info['created_by']}
                """
                engine = get_db_engine()
                creator_result = pd.read_sql(creator_query, engine)
                
                if not creator_result.empty:
                    creator_name = creator_result.iloc[0]['full_name']
                    if creator_name and creator_name not in ['Unknown User', 'None', '']:
                        created_info = f"{creator_name} on {created_date}"
                    else:
                        created_info = f"User ID {bom_info['created_by']} on {created_date}"
                else:
                    created_info = f"User ID {bom_info['created_by']} on {created_date}"
            except Exception as e:
                logger.warning(f"Could not fetch creator info: {e}")
                created_info = f"User ID {bom_info['created_by']} on {created_date}"
        else:
            created_info = f"System on {created_date}"
        
        # ==================== EXCEL GENERATION ====================
        
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            worksheet = workbook.add_worksheet('BOM')
            
            # ==================== FORMAT DEFINITIONS ====================
            
            # Title format (large, bold, blue background)
            header_format = workbook.add_format({
                'bold': True,
                'font_size': 14,
                'align': 'center',
                'valign': 'vcenter',
                'bg_color': '#4472C4',
                'font_color': 'white',
                'border': 1
            })
            
            # Section header format (bold, light blue)
            section_format = workbook.add_format({
                'bold': True,
                'font_size': 11,
                'align': 'left',
                'valign': 'vcenter',
                'bg_color': '#4472C4',
                'font_color': 'white',
                'border': 1
            })
            
            # Label format (bold, gray background)
            label_format = workbook.add_format({
                'bold': True,
                'align': 'left',
                'valign': 'vcenter',
                'bg_color': '#D9E1F2',
                'border': 1
            })
            
            # Value format (standard)
            value_format = workbook.add_format({
                'align': 'left',
                'valign': 'vcenter',
                'border': 1
            })
            
            # Table header format (bold, centered, blue)
            table_header_format = workbook.add_format({
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'bg_color': '#4472C4',
                'font_color': 'white',
                'border': 1
            })
            
            # Table cell format (standard)
            table_cell_format = workbook.add_format({
                'align': 'left',
                'valign': 'vcenter',
                'border': 1
            })
            
            # Number format (right-aligned, 4 decimals)
            number_format = workbook.add_format({
                'align': 'right',
                'valign': 'vcenter',
                'border': 1,
                'num_format': '0.0000'
            })
            
            # Percentage format (right-aligned, 2 decimals)
            percent_format = workbook.add_format({
                'align': 'right',
                'valign': 'vcenter',
                'border': 1,
                'num_format': '0.00"%"'
            })
            
            # Notes format (wrapped text)
            notes_format = workbook.add_format({
                'align': 'left',
                'valign': 'top',
                'border': 1,
                'text_wrap': True
            })
            
            # Footer format (small, italic)
            footer_format = workbook.add_format({
                'italic': True,
                'font_size': 9,
                'align': 'left',
                'valign': 'vcenter',
                'font_color': '#666666'
            })
            
            # ==================== CONTENT GENERATION ====================
            
            row = 0  # Current row tracker
            
            # --- SECTION 1: TITLE ---
            worksheet.merge_range(row, 0, row, 6, 'BILL OF MATERIALS', header_format)
            worksheet.set_row(row, 25)
            row += 2
            
            # --- SECTION 2: BOM INFORMATION ---
            worksheet.merge_range(row, 0, row, 6, 'BOM INFORMATION', section_format)
            row += 1
            
            # Code & Status
            worksheet.write(row, 0, 'Code:', label_format)
            worksheet.write(row, 1, bom_info['bom_code'], value_format)
            worksheet.write(row, 3, 'Status:', label_format)
            status_text = f"● {bom_info['status']}"
            worksheet.write(row, 4, status_text, value_format)
            row += 1
            
            # Name & Version
            worksheet.write(row, 0, 'Name:', label_format)
            worksheet.merge_range(row, 1, row, 2, bom_info['bom_name'], value_format)
            worksheet.write(row, 3, 'Version:', label_format)
            worksheet.write(row, 4, bom_info.get('version', 1), value_format)
            row += 1
            
            # Type & Effective Date
            worksheet.write(row, 0, 'Type:', label_format)
            worksheet.write(row, 1, bom_info['bom_type'], value_format)
            worksheet.write(row, 3, 'Effective Date:', label_format)
            
            eff_date = bom_info.get('effective_date', '')
            if eff_date and not pd.isna(eff_date):
                eff_date = str(eff_date)
            else:
                eff_date = '-'
            worksheet.write(row, 4, eff_date, value_format)
            row += 2
            
            # --- SECTION 3: OUTPUT PRODUCT ---
            worksheet.merge_range(row, 0, row, 6, 'OUTPUT PRODUCT', section_format)
            row += 1
            
            # Product
            worksheet.write(row, 0, 'Product:', label_format)
            product_text = f"{bom_info['product_name']} ({bom_info['product_code']})"
            worksheet.merge_range(row, 1, row, 4, product_text, value_format)
            row += 1
            
            # Quantity
            worksheet.write(row, 0, 'Quantity:', label_format)
            qty_text = f"{float(bom_info['output_qty']):.2f} {bom_info['uom']}"
            worksheet.write(row, 1, qty_text, value_format)
            row += 2
            
            # --- SECTION 4: CREATOR INFORMATION ---
            worksheet.write(row, 0, 'Created:', label_format)
            worksheet.merge_range(row, 1, row, 4, created_info, value_format)
            row += 2
            
            # --- SECTION 5: MATERIALS TABLE ---
            worksheet.merge_range(row, 0, row, 6, 'MATERIALS REQUIRED', section_format)
            row += 1
            
            # Table headers
            headers = ['No', 'Code', 'Material Name', 'Type', 'Quantity', 'UOM', 'Scrap %']
            for col, header in enumerate(headers):
                worksheet.write(row, col, header, table_header_format)
            row += 1
            
            # Material rows
            material_counts = {
                'RAW_MATERIAL': 0,
                'PACKAGING': 0,
                'CONSUMABLE': 0
            }
            
            for idx, material in bom_details.iterrows():
                # Row number
                worksheet.write(row, 0, idx + 1, table_cell_format)
                
                # Material code
                worksheet.write(row, 1, material['material_code'], table_cell_format)
                
                # Material name
                worksheet.write(row, 2, material['material_name'], table_cell_format)
                
                # Material type (shortened)
                type_map = {
                    'RAW_MATERIAL': 'RAW',
                    'PACKAGING': 'PKG',
                    'CONSUMABLE': 'CONS'
                }
                type_short = type_map.get(material['material_type'], material['material_type'])
                worksheet.write(row, 3, type_short, table_cell_format)
                
                # Quantity (4 decimals)
                worksheet.write(row, 4, float(material['quantity']), number_format)
                
                # UOM
                worksheet.write(row, 5, material['uom'], table_cell_format)
                
                # Scrap rate (percentage)
                worksheet.write(row, 6, float(material['scrap_rate']), percent_format)
                
                # Count materials by type
                mat_type = material['material_type']
                material_counts[mat_type] = material_counts.get(mat_type, 0) + 1
                
                row += 1
            
            row += 1
            
            # --- SECTION 6: SUMMARY ---
            worksheet.merge_range(row, 0, row, 6, 'SUMMARY', section_format)
            row += 1
            
            # Total materials
            total_materials = len(bom_details)
            worksheet.write(row, 0, '• Total Materials:', label_format)
            worksheet.write(row, 1, total_materials, value_format)
            row += 1
            
            # Raw materials count
            worksheet.write(row, 0, '  - Raw Materials:', value_format)
            worksheet.write(row, 1, material_counts['RAW_MATERIAL'], value_format)
            row += 1
            
            # Packaging count
            worksheet.write(row, 0, '  - Packaging:', value_format)
            worksheet.write(row, 1, material_counts['PACKAGING'], value_format)
            row += 1
            
            # Consumables count
            worksheet.write(row, 0, '  - Consumables:', value_format)
            worksheet.write(row, 1, material_counts['CONSUMABLE'], value_format)
            row += 2
            
            # --- SECTION 7: NOTES (if available) ---
            if bom_info.get('notes') and str(bom_info['notes']).strip():
                worksheet.merge_range(row, 0, row, 6, 'NOTES', section_format)
                row += 1
                
                # Write notes with text wrapping
                worksheet.merge_range(row, 0, row + 2, 6, 
                                    str(bom_info['notes']), notes_format)
                worksheet.set_row(row, 45)
                row += 3
            
            row += 1
            
            # --- SECTION 8: FOOTER ---
            generated_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            generated_by = st.session_state.get('username', 'System')
            footer_text = (f"Generated: {generated_time} by {generated_by} | "
                          f"Document: BOM-{bom_info['bom_code']}-v{bom_info.get('version', 1)}")
            
            worksheet.merge_range(row, 0, row, 6, footer_text, footer_format)
            
            # ==================== COLUMN WIDTHS ====================
            
            worksheet.set_column('A:A', 18)  # Labels / No
            worksheet.set_column('B:B', 12)  # Code
            worksheet.set_column('C:C', 35)  # Material Name
            worksheet.set_column('D:D', 8)   # Type
            worksheet.set_column('E:E', 10)  # Quantity
            worksheet.set_column('F:F', 8)   # UOM
            worksheet.set_column('G:G', 10)  # Scrap %
        
        # ==================== FILE DOWNLOAD ====================
        
        # Get file bytes
        excel_data = output.getvalue()
        
        # Generate filename
        version = bom_info.get('version', 1)
        date_str = datetime.now().strftime('%Y%m%d')
        filename = f"BOM_{bom_info['bom_code']}_v{version}_{date_str}.xlsx"
        
        # Create download button
        from utils.bom.common import create_download_button
        
        create_download_button(
            data=excel_data,
            filename=filename,
            label=f"📥 Download {bom_info['bom_code']}"
        )
        
        st.success(f"✅ Excel file ready! ({len(bom_details)} materials)")
    
    except Exception as e:
        logger.error(f"Error exporting BOM {bom_id}: {e}", exc_info=True)
        st.error(f"❌ Export failed: {str(e)}")
        st.info("💡 Please try again or contact support if the issue persists.")


def render_active_dialog():
    """Mount and render active dialog"""
    dialog_name = state.get_open_dialog()
    
    if not dialog_name:
        return
    
    try:
        if dialog_name == state.DIALOG_CREATE:
            show_create_dialog()
        
        elif dialog_name == state.DIALOG_VIEW:
            bom_id = state.get_current_bom()
            if bom_id:
                show_view_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_EDIT:
            bom_id = state.get_current_bom()
            if bom_id:
                show_edit_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_DELETE:
            bom_id = state.get_current_bom()
            if bom_id:
                show_delete_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_STATUS:
            bom_id = state.get_current_bom()
            if bom_id:
                show_status_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_WHERE_USED:
            show_where_used_dialog()
    
    except Exception as e:
        logger.error(f"Error rendering dialog {dialog_name}: {e}")
        st.error(f"❌ Dialog error: {str(e)}")
        state.close_dialog()


# ==================== Run Application ====================

if __name__ == "__main__":
    main()