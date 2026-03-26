# pages/7_🏭_Production_Planning.py

"""
Production Planning Page — Layer 3 Phase 2 of SCM Planning Pipeline.

GAP → MO Suggestions with material readiness, scheduling, and priority.

6 Tabs:
  Tab 0: ⚙️ Settings — config editor with gate logic (ZERO ASSUMPTION)
  Tab 1: ✅ Ready — items that can start production immediately
  Tab 2: ⏳ Waiting — partial materials, bottleneck info
  Tab 3: 🔴 Blocked — no materials + unschedulable items
  Tab 4: 📅 Timeline — Gantt chart + weekly schedule
  Tab 5: 📊 Overview — KPIs, urgency, reconciliation
"""

import streamlit as st
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Production Planning", page_icon="🏭", layout="wide")

SESSION_KEYS = ['mo_result', 'mo_planner', 'mo_config', 'mo_lt_stats']


def main():
    st.title("🏭 Production Planning — MO Suggestions")
    st.caption("Layer 3 Phase 2: GAP → Material readiness → Scheduled MO suggestions with priority")

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
    # ACTION BUTTONS
    # =========================================================================
    btn_cols = st.columns([3, 1, 1])

    with btn_cols[0]:
        can_run = config is not None and config.is_ready
        run_clicked = st.button(
            "🔄 Generate MO Suggestions",
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )
        if not can_run and config is not None:
            missing = len(config.missing_required or [])
            errors = len(config.validation_errors or [])
            st.caption(
                f"⚠️ Cannot run — {missing} missing, {errors} errors. "
                f"Fix in **⚙️ Settings** tab."
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
    # TABS
    # =========================================================================
    result = st.session_state.get('mo_result')
    m = result.get_summary() if result and result.has_lines() else {}

    tab_labels = [
        "⚙️ Settings",
        f"✅ Ready ({m.get('ready_count', 0)})" if m else "✅ Ready",
        f"⏳ Waiting ({m.get('waiting_count', 0)})" if m else "⏳ Waiting",
        f"🔴 Blocked ({m.get('blocked_count', 0)})" if m else "🔴 Blocked",
        "📅 Timeline",
        "📊 Overview",
    ]

    tab_settings, tab_ready, tab_waiting, tab_blocked, tab_timeline, tab_overview = (
        st.tabs(tab_labels)
    )

    # ── Tab 0: Settings ──
    with tab_settings:
        from utils.supply_chain_production.production_components import render_settings_tab
        changes = render_settings_tab(config, lt_stats)
        if changes:
            _save_config(changes)

    # ── Tab 1–5: Results (only if available) ──
    if result is None or not result.has_lines():
        for tab in [tab_ready, tab_waiting, tab_blocked, tab_timeline, tab_overview]:
            with tab:
                from utils.supply_chain_production.production_components import render_empty_state
                render_empty_state()
    else:
        from utils.supply_chain_production.production_components import (
            ready_tab_fragment,
            waiting_tab_fragment,
            blocked_tab_fragment,
            timeline_tab_fragment,
            overview_tab_fragment,
            render_filter_warning_banner,
        )

        # Persistent filter banner on result tabs
        for tab in [tab_ready, tab_waiting, tab_blocked, tab_timeline, tab_overview]:
            with tab:
                render_filter_warning_banner(result)

        with tab_ready:
            ready_tab_fragment(result)
        with tab_waiting:
            waiting_tab_fragment(result)
        with tab_blocked:
            blocked_tab_fragment(result)
        with tab_timeline:
            timeline_tab_fragment(result)
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
            st.session_state['mo_result'] = result

            m = result.get_summary()
            if result.has_lines():
                st.success(
                    f"✅ Generated {m['total_mo_lines']} MO suggestions "
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