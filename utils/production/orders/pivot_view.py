# utils/production/orders/pivot_view.py
"""
Pivot View component for Production Orders
Allows analyzing orders by Product × Time Period with configurable grouping

Version: 1.1.0
Changes:
- v1.1.0: Applied Fragment pattern for performance
          + Config panel uses st.form (no rerun on each change)
          + Pivot table wrapped in @st.fragment
          + Drill-down in separate fragment
          + Only pivot section reruns, not full page
- v1.0.0: Initial implementation

Features:
- Time grouping: Daily, Weekly, Monthly, Quarterly
- Row dimensions: Product, BOM Type, Status, Priority, Warehouse, Brand
- Value metrics: Order Count, Planned Qty, Produced Qty
- Cell drill-down to see individual orders
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal

import streamlit as st
import pandas as pd
import numpy as np

from .queries import OrderQueries
from .common import (
    format_number, get_vietnam_today, get_vietnam_now,
    format_date, OrderConstants
)

logger = logging.getLogger(__name__)


class PivotViewConfig:
    """Configuration constants for Pivot View"""
    
    # Time grouping options
    TIME_GROUPS = {
        'daily': 'Daily',
        'weekly': 'Weekly', 
        'monthly': 'Monthly',
        'quarterly': 'Quarterly'
    }
    
    # Row dimension options
    ROW_DIMENSIONS = {
        'product': 'Product',
        'bom_type': 'BOM Type',
        'status': 'Status',
        'priority': 'Priority',
        'source_warehouse': 'Source Warehouse',
        'target_warehouse': 'Target Warehouse',
        'brand': 'Brand'
    }
    
    # Value metrics
    VALUE_METRICS = {
        'order_count': 'Order Count',
        'planned_qty': 'Planned Qty',
        'produced_qty': 'Produced Qty',
        'pending_qty': 'Pending Qty'
    }
    
    # Default settings
    DEFAULT_TIME_GROUP = 'daily'
    DEFAULT_ROW_DIMENSION = 'product'
    DEFAULT_METRIC = 'planned_qty'
    DEFAULT_STATUSES = ['DRAFT', 'CONFIRMED', 'IN_PROGRESS']


class OrderPivotView:
    """Pivot View for Production Orders analysis with Fragment optimization"""
    
    def __init__(self):
        self.queries = OrderQueries()
        self.config = PivotViewConfig()
    
    # ==================== Session State Initialization ====================
    
    def _init_session_state(self):
        """Initialize session state for pivot view"""
        defaults = {
            'pivot_time_group': self.config.DEFAULT_TIME_GROUP,
            'pivot_row_dimension': self.config.DEFAULT_ROW_DIMENSION,
            'pivot_metric': self.config.DEFAULT_METRIC,
            'pivot_date_type': 'scheduled',
            'pivot_status_filter': self.config.DEFAULT_STATUSES.copy(),
            'pivot_from_date': None,
            'pivot_to_date': None,
            'pivot_data_loaded': False,
            'pivot_df': None,
            'pivot_cell_data_map': {},
            'pivot_applied_config': None,
        }
        
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value
        
        # Set default dates if not set
        if st.session_state.pivot_from_date is None:
            from_date, to_date = self._get_default_date_range(st.session_state.pivot_time_group)
            st.session_state.pivot_from_date = from_date
            st.session_state.pivot_to_date = to_date
    
    def _get_default_date_range(self, time_group: str) -> Tuple[date, date]:
        """Get default date range based on time grouping"""
        today = get_vietnam_today()
        
        if time_group == 'daily':
            from_date = today - timedelta(days=6)
            to_date = today + timedelta(days=7)
        elif time_group == 'weekly':
            from_date = today - timedelta(days=today.weekday())
            to_date = from_date + timedelta(days=27)
        elif time_group == 'monthly':
            from_date = today.replace(day=1)
            if today.month <= 9:
                to_date = today.replace(month=today.month + 3, day=1) - timedelta(days=1)
            else:
                to_date = today.replace(year=today.year + 1, month=(today.month + 3) % 12 or 12, day=1) - timedelta(days=1)
        else:
            from_date = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
            to_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        
        return from_date, to_date
    
    # ==================== Data Preparation ====================
    
    def get_pivot_data(self, 
                       from_date: date,
                       to_date: date,
                       status_filter: Optional[List[str]] = None,
                       date_type: str = 'scheduled') -> pd.DataFrame:
        """Get orders data for pivot analysis"""
        orders = self.queries.get_orders(
            status=status_filter,
            from_date=from_date,
            to_date=to_date,
            date_type=date_type,
            page=1,
            page_size=10000
        )
        
        if orders is None or orders.empty:
            return pd.DataFrame()
        
        orders['pending_qty'] = orders['planned_qty'] - orders['produced_qty']
        
        date_col = 'scheduled_date' if date_type == 'scheduled' else 'order_date'
        orders[date_col] = pd.to_datetime(orders[date_col])
        
        return orders
    
    def generate_time_periods(self, 
                              from_date: date, 
                              to_date: date,
                              time_group: str) -> List[Dict[str, Any]]:
        """Generate time period columns based on grouping"""
        periods = []
        current = from_date
        
        if time_group == 'daily':
            while current <= to_date:
                periods.append({
                    'start': current,
                    'end': current,
                    'label': current.strftime('%d/%m'),
                    'full_label': current.strftime('%d/%m/%Y')
                })
                current += timedelta(days=1)
                
        elif time_group == 'weekly':
            week_start = from_date - timedelta(days=from_date.weekday())
            week_num = 1
            
            while week_start <= to_date:
                week_end = week_start + timedelta(days=6)
                
                periods.append({
                    'start': week_start,
                    'end': week_end,
                    'label': f"W{week_num} ({week_start.strftime('%d/%m')})",
                    'full_label': f"Week {week_num}: {week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}"
                })
                week_start += timedelta(days=7)
                week_num += 1
                
        elif time_group == 'monthly':
            current_year = from_date.year
            current_month = from_date.month
            
            while date(current_year, current_month, 1) <= to_date:
                month_start = date(current_year, current_month, 1)
                
                if current_month == 12:
                    month_end = date(current_year + 1, 1, 1) - timedelta(days=1)
                else:
                    month_end = date(current_year, current_month + 1, 1) - timedelta(days=1)
                
                periods.append({
                    'start': month_start,
                    'end': month_end,
                    'label': month_start.strftime('%b %Y'),
                    'full_label': month_start.strftime('%B %Y')
                })
                
                if current_month == 12:
                    current_month = 1
                    current_year += 1
                else:
                    current_month += 1
                    
        elif time_group == 'quarterly':
            current_year = from_date.year
            current_quarter = (from_date.month - 1) // 3 + 1
            
            while True:
                quarter_start_month = (current_quarter - 1) * 3 + 1
                quarter_start = date(current_year, quarter_start_month, 1)
                
                if quarter_start > to_date:
                    break
                
                quarter_end_month = quarter_start_month + 2
                if quarter_end_month == 12:
                    quarter_end = date(current_year + 1, 1, 1) - timedelta(days=1)
                else:
                    quarter_end = date(current_year, quarter_end_month + 1, 1) - timedelta(days=1)
                
                periods.append({
                    'start': quarter_start,
                    'end': quarter_end,
                    'label': f"Q{current_quarter} {current_year}",
                    'full_label': f"Q{current_quarter} {current_year}"
                })
                
                if current_quarter == 4:
                    current_quarter = 1
                    current_year += 1
                else:
                    current_quarter += 1
        
        return periods
    
    def get_row_dimension_values(self, 
                                  orders: pd.DataFrame,
                                  row_dimension: str) -> pd.DataFrame:
        """Get unique values for row dimension with display labels"""
        if orders.empty:
            return pd.DataFrame(columns=['id', 'display_label'])
        
        if row_dimension == 'product':
            products = orders.groupby('product_id').first().reset_index()
            products['display_label'] = products.apply(
                lambda r: f"{r['pt_code'] or ''} | {r['product_name']} | {r['package_size'] or ''} ({r['brand_name'] or ''})",
                axis=1
            )
            return products[['product_id', 'display_label']].rename(columns={'product_id': 'id'})
        
        elif row_dimension == 'bom_type':
            types = orders['bom_type'].dropna().unique()
            return pd.DataFrame({'id': types, 'display_label': types})
        
        elif row_dimension == 'status':
            statuses = orders['status'].unique()
            status_labels = {
                'DRAFT': '📝 Draft', 'CONFIRMED': '✅ Confirmed',
                'IN_PROGRESS': '🔄 In Progress', 'COMPLETED': '✔️ Completed',
                'CANCELLED': '❌ Cancelled'
            }
            return pd.DataFrame({
                'id': statuses,
                'display_label': [status_labels.get(s, s) for s in statuses]
            })
        
        elif row_dimension == 'priority':
            priorities = orders['priority'].unique()
            priority_labels = {
                'LOW': '🔵 Low', 'NORMAL': '🟡 Normal',
                'HIGH': '🟠 High', 'URGENT': '🔴 Urgent'
            }
            return pd.DataFrame({
                'id': priorities,
                'display_label': [priority_labels.get(p, p) for p in priorities]
            })
        
        elif row_dimension == 'source_warehouse':
            warehouses = orders.groupby('warehouse_id').first().reset_index()
            return pd.DataFrame({
                'id': warehouses['warehouse_id'],
                'display_label': warehouses['warehouse_name']
            })
        
        elif row_dimension == 'target_warehouse':
            warehouses = orders.groupby('target_warehouse_id').first().reset_index()
            return pd.DataFrame({
                'id': warehouses['target_warehouse_id'],
                'display_label': warehouses['target_warehouse_name']
            })
        
        elif row_dimension == 'brand':
            brands = orders['brand_name'].dropna().unique()
            return pd.DataFrame({'id': brands, 'display_label': brands})
        
        return pd.DataFrame(columns=['id', 'display_label'])
    
    def get_dimension_column(self, row_dimension: str) -> str:
        """Map row dimension to DataFrame column name"""
        mapping = {
            'product': 'product_id', 'bom_type': 'bom_type',
            'status': 'status', 'priority': 'priority',
            'source_warehouse': 'warehouse_id',
            'target_warehouse': 'target_warehouse_id',
            'brand': 'brand_name'
        }
        return mapping.get(row_dimension, 'product_id')
    
    def build_pivot_table(self,
                          orders: pd.DataFrame,
                          periods: List[Dict],
                          row_dimension: str,
                          metric: str,
                          date_type: str = 'scheduled') -> Tuple[pd.DataFrame, Dict]:
        """Build pivot table from orders data"""
        if orders.empty:
            return pd.DataFrame(), {}
        
        row_values = self.get_row_dimension_values(orders, row_dimension)
        dim_column = self.get_dimension_column(row_dimension)
        date_column = 'scheduled_date' if date_type == 'scheduled' else 'order_date'
        
        pivot_data = []
        cell_data_map = {}
        
        for row_idx, row in row_values.iterrows():
            row_id = row['id']
            row_label = row['display_label']
            
            row_data = {'Row': row_label, '_row_id': row_id}
            row_orders = orders[orders[dim_column] == row_id]
            row_total = 0
            
            for col_idx, period in enumerate(periods):
                period_start = pd.Timestamp(period['start'])
                period_end = pd.Timestamp(period['end']) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                
                period_orders = row_orders[
                    (row_orders[date_column] >= period_start) & 
                    (row_orders[date_column] <= period_end)
                ]
                
                if metric == 'order_count':
                    value = len(period_orders)
                elif metric == 'planned_qty':
                    value = period_orders['planned_qty'].sum()
                elif metric == 'produced_qty':
                    value = period_orders['produced_qty'].sum()
                elif metric == 'pending_qty':
                    value = period_orders['pending_qty'].sum()
                else:
                    value = 0
                
                row_data[period['label']] = value
                row_total += value
                
                if not period_orders.empty:
                    cell_key = f"{row_idx}_{col_idx}"
                    cell_data_map[cell_key] = period_orders['id'].tolist()
            
            row_data['Total'] = row_total
            pivot_data.append(row_data)
        
        pivot_df = pd.DataFrame(pivot_data)
        
        if not pivot_df.empty:
            totals_row = {'Row': '**TOTAL**', '_row_id': None}
            for period in periods:
                totals_row[period['label']] = pivot_df[period['label']].sum()
            totals_row['Total'] = pivot_df['Total'].sum()
            
            pivot_df = pd.concat([pivot_df, pd.DataFrame([totals_row])], ignore_index=True)
        
        return pivot_df, cell_data_map
    
    # ==================== UI Rendering with Fragments ====================
    
    def render_config_panel(self) -> bool:
        """Render pivot configuration panel using st.form"""
        config_applied = False
        
        with st.expander("⚙️ Pivot Configuration", expanded=True):
            with st.form(key="pivot_config_form", clear_on_submit=False):
                st.markdown("##### 📅 Time Settings")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    time_group = st.selectbox(
                        "Time Grouping",
                        options=list(self.config.TIME_GROUPS.keys()),
                        format_func=lambda x: self.config.TIME_GROUPS[x],
                        index=list(self.config.TIME_GROUPS.keys()).index(
                            st.session_state.pivot_time_group
                        ),
                        key="form_pivot_time_group"
                    )
                
                with col2:
                    date_type = st.selectbox(
                        "Date Field",
                        options=['scheduled', 'order'],
                        format_func=lambda x: 'Scheduled Date' if x == 'scheduled' else 'Order Date',
                        index=0 if st.session_state.pivot_date_type == 'scheduled' else 1,
                        key="form_pivot_date_type"
                    )
                
                with col3:
                    from_date = st.date_input(
                        "From Date",
                        value=st.session_state.pivot_from_date,
                        key="form_pivot_from_date"
                    )
                
                with col4:
                    to_date = st.date_input(
                        "To Date",
                        value=st.session_state.pivot_to_date,
                        key="form_pivot_to_date"
                    )
                
                st.markdown("---")
                st.markdown("##### 📊 Pivot Settings")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    row_dimension = st.selectbox(
                        "Row Dimension",
                        options=list(self.config.ROW_DIMENSIONS.keys()),
                        format_func=lambda x: self.config.ROW_DIMENSIONS[x],
                        index=list(self.config.ROW_DIMENSIONS.keys()).index(
                            st.session_state.pivot_row_dimension
                        ),
                        key="form_pivot_row_dim"
                    )
                
                with col2:
                    metric = st.selectbox(
                        "Value Metric",
                        options=list(self.config.VALUE_METRICS.keys()),
                        format_func=lambda x: self.config.VALUE_METRICS[x],
                        index=list(self.config.VALUE_METRICS.keys()).index(
                            st.session_state.pivot_metric
                        ),
                        key="form_pivot_metric"
                    )
                
                with col3:
                    status_options = ['DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
                    status_filter = st.multiselect(
                        "Status Filter",
                        options=status_options,
                        default=st.session_state.pivot_status_filter,
                        key="form_pivot_status"
                    )
                
                st.markdown("---")
                col1, col2, col3 = st.columns([1, 1, 2])
                
                with col1:
                    apply_btn = st.form_submit_button(
                        "🔄 Apply",
                        type="primary",
                        use_container_width=True
                    )
                
                with col2:
                    reset_btn = st.form_submit_button(
                        "↩️ Reset",
                        use_container_width=True
                    )
                
                if apply_btn:
                    st.session_state.pivot_time_group = time_group
                    st.session_state.pivot_row_dimension = row_dimension
                    st.session_state.pivot_metric = metric
                    st.session_state.pivot_date_type = date_type
                    st.session_state.pivot_from_date = from_date
                    st.session_state.pivot_to_date = to_date
                    st.session_state.pivot_status_filter = status_filter if status_filter else None
                    st.session_state.pivot_data_loaded = False
                    config_applied = True
                
                if reset_btn:
                    st.session_state.pivot_time_group = self.config.DEFAULT_TIME_GROUP
                    st.session_state.pivot_row_dimension = self.config.DEFAULT_ROW_DIMENSION
                    st.session_state.pivot_metric = self.config.DEFAULT_METRIC
                    st.session_state.pivot_date_type = 'scheduled'
                    st.session_state.pivot_status_filter = self.config.DEFAULT_STATUSES.copy()
                    
                    from_date, to_date = self._get_default_date_range(self.config.DEFAULT_TIME_GROUP)
                    st.session_state.pivot_from_date = from_date
                    st.session_state.pivot_to_date = to_date
                    st.session_state.pivot_data_loaded = False
                    config_applied = True
        
        return config_applied
    
    @st.fragment
    def _fragment_pivot_table(self):
        """Fragment: Pivot table rendering - isolated rerun"""
        config = {
            'time_group': st.session_state.pivot_time_group,
            'row_dimension': st.session_state.pivot_row_dimension,
            'metric': st.session_state.pivot_metric,
            'from_date': st.session_state.pivot_from_date,
            'to_date': st.session_state.pivot_to_date,
            'date_type': st.session_state.pivot_date_type,
            'status_filter': st.session_state.pivot_status_filter
        }
        
        if not st.session_state.pivot_data_loaded or st.session_state.pivot_applied_config != config:
            with st.spinner("Loading pivot data..."):
                orders = self.get_pivot_data(
                    from_date=config['from_date'],
                    to_date=config['to_date'],
                    status_filter=config['status_filter'],
                    date_type=config['date_type']
                )
                
                if orders.empty:
                    st.warning("📊 No orders found for the selected period and filters.")
                    st.session_state.pivot_df = pd.DataFrame()
                    st.session_state.pivot_cell_data_map = {}
                    st.session_state.pivot_data_loaded = True
                    st.session_state.pivot_applied_config = config.copy()
                    return
                
                periods = self.generate_time_periods(
                    config['from_date'],
                    config['to_date'],
                    config['time_group']
                )
                
                pivot_df, cell_data_map = self.build_pivot_table(
                    orders=orders,
                    periods=periods,
                    row_dimension=config['row_dimension'],
                    metric=config['metric'],
                    date_type=config['date_type']
                )
                
                st.session_state.pivot_df = pivot_df
                st.session_state.pivot_cell_data_map = cell_data_map
                st.session_state.pivot_periods = periods
                st.session_state.pivot_data_loaded = True
                st.session_state.pivot_applied_config = config.copy()
        
        pivot_df = st.session_state.pivot_df
        
        if pivot_df is None or pivot_df.empty:
            st.warning("📊 No data to display. Try adjusting your filters.")
            return
        
        self._render_pivot_table_display(pivot_df, config)
    
    def _render_pivot_table_display(self, pivot_df: pd.DataFrame, config: Dict[str, Any]):
        """Render the pivot table with formatting"""
        display_df = pivot_df.drop(columns=['_row_id'], errors='ignore').copy()
        
        metric = config['metric']
        for col in display_df.columns:
            if col != 'Row':
                display_df[col] = display_df[col].apply(
                    lambda x: format_number(x, 0) if pd.notna(x) and x != 0 else '-'
                )
        
        metric_label = self.config.VALUE_METRICS.get(metric, metric)
        row_dim_label = self.config.ROW_DIMENSIONS.get(config['row_dimension'], config['row_dimension'])
        time_label = self.config.TIME_GROUPS.get(config['time_group'], config['time_group'])
        
        st.markdown(f"""
        ### 📊 {metric_label} by {row_dim_label} ({time_label})
        📅 **Period:** {format_date(config['from_date'])} - {format_date(config['to_date'])}
        """)
        
        num_cols = len(display_df.columns) - 1
        if num_cols > 15:
            st.warning(f"⚠️ Table has {num_cols} time columns. Consider using a larger time grouping.")
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=min(500, (len(display_df) + 1) * 35 + 50)
        )
        
        total_value = pivot_df[pivot_df['Row'] != '**TOTAL**']['Total'].sum()
        num_rows = len(pivot_df) - 1
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(f"📊 Total {metric_label}", format_number(total_value, 0))
        with col2:
            st.metric(f"📋 {row_dim_label}s", num_rows)
        with col3:
            if num_rows > 0:
                avg = total_value / num_rows
                st.metric(f"📈 Avg per {row_dim_label}", format_number(avg, 0))
        
        st.markdown("---")
        col1, col2 = st.columns([1, 3])
        
        with col1:
            if st.button("📥 Export Excel", key="btn_pivot_export"):
                self._export_to_excel(pivot_df, config)
    
    @st.fragment
    def _fragment_drill_down(self):
        """Fragment: Drill-down section - isolated rerun"""
        pivot_df = st.session_state.get('pivot_df')
        cell_data_map = st.session_state.get('pivot_cell_data_map', {})
        
        if pivot_df is None or pivot_df.empty or not cell_data_map:
            return
        
        st.markdown("---")
        st.markdown("### 🔍 Drill-Down")
        st.caption("Select a row and period to see detailed orders")
        
        rows = pivot_df[pivot_df['Row'] != '**TOTAL**']['Row'].tolist()
        periods = [c for c in pivot_df.columns if c not in ['Row', '_row_id', 'Total']]
        
        col1, col2 = st.columns(2)
        
        with col1:
            selected_row = st.selectbox(
                "Select Row",
                options=[''] + rows,
                key="drill_down_row",
                format_func=lambda x: "-- Select --" if x == '' else x
            )
        
        with col2:
            selected_period = st.selectbox(
                "Select Period",
                options=[''] + periods,
                key="drill_down_period",
                format_func=lambda x: "-- Select --" if x == '' else x
            )
        
        if selected_row and selected_period and selected_row != '' and selected_period != '':
            row_idx = rows.index(selected_row)
            col_idx = periods.index(selected_period)
            cell_key = f"{row_idx}_{col_idx}"
            
            if cell_key in cell_data_map:
                order_ids = cell_data_map[cell_key]
                
                st.markdown(f"**📦 {len(order_ids)} order(s) found:**")
                
                orders_df = self.queries.get_orders(page=1, page_size=10000)
                
                if orders_df is not None and not orders_df.empty:
                    cell_orders = orders_df[orders_df['id'].isin(order_ids)]
                    
                    if not cell_orders.empty:
                        display_cols = ['order_no', 'product_name', 'planned_qty', 'produced_qty', 'status', 'scheduled_date']
                        display_df = cell_orders[display_cols].copy()
                        display_df.columns = ['Order No', 'Product', 'Planned', 'Produced', 'Status', 'Scheduled']
                        display_df['Scheduled'] = display_df['Scheduled'].apply(
                            lambda x: format_date(x) if pd.notna(x) else ''
                        )
                        
                        st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ No orders in this cell")
    
    def _export_to_excel(self, pivot_df: pd.DataFrame, config: Dict):
        """Export pivot table to Excel"""
        from .common import export_to_excel
        
        export_df = pivot_df.drop(columns=['_row_id'], errors='ignore').copy()
        
        timestamp = get_vietnam_now().strftime('%Y%m%d_%H%M%S')
        metric_label = self.config.VALUE_METRICS.get(config['metric'], config['metric'])
        filename = f"Pivot_{metric_label}_{timestamp}.xlsx"
        
        try:
            excel_data = export_to_excel(export_df)
            
            st.download_button(
                label="💾 Download Excel",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="pivot_download_excel"
            )
            st.success("✅ Excel file ready!")
        except Exception as e:
            st.error(f"❌ Export failed: {str(e)}")
            logger.error(f"Pivot export failed: {e}", exc_info=True)
    
    def render(self):
        """Main render method for Pivot View with fragment optimization"""
        st.markdown("## 📊 Pivot Analysis")
        
        self._init_session_state()
        
        config_applied = self.render_config_panel()
        
        if config_applied:
            st.session_state.pivot_data_loaded = False
        
        self._fragment_pivot_table()
        
        self._fragment_drill_down()


# ==================== Convenience Functions ====================

def render_pivot_view():
    """Convenience function to render pivot view"""
    pivot_view = OrderPivotView()
    pivot_view.render()