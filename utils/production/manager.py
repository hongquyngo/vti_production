# utils/production/manager.py
"""
Production Order Management
Core production order CRUD and status management
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import math
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


class ProductionManager:
    """Production Order Management"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
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
                p.name as product_name,
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
        
        if order_data['warehouse_id'] == order_data['target_warehouse_id']:
            raise ValueError("Source and target warehouse must be different")
        
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
                entity_id = entity_row['company_id'] if entity_row else None
                
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
                
                # Create material requirements
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
    
    def get_active_boms(self, bom_type: Optional[str] = None) -> pd.DataFrame:
        """Get active BOMs for order creation"""
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
            WHERE h.delete_flag = 0 AND h.status = 'ACTIVE'
        """
        
        params = []
        if bom_type:
            query += " AND h.bom_type = %s"
            params.append(bom_type)
        
        query += " ORDER BY h.bom_name"
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params) if params else None)
        except Exception as e:
            logger.error(f"Error getting active BOMs: {e}")
            return pd.DataFrame()
    
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
    
    def _generate_order_number(self, conn) -> str:
        """Generate unique order number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(order_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM manufacturing_orders
            WHERE order_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'MO-{timestamp}-%'})
        next_num = result.fetchone()['next_num']
        next_num = int(next_num) if next_num is not None else 1
        
        return f"MO-{timestamp}-{next_num:04d}"
    
    def _create_material_requirements(self, conn, order_id: int, order_data: Dict):
        """Create material requirements from BOM"""
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
        
        materials = conn.execute(bom_query, {
            'bom_id': order_data['bom_header_id'],
            'planned_qty': float(order_data['planned_qty'])
        })
        
        for mat in materials:
            # Calculate required quantity with scrap
            production_cycles = float(mat['planned_qty']) / float(mat['output_qty'])
            base_material = production_cycles * float(mat['quantity'])
            with_scrap = base_material * (1 + float(mat['scrap_rate']) / 100)
            required_qty = math.ceil(with_scrap)
            
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