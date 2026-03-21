# utils/production/completions/manager.py
"""
Production Receipts Manager - Business logic for Production Output Recording
Record production output with QC breakdown, close orders manually

Version: 4.0.0
Changes:
- v4.0.0: Production Receipts refactoring
  - complete_production() now accepts passed_qty/pending_qty/failed_qty
  - REMOVED auto-complete: MO stays IN_PROGRESS after receipt
  - NEW close_order(): manual order closure with validation
  - QC transitions locked: PASSED/FAILED → immutable
  - QC updates blocked when MO = COMPLETED
- v3.2.0: Added pending QC post-validation
- v3.1.0: Changed validation from "fully issued" to "issued" (issued_qty > 0)
- v3.0.0: Full partial QC support
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
    
    def complete_production(self, order_id: int,
                           passed_qty: float, pending_qty: float, failed_qty: float,
                           batch_no: str, warehouse_id: int,
                           user_id: int, keycloak_id: str,
                           expiry_date: Optional[date] = None,
                           defect_type: Optional[str] = None,
                           notes: str = '') -> Dict[str, Any]:
        """
        Record production output with QC breakdown.
        MO stays IN_PROGRESS — does NOT auto-complete.
        
        Args:
            order_id: Production order ID
            passed_qty: Quantity that passed QC (→ inventory)
            pending_qty: Quantity pending QC (→ no inventory)
            failed_qty: Quantity that failed QC (→ no inventory)
            batch_no: Production batch number
            warehouse_id: Target warehouse for finished goods
            user_id: User ID for manufacturing tables (INT)
            keycloak_id: Keycloak ID for inventory tables (VARCHAR)
            expiry_date: Optional expiry date for finished goods
            defect_type: Defect type if failed_qty > 0
            notes: Production notes
        
        Returns:
            Dictionary with receipt info
        
        Raises:
            ValueError: If validation fails
        """
        total_produced = passed_qty + pending_qty + failed_qty
        
        if total_produced <= 0:
            raise ValueError("Total produced quantity must be greater than 0")
        
        with self.engine.begin() as conn:
            try:
                # Get order info
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                if order['status'] not in ['IN_PROGRESS']:
                    raise ValueError(f"Cannot record output for {order['status']} order. Only IN_PROGRESS orders allowed.")
                
                # Validate RAW_MATERIALs have been issued
                unissued_materials = self._get_unissued_raw_materials(conn, order_id)
                if unissued_materials:
                    material_list = ", ".join([m['name'] for m in unissued_materials[:3]])
                    if len(unissued_materials) > 3:
                        material_list += f" and {len(unissued_materials) - 3} more..."
                    raise ValueError(
                        f"Cannot record output: {len(unissued_materials)} raw material(s) have not been issued. "
                        f"Materials: {material_list}"
                    )
                
                group_id = str(uuid.uuid4())
                created_receipts = []
                
                # Determine portions
                has_passed = passed_qty > 0
                has_pending = pending_qty > 0
                has_failed = failed_qty > 0
                portions = sum([has_passed, has_pending, has_failed])
                
                if portions == 1:
                    # Single receipt
                    if has_passed:
                        status = 'PASSED'
                        qty = passed_qty
                    elif has_pending:
                        status = 'PENDING'
                        qty = pending_qty
                    else:
                        status = 'FAILED'
                        qty = failed_qty
                    
                    receipt_no = self._generate_receipt_number(conn)
                    receipt_id = self._insert_receipt(
                        conn, receipt_no, order_id, order['product_id'],
                        qty, order['uom'], batch_no, expiry_date, warehouse_id,
                        status, notes, defect_type if status == 'FAILED' else None,
                        user_id, None
                    )
                    
                    if status == 'PASSED':
                        self._add_production_to_inventory(
                            conn, order, qty, batch_no, warehouse_id,
                            expiry_date, group_id, keycloak_id, receipt_id
                        )
                    
                    created_receipts.append({
                        'receipt_no': receipt_no, 'receipt_id': receipt_id,
                        'status': status, 'qty': qty
                    })
                
                else:
                    # Multiple receipts — priority: PASSED > PENDING > FAILED
                    # Main receipt gets highest priority status
                    main_receipt_id = None
                    
                    if has_passed:
                        receipt_no = self._generate_receipt_number(conn)
                        main_receipt_id = self._insert_receipt(
                            conn, receipt_no, order_id, order['product_id'],
                            passed_qty, order['uom'], batch_no, expiry_date, warehouse_id,
                            'PASSED', notes, None, user_id, None
                        )
                        self._add_production_to_inventory(
                            conn, order, passed_qty, batch_no, warehouse_id,
                            expiry_date, group_id, keycloak_id, main_receipt_id
                        )
                        created_receipts.append({
                            'receipt_no': receipt_no, 'receipt_id': main_receipt_id,
                            'status': 'PASSED', 'qty': passed_qty
                        })
                    
                    if has_pending:
                        receipt_no = self._generate_receipt_number(conn)
                        parent_id = main_receipt_id
                        if not has_passed:
                            # PENDING is the main receipt
                            parent_id = None
                            main_receipt_id = None  # will be set below
                        
                        pending_receipt_id = self._insert_receipt(
                            conn, receipt_no, order_id, order['product_id'],
                            pending_qty, order['uom'], batch_no, expiry_date, warehouse_id,
                            'PENDING', notes, None, user_id, parent_id
                        )
                        if main_receipt_id is None:
                            main_receipt_id = pending_receipt_id
                        created_receipts.append({
                            'receipt_no': receipt_no, 'receipt_id': pending_receipt_id,
                            'status': 'PENDING', 'qty': pending_qty
                        })
                    
                    if has_failed:
                        receipt_no = self._generate_receipt_number(conn)
                        parent_id = main_receipt_id
                        failed_receipt_id = self._insert_receipt(
                            conn, receipt_no, order_id, order['product_id'],
                            failed_qty, order['uom'], batch_no, expiry_date, warehouse_id,
                            'FAILED', notes, defect_type, user_id, parent_id
                        )
                        created_receipts.append({
                            'receipt_no': receipt_no, 'receipt_id': failed_receipt_id,
                            'status': 'FAILED', 'qty': failed_qty
                        })
                
                # Update order produced quantity — NO STATUS CHANGE
                update_query = text("""
                    UPDATE manufacturing_orders
                    SET produced_qty = COALESCE(produced_qty, 0) + :total_produced,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(update_query, {
                    'total_produced': total_produced,
                    'order_id': order_id,
                    'user_id': user_id
                })
                
                logger.info(
                    f"✅ Recorded production output for order {order_id}: "
                    f"PASSED={passed_qty}, PENDING={pending_qty}, FAILED={failed_qty}"
                )
                
                main = created_receipts[0]
                return {
                    'receipt_no': main['receipt_no'],
                    'receipt_id': main['receipt_id'],
                    'order_completed': False,  # Never auto-complete
                    'quantity': total_produced,
                    'batch_no': batch_no,
                    'quality_status': main['status'],
                    'receipts': created_receipts
                }
                
            except Exception as e:
                logger.error(f"❌ Error recording production for order {order_id}: {e}")
                raise
    
    # ==================== Close Order ====================
    
    def close_order(self, order_id: int, user_id: int) -> Dict[str, Any]:
        """
        Manually close a manufacturing order.
        
        Pre-conditions (validated inside transaction):
        1. MO.status == IN_PROGRESS
        2. At least 1 receipt exists
        3. Zero PENDING receipts
        4. RAW_MATERIALs issued
        
        Returns:
            Dict with success status and order info
        
        Raises:
            ValueError with specific message if validation fails
        """
        with self.engine.begin() as conn:
            try:
                order = self._get_order_info(conn, order_id)
                if not order:
                    raise ValueError(f"Order {order_id} not found")
                
                if order['status'] != 'IN_PROGRESS':
                    raise ValueError(f"Cannot close order: status is {order['status']}, must be IN_PROGRESS")
                
                # Check receipts exist
                receipt_check = text("""
                    SELECT COUNT(*) as cnt FROM production_receipts
                    WHERE manufacturing_order_id = :order_id
                """)
                receipt_count = int(conn.execute(receipt_check, {'order_id': order_id}).fetchone()[0])
                if receipt_count == 0:
                    raise ValueError("Cannot close order: no production receipts exist")
                
                # Check no PENDING receipts
                pending_check = text("""
                    SELECT COUNT(*) as cnt FROM production_receipts
                    WHERE manufacturing_order_id = :order_id AND quality_status = 'PENDING'
                """)
                pending_count = int(conn.execute(pending_check, {'order_id': order_id}).fetchone()[0])
                if pending_count > 0:
                    raise ValueError(f"Cannot close order: {pending_count} receipt(s) still have PENDING QC status")
                
                # Check raw materials issued
                unissued = self._get_unissued_raw_materials(conn, order_id)
                if unissued:
                    material_list = ", ".join([m['name'] for m in unissued[:3]])
                    raise ValueError(f"Cannot close order: {len(unissued)} raw material(s) not issued ({material_list})")
                
                # Close the order
                close_query = text("""
                    UPDATE manufacturing_orders
                    SET status = 'COMPLETED',
                        completion_date = NOW(),
                        closed_by = :user_id,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :order_id
                """)
                
                conn.execute(close_query, {
                    'order_id': order_id,
                    'user_id': user_id
                })
                
                logger.info(f"🔒 Closed manufacturing order {order['order_no']} (ID: {order_id}) by user {user_id}")
                
                return {
                    'success': True,
                    'order_no': order['order_no'],
                    'order_id': order_id
                }
                
            except Exception as e:
                logger.error(f"❌ Error closing order {order_id}: {e}")
                raise
    
    # ==================== Update Quality Status (Original - Full Batch) ====================
    
    def update_quality_status(self, receipt_id: int, new_status: str,
                             notes: str, user_id: int,
                             keycloak_id: str = None) -> bool:
        """
        Update quality status of a receipt (entire batch).
        
        Guards (v4.0):
        - MO must be IN_PROGRESS (COMPLETED = locked)
        - Only PENDING → PASSED or PENDING → FAILED allowed (one-way)
        
        Inventory Logic:
        - PENDING → PASSED: Create stockInProduction record
        - PENDING → FAILED: No inventory change
        """
        with self.engine.begin() as conn:
            try:
                receipt = self._get_receipt_info(conn, receipt_id)
                if not receipt:
                    raise ValueError(f"Receipt {receipt_id} not found")
                
                old_status = receipt['quality_status']
                
                # Guard: Check MO status
                order_status = self._get_order_status_for_receipt_tx(conn, receipt_id)
                if order_status == 'COMPLETED':
                    raise ValueError("Cannot update QC: order is COMPLETED and locked.")
                
                # Guard: One-way transitions only
                if old_status in ('PASSED', 'FAILED'):
                    raise ValueError(
                        f"Cannot change QC from {old_status}. "
                        f"Only PENDING receipts can be updated."
                    )
                
                if old_status == 'PENDING' and new_status not in ('PASSED', 'FAILED'):
                    raise ValueError("PENDING can only transition to PASSED or FAILED.")
                
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
        Update quality status with partial results support.
        
        Guards (v4.0):
        - MO must be IN_PROGRESS (COMPLETED = locked)
        - Only PENDING receipts can be updated
        - Cannot assign back to PENDING (one-way: PENDING → PASSED/FAILED only)
        """
        with self.engine.begin() as conn:
            try:
                receipt = self._get_receipt_info(conn, receipt_id)
                if not receipt:
                    return {'success': False, 'error': 'Receipt not found'}
                
                old_status = receipt['quality_status']
                
                # Guard: Check MO status
                order_status = self._get_order_status_for_receipt_tx(conn, receipt_id)
                if order_status == 'COMPLETED':
                    return {'success': False, 'error': 'Cannot update QC: order is COMPLETED and locked.'}
                
                # Guard: Only PENDING can be updated
                if old_status in ('PASSED', 'FAILED'):
                    return {
                        'success': False,
                        'error': f'Cannot change QC from {old_status}. Only PENDING receipts can be updated.'
                    }
                
                total_qty = float(receipt['quantity'])
                
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
    
    def _insert_receipt(self, conn, receipt_no: str, order_id: int, product_id,
                        quantity: float, uom: str, batch_no: str,
                        expired_date, warehouse_id: int, quality_status: str,
                        notes: str, defect_type: Optional[str],
                        user_id: int, parent_receipt_id: Optional[int]) -> int:
        """Insert a production receipt and return its ID"""
        query = text("""
            INSERT INTO production_receipts (
                receipt_no, manufacturing_order_id, receipt_date,
                product_id, quantity, uom, batch_no, expired_date,
                warehouse_id, quality_status, notes, defect_type,
                parent_receipt_id, created_by, created_date
            ) VALUES (
                :receipt_no, :order_id, NOW(),
                :product_id, :quantity, :uom, :batch_no, :expired_date,
                :warehouse_id, :quality_status, :notes, :defect_type,
                :parent_receipt_id, :user_id, NOW()
            )
        """)
        
        result = conn.execute(query, {
            'receipt_no': receipt_no,
            'order_id': order_id,
            'product_id': product_id,
            'quantity': quantity,
            'uom': uom,
            'batch_no': batch_no,
            'expired_date': expired_date,
            'warehouse_id': warehouse_id,
            'quality_status': quality_status,
            'notes': notes,
            'defect_type': defect_type,
            'parent_receipt_id': parent_receipt_id,
            'user_id': user_id
        })
        
        return result.lastrowid
    
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
    
    def _get_order_status_for_receipt_tx(self, conn, receipt_id: int) -> Optional[str]:
        """Get MO status for a receipt (within transaction)"""
        query = text("""
            SELECT mo.status
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            WHERE pr.id = :receipt_id
        """)
        result = conn.execute(query, {'receipt_id': receipt_id})
        row = result.fetchone()
        return row[0] if row else None
    
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