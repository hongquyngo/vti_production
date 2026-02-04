# utils/production/completions/queries.py
"""
Database queries for Completions domain
All SQL queries are centralized here for easy maintenance

Version: 1.4.0
Changes:
- v1.4.0: Added validation queries (check_duplicate_batch_no, get_pending_receipts_count)
- v1.3.0: Added scheduled_date to receipts query
- v1.2.0: Added order_date and package_size to receipts query for improved display
- v1.1.0: Added connection check method
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


class DatabaseConnectionError(Exception):
    """Custom exception for database connection errors"""
    pass


class CompletionQueries:
    """Database queries for Production Completion management"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self._connection_error = None
    
    def check_connection(self) -> Tuple[bool, Optional[str]]:
        """
        Check database connection
        
        Returns:
            Tuple of (is_connected, error_message)
        """
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
    
    # ==================== Receipt Queries ====================
    
    def get_receipts(self,
                    from_date: Optional[date] = None,
                    to_date: Optional[date] = None,
                    quality_status: Optional[str] = None,
                    product_id: Optional[int] = None,
                    warehouse_id: Optional[int] = None,
                    order_no: Optional[str] = None,
                    batch_no: Optional[str] = None,
                    page: int = 1,
                    page_size: int = 20) -> Optional[pd.DataFrame]:
        """
        Get production receipts with filters and pagination
        
        Returns:
            DataFrame with receipt list, or None if connection error
        """
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                pr.receipt_date,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                pr.expired_date,
                pr.quality_status,
                pr.notes,
                pr.created_date,
                mo.order_no,
                mo.id as order_id,
                mo.order_date,
                mo.scheduled_date,
                mo.planned_qty,
                mo.produced_qty,
                p.id as product_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name as brand_name,
                w.id as warehouse_id,
                w.name as warehouse_name,
                CASE 
                    WHEN mo.planned_qty > 0 
                    THEN ROUND((mo.produced_qty / mo.planned_qty) * 100, 1)
                    ELSE 0
                END as yield_rate
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN products p ON pr.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(pr.receipt_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(pr.receipt_date) <= %s"
            params.append(to_date)
        
        if quality_status:
            query += " AND pr.quality_status = %s"
            params.append(quality_status)
        
        if product_id:
            query += " AND pr.product_id = %s"
            params.append(product_id)
        
        if warehouse_id:
            query += " AND pr.warehouse_id = %s"
            params.append(warehouse_id)
        
        if order_no:
            query += " AND mo.order_no LIKE %s"
            params.append(f"%{order_no}%")
        
        if batch_no:
            query += " AND pr.batch_no LIKE %s"
            params.append(f"%{batch_no}%")
        
        query += " ORDER BY pr.created_date DESC"
        
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
            logger.error(f"Database connection error getting receipts: {e}")
            return None
        except Exception as e:
            self._connection_error = f"Database error: {str(e)}"
            logger.error(f"Error getting receipts: {e}")
            return None
    
    def get_receipts_count(self,
                          from_date: Optional[date] = None,
                          to_date: Optional[date] = None,
                          quality_status: Optional[str] = None,
                          product_id: Optional[int] = None,
                          warehouse_id: Optional[int] = None,
                          order_no: Optional[str] = None,
                          batch_no: Optional[str] = None) -> int:
        """Get total count of receipts matching filters"""
        query = """
            SELECT COUNT(*) as total
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(pr.receipt_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(pr.receipt_date) <= %s"
            params.append(to_date)
        
        if quality_status:
            query += " AND pr.quality_status = %s"
            params.append(quality_status)
        
        if product_id:
            query += " AND pr.product_id = %s"
            params.append(product_id)
        
        if warehouse_id:
            query += " AND pr.warehouse_id = %s"
            params.append(warehouse_id)
        
        if order_no:
            query += " AND mo.order_no LIKE %s"
            params.append(f"%{order_no}%")
        
        if batch_no:
            query += " AND pr.batch_no LIKE %s"
            params.append(f"%{batch_no}%")
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return int(result['total'].iloc[0])
        except Exception as e:
            logger.error(f"Error getting receipts count: {e}")
            return 0
    
    def get_receipt_details(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        """Get full receipt details including order and product info"""
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                pr.receipt_date,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                pr.expired_date,
                pr.quality_status,
                pr.notes,
                pr.created_by,
                pr.created_date,
                mo.id as manufacturing_order_id,
                mo.order_no,
                mo.order_date,
                mo.scheduled_date,
                mo.planned_qty,
                mo.produced_qty,
                mo.status as order_status,
                p.id as product_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                w.id as warehouse_id,
                w.name as warehouse_name,
                bh.bom_name,
                CONCAT(e.first_name, ' ', e.last_name) as created_by_name
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN products p ON pr.product_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            LEFT JOIN bom_headers bh ON mo.bom_header_id = bh.id
            LEFT JOIN users u ON pr.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE pr.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(receipt_id,))
            if not result.empty:
                return result.iloc[0].to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting receipt details for {receipt_id}: {e}")
            return None
    
    def get_receipt_materials(self, order_id: int) -> pd.DataFrame:
        """Get material usage for an order"""
        query = """
            SELECT 
                p.id as material_id,
                p.name as material_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name as brand_name,
                bd.material_type,
                mom.required_qty,
                COALESCE(mom.issued_qty, 0) as issued_qty,
                mom.uom,
                CASE 
                    WHEN COALESCE(mom.issued_qty, 0) >= mom.required_qty THEN 'COMPLETED'
                    WHEN COALESCE(mom.issued_qty, 0) > 0 THEN 'PARTIAL'
                    ELSE 'PENDING'
                END as status
            FROM manufacturing_order_materials mom
            JOIN products p ON mom.material_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            LEFT JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
                AND bd.material_id = mom.material_id
            WHERE mom.manufacturing_order_id = %s
            ORDER BY bd.material_type, p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting receipt materials for order {order_id}: {e}")
            return pd.DataFrame()
    
    # ==================== Order Queries ====================
    
    def get_completable_orders(self) -> pd.DataFrame:
        """Get orders that can be completed (IN_PROGRESS status)"""
        query = """
            SELECT 
                mo.id,
                mo.order_no,
                mo.order_date,
                mo.status,
                mo.planned_qty,
                COALESCE(mo.produced_qty, 0) as produced_qty,
                mo.planned_qty - COALESCE(mo.produced_qty, 0) as remaining_qty,
                mo.uom,
                p.id as product_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                b.brand_name as brand_name,
                w.id as warehouse_id,
                w.name as warehouse_name,
                tw.id as target_warehouse_id,
                tw.name as target_warehouse_name,
                bh.bom_name as bom_name
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            JOIN warehouses w ON mo.warehouse_id = w.id
            JOIN warehouses tw ON mo.target_warehouse_id = tw.id
            LEFT JOIN bom_headers bh ON mo.bom_header_id = bh.id
            WHERE mo.delete_flag = 0
                AND mo.status = 'IN_PROGRESS'
            ORDER BY mo.order_no DESC
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting completable orders: {e}")
            return pd.DataFrame()
    
    def get_order_output_summary(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get production output summary for an order"""
        query = """
            SELECT 
                mo.planned_qty,
                COALESCE(mo.produced_qty, 0) as produced_qty,
                mo.uom,
                COUNT(pr.id) as receipt_count,
                COALESCE(SUM(pr.quantity), 0) as total_receipts,
                COALESCE(SUM(CASE WHEN pr.quality_status = 'PASSED' THEN pr.quantity ELSE 0 END), 0) as passed_qty,
                COALESCE(SUM(CASE WHEN pr.quality_status = 'PENDING' THEN pr.quantity ELSE 0 END), 0) as pending_qty,
                COALESCE(SUM(CASE WHEN pr.quality_status = 'FAILED' THEN pr.quantity ELSE 0 END), 0) as failed_qty,
                CASE 
                    WHEN mo.planned_qty > 0 
                    THEN ROUND((COALESCE(mo.produced_qty, 0) / mo.planned_qty) * 100, 1)
                    ELSE 0
                END as yield_rate,
                mo.planned_qty - COALESCE(mo.produced_qty, 0) as shortfall
            FROM manufacturing_orders mo
            LEFT JOIN production_receipts pr ON mo.id = pr.manufacturing_order_id
            WHERE mo.id = %s
            GROUP BY mo.id, mo.planned_qty, mo.produced_qty, mo.uom
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting order output summary for {order_id}: {e}")
            return None
    
    def get_order_receipts(self, order_id: int) -> pd.DataFrame:
        """Get all receipts for an order"""
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                pr.receipt_date,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                pr.quality_status
            FROM production_receipts pr
            WHERE pr.manufacturing_order_id = %s
            ORDER BY pr.receipt_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting order receipts for {order_id}: {e}")
            return pd.DataFrame()
    
    # ==================== Lookup Queries ====================
    
    def get_products(self) -> pd.DataFrame:
        """Get products for filter dropdown"""
        query = """
            SELECT DISTINCT p.id, p.name, p.pt_code, p.package_size
            FROM products p
            JOIN production_receipts pr ON p.id = pr.product_id
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting products: {e}")
            return pd.DataFrame()
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get warehouses for filter dropdown"""
        query = """
            SELECT DISTINCT w.id, w.name
            FROM warehouses w
            JOIN production_receipts pr ON w.id = pr.warehouse_id
            ORDER BY w.name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
            return pd.DataFrame()
    
    # ==================== Validation Queries ====================
    
    def check_duplicate_batch_no(self, batch_no: str,
                                  order_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Check if batch_no already exists in production_receipts.
        
        Args:
            batch_no: Batch number to check
            order_id: Exclude receipts from this order (same order = expected)
        
        Returns:
            Dict with is_duplicate, count, existing list
        """
        query = """
            SELECT pr.receipt_no, mo.order_no, pr.receipt_date
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            WHERE pr.batch_no = %s
        """
        params = [batch_no]
        
        if order_id:
            query += " AND pr.manufacturing_order_id != %s"
            params.append(order_id)
        
        query += " ORDER BY pr.receipt_date DESC LIMIT 5"
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params))
            return {
                'is_duplicate': not result.empty,
                'count': len(result),
                'existing': result.to_dict('records') if not result.empty else []
            }
        except Exception as e:
            logger.error(f"Error checking duplicate batch_no '{batch_no}': {e}")
            return {'is_duplicate': False, 'count': 0, 'existing': []}
    
    def get_pending_receipts_count(self, order_id: int) -> int:
        """
        Get count of receipts with PENDING quality status for an order.
        Used to validate order auto-completion eligibility.
        
        Args:
            order_id: Manufacturing order ID
            
        Returns:
            Number of PENDING receipts
        """
        query = """
            SELECT COUNT(*) as pending_count
            FROM production_receipts
            WHERE manufacturing_order_id = %s
                AND quality_status = 'PENDING'
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return int(result['pending_count'].iloc[0])
        except Exception as e:
            logger.error(f"Error getting pending receipts count for order {order_id}: {e}")
            return 0
    
    def get_duplicate_batch_info(self, batch_nos: list) -> Dict[str, int]:
        """
        Check which batch_nos appear in multiple manufacturing orders.
        Efficient bulk query — one call for entire page of data.
        
        Args:
            batch_nos: List of batch numbers to check
            
        Returns:
            Dict {batch_no: order_count} for duplicated batches only
        """
        if not batch_nos:
            return {}
        
        # Deduplicate and filter empty
        unique_batches = list(set(b for b in batch_nos if b))
        if not unique_batches:
            return {}
        
        placeholders = ','.join(['%s'] * len(unique_batches))
        query = f"""
            SELECT batch_no, COUNT(DISTINCT manufacturing_order_id) as order_count
            FROM production_receipts
            WHERE batch_no IN ({placeholders})
            GROUP BY batch_no
            HAVING COUNT(DISTINCT manufacturing_order_id) > 1
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(unique_batches))
            return dict(zip(result['batch_no'], result['order_count']))
        except Exception as e:
            logger.error(f"Error checking duplicate batches: {e}")
            return {}
    
    # ==================== Dashboard Metrics ====================
    
    def get_completion_metrics(self, from_date: Optional[date] = None,
                              to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get completion metrics for dashboard"""
        from .common import get_vietnam_today
        
        today = get_vietnam_today()
        
        base_query = """
            SELECT 
                COUNT(*) as total_receipts,
                SUM(CASE WHEN DATE(receipt_date) = %s THEN 1 ELSE 0 END) as today_receipts,
                COALESCE(SUM(quantity), 0) as total_quantity,
                COALESCE(SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END), 0) as passed_qty,
                COALESCE(SUM(CASE WHEN quality_status = 'PENDING' THEN quantity ELSE 0 END), 0) as pending_qty,
                COALESCE(SUM(CASE WHEN quality_status = 'FAILED' THEN quantity ELSE 0 END), 0) as failed_qty
            FROM production_receipts
            WHERE 1=1
        """
        
        params = [today]
        
        if from_date:
            base_query += " AND DATE(receipt_date) >= %s"
            params.append(from_date)
        
        if to_date:
            base_query += " AND DATE(receipt_date) <= %s"
            params.append(to_date)
        
        # In-progress orders count
        orders_query = """
            SELECT COUNT(*) as in_progress_orders
            FROM manufacturing_orders
            WHERE delete_flag = 0
                AND status = 'IN_PROGRESS'
        """
        
        # Quality breakdown
        quality_query = """
            SELECT 
                quality_status,
                COUNT(*) as count,
                COALESCE(SUM(quantity), 0) as quantity
            FROM production_receipts
            WHERE 1=1
        """
        
        if from_date:
            quality_query += " AND DATE(receipt_date) >= %s"
        if to_date:
            quality_query += " AND DATE(receipt_date) <= %s"
        
        quality_query += " GROUP BY quality_status"
        
        try:
            result = pd.read_sql(base_query, self.engine, params=tuple(params))
            orders = pd.read_sql(orders_query, self.engine)
            
            quality_params = []
            if from_date:
                quality_params.append(from_date)
            if to_date:
                quality_params.append(to_date)
            quality = pd.read_sql(quality_query, self.engine,
                                 params=tuple(quality_params) if quality_params else None)
            
            row = result.iloc[0]
            
            total_qty = float(row['total_quantity'])
            passed_qty = float(row['passed_qty'])
            pass_rate = round((passed_qty / total_qty * 100) if total_qty > 0 else 0, 1)
            
            quality_breakdown = {}
            if not quality.empty:
                for _, qrow in quality.iterrows():
                    quality_breakdown[qrow['quality_status']] = {
                        'count': int(qrow['count']),
                        'quantity': float(qrow['quantity'])
                    }
            
            return {
                'total_receipts': int(row['total_receipts']),
                'today_receipts': int(row['today_receipts']),
                'total_quantity': total_qty,
                'passed_qty': passed_qty,
                'pending_qty': float(row['pending_qty']),
                'failed_qty': float(row['failed_qty']),
                'pass_rate': pass_rate,
                'in_progress_orders': int(orders.iloc[0]['in_progress_orders']),
                'quality_breakdown': quality_breakdown
            }
            
        except Exception as e:
            logger.error(f"Error getting completion metrics: {e}")
            return {
                'total_receipts': 0,
                'today_receipts': 0,
                'total_quantity': 0,
                'passed_qty': 0,
                'pending_qty': 0,
                'failed_qty': 0,
                'pass_rate': 0,
                'in_progress_orders': 0,
                'quality_breakdown': {}
            }