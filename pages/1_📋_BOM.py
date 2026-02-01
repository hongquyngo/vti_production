# pages/1___BOM.py
"""
Bill of Materials (BOM) Management - VERSION 2.7
Clean single-page UI with dialog-driven workflows

Changes in v2.7:
- Added Circular Dependency Detection (output product = input material)
- New issue badge: 🔄 Circular
- New filter option: Circular in Issues filter
- Critical warning banner for BOMs with circular dependency

Changes in v2.6:
- Smart Filter Bar with multiselect widgets
- Replaced single selects with multiselect for Type, Status, Issues
- Added filters: Date Range, Creator, Brand
- Auto-apply filters (no Search button needed)
- Active filter chips with remove capability
- Fragment-based rendering for better performance
- Export filtered results only
- Default filter: ACTIVE status

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
from datetime import datetime, date, timedelta
from io import BytesIO
from typing import List, Optional

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
    get_products_with_multiple_active_boms,
    # Phase 3: Circular Dependency Detection (Output = Input)
    get_boms_with_circular_dependency_check
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
    
    # Metrics row (non-fragment)
    render_filters_and_metrics()
    
    # Smart Filter Bar + BOM Table (fragment-based for efficient re-rendering)
    render_smart_filter_bar()
    
    # Mount active dialog (outside fragment)
    render_active_dialog()
    
    # Footer
    render_footer()


def render_header():
    """Render page header with action buttons"""
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
    
    with col1:
        st.title("📋 BOM Management")
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔍 Where Used", use_container_width=True):
            state.open_dialog(state.DIALOG_WHERE_USED)
            st.rerun()
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        # Export filtered list button
        filtered_boms = st.session_state.get('filtered_boms', pd.DataFrame())
        if not filtered_boms.empty:
            excel_data = export_boms_to_excel(filtered_boms)
            st.download_button(
                label="📥 Export List",
                data=excel_data,
                file_name=f"BOM_List_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                help=f"Export {len(filtered_boms)} filtered BOMs to Excel"
            )
        else:
            st.button("📥 Export List", use_container_width=True, disabled=True)
    
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            state.clear_cache()
            state.reset_filters()  # Reset filters to default
            # Also clear conflict cache
            if 'conflict_products' in st.session_state:
                del st.session_state['conflict_products']
            st.rerun()
    
    with col5:
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
    """Render metrics row (non-fragment, runs once per page load)"""
    st.markdown("### 📊 Dashboard Metrics")
    
    # Metrics row - 6 columns
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
    
    # Store for use in filters
    st.session_state['conflict_bom_ids'] = conflict_bom_ids
    
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
        if conflict_product_count > 0:
            st.metric(
                "⚠️ Conflicts", 
                conflict_bom_count,
                delta=f"{conflict_product_count} products",
                delta_color="inverse",
                help=f"{conflict_product_count} product(s) have multiple active BOMs"
            )
        else:
            st.metric("✅ Conflicts", 0, help="No products with multiple active BOMs")
    
    if conflict_product_count > 0:
        st.warning(
            f"⚠️ **{conflict_product_count} product(s)** have multiple active BOMs "
            f"({conflict_bom_count} BOMs affected). Use Issues filter to review."
        )


def get_filter_options():
    """Get available options for filter dropdowns from cached data"""
    all_boms = st.session_state.get('all_boms', pd.DataFrame())
    
    if all_boms.empty:
        return {
            'bom_codes': [],
            'bom_names': [],
            'products': [],
            'creators': [],
            'brands': []
        }
    
    # Get unique BOM codes
    bom_codes = all_boms['bom_code'].dropna().unique().tolist()
    bom_codes.sort()
    
    # Get unique BOM names
    bom_names = all_boms['bom_name'].dropna().unique().tolist()
    bom_names.sort()
    
    # Get unique products (format: code - name)
    products = []
    product_seen = set()
    for _, row in all_boms.iterrows():
        prod_code = row.get('product_code', '')
        prod_name = row.get('product_name', '')
        if prod_code and prod_code not in product_seen:
            product_seen.add(prod_code)
            products.append(f"{prod_code} - {prod_name}")
    products.sort()
    
    # Get unique creators (non-null)
    creators = all_boms['creator_name'].dropna().unique().tolist()
    creators = [c for c in creators if c and c != 'Unknown']
    creators.sort()
    
    # Get unique brands (non-null)
    brands = all_boms['brand'].dropna().unique().tolist()
    brands = [b for b in brands if b and str(b).strip()]
    brands.sort()
    
    return {
        'bom_codes': bom_codes,
        'bom_names': bom_names,
        'products': products,
        'creators': creators,
        'brands': brands
    }


def apply_smart_filters(boms: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all smart filters to BOM dataframe
    
    Args:
        boms: Source DataFrame with all BOMs
        
    Returns:
        Filtered DataFrame
    """
    if boms.empty:
        return boms
    
    filtered = boms.copy()
    
    # Get filter values from state
    filter_bom_codes = state.get_filter_bom_codes()
    filter_bom_names = state.get_filter_bom_names()
    filter_products = state.get_filter_products()
    filter_types = state.get_filter_types()
    filter_statuses = state.get_filter_statuses()
    filter_issues = state.get_filter_issues()
    filter_date_from, filter_date_to = state.get_filter_date_range()
    filter_creators = state.get_filter_creators()
    filter_brands = state.get_filter_brands()
    
    # Apply BOM Code filter
    if filter_bom_codes:
        filtered = filtered[filtered['bom_code'].isin(filter_bom_codes)]
    
    # Apply BOM Name filter
    if filter_bom_names:
        filtered = filtered[filtered['bom_name'].isin(filter_bom_names)]
    
    # Apply Product filter (format: "code - name")
    if filter_products:
        # Extract product codes from filter values
        product_codes = [p.split(' - ')[0] for p in filter_products]
        filtered = filtered[filtered['product_code'].isin(product_codes)]
    
    # Apply Type filter
    if filter_types:
        filtered = filtered[filtered['bom_type'].isin(filter_types)]
    
    # Apply Status filter
    if filter_statuses:
        filtered = filtered[filtered['status'].isin(filter_statuses)]
    
    # Apply Date Range filter (created_date)
    if filter_date_from:
        filtered = filtered[filtered['created_date'].dt.date >= filter_date_from]
    
    if filter_date_to:
        filtered = filtered[filtered['created_date'].dt.date <= filter_date_to]
    
    # Apply Creator filter
    if filter_creators:
        filtered = filtered[filtered['creator_name'].isin(filter_creators)]
    
    # Apply Brand filter
    if filter_brands:
        filtered = filtered[filtered['brand'].isin(filter_brands)]
    
    # Apply Issues filter (requires additional checks)
    if filter_issues:
        # Get duplicate, conflict, and circular maps
        bom_ids = filtered['id'].tolist()
        duplicates_map = get_boms_with_duplicate_check(bom_ids)
        conflicts_map = get_boms_with_active_conflict_check(bom_ids)
        circular_map = get_boms_with_circular_dependency_check(bom_ids)
        
        # Build mask based on selected issues
        mask = pd.Series([False] * len(filtered), index=filtered.index)
        
        if 'Conflicts' in filter_issues:
            # BOMs with conflicts (ACTIVE status and conflict_count > 0)
            for idx, row in filtered.iterrows():
                if row['status'] == 'ACTIVE' and conflicts_map.get(row['id'], 0) > 0:
                    mask[idx] = True
        
        if 'Duplicates' in filter_issues:
            # BOMs with duplicate materials
            for idx, row in filtered.iterrows():
                if duplicates_map.get(row['id'], False):
                    mask[idx] = True
        
        if 'Circular' in filter_issues:
            # BOMs with circular dependency (output = input)
            for idx, row in filtered.iterrows():
                if circular_map.get(row['id'], False):
                    mask[idx] = True
        
        if 'No Issues' in filter_issues:
            # BOMs without any issues
            for idx, row in filtered.iterrows():
                has_conflict = row['status'] == 'ACTIVE' and conflicts_map.get(row['id'], 0) > 0
                has_duplicate = duplicates_map.get(row['id'], False)
                has_circular = circular_map.get(row['id'], False)
                if not has_conflict and not has_duplicate and not has_circular:
                    mask[idx] = True
        
        filtered = filtered[mask]
    
    return filtered


@st.fragment
def render_smart_filter_bar():
    """
    Render Smart Filter Bar with multiselects and active filter chips
    Uses fragment for efficient re-rendering without full page reload
    """
    st.markdown("### 🔍 Smart Filters")
    
    # Get filter options
    options = get_filter_options()
    
    # Row 1: BOM Code, BOM Name, Product (main search filters - searchable multiselect)
    col1, col2, col3 = st.columns(3)
    
    with col1:
        selected_bom_codes = st.multiselect(
            "🔖 BOM Code",
            options=options['bom_codes'],
            default=state.get_filter_bom_codes(),
            key='ms_filter_bom_codes',
            placeholder="Search BOM codes..."
        )
        if selected_bom_codes != state.get_filter_bom_codes():
            state.set_filter_bom_codes(selected_bom_codes)
    
    with col2:
        selected_bom_names = st.multiselect(
            "📝 BOM Name",
            options=options['bom_names'],
            default=state.get_filter_bom_names(),
            key='ms_filter_bom_names',
            placeholder="Search BOM names..."
        )
        if selected_bom_names != state.get_filter_bom_names():
            state.set_filter_bom_names(selected_bom_names)
    
    with col3:
        selected_products = st.multiselect(
            "📦 Product",
            options=options['products'],
            default=state.get_filter_products(),
            key='ms_filter_products',
            placeholder="Search products..."
        )
        if selected_products != state.get_filter_products():
            state.set_filter_products(selected_products)
    
    # Row 2: Type, Status, Issues (categorization)
    col4, col5, col6 = st.columns(3)
    
    with col4:
        selected_types = st.multiselect(
            "🏭 BOM Type",
            options=['KITTING', 'CUTTING', 'REPACKING'],
            default=state.get_filter_types(),
            key='ms_filter_types',
            placeholder="All Types"
        )
        if selected_types != state.get_filter_types():
            state.set_filter_types(selected_types)
    
    with col5:
        selected_statuses = st.multiselect(
            "📊 Status",
            options=['DRAFT', 'ACTIVE', 'INACTIVE'],
            default=state.get_filter_statuses(),
            key='ms_filter_statuses',
            placeholder="All Statuses"
        )
        if selected_statuses != state.get_filter_statuses():
            state.set_filter_statuses(selected_statuses)
    
    with col6:
        selected_issues = st.multiselect(
            "⚠️ Issues",
            options=['Conflicts', 'Duplicates', 'Circular', 'No Issues'],
            default=state.get_filter_issues(),
            key='ms_filter_issues',
            placeholder="All (No Filter)",
            help="Conflicts: Multiple active BOMs | Duplicates: Duplicate materials | Circular: Output=Input | No Issues: Clean BOMs"
        )
        if selected_issues != state.get_filter_issues():
            state.set_filter_issues(selected_issues)
    
    # Row 3: Creator, Brand, Date Range, Reset
    col7, col8, col9, col10 = st.columns([1.2, 1.2, 1.4, 0.4])
    
    with col7:
        selected_creators = st.multiselect(
            "👤 Creator",
            options=options['creators'],
            default=state.get_filter_creators(),
            key='ms_filter_creators',
            placeholder="All Creators"
        )
        if selected_creators != state.get_filter_creators():
            state.set_filter_creators(selected_creators)
    
    with col8:
        selected_brands = st.multiselect(
            "🏷️ Brand",
            options=options['brands'],
            default=state.get_filter_brands(),
            key='ms_filter_brands',
            placeholder="All Brands"
        )
        if selected_brands != state.get_filter_brands():
            state.set_filter_brands(selected_brands)
    
    with col9:
        st.markdown("**📅 Date Range**")
        date_col1, date_col2 = st.columns(2)
        
        current_from, current_to = state.get_filter_date_range()
        
        with date_col1:
            use_date_from = st.checkbox("From", value=current_from is not None, key="use_date_from")
            if use_date_from:
                date_from = st.date_input(
                    "From",
                    value=current_from or date.today() - timedelta(days=30),
                    key='filter_date_from',
                    format="DD/MM/YYYY",
                    label_visibility="collapsed"
                )
            else:
                date_from = None
        
        with date_col2:
            use_date_to = st.checkbox("To", value=current_to is not None, key="use_date_to")
            if use_date_to:
                date_to = st.date_input(
                    "To",
                    value=current_to or date.today(),
                    key='filter_date_to',
                    format="DD/MM/YYYY",
                    label_visibility="collapsed"
                )
            else:
                date_to = None
        
        if date_from != current_from or date_to != current_to:
            state.set_filter_date_range(date_from, date_to)
    
    with col10:
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("🔄", use_container_width=True, help="Reset all filters to default"):
            state.reset_filters()
            st.rerun(scope="fragment")
    
    # Active filter chips
    render_active_filter_chips()
    
    st.markdown("---")
    
    # Apply filters and render table
    all_boms = st.session_state.get('all_boms', pd.DataFrame())
    filtered_boms = apply_smart_filters(all_boms)
    
    # Store filtered result
    st.session_state['filtered_boms'] = filtered_boms
    
    # Show result count
    total_count = len(all_boms)
    filtered_count = len(filtered_boms)
    
    if state.has_active_filters():
        st.caption(f"📋 Showing **{filtered_count}** of {total_count} BOMs")
    else:
        st.caption(f"📋 Showing all **{total_count}** BOMs")
    
    # Render the BOM table within the fragment
    render_bom_table_content(filtered_boms)


def render_active_filter_chips():
    """Render clickable chips for active filters"""
    chips = state.get_active_filter_chips()
    
    if not chips:
        return
    
    st.markdown("**Active Filters:**")
    
    # Create columns for chips (max 8 per row)
    num_chips = len(chips)
    if num_chips > 0:
        cols = st.columns(min(num_chips + 1, 9))  # +1 for Clear All button
        
        for idx, chip in enumerate(chips[:8]):  # Max 8 chips shown
            with cols[idx]:
                if st.button(
                    f"✕ {chip['label']}", 
                    key=f"chip_{chip['category']}_{chip['value']}",
                    use_container_width=True
                ):
                    state.remove_filter_chip(chip['category'], chip['value'])
                    st.rerun(scope="fragment")
        
        # Clear All button
        with cols[min(num_chips, 8)]:
            if st.button("🗑️ Clear All", key="clear_all_chips", use_container_width=True):
                state.reset_filters()
                st.rerun(scope="fragment")


def render_bom_table_content(boms: pd.DataFrame):
    """
    Render BOM table content with actions, duplicate warnings, conflict badges, and circular dependency
    
    Args:
        boms: Filtered DataFrame of BOMs to display
    """
    st.markdown("### 📋 BOM List")
    
    if boms.empty:
        st.info("ℹ️ No BOMs match the current filters. Try adjusting your filters or create a new BOM.")
        return
    
    # Check for duplicates in all BOMs (cached for performance)
    bom_ids = boms['id'].tolist()
    duplicates_map = get_boms_with_duplicate_check(bom_ids)
    
    # Phase 2: Check for active BOM conflicts
    conflicts_map = get_boms_with_active_conflict_check(bom_ids)
    
    # Phase 3: Check for circular dependencies (output = input)
    circular_map = get_boms_with_circular_dependency_check(bom_ids)
    
    # Count BOMs with duplicates for summary
    boms_with_duplicates = sum(1 for v in duplicates_map.values() if v)
    
    # Count BOMs with conflicts (other active BOMs for same product)
    boms_with_conflicts = sum(1 for v in conflicts_map.values() if v > 0)
    
    # Count BOMs with circular dependencies
    boms_with_circular = sum(1 for v in circular_map.values() if v)
    
    # Show summary warnings (only if not already filtering by issues)
    filter_issues = state.get_filter_issues()
    if boms_with_duplicates > 0 and 'Duplicates' not in filter_issues:
        st.warning(f"⚠️ **Note:** {boms_with_duplicates} BOM(s) have duplicate materials. See 'Issues' column.")
    
    if boms_with_circular > 0 and 'Circular' not in filter_issues:
        st.error(f"🔄 **Critical:** {boms_with_circular} BOM(s) have circular dependency (output = input). See 'Issues' column.")
    
    # Format display data
    display_df = boms.copy()
    
    # Add duplicate warning flag
    display_df['has_duplicate'] = display_df['id'].apply(lambda x: duplicates_map.get(x, False))
    
    # Add conflict count
    display_df['conflict_count'] = display_df['id'].apply(lambda x: conflicts_map.get(x, 0))
    
    # Add circular dependency flag
    display_df['has_circular'] = display_df['id'].apply(lambda x: circular_map.get(x, False))
    
    # Combined Issues column (Phase 3 enhancement)
    def format_issues_display(row):
        issues = []
        
        # Check circular dependency (highest priority - critical issue)
        if row['has_circular']:
            issues.append("🔄 Circular")
        
        # Check conflict (only for ACTIVE BOMs)
        if row['status'] == 'ACTIVE' and row['conflict_count'] > 0:
            total_active = row['conflict_count'] + 1  # Include current BOM
            issues.append(f"🔴 {total_active} Active")
        
        # Check duplicate
        if row['has_duplicate']:
            issues.append("⚠️ Dup")
        
        return " | ".join(issues) if issues else "✅"
    
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
        "issues_display": st.column_config.TextColumn("Issues", width="small"),
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
        st.caption("Manufacturing Module v2.6 - BOM Management | Smart Filter Bar with Multiselect")
    
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