# utils/production/returns/manager.py
"""
Return Manager - Business logic for Material Returns
Return unused materials with validation and inventory updates

Version: 1.0.0
Based on: materials.py return_materials function
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

import pandas as pd
from sqlalchemy import text

from utils.db import get_db_engine
from .common import get_vietnam_now

logger = logging.getLogger(__name__)


class ReturnManager:
    """Business logic for Material Return management"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Return Materials ====================
    
    def return_materials(self, order_id: int, returns: List[Dict],
                        reason: str, user_id: int, keycloak_id: str,
                        returned_by: int = None, received_by: int = None) -> Dict[str, Any]:
        """
        Return unused materials with validation and proper tracking
        
        Args:
            order_id: Production order ID
            returns: List of return items with issue_detail_id, quantity, condition
            reason: Return reason code (EXCESS, DEFECT, WRONG_MATERIAL, PLAN_CHANGE, OTHER)
            user_id: User ID for created_by (INT)
            keycloak_id: Keycloak ID for inventory tables (VARCHAR)
            returned_by: Employee ID of production staff returning materials
            received_by: Employee ID of warehouse staff receiving materials
        
        Returns:
            Dictionary with return_no, return_id, details
        
        Raises:
            ValueError: If validation fails
        """
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
                issue_row = issue_result.fetchone()
                if not issue_row:
                    raise ValueError("No material issue found for this order")
                
                issue = dict(zip(issue_result.keys(), issue_row))
                
                # Validate all returns
                for ret in returns:
                    self._validate_return(conn, ret)
                
                # Generate return number
                return_no = self._generate_return_number(conn)
                group_id = str(uuid.uuid4())
                
                # Create return header
                return_query = text("""
                    INSERT INTO material_returns (
                        return_no, material_issue_id, manufacturing_order_id,
                        return_date, warehouse_id, status,
                        returned_by, received_by,
                        reason, created_by, created_date
                    ) VALUES (
                        :return_no, :issue_id, :order_id,
                        NOW(), :warehouse_id, 'CONFIRMED',
                        :returned_by, :received_by,
                        :reason, :user_id, NOW()
                    )
                """)
                
                return_result = conn.execute(return_query, {
                    'return_no': return_no,
                    'issue_id': issue['id'],
                    'order_id': order_id,
                    'warehouse_id': order['warehouse_id'],
                    'returned_by': returned_by,
                    'received_by': received_by,
                    'user_id': user_id,
                    'reason': reason
                })
                
                return_id = return_result.lastrowid
                
                # Create return details and update inventory
                return_details = []
                
                for ret in returns:
                    detail = self._process_return_item(
                        conn, return_id, ret, order['warehouse_id'],
                        group_id, user_id, keycloak_id,
                        order.get('entity_id', 1)
                    )
                    return_details.append(detail)
                
                # Update manufacturing_order_materials issued quantities
                self._update_order_materials_for_return(conn, return_details, order_id)
                
                logger.info(f"✅ Created return {return_no} for order {order_id}")
                
                return {
                    'return_no': return_no,
                    'return_id': return_id,
                    'details': return_details
                }
                
            except Exception as e:
                logger.error(f"❌ Error processing returns for order {order_id}: {e}")
                raise
    
    # ==================== Private Helper Methods ====================
    
    def _get_order_info(self, conn, order_id: int) -> Optional[Dict]:
        """Get order information"""
        query = text("""
            SELECT 
                mo.id, mo.order_no, mo.product_id,
                mo.warehouse_id, mo.status, mo.entity_id
            FROM manufacturing_orders mo
            WHERE mo.id = :order_id AND mo.delete_flag = 0
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'order_id': order_id})
        row = result.fetchone()
        
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _validate_return(self, conn, return_item: Dict):
        """Validate a single return item"""
        query = text("""
            SELECT 
                mid.id,
                mid.quantity as issued_qty,
                COALESCE(SUM(mrd.quantity), 0) as returned_qty
            FROM material_issue_details mid
            LEFT JOIN material_return_details mrd 
                ON mrd.original_issue_detail_id = mid.id
            LEFT JOIN material_returns mr 
                ON mr.id = mrd.material_return_id AND mr.status = 'CONFIRMED'
            WHERE mid.id = :issue_detail_id
            GROUP BY mid.id, mid.quantity
        """)
        
        result = conn.execute(query, {'issue_detail_id': return_item['issue_detail_id']})
        row = result.fetchone()
        
        if not row:
            raise ValueError(f"Issue detail {return_item['issue_detail_id']} not found")
        
        data = dict(zip(result.keys(), row))
        returnable = float(data['issued_qty']) - float(data['returned_qty'])
        
        if return_item['quantity'] > returnable:
            raise ValueError(
                f"Cannot return {return_item['quantity']} - "
                f"only {returnable} returnable"
            )
    
    def _generate_return_number(self, conn) -> str:
        """Generate unique return number MR-YYYYMMDD-XXX"""
        timestamp = get_vietnam_now().strftime('%Y%m%d')
        prefix = f"MR-{timestamp}-"
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(return_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM material_returns
            WHERE return_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'{prefix}%'})
        row = result.fetchone()
        next_num = int(row[0]) if row and row[0] else 1
        
        return f"{prefix}{next_num:03d}"
    
    def _process_return_item(self, conn, return_id: int, return_item: Dict,
                            warehouse_id: int, group_id: str,
                            user_id: int, keycloak_id: str,
                            entity_id: int) -> Dict[str, Any]:
        """Process a single return item"""
        # Get issue detail info
        query = text("""
            SELECT 
                mid.material_id,
                mid.batch_no,
                mid.uom,
                mid.expired_date,
                mid.is_alternative,
                mid.original_material_id,
                mid.manufacturing_order_material_id
            FROM material_issue_details mid
            WHERE mid.id = :issue_detail_id
        """)
        
        result = conn.execute(query, {'issue_detail_id': return_item['issue_detail_id']})
        row = result.fetchone()
        issue_detail = dict(zip(result.keys(), row))
        
        # Insert return detail
        detail_query = text("""
            INSERT INTO material_return_details (
                material_return_id, material_id, original_issue_detail_id,
                batch_no, quantity, uom, `condition`, expired_date
            ) VALUES (
                :return_id, :material_id, :issue_detail_id,
                :batch_no, :quantity, :uom, :condition, :expired_date
            )
        """)
        
        detail_result = conn.execute(detail_query, {
            'return_id': return_id,
            'material_id': issue_detail['material_id'],
            'issue_detail_id': return_item['issue_detail_id'],
            'batch_no': issue_detail['batch_no'],
            'quantity': return_item['quantity'],
            'uom': issue_detail['uom'],
            'condition': return_item.get('condition', 'GOOD'),
            'expired_date': issue_detail['expired_date']
        })
        
        return_detail_id = detail_result.lastrowid
        
        # Add back to inventory if condition is GOOD
        if return_item.get('condition', 'GOOD') == 'GOOD':
            self._update_inventory_for_return(
                conn, issue_detail, return_item['quantity'],
                warehouse_id, group_id, keycloak_id, return_detail_id
            )
        
        return {
            'material_id': issue_detail['material_id'],
            'quantity': return_item['quantity'],
            'condition': return_item.get('condition', 'GOOD'),
            'is_alternative': issue_detail['is_alternative'],
            'original_issue_detail_id': return_item['issue_detail_id'],
            'manufacturing_order_material_id': issue_detail['manufacturing_order_material_id']
        }
    
    def _update_inventory_for_return(self, conn, issue_detail: Dict, quantity: float,
                                     warehouse_id: int, group_id: str,
                                     keycloak_id: str, return_detail_id: int):
        """Update inventory for material return"""
        # Create stockInProductionReturn record
        inv_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type,
                quantity, remain, batch_no, expired_date,
                group_id, action_detail_id,
                created_by, created_date
            ) VALUES (
                :material_id, :warehouse_id, 'stockInProductionReturn',
                :quantity, :quantity, :batch_no, :expired_date,
                :group_id, :action_detail_id,
                :created_by, NOW()
            )
        """)
        
        conn.execute(inv_query, {
            'material_id': issue_detail['material_id'],
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'batch_no': issue_detail['batch_no'],
            'expired_date': issue_detail['expired_date'],
            'group_id': group_id,
            'action_detail_id': return_detail_id,
            'created_by': keycloak_id
        })
    
    def _update_order_materials_for_return(self, conn, return_details: List[Dict],
                                           order_id: int):
        """Update manufacturing_order_materials after return"""
        for detail in return_details:
            # Get conversion info if alternative
            mom_id = detail.get('manufacturing_order_material_id')
            if not mom_id:
                continue
            
            return_qty = float(detail['quantity'])
            
            # Calculate equivalent quantity
            if detail.get('is_alternative'):
                conversion_ratio = self._get_conversion_ratio(
                    conn, mom_id, detail['material_id']
                )
                equivalent_returned = return_qty / conversion_ratio
            else:
                equivalent_returned = return_qty
            
            # Update issued_qty with equivalent
            update_query = text("""
                UPDATE manufacturing_order_materials
                SET issued_qty = GREATEST(0, COALESCE(issued_qty, 0) - :equivalent_qty),
                    status = CASE 
                        WHEN COALESCE(issued_qty, 0) - :equivalent_qty <= 0 THEN 'PENDING'
                        WHEN COALESCE(issued_qty, 0) - :equivalent_qty < required_qty THEN 'PARTIAL'
                        ELSE 'ISSUED'
                    END
                WHERE id = :order_material_id
            """)
            
            conn.execute(update_query, {
                'equivalent_qty': equivalent_returned,
                'order_material_id': mom_id
            })
            
            logger.info(
                f"📦 Returned {return_qty} (equivalent: {equivalent_returned:.4f}) "
                f"for material_id {detail['material_id']}"
            )
    
    def _get_conversion_ratio(self, conn, order_material_id: int,
                              alternative_material_id: int) -> float:
        """Get conversion ratio for alternative material"""
        query = text("""
            SELECT 
                bd.quantity as primary_qty,
                alt.quantity as alt_qty
            FROM manufacturing_order_materials mom
            JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id
                AND bd.material_id = mom.material_id
            JOIN bom_material_alternatives alt ON alt.bom_detail_id = bd.id
                AND alt.alternative_material_id = :alt_material_id
            WHERE mom.id = :order_material_id
            LIMIT 1
        """)
        
        result = conn.execute(query, {
            'order_material_id': order_material_id,
            'alt_material_id': alternative_material_id
        })
        row = result.fetchone()
        
        if row:
            data = dict(zip(result.keys(), row))
            return float(data['alt_qty']) / float(data['primary_qty'])
        
        return 1.0  # Default ratio if not found
