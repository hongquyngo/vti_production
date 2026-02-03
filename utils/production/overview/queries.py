# utils/production/overview/queries.py
"""
Database queries for Production Overview domain
Complex aggregation queries joining MO, materials, receipts

Version: 5.0.0
Changes:
- v5.0.0: MAJOR CHANGE - Show actual issued materials (1 row = 1 issue detail)
          - get_materials_for_export() now returns 1 row per material_issue_detail
          - Shows PRIMARY and ALTERNATIVE materials separately
          - Actual material PT code, name, UOM (not just primary)
          - Material Type column (PRIMARY/ALTERNATIVE)
          - Full traceability with primary material reference
- v4.0.0: Simplified for single Production Data table
          - get_materials_for_export() is the main query (1 row = 1 material line)
          - get_production_overview() used only for dashboard metrics/analytics
- v3.0.0: CRITICAL FIX - Fixed double-counting returns bug
          - Now calculates GROSS issued from material_issue_details (actual / conversion_ratio)
          - Calculates RETURNED equivalent from material_return_details (actual / conversion_ratio)
          - NET = GROSS - RETURNED (correctly calculated)
          - Previous: issued_qty was already NET but was subtracted by returned again (WRONG)
- v2.0.0: Added lifecycle stage queries, analytics data methods
- v1.0.0: Initial version

IMPORTANT DATA LOGIC (v5.0.0):
- Each row represents ONE ACTUAL MATERIAL ISSUE (from material_issue_details)
- For PRIMARY materials: is_alternative = 0, shows primary material info
- For ALTERNATIVE materials: is_alternative = 1, shows alternative material info AND primary reference
- Quantities are ACTUAL physical units issued (not converted/equivalent)
- Returns are tracked per issue_detail_id
"""

import logging
from datetime import date
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, DatabaseError

from utils.db import get_db_engine
from .common import (
    calculate_percentage, calculate_health_status, calculate_days_variance,
    HealthStatus, get_vietnam_today
)

logger = logging.getLogger(__name__)


class OverviewQueries:
    """Database queries for Production Overview"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self._connection_error = None
    
    def check_connection(self) -> Tuple[bool, Optional[str]]:
        """Check database connection"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._connection_error = None
            return True, None
        except OperationalError as e:
            error_msg = "Cannot connect to database. Please check your network/VPN connection."
            self._connection_error = error_msg
            logger.error(f"Database connection error: {e}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Database error: {str(e)}"
            self._connection_error = error_msg
            logger.error(f"Database error: {e}")
            return False, error_msg
    
    def get_last_error(self) -> Optional[str]:
        """Get last connection error message"""
        return self._connection_error
    
    # ==================== Date Filter Helper ====================
    
    def _build_date_filter_clause(self, date_type: Optional[str],
                                   from_date: Optional[date],
                                   to_date: Optional[date],
                                   params: list) -> str:
        """
        Build WHERE clause fragment for date filtering based on date type.
        Mutates params list in-place.
        
        Args:
            date_type: One of 'order_date', 'scheduled_date', 'completion_date', 'receipt_date'
            from_date: Start date filter
            to_date: End date filter
            params: Parameter list to append values to
            
        Returns:
            SQL WHERE clause fragment (starts with ' AND ...')
        """
        if not from_date and not to_date:
            return ""
        
        date_type = date_type or 'order_date'
        
        # MO-level date columns
        if date_type in ('order_date', 'scheduled_date', 'completion_date'):
            col_map = {
                'order_date': 'mo.order_date',
                'scheduled_date': 'mo.scheduled_date',
                'completion_date': 'mo.completion_date',
            }
            col = col_map[date_type]
            clause = ""
            if from_date:
                clause += f" AND DATE({col}) >= %s"
                params.append(from_date)
            if to_date:
                clause += f" AND DATE({col}) <= %s"
                params.append(to_date)
            return clause
        
        # Receipt date: subquery on production_receipts
        elif date_type == 'receipt_date':
            sub_parts = []
            if from_date:
                sub_parts.append("DATE(pr_f.receipt_date) >= %s")
                params.append(from_date)
            if to_date:
                sub_parts.append("DATE(pr_f.receipt_date) <= %s")
                params.append(to_date)
            sub_where = " AND ".join(sub_parts)
            return (f" AND mo.id IN (SELECT DISTINCT pr_f.manufacturing_order_id"
                    f" FROM production_receipts pr_f WHERE {sub_where})")
        
        return ""
    
    # ==================== Main Overview Query ====================
    
    def get_production_overview(self,
                                from_date: Optional[date] = None,
                                to_date: Optional[date] = None,
                                status: Optional[str] = None,
                                health_filter: Optional[str] = None,
                                search: Optional[str] = None,
                                page: int = 1,
                                page_size: int = 15,
                                date_type: Optional[str] = None) -> Optional[pd.DataFrame]:
        """
        Get production overview with aggregated data
        
        Joins: manufacturing_orders + materials summary + receipts summary
        
        Args:
            from_date: Filter orders from this date (order_date)
            to_date: Filter orders to this date (order_date)
            status: Filter by order status
            health_filter: Filter by health status (ON_TRACK, AT_RISK, DELAYED)
            search: Search in order_no, product name, pt_code
            page: Page number (1-indexed)
            page_size: Records per page
            
        Returns:
            DataFrame with overview data, None if connection error
        """
        query = """
            SELECT 
                mo.id,
                mo.order_no,
                mo.order_date,
                mo.scheduled_date,
                mo.completion_date,
                mo.status,
                mo.priority,
                mo.planned_qty,
                mo.produced_qty,
                mo.uom,
                mo.notes,
                
                -- Product info
                p.id as product_id,
                p.pt_code,
                p.name as product_name,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                
                -- BOM info
                bh.bom_type,
                bh.bom_name,
                
                -- Warehouse info
                w1.name as source_warehouse,
                w2.name as target_warehouse,
                
                -- Material aggregation
                -- CRITICAL: issued_qty is NET EQUIVALENT (returns already subtracted)
                COALESCE(mat.total_required, 0) as total_material_required,
                COALESCE(mat.total_net_issued, 0) as total_material_net_issued,
                COALESCE(mat.material_count, 0) as material_count,
                COALESCE(mat.materials_fully_issued, 0) as materials_fully_issued,
                
                -- Issue details (ACTUAL quantities for reference)
                COALESCE(iss.total_issued_actual, 0) as total_issued_actual,
                COALESCE(iss.alternative_issue_count, 0) as alternative_issue_count,
                
                -- Receipt aggregation
                COALESCE(rcpt.total_receipts, 0) as total_receipts,
                COALESCE(rcpt.total_receipt_qty, 0) as total_receipt_qty,
                COALESCE(rcpt.passed_qty, 0) as passed_qty,
                COALESCE(rcpt.failed_qty, 0) as failed_qty,
                COALESCE(rcpt.pending_qty, 0) as pending_qty,
                
                -- Return aggregation (ACTUAL quantities)
                COALESCE(ret.total_returned_actual, 0) as total_returned_actual,
                COALESCE(ret.return_line_count, 0) as return_line_count,
                
                -- Calculated fields
                CASE 
                    WHEN mo.planned_qty > 0 
                    THEN ROUND((mo.produced_qty / mo.planned_qty) * 100, 1)
                    ELSE 0 
                END as progress_percentage,
                
                -- Material percentage based on NET issued (equivalent) vs required
                -- This is the ACCURATE percentage for fulfillment tracking
                CASE 
                    WHEN COALESCE(mat.total_required, 0) > 0 
                    THEN ROUND((COALESCE(mat.total_net_issued, 0) / mat.total_required) * 100, 1)
                    ELSE 0 
                END as material_percentage,
                
                CASE 
                    WHEN COALESCE(rcpt.total_receipt_qty, 0) > 0 
                    THEN ROUND((COALESCE(rcpt.passed_qty, 0) / rcpt.total_receipt_qty) * 100, 1)
                    ELSE NULL 
                END as quality_percentage,
                
                DATEDIFF(CURDATE(), mo.scheduled_date) as schedule_variance_days
                
            FROM manufacturing_orders mo
            
            -- Product & BOM joins
            JOIN products p ON mo.product_id = p.id
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            JOIN brands br ON p.brand_id = br.id
            JOIN warehouses w1 ON mo.warehouse_id = w1.id
            JOIN warehouses w2 ON mo.target_warehouse_id = w2.id
            
            -- Material aggregation subquery
            -- CRITICAL: issued_qty in manufacturing_order_materials is already NET EQUIVALENT
            -- (already adjusted for returns in equivalent units)
            -- We calculate GROSS by: NET + RETURNED_equivalent
            -- But since we don't have conversion_ratio stored, we use a simplified approach:
            -- - NET = issued_qty (accurate, from table)
            -- - RETURNED_actual = from return_details (for display)
            -- - For most cases (no alternatives), GROSS ≈ NET + RETURNED
            LEFT JOIN (
                SELECT 
                    mom.manufacturing_order_id,
                    COUNT(DISTINCT mom.id) as material_count,
                    SUM(mom.required_qty) as total_required,
                    -- NET issued (equivalent) - this is the accurate value
                    SUM(mom.issued_qty) as total_net_issued,
                    SUM(CASE WHEN mom.issued_qty >= mom.required_qty THEN 1 ELSE 0 END) as materials_fully_issued
                FROM manufacturing_order_materials mom
                GROUP BY mom.manufacturing_order_id
            ) mat ON mat.manufacturing_order_id = mo.id
            
            -- Issue details aggregation (ACTUAL quantities for reference)
            LEFT JOIN (
                SELECT 
                    mom.manufacturing_order_id,
                    SUM(mid.quantity) as total_issued_actual,
                    COUNT(DISTINCT CASE WHEN mid.is_alternative = 1 THEN mid.id END) as alternative_issue_count
                FROM material_issue_details mid
                JOIN material_issues mi ON mid.material_issue_id = mi.id
                JOIN manufacturing_order_materials mom ON mid.manufacturing_order_material_id = mom.id
                WHERE mi.status = 'CONFIRMED'
                GROUP BY mom.manufacturing_order_id
            ) iss ON iss.manufacturing_order_id = mo.id
            
            -- Receipt aggregation subquery
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    COUNT(*) as total_receipts,
                    SUM(quantity) as total_receipt_qty,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty,
                    SUM(CASE WHEN quality_status = 'FAILED' THEN quantity ELSE 0 END) as failed_qty,
                    SUM(CASE WHEN quality_status = 'PENDING' THEN quantity ELSE 0 END) as pending_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) rcpt ON rcpt.manufacturing_order_id = mo.id
            
            -- Return aggregation subquery (ACTUAL quantities)
            -- NOTE: Without conversion_ratio stored, we show ACTUAL returned for transparency
            -- The NET (issued_qty) is accurate because returns are already subtracted in equivalent units
            LEFT JOIN (
                SELECT 
                    mom.manufacturing_order_id,
                    -- RETURNED actual (physical units returned)
                    SUM(mrd.quantity) as total_returned_actual,
                    COUNT(DISTINCT mrd.id) as return_line_count
                FROM material_return_details mrd
                JOIN material_issue_details mid ON mrd.original_issue_detail_id = mid.id
                JOIN manufacturing_order_materials mom ON mid.manufacturing_order_material_id = mom.id
                JOIN material_returns mr ON mrd.material_return_id = mr.id
                WHERE mr.status = 'CONFIRMED'
                GROUP BY mom.manufacturing_order_id
            ) ret ON ret.manufacturing_order_id = mo.id
            
            WHERE mo.delete_flag = 0
        """
        
        params = []
        query += self._build_date_filter_clause(date_type, from_date, to_date, params)
        
        if status:
            query += " AND mo.status = %s"
            params.append(status)
        
        if search:
            query += """
                AND (
                    mo.order_no LIKE %s 
                    OR p.name LIKE %s 
                    OR p.pt_code LIKE %s
                    OR p.legacy_pt_code LIKE %s
                )
            """
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 4)
        
        query += " ORDER BY mo.order_date DESC, mo.created_date DESC"
        
        # Pagination
        offset = (page - 1) * page_size
        query += " LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        
        try:
            df = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            self._connection_error = None
            
            # Calculate health status for each row
            if not df.empty:
                df['health_status'] = df.apply(
                    lambda row: calculate_health_status(
                        material_percentage=row['material_percentage'] or 0,
                        schedule_variance_days=row['schedule_variance_days'] or 0,
                        quality_percentage=row['quality_percentage'],
                        status=row['status']
                    ).value,
                    axis=1
                )
                
                # Apply health filter if specified
                if health_filter:
                    df = df[df['health_status'] == health_filter]
            
            return df
            
        except (OperationalError, DatabaseError) as e:
            self._connection_error = "Cannot connect to database. Please check your network/VPN connection."
            logger.error(f"Database connection error: {e}")
            return None
        except Exception as e:
            self._connection_error = f"Database error: {str(e)}"
            logger.error(f"Error getting production overview: {e}")
            return None
    
    def get_overview_count(self,
                          from_date: Optional[date] = None,
                          to_date: Optional[date] = None,
                          status: Optional[str] = None,
                          search: Optional[str] = None,
                          date_type: Optional[str] = None) -> int:
        """Get total count of orders matching filters"""
        query = """
            SELECT COUNT(*) as total
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            WHERE mo.delete_flag = 0
        """
        
        params = []
        query += self._build_date_filter_clause(date_type, from_date, to_date, params)
        
        if status:
            query += " AND mo.status = %s"
            params.append(status)
        
        if search:
            query += """
                AND (
                    mo.order_no LIKE %s 
                    OR p.name LIKE %s 
                    OR p.pt_code LIKE %s
                    OR p.legacy_pt_code LIKE %s
                )
            """
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 4)
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return int(result.iloc[0]['total']) if not result.empty else 0
        except Exception as e:
            logger.error(f"Error getting overview count: {e}")
            return 0
    
    # ==================== Dashboard Metrics ====================
    
    def get_overview_metrics(self,
                            from_date: Optional[date] = None,
                            to_date: Optional[date] = None,
                            date_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get aggregated metrics for dashboard
        
        Returns:
            Dictionary with KPI metrics
        """
        query = """
            SELECT 
                COUNT(*) as total_orders,
                
                -- Status counts
                SUM(CASE WHEN mo.status = 'DRAFT' THEN 1 ELSE 0 END) as draft_count,
                SUM(CASE WHEN mo.status = 'CONFIRMED' THEN 1 ELSE 0 END) as confirmed_count,
                SUM(CASE WHEN mo.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress_count,
                SUM(CASE WHEN mo.status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_count,
                SUM(CASE WHEN mo.status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_count,
                
                -- Quantity totals
                SUM(mo.planned_qty) as total_planned_qty,
                SUM(mo.produced_qty) as total_produced_qty,
                
                -- Schedule analysis (for IN_PROGRESS orders)
                SUM(CASE 
                    WHEN mo.status = 'IN_PROGRESS' AND DATEDIFF(CURDATE(), mo.scheduled_date) <= 0 
                    THEN 1 ELSE 0 
                END) as on_schedule_count,
                SUM(CASE 
                    WHEN mo.status = 'IN_PROGRESS' AND DATEDIFF(CURDATE(), mo.scheduled_date) BETWEEN 1 AND 2 
                    THEN 1 ELSE 0 
                END) as at_risk_count,
                SUM(CASE 
                    WHEN mo.status = 'IN_PROGRESS' AND DATEDIFF(CURDATE(), mo.scheduled_date) > 2 
                    THEN 1 ELSE 0 
                END) as delayed_count
                
            FROM manufacturing_orders mo
            WHERE mo.delete_flag = 0
        """
        
        params = []
        query += self._build_date_filter_clause(date_type, from_date, to_date, params)
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            
            if result.empty:
                return self._empty_metrics()
            
            row = result.iloc[0]
            total = int(row['total_orders'] or 0)
            completed = int(row['completed_count'] or 0)
            in_progress = int(row['in_progress_count'] or 0)
            
            total_planned = float(row['total_planned_qty'] or 0)
            total_produced = float(row['total_produced_qty'] or 0)
            
            # Calculate yield rate
            yield_rate = calculate_percentage(total_produced, total_planned)
            
            # Calculate completion rate
            completion_rate = calculate_percentage(completed, total) if total > 0 else 0
            
            return {
                'total_orders': total,
                'draft_count': int(row['draft_count'] or 0),
                'confirmed_count': int(row['confirmed_count'] or 0),
                'in_progress_count': in_progress,
                'completed_count': completed,
                'cancelled_count': int(row['cancelled_count'] or 0),
                'total_planned_qty': total_planned,
                'total_produced_qty': total_produced,
                'yield_rate': yield_rate,
                'completion_rate': completion_rate,
                'on_schedule_count': int(row['on_schedule_count'] or 0),
                'at_risk_count': int(row['at_risk_count'] or 0),
                'delayed_count': int(row['delayed_count'] or 0),
            }
            
        except Exception as e:
            logger.error(f"Error getting overview metrics: {e}")
            return self._empty_metrics()
    
    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics structure"""
        return {
            'total_orders': 0,
            'draft_count': 0,
            'confirmed_count': 0,
            'in_progress_count': 0,
            'completed_count': 0,
            'cancelled_count': 0,
            'total_planned_qty': 0,
            'total_produced_qty': 0,
            'yield_rate': 0,
            'completion_rate': 0,
            'on_schedule_count': 0,
            'at_risk_count': 0,
            'delayed_count': 0,
        }
    
    # ==================== Detail Queries ====================
    
    def get_order_materials_detail(self, order_id: int) -> pd.DataFrame:
        """
        Get detailed materials for an order including issue/return breakdown
        
        SIMPLIFIED APPROACH (no conversion_ratio stored):
        - NET = issued_qty from table (accurate, in equivalent units)
        - RETURNED_actual = from return_details (physical units)
        - Issue percentage = NET / Required
        
        Args:
            order_id: Manufacturing order ID
            
        Returns:
            DataFrame with material details
        """
        query = """
            SELECT 
                mom.id as material_id,
                p.pt_code,
                p.name as material_name,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                mom.required_qty,
                mom.uom,
                mom.status,
                
                -- NET issued (equivalent) - accurate value from table
                mom.issued_qty as net_issued,
                
                -- ISSUED actual (physical units from issue_details)
                COALESCE(iss.issued_actual, 0) as issued_actual,
                COALESCE(iss.has_alternatives, 0) as has_alternatives,
                
                -- RETURNED actual (physical units from return_details)
                COALESCE(ret.returned_actual, 0) as returned_actual,
                
                -- Issue percentage based on NET issued (equivalent) vs required
                CASE 
                    WHEN mom.required_qty > 0 
                    THEN ROUND((mom.issued_qty / mom.required_qty) * 100, 1)
                    ELSE 0 
                END as issue_percentage
                
            FROM manufacturing_order_materials mom
            JOIN products p ON mom.material_id = p.id
            JOIN brands br ON p.brand_id = br.id
            
            -- ISSUED actual from issue_details
            LEFT JOIN (
                SELECT 
                    mid.manufacturing_order_material_id,
                    SUM(mid.quantity) as issued_actual,
                    MAX(CASE WHEN mid.is_alternative = 1 THEN 1 ELSE 0 END) as has_alternatives
                FROM material_issue_details mid
                JOIN material_issues mi ON mid.material_issue_id = mi.id
                WHERE mi.status = 'CONFIRMED'
                GROUP BY mid.manufacturing_order_material_id
            ) iss ON iss.manufacturing_order_material_id = mom.id
            
            -- RETURNED actual from return_details
            LEFT JOIN (
                SELECT 
                    mid.manufacturing_order_material_id,
                    SUM(mrd.quantity) as returned_actual
                FROM material_return_details mrd
                JOIN material_issue_details mid ON mrd.original_issue_detail_id = mid.id
                JOIN material_returns mr ON mrd.material_return_id = mr.id
                WHERE mr.status = 'CONFIRMED'
                GROUP BY mid.manufacturing_order_material_id
            ) ret ON ret.manufacturing_order_material_id = mom.id
            
            WHERE mom.manufacturing_order_id = %s
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting order materials detail: {e}")
            return pd.DataFrame()
    
    def get_order_receipts_detail(self, order_id: int) -> pd.DataFrame:
        """
        Get detailed receipts for an order
        
        Args:
            order_id: Manufacturing order ID
            
        Returns:
            DataFrame with receipt details
        """
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                pr.receipt_date,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                pr.quality_status,
                pr.defect_type,
                pr.notes,
                w.name as warehouse_name,
                CONCAT(e.first_name, ' ', e.last_name) as created_by_name
            FROM production_receipts pr
            JOIN warehouses w ON pr.warehouse_id = w.id
            LEFT JOIN users u ON pr.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE pr.manufacturing_order_id = %s
            ORDER BY pr.receipt_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting order receipts detail: {e}")
            return pd.DataFrame()
    
    def get_order_timeline(self, order_id: int) -> pd.DataFrame:
        """
        Get timeline events for an order (issues, returns, receipts)
        
        Args:
            order_id: Manufacturing order ID
            
        Returns:
            DataFrame with timeline events
        """
        query = """
            -- Material Issues
            SELECT 
                'ISSUE' as event_type,
                mi.issue_no as document_no,
                mi.issue_date as event_date,
                CONCAT('Issued ', COUNT(mid.id), ' materials') as description,
                mi.status
            FROM material_issues mi
            JOIN material_issue_details mid ON mid.material_issue_id = mi.id
            WHERE mi.manufacturing_order_id = %s AND mi.status = 'CONFIRMED'
            GROUP BY mi.id, mi.issue_no, mi.issue_date, mi.status
            
            UNION ALL
            
            -- Material Returns
            SELECT 
                'RETURN' as event_type,
                mr.return_no as document_no,
                mr.return_date as event_date,
                CONCAT('Returned ', COUNT(mrd.id), ' items') as description,
                mr.status
            FROM material_returns mr
            JOIN material_return_details mrd ON mrd.material_return_id = mr.id
            WHERE mr.manufacturing_order_id = %s AND mr.status = 'CONFIRMED'
            GROUP BY mr.id, mr.return_no, mr.return_date, mr.status
            
            UNION ALL
            
            -- Production Receipts
            SELECT 
                'RECEIPT' as event_type,
                pr.receipt_no as document_no,
                pr.receipt_date as event_date,
                CONCAT('Produced ', pr.quantity, ' ', pr.uom, ' - ', pr.quality_status) as description,
                pr.quality_status as status
            FROM production_receipts pr
            WHERE pr.manufacturing_order_id = %s
            
            ORDER BY event_date ASC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id, order_id, order_id))
        except Exception as e:
            logger.error(f"Error getting order timeline: {e}")
            return pd.DataFrame()
    
    # ==================== Pivot Query ====================
    
    def get_pivot_data(self,
                       date_type: str = 'order_date',
                       from_date: Optional[date] = None,
                       to_date: Optional[date] = None,
                       status: Optional[str] = None,
                       period: str = 'month',
                       dimension: str = 'output_product') -> Optional[pd.DataFrame]:
        """
        Get aggregated data for pivot table.
        
        Builds different queries for MO-level vs receipt-level date types:
        - MO-level: aggregates from manufacturing_orders (planned/produced qty)
        - Receipt-level: aggregates from production_receipts (receipt/QC qty)
        
        Args:
            date_type: Date column to group by ('order_date', 'scheduled_date', 'completion_date', 'receipt_date')
            from_date: Start date
            to_date: End date
            status: Filter by MO status
            period: Time grouping ('day', 'week', 'month')
            dimension: Row grouping dimension
            
        Returns:
            DataFrame with columns: period_key, dimension_key, + measure columns
        """
        is_receipt = (date_type == 'receipt_date')
        
        # --- Date column for period grouping ---
        date_col_map = {
            'order_date': 'mo.order_date',
            'scheduled_date': 'mo.scheduled_date',
            'completion_date': 'mo.completion_date',
            'receipt_date': 'pr.receipt_date',
        }
        date_col = date_col_map.get(date_type, 'mo.order_date')
        
        # --- Period expression ---
        if period == 'day':
            period_expr = f"DATE_FORMAT({date_col}, '%%Y-%%m-%%d')"
        elif period == 'week':
            period_expr = f"DATE_FORMAT({date_col} - INTERVAL WEEKDAY({date_col}) DAY, '%%Y-%%m-%%d')"
        else:  # month
            period_expr = f"DATE_FORMAT({date_col}, '%%Y-%%m')"
        
        # --- Dimension expression ---
        dim_map = {
            'mo_number': "mo.order_no",
            'output_product': "CONCAT(p.pt_code, ' | ', p.name)",
            'brand': "br.brand_name",
            'bom_type': "bh.bom_type",
            'source_warehouse': "w1.name",
            'target_warehouse': "w2.name",
            'order_status': "mo.status",
            'priority': "mo.priority",
            'entity': "COALESCE(c.english_name, 'N/A')",
        }
        if is_receipt:
            dim_map['qc_status'] = "pr.quality_status"
        dim_expr = dim_map.get(dimension, "mo.status")
        
        # --- Build query ---
        base_joins = """
            JOIN products p ON mo.product_id = p.id
            JOIN brands br ON p.brand_id = br.id
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            JOIN warehouses w1 ON mo.warehouse_id = w1.id
            JOIN warehouses w2 ON mo.target_warehouse_id = w2.id
            LEFT JOIN companies c ON mo.entity_id = c.id
        """
        
        if is_receipt:
            query = f"""
                SELECT
                    {period_expr} as period_key,
                    {dim_expr} as dimension_key,
                    COUNT(DISTINCT mo.id) as mo_count,
                    COALESCE(SUM(pr.quantity), 0) as receipt_qty,
                    COALESCE(SUM(CASE WHEN pr.quality_status = 'PASSED' THEN pr.quantity ELSE 0 END), 0) as qc_passed_qty,
                    COALESCE(SUM(CASE WHEN pr.quality_status = 'FAILED' THEN pr.quantity ELSE 0 END), 0) as qc_failed_qty,
                    COALESCE(SUM(CASE WHEN pr.quality_status = 'PENDING' THEN pr.quantity ELSE 0 END), 0) as qc_pending_qty,
                    CASE WHEN SUM(pr.quantity) > 0
                        THEN ROUND(SUM(CASE WHEN pr.quality_status = 'PASSED' THEN pr.quantity ELSE 0 END)
                                   / SUM(pr.quantity) * 100, 1)
                        ELSE 0 END as pass_rate_pct
                FROM production_receipts pr
                JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
                {base_joins}
                WHERE mo.delete_flag = 0
            """
        else:
            query = f"""
                SELECT
                    {period_expr} as period_key,
                    {dim_expr} as dimension_key,
                    COUNT(DISTINCT mo.id) as mo_count,
                    COALESCE(SUM(mo.planned_qty), 0) as planned_qty,
                    COALESCE(SUM(mo.produced_qty), 0) as produced_qty,
                    CASE WHEN SUM(mo.planned_qty) > 0
                        THEN ROUND(SUM(mo.produced_qty) / SUM(mo.planned_qty) * 100, 1)
                        ELSE 0 END as yield_pct
                FROM manufacturing_orders mo
                {base_joins}
                WHERE mo.delete_flag = 0
            """
        
        # --- Date range filter ---
        params = []
        
        if is_receipt:
            if from_date:
                query += " AND DATE(pr.receipt_date) >= %s"
                params.append(from_date)
            if to_date:
                query += " AND DATE(pr.receipt_date) <= %s"
                params.append(to_date)
        else:
            date_col_simple = {
                'order_date': 'mo.order_date',
                'scheduled_date': 'mo.scheduled_date',
                'completion_date': 'mo.completion_date',
            }.get(date_type, 'mo.order_date')
            if from_date:
                query += f" AND DATE({date_col_simple}) >= %s"
                params.append(from_date)
            if to_date:
                query += f" AND DATE({date_col_simple}) <= %s"
                params.append(to_date)
        
        # --- Status filter ---
        if status:
            query += " AND mo.status = %s"
            params.append(status)
        
        query += " GROUP BY period_key, dimension_key ORDER BY period_key, dimension_key"
        
        try:
            df = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            self._connection_error = None
            return df
        except Exception as e:
            self._connection_error = f"Pivot query error: {str(e)}"
            logger.error(f"Error getting pivot data: {e}")
            return None
    
    # ==================== Filter Options ====================
    
    def get_filter_options(self) -> Dict[str, List[str]]:
        """Get filter dropdown options"""
        return {
            'statuses': ['All', 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
            'health': ['All', 'ON_TRACK', 'AT_RISK', 'DELAYED', 'NOT_STARTED'],
        }
    
    # ==================== Export Queries ====================
    
    def get_materials_for_export(self,
                                 from_date: Optional[date] = None,
                                 to_date: Optional[date] = None,
                                 status: Optional[str] = None,
                                 search: Optional[str] = None,
                                 date_type: Optional[str] = None) -> pd.DataFrame:
        """
        Get all ACTUAL materials issued for export (1 row = 1 issue detail)
        Shows PRIMARY and ALTERNATIVE materials separately with full traceability
        
        NEW APPROACH (v5.0.0):
        - 1 row = 1 material_issue_detail (actual material issued)
        - Shows actual material PT code, name, UOM
        - Material Type: PRIMARY or ALTERNATIVE
        - For alternatives: shows original primary material
        - Actual quantities in physical units issued
        
        Args:
            from_date: Filter orders from this date
            to_date: Filter orders to this date
            status: Filter by order status
            search: Search in order_no, product name, pt_code
            
        Returns:
            DataFrame with actual issued material details (1 row per issue detail)
        """
        query = """
            SELECT 
                -- MO Header info
                mo.id as mo_id,
                mo.order_no,
                mo.order_date,
                mo.scheduled_date,
                mo.completion_date,
                mo.status as order_status,
                mo.priority,
                mo.planned_qty as mo_planned_qty,
                mo.produced_qty as mo_produced_qty,
                mo.uom as mo_uom,
                mo.notes as mo_notes,
                
                -- Output Product info
                op.pt_code as output_pt_code,
                op.legacy_pt_code as output_legacy_code,
                op.name as output_product_name,
                op.package_size as output_package_size,
                obr.brand_name as output_brand,
                bh.bom_type,
                
                -- Warehouse info
                w1.name as source_warehouse,
                w2.name as target_warehouse,
                
                -- MO aggregated metrics
                CASE 
                    WHEN mo.planned_qty > 0 
                    THEN ROUND((mo.produced_qty / mo.planned_qty) * 100, 1)
                    ELSE 0 
                END as progress_percentage,
                
                COALESCE(rcpt.total_receipts, 0) as total_receipts,
                COALESCE(rcpt.passed_qty, 0) as passed_qty,
                COALESCE(rcpt.failed_qty, 0) as failed_qty,
                COALESCE(rcpt.pending_qty, 0) as pending_qty,
                CASE 
                    WHEN COALESCE(rcpt.total_receipt_qty, 0) > 0 
                    THEN ROUND((COALESCE(rcpt.passed_qty, 0) / rcpt.total_receipt_qty) * 100, 1)
                    ELSE NULL 
                END as qc_pass_percentage,
                
                DATEDIFF(CURDATE(), mo.scheduled_date) as schedule_variance_days,
                
                -- Primary Material (Original requirement from MOM)
                prim_p.pt_code as primary_pt_code,
                prim_p.legacy_pt_code as primary_legacy_code,
                prim_p.name as primary_material_name,
                prim_p.package_size as primary_package_size,
                prim_br.brand_name as primary_brand,
                mom.required_qty as primary_required_qty,
                mom.uom as primary_uom,
                mom.status as material_status,
                
                -- Material Issue Detail info
                mid.id as issue_detail_id,
                mi.issue_no,
                mi.issue_date,
                mid.batch_no,
                mid.expired_date,
                
                -- Material Type flag
                mid.is_alternative,
                CASE 
                    WHEN mid.is_alternative = 1 THEN 'ALTERNATIVE'
                    ELSE 'PRIMARY'
                END as material_type,
                
                -- ACTUAL Material issued (could be primary or alternative)
                act_p.id as actual_material_id,
                act_p.pt_code as actual_pt_code,
                act_p.legacy_pt_code as actual_legacy_code,
                act_p.name as actual_material_name,
                act_p.package_size as actual_package_size,
                act_br.brand_name as actual_brand,
                
                -- Actual issued quantities (physical units)
                mid.quantity as issued_qty,
                mid.uom as issued_uom,
                
                -- Return info for this issue detail
                COALESCE(ret.returned_qty, 0) as returned_qty,
                ret.last_return_date,
                
                -- Net quantity (issued - returned)
                mid.quantity - COALESCE(ret.returned_qty, 0) as net_qty,
                
                -- Issue percentage (for primary materials only, based on this specific issue)
                CASE 
                    WHEN mid.is_alternative = 0 AND mom.required_qty > 0 
                    THEN ROUND((mid.quantity / mom.required_qty) * 100, 1)
                    ELSE NULL
                END as issue_percentage
                
            FROM manufacturing_orders mo
            
            -- Output Product & BOM joins
            JOIN products op ON mo.product_id = op.id
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            JOIN brands obr ON op.brand_id = obr.id
            JOIN warehouses w1 ON mo.warehouse_id = w1.id
            JOIN warehouses w2 ON mo.target_warehouse_id = w2.id
            
            -- Receipt aggregation subquery (for MO metrics)
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    COUNT(*) as total_receipts,
                    SUM(quantity) as total_receipt_qty,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty,
                    SUM(CASE WHEN quality_status = 'FAILED' THEN quantity ELSE 0 END) as failed_qty,
                    SUM(CASE WHEN quality_status = 'PENDING' THEN quantity ELSE 0 END) as pending_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) rcpt ON rcpt.manufacturing_order_id = mo.id
            
            -- Material Issue Details (MAIN DATA SOURCE - 1 row per issue)
            JOIN material_issues mi ON mi.manufacturing_order_id = mo.id
            JOIN material_issue_details mid ON mid.material_issue_id = mi.id
            
            -- Manufacturing Order Materials (for primary material info & requirements)
            JOIN manufacturing_order_materials mom ON mid.manufacturing_order_material_id = mom.id
            
            -- Primary Material info (from MOM)
            JOIN products prim_p ON mom.material_id = prim_p.id
            JOIN brands prim_br ON prim_p.brand_id = prim_br.id
            
            -- ACTUAL Material issued (could be primary or alternative)
            JOIN products act_p ON mid.material_id = act_p.id
            JOIN brands act_br ON act_p.brand_id = act_br.id
            
            -- Return aggregation per issue detail
            LEFT JOIN (
                SELECT 
                    mrd.original_issue_detail_id,
                    SUM(mrd.quantity) as returned_qty,
                    MAX(mr.return_date) as last_return_date
                FROM material_return_details mrd
                JOIN material_returns mr ON mrd.material_return_id = mr.id
                WHERE mr.status = 'CONFIRMED'
                GROUP BY mrd.original_issue_detail_id
            ) ret ON ret.original_issue_detail_id = mid.id
            
            WHERE mo.delete_flag = 0
              AND mi.status = 'CONFIRMED'
        """
        
        params = []
        query += self._build_date_filter_clause(date_type, from_date, to_date, params)
        
        if status:
            query += " AND mo.status = %s"
            params.append(status)
        
        if search:
            query += """
                AND (
                    mo.order_no LIKE %s 
                    OR op.name LIKE %s 
                    OR op.pt_code LIKE %s
                    OR op.legacy_pt_code LIKE %s
                )
            """
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 4)
        
        query += " ORDER BY mo.order_no, prim_p.name, mid.is_alternative, act_p.name"
        
        try:
            df = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return df
        except Exception as e:
            logger.error(f"Error getting materials for export: {e}")
            return pd.DataFrame()