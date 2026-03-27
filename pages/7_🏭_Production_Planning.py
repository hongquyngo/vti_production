# pages/7_🏭_Production_Planning.py

"""
Production Planning Page — Layer 3 of SCM Planning Pipeline.

GAP → MO Suggestions with material readiness, scheduling, and priority.

5 Tabs:
  Tab 0: 📊 Overview — KPIs, urgency matrix, top urgent, reconciliation
  Tab 1: ✅ Ready — items that can start production (Summary / Schedule / Detail)
  Tab 2: ⏳ Waiting — partial materials, bottleneck info (Summary / Schedule / Detail)
  Tab 3: 🔴 Blocked — no materials + unschedulable items (Detail / Schedule)
  Tab 4: ⚙️ Settings — config editor with gate logic (ZERO ASSUMPTION)
"""

import streamlit as st
import logging
from datetime import date, timedelta
import os
from pathlib import Path

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Production Planning", page_icon="🏭", layout="wide")

# Project root for imports
project_root = os.environ.get('PROJECT_ROOT', Path(__file__).parent.parent)
if str(project_root) not in os.sys.path:
    os.sys.path.insert(0, str(project_root))

from utils.auth import AuthManager

SESSION_KEYS = ['mo_result', 'mo_planner', 'mo_config', 'mo_lt_stats']


def main():
    # =========================================================================
    # AUTHENTICATION
    # =========================================================================
    auth_manager = AuthManager()
    if not auth_manager.check_session():
        st.warning("⚠️ Please login to access this page")
        st.stop()

    # =========================================================================
    # SIDEBAR
    # =========================================================================
    with st.sidebar:
        st.markdown(f"👤 **User:** {auth_manager.get_user_display_name()}")
        if st.button("🚪 Logout", use_container_width=True):
            auth_manager.logout()
            st.rerun()

        st.divider()
        from utils.supply_chain_production.production_constants import VERSION
        st.caption(f"Production Planning v{VERSION}")

    # =========================================================================
    # PAGE HEADER + GUIDE BUTTON
    # =========================================================================
    hdr_cols = st.columns([5, 1])
    with hdr_cols[0]:
        st.title("🏭 Production Planning — MO Suggestions")
        st.caption("Layer 3: GAP → Material readiness → Scheduled MO suggestions with priority")
    with hdr_cols[1]:
        st.markdown("")  # spacer
        from utils.supply_chain_production.production_help import render_user_guide_button
        render_user_guide_button()

    # Session state init
    for key in SESSION_KEYS:
        if key not in st.session_state:
            st.session_state[key] = None

    # =========================================================================
    # LOAD CONFIG (always — needed for gate check)
    # =========================================================================
    config, lt_stats = _load_config()
    st.session_state['mo_config'] = config
    st.session_state['mo_lt_stats'] = lt_stats

    # =========================================================================
    # PIPELINE STATUS BAR (Phase B)
    # =========================================================================
    from utils.supply_chain_production.production_components import (
        get_pipeline_status, render_pipeline_status_bar,
        build_tab_labels, render_empty_state_for_tab,
    )

    pipeline = get_pipeline_status()
    render_pipeline_status_bar(pipeline)

    gap_available = pipeline['gap']['available']

    # =========================================================================
    # DISPLAY FILTER SCOPE (detect brand/product filter from GAP)
    # =========================================================================
    scope_info = {'has_filter': False}
    use_filtered_scope = True  # default: use filtered if available

    if gap_available:
        from utils.supply_chain_production.production_validators import (
            extract_display_filter_scope_for_production,
        )
        gap_result_for_scope = _get_gap_result()
        scope_info = extract_display_filter_scope_for_production(gap_result_for_scope)

        if scope_info['has_filter']:
            st.divider()
            st.markdown("### 🔍 GAP Display Filter Detected")
            st.markdown(
                f"SCM GAP was analyzed with filter: **{scope_info['scope_label']}**. "
                f"Choose which products to include in MO suggestions:"
            )

            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown(
                    f"**🎯 Filtered** — {scope_info['scope_label']}\n\n"
                    f"`{scope_info['fg_filtered']}` of `{scope_info['fg_total']}` FG products"
                )
            with sc2:
                st.markdown(
                    f"**🟠 Full** — all products\n\n"
                    f"`{scope_info['fg_total']}` FG products"
                )

            scope_choice = st.radio(
                "MO Planning scope",
                [
                    f"🎯 Filtered ({scope_info['scope_label']})",
                    f"🟠 Full (all {scope_info['fg_total']} FG)",
                ],
                key="mo_scope_choice",
                horizontal=True,
                help="Filtered = only MO suggestions for products matching the GAP filter. Full = all products.",
            )
            use_filtered_scope = scope_choice.startswith("🎯")
            st.divider()

    # Store scope in session for _run_planning
    st.session_state['_mo_scope_info'] = scope_info
    st.session_state['_mo_use_filtered'] = use_filtered_scope

    # =========================================================================
    # ACTION BUTTONS
    # =========================================================================
    btn_cols = st.columns([3, 1, 1])

    with btn_cols[0]:
        can_run = (
            config is not None
            and config.is_ready
            and gap_available
        )
        # Button label reflects scope
        if scope_info['has_filter'] and use_filtered_scope:
            btn_label = f"🔄 Generate MO Suggestions (filtered: {scope_info['scope_label']})"
        else:
            btn_label = "🔄 Generate MO Suggestions"

        run_clicked = st.button(
            btn_label,
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )
        if not can_run and config is not None:
            if not gap_available:
                st.caption(
                    "⚠️ Cannot run — SCM GAP result not available. "
                    "Run **Supply Chain GAP** first."
                )
            elif not config.is_ready:
                missing = len(config.missing_required or [])
                errors = len(config.validation_errors or [])
                st.caption(
                    f"⚠️ Cannot run — {missing} missing, {errors} errors. "
                    f"Fix in **Settings** tab."
                )

    with btn_cols[1]:
        reset_clicked = st.button("🗑️ Clear Results", use_container_width=True)

    with btn_cols[2]:
        pass  # Export is below tabs

    if reset_clicked:
        st.session_state['mo_result'] = None
        st.session_state['mo_planner'] = None
        st.rerun()

    # =========================================================================
    # RUN PLANNING
    # =========================================================================
    if run_clicked:
        _run_planning(config)

    # =========================================================================
    # TABS — Overview first (daily landing), Settings last (one-time config)
    # =========================================================================
    result = st.session_state.get('mo_result')
    config_ready = config is not None and config.is_ready

    tab_labels = build_tab_labels(result, config_ready, gap_available)

    tab_overview, tab_ready, tab_waiting, tab_blocked, tab_settings = (
        st.tabs(tab_labels)
    )

    # ── Tab: Settings (last — one-time config) ──
    with tab_settings:
        from utils.supply_chain_production.production_components import render_settings_tab
        changes = render_settings_tab(config, lt_stats)
        if changes:
            _save_config(changes)

    # ── Tabs: Results or per-tab empty states ──
    if result is None or not result.has_lines():
        tab_map = {
            tab_overview: 'overview',
            tab_ready: 'ready',
            tab_waiting: 'waiting',
            tab_blocked: 'blocked',
        }
        for tab, tab_name in tab_map.items():
            with tab:
                render_empty_state_for_tab(tab_name, config_ready, gap_available)
    else:
        from utils.supply_chain_production.production_components import (
            ready_tab_fragment,
            waiting_tab_fragment,
            blocked_tab_fragment,
            overview_tab_fragment,
            render_filter_warning_banner,
        )

        # Persistent filter banner on result tabs
        for tab in [tab_ready, tab_waiting, tab_blocked, tab_overview]:
            with tab:
                render_filter_warning_banner(result)

        with tab_ready:
            ready_tab_fragment(result)
        with tab_waiting:
            waiting_tab_fragment(result)
        with tab_blocked:
            blocked_tab_fragment(result)
        with tab_overview:
            overview_tab_fragment(result)

        # Export — below tabs
        st.divider()
        ec1, ec2 = st.columns([1, 3])
        with ec1:
            _do_export(result)


# =============================================================================
# CONFIG LOADING
# =============================================================================

def _load_config():
    """Load config from DB and lead time stats."""
    try:
        from utils.supply_chain_production.production_config import ProductionConfigLoader
        from utils.supply_chain_production.production_data_loader import get_production_data_loader

        loader = ProductionConfigLoader()
        config = loader.load_and_validate()

        data_loader = get_production_data_loader()
        lt_stats = data_loader.load_lead_time_stats()

        return config, lt_stats
    except Exception as e:
        logger.error(f"Failed to load production config: {e}", exc_info=True)
        st.error(f"⚠️ Failed to load config: {e}")

        # Return minimal config with is_ready=False
        from utils.supply_chain_production.production_config import ProductionConfig
        return ProductionConfig(is_ready=False, missing_required=['DB_CONNECTION_FAILED']), None


def _save_config(changes):
    """Save config changes to DB and reload.

    Args:
        changes: Dict[str, Any] — keys are 'GROUP.CONFIG_KEY' format
                 e.g. 'LEAD_TIME.CUTTING.DAYS', 'PRIORITY.WEIGHT.TIME_URGENCY'
                 Split on first '.' to get (config_group, config_key).
    """
    try:
        from utils.supply_chain_production.production_config import ProductionConfigLoader
        loader = ProductionConfigLoader()

        saved = 0
        for compound_key, value in changes.items():
            try:
                # Split 'LEAD_TIME.CUTTING.DAYS' → group='LEAD_TIME', key='CUTTING.DAYS'
                parts = compound_key.split('.', 1)
                if len(parts) != 2:
                    st.error(f"Invalid config key format: {compound_key}")
                    continue
                config_group, config_key = parts
                if loader.save_config(config_group, config_key, str(value)):
                    saved += 1
                else:
                    st.error(f"Failed to save {compound_key}: no matching row in DB")
            except Exception as e:
                st.error(f"Failed to save {compound_key}: {e}")

        if saved > 0:
            st.success(f"💾 Saved {saved} setting(s). Reloading...")
            # Clear cached config to force reload
            st.session_state['mo_config'] = None
            st.rerun()

    except Exception as e:
        logger.error(f"Failed to save config: {e}", exc_info=True)
        st.error(f"Save failed: {e}")


# =============================================================================
# PLANNING EXECUTION
# =============================================================================

def _run_planning(config):
    """Execute the full production planning pipeline."""
    from utils.supply_chain_production.mo_planner import MOPlanner

    with st.spinner("Loading data and generating MO suggestions..."):
        try:
            gap_result = _get_gap_result()
            if gap_result is None:
                st.warning(
                    "⚠️ No SCM GAP result found. "
                    "Please run **Supply Chain GAP Analysis** first."
                )
                return

            # ── Apply display filter scope (if filtered) ──
            scope_info = st.session_state.get('_mo_scope_info', {})
            use_filtered = st.session_state.get('_mo_use_filtered', True)
            original_mo_suggestions = None  # track for restore

            if scope_info.get('has_filter') and use_filtered:
                filtered_ids = scope_info.get('filtered_product_ids', set())
                if filtered_ids:
                    original_mo_suggestions = getattr(gap_result, 'mo_suggestions', []) or []
                    filtered_list = [
                        a for a in original_mo_suggestions
                        if getattr(a, 'product_id', None) in filtered_ids
                    ]
                    gap_result.mo_suggestions = filtered_list
                    logger.info(
                        f"Display filter applied: {len(filtered_list)}/{len(original_mo_suggestions)} "
                        f"mo_suggestions kept ({scope_info.get('scope_label', '')})"
                    )

            # Create planner with auto-loaded supplementary data
            planner = MOPlanner.create_with_data_loader(config)
            st.session_state['mo_planner'] = planner

            # Get PO result if available (improves material ETA)
            po_result = _get_po_result()

            # Run pipeline
            result = planner.plan_from_gap_result(
                gap_result=gap_result,
                po_result=po_result,
            )

            # Restore original mo_suggestions if we filtered them
            if original_mo_suggestions is not None:
                gap_result.mo_suggestions = original_mo_suggestions

            # Store scope in result for UI display
            if scope_info.get('has_filter'):
                result.input_summary['display_filter'] = {
                    'active': use_filtered,
                    'scope_label': scope_info.get('scope_label', ''),
                    'fg_filtered': scope_info.get('fg_filtered', 0),
                    'fg_total': scope_info.get('fg_total', 0),
                }

            st.session_state['mo_result'] = result

            m = result.get_summary()
            if result.has_lines():
                scope_tag = ""
                if scope_info.get('has_filter') and use_filtered:
                    scope_tag = f" (filtered: {scope_info['scope_label']})"
                st.success(
                    f"✅ Generated {m['total_mo_lines']} MO suggestions{scope_tag} "
                    f"({m.get('ready_count', 0)} ready, "
                    f"{m.get('waiting_count', 0)} waiting, "
                    f"{m.get('blocked_count', 0)} blocked)"
                )
                if m.get('unschedulable_count', 0) > 0:
                    st.warning(
                        f"⚠️ {m['unschedulable_count']} items could not be scheduled — "
                        f"check **🔴 Blocked** tab."
                    )
            else:
                st.info("No MO suggestions needed — no manufacturing shortages from GAP.")

        except Exception as e:
            logger.error(f"Production Planning failed: {e}", exc_info=True)
            st.error(f"Production Planning failed: {e}")


# =============================================================================
# HELPERS
# =============================================================================

def _get_gap_result():
    """Get GAP result from session state."""
    try:
        from utils.supply_chain_gap.state import get_state as get_gap_state
        gap_state = get_gap_state()
        return gap_state.get_result() if gap_state.has_result() else None
    except Exception:
        return None


def _get_po_result():
    """Get PO Planning result if available (optional — improves material ETA)."""
    try:
        return st.session_state.get('po_result')
    except Exception:
        return None


def _do_export(result):
    """Render Excel export button."""
    from utils.supply_chain_production.production_export import (
        export_mo_suggestions_to_excel, get_mo_export_filename,
    )
    try:
        buffer = export_mo_suggestions_to_excel(result)
        st.download_button(
            label="📥 Export Excel",
            data=buffer,
            file_name=get_mo_export_filename(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="mo_download",
            type="primary",
        )
    except Exception as e:
        st.error(f"Export failed: {e}")


if __name__ == '__main__':
    main()