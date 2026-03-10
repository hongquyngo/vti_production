# utils/supply_chain_gap/period_calculator.py

"""
Period-based GAP Calculator for Supply Chain GAP Analysis
Calculates GAP by time period (Weekly/Monthly) with carry-forward & backlog tracking.

This answers: WHEN do shortages occur? — enabling production/procurement planning by lead time.

VERSION: 2.2.0
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

from .constants import PERIOD_TYPES, STATUS_CONFIG

logger = logging.getLogger(__name__)


# =============================================================================
# PERIOD HELPER FUNCTIONS
# =============================================================================

def convert_to_period(date_value, period_type: str) -> Optional[str]:
    """Convert a date to a period string (Weekly / Monthly)."""
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
        else:
            return date_val.strftime('%Y-%m-%d')
    except Exception:
        return None


def parse_week_sort_key(period_str: str) -> Tuple[int, int]:
    """Parse 'Week N - YYYY' → (year, week) for sorting."""
    try:
        if pd.isna(period_str) or not period_str:
            return (9999, 99)
        period_str = str(period_str).strip()
        if " - " in period_str and period_str.startswith("Week "):
            parts = period_str.split(" - ")
            week = int(parts[0].replace("Week ", "").strip())
            year = int(parts[1].strip())
            if 1 <= week <= 53:
                return (year, week)
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


def format_period_display(period_str: str, period_type: str) -> str:
    """
    Format period with date range.
    'Week 5 - 2025' → 'Week 5 (Jan 27 - Feb 02, 2025)'
    """
    try:
        clean = str(period_str).strip()
        if period_type == "Weekly" and "Week" in clean and " - " in clean:
            parts = clean.split(" - ")
            week = int(parts[0].replace("Week ", "").strip())
            year = int(parts[1].strip())
            jan4 = datetime(year, 1, 4)
            week_start = jan4 - timedelta(days=jan4.isoweekday() - 1)
            target_start = week_start + timedelta(weeks=week - 1)
            target_end = target_start + timedelta(days=6)
            return f"W{week} ({target_start.strftime('%b %d')} - {target_end.strftime('%b %d')})"
        elif period_type == "Monthly":
            return clean
    except Exception:
        pass
    return str(period_str).strip()


def get_period_sort_key(period_str: str, period_type: str):
    """Get sort key for any period type."""
    if period_type == "Weekly":
        return parse_week_sort_key(period_str)
    elif period_type == "Monthly":
        return parse_month_sort_key(period_str)
    else:
        try:
            return pd.to_datetime(period_str, errors='coerce')
        except Exception:
            return pd.Timestamp.max


# =============================================================================
# PERIOD GAP CALCULATOR
# =============================================================================

class PeriodGAPCalculator:
    """
    Period-based GAP calculator with carry-forward and backlog tracking.

    Flow:
    1. Convert supply/demand dates → periods
    2. Group by (product_id, period)
    3. Build full product × period matrix
    4. Apply carry-forward logic per product across sorted periods
    5. Return period GAP DataFrame
    """

    def __init__(self, period_type: str = 'Weekly'):
        self.period_type = period_type

    # -----------------------------------------------------------------
    # PUBLIC
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
        """
        Calculate FG period GAP with carry-forward.

        Returns:
            (period_gap_df, period_metrics)
        """
        logger.info(f"Period GAP: calculating {self.period_type} periods...")

        # --- Filter sources ---
        supply_df = fg_supply_df.copy() if not fg_supply_df.empty else pd.DataFrame()
        demand_df = fg_demand_df.copy() if not fg_demand_df.empty else pd.DataFrame()

        if selected_supply_sources and not supply_df.empty and 'supply_source' in supply_df.columns:
            supply_df = supply_df[supply_df['supply_source'].isin(selected_supply_sources)]

        # Filter DRAFT MO if not included
        if not include_draft_mo and not supply_df.empty and 'availability_status' in supply_df.columns:
            supply_df = supply_df[
                ~((supply_df['supply_source'] == 'MO_EXPECTED') &
                  (supply_df['availability_status'] == 'DRAFT'))
            ]

        if selected_demand_sources and not demand_df.empty and 'demand_source' in demand_df.columns:
            demand_df = demand_df[demand_df['demand_source'].isin(selected_demand_sources)]

        # --- Convert dates to periods ---
        supply_with_period = self._add_period_to_supply(supply_df)
        demand_with_period = self._add_period_to_demand(demand_df)

        # --- Group by (product_id, period) ---
        supply_grouped = self._group_supply(supply_with_period)
        demand_grouped = self._group_demand(demand_with_period)

        # --- Build product × period matrix ---
        period_matrix = self._build_period_matrix(supply_grouped, demand_grouped)

        if period_matrix.empty:
            return pd.DataFrame(), {}

        # --- Prepare safety stock lookup ---
        safety_lookup: Dict[int, float] = {}
        if include_safety and fg_safety_stock_df is not None and not fg_safety_stock_df.empty:
            for _, row in fg_safety_stock_df.iterrows():
                pid = row.get('product_id')
                qty = row.get('safety_stock_qty', 0) or 0
                if pid is not None:
                    safety_lookup[pid] = qty

        # --- Apply carry-forward per product ---
        result_rows = []
        for product_id in period_matrix['product_id'].unique():
            prod_data = period_matrix[period_matrix['product_id'] == product_id].copy()

            # Sort by period
            prod_data['_sort'] = prod_data['period'].apply(
                lambda p: get_period_sort_key(p, self.period_type)
            )
            prod_data = prod_data.sort_values('_sort').drop(columns=['_sort'])

            safety_qty = safety_lookup.get(product_id, 0)

            rows = self._apply_carry_forward(
                prod_data, safety_qty, track_backlog
            )
            result_rows.extend(rows)

        if not result_rows:
            return pd.DataFrame(), {}

        gap_df = pd.DataFrame(result_rows)

        # Global sort: product → period
        gap_df['_sort_period'] = gap_df['period'].apply(
            lambda p: get_period_sort_key(p, self.period_type)
        )
        gap_df = gap_df.sort_values(['pt_code', '_sort_period']).drop(
            columns=['_sort_period']
        ).reset_index(drop=True)

        # Add display period
        gap_df['period_display'] = gap_df['period'].apply(
            lambda p: format_period_display(p, self.period_type)
        )

        # Metrics
        metrics = self._compute_period_metrics(gap_df, track_backlog)

        logger.info(
            f"Period GAP complete: {len(gap_df)} rows, "
            f"{gap_df['product_id'].nunique()} products, "
            f"{gap_df['period'].nunique()} periods"
        )

        return gap_df, metrics

    # -----------------------------------------------------------------
    # DATE → PERIOD CONVERSION
    # -----------------------------------------------------------------

    def _add_period_to_supply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add period column to supply using availability_date."""
        if df.empty:
            return df
        df = df.copy()

        date_col = 'availability_date'
        if date_col not in df.columns:
            # Fallback: try other date columns
            for fallback in ['date_ref', 'expected_date']:
                if fallback in df.columns:
                    date_col = fallback
                    break
            else:
                logger.warning("No date column found in supply; using today")
                df['_date'] = pd.Timestamp.now().normalize()
                date_col = '_date'

        df['period'] = df[date_col].apply(
            lambda x: convert_to_period(x, self.period_type)
        )
        df = df[df['period'].notna() & (df['period'] != 'nan')]
        return df

    def _add_period_to_demand(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add period column to demand using required_date."""
        if df.empty:
            return df
        df = df.copy()

        date_col = 'required_date'
        if date_col not in df.columns:
            for fallback in ['demand_date', 'etd']:
                if fallback in df.columns:
                    date_col = fallback
                    break
            else:
                logger.warning("No date column found in demand")
                return df.head(0)

        df['period'] = df[date_col].apply(
            lambda x: convert_to_period(x, self.period_type)
        )
        df = df[df['period'].notna() & (df['period'] != 'nan')]
        return df

    # -----------------------------------------------------------------
    # GROUPING
    # -----------------------------------------------------------------

    def _group_supply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Group supply by (product_id, period)."""
        if df.empty:
            return pd.DataFrame()

        agg = {'available_quantity': 'sum'}
        for col in ['pt_code', 'product_name', 'brand', 'package_size', 'standard_uom']:
            if col in df.columns:
                agg[col] = 'first'

        grouped = df.groupby(['product_id', 'period']).agg(agg).reset_index()
        grouped.rename(columns={'available_quantity': 'supply_qty'}, inplace=True)
        return grouped

    def _group_demand(self, df: pd.DataFrame) -> pd.DataFrame:
        """Group demand by (product_id, period)."""
        if df.empty:
            return pd.DataFrame()

        agg = {'required_quantity': 'sum'}
        for col in ['pt_code', 'product_name', 'brand', 'package_size', 'standard_uom']:
            if col in df.columns:
                agg[col] = 'first'
        if 'customer' in df.columns:
            agg['customer'] = 'nunique'

        grouped = df.groupby(['product_id', 'period']).agg(agg).reset_index()
        grouped.rename(columns={
            'required_quantity': 'demand_qty',
            'customer': 'customer_count'
        }, inplace=True)
        return grouped

    # -----------------------------------------------------------------
    # MATRIX BUILDER
    # -----------------------------------------------------------------

    def _build_period_matrix(
        self,
        supply_grouped: pd.DataFrame,
        demand_grouped: pd.DataFrame
    ) -> pd.DataFrame:
        """Build full product × period matrix with merged info."""

        all_keys = set()
        for df in [supply_grouped, demand_grouped]:
            if not df.empty and 'product_id' in df.columns and 'period' in df.columns:
                keys = list(zip(df['product_id'], df['period']))
                all_keys.update(keys)

        if not all_keys:
            return pd.DataFrame()

        base = pd.DataFrame(list(all_keys), columns=['product_id', 'period'])

        # Gather product info from both sides
        info_frames = []
        for df in [demand_grouped, supply_grouped]:
            if df.empty:
                continue
            info_cols = ['product_id']
            for c in ['pt_code', 'product_name', 'brand', 'package_size', 'standard_uom']:
                if c in df.columns:
                    info_cols.append(c)
            if len(info_cols) > 1:
                info_frames.append(df[info_cols].drop_duplicates(subset=['product_id'], keep='first'))

        if info_frames:
            product_info = pd.concat(info_frames, ignore_index=True).drop_duplicates(
                subset=['product_id'], keep='first'
            )
            base = base.merge(product_info, on='product_id', how='left')

        # Merge supply qty
        if not supply_grouped.empty:
            base = base.merge(
                supply_grouped[['product_id', 'period', 'supply_qty']],
                on=['product_id', 'period'], how='left'
            )

        # Merge demand qty + customer count
        if not demand_grouped.empty:
            demand_cols = ['product_id', 'period', 'demand_qty']
            if 'customer_count' in demand_grouped.columns:
                demand_cols.append('customer_count')
            base = base.merge(
                demand_grouped[demand_cols],
                on=['product_id', 'period'], how='left'
            )

        base['supply_qty'] = base['supply_qty'].fillna(0)
        base['demand_qty'] = base['demand_qty'].fillna(0)
        if 'customer_count' not in base.columns:
            base['customer_count'] = 0
        else:
            base['customer_count'] = base['customer_count'].fillna(0).astype(int)

        return base

    # -----------------------------------------------------------------
    # CARRY-FORWARD ENGINE
    # -----------------------------------------------------------------

    def _apply_carry_forward(
        self,
        product_periods: pd.DataFrame,
        safety_stock_qty: float,
        track_backlog: bool
    ) -> List[Dict[str, Any]]:
        """
        Apply carry-forward logic for ONE product across sorted periods.

        Safety stock is treated as initial backlog:
        - carry_forward starts at 0
        - backlog starts at safety_stock_qty (must be "filled" first)

        With track_backlog=True:
            effective_demand = demand + backlog_from_previous
            total_available  = supply + carry_forward
            gap              = total_available - effective_demand
            if gap >= 0: carry_forward=gap, backlog=0
            else:        carry_forward=0,   backlog=|gap|

        With track_backlog=False:
            total_available = supply + carry_forward
            gap = total_available - demand
            carry_forward = max(0, gap)  (negative gap does NOT carry)
        """
        rows = []
        carry_forward = 0.0
        backlog = safety_stock_qty  # safety stock = initial "reserved" demand

        for _, row in product_periods.iterrows():
            begin_inv = carry_forward
            backlog_from_prev = backlog

            supply_in = row['supply_qty']
            demand_in = row['demand_qty']

            if track_backlog:
                effective_demand = demand_in + backlog
                total_available = supply_in + carry_forward
                gap = total_available - effective_demand

                if gap >= 0:
                    carry_forward = gap
                    backlog = 0.0
                else:
                    carry_forward = 0.0
                    backlog = abs(gap)

                if effective_demand > 0:
                    fulfillment = min(100.0, total_available / effective_demand * 100)
                else:
                    fulfillment = 100.0 if total_available > 0 else 0.0
            else:
                total_available = supply_in + carry_forward
                gap = total_available - demand_in
                carry_forward = max(0.0, gap)
                effective_demand = demand_in
                backlog_from_prev = 0.0
                backlog = 0.0

                if demand_in > 0:
                    fulfillment = min(100.0, total_available / demand_in * 100)
                else:
                    fulfillment = 100.0 if total_available > 0 else 0.0

            status = "✅ Fulfilled" if gap >= 0 else "❌ Shortage"

            result = {
                'product_id': row['product_id'],
                'pt_code': row.get('pt_code', ''),
                'product_name': row.get('product_name', ''),
                'brand': row.get('brand', ''),
                'package_size': row.get('package_size', ''),
                'standard_uom': row.get('standard_uom', ''),
                'period': row['period'],
                'begin_inventory': round(begin_inv, 0),
                'supply_in_period': round(supply_in, 0),
                'total_available': round(total_available, 0),
                'demand_in_period': round(demand_in, 0),
                'gap_quantity': round(gap, 0),
                'fulfillment_rate': round(fulfillment, 1),
                'fulfillment_status': status,
                'customer_count': row.get('customer_count', 0),
            }

            if track_backlog:
                result['backlog_from_prev'] = round(backlog_from_prev, 0)
                result['effective_demand'] = round(effective_demand, 0)
                result['backlog_to_next'] = round(backlog, 0)

            rows.append(result)

        return rows

    # -----------------------------------------------------------------
    # METRICS
    # -----------------------------------------------------------------

    def _compute_period_metrics(
        self, gap_df: pd.DataFrame, track_backlog: bool
    ) -> Dict[str, Any]:
        """Compute summary metrics from period GAP results."""
        if gap_df.empty:
            return {}

        shortage_df = gap_df[gap_df['gap_quantity'] < 0]

        metrics = {
            'total_products': int(gap_df['product_id'].nunique()),
            'total_periods': int(gap_df['period'].nunique()),
            'shortage_products': int(shortage_df['product_id'].nunique()),
            'shortage_periods': int(shortage_df['period'].nunique()),
            'total_shortage_qty': float(shortage_df['gap_quantity'].abs().sum()),
            'avg_fulfillment_rate': float(gap_df['fulfillment_rate'].mean()),
            'min_fulfillment_rate': float(gap_df['fulfillment_rate'].min()),
        }

        if track_backlog and 'backlog_to_next' in gap_df.columns:
            final_backlog = gap_df.groupby('product_id')['backlog_to_next'].last()
            metrics['total_final_backlog'] = float(final_backlog.sum())
            metrics['products_with_backlog'] = int((final_backlog > 0).sum())

        # First shortage period
        if not shortage_df.empty:
            shortage_df_sorted = shortage_df.copy()
            shortage_df_sorted['_sk'] = shortage_df_sorted['period'].apply(
                lambda p: get_period_sort_key(p, self.period_type)
            )
            first_shortage_period = shortage_df_sorted.sort_values('_sk').iloc[0]['period']
            metrics['first_shortage_period'] = first_shortage_period

        return metrics


# =============================================================================
# ANALYSIS HELPERS
# =============================================================================

def identify_critical_shortage_periods(
    period_gap_df: pd.DataFrame,
    period_type: str = 'Weekly',
    top_n: int = 10
) -> pd.DataFrame:
    """Identify periods with the largest aggregate shortage."""
    if period_gap_df.empty:
        return pd.DataFrame()

    shortage = period_gap_df[period_gap_df['gap_quantity'] < 0]
    if shortage.empty:
        return pd.DataFrame()

    agg = shortage.groupby('period').agg(
        total_shortage=('gap_quantity', lambda x: x.abs().sum()),
        products_affected=('product_id', 'nunique'),
        avg_fulfillment=('fulfillment_rate', 'mean'),
    ).reset_index()

    agg = agg.sort_values('total_shortage', ascending=False).head(top_n)
    agg['period_display'] = agg['period'].apply(
        lambda p: format_period_display(p, period_type)
    )
    return agg.reset_index(drop=True)


def identify_critical_shortage_products(
    period_gap_df: pd.DataFrame,
    top_n: int = 10
) -> pd.DataFrame:
    """Identify products with the largest total period shortage."""
    if period_gap_df.empty:
        return pd.DataFrame()

    shortage = period_gap_df[period_gap_df['gap_quantity'] < 0]
    if shortage.empty:
        return pd.DataFrame()

    agg_dict = {
        'gap_quantity': lambda x: x.abs().sum(),
        'fulfillment_rate': 'mean',
        'period': 'nunique',
    }
    for col in ['product_name', 'brand', 'package_size', 'standard_uom']:
        if col in shortage.columns:
            agg_dict[col] = 'first'

    agg = shortage.groupby('pt_code').agg(agg_dict).reset_index()
    agg.rename(columns={
        'gap_quantity': 'total_shortage',
        'fulfillment_rate': 'avg_fulfillment',
        'period': 'shortage_periods',
    }, inplace=True)

    return agg.sort_values('total_shortage', ascending=False).head(top_n).reset_index(drop=True)


def get_product_period_timeline(
    period_gap_df: pd.DataFrame,
    product_id: int
) -> pd.DataFrame:
    """Get full period timeline for a single product."""
    if period_gap_df.empty:
        return pd.DataFrame()
    return period_gap_df[period_gap_df['product_id'] == product_id].copy()
