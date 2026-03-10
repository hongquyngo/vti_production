# utils/supply_chain_gap/period_calculator.py

"""
Period-based GAP Calculator for Supply Chain GAP Analysis
Calculates GAP by time period (Weekly/Monthly) with carry-forward & backlog tracking.

VERSION: 2.3.0

Features:
- FG Period GAP (carry-forward + backlog)
- Raw Material Period GAP via BOM explosion of FG shortage by period
- Pivot data builder (products × periods matrix)
- Filtering helpers for manufacturing/trading subsets
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# =============================================================================
# PERIOD HELPERS
# =============================================================================

def convert_to_period(date_value, period_type: str) -> Optional[str]:
    """Convert date → period string (Weekly / Monthly)."""
    try:
        if pd.isna(date_value):
            return None
        date_val = pd.to_datetime(date_value, errors='coerce')
        if pd.isna(date_val):
            return None
        if period_type == "Weekly":
            iso_year, week_num, _ = date_val.isocalendar()
            return f"Week {week_num} - {iso_year}"
        elif period_type == "Monthly":
            return date_val.strftime('%b %Y')
        return date_val.strftime('%Y-%m-%d')
    except Exception:
        return None


def parse_week_sort_key(period_str: str) -> Tuple[int, int]:
    """Parse 'Week N - YYYY' → (year, week) for sorting."""
    try:
        if pd.isna(period_str) or not period_str:
            return (9999, 99)
        s = str(period_str).strip()
        if " - " in s and s.startswith("Week "):
            parts = s.split(" - ")
            w, y = int(parts[0].replace("Week ", "").strip()), int(parts[1].strip())
            if 1 <= w <= 53:
                return (y, w)
    except (ValueError, AttributeError):
        pass
    return (9999, 99)


def parse_month_sort_key(period_str: str) -> pd.Timestamp:
    """Parse 'Jan 2025' → Timestamp for sorting."""
    try:
        if pd.isna(period_str) or not period_str:
            return pd.Timestamp.max
        return pd.to_datetime(f"01 {str(period_str).strip()}", format="%d %b %Y")
    except Exception:
        return pd.Timestamp.max


def get_period_sort_key(period_str: str, period_type: str):
    """Sort key for any period type."""
    if period_type == "Weekly":
        return parse_week_sort_key(period_str)
    elif period_type == "Monthly":
        return parse_month_sort_key(period_str)
    try:
        return pd.to_datetime(period_str, errors='coerce')
    except Exception:
        return pd.Timestamp.max


def format_period_display(period_str: str, period_type: str) -> str:
    """Format period with date range.  'Week 5 - 2025' → 'W5 (Jan 27 - Feb 02)'"""
    try:
        clean = str(period_str).strip()
        if period_type == "Weekly" and "Week" in clean and " - " in clean:
            parts = clean.split(" - ")
            week = int(parts[0].replace("Week ", "").strip())
            year = int(parts[1].strip())
            jan4 = datetime(year, 1, 4)
            ws = jan4 - timedelta(days=jan4.isoweekday() - 1) + timedelta(weeks=week - 1)
            we = ws + timedelta(days=6)
            return f"W{week} ({ws.strftime('%b %d')} - {we.strftime('%b %d')})"
        elif period_type == "Monthly":
            return clean
    except Exception:
        pass
    return str(period_str).strip()


def get_current_period(period_type: str) -> str:
    """Get current period string."""
    return convert_to_period(datetime.now(), period_type) or ""


def is_past_period(period_str: str, period_type: str,
                   reference_date: Optional[datetime] = None) -> bool:
    """Check if a period string represents a past (completed) period."""
    if reference_date is None:
        reference_date = datetime.now()
    try:
        if pd.isna(period_str) or not period_str:
            return False
        s = str(period_str).strip()

        if period_type == "Weekly":
            year, week = parse_week_sort_key(s)
            if year < 9999:
                jan4 = datetime(year, 1, 4)
                ws = jan4 - timedelta(days=jan4.isoweekday() - 1)
                we = ws + timedelta(weeks=week - 1, days=6)
                return we.date() < reference_date.date()

        elif period_type == "Monthly":
            ts = parse_month_sort_key(s)
            if ts != pd.Timestamp.max:
                next_month = ts + pd.DateOffset(months=1)
                return next_month.date() <= reference_date.date()
    except Exception:
        pass
    return False


def classify_product_type(
    product_id: int,
    demand_product_ids: set,
    supply_product_ids: set
) -> str:
    """Classify product as Matched / Demand Only / Supply Only."""
    in_demand = product_id in demand_product_ids
    in_supply = product_id in supply_product_ids
    if in_demand and in_supply:
        return "Matched"
    elif in_demand:
        return "Demand Only"
    elif in_supply:
        return "Supply Only"
    return "Unknown"


# =============================================================================
# PERIOD GAP CALCULATOR
# =============================================================================

class PeriodGAPCalculator:
    """
    Period-based GAP calculator with carry-forward and backlog tracking.
    Handles both FG products and raw materials.
    """

    def __init__(self, period_type: str = 'Weekly'):
        self.period_type = period_type

    # -----------------------------------------------------------------
    # PUBLIC: FG PERIOD GAP
    # -----------------------------------------------------------------

    def calculate_fg_period_gap(
        self,
        fg_supply_df: pd.DataFrame,
        fg_demand_df: pd.DataFrame,
        fg_safety_stock_df: Optional[pd.DataFrame] = None,
        selected_supply_sources: Optional[List[str]] = None,
        selected_demand_sources: Optional[List[str]] = None,
        include_safety: bool = True,
        track_backlog: bool = True,
        include_draft_mo: bool = False
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Calculate FG period GAP with carry-forward. Returns (gap_df, metrics)."""
        logger.info(f"Period GAP (FG): calculating {self.period_type} periods...")

        supply_df = fg_supply_df.copy() if not fg_supply_df.empty else pd.DataFrame()
        demand_df = fg_demand_df.copy() if not fg_demand_df.empty else pd.DataFrame()

        # Filter sources
        if selected_supply_sources and not supply_df.empty and 'supply_source' in supply_df.columns:
            supply_df = supply_df[supply_df['supply_source'].isin(selected_supply_sources)]
        if not include_draft_mo and not supply_df.empty and 'availability_status' in supply_df.columns:
            supply_df = supply_df[
                ~((supply_df['supply_source'] == 'MO_EXPECTED') &
                  (supply_df['availability_status'] == 'DRAFT'))
            ]
        if selected_demand_sources and not demand_df.empty and 'demand_source' in demand_df.columns:
            demand_df = demand_df[demand_df['demand_source'].isin(selected_demand_sources)]

        # Convert dates → periods
        supply_p = self._add_period_to_fg_supply(supply_df)
        demand_p = self._add_period_to_fg_demand(demand_df)

        # Collect product IDs per side for product_type classification
        demand_pids = set(demand_p['product_id'].unique()) if not demand_p.empty else set()
        supply_pids = set(supply_p['product_id'].unique()) if not supply_p.empty else set()

        # Group by (product_id, period)
        supply_g = self._group_fg_supply(supply_p)
        demand_g = self._group_fg_demand(demand_p)

        # Build full matrix
        matrix = self._build_matrix(supply_g, demand_g, 'product_id', 'supply_qty', 'demand_qty')
        if matrix.empty:
            return pd.DataFrame(), {}

        # Safety stock lookup
        safety = {}
        if include_safety and fg_safety_stock_df is not None and not fg_safety_stock_df.empty:
            for _, r in fg_safety_stock_df.iterrows():
                pid = r.get('product_id')
                if pid is not None:
                    safety[pid] = r.get('safety_stock_qty', 0) or 0

        # Apply carry-forward per product
        result_rows = []
        for pid in matrix['product_id'].unique():
            prod = matrix[matrix['product_id'] == pid].copy()
            prod = self._sort_by_period(prod)
            rows = self._apply_carry_forward(
                prod, safety.get(pid, 0), track_backlog, id_col='product_id'
            )
            result_rows.extend(rows)

        if not result_rows:
            return pd.DataFrame(), {}

        gap_df = pd.DataFrame(result_rows)
        gap_df = self._sort_final(gap_df, 'pt_code')
        gap_df['period_display'] = gap_df['period'].apply(
            lambda p: format_period_display(p, self.period_type)
        )

        # Mark past periods
        gap_df['is_past'] = gap_df['period'].apply(
            lambda p: is_past_period(p, self.period_type)
        )

        # Classify product type (Matched / Demand Only / Supply Only)
        gap_df['product_type'] = gap_df['product_id'].apply(
            lambda pid: classify_product_type(pid, demand_pids, supply_pids)
        )

        metrics = self._compute_metrics(gap_df, track_backlog, id_col='product_id')
        logger.info(f"Period GAP (FG): {len(gap_df)} rows, {metrics.get('total_products', 0)} products")
        return gap_df, metrics

    # -----------------------------------------------------------------
    # PUBLIC: RAW MATERIAL PERIOD GAP
    # -----------------------------------------------------------------

    def calculate_raw_period_gap(
        self,
        fg_period_gap_df: pd.DataFrame,
        manufacturing_product_ids: List[int],
        bom_explosion_df: pd.DataFrame,
        raw_supply_summary_df: pd.DataFrame,
        raw_safety_stock_df: Optional[pd.DataFrame] = None,
        include_safety: bool = True,
        track_backlog: bool = True,
        selected_supply_sources: Optional[List[str]] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Calculate raw material period GAP from BOM explosion of FG shortage by period.

        Approach:
        1. Filter FG period gap → manufacturing products with shortage per period
        2. BOM explode shortage qty → raw demand by (material, period)
        3. Raw supply: summary totals placed in first period (available now)
        4. Apply carry-forward per material

        Returns: (raw_period_gap_df, raw_period_metrics)
        """
        logger.info("Period GAP (Raw): calculating from FG shortage BOM explosion...")

        if fg_period_gap_df.empty or bom_explosion_df.empty:
            return pd.DataFrame(), {}

        # Step 1: FG manufacturing shortage by period
        mfg_shortage = fg_period_gap_df[
            (fg_period_gap_df['product_id'].isin(manufacturing_product_ids)) &
            (fg_period_gap_df['gap_quantity'] < 0)
        ].copy()

        if mfg_shortage.empty:
            logger.info("Period GAP (Raw): no manufacturing shortage in any period")
            return pd.DataFrame(), {}

        # Step 2: BOM explode shortage → raw demand by (material, period)
        id_col = 'output_product_id' if 'output_product_id' in bom_explosion_df.columns else 'fg_product_id'
        raw_demand = self._bom_explode_by_period(mfg_shortage, bom_explosion_df, id_col)

        if raw_demand.empty:
            return pd.DataFrame(), {}

        # Step 3: Raw supply — place summary totals in first period
        raw_supply = self._prepare_raw_supply_by_period(
            raw_supply_summary_df, raw_demand, selected_supply_sources
        )

        # Build matrix
        matrix = self._build_matrix(
            raw_supply, raw_demand, 'material_id', 'supply_qty', 'demand_qty'
        )
        if matrix.empty:
            return pd.DataFrame(), {}

        # Merge material info
        mat_info_cols = ['material_id']
        for c in ['material_pt_code', 'material_name', 'material_brand',
                   'material_package_size', 'material_uom', 'material_type', 'is_primary']:
            if c in raw_demand.columns:
                mat_info_cols.append(c)
        if len(mat_info_cols) > 1:
            mat_info = raw_demand[mat_info_cols].drop_duplicates(subset=['material_id'], keep='first')
            matrix = matrix.merge(mat_info, on='material_id', how='left')

        # Safety stock lookup
        safety = {}
        if include_safety and raw_safety_stock_df is not None and not raw_safety_stock_df.empty:
            sid = 'material_id' if 'material_id' in raw_safety_stock_df.columns else 'product_id'
            for _, r in raw_safety_stock_df.iterrows():
                mid = r.get(sid)
                if mid is not None:
                    safety[mid] = r.get('safety_stock_qty', 0) or 0

        # Apply carry-forward per material
        result_rows = []
        for mid in matrix['material_id'].unique():
            mat = matrix[matrix['material_id'] == mid].copy()
            mat = self._sort_by_period(mat)
            rows = self._apply_carry_forward(
                mat, safety.get(mid, 0), track_backlog,
                id_col='material_id',
                code_col='material_pt_code', name_col='material_name',
                brand_col='material_brand', pkg_col='material_package_size',
                uom_col='material_uom'
            )
            result_rows.extend(rows)

        if not result_rows:
            return pd.DataFrame(), {}

        gap_df = pd.DataFrame(result_rows)
        gap_df = self._sort_final(gap_df, 'material_pt_code')
        gap_df['period_display'] = gap_df['period'].apply(
            lambda p: format_period_display(p, self.period_type)
        )
        gap_df['is_past'] = gap_df['period'].apply(
            lambda p: is_past_period(p, self.period_type)
        )

        metrics = self._compute_metrics(gap_df, track_backlog, id_col='material_id')
        logger.info(f"Period GAP (Raw): {len(gap_df)} rows, {metrics.get('total_products', 0)} materials")
        return gap_df, metrics

    # -----------------------------------------------------------------
    # BOM EXPLOSION BY PERIOD
    # -----------------------------------------------------------------

    def _bom_explode_by_period(
        self,
        mfg_shortage_df: pd.DataFrame,
        bom_df: pd.DataFrame,
        fg_id_col: str
    ) -> pd.DataFrame:
        """BOM explode FG shortage per period → raw demand by (material, period)."""

        merged = bom_df.merge(
            mfg_shortage_df[['product_id', 'period', 'gap_quantity']].rename(
                columns={'product_id': fg_id_col, 'gap_quantity': 'fg_shortage'}
            ),
            on=fg_id_col, how='inner'
        )
        if merged.empty:
            return pd.DataFrame()

        merged['fg_shortage'] = merged['fg_shortage'].abs()
        bom_out = merged['bom_output_quantity'].fillna(1).replace(0, 1) \
            if 'bom_output_quantity' in merged.columns else 1
        qty_per = merged['quantity_per_output'].fillna(1) \
            if 'quantity_per_output' in merged.columns else 1
        scrap = merged['scrap_rate'].fillna(0) \
            if 'scrap_rate' in merged.columns else 0

        merged['demand_qty'] = (merged['fg_shortage'] / bom_out) * qty_per * (1 + scrap / 100)

        # Aggregate by (material_id, period)
        agg = {'demand_qty': 'sum', fg_id_col: 'nunique'}
        for c in ['material_pt_code', 'material_name', 'material_brand',
                   'material_package_size', 'material_uom', 'material_type', 'is_primary']:
            if c in merged.columns:
                agg[c] = 'first'

        result = merged.groupby(['material_id', 'period']).agg(agg).reset_index()
        result.rename(columns={fg_id_col: 'fg_product_count'}, inplace=True)
        return result

    def _prepare_raw_supply_by_period(
        self,
        summary_df: pd.DataFrame,
        demand_df: pd.DataFrame,
        selected_supply_sources: Optional[List[str]]
    ) -> pd.DataFrame:
        """
        Prepare raw supply for period analysis.
        Summary totals are placed in the FIRST demand period (available now).
        """
        if summary_df.empty or demand_df.empty:
            return pd.DataFrame()

        # Get first period from demand (earliest period = current)
        periods = demand_df['period'].unique().tolist()
        sorted_periods = sorted(periods, key=lambda p: get_period_sort_key(p, self.period_type))
        first_period = sorted_periods[0] if sorted_periods else get_current_period(self.period_type)

        # Calculate total supply per material
        SOURCE_MAP = {
            'INVENTORY': 'inventory_qty', 'CAN_PENDING': 'can_pending_qty',
            'WAREHOUSE_TRANSFER': 'warehouse_transfer_qty', 'PURCHASE_ORDER': 'purchase_order_qty'
        }

        supply_copy = summary_df.copy()
        mid_col = 'material_id' if 'material_id' in supply_copy.columns else 'product_id'

        if selected_supply_sources:
            cols = [SOURCE_MAP[s] for s in selected_supply_sources if s in SOURCE_MAP]
            if cols:
                for c in cols:
                    if c not in supply_copy.columns:
                        supply_copy[c] = 0
                supply_copy['supply_qty'] = supply_copy[cols].fillna(0).sum(axis=1)
            else:
                supply_copy['supply_qty'] = supply_copy.get('total_supply', 0)
        else:
            supply_copy['supply_qty'] = supply_copy.get('total_supply', 0)

        # Place all supply in first period
        result = supply_copy[[mid_col, 'supply_qty']].copy()
        if mid_col != 'material_id':
            result.rename(columns={mid_col: 'material_id'}, inplace=True)
        result['period'] = first_period
        result = result[result['supply_qty'] > 0]

        return result

    # -----------------------------------------------------------------
    # DATE → PERIOD CONVERSION
    # -----------------------------------------------------------------

    def _add_period_to_fg_supply(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        date_col = 'availability_date'
        if date_col not in df.columns:
            for fb in ['date_ref', 'expected_date']:
                if fb in df.columns:
                    date_col = fb
                    break
            else:
                df['_date'] = pd.Timestamp.now().normalize()
                date_col = '_date'
        df['period'] = df[date_col].apply(lambda x: convert_to_period(x, self.period_type))
        return df[df['period'].notna() & (df['period'] != 'nan')]

    def _add_period_to_fg_demand(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        date_col = 'required_date'
        if date_col not in df.columns:
            for fb in ['demand_date', 'etd']:
                if fb in df.columns:
                    date_col = fb
                    break
            else:
                return df.head(0)
        df['period'] = df[date_col].apply(lambda x: convert_to_period(x, self.period_type))
        return df[df['period'].notna() & (df['period'] != 'nan')]

    # -----------------------------------------------------------------
    # GROUPING
    # -----------------------------------------------------------------

    def _group_fg_supply(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        agg = {'available_quantity': 'sum'}
        for c in ['pt_code', 'product_name', 'brand', 'package_size', 'standard_uom']:
            if c in df.columns:
                agg[c] = 'first'
        g = df.groupby(['product_id', 'period']).agg(agg).reset_index()
        g.rename(columns={'available_quantity': 'supply_qty'}, inplace=True)
        return g

    def _group_fg_demand(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        agg = {'required_quantity': 'sum'}
        for c in ['pt_code', 'product_name', 'brand', 'package_size', 'standard_uom']:
            if c in df.columns:
                agg[c] = 'first'
        if 'customer' in df.columns:
            agg['customer'] = 'nunique'
        g = df.groupby(['product_id', 'period']).agg(agg).reset_index()
        g.rename(columns={'required_quantity': 'demand_qty', 'customer': 'customer_count'}, inplace=True)
        return g

    # -----------------------------------------------------------------
    # MATRIX BUILDER (generic)
    # -----------------------------------------------------------------

    def _build_matrix(
        self, supply_g: pd.DataFrame, demand_g: pd.DataFrame,
        id_col: str, supply_val: str, demand_val: str
    ) -> pd.DataFrame:
        """Build full ID × period matrix from supply + demand grouped data."""
        all_keys = set()
        for df in [supply_g, demand_g]:
            if not df.empty and id_col in df.columns and 'period' in df.columns:
                all_keys.update(zip(df[id_col], df['period']))
        if not all_keys:
            return pd.DataFrame()

        base = pd.DataFrame(list(all_keys), columns=[id_col, 'period'])

        # Merge product info from both sides
        info_frames = []
        for df in [demand_g, supply_g]:
            if df.empty:
                continue
            info_cols = [id_col]
            for c in df.columns:
                if c not in [id_col, 'period', supply_val, demand_val, 'customer_count']:
                    info_cols.append(c)
            if len(info_cols) > 1:
                info_frames.append(df[info_cols].drop_duplicates(subset=[id_col], keep='first'))
        if info_frames:
            info = pd.concat(info_frames, ignore_index=True).drop_duplicates(subset=[id_col], keep='first')
            base = base.merge(info, on=id_col, how='left')

        # Merge values
        if not supply_g.empty and supply_val in supply_g.columns:
            base = base.merge(supply_g[[id_col, 'period', supply_val]], on=[id_col, 'period'], how='left')
        if not demand_g.empty and demand_val in demand_g.columns:
            merge_cols = [id_col, 'period', demand_val]
            if 'customer_count' in demand_g.columns:
                merge_cols.append('customer_count')
            base = base.merge(demand_g[merge_cols], on=[id_col, 'period'], how='left')

        base[supply_val] = base.get(supply_val, pd.Series(dtype=float)).fillna(0)
        base[demand_val] = base.get(demand_val, pd.Series(dtype=float)).fillna(0)
        if 'customer_count' not in base.columns:
            base['customer_count'] = 0
        else:
            base['customer_count'] = base['customer_count'].fillna(0).astype(int)

        return base

    # -----------------------------------------------------------------
    # SORTING
    # -----------------------------------------------------------------

    def _sort_by_period(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_sk'] = df['period'].apply(lambda p: get_period_sort_key(p, self.period_type))
        return df.sort_values('_sk').drop(columns=['_sk'])

    def _sort_final(self, df: pd.DataFrame, code_col: str) -> pd.DataFrame:
        df = df.copy()
        df['_sp'] = df['period'].apply(lambda p: get_period_sort_key(p, self.period_type))
        sort_cols = [code_col, '_sp'] if code_col in df.columns else ['_sp']
        return df.sort_values(sort_cols).drop(columns=['_sp']).reset_index(drop=True)

    # -----------------------------------------------------------------
    # CARRY-FORWARD ENGINE (generic)
    # -----------------------------------------------------------------

    def _apply_carry_forward(
        self, product_periods: pd.DataFrame,
        safety_stock_qty: float, track_backlog: bool,
        id_col: str = 'product_id',
        code_col: str = 'pt_code', name_col: str = 'product_name',
        brand_col: str = 'brand', pkg_col: str = 'package_size',
        uom_col: str = 'standard_uom'
    ) -> List[Dict[str, Any]]:
        """Apply carry-forward for ONE item across sorted periods."""
        rows = []
        carry = 0.0
        backlog = safety_stock_qty

        for _, row in product_periods.iterrows():
            begin_inv = carry
            backlog_prev = backlog
            supply_in = row.get('supply_qty', 0)
            demand_in = row.get('demand_qty', 0)

            if track_backlog:
                eff_demand = demand_in + backlog
                total_avail = supply_in + carry
                gap = total_avail - eff_demand
                if gap >= 0:
                    carry, backlog = gap, 0.0
                else:
                    carry, backlog = 0.0, abs(gap)
                fill = min(100.0, total_avail / eff_demand * 100) if eff_demand > 0 else (100.0 if total_avail > 0 else 0.0)
            else:
                total_avail = supply_in + carry
                gap = total_avail - demand_in
                carry = max(0.0, gap)
                eff_demand = demand_in
                backlog_prev = backlog = 0.0
                fill = min(100.0, total_avail / demand_in * 100) if demand_in > 0 else (100.0 if total_avail > 0 else 0.0)

            r = {
                id_col: row[id_col],
                code_col: row.get(code_col, ''),
                name_col: row.get(name_col, ''),
                brand_col: row.get(brand_col, ''),
                pkg_col: row.get(pkg_col, ''),
                uom_col: row.get(uom_col, ''),
                'period': row['period'],
                'begin_inventory': round(begin_inv),
                'supply_in_period': round(supply_in),
                'total_available': round(total_avail),
                'demand_in_period': round(demand_in),
                'gap_quantity': round(gap),
                'fulfillment_rate': round(fill, 1),
                'fulfillment_status': "✅ Fulfilled" if gap >= 0 else "❌ Shortage",
                'customer_count': int(row.get('customer_count', 0)),
            }
            if track_backlog:
                r['backlog_from_prev'] = round(backlog_prev)
                r['effective_demand'] = round(eff_demand)
                r['backlog_to_next'] = round(backlog)
            rows.append(r)
        return rows

    # -----------------------------------------------------------------
    # METRICS
    # -----------------------------------------------------------------

    def _compute_metrics(self, gap_df: pd.DataFrame, track_backlog: bool,
                         id_col: str = 'product_id') -> Dict[str, Any]:
        if gap_df.empty:
            return {}
        shortage = gap_df[gap_df['gap_quantity'] < 0]
        m = {
            'total_products': int(gap_df[id_col].nunique()),
            'total_periods': int(gap_df['period'].nunique()),
            'shortage_products': int(shortage[id_col].nunique()) if not shortage.empty else 0,
            'shortage_periods': int(shortage['period'].nunique()) if not shortage.empty else 0,
            'total_shortage_qty': float(shortage['gap_quantity'].abs().sum()) if not shortage.empty else 0,
            'avg_fulfillment_rate': float(gap_df['fulfillment_rate'].mean()),
        }
        if track_backlog and 'backlog_to_next' in gap_df.columns:
            fb = gap_df.groupby(id_col)['backlog_to_next'].last()
            m['total_final_backlog'] = float(fb.sum())
            m['products_with_backlog'] = int((fb > 0).sum())
        if not shortage.empty:
            s2 = shortage.copy()
            s2['_sk'] = s2['period'].apply(lambda p: get_period_sort_key(p, self.period_type))
            m['first_shortage_period'] = s2.sort_values('_sk').iloc[0]['period']
        return m


# =============================================================================
# FILTER + PIVOT HELPERS
# =============================================================================

def filter_period_gap_by_product_ids(
    period_gap_df: pd.DataFrame,
    product_ids: List[int],
    id_col: str = 'product_id'
) -> pd.DataFrame:
    """Filter period gap to specific product IDs."""
    if period_gap_df.empty or not product_ids:
        return pd.DataFrame()
    return period_gap_df[period_gap_df[id_col].isin(product_ids)].copy()


def create_pivot_data(
    period_gap_df: pd.DataFrame,
    period_type: str = 'Weekly',
    code_col: str = 'pt_code',
    name_col: str = 'product_name',
    value_col: str = 'gap_quantity'
) -> pd.DataFrame:
    """
    Create pivot table: rows=products, columns=periods, values=gap_quantity.
    Returns styled-ready DataFrame.
    """
    if period_gap_df.empty:
        return pd.DataFrame()

    # Sort periods
    all_periods = period_gap_df['period'].unique().tolist()
    sorted_periods = sorted(all_periods, key=lambda p: get_period_sort_key(p, period_type))

    # Create pivot
    pivot = period_gap_df.pivot_table(
        index=[code_col, name_col] if name_col in period_gap_df.columns else [code_col],
        columns='period',
        values=value_col,
        aggfunc='sum',
        fill_value=0
    )

    # Reorder columns by sorted periods
    available_cols = [p for p in sorted_periods if p in pivot.columns]
    pivot = pivot[available_cols]

    # Add category column (total GAP across all periods)
    pivot['_total_gap'] = pivot.sum(axis=1)
    pivot['Category'] = pivot['_total_gap'].apply(
        lambda x: '🔺 Shortage' if x < 0 else ('📈 Surplus' if x > 0 else '✅ Balanced')
    )

    # Format column headers — mark past periods with 🔴
    def _format_col(col_name):
        if col_name in ('_total_gap', 'Category'):
            return col_name
        display = format_period_display(col_name, period_type)
        if is_past_period(col_name, period_type):
            return f"🔴 {display}"
        return f"🟢 {display}"
    
    pivot.columns = [_format_col(c) for c in pivot.columns]

    # Drop helper column
    pivot = pivot.drop(columns=['_total_gap'])

    # Move Category to first position
    cols = pivot.columns.tolist()
    if 'Category' in cols:
        cols.remove('Category')
        cols.insert(0, 'Category')
        pivot = pivot[cols]

    return pivot.reset_index()


# =============================================================================
# ANALYSIS HELPERS
# =============================================================================

def identify_critical_shortage_periods(
    period_gap_df: pd.DataFrame, period_type: str = 'Weekly', top_n: int = 10,
    id_col: str = 'product_id'
) -> pd.DataFrame:
    """Periods with the largest aggregate shortage."""
    if period_gap_df.empty:
        return pd.DataFrame()
    shortage = period_gap_df[period_gap_df['gap_quantity'] < 0]
    if shortage.empty:
        return pd.DataFrame()
    agg = shortage.groupby('period').agg(
        total_shortage=('gap_quantity', lambda x: x.abs().sum()),
        products_affected=(id_col, 'nunique'),
        avg_fulfillment=('fulfillment_rate', 'mean'),
    ).reset_index()
    agg = agg.sort_values('total_shortage', ascending=False).head(top_n)
    agg['period_display'] = agg['period'].apply(lambda p: format_period_display(p, period_type))
    return agg.reset_index(drop=True)


def identify_critical_shortage_products(
    period_gap_df: pd.DataFrame, top_n: int = 10,
    code_col: str = 'pt_code'
) -> pd.DataFrame:
    """Products with the largest total period shortage."""
    if period_gap_df.empty:
        return pd.DataFrame()
    shortage = period_gap_df[period_gap_df['gap_quantity'] < 0]
    if shortage.empty:
        return pd.DataFrame()
    agg_dict = {'gap_quantity': lambda x: x.abs().sum(), 'fulfillment_rate': 'mean', 'period': 'nunique'}
    for c in ['product_name', 'brand', 'standard_uom']:
        if c in shortage.columns:
            agg_dict[c] = 'first'
    agg = shortage.groupby(code_col).agg(agg_dict).reset_index()
    agg.rename(columns={'gap_quantity': 'total_shortage', 'fulfillment_rate': 'avg_fulfillment', 'period': 'shortage_periods'}, inplace=True)
    return agg.sort_values('total_shortage', ascending=False).head(top_n).reset_index(drop=True)


def get_product_period_timeline(period_gap_df: pd.DataFrame, product_id: int) -> pd.DataFrame:
    """Full period timeline for a single product."""
    if period_gap_df.empty:
        return pd.DataFrame()
    return period_gap_df[period_gap_df['product_id'] == product_id].copy()