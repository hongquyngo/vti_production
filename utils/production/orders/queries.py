# utils/production/orders/queries.py
"""
Database queries for Orders domain
All SQL queries are centralized here for easy maintenance

Version: 1.3.0
Changes:
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
                   status: Optional[str] = None,
                   order_type: Optional[str] = None,
                   priority: Optional[str] = None,
                   from_date: Optional[date] = None,
                   to_date: Optional[date] = None,
                   search: Optional[str] = None,
                   page: int = 1, 
                   page_size: int = 20) -> Optional[pd.DataFrame]:
        """
        Get production orders with filters and pagination
        
        Args:
            status: Filter by order status
            order_type: Filter by BOM type (CUTTING, REPACKING, etc.)
            priority: Filter by priority level
            from_date: Filter orders from this date
            to_date: Filter orders to this date
            search: Search in order_no, product name
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            DataFrame with order list
        """
        query = """
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
                br.brand_name,
                w1.name as warehouse_name,
                w2.name as target_warehouse_name,
                o.created_date,
                o.created_by,
                CONCAT(e.first_name, ' ', e.last_name) as created_by_name
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
        
        if status:
            query += " AND o.status = %s"
            params.append(status)
        
        if order_type:
            query += " AND b.bom_type = %s"
            params.append(order_type)
        
        if priority:
            query += " AND o.priority = %s"
            params.append(priority)
        
        if from_date:
            query += " AND DATE(o.order_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(o.order_date) <= %s"
            params.append(to_date)
        
        if search:
            query += """
                AND (
                    o.order_no LIKE %s 
                    OR p.name LIKE %s 
                    OR p.pt_code LIKE %s
                    OR p.package_size LIKE %s
                    OR p.legacy_pt_code LIKE %s
                    OR b.bom_name LIKE %s
                    OR b.bom_code LIKE %s
                    OR br.brand_name LIKE %s
                    OR o.notes LIKE %s
                    OR CONCAT(e.first_name, ' ', e.last_name) LIKE %s
                )
            """
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 10)
        
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
                        status: Optional[str] = None,
                        order_type: Optional[str] = None,
                        priority: Optional[str] = None,
                        from_date: Optional[date] = None,
                        to_date: Optional[date] = None,
                        search: Optional[str] = None) -> int:
        """Get total count of orders matching filters"""
        query = """
            SELECT COUNT(*) as total
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN brands br ON p.brand_id = br.id
            LEFT JOIN users u ON o.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE o.delete_flag = 0
        """
        
        params = []
        
        if status:
            query += " AND o.status = %s"
            params.append(status)
        
        if order_type:
            query += " AND b.bom_type = %s"
            params.append(order_type)
        
        if priority:
            query += " AND o.priority = %s"
            params.append(priority)
        
        if from_date:
            query += " AND DATE(o.order_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(o.order_date) <= %s"
            params.append(to_date)
        
        if search:
            query += """
                AND (
                    o.order_no LIKE %s 
                    OR p.name LIKE %s 
                    OR p.pt_code LIKE %s
                    OR p.package_size LIKE %s
                    OR p.legacy_pt_code LIKE %s
                    OR b.bom_name LIKE %s
                    OR b.bom_code LIKE %s
                    OR br.brand_name LIKE %s
                    OR o.notes LIKE %s
                    OR CONCAT(e.first_name, ' ', e.last_name) LIKE %s
                )
            """
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 10)
        
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
        """Get dynamic filter options from database"""
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
                'statuses': ['All'] + statuses,
                'order_types': ['All'] + types,
                'priorities': ['All'] + priorities
            }
        except Exception as e:
            logger.error(f"Error getting filter options: {e}")
            return {
                'statuses': ['All', 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
                'order_types': ['All', 'CUTTING', 'REPACKING', 'KITTING'],
                'priorities': ['All', 'LOW', 'NORMAL', 'HIGH', 'URGENT']
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