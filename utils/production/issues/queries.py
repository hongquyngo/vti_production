# utils/production/issues/queries.py
"""
Database queries for Issues domain
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


class IssueQueries:
    """Database queries for Material Issue management"""
    
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
    
    # ==================== Issue History Queries ====================
    
    def get_issues(self,
                   from_date: Optional[date] = None,
                   to_date: Optional[date] = None,
                   search: Optional[str] = None,
                   status: Optional[str] = None,
                   page: int = 1,
                   page_size: int = 20) -> pd.DataFrame:
        """
        Get material issues with filters and pagination
        
        Args:
            from_date: Filter from date
            to_date: Filter to date
            search: Search by order number, product code, name, package size, legacy code
            status: Filter by status
            page: Page number (1-indexed)
            page_size: Records per page
            
        Returns:
            DataFrame with issue list
        """
        query = """
            SELECT 
                mi.id,
                mi.issue_no,
                mi.issue_date,
                mi.status,
                mi.notes,
                mi.created_date,
                mo.order_no,
                mo.id as order_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                w.name as warehouse_name,
                CONCAT(e_issued.first_name, ' ', e_issued.last_name) as issued_by_name,
                CONCAT(e_received.first_name, ' ', e_received.last_name) as received_by_name,
                (SELECT COUNT(*) FROM material_issue_details WHERE material_issue_id = mi.id) as item_count
            FROM material_issues mi
            JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            JOIN warehouses w ON mi.warehouse_id = w.id
            LEFT JOIN employees e_issued ON mi.issued_by = e_issued.id
            LEFT JOIN employees e_received ON mi.received_by = e_received.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(mi.issue_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mi.issue_date) <= %s"
            params.append(to_date)
        
        if search:
            query += """ AND (
                mo.order_no LIKE %s
                OR p.pt_code LIKE %s 
                OR p.legacy_pt_code LIKE %s 
                OR p.name LIKE %s 
                OR p.package_size LIKE %s
            )"""
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])
        
        if status:
            query += " AND mi.status = %s"
            params.append(status)
        
        query += " ORDER BY mi.created_date DESC"
        
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
            logger.error(f"Database connection error getting issues: {e}")
            return None
        except Exception as e:
            self._connection_error = f"Database error: {str(e)}"
            logger.error(f"Error getting issues: {e}")
            return None
    
    def get_issues_count(self,
                        from_date: Optional[date] = None,
                        to_date: Optional[date] = None,
                        search: Optional[str] = None,
                        status: Optional[str] = None) -> int:
        """Get total count of issues matching filters"""
        query = """
            SELECT COUNT(*) as total
            FROM material_issues mi
            JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(mi.issue_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(mi.issue_date) <= %s"
            params.append(to_date)
        
        if search:
            query += """ AND (
                mo.order_no LIKE %s
                OR p.pt_code LIKE %s 
                OR p.legacy_pt_code LIKE %s 
                OR p.name LIKE %s 
                OR p.package_size LIKE %s
            )"""
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])
        
        if status:
            query += " AND mi.status = %s"
            params.append(status)
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return int(result['total'].iloc[0])
        except Exception as e:
            logger.error(f"Error getting issues count: {e}")
            return 0
    
    def get_issue_details(self, issue_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information for a single issue"""
        query = """
            SELECT 
                mi.id,
                mi.issue_no,
                mi.issue_date,
                mi.status,
                mi.notes,
                mi.created_date,
                mi.warehouse_id,
                mo.order_no,
                mo.id as order_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                mo.planned_qty,
                mo.uom as product_uom,
                w.name as warehouse_name,
                mi.issued_by as issued_by_id,
                CONCAT(e_issued.first_name, ' ', e_issued.last_name) as issued_by_name,
                mi.received_by as received_by_id,
                CONCAT(e_received.first_name, ' ', e_received.last_name) as received_by_name,
                mi.created_by as created_by_id,
                CONCAT(e_created.first_name, ' ', e_created.last_name) as created_by_name
            FROM material_issues mi
            JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            JOIN warehouses w ON mi.warehouse_id = w.id
            LEFT JOIN employees e_issued ON mi.issued_by = e_issued.id
            LEFT JOIN employees e_received ON mi.received_by = e_received.id
            LEFT JOIN users u ON mi.created_by = u.id
            LEFT JOIN employees e_created ON u.employee_id = e_created.id
            WHERE mi.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(issue_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting issue details for {issue_id}: {e}")
            return None
    
    def get_issue_materials(self, issue_id: int) -> pd.DataFrame:
        """Get materials for an issue"""
        query = """
            SELECT 
                mid.id,
                mid.material_id,
                p.name as material_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                mid.batch_no,
                mid.quantity,
                mid.uom,
                mid.expired_date,
                COALESCE(mid.is_alternative, 0) as is_alternative,
                mid.original_material_id,
                op.name as original_material_name,
                op.legacy_pt_code as original_legacy_pt_code
            FROM material_issue_details mid
            JOIN products p ON mid.material_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            LEFT JOIN products op ON mid.original_material_id = op.id
            WHERE mid.material_issue_id = %s
            ORDER BY p.name, mid.batch_no
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(issue_id,))
        except Exception as e:
            logger.error(f"Error getting issue materials for {issue_id}: {e}")
            return pd.DataFrame()
    
    # ==================== Issuable Orders Queries ====================
    
    def get_issuable_orders(self) -> pd.DataFrame:
        """Get orders that can have materials issued (including IN_PROGRESS for additional issues)"""
        query = """
            SELECT 
                mo.id,
                mo.order_no,
                mo.order_date,
                mo.scheduled_date,
                mo.status,
                mo.priority,
                mo.planned_qty,
                mo.uom,
                mo.warehouse_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                b.bom_name,
                b.bom_type,
                w.name as warehouse_name,
                (SELECT COUNT(*) FROM manufacturing_order_materials 
                 WHERE manufacturing_order_id = mo.id AND status = 'PENDING') as pending_materials
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            JOIN bom_headers b ON mo.bom_header_id = b.id
            JOIN warehouses w ON mo.warehouse_id = w.id
            WHERE mo.delete_flag = 0
                AND mo.status IN ('DRAFT', 'CONFIRMED', 'IN_PROGRESS')
                AND EXISTS (
                    SELECT 1 FROM manufacturing_order_materials mom
                    WHERE mom.manufacturing_order_id = mo.id
                    AND mom.required_qty > COALESCE(mom.issued_qty, 0)
                )
            ORDER BY 
                FIELD(mo.priority, 'URGENT', 'HIGH', 'NORMAL', 'LOW'),
                mo.scheduled_date ASC
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting issuable orders: {e}")
            return pd.DataFrame()
    
    def get_order_for_issue(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get order information for issuing materials"""
        query = """
            SELECT 
                mo.id,
                mo.order_no,
                mo.bom_header_id,
                mo.product_id,
                mo.planned_qty,
                mo.uom,
                mo.warehouse_id,
                mo.target_warehouse_id,
                mo.status,
                mo.priority,
                mo.entity_id,
                p.name as product_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                b.bom_name,
                b.bom_type,
                w.name as warehouse_name
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            JOIN bom_headers b ON mo.bom_header_id = b.id
            JOIN warehouses w ON mo.warehouse_id = w.id
            WHERE mo.id = %s AND mo.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting order for issue {order_id}: {e}")
            return None
    
    # ==================== Material Availability Queries ====================
    
    def get_material_availability(self, order_id: int) -> pd.DataFrame:
        """
        Get material availability for an order including alternatives
        
        Returns DataFrame with:
        - material_id, material_name, required_qty, issued_qty, pending_qty
        - available_qty, availability_status
        - has_alternatives, alternative_total_qty, alternative_details
        """
        # Main materials query
        query = """
            SELECT 
                mom.id as order_material_id,
                mom.material_id,
                p.name as material_name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                mom.required_qty,
                COALESCE(mom.issued_qty, 0) as issued_qty,
                mom.required_qty - COALESCE(mom.issued_qty, 0) as pending_qty,
                mom.uom,
                mom.status as material_status,
                COALESCE(SUM(ih.remain), 0) as available_qty,
                mo.warehouse_id,
                bd.id as bom_detail_id,
                bd.quantity as bom_qty
            FROM manufacturing_order_materials mom
            JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            JOIN products p ON mom.material_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            LEFT JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
                AND bd.material_id = mom.material_id
            LEFT JOIN inventory_histories ih 
                ON ih.product_id = mom.material_id 
                AND ih.warehouse_id = mo.warehouse_id
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE mom.manufacturing_order_id = %s
            GROUP BY mom.id, mom.material_id, p.name, p.pt_code, p.legacy_pt_code, 
                     p.package_size, br.brand_name, mom.required_qty, mom.issued_qty, 
                     mom.uom, mom.status, mo.warehouse_id, bd.id, bd.quantity
            ORDER BY p.name
        """
        
        try:
            materials = pd.read_sql(query, self.engine, params=(order_id,))
            
            if materials.empty:
                return materials
            
            # Initialize new columns with proper types
            materials['availability_status'] = 'INSUFFICIENT'
            materials['has_alternatives'] = False
            materials['alternative_total_qty'] = 0.0
            # Use object dtype for list column
            materials['alternative_details'] = None
            materials['alternative_details'] = materials['alternative_details'].astype(object)
            
            # Calculate availability status and get alternatives
            warehouse_id = int(materials['warehouse_id'].iloc[0])
            
            for idx in range(len(materials)):
                row = materials.iloc[idx]
                pending = float(row['pending_qty'])
                available = float(row['available_qty'])
                
                # Availability status
                if available >= pending:
                    status = 'SUFFICIENT'
                elif available > 0:
                    status = 'PARTIAL'
                else:
                    status = 'INSUFFICIENT'
                
                materials.iloc[idx, materials.columns.get_loc('availability_status')] = status
                
                # Get alternatives if bom_detail_id exists
                if pd.notna(row['bom_detail_id']):
                    primary_bom_qty = float(row['bom_qty']) if pd.notna(row.get('bom_qty')) else 1.0
                    alternatives = self._get_material_alternatives(
                        int(row['bom_detail_id']), warehouse_id, primary_bom_qty
                    )
                    materials.iloc[idx, materials.columns.get_loc('has_alternatives')] = len(alternatives) > 0
                    materials.iloc[idx, materials.columns.get_loc('alternative_total_qty')] = sum(
                        alt['available'] for alt in alternatives
                    )
                    materials.at[idx, 'alternative_details'] = alternatives
                else:
                    materials.iloc[idx, materials.columns.get_loc('has_alternatives')] = False
                    materials.iloc[idx, materials.columns.get_loc('alternative_total_qty')] = 0
                    materials.at[idx, 'alternative_details'] = []
            
            return materials
            
        except Exception as e:
            logger.error(f"Error getting material availability for order {order_id}: {e}")
            return pd.DataFrame()
    
    def _get_material_alternatives(self, bom_detail_id: int, 
                                   warehouse_id: int,
                                   primary_bom_qty: float = 1.0) -> List[Dict[str, Any]]:
        """
        Get alternative materials with availability and conversion ratio
        
        Args:
            bom_detail_id: BOM detail ID for primary material
            warehouse_id: Warehouse to check stock
            primary_bom_qty: BOM quantity of primary material (for ratio calculation)
        
        Returns:
            List of alternatives with conversion_ratio added
        """
        query = """
            SELECT 
                alt.id as alternative_id,
                alt.alternative_material_id,
                p.name,
                p.pt_code,
                p.legacy_pt_code,
                p.package_size,
                br.brand_name as brand_name,
                alt.quantity,
                alt.uom,
                alt.priority,
                COALESCE(SUM(ih.remain), 0) as available
            FROM bom_material_alternatives alt
            JOIN products p ON alt.alternative_material_id = p.id
            LEFT JOIN brands br ON p.brand_id = br.id
            LEFT JOIN inventory_histories ih 
                ON ih.product_id = alt.alternative_material_id
                AND ih.warehouse_id = %s
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE alt.bom_detail_id = %s
                AND alt.is_active = 1
            GROUP BY alt.id, alt.alternative_material_id, p.name, p.pt_code,
                     p.legacy_pt_code, p.package_size, br.brand_name, alt.quantity, 
                     alt.uom, alt.priority
            ORDER BY alt.priority ASC
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(warehouse_id, bom_detail_id))
            alternatives = result.to_dict('records')
            
            # Calculate conversion_ratio for each alternative
            # conversion_ratio = alt_bom_qty / primary_bom_qty
            # Example: primary needs 1.0, alternative needs 1.2 → ratio = 1.2
            # To cover 0.2049 shortage in primary units, need 0.2049 * 1.2 = 0.2459 alt units
            for alt in alternatives:
                alt_bom_qty = float(alt.get('quantity', 1.0))
                if primary_bom_qty > 0:
                    alt['conversion_ratio'] = alt_bom_qty / primary_bom_qty
                else:
                    alt['conversion_ratio'] = 1.0
            
            return alternatives
        except Exception as e:
            logger.error(f"Error getting alternatives for {bom_detail_id}: {e}")
            return []
    
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
    
    def get_issue_metrics(self, from_date: Optional[date] = None,
                         to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get issue metrics for dashboard"""
        from .common import get_vietnam_today
        
        today = get_vietnam_today()
        
        base_query = """
            SELECT 
                COUNT(*) as total_issues,
                SUM(CASE WHEN DATE(issue_date) = %s THEN 1 ELSE 0 END) as today_issues,
                SUM(CASE WHEN status = 'CONFIRMED' THEN 1 ELSE 0 END) as confirmed_count
            FROM material_issues
            WHERE 1=1
        """
        
        params = [today]
        
        if from_date:
            base_query += " AND DATE(issue_date) >= %s"
            params.append(from_date)
        
        if to_date:
            base_query += " AND DATE(issue_date) <= %s"
            params.append(to_date)
        
        # Pending orders count
        pending_query = """
            SELECT COUNT(*) as pending_orders
            FROM manufacturing_orders
            WHERE delete_flag = 0
                AND status IN ('DRAFT', 'CONFIRMED')
        """
        
        # Total units issued
        units_query = """
            SELECT COALESCE(SUM(mid.quantity), 0) as total_units
            FROM material_issue_details mid
            JOIN material_issues mi ON mid.material_issue_id = mi.id
            WHERE 1=1
        """
        
        if from_date:
            units_query += " AND DATE(mi.issue_date) >= %s"
        if to_date:
            units_query += " AND DATE(mi.issue_date) <= %s"
        
        try:
            result = pd.read_sql(base_query, self.engine, params=tuple(params))
            pending = pd.read_sql(pending_query, self.engine)
            
            units_params = []
            if from_date:
                units_params.append(from_date)
            if to_date:
                units_params.append(to_date)
            units = pd.read_sql(units_query, self.engine, 
                              params=tuple(units_params) if units_params else None)
            
            row = result.iloc[0]
            
            return {
                'total_issues': int(row['total_issues']),
                'today_issues': int(row['today_issues']),
                'confirmed_count': int(row['confirmed_count']),
                'pending_orders': int(pending.iloc[0]['pending_orders']),
                'total_units': float(units.iloc[0]['total_units'])
            }
            
        except Exception as e:
            logger.error(f"Error getting issue metrics: {e}")
            return {
                'total_issues': 0,
                'today_issues': 0,
                'confirmed_count': 0,
                'pending_orders': 0,
                'total_units': 0
            }