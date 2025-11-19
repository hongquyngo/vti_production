# utils/production/materials.py
"""
Material Issue, Return, and Production Completion Logic - REFACTORED v7.0
FEFO-based material issuing with automatic alternative substitution and conversion ratio tracking

MAJOR CHANGES v7.0:
✅ NEW: issued_qty trong manufacturing_order_materials = tổng EQUIVALENT (quy đổi về primary)
✅ NEW: material_issue_details ghi ACTUAL quantity xuất ra
✅ NEW: Hỗ trợ nhiều alternatives với conversion ratios khác nhau
✅ NEW: Return logic convert ngược về equivalent
✅ NEW: Helper functions: _get_bom_detail_info, _get_alternatives_for_material, _get_conversion_ratio
✅ MAINTAINED: All inventory_histories logic with fallback
✅ MAINTAINED: FEFO logic and batch tracking
✅ MAINTAINED: Full alternative material tracking
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import uuid
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== MAIN PUBLIC FUNCTIONS ====================

def issue_materials(order_id: int, user_id: int, keycloak_id: str, 
                   issued_by: int, received_by: int = None,
                   notes: str = None) -> Dict[str, Any]:
    """
    Issue materials for production using FEFO (First Expiry, First Out)
    with automatic alternative material substitution and tracking
    
    Args:
        order_id: Manufacturing order ID
        user_id: User ID for created_by (INT)
        keycloak_id: Keycloak ID for inventory tables (VARCHAR)
        issued_by: Employee ID of warehouse staff issuing materials (REQUIRED)
        received_by: Employee ID of production staff receiving materials
        notes: Optional notes about the issue
    
    Returns:
        Dictionary with issue_no, issue_id, details, substitutions
    
    Raises:
        ValueError: If order not found, invalid status, insufficient stock, or missing issued_by
    """
    engine = get_db_engine()
    
    # Validate required issued_by
    if issued_by is None:
        raise ValueError("issued_by is required - must specify warehouse staff employee ID")
    
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
            materials = _get_pending_materials(conn, order_id)
            issue_details = []
            substitutions = []
            
            # Issue each material using FEFO with alternative substitution
            for _, mat in materials.iterrows():
                remaining = float(mat['required_qty']) - float(mat['issued_qty'])
                if remaining > 0:
                    try:
                        issued = _issue_material_with_alternatives(
                            conn, issue_id, order_id, mat,
                            remaining, order['warehouse_id'], 
                            group_id, user_id, keycloak_id, 
                            order.get('entity_id', 1)
                        )
                        issue_details.extend(issued['details'])
                        if issued['substitutions']:
                            substitutions.extend(issued['substitutions'])
                    except ValueError as e:
                        logger.error(f"Failed to issue material {mat['material_name']}: {e}")
                        raise
            
            # Update order status to IN_PROGRESS
            status_query = text("""
                UPDATE manufacturing_orders
                SET status = 'IN_PROGRESS', 
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :order_id
            """)
            conn.execute(status_query, {
                'order_id': order_id,
                'user_id': user_id
            })
            
            logger.info(f"✅ Issued materials for order {order_id}, issue no: {issue_no}")
            if substitutions:
                logger.info(f"🔄 Material substitutions made: {len(substitutions)} items")
            
            return {
                'issue_no': issue_no,
                'issue_id': issue_id,
                'details': issue_details,
                'substitutions': substitutions
            }
            
        except Exception as e:
            logger.error(f"❌ Error issuing materials for order {order_id}: {e}")
            raise


def return_materials(order_id: int, returns: List[Dict],
                    reason: str, user_id: int, keycloak_id: str,
                    returned_by: int = None, received_by: int = None) -> Dict[str, Any]:
    """
    Return unused materials with validation and proper tracking
    
    Args:
        order_id: Production order ID
        returns: List of return items with issue_detail_id, quantity, etc.
        reason: Return reason code
        user_id: User ID for created_by (INT)
        keycloak_id: Keycloak ID for inventory tables (VARCHAR)
        returned_by: Employee ID of production staff returning materials
        received_by: Employee ID of warehouse staff receiving materials
        
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
            issue_row = issue_result.fetchone()
            if not issue_row:
                raise ValueError("No material issue found for this order")
            
            issue = dict(zip(issue_result.keys(), issue_row))
            
            # Validate all returns
            for ret in returns:
                _validate_return(conn, ret)
            
            # Create return header
            return_no = _generate_return_number(conn)
            group_id = str(uuid.uuid4())
            
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
                detail = _process_return_item(
                    conn, return_id, ret, order['warehouse_id'], 
                    group_id, user_id, keycloak_id, 
                    order.get('entity_id', 1)
                )
                return_details.append(detail)
            
            # Update manufacturing_order_materials issued quantities with conversion
            _update_order_materials_for_return(conn, return_details, order_id)
            
            logger.info(f"✅ Created return {return_no} for order {order_id}")
            
            return {
                'return_no': return_no,
                'return_id': return_id,
                'details': return_details
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing returns for order {order_id}: {e}")
            raise


def complete_production(order_id: int, produced_qty: float,
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
        Dictionary with receipt_no and details
    """
    engine = get_db_engine()
    
    with engine.begin() as conn:
        try:
            # Get order info
            order = _get_order_info(conn, order_id)
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            if order['status'] not in ['IN_PROGRESS']:
                raise ValueError(f"Cannot complete {order['status']} order")
            
            # Generate receipt number and group ID
            receipt_no = _generate_receipt_number(conn)
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
            if quality_status == 'PASSED':
                _add_production_to_inventory(
                    conn, order, produced_qty, batch_no,
                    warehouse_id, expiry_date, 
                    group_id, keycloak_id, 
                    order.get('entity_id', 1),
                    receipt_id
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
                'quantity': produced_qty,
                'batch_no': batch_no,
                'quality_status': quality_status,
                'order_completed': order_completed
            }
            
        except Exception as e:
            logger.error(f"❌ Error completing production for order {order_id}: {e}")
            raise


def get_returnable_materials(order_id: int) -> pd.DataFrame:
    """
    Get list of materials that can be returned for an order
    
    Returns DataFrame with columns:
    - issue_detail_id, material_id, material_name, batch_no,
    - issued_qty, returned_qty, returnable_qty, uom, expired_date,
    - issue_date, is_alternative, original_material_id
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            mid.id as issue_detail_id,
            mid.material_id,
            p.name as material_name,
            mid.batch_no,
            mid.quantity as issued_qty,
            COALESCE(SUM(mrd.quantity), 0) as returned_qty,
            mid.quantity - COALESCE(SUM(mrd.quantity), 0) as returnable_qty,
            mid.uom,
            mid.expired_date,
            mi.issue_date,
            COALESCE(mid.is_alternative, 0) as is_alternative,
            mid.original_material_id,
            CASE 
                WHEN mid.is_alternative = 1 THEN 
                    CONCAT(p.name, ' (Alt for: ', p2.name, ')')
                ELSE p.name
            END as display_name
        FROM material_issues mi
        JOIN material_issue_details mid ON mi.id = mid.material_issue_id
        JOIN products p ON mid.material_id = p.id
        LEFT JOIN products p2 ON mid.original_material_id = p2.id
        LEFT JOIN material_return_details mrd 
            ON mrd.original_issue_detail_id = mid.id
        LEFT JOIN material_returns mr 
            ON mr.id = mrd.material_return_id AND mr.status = 'CONFIRMED'
        WHERE mi.manufacturing_order_id = %s
            AND mi.status = 'CONFIRMED'
        GROUP BY mid.id, mid.material_id, p.name, mid.batch_no, 
                 mid.quantity, mid.uom, mid.expired_date,
                 mid.is_alternative, mid.original_material_id, p2.name,
                 mi.issue_date
        HAVING returnable_qty > 0
        ORDER BY p.name, mid.batch_no
    """
    
    try:
        return pd.read_sql(query, engine, params=(order_id,))
    except Exception as e:
        logger.error(f"❌ Error getting returnable materials: {e}")
        return pd.DataFrame()


# ==================== CORE ISSUE LOGIC ====================

def _issue_material_with_alternatives(conn, issue_id: int, order_id: int,
                                     material: pd.Series, required_qty: float,
                                     warehouse_id: int, group_id: str,
                                     user_id: int, keycloak_id: str,
                                     entity_id: int) -> Dict[str, Any]:
    """
    Issue material using FEFO, automatically substituting alternatives if needed
    
    Key: Track cả actual quantity và equivalent quantity
    - actual: số lượng thực xuất (ghi vào material_issue_details)
    - equivalent: quy đổi về primary (cộng vào issued_qty)
    
    Returns:
        Dictionary with issued details and substitution info
    """
    issued_details = []
    substitutions = []
    remaining_equivalent = float(required_qty)  # Remaining tính theo equivalent
    
    # Get BOM detail info for this material (cần cho conversion ratio)
    bom_info = _get_bom_detail_info(conn, material['order_material_id'])
    primary_bom_qty = float(bom_info['quantity']) if bom_info else 1.0
    
    # === TRY PRIMARY MATERIAL FIRST ===
    primary_equivalent_issued = 0.0
    try:
        primary_details = _issue_single_material_fefo(
            conn, issue_id, order_id, material, 
            remaining_equivalent,  # Primary: equivalent = actual
            warehouse_id, group_id, user_id, keycloak_id, entity_id,
            is_alternative=False, 
            original_material_id=None,
            conversion_ratio=1.0  # Primary ratio = 1
        )
        issued_details.extend(primary_details)
        
        # Primary: actual = equivalent
        for detail in primary_details:
            primary_equivalent_issued += float(detail['quantity'])
        
        remaining_equivalent -= primary_equivalent_issued
        
    except ValueError as e:
        # Insufficient stock for primary - log but continue with alternatives
        logger.warning(f"⚠️ Insufficient primary material {material['material_name']}: {e}")
    
    # === TRY ALTERNATIVES IF NEEDED ===
    if remaining_equivalent > 0 and bom_info:
        # Get alternatives ordered by priority
        alternatives = _get_alternatives_for_material(conn, bom_info['bom_detail_id'])
        
        # Try each alternative in priority order
        for alt in alternatives:
            if remaining_equivalent <= 0:
                break
            
            try:
                # Calculate conversion ratio
                conversion_ratio = float(alt['quantity']) / primary_bom_qty
                
                # Calculate actual quantity needed for alternative
                alt_actual_qty = remaining_equivalent * conversion_ratio
                
                # Create temporary material data for alternative
                alt_material = pd.Series({
                    'order_material_id': material['order_material_id'],
                    'material_id': alt['alternative_material_id'],
                    'material_name': alt['alternative_material_name'],
                    'uom': alt['uom']
                })
                
                # Try issuing alternative with tracking
                alt_details = _issue_single_material_fefo(
                    conn, issue_id, order_id, alt_material, 
                    alt_actual_qty,  # Actual quantity
                    warehouse_id, group_id, user_id, keycloak_id, entity_id,
                    is_alternative=True, 
                    original_material_id=material['material_id'],
                    conversion_ratio=conversion_ratio
                )
                
                # Calculate equivalent issued from this alternative
                alt_actual_issued = sum(float(d['quantity']) for d in alt_details)
                alt_equivalent_issued = alt_actual_issued / conversion_ratio
                
                if alt_actual_issued > 0:
                    issued_details.extend(alt_details)
                    
                    # Record substitution with both actual and equivalent
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
                    
                    remaining_equivalent -= alt_equivalent_issued
                    logger.info(
                        f"🔄 Substituted {alt_actual_issued} {alt['uom']} of "
                        f"{alt['alternative_material_name']} "
                        f"(equivalent: {alt_equivalent_issued:.4f}) "
                        f"for {material['material_name']}"
                    )
                
            except ValueError as e:
                logger.warning(f"⚠️ Alternative {alt['alternative_material_name']} also insufficient: {e}")
                continue
        
        # Check if we fulfilled the requirement
        if remaining_equivalent > 0:
            total_equivalent = float(required_qty) - float(remaining_equivalent)
            if total_equivalent == 0:
                raise ValueError(f"No materials available (primary or alternatives) for {material['material_name']}")
            else:
                logger.warning(
                    f"⚠️ Only partial issue possible for {material['material_name']}: "
                    f"{total_equivalent}/{required_qty} (equivalent)"
                )
    
    return {
        'details': issued_details,
        'substitutions': substitutions
    }


def _issue_single_material_fefo(conn, issue_id: int, order_id: int,
                               material: pd.Series, required_qty: float,
                               warehouse_id: int, group_id: str, 
                               user_id: int, keycloak_id: str, entity_id: int,
                               is_alternative: bool = False,
                               original_material_id: Optional[int] = None,
                               conversion_ratio: float = 1.0) -> List[Dict]:
    """
    Issue single material using FEFO with alternative tracking
    
    Args:
        issue_id: Material issue ID
        order_id: Manufacturing order ID
        material: Material series with material_id, name, etc.
        required_qty: ACTUAL quantity to issue (not equivalent)
        warehouse_id: Source warehouse
        group_id: Transaction group ID
        user_id: User ID for manufacturing tables (INT)
        keycloak_id: Keycloak ID for inventory tables (VARCHAR)
        entity_id: Company/Entity ID
        is_alternative: Whether this is an alternative material
        original_material_id: ID of original material if this is alternative
        conversion_ratio: Ratio to convert actual -> equivalent (alt_qty / primary_qty)
    
    Returns:
        List of issued details with actual quantities
    """
    # Get available batches using FEFO
    batch_query = text("""
        SELECT 
            id as inventory_history_id,
            batch_no,
            expired_date,
            remain as available_qty
        FROM inventory_histories
        WHERE product_id = :material_id
            AND warehouse_id = :warehouse_id
            AND remain > 0
            AND delete_flag = 0
        ORDER BY 
            COALESCE(expired_date, '2099-12-31') ASC,  -- FEFO
            created_date ASC                           -- FIFO as secondary
        FOR UPDATE
    """)
    
    batch_result = conn.execute(batch_query, {
        'material_id': material['material_id'],
        'warehouse_id': warehouse_id
    })
    
    batches = []
    for row in batch_result:
        batches.append(dict(zip(batch_result.keys(), row)))
    
    if not batches:
        raise ValueError(f"No stock available for material {material['material_name']}")
    
    # Issue from batches
    issued_details = []
    total_actual_issued = 0.0
    total_equivalent_issued = 0.0
    
    for batch in batches:
        if total_actual_issued >= required_qty:
            break
        
        # Calculate quantity to issue from this batch
        batch_available = float(batch['available_qty'])
        required_remaining = float(required_qty) - float(total_actual_issued)
        issue_qty = min(batch_available, required_remaining)
        
        # Insert issue detail with alternative tracking (actual quantity)
        detail_id = _insert_issue_detail(
            conn, issue_id, material['order_material_id'],
            material['material_id'], batch, issue_qty, material['uom'],
            is_alternative, original_material_id
        )
        
        # Update inventory with proper operation tracking
        _update_inventory_for_issue(
            conn, batch['inventory_history_id'], material['material_id'],
            warehouse_id, issue_qty, group_id, keycloak_id, 
            entity_id, issue_id
        )
        
        issued_details.append({
            'detail_id': detail_id,
            'material_id': material['material_id'],
            'material_name': material['material_name'],
            'batch_no': batch['batch_no'],
            'quantity': issue_qty,  # Actual quantity
            'uom': material['uom'],
            'expired_date': batch['expired_date'],
            'is_alternative': is_alternative,
            'original_material_id': original_material_id,
            'conversion_ratio': conversion_ratio
        })
        
        total_actual_issued += issue_qty
        total_equivalent_issued += issue_qty / conversion_ratio
    
    if total_actual_issued < required_qty:
        raise ValueError(f"Insufficient stock: required {required_qty}, available {total_actual_issued}")
    
    # Update manufacturing_order_materials với EQUIVALENT quantity
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


# ==================== RETURN LOGIC ====================

def _update_order_materials_for_return(conn, return_details: List[Dict], order_id: int):
    """
    Update manufacturing_order_materials after return
    
    Key: Convert return quantity về equivalent trước khi trừ issued_qty
    """
    for detail in return_details:
        # Get original issue detail để lấy conversion info
        issue_detail_query = text("""
            SELECT 
                mid.material_id,
                mid.is_alternative,
                mid.original_material_id,
                mid.manufacturing_order_material_id,
                mom.material_id as primary_material_id
            FROM material_issue_details mid
            JOIN manufacturing_order_materials mom 
                ON mid.manufacturing_order_material_id = mom.id
            WHERE mid.id = :issue_detail_id
        """)
        
        result = conn.execute(issue_detail_query, {
            'issue_detail_id': detail['original_issue_detail_id']
        })
        issue_info = dict(zip(result.keys(), result.fetchone()))
        
        return_qty = float(detail['quantity'])
        
        # Calculate equivalent quantity
        if issue_info['is_alternative']:
            # Get conversion ratio for this alternative
            conversion_ratio = _get_conversion_ratio(
                conn, 
                issue_info['manufacturing_order_material_id'],
                issue_info['material_id']
            )
            equivalent_returned = return_qty / conversion_ratio
        else:
            # Primary material: equivalent = actual
            equivalent_returned = return_qty
        
        # Update issued_qty với equivalent
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
            'order_material_id': issue_info['manufacturing_order_material_id']
        })
        
        logger.info(
            f"📦 Returned {return_qty} (equivalent: {equivalent_returned:.4f}) "
            f"for material_id {issue_info['material_id']}"
        )


# ==================== HELPER FUNCTIONS ====================

def _get_order_info(conn, order_id: int) -> Optional[Dict]:
    """Get order information with necessary fields"""
    query = text("""
        SELECT 
            mo.id,
            mo.order_no,
            mo.status,
            mo.product_id,
            mo.planned_qty,
            mo.uom,
            mo.warehouse_id,
            mo.entity_id
        FROM manufacturing_orders mo
        WHERE mo.id = :order_id
            AND mo.delete_flag = 0
        FOR UPDATE
    """)
    
    result = conn.execute(query, {'order_id': order_id})
    row = result.fetchone()
    
    if not row:
        return None
    
    return dict(zip(result.keys(), row))


def _get_pending_materials(conn, order_id: int) -> pd.DataFrame:
    """Get materials pending issue for an order"""
    query = text("""
        SELECT 
            mom.id as order_material_id,
            mom.material_id,
            p.name as material_name,
            mom.required_qty,
            COALESCE(mom.issued_qty, 0) as issued_qty,
            mom.uom,
            mom.status
        FROM manufacturing_order_materials mom
        JOIN products p ON mom.material_id = p.id
        WHERE mom.manufacturing_order_id = :order_id
            AND mom.status IN ('PENDING', 'PARTIAL')
        ORDER BY p.name
    """)
    
    result = conn.execute(query, {'order_id': order_id})
    
    # Convert to DataFrame
    rows = []
    for row in result:
        rows.append(dict(zip(result.keys(), row)))
    
    return pd.DataFrame(rows)


def _get_bom_detail_info(conn, order_material_id: int) -> Optional[Dict]:
    """Get BOM detail info for a manufacturing order material"""
    query = text("""
        SELECT 
            bd.id as bom_detail_id,
            bd.quantity,
            bd.uom
        FROM manufacturing_order_materials mom
        JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
        JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
            AND bd.material_id = mom.material_id
        WHERE mom.id = :order_material_id
    """)
    
    result = conn.execute(query, {'order_material_id': order_material_id})
    row = result.fetchone()
    
    return dict(zip(result.keys(), row)) if row else None


def _get_alternatives_for_material(conn, bom_detail_id: int) -> List[Dict]:
    """Get active alternatives ordered by priority"""
    query = text("""
        SELECT 
            alt.id as alternative_id,
            alt.alternative_material_id,
            p.name as alternative_material_name,
            alt.quantity,
            alt.uom,
            alt.scrap_rate,
            alt.priority
        FROM bom_material_alternatives alt
        JOIN products p ON alt.alternative_material_id = p.id
        WHERE alt.bom_detail_id = :bom_detail_id
            AND alt.is_active = 1
        ORDER BY alt.priority ASC
    """)
    
    result = conn.execute(query, {'bom_detail_id': bom_detail_id})
    return [dict(zip(result.keys(), row)) for row in result]


def _get_conversion_ratio(conn, order_material_id: int, 
                         alternative_material_id: int) -> float:
    """
    Get conversion ratio for alternative material
    
    Returns: alternative_qty / primary_qty
    """
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
    """)
    
    result = conn.execute(query, {
        'order_material_id': order_material_id,
        'alt_material_id': alternative_material_id
    })
    
    row = result.fetchone()
    if not row:
        logger.warning(
            f"Conversion ratio not found for order_material {order_material_id}, "
            f"alternative {alternative_material_id}. Using 1.0"
        )
        return 1.0
    
    row_dict = dict(zip(result.keys(), row))
    return float(row_dict['alt_qty']) / float(row_dict['primary_qty'])


def _validate_return(conn, return_item: Dict):
    """Validate return item"""
    query = text("""
        SELECT 
            mid.quantity as issued_qty,
            COALESCE(SUM(mrd.quantity), 0) as returned_qty
        FROM material_issue_details mid
        LEFT JOIN material_return_details mrd 
            ON mrd.original_issue_detail_id = mid.id
        WHERE mid.id = :issue_detail_id
        GROUP BY mid.quantity
    """)
    
    result = conn.execute(query, {'issue_detail_id': return_item['issue_detail_id']})
    row = result.fetchone()
    
    if not row:
        raise ValueError(f"Issue detail {return_item['issue_detail_id']} not found")
    
    data = dict(zip(result.keys(), row))
    available = data['issued_qty'] - data['returned_qty']
    
    if return_item['quantity'] > available:
        raise ValueError(f"Cannot return {return_item['quantity']}, only {available} available")


def _insert_issue_detail(conn, issue_id: int, order_material_id: int,
                        material_id: int, batch_info: Dict, quantity: float, 
                        uom: str, is_alternative: bool = False,
                        original_material_id: Optional[int] = None) -> int:
    """
    Insert issue detail with alternative tracking
    
    Returns:
        Inserted detail ID
    """
    # First check if alternative tracking columns exist
    check_columns_query = text("""
        SELECT COUNT(*) as col_count
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE table_schema = DATABASE() 
            AND table_name = 'material_issue_details' 
            AND column_name IN ('is_alternative', 'original_material_id')
    """)
    
    result = conn.execute(check_columns_query)
    col_count = result.fetchone()[0]
    
    if col_count == 2:
        # New columns exist, use enhanced query
        detail_query = text("""
            INSERT INTO material_issue_details (
                material_issue_id, manufacturing_order_material_id,
                material_id, inventory_history_id, batch_no,
                quantity, uom, expired_date,
                is_alternative, original_material_id
            ) VALUES (
                :issue_id, :order_material_id,
                :material_id, :inv_history_id, :batch_no,
                :quantity, :uom, :expired_date,
                :is_alternative, :original_material_id
            )
        """)
        
        params = {
            'issue_id': issue_id,
            'order_material_id': order_material_id,
            'material_id': material_id,
            'inv_history_id': batch_info['inventory_history_id'],
            'batch_no': batch_info['batch_no'],
            'quantity': quantity,
            'uom': uom,
            'expired_date': batch_info['expired_date'],
            'is_alternative': 1 if is_alternative else 0,
            'original_material_id': original_material_id
        }
    else:
        # Use basic query without new columns
        detail_query = text("""
            INSERT INTO material_issue_details (
                material_issue_id, manufacturing_order_material_id,
                material_id, inventory_history_id, batch_no,
                quantity, uom, expired_date
            ) VALUES (
                :issue_id, :order_material_id,
                :material_id, :inv_history_id, :batch_no,
                :quantity, :uom, :expired_date
            )
        """)
        
        params = {
            'issue_id': issue_id,
            'order_material_id': order_material_id,
            'material_id': material_id,
            'inv_history_id': batch_info['inventory_history_id'],
            'batch_no': batch_info['batch_no'],
            'quantity': quantity,
            'uom': uom,
            'expired_date': batch_info['expired_date']
        }
    
    result = conn.execute(detail_query, params)
    return result.lastrowid


def _update_inventory_for_issue(conn, inv_history_id: int, material_id: int,
                               warehouse_id: int, quantity: float,
                               group_id: str, keycloak_id: str,
                               entity_id: int, issue_id: int):
    """
    Update inventory for material issue with proper tracking
    
    CRITICAL: Uses keycloak_id for created_by (VARCHAR), not user_id (INT)
    Checks if operation/reference columns exist before using them
    """
    # Update remain in original record
    update_query = text("""
        UPDATE inventory_histories
        SET remain = remain - :quantity
        WHERE id = :inv_history_id AND remain >= :quantity
    """)
    
    result = conn.execute(update_query, {
        'quantity': quantity,
        'inv_history_id': inv_history_id
    })
    
    if result.rowcount == 0:
        raise ValueError("Inventory update failed - concurrent modification")
    
    # Create OUT record with proper operation tracking
    # Check if new columns exist
    check_columns_query = text("""
        SELECT COUNT(*) as col_count
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE table_schema = DATABASE() 
            AND table_name = 'inventory_histories' 
            AND column_name IN ('operation', 'reference_type', 'reference_id', 'entity_id')
    """)
    
    result = conn.execute(check_columns_query)
    col_count = result.fetchone()[0]
    
    if col_count == 4:
        # New columns exist - use enhanced tracking
        out_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type, operation,
                quantity, remain, group_id, 
                reference_type, reference_id, entity_id,
                created_by, created_date
            ) VALUES (
                :material_id, :warehouse_id, 'OUT', 'stockOutProduction',
                :quantity, 0, :group_id,
                'MATERIAL_ISSUE', :issue_id, :entity_id,
                :created_by, NOW()
            )
        """)
        
        conn.execute(out_query, {
            'material_id': material_id,
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'group_id': group_id,
            'issue_id': issue_id,
            'entity_id': entity_id,
            'created_by': keycloak_id
        })
    else:
        # Fallback to basic tracking
        out_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type, quantity, remain,
                group_id, created_by, created_date
            ) VALUES (
                :material_id, :warehouse_id, 'OUT', :quantity, 0,
                :group_id, :created_by, NOW()
            )
        """)
        
        conn.execute(out_query, {
            'material_id': material_id,
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'group_id': group_id,
            'created_by': keycloak_id
        })


def _process_return_item(conn, return_id: int, return_item: Dict,
                        warehouse_id: int, group_id: str, 
                        user_id: int, keycloak_id: str, entity_id: int) -> Dict:
    """
    Process single return item with proper tracking
    
    CRITICAL: Preserves alternative tracking from original issue
    """
    # Get original issue details INCLUDING alternative tracking
    query = text("""
        SELECT 
            mid.material_id, 
            mid.batch_no, 
            mid.expired_date,
            mid.uom,
            COALESCE(mid.is_alternative, 0) as is_alternative,
            mid.original_material_id
        FROM material_issue_details mid
        WHERE mid.id = :issue_detail_id
    """)
    
    result = conn.execute(query, {'issue_detail_id': return_item['issue_detail_id']})
    row = result.fetchone()
    issue_detail = dict(zip(result.keys(), row))
    
    # Check if material_return_details has alternative tracking columns
    check_return_columns = text("""
        SELECT COUNT(*) as col_count
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE table_schema = DATABASE() 
            AND table_name = 'material_return_details' 
            AND column_name IN ('is_alternative', 'original_material_id')
    """)
    
    result = conn.execute(check_return_columns)
    has_alt_columns = result.fetchone()[0] == 2
    
    if has_alt_columns:
        # Insert return detail WITH alternative tracking
        detail_query = text("""
            INSERT INTO material_return_details (
                material_return_id, material_id, original_issue_detail_id,
                batch_no, quantity, uom, `condition`, expired_date,
                is_alternative, original_material_id
            ) VALUES (
                :return_id, :material_id, :issue_detail_id,
                :batch_no, :quantity, :uom, :condition, :expired_date,
                :is_alternative, :original_material_id
            )
        """)
        
        conn.execute(detail_query, {
            'return_id': return_id,
            'material_id': issue_detail['material_id'],
            'issue_detail_id': return_item['issue_detail_id'],
            'batch_no': issue_detail['batch_no'],
            'quantity': return_item['quantity'],
            'uom': issue_detail['uom'],
            'condition': return_item.get('condition', 'GOOD'),
            'expired_date': issue_detail['expired_date'],
            'is_alternative': issue_detail['is_alternative'],
            'original_material_id': issue_detail['original_material_id']
        })
    else:
        # Fallback to basic return detail
        detail_query = text("""
            INSERT INTO material_return_details (
                material_return_id, material_id, original_issue_detail_id,
                batch_no, quantity, uom, `condition`, expired_date
            ) VALUES (
                :return_id, :material_id, :issue_detail_id,
                :batch_no, :quantity, :uom, :condition, :expired_date
            )
        """)
        
        conn.execute(detail_query, {
            'return_id': return_id,
            'material_id': issue_detail['material_id'],
            'issue_detail_id': return_item['issue_detail_id'],
            'batch_no': issue_detail['batch_no'],
            'quantity': return_item['quantity'],
            'uom': issue_detail['uom'],
            'condition': return_item.get('condition', 'GOOD'),
            'expired_date': issue_detail['expired_date']
        })
    
    # Add back to inventory if condition is GOOD
    if return_item.get('condition', 'GOOD') == 'GOOD':
        _update_inventory_for_return(
            conn, issue_detail, return_item['quantity'],
            warehouse_id, group_id, keycloak_id, entity_id, return_id
        )
    
    return {
        'material_id': issue_detail['material_id'],
        'quantity': return_item['quantity'],
        'condition': return_item.get('condition', 'GOOD'),
        'is_alternative': issue_detail['is_alternative'],
        'original_issue_detail_id': return_item['issue_detail_id']
    }


def _update_inventory_for_return(conn, issue_detail: Dict, quantity: float,
                                warehouse_id: int, group_id: str, 
                                keycloak_id: str, entity_id: int, return_id: int):
    """
    Update inventory for material return with proper tracking
    
    CRITICAL: Uses keycloak_id for created_by (VARCHAR), not user_id (INT)
    """
    # Check if new columns exist
    check_columns_query = text("""
        SELECT COUNT(*) as col_count
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE table_schema = DATABASE() 
            AND table_name = 'inventory_histories' 
            AND column_name IN ('operation', 'reference_type', 'reference_id', 'entity_id')
    """)
    
    result = conn.execute(check_columns_query)
    col_count = result.fetchone()[0]
    
    if col_count == 4:
        # New columns exist - use enhanced tracking
        inv_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type, operation,
                quantity, remain, batch_no, expired_date, 
                group_id, reference_type, reference_id, entity_id,
                created_by, created_date
            ) VALUES (
                :material_id, :warehouse_id, 'IN', 'stockInProductionReturn',
                :quantity, :quantity, :batch_no, :expired_date,
                :group_id, 'MATERIAL_RETURN', :return_id, :entity_id,
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
            'return_id': return_id,
            'entity_id': entity_id,
            'created_by': keycloak_id
        })
    else:
        # Fallback to basic tracking
        inv_query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type, quantity, remain,
                batch_no, expired_date, group_id, created_by, created_date
            ) VALUES (
                :material_id, :warehouse_id, 'IN', :quantity, :quantity,
                :batch_no, :expired_date, :group_id, :created_by, NOW()
            )
        """)
        
        conn.execute(inv_query, {
            'material_id': issue_detail['material_id'],
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'batch_no': issue_detail['batch_no'],
            'expired_date': issue_detail['expired_date'],
            'group_id': group_id,
            'created_by': keycloak_id
        })


def _add_production_to_inventory(conn, order: Dict, quantity: float,
                                batch_no: str, warehouse_id: int,
                                expiry_date: Optional[date],
                                group_id: str, keycloak_id: str, 
                                entity_id: int, receipt_id: int):
    """
    Add production output to inventory with proper tracking
    
    CRITICAL: Uses keycloak_id for created_by (VARCHAR), not user_id (INT)
    """
    # Check if new columns exist
    check_columns_query = text("""
        SELECT COUNT(*) as col_count
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE table_schema = DATABASE() 
            AND table_name = 'inventory_histories' 
            AND column_name IN ('operation', 'reference_type', 'reference_id', 'entity_id')
    """)
    
    result = conn.execute(check_columns_query)
    col_count = result.fetchone()[0]
    
    if col_count == 4:
        # New columns exist - use enhanced tracking
        query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type, operation,
                quantity, remain, batch_no, expired_date,
                group_id, reference_type, reference_id, entity_id,
                created_by, created_date
            ) VALUES (
                :product_id, :warehouse_id, 'IN', 'stockInProduction',
                :quantity, :quantity, :batch_no, :expired_date,
                :group_id, 'PRODUCTION_RECEIPT', :receipt_id, :entity_id,
                :created_by, NOW()
            )
        """)
        
        conn.execute(query, {
            'product_id': order['product_id'],
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'batch_no': batch_no,
            'expired_date': expiry_date,
            'group_id': group_id,
            'receipt_id': receipt_id,
            'entity_id': entity_id,
            'created_by': keycloak_id
        })
    else:
        # Fallback to basic tracking
        query = text("""
            INSERT INTO inventory_histories (
                product_id, warehouse_id, type, quantity, remain,
                batch_no, expired_date, group_id, created_by, created_date
            ) VALUES (
                :product_id, :warehouse_id, 'IN', :quantity, :quantity,
                :batch_no, :expired_date, :group_id, :created_by, NOW()
            )
        """)
        
        conn.execute(query, {
            'product_id': order['product_id'],
            'warehouse_id': warehouse_id,
            'quantity': quantity,
            'batch_no': batch_no,
            'expired_date': expiry_date,
            'group_id': group_id,
            'created_by': keycloak_id
        })


# ==================== NUMBER GENERATORS ====================

def _generate_issue_number(conn) -> str:
    """Generate unique issue number matching DB schema format MI-YYYYMMDD-XXX"""
    timestamp = datetime.now().strftime('%Y%m%d')
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


def _generate_return_number(conn) -> str:
    """Generate unique return number matching DB schema format MR-YYYYMMDD-XXX"""
    timestamp = datetime.now().strftime('%Y%m%d')
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


def _generate_receipt_number(conn) -> str:
    """Generate unique receipt number matching DB schema format PR-YYYYMMDD-XXX"""
    timestamp = datetime.now().strftime('%Y%m%d')
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