# utils/production/materials.py
"""
Material Issue, Return, and Production Completion Logic - REFACTORED v6.1 BACKWARD COMPATIBLE
FEFO-based material issuing with automatic alternative substitution and tracking

MAJOR CHANGES v6.1 (Backward Compatible Fix):
✅ FIXED: Removed entity_id from material_issues INSERT (column doesn't exist in DB)
✅ FIXED: Removed entity_id and group_id from material_returns INSERT (columns don't exist)
✅ FIXED: Removed entity_id from production_receipts INSERT (column doesn't exist)
✅ FIXED: Updated function signatures to remove entity_id parameter
✅ MAINTAINED: All inventory_histories logic with fallback (checks if columns exist)
✅ MAINTAINED: Full alternative material tracking and substitution logic
✅ MAINTAINED: FEFO logic and batch tracking
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import uuid
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


def issue_materials(order_id: int, user_id: int, keycloak_id: str, 
                   issued_by: int = None, received_by: int = None,
                   notes: str = None) -> Dict[str, Any]:
    """
    Issue materials for production using FEFO (First Expiry, First Out)
    with automatic alternative material substitution and tracking
    
    Args:
        order_id: Manufacturing order ID
        user_id: User ID for created_by (INT)
        keycloak_id: Keycloak ID for inventory tables (VARCHAR)
        issued_by: Employee ID of warehouse staff issuing materials
        received_by: Employee ID of production staff receiving materials
        notes: Optional notes about the issue
    
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
            
            # Create issue header - WITH employee IDs and notes
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
            
            # Create return header - WITH employee IDs
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
            
            # Update manufacturing_order_materials issued quantities
            _update_order_materials_for_return(conn, return_details)
            
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
            
            # Create production receipt - REMOVED entity_id (doesn't exist in DB)
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
                    order.get('entity_id', 1),  # Get from order, fallback to 1
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
            
            logger.info(f"✅ Completed production receipt {receipt_no} for order {order_id}")
            
            return {
                'receipt_no': receipt_no,
                'receipt_id': receipt_id,
                'quantity': produced_qty,
                'batch_no': batch_no,
                'quality_status': quality_status
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

# ==================== INTERNAL HELPER FUNCTIONS ====================

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


def _issue_material_with_alternatives(conn, issue_id: int, order_id: int,
                                     material: pd.Series, required_qty: float,
                                     warehouse_id: int, group_id: str,
                                     user_id: int, keycloak_id: str,
                                     entity_id: int) -> Dict[str, Any]:
    """
    Issue material using FEFO, automatically substituting alternatives if needed
    
    Returns:
        Dictionary with issued details and substitution info
    """
    issued_details = []
    substitutions = []
    remaining = float(required_qty)
    
    # Try primary material first
    primary_issued = 0.0
    try:
        primary_details = _issue_single_material_fefo(
            conn, issue_id, order_id, material, remaining,
            warehouse_id, group_id, user_id, keycloak_id, entity_id,
            is_alternative=False, original_material_id=None
        )
        issued_details.extend(primary_details)
        
        # Calculate how much was issued from primary
        for detail in primary_details:
            primary_issued += float(detail['quantity'])
        
        remaining -= primary_issued
        
    except ValueError as e:
        # Insufficient stock for primary - log but continue with alternatives
        logger.warning(f"⚠️ Insufficient primary material {material['material_name']}: {e}")
    
    # If still need more, try alternatives
    if remaining > 0:
        # Get BOM detail ID for this material
        bom_detail_query = text("""
            SELECT bd.id as bom_detail_id
            FROM manufacturing_order_materials mom
            JOIN manufacturing_orders mo ON mom.manufacturing_order_id = mo.id
            JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
                AND bd.material_id = mom.material_id
            WHERE mom.id = :order_material_id
        """)
        
        result = conn.execute(bom_detail_query, {
            'order_material_id': material['order_material_id']
        })
        bom_detail_row = result.fetchone()
        
        if not bom_detail_row:
            if primary_issued == 0:
                raise ValueError(f"No materials available for {material['material_name']}")
            else:
                # Partial issue from primary only
                logger.warning(f"⚠️ Only partial issue possible for {material['material_name']}: {primary_issued}/{required_qty}")
                return {'details': issued_details, 'substitutions': []}
        
        bom_detail = dict(zip(result.keys(), bom_detail_row))
        
        # Get alternatives ordered by priority
        alternatives_query = text("""
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
        
        alternatives_result = conn.execute(alternatives_query, {
            'bom_detail_id': bom_detail['bom_detail_id']
        })
        
        # Convert alternatives to list of dicts
        alternatives_list = []
        for row in alternatives_result:
            alternatives_list.append(dict(zip(alternatives_result.keys(), row)))
        
        # Try each alternative in priority order
        for alt in alternatives_list:
            if remaining <= 0:
                break
                
            try:
                # Create temporary material data for alternative
                alt_material = pd.Series({
                    'order_material_id': material['order_material_id'],
                    'material_id': alt['alternative_material_id'],
                    'material_name': alt['alternative_material_name'],
                    'uom': alt['uom']
                })
                
                # Try issuing alternative with tracking
                alt_details = _issue_single_material_fefo(
                    conn, issue_id, order_id, alt_material, remaining,
                    warehouse_id, group_id, user_id, keycloak_id, entity_id,
                    is_alternative=True, 
                    original_material_id=material['material_id']
                )
                
                # Calculate how much was issued from this alternative
                alt_issued = sum(float(d['quantity']) for d in alt_details)
                
                if alt_issued > 0:
                    issued_details.extend(alt_details)
                    
                    # Record substitution
                    substitutions.append({
                        'original_material': material['material_name'],
                        'original_material_id': material['material_id'],
                        'substitute_material': alt['alternative_material_name'],
                        'substitute_material_id': alt['alternative_material_id'],
                        'quantity': alt_issued,
                        'uom': alt['uom'],
                        'priority': alt['priority']
                    })
                    
                    remaining -= alt_issued
                    logger.info(f"🔄 Substituted {alt_issued} {alt['uom']} of {alt['alternative_material_name']} for {material['material_name']}")
                
            except ValueError as e:
                logger.warning(f"⚠️ Alternative {alt['alternative_material_name']} also insufficient: {e}")
                continue
        
        # Check if we fulfilled the requirement
        if remaining > 0:
            total_issued = float(required_qty) - float(remaining)
            if total_issued == 0:
                raise ValueError(f"No materials available (primary or alternatives) for {material['material_name']}")
            else:
                logger.warning(f"⚠️ Only partial issue possible for {material['material_name']}: {total_issued}/{required_qty}")
    
    return {
        'details': issued_details,
        'substitutions': substitutions
    }


def _issue_single_material_fefo(conn, issue_id: int, order_id: int,
                               material: pd.Series, required_qty: float,
                               warehouse_id: int, group_id: str, 
                               user_id: int, keycloak_id: str, entity_id: int,
                               is_alternative: bool = False,
                               original_material_id: Optional[int] = None) -> List[Dict]:
    """
    Issue single material using FEFO with alternative tracking
    
    Args:
        issue_id: Material issue ID
        order_id: Manufacturing order ID
        material: Material series with material_id, name, etc.
        required_qty: Quantity required
        warehouse_id: Source warehouse
        group_id: Transaction group ID
        user_id: User ID for manufacturing tables (INT)
        keycloak_id: Keycloak ID for inventory tables (VARCHAR)
        entity_id: Company/Entity ID (for inventory tracking if columns exist)
        is_alternative: Whether this is an alternative material
        original_material_id: ID of original material if this is alternative
    
    Returns:
        List of issued details
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
    total_issued = 0.0
    
    for batch in batches:
        if total_issued >= required_qty:
            break
        
        # Calculate quantity to issue from this batch
        batch_available = float(batch['available_qty'])
        required_remaining = float(required_qty) - float(total_issued)
        issue_qty = min(batch_available, required_remaining)
        
        # Insert issue detail with alternative tracking
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
            'quantity': issue_qty,
            'uom': material['uom'],
            'expired_date': batch['expired_date'],
            'is_alternative': is_alternative,
            'original_material_id': original_material_id
        })
        
        total_issued += issue_qty
    
    if total_issued < required_qty:
        raise ValueError(f"Insufficient stock: required {required_qty}, available {total_issued}")
    
    # Update manufacturing_order_materials issued quantity
    update_query = text("""
        UPDATE manufacturing_order_materials
        SET issued_qty = COALESCE(issued_qty, 0) + :issued_qty,
            status = CASE 
                WHEN COALESCE(issued_qty, 0) + :issued_qty >= required_qty THEN 'ISSUED'
                WHEN COALESCE(issued_qty, 0) + :issued_qty > 0 THEN 'PARTIAL'
                ELSE 'PENDING'
            END
        WHERE id = :order_material_id
    """)
    
    conn.execute(update_query, {
        'issued_qty': total_issued,
        'order_material_id': material['order_material_id']
    })
    
    return issued_details


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
            'created_by': keycloak_id  # CRITICAL: Use keycloak_id, not user_id
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
            'created_by': keycloak_id  # CRITICAL: Use keycloak_id
        })


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
            'uom': return_item['uom'],
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
            'uom': return_item['uom'],
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
        'is_alternative': issue_detail['is_alternative']
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
            'created_by': keycloak_id  # CRITICAL: Use keycloak_id
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
            'created_by': keycloak_id  # CRITICAL: Use keycloak_id
        })


def _update_order_materials_for_return(conn, return_details: List[Dict]):
    """Update manufacturing order materials after return"""
    for detail in return_details:
        query = text("""
            UPDATE manufacturing_order_materials mom
            JOIN material_issue_details mid ON mid.manufacturing_order_material_id = mom.id
            SET mom.issued_qty = GREATEST(0, mom.issued_qty - :quantity),
                mom.status = CASE 
                    WHEN mom.issued_qty - :quantity <= 0 THEN 'PENDING'
                    WHEN mom.issued_qty - :quantity < mom.required_qty THEN 'PARTIAL'
                    ELSE 'ISSUED'
                END
            WHERE mid.material_id = :material_id
                AND mid.id IN (
                    SELECT original_issue_detail_id 
                    FROM material_return_details 
                    WHERE material_id = :material_id
                )
        """)
        
        conn.execute(query, {
            'material_id': detail['material_id'],
            'quantity': detail['quantity']
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
            'created_by': keycloak_id  # CRITICAL: Use keycloak_id
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
            'created_by': keycloak_id  # CRITICAL: Use keycloak_id
        })


def _generate_issue_number(conn) -> str:
    """Generate unique issue number"""
    prefix = f"ISS{datetime.now().strftime('%Y%m%d')}"
    
    query = text("""
        SELECT COUNT(*) + 1 as seq
        FROM material_issues
        WHERE issue_no LIKE :prefix
    """)
    
    result = conn.execute(query, {'prefix': f'{prefix}%'})
    seq = result.fetchone()[0]
    
    return f"{prefix}{str(seq).zfill(4)}"


def _generate_return_number(conn) -> str:
    """Generate unique return number"""
    prefix = f"RET{datetime.now().strftime('%Y%m%d')}"
    
    query = text("""
        SELECT COUNT(*) + 1 as seq
        FROM material_returns
        WHERE return_no LIKE :prefix
    """)
    
    result = conn.execute(query, {'prefix': f'{prefix}%'})
    seq = result.fetchone()[0]
    
    return f"{prefix}{str(seq).zfill(4)}"


def _generate_receipt_number(conn) -> str:
    """Generate unique receipt number"""
    prefix = f"RCP{datetime.now().strftime('%Y%m%d')}"
    
    query = text("""
        SELECT COUNT(*) + 1 as seq
        FROM production_receipts
        WHERE receipt_no LIKE :prefix
    """)
    
    result = conn.execute(query, {'prefix': f'{prefix}%'})
    seq = result.fetchone()[0]
    
    return f"{prefix}{str(seq).zfill(4)}"