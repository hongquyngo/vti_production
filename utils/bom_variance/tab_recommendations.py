# utils/bom_variance/tab_recommendations.py
"""
BOM Variance - Tab 3: Recommendations - VERSION 2.0

Phase 3 Implementation - Contains:
- List of materials needing adjustment (filterable)
- Suggested quantity and scrap rate changes
- Side-by-side comparison (Current vs Suggested)
- Bulk selection for applying changes
- Export recommendations to Excel
- Preview before applying changes (for Phase 4)
"""

import streamlit as st
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from io import BytesIO

from .config import (
    get_config,
    format_variance_display,
    format_bom_display,
    format_bom_display_full,
    create_bom_options_from_df,
    MATERIAL_TYPES,
    BOM_TYPES,
    ApplyMode
)
from . import actions

logger = logging.getLogger(__name__)


# ==================== Data Preparation ====================

def get_recommendations_data(full_data: pd.DataFrame, analyzer) -> pd.DataFrame:
    """
    Prepare recommendations data with calculated suggestions
    
    Args:
        full_data: Full variance DataFrame
        analyzer: VarianceAnalyzer instance
        
    Returns:
        DataFrame with recommendation columns added
    """
    if full_data.empty:
        return pd.DataFrame()
    
    # Filter to high variance items only
    high_variance = full_data[full_data['has_high_variance'] == True].copy()
    
    if high_variance.empty:
        return pd.DataFrame()
    
    # Calculate suggestions for each material
    recommendations = []
    
    for _, row in high_variance.iterrows():
        rec = row.to_dict()
        
        # Calculate suggestion using analyzer
        suggestion = analyzer.calculate_suggestion(
            theoretical_qty=row.get('theoretical_qty', 0),
            theoretical_qty_with_scrap=row.get('theoretical_qty_with_scrap', 0),
            actual_avg=row.get('actual_avg_per_unit', 0),
            current_scrap_rate=row.get('scrap_rate', 0),
            bom_output_qty=row.get('bom_output_qty', 1)
        )
        
        rec['suggestion'] = suggestion
        rec['has_suggestion'] = suggestion.get('has_suggestion', False)
        
        if suggestion.get('has_suggestion', False):
            # Option 1: Adjust quantity
            rec['suggested_qty'] = suggestion['option_adjust_quantity']['quantity']
            rec['current_qty'] = suggestion['current']['quantity']
            rec['qty_change'] = rec['suggested_qty'] - rec['current_qty']
            rec['qty_change_pct'] = (rec['qty_change'] / rec['current_qty'] * 100) if rec['current_qty'] > 0 else 0
            
            # Option 2: Adjust scrap rate
            rec['suggested_scrap'] = suggestion['option_adjust_scrap']['scrap_rate']
            rec['current_scrap'] = suggestion['current']['scrap_rate']
            rec['scrap_change'] = rec['suggested_scrap'] - rec['current_scrap']
        else:
            rec['suggested_qty'] = row.get('bom_quantity', 0)
            rec['current_qty'] = row.get('bom_quantity', 0)
            rec['qty_change'] = 0
            rec['qty_change_pct'] = 0
            rec['suggested_scrap'] = row.get('scrap_rate', 0)
            rec['current_scrap'] = row.get('scrap_rate', 0)
            rec['scrap_change'] = 0
        
        recommendations.append(rec)
    
    return pd.DataFrame(recommendations)


def filter_recommendations(
    df: pd.DataFrame,
    bom_filter: List[str] = None,
    material_type_filter: List[str] = None,
    adjustment_type: str = 'All'
) -> pd.DataFrame:
    """Apply filters to recommendations"""
    if df.empty:
        return df
    
    filtered = df.copy()
    
    # BOM filter
    if bom_filter:
        filtered = filtered[filtered['bom_code'].isin(bom_filter)]
    
    # Material type filter
    if material_type_filter:
        filtered = filtered[filtered['material_type'].isin(material_type_filter)]
    
    # Adjustment type filter
    if adjustment_type == 'Increase Qty':
        filtered = filtered[filtered['qty_change'] > 0]
    elif adjustment_type == 'Decrease Qty':
        filtered = filtered[filtered['qty_change'] < 0]
    elif adjustment_type == 'Increase Scrap':
        filtered = filtered[filtered['scrap_change'] > 0]
    elif adjustment_type == 'Decrease Scrap':
        filtered = filtered[filtered['scrap_change'] < 0]
    
    return filtered


# ==================== Main Render Function ====================

def render(full_data: pd.DataFrame, analyzer) -> None:
    """
    Main render function for Recommendations tab
    
    Args:
        full_data: Full variance DataFrame
        analyzer: VarianceAnalyzer instance
    """
    st.subheader("💡 Recommendations")
    
    if full_data.empty:
        st.warning("⚠️ No data available for recommendations.")
        return
    
    # Get recommendations data
    recommendations = get_recommendations_data(full_data, analyzer)
    
    if recommendations.empty:
        st.success("✅ No materials found with variance above threshold. BOMs are performing well!")
        render_summary_stats(full_data)
        return
    
    # ==================== Summary Stats ====================
    render_summary_header(recommendations)
    
    st.markdown("---")
    
    # ==================== Filters ====================
    filtered_recommendations = render_filters(recommendations)
    
    st.markdown("---")
    
    # ==================== Recommendations Table ====================
    selected_items = render_recommendations_table(filtered_recommendations)
    
    st.markdown("---")
    
    # ==================== Actions Section ====================
    render_actions_section(selected_items, filtered_recommendations)


# ==================== Summary Header ====================

def render_summary_header(recommendations: pd.DataFrame):
    """Render summary statistics header"""
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_items = len(recommendations)
    total_boms = recommendations['bom_header_id'].nunique()
    
    # Count by direction
    increase_qty = len(recommendations[recommendations['qty_change'] > 0])
    decrease_qty = len(recommendations[recommendations['qty_change'] < 0])
    
    with col1:
        st.metric(
            "📋 Total Recommendations",
            total_items,
            help="Materials needing adjustment"
        )
    
    with col2:
        st.metric(
            "📦 BOMs Affected",
            total_boms,
            help="Number of BOMs with materials needing review"
        )
    
    with col3:
        st.metric(
            "📈 Increase Qty",
            increase_qty,
            delta=f"{increase_qty/total_items*100:.0f}%" if total_items > 0 else "0%",
            delta_color="off",
            help="Materials where actual > BOM (need more)"
        )
    
    with col4:
        st.metric(
            "📉 Decrease Qty",
            decrease_qty,
            delta=f"{decrease_qty/total_items*100:.0f}%" if total_items > 0 else "0%",
            delta_color="off",
            help="Materials where actual < BOM (need less)"
        )


def render_summary_stats(full_data: pd.DataFrame):
    """Render summary when no recommendations"""
    
    st.markdown("### 📊 Current Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("BOMs Analyzed", full_data['bom_header_id'].nunique())
    
    with col2:
        st.metric("Materials Tracked", len(full_data))
    
    with col3:
        avg_var = full_data['variance_pct'].abs().mean()
        st.metric("Avg Variance", f"{avg_var:.1f}%")


# ==================== Filters Section ====================

def get_bom_summary_for_filter(recommendations: pd.DataFrame) -> pd.DataFrame:
    """Aggregate BOM stats for filter dropdown"""
    if recommendations.empty:
        return pd.DataFrame()
    
    # Group by BOM to get stats
    bom_agg = recommendations.groupby('bom_header_id').agg({
        'bom_code': 'first',
        'bom_name': 'first',
        'bom_type': 'first',
        'output_product_code': 'first' if 'output_product_code' in recommendations.columns else lambda x: None,
        'material_id': 'count',  # material_count
        'variance_pct': lambda x: (x.abs() > get_config().variance_threshold).sum()  # high_variance_count
    }).reset_index()
    
    bom_agg.columns = [
        'bom_header_id', 'bom_code', 'bom_name', 'bom_type', 
        'output_product_code', 'material_count', 'high_variance_count'
    ]
    
    # Add mo_count if available
    if 'mo_count' in recommendations.columns:
        mo_counts = recommendations.groupby('bom_header_id')['mo_count'].first().reset_index()
        bom_agg = bom_agg.merge(mo_counts, on='bom_header_id', how='left')
    else:
        bom_agg['mo_count'] = 0
    
    return bom_agg.sort_values('high_variance_count', ascending=False)


def render_filters(recommendations: pd.DataFrame) -> pd.DataFrame:
    """Render filter controls and return filtered data"""
    
    with st.expander("🔍 Filter Recommendations", expanded=False):
        # BOM filter gets more space (3:1:1 ratio)
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            # BOM filter with full display format
            bom_summary = get_bom_summary_for_filter(recommendations)
            bom_options, bom_id_map = create_bom_options_from_df(bom_summary, include_stats=True)
            
            selected_bom_displays = st.multiselect(
                "Filter by BOM",
                options=bom_options,
                default=[],
                placeholder="All BOMs",
                key="rec_bom_filter"
            )
            
            # Convert selected displays back to bom_codes
            selected_boms = []
            if selected_bom_displays:
                for display in selected_bom_displays:
                    bom_id = bom_id_map.get(display)
                    if bom_id:
                        # Find bom_code from bom_id
                        match = bom_summary[bom_summary['bom_header_id'] == bom_id]
                        if not match.empty:
                            selected_boms.append(match.iloc[0]['bom_code'])
        
        with col2:
            # Material type filter
            mat_type_options = [t for t in MATERIAL_TYPES if t in recommendations['material_type'].values]
            selected_mat_types = st.multiselect(
                "Material Type",
                options=mat_type_options,
                default=[],
                placeholder="All types",
                key="rec_mat_type_filter"
            )
        
        with col3:
            # Adjustment direction filter
            adjustment_options = ['All', 'Increase Qty', 'Decrease Qty', 'Increase Scrap', 'Decrease Scrap']
            selected_adjustment = st.selectbox(
                "Adjustment Type",
                options=adjustment_options,
                index=0,
                key="rec_adjustment_filter"
            )
    
    # Apply filters
    filtered = filter_recommendations(
        recommendations,
        bom_filter=selected_boms if selected_boms else None,
        material_type_filter=selected_mat_types if selected_mat_types else None,
        adjustment_type=selected_adjustment
    )
    
    # Show filter summary
    if len(filtered) < len(recommendations):
        st.info(f"📊 Showing **{len(filtered)}** of **{len(recommendations)}** recommendations")
    
    return filtered


# ==================== Recommendations Table ====================

def render_recommendations_table(recommendations: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Render recommendations table with selection checkboxes
    
    Returns:
        List of selected recommendation dictionaries
    """
    st.markdown("##### 📋 Recommendations List")
    
    if recommendations.empty:
        st.info("No recommendations match the current filters.")
        return []
    
    # Initialize selection state
    if 'selected_recommendations' not in st.session_state:
        st.session_state['selected_recommendations'] = set()
    
    # Adjustment method selector
    col1, col2 = st.columns([2, 1])
    
    with col1:
        adjustment_method = st.radio(
            "Preferred Adjustment Method",
            options=["Adjust Quantity", "Adjust Scrap Rate"],
            horizontal=True,
            key="adjustment_method",
            help="Choose how to adjust BOM values"
        )
    
    with col2:
        # Select all / Clear all
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("☑️ Select All", use_container_width=True, key="select_all"):
                for _, row in recommendations.iterrows():
                    key = f"{row['bom_header_id']}_{row['material_id']}"
                    st.session_state['selected_recommendations'].add(key)
                st.rerun()
        with btn_col2:
            if st.button("⬜ Clear All", use_container_width=True, key="clear_all"):
                st.session_state['selected_recommendations'] = set()
                st.rerun()
    
    st.markdown("---")
    
    # Render table with checkboxes
    selected_items = []
    
    # Group by BOM for better organization
    for bom_code in sorted(recommendations['bom_code'].unique()):
        bom_data = recommendations[recommendations['bom_code'] == bom_code]
        bom_info = bom_data.iloc[0]
        
        # BOM header
        with st.container():
            st.markdown(f"**📦 {bom_code}** - {bom_info.get('bom_name', '')} [{bom_info.get('bom_type', '')}]")
            
            # Materials table for this BOM
            for _, row in bom_data.iterrows():
                item_key = f"{row['bom_header_id']}_{row['material_id']}"
                is_selected = item_key in st.session_state['selected_recommendations']
                
                col_select, col_material, col_current, col_arrow, col_suggested, col_impact = st.columns([0.5, 2, 1.5, 0.3, 1.5, 1.2])
                
                with col_select:
                    if st.checkbox("Select", value=is_selected, key=f"chk_{item_key}", label_visibility="collapsed"):
                        st.session_state['selected_recommendations'].add(item_key)
                        is_selected = True
                    else:
                        st.session_state['selected_recommendations'].discard(item_key)
                        is_selected = False
                
                with col_material:
                    source = '🔄' if row.get('is_alternative', 0) == 1 else '📦'
                    st.markdown(f"{source} **{row['material_code']}**")
                    st.caption(f"{row['material_name'][:30]}..." if len(str(row.get('material_name', ''))) > 30 else row.get('material_name', ''))
                
                with col_current:
                    if adjustment_method == "Adjust Quantity":
                        st.markdown("**Current:**")
                        st.code(f"Qty: {row['current_qty']:.4f}")
                    else:
                        st.markdown("**Current:**")
                        st.code(f"Scrap: {row['current_scrap']:.2f}%")
                
                with col_arrow:
                    st.markdown("<br>→", unsafe_allow_html=True)
                
                with col_suggested:
                    if adjustment_method == "Adjust Quantity":
                        st.markdown("**Suggested:**")
                        change = row['qty_change']
                        color = "green" if change < 0 else "red"
                        st.code(f"Qty: {row['suggested_qty']:.4f}")
                    else:
                        st.markdown("**Suggested:**")
                        change = row['scrap_change']
                        color = "red" if change > 0 else "green"
                        st.code(f"Scrap: {row['suggested_scrap']:.2f}%")
                
                with col_impact:
                    variance = row.get('variance_pct', 0)
                    st.markdown("**Variance:**")
                    st.markdown(format_variance_display(variance))
                
                # Add to selected items if checked
                if is_selected:
                    selected_items.append({
                        'bom_header_id': row['bom_header_id'],
                        'bom_code': row['bom_code'],
                        'bom_detail_id': row.get('bom_detail_id'),
                        'material_id': row['material_id'],
                        'material_code': row['material_code'],
                        'is_alternative': row.get('is_alternative', 0),
                        'current_qty': row['current_qty'],
                        'suggested_qty': row['suggested_qty'],
                        'current_scrap': row['current_scrap'],
                        'suggested_scrap': row['suggested_scrap'],
                        'adjustment_method': adjustment_method,
                        'variance_pct': row.get('variance_pct', 0)
                    })
            
            st.markdown("---")
    
    # Selection summary
    st.caption(f"✅ **{len(selected_items)}** items selected")
    
    return selected_items


# ==================== Actions Section ====================

def render_actions_section(selected_items: List[Dict], recommendations: pd.DataFrame):
    """Render action buttons and apply dialog"""
    
    st.markdown("##### ⚡ Actions")
    
    # Initialize apply state
    if 'show_apply_dialog' not in st.session_state:
        st.session_state['show_apply_dialog'] = False
    if 'apply_results' not in st.session_state:
        st.session_state['apply_results'] = None
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Export to Excel
        excel_data = export_recommendations_excel(recommendations)
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"bom_variance_recommendations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    with col2:
        # Review & Apply button
        if selected_items:
            if st.button("📋 Review & Apply", use_container_width=True, type="primary"):
                st.session_state['show_apply_dialog'] = True
        else:
            st.button("📋 Review & Apply", use_container_width=True, type="primary", disabled=True,
                     help="Select items first")
    
    # Show apply dialog
    if st.session_state['show_apply_dialog'] and selected_items:
        render_apply_dialog(selected_items)
    
    # Show results if available
    if st.session_state['apply_results']:
        render_apply_results(st.session_state['apply_results'])


def render_apply_dialog(selected_items: List[Dict]):
    """Render apply dialog with mode selection and confirmation"""
    
    st.markdown("---")
    st.markdown("### 📋 Apply Recommendations")
    
    # Group by BOM
    bom_groups = {}
    for item in selected_items:
        bom_id = item['bom_header_id']
        bom_code = item['bom_code']
        if bom_id not in bom_groups:
            bom_groups[bom_id] = {
                'bom_code': bom_code,
                'items': [],
                'can_direct_update': None,
                'update_reason': None
            }
        bom_groups[bom_id]['items'].append(item)
    
    # Check direct update eligibility for each BOM
    for bom_id, group in bom_groups.items():
        can_update, reason, _ = actions.can_direct_update(bom_id)
        group['can_direct_update'] = can_update
        group['update_reason'] = reason
    
    # Summary
    st.info(f"📊 **{len(selected_items)}** materials across **{len(bom_groups)}** BOMs")
    
    # Apply mode selection
    col1, col2 = st.columns(2)
    
    with col1:
        apply_mode = st.radio(
            "Apply Mode",
            options=["Clone BOM (Recommended)", "Direct Update"],
            index=0,
            key="apply_mode_selector",
            help="Clone creates new DRAFT BOM. Direct Update modifies existing BOM."
        )
    
    with col2:
        adjustment_method = st.session_state.get('adjustment_method', 'Adjust Quantity')
        st.markdown(f"**Adjustment Method:** {adjustment_method}")
    
    # Show BOM eligibility
    st.markdown("---")
    st.markdown("**BOM Status:**")
    
    all_can_direct = True
    for bom_id, group in bom_groups.items():
        status_icon = "✅" if group['can_direct_update'] else "⚠️"
        direct_status = "Can direct update" if group['can_direct_update'] else group['update_reason']
        
        if not group['can_direct_update']:
            all_can_direct = False
        
        st.markdown(f"{status_icon} **{group['bom_code']}**: {len(group['items'])} materials - {direct_status}")
    
    # Warning for direct update
    if apply_mode == "Direct Update" and not all_can_direct:
        st.warning("⚠️ Some BOMs cannot be directly updated. Only eligible BOMs will be updated, others will be skipped.")
    
    # Preview changes
    with st.expander("📝 Preview Changes", expanded=True):
        for bom_id, group in bom_groups.items():
            st.markdown(f"**{group['bom_code']}**")
            
            preview_data = []
            for item in group['items']:
                adj_method = item.get('adjustment_method', adjustment_method)
                if adj_method == "Adjust Quantity":
                    preview_data.append({
                        'Material': item['material_code'],
                        'Type': 'Qty',
                        'Current': f"{item['current_qty']:.4f}",
                        'New': f"{item['suggested_qty']:.4f}",
                        'Change': f"{item['suggested_qty'] - item['current_qty']:+.4f}"
                    })
                else:
                    preview_data.append({
                        'Material': item['material_code'],
                        'Type': 'Scrap',
                        'Current': f"{item['current_scrap']:.2f}%",
                        'New': f"{item['suggested_scrap']:.2f}%",
                        'Change': f"{item['suggested_scrap'] - item['current_scrap']:+.2f}%"
                    })
            
            st.dataframe(pd.DataFrame(preview_data), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state['show_apply_dialog'] = False
            st.rerun()
    
    with col3:
        confirm_text = "🚀 Clone BOMs" if "Clone" in apply_mode else "🔄 Update BOMs"
        if st.button(confirm_text, use_container_width=True, type="primary"):
            # Execute apply
            mode = ApplyMode.CLONE if "Clone" in apply_mode else ApplyMode.DIRECT_UPDATE
            adjustment_method = st.session_state.get('adjustment_method', 'Adjust Quantity')
            
            results = execute_apply(bom_groups, mode, adjustment_method)
            st.session_state['apply_results'] = results
            st.session_state['show_apply_dialog'] = False
            st.rerun()


def execute_apply(
    bom_groups: Dict[int, Dict],
    mode: ApplyMode,
    adjustment_method: str
) -> Dict[str, Any]:
    """Execute the apply operation"""
    
    results = {
        'mode': mode.value,
        'total_boms': len(bom_groups),
        'successful': [],
        'failed': [],
        'skipped': []
    }
    
    for bom_id, group in bom_groups.items():
        bom_code = group['bom_code']
        
        # Check eligibility for direct update
        if mode == ApplyMode.DIRECT_UPDATE and not group['can_direct_update']:
            results['skipped'].append({
                'bom_id': bom_id,
                'bom_code': bom_code,
                'reason': group['update_reason']
            })
            continue
        
        # Prepare adjustments
        adjustments = []
        for item in group['items']:
            adj = {
                'material_id': item['material_id'],
                'is_alternative': item.get('is_alternative', 0)
            }
            
            if adjustment_method == "Adjust Quantity":
                adj['new_quantity'] = item.get('suggested_qty')
            else:
                adj['new_scrap_rate'] = item.get('suggested_scrap')
            
            adjustments.append(adj)
        
        # Apply
        try:
            result = actions.apply_bulk_recommendations(
                bom_id=bom_id,
                adjustments=adjustments,
                mode=mode,
                applied_by=st.session_state.get('user_id', 1)
            )
            
            if result.success:
                results['successful'].append({
                    'bom_id': bom_id,
                    'bom_code': bom_code,
                    'new_bom_id': result.new_bom_id,
                    'new_bom_code': result.new_bom_code,
                    'changes_count': len(result.changes_applied),
                    'message': result.message
                })
            else:
                results['failed'].append({
                    'bom_id': bom_id,
                    'bom_code': bom_code,
                    'error': result.message
                })
                
        except Exception as e:
            logger.error(f"Error applying to BOM {bom_code}: {e}")
            results['failed'].append({
                'bom_id': bom_id,
                'bom_code': bom_code,
                'error': str(e)
            })
    
    return results


def render_apply_results(results: Dict[str, Any]):
    """Render results of apply operation"""
    
    st.markdown("---")
    st.markdown("### 📊 Apply Results")
    
    mode_display = "Clone" if results['mode'] == 'clone' else "Direct Update"
    
    # Summary
    success_count = len(results['successful'])
    failed_count = len(results['failed'])
    skipped_count = len(results['skipped'])
    total = success_count + failed_count + skipped_count
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Mode", mode_display)
    with col2:
        st.metric("✅ Success", success_count)
    with col3:
        st.metric("❌ Failed", failed_count)
    with col4:
        st.metric("⏭️ Skipped", skipped_count)
    
    # Success details
    if results['successful']:
        st.success(f"✅ Successfully processed {success_count} BOMs")
        
        with st.expander("📋 Success Details", expanded=True):
            for item in results['successful']:
                if results['mode'] == 'clone':
                    st.markdown(f"✅ **{item['bom_code']}** → Created **{item['new_bom_code']}** (ID: {item['new_bom_id']}) with {item['changes_count']} changes")
                else:
                    st.markdown(f"✅ **{item['bom_code']}** updated with {item['changes_count']} changes")
    
    # Failed details
    if results['failed']:
        st.error(f"❌ Failed to process {failed_count} BOMs")
        
        with st.expander("🚨 Error Details", expanded=True):
            for item in results['failed']:
                st.markdown(f"❌ **{item['bom_code']}**: {item['error']}")
    
    # Skipped details
    if results['skipped']:
        st.warning(f"⏭️ Skipped {skipped_count} BOMs")
        
        with st.expander("ℹ️ Skipped Details", expanded=False):
            for item in results['skipped']:
                st.markdown(f"⏭️ **{item['bom_code']}**: {item['reason']}")
    
    # Clear results button
    if st.button("🔄 Clear Results & Continue", use_container_width=True):
        st.session_state['apply_results'] = None
        st.session_state['selected_recommendations'] = set()
        st.rerun()


def render_preview_dialog(selected_items: List[Dict]):
    """Render preview of changes"""
    
    st.markdown("##### 📝 Preview of Changes")
    
    # Group by BOM
    bom_groups = {}
    for item in selected_items:
        bom_code = item['bom_code']
        if bom_code not in bom_groups:
            bom_groups[bom_code] = []
        bom_groups[bom_code].append(item)
    
    for bom_code, items in bom_groups.items():
        st.markdown(f"**{bom_code}** ({len(items)} changes)")
        
        preview_data = []
        for item in items:
            if item['adjustment_method'] == "Adjust Quantity":
                preview_data.append({
                    'Material': item['material_code'],
                    'Change Type': 'Quantity',
                    'Current': f"{item['current_qty']:.4f}",
                    'New': f"{item['suggested_qty']:.4f}",
                    'Diff': f"{item['suggested_qty'] - item['current_qty']:+.4f}"
                })
            else:
                preview_data.append({
                    'Material': item['material_code'],
                    'Change Type': 'Scrap Rate',
                    'Current': f"{item['current_scrap']:.2f}%",
                    'New': f"{item['suggested_scrap']:.2f}%",
                    'Diff': f"{item['suggested_scrap'] - item['current_scrap']:+.2f}%"
                })
        
        st.dataframe(pd.DataFrame(preview_data), use_container_width=True, hide_index=True)


# ==================== Excel Export ====================

def export_recommendations_excel(recommendations: pd.DataFrame) -> bytes:
    """
    Export recommendations to Excel file
    
    Args:
        recommendations: DataFrame with recommendations
        
    Returns:
        Excel file as bytes
    """
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Summary
        summary_data = {
            'Metric': [
                'Total Recommendations',
                'BOMs Affected',
                'Materials to Increase',
                'Materials to Decrease',
                'Average Variance %',
                'Max Variance %',
                'Report Generated'
            ],
            'Value': [
                len(recommendations),
                recommendations['bom_header_id'].nunique(),
                len(recommendations[recommendations['qty_change'] > 0]),
                len(recommendations[recommendations['qty_change'] < 0]),
                f"{recommendations['variance_pct'].abs().mean():.2f}%",
                f"{recommendations['variance_pct'].abs().max():.2f}%",
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
        
        # Sheet 2: Recommendations Detail
        export_cols = [
            'bom_code', 'bom_name', 'bom_type',
            'material_code', 'material_name', 'material_type',
            'is_alternative',
            'current_qty', 'suggested_qty', 'qty_change', 'qty_change_pct',
            'current_scrap', 'suggested_scrap', 'scrap_change',
            'theoretical_qty_with_scrap', 'actual_avg_per_unit', 'variance_pct',
            'mo_count', 'cv_percent'
        ]
        
        # Filter to existing columns
        export_cols = [c for c in export_cols if c in recommendations.columns]
        
        export_df = recommendations[export_cols].copy()
        
        # Rename columns for clarity
        column_renames = {
            'bom_code': 'BOM Code',
            'bom_name': 'BOM Name',
            'bom_type': 'BOM Type',
            'material_code': 'Material Code',
            'material_name': 'Material Name',
            'material_type': 'Material Type',
            'is_alternative': 'Is Alternative',
            'current_qty': 'Current Qty',
            'suggested_qty': 'Suggested Qty',
            'qty_change': 'Qty Change',
            'qty_change_pct': 'Qty Change %',
            'current_scrap': 'Current Scrap %',
            'suggested_scrap': 'Suggested Scrap %',
            'scrap_change': 'Scrap Change %',
            'theoretical_qty_with_scrap': 'BOM Qty (with scrap)',
            'actual_avg_per_unit': 'Actual Avg',
            'variance_pct': 'Variance %',
            'mo_count': 'MO Count',
            'cv_percent': 'CV %'
        }
        
        export_df = export_df.rename(columns=column_renames)
        export_df.to_excel(writer, sheet_name='Recommendations', index=False)
        
        # Sheet 3: By BOM Summary
        bom_summary = recommendations.groupby(['bom_code', 'bom_name', 'bom_type']).agg({
            'material_id': 'count',
            'variance_pct': 'mean',
            'qty_change': lambda x: (x > 0).sum(),
            'mo_count': 'first'
        }).reset_index()
        
        bom_summary.columns = ['BOM Code', 'BOM Name', 'Type', 'Materials to Adjust', 
                              'Avg Variance %', 'Increase Qty Count', 'MO Count']
        bom_summary.to_excel(writer, sheet_name='By BOM', index=False)
        
        # Sheet 4: Instructions
        instructions = pd.DataFrame({
            'Step': [1, 2, 3, 4, 5],
            'Action': [
                'Review the Recommendations sheet for all suggested changes',
                'Filter by BOM or Material Type as needed',
                'For each material, choose between Qty adjustment or Scrap Rate adjustment',
                'Use the BOM Variance tool to apply changes (Clone BOM recommended)',
                'After applying, monitor future MOs to verify improvement'
            ],
            'Notes': [
                'Red variance = actual > BOM (using more than expected)',
                'Blue variance = actual < BOM (using less than expected)',
                'Qty adjustment changes the BOM quantity directly',
                'Scrap adjustment changes the expected loss percentage',
                'Run variance analysis again after 5-10 MOs'
            ]
        })
        instructions.to_excel(writer, sheet_name='Instructions', index=False)
    
    output.seek(0)
    return output.getvalue()


# ==================== Comparison View ====================

def render_comparison_view(material_row: pd.Series, analyzer):
    """Render side-by-side comparison of current vs suggested"""
    
    st.markdown("##### 📊 Detailed Comparison")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**📋 Current BOM**")
        st.metric("Quantity", f"{material_row['current_qty']:.4f}")
        st.metric("Scrap Rate", f"{material_row['current_scrap']:.2f}%")
        theoretical = material_row.get('theoretical_qty_with_scrap', 0)
        st.metric("Effective/Output", f"{theoretical:.4f}")
    
    with col2:
        st.markdown("**📈 Actual Usage**")
        actual = material_row.get('actual_avg_per_unit', 0)
        st.metric("Avg Consumption", f"{actual:.4f}")
        variance = material_row.get('variance_pct', 0)
        st.metric("Variance", format_variance_display(variance))
        cv = material_row.get('cv_percent', 0)
        st.metric("Consistency (CV)", f"{cv:.1f}%")
    
    with col3:
        st.markdown("**💡 Suggested**")
        st.metric(
            "Option A: Qty",
            f"{material_row['suggested_qty']:.4f}",
            delta=f"{material_row['qty_change']:+.4f}"
        )
        st.metric(
            "Option B: Scrap",
            f"{material_row['suggested_scrap']:.2f}%",
            delta=f"{material_row['scrap_change']:+.2f}%"
        )