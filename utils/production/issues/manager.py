# utils/production/issues/manager.py
"""
Issue Manager - Business logic for Material Issues
Issue materials using FEFO with alternative substitution

Version: 1.0.0
Based on: materials.py v8.2
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


class IssueManager:
    """Business logic for Material Issue management"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Issue Materials ====================
    
    def issue_materials(self, order_id: int, user_id: int, keycloak_id: str,
                       issued_by: int, received_by: int = None,
                       notes: str = None,
                       custom_quantities: Dict[int, float] = None,
                       use_alternatives: Dict[int, bool] = None,
                       alternative_quantities: Dict[str, float] = None) -> Dict[str, Any]:
        """
        Issue materials for production using FEFO (First Expiry, First Out)
        with automatic alternative material substitution
        
        Args:
            order_id: Manufacturing order ID
            user_id: User ID for created_by (INT)
            keycloak_id: Keycloak ID for inventory tables (VARCHAR)
            issued_by: Employee ID of warehouse staff (REQUIRED)
            received_by: Employee ID of production staff
            notes: Optional notes
            custom_quantities: Dict {material_id: quantity} for custom amounts
            use_alternatives: Dict {material_id: bool} for using alternatives
            alternative_quantities: Dict {"material_id_alt_id": quantity} for alternative amounts
        
        Returns:
            Dictionary with issue_no, issue_id, details, substitutions
        
        Raises:
            ValueError: If validation fails
        """
        if issued_by is None:
            raise ValueError("issued_by is required")
        
        with self.engine.begin() as conn:
            try:
                # Get order info
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                if order['status'] not in ['DRAFT', 'CONFIRMED', 'IN_PROGRESS']:
                    raise ValueError(f"Cannot issue materials for {order['status']} order")
                
                # Generate issue number
                issue_no = self._generate_issue_number(conn)
                group_id = str(uuid.uuid4())
                
                # Create issue header
                issue_query = text("""
                    INSERT INTO material_issues (
                        issue_no, manufacturing_order_id, warehouse_id,
                        issue_date, status, issued_by, received_by, notes,
                        created_by, created_date, group_id
                    ) VALUES (
                        :issue_no, :order_id, :warehouse_id,
                        NOW(), 'CONFIRMED', :issued_by, :received_by, :notes,
                        :user_id, NOW(), :group_id
                    )
                """)
                
                issue_result = conn.execute(issue_query, {
                    'issue_no': issue_no,
                    'order_id': order_id,
                    'warehouse_id': order['warehouse_id'],
                    'issued_by': issued_by,
                    'received_by': received_by,
                    'notes': notes,
                    'user_id': user_id,
                    'group_id': group_id
                })
                
                issue_id = issue_result.lastrowid
                
                # Get materials to issue
                materials = self._get_pending_materials(conn, order_id)
                issue_details = []
                substitutions = []
                
                # Issue each material
                for _, mat in materials.iterrows():
                    material_id = int(mat['material_id'])
                    
                    # Determine quantity for primary material
                    if custom_quantities and material_id in custom_quantities:
                        qty_to_issue = float(custom_quantities[material_id])
                    else:
                        qty_to_issue = float(mat['required_qty']) - float(mat['issued_qty'])
                    
                    # Check if there's any alternative quantity to issue
                    has_alt_qty = False
                    if alternative_quantities:
                        for key in alternative_quantities:
                            if key.startswith(f"{material_id}_") and alternative_quantities[key] > 0:
                                has_alt_qty = True
                                break
                    
                    # Process if primary > 0 OR has alternatives with quantity
                    if qty_to_issue > 0 or has_alt_qty:
                        should_use_alternatives = (
                            use_alternatives and 
                            use_alternatives.get(material_id, False)
                        )
                        
                        # Validate stock only for primary if issuing primary
                        if qty_to_issue > 0:
                            available = self._get_available_stock(
                                conn, material_id, order['warehouse_id']
                            )
                            if qty_to_issue > available and not should_use_alternatives:
                                raise ValueError(
                                    f"Cannot issue {qty_to_issue} of {mat['material_name']} - "
                                    f"only {available} available"
                                )
                        
                        try:
                            issued = self._issue_material_with_alternatives(
                                conn, issue_id, order_id, mat,
                                qty_to_issue, order['warehouse_id'],
                                group_id, user_id, keycloak_id,
                                order.get('entity_id', 1),
                                alternative_quantities=alternative_quantities
                            )
                            issue_details.extend(issued['details'])
                            if issued['substitutions']:
                                substitutions.extend(issued['substitutions'])
                        except ValueError as e:
                            logger.error(f"Failed to issue {mat['material_name']}: {e}")
                            raise
                
                # Update order status
                status_query = text("""
                    UPDATE manufacturing_orders
                    SET status = 'IN_PROGRESS',
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                conn.execute(status_query, {'order_id': order_id, 'user_id': user_id})
                
                logger.info(f"✅ Issued materials for order {order_id}, issue no: {issue_no}")
                
                return {
                    'issue_no': issue_no,
                    'issue_id': issue_id,
                    'details': issue_details,
                    'substitutions': substitutions
                }
                
            except Exception as e:
                logger.error(f"❌ Error issuing materials: {e}")
                raise
    
    # ==================== Private Helper Methods ====================
    
    def _get_order_info(self, conn, order_id: int) -> Optional[Dict]:
        """Get order information"""
        query = text("""
            SELECT 
                mo.id, mo.order_no, mo.bom_header_id, mo.product_id,
                mo.planned_qty, mo.uom, mo.warehouse_id, mo.target_warehouse_id,
                mo.status, mo.entity_id,
                p.name as product_name
            FROM manufacturing_orders mo
            JOIN products p ON mo.product_id = p.id
            WHERE mo.id = :order_id AND mo.delete_flag = 0
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'order_id': order_id})
        row = result.fetchone()
        
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _get_pending_materials(self, conn, order_id: int) -> pd.DataFrame:
        """Get materials with pending quantities"""
        query = """
            SELECT 
                mom.id as order_material_id,
                mom.material_id,
                p.name as material_name,
                mom.required_qty,
                COALESCE(mom.issued_qty, 0) as issued_qty,
                mom.uom
            FROM manufacturing_order_materials mom
            JOIN products p ON mom.material_id = p.id
            WHERE mom.manufacturing_order_id = %s
                AND mom.required_qty > COALESCE(mom.issued_qty, 0)
            ORDER BY p.name
        """
        
        return pd.read_sql(query, conn, params=(order_id,))
    
    def _get_available_stock(self, conn, material_id: int, warehouse_id: int) -> float:
        """Get available stock for a material"""
        query = text("""
            SELECT COALESCE(SUM(remain), 0) as available
            FROM inventory_histories
            WHERE product_id = :material_id
                AND warehouse_id = :warehouse_id
                AND remain > 0
                AND delete_flag = 0
        """)
        
        result = conn.execute(query, {
            'material_id': material_id,
            'warehouse_id': warehouse_id
        })
        row = result.fetchone()
        return float(row[0]) if row else 0.0
    
    def _generate_issue_number(self, conn) -> str:
        """Generate unique issue number MI-YYYYMMDD-XXX"""
        timestamp = get_vietnam_now().strftime('%Y%m%d')
        prefix = f"MI-{timestamp}-"
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(issue_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM material_issues
            WHERE issue_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'{prefix}%'})
        row = result.fetchone()
        next_num = int(row[0]) if row and row[0] else 1
        
        return f"{prefix}{next_num:03d}"
    
    def _issue_material_with_alternatives(self, conn, issue_id: int, order_id: int,
                                         material: pd.Series, required_qty: float,
                                         warehouse_id: int, group_id: str,
                                         user_id: int, keycloak_id: str,
                                         entity_id: int,
                                         alternative_quantities: Dict[str, float] = None) -> Dict[str, Any]:
        """Issue material with FEFO and alternative substitution"""
        issued_details = []
        substitutions = []
        
        material_id = int(material['material_id'])
        
        # Get BOM detail info
        bom_info = self._get_bom_detail_info(conn, material['order_material_id'])
        primary_bom_qty = float(bom_info['quantity']) if bom_info else 1.0
        
        # Issue primary material (quantity from custom_quantities, passed as required_qty)
        primary_issued = 0.0
        if required_qty > 0:
            try:
                primary_details = self._issue_single_material_fefo(
                    conn, issue_id, order_id, material,
                    required_qty, warehouse_id, group_id,
                    user_id, keycloak_id, entity_id,
                    is_alternative=False, original_material_id=None,
                    conversion_ratio=1.0
                )
                issued_details.extend(primary_details)
                
                for detail in primary_details:
                    primary_issued += float(detail['quantity'])
                    
            except ValueError as e:
                logger.warning(f"⚠️ Insufficient primary {material['material_name']}: {e}")
        
        # Issue alternatives based on specified quantities
        if alternative_quantities and bom_info:
            alternatives = self._get_alternatives_for_material(
                conn, bom_info['bom_detail_id']
            )
            
            for alt in alternatives:
                # Use alt['id'] (bom_material_alternatives.id) to match key format from forms.py
                alt_key = f"{material_id}_{alt['id']}"
                alt_qty_to_issue = alternative_quantities.get(alt_key, 0)
                
                if alt_qty_to_issue <= 0:
                    continue
                
                try:
                    conversion_ratio = float(alt['quantity']) / primary_bom_qty
                    
                    alt_material = pd.Series({
                        'order_material_id': material['order_material_id'],
                        'material_id': alt['alternative_material_id'],
                        'material_name': alt['alternative_material_name'],
                        'uom': alt['uom']
                    })
                    
                    alt_details = self._issue_single_material_fefo(
                        conn, issue_id, order_id, alt_material,
                        alt_qty_to_issue, warehouse_id, group_id,
                        user_id, keycloak_id, entity_id,
                        is_alternative=True,
                        original_material_id=material['material_id'],
                        conversion_ratio=conversion_ratio
                    )
                    
                    alt_actual_issued = sum(float(d['quantity']) for d in alt_details)
                    alt_equivalent_issued = alt_actual_issued / conversion_ratio if conversion_ratio != 0 else 0
                    
                    if alt_actual_issued > 0:
                        issued_details.extend(alt_details)
                        substitutions.append({
                            'original_material': material['material_name'],
                            'original_material_id': material['material_id'],
                            'substitute_material': alt['alternative_material_name'],
                            'substitute_material_id': alt['alternative_material_id'],
                            'actual_quantity': alt_actual_issued,
                            'equivalent_quantity': alt_equivalent_issued,
                            'conversion_ratio': conversion_ratio,
                            'uom': alt['uom'],
                            'priority': alt['priority']
                        })
                        
                except ValueError as e:
                    logger.warning(f"⚠️ Alternative issue failed: {e}")
                    continue
        
        return {'details': issued_details, 'substitutions': substitutions}
    
    def _issue_single_material_fefo(self, conn, issue_id: int, order_id: int,
                                   material: pd.Series, required_qty: float,
                                   warehouse_id: int, group_id: str,
                                   user_id: int, keycloak_id: str, entity_id: int,
                                   is_alternative: bool = False,
                                   original_material_id: Optional[int] = None,
                                   conversion_ratio: float = 1.0) -> List[Dict]:
        """Issue single material using FEFO"""
        # Get batches
        batch_query = text("""
            SELECT 
                id as inventory_history_id,
                batch_no, expired_date, remain as available_qty
            FROM inventory_histories
            WHERE product_id = :material_id
                AND warehouse_id = :warehouse_id
                AND remain > 0 AND delete_flag = 0
            ORDER BY COALESCE(expired_date, '2099-12-31') ASC, created_date ASC
            FOR UPDATE
        """)
        
        batch_result = conn.execute(batch_query, {
            'material_id': material['material_id'],
            'warehouse_id': warehouse_id
        })
        
        batches = [dict(zip(batch_result.keys(), row)) for row in batch_result]
        
        if not batches:
            raise ValueError(f"No stock for {material['material_name']}")
        
        issued_details = []
        total_actual_issued = 0.0
        total_equivalent_issued = 0.0
        
        for batch in batches:
            if total_actual_issued >= required_qty:
                break
            
            batch_available = float(batch['available_qty'])
            required_remaining = float(required_qty) - float(total_actual_issued)
            issue_qty = min(batch_available, required_remaining)
            
            # Insert issue detail
            detail_id = self._insert_issue_detail(
                conn, issue_id, material['order_material_id'],
                material['material_id'], batch, issue_qty, material['uom'],
                is_alternative, original_material_id
            )
            
            # Update inventory
            self._update_inventory_for_issue(
                conn, batch['inventory_history_id'], material['material_id'],
                warehouse_id, issue_qty, batch['batch_no'], batch['expired_date'],
                group_id, keycloak_id, detail_id
            )
            
            issued_details.append({
                'detail_id': detail_id,
                'material_id': material['material_id'],
                'material_name': material['material_name'],
                'batch_no': batch['batch_no'],
                'quantity': issue_qty,
                'uom': material['uom'],
                'expired_date': batch['expired_date'],
                'is_alternative': is_alternative,
                'original_material_id': original_material_id,
                'conversion_ratio': conversion_ratio
            })
            
            total_actual_issued += issue_qty
            total_equivalent_issued += issue_qty / conversion_ratio
        
        if total_actual_issued < required_qty:
            raise ValueError(f"Insufficient stock: need {required_qty}, have {total_actual_issued}")
        
        # Update order materials with equivalent qty
        update_query = text("""
            UPDATE manufacturing_order_materials
            SET issued_qty = COALESCE(issued_qty, 0) + :equivalent_issued,
                status = CASE 
                    WHEN COALESCE(issued_qty, 0) + :equivalent_issued >= required_qty THEN 'ISSUED'
                    WHEN COALESCE(issued_qty, 0) + :equivalent_issued > 0 THEN 'PARTIAL'
                    ELSE 'PENDING'
                END
            WHERE id = :order_material_id
        """)
        
        conn.execute(update_query, {
            'equivalent_issued': total_equivalent_issued,
            'order_material_id': material['order_material_id']
        })
        
        return issued_details
    
    def _insert_issue_detail(self, conn, issue_id: int, order_material_id: int,
                            material_id: int, batch: Dict, quantity: float,
                            uom: str, is_alternative: bool,
                            original_material_id: Optional[int]) -> int:
        """Insert issue detail record with full tracking"""
        query = text("""
            INSERT INTO material_issue_details (
                material_issue_id, manufacturing_order_material_id,
                material_id, inventory_history_id, batch_no, quantity, uom, expired_date,
                is_alternative, original_material_id
            ) VALUES (
                :issue_id, :order_material_id,
                :material_id, :inventory_history_id, :batch_no, :quantity, :uom, :expired_date,
                :is_alternative, :original_material_id
            )
        """)
        
        result = conn.execute(query, {
            'issue_id': issue_id,
            'order_material_id': order_material_id,
            'material_id': material_id,
            'inventory_history_id': batch.get('inventory_history_id'),
            'batch_no': batch['batch_no'],
            'quantity': quantity,
            'uom': uom,
            'expired_date': batch['expired_date'],
            'is_alternative': 1 if is_alternative else 0,
            'original_material_id': original_material_id
        })
        
        return result.lastrowid
    
    def _update_inventory_for_issue(self, conn, inventory_id: int, material_id: int,
                                   warehouse_id: int, quantity: float,
                                   batch_no: str, expired_date, group_id: str,
                                   keycloak_id: str, detail_id: int):
        """Update inventory for issue"""
        # Reduce remain
        update_query = text("""
            UPDATE inventory_histories
            SET remain = remain - :quantity
            WHERE id = :inventory_id
        """)
        conn.execute(update_query, {'quantity': quantity, 'inventory_id': inventory_id})
        
        # Create OUT record
        out_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type,
                quantity, remain, batch_no, expired_date,
                group_id, action_detail_id, created_by, created_date
            ) VALUES (
                :material_id, :warehouse_id, 'stockOutProduction',
                :quantity, 0, :batch_no, :expired_date,
                :group_id, :detail_id, :created_by, NOW()
            )
        """)
        
        conn.execute(out_query, {
            'material_id': material_id,
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'batch_no': batch_no,
            'expired_date': expired_date,
            'group_id': group_id,
            'detail_id': detail_id,
            'created_by': keycloak_id
        })
    
    def _get_bom_detail_info(self, conn, order_material_id: int) -> Optional[Dict]:
        """Get BOM detail info for material"""
        query = text("""
            SELECT 
                bd.id as bom_detail_id,
                bd.quantity,
                bd.scrap_rate
            FROM manufacturing_order_materials mom
            JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id
                AND bd.material_id = mom.material_id
            WHERE mom.id = :order_material_id
            LIMIT 1
        """)
        
        result = conn.execute(query, {'order_material_id': order_material_id})
        row = result.fetchone()
        
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _get_alternatives_for_material(self, conn, bom_detail_id: int) -> List[Dict]:
        """Get alternatives ordered by priority"""
        query = text("""
            SELECT 
                alt.id, alt.alternative_material_id,
                p.name as alternative_material_name,
                alt.quantity, alt.uom, alt.priority
            FROM bom_material_alternatives alt
            JOIN products p ON alt.alternative_material_id = p.id
            WHERE alt.bom_detail_id = :bom_detail_id AND alt.is_active = 1
            ORDER BY alt.priority ASC
        """)
        
        result = conn.execute(query, {'bom_detail_id': bom_detail_id})
        return [dict(zip(result.keys(), row)) for row in result]