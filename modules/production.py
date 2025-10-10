# modules/production.py - Complete Production Management (Enhanced)
"""
Production Order Management Module
Handles the complete production cycle: Order → Issue → Return → Complete
Enhanced version with:
- Fixed inventory transaction quantities (all positive)
- Return quantity validation
- Actual material usage tracking
- Production efficiency metrics
- Partial production cycle support
"""

import logging
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_UP
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import uuid
import math

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from utils.db import get_db_engine
from modules.inventory import InventoryManager

logger = logging.getLogger(__name__)


# ==================== Enums ====================

class OrderStatus(Enum):
    """Production order status"""
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED" 
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Priority(Enum):
    """Order priority"""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class RoundingStrategy(Enum):
    """Material requirement rounding strategy"""
    ALWAYS_UP = "ALWAYS_UP"  # Always round up (default)
    ALLOW_PARTIAL = "ALLOW_PARTIAL"  # Allow partial cycles
    NEAREST = "NEAREST"  # Round to nearest


# ==================== Main Manager ====================

class ProductionManager:
    """Production Order Management"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self.inv_manager = InventoryManager()
    
    # ==================== Order Creation ====================
    
    def create_order(self, order_data: Dict[str, Any]) -> str:
        """Create new production order"""
        with self.engine.begin() as conn:
            try:
                # Generate order number
                order_no = self._generate_order_number(conn)
                
                # Get entity ID from warehouse
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
                
                # Create material requirements with rounding strategy
                rounding_strategy = order_data.get('rounding_strategy', RoundingStrategy.ALWAYS_UP)
                self._create_material_requirements(conn, order_id, order_data, rounding_strategy)
                
                logger.info(f"Created production order {order_no}")
                return order_no
                
            except Exception as e:
                logger.error(f"Error creating order: {e}")
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
        return f"MO-{timestamp}-{next_num:04d}"
    
    def _create_material_requirements(self, conn, order_id: int, order_data: Dict,
                                     rounding_strategy: RoundingStrategy = RoundingStrategy.ALWAYS_UP):
        """Create material requirements from BOM with flexible rounding"""
        # Get BOM details
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
        
        # Calculate and insert requirements
        for mat in materials:
            # Calculate production cycles
            production_cycles = float(mat['planned_qty']) / float(mat['output_qty'])
            
            # Calculate base material need
            base_material = production_cycles * float(mat['quantity'])
            
            # Apply scrap rate
            with_scrap = base_material * (1 + float(mat['scrap_rate']) / 100)
            
            # Apply rounding strategy
            if rounding_strategy == RoundingStrategy.ALWAYS_UP:
                required_qty = math.ceil(with_scrap)
            elif rounding_strategy == RoundingStrategy.ALLOW_PARTIAL:
                required_qty = with_scrap  # Keep exact amount
            else:  # NEAREST
                required_qty = round(with_scrap)
            
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
    
    # ==================== Material Issue ====================
    
    def issue_materials(self, order_id: int, user_id: int) -> Dict[str, Any]:
        """Issue materials for production using FEFO"""
        with self.engine.begin() as conn:
            try:
                # Get order info
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                # Check status
                if order['status'] not in ['DRAFT', 'CONFIRMED']:
                    raise ValueError(f"Cannot issue materials for {order['status']} order")
                
                # Generate issue number and group ID
                issue_no = self._generate_issue_number(conn)
                group_id = str(uuid.uuid4())
                
                # Create issue header
                issue_query = text("""
                    INSERT INTO material_issues (
                        issue_no, manufacturing_order_id, warehouse_id,
                        issue_date, status, issued_by, created_by, created_date, group_id
                    ) VALUES (
                        :issue_no, :order_id, :warehouse_id,
                        NOW(), 'CONFIRMED', :user_id, :user_id, NOW(), :group_id
                    )
                """)
                
                issue_result = conn.execute(issue_query, {
                    'issue_no': issue_no,
                    'order_id': order_id,
                    'warehouse_id': order['warehouse_id'],
                    'user_id': user_id,
                    'group_id': group_id
                })
                
                issue_id = issue_result.lastrowid
                
                # Get materials to issue
                materials = self._get_pending_materials(conn, order_id)
                issue_details = []
                
                # Issue each material using FEFO
                for _, mat in materials.iterrows():
                    remaining = mat['required_qty'] - mat['issued_qty']
                    if remaining > 0:
                        issued = self._issue_material_fefo(
                            conn, issue_id, order_id, mat,
                            remaining, order['warehouse_id'], group_id, user_id
                        )
                        issue_details.extend(issued)
                
                # Update order status to IN_PROGRESS
                status_query = text("""
                    UPDATE manufacturing_orders
                    SET status = 'IN_PROGRESS', updated_date = NOW()
                    WHERE id = :order_id
                """)
                conn.execute(status_query, {'order_id': order_id})
                
                logger.info(f"Issued materials for order {order_id}")
                
                return {
                    'issue_no': issue_no,
                    'issue_id': issue_id,
                    'details': issue_details
                }
                
            except Exception as e:
                logger.error(f"Error issuing materials: {e}")
                raise
    
    def _issue_material_fefo(self, conn, issue_id: int, order_id: int,
                             material: pd.Series, required_qty: float,
                             warehouse_id: int, group_id: str, user_id: int) -> List[Dict]:
        """Issue single material using FEFO"""
        # Get available batches
        batch_query = text("""
            SELECT 
                id, batch_no, remain, expired_date
            FROM inventory_histories
            WHERE product_id = :material_id
                AND warehouse_id = :warehouse_id
                AND remain > 0
                AND delete_flag = 0
            ORDER BY 
                CASE WHEN expired_date IS NULL THEN 1 ELSE 0 END,
                expired_date ASC,
                created_date ASC
            FOR UPDATE
        """)
        
        batches = conn.execute(batch_query, {
            'material_id': material['material_id'],
            'warehouse_id': warehouse_id
        })
        
        issued_details = []
        remaining = required_qty
        
        for batch in batches:
            if remaining <= 0:
                break
            
            # Skip expired batches
            if batch['expired_date'] and batch['expired_date'] < date.today():
                logger.warning(f"Skipping expired batch {batch['batch_no']}")
                continue
            
            # Calculate quantity to take
            take_qty = min(remaining, float(batch['remain']))
            
            # Create issue detail
            detail_query = text("""
                INSERT INTO material_issue_details (
                    material_issue_id, material_id, quantity, uom,
                    batch_no, inventory_history_id, manufacturing_order_id,
                    created_date
                ) VALUES (
                    :issue_id, :material_id, :quantity, :uom,
                    :batch_no, :inventory_id, :order_id, NOW()
                )
            """)
            
            detail_result = conn.execute(detail_query, {
                'issue_id': issue_id,
                'material_id': material['material_id'],
                'quantity': take_qty,
                'uom': material['uom'],
                'batch_no': batch['batch_no'],
                'inventory_id': batch['id'],
                'order_id': order_id
            })
            
            detail_id = detail_result.lastrowid
            
            # Update inventory remain
            update_query = text("""
                UPDATE inventory_histories
                SET remain = remain - :quantity, updated_date = NOW()
                WHERE id = :inventory_id
            """)
            
            conn.execute(update_query, {
                'quantity': take_qty,
                'inventory_id': batch['id']
            })
            
            # Create stock out record - FIXED: Use positive quantity
            stock_out_query = text("""
                INSERT INTO inventory_histories (
                    type, product_id, warehouse_id, quantity, remain,
                    batch_no, expired_date, action_detail_id, group_id,
                    created_by, created_date, delete_flag
                ) VALUES (
                    'stockOutProduction', :material_id, :warehouse_id,
                    :quantity, 0, :batch_no, :expired_date,
                    :detail_id, :group_id, :user_id, NOW(), 0
                )
            """)
            
            conn.execute(stock_out_query, {
                'material_id': material['material_id'],
                'warehouse_id': warehouse_id,
                'quantity': take_qty,  # FIXED: Positive value
                'batch_no': batch['batch_no'],
                'expired_date': batch['expired_date'],
                'detail_id': detail_id,
                'group_id': group_id,
                'user_id': str(user_id)
            })
            
            # Update material issued quantity
            update_material_query = text("""
                UPDATE manufacturing_order_materials
                SET issued_qty = COALESCE(issued_qty, 0) + :quantity,
                    status = CASE 
                        WHEN COALESCE(issued_qty, 0) + :quantity >= required_qty 
                        THEN 'ISSUED' ELSE 'PARTIAL' 
                    END,
                    updated_date = NOW()
                WHERE manufacturing_order_id = :order_id
                    AND material_id = :material_id
            """)
            
            conn.execute(update_material_query, {
                'quantity': take_qty,
                'order_id': order_id,
                'material_id': material['material_id']
            })
            
            issued_details.append({
                'material_id': material['material_id'],
                'material_name': material['material_name'],
                'batch_no': batch['batch_no'],
                'quantity': take_qty,
                'uom': material['uom'],
                'expired_date': batch['expired_date']
            })
            
            remaining -= take_qty
        
        # Log if insufficient stock
        if remaining > 0:
            logger.warning(f"Insufficient stock for material {material['material_id']}: "
                         f"short by {remaining} {material['uom']}")
        
        return issued_details
    
    # ==================== Material Return with Validation ====================
    
    def validate_return_quantity(self, issue_detail_id: int, return_qty: float) -> bool:
        """Validate return quantity doesn't exceed issued quantity"""
        query = """
            SELECT 
                mid.quantity as issued_qty,
                COALESCE(SUM(mrd.quantity), 0) as previously_returned
            FROM material_issue_details mid
            LEFT JOIN material_return_details mrd 
                ON mrd.original_issue_detail_id = mid.id
            LEFT JOIN material_returns mr 
                ON mr.id = mrd.material_return_id AND mr.status = 'CONFIRMED'
            WHERE mid.id = %s
            GROUP BY mid.quantity
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(issue_detail_id,))
            if result.empty:
                raise ValueError(f"Issue detail {issue_detail_id} not found")
            
            row = result.iloc[0]
            total_returns = float(row['previously_returned']) + return_qty
            
            if total_returns > float(row['issued_qty']):
                raise ValueError(
                    f"Cannot return {return_qty}. "
                    f"Issued: {row['issued_qty']}, "
                    f"Previously returned: {row['previously_returned']}, "
                    f"Total would be: {total_returns}"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating return quantity: {e}")
            raise
    
    def return_materials(self, order_id: int, returns: List[Dict],
                        reason: str, user_id: int) -> Dict[str, Any]:
        """Return unused materials with validation"""
        with self.engine.begin() as conn:
            try:
                # Get order info
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                # Get material issue
                issue_query = text("""
                    SELECT id FROM material_issues
                    WHERE manufacturing_order_id = :order_id
                    AND status = 'CONFIRMED'
                    ORDER BY created_date DESC
                    LIMIT 1
                """)
                
                issue_result = conn.execute(issue_query, {'order_id': order_id})
                issue = issue_result.fetchone()
                if not issue:
                    raise ValueError("No material issue found for this order")
                
                # Validate all returns before processing
                for ret in returns:
                    self.validate_return_quantity(
                        ret['issue_detail_id'], 
                        ret['quantity']
                    )
                
                # Generate return number
                return_no = self._generate_return_number(conn)
                
                # Create return header
                return_query = text("""
                    INSERT INTO material_returns (
                        return_no, material_issue_id, manufacturing_order_id,
                        return_date, warehouse_id, status, reason,
                        created_by, created_date
                    ) VALUES (
                        :return_no, :issue_id, :order_id,
                        NOW(), :warehouse_id, 'CONFIRMED', :reason,
                        :created_by, NOW()
                    )
                """)
                
                return_result = conn.execute(return_query, {
                    'return_no': return_no,
                    'issue_id': issue['id'],
                    'order_id': order_id,
                    'warehouse_id': order['warehouse_id'],
                    'reason': reason,
                    'created_by': str(user_id)
                })
                
                return_id = return_result.lastrowid
                return_details = []
                
                # Process each return
                for ret in returns:
                    # Create return detail
                    detail_query = text("""
                        INSERT INTO material_return_details (
                            material_return_id, material_id,
                            original_issue_detail_id, batch_no,
                            quantity, uom, condition, expired_date
                        ) VALUES (
                            :return_id, :material_id,
                            :issue_detail_id, :batch_no,
                            :quantity, :uom, :condition, :expired_date
                        )
                    """)
                    
                    conn.execute(detail_query, {
                        'return_id': return_id,
                        'material_id': ret['material_id'],
                        'issue_detail_id': ret['issue_detail_id'],
                        'batch_no': ret['batch_no'],
                        'quantity': ret['quantity'],
                        'uom': ret['uom'],
                        'condition': ret.get('condition', 'GOOD'),
                        'expired_date': ret.get('expired_date')
                    })
                    
                    # Create stock in record - Positive quantity
                    stock_in_query = text("""
                        INSERT INTO inventory_histories (
                            type, product_id, warehouse_id, quantity, remain,
                            batch_no, expired_date, created_by, created_date
                        ) VALUES (
                            'stockInProductionReturn', :material_id, :warehouse_id,
                            :quantity, :quantity, :batch_no, :expired_date,
                            :created_by, NOW()
                        )
                    """)
                    
                    conn.execute(stock_in_query, {
                        'material_id': ret['material_id'],
                        'warehouse_id': order['warehouse_id'],
                        'quantity': ret['quantity'],  # Positive value
                        'batch_no': ret['batch_no'],
                        'expired_date': ret.get('expired_date'),
                        'created_by': str(user_id)
                    })
                    
                    return_details.append({
                        'material_id': ret['material_id'],
                        'batch_no': ret['batch_no'],
                        'quantity': ret['quantity'],
                        'condition': ret.get('condition', 'GOOD')
                    })
                
                logger.info(f"Returned materials for order {order_id}")
                
                return {
                    'return_no': return_no,
                    'return_id': return_id,
                    'details': return_details
                }
                
            except Exception as e:
                logger.error(f"Error returning materials: {e}")
                raise
    
    # ==================== Production Completion ====================
    
    def complete_production(self, order_id: int, produced_qty: float,
                           batch_no: str, quality_status: str,
                           notes: str, user_id: int,
                           expired_date: Optional[date] = None) -> Dict[str, Any]:
        """Complete production order"""
        with self.engine.begin() as conn:
            try:
                # Get order info
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                # Check status
                if order['status'] != 'IN_PROGRESS':
                    raise ValueError(f"Cannot complete {order['status']} order")
                
                # Generate receipt number
                receipt_no = self._generate_receipt_number(conn)
                
                # Calculate expiry if not provided
                if not expired_date and order.get('shelf_life'):
                    expired_date = date.today() + timedelta(days=order['shelf_life'])
                
                # Create production receipt
                receipt_query = text("""
                    INSERT INTO production_receipts (
                        receipt_no, manufacturing_order_id, receipt_date,
                        product_id, quantity, uom, batch_no, expired_date,
                        warehouse_id, quality_status, notes,
                        created_by, created_date
                    ) VALUES (
                        :receipt_no, :order_id, NOW(),
                        :product_id, :quantity, :uom, :batch_no, :expired_date,
                        :warehouse_id, :quality_status, :notes,
                        :created_by, NOW()
                    )
                """)
                
                receipt_result = conn.execute(receipt_query, {
                    'receipt_no': receipt_no,
                    'order_id': order_id,
                    'product_id': order['product_id'],
                    'quantity': produced_qty,
                    'uom': order['uom'],
                    'batch_no': batch_no,
                    'expired_date': expired_date,
                    'warehouse_id': order['target_warehouse_id'],
                    'quality_status': quality_status,
                    'notes': notes,
                    'created_by': user_id
                })
                
                receipt_id = receipt_result.lastrowid
                
                # Create stock in record - Positive quantity
                stock_in_query = text("""
                    INSERT INTO inventory_histories (
                        type, product_id, warehouse_id, quantity, remain,
                        batch_no, expired_date, action_detail_id,
                        created_by, created_date
                    ) VALUES (
                        'stockInProduction', :product_id, :warehouse_id,
                        :quantity, :quantity, :batch_no, :expired_date,
                        :receipt_id, :created_by, NOW()
                    )
                """)
                
                conn.execute(stock_in_query, {
                    'product_id': order['product_id'],
                    'warehouse_id': order['target_warehouse_id'],
                    'quantity': produced_qty,  # Positive value
                    'batch_no': batch_no,
                    'expired_date': expired_date,
                    'receipt_id': receipt_id,
                    'created_by': str(user_id)
                })
                
                # Update order status
                update_query = text("""
                    UPDATE manufacturing_orders
                    SET produced_qty = :produced_qty,
                        status = 'COMPLETED',
                        completion_date = NOW(),
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(update_query, {
                    'produced_qty': produced_qty,
                    'user_id': user_id,
                    'order_id': order_id
                })
                
                logger.info(f"Completed production order {order_id}")
                
                return {
                    'receipt_no': receipt_no,
                    'receipt_id': receipt_id,
                    'batch_no': batch_no,
                    'quantity': produced_qty,
                    'quality_status': quality_status
                }
                
            except Exception as e:
                logger.error(f"Error completing production: {e}")
                raise
    
    # ==================== Material Usage & Efficiency ====================
    
    def get_actual_material_usage(self, order_id: int) -> pd.DataFrame:
        """Calculate actual material usage = issued - returned"""
        query = """
            SELECT 
                mom.material_id,
                p.name as material_name,
                mom.required_qty,
                COALESCE(mom.issued_qty, 0) as issued_qty,
                COALESCE(returns.returned_qty, 0) as returned_qty,
                COALESCE(mom.issued_qty, 0) - COALESCE(returns.returned_qty, 0) as actual_used_qty,
                mom.uom,
                CASE 
                    WHEN mom.required_qty > 0 AND mom.issued_qty > 0 
                    THEN ROUND(((COALESCE(mom.issued_qty, 0) - COALESCE(returns.returned_qty, 0)) / mom.required_qty * 100), 2)
                    ELSE 0 
                END as usage_efficiency_pct,
                CASE
                    WHEN COALESCE(mom.issued_qty, 0) - COALESCE(returns.returned_qty, 0) > mom.required_qty 
                    THEN 'OVER_USED'
                    WHEN COALESCE(mom.issued_qty, 0) - COALESCE(returns.returned_qty, 0) < mom.required_qty 
                    THEN 'UNDER_USED'
                    ELSE 'EXACT'
                END as usage_status
            FROM manufacturing_order_materials mom
            JOIN products p ON p.id = mom.material_id
            LEFT JOIN (
                SELECT 
                    mr.manufacturing_order_id,
                    mrd.material_id,
                    SUM(mrd.quantity) as returned_qty
                FROM material_return_details mrd
                JOIN material_returns mr ON mr.id = mrd.material_return_id
                WHERE mr.status = 'CONFIRMED'
                GROUP BY mr.manufacturing_order_id, mrd.material_id
            ) returns ON returns.manufacturing_order_id = mom.manufacturing_order_id
                AND returns.material_id = mom.material_id
            WHERE mom.manufacturing_order_id = %s
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting actual material usage: {e}")
            return pd.DataFrame()
    
    def calculate_production_efficiency(self, order_id: int) -> Dict[str, Any]:
        """Calculate comprehensive production efficiency metrics"""
        try:
            # Get order details
            order = self.get_order_details(order_id)
            if not order:
                return {}
            
            # Production efficiency
            production_efficiency = 0
            if order['planned_qty'] > 0:
                production_efficiency = (order['produced_qty'] / order['planned_qty']) * 100
            
            # Material usage efficiency
            material_usage = self.get_actual_material_usage(order_id)
            
            # Calculate weighted average material efficiency
            total_material_cost = 0
            weighted_efficiency = 0
            
            if not material_usage.empty:
                # Note: You need to add unit_cost to the query or fetch it separately
                for _, mat in material_usage.iterrows():
                    # Simplified calculation - you may want to get actual costs
                    material_value = mat['actual_used_qty']  # * unit_cost
                    total_material_cost += material_value
                    weighted_efficiency += mat['usage_efficiency_pct'] * material_value
                
                if total_material_cost > 0:
                    weighted_efficiency = weighted_efficiency / total_material_cost
            
            # Time efficiency
            time_efficiency = None
            if order.get('completion_date') and order.get('scheduled_date'):
                scheduled = pd.to_datetime(order['scheduled_date'])
                completed = pd.to_datetime(order['completion_date'])
                days_diff = (completed - scheduled).days
                
                if days_diff <= 0:
                    time_efficiency = 100  # On time or early
                else:
                    time_efficiency = max(0, 100 - (days_diff * 10))  # -10% per day late
            
            # Scrap rate calculation
            total_scrap = 0
            if not material_usage.empty:
                total_scrap = material_usage[
                    material_usage['actual_used_qty'] > material_usage['required_qty']
                ]['actual_used_qty'].sum() - material_usage[
                    material_usage['actual_used_qty'] > material_usage['required_qty']
                ]['required_qty'].sum()
            
            return {
                'order_id': order_id,
                'order_no': order.get('order_no'),
                'production_efficiency_pct': round(production_efficiency, 2),
                'material_efficiency_pct': round(weighted_efficiency, 2) if weighted_efficiency else None,
                'time_efficiency_pct': round(time_efficiency, 2) if time_efficiency else None,
                'total_material_cost': total_material_cost,
                'total_scrap_qty': total_scrap,
                'material_details': material_usage.to_dict('records') if not material_usage.empty else [],
                'status': order['status'],
                'planned_qty': order['planned_qty'],
                'produced_qty': order['produced_qty']
            }
            
        except Exception as e:
            logger.error(f"Error calculating production efficiency: {e}")
            return {}
    
    # ==================== Query Methods ====================
    
    def get_orders(self, status: Optional[str] = None,
                  order_type: Optional[str] = None,
                  from_date: Optional[date] = None,
                  to_date: Optional[date] = None,
                  priority: Optional[str] = None,
                  page: int = 1, page_size: int = 100) -> pd.DataFrame:
        """Get production orders with filters - includes warehouse IDs"""
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
        
        # Add pagination
        offset = (page - 1) * page_size
        query += " LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params))
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return pd.DataFrame()
    
    def get_order_details(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get order details with warehouse IDs"""
        query = """
            SELECT 
                o.*,
                p.name as product_name,
                b.bom_name,
                b.bom_type,
                o.warehouse_id,
                w1.name as warehouse_name,
                o.target_warehouse_id,
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
            logger.error(f"Error getting order details: {e}")
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
            logger.error(f"Error getting order materials: {e}")
            return pd.DataFrame()
    
    def get_returnable_materials(self, order_id: int) -> pd.DataFrame:
        """Get materials that can be returned"""
        query = """
            SELECT 
                mid.id as issue_detail_id,
                mid.material_id,
                p.name as material_name,
                mid.batch_no,
                mid.quantity as issued_qty,
                COALESCE(returned.qty, 0) as returned_qty,
                (mid.quantity - COALESCE(returned.qty, 0)) as returnable_qty,
                mid.uom,
                ih.expired_date
            FROM material_issue_details mid
            JOIN material_issues mi ON mid.material_issue_id = mi.id
            JOIN products p ON mid.material_id = p.id
            LEFT JOIN inventory_histories ih ON mid.inventory_history_id = ih.id
            LEFT JOIN (
                SELECT 
                    mrd.original_issue_detail_id,
                    SUM(mrd.quantity) as qty
                FROM material_return_details mrd
                JOIN material_returns mr ON mrd.material_return_id = mr.id
                WHERE mr.status = 'CONFIRMED'
                GROUP BY mrd.original_issue_detail_id
            ) returned ON returned.original_issue_detail_id = mid.id
            WHERE mi.manufacturing_order_id = %s
                AND mi.status = 'CONFIRMED'
            HAVING returnable_qty > 0
            ORDER BY p.name, mid.batch_no
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting returnable materials: {e}")
            return pd.DataFrame()
    
    def calculate_material_requirements(self, bom_id: int, 
                                       quantity: float) -> pd.DataFrame:
        """Calculate material requirements"""
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
            logger.error(f"Error calculating requirements: {e}")
            return pd.DataFrame()
    
    def update_order_status(self, order_id: int, new_status: str,
                          user_id: Optional[int] = None) -> bool:
        """Update order status"""
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
                
                return result.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error updating order status: {e}")
                return False
    
    # ==================== Analytics & Reports ====================
    
    def get_production_summary(self, from_date: date, to_date: date) -> Dict[str, Any]:
        """Get production summary statistics"""
        try:
            # Orders summary
            orders_query = """
                SELECT 
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_orders,
                    SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress_orders,
                    SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_orders,
                    AVG(CASE WHEN status = 'COMPLETED' THEN produced_qty / planned_qty * 100 ELSE NULL END) as avg_completion_rate
                FROM manufacturing_orders
                WHERE order_date BETWEEN %s AND %s
                    AND delete_flag = 0
            """
            
            orders_stats = pd.read_sql(orders_query, self.engine, params=(from_date, to_date))
            
            # Material efficiency
            material_query = """
                SELECT 
                    AVG(efficiency.usage_efficiency_pct) as avg_material_efficiency
                FROM (
                    SELECT 
                        mo.id,
                        AVG(CASE 
                            WHEN mom.required_qty > 0 
                            THEN ((mom.issued_qty - COALESCE(ret.returned_qty, 0)) / mom.required_qty * 100)
                            ELSE 0 
                        END) as usage_efficiency_pct
                    FROM manufacturing_orders mo
                    JOIN manufacturing_order_materials mom ON mom.manufacturing_order_id = mo.id
                    LEFT JOIN (
                        SELECT 
                            mr.manufacturing_order_id,
                            mrd.material_id,
                            SUM(mrd.quantity) as returned_qty
                        FROM material_return_details mrd
                        JOIN material_returns mr ON mr.id = mrd.material_return_id
                        WHERE mr.status = 'CONFIRMED'
                        GROUP BY mr.manufacturing_order_id, mrd.material_id
                    ) ret ON ret.manufacturing_order_id = mo.id AND ret.material_id = mom.material_id
                    WHERE mo.order_date BETWEEN %s AND %s
                        AND mo.status = 'COMPLETED'
                        AND mo.delete_flag = 0
                    GROUP BY mo.id
                ) efficiency
            """
            
            material_stats = pd.read_sql(material_query, self.engine, params=(from_date, to_date))
            
            return {
                'period': {
                    'from_date': from_date.isoformat(),
                    'to_date': to_date.isoformat()
                },
                'orders': orders_stats.iloc[0].to_dict() if not orders_stats.empty else {},
                'material_efficiency': material_stats.iloc[0].to_dict() if not material_stats.empty else {}
            }
            
        except Exception as e:
            logger.error(f"Error getting production summary: {e}")
            return {}
    
    # ==================== Helper Methods ====================
    
    def _get_order_info(self, conn, order_id: int) -> Optional[Dict]:
        """Get order information for internal use"""
        query = text("""
            SELECT o.*, b.bom_type, p.shelf_life
            FROM manufacturing_orders o
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN products p ON o.product_id = p.id
            WHERE o.id = :order_id AND o.delete_flag = 0
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'order_id': order_id})
        row = result.fetchone()
        return dict(row) if row else None
    
    def _get_pending_materials(self, conn, order_id: int) -> pd.DataFrame:
        """Get pending materials for order"""
        query = """
            SELECT 
                m.material_id,
                p.name as material_name,
                m.required_qty,
                COALESCE(m.issued_qty, 0) as issued_qty,
                m.uom
            FROM manufacturing_order_materials m
            JOIN products p ON m.material_id = p.id
            WHERE m.manufacturing_order_id = %s
            ORDER BY p.name
        """
        
        return pd.read_sql(query, conn, params=(order_id,))
    
    def _generate_issue_number(self, conn) -> str:
        """Generate material issue number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(issue_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM material_issues
            WHERE issue_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'MI-{timestamp}-%'})
        next_num = result.fetchone()['next_num']
        return f"MI-{timestamp}-{next_num:04d}"
    
    def _generate_return_number(self, conn) -> str:
        """Generate material return number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(return_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM material_returns
            WHERE return_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'MR-{timestamp}-%'})
        next_num = result.fetchone()['next_num']
        return f"MR-{timestamp}-{next_num:04d}"
    
    def _generate_receipt_number(self, conn) -> str:
        """Generate production receipt number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(receipt_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM production_receipts
            WHERE receipt_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'PR-{timestamp}-%'})
        next_num = result.fetchone()['next_num']
        return f"PR-{timestamp}-{next_num:04d}"