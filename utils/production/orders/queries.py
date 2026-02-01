# utils/production/orders/queries.py
"""
Database queries for Orders domain
All SQL queries are centralized here for easy maintenance

Version: 1.5.0
Changes:
- v1.5.0: Advanced multiselect filter support
          + get_orders() and get_orders_count() accept list parameters
          + Added product_ids, bom_ids, brand_ids, warehouse_ids filters
          + Added order_nos for text search
          + Added get_search_filter_options() for multiselect options
- v1.4.0: Added BOM conflict detection for Product-first selection flow
          + get_products_with_active_boms() - Products with BOM count
          + get_boms_by_product() - BOMs for specific product
          + check_product_bom_conflict() - Check if product has multiple active BOMs
          + get_orders_with_bom_conflicts() - Orders with BOM conflicts
          + get_bom_conflict_summary() - Conflict metrics for dashboard
          + Modified get_orders() to include bom_conflict_count column
- v1.3.0: Added get_alternative_materials() and check_material_availability_with_alternatives()
          for checking alternative materials availability when primary is PARTIAL/INSUFFICIENT
- v1.2.0: Expanded search to include package_size, legacy_pt_code, bom_name, 
          bom_code, brand_name, notes, creator_name
- v1.1.0: Added connection check method
- v1.0.0: Better error handling to distinguish connection errors from no data
"""

import logging
from datetime import date
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, DatabaseError

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


class OrderQueries:
    """Database queries for Order management"""
    
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
    
    # ==================== Order Queries ====================
    
    def get_orders(self, 
                   status: Optional[List[str]] = None,
                   order_type: Optional[List[str]] = None,
                   priority: Optional[List[str]] = None,
                   product_ids: Optional[List[int]] = None,
                   bom_ids: Optional[List[int]] = None,
                   brand_ids: Optional[List[int]] = None,
                   source_warehouse_ids: Optional[List[int]] = None,
                   target_warehouse_ids: Optional[List[int]] = None,
                   order_nos: Optional[List[str]] = None,
                   from_date: Optional[date] = None,
                   to_date: Optional[date] = None,
                   date_type: str = 'scheduled',
                   conflicts_only: bool = False,
                   conflict_check_active_only: bool = True,
                   page: int = 1, 
                   page_size: int = 20) -> Optional[pd.DataFrame]:
        """
        Get production orders with filters and pagination
        
        Args:
            status: List of statuses to filter (e.g., ['DRAFT', 'CONFIRMED'])
            order_type: List of BOM types (e.g., ['CUTTING', 'REPACKING'])
            priority: List of priority levels
            product_ids: List of product IDs to filter
            bom_ids: List of BOM IDs to filter
            brand_ids: List of brand IDs to filter
            source_warehouse_ids: List of source warehouse IDs
            target_warehouse_ids: List of target warehouse IDs
            order_nos: List of order numbers to filter
            from_date: Filter orders from this date
            to_date: Filter orders to this date
            date_type: 'scheduled' to filter by scheduled_date, 'order' to filter by order_date
            conflicts_only: If True, only return orders with BOM conflicts
            conflict_check_active_only: If True, count only active BOMs for conflict
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            DataFrame with order list including bom_conflict_count
        """
        # Subquery for counting BOMs per product
        if conflict_check_active_only:
            bom_count_condition = "AND bh.status = 'ACTIVE'"
        else:
            bom_count_condition = ""
        
        query = f"""
            SELECT 
                o.id,
                o.order_no,
                o.order_date,
                o.scheduled_date,
                o.completion_date,
                o.status,
                o.priority,
                o.planned_qty,
                o.produced_qty,
                o.uom,
                o.product_id,
                o.bom_header_id,
                o.warehouse_id,
                o.target_warehouse_id,
                o.notes,
                p.pt_code,
                p.name as product_name,
                p.package_size,
                p.legacy_pt_code,
                b.bom_type,
                b.bom_name,
                b.bom_code,
                b.status as bom_status,
                br.brand_name,
                w1.name as warehouse_name,
                w2.name as target_warehouse_name,
                o.created_date,
                o.created_by,
                CONCAT(e.first_name, ' ', e.last_name) as created_by_name,
                (
                    SELECT COUNT(*) 
                    FROM bom_headers bh 
                    WHERE bh.product_id = o.product_id 
                    AND bh.delete_flag = 0
                    {bom_count_condition}
                ) as bom_conflict_count
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN brands br ON p.brand_id = br.id
            JOIN warehouses w1 ON o.warehouse_id = w1.id
            JOIN warehouses w2 ON o.target_warehouse_id = w2.id
            LEFT JOIN users u ON o.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE o.delete_flag = 0
        """
        
        params = []
        
        # Status filter (list)
        if status and len(status) > 0:
            placeholders = ', '.join(['%s'] * len(status))
            query += f" AND o.status IN ({placeholders})"
            params.extend(status)
        
        # Order type filter (list)
        if order_type and len(order_type) > 0:
            placeholders = ', '.join(['%s'] * len(order_type))
            query += f" AND b.bom_type IN ({placeholders})"
            params.extend(order_type)
        
        # Priority filter (list)
        if priority and len(priority) > 0:
            placeholders = ', '.join(['%s'] * len(priority))
            query += f" AND o.priority IN ({placeholders})"
            params.extend(priority)
        
        # Product IDs filter
        if product_ids and len(product_ids) > 0:
            placeholders = ', '.join(['%s'] * len(product_ids))
            query += f" AND o.product_id IN ({placeholders})"
            params.extend(product_ids)
        
        # BOM IDs filter
        if bom_ids and len(bom_ids) > 0:
            placeholders = ', '.join(['%s'] * len(bom_ids))
            query += f" AND o.bom_header_id IN ({placeholders})"
            params.extend(bom_ids)
        
        # Brand IDs filter
        if brand_ids and len(brand_ids) > 0:
            placeholders = ', '.join(['%s'] * len(brand_ids))
            query += f" AND br.id IN ({placeholders})"
            params.extend(brand_ids)
        
        # Source warehouse IDs filter
        if source_warehouse_ids and len(source_warehouse_ids) > 0:
            placeholders = ', '.join(['%s'] * len(source_warehouse_ids))
            query += f" AND o.warehouse_id IN ({placeholders})"
            params.extend(source_warehouse_ids)
        
        # Target warehouse IDs filter
        if target_warehouse_ids and len(target_warehouse_ids) > 0:
            placeholders = ', '.join(['%s'] * len(target_warehouse_ids))
            query += f" AND o.target_warehouse_id IN ({placeholders})"
            params.extend(target_warehouse_ids)
        
        # Order numbers filter (list)
        if order_nos and len(order_nos) > 0:
            placeholders = ", ".join(["%s"] * len(order_nos))
            query += f" AND o.order_no IN ({placeholders})"
            params.extend(order_nos)
        
        # Date filter - based on date_type
        date_column = "o.scheduled_date" if date_type == 'scheduled' else "o.order_date"
        
        if from_date:
            query += f" AND DATE({date_column}) >= %s"
            params.append(from_date)
        
        if to_date:
            query += f" AND DATE({date_column}) <= %s"
            params.append(to_date)
        
        # Filter for orders with BOM conflicts only
        if conflicts_only:
            query += f"""
                AND (
                    SELECT COUNT(*) 
                    FROM bom_headers bh 
                    WHERE bh.product_id = o.product_id 
                    AND bh.delete_flag = 0
                    {bom_count_condition}
                ) > 1
            """
        
        query += " ORDER BY o.created_date DESC"
        
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
            logger.error(f"Database connection error getting orders: {e}")
            return None
        except Exception as e:
            self._connection_error = f"Database error: {str(e)}"
            logger.error(f"Error getting orders: {e}")
            return None
    
    def get_orders_count(self,
                        status: Optional[List[str]] = None,
                        order_type: Optional[List[str]] = None,
                        priority: Optional[List[str]] = None,
                        product_ids: Optional[List[int]] = None,
                        bom_ids: Optional[List[int]] = None,
                        brand_ids: Optional[List[int]] = None,
                        source_warehouse_ids: Optional[List[int]] = None,
                        target_warehouse_ids: Optional[List[int]] = None,
                        order_nos: Optional[List[str]] = None,
                        from_date: Optional[date] = None,
                        to_date: Optional[date] = None,
                        date_type: str = 'scheduled',
                        conflicts_only: bool = False,
                        conflict_check_active_only: bool = True) -> int:
        """
        Get total count of orders matching filters
        
        Args:
            status: List of statuses to filter
            order_type: List of BOM types
            priority: List of priority levels
            product_ids: List of product IDs
            bom_ids: List of BOM IDs
            brand_ids: List of brand IDs
            source_warehouse_ids: List of source warehouse IDs
            target_warehouse_ids: List of target warehouse IDs
            order_nos: List of order numbers to filter
            from_date: Filter from date
            to_date: Filter to date
            date_type: 'scheduled' or 'order'
            conflicts_only: Show only orders with BOM conflicts
            conflict_check_active_only: Count only active BOMs for conflict
        """
        # Condition for counting BOMs
        if conflict_check_active_only:
            bom_count_condition = "AND bh.status = 'ACTIVE'"
        else:
            bom_count_condition = ""
        
        query = """
            SELECT COUNT(*) as total
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN brands br ON p.brand_id = br.id
            WHERE o.delete_flag = 0
        """
        
        params = []
        
        # Status filter (list)
        if status and len(status) > 0:
            placeholders = ', '.join(['%s'] * len(status))
            query += f" AND o.status IN ({placeholders})"
            params.extend(status)
        
        # Order type filter (list)
        if order_type and len(order_type) > 0:
            placeholders = ', '.join(['%s'] * len(order_type))
            query += f" AND b.bom_type IN ({placeholders})"
            params.extend(order_type)
        
        # Priority filter (list)
        if priority and len(priority) > 0:
            placeholders = ', '.join(['%s'] * len(priority))
            query += f" AND o.priority IN ({placeholders})"
            params.extend(priority)
        
        # Product IDs filter
        if product_ids and len(product_ids) > 0:
            placeholders = ', '.join(['%s'] * len(product_ids))
            query += f" AND o.product_id IN ({placeholders})"
            params.extend(product_ids)
        
        # BOM IDs filter
        if bom_ids and len(bom_ids) > 0:
            placeholders = ', '.join(['%s'] * len(bom_ids))
            query += f" AND o.bom_header_id IN ({placeholders})"
            params.extend(bom_ids)
        
        # Brand IDs filter
        if brand_ids and len(brand_ids) > 0:
            placeholders = ', '.join(['%s'] * len(brand_ids))
            query += f" AND br.id IN ({placeholders})"
            params.extend(brand_ids)
        
        # Source warehouse IDs filter
        if source_warehouse_ids and len(source_warehouse_ids) > 0:
            placeholders = ', '.join(['%s'] * len(source_warehouse_ids))
            query += f" AND o.warehouse_id IN ({placeholders})"
            params.extend(source_warehouse_ids)
        
        # Target warehouse IDs filter
        if target_warehouse_ids and len(target_warehouse_ids) > 0:
            placeholders = ', '.join(['%s'] * len(target_warehouse_ids))
            query += f" AND o.target_warehouse_id IN ({placeholders})"
            params.extend(target_warehouse_ids)
        
        # Order numbers filter (list)
        if order_nos and len(order_nos) > 0:
            placeholders = ", ".join(["%s"] * len(order_nos))
            query += f" AND o.order_no IN ({placeholders})"
            params.extend(order_nos)
        
        # Date filter - based on date_type
        date_column = "o.scheduled_date" if date_type == 'scheduled' else "o.order_date"
        
        if from_date:
            query += f" AND DATE({date_column}) >= %s"
            params.append(from_date)
        
        if to_date:
            query += f" AND DATE({date_column}) <= %s"
            params.append(to_date)
        
        # Filter for orders with BOM conflicts only
        if conflicts_only:
            query += f"""
                AND (
                    SELECT COUNT(*) 
                    FROM bom_headers bh 
                    WHERE bh.product_id = o.product_id 
                    AND bh.delete_flag = 0
                    {bom_count_condition}
                ) > 1
            """
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return int(result['total'].iloc[0])
        except Exception as e:
            logger.error(f"Error getting orders count: {e}")
            return 0
    
    def get_order_details(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information for a single order"""
        query = """
            SELECT 
                o.*,
                p.name as product_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                p.description as product_description,
                br.brand_name,
                b.bom_name,
                b.bom_type,
                b.output_qty as bom_output_qty,
                w1.name as warehouse_name,
                w2.name as target_warehouse_name,
                CONCAT(e.first_name, ' ', e.last_name) as created_by_name
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN brands br ON p.brand_id = br.id
            JOIN warehouses w1 ON o.warehouse_id = w1.id
            JOIN warehouses w2 ON o.target_warehouse_id = w2.id
            LEFT JOIN users u ON o.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE o.id = %s AND o.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting order details for {order_id}: {e}")
            return None
    
    def get_order_materials(self, order_id: int) -> pd.DataFrame:
        """Get materials required for an order"""
        query = """
            SELECT 
                m.id,
                m.material_id,
                p.name as material_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                m.required_qty,
                COALESCE(m.issued_qty, 0) as issued_qty,
                m.uom,
                m.status,
                (m.required_qty - COALESCE(m.issued_qty, 0)) as pending_qty
            FROM manufacturing_order_materials m
            JOIN products p ON m.material_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE m.manufacturing_order_id = %s
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting order materials for {order_id}: {e}")
            return pd.DataFrame()
    
    # ==================== BOM Queries ====================
    
    def get_active_boms(self) -> pd.DataFrame:
        """Get all active BOMs for order creation"""
        query = """
            SELECT 
                b.id,
                b.bom_name,
                b.bom_type,
                b.output_qty,
                b.uom,
                b.product_id,
                p.name as product_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name
            FROM bom_headers b
            JOIN products p ON b.product_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE b.delete_flag = 0
                AND b.status = 'ACTIVE'
            ORDER BY b.bom_name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting active BOMs: {e}")
            return pd.DataFrame()
    
    def get_products_with_active_boms(self) -> pd.DataFrame:
        """
        Get products that have at least one active BOM
        Includes count of active BOMs and total BOMs per product
        
        Returns:
            DataFrame with product info and BOM counts
        """
        query = """
            SELECT 
                p.id as product_id,
                p.pt_code,
                p.name as product_name,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                COUNT(CASE WHEN b.status = 'ACTIVE' THEN 1 END) as active_bom_count,
                COUNT(*) as total_bom_count
            FROM products p
            JOIN brands br ON p.brand_id = br.id
            JOIN bom_headers b ON b.product_id = p.id AND b.delete_flag = 0
            WHERE p.delete_flag = 0
            GROUP BY p.id, p.pt_code, p.name, p.package_size, p.legacy_pt_code, br.brand_name
            HAVING COUNT(CASE WHEN b.status = 'ACTIVE' THEN 1 END) >= 1
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting products with active BOMs: {e}")
            return pd.DataFrame()
    
    def get_boms_by_product(self, product_id: int, active_only: bool = True) -> pd.DataFrame:
        """
        Get BOMs for a specific product
        
        Args:
            product_id: Product ID
            active_only: If True, return only active BOMs
            
        Returns:
            DataFrame with BOMs for the product
        """
        status_condition = "AND b.status = 'ACTIVE'" if active_only else ""
        
        query = f"""
            SELECT 
                b.id,
                b.bom_code,
                b.bom_name,
                b.bom_type,
                b.output_qty,
                b.uom,
                b.status,
                b.product_id,
                p.name as product_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                b.created_date
            FROM bom_headers b
            JOIN products p ON b.product_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE b.product_id = %s 
                AND b.delete_flag = 0
                {status_condition}
            ORDER BY b.status DESC, b.bom_name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id,))
        except Exception as e:
            logger.error(f"Error getting BOMs for product {product_id}: {e}")
            return pd.DataFrame()
    
    def check_product_bom_conflict(self, product_id: int, 
                                   active_only: bool = True) -> Dict[str, Any]:
        """
        Check if a product has BOM conflict (multiple BOMs)
        
        Args:
            product_id: Product ID to check
            active_only: If True, count only active BOMs
            
        Returns:
            Dictionary with conflict info:
                - has_conflict: bool
                - bom_count: int
                - message: str
        """
        status_condition = "AND status = 'ACTIVE'" if active_only else ""
        
        query = f"""
            SELECT COUNT(*) as bom_count
            FROM bom_headers
            WHERE product_id = %s 
                AND delete_flag = 0
                {status_condition}
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(product_id,))
            bom_count = int(result['bom_count'].iloc[0]) if not result.empty else 0
            
            has_conflict = bom_count > 1
            
            if has_conflict:
                conflict_type = "active" if active_only else "total"
                message = f"⚠️ This product has {bom_count} {conflict_type} BOMs. Please resolve the conflict before creating an order."
            else:
                message = ""
            
            return {
                'has_conflict': has_conflict,
                'bom_count': bom_count,
                'message': message
            }
            
        except Exception as e:
            logger.error(f"Error checking BOM conflict for product {product_id}: {e}")
            return {
                'has_conflict': False,
                'bom_count': 0,
                'message': f"Error checking conflict: {str(e)}"
            }
    
    def get_bom_conflict_summary(self, 
                                 active_only: bool = True,
                                 from_date: Optional[date] = None,
                                 to_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Get summary of BOM conflicts in orders
        
        Args:
            active_only: If True, count only active BOMs for conflict detection
            from_date: Filter orders from this date
            to_date: Filter orders to this date
            
        Returns:
            Dictionary with conflict summary:
                - total_conflict_orders: int
                - affected_products: int
                - conflict_by_status: dict
        """
        if active_only:
            bom_count_condition = "AND bh.status = 'ACTIVE'"
        else:
            bom_count_condition = ""
        
        # Build date filter
        date_filter = ""
        params = []
        if from_date:
            date_filter += " AND DATE(o.order_date) >= %s"
            params.append(from_date)
        if to_date:
            date_filter += " AND DATE(o.order_date) <= %s"
            params.append(to_date)
        
        query = f"""
            SELECT 
                COUNT(*) as total_conflict_orders,
                COUNT(DISTINCT o.product_id) as affected_products,
                SUM(CASE WHEN o.status = 'DRAFT' THEN 1 ELSE 0 END) as draft_conflicts,
                SUM(CASE WHEN o.status = 'CONFIRMED' THEN 1 ELSE 0 END) as confirmed_conflicts,
                SUM(CASE WHEN o.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress_conflicts,
                SUM(CASE WHEN o.status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_conflicts
            FROM manufacturing_orders o
            WHERE o.delete_flag = 0
                AND (
                    SELECT COUNT(*) 
                    FROM bom_headers bh 
                    WHERE bh.product_id = o.product_id 
                    AND bh.delete_flag = 0
                    {bom_count_condition}
                ) > 1
                {date_filter}
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            
            if result.empty:
                return self._empty_conflict_summary()
            
            row = result.iloc[0]
            return {
                'total_conflict_orders': int(row['total_conflict_orders'] or 0),
                'affected_products': int(row['affected_products'] or 0),
                'conflict_by_status': {
                    'DRAFT': int(row['draft_conflicts'] or 0),
                    'CONFIRMED': int(row['confirmed_conflicts'] or 0),
                    'IN_PROGRESS': int(row['in_progress_conflicts'] or 0),
                    'COMPLETED': int(row['completed_conflicts'] or 0)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting BOM conflict summary: {e}")
            return self._empty_conflict_summary()
    
    def _empty_conflict_summary(self) -> Dict[str, Any]:
        """Return empty conflict summary structure"""
        return {
            'total_conflict_orders': 0,
            'affected_products': 0,
            'conflict_by_status': {
                'DRAFT': 0,
                'CONFIRMED': 0,
                'IN_PROGRESS': 0,
                'COMPLETED': 0
            }
        }
    
    def get_bom_info(self, bom_id: int) -> Optional[Dict[str, Any]]:
        """Get BOM information by ID"""
        query = """
            SELECT 
                b.id,
                b.bom_name,
                b.bom_type,
                b.output_qty,
                b.uom,
                b.product_id,
                p.name as product_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name
            FROM bom_headers b
            JOIN products p ON b.product_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE b.id = %s AND b.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(bom_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting BOM info for {bom_id}: {e}")
            return None
    
    def get_bom_details(self, bom_id: int) -> pd.DataFrame:
        """Get BOM detail lines (materials)"""
        query = """
            SELECT 
                d.id as bom_detail_id,
                d.material_id,
                p.name as material_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                d.quantity,
                d.uom,
                d.scrap_rate,
                h.output_qty
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON d.material_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE h.id = %s
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(bom_id,))
        except Exception as e:
            logger.error(f"Error getting BOM details for {bom_id}: {e}")
            return pd.DataFrame()
    
    # ==================== Warehouse Queries ====================
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get all active warehouses"""
        query = """
            SELECT 
                id,
                name,
                address,
                company_id,
                manager_id
            FROM warehouses
            WHERE delete_flag = 0
            ORDER BY name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
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
    
    # ==================== Filter Options ====================
    
    def get_filter_options(self) -> Dict[str, List[str]]:
        """Get dynamic filter options from database (for multiselect)"""
        status_query = """
            SELECT DISTINCT status 
            FROM manufacturing_orders 
            WHERE delete_flag = 0 
            ORDER BY FIELD(status, 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')
        """
        
        type_query = """
            SELECT DISTINCT bh.bom_type 
            FROM manufacturing_orders mo
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            WHERE mo.delete_flag = 0
            ORDER BY bh.bom_type
        """
        
        priority_query = """
            SELECT DISTINCT priority 
            FROM manufacturing_orders 
            WHERE delete_flag = 0 
            ORDER BY FIELD(priority, 'LOW', 'NORMAL', 'HIGH', 'URGENT')
        """
        
        try:
            statuses = pd.read_sql(status_query, self.engine)['status'].tolist()
            types = pd.read_sql(type_query, self.engine)['bom_type'].tolist()
            priorities = pd.read_sql(priority_query, self.engine)['priority'].tolist()
            
            return {
                'statuses': statuses,
                'order_types': types,
                'priorities': priorities
            }
        except Exception as e:
            logger.error(f"Error getting filter options: {e}")
            return {
                'statuses': ['DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
                'order_types': ['CUTTING', 'REPACKING', 'KITTING'],
                'priorities': ['LOW', 'NORMAL', 'HIGH', 'URGENT']
            }
    
    def get_search_filter_options(self) -> Dict[str, pd.DataFrame]:
        """
        Get options for search multiselect filters
        Returns products, BOMs, brands, warehouses that exist in orders
        """
        # Products used in orders
        product_query = """
            SELECT DISTINCT 
                p.id,
                p.pt_code,
                p.name as product_name,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE mo.delete_flag = 0
            ORDER BY p.name
        """
        
        # BOMs used in orders
        bom_query = """
            SELECT DISTINCT 
                bh.id,
                bh.bom_code,
                bh.bom_name,
                bh.bom_type
            FROM manufacturing_orders mo
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            WHERE mo.delete_flag = 0
            ORDER BY bh.bom_name
        """
        
        # Brands from products in orders
        brand_query = """
            SELECT DISTINCT 
                br.id,
                br.brand_name
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            JOIN brands br ON p.brand_id = br.id
            WHERE mo.delete_flag = 0
            ORDER BY br.brand_name
        """
        
        # Source warehouses used in orders
        source_wh_query = """
            SELECT DISTINCT 
                w.id,
                w.name as warehouse_name
            FROM manufacturing_orders mo
            JOIN warehouses w ON mo.warehouse_id = w.id
            WHERE mo.delete_flag = 0
            ORDER BY w.name
        """
        
        # Target warehouses used in orders
        target_wh_query = """
            SELECT DISTINCT 
                w.id,
                w.name as warehouse_name
            FROM manufacturing_orders mo
            JOIN warehouses w ON mo.target_warehouse_id = w.id
            WHERE mo.delete_flag = 0
            ORDER BY w.name
        """
        
        # Order numbers (for multiselect filter)
        order_no_query = """
            SELECT DISTINCT order_no
            FROM manufacturing_orders
            WHERE delete_flag = 0
            ORDER BY order_no DESC
            LIMIT 500
        """
        
        try:
            return {
                'products': pd.read_sql(product_query, self.engine),
                'boms': pd.read_sql(bom_query, self.engine),
                'brands': pd.read_sql(brand_query, self.engine),
                'source_warehouses': pd.read_sql(source_wh_query, self.engine),
                'target_warehouses': pd.read_sql(target_wh_query, self.engine),
                'order_nos': pd.read_sql(order_no_query, self.engine),
            }
        except Exception as e:
            logger.error(f"Error getting search filter options: {e}")
            return {
                'products': pd.DataFrame(),
                'boms': pd.DataFrame(),
                'brands': pd.DataFrame(),
                'source_warehouses': pd.DataFrame(),
                'target_warehouses': pd.DataFrame(),
                'order_nos': pd.DataFrame(),
            }
    
    # ==================== Material Availability ====================
    
    def check_material_availability(self, bom_id: int, quantity: float, 
                                   warehouse_id: int) -> pd.DataFrame:
        """
        Check material availability for a BOM
        
        Args:
            bom_id: BOM header ID
            quantity: Planned production quantity
            warehouse_id: Source warehouse ID
            
        Returns:
            DataFrame with material availability status
        """
        query = """
            SELECT 
                d.id as bom_detail_id,
                d.material_id,
                p.name as material_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                d.quantity * %s / h.output_qty * (1 + d.scrap_rate/100) as required_qty,
                d.uom,
                COALESCE(SUM(ih.remain), 0) as available_qty,
                CASE 
                    WHEN COALESCE(SUM(ih.remain), 0) >= 
                         d.quantity * %s / h.output_qty * (1 + d.scrap_rate/100)
                    THEN 'SUFFICIENT'
                    WHEN COALESCE(SUM(ih.remain), 0) > 0
                    THEN 'PARTIAL'
                    ELSE 'INSUFFICIENT'
                END as availability_status
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON d.material_id = p.id
            JOIN brands br ON p.brand_id = br.id
            LEFT JOIN inventory_histories ih 
                ON ih.product_id = d.material_id 
                AND ih.warehouse_id = %s
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE h.id = %s
            GROUP BY d.id, d.material_id, p.name, p.pt_code, p.package_size, 
                     p.legacy_pt_code, br.brand_name,
                     d.quantity, d.uom, d.scrap_rate, h.output_qty
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, 
                             params=(quantity, quantity, warehouse_id, bom_id))
        except Exception as e:
            logger.error(f"Error checking material availability: {e}")
            return pd.DataFrame()
    
    def get_alternative_materials(self, bom_id: int, quantity: float,
                                  warehouse_id: int, 
                                  bom_detail_ids: List[int]) -> pd.DataFrame:
        """
        Get alternative materials for specified BOM details with availability check
        Uses bom_material_alternatives table structure
        
        Args:
            bom_id: BOM header ID
            quantity: Planned production quantity
            warehouse_id: Source warehouse ID
            bom_detail_ids: List of BOM detail IDs to get alternatives for
            
        Returns:
            DataFrame with alternative materials and their availability
        """
        if not bom_detail_ids:
            return pd.DataFrame()
        
        # Build query with proper parameter handling
        placeholders = ', '.join(['%s'] * len(bom_detail_ids))
        
        # Note: bom_material_alternatives has its own quantity, uom, scrap_rate
        # Formula: (planned_qty / output_qty) * alt.quantity * (1 + alt.scrap_rate/100)
        query = f"""
            SELECT 
                alt.bom_detail_id,
                alt.alternative_material_id as material_id,
                alt.priority as alt_priority,
                alt.quantity as alt_quantity,
                alt.scrap_rate as alt_scrap_rate,
                p.name as material_name,
                p.pt_code,
                p.package_size,
                p.legacy_pt_code,
                br.brand_name,
                alt.quantity * %s / h.output_qty * (1 + COALESCE(alt.scrap_rate, 0)/100) as required_qty,
                alt.uom,
                COALESCE(SUM(ih.remain), 0) as available_qty,
                CASE 
                    WHEN COALESCE(SUM(ih.remain), 0) >= 
                         alt.quantity * %s / h.output_qty * (1 + COALESCE(alt.scrap_rate, 0)/100)
                    THEN 'SUFFICIENT'
                    WHEN COALESCE(SUM(ih.remain), 0) > 0
                    THEN 'PARTIAL'
                    ELSE 'INSUFFICIENT'
                END as availability_status,
                'ALTERNATIVE' as material_type
            FROM bom_material_alternatives alt
            JOIN bom_details d ON alt.bom_detail_id = d.id
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON alt.alternative_material_id = p.id
            JOIN brands br ON p.brand_id = br.id
            LEFT JOIN inventory_histories ih 
                ON ih.product_id = alt.alternative_material_id 
                AND ih.warehouse_id = %s
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE h.id = %s
                AND alt.is_active = 1
                AND d.id IN ({placeholders})
            GROUP BY alt.bom_detail_id, alt.alternative_material_id, alt.priority, 
                     alt.quantity, alt.scrap_rate, alt.uom,
                     p.name, p.pt_code, p.package_size, 
                     p.legacy_pt_code, br.brand_name, h.output_qty
            ORDER BY alt.bom_detail_id, alt.priority
        """
        
        try:
            params = [quantity, quantity, warehouse_id, bom_id] + list(bom_detail_ids)
            return pd.read_sql(query, self.engine, params=tuple(params))
        except Exception as e:
            logger.error(f"Error getting alternative materials: {e}")
            return pd.DataFrame()
    
    def check_material_availability_with_alternatives(self, bom_id: int, 
                                                      quantity: float,
                                                      warehouse_id: int) -> Dict[str, Any]:
        """
        Check material availability including alternatives for PARTIAL/INSUFFICIENT items
        
        Args:
            bom_id: BOM header ID
            quantity: Planned production quantity
            warehouse_id: Source warehouse ID
            
        Returns:
            Dictionary containing:
                - primary: DataFrame with primary materials
                - alternatives: DataFrame with alternative materials (grouped by bom_detail_id)
                - summary: Dict with counts
        """
        # Step 1: Get primary materials
        primary_df = self.check_material_availability(bom_id, quantity, warehouse_id)
        
        if primary_df.empty:
            return {
                'primary': primary_df,
                'alternatives': pd.DataFrame(),
                'summary': {
                    'total': 0,
                    'sufficient': 0,
                    'partial': 0,
                    'insufficient': 0,
                    'has_alternatives': 0,
                    'has_sufficient_alternatives': 0
                }
            }
        
        # Step 2: Find materials that need alternatives (PARTIAL or INSUFFICIENT)
        needs_alternatives = primary_df[
            primary_df['availability_status'].isin(['PARTIAL', 'INSUFFICIENT'])
        ]
        
        alternatives_df = pd.DataFrame()
        
        if not needs_alternatives.empty:
            bom_detail_ids = needs_alternatives['bom_detail_id'].tolist()
            alternatives_df = self.get_alternative_materials(
                bom_id, quantity, warehouse_id, bom_detail_ids
            )
        
        # Step 3: Calculate summary
        total = len(primary_df)
        sufficient = len(primary_df[primary_df['availability_status'] == 'SUFFICIENT'])
        partial = len(primary_df[primary_df['availability_status'] == 'PARTIAL'])
        insufficient = len(primary_df[primary_df['availability_status'] == 'INSUFFICIENT'])
        
        # Count how many items have sufficient alternatives
        has_sufficient_alt = 0
        if not alternatives_df.empty:
            sufficient_alts = alternatives_df[alternatives_df['availability_status'] == 'SUFFICIENT']
            has_sufficient_alt = sufficient_alts['bom_detail_id'].nunique()
        
        return {
            'primary': primary_df,
            'alternatives': alternatives_df,
            'summary': {
                'total': total,
                'sufficient': sufficient,
                'partial': partial,
                'insufficient': insufficient,
                'has_alternatives': len(alternatives_df['bom_detail_id'].unique()) if not alternatives_df.empty else 0,
                'has_sufficient_alternatives': has_sufficient_alt
            }
        }
    
    # ==================== Dashboard Metrics ====================
    
    def get_order_metrics(self, from_date: Optional[date] = None,
                         to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get order metrics for dashboard"""
        base_query = """
            SELECT 
                COUNT(*) as total_orders,
                SUM(CASE WHEN status = 'DRAFT' THEN 1 ELSE 0 END) as draft_count,
                SUM(CASE WHEN status = 'CONFIRMED' THEN 1 ELSE 0 END) as confirmed_count,
                SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress_count,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_count,
                SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_count,
                SUM(CASE WHEN priority = 'URGENT' THEN 1 ELSE 0 END) as urgent_count,
                SUM(CASE WHEN priority = 'HIGH' THEN 1 ELSE 0 END) as high_priority_count
            FROM manufacturing_orders
            WHERE delete_flag = 0
        """
        
        params = []
        
        if from_date:
            base_query += " AND DATE(order_date) >= %s"
            params.append(from_date)
        
        if to_date:
            base_query += " AND DATE(order_date) <= %s"
            params.append(to_date)
        
        try:
            result = pd.read_sql(base_query, self.engine, 
                               params=tuple(params) if params else None)
            
            if result.empty:
                return self._empty_metrics()
            
            row = result.iloc[0]
            total = int(row['total_orders'])
            completed = int(row['completed_count'])
            
            return {
                'total_orders': total,
                'draft_count': int(row['draft_count']),
                'confirmed_count': int(row['confirmed_count']),
                'in_progress_count': int(row['in_progress_count']),
                'completed_count': completed,
                'cancelled_count': int(row['cancelled_count']),
                'urgent_count': int(row['urgent_count']),
                'high_priority_count': int(row['high_priority_count']),
                'active_count': int(row['in_progress_count']) + int(row['confirmed_count']),
                'completion_rate': round((completed / total * 100), 1) if total > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting order metrics: {e}")
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
            'urgent_count': 0,
            'high_priority_count': 0,
            'active_count': 0,
            'completion_rate': 0
        }