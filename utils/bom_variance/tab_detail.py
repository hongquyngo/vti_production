# utils/bom_variance/tab_detail.py
"""
BOM Variance - Tab 2: BOM Detail Analysis - VERSION 2.0

Phase 2 Implementation - Contains:
- BOM selector for detailed analysis
- Material-by-material variance comparison
- Per-MO consumption history
- Trend charts over time
- Alternative material usage tracking
"""

import streamlit as st
import pandas as pd
import numpy as np
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import date

from .config import (
    get_config, 
    format_variance_display,
    format_product_display,
    format_bom_display_full,
    create_bom_options_from_df
)

logger = logging.getLogger(__name__)


# ==================== Data Helpers ====================

def get_bom_options(full_data: pd.DataFrame) -> pd.DataFrame:
    """Extract unique BOMs from variance data for selector"""
    if full_data.empty:
        return pd.DataFrame()
    
    bom_cols = [
        'bom_header_id', 'bom_code', 'bom_name', 'bom_type', 'bom_status',
        'output_product_code', 'output_product_name'
    ]
    bom_cols = [c for c in bom_cols if c in full_data.columns]
    
    # Aggregate stats per BOM
    bom_stats = full_data.groupby('bom_header_id').agg({
        'material_id': 'count',
        'mo_count': 'first',
        'has_high_variance': 'sum',
        'variance_pct': lambda x: x.abs().mean()
    }).reset_index()
    bom_stats.columns = ['bom_header_id', 'material_count', 'mo_count', 'high_variance_count', 'avg_variance']
    
    # Get BOM info
    bom_info = full_data[bom_cols].drop_duplicates()
    
    # Merge
    result = bom_info.merge(bom_stats, on='bom_header_id')
    
    return result.sort_values('high_variance_count', ascending=False)


def get_materials_for_bom(full_data: pd.DataFrame, bom_id: int) -> pd.DataFrame:
    """Get materials for a specific BOM"""
    if full_data.empty:
        return pd.DataFrame()
    
    return full_data[full_data['bom_header_id'] == bom_id].copy()


def get_material_options(bom_materials: pd.DataFrame) -> List[Dict[str, Any]]:
    """Create material options for selector"""
    if bom_materials.empty:
        return []
    
    options = []
    for _, row in bom_materials.iterrows():
        source = '🔄 Alt' if row.get('is_alternative', 0) == 1 else '📦 Pri'
        variance = row.get('variance_pct', 0)
        var_str = f"{variance:+.1f}%" if pd.notna(variance) else "N/A"
        
        options.append({
            'material_id': row['material_id'],
            'material_code': row['material_code'],
            'material_name': row['material_name'],
            'is_alternative': row.get('is_alternative', 0),
            'display': f"{source} {row['material_code']} - {row['material_name']} ({var_str})"
        })
    
    return options


# ==================== Main Render Function ====================

def render(full_data: pd.DataFrame, analyzer=None) -> None:
    """
    Main render function for BOM Detail Analysis tab
    
    Args:
        full_data: Full variance DataFrame from analyzer
        analyzer: VarianceAnalyzer instance (optional, for additional queries)
    """
    st.subheader("🔍 BOM Detail Analysis")
    
    if full_data.empty:
        st.warning("⚠️ No data available for analysis. Check your date range and settings.")
        return
    
    # Get BOM options
    bom_options = get_bom_options(full_data)
    
    if bom_options.empty:
        st.warning("⚠️ No BOMs found with completed MOs in the selected period.")
        return
    
    # ==================== BOM Selector ====================
    selected_bom_id = render_bom_selector(bom_options)
    
    if selected_bom_id is None:
        st.info("👆 Please select a BOM to view detailed analysis.")
        return
    
    st.markdown("---")
    
    # Get data for selected BOM
    bom_materials = get_materials_for_bom(full_data, selected_bom_id)
    bom_info = bom_options[bom_options['bom_header_id'] == selected_bom_id].iloc[0]
    
    # ==================== BOM Summary Header ====================
    render_bom_summary_header(bom_info, bom_materials)
    
    st.markdown("---")
    
    # ==================== Material Breakdown ====================
    render_material_breakdown(bom_materials)
    
    st.markdown("---")
    
    # ==================== Detailed Analysis Section ====================
    render_detailed_analysis(bom_materials, selected_bom_id, analyzer)


# ==================== BOM Selector ====================

def render_bom_selector(bom_options: pd.DataFrame) -> Optional[int]:
    """
    Render BOM selector with search and summary
    
    Returns:
        Selected BOM header ID or None
    """
    st.markdown("##### 📋 Select BOM for Analysis")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Create display options using unified format function
        display_options, bom_id_map = create_bom_options_from_df(
            bom_options, 
            include_stats=True
        )
        
        selected_display = st.selectbox(
            "BOM",
            options=[""] + display_options,
            index=0,
            placeholder="Search by BOM code or name...",
            help="Select a BOM to view detailed variance analysis"
        )
        
        if selected_display and selected_display in bom_id_map:
            return int(bom_id_map[selected_display])
    
    with col2:
        # Quick stats
        st.markdown("**Quick Stats**")
        total_boms = len(bom_options)
        boms_with_issues = len(bom_options[bom_options['high_variance_count'] > 0])
        st.caption(f"📊 {total_boms} BOMs available")
        st.caption(f"⚠️ {boms_with_issues} with variance issues")
    
    return None


# ==================== BOM Summary Header ====================

def render_bom_summary_header(bom_info: pd.Series, bom_materials: pd.DataFrame):
    """Render summary header for selected BOM"""
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"**📦 {bom_info['bom_code']}**")
        st.caption(bom_info['bom_name'])
    
    with col2:
        st.metric(
            "Type",
            bom_info['bom_type'],
            help="BOM Type"
        )
    
    with col3:
        st.metric(
            "Materials",
            int(bom_info['material_count']),
            delta=f"{int(bom_info['high_variance_count'])} issues",
            delta_color="inverse" if bom_info['high_variance_count'] > 0 else "off"
        )
    
    with col4:
        avg_var = bom_info['avg_variance']
        st.metric(
            "Avg Variance",
            f"{avg_var:.1f}%" if pd.notna(avg_var) else "N/A",
            delta=f"{int(bom_info['mo_count'])} MOs",
            delta_color="off"
        )
    
    # Output product info
    st.caption(f"🎯 Output: {bom_info['output_product_code']} - {bom_info['output_product_name']}")


# ==================== Material Breakdown ====================

def render_material_breakdown(bom_materials: pd.DataFrame):
    """Render material-by-material variance breakdown"""
    
    st.markdown("##### 🧪 Material Breakdown")
    
    if bom_materials.empty:
        st.info("No materials found for this BOM.")
        return
    
    # Check for new columns
    has_new_columns = 'mo_count_pure' in bom_materials.columns
    
    # Prepare display dataframe
    display_cols = [
        'material_code', 'material_name', 'material_type',
        'theoretical_qty_with_scrap', 'actual_avg_per_unit',
        'variance_pct', 'cv_percent'
    ]
    
    if has_new_columns:
        display_cols.extend(['mo_count_pure', 'mo_count_mixed', 'is_alternative'])
    else:
        display_cols.extend(['mo_count', 'is_alternative'])
    
    display_cols = [c for c in display_cols if c in bom_materials.columns]
    display_df = bom_materials[display_cols].copy()
    
    # Format columns
    display_df['Source'] = display_df['is_alternative'].apply(
        lambda x: '🔄 Alt' if x == 1 else '📦 Pri'
    )
    
    display_df['Theory'] = display_df['theoretical_qty_with_scrap'].apply(
        lambda x: f"{x:.4f}" if pd.notna(x) else "N/A"
    )
    
    display_df['Actual'] = display_df['actual_avg_per_unit'].apply(
        lambda x: f"{x:.4f}" if pd.notna(x) else "N/A"
    )
    
    display_df['Variance'] = display_df['variance_pct'].apply(format_variance_display)
    
    display_df['CV%'] = display_df['cv_percent'].apply(
        lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A"
    )
    
    if has_new_columns:
        display_df['MOs'] = display_df.apply(
            lambda row: f"{int(row['mo_count_pure'])}p" + 
                       (f"+{int(row['mo_count_mixed'])}m" if row['mo_count_mixed'] > 0 else ""),
            axis=1
        )
    else:
        display_df['MOs'] = display_df['mo_count'].astype(int).astype(str)
    
    # Select final columns
    final_cols = ['material_code', 'material_name', 'Source', 'material_type', 
                  'Theory', 'Actual', 'Variance', 'MOs', 'CV%']
    final_cols = [c for c in final_cols if c in display_df.columns]
    
    column_config = {
        'material_code': st.column_config.TextColumn('Code', width='small'),
        'material_name': st.column_config.TextColumn('Name', width='medium'),
        'Source': st.column_config.TextColumn('Source', width='small'),
        'material_type': st.column_config.TextColumn('Type', width='small'),
        'Theory': st.column_config.TextColumn('Theory', width='small'),
        'Actual': st.column_config.TextColumn('Actual', width='small'),
        'Variance': st.column_config.TextColumn('Variance', width='small'),
        'MOs': st.column_config.TextColumn('MOs', width='small'),
        'CV%': st.column_config.TextColumn('CV%', width='small'),
    }
    
    # Sort by absolute variance
    display_df['abs_var'] = display_df['variance_pct'].abs()
    display_df = display_df.sort_values('abs_var', ascending=False)
    
    st.dataframe(
        display_df[final_cols],
        use_container_width=True,
        hide_index=True,
        column_config=column_config
    )
    
    # Legend
    st.caption("""
    📝 **Legend:** Source (📦 Pri = Primary, 🔄 Alt = Alternative) | 
    Theory = Qty per output with scrap | Actual = Avg consumption per output |
    MOs = Xp+Ym (pure + mixed) | CV% = Consistency (lower = better)
    """)


# ==================== Detailed Analysis Section ====================

def render_detailed_analysis(bom_materials: pd.DataFrame, bom_id: int, analyzer):
    """Render detailed analysis with material selector and charts"""
    
    st.markdown("##### 📈 Detailed Analysis")
    
    # Material selector
    material_options = get_material_options(bom_materials)
    
    if not material_options:
        st.info("No materials available for detailed analysis.")
        return
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        display_list = [opt['display'] for opt in material_options]
        selected_display = st.selectbox(
            "Select Material for Details",
            options=display_list,
            index=0,
            key="detail_material_selector"
        )
        
        # Find selected material
        selected_material = None
        for opt in material_options:
            if opt['display'] == selected_display:
                selected_material = opt
                break
    
    with col2:
        chart_type = st.radio(
            "Chart Type",
            options=["Trend", "Distribution"],
            horizontal=True,
            key="detail_chart_type"
        )
    
    if selected_material is None:
        return
    
    material_id = selected_material['material_id']
    material_row = bom_materials[bom_materials['material_id'] == material_id].iloc[0]
    
    st.markdown("---")
    
    # Two columns: Chart + Stats
    col_chart, col_stats = st.columns([2, 1])
    
    with col_chart:
        if chart_type == "Trend":
            render_consumption_trend_chart(bom_id, material_id, material_row, analyzer)
        else:
            render_consumption_distribution_chart(bom_id, material_id, material_row, analyzer)
    
    with col_stats:
        render_material_stats_card(material_row)
    
    # MO History Table
    st.markdown("---")
    render_mo_history_table(bom_id, material_id, analyzer)
    
    # Alternative Usage Section
    render_alternative_usage_section(bom_materials, bom_id, analyzer)


# ==================== Charts ====================

def render_consumption_trend_chart(
    bom_id: int, 
    material_id: int, 
    material_row: pd.Series,
    analyzer
):
    """Render consumption trend chart over time"""
    
    st.markdown("**📈 Consumption Trend**")
    
    # Get MO detail data
    if analyzer is None:
        st.info("ℹ️ Analyzer not available for trend data.")
        return
    
    try:
        config = get_config()
        mo_data = analyzer.queries.get_mo_consumption_detail(
            bom_id=bom_id,
            material_id=material_id,
            date_from=config.date_from,
            date_to=config.date_to
        )
    except Exception as e:
        st.error(f"Error loading MO data: {e}")
        return
    
    if mo_data.empty:
        st.info("ℹ️ No MO consumption data available for this material.")
        return
    
    # Prepare data for chart
    mo_data = mo_data.sort_values('completion_date')
    theoretical = material_row.get('theoretical_qty_with_scrap', 0)
    
    try:
        import plotly.graph_objects as go
        
        fig = go.Figure()
        
        # Actual consumption line
        fig.add_trace(go.Scatter(
            x=mo_data['completion_date'],
            y=mo_data['consumption_per_unit'],
            mode='lines+markers',
            name='Actual',
            line=dict(color='#3498db', width=2),
            marker=dict(size=8),
            hovertemplate='<b>%{x}</b><br>Actual: %{y:.4f}<extra></extra>'
        ))
        
        # Theoretical line
        fig.add_hline(
            y=theoretical,
            line_dash="dash",
            line_color="#2ecc71",
            annotation_text=f"BOM: {theoretical:.4f}",
            annotation_position="top right"
        )
        
        # Threshold lines
        threshold_upper = theoretical * 1.05  # +5%
        threshold_lower = theoretical * 0.95  # -5%
        
        fig.add_hrect(
            y0=threshold_lower, y1=threshold_upper,
            fillcolor="#2ecc71", opacity=0.1,
            line_width=0,
            annotation_text="±5%",
            annotation_position="top left"
        )
        
        fig.update_layout(
            title=None,
            xaxis_title="Completion Date",
            yaxis_title="Consumption per Unit",
            height=300,
            margin=dict(l=20, r=20, t=20, b=40),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except ImportError:
        # Fallback to simple line chart
        chart_data = mo_data[['completion_date', 'consumption_per_unit']].set_index('completion_date')
        st.line_chart(chart_data)
        st.caption(f"BOM Theoretical: {theoretical:.4f}")


def render_consumption_distribution_chart(
    bom_id: int,
    material_id: int,
    material_row: pd.Series,
    analyzer
):
    """Render consumption distribution histogram"""
    
    st.markdown("**📊 Consumption Distribution**")
    
    if analyzer is None:
        st.info("ℹ️ Analyzer not available for distribution data.")
        return
    
    try:
        config = get_config()
        mo_data = analyzer.queries.get_mo_consumption_detail(
            bom_id=bom_id,
            material_id=material_id,
            date_from=config.date_from,
            date_to=config.date_to
        )
    except Exception as e:
        st.error(f"Error loading MO data: {e}")
        return
    
    if mo_data.empty:
        st.info("ℹ️ No MO consumption data available for this material.")
        return
    
    consumption_values = mo_data['consumption_per_unit'].dropna()
    theoretical = material_row.get('theoretical_qty_with_scrap', 0)
    
    try:
        import plotly.graph_objects as go
        
        fig = go.Figure()
        
        # Histogram
        fig.add_trace(go.Histogram(
            x=consumption_values,
            nbinsx=15,
            name='Distribution',
            marker_color='#3498db',
            opacity=0.7
        ))
        
        # Theoretical line
        fig.add_vline(
            x=theoretical,
            line_dash="dash",
            line_color="#2ecc71",
            annotation_text=f"BOM: {theoretical:.4f}",
            annotation_position="top"
        )
        
        # Mean line
        mean_val = consumption_values.mean()
        fig.add_vline(
            x=mean_val,
            line_dash="dot",
            line_color="#e74c3c",
            annotation_text=f"Mean: {mean_val:.4f}",
            annotation_position="bottom"
        )
        
        fig.update_layout(
            title=None,
            xaxis_title="Consumption per Unit",
            yaxis_title="Frequency",
            height=300,
            margin=dict(l=20, r=20, t=20, b=40),
            showlegend=False
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except ImportError:
        # Fallback
        st.bar_chart(consumption_values.value_counts().sort_index())


# ==================== Stats Card ====================

def render_material_stats_card(material_row: pd.Series):
    """Render statistics card for selected material"""
    
    st.markdown("**📋 Statistics**")
    
    # Basic info
    st.markdown(f"**{material_row['material_code']}**")
    st.caption(material_row['material_name'])
    
    st.markdown("---")
    
    # Theoretical vs Actual
    theoretical = material_row.get('theoretical_qty_with_scrap', 0)
    actual = material_row.get('actual_avg_per_unit', 0)
    variance = material_row.get('variance_pct', 0)
    
    st.markdown("**BOM Theoretical:**")
    st.code(f"{theoretical:.4f}")
    
    st.markdown("**Actual Average:**")
    st.code(f"{actual:.4f}")
    
    st.markdown("**Variance:**")
    var_color = "green" if abs(variance) <= 5 else ("orange" if abs(variance) <= 10 else "red")
    st.markdown(f":{var_color}[{format_variance_display(variance)}]")
    
    st.markdown("---")
    
    # Additional stats
    cv = material_row.get('cv_percent', 0)
    cv_status = '⚠️ High variability' if cv > 15 else '✅ Consistent'
    st.caption(f"CV: {cv:.1f}% {cv_status}")
    
    scrap_rate = material_row.get('scrap_rate', 0)
    st.caption(f"Scrap Rate: {scrap_rate:.2f}%")
    
    # MO counts
    if 'mo_count_pure' in material_row:
        pure = int(material_row['mo_count_pure'])
        mixed = int(material_row.get('mo_count_mixed', 0))
        st.caption(f"MOs: {pure} pure + {mixed} mixed")
    else:
        mo_count = int(material_row.get('mo_count', 0))
        st.caption(f"MOs: {mo_count}")


# ==================== MO History Table ====================

def render_mo_history_table(bom_id: int, material_id: int, analyzer):
    """Render per-MO consumption history table"""
    
    with st.expander("📜 MO Consumption History", expanded=False):
        if analyzer is None:
            st.info("ℹ️ Analyzer not available for MO history.")
            return
        
        try:
            config = get_config()
            mo_data = analyzer.queries.get_mo_consumption_detail(
                bom_id=bom_id,
                material_id=material_id,
                date_from=config.date_from,
                date_to=config.date_to
            )
        except Exception as e:
            st.error(f"Error loading MO history: {e}")
            return
        
        if mo_data.empty:
            st.info("ℹ️ No MO history available for this material.")
            return
        
        # Prepare display
        display_df = mo_data[[
            'order_no', 'completion_date', 'produced_qty',
            'gross_issued', 'returned_qty', 'net_consumed', 'consumption_per_unit'
        ]].copy()
        
        display_df['completion_date'] = pd.to_datetime(display_df['completion_date']).dt.strftime('%Y-%m-%d')
        display_df['gross_issued'] = display_df['gross_issued'].apply(lambda x: f"{x:.4f}")
        display_df['returned_qty'] = display_df['returned_qty'].apply(lambda x: f"{x:.4f}")
        display_df['net_consumed'] = display_df['net_consumed'].apply(lambda x: f"{x:.4f}")
        display_df['consumption_per_unit'] = display_df['consumption_per_unit'].apply(lambda x: f"{x:.4f}")
        
        st.dataframe(
            display_df.rename(columns={
                'order_no': 'MO#',
                'completion_date': 'Completed',
                'produced_qty': 'Produced',
                'gross_issued': 'Issued',
                'returned_qty': 'Returned',
                'net_consumed': 'Net Used',
                'consumption_per_unit': 'Per Unit'
            }),
            use_container_width=True,
            hide_index=True
        )
        
        st.caption(f"📊 Showing {len(mo_data)} MOs | Net Used = Issued - Returned")


# ==================== Alternative Material Usage ====================

def render_alternative_usage_section(bom_materials: pd.DataFrame, bom_id: int, analyzer):
    """Render alternative material usage analysis"""
    
    # Check if there are alternatives
    has_alternatives = 'is_alternative' in bom_materials.columns and bom_materials['is_alternative'].sum() > 0
    
    if not has_alternatives:
        return
    
    with st.expander("🔄 Alternative Material Usage", expanded=False):
        # Get primary and alternative pairs
        primary_materials = bom_materials[bom_materials['is_alternative'] == 0]
        alt_materials = bom_materials[bom_materials['is_alternative'] == 1]
        
        if alt_materials.empty:
            st.info("ℹ️ No alternative materials used in this BOM.")
            return
        
        st.markdown("**Alternative Materials Used:**")
        
        for _, alt_row in alt_materials.iterrows():
            primary_id = alt_row.get('primary_material_id')
            
            # Find corresponding primary
            primary_row = primary_materials[primary_materials['material_id'] == primary_id]
            
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                if not primary_row.empty:
                    p = primary_row.iloc[0]
                    st.markdown(f"📦 **Primary:** {p['material_code']}")
                    st.caption(f"Theory: {p.get('theoretical_qty_with_scrap', 0):.4f}")
                else:
                    st.markdown("📦 **Primary:** N/A")
            
            with col2:
                st.markdown(f"🔄 **Alternative:** {alt_row['material_code']}")
                st.caption(f"Theory: {alt_row.get('theoretical_qty_with_scrap', 0):.4f}")
            
            with col3:
                variance = alt_row.get('variance_pct', 0)
                st.markdown(format_variance_display(variance))
            
            st.markdown("---")
        
        # Summary stats
        total_alt = len(alt_materials)
        alt_with_issues = len(alt_materials[alt_materials['has_high_variance'] == True])
        st.caption(f"📊 {total_alt} alternatives | {alt_with_issues} with variance issues")