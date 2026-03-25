# pages/6_📦_PO_Planning.py

"""
PO Planning Page — Layer 3 of SCM Planning Pipeline.

UI Fixes v1.2:
- Removed "Skip zero-shortage items" (always True, GAP only sends shortage > 0)
- Renamed demand offset → "Planning horizon" with default 60 days
- Moved Export below tabs (near data)
- Reordered tabs: By Vendor → All Lines → Overview → Coverage
- Hidden "Data Source" into Advanced expander
- Informed Consent filter review flow
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

    # =========================================================================
    # SIDEBAR
    # =========================================================================
    with st.sidebar:
        st.markdown("### ⚙️ PO Planning Config")

        strategy = st.selectbox(
            "Vendor Selection Strategy",
            ['CHEAPEST', 'FASTEST'],
            index=0,
            help=(
                "CHEAPEST: pick vendor with lowest unit price (USD)\n"
                "FASTEST: pick vendor with shortest lead time"
            ),
        )

        planning_horizon = st.number_input(
            "Planning horizon (days)",
            min_value=14, max_value=365, value=60,
            help=(
                "Fallback demand date = today + this value.\n"
                "Used when GAP period data has no specific date for a product.\n"
                "Should be longer than your longest vendor lead time."
            ),
        )

        st.divider()
        with st.expander("🔧 Advanced", expanded=False):
            source_mode = st.radio(
                "Data Source",
                ['From SCM GAP Result', 'Refresh vendor pricing'],
                index=0,
                help=(
                    "From SCM GAP Result: use existing analysis (default)\n"
                    "Refresh vendor pricing: reload costbook & vendor data from DB"
                ),
            )

    # =========================================================================
    # ACTION BUTTONS (Generate + Reset only — Export moved below tabs)
    # =========================================================================
    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        run_clicked = st.button(
            "🔄 Generate PO Suggestions",
            type="primary",
            use_container_width=True,
        )
    with col2:
        reset_clicked = st.button("🗑️ Clear Results", use_container_width=True)
    with col3:
        pass  # empty — Export is below tabs now

    # Reset
    if reset_clicked:
        for key in ['po_result', 'po_planner', 'po_filter_review', 'po_pending_args']:
            st.session_state[key] = None
        st.rerun()

    # =========================================================================
    # STEP 1: Generate → filter review first
    # =========================================================================
    if run_clicked:
        gap_result = _get_gap_result(source_mode)
        if gap_result is None:
            st.warning(
                "⚠️ No SCM GAP result found. "
                "Please run **Supply Chain GAP Analysis** first."
            )
        else:
            from utils.supply_chain_planning.validators import validate_gap_filters
            filter_review = validate_gap_filters(gap_result)

            if filter_review.get('all_complete', False):
                _run_planning(strategy, planning_horizon, source_mode)
            else:
                st.session_state['po_filter_review'] = filter_review
                st.session_state['po_pending_args'] = {
                    'strategy': strategy,
                    'planning_horizon': planning_horizon,
                    'source_mode': source_mode,
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
            label = ("⚠️ Proceed anyway — I understand the risk"
                     if review.get('has_high_risk')
                     else "✅ Proceed with current filters")
            proceed = st.button(label, type="primary", use_container_width=True)
        with bc2:
            go_back = st.button("← Go back to SCM GAP", use_container_width=True)

        if proceed:
            _run_planning(args['strategy'], args['planning_horizon'], args['source_mode'])
            st.session_state['po_filter_review'] = None
            st.session_state['po_pending_args'] = None
            st.rerun()
        if go_back:
            st.session_state['po_filter_review'] = None
            st.session_state['po_pending_args'] = None
            st.switch_page("pages/5_🔬_Supply_Chain_GAP.py")
        return

    # =========================================================================
    # DISPLAY RESULTS
    # =========================================================================
    result = st.session_state.get('po_result')
    if result is None:
        _show_empty_state()
        return
    _render_results(result)


# =============================================================================
# FILTER REVIEW
# =============================================================================

def _render_filter_review(review):
    st.divider()
    st.markdown("### 🔍 GAP Filter Review")
    st.markdown("PO Planning uses shortage data from SCM GAP. Review your config against the standard:")

    from utils.supply_chain_planning.po_planning_components import render_gap_config_checklist
    render_gap_config_checklist(review)

    st.divider()


# =============================================================================
# HELPERS
# =============================================================================

def _get_gap_result(source_mode):
    try:
        from utils.supply_chain_gap.state import get_state as get_gap_state
        gap_state = get_gap_state()
        return gap_state.get_result() if gap_state.has_result() else None
    except Exception:
        return None


def _run_planning(strategy, planning_horizon, source_mode):
    from utils.supply_chain_planning.po_planner import POPlanner

    with st.spinner("Loading data and generating PO suggestions..."):
        try:
            reload_vendor = (source_mode == 'Refresh vendor pricing')
            if reload_vendor or st.session_state.get('po_planner') is None:
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
                default_demand_date=date.today() + timedelta(days=planning_horizon),
                # deduct_pending_po is always forced False inside plan_from_gap_result()
                # because GAP already includes PO in supply calculation.
                deduct_pending_po=False,
                skip_zero_shortage=True,
            )
            st.session_state['po_result'] = result

            m = result.get_summary()
            if result.has_lines():
                st.success(
                    f"✅ Generated {m['total_po_lines']} PO lines "
                    f"across {m['total_vendors']} vendors "
                    f"(${m['total_value_usd']:,.0f} total)"
                )
            else:
                st.info("No PO suggestions needed — all shortages covered")
        except Exception as e:
            logger.error(f"PO Planning failed: {e}", exc_info=True)
            st.error(f"PO Planning failed: {e}")


def _do_export(result):
    from utils.supply_chain_planning.po_planning_export import (
        export_po_suggestions_to_excel, get_po_export_filename
    )
    try:
        buffer = export_po_suggestions_to_excel(result)
        st.download_button(
            label="📥 Export Excel",
            data=buffer,
            file_name=get_po_export_filename(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="po_download",
            type="primary",
        )
    except Exception as e:
        st.error(f"Export failed: {e}")


def _show_empty_state():
    st.markdown("---")
    st.markdown("""
    ### 🚀 How to use PO Planning
    1. Go to **Supply Chain GAP** page → run analysis with standard config
    2. Come back here → click **🔄 Generate PO Suggestions**
    3. System reviews GAP filters → confirm if needed
    4. Review vendor-grouped PO lines with urgency and timing
    5. Export to Excel for procurement team
    """)

    from utils.supply_chain_planning.po_planning_components import render_standard_config_reference
    render_standard_config_reference()


def _render_results(result):
    from utils.supply_chain_planning.po_planning_components import (
        po_overview_fragment,
        po_vendor_groups_fragment,
        po_all_lines_fragment,
        po_coverage_fragment,
        render_filter_warning_banner,
    )

    # Persistent filter banner — above tabs
    render_filter_warning_banner(result)

    m = result.get_summary()

    # Tabs: By Vendor first (procurement-friendly)
    tab_vendor, tab_lines, tab_overview, tab_coverage = st.tabs([
        f"🏭 By Vendor ({m.get('total_vendors', 0)})",
        f"📋 All Lines ({m.get('total_po_lines', 0)})",
        f"📊 Overview",
        f"📈 Coverage",
    ])

    with tab_vendor:
        po_vendor_groups_fragment(result)
    with tab_lines:
        po_all_lines_fragment(result)
    with tab_overview:
        po_overview_fragment(result)
    with tab_coverage:
        po_coverage_fragment(result)

    # Export — below tabs, near the data
    st.divider()
    ec1, ec2 = st.columns([1, 3])
    with ec1:
        _do_export(result)


if __name__ == '__main__':
    main()