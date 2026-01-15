# pages/4_📊_BOM_Variance.py
"""
BOM Variance Analysis - VERSION 1.4 (Usage Mode Support)

Dashboard for analyzing actual material consumption vs BOM theoretical values.
Identifies variances and suggests adjustments to improve BOM accuracy.

Changes in v1.4:
- Support for Usage Mode (PRIMARY_ONLY, ALTERNATIVE_ONLY, MIXED)
- Variance calculated from PURE MOs only (not mixed)
- New columns: mo_count_pure, mo_count_mixed, has_mixed_usage
- Display "Xp+Ym" format for MO counts (X pure + Y mixed)
- Added Mixed Usage Summary section
- Show material source indicator (Pri/Alt)
- Backward compatible with v2.0 queries

Changes in v1.3:
- Added "Apply Filters" button to trigger data refresh after filter selection
- Fixed issue where filters didn't update the data table (due to @st.fragment isolation)
- Removed Quick Filter buttons to simplify UI (less overwhelming)
- Cleaner action row with just Reset All + Apply Filters

Changes in v1.2:
- Added Output Product multiselect filter
- Added BOM multiselect filter
- Replaced Material search with multiselect
- Implemented cascading filters (Product → BOM)
- Full format display: code (legacy) | name | pkg (brand)
- Collapsible filter section
- Improved filter organization

Changes in v1.1:
- Added data filters: Material Type, BOM Type, Variance Direction
- Added quick filter buttons
- Implemented @st.fragment to avoid full page reruns
- Cached full data, filter locally with pandas
"""

import streamlit as st
import pandas as pd
import logging
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from utils.auth import AuthManager
from utils.bom_variance import VarianceAnalyzer, VarianceConfig

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

# ==================== Constants ====================

MATERIAL_TYPES = ['RAW_MATERIAL', 'PACKAGING', 'CONSUMABLE']
BOM_TYPES = ['CUTTING', 'KITTING', 'REPACKING']
VARIANCE_DIRECTIONS = ['All', 'Under-used', 'On-target', 'Over-used', 'High Variance']

# ==================== Session State ====================

def init_session_state():
    """Initialize session state for variance analysis"""
    
    # Configuration (for DB query parameters)
    if 'variance_config' not in st.session_state:
        st.session_state['variance_config'] = VarianceConfig()
    
    # Full data cache (loaded from DB)
    if 'variance_full_data' not in st.session_state:
        st.session_state['variance_full_data'] = None
    
    # Filter states - Category filters
    if 'filter_material_types' not in st.session_state:
        st.session_state['filter_material_types'] = []  # Empty = All
    
    if 'filter_bom_types' not in st.session_state:
        st.session_state['filter_bom_types'] = []  # Empty = All
    
    if 'filter_variance_direction' not in st.session_state:
        st.session_state['filter_variance_direction'] = 'All'
    
    # Filter states - Entity filters (v1.2)
    if 'filter_products' not in st.session_state:
        st.session_state['filter_products'] = []  # Empty = All
    
    if 'filter_boms' not in st.session_state:
        st.session_state['filter_boms'] = []  # Empty = All
    
    if 'filter_materials' not in st.session_state:
        st.session_state['filter_materials'] = []  # Empty = All
    
    # Quick filter toggles
    if 'filter_high_variance_only' not in st.session_state:
        st.session_state['filter_high_variance_only'] = False
    
    if 'filter_zero_actual_only' not in st.session_state:
        st.session_state['filter_zero_actual_only'] = False
    
    # Filter section expanded state
    if 'filters_expanded' not in st.session_state:
        st.session_state['filters_expanded'] = True


def get_analyzer() -> VarianceAnalyzer:
    """Get analyzer instance with current config"""
    return VarianceAnalyzer(st.session_state['variance_config'])


def clear_data_cache():
    """Clear data cache (triggers reload from DB)"""
    st.session_state['variance_full_data'] = None


def reset_filters():
    """Reset all filters to default (empty = all)"""
    st.session_state['filter_material_types'] = []
    st.session_state['filter_bom_types'] = []
    st.session_state['filter_variance_direction'] = 'All'
    st.session_state['filter_products'] = []
    st.session_state['filter_boms'] = []
    st.session_state['filter_materials'] = []
    st.session_state['filter_high_variance_only'] = False
    st.session_state['filter_zero_actual_only'] = False


# ==================== Format Functions ====================

def format_product_display(code: str, name: str, 
                          package_size: Optional[str] = None,
                          brand: Optional[str] = None,
                          legacy_code: Optional[str] = None,
                          max_name_length: int = 40) -> str:
    """
    Format product display: code (legacy) | name | package_size (brand)
    
    Examples:
        "PT-001 (OLD-001) | Product ABC | 100g (Brand A)"
        "PT-002 (NEW) | Product XYZ | 500ml"
    """
    # Truncate name if too long
    if name and len(name) > max_name_length:
        name = name[:max_name_length - 3] + "..."
    
    # Format legacy code
    legacy_display = "NEW"
    if legacy_code and str(legacy_code).strip() and str(legacy_code).strip() not in ['-', 'None', '']:
        legacy_display = str(legacy_code).strip()
    
    result = f"{code} ({legacy_display}) | {name}"
    
    # Add package size and/or brand
    extra_parts = []
    
    if package_size and str(package_size).strip() and str(package_size).strip() not in ['-', 'None', '']:
        extra_parts.append(str(package_size).strip())
    
    if brand and str(brand).strip() and str(brand).strip() not in ['-', 'None', '']:
        if extra_parts:
            extra_parts[0] = f"{extra_parts[0]} ({str(brand).strip()})"
        else:
            extra_parts.append(f"({str(brand).strip()})")
    
    if extra_parts:
        result += " | " + " ".join(extra_parts)
    
    return result


def format_bom_display(bom_code: str, bom_name: str, bom_type: str = None) -> str:
    """
    Format BOM display: bom_code | bom_name [type]
    
    Examples:
        "BOM-CUT-001 | Main Product BOM [CUTTING]"
    """
    result = f"{bom_code} | {bom_name}"
    if bom_type:
        result += f" [{bom_type}]"
    return result


# ==================== Filter Options Extraction ====================

def get_filter_options(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Extract unique values for filter dropdowns from variance data
    No additional DB query needed
    """
    if df.empty:
        return {
            'products': pd.DataFrame(),
            'boms': pd.DataFrame(),
            'materials': pd.DataFrame()
        }
    
    # Unique products (output products)
    product_cols = ['output_product_code', 'output_product_name']
    # Add optional columns if they exist
    for col in ['output_product_legacy_code', 'output_product_package_size', 'output_product_brand']:
        if col in df.columns:
            product_cols.append(col)
    
    products = df[product_cols].drop_duplicates().sort_values('output_product_code')
    
    # Unique BOMs
    bom_cols = ['bom_header_id', 'bom_code', 'bom_name', 'bom_type', 'output_product_code']
    bom_cols = [c for c in bom_cols if c in df.columns]
    boms = df[bom_cols].drop_duplicates().sort_values('bom_code')
    
    # Unique materials
    material_cols = ['material_id', 'material_code', 'material_name', 'material_type']
    # Add optional columns if they exist
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
    """
    Get BOM options filtered by selected products (cascading filter)
    """
    if df.empty:
        return pd.DataFrame()
    
    bom_cols = ['bom_header_id', 'bom_code', 'bom_name', 'bom_type', 'output_product_code']
    bom_cols = [c for c in bom_cols if c in df.columns]
    
    if selected_products:
        # Filter by selected products
        filtered_df = df[df['output_product_code'].isin(selected_products)]
    else:
        filtered_df = df
    
    return filtered_df[bom_cols].drop_duplicates().sort_values('bom_code')


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


def create_bom_options(boms_df: pd.DataFrame) -> List[str]:
    """Create formatted BOM options for multiselect"""
    if boms_df.empty:
        return []
    
    options = []
    for _, row in boms_df.iterrows():
        display = format_bom_display(
            bom_code=row.get('bom_code', ''),
            bom_name=row.get('bom_name', ''),
            bom_type=row.get('bom_type')
        )
        options.append(display)
    
    return options


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


def extract_code_from_option(option: str) -> str:
    """Extract code from formatted option string"""
    # Format: "CODE (legacy) | name | ..."
    if '|' in option:
        first_part = option.split('|')[0].strip()
        if '(' in first_part:
            return first_part.split('(')[0].strip()
        return first_part
    return option


def extract_bom_code_from_option(option: str) -> str:
    """Extract BOM code from formatted option string"""
    # Format: "BOM-CODE | name [TYPE]"
    if '|' in option:
        return option.split('|')[0].strip()
    return option


# ==================== Data Loading & Filtering ====================

def load_variance_data() -> pd.DataFrame:
    """
    Load full variance data from DB (cached in session state)
    Only reloads when config changes or cache is cleared
    """
    if st.session_state['variance_full_data'] is None:
        analyzer = get_analyzer()
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
    config = st.session_state['variance_config']
    threshold = config.variance_threshold
    
    # Filter by Material Type
    material_types = st.session_state['filter_material_types']
    if material_types:  # Non-empty = filter
        filtered = filtered[filtered['material_type'].isin(material_types)]
    
    # Filter by BOM Type
    bom_types = st.session_state['filter_bom_types']
    if bom_types:  # Non-empty = filter
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
    
    # Filter by Output Product (v1.2)
    selected_products = st.session_state['filter_products']
    if selected_products:
        product_codes = [extract_code_from_option(p) for p in selected_products]
        filtered = filtered[filtered['output_product_code'].isin(product_codes)]
    
    # Filter by BOM (v1.2)
    selected_boms = st.session_state['filter_boms']
    if selected_boms:
        bom_codes = [extract_bom_code_from_option(b) for b in selected_boms]
        filtered = filtered[filtered['bom_code'].isin(bom_codes)]
    
    # Filter by Material (v1.2)
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


def get_filter_counts(df: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """
    Get counts for filter options from full data
    """
    if df.empty:
        return {
            'material_types': {t: 0 for t in MATERIAL_TYPES},
            'bom_types': {t: 0 for t in BOM_TYPES},
            'variance_directions': {d: 0 for d in VARIANCE_DIRECTIONS}
        }
    
    config = st.session_state['variance_config']
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
    import numpy as np
    
    if df.empty:
        return {
            'bins': [],
            'counts': [],
            'categories': {'under_used': 0, 'on_target': 0, 'over_used': 0, 'high_variance': 0},
            'stats': {}
        }
    
    config = st.session_state['variance_config']
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


# ==================== Main Application ====================

def main():
    """Main application entry point"""
    init_session_state()
    
    # Header
    render_header()
    
    # Sidebar with configuration (triggers DB reload)
    render_sidebar_config()
    
    # Load full data once
    full_data = load_variance_data()
    
    # Main content
    render_main_content(full_data)
    
    # Footer
    render_footer()


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


def render_sidebar_config():
    """Render sidebar with analysis configuration (DB query parameters)"""
    
    with st.sidebar:
        st.header("⚙️ Analysis Settings")
        
        config = st.session_state['variance_config']
        
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
        
        # Apply settings button (triggers DB reload)
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


def render_main_content(full_data: pd.DataFrame):
    """Render main content area with tabs"""
    
    # Tab selection
    tab1, tab2, tab3 = st.tabs([
        "📊 Dashboard Overview",
        "🔍 BOM Detail Analysis",
        "💡 Recommendations"
    ])
    
    with tab1:
        render_dashboard_tab(full_data)
    
    with tab2:
        render_detail_tab_placeholder(full_data)
    
    with tab3:
        render_recommendations_tab_placeholder(full_data)


# ==================== Tab 1: Dashboard Overview ====================

def render_dashboard_tab(full_data: pd.DataFrame):
    """Render Dashboard Overview tab with filters"""
    
    if full_data.empty:
        st.warning("⚠️ No variance data available. Check your date range and settings.")
        return
    
    # Render collapsible filters section
    render_filters_section(full_data)
    
    st.markdown("---")
    
    # Apply filters and render results
    render_filtered_results(full_data)


@st.fragment
def render_filters_section(full_data: pd.DataFrame):
    """
    Render filter controls - uses @st.fragment to avoid full page rerun
    Collapsible with expander
    """
    # Get counts and options from full data
    counts = get_filter_counts(full_data)
    filter_options = get_filter_options(full_data)
    config = st.session_state['variance_config']
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
            
            # Get current values with counts
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
            
            # Extract actual values (remove counts)
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
        
        # Row 2: Entity Filters (v1.2)
        st.markdown(f"##### Entity Filters ({counts['entities']['products']} products, {counts['entities']['boms']} BOMs, {counts['entities']['materials']} materials)")
        col4, col5 = st.columns(2)
        
        with col4:
            # Output Product multiselect
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
            # BOM multiselect - cascaded by selected products
            selected_product_codes = [extract_code_from_option(p) for p in selected_products]
            
            # Get cascaded BOM options
            cascaded_boms = get_cascaded_bom_options(full_data, selected_product_codes)
            bom_options = create_bom_options(cascaded_boms)
            
            # Filter current selections to only valid options
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
            # Material multiselect (replaces search box)
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
            # Quick filter toggles
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


@st.fragment
def render_filtered_results(full_data: pd.DataFrame):
    """
    Render filtered results - uses @st.fragment for partial updates
    """
    # Apply filters
    filtered_data = apply_filters(full_data)
    
    # Show filter summary
    total_count = len(full_data)
    filtered_count = len(filtered_data)
    
    if filtered_count < total_count:
        st.info(f"📊 Showing **{filtered_count}** of **{total_count}** records (filtered)")
    
    if filtered_data.empty:
        st.warning("⚠️ No data matches the current filters. Try adjusting your criteria.")
        return
    
    # Calculate metrics from filtered data
    metrics = calculate_metrics(filtered_data)
    distribution = calculate_distribution(filtered_data)
    
    # Summary Metrics Row
    render_summary_metrics(metrics)
    
    st.markdown("---")
    
    # Two column layout
    col1, col2 = st.columns([1, 1])
    
    with col1:
        # Variance Distribution
        render_variance_distribution(distribution)
        
        st.markdown("---")
        
        # Variance by BOM Type
        render_bom_type_summary(filtered_data)
    
    with col2:
        # Top Variances Table
        render_top_variances_table(filtered_data)
    
    # Mixed Usage Summary (if any)
    render_mixed_usage_summary(filtered_data)


def render_summary_metrics(metrics: Dict[str, Any]):
    """Render summary metrics cards"""
    
    st.subheader("📈 Summary Metrics")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            "BOMs Analyzed",
            metrics.get('total_boms_analyzed', 0),
            help="Number of BOMs in filtered data"
        )
    
    with col2:
        st.metric(
            "Materials Analyzed",
            metrics.get('total_materials_analyzed', 0),
            help="Total material-BOM combinations in filtered data"
        )
    
    with col3:
        boms_with_variance = metrics.get('boms_with_variance', 0)
        total_boms = metrics.get('total_boms_analyzed', 0)
        pct = (boms_with_variance / total_boms * 100) if total_boms > 0 else 0
        
        st.metric(
            "⚠️ High Variance",
            boms_with_variance,
            delta=f"{pct:.1f}%" if pct > 0 else None,
            delta_color="inverse",
            help="BOMs with at least one material above variance threshold"
        )
    
    with col4:
        st.metric(
            "⚠️ Materials to Review",
            metrics.get('materials_with_variance', 0),
            help="Materials with variance above threshold"
        )
    
    with col5:
        avg_variance = metrics.get('avg_variance_pct', 0)
        max_variance = metrics.get('max_variance_pct', 0)
        
        st.metric(
            "Avg. Variance",
            f"{avg_variance:.1f}%",
            delta=f"Max: {max_variance:.1f}%",
            delta_color="off",
            help="Average absolute variance across filtered materials"
        )


def render_variance_distribution(distribution: Dict[str, Any]):
    """Render variance distribution chart"""
    
    st.subheader("📊 Variance Distribution")
    
    categories = distribution.get('categories', {})
    stats = distribution.get('stats', {})
    
    if not categories or all(v == 0 for v in categories.values()):
        st.info("ℹ️ No variance data available for the selected filters.")
        return
    
    # Category metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "🟢 On Target",
            categories.get('on_target', 0),
            help="Materials within variance threshold"
        )
    
    with col2:
        st.metric(
            "🔵 Under-used",
            categories.get('under_used', 0),
            help="Materials used less than expected"
        )
    
    with col3:
        st.metric(
            "🟠 Over-used",
            categories.get('over_used', 0),
            help="Materials used more than expected"
        )
    
    with col4:
        st.metric(
            "🔴 High Variance",
            categories.get('high_variance', 0),
            help="Materials with variance > 2x threshold"
        )
    
    # Bar chart for distribution
    bins = distribution.get('bin_labels', [])
    counts = distribution.get('counts', [])
    
    if bins and counts:
        try:
            import plotly.graph_objects as go
            
            # Color based on range
            colors = []
            for label in bins:
                if label.startswith('-'):
                    colors.append('#3498db')  # Blue for negative
                elif '0 to' in label or 'to 0' in label:
                    colors.append('#2ecc71')  # Green for near zero
                else:
                    colors.append('#e67e22')  # Orange for positive
            
            fig = go.Figure(data=[
                go.Bar(
                    x=bins,
                    y=counts,
                    marker_color=colors
                )
            ])
            
            fig.update_layout(
                title="Variance Distribution",
                xaxis_title="Variance Range (%)",
                yaxis_title="Number of Materials",
                height=300,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.bar_chart(pd.DataFrame({'Count': counts}, index=bins))
    
    # Statistics
    if stats:
        with st.expander("📊 Statistics", expanded=False):
            stat_col1, stat_col2, stat_col3 = st.columns(3)
            with stat_col1:
                st.write(f"**Mean:** {stats.get('mean', 0):.2f}%")
                st.write(f"**Median:** {stats.get('median', 0):.2f}%")
            with stat_col2:
                st.write(f"**Std Dev:** {stats.get('std', 0):.2f}%")
            with stat_col3:
                st.write(f"**Min:** {stats.get('min', 0):.2f}%")
                st.write(f"**Max:** {stats.get('max', 0):.2f}%")


def render_bom_type_summary(filtered_data: pd.DataFrame):
    """Render variance summary by BOM type"""
    
    st.subheader("📋 Variance by BOM Type")
    
    if filtered_data.empty:
        st.info("ℹ️ No BOM type data available.")
        return
    
    # Check if new columns exist
    has_new_columns = 'mo_count_pure' in filtered_data.columns
    
    # Group by BOM type
    if has_new_columns:
        summary = filtered_data.groupby('bom_type').agg({
            'bom_header_id': 'nunique',
            'material_id': 'count',
            'variance_pct': 'mean',
            'has_high_variance': 'sum',
            'mo_count_pure': 'sum',
            'mo_count_mixed': 'sum'
        }).reset_index()
        
        summary.columns = ['BOM Type', 'BOMs', 'Materials', 'Avg Variance', 'High Var.', 'Pure MOs', 'Mixed MOs']
    else:
        summary = filtered_data.groupby('bom_type').agg({
            'bom_header_id': 'nunique',
            'material_id': 'count',
            'variance_pct': 'mean',
            'has_high_variance': 'sum'
        }).reset_index()
        
        summary.columns = ['BOM Type', 'BOMs', 'Materials', 'Avg Variance', 'High Var.']
    
    # Format display
    summary['Avg Variance'] = summary['Avg Variance'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    summary['% High Var.'] = summary.apply(
        lambda row: f"{row['High Var.'] / row['Materials'] * 100:.0f}%" 
        if row['Materials'] > 0 else "0%",
        axis=1
    )
    
    if has_new_columns:
        st.dataframe(
            summary[['BOM Type', 'BOMs', 'Materials', 'Avg Variance', 'High Var.', '% High Var.', 'Pure MOs', 'Mixed MOs']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.dataframe(
            summary[['BOM Type', 'BOMs', 'Materials', 'Avg Variance', 'High Var.', '% High Var.']],
            use_container_width=True,
            hide_index=True
        )


def render_mixed_usage_summary(filtered_data: pd.DataFrame):
    """Render summary of materials with mixed usage (primary + alternative in same MO)"""
    
    # Check if new columns exist
    if 'mo_count_mixed' not in filtered_data.columns:
        return
    
    # Filter to items with mixed usage
    mixed_data = filtered_data[filtered_data['mo_count_mixed'] > 0].copy()
    
    if mixed_data.empty:
        return
    
    with st.expander(f"🔀 Mixed Usage Summary ({len(mixed_data)} materials)", expanded=False):
        st.caption("""
        ⚠️ **Mixed Usage:** These materials had MOs where both primary and alternative were used together.
        Variance is calculated from **pure MOs only** (where only one material type was used).
        Mixed MO data is shown for reference but not used in variance calculation.
        """)
        
        # Summary table
        display_df = mixed_data[[
            'bom_code', 'material_code', 'material_name', 'is_alternative',
            'mo_count_pure', 'mo_count_mixed', 'actual_avg_per_unit', 'avg_per_unit_mixed',
            'theoretical_qty_with_scrap', 'variance_pct'
        ]].copy()
        
        # Format
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


def render_top_variances_table(filtered_data: pd.DataFrame, limit: int = 10):
    """Render top variances table"""
    
    st.subheader(f"🔝 Top {limit} Variances")
    
    if filtered_data.empty:
        st.info("ℹ️ No variance data available for the selected filters.")
        return
    
    # Filter to only show items with pure MO data (variance is calculated from pure MOs)
    data_with_variance = filtered_data[filtered_data['variance_pct'].notna()].copy()
    
    if data_with_variance.empty:
        st.info("ℹ️ No variance data from pure MOs. All MOs may have mixed material usage.")
        return
    
    # Sort by absolute variance
    data_with_variance['abs_variance'] = data_with_variance['variance_pct'].abs()
    top_data = data_with_variance.sort_values('abs_variance', ascending=False).head(limit)
    
    # Check if new columns exist (backward compatibility)
    has_new_columns = 'mo_count_pure' in top_data.columns
    
    # Format for display
    if has_new_columns:
        display_df = top_data[[
            'bom_code', 'bom_type', 'material_code', 'material_name', 'material_type',
            'is_alternative', 'theoretical_qty_with_scrap', 'actual_avg_per_unit', 
            'variance_pct', 'mo_count_pure', 'mo_count_mixed', 'cv_percent'
        ]].copy()
        
        # Format MO count with pure/mixed indicator
        display_df['mo_display'] = display_df.apply(
            lambda row: f"{int(row['mo_count_pure'])}p" + (f"+{int(row['mo_count_mixed'])}m" if row['mo_count_mixed'] > 0 else ""),
            axis=1
        )
        
        # Format is_alternative
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
    
    # Format columns
    display_df['theoretical_qty_with_scrap'] = display_df['theoretical_qty_with_scrap'].apply(lambda x: f"{x:.4f}")
    display_df['actual_avg_per_unit'] = display_df['actual_avg_per_unit'].apply(lambda x: f"{x:.4f}")
    display_df['variance_display'] = display_df['variance_pct'].apply(format_variance_display)
    display_df['cv_display'] = display_df['cv_percent'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    
    # Select columns based on availability
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
    
    # Legend
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


def format_variance_display(value: float) -> str:
    """Format variance for display with color indicator"""
    if pd.isna(value):
        return "N/A"
    
    if value > 10:
        return f"🔴 +{value:.1f}%"
    elif value > 5:
        return f"🟠 +{value:.1f}%"
    elif value > 0:
        return f"🟡 +{value:.1f}%"
    elif value > -5:
        return f"🟢 {value:.1f}%"
    elif value > -10:
        return f"🔵 {value:.1f}%"
    else:
        return f"🔵 {value:.1f}%"


# ==================== Tab 2 & 3 Placeholders ====================

def render_detail_tab_placeholder(full_data: pd.DataFrame):
    """Placeholder for BOM Detail Analysis tab (Phase 2)"""
    
    st.subheader("🔍 BOM Detail Analysis")
    
    st.info("""
    🚧 **Coming in Phase 2**
    
    This tab will include:
    - BOM selector for detailed analysis
    - Material-by-material variance comparison
    - Per-MO consumption history
    - Trend charts over time
    - Alternative material usage tracking
    """)
    
    if not full_data.empty:
        st.subheader("📋 Available BOMs for Analysis")
        
        bom_summary = full_data.groupby(['bom_code', 'bom_name', 'bom_type', 'bom_status']).agg({
            'material_id': 'count',
            'mo_count': 'first',
            'has_high_variance': 'sum'
        }).reset_index()
        
        bom_summary.columns = ['BOM Code', 'BOM Name', 'Type', 'Status', 'Materials', 'MOs', 'High Var.']
        
        st.dataframe(
            bom_summary.sort_values('High Var.', ascending=False),
            use_container_width=True,
            hide_index=True
        )


def render_recommendations_tab_placeholder(full_data: pd.DataFrame):
    """Placeholder for Recommendations tab (Phase 3)"""
    
    st.subheader("💡 Recommendations")
    
    st.info("""
    🚧 **Coming in Phase 3**
    
    This tab will include:
    - List of materials needing adjustment
    - Suggested quantity and scrap rate changes
    - Two apply options:
        - **Clone BOM**: Create new DRAFT BOM with adjusted values
        - **Direct Update**: Update existing BOM (if no usage history)
    - Bulk actions for multiple materials
    - Export recommendations to Excel
    """)
    
    if not full_data.empty:
        high_variance = full_data[full_data['has_high_variance'] == True]
        
        if not high_variance.empty:
            st.subheader("⚠️ Materials Needing Review")
            st.caption(f"Showing {len(high_variance)} materials with variance above threshold")
            
            bom_summary = high_variance.groupby(['bom_code', 'bom_name']).agg({
                'material_id': 'count',
                'variance_pct': 'mean'
            }).reset_index()
            
            bom_summary.columns = ['BOM Code', 'BOM Name', 'Materials to Review', 'Avg Variance %']
            bom_summary['Avg Variance %'] = bom_summary['Avg Variance %'].apply(lambda x: f"{x:.1f}%")
            
            st.dataframe(
                bom_summary.sort_values('Materials to Review', ascending=False),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("✅ No materials found with variance above threshold. BOMs are performing well!")


# ==================== Footer ====================

def render_footer():
    """Render page footer"""
    st.markdown("---")
    
    config = st.session_state['variance_config']
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.caption(
            f"📊 BOM Variance Analysis v1.4 | "
            f"Period: {config.date_from} to {config.date_to} | "
            f"Threshold: {config.variance_threshold}%"
        )
    
    with col2:
        st.caption(f"Session: {st.session_state.get('user_name', 'Guest')}")


# ==================== Run Application ====================

if __name__ == "__main__":
    main()