# utils/supply_chain_production/production_components.py

"""
UI Components for Production Planning — Streamlit fragments and tables.

Components:
- Settings tab (config editor with gate logic)
- KPI cards (readiness, urgency, value)
- Urgency distribution bar
- MO lines table (Ready / Waiting / Blocked)
- Unschedulable panel
- Material readiness heatmap
- Timeline (Gantt)
- Reconciliation panel
- Tab fragments (isolated state)
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from typing import Dict, Any, Optional, List
import logging

from .production_constants import (
    URGENCY_LEVELS,
    READINESS_STATUS,
    BOM_TYPES,
    MO_ACTION_TYPES,
    UNSCHEDULABLE_REASONS,
    CONFIG_GROUPS,
    VERSION,
)
from .production_config import ProductionConfig
from .mo_result import MOLineItem, MOSuggestionResult

logger = logging.getLogger(__name__)


# =============================================================================
# STYLED DATAFRAME HELPER
# =============================================================================

def _styled_dataframe(
    df: pd.DataFrame,
    qty_cols: Optional[List[str]] = None,
    currency_cols: Optional[List[str]] = None,
    pct_cols: Optional[List[str]] = None,
) -> 'pd.io.formats.style.Styler':
    """Apply thousand-separator formatting via pandas Styler."""
    fmt = {}
    if qty_cols:
        for c in qty_cols:
            if c in df.columns:
                fmt[c] = '{:,.0f}'
    if currency_cols:
        for c in currency_cols:
            if c in df.columns:
                fmt[c] = '${:,.2f}'
    if pct_cols:
        for c in pct_cols:
            if c in df.columns:
                fmt[c] = '{:.1f}%'
    return df.style.format(fmt, na_rep='-') if fmt else df


# =============================================================================
# PIPELINE STATUS BAR (Phase B)
# =============================================================================

def get_pipeline_status() -> Dict[str, Any]:
    """
    Check upstream module status from session state.

    Pipeline:  GAP ──┬── PO Planning
                     └── Production Planning (MO)

    GAP is the root. PO and MO are parallel branches.
    """
    import streamlit as _st

    # GAP result
    gap_available = False
    gap_summary = ''
    try:
        from utils.supply_chain_gap.state import get_state as get_gap_state
        gap_state = get_gap_state()
        if gap_state.has_result():
            gap_available = True
            result = gap_state.get_result()
            fg_count = 0
            shortage_count = 0
            if hasattr(result, 'fg_gap_df') and result.fg_gap_df is not None:
                fg_count = len(result.fg_gap_df)
                shortage_count = len(result.fg_gap_df[result.fg_gap_df.get('net_gap', 0) < 0]) \
                    if 'net_gap' in result.fg_gap_df.columns else 0
            gap_summary = f"{fg_count} products, {shortage_count} shortages"
    except Exception:
        pass

    # PO result
    po_available = False
    po_summary = ''
    try:
        po_result = _st.session_state.get('po_result')
        if po_result is not None and hasattr(po_result, 'all_lines') and po_result.all_lines:
            po_available = True
            po_summary = f"{len(po_result.all_lines)} PO lines"
    except Exception:
        pass

    # MO result
    mo_available = False
    mo_summary = ''
    try:
        mo_result = _st.session_state.get('mo_result')
        if mo_result is not None and hasattr(mo_result, 'has_lines') and mo_result.has_lines():
            mo_available = True
            m = mo_result.get_summary()
            mo_summary = f"{m.get('total_mo_lines', 0)} MO lines"
    except Exception:
        pass

    # Config ready?
    config_ready = False
    try:
        mo_config = _st.session_state.get('mo_config')
        if mo_config and hasattr(mo_config, 'is_ready'):
            config_ready = mo_config.is_ready
    except Exception:
        pass

    return {
        'gap': {'available': gap_available, 'summary': gap_summary},
        'po': {'available': po_available, 'summary': po_summary},
        'mo': {'available': mo_available, 'summary': mo_summary},
        'config_ready': config_ready,
    }


def render_pipeline_status_bar(pipeline: Dict[str, Any]):
    """
    Render horizontal pipeline status bar.

    GAP ──┬── PO Planning
          └── Production Planning (current)
    """
    gap = pipeline['gap']
    po = pipeline['po']
    mo = pipeline['mo']

    # Build step indicators
    def _step_html(icon: str, label: str, status: str, detail: str = '') -> str:
        if status == 'done':
            bg = '#C6EFCE'
            border = '#10B981'
            color = '#006100'
            sym = '✓'
        elif status == 'active':
            bg = '#D6EAFF'
            border = '#3B82F6'
            color = '#185FA5'
            sym = '●'
        elif status == 'warning':
            bg = '#FFEB9C'
            border = '#F59E0B'
            color = '#9C5700'
            sym = '!'
        else:  # pending
            bg = 'transparent'
            border = '#D3D1C7'
            color = '#888780'
            sym = '○'

        title_attr = f' title="{detail}"' if detail else ''
        return (
            f'<span style="display:inline-flex;align-items:center;gap:5px;'
            f'padding:5px 12px;border-radius:6px;font-size:13px;'
            f'background:{bg};border:1px solid {border};color:{color}"'
            f'{title_attr}>'
            f'<b>{sym}</b> {label}</span>'
        )

    arrow = '<span style="color:#B4B2A9;font-size:11px;margin:0 2px">▸</span>'
    branch = '<span style="color:#B4B2A9;font-size:11px;margin:0 2px">┬▸</span>'
    branch2 = '<span style="color:#B4B2A9;font-size:11px;margin:0 2px">└▸</span>'

    # GAP status
    gap_status = 'done' if gap['available'] else 'warning'
    gap_html = _step_html('🔬', 'SCM GAP', gap_status, gap['summary'])

    # PO status
    if po['available']:
        po_status = 'done'
    elif gap['available']:
        po_status = 'pending'
    else:
        po_status = 'pending'
    po_html = _step_html('📦', 'PO Planning', po_status, po['summary'])

    # MO status (current page)
    if mo['available']:
        mo_status = 'done'
    else:
        mo_status = 'active'
    mo_html = _step_html('🏭', 'MO Planning', mo_status, mo['summary'])

    # Render as two-line branch layout
    html = (
        f'<div style="display:flex;flex-direction:column;gap:4px;'
        f'padding:10px 14px;border-radius:8px;'
        f'background:var(--color-background-secondary, #F8F8F6);margin-bottom:12px">'
        # Row 1: GAP → PO
        f'<div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap">'
        f'{gap_html}{branch}{po_html}'
        f'</div>'
        # Row 2: indent + MO (current)
        f'<div style="display:flex;align-items:center;gap:4px;margin-left:0;flex-wrap:wrap">'
        f'<span style="display:inline-block;width:{_estimate_step_width(gap_html)}px"></span>'
        f'{branch2}{mo_html}'
        f'<span style="font-size:11px;color:var(--color-text-tertiary, #888);margin-left:4px">(current page)</span>'
        f'</div>'
        f'</div>'
    )

    st.markdown(html, unsafe_allow_html=True)

    # Warning if GAP not run
    if not gap['available']:
        st.warning(
            "⚠️ **SCM GAP not run yet.** Run Supply Chain GAP Analysis first — "
            "Production Planning needs GAP shortage data to generate MO suggestions."
        )


def _estimate_step_width(html: str) -> int:
    """Rough width estimate for alignment. Not pixel-perfect but good enough."""
    # Count visible text chars roughly
    import re
    text = re.sub(r'<[^>]+>', '', html)
    return max(80, len(text) * 7)


# =============================================================================
# TAB LABEL HELPERS (Phase B)
# =============================================================================

def build_tab_labels(
    result,
    config_ready: bool,
    gap_available: bool,
) -> list:
    """
    Build tab labels with status indicators.

    Dot colors:
      🟢 = has data (result available)
      🟡 = settings incomplete or GAP not run
      ⚪ = not yet run (ready to generate)
    """
    m = result.get_summary() if result and result.has_lines() else {}
    has_result = bool(m)

    # Settings dot
    if config_ready:
        settings_dot = '🟢'
    else:
        settings_dot = '🟡'

    # Result tabs dot
    if has_result:
        result_dot = '🟢'
    elif not config_ready or not gap_available:
        result_dot = '🟡'
    else:
        result_dot = '⚪'

    # Order: Overview → Ready → Waiting → Blocked → Timeline → Settings
    labels = [
        f"{result_dot} Overview",
        f"{result_dot} Ready ({m.get('ready_count', 0)})" if has_result else f"{result_dot} Ready",
        f"{result_dot} Waiting ({m.get('waiting_count', 0)})" if has_result else f"{result_dot} Waiting",
        f"{result_dot} Blocked ({m.get('blocked_count', 0)})" if has_result else f"{result_dot} Blocked",
        f"{result_dot} Timeline",
        f"{settings_dot} Settings",
    ]
    return labels


# =============================================================================
# ENHANCED EMPTY STATES (Phase B)
# =============================================================================

def render_empty_state_for_tab(
    tab_name: str,
    config_ready: bool,
    gap_available: bool,
):
    """
    Context-aware empty state per tab — shows what the tab will display
    and what's needed to get there.
    """
    # Determine blocker
    if not gap_available:
        blocker = 'gap'
    elif not config_ready:
        blocker = 'config'
    else:
        blocker = 'run'  # everything ready, just need to click Generate

    # Blocker message
    if blocker == 'gap':
        st.warning(
            "🔬 **Run Supply Chain GAP first.** "
            "Go to **Supply Chain GAP** page → run analysis → then return here."
        )
    elif blocker == 'config':
        st.info(
            "⚙️ **Complete Settings first.** "
            "Go to **Settings** tab → fill required fields → then click Generate."
        )
    else:
        st.info(
            "🔄 **Ready to generate.** "
            "Click **Generate MO Suggestions** above to populate this tab."
        )

    # Tab-specific preview
    previews = {
        'ready': {
            'icon': '✅',
            'title': 'Ready to produce',
            'desc': (
                'MO suggestions where all BOM materials are available. '
                'Each line shows product, suggested quantity, batch count, '
                'priority score, and a "Create MO" action button.'
            ),
            'columns': 'Priority · Code · Product · BOM · Shortage · Suggested Qty · Start Date · Action',
        },
        'waiting': {
            'icon': '⏳',
            'title': 'Waiting for materials',
            'desc': (
                'Items with partial material availability. Shows bottleneck material, '
                'ETA for full coverage, max producible now, and contention alerts.'
            ),
            'columns': 'Priority · Code · Readiness · Materials · Bottleneck · ETA · Max Now',
        },
        'blocked': {
            'icon': '🔴',
            'title': 'Blocked + Unschedulable',
            'desc': (
                'Items where materials are unavailable with no ETA, plus items '
                'that cannot be scheduled (missing BOM config). Each shows a fix action.'
            ),
            'columns': 'Code · Product · Reason · Blocked Materials · Fix Action',
        },
        'timeline': {
            'icon': '📅',
            'title': 'Production timeline',
            'desc': (
                'Gantt chart showing each MO suggestion as a bar from start to completion date. '
                'Color-coded by readiness: green = ready, yellow = waiting, red = blocked. '
                'Red dashed line marks today.'
            ),
            'columns': 'Gantt chart + weekly production schedule table',
        },
        'overview': {
            'icon': '📊',
            'title': 'Overview & reconciliation',
            'desc': (
                'KPI cards (ready/waiting/blocked counts + at-risk values), '
                'urgency distribution bar, top 5 most urgent items, '
                'BOM type breakdown, and data reconciliation check.'
            ),
            'columns': 'KPIs · Urgency bar · Top urgent · BOM breakdown · Reconciliation',
        },
    }

    p = previews.get(tab_name)
    if p:
        st.markdown(f"### {p['icon']} {p['title']}")
        st.markdown(p['desc'])
        st.caption(f"**Columns:** {p['columns']}")

    st.caption(f"Production Planning Module v{VERSION}")


# =============================================================================
# SETTINGS TAB (TAB 0) — Phase A UX Upgrade
# =============================================================================

def _count_configured(config: ProductionConfig) -> dict:
    """Count configured vs required fields per group for progress display."""
    groups = {
        'lead_time': {
            'fields': [
                ('lead_time_cutting_days', 'Cutting lead time'),
                ('lead_time_repacking_days', 'Repacking lead time'),
                ('lead_time_kitting_days', 'Kitting lead time'),
            ],
            'label': 'Lead Time Setup',
            'icon': '📅',
        },
        'priority': {
            'fields': [
                ('priority_weight_time', 'Time urgency weight'),
                ('priority_weight_readiness', 'Readiness weight'),
                ('priority_weight_value', 'At-risk value weight'),
                ('priority_weight_customer', 'Customer linkage weight'),
            ],
            'label': 'Priority Weights',
            'icon': '⚖️',
        },
        'planning': {
            'fields': [
                ('planning_horizon_days', 'Planning horizon'),
            ],
            'label': 'Planning Parameters',
            'icon': '📋',
        },
    }

    total_required = 0
    total_configured = 0
    for gkey, g in groups.items():
        configured = 0
        for field_name, _ in g['fields']:
            val = getattr(config, field_name, None)
            if val is not None and val != 0:
                configured += 1
        g['configured'] = configured
        g['total'] = len(g['fields'])
        g['complete'] = configured == len(g['fields'])
        total_required += len(g['fields'])
        total_configured += configured

    return {
        'groups': groups,
        'total_required': total_required,
        'total_configured': total_configured,
        'all_complete': total_configured == total_required,
    }


def _render_progress_bar(progress: dict, config: ProductionConfig):
    """Render the progress bar replacing the wall of red X marks."""
    configured = progress['total_configured']
    total = progress['total_required']
    pct = round(configured / total * 100) if total > 0 else 0

    if config.is_ready:
        st.success(
            f"✅ All {total} required settings configured. Ready to generate MO suggestions."
        )
    else:
        # Progress bar with positive framing
        errors = config.validation_errors or []

        st.markdown(
            f"**{configured} of {total}** required settings configured"
        )
        st.progress(pct / 100, text=f"{pct}%")

        # Show validation errors compactly (not the missing list)
        if errors:
            for err in errors:
                st.warning(f"⚠️ {err}")


def _render_quick_start(config: ProductionConfig, lt_stats_df, historical_summary):
    """Render quick-start defaults bar for first-time setup."""
    if config.is_ready:
        return False

    # Build display text from historical data
    parts = []
    for bom_type in ('CUTTING', 'REPACKING', 'KITTING'):
        hist = historical_summary.get(bom_type) if historical_summary else None
        if hist and hist.get('total_mos', 0) >= 5:
            _avg = hist.get('avg_days', 0)
            avg = float(_avg) if _avg is not None and not pd.isna(_avg) else 0.0
            total = hist['total_mos']
            parts.append(f"{bom_type}: avg {avg:.1f}d ({total} MOs)")

    if parts:
        detail = ", ".join(parts)
        msg = (
            f"💡 **Quick start available.** "
            f"Historical data found: {detail}. "
            f"Apply recommended defaults based on your production history, then review and adjust."
        )
    else:
        msg = (
            "💡 **Quick start available.** "
            "Apply industry-standard defaults (lead times, priority weights, horizon), "
            "then review and adjust."
        )

    qs_cols = st.columns([5, 1])
    with qs_cols[0]:
        st.info(msg)
    with qs_cols[1]:
        clicked = st.button(
            "⚡ Apply Defaults",
            type="primary",
            use_container_width=True,
            key="apply_quick_start",
        )
    return clicked


def _build_historical_hint(lt_stats_df, bom_type: str) -> str:
    """Build inline hint text from historical stats for a BOM type."""
    if lt_stats_df is None or lt_stats_df.empty:
        return ""
    bom_rows = lt_stats_df[lt_stats_df['bom_type'] == bom_type] if 'bom_type' in lt_stats_df.columns else None
    if bom_rows is None or bom_rows.empty:
        return ""

    row = bom_rows.iloc[0]
    avg = row.get('avg_lead_time_days')
    mos = row.get('completed_mo_count', 0)
    if avg is not None and not pd.isna(avg):
        return f"📊 Historical: avg {float(avg):.1f}d from {int(mos) if not pd.isna(mos) else 0} completed MOs"
    return ""


def render_settings_tab(config: ProductionConfig, lead_time_stats_df: Optional[pd.DataFrame] = None):
    """
    Render the Settings tab — Phase A UX upgrade.

    Features:
    - Progress bar (replaces wall of red X marks)
    - Quick-start defaults from historical data
    - Collapsible groups with completion badges
    - Inline historical hints per field
    - Positive framing ("4 of 8 configured" not "8 errors")
    """
    st.markdown("### ⚙️ Production Planning Settings")
    st.caption(
        "Configure all required settings before running. "
        "No hidden defaults — every parameter is set explicitly by you."
    )

    # ── Compute progress ──
    progress = _count_configured(config)

    # ── Load historical summary for quick-start ──
    historical_summary = {}
    try:
        from .production_config import ProductionConfigLoader
        loader = ProductionConfigLoader()
        historical_summary = loader.load_historical_lead_time_summary()
    except Exception:
        pass

    # ── Quick-Start Bar ──
    quick_start_clicked = _render_quick_start(config, lead_time_stats_df, historical_summary)
    if quick_start_clicked:
        # Return quick-start values as changes — page will save them
        try:
            loader = ProductionConfigLoader()
            defaults = loader.get_recommended_defaults(historical_summary)
            return defaults.get('values', {})
        except Exception as e:
            st.error(f"Failed to compute defaults: {e}")

    # ── Progress Bar ──
    _render_progress_bar(progress, config)

    st.markdown("")

    # Track changes
    changes = {}
    groups = progress['groups']

    # =====================================================================
    # GROUP 1: Lead Time Setup
    # =====================================================================
    lt_info = groups['lead_time']
    lt_badge = "✅ Complete" if lt_info['complete'] else f"⚠️ {lt_info['total'] - lt_info['configured']} remaining"

    with st.expander(
        f"{lt_info['icon']} **{lt_info['label']}** — {lt_badge}",
        expanded=not lt_info['complete'],
    ):
        st.caption(
            "Production lead time per BOM type in calendar days. "
            "These are required — scheduling cannot proceed without them."
        )

        lt_cols = st.columns(3)
        for i, (bom_key, bom_label) in enumerate([
            ('cutting', 'CUTTING'), ('repacking', 'REPACKING'), ('kitting', 'KITTING')
        ]):
            current = getattr(config, f'lead_time_{bom_key}_days', None)
            hint = _build_historical_hint(lead_time_stats_df, bom_label)
            with lt_cols[i]:
                val = st.number_input(
                    f"{bom_label.title()} (days)",
                    min_value=0, max_value=90,
                    value=current if current is not None else 0,
                    step=1, key=f"lt_{bom_key}",
                    help=f"Calendar days to complete {bom_label.lower()} production",
                )
                if hint:
                    st.caption(hint)
                if val != current and val > 0:
                    changes[f'LEAD_TIME.{bom_label}.DAYS'] = val

        # Historical override (advanced — collapsed by default)
        st.markdown("")
        use_hist_lt = st.checkbox(
            "Use historical lead time override when data is sufficient",
            value=bool(config.lead_time_use_historical),
            key="use_hist_lt",
            help=(
                "When enabled: if a product (or BOM type) has enough completed MOs, "
                "override the config value with historical average."
            ),
        )
        if use_hist_lt != config.lead_time_use_historical:
            changes['LEAD_TIME.USE_HISTORICAL'] = use_hist_lt

        if use_hist_lt:
            hc1, hc2 = st.columns(2)
            with hc1:
                min_prod = st.number_input(
                    "Min MOs per product", min_value=1, max_value=100,
                    value=config.lead_time_min_history_product or 5,
                    key="lt_min_prod",
                )
                if min_prod != config.lead_time_min_history_product:
                    changes['LEAD_TIME.MIN_HISTORY_COUNT_PRODUCT'] = min_prod
            with hc2:
                min_bom = st.number_input(
                    "Min MOs per BOM type", min_value=1, max_value=500,
                    value=config.lead_time_min_history_bom_type or 10,
                    key="lt_min_bom",
                )
                if min_bom != config.lead_time_min_history_bom_type:
                    changes['LEAD_TIME.MIN_HISTORY_COUNT_BOM_TYPE'] = min_bom

    # =====================================================================
    # GROUP 2: Priority Weights
    # =====================================================================
    pw_info = groups['priority']
    pw_badge = "✅ Complete" if pw_info['complete'] else f"⚠️ {pw_info['total'] - pw_info['configured']} remaining"

    with st.expander(
        f"{pw_info['icon']} **{pw_info['label']}** — {pw_badge}",
        expanded=not pw_info['complete'] and lt_info['complete'],
    ):
        st.caption(
            "How to rank MO urgency. Weights must sum to exactly 100%. "
            "Recommended: Time 40%, Readiness 25%, Value 20%, Customer 15%."
        )

        pw_cols = st.columns(4)
        weight_keys = [
            ('priority_weight_time', 'Time urgency', 'PRIORITY.WEIGHT.TIME_URGENCY'),
            ('priority_weight_readiness', 'Material readiness', 'PRIORITY.WEIGHT.MATERIAL_READINESS'),
            ('priority_weight_value', 'At-risk value', 'PRIORITY.WEIGHT.AT_RISK_VALUE'),
            ('priority_weight_customer', 'Customer linkage', 'PRIORITY.WEIGHT.CUSTOMER_LINKAGE'),
        ]
        weight_sum = 0
        for i, (attr, label, config_key) in enumerate(weight_keys):
            current = getattr(config, attr, None) or 0
            with pw_cols[i]:
                val = st.number_input(
                    f"{label} (%)", min_value=0, max_value=100,
                    value=current, step=5, key=f"pw_{attr}",
                )
                weight_sum += val
                if val != current:
                    changes[config_key] = val

        if weight_sum == 100:
            st.success(f"Total: **{weight_sum}%** ✅")
        elif weight_sum > 0:
            st.error(f"Total: **{weight_sum}%** — must be exactly 100%")
        else:
            st.caption("Total: 0% — enter weights above")

    # =====================================================================
    # GROUP 3: Planning Parameters
    # =====================================================================
    pl_info = groups['planning']
    pl_badge = "✅ Complete" if pl_info['complete'] else f"⚠️ {pl_info['total'] - pl_info['configured']} remaining"

    with st.expander(
        f"{pl_info['icon']} **{pl_info['label']}** — {pl_badge}",
        expanded=not pl_info['complete'] and lt_info['complete'] and pw_info['complete'],
    ):
        pp_cols = st.columns(2)
        with pp_cols[0]:
            horizon = st.number_input(
                "Planning horizon (days)",
                min_value=14, max_value=365,
                value=config.planning_horizon_days or 60,
                key="plan_horizon",
                help="Fallback demand date = today + this value when GAP has no period data.",
            )
            if horizon != config.planning_horizon_days:
                changes['PLANNING.DEFAULT_HORIZON_DAYS'] = horizon

        with pp_cols[1]:
            allow_partial = st.checkbox(
                "Allow partial production",
                value=bool(config.allow_partial_production),
                key="allow_partial",
                help="Show max producible quantity when materials are partially available.",
            )
            if allow_partial != config.allow_partial_production:
                changes['PLANNING.ALLOW_PARTIAL_PRODUCTION'] = allow_partial

    # =====================================================================
    # GROUP 4: Yield Setup (optional — not counted in required progress)
    # =====================================================================
    with st.expander("📊 **Yield Setup** — Optional", expanded=False):
        st.caption(
            "Optional: override BOM scrap rates with actual yield from completed MOs. "
            "Leave off to use BOM-level scrap rates only."
        )

        use_hist_yield = st.checkbox(
            "Use historical yield override",
            value=bool(config.yield_use_historical),
            key="use_hist_yield",
            help="Override BOM scrap_rate with actual yield from completed MOs.",
        )
        if use_hist_yield != config.yield_use_historical:
            changes['YIELD.USE_HISTORICAL'] = use_hist_yield

        if use_hist_yield:
            min_yield_hist = st.number_input(
                "Min completed MOs for yield data", min_value=1, max_value=100,
                value=config.yield_min_history_count or 5,
                key="yield_min_hist",
            )
            if min_yield_hist != config.yield_min_history_count:
                changes['YIELD.MIN_HISTORY_COUNT'] = min_yield_hist

    # =====================================================================
    # SAVE BUTTON
    # =====================================================================
    st.markdown("")
    if changes:
        st.info(f"📝 **{len(changes)} unsaved change(s).** Click Save to apply.")

    save_col, _ = st.columns([1, 3])
    with save_col:
        save_clicked = st.button(
            "💾 Save Settings", type="primary",
            use_container_width=True, key="save_config",
        )

    return changes if save_clicked and changes else None


def _render_lead_time_reference(lt_stats_df: pd.DataFrame):
    """Show historical lead time stats as read-only reference table."""
    if lt_stats_df is None or lt_stats_df.empty:
        st.caption("No historical lead time data available yet.")
        return

    display_cols = []
    col_map = {}
    for col in ['bom_type', 'product_count', 'completed_mo_count', 'avg_lead_time_days',
                 'min_lead_time_days', 'max_lead_time_days']:
        if col in lt_stats_df.columns:
            display_cols.append(col)
            col_map[col] = col.replace('_', ' ').title()

    if not display_cols:
        return

    df = lt_stats_df[display_cols].copy()
    df.columns = [col_map.get(c, c) for c in df.columns]

    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        height=min(35 * len(df) + 38, 180),
    )


# =============================================================================
# KPI CARDS
# =============================================================================

def render_mo_kpi_cards(result: MOSuggestionResult):
    """Render top-level KPI cards for Production Planning."""
    m = result.get_summary()

    cols = st.columns(5)

    with cols[0]:
        ready = m.get('ready_count', 0)
        total = m.get('total_mo_lines', 0)
        st.metric(
            label="✅ Ready",
            value=f"{ready}",
            delta=f"of {total} total MO lines",
            delta_color="off",
        )

    with cols[1]:
        waiting = m.get('waiting_count', 0)
        st.metric(
            label="⏳ Waiting",
            value=f"{waiting}",
            help="Materials partially available — waiting for remaining supply",
        )

    with cols[2]:
        blocked = m.get('blocked_count', 0)
        unsch = m.get('unschedulable_count', 0)
        st.metric(
            label="🔴 Blocked",
            value=f"{blocked}",
            delta=f"+{unsch} unschedulable" if unsch > 0 else None,
            delta_color="off",
        )

    with cols[3]:
        value = m.get('total_at_risk_value', 0)
        st.metric(
            label="💰 At-Risk Value",
            value=f"${value:,.0f}",
        )

    with cols[4]:
        overdue = m.get('overdue_count', 0)
        delayed = m.get('delayed_count', 0)
        if overdue > 0:
            st.metric(
                label="🚨 Overdue",
                value=f"{overdue}",
                delta=f"{delayed} delayed total",
                delta_color="off",
            )
        elif delayed > 0:
            st.metric(label="⚠️ Delayed", value=f"{delayed}")
        else:
            st.metric(label="✅ On Track", value="All")


# =============================================================================
# URGENCY DISTRIBUTION BAR
# =============================================================================

def render_urgency_bar(result: MOSuggestionResult):
    """Horizontal urgency distribution bar using st.columns + markdown."""
    dist = result.get_urgency_distribution()
    if not dist:
        return

    total = sum(dist.values())
    if total == 0:
        return

    order = ['OVERDUE', 'CRITICAL', 'URGENT', 'THIS_WEEK', 'PLANNED']
    parts = []
    for level in order:
        count = dist.get(level, 0)
        if count > 0:
            cfg = URGENCY_LEVELS.get(level, {})
            icon = cfg.get('icon', '⬜')
            label = cfg.get('label', level)
            color = cfg.get('color', '#999')
            pct = round(count / total * 100)
            parts.append((level, label, icon, color, count, pct))

    if not parts:
        return

    bar_html = '<div style="display:flex;width:100%;height:32px;border-radius:6px;overflow:hidden;">'
    for level, label, icon, color, count, pct in parts:
        bar_html += (
            f'<div style="width:{pct}%;background:{color};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:12px;font-weight:600;color:#333;min-width:40px;">'
            f'{icon} {count}</div>'
        )
    bar_html += '</div>'

    st.markdown(bar_html, unsafe_allow_html=True)

    # Legend
    legend = " · ".join(
        f"{icon} {label}: **{count}** ({pct}%)"
        for _, label, icon, _, count, pct in parts
    )
    st.caption(legend)


# =============================================================================
# MO LINES TABLE
# =============================================================================

def render_mo_lines_table(
    lines: List[MOLineItem],
    title: str = "MO Lines",
    show_readiness: bool = True,
    show_action: bool = True,
    max_rows: int = 200,
):
    """Render a table of MO line items."""
    if not lines:
        st.info(f"No {title.lower()} items.")
        return

    rows = []
    for l in lines[:max_rows]:
        urgency_cfg = URGENCY_LEVELS.get(l.urgency_level, {})
        readiness_cfg = READINESS_STATUS.get(l.readiness_status, {})

        row = {
            'priority': round(l.priority_score, 1),
            'urgency': f"{urgency_cfg.get('icon', '')} {urgency_cfg.get('label', l.urgency_level)}",
            'code': l.pt_code,
            'product': l.product_name[:40] if l.product_name else '',
            'brand': l.brand,
            'bom_type': l.bom_type,
            'shortage': round(l.shortage_qty),
            'suggested': round(l.suggested_qty),
            'batches': l.batches_needed,
            'uom': l.uom,
        }

        if show_readiness:
            row['readiness'] = (
                f"{readiness_cfg.get('icon', '')} "
                f"{readiness_cfg.get('label', l.readiness_status)}"
            )
            row['materials'] = f"{l.ready_materials}/{l.total_materials}"
            if l.max_producible_now > 0 and l.readiness_status != 'READY':
                row['max_now'] = round(l.max_producible_now)
            else:
                row['max_now'] = None

        row['demand_date'] = str(l.demand_date) if l.demand_date else ''
        row['start'] = str(l.actual_start) if l.actual_start else ''
        row['completion'] = str(l.expected_completion) if l.expected_completion else ''
        row['lt_days'] = l.lead_time_days
        row['at_risk'] = round(l.at_risk_value)

        if show_action:
            action_cfg = MO_ACTION_TYPES.get(l.action_type, {})
            row['action'] = f"{action_cfg.get('icon', '')} {action_cfg.get('label', l.action_type)}"

        if l.existing_mo_count > 0:
            row['existing_mos'] = f"{l.existing_mo_count} ({l.existing_mo_remaining_qty:,.0f})"
        else:
            row['existing_mos'] = '-'

        rows.append(row)

    df = pd.DataFrame(rows)

    col_config = {
        'priority': st.column_config.NumberColumn('Priority', format="%.1f", width='small'),
        'urgency': st.column_config.TextColumn('Urgency', width='medium'),
        'code': st.column_config.TextColumn('Code', width='small'),
        'product': st.column_config.TextColumn('Product', width='large'),
        'brand': st.column_config.TextColumn('Brand', width='small'),
        'bom_type': st.column_config.TextColumn('BOM', width='small'),
        'shortage': st.column_config.NumberColumn('Shortage', format="%d"),
        'suggested': st.column_config.NumberColumn('Suggested Qty', format="%d"),
        'batches': st.column_config.NumberColumn('Batches', format="%d", width='small'),
        'uom': st.column_config.TextColumn('UOM', width='small'),
        'demand_date': st.column_config.TextColumn('Demand Date', width='medium'),
        'start': st.column_config.TextColumn('Start', width='medium'),
        'completion': st.column_config.TextColumn('Completion', width='medium'),
        'lt_days': st.column_config.NumberColumn('LT (d)', format="%d", width='small'),
        'at_risk': st.column_config.NumberColumn('At Risk ($)', format="%d"),
        'existing_mos': st.column_config.TextColumn('Existing MOs', width='medium'),
    }

    if show_readiness:
        col_config['readiness'] = st.column_config.TextColumn('Readiness', width='medium')
        col_config['materials'] = st.column_config.TextColumn('Mat. Ready', width='small')
        col_config['max_now'] = st.column_config.NumberColumn('Max Now', format="%d", width='small')

    if show_action:
        col_config['action'] = st.column_config.TextColumn('Action', width='large')

    height = min(35 * len(df) + 38, 600)

    st.dataframe(
        df,
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        height=height,
    )

    if len(lines) > max_rows:
        st.caption(f"Showing {max_rows} of {len(lines)} items.")


# =============================================================================
# UNSCHEDULABLE PANEL
# =============================================================================

def render_unschedulable_panel(result: MOSuggestionResult):
    """Render panel for items that cannot be scheduled (missing config)."""
    if not result.has_unschedulable():
        return

    items = result.unschedulable_items
    st.markdown(f"##### ⚠️ Cannot Schedule — {len(items)} Items")
    st.caption("These products need config setup before MO suggestions can be generated.")

    rows = []
    for u in items:
        reason_cfg = UNSCHEDULABLE_REASONS.get(u.reason_code, {})
        rows.append({
            'code': u.pt_code,
            'product': u.product_name[:40] if u.product_name else '',
            'brand': u.brand,
            'shortage': round(u.shortage_qty),
            'uom': u.uom,
            'reason': f"{reason_cfg.get('icon', '❓')} {reason_cfg.get('label', u.reason_code)}",
            'detail': u.reason_detail,
            'action': u.action,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'code': st.column_config.TextColumn('Code', width='small'),
            'product': st.column_config.TextColumn('Product', width='large'),
            'shortage': st.column_config.NumberColumn('Shortage', format="%d"),
            'reason': st.column_config.TextColumn('Reason', width='large'),
            'action': st.column_config.TextColumn('Fix', width='large'),
        },
        hide_index=True, use_container_width=True,
        height=min(35 * len(df) + 38, 300),
    )


# =============================================================================
# MATERIAL READINESS HEATMAP
# =============================================================================

def render_readiness_heatmap(result: MOSuggestionResult):
    """Render material readiness matrix — product × material coverage %."""
    df = result.get_readiness_matrix_df()
    if df.empty:
        st.info("No material readiness data available.")
        return

    st.markdown("##### 📋 Material Readiness Matrix")
    st.caption("Coverage % for each product × material combination. Red = blocked, Yellow = partial, Green = ready.")

    # Pivot: product on rows, material on columns, value = coverage_pct
    try:
        pivot = df.pivot_table(
            index='pt_code', columns='material_pt_code',
            values='coverage_pct', aggfunc='first',
        )
    except Exception:
        # Fallback: show flat table
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    if pivot.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    # Color map: 0=red → 50=yellow → 100=green
    def _color_cell(val):
        if pd.isna(val):
            return 'background-color: #f0f0f0'
        if val >= 100:
            return 'background-color: #c6efce; color: #006100'
        elif val >= 50:
            return 'background-color: #ffeb9c; color: #9c5700'
        else:
            return 'background-color: #ffc7ce; color: #9c0006'

    # Use .map() (pandas ≥2.1) with fallback to .applymap() for older versions
    try:
        styled = pivot.style.map(_color_cell).format('{:.0f}%', na_rep='-')
    except AttributeError:
        styled = pivot.style.applymap(_color_cell).format('{:.0f}%', na_rep='-')

    # Limit size for readability
    if len(pivot) <= 50 and len(pivot.columns) <= 30:
        st.dataframe(styled, use_container_width=True, height=min(35 * len(pivot) + 38, 500))
    else:
        st.warning(f"Matrix is large ({len(pivot)} products × {len(pivot.columns)} materials). Showing flat view.")
        display_df = df[['pt_code', 'material_pt_code', 'coverage_pct', 'status',
                         'required_qty', 'available_now']].copy()
        styled_flat = _styled_dataframe(
            display_df, qty_cols=['required_qty', 'available_now'],
            pct_cols=['coverage_pct'],
        )
        st.dataframe(styled_flat, use_container_width=True, hide_index=True, height=500)

    # Contention callout
    contested = df[df['is_contested'] == True]
    if not contested.empty:
        mat_codes = contested['material_pt_code'].unique()
        st.warning(
            f"⚡ **Material contention detected** for {len(mat_codes)} material(s): "
            f"{', '.join(mat_codes[:5])}{'...' if len(mat_codes) > 5 else ''}. "
            f"Priority-based allocation applied."
        )


# =============================================================================
# TIMELINE CHART
# =============================================================================

def render_timeline_chart(result: MOSuggestionResult):
    """Render Gantt-style timeline using Plotly."""
    gantt_data = result.get_gantt_data()
    if not gantt_data:
        st.info("No timeline data available.")
        return

    st.markdown("##### 📅 Production Timeline")

    try:
        import plotly.figure_factory as ff
        import plotly.graph_objects as go

        # Build tasks for Plotly
        tasks = []
        annotations = []

        color_map = {
            'READY': '#2ecc71',
            'USE_ALTERNATIVE': '#27ae60',
            'PARTIAL_READY': '#f39c12',
            'BLOCKED': '#e74c3c',
        }

        for entry in gantt_data:
            if 'start' not in entry or 'end' not in entry:
                continue

            tasks.append({
                'Task': entry['product'][:35],
                'Start': entry['start'],
                'Finish': entry['end'],
                'Resource': entry.get('readiness', 'PLANNED'),
            })

        if not tasks:
            st.info("No items with scheduled dates for timeline.")
            return

        # Sort by start date
        tasks.sort(key=lambda t: t['Start'])

        # Limit to top 30 for readability
        if len(tasks) > 30:
            st.caption(f"Showing top 30 of {len(tasks)} items (sorted by start date).")
            tasks = tasks[:30]

        fig = ff.create_gantt(
            tasks,
            colors=color_map,
            index_col='Resource',
            show_colorbar=True,
            group_tasks=True,
            showgrid_x=True,
            showgrid_y=True,
        )

        # Add today line
        today_str = date.today().isoformat()
        fig.add_vline(
            x=today_str, line_dash="dash",
            line_color="red", line_width=2,
            annotation_text="Today",
        )

        fig.update_layout(
            height=max(300, len(tasks) * 28 + 100),
            margin=dict(l=10, r=10, t=30, b=30),
        )

        st.plotly_chart(fig, use_container_width=True)

    except ImportError:
        st.warning("Plotly not available. Install with: `pip install plotly`")
        _render_timeline_fallback(gantt_data)
    except Exception as e:
        logger.warning(f"Plotly Gantt failed: {e}")
        _render_timeline_fallback(gantt_data)


def _render_timeline_fallback(gantt_data):
    """Simple table fallback when Plotly unavailable."""
    rows = []
    for entry in gantt_data:
        rows.append({
            'product': entry.get('product', ''),
            'bom': entry.get('bom_type', ''),
            'readiness': entry.get('readiness', ''),
            'start': entry.get('start', ''),
            'end': entry.get('end', ''),
            'demand': entry.get('demand_date', ''),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=400)


# =============================================================================
# RECONCILIATION PANEL
# =============================================================================

def render_reconciliation_panel(result: MOSuggestionResult):
    """Render reconciliation summary — input = output accounting."""
    recon = result.get_reconciliation()

    with st.expander("🔍 Data Reconciliation", expanded=False):
        is_balanced = recon.get('is_balanced', False)
        if is_balanced:
            st.success("✅ Reconciliation balanced — all input items accounted for.")
        else:
            disc = recon.get('discrepancy', 0)
            st.error(f"❌ Reconciliation discrepancy: {disc} items unaccounted.")

        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("**Input:**")
            st.markdown(f"- Total input items: **{recon.get('total_input', 0)}**")
            st.markdown(f"- Skipped (validation): {recon.get('input_skipped_validation', 0)}")

        with rc2:
            st.markdown("**Output:**")
            st.markdown(f"- ✅ Ready: {recon.get('ready', 0)}")
            st.markdown(f"- ⏳ Waiting: {recon.get('waiting', 0)}")
            st.markdown(f"- 🔴 Blocked: {recon.get('blocked', 0)}")
            st.markdown(f"- ⚠️ Unschedulable: {recon.get('unschedulable', 0)}")
            errors = recon.get('processing_errors', 0)
            if errors:
                st.markdown(f"- ❗ Errors: {errors}")


# =============================================================================
# TOP URGENT ITEMS
# =============================================================================

def _render_top_urgent_items(result: MOSuggestionResult, top_n: int = 5):
    """Top N most urgent items — actionable quick view."""
    if not result.has_lines():
        return

    lines = sorted(result.all_lines, key=lambda l: (l.urgency_priority, -l.at_risk_value))
    top = lines[:top_n]

    st.markdown(f"##### 🚨 Top {min(top_n, len(top))} Most Urgent Items")

    rows = []
    for l in top:
        urgency_cfg = URGENCY_LEVELS.get(l.urgency_level, {})
        readiness_cfg = READINESS_STATUS.get(l.readiness_status, {})
        rows.append({
            'urgency': f"{urgency_cfg.get('icon', '')} {urgency_cfg.get('label', l.urgency_level)}",
            'code': l.pt_code,
            'product': l.product_name[:35] if l.product_name else '',
            'readiness': f"{readiness_cfg.get('icon', '')} {readiness_cfg.get('label', l.readiness_status)}",
            'qty': round(l.suggested_qty),
            'value': round(l.at_risk_value),
            'action': l.action_description[:50] if l.action_description else '',
        })

    df = pd.DataFrame(rows)
    styled = _styled_dataframe(df, qty_cols=['qty'], currency_cols=['value'])
    st.dataframe(
        styled,
        column_config={
            'urgency': st.column_config.TextColumn('Urgency', width='medium'),
            'code': st.column_config.TextColumn('Code', width='small'),
            'product': st.column_config.TextColumn('Product', width='large'),
            'readiness': st.column_config.TextColumn('Readiness', width='medium'),
            'qty': st.column_config.NumberColumn('Qty'),
            'value': st.column_config.NumberColumn('Value ($)'),
            'action': st.column_config.TextColumn('Action', width='large'),
        },
        hide_index=True, use_container_width=True,
        height=35 * len(df) + 38,
    )


# =============================================================================
# BOM TYPE DISTRIBUTION
# =============================================================================

def _render_bom_distribution(result: MOSuggestionResult):
    """Show BOM type breakdown."""
    m = result.get_summary()
    bom_dist = m.get('bom_type_distribution', {})
    if not bom_dist:
        return

    st.markdown("##### 🏭 BOM Type Breakdown")
    rows = []
    for bom_type, count in sorted(bom_dist.items()):
        bom_cfg = BOM_TYPES.get(bom_type, {})
        lines = result.get_lines_by_bom_type(bom_type)
        value = sum(l.at_risk_value for l in lines)
        ready = sum(1 for l in lines if l.readiness_status == 'READY')
        rows.append({
            'type': f"{bom_cfg.get('icon', '')} {bom_type}",
            'total': count,
            'ready': ready,
            'value': round(value),
        })

    df = pd.DataFrame(rows)
    styled = _styled_dataframe(df, currency_cols=['value'])
    st.dataframe(styled, hide_index=True, use_container_width=True,
                 height=35 * len(df) + 38)


# =============================================================================
# FILTER WARNING BANNER
# =============================================================================

def render_filter_warning_banner(result: MOSuggestionResult):
    """Persistent banner showing GAP filter deviations (if any)."""
    inp = result.input_summary or {}
    review = inp.get('filter_review', {})

    if not review:
        return

    # validate_gap_filters_for_production returns 'items' key, not 'deviations'
    filter_items = review.get('items', [])
    if not filter_items:
        return

    risk_icons = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}
    parts = [
        f"{risk_icons.get(item.get('risk', ''), '⚪')} {item.get('label', item.get('filter', ''))}"
        for item in filter_items[:5]
    ]

    msg = f"⚠️ **GAP Filter Deviations:** {' · '.join(parts)}"
    if len(filter_items) > 5:
        msg += f" · +{len(filter_items) - 5} more"

    st.warning(msg)


# =============================================================================
# TAB FRAGMENTS
# =============================================================================

def ready_tab_fragment(result: MOSuggestionResult):
    """Tab 1: Ready to Produce — items that can start immediately."""
    lines = result.ready_lines
    if not lines:
        st.success("🎉 No items currently ready to produce (check Waiting/Blocked tabs).")
        return

    total_value = sum(l.at_risk_value for l in lines)
    st.markdown(
        f"**{len(lines)} MO suggestions** ready to start production — "
        f"total at-risk value: **${total_value:,.0f}**"
    )

    render_mo_lines_table(
        lines, title="Ready to Produce",
        show_readiness=False, show_action=True,
    )


def waiting_tab_fragment(result: MOSuggestionResult):
    """Tab 2: Waiting for Materials — partial readiness."""
    lines = result.waiting_lines
    if not lines:
        st.info("No items waiting for materials.")
        return

    total_value = sum(l.at_risk_value for l in lines)
    st.markdown(
        f"**{len(lines)} items** waiting for materials — "
        f"total at-risk value: **${total_value:,.0f}**"
    )

    # Bottleneck summary
    bottlenecks = {}
    for l in lines:
        if l.bottleneck_material:
            bottlenecks.setdefault(l.bottleneck_material, []).append(l.pt_code)

    if bottlenecks:
        top_bn = sorted(bottlenecks.items(), key=lambda x: -len(x[1]))[:5]
        st.markdown("**Top bottleneck materials:**")
        for mat_code, products in top_bn:
            st.markdown(f"- `{mat_code}` — blocks {len(products)} product(s)")

    render_mo_lines_table(
        lines, title="Waiting for Materials",
        show_readiness=True, show_action=True,
    )


def blocked_tab_fragment(result: MOSuggestionResult):
    """Tab 3: Blocked — no materials available + unschedulable."""
    lines = result.blocked_lines

    if lines:
        total_value = sum(l.at_risk_value for l in lines)
        st.markdown(
            f"**{len(lines)} items** blocked — materials unavailable, no ETA. "
            f"At-risk value: **${total_value:,.0f}**"
        )

        render_mo_lines_table(
            lines, title="Blocked",
            show_readiness=True, show_action=True,
        )

    # Unschedulable sub-section
    if result.has_unschedulable():
        st.divider()
        render_unschedulable_panel(result)

    if not lines and not result.has_unschedulable():
        st.success("🎉 No blocked items!")


def timeline_tab_fragment(result: MOSuggestionResult):
    """Tab 4: Timeline — Gantt chart + weekly summary."""
    render_timeline_chart(result)

    # Weekly summary table
    if result.has_lines():
        _render_weekly_summary(result)


def _render_weekly_summary(result: MOSuggestionResult):
    """Group MO suggestions by week of expected start."""
    st.markdown("##### 📊 Weekly Production Schedule")

    rows = []
    for line in result.all_lines:
        if line.actual_start:
            iso = line.actual_start.isocalendar()
            week_key = f"W{iso[1]:02d}-{iso[0]}"
            week_start = line.actual_start - timedelta(days=line.actual_start.weekday())
        elif line.must_start_by:
            iso = line.must_start_by.isocalendar()
            week_key = f"W{iso[1]:02d}-{iso[0]}"
            week_start = line.must_start_by - timedelta(days=line.must_start_by.weekday())
        else:
            week_key = "Unscheduled"
            week_start = None

        rows.append({
            'week': week_key,
            'week_start': week_start,
            'readiness': line.readiness_status,
            'value': line.at_risk_value,
        })

    if not rows:
        return

    df = pd.DataFrame(rows)
    summary = df.groupby('week').agg(
        mo_count=('week', 'size'),
        ready=('readiness', lambda x: sum(1 for v in x if v in ('READY', 'USE_ALTERNATIVE'))),
        value=('value', 'sum'),
    ).reset_index()
    summary['value'] = summary['value'].round(0)

    styled = _styled_dataframe(summary, currency_cols=['value'])
    st.dataframe(
        styled,
        column_config={
            'week': st.column_config.TextColumn('Week', width='small'),
            'mo_count': st.column_config.NumberColumn('MO Lines', format="%d"),
            'ready': st.column_config.NumberColumn('Ready', format="%d"),
            'value': st.column_config.NumberColumn('Value ($)'),
        },
        hide_index=True, use_container_width=True,
        height=min(35 * len(summary) + 38, 400),
    )


def overview_tab_fragment(result: MOSuggestionResult):
    """Tab 5: Overview — KPIs + urgency + top urgent + BOM breakdown + reconciliation."""

    # Data flow summary
    inp = result.input_summary or {}
    recon = result.get_reconciliation()
    total_input = recon.get('total_input', 0)
    if total_input > 0:
        st.markdown(
            f"**Data flow:** GAP produced **{total_input}** manufacturing shortage items → "
            f"**{recon.get('ready', 0)}** ready, "
            f"{recon.get('waiting', 0)} waiting, "
            f"{recon.get('blocked', 0)} blocked, "
            f"{recon.get('unschedulable', 0)} unschedulable"
        )

    # KPIs
    render_mo_kpi_cards(result)

    # Urgency
    st.markdown("##### 📊 Urgency Distribution")
    render_urgency_bar(result)

    # Overdue alert
    overdue = result.get_overdue_lines()
    if overdue:
        overdue_value = sum(l.at_risk_value for l in overdue)
        st.error(
            f"🚨 **{len(overdue)} items are OVERDUE** — "
            f"must-start-by date has passed. "
            f"Total at-risk value: **${overdue_value:,.0f}**."
        )

    # Top urgent
    _render_top_urgent_items(result, top_n=5)

    # BOM breakdown
    _render_bom_distribution(result)

    # Reconciliation
    render_reconciliation_panel(result)


# =============================================================================
# EMPTY STATE (backward compat — page now uses render_empty_state_for_tab)
# =============================================================================

def render_empty_state():
    """Legacy — show generic empty state. Page now uses render_empty_state_for_tab."""
    render_empty_state_for_tab('ready', config_ready=False, gap_available=False)