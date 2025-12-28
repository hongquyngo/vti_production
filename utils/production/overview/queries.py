# utils/production/overview/queries.py
"""
Database queries for Production Overview domain
Complex aggregation queries joining MO, materials, receipts

Version: 2.0.0
Changes:
- v2.0.0: Added lifecycle stage queries, analytics data methods
- v1.0.0: Initial version
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
    
    # ==================== Main Overview Query ====================
    
    def get_production_overview(self,
                                from_date: Optional[date] = None,
                                to_date: Optional[date] = None,
                                status: Optional[str] = None,
                                health_filter: Optional[str] = None,
                                search: Optional[str] = None,
                                page: int = 1,
                                page_size: int = 15) -> Optional[pd.DataFrame]:
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
                COALESCE(mat.total_required, 0) as total_material_required,
                COALESCE(mat.total_issued, 0) as total_material_issued,
                COALESCE(mat.material_count, 0) as material_count,
                COALESCE(mat.materials_fully_issued, 0) as materials_fully_issued,
                
                -- Receipt aggregation
                COALESCE(rcpt.total_receipts, 0) as total_receipts,
                COALESCE(rcpt.total_receipt_qty, 0) as total_receipt_qty,
                COALESCE(rcpt.passed_qty, 0) as passed_qty,
                COALESCE(rcpt.failed_qty, 0) as failed_qty,
                COALESCE(rcpt.pending_qty, 0) as pending_qty,
                
                -- Return aggregation
                COALESCE(ret.total_returned, 0) as total_returned,
                
                -- Calculated fields
                CASE 
                    WHEN mo.planned_qty > 0 
                    THEN ROUND((mo.produced_qty / mo.planned_qty) * 100, 1)
                    ELSE 0 
                END as progress_percentage,
                
                CASE 
                    WHEN COALESCE(mat.total_required, 0) > 0 
                    THEN ROUND((COALESCE(mat.total_issued, 0) / mat.total_required) * 100, 1)
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
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    COUNT(*) as material_count,
                    SUM(required_qty) as total_required,
                    SUM(issued_qty) as total_issued,
                    SUM(CASE WHEN issued_qty >= required_qty THEN 1 ELSE 0 END) as materials_fully_issued
                FROM manufacturing_order_materials
                GROUP BY manufacturing_order_id
            ) mat ON mat.manufacturing_order_id = mo.id
            
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
            
            -- Return aggregation subquery
            LEFT JOIN (
                SELECT 
                    mr.manufacturing_order_id,
                    SUM(mrd.quantity) as total_returned
                FROM material_returns mr
                JOIN material_return_details mrd ON mrd.material_return_id = mr.id
                WHERE mr.status = 'CONFIRMED'
                GROUP BY mr.manufacturing_order_id
            ) ret ON ret.manufacturing_order_id = mo.id
            
            WHERE mo.delete_flag = 0
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(mo.order_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mo.order_date) <= %s"
            params.append(to_date)
        
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
                          search: Optional[str] = None) -> int:
        """Get total count of orders matching filters"""
        query = """
            SELECT COUNT(*) as total
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            WHERE mo.delete_flag = 0
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(mo.order_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mo.order_date) <= %s"
            params.append(to_date)
        
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
                            to_date: Optional[date] = None) -> Dict[str, Any]:
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
        
        if from_date:
            query += " AND DATE(mo.order_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mo.order_date) <= %s"
            params.append(to_date)
        
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
                mom.issued_qty,
                mom.uom,
                mom.status,
                COALESCE(ret.returned_qty, 0) as returned_qty,
                (mom.issued_qty - COALESCE(ret.returned_qty, 0)) as net_used,
                CASE 
                    WHEN mom.required_qty > 0 
                    THEN ROUND((mom.issued_qty / mom.required_qty) * 100, 1)
                    ELSE 0 
                END as issue_percentage
            FROM manufacturing_order_materials mom
            JOIN products p ON mom.material_id = p.id
            JOIN brands br ON p.brand_id = br.id
            LEFT JOIN (
                SELECT 
                    mid.manufacturing_order_material_id,
                    SUM(mrd.quantity) as returned_qty
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
    
    # ==================== Filter Options ====================
    
    def get_filter_options(self) -> Dict[str, List[str]]:
        """Get filter dropdown options"""
        return {
            'statuses': ['All', 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
            'health': ['All', 'ON_TRACK', 'AT_RISK', 'DELAYED', 'NOT_STARTED'],
        }