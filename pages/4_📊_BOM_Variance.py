# pages/4_📊_BOM_Variance.py
"""
BOM Variance Analysis - VERSION 1.0 (Phase 1)

Dashboard for analyzing actual material consumption vs BOM theoretical values.
Identifies variances and suggests adjustments to improve BOM accuracy.

Features:
- Dashboard Overview with key metrics
- Variance distribution visualization
- Top variances quick view
- Configurable analysis parameters
- Filter by date range, BOM type

Phase 1: Dashboard Overview + Basic queries
Phase 2: BOM Detail Analysis + Charts (coming)
Phase 3: Recommendations + Apply (coming)
"""

import streamlit as st
import pandas as pd
import logging
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any

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

# ==================== Session State ====================

def init_session_state():
    """Initialize session state for variance analysis"""
    
    # Configuration
    if 'variance_config' not in st.session_state:
        st.session_state['variance_config'] = VarianceConfig()
    
    # Analysis data cache
    if 'variance_data_cache' not in st.session_state:
        st.session_state['variance_data_cache'] = None
    
    # Selected tab
    if 'variance_active_tab' not in st.session_state:
        st.session_state['variance_active_tab'] = 'dashboard'


def get_analyzer() -> VarianceAnalyzer:
    """Get analyzer instance with current config"""
    return VarianceAnalyzer(st.session_state['variance_config'])


def clear_cache():
    """Clear analysis data cache"""
    st.session_state['variance_data_cache'] = None


# ==================== Main Application ====================

def main():
    """Main application entry point"""
    init_session_state()
    
    # Header
    render_header()
    
    # Sidebar with configuration
    render_sidebar_config()
    
    # Main content tabs
    render_main_content()
    
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
            clear_cache()
            st.rerun()


def render_sidebar_config():
    """Render sidebar with analysis configuration"""
    
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
                clear_cache()
                st.rerun()
        with preset_col2:
            if st.button("3M", use_container_width=True, help="Last 3 months"):
                config.date_to = date.today()
                config.date_from = config.date_to - timedelta(days=90)
                clear_cache()
                st.rerun()
        with preset_col3:
            if st.button("6M", use_container_width=True, help="Last 6 months"):
                config.date_to = date.today()
                config.date_from = config.date_to - timedelta(days=180)
                clear_cache()
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
            clear_cache()
            st.rerun()
        
        st.markdown("---")
        
        # Current settings display
        with st.expander("📋 Current Settings", expanded=False):
            st.json({
                'date_from': str(config.date_from),
                'date_to': str(config.date_to),
                'variance_threshold': config.variance_threshold,
                'min_mo_count': config.min_mo_count,
                'cv_threshold': config.cv_threshold
            })


def render_main_content():
    """Render main content area with tabs"""
    
    # Tab selection
    tab1, tab2, tab3 = st.tabs([
        "📊 Dashboard Overview",
        "🔍 BOM Detail Analysis",
        "💡 Recommendations"
    ])
    
    with tab1:
        render_dashboard_tab()
    
    with tab2:
        render_detail_tab_placeholder()
    
    with tab3:
        render_recommendations_tab_placeholder()


# ==================== Tab 1: Dashboard Overview ====================

def render_dashboard_tab():
    """Render Dashboard Overview tab"""
    
    analyzer = get_analyzer()
    
    # Get data (with caching)
    try:
        with st.spinner("Loading variance data..."):
            metrics = analyzer.get_dashboard_metrics()
            distribution = analyzer.get_variance_distribution()
            top_variances = analyzer.get_top_variances(limit=10)
            bom_type_summary = analyzer.get_variance_by_bom_type()
    except Exception as e:
        st.error(f"❌ Error loading data: {str(e)}")
        logger.error(f"Error in dashboard: {e}")
        return
    
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
        render_bom_type_summary(bom_type_summary)
    
    with col2:
        # Top Variances Table
        render_top_variances_table(top_variances)


def render_summary_metrics(metrics: Dict[str, Any]):
    """Render summary metrics cards"""
    
    st.subheader("📈 Summary Metrics")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            "BOMs Analyzed",
            metrics.get('total_boms_analyzed', 0),
            help="Number of BOMs with completed MOs in the analysis period"
        )
    
    with col2:
        st.metric(
            "Materials Analyzed",
            metrics.get('total_materials_analyzed', 0),
            help="Total material-BOM combinations analyzed"
        )
    
    with col3:
        boms_with_variance = metrics.get('boms_with_variance', 0)
        total_boms = metrics.get('total_boms_analyzed', 0)
        pct = (boms_with_variance / total_boms * 100) if total_boms > 0 else 0
        
        st.metric(
            "⚠️ BOMs with High Variance",
            boms_with_variance,
            delta=f"{pct:.1f}%" if pct > 0 else None,
            delta_color="inverse",
            help="BOMs with at least one material above variance threshold"
        )
    
    with col4:
        materials_with_variance = metrics.get('materials_with_variance', 0)
        
        st.metric(
            "⚠️ Materials to Review",
            materials_with_variance,
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
            help="Average absolute variance across all materials"
        )


def render_variance_distribution(distribution: Dict[str, Any]):
    """Render variance distribution chart"""
    
    st.subheader("📊 Variance Distribution")
    
    categories = distribution.get('categories', {})
    stats = distribution.get('stats', {})
    
    if not categories or all(v == 0 for v in categories.values()):
        st.info("ℹ️ No variance data available for the selected period.")
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
            help="Materials used less than expected (potential savings)"
        )
    
    with col3:
        st.metric(
            "🟠 Over-used",
            categories.get('over_used', 0),
            help="Materials used more than expected (waste)"
        )
    
    with col4:
        st.metric(
            "🔴 High Variance",
            categories.get('high_variance', 0),
            help="Materials with variance > 10%"
        )
    
    # Bar chart for distribution
    bins = distribution.get('bin_labels', [])
    counts = distribution.get('counts', [])
    
    if bins and counts:
        import plotly.express as px
        import plotly.graph_objects as go
        
        # Create DataFrame for chart
        chart_df = pd.DataFrame({
            'Range': bins,
            'Count': counts
        })
        
        # Color based on range (negative = blue, near zero = green, positive = orange/red)
        colors = []
        for label in bins:
            if '-' in label.split(' to ')[0]:
                colors.append('#3498db')  # Blue for negative (under-used)
            elif '0' in label:
                colors.append('#2ecc71')  # Green for near zero
            else:
                colors.append('#e67e22')  # Orange for positive (over-used)
        
        fig = go.Figure(data=[
            go.Bar(
                x=chart_df['Range'],
                y=chart_df['Count'],
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


def render_bom_type_summary(summary_df: pd.DataFrame):
    """Render variance summary by BOM type"""
    
    st.subheader("📋 Variance by BOM Type")
    
    if summary_df.empty:
        st.info("ℹ️ No BOM type data available.")
        return
    
    # Format display columns
    display_df = summary_df.copy()
    display_df['avg_variance'] = display_df['avg_variance'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    display_df['high_variance_pct'] = display_df.apply(
        lambda row: f"{row['high_variance_count'] / row['material_count'] * 100:.0f}%" 
        if row['material_count'] > 0 else "0%",
        axis=1
    )
    
    # Display table
    st.dataframe(
        display_df[[
            'bom_type', 'bom_count', 'material_count', 
            'avg_variance', 'high_variance_count', 'high_variance_pct'
        ]].rename(columns={
            'bom_type': 'BOM Type',
            'bom_count': 'BOMs',
            'material_count': 'Materials',
            'avg_variance': 'Avg Variance',
            'high_variance_count': 'High Var.',
            'high_variance_pct': '% High Var.'
        }),
        use_container_width=True,
        hide_index=True
    )


def render_top_variances_table(top_variances: pd.DataFrame):
    """Render top variances table"""
    
    st.subheader("🔝 Top 10 Variances")
    
    if top_variances.empty:
        st.info("ℹ️ No variance data available for the selected criteria.")
        return
    
    # Format for display
    display_df = top_variances[[
        'bom_code', 'bom_type', 'material_code', 'material_name',
        'theoretical_qty_with_scrap', 'actual_avg_per_unit', 
        'variance_pct', 'mo_count', 'cv_percent'
    ]].copy()
    
    # Format columns
    display_df['theoretical_qty_with_scrap'] = display_df['theoretical_qty_with_scrap'].apply(lambda x: f"{x:.4f}")
    display_df['actual_avg_per_unit'] = display_df['actual_avg_per_unit'].apply(lambda x: f"{x:.4f}")
    display_df['variance_display'] = display_df['variance_pct'].apply(format_variance_display)
    display_df['cv_display'] = display_df['cv_percent'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    
    # Column config for better display
    column_config = {
        "bom_code": st.column_config.TextColumn("BOM Code", width="small"),
        "bom_type": st.column_config.TextColumn("Type", width="small"),
        "material_code": st.column_config.TextColumn("Material", width="small"),
        "material_name": st.column_config.TextColumn("Material Name", width="medium"),
        "theoretical_qty_with_scrap": st.column_config.TextColumn("Theory", width="small"),
        "actual_avg_per_unit": st.column_config.TextColumn("Actual", width="small"),
        "variance_display": st.column_config.TextColumn("Variance", width="small"),
        "mo_count": st.column_config.NumberColumn("MOs", width="small"),
        "cv_display": st.column_config.TextColumn("CV%", width="small"),
    }
    
    st.dataframe(
        display_df[[
            'bom_code', 'bom_type', 'material_code', 'material_name',
            'theoretical_qty_with_scrap', 'actual_avg_per_unit',
            'variance_display', 'mo_count', 'cv_display'
        ]].rename(columns={
            'bom_code': 'BOM Code',
            'bom_type': 'Type',
            'material_code': 'Material',
            'material_name': 'Material Name',
            'theoretical_qty_with_scrap': 'Theory',
            'actual_avg_per_unit': 'Actual',
            'variance_display': 'Variance',
            'mo_count': 'MOs',
            'cv_display': 'CV%'
        }),
        use_container_width=True,
        hide_index=True,
        column_config=column_config
    )
    
    # Legend
    st.caption("""
    📝 **Legend:** Theory = Theoretical qty per output (with scrap) | 
    Actual = Average actual consumption per output | 
    CV% = Coefficient of Variation (high = inconsistent usage)
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

def render_detail_tab_placeholder():
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
    
    # Preview: BOM selector
    analyzer = get_analyzer()
    
    try:
        bom_list = analyzer.get_bom_list()
        
        if not bom_list.empty:
            st.subheader("📋 Available BOMs for Analysis")
            
            # Format display
            display_df = bom_list[[
                'bom_code', 'bom_name', 'bom_type', 'status',
                'output_product_code', 'completed_mo_count', 'total_produced'
            ]].copy()
            
            display_df['total_produced'] = display_df['total_produced'].apply(
                lambda x: f"{x:,.2f}" if pd.notna(x) else "0"
            )
            
            st.dataframe(
                display_df.rename(columns={
                    'bom_code': 'BOM Code',
                    'bom_name': 'BOM Name',
                    'bom_type': 'Type',
                    'status': 'Status',
                    'output_product_code': 'Product',
                    'completed_mo_count': 'Completed MOs',
                    'total_produced': 'Total Produced'
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.warning("No BOMs with completed MOs found in the selected period.")
    
    except Exception as e:
        st.error(f"Error loading BOM list: {e}")


def render_recommendations_tab_placeholder():
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
    
    # Preview: Show materials with high variance
    analyzer = get_analyzer()
    
    try:
        recommendations = analyzer.get_recommendations(only_high_variance=True)
        
        if not recommendations.empty:
            st.subheader("⚠️ Materials Needing Review")
            st.caption(f"Showing {len(recommendations)} materials with variance above threshold")
            
            # Summary by BOM
            bom_summary = recommendations.groupby(['bom_code', 'bom_name']).agg({
                'material_id': 'count',
                'variance_pct': 'mean'
            }).reset_index()
            
            bom_summary.columns = ['BOM Code', 'BOM Name', 'Materials to Review', 'Avg Variance %']
            bom_summary['Avg Variance %'] = bom_summary['Avg Variance %'].apply(lambda x: f"{x:.1f}%")
            
            st.dataframe(
                bom_summary,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("✅ No materials found with variance above threshold. BOMs are performing well!")
    
    except Exception as e:
        st.error(f"Error loading recommendations: {e}")


# ==================== Footer ====================

def render_footer():
    """Render page footer"""
    st.markdown("---")
    
    config = st.session_state['variance_config']
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.caption(
            f"📊 BOM Variance Analysis v1.0 | "
            f"Analysis Period: {config.date_from} to {config.date_to} | "
            f"Threshold: {config.variance_threshold}%"
        )
    
    with col2:
        st.caption(f"Session: {st.session_state.get('user_name', 'Guest')}")


# ==================== Run Application ====================

if __name__ == "__main__":
    main()