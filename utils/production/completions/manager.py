# utils/production/completions/manager.py
"""
Completion Manager - Business logic for Production Completions
Complete production orders with receipt creation and inventory updates

Version: 2.0.0
Changes:
- Added update_quality_status_partial() for partial QC results
- Supports splitting receipt when some items pass and some fail
- PASSED qty → GOOD inventory, FAILED qty → DEFECTIVE (separate receipt)

Based on: materials.py complete_production function
"""

import logging
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional, Any

import pandas as pd
from sqlalchemy import text

from utils.db import get_db_engine
from .common import get_vietnam_now

logger = logging.getLogger(__name__)


class CompletionManager:
    """Business logic for Production Completion management"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Complete Production ====================
    
    def complete_production(self, order_id: int, produced_qty: float,
                           batch_no: str, warehouse_id: int,
                           quality_status: str, user_id: int, keycloak_id: str,
                           expiry_date: Optional[date] = None,
                           notes: str = '') -> Dict[str, Any]:
        """
        Complete production with output receipt
        
        Args:
            order_id: Production order ID
            produced_qty: Actual quantity produced
            batch_no: Production batch number
            warehouse_id: Target warehouse for finished goods
            quality_status: 'PENDING', 'PASSED', 'FAILED'
            user_id: User ID for manufacturing tables (INT)
            keycloak_id: Keycloak ID for inventory tables (VARCHAR)
            expiry_date: Optional expiry date for finished goods
            notes: Production notes
        
        Returns:
            Dictionary with receipt_no, receipt_id, order_completed
        
        Raises:
            ValueError: If validation fails
        """
        with self.engine.begin() as conn:
            try:
                # Get order info
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                if order['status'] not in ['IN_PROGRESS']:
                    raise ValueError(f"Cannot complete {order['status']} order. Only IN_PROGRESS orders can be completed.")
                
                # Validate all RAW_MATERIALs have been issued
                pending_materials = self._get_pending_raw_materials(conn, order_id)
                if pending_materials:
                    material_list = ", ".join([m['name'] for m in pending_materials[:3]])
                    if len(pending_materials) > 3:
                        material_list += f" and {len(pending_materials) - 3} more..."
                    raise ValueError(
                        f"Cannot complete order: {len(pending_materials)} raw material(s) have not been fully issued. "
                        f"Materials: {material_list}"
                    )
                
                # Generate receipt number and group ID
                receipt_no = self._generate_receipt_number(conn)
                group_id = str(uuid.uuid4())
                
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
                        :user_id, NOW()
                    )
                """)
                
                receipt_result = conn.execute(receipt_query, {
                    'receipt_no': receipt_no,
                    'order_id': order_id,
                    'product_id': order['product_id'],
                    'quantity': produced_qty,
                    'uom': order['uom'],
                    'batch_no': batch_no,
                    'expired_date': expiry_date,
                    'warehouse_id': warehouse_id,
                    'quality_status': quality_status,
                    'notes': notes,
                    'user_id': user_id
                })
                
                receipt_id = receipt_result.lastrowid
                
                # Update inventory if quality passed
                # Type: stockInProduction (as per spec)
                if quality_status == 'PASSED':
                    self._add_production_to_inventory(
                        conn, order, produced_qty, batch_no,
                        warehouse_id, expiry_date,
                        group_id, keycloak_id, receipt_id
                    )
                
                # Update order produced quantity
                update_query = text("""
                    UPDATE manufacturing_orders
                    SET produced_qty = COALESCE(produced_qty, 0) + :produced_qty,
                        status = CASE 
                            WHEN COALESCE(produced_qty, 0) + :produced_qty >= planned_qty 
                            THEN 'COMPLETED' ELSE 'IN_PROGRESS' 
                        END,
                        completion_date = CASE 
                            WHEN COALESCE(produced_qty, 0) + :produced_qty >= planned_qty 
                            THEN NOW() ELSE NULL 
                        END,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(update_query, {
                    'produced_qty': produced_qty,
                    'order_id': order_id,
                    'user_id': user_id
                })
                
                # Check if order is completed
                check_query = text("""
                    SELECT 
                        COALESCE(produced_qty, 0) >= planned_qty as is_completed
                    FROM manufacturing_orders
                    WHERE id = :order_id
                """)
                check_result = conn.execute(check_query, {'order_id': order_id})
                order_completed = bool(check_result.fetchone()[0])
                
                logger.info(f"✅ Completed production receipt {receipt_no} for order {order_id}")
                
                return {
                    'receipt_no': receipt_no,
                    'receipt_id': receipt_id,
                    'order_completed': order_completed,
                    'quantity': produced_qty,
                    'batch_no': batch_no,
                    'quality_status': quality_status
                }
                
            except Exception as e:
                logger.error(f"❌ Error completing production for order {order_id}: {e}")
                raise
    
    # ==================== Update Quality Status (Original - Full Batch) ====================
    
    def update_quality_status(self, receipt_id: int, new_status: str,
                             notes: str, user_id: int,
                             keycloak_id: str = None) -> bool:
        """
        Update quality status of a receipt (entire batch)
        
        Args:
            receipt_id: Receipt ID
            new_status: New quality status (PENDING, PASSED, FAILED)
            notes: Updated notes
            user_id: User ID
            keycloak_id: Keycloak ID for inventory updates
        
        Returns:
            True if successful
        
        Inventory Logic (spec compliant):
        - PENDING/FAILED → PASSED: Create stockInProduction record
        - PASSED → PENDING/FAILED: Find existing stockInProduction (via action_detail_id) and set remain=0
        """
        with self.engine.begin() as conn:
            try:
                # Get current receipt info
                receipt_query = text("""
                    SELECT 
                        pr.id, pr.quality_status, pr.quantity, pr.batch_no,
                        pr.warehouse_id, pr.expired_date, pr.product_id,
                        mo.id as order_id
                    FROM production_receipts pr
                    JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
                    WHERE pr.id = :receipt_id
                    FOR UPDATE
                """)
                
                result = conn.execute(receipt_query, {'receipt_id': receipt_id})
                row = result.fetchone()
                
                if not row:
                    raise ValueError(f"Receipt {receipt_id} not found")
                
                receipt = dict(zip(result.keys(), row))
                old_status = receipt['quality_status']
                
                # Update receipt
                update_query = text("""
                    UPDATE production_receipts
                    SET quality_status = :new_status,
                        notes = :notes
                    WHERE id = :receipt_id
                """)
                
                conn.execute(update_query, {
                    'new_status': new_status,
                    'notes': notes,
                    'receipt_id': receipt_id
                })
                
                # Handle inventory changes based on status transition
                if keycloak_id:
                    group_id = str(uuid.uuid4())
                    
                    # If changing from non-PASSED to PASSED, add to inventory
                    # Use type: stockInProduction (as per spec)
                    if old_status != 'PASSED' and new_status == 'PASSED':
                        self._add_stock_in_production(
                            conn, receipt, group_id, keycloak_id
                        )
                    
                    # If changing from PASSED to non-PASSED, remove from inventory
                    # Find existing stockInProduction record and set remain=0
                    elif old_status == 'PASSED' and new_status != 'PASSED':
                        self._remove_stock_in_production(
                            conn, receipt, keycloak_id
                        )
                
                logger.info(f"✅ Updated receipt {receipt_id} quality: {old_status} → {new_status}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error updating quality status: {e}")
                raise
    
    # ==================== Update Quality Status (Partial QC) ====================
    
    def update_quality_status_partial(self, receipt_id: int, 
                                       passed_qty: float, failed_qty: float,
                                       defect_type: str = None,
                                       notes: str = '', user_id: int = None,
                                       keycloak_id: str = None) -> Dict[str, Any]:
        """
        Update quality status with partial results
        Supports splitting receipt when some items pass and some fail
        
        Args:
            receipt_id: Receipt ID
            passed_qty: Quantity that passed QC
            failed_qty: Quantity that failed QC
            defect_type: Type of defect (required if failed_qty > 0)
            notes: QC notes
            user_id: User ID
            keycloak_id: Keycloak ID for inventory updates
        
        Returns:
            Dict with success status and details
        
        Logic:
        1. If all passed (failed_qty = 0): Update receipt to PASSED, add to inventory
        2. If all failed (passed_qty = 0): Update receipt to FAILED
        3. If partial:
           - Update original receipt: quantity = passed_qty, status = PASSED
           - Create new receipt: quantity = failed_qty, status = FAILED
           - Handle inventory accordingly
        """
        with self.engine.begin() as conn:
            try:
                # Get current receipt info
                receipt_query = text("""
                    SELECT 
                        pr.id, pr.receipt_no, pr.manufacturing_order_id,
                        pr.quality_status, pr.quantity, pr.batch_no,
                        pr.warehouse_id, pr.expired_date, pr.product_id,
                        pr.uom, pr.notes as original_notes,
                        mo.id as order_id
                    FROM production_receipts pr
                    JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
                    WHERE pr.id = :receipt_id
                    FOR UPDATE
                """)
                
                result = conn.execute(receipt_query, {'receipt_id': receipt_id})
                row = result.fetchone()
                
                if not row:
                    return {'success': False, 'error': f"Receipt {receipt_id} not found"}
                
                receipt = dict(zip(result.keys(), row))
                old_status = receipt['quality_status']
                total_qty = float(receipt['quantity'])
                
                # Validate quantities
                if abs(passed_qty + failed_qty - total_qty) > 0.01:
                    return {
                        'success': False, 
                        'error': f"Passed ({passed_qty}) + Failed ({failed_qty}) must equal Total ({total_qty})"
                    }
                
                group_id = str(uuid.uuid4())
                new_receipt_no = None
                
                # Case 1: All PASSED
                if failed_qty <= 0:
                    self._update_receipt_status(conn, receipt_id, 'PASSED', notes, user_id)
                    
                    # Handle inventory transition
                    if keycloak_id:
                        if old_status != 'PASSED':
                            self._add_stock_in_production(conn, receipt, group_id, keycloak_id)
                    
                    logger.info(f"✅ Receipt {receipt['receipt_no']} - All {passed_qty} PASSED")
                
                # Case 2: All FAILED
                elif passed_qty <= 0:
                    # Build notes with defect type
                    final_notes = self._build_failed_notes(notes, defect_type)
                    self._update_receipt_status(conn, receipt_id, 'FAILED', final_notes, user_id, defect_type)
                    
                    # Remove from inventory if was previously PASSED
                    if keycloak_id and old_status == 'PASSED':
                        self._remove_stock_in_production(conn, receipt, keycloak_id)
                    
                    logger.info(f"✅ Receipt {receipt['receipt_no']} - All {failed_qty} FAILED ({defect_type})")
                
                # Case 3: Partial - Split receipt
                else:
                    new_receipt_no = self._handle_partial_qc(
                        conn, receipt, passed_qty, failed_qty,
                        defect_type, notes, user_id, keycloak_id, group_id
                    )
                    
                    logger.info(
                        f"✅ Receipt {receipt['receipt_no']} split: "
                        f"{passed_qty} PASSED, {failed_qty} FAILED → {new_receipt_no}"
                    )
                
                return {
                    'success': True,
                    'passed_qty': passed_qty,
                    'failed_qty': failed_qty,
                    'new_receipt_no': new_receipt_no
                }
                
            except Exception as e:
                logger.error(f"❌ Error updating quality status (partial): {e}")
                return {'success': False, 'error': str(e)}
    
    def _handle_partial_qc(self, conn, receipt: Dict, passed_qty: float, 
                           failed_qty: float, defect_type: str, notes: str,
                           user_id: int, keycloak_id: str, group_id: str) -> str:
        """
        Handle partial QC - split receipt into PASSED and FAILED portions
        
        Returns:
            New receipt number for failed portion
        """
        old_status = receipt['quality_status']
        receipt_id = receipt['id']
        
        # 1. Update original receipt with PASSED quantity
        update_passed_query = text("""
            UPDATE production_receipts
            SET quantity = :passed_qty,
                quality_status = 'PASSED',
                notes = :notes,
                updated_by = :user_id,
                updated_date = NOW()
            WHERE id = :receipt_id
        """)
        
        conn.execute(update_passed_query, {
            'passed_qty': passed_qty,
            'notes': notes,
            'user_id': user_id,
            'receipt_id': receipt_id
        })
        
        # 2. Handle inventory for PASSED portion
        if keycloak_id:
            if old_status == 'PASSED':
                # Was already PASSED - need to adjust quantity
                # First remove old inventory
                self._remove_stock_in_production(conn, receipt, keycloak_id)
                
            # Add new inventory for passed quantity
            receipt_for_inv = receipt.copy()
            receipt_for_inv['quantity'] = passed_qty
            self._add_stock_in_production(conn, receipt_for_inv, group_id, keycloak_id)
        
        # 3. Create new receipt for FAILED portion
        new_receipt_no = self._generate_receipt_number(conn)
        failed_notes = self._build_failed_notes(notes, defect_type, receipt['receipt_no'])
        
        create_failed_query = text("""
            INSERT INTO production_receipts (
                receipt_no, manufacturing_order_id, receipt_date,
                product_id, quantity, uom, batch_no, expired_date,
                warehouse_id, quality_status, defect_type, notes,
                parent_receipt_id,
                created_by, created_date
            ) VALUES (
                :receipt_no, :order_id, NOW(),
                :product_id, :quantity, :uom, :batch_no, :expired_date,
                :warehouse_id, 'FAILED', :defect_type, :notes,
                :parent_receipt_id,
                :user_id, NOW()
            )
        """)
        
        conn.execute(create_failed_query, {
            'receipt_no': new_receipt_no,
            'order_id': receipt['manufacturing_order_id'],
            'product_id': receipt['product_id'],
            'quantity': failed_qty,
            'uom': receipt['uom'],
            'batch_no': receipt['batch_no'],
            'expired_date': receipt['expired_date'],
            'warehouse_id': receipt['warehouse_id'],
            'defect_type': defect_type,
            'notes': failed_notes,
            'parent_receipt_id': receipt_id,
            'user_id': user_id
        })
        
        return new_receipt_no
    
    def _update_receipt_status(self, conn, receipt_id: int, new_status: str, 
                               notes: str, user_id: int, defect_type: str = None):
        """Update receipt status and notes"""
        if defect_type:
            update_query = text("""
                UPDATE production_receipts
                SET quality_status = :new_status,
                    defect_type = :defect_type,
                    notes = :notes,
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :receipt_id
            """)
            conn.execute(update_query, {
                'new_status': new_status,
                'defect_type': defect_type,
                'notes': notes,
                'user_id': user_id,
                'receipt_id': receipt_id
            })
        else:
            update_query = text("""
                UPDATE production_receipts
                SET quality_status = :new_status,
                    notes = :notes,
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :receipt_id
            """)
            conn.execute(update_query, {
                'new_status': new_status,
                'notes': notes,
                'user_id': user_id,
                'receipt_id': receipt_id
            })
    
    def _build_failed_notes(self, notes: str, defect_type: str, 
                            parent_receipt_no: str = None) -> str:
        """Build notes for failed receipt"""
        parts = []
        
        if defect_type:
            parts.append(f"[Defect: {defect_type}]")
        
        if parent_receipt_no:
            parts.append(f"[Split from: {parent_receipt_no}]")
        
        if notes:
            parts.append(notes)
        
        return " ".join(parts) if parts else ""
    
    # ==================== Private Helper Methods ====================
    
    def _get_order_info(self, conn, order_id: int) -> Optional[Dict]:
        """Get order information"""
        query = text("""
            SELECT 
                mo.id, mo.order_no, mo.product_id,
                mo.warehouse_id, mo.target_warehouse_id,
                mo.status, mo.planned_qty, mo.produced_qty,
                mo.entity_id, p.uom
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
    
    def _generate_receipt_number(self, conn) -> str:
        """Generate unique receipt number PR-YYYYMMDD-XXX"""
        timestamp = get_vietnam_now().strftime('%Y%m%d')
        prefix = f"PR-{timestamp}-"
        
        query = text("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING_INDEX(receipt_no, '-', -1) AS UNSIGNED)), 0
            ) + 1 as next_num
            FROM production_receipts
            WHERE receipt_no LIKE :pattern
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'pattern': f'{prefix}%'})
        row = result.fetchone()
        next_num = int(row[0]) if row and row[0] else 1
        
        return f"{prefix}{next_num:03d}"
    
    def _add_production_to_inventory(self, conn, order: Dict, quantity: float,
                                     batch_no: str, warehouse_id: int,
                                     expiry_date: Optional[date],
                                     group_id: str, keycloak_id: str,
                                     receipt_id: int):
        """
        Add production output to inventory
        Type: stockInProduction (as per spec)
        action_detail_id: production_receipts.id
        """
        inv_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type,
                quantity, remain, batch_no, expired_date,
                group_id, action_detail_id,
                created_by, created_date
            ) VALUES (
                :product_id, :warehouse_id, 'stockInProduction',
                :quantity, :quantity, :batch_no, :expired_date,
                :group_id, :action_detail_id,
                :created_by, NOW()
            )
        """)
        
        conn.execute(inv_query, {
            'product_id': order['product_id'],
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'batch_no': batch_no,
            'expired_date': expiry_date,
            'group_id': group_id,
            'action_detail_id': receipt_id,
            'created_by': keycloak_id
        })
        
        logger.info(f"📦 Added {quantity} to inventory for product {order['product_id']} (stockInProduction)")
    
    def _add_stock_in_production(self, conn, receipt: Dict,
                                  group_id: str, keycloak_id: str):
        """
        Add inventory when quality changes to PASSED
        Type: stockInProduction (as per spec)
        action_detail_id: production_receipts.id
        """
        inv_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type,
                quantity, remain, batch_no, expired_date,
                group_id, action_detail_id,
                created_by, created_date
            ) VALUES (
                :product_id, :warehouse_id, 'stockInProduction',
                :quantity, :quantity, :batch_no, :expired_date,
                :group_id, :action_detail_id,
                :created_by, NOW()
            )
        """)
        
        conn.execute(inv_query, {
            'product_id': receipt['product_id'],
            'warehouse_id': receipt['warehouse_id'],
            'quantity': receipt['quantity'],
            'batch_no': receipt['batch_no'],
            'expired_date': receipt['expired_date'],
            'group_id': group_id,
            'action_detail_id': receipt['id'],
            'created_by': keycloak_id
        })
        
        logger.info(f"📦 Added stockInProduction for receipt {receipt['id']} (quality → PASSED)")
    
    def _remove_stock_in_production(self, conn, receipt: Dict, keycloak_id: str):
        """
        Remove inventory when quality changes from PASSED to non-PASSED
        
        Logic: Find existing stockInProduction record with action_detail_id = receipt_id
        and set remain = 0 (soft removal - keeps audit trail)
        """
        # Find the stockInProduction record created for this receipt
        find_query = text("""
            SELECT id, remain
            FROM inventory_histories
            WHERE type = 'stockInProduction'
                AND action_detail_id = :receipt_id
                AND product_id = :product_id
                AND warehouse_id = :warehouse_id
                AND remain > 0
                AND delete_flag = 0
            FOR UPDATE
        """)
        
        result = conn.execute(find_query, {
            'receipt_id': receipt['id'],
            'product_id': receipt['product_id'],
            'warehouse_id': receipt['warehouse_id']
        })
        row = result.fetchone()
        
        if row:
            inv_record = dict(zip(result.keys(), row))
            
            # Set remain = 0 (soft removal)
            update_query = text("""
                UPDATE inventory_histories
                SET remain = 0,
                    updated_by = :updated_by,
                    updated_date = NOW()
                WHERE id = :inv_id
            """)
            
            conn.execute(update_query, {
                'inv_id': inv_record['id'],
                'updated_by': keycloak_id
            })
            
            logger.info(f"📦 Removed stockInProduction for receipt {receipt['id']} (quality PASSED → non-PASSED)")
        else:
            # No inventory record found - might have been already processed
            logger.warning(f"⚠️ No stockInProduction record found for receipt {receipt['id']}")
    
    def _get_pending_raw_materials(self, conn, order_id: int) -> List[Dict]:
        """
        Get list of RAW_MATERIALs that have not been fully issued
        
        Args:
            conn: Database connection
            order_id: Manufacturing order ID
            
        Returns:
            List of dict with pending material info
        """
        query = text("""
            SELECT 
                mom.id,
                mom.material_id,
                p.name,
                p.pt_code,
                mom.required_qty,
                COALESCE(mom.issued_qty, 0) as issued_qty,
                mom.required_qty - COALESCE(mom.issued_qty, 0) as pending_qty,
                bd.material_type
            FROM manufacturing_order_materials mom
            JOIN products p ON mom.material_id = p.id
            LEFT JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            LEFT JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
                AND bd.material_id = mom.material_id
            WHERE mom.manufacturing_order_id = :order_id
                AND mom.required_qty > COALESCE(mom.issued_qty, 0)
                AND (bd.material_type = 'RAW_MATERIAL' OR bd.material_type IS NULL)
        """)
        
        result = conn.execute(query, {'order_id': order_id})
        
        pending = []
        for row in result.fetchall():
            row_dict = dict(zip(result.keys(), row))
            pending.append({
                'id': row_dict['id'],
                'material_id': row_dict['material_id'],
                'name': row_dict['name'],
                'pt_code': row_dict.get('pt_code'),
                'required_qty': float(row_dict['required_qty']),
                'issued_qty': float(row_dict['issued_qty']),
                'pending_qty': float(row_dict['pending_qty']),
                'material_type': row_dict.get('material_type', 'RAW_MATERIAL')
            })
        
        return pending