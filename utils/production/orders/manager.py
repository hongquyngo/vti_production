# utils/production/orders/manager.py
"""
Order Manager - Business logic for Production Orders
Create, Update, Confirm, Cancel operations

Version: 1.0.0
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Any

import pandas as pd
from sqlalchemy import text

from utils.db import get_db_engine
from .common import get_vietnam_now, OrderConstants, OrderValidator

logger = logging.getLogger(__name__)


class OrderManager:
    """Business logic for Production Order management"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Create Order ====================
    
    def create_order(self, order_data: Dict[str, Any]) -> str:
        """
        Create new production order with validation
        
        Args:
            order_data: Dictionary containing order information:
                - bom_header_id: BOM to use
                - product_id: Product to produce
                - planned_qty: Planned quantity
                - uom: Unit of measure
                - warehouse_id: Source warehouse
                - target_warehouse_id: Target warehouse
                - scheduled_date: Scheduled production date
                - priority: Order priority (optional)
                - notes: Notes (optional)
                - created_by: User ID creating the order
                
        Returns:
            Order number (e.g., "MO-20251201-0001")
            
        Raises:
            ValueError: If validation fails or creation fails
        """
        # Validate
        is_valid, error = OrderValidator.validate_create_order(order_data)
        if not is_valid:
            raise ValueError(error)
        
        with self.engine.begin() as conn:
            try:
                # Generate order number
                order_no = self._generate_order_number(conn)
                
                # Get entity ID from warehouse
                entity_id = self._get_entity_id(conn, order_data['warehouse_id'])
                
                # Insert order
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
                    'uom': order_data.get('uom', 'EA'),
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
                
                logger.info(f"✅ Created production order {order_no} (ID: {order_id})")
                return order_no
                
            except Exception as e:
                logger.error(f"❌ Error creating order: {e}")
                raise ValueError(f"Failed to create production order: {str(e)}")
    
    # ==================== Update Order ====================
    
    def update_order(self, order_id: int, update_data: Dict[str, Any], 
                    user_id: int = None) -> bool:
        """
        Update existing production order
        
        Args:
            order_id: Order ID to update
            update_data: Fields to update (planned_qty, scheduled_date, priority, notes, etc.)
            user_id: User making the update
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If order not found or cannot be edited
        """
        with self.engine.begin() as conn:
            try:
                # Get current order
                order_query = text("""
                    SELECT id, status, bom_header_id 
                    FROM manufacturing_orders 
                    WHERE id = :order_id AND delete_flag = 0
                """)
                result = conn.execute(order_query, {'order_id': order_id}).fetchone()
                
                if not result:
                    raise ValueError(f"Order {order_id} not found")
                
                current_status = result[1]
                bom_header_id = result[2]
                
                # Validate
                is_valid, error = OrderValidator.validate_update_order(update_data, current_status)
                if not is_valid:
                    raise ValueError(error)
                
                # Build update query
                update_fields = []
                params = {'order_id': order_id, 'user_id': user_id}
                
                if 'planned_qty' in update_data:
                    update_fields.append("planned_qty = :planned_qty")
                    params['planned_qty'] = float(update_data['planned_qty'])
                
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
                
                update_query = text(f"""
                    UPDATE manufacturing_orders
                    SET {', '.join(update_fields)}
                    WHERE id = :order_id AND delete_flag = 0
                """)
                
                conn.execute(update_query, params)
                
                # Recalculate materials if quantity changed
                if 'planned_qty' in update_data:
                    self._recalculate_materials(conn, order_id, bom_header_id, 
                                               update_data['planned_qty'])
                
                logger.info(f"✅ Updated order {order_id}: {list(update_data.keys())}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error updating order {order_id}: {e}")
                raise
    
    # ==================== Confirm Order ====================
    
    def confirm_order(self, order_id: int, user_id: int = None) -> bool:
        """
        Confirm a DRAFT order - changes status to CONFIRMED
        
        Args:
            order_id: Order ID to confirm
            user_id: User confirming the order
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If order cannot be confirmed
        """
        with self.engine.begin() as conn:
            try:
                # Get current status
                status_query = text("""
                    SELECT status, order_no 
                    FROM manufacturing_orders 
                    WHERE id = :order_id AND delete_flag = 0
                """)
                result = conn.execute(status_query, {'order_id': order_id}).fetchone()
                
                if not result:
                    raise ValueError(f"Order {order_id} not found")
                
                current_status = result[0]
                order_no = result[1]
                
                if not OrderValidator.can_confirm(current_status):
                    raise ValueError(f"Cannot confirm order with status: {current_status}")
                
                # Update status
                update_query = text("""
                    UPDATE manufacturing_orders
                    SET status = 'CONFIRMED',
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(update_query, {
                    'order_id': order_id,
                    'user_id': user_id
                })
                
                logger.info(f"✅ Confirmed order {order_no} (ID: {order_id})")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error confirming order {order_id}: {e}")
                raise
    
    # ==================== Cancel Order ====================
    
    def cancel_order(self, order_id: int, reason: str = None, 
                    user_id: int = None) -> bool:
        """
        Cancel an order - changes status to CANCELLED
        
        Args:
            order_id: Order ID to cancel
            reason: Cancellation reason
            user_id: User cancelling the order
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If order cannot be cancelled
        """
        with self.engine.begin() as conn:
            try:
                # Get current status
                status_query = text("""
                    SELECT status, order_no 
                    FROM manufacturing_orders 
                    WHERE id = :order_id AND delete_flag = 0
                """)
                result = conn.execute(status_query, {'order_id': order_id}).fetchone()
                
                if not result:
                    raise ValueError(f"Order {order_id} not found")
                
                current_status = result[0]
                order_no = result[1]
                
                if not OrderValidator.can_cancel(current_status):
                    raise ValueError(f"Cannot cancel order with status: {current_status}")
                
                # Build notes with reason
                notes_update = ""
                if reason:
                    notes_update = f"[CANCELLED] {reason}"
                
                # Update status
                update_query = text("""
                    UPDATE manufacturing_orders
                    SET status = 'CANCELLED',
                        notes = CASE 
                            WHEN :reason IS NOT NULL AND :reason != '' 
                            THEN CONCAT(COALESCE(notes, ''), '\n', :reason)
                            ELSE notes 
                        END,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(update_query, {
                    'order_id': order_id,
                    'reason': notes_update,
                    'user_id': user_id
                })
                
                logger.info(f"✅ Cancelled order {order_no} (ID: {order_id})")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error cancelling order {order_id}: {e}")
                raise
    
    # ==================== Delete Order ====================
    
    def delete_order(self, order_id: int, user_id: int = None) -> bool:
        """
        Soft delete an order (set delete_flag = 1)
        Only DRAFT and CANCELLED orders can be deleted
        
        Args:
            order_id: Order ID to delete
            user_id: User deleting the order
            
        Returns:
            True if successful
        """
        with self.engine.begin() as conn:
            try:
                # Get current status
                status_query = text("""
                    SELECT status, order_no 
                    FROM manufacturing_orders 
                    WHERE id = :order_id AND delete_flag = 0
                """)
                result = conn.execute(status_query, {'order_id': order_id}).fetchone()
                
                if not result:
                    raise ValueError(f"Order {order_id} not found")
                
                current_status = result[0]
                order_no = result[1]
                
                if current_status not in ['DRAFT', 'CANCELLED']:
                    raise ValueError(f"Cannot delete order with status: {current_status}")
                
                # Soft delete
                delete_query = text("""
                    UPDATE manufacturing_orders
                    SET delete_flag = 1,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(delete_query, {
                    'order_id': order_id,
                    'user_id': user_id
                })
                
                logger.info(f"✅ Deleted order {order_no} (ID: {order_id})")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error deleting order {order_id}: {e}")
                raise
    
    # ==================== Private Helper Methods ====================
    
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
        next_num = int(row[0]) if row and row[0] else 1
        
        return f"MO-{timestamp}-{next_num:04d}"
    
    def _get_entity_id(self, conn, warehouse_id: int) -> Optional[int]:
        """Get entity ID from warehouse"""
        query = text("SELECT company_id FROM warehouses WHERE id = :warehouse_id")
        result = conn.execute(query, {'warehouse_id': warehouse_id}).fetchone()
        return result[0] if result else None
    
    def _create_material_requirements(self, conn, order_id: int, order_data: Dict):
        """Create material requirements from BOM"""
        # Get BOM details
        bom_query = text("""
            SELECT 
                d.material_id,
                d.quantity,
                d.uom,
                d.scrap_rate,
                h.output_qty
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            WHERE h.id = :bom_id
        """)
        
        materials = conn.execute(bom_query, {
            'bom_id': order_data['bom_header_id']
        }).fetchall()
        
        planned_qty = float(order_data['planned_qty'])
        
        for mat in materials:
            material_id = mat[0]
            quantity = float(mat[1])
            uom = mat[2]
            scrap_rate = float(mat[3] or 0)
            output_qty = float(mat[4])
            
            # Calculate required quantity
            production_cycles = planned_qty / output_qty
            base_qty = production_cycles * quantity
            required_qty = round(base_qty * (1 + scrap_rate / 100), 4)
            
            # Insert material requirement
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
                'material_id': material_id,
                'required_qty': required_qty,
                'uom': uom,
                'warehouse_id': order_data['warehouse_id']
            })
    
    def _recalculate_materials(self, conn, order_id: int, bom_header_id: int, 
                              new_qty: float):
        """Recalculate material requirements when quantity changes"""
        # Get BOM details
        bom_query = text("""
            SELECT d.material_id, d.quantity, d.scrap_rate, h.output_qty
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            WHERE h.id = :bom_id
        """)
        
        materials = conn.execute(bom_query, {'bom_id': bom_header_id}).fetchall()
        
        for mat in materials:
            material_id = mat[0]
            quantity = float(mat[1])
            scrap_rate = float(mat[2] or 0)
            output_qty = float(mat[3])
            
            # Calculate new required quantity
            production_cycles = new_qty / output_qty
            base_qty = production_cycles * quantity
            required_qty = round(base_qty * (1 + scrap_rate / 100), 4)
            
            # Update
            update_query = text("""
                UPDATE manufacturing_order_materials
                SET required_qty = :required_qty
                WHERE manufacturing_order_id = :order_id 
                AND material_id = :material_id
            """)
            
            conn.execute(update_query, {
                'required_qty': required_qty,
                'order_id': order_id,
                'material_id': material_id
            })
        
        logger.info(f"Recalculated materials for order {order_id} with qty {new_qty}")
