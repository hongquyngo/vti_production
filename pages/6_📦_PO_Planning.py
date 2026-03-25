# pages/6_📦_PO_Planning.py

"""
PO Planning Page — Layer 3 of SCM Planning Pipeline.

Takes SCM GAP result → generates vendor-grouped PO suggestions.
Can also run standalone with manual shortage input.

Tabs:
1. Overview — KPIs, urgency, unmatched
2. By Vendor — vendor cards with PO lines
3. All Lines — flat sortable table
4. Coverage — price source & vendor reliability analysis
"""

import streamlit as st
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="PO Planning",
    page_icon="📦",
    layout="wide",
)


def main():
    st.title("📦 PO Planning — Purchase Order Suggestions")
    st.caption("Layer 3: SCM GAP → Vendor-matched PO suggestions with timing & urgency")

    # =========================================================================
    # SESSION STATE
    # =========================================================================
    if 'po_result' not in st.session_state:
        st.session_state['po_result'] = None
    if 'po_planner' not in st.session_state:
        st.session_state['po_planner'] = None

    # =========================================================================
    # SIDEBAR: CONFIGURATION
    # =========================================================================
    with st.sidebar:
        st.markdown("### ⚙️ PO Planning Config")

        strategy = st.selectbox(
            "Vendor Selection Strategy",
            ['CHEAPEST', 'FASTEST'],
            index=0,
            help=(
                "CHEAPEST: lowest unit price (USD)\n"
                "FASTEST: shortest lead time"
            ),
        )

        demand_offset = st.number_input(
            "Default demand date (days from today)",
            min_value=7, max_value=180, value=30,
            help="Fallback demand date when period data is not available",
        )

        deduct_pending = st.checkbox(
            "Deduct pending POs",
            value=True,
            help="Subtract existing PO quantities from shortage before suggesting new POs",
        )

        skip_zero = st.checkbox(
            "Skip zero-shortage items",
            value=True,
            help="Don't create PO lines where pending PO already covers shortage",
        )

        st.divider()

        # Source: from SCM GAP or manual
        source_mode = st.radio(
            "Data Source",
            ['From SCM GAP Result', 'Reload from Database'],
            index=0,
            help="Use existing GAP analysis result or reload all data fresh",
        )

    # =========================================================================
    # ACTION BUTTONS
    # =========================================================================
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        run_clicked = st.button(
            "🔄 Generate PO Suggestions",
            type="primary",
            use_container_width=True,
        )

    with col2:
        reset_clicked = st.button(
            "🗑️ Reset",
            use_container_width=True,
        )

    with col3:
        # Export button (only when result exists)
        has_result = st.session_state.get('po_result') is not None
        export_clicked = st.button(
            "📥 Export Excel",
            disabled=not has_result,
            use_container_width=True,
        )

    # =========================================================================
    # RESET
    # =========================================================================
    if reset_clicked:
        st.session_state['po_result'] = None
        st.session_state['po_planner'] = None
        st.rerun()

    # =========================================================================
    # RUN PLANNING
    # =========================================================================
    if run_clicked:
        _run_planning(
            strategy=strategy,
            demand_offset=demand_offset,
            deduct_pending=deduct_pending,
            skip_zero=skip_zero,
            source_mode=source_mode,
        )

    # =========================================================================
    # EXPORT
    # =========================================================================
    if export_clicked and has_result:
        _do_export()

    # =========================================================================
    # DISPLAY RESULTS
    # =========================================================================
    result = st.session_state.get('po_result')
    if result is None:
        _show_empty_state()
        return

    _render_results(result)


def _run_planning(strategy, demand_offset, deduct_pending, skip_zero, source_mode):
    """Execute PO planning pipeline."""
    from utils.supply_chain_planning.po_planner import POPlanner

    with st.spinner("Loading data and generating PO suggestions..."):
        try:
            # Step 1: Get or create planner
            if source_mode == 'Reload from Database' or st.session_state.get('po_planner') is None:
                planner = POPlanner.create_with_data_loader()
                st.session_state['po_planner'] = planner
            else:
                planner = st.session_state['po_planner']

            # Step 2: Get GAP result
            gap_result = None
            if source_mode == 'From SCM GAP Result':
                # Try to get from SCM GAP session state
                from utils.supply_chain_gap.state import get_state as get_gap_state
                gap_state = get_gap_state()
                gap_result = gap_state.get_result() if gap_state.has_result() else None

            if gap_result is None:
                st.warning(
                    "⚠️ No SCM GAP result found in session. "
                    "Please run **Supply Chain GAP Analysis** first, "
                    "then come back to this page."
                )
                return

            # Step 3: Run planning
            default_demand = date.today() + timedelta(days=demand_offset)

            result = planner.plan_from_gap_result(
                gap_result=gap_result,
                strategy=strategy,
                default_demand_date=default_demand,
                deduct_pending_po=deduct_pending,
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
                st.info("No PO suggestions needed — all shortages covered by pending POs")

        except ImportError as e:
            st.error(f"Module not found: {e}. Ensure supply_chain_gap module is available.")
        except Exception as e:
            logger.error(f"PO Planning failed: {e}", exc_info=True)
            st.error(f"PO Planning failed: {e}")


def _do_export():
    """Export results to Excel."""
    from utils.supply_chain_planning.po_planning_export import (
        export_po_suggestions_to_excel, get_po_export_filename
    )

    result = st.session_state.get('po_result')
    if result is None:
        return

    try:
        buffer = export_po_suggestions_to_excel(result)
        filename = get_po_export_filename()

        st.download_button(
            label="⬇️ Download Excel",
            data=buffer,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="po_download",
        )
    except Exception as e:
        st.error(f"Export failed: {e}")


def _show_empty_state():
    """Show empty state with instructions."""
    st.markdown("---")
    st.markdown("""
    ### 🚀 How to use PO Planning
    
    **Prerequisites:** Run **Supply Chain GAP Analysis** first to identify shortages.
    
    **Steps:**
    1. Go to **Supply Chain GAP** page → run analysis
    2. Come back here → click **🔄 Generate PO Suggestions**
    3. Review vendor-grouped PO lines with urgency and timing
    4. Export to Excel for procurement team
    
    **What this does:**
    - Takes shortage items (Trading FG + Raw Materials) from GAP analysis
    - Matches each product to the best vendor (costbook → last PO → no source)
    - Applies MOQ/SPQ rounding
    - Calculates lead time, must-order-by date, and urgency
    - Groups PO lines by vendor for efficient ordering
    """)


def _render_results(result):
    """Render PO planning results in tabs."""
    from utils.supply_chain_planning.po_planning_components import (
        po_overview_fragment,
        po_vendor_groups_fragment,
        po_all_lines_fragment,
        po_coverage_fragment,
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        f"📊 Overview ({result.get_summary().get('total_po_lines', 0)})",
        f"🏭 By Vendor ({result.get_summary().get('total_vendors', 0)})",
        f"📋 All Lines",
        f"📈 Coverage",
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
