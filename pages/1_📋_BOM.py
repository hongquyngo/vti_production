# pages/1___BOM.py
"""
Bill of Materials (BOM) Management - VERSION 2.5
Clean single-page UI with dialog-driven workflows

Changes in v2.5:
- Added Multiple Active BOM Conflict detection (Phase 2)
- New metric card showing conflict count
- Visual badge (🔴 2 Active) for products with multiple active BOMs
- Click on Conflicts metric filters to show only conflicting BOMs

Changes in v2.4:
- Updated product display format: code (legacy | N/A) | name | pkg (brand)

Changes in v2.3:
- Updated search placeholder to reflect extended search capabilities

Changes in v2.2:
- Added duplicate materials warning badge in BOM list
- Visual indicator for BOMs with duplicate materials

Changes in v2.1:
- Updated Edit button logic to use usage-based edit levels
- Edit enabled for INACTIVE BOMs without usage
- Better help text based on actual edit capability
"""

import streamlit as st
import pandas as pd
import logging
from datetime import datetime
from io import BytesIO

from utils.auth import AuthManager
from utils.bom.manager import BOMManager
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_number,
    format_product_display,
    get_products,
    # New imports for edit levels
    EditLevel,
    get_edit_level,
    # Duplicate detection
    get_boms_with_duplicate_check,
    # Phase 2: Multiple Active BOM Conflict Detection
    get_boms_with_active_conflict_check,
    get_products_with_multiple_active_boms
)

# Import dialogs
from utils.bom.dialogs.create import show_create_dialog
from utils.bom.dialogs.view import show_view_dialog
from utils.bom.dialogs.edit import show_edit_dialog
from utils.bom.dialogs.delete import show_delete_dialog
from utils.bom.dialogs.status import show_status_dialog
from utils.bom.dialogs.where_used import show_where_used_dialog
from utils.bom.dialogs.clone import show_clone_dialog
from utils.bom.dialogs.export import show_export_dialog

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

# ==================== Cache Management ====================

def load_products_to_cache():
    """Load products to cache if not already cached"""
    cached = state.get_cached_products()
    if cached is None:
        products = get_products()
        state.set_cached_products(products)
        logger.info("Products loaded to cache")

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    
    # Load products to cache on page load
    load_products_to_cache()
    
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
    render_footer()


def render_header():
    """Render page header with action buttons"""
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    with col1:
        st.title("📋 BOM Management")
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔍 Where Used", use_container_width=True):
            state.open_dialog(state.DIALOG_WHERE_USED)
            st.rerun()
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            state.clear_cache()
            # Also clear conflict cache
            if 'conflict_products' in st.session_state:
                del st.session_state['conflict_products']
            st.rerun()
    
    with col4:
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
    """Render filters and metrics with conflict detection"""
    st.markdown("### 🔍 Filters & Metrics")
    
    # Metrics row - 6 columns now including Conflicts
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    # Get BOMs for metrics (use cached if available)
    if 'all_boms' not in st.session_state:
        st.session_state['all_boms'] = bom_manager.get_boms()
    
    all_boms = st.session_state['all_boms']
    
    # Get conflict data (products with multiple active BOMs)
    if 'conflict_products' not in st.session_state:
        st.session_state['conflict_products'] = get_products_with_multiple_active_boms()
    
    conflict_products = st.session_state['conflict_products']
    conflict_product_count = len(conflict_products)
    
    # Count BOMs affected by conflicts
    conflict_bom_ids = set()
    for product_id, boms in conflict_products.items():
        for bom in boms:
            conflict_bom_ids.add(bom['bom_id'])
    conflict_bom_count = len(conflict_bom_ids)
    
    with col1:
        st.metric("Total BOMs", len(all_boms))
    
    with col2:
        active_count = len(all_boms[all_boms['status'] == 'ACTIVE'])
        st.metric("Active", active_count)
    
    with col3:
        draft_count = len(all_boms[all_boms['status'] == 'DRAFT'])
        st.metric("Draft", draft_count)
    
    with col4:
        inactive_count = len(all_boms[all_boms['status'] == 'INACTIVE'])
        st.metric("Inactive", inactive_count)
    
    with col5:
        in_use_count = len(all_boms[all_boms['usage_count'] > 0])
        st.metric("In Use", in_use_count)
    
    with col6:
        # Conflicts metric with warning color
        if conflict_product_count > 0:
            st.metric(
                "⚠️ Conflicts", 
                conflict_bom_count,
                delta=f"{conflict_product_count} products",
                delta_color="inverse",
                help=f"{conflict_product_count} product(s) have multiple active BOMs"
            )
        else:
            st.metric(
                "✅ Conflicts", 
                0,
                help="No products with multiple active BOMs"
            )
    
    # Show conflict summary warning if any
    if conflict_product_count > 0:
        st.warning(
            f"⚠️ **{conflict_product_count} product(s)** have multiple active BOMs "
            f"({conflict_bom_count} BOMs affected). Use 'Show Conflicts Only' filter to review."
        )
    
    st.markdown("---")
    
    # Filters row - 5 columns now
    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
    
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
            placeholder="BOM, product, material, brand, creator...",
            key="filter_search"
        )
    
    with col4:
        # New filter: Show conflicts only
        filter_conflicts = st.checkbox(
            "🔴 Conflicts Only",
            key="filter_conflicts",
            help="Show only BOMs where product has multiple active BOMs"
        )
    
    with col5:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button("🔍 Search", use_container_width=True)
    
    # Apply filters
    if search_clicked or 'filtered_boms' not in st.session_state:
        try:
            filtered_boms = bom_manager.get_boms(
                bom_type=filter_type if filter_type != "All" else None,
                status=filter_status if filter_status != "All" else None,
                search=filter_search if filter_search else None
            )
            
            # Apply conflict filter if enabled
            if filter_conflicts and conflict_bom_ids:
                filtered_boms = filtered_boms[filtered_boms['id'].isin(conflict_bom_ids)]
            
            st.session_state['filtered_boms'] = filtered_boms
        except Exception as e:
            logger.error(f"Error filtering BOMs: {e}")
            st.error(f"❌ Error: {str(e)}")
            st.session_state['filtered_boms'] = pd.DataFrame()


def render_bom_table():
    """Render BOM table with actions, duplicate warnings, and conflict badges"""
    st.markdown("### 📋 BOM List")
    
    # Get filtered BOMs
    boms = st.session_state.get('filtered_boms', pd.DataFrame())
    
    if boms.empty:
        st.info("ℹ️ No BOMs found. Create your first BOM using the button above.")
        return
    
    # Check for duplicates in all BOMs (cached for performance)
    bom_ids = boms['id'].tolist()
    duplicates_map = get_boms_with_duplicate_check(bom_ids)
    
    # Phase 2: Check for active BOM conflicts
    conflicts_map = get_boms_with_active_conflict_check(bom_ids)
    
    # Count BOMs with duplicates for summary
    boms_with_duplicates = sum(1 for v in duplicates_map.values() if v)
    
    # Count BOMs with conflicts (other active BOMs for same product)
    boms_with_conflicts = sum(1 for v in conflicts_map.values() if v > 0)
    
    # Show summary warnings
    if boms_with_duplicates > 0:
        st.warning(f"⚠️ **Warning:** {boms_with_duplicates} BOM(s) have duplicate materials. See 'Issues' column for details.")
    
    # Format display data
    display_df = boms.copy()
    
    # Add duplicate warning flag
    display_df['has_duplicate'] = display_df['id'].apply(lambda x: duplicates_map.get(x, False))
    
    # Add conflict count
    display_df['conflict_count'] = display_df['id'].apply(lambda x: conflicts_map.get(x, 0))
    
    # Combined Issues column (Phase 2 enhancement)
    def format_issues_display(row):
        issues = []
        
        # Check conflict (only for ACTIVE BOMs)
        if row['status'] == 'ACTIVE' and row['conflict_count'] > 0:
            total_active = row['conflict_count'] + 1  # Include current BOM
            issues.append(f"🔴 {total_active} Active")
        
        # Check duplicate
        if row['has_duplicate']:
            issues.append("⚠️ Dup")
        
        return " | ".join(issues) if issues else ""
    
    display_df['issues_display'] = display_df.apply(format_issues_display, axis=1)
    
    # Format columns for display
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['output_display'] = display_df.apply(
        lambda row: f"{format_number(row['output_qty'], 2)} {row['uom']}", 
        axis=1
    )
    display_df['product_display'] = display_df.apply(
        lambda row: format_product_display(
            code=row['product_code'],
            name=row['product_name'],
            package_size=row.get('package_size'),
            brand=row.get('brand'),
            legacy_code=row.get('legacy_code')
        ),
        axis=1
    )
    display_df['materials_display'] = display_df['material_count'].apply(
        lambda x: f"📦 {int(x)}" if pd.notna(x) else "📦 0"
    )
    display_df['usage_display'] = display_df['usage_count'].apply(
        lambda x: f"🏭 {int(x)}" if x > 0 else "-"
    )
    
    # Creator display - format date nicely
    display_df['creator_display'] = display_df.apply(
        lambda row: f"{row.get('creator_name', 'Unknown')}", 
        axis=1
    )
    display_df['created_display'] = display_df['created_date'].apply(
        lambda x: x.strftime('%d/%m/%Y') if pd.notna(x) else '-'
    )
    
    # Select columns to display (combined issues column)
    display_columns = [
        'bom_code', 'bom_name', 'bom_type', 'product_display',
        'output_display', 'status_display', 'materials_display', 
        'usage_display', 'issues_display', 'created_display'
    ]
    
    # Column configuration
    column_config = {
        "bom_code": st.column_config.TextColumn("BOM Code", width="small"),
        "bom_name": st.column_config.TextColumn("BOM Name", width="medium"),
        "bom_type": st.column_config.TextColumn("Type", width="small"),
        "product_display": st.column_config.TextColumn("Output Product", width="large"),
        "output_display": st.column_config.TextColumn("Output", width="small"),
        "status_display": st.column_config.TextColumn("Status", width="small"),
        "materials_display": st.column_config.TextColumn("Mat.", width="small"),
        "usage_display": st.column_config.TextColumn("Usage", width="small"),
        "issues_display": st.column_config.TextColumn("Issues", width="medium"),
        "created_display": st.column_config.TextColumn("Date", width="small"),
    }
    
    # Display dataframe with selection
    event = st.dataframe(
        display_df[display_columns],
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        on_select="rerun",
        selection_mode="single-row",
        key="bom_table"
    )
    
    # Handle row selection
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_bom = boms.iloc[selected_idx]
        selected_bom_id = selected_bom['id']
        
        st.markdown("---")
        
        # Action buttons for selected BOM
        st.markdown(f"### Actions for: **{selected_bom['bom_code']}** - {selected_bom['bom_name']}")
        
        # Show conflict warning if this BOM has conflicts (Phase 2)
        conflict_count = conflicts_map.get(selected_bom_id, 0)
        if selected_bom['status'] == 'ACTIVE' and conflict_count > 0:
            st.error(
                f"🔴 **Multiple Active BOMs Conflict:** This product has {conflict_count + 1} active BOMs. "
                f"Click 'Status' to deactivate others or review."
            )
        
        # Show duplicate warning if this BOM has duplicates
        if duplicates_map.get(selected_bom_id, False):
            st.warning("⚠️ **This BOM has duplicate materials!** Click 'View' for details or 'Edit' to fix.")
        
        # Get edit level for this BOM
        bom_info_for_level = {
            'status': selected_bom['status'],
            'total_usage': selected_bom['usage_count'],
            'active_orders': 0,  # Will be fetched when needed in edit dialog
            'material_count': selected_bom['material_count']
        }
        
        # For more accurate edit level, we need active_orders
        # But for button display, we can use a simplified check
        edit_level = _get_simplified_edit_level(selected_bom)
        
        # First row of buttons
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("👁️ View", use_container_width=True, key=f"view_btn_{selected_bom_id}"):
                state.open_dialog(state.DIALOG_VIEW, selected_bom_id)
                st.rerun()
        
        with col2:
            # Edit button - enabled based on edit level
            can_edit = edit_level > EditLevel.READ_ONLY
            help_text = _get_edit_button_help(edit_level, selected_bom)
            
            if st.button(
                "✏️ Edit",
                use_container_width=True,
                disabled=not can_edit,
                key=f"edit_btn_{selected_bom_id}",
                help=help_text
            ):
                state.open_dialog(state.DIALOG_EDIT, selected_bom_id)
                st.rerun()
        
        with col3:
            if st.button("🔄 Clone", use_container_width=True, key=f"clone_btn_{selected_bom_id}"):
                state.open_dialog(state.DIALOG_CLONE, selected_bom_id)
                st.rerun()
        
        with col4:
            if st.button("📥 Export", use_container_width=True, key=f"export_btn_{selected_bom_id}"):
                state.open_dialog(state.DIALOG_EXPORT, selected_bom_id)
                st.rerun()
        
        # Second row of buttons
        col5, col6, col7, col8 = st.columns(4)
        
        with col5:
            if st.button("📊 Status", use_container_width=True, key=f"status_btn_{selected_bom_id}"):
                state.open_dialog(state.DIALOG_STATUS, selected_bom_id)
                st.rerun()
        
        with col6:
            if st.button("🔍 Where Used", use_container_width=True, key=f"where_btn_{selected_bom_id}"):
                state.set_where_used_product(selected_bom['product_id'])
                state.open_dialog(state.DIALOG_WHERE_USED)
                st.rerun()
        
        with col7:
            # Delete only for non-active BOMs with no usage
            disabled = selected_bom['status'] == 'ACTIVE' or selected_bom['usage_count'] > 0
            if st.button(
                "🗑️ Delete",
                use_container_width=True,
                disabled=disabled,
                type="secondary",
                key=f"delete_btn_{selected_bom_id}",
                help="Cannot delete ACTIVE BOMs or BOMs in use"
            ):
                state.open_dialog(state.DIALOG_DELETE, selected_bom_id)
                st.rerun()
        
        with col8:
            pass  # Spacer for alignment


def _get_simplified_edit_level(bom_row: pd.Series) -> int:
    """
    Get simplified edit level for button display
    Note: Full edit level requires active_orders which needs DB query
    """
    status = bom_row['status']
    usage_count = int(bom_row.get('usage_count', 0))
    
    if status == 'DRAFT':
        return EditLevel.FULL_EDIT
    
    if status == 'ACTIVE':
        if usage_count == 0:
            return EditLevel.FULL_EDIT
        else:
            # Could be ALTERNATIVES_PLUS or READ_ONLY depending on active orders
            # Conservative assumption: at least alternatives
            return EditLevel.ALTERNATIVES_PLUS
    
    if status == 'INACTIVE':
        if usage_count == 0:
            return EditLevel.FULL_EDIT
        else:
            return EditLevel.READ_ONLY
    
    return EditLevel.READ_ONLY


def _get_edit_button_help(edit_level: int, bom_row: pd.Series) -> str:
    """Get help text for edit button based on edit level"""
    status = bom_row['status']
    usage_count = int(bom_row.get('usage_count', 0))
    
    if edit_level == EditLevel.FULL_EDIT:
        if status == 'DRAFT':
            return "Full edit mode - Modify all BOM information"
        else:
            return "Full edit mode - BOM has never been used"
    
    if edit_level == EditLevel.ALTERNATIVES_PLUS:
        return "Limited edit - Alternatives only (BOM has active orders)"
    
    if edit_level == EditLevel.METADATA_ONLY:
        return "Metadata only - Name, notes, effective date"
    
    # READ_ONLY
    if status == 'INACTIVE' and usage_count > 0:
        return f"Read only - BOM has {usage_count} historical order(s). Use Clone instead."
    
    return f"Read only - BOM has {usage_count} completed order(s). Use Clone instead."


def render_active_dialog():
    """Render the currently active dialog"""
    open_dialog = state.get_open_dialog()
    
    if not open_dialog:
        return
    
    # Get current BOM ID if needed
    bom_id = state.get_current_bom()
    
    try:
        if open_dialog == state.DIALOG_CREATE:
            show_create_dialog()
        
        elif open_dialog == state.DIALOG_VIEW and bom_id:
            show_view_dialog(bom_id)
        
        elif open_dialog == state.DIALOG_EDIT and bom_id:
            show_edit_dialog(bom_id)
        
        elif open_dialog == state.DIALOG_DELETE and bom_id:
            show_delete_dialog(bom_id)
        
        elif open_dialog == state.DIALOG_STATUS and bom_id:
            show_status_dialog(bom_id)
        
        elif open_dialog == state.DIALOG_WHERE_USED:
            show_where_used_dialog()
        
        elif open_dialog == state.DIALOG_CLONE and bom_id:
            show_clone_dialog(bom_id)
        
        elif open_dialog == state.DIALOG_EXPORT and bom_id:
            show_export_dialog(bom_id)
    
    except Exception as e:
        logger.error(f"Error rendering dialog {open_dialog}: {e}")
        st.error(f"❌ Error opening dialog: {str(e)}")
        state.close_dialog()


def render_footer():
    """Render page footer"""
    st.markdown("---")
    
    # Last action info
    last_action = state.get_last_action()
    if last_action.get('type'):
        action_text = f"Last action: {last_action['type'].title()}"
        if last_action.get('bom_code'):
            action_text += f" - {last_action['bom_code']}"
        if last_action.get('timestamp'):
            action_text += f" at {last_action['timestamp'].strftime('%H:%M:%S')}"
        st.caption(action_text)
    
    # Version info
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.caption("Manufacturing Module v2.5 - BOM Management | Multiple Active BOM Conflict Detection")
    
    with col2:
        st.caption(f"Session: {st.session_state.get('user_name', 'Guest')}")


# ==================== Export Functions ====================

def export_boms_to_excel(boms: pd.DataFrame) -> bytes:
    """Export BOMs to Excel file"""
    output = BytesIO()
    
    # Prepare data for export
    export_df = boms[[
        'bom_code', 'bom_name', 'bom_type', 'product_name',
        'output_qty', 'uom', 'status', 'material_count',
        'usage_count', 'effective_date', 'created_date'
    ]].copy()
    
    # Rename columns for export
    export_df.columns = [
        'BOM Code', 'BOM Name', 'Type', 'Product',
        'Output Qty', 'UOM', 'Status', 'Materials',
        'Usage Count', 'Effective Date', 'Created Date'
    ]
    
    # Write to Excel
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        export_df.to_excel(writer, sheet_name='BOMs', index=False)
        
        # Auto-adjust column width
        worksheet = writer.sheets['BOMs']
        for idx, col in enumerate(export_df.columns):
            max_len = max(
                export_df[col].astype(str).str.len().max(),
                len(str(col))
            )
            worksheet.set_column(idx, idx, min(max_len + 2, 50))
    
    return output.getvalue()


# ==================== Run Application ====================

if __name__ == "__main__":
    main()