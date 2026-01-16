# utils/bom_variance/tab_dashboard.py
"""
BOM Variance - Tab 1: Dashboard Overview - VERSION 2.0

Contains all UI components and logic for the Dashboard Overview tab:
- Filters section (collapsible)
- Summary metrics (4 compact cards)
- Variance donut chart
- Breakdown by type (BOM Type + Material Type)
- Top variances table
- Mixed usage summary

Restructured from monolithic page for better maintainability.
"""

import streamlit as st
import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List, Optional

from .config import (
    MATERIAL_TYPES, BOM_TYPES, VARIANCE_DIRECTIONS,
    get_config, reset_filters,
    format_product_display, format_bom_display, format_variance_display,
    format_bom_display_full, create_bom_options_from_df,
    extract_code_from_option, extract_bom_code_from_option
)

logger = logging.getLogger(__name__)


# ==================== Data Loading & Filtering ====================

def load_variance_data(analyzer) -> pd.DataFrame:
    """
    Load full variance data from DB (cached in session state)
    Only reloads when config changes or cache is cleared
    """
    if st.session_state['variance_full_data'] is None:
        try:
            df = analyzer.get_variance_data(include_no_data=False)
            st.session_state['variance_full_data'] = df
            logger.info(f"Loaded {len(df)} variance records from DB")
        except Exception as e:
            logger.error(f"Error loading variance data: {e}")
            st.session_state['variance_full_data'] = pd.DataFrame()
    
    return st.session_state['variance_full_data']


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all filters to the dataframe locally (no DB query)
    """
    if df.empty:
        return df
    
    filtered = df.copy()
    config = get_config()
    threshold = config.variance_threshold
    
    # Filter by Material Type
    material_types = st.session_state['filter_material_types']
    if material_types:
        filtered = filtered[filtered['material_type'].isin(material_types)]
    
    # Filter by BOM Type
    bom_types = st.session_state['filter_bom_types']
    if bom_types:
        filtered = filtered[filtered['bom_type'].isin(bom_types)]
    
    # Filter by Variance Direction
    direction = st.session_state['filter_variance_direction']
    if direction == 'Under-used':
        filtered = filtered[filtered['variance_pct'] < -threshold]
    elif direction == 'On-target':
        filtered = filtered[filtered['variance_pct'].abs() <= threshold]
    elif direction == 'Over-used':
        filtered = filtered[filtered['variance_pct'] > threshold]
    elif direction == 'High Variance':
        filtered = filtered[filtered['variance_pct'].abs() > threshold]
    
    # Filter by Output Product
    selected_products = st.session_state['filter_products']
    if selected_products:
        product_codes = [extract_code_from_option(p) for p in selected_products]
        filtered = filtered[filtered['output_product_code'].isin(product_codes)]
    
    # Filter by BOM
    selected_boms = st.session_state['filter_boms']
    if selected_boms:
        bom_codes = [extract_bom_code_from_option(b) for b in selected_boms]
        filtered = filtered[filtered['bom_code'].isin(bom_codes)]
    
    # Filter by Material
    selected_materials = st.session_state['filter_materials']
    if selected_materials:
        material_codes = [extract_code_from_option(m) for m in selected_materials]
        filtered = filtered[filtered['material_code'].isin(material_codes)]
    
    # Quick filter: High Variance Only
    if st.session_state['filter_high_variance_only']:
        filtered = filtered[filtered['has_high_variance'] == True]
    
    # Quick filter: Zero Actual Only
    if st.session_state['filter_zero_actual_only']:
        filtered = filtered[filtered['actual_avg_per_unit'] == 0]
    
    return filtered


# ==================== Filter Options Extraction ====================

def get_filter_options(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Extract unique values for filter dropdowns from variance data"""
    if df.empty:
        return {
            'products': pd.DataFrame(),
            'boms': pd.DataFrame(),
            'materials': pd.DataFrame()
        }
    
    # Unique products (output products)
    product_cols = ['output_product_code', 'output_product_name']
    for col in ['output_product_legacy_code', 'output_product_package_size', 'output_product_brand']:
        if col in df.columns:
            product_cols.append(col)
    
    products = df[product_cols].drop_duplicates().sort_values('output_product_code')
    
    # Unique BOMs with stats for better display
    bom_cols = ['bom_header_id', 'bom_code', 'bom_name', 'bom_type', 'output_product_code']
    bom_cols = [c for c in bom_cols if c in df.columns]
    
    # Aggregate BOM stats
    bom_stats = df.groupby('bom_header_id').agg({
        'material_id': 'count',
        'has_high_variance': 'sum',
        'mo_count': 'first' if 'mo_count' in df.columns else lambda x: 0
    }).reset_index()
    bom_stats.columns = ['bom_header_id', 'material_count', 'high_variance_count', 'mo_count']
    
    boms_base = df[bom_cols].drop_duplicates()
    boms = boms_base.merge(bom_stats, on='bom_header_id', how='left')
    boms = boms.sort_values('high_variance_count', ascending=False)
    
    # Unique materials
    material_cols = ['material_id', 'material_code', 'material_name', 'material_type']
    for col in ['material_legacy_code', 'material_package_size', 'material_brand']:
        if col in df.columns:
            material_cols.append(col)
    
    materials = df[material_cols].drop_duplicates().sort_values('material_code')
    
    return {
        'products': products,
        'boms': boms,
        'materials': materials
    }


def get_cascaded_bom_options(df: pd.DataFrame, selected_products: List[str]) -> pd.DataFrame:
    """Get BOM options filtered by selected products (cascading filter) with stats"""
    if df.empty:
        return pd.DataFrame()
    
    # Filter by selected products if any
    if selected_products:
        filtered_df = df[df['output_product_code'].isin(selected_products)]
    else:
        filtered_df = df
    
    if filtered_df.empty:
        return pd.DataFrame()
    
    # Get basic columns
    bom_cols = ['bom_header_id', 'bom_code', 'bom_name', 'bom_type', 'output_product_code']
    bom_cols = [c for c in bom_cols if c in filtered_df.columns]
    
    # Aggregate BOM stats
    bom_stats = filtered_df.groupby('bom_header_id').agg({
        'material_id': 'count',
        'has_high_variance': 'sum',
        'mo_count': 'first' if 'mo_count' in filtered_df.columns else lambda x: 0
    }).reset_index()
    bom_stats.columns = ['bom_header_id', 'material_count', 'high_variance_count', 'mo_count']
    
    boms_base = filtered_df[bom_cols].drop_duplicates()
    boms = boms_base.merge(bom_stats, on='bom_header_id', how='left')
    
    return boms.sort_values('high_variance_count', ascending=False)


def create_product_options(products_df: pd.DataFrame) -> List[str]:
    """Create formatted product options for multiselect"""
    if products_df.empty:
        return []
    
    options = []
    for _, row in products_df.iterrows():
        display = format_product_display(
            code=row.get('output_product_code', ''),
            name=row.get('output_product_name', ''),
            package_size=row.get('output_product_package_size'),
            brand=row.get('output_product_brand'),
            legacy_code=row.get('output_product_legacy_code')
        )
        options.append(display)
    
    return options


def create_bom_options(boms_df: pd.DataFrame) -> tuple:
    """
    Create formatted BOM options for multiselect
    
    Returns:
        Tuple of (list of display options, dict mapping display -> bom_code)
    """
    if boms_df.empty:
        return [], {}
    
    # Use unified format function
    options, id_map = create_bom_options_from_df(boms_df, include_stats=True)
    
    # Create bom_code map (for filtering, we need bom_code not bom_id)
    code_map = {}
    for _, row in boms_df.iterrows():
        bom_id = row['bom_header_id']
        bom_code = row.get('bom_code', str(bom_id))
        # Find the display option that maps to this bom_id
        for display, mapped_id in id_map.items():
            if mapped_id == bom_id:
                code_map[display] = bom_code
                break
    
    return options, code_map


def create_material_options(materials_df: pd.DataFrame) -> List[str]:
    """Create formatted material options for multiselect"""
    if materials_df.empty:
        return []
    
    options = []
    for _, row in materials_df.iterrows():
        display = format_product_display(
            code=row.get('material_code', ''),
            name=row.get('material_name', ''),
            package_size=row.get('material_package_size'),
            brand=row.get('material_brand'),
            legacy_code=row.get('material_legacy_code')
        )
        options.append(display)
    
    return options


def get_filter_counts(df: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """Get counts for filter options from full data"""
    if df.empty:
        return {
            'material_types': {t: 0 for t in MATERIAL_TYPES},
            'bom_types': {t: 0 for t in BOM_TYPES},
            'variance_directions': {d: 0 for d in VARIANCE_DIRECTIONS}
        }
    
    config = get_config()
    threshold = config.variance_threshold
    
    # Material type counts
    material_counts = df.groupby('material_type').size().to_dict()
    material_counts = {t: material_counts.get(t, 0) for t in MATERIAL_TYPES}
    
    # BOM type counts
    bom_counts = df.groupby('bom_type').size().to_dict()
    bom_counts = {t: bom_counts.get(t, 0) for t in BOM_TYPES}
    
    # Variance direction counts
    direction_counts = {
        'All': len(df),
        'Under-used': len(df[df['variance_pct'] < -threshold]),
        'On-target': len(df[df['variance_pct'].abs() <= threshold]),
        'Over-used': len(df[df['variance_pct'] > threshold]),
        'High Variance': len(df[df['variance_pct'].abs() > threshold])
    }
    
    # Entity counts
    entity_counts = {
        'products': df['output_product_code'].nunique(),
        'boms': df['bom_code'].nunique(),
        'materials': df['material_code'].nunique()
    }
    
    return {
        'material_types': material_counts,
        'bom_types': bom_counts,
        'variance_directions': direction_counts,
        'entities': entity_counts
    }


# ==================== Metrics Calculation ====================

def calculate_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate dashboard metrics from filtered data"""
    if df.empty:
        return {
            'total_boms_analyzed': 0,
            'total_materials_analyzed': 0,
            'boms_with_variance': 0,
            'materials_with_variance': 0,
            'materials_with_mixed': 0,
            'avg_variance_pct': 0,
            'max_variance_pct': 0
        }
    
    high_variance = df[df['has_high_variance'] == True]
    
    # Check if new columns exist
    has_mixed_col = 'has_mixed_usage' in df.columns
    materials_with_mixed = len(df[df['has_mixed_usage'] == True]) if has_mixed_col else 0
    
    return {
        'total_boms_analyzed': df['bom_header_id'].nunique(),
        'total_materials_analyzed': len(df),
        'boms_with_variance': high_variance['bom_header_id'].nunique(),
        'materials_with_variance': len(high_variance),
        'materials_with_mixed': materials_with_mixed,
        'avg_variance_pct': float(df['variance_pct'].abs().mean()) if not df['variance_pct'].isna().all() else 0,
        'max_variance_pct': float(df['variance_pct'].abs().max()) if not df['variance_pct'].isna().all() else 0
    }


def calculate_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate variance distribution from filtered data"""
    if df.empty:
        return {
            'bins': [],
            'counts': [],
            'categories': {'under_used': 0, 'on_target': 0, 'over_used': 0, 'high_variance': 0},
            'stats': {}
        }
    
    config = get_config()
    threshold = config.variance_threshold
    
    variance_pct = df['variance_pct'].dropna()
    
    if variance_pct.empty:
        return {
            'bins': [],
            'counts': [],
            'categories': {'under_used': 0, 'on_target': 0, 'over_used': 0, 'high_variance': 0},
            'stats': {}
        }
    
    # Create histogram bins
    bins = [-50, -20, -10, -5, 0, 5, 10, 20, 50]
    counts, _ = np.histogram(variance_pct.clip(-50, 50), bins=bins)
    
    categories = {
        'under_used': int((variance_pct < -threshold).sum()),
        'on_target': int((variance_pct.abs() <= threshold).sum()),
        'over_used': int((variance_pct > threshold).sum()),
        'high_variance': int((variance_pct.abs() > threshold * 2).sum())
    }
    
    stats = {
        'mean': float(variance_pct.mean()),
        'median': float(variance_pct.median()),
        'std': float(variance_pct.std()) if len(variance_pct) > 1 else 0,
        'min': float(variance_pct.min()),
        'max': float(variance_pct.max())
    }
    
    return {
        'bins': bins,
        'counts': counts.tolist(),
        'bin_labels': [f"{bins[i]} to {bins[i+1]}%" for i in range(len(bins)-1)],
        'categories': categories,
        'stats': stats
    }


# ==================== UI Components ====================

@st.fragment
def render_filters_section(full_data: pd.DataFrame):
    """Render filter controls - uses @st.fragment to avoid full page rerun"""
    counts = get_filter_counts(full_data)
    filter_options = get_filter_options(full_data)
    config = get_config()
    threshold = config.variance_threshold
    
    # Count active filters
    active_filters = sum([
        len(st.session_state['filter_material_types']) > 0,
        len(st.session_state['filter_bom_types']) > 0,
        st.session_state['filter_variance_direction'] != 'All',
        len(st.session_state['filter_products']) > 0,
        len(st.session_state['filter_boms']) > 0,
        len(st.session_state['filter_materials']) > 0,
        st.session_state['filter_high_variance_only'],
        st.session_state['filter_zero_actual_only']
    ])
    
    filter_label = f"🔍 Filters ({active_filters} active)" if active_filters > 0 else "🔍 Filters"
    
    with st.expander(filter_label, expanded=st.session_state['filters_expanded']):
        # Row 1: Category Filters
        st.markdown("##### Category Filters")
        col1, col2, col3 = st.columns([1, 1, 1.5])
        
        with col1:
            # Material Type multiselect with counts
            material_options = [
                f"{t} ({counts['material_types'].get(t, 0)})" 
                for t in MATERIAL_TYPES
            ]
            
            current_material_types = st.session_state['filter_material_types']
            current_material_values = [
                f"{t} ({counts['material_types'].get(t, 0)})" 
                for t in current_material_types
                if t in MATERIAL_TYPES
            ]
            
            selected_materials = st.multiselect(
                "Material Type",
                options=material_options,
                default=current_material_values,
                key="ms_material_type",
                placeholder="All material types",
                help="Filter by material type"
            )
            
            st.session_state['filter_material_types'] = [
                opt.split(' (')[0] for opt in selected_materials
            ]
        
        with col2:
            # BOM Type multiselect with counts
            bom_type_options = [
                f"{t} ({counts['bom_types'].get(t, 0)})" 
                for t in BOM_TYPES
            ]
            
            current_bom_types = st.session_state['filter_bom_types']
            current_bom_type_values = [
                f"{t} ({counts['bom_types'].get(t, 0)})" 
                for t in current_bom_types
                if t in BOM_TYPES
            ]
            
            selected_bom_types = st.multiselect(
                "BOM Type",
                options=bom_type_options,
                default=current_bom_type_values,
                key="ms_bom_type",
                placeholder="All BOM types",
                help="Filter by BOM type"
            )
            
            st.session_state['filter_bom_types'] = [
                opt.split(' (')[0] for opt in selected_bom_types
            ]
        
        with col3:
            # Variance Direction radio with counts
            direction_options = [
                f"{d} ({counts['variance_directions'].get(d, 0)})"
                for d in VARIANCE_DIRECTIONS
            ]
            
            current_direction = st.session_state['filter_variance_direction']
            current_idx = VARIANCE_DIRECTIONS.index(current_direction) if current_direction in VARIANCE_DIRECTIONS else 0
            
            selected_direction = st.radio(
                "Variance Direction",
                options=direction_options,
                index=current_idx,
                key="radio_variance_direction",
                horizontal=True,
                help=f"Based on threshold: ±{threshold}%"
            )
            
            st.session_state['filter_variance_direction'] = selected_direction.split(' (')[0]
        
        st.markdown("---")
        
        # Row 2: Entity Filters
        st.markdown(f"##### Entity Filters ({counts['entities']['products']} products, {counts['entities']['boms']} BOMs, {counts['entities']['materials']} materials)")
        col4, col5 = st.columns(2)
        
        with col4:
            product_options = create_product_options(filter_options['products'])
            
            selected_products = st.multiselect(
                "Output Product",
                options=product_options,
                default=st.session_state['filter_products'],
                key="ms_products",
                placeholder="Search products by code, name, brand...",
                help="Filter by output product (cascades to BOM filter)"
            )
            st.session_state['filter_products'] = selected_products
        
        with col5:
            selected_product_codes = [extract_code_from_option(p) for p in selected_products]
            cascaded_boms = get_cascaded_bom_options(full_data, selected_product_codes)
            bom_options, bom_code_map = create_bom_options(cascaded_boms)
            
            current_bom_selections = st.session_state['filter_boms']
            valid_bom_selections = [b for b in current_bom_selections if b in bom_options]
            
            selected_boms = st.multiselect(
                "BOM",
                options=bom_options,
                default=valid_bom_selections,
                key="ms_boms",
                placeholder="Search BOMs by code, name...",
                help="Filter by specific BOM" + (" (filtered by selected products)" if selected_products else "")
            )
            st.session_state['filter_boms'] = selected_boms
        
        # Row 3: Material Filter
        col6, col7 = st.columns([2, 1])
        
        with col6:
            material_options = create_material_options(filter_options['materials'])
            
            selected_mat = st.multiselect(
                "Material",
                options=material_options,
                default=st.session_state['filter_materials'],
                key="ms_materials",
                placeholder="Search materials by code, name, brand...",
                help="Filter by specific material"
            )
            st.session_state['filter_materials'] = selected_mat
        
        with col7:
            st.markdown("<br>", unsafe_allow_html=True)
            qf_col1, qf_col2 = st.columns(2)
            
            with qf_col1:
                high_var = st.toggle(
                    "🔴 High Variance",
                    value=st.session_state['filter_high_variance_only'],
                    key="toggle_high_var",
                    help="Show only high variance items"
                )
                st.session_state['filter_high_variance_only'] = high_var
            
            with qf_col2:
                zero_actual = st.toggle(
                    "⚠️ Zero Actual",
                    value=st.session_state['filter_zero_actual_only'],
                    key="toggle_zero_actual",
                    help="Show only items with zero actual consumption"
                )
                st.session_state['filter_zero_actual_only'] = zero_actual
        
        # Action Buttons Row
        st.markdown("---")
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
        
        with btn_col1:
            if st.button("🔄 Reset All", use_container_width=True, help="Reset all filters to default"):
                reset_filters()
                st.rerun()
        
        with btn_col2:
            if st.button(
                "✅ Apply Filters", 
                use_container_width=True, 
                type="primary",
                help="Apply selected filters to refresh the data view"
            ):
                st.rerun()


def render_summary_metrics_compact(metrics: Dict[str, Any]):
    """Render compact summary metrics - 4 essential cards"""
    col1, col2, col3, col4 = st.columns(4)
    
    total_boms = metrics.get('total_boms_analyzed', 0)
    total_materials = metrics.get('total_materials_analyzed', 0)
    materials_with_variance = metrics.get('materials_with_variance', 0)
    avg_variance = metrics.get('avg_variance_pct', 0)
    max_variance = metrics.get('max_variance_pct', 0)
    
    issue_pct = (materials_with_variance / total_materials * 100) if total_materials > 0 else 0
    
    with col1:
        st.metric(
            "📦 BOMs",
            total_boms,
            help="Number of BOMs analyzed in selected period"
        )
    
    with col2:
        st.metric(
            "🧪 Materials",
            total_materials,
            help="Total material-BOM combinations analyzed"
        )
    
    with col3:
        st.metric(
            "⚠️ Issues",
            materials_with_variance,
            delta=f"{issue_pct:.0f}% of total",
            delta_color="inverse",
            help="Materials with variance above threshold - need review"
        )
    
    with col4:
        st.metric(
            "📈 Avg Variance",
            f"{avg_variance:.1f}%",
            delta=f"Max: {max_variance:.0f}%",
            delta_color="off",
            help="Average absolute variance | Maximum variance"
        )


def render_variance_donut_chart(distribution: Dict[str, Any]):
    """Render variance overview with donut chart"""
    st.subheader("📊 Variance Overview")
    
    categories = distribution.get('categories', {})
    
    if not categories or all(v == 0 for v in categories.values()):
        st.info("ℹ️ No variance data available.")
        return
    
    on_target = categories.get('on_target', 0)
    under_used = categories.get('under_used', 0)
    over_used = categories.get('over_used', 0)
    high_variance = categories.get('high_variance', 0)
    
    total = on_target + under_used + over_used
    on_target_pct = (on_target / total * 100) if total > 0 else 0
    
    try:
        import plotly.graph_objects as go
        
        labels = ['On Target', 'Under-used', 'Over-used']
        values = [on_target, under_used, over_used]
        colors = ['#2ecc71', '#3498db', '#e67e22']
        
        fig = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            hole=0.6,
            marker_colors=colors,
            textinfo='value',
            textfont_size=14,
            hovertemplate="<b>%{label}</b><br>%{value} materials<br>%{percent}<extra></extra>"
        )])
        
        fig.add_annotation(
            text=f"<b>{on_target_pct:.0f}%</b><br>On Track",
            x=0.5, y=0.5,
            font_size=16,
            showarrow=False
        )
        
        fig.update_layout(
            showlegend=False,
            height=250,
            margin=dict(l=20, r=20, t=10, b=10)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except ImportError:
        st.markdown(f"""
        <div style="text-align: center; padding: 20px;">
            <h1 style="font-size: 48px; margin: 0;">{on_target_pct:.0f}%</h1>
            <p style="color: #666;">On Track</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Legend with colored indicators
    leg_col1, leg_col2 = st.columns(2)
    
    with leg_col1:
        st.markdown(f"🟢 **On Target:** {on_target}")
        st.markdown(f"🔵 **Under-used:** {under_used}")
    
    with leg_col2:
        st.markdown(f"🟠 **Over-used:** {over_used}")
        st.markdown(f"🔴 **High Variance:** {high_variance}")
    
    # Statistics expander
    stats = distribution.get('stats', {})
    if stats:
        with st.expander("📊 Statistics", expanded=False):
            stat_col1, stat_col2 = st.columns(2)
            with stat_col1:
                st.caption(f"Mean: {stats.get('mean', 0):.2f}%")
                st.caption(f"Median: {stats.get('median', 0):.2f}%")
            with stat_col2:
                st.caption(f"Std Dev: {stats.get('std', 0):.2f}%")
                st.caption(f"Range: {stats.get('min', 0):.1f}% to {stats.get('max', 0):.1f}%")


def render_by_type_combined(filtered_data: pd.DataFrame):
    """Render BOM Type and Material Type summaries combined"""
    st.subheader("📋 Breakdown by Type")
    
    if filtered_data.empty:
        st.info("ℹ️ No data available.")
        return
    
    # ==================== BOM Type Section ====================
    st.markdown("**By BOM Type**")
    
    bom_summary = filtered_data.groupby('bom_type').agg({
        'bom_header_id': 'nunique',
        'material_id': 'count',
        'variance_pct': 'mean',
        'has_high_variance': 'sum'
    }).reset_index()
    
    bom_summary.columns = ['Type', 'BOMs', 'Materials', 'Avg Var', 'Issues']
    
    for _, row in bom_summary.iterrows():
        bom_type = row['Type']
        boms = int(row['BOMs'])
        materials = int(row['Materials'])
        avg_var = row['Avg Var'] if pd.notna(row['Avg Var']) else 0
        issues = int(row['Issues'])
        
        issue_pct = (issues / materials * 100) if materials > 0 else 0
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.markdown(f"**{bom_type}** ({boms} BOMs)")
        with col2:
            if pd.notna(row['Avg Var']):
                var_color = "🟢" if abs(avg_var) <= 5 else ("🟠" if abs(avg_var) <= 10 else "🔴")
                st.markdown(f"{var_color} {avg_var:+.1f}%")
            else:
                st.markdown("⚪ N/A")
        with col3:
            st.markdown(f"⚠️ {issues}")
        
        st.progress(min(issue_pct / 100, 1.0), text=None)
    
    st.markdown("---")
    
    # ==================== Material Type Section ====================
    st.markdown("**By Material Type**")
    
    mat_summary = filtered_data.groupby('material_type').agg({
        'material_id': 'count',
        'variance_pct': 'mean',
        'has_high_variance': 'sum'
    }).reset_index()
    
    mat_summary.columns = ['Type', 'Count', 'Avg Var', 'Issues']
    
    for _, row in mat_summary.iterrows():
        mat_type = row['Type']
        count = int(row['Count'])
        avg_var = row['Avg Var'] if pd.notna(row['Avg Var']) else 0
        issues = int(row['Issues'])
        
        issue_pct = (issues / count * 100) if count > 0 else 0
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            emoji = "🧪" if mat_type == "RAW_MATERIAL" else ("📦" if mat_type == "PACKAGING" else "🔧")
            st.markdown(f"{emoji} **{mat_type}** ({count})")
        with col2:
            if pd.notna(row['Avg Var']):
                var_color = "🟢" if abs(avg_var) <= 5 else ("🟠" if abs(avg_var) <= 10 else "🔴")
                st.markdown(f"{var_color} {avg_var:+.1f}%")
            else:
                st.markdown("⚪ N/A")
        with col3:
            st.markdown(f"⚠️ {issues}")
        
        st.progress(min(issue_pct / 100, 1.0), text=None)


def render_top_variances_table(filtered_data: pd.DataFrame, limit: int = 10):
    """Render top variances table"""
    st.subheader(f"🔝 Top {limit} Variances")
    
    if filtered_data.empty:
        st.info("ℹ️ No variance data available for the selected filters.")
        return
    
    data_with_variance = filtered_data[filtered_data['variance_pct'].notna()].copy()
    
    if data_with_variance.empty:
        st.info("ℹ️ No variance data from pure MOs. All MOs may have mixed material usage.")
        return
    
    data_with_variance['abs_variance'] = data_with_variance['variance_pct'].abs()
    top_data = data_with_variance.sort_values('abs_variance', ascending=False).head(limit)
    
    has_new_columns = 'mo_count_pure' in top_data.columns
    
    if has_new_columns:
        display_df = top_data[[
            'bom_code', 'bom_type', 'material_code', 'material_name', 'material_type',
            'is_alternative', 'theoretical_qty_with_scrap', 'actual_avg_per_unit', 
            'variance_pct', 'mo_count_pure', 'mo_count_mixed', 'cv_percent'
        ]].copy()
        
        display_df['mo_display'] = display_df.apply(
            lambda row: f"{int(row['mo_count_pure'])}p" + (f"+{int(row['mo_count_mixed'])}m" if row['mo_count_mixed'] > 0 else ""),
            axis=1
        )
        
        display_df['mat_source'] = display_df['is_alternative'].apply(
            lambda x: '🔄 Alt' if x == 1 else '📦 Pri'
        )
    else:
        display_df = top_data[[
            'bom_code', 'bom_type', 'material_code', 'material_name', 'material_type',
            'theoretical_qty_with_scrap', 'actual_avg_per_unit', 
            'variance_pct', 'mo_count', 'cv_percent'
        ]].copy()
        display_df['mo_display'] = display_df['mo_count'].astype(int).astype(str)
        display_df['mat_source'] = ''
    
    display_df['theoretical_qty_with_scrap'] = display_df['theoretical_qty_with_scrap'].apply(lambda x: f"{x:.4f}")
    display_df['actual_avg_per_unit'] = display_df['actual_avg_per_unit'].apply(lambda x: f"{x:.4f}")
    display_df['variance_display'] = display_df['variance_pct'].apply(format_variance_display)
    display_df['cv_display'] = display_df['cv_percent'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    
    if has_new_columns:
        columns_to_show = [
            'bom_code', 'bom_type', 'material_code', 'material_name', 'mat_source',
            'theoretical_qty_with_scrap', 'actual_avg_per_unit',
            'variance_display', 'mo_display', 'cv_display'
        ]
        column_names = {
            'bom_code': 'BOM',
            'bom_type': 'Type',
            'material_code': 'Material',
            'material_name': 'Name',
            'mat_source': 'Source',
            'theoretical_qty_with_scrap': 'Theory',
            'actual_avg_per_unit': 'Actual',
            'variance_display': 'Variance',
            'mo_display': 'MOs',
            'cv_display': 'CV%'
        }
    else:
        columns_to_show = [
            'bom_code', 'bom_type', 'material_code', 'material_name', 'material_type',
            'theoretical_qty_with_scrap', 'actual_avg_per_unit',
            'variance_display', 'mo_display', 'cv_display'
        ]
        column_names = {
            'bom_code': 'BOM',
            'bom_type': 'Type',
            'material_code': 'Material',
            'material_name': 'Name',
            'material_type': 'Mat.Type',
            'theoretical_qty_with_scrap': 'Theory',
            'actual_avg_per_unit': 'Actual',
            'variance_display': 'Variance',
            'mo_display': 'MOs',
            'cv_display': 'CV%'
        }
    
    st.dataframe(
        display_df[columns_to_show].rename(columns=column_names),
        use_container_width=True,
        hide_index=True
    )
    
    if has_new_columns:
        st.caption("""
        📝 **Legend:** 
        - **Source:** 📦 Pri = Primary material | 🔄 Alt = Alternative material
        - **Theory:** Theoretical qty per output (with scrap)
        - **Actual:** Average consumption per output (from pure MOs only)
        - **MOs:** Xp+Ym = X pure MOs + Y mixed MOs (variance calculated from pure MOs only)
        - **CV%:** Coefficient of Variation (high = inconsistent)
        """)
    else:
        st.caption("""
        📝 **Legend:** Theory = Theoretical qty per output (with scrap) | 
        Actual = Average actual consumption per output | 
        CV% = Coefficient of Variation (high = inconsistent)
        """)


def render_mixed_usage_summary(filtered_data: pd.DataFrame):
    """Render summary of materials with mixed usage"""
    if 'mo_count_mixed' not in filtered_data.columns:
        return
    
    mixed_data = filtered_data[filtered_data['mo_count_mixed'] > 0].copy()
    
    if mixed_data.empty:
        return
    
    with st.expander(f"🔀 Mixed Usage Summary ({len(mixed_data)} materials)", expanded=False):
        st.caption("""
        ⚠️ **Mixed Usage:** These materials had MOs where both primary and alternative were used together.
        Variance is calculated from **pure MOs only** (where only one material type was used).
        Mixed MO data is shown for reference but not used in variance calculation.
        """)
        
        display_df = mixed_data[[
            'bom_code', 'material_code', 'material_name', 'is_alternative',
            'mo_count_pure', 'mo_count_mixed', 'actual_avg_per_unit', 'avg_per_unit_mixed',
            'theoretical_qty_with_scrap', 'variance_pct'
        ]].copy()
        
        display_df['mat_source'] = display_df['is_alternative'].apply(
            lambda x: '🔄 Alt' if x == 1 else '📦 Pri'
        )
        display_df['pure_avg'] = display_df['actual_avg_per_unit'].apply(
            lambda x: f"{x:.4f}" if x > 0 else "N/A"
        )
        display_df['mixed_avg'] = display_df['avg_per_unit_mixed'].apply(
            lambda x: f"{x:.4f}" if x > 0 else "N/A"
        )
        display_df['theory'] = display_df['theoretical_qty_with_scrap'].apply(lambda x: f"{x:.4f}")
        display_df['variance_display'] = display_df['variance_pct'].apply(
            lambda x: f"{x:+.1f}%" if pd.notna(x) else "N/A (no pure MOs)"
        )
        
        st.dataframe(
            display_df[[
                'bom_code', 'material_code', 'mat_source', 
                'mo_count_pure', 'mo_count_mixed',
                'theory', 'pure_avg', 'mixed_avg', 'variance_display'
            ]].rename(columns={
                'bom_code': 'BOM',
                'material_code': 'Material',
                'mat_source': 'Source',
                'mo_count_pure': 'Pure MOs',
                'mo_count_mixed': 'Mixed MOs',
                'theory': 'Theory',
                'pure_avg': 'Avg (Pure)',
                'mixed_avg': 'Avg (Mixed)',
                'variance_display': 'Variance'
            }),
            use_container_width=True,
            hide_index=True
        )


# ==================== Main Render Functions ====================

@st.fragment
def render_filtered_results(full_data: pd.DataFrame):
    """Render filtered results - main content area"""
    filtered_data = apply_filters(full_data)
    
    total_count = len(full_data)
    filtered_count = len(filtered_data)
    
    if filtered_count < total_count:
        st.info(f"📊 Showing **{filtered_count}** of **{total_count}** records (filtered)")
    
    if filtered_data.empty:
        st.warning("⚠️ No data matches the current filters. Try adjusting your criteria.")
        return
    
    metrics = calculate_metrics(filtered_data)
    distribution = calculate_distribution(filtered_data)
    
    # Section 1: Summary Metrics
    render_summary_metrics_compact(metrics)
    
    st.markdown("---")
    
    # Section 2: Two-column (Donut Chart | By Type)
    col1, col2 = st.columns([1, 1])
    
    with col1:
        render_variance_donut_chart(distribution)
    
    with col2:
        render_by_type_combined(filtered_data)
    
    st.markdown("---")
    
    # Section 3: Top Issues Table
    render_top_variances_table(filtered_data, limit=10)
    
    # Section 4: Mixed Usage (Collapsed)
    render_mixed_usage_summary(filtered_data)


def render(analyzer) -> None:
    """
    Main render function for Dashboard tab
    
    Args:
        analyzer: VarianceAnalyzer instance
    """
    full_data = load_variance_data(analyzer)
    
    if full_data.empty:
        st.warning("⚠️ No variance data available. Check your date range and settings.")
        return
    
    # Render collapsible filters section
    render_filters_section(full_data)
    
    st.markdown("---")
    
    # Apply filters and render results
    render_filtered_results(full_data)