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
# AUTH HELPER — get current user_id for audit trail
# =============================================================================

def _get_current_user_id() -> Optional[int]:
    """
    Get current user_id from session state for audit trail (created_by / updated_by).

    Reads from st.session_state where AuthManager stores user info after login.
    Returns None if not available (graceful — CRUD still works, just no audit).
    """
    try:
        # AuthManager stores user dict in session_state on login
        user = st.session_state.get('user')
        if user and isinstance(user, dict):
            uid = user.get('id') or user.get('user_id')
            return int(uid) if uid is not None else None
        # Fallback: some auth patterns store user_id directly
        uid = st.session_state.get('user_id')
        return int(uid) if uid is not None else None
    except Exception:
        return None


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
# BOM / PRODUCT DISPLAY HELPERS — consistent across all dialogs
# =============================================================================

def _format_bom_label(row, style: str = 'full') -> str:
    """
    Format BOM label for selectbox/dropdown display.

    Styles:
      'full'    → "BOM-202511-001 · VTI006000156 · Băng keo OPP 48mm (Vietape) · CUTTING · batch 1000"
      'compact' → "BOM-202511-001 — VTI006000156 · Băng keo OPP 48mm (Vietape)"
      'short'   → "VTI006000156 · Băng keo OPP 48mm"
    """
    bom_code = row.get('bom_code', '') or ''
    pt_code = row.get('pt_code', '') or ''
    product_name = (row.get('product_name', '') or '')[:40]
    package_size = row.get('package_size', '') or ''
    brand = row.get('brand', '') or ''
    bom_type = row.get('bom_type', '') or ''
    output_qty = row.get('output_qty', 0) or 0

    # Build product description: "Tên SP 48mm x 50m (Brand)"
    product_desc = product_name
    if package_size:
        product_desc = f"{product_name} {package_size}"
    brand_suffix = f" ({brand})" if brand else ""

    if style == 'full':
        parts = [bom_code, pt_code]
        if product_desc:
            parts.append(f"{product_desc}{brand_suffix}")
        parts.append(bom_type)
        if output_qty and float(output_qty) > 0:
            parts.append(f"batch {int(float(output_qty)):,}")
        return ' · '.join(parts)

    elif style == 'compact':
        parts = [bom_code, pt_code]
        if product_desc:
            parts.append(f"{product_desc}{brand_suffix}")
        return ' — '.join(parts[:2]) + (f' · {parts[2]}' if len(parts) > 2 else '')

    else:  # 'short'
        if product_desc:
            return f"{pt_code} · {product_desc}{brand_suffix}"
        return pt_code


def _format_product_display(row) -> str:
    """
    Format product column for overview table.

    Returns: "VTI006000156 · Băng keo OPP 48mm (Vietape)"
    Falls back to pt_code only if no extra info available.
    """
    pt_code = row.get('pt_code', row.get('Product', '')) or ''
    product_name = (row.get('product_name', '') or '')[:35]
    package_size = row.get('package_size', '') or ''
    brand = row.get('brand', '') or ''

    if not product_name:
        return pt_code

    desc = product_name
    if package_size:
        desc = f"{product_name} {package_size}"
    if brand:
        desc = f"{desc} ({brand})"
    return f"{pt_code} · {desc}"


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
    """Build inline hint text from historical stats for a BOM type.
    Aggregates across all BOMs of this type for the fallback hint."""
    if lt_stats_df is None or lt_stats_df.empty:
        return ""
    bom_rows = lt_stats_df[lt_stats_df['bom_type'] == bom_type] if 'bom_type' in lt_stats_df.columns else None
    if bom_rows is None or bom_rows.empty:
        return ""

    total_mos = bom_rows['completed_mo_count'].sum()
    if total_mos > 0:
        weighted_avg = (
            (bom_rows['avg_lead_time_days'] * bom_rows['completed_mo_count']).sum()
            / total_mos
        )
        n_boms = len(bom_rows)
        return (
            f"📊 Historical: avg {weighted_avg:.1f}d from "
            f"{int(total_mos)} MOs across {n_boms} BOM(s)"
        )
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
    # BOM LEAD TIME OVERVIEW (read-only — from bom_lead_times table)
    # =====================================================================
    _render_bom_lead_time_overview(lead_time_stats_df)

    # =====================================================================
    # GROUP 1: Lead Time Fallback Defaults
    # =====================================================================
    lt_info = groups['lead_time']
    lt_badge = "✅ Complete" if lt_info['complete'] else f"⚠️ {lt_info['total'] - lt_info['configured']} remaining"

    with st.expander(
        f"{lt_info['icon']} **Lead Time — Fallback Defaults** — {lt_badge}",
        expanded=not lt_info['complete'],
    ):
        st.caption(
            "Default lead time per BOM type. Used as fallback when a BOM "
            "does not have its own lead time set in the BOM Lead Times table above. "
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


def _render_bom_lead_time_overview(lead_time_stats_df: Optional[pd.DataFrame] = None):
    """
    BOM Lead Time management panel (Phase 2).

    Architecture:
    - Action buttons → open @st.dialog modals (no inline rendering)
    - Overview table → @st.fragment (sort changes only rerun table, not page)
    - Dialog save/cancel → st.rerun() closes dialog + refreshes page
    """
    # Try loading data
    bom_lt_df = pd.DataFrame()
    plants_df = pd.DataFrame()
    all_boms_df = pd.DataFrame()
    try:
        from .production_data_loader import get_production_data_loader
        loader = get_production_data_loader()
        bom_lt_df = loader.load_bom_lead_times()
        plants_df = loader.load_plants()
        all_boms_df = loader.load_all_active_boms()
    except Exception:
        pass

    has_bom_lt = not bom_lt_df.empty
    has_historical = (
        lead_time_stats_df is not None
        and not lead_time_stats_df.empty
        and 'bom_header_id' in lead_time_stats_df.columns
    )
    has_boms = not all_boms_df.empty

    if not has_bom_lt and not has_historical and not has_boms:
        return

    with st.expander("🏭 **BOM Lead Times** — per-BOM management", expanded=False):
        # Show toast from previous dialog action
        _toast = st.session_state.pop('_blt_toast', None)
        if _toast:
            st.toast(_toast, icon="✅")

        st.caption(
            "Lead time per BOM, managed by Production team. "
            "BOMs without a configured lead time use the fallback defaults below."
        )

        # ── Plants info ──
        if not plants_df.empty:
            plant_names = [
                f"{r['plant_code']} ({r['plant_name']})"
                for _, r in plants_df.iterrows()
            ]
            st.caption(f"🏭 Plants: {' · '.join(plant_names)}")

        # ── ACTION BUTTONS → open dialogs ──
        act_cols = st.columns([1, 1, 1, 2])

        with act_cols[0]:
            if st.button(
                "📥 Bulk Fill from Historical",
                key="blt_bulk_fill",
                help="Auto-fill lead times for unconfigured BOMs using historical avg.",
            ):
                _bulk_fill_dialog(lead_time_stats_df, bom_lt_df, all_boms_df)

        with act_cols[1]:
            if st.button("✏️ Edit BOM Lead Time", key="blt_show_editor"):
                _bom_lt_editor_dialog(all_boms_df, plants_df, bom_lt_df, lead_time_stats_df)

        with act_cols[2]:
            if st.button("🏭 Manage Plants", key="blt_show_plant"):
                _manage_plants_dialog(plants_df)

        # ── OVERVIEW TABLE (as @st.fragment — sort doesn't rerun page) ──
        rows = _build_overview_rows(bom_lt_df, lead_time_stats_df, has_bom_lt, has_historical,
                                    all_boms_df=all_boms_df)
        _bom_lt_overview_table(rows, has_bom_lt)


def _build_overview_rows(bom_lt_df, lead_time_stats_df, has_bom_lt, has_historical,
                         all_boms_df=None):
    """Build rows for the BOM LT overview table.

    Uses all_boms_df as enrichment source for product_name, package_size, brand.
    """
    rows = []

    # Build product info lookup from all_boms_df: bom_header_id → {product_name, package_size, brand, ...}
    product_lookup = {}
    if all_boms_df is not None and not all_boms_df.empty:
        for _, row in all_boms_df.iterrows():
            bom_id = row.get('bom_header_id')
            if bom_id is not None and not pd.isna(bom_id):
                product_lookup[int(bom_id)] = {
                    'product_name': row.get('product_name', '') or '',
                    'package_size': row.get('package_size', '') or '',
                    'brand': row.get('brand', '') or '',
                    'standard_uom': row.get('standard_uom', '') or '',
                    'output_qty': row.get('output_qty', 0) or 0,
                }

    def _product_display(bom_id, pt_code, fallback_name=''):
        """Build enriched product display from lookup."""
        info = product_lookup.get(int(bom_id) if bom_id is not None and not pd.isna(bom_id) else -1, {})
        name = info.get('product_name', fallback_name) or fallback_name
        pkg = info.get('package_size', '')
        brand = info.get('brand', '')

        if not name:
            return str(pt_code or '')

        desc = f"{pt_code} · {name[:30]}"
        if pkg:
            desc += f" {pkg}"
        if brand:
            desc += f" ({brand})"
        return desc

    # Track which bom_header_ids have configured LT
    configured_bom_ids = set()

    if has_bom_lt:
        for _, row in bom_lt_df.iterrows():
            bom_id = row.get('bom_header_id')
            configured_bom_ids.add(bom_id)
            eff = row.get('effective_date')
            r = {
                '_blt_id': int(row['bom_lead_time_id']) if pd.notna(row.get('bom_lead_time_id')) else None,
                'BOM Code': row.get('bom_code', ''),
                'Type': row.get('bom_type', ''),
                'Product': _product_display(bom_id, row.get('pt_code', ''), row.get('product_name', '')),
                'Std LT': f"{int(row['standard_lead_time_days'])}d",
                'Min': f"{int(row['minimum_lead_time_days'])}d" if pd.notna(row.get('minimum_lead_time_days')) else '—',
                'Max': f"{int(row['maximum_lead_time_days'])}d" if pd.notna(row.get('maximum_lead_time_days')) else '—',
                'Plant': row.get('plant_name', 'Global') if pd.notna(row.get('plant_name')) else 'Global',
                'Source': row.get('source', ''),
                'Effective': str(eff) if pd.notna(eff) else '—',
            }

            if has_historical:
                _enrich_with_historical(r, bom_id, lead_time_stats_df)

            rows.append(r)

    # Add BOMs from historical that don't have configured LT
    if has_historical:
        seen_boms = set(configured_bom_ids)
        for _, row in lead_time_stats_df.iterrows():
            bom_id = row.get('bom_header_id')
            if bom_id is None or pd.isna(bom_id) or bom_id in seen_boms:
                continue
            seen_boms.add(bom_id)
            avg = row.get('avg_lead_time_days')
            mos = row.get('completed_mo_count', 0)
            h_min = row.get('min_lead_time_days')
            h_max = row.get('max_lead_time_days')
            h_std = row.get('stddev_lead_time_days')

            r = {
                '_blt_id': None,
                'BOM Code': row.get('bom_code', ''),
                'Type': row.get('bom_type', ''),
                'Product': _product_display(bom_id, row.get('pt_code', '')),
            }
            if has_bom_lt:
                # Mixed mode: some configured, some not
                r['Std LT'] = '— (not set)'
                r['Min'] = '—'
                r['Max'] = '—'
                r['Plant'] = '—'
                r['Source'] = '—'
                r['Effective'] = '—'

            r['Hist Avg'] = f"{float(avg):.1f}d" if pd.notna(avg) else '—'
            r['Hist Min'] = f"{int(h_min)}d" if pd.notna(h_min) else '—'
            r['Hist Max'] = f"{int(h_max)}d" if pd.notna(h_max) else '—'
            r['Hist σ'] = f"{float(h_std):.1f}" if pd.notna(h_std) else '—'
            r['MOs'] = int(mos) if pd.notna(mos) else 0
            rows.append(r)

    return rows


def _enrich_with_historical(r: dict, bom_id, lead_time_stats_df):
    """Add Hist Avg/Min/Max/σ/MOs to a row dict from lead_time_stats_df."""
    hist_row = lead_time_stats_df[lead_time_stats_df['bom_header_id'] == bom_id]
    if not hist_row.empty:
        h = hist_row.iloc[0]
        avg = h.get('avg_lead_time_days')
        mos = h.get('completed_mo_count', 0)
        h_min = h.get('min_lead_time_days')
        h_max = h.get('max_lead_time_days')
        h_std = h.get('stddev_lead_time_days')
        if pd.notna(avg):
            r['Hist Avg'] = f"{float(avg):.1f}d"
            r['Hist Min'] = f"{int(h_min)}d" if pd.notna(h_min) else '—'
            r['Hist Max'] = f"{int(h_max)}d" if pd.notna(h_max) else '—'
            r['Hist σ'] = f"{float(h_std):.1f}" if pd.notna(h_std) else '—'
            r['MOs'] = int(mos) if pd.notna(mos) else 0
            return
    r['Hist Avg'] = '—'
    r['Hist Min'] = '—'
    r['Hist Max'] = '—'
    r['Hist σ'] = '—'
    r['MOs'] = 0


# =============================================================================
# BOM LEAD TIME — OVERVIEW TABLE FRAGMENT
# =============================================================================

@st.fragment
def _bom_lt_overview_table(rows: list, has_bom_lt: bool):
    """
    Overview table rendered as @st.fragment — sort radio changes only rerun
    this fragment, not the full page. Delete button opens a dialog.
    """
    if not rows:
        st.info(
            "No BOM lead time data available yet. "
            "Configure per-BOM lead times or use fallback defaults below."
        )
        return

    df = pd.DataFrame(rows)
    display_df = df.drop(columns=['_blt_id'], errors='ignore')

    # Drop noise columns when no BOM LT configured
    if not has_bom_lt:
        drop_cols = [c for c in ['Std LT', 'Min', 'Max', 'Plant', 'Source', 'Effective']
                     if c in display_df.columns]
        display_df = display_df.drop(columns=drop_cols)

    # Sort options — interaction only reruns this fragment
    sort_options = ['MOs (most used first)', 'BOM Type', 'Unconfigured first']
    if has_bom_lt:
        sort_options.append('Source')
    sort_choice = st.radio(
        "Sort by:", sort_options, key="blt_overview_sort",
        horizontal=True, label_visibility="collapsed",
    )

    if sort_choice == 'BOM Type' and 'Type' in display_df.columns:
        display_df = display_df.sort_values(
            ['Type', 'BOM Code'], ascending=True,
        ).reset_index(drop=True)
    elif sort_choice == 'Unconfigured first':
        display_df['_sort'] = df['_blt_id'].apply(
            lambda x: 0 if pd.isna(x) or x is None else 1
        )
        display_df = display_df.sort_values(
            ['_sort', 'Type', 'BOM Code'], ascending=True,
        ).drop(columns=['_sort']).reset_index(drop=True)
    elif sort_choice == 'Source' and 'Source' in display_df.columns:
        display_df = display_df.sort_values(
            ['Source', 'Type', 'BOM Code'], ascending=True,
        ).reset_index(drop=True)
    else:
        if 'MOs' in display_df.columns:
            display_df = display_df.sort_values('MOs', ascending=False).reset_index(drop=True)

    st.dataframe(display_df, hide_index=True, use_container_width=True,
                 height=min(35 * len(display_df) + 38, 400))

    # Summary
    configured = sum(1 for r in rows if r.get('_blt_id') is not None)
    total = len(rows)
    if configured == total and total > 0:
        st.success(f"✅ {configured}/{total} BOMs have lead time configured")
    elif configured > 0:
        st.info(
            f"📊 {configured}/{total} BOMs configured · "
            f"**{total - configured}** using fallback defaults"
        )
    else:
        st.warning(
            f"⚠️ No BOM-level lead times configured yet — "
            f"all {total} BOMs using fallback defaults below. "
            f"Set per-BOM lead times for more accurate scheduling."
        )

    # Delete button → opens dialog
    configured_rows = [r for r in rows if r.get('_blt_id') is not None]
    if configured_rows:
        if st.button("🗑️ Remove BOM Lead Time", key="blt_show_delete"):
            _delete_bom_lt_dialog(configured_rows)


# =============================================================================
# BOM LEAD TIME — DELETE DIALOG
# =============================================================================

@st.dialog("Remove BOM Lead Time")
def _delete_bom_lt_dialog(configured_rows: list):
    """Dialog to select and delete a BOM lead time, or undo bulk fill."""
    st.caption(
        "Remove a configured BOM lead time. "
        "The BOM will fall back to the default lead time setting below."
    )

    options = {}
    for r in configured_rows:
        blt_id = r.get('_blt_id')
        if blt_id is None:
            continue
        label = (
            f"{r.get('BOM Code', '')} — {r.get('Product', '')} "
            f"({r.get('Type', '')}, {r.get('Std LT', '')}, "
            f"Plant: {r.get('Plant', 'Global')})"
        )
        options[label] = blt_id

    if not options:
        st.info("No configured BOM lead times to remove.")
        return

    selected_label = st.selectbox(
        "Select BOM lead time to remove",
        options=list(options.keys()),
        key="dlg_del_select",
    )
    selected_blt_id = options.get(selected_label)

    del_cols = st.columns([1, 1, 2])
    with del_cols[0]:
        if st.button("🗑️ Delete", key="dlg_del_confirm", type="primary"):
            if selected_blt_id is not None:
                try:
                    from .production_data_loader import get_production_data_loader
                    loader = get_production_data_loader()
                    ok = loader.delete_bom_lead_time(selected_blt_id)
                    if ok:
                        st.session_state['_blt_toast'] = f"Removed BOM lead time (id={selected_blt_id})"
                        st.rerun()
                    else:
                        st.error("Delete failed — row not found or already deleted.")
                except Exception as e:
                    st.error(f"Delete failed: {e}")
    with del_cols[1]:
        if st.button("Cancel", key="dlg_del_cancel"):
            st.rerun()

    # Undo Bulk Fill section
    bulk_filled = [r for r in configured_rows if r.get('Source') == 'HISTORICAL_AVG']
    if bulk_filled:
        st.divider()
        st.caption(
            f"**Undo Bulk Fill:** {len(bulk_filled)} BOM lead time(s) were auto-filled. "
            f"Clearing them reverts all to fallback defaults."
        )
        if st.button(
            f"🗑️ Clear All Bulk-Filled ({len(bulk_filled)})",
            key="dlg_undo_bulk",
        ):
            try:
                from .production_data_loader import get_production_data_loader
                loader = get_production_data_loader()
                count, err = loader.bulk_delete_bom_lead_times_by_source('HISTORICAL_AVG')
                if err:
                    st.error(f"Failed: {err}")
                elif count > 0:
                    st.session_state['_blt_toast'] = f"Cleared {count} bulk-filled BOM lead times"
                    st.rerun()
                else:
                    st.info("No bulk-filled rows found to clear.")
            except Exception as e:
                st.error(f"Clear failed: {e}")



# =============================================================================
# BULK FILL DIALOG
# =============================================================================

@st.dialog("Bulk Fill from Historical", width="large")
def _bulk_fill_dialog(lead_time_stats_df, bom_lt_df, all_boms_df):
    """
    Dialog: auto-fill BOM lead times from historical averages.
    Only fills BOMs without existing config. Preview → Confirm.
    """
    import math

    if lead_time_stats_df is None or lead_time_stats_df.empty:
        st.warning("No historical data available for bulk fill.")
        return

    if 'bom_header_id' not in lead_time_stats_df.columns:
        st.warning("Historical data missing bom_header_id — recreate production_lead_time_stats_view.")
        return

    # Build product lookup from all_boms_df for enriched display
    product_lookup = {}
    if all_boms_df is not None and not all_boms_df.empty:
        for _, r in all_boms_df.iterrows():
            bid = r.get('bom_header_id')
            if bid is not None and not pd.isna(bid):
                product_lookup[int(bid)] = {
                    'bom_code': r.get('bom_code', ''),
                    'pt_code': r.get('pt_code', ''),
                    'product_name': (r.get('product_name', '') or '')[:35],
                    'package_size': r.get('package_size', '') or '',
                    'brand': r.get('brand', '') or '',
                    'bom_type': r.get('bom_type', ''),
                }

    # Find BOMs already configured
    already_configured = set()
    if not bom_lt_df.empty:
        already_configured = set(bom_lt_df['bom_header_id'].dropna().astype(int).tolist())

    # Build rows to insert
    rows_to_save = []
    skipped_already = 0
    skipped_no_data = 0

    for _, row in lead_time_stats_df.iterrows():
        bom_id = row.get('bom_header_id')
        if bom_id is None or pd.isna(bom_id):
            continue
        bom_id = int(bom_id)

        if bom_id in already_configured:
            skipped_already += 1
            continue

        avg = row.get('avg_lead_time_days')
        mos = row.get('completed_mo_count', 0)
        h_min = row.get('min_lead_time_days')
        h_max = row.get('max_lead_time_days')

        if avg is None or pd.isna(avg) or (mos is not None and not pd.isna(mos) and int(mos) < 1):
            skipped_no_data += 1
            continue

        std_lt = max(1, math.ceil(float(avg)))
        min_lt = max(1, int(h_min)) if h_min is not None and not pd.isna(h_min) else None
        max_lt = int(h_max) if h_max is not None and not pd.isna(h_max) else None
        if min_lt and std_lt < min_lt:
            std_lt = min_lt

        rows_to_save.append({
            'bom_header_id': bom_id,
            'standard_lead_time_days': std_lt,
            'minimum_lead_time_days': min_lt,
            'maximum_lead_time_days': max_lt,
            'source': 'HISTORICAL_AVG',
            'notes': f"Bulk filled from {int(mos)} completed MOs (avg {float(avg):.1f}d)",
            # Display-only fields (not sent to DB)
            '_bom_code': row.get('bom_code', '') or product_lookup.get(bom_id, {}).get('bom_code', ''),
            '_pt_code': row.get('pt_code', '') or product_lookup.get(bom_id, {}).get('pt_code', ''),
            '_product_name': product_lookup.get(bom_id, {}).get('product_name', ''),
            '_package_size': product_lookup.get(bom_id, {}).get('package_size', ''),
            '_brand': product_lookup.get(bom_id, {}).get('brand', ''),
            '_bom_type': row.get('bom_type', '') or product_lookup.get(bom_id, {}).get('bom_type', ''),
            '_mos': int(mos) if not pd.isna(mos) else 0,
        })

    if not rows_to_save:
        if skipped_already > 0 and skipped_no_data == 0:
            st.info(f"All {skipped_already} BOMs with historical data already have lead times configured.")
        elif skipped_already > 0 and skipped_no_data > 0:
            st.info(
                f"All BOMs with usable data already configured ({skipped_already} BOMs). "
                f"{skipped_no_data} BOM(s) skipped — have MOs but none COMPLETED yet."
            )
        elif skipped_no_data > 0:
            st.warning(
                f"No BOMs with sufficient historical data. "
                f"{skipped_no_data} BOM(s) have MOs but none COMPLETED yet — "
                f"complete at least 1 MO per BOM to enable historical fill. "
                f"Use **✏️ Edit BOM Lead Time** to set values manually."
            )
        else:
            st.warning("No historical production data found. Run production MOs first or set lead times manually.")
        return

    # Preview
    st.markdown(
        f"**{len(rows_to_save)} BOMs to fill** "
        f"(skipped {skipped_already} already configured, {skipped_no_data} no data)"
    )

    preview = pd.DataFrame([
        {
            'BOM Code': r.get('_bom_code', ''),
            'Type': r.get('_bom_type', ''),
            'Product': (
                f"{r.get('_pt_code', '')} · {r.get('_product_name', '')}"
                + (f" {r.get('_package_size', '')}" if r.get('_package_size') else '')
                + (f" ({r.get('_brand', '')})" if r.get('_brand') else '')
            ).strip() if r.get('_product_name') else r.get('_pt_code', ''),
            'Std LT': f"{r['standard_lead_time_days']}d",
            'Min': f"{r['minimum_lead_time_days']}d" if r.get('minimum_lead_time_days') else '—',
            'Max': f"{r['maximum_lead_time_days']}d" if r.get('maximum_lead_time_days') else '—',
            'MOs': r.get('_mos', 0),
        }
        for r in rows_to_save[:20]
    ])
    st.dataframe(preview, hide_index=True, use_container_width=True,
                 height=min(35 * len(preview) + 38, 250))
    if len(rows_to_save) > 20:
        st.caption(f"Showing 20 of {len(rows_to_save)} rows")

    # Confirm / Cancel
    cols = st.columns([1, 1, 2])
    with cols[0]:
        if st.button("✅ Confirm Bulk Fill", key="dlg_bulk_confirm", type="primary"):
            try:
                from .production_data_loader import get_production_data_loader
                loader = get_production_data_loader()
                success, errors = loader.bulk_save_bom_lead_times(
                    rows_to_save, user_id=_get_current_user_id(),
                )
                if success > 0:
                    msg = f"Saved {success}/{len(rows_to_save)} BOM lead times"
                    if errors:
                        msg += f" ({len(errors)} errors)"
                    st.session_state['_blt_toast'] = msg
                    st.rerun()
                else:
                    st.error(f"Failed to save. Errors: {'; '.join(errors[:5])}")
            except Exception as e:
                st.error(f"Bulk fill failed: {e}")
    with cols[1]:
        if st.button("Cancel", key="dlg_bulk_cancel"):
            st.rerun()


# =============================================================================
# BOM LEAD TIME EDITOR DIALOG
# =============================================================================

@st.dialog("Edit BOM Lead Time", width="large")
def _bom_lt_editor_dialog(all_boms_df, plants_df, bom_lt_df, lead_time_stats_df):
    """Dialog to add or edit a single BOM lead time."""
    if all_boms_df.empty:
        st.warning("No active BOMs found.")
        return

    # BOM selector — full product info for user-friendly selection
    bom_options = {}
    bom_details = {}  # store extra info for display after selection
    for _, row in all_boms_df.iterrows():
        label = _format_bom_label(row, style='full')
        bom_id = int(row['bom_header_id'])
        bom_options[label] = bom_id
        bom_details[bom_id] = row.to_dict()

    selected_label = st.selectbox(
        "Select BOM",
        options=list(bom_options.keys()),
        key="dlg_ed_bom_select",
    )
    selected_bom_id = bom_options.get(selected_label) if selected_label else None

    # Show selected BOM details as context
    if selected_bom_id and selected_bom_id in bom_details:
        detail = bom_details[selected_bom_id]
        info_parts = []
        if detail.get('product_name'):
            info_parts.append(f"**{detail['product_name']}**")
        if detail.get('package_size'):
            info_parts.append(detail['package_size'])
        if detail.get('brand'):
            info_parts.append(f"Brand: {detail['brand']}")
        if detail.get('output_qty') and float(detail['output_qty']) > 0:
            uom = detail.get('standard_uom', '')
            info_parts.append(f"Batch: {int(float(detail['output_qty'])):,} {uom}")
        if info_parts:
            st.caption(' · '.join(info_parts))

    # Plant selector
    plant_options = {'Global (all plants)': None}
    if not plants_df.empty:
        for _, row in plants_df.iterrows():
            plant_options[f"{row['plant_code']} — {row['plant_name']}"] = int(row['plant_id'])
    selected_plant_label = st.selectbox(
        "Plant",
        options=list(plant_options.keys()),
        key="dlg_ed_plant_select",
    )
    selected_plant_id = plant_options.get(selected_plant_label)

    # Pre-fill from existing config or historical
    prefill_std, prefill_min, prefill_max = 1, 0, 0
    hint_text = ""

    if selected_bom_id and not bom_lt_df.empty:
        existing = bom_lt_df[bom_lt_df['bom_header_id'] == selected_bom_id]
        if not existing.empty:
            row = existing.iloc[0]
            prefill_std = int(row['standard_lead_time_days']) if pd.notna(row.get('standard_lead_time_days')) else 1
            prefill_min = int(row['minimum_lead_time_days']) if pd.notna(row.get('minimum_lead_time_days')) else 0
            prefill_max = int(row['maximum_lead_time_days']) if pd.notna(row.get('maximum_lead_time_days')) else 0
            hint_text = "📋 Pre-filled from existing config"

    if hint_text == "" and selected_bom_id and lead_time_stats_df is not None and not lead_time_stats_df.empty:
        hist = lead_time_stats_df[lead_time_stats_df['bom_header_id'] == selected_bom_id] \
            if 'bom_header_id' in lead_time_stats_df.columns else pd.DataFrame()
        if not hist.empty:
            h = hist.iloc[0]
            avg = h.get('avg_lead_time_days')
            if pd.notna(avg):
                import math
                prefill_std = max(1, math.ceil(float(avg)))
                prefill_min = max(0, int(h['min_lead_time_days'])) if pd.notna(h.get('min_lead_time_days')) else 0
                prefill_max = int(h['max_lead_time_days']) if pd.notna(h.get('max_lead_time_days')) else 0
                mos = int(h['completed_mo_count']) if pd.notna(h.get('completed_mo_count')) else 0
                hint_text = f"📊 Pre-filled from historical: avg {float(avg):.1f}d from {mos} MOs"

    if hint_text:
        st.caption(hint_text)

    # Input fields
    ed_cols = st.columns(3)
    with ed_cols[0]:
        std_lt = st.number_input(
            "Standard LT (days)", min_value=1, max_value=365,
            value=max(1, prefill_std), key="dlg_ed_std",
            help="Safest estimate. Used for backward scheduling.",
        )
    with ed_cols[1]:
        min_lt = st.number_input(
            "Min LT (days)", min_value=0, max_value=365,
            value=prefill_min, key="dlg_ed_min",
            help="Best-case lead time. 0 = not set.",
        )
    with ed_cols[2]:
        max_lt = st.number_input(
            "Max LT (days)", min_value=0, max_value=365,
            value=prefill_max, key="dlg_ed_max",
            help="Worst-case lead time. 0 = not set.",
        )

    # Validation warnings (Fix #9)
    if min_lt > 0 and std_lt < min_lt:
        st.warning(f"⚠️ Standard LT ({std_lt}d) is less than Min LT ({min_lt}d) — standard should be ≥ min.")
    if max_lt > 0 and std_lt > max_lt:
        st.warning(f"⚠️ Standard LT ({std_lt}d) is greater than Max LT ({max_lt}d) — standard should be ≤ max.")
    if min_lt > 0 and max_lt > 0 and min_lt > max_lt:
        st.warning(f"⚠️ Min LT ({min_lt}d) is greater than Max LT ({max_lt}d).")

    notes = st.text_input("Notes", value="", key="dlg_ed_notes",
                          placeholder="Reason: new machine, process change, etc.")

    # Save + Cancel
    cols = st.columns([1, 1, 2])
    with cols[0]:
        if st.button("💾 Save", key="dlg_ed_save", type="primary"):
            if selected_bom_id is None:
                st.error("Select a BOM first.")
            else:
                try:
                    from .production_data_loader import get_production_data_loader
                    loader = get_production_data_loader()
                    ok = loader.save_bom_lead_time(
                        bom_header_id=selected_bom_id,
                        standard_lead_time_days=std_lt,
                        plant_id=selected_plant_id,
                        minimum_lead_time_days=min_lt if min_lt > 0 else None,
                        maximum_lead_time_days=max_lt if max_lt > 0 else None,
                        notes=notes,
                        source='MANUAL',
                        user_id=_get_current_user_id(),
                    )
                    if ok:
                        st.session_state['_blt_toast'] = f"Saved lead time for {selected_label}"
                        st.rerun()
                    else:
                        st.error("Save failed — check logs.")
                except Exception as e:
                    st.error(f"Save failed: {e}")
    with cols[1]:
        if st.button("Cancel", key="dlg_ed_cancel"):
            st.rerun()


# =============================================================================
# PLANT MANAGEMENT DIALOG
# =============================================================================

@st.dialog("Manage Plants", width="large")
def _manage_plants_dialog(plants_df: Optional[pd.DataFrame] = None):
    """
    Dialog for plant management — list existing + add new + edit existing.
    Dynamic company dropdown (Fix #6). Edit support (Fix #4).
    """
    # ── Load companies for entity dropdown (Fix #6) ──
    entity_options = {}
    try:
        from .production_data_loader import get_production_data_loader
        _loader = get_production_data_loader()
        _loader._ensure_connection()
        _companies_df = pd.read_sql(
            "SELECT id, english_name, company_code FROM companies "
            "WHERE delete_flag = 0 ORDER BY english_name",
            _loader._engine,
        )
        for _, row in _companies_df.iterrows():
            label = f"{row['english_name']} ({row.get('company_code', '')})" if row.get('company_code') else row['english_name']
            entity_options[label] = int(row['id'])
    except Exception:
        pass

    if not entity_options:
        entity_options = {'Vietape VN (entity_id=23)': 23}

    # ── Existing plants table ──
    if plants_df is not None and not plants_df.empty:
        st.markdown("**Existing plants:**")
        display_cols = ['plant_code', 'plant_name', 'plant_type', 'entity_name', 'address']
        avail_cols = [c for c in display_cols if c in plants_df.columns]
        st.dataframe(
            plants_df[avail_cols],
            hide_index=True, use_container_width=True,
            height=min(35 * len(plants_df) + 38, 180),
        )

    # ── Mode: Add new vs Edit existing (Fix #4) ──
    mode_options = ['➕ Add New Plant']
    edit_plant_map = {}
    if plants_df is not None and not plants_df.empty:
        for _, row in plants_df.iterrows():
            label = f"✏️ Edit: {row['plant_code']} — {row['plant_name']}"
            mode_options.append(label)
            edit_plant_map[label] = row.to_dict()

    selected_mode = st.radio(
        "Action", mode_options, key="dlg_pf_mode", horizontal=True,
    )

    is_edit = selected_mode.startswith('✏️')
    edit_row = edit_plant_map.get(selected_mode, {})

    # ── Form fields ──
    pf_cols = st.columns(2)
    with pf_cols[0]:
        plant_code = st.text_input(
            "Plant Code", key="dlg_pf_code",
            value=edit_row.get('plant_code', ''),
            placeholder="PLT-VN-01",
            help="Unique code. Format: PLT-[COUNTRY]-[NUM]",
            disabled=is_edit,
        )
    with pf_cols[1]:
        plant_name = st.text_input(
            "Plant Name", key="dlg_pf_name",
            value=edit_row.get('plant_name', ''),
            placeholder="Xưởng Cắt Yên Mỹ",
        )

    pf_cols2 = st.columns(3)
    with pf_cols2[0]:
        type_options = ['MIXED', 'CUTTING', 'REPACKING', 'KITTING']
        current_type = edit_row.get('plant_type', 'MIXED')
        type_idx = type_options.index(current_type) if current_type in type_options else 0
        plant_type = st.selectbox(
            "Type", type_options, index=type_idx, key="dlg_pf_type",
        )
    with pf_cols2[1]:
        entity_labels = list(entity_options.keys())
        current_entity_id = edit_row.get('entity_id', 23)
        default_idx = 0
        for i, (lbl, eid) in enumerate(entity_options.items()):
            if eid == current_entity_id:
                default_idx = i
                break
        selected_entity_label = st.selectbox(
            "Company (Entity)",
            entity_labels, index=default_idx, key="dlg_pf_entity",
            help="Pháp nhân sở hữu nhà máy",
        )
        entity_id = entity_options.get(selected_entity_label, 23)
    with pf_cols2[2]:
        address = st.text_input(
            "Address", key="dlg_pf_address",
            value=edit_row.get('address', '') or '',
            placeholder="KCN Yên Mỹ, Hưng Yên",
        )

    notes = st.text_input(
        "Notes", key="dlg_pf_notes",
        value=edit_row.get('notes', '') or '',
        placeholder="Năng lực, ca làm việc, thiết bị đặc biệt",
    )

    # ── Save + Cancel ──
    cols = st.columns([1, 1, 2])
    with cols[0]:
        save_label = "💾 Update Plant" if is_edit else "💾 Save Plant"
        if st.button(save_label, key="dlg_pf_save", type="primary"):
            if not plant_code or not plant_name:
                st.error("Plant code and name are required.")
            else:
                try:
                    from .production_data_loader import get_production_data_loader
                    loader = get_production_data_loader()
                    result_id = loader.save_plant(
                        plant_code=plant_code,
                        plant_name=plant_name,
                        entity_id=entity_id,
                        plant_type=plant_type,
                        address=address,
                        notes=notes,
                        user_id=_get_current_user_id(),
                        plant_id=int(edit_row['plant_id']) if is_edit else None,
                    )
                    if result_id:
                        action = "Updated" if is_edit else "Created"
                        st.session_state['_blt_toast'] = f"{action} plant: {plant_code} (ID: {result_id})"
                        st.rerun()
                    else:
                        st.error("Failed to save plant — check logs.")
                except Exception as e:
                    error_msg = str(e)
                    if 'Duplicate entry' in error_msg or 'uq_plant_code' in error_msg:
                        st.error(f"Plant code '{plant_code}' already exists. Choose a different code.")
                    else:
                        st.error(f"Failed: {e}")
    with cols[1]:
        if st.button("Cancel", key="dlg_pf_cancel"):
            st.rerun()

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
# DYNAMIC PIVOT TABLE — User-configurable Rows × Columns × Values
# =============================================================================

# Field definitions for pivot: (display_label, df_column, category)
_PIVOT_ROW_OPTIONS = {
    'Brand': 'brand',
    'BOM Type': 'bom_type',
    'Product': '_product_label',
    'Urgency': 'urgency_level',
    'Readiness': 'readiness_status',
    'Start Week': '_start_week',
    'Demand Week': '_demand_week',
    'UOM': 'uom',
    'LT Source': 'lead_time_source',
    'Action': 'action_type',
    'Delayed': '_delayed_label',
}

_PIVOT_COL_OPTIONS = {
    '(none)': None,
    'Start Week': '_start_week',
    'BOM Type': 'bom_type',
    'Brand': 'brand',
    'Urgency': 'urgency_level',
    'Readiness': 'readiness_status',
    'Demand Week': '_demand_week',
    'UOM': 'uom',
    'Delayed': '_delayed_label',
}

_PIVOT_VALUE_OPTIONS = {
    'Count': '_count',
    'Suggested Qty': 'suggested_qty',
    'Shortage Qty': 'shortage_qty',
    'Batches': 'batches_needed',
    'At Risk Value ($)': 'at_risk_value',
    'Priority Score': 'priority_score',
    'Lead Time (days)': 'lead_time_days',
    'Max Producible Now': 'max_producible_now',
}

_PIVOT_AGG_OPTIONS = {
    'sum': 'sum',
    'count': 'count',
    'mean': 'mean',
    'min': 'min',
    'max': 'max',
}


def _lines_to_pivot_df(lines: List[MOLineItem]) -> pd.DataFrame:
    """Convert MOLineItem list to a flat DataFrame with derived columns for pivoting."""
    rows = []
    for l in lines:
        # Start week
        start_d = l.actual_start or l.must_start_by
        if start_d:
            iso = start_d.isocalendar()
            start_week = f"W{iso[1]:02d}-{iso[0]}"
        else:
            start_week = "Unscheduled"

        # Demand week
        if l.demand_date:
            iso_d = l.demand_date.isocalendar()
            demand_week = f"W{iso_d[1]:02d}-{iso_d[0]}"
        else:
            demand_week = "N/A"

        # Urgency display
        urg_cfg = URGENCY_LEVELS.get(l.urgency_level, {})
        rdy_cfg = READINESS_STATUS.get(l.readiness_status, {})

        rows.append({
            'pt_code': l.pt_code,
            'product_name': (l.product_name or '')[:35],
            '_product_label': f"{l.pt_code} · {(l.product_name or '')[:25]}",
            'brand': l.brand or '(No Brand)',
            'bom_type': l.bom_type,
            'urgency_level': f"{urg_cfg.get('icon', '')} {urg_cfg.get('label', l.urgency_level)}",
            'readiness_status': f"{rdy_cfg.get('icon', '')} {rdy_cfg.get('label', l.readiness_status)}",
            '_start_week': start_week,
            '_demand_week': demand_week,
            'uom': l.uom,
            'lead_time_source': l.lead_time_source,
            'action_type': l.action_type,
            '_delayed_label': 'Delayed' if l.is_delayed else 'On Time',
            # Numeric values
            'suggested_qty': l.suggested_qty,
            'shortage_qty': l.shortage_qty,
            'batches_needed': l.batches_needed,
            'at_risk_value': l.at_risk_value,
            'priority_score': l.priority_score,
            'lead_time_days': l.lead_time_days,
            'max_producible_now': l.max_producible_now,
            '_count': 1,
        })

    return pd.DataFrame(rows)


def _render_dynamic_pivot(lines: List[MOLineItem], key_prefix: str = "pv"):
    """
    Render a dynamic pivot table with user-selectable Rows, Columns, Values, Aggregation.

    Similar to Sales Detail / Inventory pivot views in other ERP modules.
    """
    if not lines:
        st.info("No data for pivot.")
        return

    # ── Build base DataFrame ──
    df = _lines_to_pivot_df(lines)

    # ── Controls: Rows / Columns / Value / Aggregation ──
    ctrl_cols = st.columns([2, 2, 2, 1])

    with ctrl_cols[0]:
        row_label = st.selectbox(
            "Rows",
            options=list(_PIVOT_ROW_OPTIONS.keys()),
            index=1,  # default: BOM Type
            key=f"{key_prefix}_rows",
        )
        row_col = _PIVOT_ROW_OPTIONS[row_label]

    with ctrl_cols[1]:
        col_label = st.selectbox(
            "Columns",
            options=list(_PIVOT_COL_OPTIONS.keys()),
            index=2,  # default: Start Week
            key=f"{key_prefix}_cols",
        )
        col_col = _PIVOT_COL_OPTIONS[col_label]

    with ctrl_cols[2]:
        val_label = st.selectbox(
            "Values",
            options=list(_PIVOT_VALUE_OPTIONS.keys()),
            index=4,  # default: At Risk Value ($)
            key=f"{key_prefix}_vals",
        )
        val_col = _PIVOT_VALUE_OPTIONS[val_label]

    with ctrl_cols[3]:
        agg_label = st.selectbox(
            "Aggregation",
            options=list(_PIVOT_AGG_OPTIONS.keys()),
            index=0,  # default: sum
            key=f"{key_prefix}_agg",
        )
        agg_func = _PIVOT_AGG_OPTIONS[agg_label]

    # ── Validate: Row and Column must differ ──
    if col_col and row_col == col_col:
        st.warning("Rows and Columns must be different fields.")
        return

    # ── Build pivot ──
    try:
        if col_col is None:
            # No column pivot — simple groupby
            if val_col == '_count':
                pivot = df.groupby(row_col).size().reset_index(name='Count')
                pivot = pivot.sort_values('Count', ascending=False)
            else:
                pivot = df.groupby(row_col)[val_col].agg(agg_func).reset_index()
                pivot.columns = [row_label, val_label]
                pivot = pivot.sort_values(val_label, ascending=False)

                # Add Total row
                if agg_func in ('sum', 'count'):
                    total_val = pivot[val_label].sum()
                    total_row = pd.DataFrame([{row_label: '**TOTAL**', val_label: total_val}])
                    pivot = pd.concat([pivot, total_row], ignore_index=True)
        else:
            # Full pivot: rows × columns
            if val_col == '_count':
                pivot = pd.pivot_table(
                    df, values='_count', index=row_col, columns=col_col,
                    aggfunc='sum', fill_value=0, margins=True, margins_name='Total',
                )
            else:
                pivot = pd.pivot_table(
                    df, values=val_col, index=row_col, columns=col_col,
                    aggfunc=agg_func, fill_value=0, margins=True, margins_name='Total',
                )

            # Flatten MultiIndex columns if needed
            if isinstance(pivot.columns, pd.MultiIndex):
                pivot.columns = [str(c[-1]) for c in pivot.columns]

            pivot = pivot.reset_index()
            pivot.columns.name = None

            # Rename first column
            pivot = pivot.rename(columns={row_col: row_label})

    except Exception as e:
        st.error(f"Pivot error: {e}")
        return

    # ── Format & Display ──
    is_currency = 'value' in val_label.lower() or '$' in val_label
    is_qty = 'qty' in val_label.lower() or 'batch' in val_label.lower() or val_label == 'Count'

    # Apply styling
    if col_col is not None and len(pivot.columns) > 2:
        # Color-code the numeric cells (skip first column = row labels, last = Total)
        numeric_cols = [c for c in pivot.columns if c != row_label]

        def _color_cell(val):
            """Gradient: higher value = darker blue."""
            try:
                v = float(val)
                if v <= 0:
                    return ''
                return f'background-color: rgba(59, 130, 246, {min(0.5, v / pivot[numeric_cols].max().max() * 0.5):.2f})'
            except (ValueError, TypeError):
                return ''

        # Format numbers
        fmt = {}
        for c in numeric_cols:
            if is_currency:
                fmt[c] = '${:,.0f}'
            elif is_qty:
                fmt[c] = '{:,.0f}'
            else:
                fmt[c] = '{:,.1f}'

        try:
            styled = pivot.style.map(
                _color_cell, subset=numeric_cols,
            ).format(fmt, na_rep='0')
        except (AttributeError, TypeError):
            try:
                styled = pivot.style.applymap(
                    _color_cell, subset=numeric_cols,
                ).format(fmt, na_rep='0')
            except Exception:
                styled = pivot

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            height=min(35 * len(pivot) + 38, 600),
        )
    else:
        # Simple table — no color coding
        st.dataframe(
            pivot,
            use_container_width=True,
            hide_index=True,
            height=min(35 * len(pivot) + 38, 600),
        )

    # ── Summary caption ──
    st.caption(
        f"{len(df)} items · Rows: **{row_label}** "
        + (f"· Columns: **{col_label}** " if col_col else "")
        + f"· Values: **{val_label}** ({agg_label})"
    )


# =============================================================================
# SMART PIVOT VIEWS — Summary views for Production Planners
# =============================================================================

def _get_line_week_key(line: MOLineItem) -> str:
    """Extract week key (W13-2026) from a line's start date."""
    d = line.actual_start or line.must_start_by
    if d is None:
        return "Unscheduled"
    iso = d.isocalendar()
    return f"W{iso[1]:02d}-{iso[0]}"


def _get_line_week_start(line: MOLineItem) -> Optional[date]:
    """Extract Monday of start week."""
    d = line.actual_start or line.must_start_by
    if d is None:
        return None
    return d - timedelta(days=d.weekday())


# ── R2: Ready — Group by BOM Type ──────────────────────────────────────

def _pivot_ready_by_bom_type(lines: List[MOLineItem]):
    """Pivot Ready items by BOM Type — for workshop assignment."""
    if not lines:
        return

    st.markdown("##### 🏭 By Workshop (BOM Type)")

    groups = {}
    for l in lines:
        groups.setdefault(l.bom_type, []).append(l)

    rows = []
    for bom_type in sorted(groups.keys()):
        items = groups[bom_type]
        bom_cfg = BOM_TYPES.get(bom_type, {})
        total_batches = sum(l.batches_needed for l in items)
        total_qty = sum(l.suggested_qty for l in items)
        total_value = sum(l.at_risk_value for l in items)
        overdue = sum(1 for l in items if l.urgency_level == 'OVERDUE')
        critical = sum(1 for l in items if l.urgency_level == 'CRITICAL')

        urgency_tag = ""
        if overdue > 0:
            urgency_tag = f"🚨 {overdue} overdue"
        elif critical > 0:
            urgency_tag = f"🔴 {critical} critical"

        rows.append({
            'Workshop': f"{bom_cfg.get('icon', '')} {bom_type}",
            'MO Lines': len(items),
            'Total Batches': total_batches,
            'Total Qty': round(total_qty),
            'Value ($)': round(total_value),
            'Urgent': urgency_tag,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'Workshop': st.column_config.TextColumn(width='medium'),
            'MO Lines': st.column_config.NumberColumn(format="%d", width='small'),
            'Total Batches': st.column_config.NumberColumn(format="%d", width='small'),
            'Total Qty': st.column_config.NumberColumn(format="%,d"),
            'Value ($)': st.column_config.NumberColumn(format="$%,d"),
            'Urgent': st.column_config.TextColumn(width='medium'),
        },
        hide_index=True, use_container_width=True,
        height=35 * len(df) + 38,
    )


# ── R3: Ready — Group by Brand ─────────────────────────────────────────

def _pivot_ready_by_brand(lines: List[MOLineItem]):
    """Pivot Ready items by Brand — for management reporting."""
    if not lines:
        return

    st.markdown("##### 🏷️ By Brand")

    groups = {}
    for l in lines:
        brand = l.brand or '(No Brand)'
        groups.setdefault(brand, []).append(l)

    rows = []
    for brand in sorted(groups.keys(), key=lambda b: -sum(i.at_risk_value for i in groups[b])):
        items = groups[brand]
        avg_priority = sum(l.priority_score for l in items) / len(items)
        rows.append({
            'Brand': brand,
            'MO Lines': len(items),
            'Total Batches': sum(l.batches_needed for l in items),
            'Value ($)': round(sum(l.at_risk_value for l in items)),
            'Avg Priority': round(avg_priority, 1),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'Brand': st.column_config.TextColumn(width='medium'),
            'MO Lines': st.column_config.NumberColumn(format="%d", width='small'),
            'Total Batches': st.column_config.NumberColumn(format="%d", width='small'),
            'Value ($)': st.column_config.NumberColumn(format="$%,d"),
            'Avg Priority': st.column_config.NumberColumn(format="%.1f", width='small',
                                                          help="Lower = more urgent"),
        },
        hide_index=True, use_container_width=True,
        height=min(35 * len(df) + 38, 300),
    )


# ── R4: Ready — Group by Start Week ────────────────────────────────────

def _pivot_ready_by_week(lines: List[MOLineItem]):
    """Pivot Ready items by start week — for workload planning."""
    if not lines:
        return

    st.markdown("##### 📅 By Start Week")

    groups = {}
    for l in lines:
        week = _get_line_week_key(l)
        groups.setdefault(week, []).append(l)

    rows = []
    # Sort by week key (W13-2026 format sorts naturally)
    for week in sorted(groups.keys()):
        items = groups[week]
        week_start = _get_line_week_start(items[0])
        date_range = ""
        if week_start:
            week_end = week_start + timedelta(days=4)
            date_range = f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m')}"

        # BOM type breakdown inline
        bom_counts = {}
        for l in items:
            bom_counts[l.bom_type] = bom_counts.get(l.bom_type, 0) + 1
        bom_summary = ", ".join(
            f"{BOM_TYPES.get(bt, {}).get('icon', '')} {c}"
            for bt, c in sorted(bom_counts.items())
        )

        rows.append({
            'Week': week,
            'Dates': date_range,
            'MO Lines': len(items),
            'Batches': sum(l.batches_needed for l in items),
            'Value ($)': round(sum(l.at_risk_value for l in items)),
            'Workshops': bom_summary,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'Week': st.column_config.TextColumn(width='small'),
            'Dates': st.column_config.TextColumn(width='medium'),
            'MO Lines': st.column_config.NumberColumn(format="%d", width='small'),
            'Batches': st.column_config.NumberColumn(format="%d", width='small'),
            'Value ($)': st.column_config.NumberColumn(format="$%,d"),
            'Workshops': st.column_config.TextColumn(width='large'),
        },
        hide_index=True, use_container_width=True,
        height=min(35 * len(df) + 38, 250),
    )


# ── W1: Waiting — Bottleneck Material Pivot ─────────────────────────────

def _pivot_waiting_bottleneck_materials(lines: List[MOLineItem]):
    """Pivot Waiting items by bottleneck material — the most actionable view."""
    if not lines:
        return

    # Collect bottleneck info
    bottleneck_map: Dict[str, Dict] = {}
    for l in lines:
        mat = l.bottleneck_material
        if not mat:
            continue
        if mat not in bottleneck_map:
            bottleneck_map[mat] = {
                'products': [],
                'total_value': 0.0,
                'earliest_eta': None,
                'latest_eta': None,
                'contention_count': 0,
            }
        info = bottleneck_map[mat]
        info['products'].append(l.pt_code)
        info['total_value'] += l.at_risk_value
        if l.has_contention:
            info['contention_count'] += 1
        if l.bottleneck_eta:
            if info['earliest_eta'] is None or l.bottleneck_eta < info['earliest_eta']:
                info['earliest_eta'] = l.bottleneck_eta
            if info['latest_eta'] is None or l.bottleneck_eta > info['latest_eta']:
                info['latest_eta'] = l.bottleneck_eta

    if not bottleneck_map:
        return

    st.markdown("##### 🧱 Bottleneck Materials — Push these to unlock MOs")

    rows = []
    # Sort by number of blocked products (highest impact first)
    for mat_code, info in sorted(bottleneck_map.items(), key=lambda x: -len(x[1]['products'])):
        eta_str = ""
        if info['earliest_eta']:
            eta_str = str(info['earliest_eta'])
            if info['latest_eta'] and info['latest_eta'] != info['earliest_eta']:
                eta_str += f" → {info['latest_eta']}"

        rows.append({
            'Material': mat_code,
            'Blocks': f"{len(info['products'])} products",
            'Value Blocked ($)': round(info['total_value']),
            'ETA': eta_str or '❌ No ETA',
            'Contention': '⚡ Yes' if info['contention_count'] > 0 else '',
            'Affected': ', '.join(info['products'][:5]) + (
                f" +{len(info['products'])-5}" if len(info['products']) > 5 else ""
            ),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'Material': st.column_config.TextColumn(width='medium'),
            'Blocks': st.column_config.TextColumn(width='small'),
            'Value Blocked ($)': st.column_config.NumberColumn(format="$%,d"),
            'ETA': st.column_config.TextColumn(width='medium'),
            'Contention': st.column_config.TextColumn(width='small'),
            'Affected': st.column_config.TextColumn('Affected Products', width='large'),
        },
        hide_index=True, use_container_width=True,
        height=min(35 * len(df) + 38, 400),
    )

    # Highlight: total value blocked by top 3 materials
    if len(rows) >= 2:
        top3_value = sum(r['Value Blocked ($)'] for r in rows[:3])
        total_value = sum(r['Value Blocked ($)'] for r in rows)
        if total_value > 0:
            pct = round(top3_value / total_value * 100)
            st.caption(
                f"💡 Top 3 bottleneck materials account for **${top3_value:,}** "
                f"({pct}% of total blocked value). Prioritize PO follow-up on these."
            )


# ── W2: Waiting — ETA Timeline (when will items unlock?) ────────────────

def _pivot_waiting_eta_timeline(lines: List[MOLineItem]):
    """Group Waiting items by ETA week — forecast when items become Ready."""
    if not lines:
        return

    st.markdown("##### 📅 ETA Forecast — When will items unlock?")

    groups = {'No ETA': []}
    for l in lines:
        if l.bottleneck_eta:
            iso = l.bottleneck_eta.isocalendar()
            week_key = f"W{iso[1]:02d}-{iso[0]}"
        else:
            week_key = 'No ETA'
        groups.setdefault(week_key, []).append(l)

    rows = []
    cumulative_count = 0
    cumulative_value = 0.0

    # Sorted weeks first, "No ETA" last
    sorted_keys = sorted(k for k in groups.keys() if k != 'No ETA')
    if 'No ETA' in groups and groups['No ETA']:
        sorted_keys.append('No ETA')

    for week in sorted_keys:
        items = groups[week]
        week_value = sum(l.at_risk_value for l in items)

        if week != 'No ETA':
            cumulative_count += len(items)
            cumulative_value += week_value

        date_hint = ""
        if week != 'No ETA' and items:
            eta = items[0].bottleneck_eta
            if eta:
                week_start = eta - timedelta(days=eta.weekday())
                date_hint = f"{week_start.strftime('%d/%m')} – {(week_start + timedelta(days=4)).strftime('%d/%m')}"

        rows.append({
            'ETA Week': week,
            'Dates': date_hint,
            'Items Unlock': len(items),
            'Value Unlocks ($)': round(week_value),
            'Cumulative': cumulative_count if week != 'No ETA' else '—',
            'Cum. Value ($)': round(cumulative_value) if week != 'No ETA' else '—',
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'ETA Week': st.column_config.TextColumn(width='small'),
            'Dates': st.column_config.TextColumn(width='medium'),
            'Items Unlock': st.column_config.NumberColumn(format="%d", width='small'),
            'Value Unlocks ($)': st.column_config.NumberColumn(format="$%,d"),
            'Cumulative': st.column_config.TextColumn(width='small'),
            'Cum. Value ($)': st.column_config.TextColumn(width='small'),
        },
        hide_index=True, use_container_width=True,
        height=min(35 * len(df) + 38, 300),
    )

    # Almost-ready highlight (W3)
    almost_ready = [l for l in lines if l.materials_ready_pct >= 80]
    if almost_ready:
        ar_value = sum(l.at_risk_value for l in almost_ready)
        st.success(
            f"🟢 **{len(almost_ready)} items are ≥80% material ready** "
            f"(${ar_value:,.0f} value) — consider partial production or prioritize remaining PO."
        )


# ── O1: Overview — Urgency × Readiness Matrix ──────────────────────────

def _pivot_urgency_readiness_matrix(result: MOSuggestionResult):
    """2D matrix: Urgency rows × Readiness cols → count + value."""
    lines = result.all_lines
    if not lines:
        return

    st.markdown("##### 🎯 Urgency × Readiness Matrix")
    st.caption("Rows = urgency, Columns = readiness. Cell = count (value). "
               "**Top-left corner = act immediately.**")

    # Build matrix data
    matrix: Dict[str, Dict[str, Dict]] = {}
    urgency_order = ['OVERDUE', 'CRITICAL', 'URGENT', 'THIS_WEEK', 'PLANNED']
    readiness_order = ['READY', 'USE_ALTERNATIVE', 'PARTIAL_READY', 'BLOCKED']

    readiness_labels = {
        'READY': '✅ Ready',
        'USE_ALTERNATIVE': '🔄 Alt',
        'PARTIAL_READY': '🟡 Partial',
        'BLOCKED': '🔴 Blocked',
    }

    for l in lines:
        urg = l.urgency_level
        rdy = l.readiness_status
        if urg not in matrix:
            matrix[urg] = {}
        if rdy not in matrix[urg]:
            matrix[urg][rdy] = {'count': 0, 'value': 0.0}
        matrix[urg][rdy]['count'] += 1
        matrix[urg][rdy]['value'] += l.at_risk_value

    # Build display rows
    rows = []
    for urg in urgency_order:
        if urg not in matrix:
            continue
        urg_cfg = URGENCY_LEVELS.get(urg, {})
        row = {'Urgency': f"{urg_cfg.get('icon', '')} {urg_cfg.get('label', urg)}"}
        row_total = 0
        for rdy in readiness_order:
            col_label = readiness_labels.get(rdy, rdy)
            cell = matrix.get(urg, {}).get(rdy)
            if cell and cell['count'] > 0:
                row[col_label] = f"{cell['count']} (${cell['value']:,.0f})"
                row_total += cell['count']
            else:
                row[col_label] = ''
        row['Total'] = row_total
        rows.append(row)

    if not rows:
        return

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        column_config={
            'Urgency': st.column_config.TextColumn(width='medium'),
            'Total': st.column_config.NumberColumn(format="%d", width='small'),
        },
        hide_index=True, use_container_width=True,
        height=35 * len(df) + 38,
    )

    # Action callout: Critical + Ready items
    critical_ready = [
        l for l in lines
        if l.urgency_level in ('OVERDUE', 'CRITICAL')
        and l.readiness_status in ('READY', 'USE_ALTERNATIVE')
    ]
    if critical_ready:
        cr_value = sum(l.at_risk_value for l in critical_ready)
        st.error(
            f"🚨 **{len(critical_ready)} items are both URGENT and READY** — "
            f"${cr_value:,.0f} at risk. Create MOs for these immediately."
        )


# =============================================================================
# TAB FRAGMENTS
#
# Architecture:
#   tab_entry_function(result)  → static cards (no rerun needed)
#                               → calls @st.fragment for interactive content
#
#   @st.fragment _xxx_content() → radio toggle + pivot/table/summary
#                               → changing radio or pivot controls only reruns
#                                 this fragment, NOT the full page
#
# This avoids full page rerun (config reload, pipeline bar, DB queries)
# when user simply switches between Summary / Detail / Pivot views.
# =============================================================================

def ready_tab_fragment(result: MOSuggestionResult):
    """Tab 1: Ready to Produce — items that can start immediately."""
    lines = result.ready_lines
    if not lines:
        st.success("🎉 No items currently ready to produce (check Waiting/Blocked tabs).")
        return

    total_value = sum(l.at_risk_value for l in lines)
    total_batches = sum(l.batches_needed for l in lines)
    total_qty = sum(l.suggested_qty for l in lines)
    brands = set(l.brand for l in lines if l.brand)

    # ── Summary Cards (static — outside fragment) ──
    kc = st.columns(5)
    with kc[0]:
        st.metric("MO Lines", f"{len(lines)}")
    with kc[1]:
        st.metric("Total Batches", f"{total_batches:,}")
    with kc[2]:
        st.metric("Total Qty", f"{total_qty:,.0f}")
    with kc[3]:
        st.metric("Value ($)", f"${total_value:,.0f}")
    with kc[4]:
        st.metric("Brands", f"{len(brands)}")

    # ── Interactive Content (fragment — isolated rerun) ──
    _ready_tab_content(lines, total_value)


@st.fragment
def _ready_tab_content(lines: list, total_value: float):
    """Fragment: Ready tab view toggle + content. Reruns only this on interaction."""
    view_mode = st.radio(
        "View mode",
        ['📊 Summary', '📋 Detail', '🔄 Pivot'],
        horizontal=True,
        key="ready_view_mode",
        label_visibility="collapsed",
    )

    if view_mode == '📊 Summary':
        _pivot_ready_by_bom_type(lines)
        _pivot_ready_by_week(lines)
        with st.expander("🏷️ By Brand", expanded=False):
            _pivot_ready_by_brand(lines)

    elif view_mode == '🔄 Pivot':
        st.markdown("##### 🔄 Pivot Table")
        _render_dynamic_pivot(lines, key_prefix="pv_ready")

    else:
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
    has_eta = sum(1 for l in lines if l.bottleneck_eta is not None)
    no_eta = len(lines) - has_eta
    almost_ready = sum(1 for l in lines if l.materials_ready_pct >= 80)

    # ── Summary Cards (static — outside fragment) ──
    kc = st.columns(5)
    with kc[0]:
        st.metric("Waiting Items", f"{len(lines)}")
    with kc[1]:
        st.metric("Value ($)", f"${total_value:,.0f}")
    with kc[2]:
        st.metric("Has ETA", f"{has_eta}", delta=f"{no_eta} no ETA" if no_eta else None, delta_color="off")
    with kc[3]:
        st.metric("Almost Ready", f"{almost_ready}", help="≥80% materials available")
    with kc[4]:
        bottleneck_count = len(set(l.bottleneck_material for l in lines if l.bottleneck_material))
        st.metric("Bottleneck NVL", f"{bottleneck_count}")

    # ── Interactive Content (fragment — isolated rerun) ──
    _waiting_tab_content(lines, total_value)


@st.fragment
def _waiting_tab_content(lines: list, total_value: float):
    """Fragment: Waiting tab view toggle + content. Reruns only this on interaction."""
    view_mode = st.radio(
        "View mode",
        ['📊 Summary', '📋 Detail', '🔄 Pivot'],
        horizontal=True,
        key="waiting_view_mode",
        label_visibility="collapsed",
    )

    if view_mode == '📊 Summary':
        _pivot_waiting_bottleneck_materials(lines)
        _pivot_waiting_eta_timeline(lines)

    elif view_mode == '🔄 Pivot':
        st.markdown("##### 🔄 Pivot Table")
        _render_dynamic_pivot(lines, key_prefix="pv_waiting")

    else:
        st.markdown(
            f"**{len(lines)} items** waiting for materials — "
            f"total at-risk value: **${total_value:,.0f}**"
        )
        render_mo_lines_table(
            lines, title="Waiting for Materials",
            show_readiness=True, show_action=True,
        )


def blocked_tab_fragment(result: MOSuggestionResult):
    """Tab 3: Blocked — no materials available + unschedulable."""
    lines = result.blocked_lines

    if lines:
        # ── Interactive Content (fragment — isolated rerun) ──
        _blocked_tab_content(lines)

    # Unschedulable sub-section (static — outside fragment)
    if result.has_unschedulable():
        st.divider()
        render_unschedulable_panel(result)

    if not lines and not result.has_unschedulable():
        st.success("🎉 No blocked items!")


@st.fragment
def _blocked_tab_content(lines: list):
    """Fragment: Blocked tab view toggle + content. Reruns only this on interaction."""
    total_value = sum(l.at_risk_value for l in lines)

    view_mode = st.radio(
        "View mode",
        ['📋 Detail', '🔄 Pivot'],
        horizontal=True,
        key="blocked_view_mode",
        label_visibility="collapsed",
    )

    if view_mode == '🔄 Pivot':
        st.markdown("##### 🔄 Pivot Table — Blocked Items")
        _render_dynamic_pivot(lines, key_prefix="pv_blocked")
    else:
        st.markdown(
            f"**{len(lines)} items** blocked — materials unavailable, no ETA. "
            f"At-risk value: **${total_value:,.0f}**"
        )
        render_mo_lines_table(
            lines, title="Blocked",
            show_readiness=True, show_action=True,
        )


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
    """Tab 5: Overview — KPIs + urgency + matrix + top urgent + BOM breakdown + reconciliation."""

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

    # O1: Urgency × Readiness Matrix (new — the key strategic view)
    _pivot_urgency_readiness_matrix(result)

    # Top urgent
    _render_top_urgent_items(result, top_n=5)

    # BOM breakdown
    _render_bom_distribution(result)

    # Dynamic Pivot — all lines (fragment — isolated rerun)
    _overview_pivot_content(result.all_lines)

    # Reconciliation
    render_reconciliation_panel(result)


@st.fragment
def _overview_pivot_content(all_lines: list):
    """Fragment: Overview pivot table. Changing controls only reruns this."""
    with st.expander("🔄 **Pivot Table** — All MO Lines", expanded=False):
        _render_dynamic_pivot(all_lines, key_prefix="pv_overview")


# =============================================================================
# EMPTY STATE (backward compat — page now uses render_empty_state_for_tab)
# =============================================================================

def render_empty_state():
    """Legacy — show generic empty state. Page now uses render_empty_state_for_tab."""
    render_empty_state_for_tab('ready', config_ready=False, gap_available=False)