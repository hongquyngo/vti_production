# utils/production/manager.py
"""
Production Order Management - v1.1
Core production order CRUD and status management with BOM alternatives support
BACKWARD COMPATIBLE - Does not require is_primary column

CHANGES v1.1:
- Vietnam timezone (Asia/Ho_Chi_Minh) for order number generation
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import math
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine
from .common import get_vietnam_now

logger = logging.getLogger(__name__)


class ProductionManager:
    """Production Order Management with BOM Alternatives Support"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self._bom_cache = {}
    
    def get_filter_options(self) -> Dict[str, List[str]]:
        """
        Get dynamic filter options from database
        
        Returns:
            Dict with keys: 'statuses', 'order_types', 'priorities'
        """
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
            # Fallback to defaults if query fails
            return {
                'statuses': ['All', 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
                'order_types': ['All', 'CUTTING', 'REPACKING', 'KITTING'],
                'priorities': ['All', 'LOW', 'NORMAL', 'HIGH', 'URGENT']
            }


    def get_orders(self, status: Optional[str] = None,
                order_type: Optional[str] = None,
                from_date: Optional[date] = None,
                to_date: Optional[date] = None,
                priority: Optional[str] = None,
                page: int = 1, page_size: int = 100) -> pd.DataFrame:
        """Get production orders with filters"""
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
                p.pt_code,
                p.name as product_name,
                p.package_size,
                b.bom_type,
                b.bom_name,
                o.warehouse_id,
                w1.name as warehouse_name,
                o.target_warehouse_id,
                w2.name as target_warehouse_name
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN warehouses w1 ON o.warehouse_id = w1.id
            JOIN warehouses w2 ON o.target_warehouse_id = w2.id
            WHERE o.delete_flag = 0
        """
        
        params = []
        
        if status:
            query += " AND o.status = %s"
            params.append(status)
        
        if order_type:
            query += " AND b.bom_type = %s"
            params.append(order_type)
        
        if from_date:
            query += " AND o.order_date >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND o.order_date <= %s"
            params.append(to_date)
        
        if priority:
            query += " AND o.priority = %s"
            params.append(priority)
        
        query += " ORDER BY o.created_date DESC"
        
        offset = (page - 1) * page_size
        query += " LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params))
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return pd.DataFrame()


    def create_order(self, order_data: Dict[str, Any]) -> str:
        """Create new production order with validation"""
        # Validate required fields
        required = ['bom_header_id', 'product_id', 'planned_qty', 'warehouse_id', 
                   'target_warehouse_id', 'scheduled_date']
        missing = [f for f in required if f not in order_data or order_data[f] is None]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
        # Validate values
        if order_data['planned_qty'] <= 0:
            raise ValueError("Planned quantity must be positive")
        
        
        with self.engine.begin() as conn:
            try:
                # Generate order number
                order_no = self._generate_order_number(conn)
                
                # Get entity ID
                entity_query = text("""
                    SELECT company_id FROM warehouses WHERE id = :warehouse_id
                """)
                entity_result = conn.execute(entity_query, {
                    'warehouse_id': order_data['warehouse_id']
                })
                entity_row = entity_result.fetchone()
                entity_id = entity_row[0] if entity_row else None
                
                # Create order
                order_query = text("""
                    INSERT INTO manufacturing_orders (
                        order_no, order_date, bom_header_id, product_id,
                        planned_qty, produced_qty, uom, warehouse_id,
                        target_warehouse_id, scheduled_date, status,
                        priority, notes, entity_id, created_by, created_date
                    ) VALUES (
                        :order_no, CURDATE(), :bom_header_id, :product_id,
                        :planned_qty, 0, :uom, :warehouse_id,
                        :target_warehouse_id, :scheduled_date, 'DRAFT',
                        :priority, :notes, :entity_id, :created_by, NOW()
                    )
                """)
                
                result = conn.execute(order_query, {
                    'order_no': order_no,
                    'bom_header_id': order_data['bom_header_id'],
                    'product_id': order_data['product_id'],
                    'planned_qty': float(order_data['planned_qty']),
                    'uom': order_data['uom'],
                    'warehouse_id': order_data['warehouse_id'],
                    'target_warehouse_id': order_data['target_warehouse_id'],
                    'scheduled_date': order_data['scheduled_date'],
                    'priority': order_data.get('priority', 'NORMAL'),
                    'notes': order_data.get('notes', ''),
                    'entity_id': entity_id,
                    'created_by': order_data.get('created_by', 1)
                })
                
                order_id = result.lastrowid
                
                # Create material requirements (all materials from bom_details)
                self._create_material_requirements(conn, order_id, order_data)
                
                logger.info(f"Created production order {order_no} (ID: {order_id})")
                return order_no
                
            except Exception as e:
                logger.error(f"Error creating order: {e}", extra={
                    'bom_id': order_data.get('bom_header_id'),
                    'product_id': order_data.get('product_id'),
                    'quantity': order_data.get('planned_qty')
                })
                raise ValueError(f"Failed to create production order: {str(e)}") from e
    
    def get_order_details(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get order details"""
        query = """
            SELECT 
                o.*,
                p.name as product_name,
                b.bom_name,
                b.bom_type,
                w1.name as warehouse_name,
                w2.name as target_warehouse_name
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN warehouses w1 ON o.warehouse_id = w1.id
            JOIN warehouses w2 ON o.target_warehouse_id = w2.id
            WHERE o.id = %s AND o.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting order details for order {order_id}: {e}")
            return None
    
    def get_order_materials(self, order_id: int) -> pd.DataFrame:
        """Get materials for order"""
        query = """
            SELECT 
                m.material_id,
                p.name as material_name,
                m.required_qty,
                COALESCE(m.issued_qty, 0) as issued_qty,
                m.uom,
                m.status,
                (m.required_qty - COALESCE(m.issued_qty, 0)) as pending_qty
            FROM manufacturing_order_materials m
            JOIN products p ON m.material_id = p.id
            WHERE m.manufacturing_order_id = %s
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting order materials for order {order_id}: {e}")
            return pd.DataFrame()
    
    def calculate_material_requirements(self, bom_id: int, 
                                       quantity: float) -> pd.DataFrame:
        """
        Calculate material requirements for production order
        All materials in bom_details are considered primary materials
        
        Args:
            bom_id: ID of the BOM header
            quantity: Planned production quantity
            
        Returns:
            DataFrame with material requirements including scrap rate
        """
        query = """
            SELECT 
                d.material_id,
                p.name as material_name,
                d.quantity * %s / h.output_qty * (1 + d.scrap_rate/100) as required_qty,
                d.uom
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON d.material_id = p.id
            WHERE h.id = %s
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(quantity, bom_id))
        except Exception as e:
            logger.error(f"Error calculating requirements for BOM {bom_id}: {e}")
            return pd.DataFrame()
    
    def get_bom_alternatives(self, bom_detail_id: int) -> pd.DataFrame:
        """
        Get alternative materials for a BOM detail, ordered by priority
        
        Args:
            bom_detail_id: ID of the BOM detail (primary material)
            
        Returns:
            DataFrame with alternative materials sorted by priority
        """
        query = """
            SELECT 
                alt.id as alternative_id,
                alt.bom_detail_id,
                alt.alternative_material_id,
                p.name as alternative_material_name,
                alt.material_type,
                alt.quantity,
                alt.uom,
                alt.scrap_rate,
                alt.priority,
                alt.is_active,
                alt.notes
            FROM bom_material_alternatives alt
            JOIN products p ON alt.alternative_material_id = p.id
            WHERE alt.bom_detail_id = %s
                AND alt.is_active = 1
            ORDER BY alt.priority ASC
        """
        
        try:
            df = pd.read_sql(query, self.engine, params=(bom_detail_id,))
            logger.info(f"Found {len(df)} alternatives for BOM detail {bom_detail_id}")
            return df
        except Exception as e:
            logger.error(f"Error getting alternatives for BOM detail {bom_detail_id}: {e}")
            return pd.DataFrame()
    
    def get_bom_detail_with_alternatives(self, bom_id: int, 
                                        quantity: float) -> List[Dict[str, Any]]:
        """
        Get BOM details with their alternatives for a production order
        
        Args:
            bom_id: BOM header ID
            quantity: Planned production quantity
            
        Returns:
            List of materials with their alternatives
        """
        # Get all materials from bom_details (all are primary)
        primary_query = """
            SELECT 
                d.id as bom_detail_id,
                d.material_id,
                p.name as material_name,
                d.quantity,
                d.uom,
                d.scrap_rate,
                h.output_qty
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON d.material_id = p.id
            WHERE h.id = %s
            ORDER BY p.name
        """
        
        try:
            primaries = pd.read_sql(primary_query, self.engine, params=(bom_id,))
            
            materials_list = []
            for _, primary in primaries.iterrows():
                # Calculate required quantity for primary
                production_cycles = quantity / float(primary['output_qty'])
                base_qty = production_cycles * float(primary['quantity'])
                with_scrap = base_qty * (1 + float(primary['scrap_rate']) / 100)
                required_qty = math.ceil(with_scrap)
                
                material_data = {
                    'bom_detail_id': int(primary['bom_detail_id']),
                    'material_id': int(primary['material_id']),
                    'material_name': primary['material_name'],
                    'required_qty': required_qty,
                    'uom': primary['uom'],
                    'is_primary': True,
                    'alternatives': []
                }
                
                # Get alternatives for this material
                alternatives = self.get_bom_alternatives(int(primary['bom_detail_id']))
                
                for _, alt in alternatives.iterrows():
                    # Calculate required quantity for alternative
                    alt_base_qty = production_cycles * float(alt['quantity'])
                    alt_with_scrap = alt_base_qty * (1 + float(alt['scrap_rate']) / 100)
                    alt_required_qty = math.ceil(alt_with_scrap)
                    
                    material_data['alternatives'].append({
                        'alternative_id': int(alt['alternative_id']),
                        'material_id': int(alt['alternative_material_id']),
                        'material_name': alt['alternative_material_name'],
                        'required_qty': alt_required_qty,
                        'uom': alt['uom'],
                        'priority': int(alt['priority'])
                    })
                
                materials_list.append(material_data)
            
            return materials_list
            
        except Exception as e:
            logger.error(f"Error getting BOM details with alternatives for BOM {bom_id}: {e}")
            return []
    

    def get_active_boms(self, bom_type: Optional[str] = None) -> pd.DataFrame:
            """Get active BOMs for order creation"""
            # Simple query without caching complexity
            query = """
                SELECT 
                    h.id,
                    h.bom_code,
                    h.bom_name,
                    h.bom_type,
                    h.product_id,
                    p.name as product_name,
                    h.output_qty,
                    h.uom
                FROM bom_headers h
                JOIN products p ON h.product_id = p.id
                WHERE h.delete_flag = 0 
                    AND h.status = 'ACTIVE'
                    AND p.delete_flag = 0
            """
            
            params = []
            if bom_type:
                query += " AND h.bom_type = %s"
                params.append(bom_type)
            
            query += " ORDER BY h.bom_code, h.bom_name"
            
            try:
                df = pd.read_sql(query, self.engine, 
                            params=tuple(params) if params else None)
                logger.info(f"Retrieved {len(df)} active BOMs for type: {bom_type}")
                return df
            except Exception as e:
                logger.error(f"Error getting active BOMs: {e}")
                return pd.DataFrame()
        
    def clear_bom_cache(self):
        """Clear cached BOM data if exists"""
        if hasattr(self, '_bom_cache'):
            self._bom_cache.clear()
            logger.debug("BOM cache cleared")

    def get_bom_info(self, bom_id: int) -> Optional[Dict]:
        """Get BOM info for order creation"""
        query = """
            SELECT 
                h.id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.product_id,
                p.name as product_name,
                h.output_qty,
                h.uom
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            WHERE h.id = %s AND h.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(bom_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting BOM info for BOM {bom_id}: {e}")
            return None
    
    def update_order_status(self, order_id: int, new_status: str,
                          user_id: Optional[int] = None) -> bool:
        """Update order status with validation"""
        valid_statuses = ['DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}")
        
        with self.engine.begin() as conn:
            try:
                query = text("""
                    UPDATE manufacturing_orders
                    SET status = :status,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id AND delete_flag = 0
                """)
                
                result = conn.execute(query, {
                    'status': new_status,
                    'user_id': user_id,
                    'order_id': order_id
                })
                
                success = result.rowcount > 0
                if success:
                    logger.info(f"Updated order {order_id} status to {new_status}")
                else:
                    logger.warning(f"No order found with ID {order_id}")
                
                return success
                
            except Exception as e:
                logger.error(f"Error updating order status: {e}")
                raise
    
    def update_order(self, order_id: int, update_data: dict, user_id: Optional[int] = None) -> bool:
        """
        Update production order details (only for DRAFT/CONFIRMED status)
        
        Args:
            order_id: Order ID to update
            update_data: Dictionary with fields to update
                - planned_qty (optional)
                - scheduled_date (optional)
                - priority (optional)
                - notes (optional)
                - warehouse_id (optional)
                - target_warehouse_id (optional)
            user_id: User making the update
        
        Returns:
            True if successful
        """
        with self.engine.begin() as conn:
            try:
                # Check current status
                check_query = text("""
                    SELECT status, bom_header_id FROM manufacturing_orders
                    WHERE id = :order_id AND delete_flag = 0
                """)
                result = conn.execute(check_query, {'order_id': order_id})
                order = result.fetchone()
                
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                if order[0] not in ['DRAFT', 'CONFIRMED']:
                    raise ValueError(f"Cannot edit order with status {order[0]}. Only DRAFT or CONFIRMED orders can be edited.")
                
                # Build dynamic update query
                update_fields = []
                params = {'order_id': order_id, 'user_id': user_id}
                
                if 'planned_qty' in update_data:
                    update_fields.append("planned_qty = :planned_qty")
                    params['planned_qty'] = update_data['planned_qty']
                
                if 'scheduled_date' in update_data:
                    update_fields.append("scheduled_date = :scheduled_date")
                    params['scheduled_date'] = update_data['scheduled_date']
                
                if 'priority' in update_data:
                    update_fields.append("priority = :priority")
                    params['priority'] = update_data['priority']
                
                if 'notes' in update_data:
                    update_fields.append("notes = :notes")
                    params['notes'] = update_data['notes']
                
                if 'warehouse_id' in update_data:
                    update_fields.append("warehouse_id = :warehouse_id")
                    params['warehouse_id'] = update_data['warehouse_id']
                
                if 'target_warehouse_id' in update_data:
                    update_fields.append("target_warehouse_id = :target_warehouse_id")
                    params['target_warehouse_id'] = update_data['target_warehouse_id']
                
                if not update_fields:
                    return True  # Nothing to update
                
                # Add audit fields
                update_fields.extend([
                    "updated_by = :user_id",
                    "updated_date = NOW()"
                ])
                
                query = text(f"""
                    UPDATE manufacturing_orders
                    SET {', '.join(update_fields)}
                    WHERE id = :order_id AND delete_flag = 0
                """)
                
                result = conn.execute(query, params)
                
                # If planned_qty changed, update order materials
                if 'planned_qty' in update_data:
                    self._recalculate_order_materials(conn, order_id, order[1], update_data['planned_qty'])
                
                success = result.rowcount > 0
                if success:
                    logger.info(f"Updated order {order_id}: {list(update_data.keys())}")
                
                return success
                
            except Exception as e:
                logger.error(f"Error updating order {order_id}: {e}")
                raise

    def _recalculate_order_materials(self, conn, order_id: int, bom_header_id: int, new_qty: float):
        """Recalculate order materials based on new planned quantity"""
        try:
            # Get BOM details
            bom_query = text("""
                SELECT bd.material_id, bd.quantity, bd.scrap_rate
                FROM bom_details bd
                WHERE bd.bom_header_id = :bom_id AND bd.delete_flag = 0
            """)
            bom_details = conn.execute(bom_query, {'bom_id': bom_header_id}).fetchall()
            
            # Get BOM output qty
            output_query = text("""
                SELECT output_qty FROM bom_headers WHERE id = :bom_id
            """)
            output_result = conn.execute(output_query, {'bom_id': bom_header_id}).fetchone()
            output_qty = output_result[0] if output_result else 1
            
            # Calculate multiplier
            multiplier = new_qty / float(output_qty)
            
            # Update each material
            for detail in bom_details:
                material_id = detail[0]
                base_qty = float(detail[1])
                scrap_rate = float(detail[2] or 0)
                
                required_qty = base_qty * multiplier * (1 + scrap_rate / 100)
                
                update_query = text("""
                    UPDATE manufacturing_order_materials
                    SET required_qty = :required_qty
                    WHERE order_id = :order_id AND material_id = :material_id
                """)
                
                conn.execute(update_query, {
                    'required_qty': required_qty,
                    'order_id': order_id,
                    'material_id': material_id
                })
            
            logger.info(f"Recalculated materials for order {order_id} with new qty {new_qty}")
            
        except Exception as e:
            logger.error(f"Error recalculating materials: {e}")
            raise

    def _generate_order_number(self, conn) -> str:
        """Generate unique order number (Vietnam timezone)"""
        timestamp = get_vietnam_now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(order_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM manufacturing_orders
            WHERE order_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'MO-{timestamp}-%'})
        row = result.fetchone()
        next_num = row[0] if row else 1  # Use index instead of key
        next_num = int(next_num) if next_num is not None else 1
        
        return f"MO-{timestamp}-{next_num:04d}"
    
    def _create_material_requirements(self, conn, order_id: int, order_data: Dict):
        """
        Create material requirements from BOM
        All materials in bom_details are primary materials
        Alternatives will be handled dynamically during material issue
        """
        bom_query = text("""
            SELECT 
                d.material_id,
                d.quantity,
                d.uom,
                d.scrap_rate,
                h.output_qty,
                :planned_qty as planned_qty
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            WHERE h.id = :bom_id
        """)
        
        materials_result = conn.execute(bom_query, {
            'bom_id': order_data['bom_header_id'],
            'planned_qty': float(order_data['planned_qty'])
        })
        
        # Convert rows to list of dicts for easier access
        materials_list = []
        for row in materials_result:
            materials_list.append(dict(zip(materials_result.keys(), row)))
        
        for mat in materials_list:
            # Calculate required quantity with scrap - EXACT value, no rounding
            production_cycles = float(mat['planned_qty']) / float(mat['output_qty'])
            base_material = production_cycles * float(mat['quantity'])
            with_scrap = base_material * (1 + float(mat['scrap_rate']) / 100)
            required_qty = round(with_scrap, 4)  # Keep 4 decimal places for precision
            
            insert_query = text("""
                INSERT INTO manufacturing_order_materials (
                    manufacturing_order_id, material_id, required_qty,
                    issued_qty, uom, warehouse_id, status, created_date
                ) VALUES (
                    :order_id, :material_id, :required_qty,
                    0, :uom, :warehouse_id, 'PENDING', NOW()
                )
            """)
            
            conn.execute(insert_query, {
                'order_id': order_id,
                'material_id': mat['material_id'],
                'required_qty': required_qty,
                'uom': mat['uom'],
                'warehouse_id': order_data['warehouse_id']
            })


    def get_active_employees(self) -> pd.DataFrame:
        """
        Get list of active employees for dropdown selection
        
        Returns:
            DataFrame with id, full_name, position for employee selection
        """
        query = text("""
            SELECT 
                e.id,
                CONCAT(e.first_name, ' ', e.last_name) as full_name,
                e.email,
                p.name as position_name,
                d.name as department_name
            FROM employees e
            LEFT JOIN positions p ON e.position_id = p.id
            LEFT JOIN departments d ON e.department_id = d.id 
                AND (d.delete_flag = 0 OR d.delete_flag IS NULL)
            WHERE e.delete_flag = 0
            AND (e.status = 'ACTIVE' OR e.status IS NULL)
            ORDER BY e.first_name, e.last_name
        """)
        
        with self.engine.connect() as conn:
            result = pd.read_sql(query, conn)
        
        return result