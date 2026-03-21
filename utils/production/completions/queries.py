# utils/production/completions/queries.py
"""
Database queries for Production Receipts domain
All SQL queries are centralized here for easy maintenance

Version: 2.1.0
Changes:
- v2.1.0: Date filter improvements
  - Added DATE_FIELD_MAP for multi-column date filtering
  - Added date_field param to get_receipts() and get_filtered_stats()
  - Supports receipt_date, order_date, scheduled_date filtering
- v2.0.0: Production Receipts refactoring
  - Added order_status, receipt age_days to get_receipts()
  - Added exclude_completed filter to get_receipts() and get_filtered_stats()
  - Added get_close_order_validation(), get_ready_to_close_orders()
  - Added get_order_status_for_receipt()
  - Updated get_live_stats() to include ready_to_close count
- v1.4.0: Added validation queries (check_duplicate_batch_no, get_pending_receipts_count)
- v1.3.0: Added scheduled_date to receipts query
"""

import logging
from datetime import date
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, DatabaseError

from utils.db import get_db_engine
from .common import PerformanceTimer

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Custom exception for database connection errors"""
    pass


DATE_FIELD_MAP = {
    'receipt_date': 'DATE(pr.receipt_date)',
    'order_date': 'DATE(mo.order_date)',
    'scheduled_date': 'DATE(mo.scheduled_date)',
}


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
                    exclude_completed: bool = True,
                    date_field: str = 'receipt_date',
                    page: int = 1,
                    page_size: int = 20) -> Optional[pd.DataFrame]:
        """
        Get production receipts with filters and pagination
        
        Args:
            exclude_completed: If True, hide receipts from COMPLETED MOs (default)
            date_field: Which date column to filter on ('receipt_date', 'order_date', 'scheduled_date')
        
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
                mo.status as order_status,
                DATEDIFF(NOW(), pr.created_date) as age_days,
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
        
        # Resolve date column from field mapping
        date_column = DATE_FIELD_MAP.get(date_field, 'DATE(pr.receipt_date)')
        
        if exclude_completed:
            query += " AND mo.status != 'COMPLETED'"
        
        if from_date:
            query += f" AND {date_column} >= %s"
            params.append(from_date)
        
        if to_date:
            query += f" AND {date_column} <= %s"
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
            import time as _t; _t0 = _t.perf_counter()
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            _ms = (_t.perf_counter() - _t0) * 1000
            logger.info(f"[PERF] get_receipts: {_ms:.0f}ms ({len(result)} rows, page={page})")
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
            import time as _t; _t0 = _t.perf_counter()
            result = pd.read_sql(query, self.engine, params=tuple(unique_batches))
            _ms = (_t.perf_counter() - _t0) * 1000
            logger.info(f"[PERF] get_duplicate_batch_info: {_ms:.0f}ms ({len(unique_batches)} batches)")
            return dict(zip(result['batch_no'], result['order_count']))
        except Exception as e:
            logger.error(f"Error checking duplicate batches: {e}")
            return {}
    
    # ==================== Live Stats (Lightweight) ====================
    
    def get_live_stats(self) -> Dict[str, int]:
        """
        Lightweight query for header live KPIs.
        Returns in_progress orders count, today's receipts count,
        and ready-to-close orders count.
        Called outside fragment — renders once per page load.
        """
        from .common import get_vietnam_today
        today = get_vietnam_today()
        
        query = """
            SELECT 
                (SELECT COUNT(*) FROM manufacturing_orders 
                 WHERE delete_flag = 0 AND status = 'IN_PROGRESS') as in_progress,
                (SELECT COUNT(*) FROM production_receipts 
                 WHERE DATE(receipt_date) = %s) as today_count,
                (SELECT COUNT(*) FROM manufacturing_orders mo
                 WHERE mo.delete_flag = 0 
                   AND mo.status = 'IN_PROGRESS'
                   AND mo.produced_qty >= mo.planned_qty
                   AND NOT EXISTS (
                       SELECT 1 FROM production_receipts pr 
                       WHERE pr.manufacturing_order_id = mo.id 
                         AND pr.quality_status = 'PENDING'
                   )
                   AND EXISTS (
                       SELECT 1 FROM production_receipts pr2
                       WHERE pr2.manufacturing_order_id = mo.id
                   )
                ) as ready_to_close
        """
        
        try:
            import time as _t; _t0 = _t.perf_counter()
            result = pd.read_sql(query, self.engine, params=(today,))
            _ms = (_t.perf_counter() - _t0) * 1000
            logger.info(f"[PERF] get_live_stats: {_ms:.0f}ms")
            row = result.iloc[0]
            return {
                'in_progress': int(row['in_progress']),
                'today_count': int(row['today_count']),
                'ready_to_close': int(row['ready_to_close'])
            }
        except Exception as e:
            logger.error(f"Error getting live stats: {e}")
            return {'in_progress': 0, 'today_count': 0, 'ready_to_close': 0}
    
    # ==================== Filtered Stats (All Matching Data) ====================
    
    def get_filtered_stats(self,
                           from_date: Optional[date] = None,
                           to_date: Optional[date] = None,
                           quality_status: Optional[str] = None,
                           product_id: Optional[int] = None,
                           warehouse_id: Optional[int] = None,
                           order_no: Optional[str] = None,
                           batch_no: Optional[str] = None,
                           exclude_completed: bool = True,
                           date_field: str = 'receipt_date') -> Dict[str, Any]:
        """
        Get summary statistics for ALL filtered receipts (not just current page).
        Single query returning count, quantity, quality breakdown.
        
        Returns:
            Dict with total_count, total_quantity, passed/pending/failed counts
        """
        query = """
            SELECT 
                COUNT(*) as total_count,
                COALESCE(SUM(pr.quantity), 0) as total_quantity,
                SUM(CASE WHEN pr.quality_status = 'PASSED' THEN 1 ELSE 0 END) as passed_count,
                SUM(CASE WHEN pr.quality_status = 'PENDING' THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN pr.quality_status = 'FAILED' THEN 1 ELSE 0 END) as failed_count,
                COALESCE(SUM(CASE WHEN pr.quality_status = 'PASSED' THEN pr.quantity ELSE 0 END), 0) as passed_qty,
                COALESCE(SUM(CASE WHEN pr.quality_status = 'PENDING' THEN pr.quantity ELSE 0 END), 0) as pending_qty,
                COALESCE(SUM(CASE WHEN pr.quality_status = 'FAILED' THEN pr.quantity ELSE 0 END), 0) as failed_qty
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            WHERE 1=1
        """
        
        params = []
        
        # Resolve date column from field mapping
        date_column = DATE_FIELD_MAP.get(date_field, 'DATE(pr.receipt_date)')
        
        if exclude_completed:
            query += " AND mo.status != 'COMPLETED'"
        
        if from_date:
            query += f" AND {date_column} >= %s"
            params.append(from_date)
        if to_date:
            query += f" AND {date_column} <= %s"
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
            import time as _t; _t0 = _t.perf_counter()
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            _ms = (_t.perf_counter() - _t0) * 1000
            logger.info(f"[PERF] get_filtered_stats: {_ms:.0f}ms")
            row = result.iloc[0]
            
            total = int(row['total_count'])
            passed = int(row['passed_count'])
            total_qty = float(row['total_quantity'])
            passed_qty = float(row['passed_qty'])
            
            return {
                'total_count': total,
                'total_quantity': total_qty,
                'passed_count': passed,
                'pending_count': int(row['pending_count']),
                'failed_count': int(row['failed_count']),
                'passed_qty': passed_qty,
                'pending_qty': float(row['pending_qty']),
                'failed_qty': float(row['failed_qty']),
                'pass_rate': round((passed / total * 100) if total > 0 else 0, 1),
            }
        except Exception as e:
            logger.error(f"Error getting filtered stats: {e}")
            return {
                'total_count': 0, 'total_quantity': 0,
                'passed_count': 0, 'pending_count': 0, 'failed_count': 0,
                'passed_qty': 0, 'pending_qty': 0, 'failed_qty': 0,
                'pass_rate': 0,
            }
    
    # ==================== Close Order Queries ====================
    
    def get_close_order_validation(self, order_id: int) -> Dict[str, Any]:
        """
        Check all pre-conditions for closing an order.
        Returns dict with can_close, reasons, and stats.
        """
        query = """
            SELECT
                mo.id,
                mo.order_no,
                mo.status,
                mo.produced_qty,
                mo.planned_qty,
                mo.uom,
                COALESCE(pr_stats.receipt_count, 0) AS receipt_count,
                COALESCE(pr_stats.pending_count, 0) AS pending_count,
                COALESCE(pr_stats.passed_count, 0) AS passed_count,
                COALESCE(pr_stats.failed_count, 0) AS failed_count,
                COALESCE(pr_stats.passed_qty, 0) AS passed_qty,
                COALESCE(unissued.unissued_count, 0) AS unissued_materials
            FROM manufacturing_orders mo
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    COUNT(*) AS receipt_count,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN 1 ELSE 0 END) AS passed_count,
                    SUM(CASE WHEN quality_status = 'PENDING' THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN quality_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) AS passed_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) pr_stats ON mo.id = pr_stats.manufacturing_order_id
            LEFT JOIN (
                SELECT 
                    mom.manufacturing_order_id,
                    COUNT(*) AS unissued_count
                FROM manufacturing_order_materials mom
                LEFT JOIN manufacturing_orders mo2 ON mom.manufacturing_order_id = mo2.id
                LEFT JOIN bom_details bd ON bd.bom_header_id = mo2.bom_header_id 
                    AND bd.material_id = mom.material_id
                WHERE COALESCE(mom.issued_qty, 0) = 0
                    AND (bd.material_type = 'RAW_MATERIAL' OR bd.material_type IS NULL)
                GROUP BY mom.manufacturing_order_id
            ) unissued ON mo.id = unissued.manufacturing_order_id
            WHERE mo.id = %s AND mo.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            if result.empty:
                return {'can_close': False, 'reasons': ['Order not found']}
            
            row = result.iloc[0]
            reasons = []
            
            if row['status'] != 'IN_PROGRESS':
                reasons.append(f"Order status is {row['status']}, must be IN_PROGRESS")
            if row['receipt_count'] == 0:
                reasons.append("No production receipts exist")
            if row['pending_count'] > 0:
                reasons.append(f"{int(row['pending_count'])} receipt(s) still PENDING QC")
            if row['unissued_materials'] > 0:
                reasons.append(f"{int(row['unissued_materials'])} raw material(s) not issued")
            
            return {
                'can_close': len(reasons) == 0,
                'reasons': reasons,
                'order_no': row['order_no'],
                'status': row['status'],
                'produced_qty': float(row['produced_qty']),
                'planned_qty': float(row['planned_qty']),
                'uom': row['uom'],
                'receipt_count': int(row['receipt_count']),
                'pending_count': int(row['pending_count']),
                'passed_count': int(row['passed_count']),
                'failed_count': int(row['failed_count']),
                'passed_qty': float(row['passed_qty']),
            }
        except Exception as e:
            logger.error(f"Error validating close order {order_id}: {e}")
            return {'can_close': False, 'reasons': [f'Database error: {str(e)}']}
    
    def get_ready_to_close_orders(self) -> Dict[str, Any]:
        """
        Get counts and lists of orders ready to close vs blocked by pending QC.
        For Ready-to-Close banner display.
        """
        query = """
            SELECT
                mo.id,
                mo.order_no,
                mo.produced_qty,
                mo.planned_qty,
                mo.uom,
                p.name AS product_name,
                COALESCE(pr_stats.pending_count, 0) AS pending_count,
                COALESCE(pr_stats.receipt_count, 0) AS receipt_count,
                CASE 
                    WHEN COALESCE(pr_stats.pending_count, 0) = 0 
                         AND COALESCE(pr_stats.receipt_count, 0) > 0
                    THEN 'READY'
                    ELSE 'BLOCKED'
                END AS close_status
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    COUNT(*) AS receipt_count,
                    SUM(CASE WHEN quality_status = 'PENDING' THEN 1 ELSE 0 END) AS pending_count
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) pr_stats ON mo.id = pr_stats.manufacturing_order_id
            WHERE mo.status = 'IN_PROGRESS' 
                AND mo.delete_flag = 0
                AND mo.produced_qty >= mo.planned_qty
            ORDER BY mo.order_no
        """
        
        try:
            result = pd.read_sql(query, self.engine)
            if result.empty:
                return {'ready_count': 0, 'blocked_count': 0, 'ready_orders': [], 'blocked_orders': []}
            
            ready = result[result['close_status'] == 'READY']
            blocked = result[result['close_status'] == 'BLOCKED']
            
            return {
                'ready_count': len(ready),
                'blocked_count': len(blocked),
                'ready_orders': ready.to_dict('records') if not ready.empty else [],
                'blocked_orders': blocked.to_dict('records') if not blocked.empty else [],
            }
        except Exception as e:
            logger.error(f"Error getting ready-to-close orders: {e}")
            return {'ready_count': 0, 'blocked_count': 0, 'ready_orders': [], 'blocked_orders': []}
    
    def get_order_status_for_receipt(self, receipt_id: int) -> Optional[str]:
        """Get the MO status for a given receipt. Used for QC lock checks."""
        query = """
            SELECT mo.status
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            WHERE pr.id = %s
        """
        try:
            result = pd.read_sql(query, self.engine, params=(receipt_id,))
            if not result.empty:
                return result.iloc[0]['status']
            return None
        except Exception as e:
            logger.error(f"Error getting order status for receipt {receipt_id}: {e}")
            return None
    
    # ==================== Bulk Load (Client-Side Filtering) ====================
    
    def get_all_active_receipts(self, include_completed: bool = False) -> Optional[pd.DataFrame]:
        """
        Load ALL receipts in one query — no pagination, no filters.
        Filtering, sorting, pagination done client-side with pandas.
        
        This replaces per-page get_receipts + get_filtered_stats + get_duplicate_batch_info
        with a SINGLE cached DB hit.
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
                mo.status as order_status,
                DATEDIFF(NOW(), pr.created_date) as age_days,
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
        
        if not include_completed:
            query += " AND mo.status != 'COMPLETED'"
        
        query += " ORDER BY pr.created_date DESC"
        
        try:
            import time as _t; _t0 = _t.perf_counter()
            result = pd.read_sql(query, self.engine)
            _ms = (_t.perf_counter() - _t0) * 1000
            logger.info(f"[PERF] get_all_active_receipts: {_ms:.0f}ms ({len(result)} rows, completed={include_completed})")
            self._connection_error = None
            return result
        except (OperationalError, DatabaseError) as e:
            self._connection_error = "Cannot connect to database. Please check your network/VPN connection."
            logger.error(f"Database connection error in bulk load: {e}")
            return None
        except Exception as e:
            self._connection_error = f"Database error: {str(e)}"
            logger.error(f"Error in bulk load: {e}")
            return None
    
    def _get_header_on_single_conn(self) -> Dict[str, Any]:
        """
        Run live_stats + ready_to_close on ONE connection (2 queries, 1 conn).
        Avoids pool contention — only 2 connections used total in bootstrap.
        """
        from .common import get_vietnam_today
        today = get_vietnam_today()
        
        stats_query = text("""
            SELECT 
                (SELECT COUNT(*) FROM manufacturing_orders 
                 WHERE delete_flag = 0 AND status = 'IN_PROGRESS') as in_progress,
                (SELECT COUNT(*) FROM production_receipts 
                 WHERE DATE(receipt_date) = :today) as today_count
        """)
        
        ready_query = text("""
            SELECT
                mo.id,
                mo.order_no,
                mo.produced_qty,
                mo.planned_qty,
                mo.uom,
                p.name AS product_name,
                COALESCE(pr_stats.pending_count, 0) AS pending_count,
                COALESCE(pr_stats.receipt_count, 0) AS receipt_count,
                CASE 
                    WHEN COALESCE(pr_stats.pending_count, 0) = 0 
                         AND COALESCE(pr_stats.receipt_count, 0) > 0
                    THEN 'READY'
                    ELSE 'BLOCKED'
                END AS close_status
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    COUNT(*) AS receipt_count,
                    SUM(CASE WHEN quality_status = 'PENDING' THEN 1 ELSE 0 END) AS pending_count
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) pr_stats ON mo.id = pr_stats.manufacturing_order_id
            WHERE mo.status = 'IN_PROGRESS' 
                AND mo.delete_flag = 0
                AND mo.produced_qty >= mo.planned_qty
            ORDER BY mo.order_no
        """)
        
        try:
            import time as _t; _t0 = _t.perf_counter()
            
            # Single connection for both queries — no pool round-trip for 2nd query
            with self.engine.connect() as conn:
                stats_result = conn.execute(stats_query, {'today': today})
                stats_row = stats_result.fetchone()
                
                ready_result = pd.read_sql(ready_query, conn)
            
            _ms = (_t.perf_counter() - _t0) * 1000
            logger.info(f"[PERF] _get_header_on_single_conn: {_ms:.0f}ms (stats+ready, 1 conn)")
            
            # Parse stats
            live_stats = {
                'in_progress': int(stats_row[0]) if stats_row else 0,
                'today_count': int(stats_row[1]) if stats_row else 0,
            }
            
            # Parse ready-to-close
            if ready_result.empty:
                ready_info = {'ready_count': 0, 'blocked_count': 0, 'ready_orders': [], 'blocked_orders': []}
            else:
                ready = ready_result[ready_result['close_status'] == 'READY']
                blocked = ready_result[ready_result['close_status'] == 'BLOCKED']
                ready_info = {
                    'ready_count': len(ready),
                    'blocked_count': len(blocked),
                    'ready_orders': ready.to_dict('records') if not ready.empty else [],
                    'blocked_orders': blocked.to_dict('records') if not blocked.empty else [],
                }
            
            live_stats['ready_to_close'] = ready_info['ready_count']
            
            return {
                'live_stats': live_stats,
                'ready_to_close': ready_info,
            }
            
        except Exception as e:
            logger.error(f"Error getting header data: {e}")
            return {
                'live_stats': {'in_progress': 0, 'today_count': 0, 'ready_to_close': 0},
                'ready_to_close': {'ready_count': 0, 'blocked_count': 0, 'ready_orders': [], 'blocked_orders': []},
            }
    
    # ==================== Parallel Bootstrap ====================
    
    def bootstrap_all(self, include_completed: bool = False) -> Dict[str, Any]:
        """
        Load ALL page data in 2 parallel threads, 2 connections max.
        
        Thread 1: get_all_active_receipts      ~236ms ─┐ 1 conn
        Thread 2: _get_header_on_single_conn   ~300ms ─┘ 1 conn (2 queries reuse)
                                                         ─────────
                                          max(236, 300) ≈ 300ms total
        """
        from concurrent.futures import ThreadPoolExecutor
        import time as _t
        
        _t0 = _t.perf_counter()
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_receipts = executor.submit(
                self.get_all_active_receipts, include_completed
            )
            fut_header = executor.submit(self._get_header_on_single_conn)
            
            try:
                receipts = fut_receipts.result(timeout=30)
            except Exception as e:
                logger.error(f"Bootstrap receipts failed: {e}")
                receipts = None
            
            try:
                header = fut_header.result(timeout=30)
            except Exception as e:
                logger.error(f"Bootstrap header failed: {e}")
                header = {
                    'live_stats': {'in_progress': 0, 'today_count': 0, 'ready_to_close': 0},
                    'ready_to_close': {'ready_count': 0, 'blocked_count': 0, 'ready_orders': [], 'blocked_orders': []},
                }
        
        connection_error = None
        if receipts is None:
            connection_error = self._connection_error or "Cannot connect to database"
        
        _ms = (_t.perf_counter() - _t0) * 1000
        n_rows = len(receipts) if receipts is not None else 0
        logger.info(f"[PERF] bootstrap_all: {_ms:.0f}ms total (2 threads, 2 conns, {n_rows} receipts)")
        
        return {
            'receipts': receipts,
            'header': header,
            'connection_error': connection_error,
        }