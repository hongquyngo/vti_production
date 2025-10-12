# utils/production/materials.py
"""
Material Issue, Return, and Production Completion Logic
FEFO-based material issuing and production completion
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import uuid
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


def issue_materials(order_id: int, user_id: int) -> Dict[str, Any]:
    """
    Issue materials for production using FEFO (First Expiry, First Out)
    
    Raises:
        ValueError: If order not found, invalid status, or insufficient stock
    """
    engine = get_db_engine()
    
    with engine.begin() as conn:
        try:
            # Get order info with lock
            order = _get_order_info(conn, order_id)
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            if order['status'] not in ['DRAFT', 'CONFIRMED']:
                raise ValueError(f"Cannot issue materials for {order['status']} order")
            
            # Generate issue number and group ID
            issue_no = _generate_issue_number(conn)
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
            materials = _get_pending_materials(conn, order_id)
            issue_details = []
            
            # Issue each material using FEFO
            for _, mat in materials.iterrows():
                remaining = mat['required_qty'] - mat['issued_qty']
                if remaining > 0:
                    issued = _issue_material_fefo(
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
            
            logger.info(f"Issued materials for order {order_id}, issue no: {issue_no}")
            
            return {
                'issue_no': issue_no,
                'issue_id': issue_id,
                'details': issue_details
            }
            
        except Exception as e:
            logger.error(f"Error issuing materials for order {order_id}: {e}")
            raise


def return_materials(order_id: int, returns: List[Dict],
                    reason: str, user_id: int) -> Dict[str, Any]:
    """
    Return unused materials with validation
    
    Args:
        order_id: Production order ID
        returns: List of return items with issue_detail_id, quantity, etc.
        reason: Return reason code
        user_id: User performing the return
        
    Returns:
        Dictionary with return_no and details
    """
    engine = get_db_engine()
    
    with engine.begin() as conn:
        try:
            # Get order info
            order = _get_order_info(conn, order_id)
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
            
            # Validate all returns
            for ret in returns:
                _validate_return_quantity(conn, ret['issue_detail_id'], ret['quantity'])
            
            # Generate return number
            return_no = _generate_return_number(conn)
            
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
                
                # Create stock in record
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
                    'quantity': ret['quantity'],
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
            
            logger.info(f"Returned materials for order {order_id}, return no: {return_no}")
            
            return {
                'return_no': return_no,
                'return_id': return_id,
                'details': return_details
            }
            
        except Exception as e:
            logger.error(f"Error returning materials for order {order_id}: {e}")
            raise


def complete_production(order_id: int, produced_qty: float,
                       batch_no: str, quality_status: str,
                       notes: str, user_id: int,
                       expired_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Complete production order and create finished goods receipt
    
    Args:
        order_id: Production order ID
        produced_qty: Actual quantity produced
        batch_no: Batch number for finished goods
        quality_status: Quality check result (PASSED/FAILED/PENDING)
        notes: Production notes
        user_id: User completing the order
        expired_date: Optional expiry date for finished goods
        
    Returns:
        Dictionary with receipt details
    """
    engine = get_db_engine()
    
    with engine.begin() as conn:
        try:
            # Get order info
            order = _get_order_info(conn, order_id)
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            if order['status'] != 'IN_PROGRESS':
                raise ValueError(f"Cannot complete {order['status']} order")
            
            if produced_qty <= 0:
                raise ValueError("Produced quantity must be positive")
            
            # Generate receipt number
            receipt_no = _generate_receipt_number(conn)
            
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
            
            # Create stock in record
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
                'quantity': produced_qty,
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
            
            logger.info(f"Completed production order {order_id}, receipt no: {receipt_no}")
            
            return {
                'receipt_no': receipt_no,
                'receipt_id': receipt_id,
                'batch_no': batch_no,
                'quantity': produced_qty,
                'quality_status': quality_status
            }
            
        except Exception as e:
            logger.error(f"Error completing production for order {order_id}: {e}")
            raise


def get_returnable_materials(order_id: int) -> pd.DataFrame:
    """Get materials that can be returned for an order"""
    engine = get_db_engine()
    
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
        return pd.read_sql(query, engine, params=(order_id,))
    except Exception as e:
        logger.error(f"Error getting returnable materials for order {order_id}: {e}")
        return pd.DataFrame()


# ==================== Helper Functions ====================

def _get_order_info(conn, order_id: int) -> Optional[Dict]:
    """Get order information with lock"""
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
    return dict(row._mapping) if row else None


def _get_pending_materials(conn, order_id: int) -> pd.DataFrame:
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


def _issue_material_fefo(conn, issue_id: int, order_id: int,
                         material: pd.Series, required_qty: float,
                         warehouse_id: int, group_id: str, user_id: int) -> List[Dict]:
    """
    Issue single material using FEFO (First Expiry, First Out)
    
    Raises:
        ValueError: If insufficient stock available
    """
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
        
        # Create stock out record
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
            'quantity': take_qty,
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
    
    # ⭐ CRITICAL FIX: Raise error if insufficient stock
    if remaining > 0:
        raise ValueError(
            f"Insufficient stock for material '{material['material_name']}': "
            f"Required {required_qty} {material['uom']}, "
            f"Available {required_qty - remaining} {material['uom']}, "
            f"Short by {remaining} {material['uom']}"
        )
    
    return issued_details


def _validate_return_quantity(conn, issue_detail_id: int, return_qty: float):
    """Validate return quantity doesn't exceed issued quantity"""
    query = text("""
        SELECT 
            mid.quantity as issued_qty,
            COALESCE(SUM(mrd.quantity), 0) as previously_returned
        FROM material_issue_details mid
        LEFT JOIN material_return_details mrd 
            ON mrd.original_issue_detail_id = mid.id
        LEFT JOIN material_returns mr 
            ON mr.id = mrd.material_return_id AND mr.status = 'CONFIRMED'
        WHERE mid.id = :issue_detail_id
        GROUP BY mid.quantity
    """)
    
    result = conn.execute(query, {'issue_detail_id': issue_detail_id})
    row = result.fetchone()
    
    if not row:
        raise ValueError(f"Issue detail {issue_detail_id} not found")
    
    total_returns = float(row['previously_returned']) + return_qty
    
    if total_returns > float(row['issued_qty']):
        raise ValueError(
            f"Cannot return {return_qty}. "
            f"Issued: {row['issued_qty']}, "
            f"Previously returned: {row['previously_returned']}"
        )


def _generate_issue_number(conn) -> str:
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
    next_num = int(next_num) if next_num is not None else 1
    
    return f"MI-{timestamp}-{next_num:04d}"


def _generate_return_number(conn) -> str:
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
    next_num = int(next_num) if next_num is not None else 1
    
    return f"MR-{timestamp}-{next_num:04d}"


def _generate_receipt_number(conn) -> str:
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
    next_num = int(next_num) if next_num is not None else 1
    
    return f"PR-{timestamp}-{next_num:04d}"