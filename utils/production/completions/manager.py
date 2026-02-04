# utils/production/completions/manager.py
"""
Completion Manager - Business logic for Production Completions
Complete production orders with receipt creation and inventory updates

Version: 3.2.0
Changes:
- v3.2.0: Added pending QC post-validation - order cannot auto-complete
  if any receipts have PENDING quality status (blocks entire transaction)
- v3.1.0: Changed validation from "fully issued" to "issued" (issued_qty > 0)
  - Renamed _get_pending_raw_materials → _get_unissued_raw_materials
  - Allows completion when materials are partially issued (practical tolerance)
- v3.0.0: Full partial QC support - PASSED + PENDING + FAILED combinations
- v2.0.1: Fixed SQL error - removed updated_by/updated_date from production_receipts UPDATE
- v2.0.0: Added update_quality_status_partial() for partial QC results

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
                
                # Validate all RAW_MATERIALs have been issued (at least partially)
                unissued_materials = self._get_unissued_raw_materials(conn, order_id)
                if unissued_materials:
                    material_list = ", ".join([m['name'] for m in unissued_materials[:3]])
                    if len(unissued_materials) > 3:
                        material_list += f" and {len(unissued_materials) - 3} more..."
                    raise ValueError(
                        f"Cannot complete order: {len(unissued_materials)} raw material(s) have not been issued. "
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
                
                # ===== POST-VALIDATION: Pending QC blocks order auto-completion =====
                # If this receipt would cause order to auto-complete,
                # verify ALL receipts (including this one) have been QC'd.
                new_total = float(order.get('produced_qty') or 0) + produced_qty
                would_complete = new_total >= float(order['planned_qty'])
                
                if would_complete:
                    pending_check = text("""
                        SELECT COUNT(*) as cnt
                        FROM production_receipts
                        WHERE manufacturing_order_id = :order_id
                            AND quality_status = 'PENDING'
                    """)
                    pending_result = conn.execute(pending_check, {'order_id': order_id})
                    pending_count = int(pending_result.fetchone()[0])
                    
                    if pending_count > 0:
                        raise ValueError(
                            f"Cannot complete order: {pending_count} receipt(s) still have PENDING quality status. "
                            f"All receipts must pass QC before order can be finalized.\n"
                            f"Tip: Update quality status of pending receipts, or change this receipt's quality to PASSED/FAILED."
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
        - PASSED → PENDING/FAILED: Remove from inventory (set remain = 0)
        """
        with self.engine.begin() as conn:
            try:
                # Get current receipt info
                receipt = self._get_receipt_info(conn, receipt_id)
                if not receipt:
                    raise ValueError(f"Receipt {receipt_id} not found")
                
                old_status = receipt['quality_status']
                
                # Skip if no change
                if old_status == new_status:
                    logger.info(f"Quality status unchanged for receipt {receipt_id}")
                    return True
                
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
                
                # Handle inventory changes
                group_id = str(uuid.uuid4())
                
                if old_status != 'PASSED' and new_status == 'PASSED':
                    # Add to inventory
                    self._add_stock_in_production(conn, receipt, group_id, keycloak_id or str(user_id))
                
                elif old_status == 'PASSED' and new_status != 'PASSED':
                    # Remove from inventory
                    self._remove_stock_in_production(conn, receipt, keycloak_id or str(user_id))
                
                logger.info(f"✅ Updated quality status for receipt {receipt_id}: {old_status} → {new_status}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error updating quality status for receipt {receipt_id}: {e}")
                raise
    
    # ==================== Update Quality Status (Partial QC Support) ====================
    
    def update_quality_status_partial(self, receipt_id: int,
                                      passed_qty: float,
                                      pending_qty: float,
                                      failed_qty: float,
                                      defect_type: Optional[str],
                                      notes: str,
                                      user_id: int,
                                      keycloak_id: str = None) -> Dict[str, Any]:
        """
        Update quality status with partial results support
        
        Supports all 7 scenarios:
        1. All PASSED (passed = total)
        2. All PENDING (pending = total)
        3. All FAILED (failed = total)
        4. PASSED + FAILED (split into 2 receipts)
        5. PASSED + PENDING (split into 2 receipts)
        6. PENDING + FAILED (split into 2 receipts)
        7. PASSED + PENDING + FAILED (split into 3 receipts)
        
        Split priority: PASSED > PENDING > FAILED
        Original receipt keeps highest priority status
        
        Args:
            receipt_id: Receipt ID
            passed_qty: Quantity that passed QC
            pending_qty: Quantity still pending QC
            failed_qty: Quantity that failed QC
            defect_type: Defect type for failed items
            notes: QC notes
            user_id: User ID
            keycloak_id: Keycloak ID for inventory
        
        Returns:
            Dict with success status and new receipt info
        """
        with self.engine.begin() as conn:
            try:
                receipt = self._get_receipt_info(conn, receipt_id)
                if not receipt:
                    return {'success': False, 'error': 'Receipt not found'}
                
                total_qty = float(receipt['quantity'])
                old_status = receipt['quality_status']
                
                # Validate total
                input_total = passed_qty + pending_qty + failed_qty
                if abs(input_total - total_qty) > 0.01:
                    return {
                        'success': False,
                        'error': f'Total ({input_total}) must equal receipt quantity ({total_qty})'
                    }
                
                group_id = str(uuid.uuid4())
                new_receipts = []
                
                # Determine how many portions we have
                has_passed = passed_qty > 0
                has_pending = pending_qty > 0
                has_failed = failed_qty > 0
                portions = sum([has_passed, has_pending, has_failed])
                
                if portions == 1:
                    # Simple case: entire batch goes to one status
                    if has_passed:
                        new_status = 'PASSED'
                    elif has_pending:
                        new_status = 'PENDING'
                    else:
                        new_status = 'FAILED'
                    
                    # Update original receipt
                    self._update_receipt_status(conn, receipt_id, new_status, notes, defect_type if new_status == 'FAILED' else None)
                    
                    # Handle inventory
                    if old_status != 'PASSED' and new_status == 'PASSED':
                        self._add_stock_in_production(conn, receipt, group_id, keycloak_id or str(user_id))
                    elif old_status == 'PASSED' and new_status != 'PASSED':
                        self._remove_stock_in_production(conn, receipt, keycloak_id or str(user_id))
                
                else:
                    # Split case: multiple portions
                    # Priority: PASSED > PENDING > FAILED
                    # Original receipt keeps highest priority
                    
                    if has_passed:
                        # Original → PASSED
                        self._update_receipt_quantity_status(conn, receipt_id, passed_qty, 'PASSED', notes, None)
                        
                        # Handle inventory for original
                        if old_status != 'PASSED':
                            # Create new inventory record with new quantity
                            receipt_copy = dict(receipt)
                            receipt_copy['quantity'] = passed_qty
                            self._add_stock_in_production(conn, receipt_copy, group_id, keycloak_id or str(user_id))
                        elif old_status == 'PASSED':
                            # Reduce existing inventory
                            removed_qty = pending_qty + failed_qty
                            if removed_qty > 0:
                                self._reduce_stock_in_production(conn, receipt, removed_qty, keycloak_id or str(user_id))
                        
                        # Create PENDING receipt if needed
                        if has_pending:
                            pending_receipt_no = self._create_split_receipt(
                                conn, receipt, pending_qty, 'PENDING', notes, None, user_id
                            )
                            new_receipts.append({'receipt_no': pending_receipt_no, 'status': 'PENDING', 'qty': pending_qty})
                        
                        # Create FAILED receipt if needed
                        if has_failed:
                            failed_receipt_no = self._create_split_receipt(
                                conn, receipt, failed_qty, 'FAILED', notes, defect_type, user_id
                            )
                            new_receipts.append({'receipt_no': failed_receipt_no, 'status': 'FAILED', 'qty': failed_qty})
                    
                    elif has_pending:
                        # Original → PENDING (no PASSED qty)
                        self._update_receipt_quantity_status(conn, receipt_id, pending_qty, 'PENDING', notes, None)
                        
                        # If was PASSED, remove from inventory
                        if old_status == 'PASSED':
                            self._remove_stock_in_production(conn, receipt, keycloak_id or str(user_id))
                        
                        # Create FAILED receipt
                        if has_failed:
                            failed_receipt_no = self._create_split_receipt(
                                conn, receipt, failed_qty, 'FAILED', notes, defect_type, user_id
                            )
                            new_receipts.append({'receipt_no': failed_receipt_no, 'status': 'FAILED', 'qty': failed_qty})
                
                logger.info(f"✅ Partial QC updated for receipt {receipt_id}: PASSED={passed_qty}, PENDING={pending_qty}, FAILED={failed_qty}")
                
                return {
                    'success': True,
                    'new_receipts': new_receipts
                }
                
            except Exception as e:
                logger.error(f"❌ Error in partial QC update for receipt {receipt_id}: {e}")
                return {'success': False, 'error': str(e)}
    
    # ==================== Private Helper Methods ====================
    
    def _get_receipt_info(self, conn, receipt_id: int) -> Optional[Dict]:
        """Get receipt information"""
        query = text("""
            SELECT 
                pr.id, pr.receipt_no, pr.manufacturing_order_id,
                pr.product_id, pr.quantity, pr.uom,
                pr.batch_no, pr.expired_date, pr.warehouse_id,
                pr.quality_status, pr.notes
            FROM production_receipts pr
            WHERE pr.id = :receipt_id
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'receipt_id': receipt_id})
        row = result.fetchone()
        
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _update_receipt_status(self, conn, receipt_id: int, status: str, 
                               notes: str, defect_type: Optional[str]):
        """Update receipt status only"""
        query = text("""
            UPDATE production_receipts
            SET quality_status = :status,
                notes = :notes,
                defect_type = :defect_type
            WHERE id = :receipt_id
        """)
        
        conn.execute(query, {
            'receipt_id': receipt_id,
            'status': status,
            'notes': notes,
            'defect_type': defect_type
        })
    
    def _update_receipt_quantity_status(self, conn, receipt_id: int, quantity: float,
                                        status: str, notes: str, defect_type: Optional[str]):
        """Update receipt quantity and status"""
        query = text("""
            UPDATE production_receipts
            SET quantity = :quantity,
                quality_status = :status,
                notes = :notes,
                defect_type = :defect_type
            WHERE id = :receipt_id
        """)
        
        conn.execute(query, {
            'receipt_id': receipt_id,
            'quantity': quantity,
            'status': status,
            'notes': notes,
            'defect_type': defect_type
        })
    
    def _create_split_receipt(self, conn, original: Dict, quantity: float,
                              status: str, notes: str, defect_type: Optional[str],
                              user_id: int) -> str:
        """Create a new receipt from split"""
        receipt_no = self._generate_receipt_number(conn)
        
        query = text("""
            INSERT INTO production_receipts (
                receipt_no, manufacturing_order_id, receipt_date,
                product_id, quantity, uom, batch_no, expired_date,
                warehouse_id, quality_status, notes, defect_type,
                created_by, created_date
            ) VALUES (
                :receipt_no, :order_id, NOW(),
                :product_id, :quantity, :uom, :batch_no, :expired_date,
                :warehouse_id, :status, :notes, :defect_type,
                :user_id, NOW()
            )
        """)
        
        conn.execute(query, {
            'receipt_no': receipt_no,
            'order_id': original['manufacturing_order_id'],
            'product_id': original['product_id'],
            'quantity': quantity,
            'uom': original['uom'],
            'batch_no': original['batch_no'],
            'expired_date': original['expired_date'],
            'warehouse_id': original['warehouse_id'],
            'status': status,
            'notes': notes,
            'defect_type': defect_type,
            'user_id': user_id
        })
        
        return receipt_no
    
    def _reduce_stock_in_production(self, conn, receipt: Dict, reduce_qty: float, keycloak_id: str):
        """Reduce inventory quantity when partial QC fails/pending from PASSED"""
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
            new_remain = max(0, float(inv_record['remain']) - reduce_qty)
            
            update_query = text("""
                UPDATE inventory_histories
                SET remain = :new_remain,
                    updated_date = NOW()
                WHERE id = :inv_id
            """)
            
            conn.execute(update_query, {
                'inv_id': inv_record['id'],
                'new_remain': new_remain
            })
            
            logger.info(f"📦 Reduced stockInProduction by {reduce_qty} for receipt {receipt['id']}")
    
    def _get_order_info(self, conn, order_id: int) -> Optional[Dict]:
        """Get order information"""
        query = text("""
            SELECT 
                mo.id, mo.order_no, mo.status,
                mo.product_id, mo.planned_qty, mo.produced_qty, mo.uom,
                mo.warehouse_id, mo.target_warehouse_id
            FROM manufacturing_orders mo
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
                    updated_date = NOW()
                WHERE id = :inv_id
            """)
            
            conn.execute(update_query, {
                'inv_id': inv_record['id']
            })
            
            logger.info(f"📦 Removed stockInProduction for receipt {receipt['id']} (quality PASSED → non-PASSED)")
        else:
            # No inventory record found - might have been already processed
            logger.warning(f"⚠️ No stockInProduction record found for receipt {receipt['id']}")
    
    def _get_unissued_raw_materials(self, conn, order_id: int) -> List[Dict]:
        """
        Get list of RAW_MATERIALs that have NOT been issued at all (issued_qty = 0)
        
        Note: This allows partial issuance - materials with issued_qty > 0 will pass validation
        even if issued_qty < required_qty (practical tolerance for production variances)
        
        Args:
            conn: Database connection
            order_id: Manufacturing order ID
            
        Returns:
            List of dict with unissued material info
        """
        query = text("""
            SELECT 
                mom.id,
                mom.material_id,
                p.name,
                p.pt_code,
                mom.required_qty,
                COALESCE(mom.issued_qty, 0) as issued_qty,
                bd.material_type
            FROM manufacturing_order_materials mom
            JOIN products p ON mom.material_id = p.id
            LEFT JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            LEFT JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
                AND bd.material_id = mom.material_id
            WHERE mom.manufacturing_order_id = :order_id
                AND COALESCE(mom.issued_qty, 0) = 0
                AND (bd.material_type = 'RAW_MATERIAL' OR bd.material_type IS NULL)
        """)
        
        result = conn.execute(query, {'order_id': order_id})
        
        unissued = []
        for row in result.fetchall():
            row_dict = dict(zip(result.keys(), row))
            unissued.append({
                'id': row_dict['id'],
                'material_id': row_dict['material_id'],
                'name': row_dict['name'],
                'pt_code': row_dict.get('pt_code'),
                'required_qty': float(row_dict['required_qty']),
                'issued_qty': float(row_dict['issued_qty']),
                'material_type': row_dict.get('material_type', 'RAW_MATERIAL')
            })
        
        return unissued