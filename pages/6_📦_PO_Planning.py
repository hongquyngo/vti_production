# pages/6_📦_PO_Planning.py

"""
PO Planning Page — Layer 3 of SCM Planning Pipeline.

Flow:
1. User clicks "Generate PO Suggestions"
2. System reviews GAP filter context (Informed Consent)
3. If all filters complete → auto-proceed
4. If filters incomplete → show review panel, user must confirm
5. Results displayed with persistent banner if filters incomplete
"""

import streamlit as st
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

st.set_page_config(page_title="PO Planning", page_icon="📦", layout="wide")


def main():
    st.title("📦 PO Planning — Purchase Order Suggestions")
    st.caption("Layer 3: SCM GAP → Vendor-matched PO suggestions with timing & urgency")

    # Session state
    for key in ['po_result', 'po_planner', 'po_filter_review', 'po_pending_args']:
        if key not in st.session_state:
            st.session_state[key] = None

    # Sidebar config
    with st.sidebar:
        st.markdown("### ⚙️ PO Planning Config")
        strategy = st.selectbox("Vendor Selection Strategy", ['CHEAPEST', 'FASTEST'], index=0,
                                help="CHEAPEST: lowest unit price (USD)\nFASTEST: shortest lead time")
        demand_offset = st.number_input("Default demand date (days from today)",
                                         min_value=7, max_value=180, value=30)
        skip_zero = st.checkbox("Skip zero-shortage items", value=True)
        st.divider()
        source_mode = st.radio("Data Source", ['From SCM GAP Result', 'Reload from Database'], index=0)

    # Action buttons
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        run_clicked = st.button("🔄 Generate PO Suggestions", type="primary", use_container_width=True)
    with col2:
        reset_clicked = st.button("🗑️ Reset", use_container_width=True)
    with col3:
        has_result = st.session_state.get('po_result') is not None
        export_clicked = st.button("📥 Export Excel", disabled=not has_result, use_container_width=True)

    # Reset
    if reset_clicked:
        for key in ['po_result', 'po_planner', 'po_filter_review', 'po_pending_args']:
            st.session_state[key] = None
        st.rerun()

    # =========================================================================
    # STEP 1: Generate clicked → run filter review first
    # =========================================================================
    if run_clicked:
        gap_result = _get_gap_result(source_mode)
        if gap_result is None:
            st.warning("⚠️ No SCM GAP result found. Please run **Supply Chain GAP Analysis** first.")
        else:
            from utils.supply_chain_planning.validators import validate_gap_filters
            filter_review = validate_gap_filters(gap_result)

            if filter_review.get('all_complete', False):
                # All filters ON → auto-proceed
                _run_planning(strategy, demand_offset, skip_zero, source_mode)
            else:
                # Incomplete → show review, wait for confirm
                st.session_state['po_filter_review'] = filter_review
                st.session_state['po_pending_args'] = {
                    'strategy': strategy, 'demand_offset': demand_offset,
                    'skip_zero': skip_zero, 'source_mode': source_mode,
                }

    # =========================================================================
    # STEP 2: Filter review panel (if pending)
    # =========================================================================
    if st.session_state.get('po_filter_review') and st.session_state.get('po_pending_args'):
        review = st.session_state['po_filter_review']
        args = st.session_state['po_pending_args']

        _render_filter_review(review)

        bc1, bc2 = st.columns([1, 1])
        with bc1:
            btn_label = ("⚠️ Proceed anyway — I understand the risk"
                         if review.get('has_high_risk')
                         else "✅ Proceed with current filters")
            proceed = st.button(btn_label, type="primary", use_container_width=True)
        with bc2:
            go_back = st.button("← Go back to SCM GAP", use_container_width=True)

        if proceed:
            _run_planning(args['strategy'], args['demand_offset'],
                          args['skip_zero'], args['source_mode'])
            st.session_state['po_filter_review'] = None
            st.session_state['po_pending_args'] = None
            st.rerun()

        if go_back:
            st.session_state['po_filter_review'] = None
            st.session_state['po_pending_args'] = None
            st.switch_page("pages/5_🔬_Supply_Chain_GAP.py")

        return  # Don't render results while review pending

    # Export
    if export_clicked and has_result:
        _do_export()

    # Display results
    result = st.session_state.get('po_result')
    if result is None:
        _show_empty_state()
        return
    _render_results(result)


def _render_filter_review(review):
    """Render filter review panel for user confirmation."""
    st.divider()
    st.markdown("### 🔍 GAP Filter Review")
    st.markdown("PO Planning uses shortage data from SCM GAP. Review the filters used:")

    items = review.get('items', [])
    if not items:
        st.success("✅ All supply & demand sources enabled — data is complete.")
        return

    from utils.supply_chain_planning.validators import SUPPLY_SOURCE_IMPACT, DEMAND_SOURCE_IMPACT

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📦 Supply Sources**")
        for s in review.get('supply_sources_on', []):
            info = SUPPLY_SOURCE_IMPACT.get(s, {})
            st.markdown(f"✅ {info.get('icon', '')} {info.get('label', s)}")
        for s in review.get('supply_sources_off', []):
            info = SUPPLY_SOURCE_IMPACT.get(s, {})
            risk = info.get('risk', 'INFO')
            marker = '🔴' if risk == 'HIGH' else '🟡' if risk == 'MEDIUM' else 'ℹ️'
            st.markdown(f"{marker} ~~{info.get('label', s)}~~ — **OFF**")

    with col2:
        st.markdown("**📊 Demand Sources**")
        for d in review.get('demand_sources_on', []):
            info = DEMAND_SOURCE_IMPACT.get(d, {})
            st.markdown(f"✅ {info.get('icon', '')} {info.get('label', d)}")
        for d in review.get('demand_sources_off', []):
            info = DEMAND_SOURCE_IMPACT.get(d, {})
            st.markdown(f"ℹ️ ~~{info.get('label', d)}~~ — **OFF**")

    high_items = [i for i in items if i['risk'] == 'HIGH']
    medium_items = [i for i in items if i['risk'] == 'MEDIUM']
    info_items = [i for i in items if i['risk'] == 'INFO']

    if high_items:
        st.markdown("---")
        for item in high_items:
            st.error(f"🔴 **{item['label']}** is OFF — {item['consequence']}")
    if medium_items:
        for item in medium_items:
            st.warning(f"🟡 **{item['label']}** — {item['consequence']}")
    if info_items:
        with st.expander(f"ℹ️ {len(info_items)} informational notes", expanded=False):
            for item in info_items:
                st.caption(f"• **{item['label']}** — {item['consequence']}")
    st.divider()


def _get_gap_result(source_mode):
    if source_mode == 'From SCM GAP Result':
        try:
            from utils.supply_chain_gap.state import get_state as get_gap_state
            gap_state = get_gap_state()
            return gap_state.get_result() if gap_state.has_result() else None
        except Exception:
            return None
    return None


def _run_planning(strategy, demand_offset, skip_zero, source_mode):
    from utils.supply_chain_planning.po_planner import POPlanner

    with st.spinner("Loading data and generating PO suggestions..."):
        try:
            if source_mode == 'Reload from Database' or st.session_state.get('po_planner') is None:
                planner = POPlanner.create_with_data_loader()
                st.session_state['po_planner'] = planner
            else:
                planner = st.session_state['po_planner']

            gap_result = _get_gap_result(source_mode)
            if gap_result is None:
                st.warning("⚠️ No SCM GAP result found.")
                return

            result = planner.plan_from_gap_result(
                gap_result=gap_result,
                strategy=strategy,
                default_demand_date=date.today() + timedelta(days=demand_offset),
                deduct_pending_po=True,
                skip_zero_shortage=skip_zero,
            )
            st.session_state['po_result'] = result

            metrics = result.get_summary()
            if result.has_lines():
                st.success(
                    f"✅ Generated {metrics['total_po_lines']} PO lines "
                    f"across {metrics['total_vendors']} vendors "
                    f"(${metrics['total_value_usd']:,.0f} total)"
                )
            else:
                st.info("No PO suggestions needed — all shortages covered")
        except ImportError as e:
            st.error(f"Module not found: {e}")
        except Exception as e:
            logger.error(f"PO Planning failed: {e}", exc_info=True)
            st.error(f"PO Planning failed: {e}")


def _do_export():
    from utils.supply_chain_planning.po_planning_export import (
        export_po_suggestions_to_excel, get_po_export_filename
    )
    result = st.session_state.get('po_result')
    if result is None:
        return
    try:
        buffer = export_po_suggestions_to_excel(result)
        st.download_button(
            label="⬇️ Download Excel", data=buffer,
            file_name=get_po_export_filename(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="po_download",
        )
    except Exception as e:
        st.error(f"Export failed: {e}")


def _show_empty_state():
    st.markdown("---")
    st.markdown("""
    ### 🚀 How to use PO Planning
    1. Go to **Supply Chain GAP** page → run analysis
    2. Come back here → click **🔄 Generate PO Suggestions**
    3. System reviews GAP filters → confirm if needed
    4. Review vendor-grouped PO lines with urgency and timing
    5. Export to Excel for procurement team
    """)


def _render_results(result):
    from utils.supply_chain_planning.po_planning_components import (
        po_overview_fragment, po_vendor_groups_fragment,
        po_all_lines_fragment, po_coverage_fragment,
        render_filter_warning_banner,
    )
    render_filter_warning_banner(result)

    tab1, tab2, tab3, tab4 = st.tabs([
        f"📊 Overview ({result.get_summary().get('total_po_lines', 0)})",
        f"🏭 By Vendor ({result.get_summary().get('total_vendors', 0)})",
        "📋 All Lines", "📈 Coverage",
    ])
    with tab1:
        po_overview_fragment(result)
    with tab2:
        po_vendor_groups_fragment(result)
    with tab3:
        po_all_lines_fragment(result)
    with tab4:
        po_coverage_fragment(result)


if __name__ == '__main__':
    main()