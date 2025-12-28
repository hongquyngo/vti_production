# utils/production/returns/queries.py
"""
Database queries for Returns domain
All SQL queries are centralized here for easy maintenance

Version: 1.1.0
Changes:
- Added connection check method
- Better error handling to distinguish connection errors from no data
"""

import logging
from datetime import date
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, DatabaseError

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


class ReturnQueries:
    """Database queries for Material Return management"""
    
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
    
    # ==================== Return History Queries ====================
    
    def get_returns(self,
                    from_date: Optional[date] = None,
                    to_date: Optional[date] = None,
                    order_no: Optional[str] = None,
                    status: Optional[str] = None,
                    reason: Optional[str] = None,
                    page: int = 1,
                    page_size: int = 20) -> pd.DataFrame:
        """
        Get material returns with filters and pagination
        
        Returns:
            DataFrame with return list
        """
        query = """
            SELECT 
                mr.id,
                mr.return_no,
                mr.return_date,
                mr.status,
                mr.reason,
                mr.created_date,
                mo.order_no,
                mo.id as order_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name,
                w.name as warehouse_name,
                CONCAT(e_returned.first_name, ' ', e_returned.last_name) as returned_by_name,
                CONCAT(e_received.first_name, ' ', e_received.last_name) as received_by_name,
                (SELECT COUNT(*) FROM material_return_details WHERE material_return_id = mr.id) as item_count,
                (SELECT COALESCE(SUM(quantity), 0) FROM material_return_details WHERE material_return_id = mr.id) as total_qty
            FROM material_returns mr
            JOIN manufacturing_orders mo ON mr.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            JOIN warehouses w ON mr.warehouse_id = w.id
            LEFT JOIN employees e_returned ON mr.returned_by = e_returned.id
            LEFT JOIN employees e_received ON mr.received_by = e_received.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(mr.return_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mr.return_date) <= %s"
            params.append(to_date)
        
        if order_no:
            query += " AND mo.order_no LIKE %s"
            params.append(f"%{order_no}%")
        
        if status:
            query += " AND mr.status = %s"
            params.append(status)
        
        if reason:
            query += " AND mr.reason = %s"
            params.append(reason)
        
        query += " ORDER BY mr.created_date DESC"
        
        # Pagination
        offset = (page - 1) * page_size
        query += " LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            self._connection_error = None
            return result
        except (OperationalError, DatabaseError) as e:
            self._connection_error = "Cannot connect to database. Please check your network/VPN connection."
            logger.error(f"Database connection error getting returns: {e}")
            return None
        except Exception as e:
            self._connection_error = f"Database error: {str(e)}"
            logger.error(f"Error getting returns: {e}")
            return None
    
    def get_returns_count(self,
                          from_date: Optional[date] = None,
                          to_date: Optional[date] = None,
                          order_no: Optional[str] = None,
                          status: Optional[str] = None,
                          reason: Optional[str] = None) -> int:
        """Get total count of returns matching filters"""
        query = """
            SELECT COUNT(*) as total
            FROM material_returns mr
            JOIN manufacturing_orders mo ON mr.manufacturing_order_id = mo.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(mr.return_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mr.return_date) <= %s"
            params.append(to_date)
        
        if order_no:
            query += " AND mo.order_no LIKE %s"
            params.append(f"%{order_no}%")
        
        if status:
            query += " AND mr.status = %s"
            params.append(status)
        
        if reason:
            query += " AND mr.reason = %s"
            params.append(reason)
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return int(result['total'].iloc[0])
        except Exception as e:
            logger.error(f"Error getting returns count: {e}")
            return 0
    
    def get_return_details(self, return_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information for a single return"""
        query = """
            SELECT 
                mr.id,
                mr.return_no,
                mr.return_date,
                mr.status,
                mr.reason,
                mr.created_date,
                mr.warehouse_id,
                mo.order_no,
                mo.id as order_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name,
                w.name as warehouse_name,
                mi.issue_no,
                mr.returned_by as returned_by_id,
                CONCAT(e_returned.first_name, ' ', e_returned.last_name) as returned_by_name,
                mr.received_by as received_by_id,
                CONCAT(e_received.first_name, ' ', e_received.last_name) as received_by_name,
                mr.created_by as created_by_id,
                CONCAT(e_created.first_name, ' ', e_created.last_name) as created_by_name
            FROM material_returns mr
            JOIN manufacturing_orders mo ON mr.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            JOIN warehouses w ON mr.warehouse_id = w.id
            LEFT JOIN material_issues mi ON mr.material_issue_id = mi.id
            LEFT JOIN employees e_returned ON mr.returned_by = e_returned.id
            LEFT JOIN employees e_received ON mr.received_by = e_received.id
            LEFT JOIN users u ON mr.created_by = u.id
            LEFT JOIN employees e_created ON u.employee_id = e_created.id
            WHERE mr.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(return_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting return details for {return_id}: {e}")
            return None
    
    def get_return_materials(self, return_id: int) -> pd.DataFrame:
        """Get materials for a return"""
        query = """
            SELECT 
                mrd.id,
                mrd.material_id,
                p.name as material_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name,
                mrd.batch_no,
                mrd.quantity,
                mrd.uom,
                mrd.`condition`,
                mrd.expired_date,
                COALESCE(mid.is_alternative, 0) as is_alternative,
                mid.original_material_id,
                op.name as original_material_name
            FROM material_return_details mrd
            JOIN products p ON mrd.material_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN material_issue_details mid ON mrd.original_issue_detail_id = mid.id
            LEFT JOIN products op ON mid.original_material_id = op.id
            WHERE mrd.material_return_id = %s
            ORDER BY p.name, mrd.batch_no
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(return_id,))
        except Exception as e:
            logger.error(f"Error getting return materials for {return_id}: {e}")
            return pd.DataFrame()
    
    # ==================== Returnable Materials Queries ====================
    
    def get_returnable_orders(self) -> pd.DataFrame:
        """Get orders that can have materials returned (IN_PROGRESS status)"""
        query = """
            SELECT 
                mo.id,
                mo.order_no,
                mo.order_date,
                mo.status,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name,
                w.name as warehouse_name,
                (SELECT COUNT(*) FROM material_issues mi 
                 WHERE mi.manufacturing_order_id = mo.id AND mi.status = 'CONFIRMED') as issue_count
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            JOIN warehouses w ON mo.warehouse_id = w.id
            WHERE mo.delete_flag = 0
                AND mo.status = 'IN_PROGRESS'
            ORDER BY mo.order_no DESC
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting returnable orders: {e}")
            return pd.DataFrame()
    
    def get_returnable_materials(self, order_id: int) -> pd.DataFrame:
        """
        Get list of materials that can be returned for an order
        
        Returns DataFrame with:
        - issue_detail_id, material_id, material_name, batch_no,
        - issued_qty, returned_qty, returnable_qty, uom, expired_date,
        - issue_date, is_alternative, original_material_id
        """
        query = """
            SELECT 
                mid.id as issue_detail_id,
                mid.material_id,
                p.name as material_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name,
                mid.batch_no,
                mid.quantity as issued_qty,
                COALESCE(SUM(mrd.quantity), 0) as returned_qty,
                mid.quantity - COALESCE(SUM(mrd.quantity), 0) as returnable_qty,
                mid.uom,
                mid.expired_date,
                mi.issue_date,
                mi.issue_no,
                COALESCE(mid.is_alternative, 0) as is_alternative,
                mid.original_material_id,
                p2.name as original_material_name
            FROM material_issues mi
            JOIN material_issue_details mid ON mi.id = mid.material_issue_id
            JOIN products p ON mid.material_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN products p2 ON mid.original_material_id = p2.id
            LEFT JOIN material_return_details mrd 
                ON mrd.original_issue_detail_id = mid.id
            LEFT JOIN material_returns mr 
                ON mr.id = mrd.material_return_id AND mr.status = 'CONFIRMED'
            WHERE mi.manufacturing_order_id = %s
                AND mi.status = 'CONFIRMED'
            GROUP BY mid.id, mid.material_id, p.name, p.pt_code, p.legacy_pt_code,
                     p.package_size, b.brand_name, mid.batch_no, 
                     mid.quantity, mid.uom, mid.expired_date,
                     mid.is_alternative, mid.original_material_id, p2.name,
                     mi.issue_date, mi.issue_no
            HAVING returnable_qty > 0
            ORDER BY p.name, mid.batch_no
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"❌ Error getting returnable materials: {e}")
            return pd.DataFrame()
    
    # ==================== Employee Queries ====================
    
    def get_employees(self) -> pd.DataFrame:
        """Get active employees for dropdowns"""
        query = """
            SELECT 
                e.id,
                CONCAT(e.first_name, ' ', e.last_name) as full_name,
                e.email,
                p.name as position_name,
                d.name as department_name
            FROM employees e
            LEFT JOIN positions p ON e.position_id = p.id
            LEFT JOIN departments d ON e.department_id = d.id
            WHERE e.delete_flag = 0
                AND (e.status = 'ACTIVE' OR e.status IS NULL)
            ORDER BY e.first_name, e.last_name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting employees: {e}")
            return pd.DataFrame()
    
    # ==================== Dashboard Metrics ====================
    
    def get_return_metrics(self, from_date: Optional[date] = None,
                          to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get return metrics for dashboard"""
        from .common import get_vietnam_today
        
        today = get_vietnam_today()
        
        base_query = """
            SELECT 
                COUNT(*) as total_returns,
                SUM(CASE WHEN DATE(return_date) = %s THEN 1 ELSE 0 END) as today_returns,
                SUM(CASE WHEN status = 'CONFIRMED' THEN 1 ELSE 0 END) as confirmed_count
            FROM material_returns
            WHERE 1=1
        """
        
        params = [today]
        
        if from_date:
            base_query += " AND DATE(return_date) >= %s"
            params.append(from_date)
        
        if to_date:
            base_query += " AND DATE(return_date) <= %s"
            params.append(to_date)
        
        # Returnable orders count
        returnable_query = """
            SELECT COUNT(*) as returnable_orders
            FROM manufacturing_orders
            WHERE delete_flag = 0
                AND status = 'IN_PROGRESS'
        """
        
        # Total units returned
        units_query = """
            SELECT COALESCE(SUM(mrd.quantity), 0) as total_units
            FROM material_return_details mrd
            JOIN material_returns mr ON mrd.material_return_id = mr.id
            WHERE 1=1
        """
        
        if from_date:
            units_query += " AND DATE(mr.return_date) >= %s"
        if to_date:
            units_query += " AND DATE(mr.return_date) <= %s"
        
        # Reason breakdown
        reason_query = """
            SELECT reason, COUNT(*) as count
            FROM material_returns
            WHERE 1=1
        """
        
        if from_date:
            reason_query += " AND DATE(return_date) >= %s"
        if to_date:
            reason_query += " AND DATE(return_date) <= %s"
        
        reason_query += " GROUP BY reason"
        
        try:
            result = pd.read_sql(base_query, self.engine, params=tuple(params))
            returnable = pd.read_sql(returnable_query, self.engine)
            
            units_params = []
            if from_date:
                units_params.append(from_date)
            if to_date:
                units_params.append(to_date)
            units = pd.read_sql(units_query, self.engine, 
                              params=tuple(units_params) if units_params else None)
            
            reasons = pd.read_sql(reason_query, self.engine,
                                 params=tuple(units_params) if units_params else None)
            
            row = result.iloc[0]
            
            reason_breakdown = dict(zip(reasons['reason'], reasons['count'])) if not reasons.empty else {}
            
            return {
                'total_returns': int(row['total_returns']),
                'today_returns': int(row['today_returns']),
                'confirmed_count': int(row['confirmed_count']),
                'returnable_orders': int(returnable.iloc[0]['returnable_orders']),
                'total_units': float(units.iloc[0]['total_units']),
                'reason_breakdown': reason_breakdown
            }
            
        except Exception as e:
            logger.error(f"Error getting return metrics: {e}")
            return {
                'total_returns': 0,
                'today_returns': 0,
                'confirmed_count': 0,
                'returnable_orders': 0,
                'total_units': 0,
                'reason_breakdown': {}
            }