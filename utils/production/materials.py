# utils/production/materials.py
"""
Material Issue, Return, and Production Completion Logic
FEFO-based material issuing with automatic alternative substitution
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
    with automatic alternative material substitution
    
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
            substitutions = []  # Track any substitutions made
            
            # Issue each material using FEFO with alternative substitution
            for _, mat in materials.iterrows():
                remaining = mat['required_qty'] - mat['issued_qty']
                if remaining > 0:
                    try:
                        # Try issuing primary material first
                        issued = _issue_material_with_alternatives(
                            conn, issue_id, order_id, mat,
                            remaining, order['warehouse_id'], group_id, user_id
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
                SET status = 'IN_PROGRESS', updated_date = NOW()
                WHERE id = :order_id
            """)
            conn.execute(status_query, {'order_id': order_id})
            
            logger.info(f"Issued materials for order {order_id}, issue no: {issue_no}")
            if substitutions:
                logger.info(f"Material substitutions made: {substitutions}")
            
            return {
                'issue_no': issue_no,
                'issue_id': issue_id,
                'details': issue_details,
                'substitutions': substitutions
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
            issue_row = issue_result.fetchone()
            if not issue_row:
                raise ValueError("No material issue found for this order")
            
            issue = dict(zip(issue_result.keys(), issue_row))  # Convert to dict
            
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
                    'quantity': ret['quantity']
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
    Complete production and create receipt
    
    Args:
        order_id: Production order ID
        produced_qty: Actual produced quantity
        batch_no: Batch number for produced goods
        quality_status: Quality check status (PASSED/FAILED/PENDING)
        notes: Production notes
        user_id: User completing the production
        expired_date: Optional expiry date for produced goods
        
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
                raise ValueError(f"Cannot complete order with status {order['status']}")
            
            # Generate receipt number
            receipt_no = _generate_receipt_number(conn)
            
            # Create production receipt
            receipt_query = text("""
                INSERT INTO production_receipts (
                    receipt_no, manufacturing_order_id, receipt_date,
                    product_id, quantity, uom, batch_no, expired_date,
                    warehouse_id, quality_status, notes, created_by, created_date
                ) VALUES (
                    :receipt_no, :order_id, NOW(),
                    :product_id, :quantity, :uom, :batch_no, :expired_date,
                    :warehouse_id, :quality_status, :notes, :created_by, NOW()
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
            
            # Create stock in record for produced goods
            stock_in_query = text("""
                INSERT INTO inventory_histories (
                    type, product_id, warehouse_id, quantity, remain,
                    batch_no, expired_date, action_detail_id,
                    created_by, created_date, delete_flag
                ) VALUES (
                    'stockInProduction', :product_id, :warehouse_id,
                    :quantity, :quantity, :batch_no, :expired_date,
                    :receipt_id, :created_by, NOW(), 0
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
            
            # Update order
            update_query = text("""
                UPDATE manufacturing_orders
                SET produced_qty = produced_qty + :quantity,
                    status = CASE 
                        WHEN produced_qty + :quantity >= planned_qty THEN 'COMPLETED'
                        ELSE 'IN_PROGRESS'
                    END,
                    completion_date = CASE 
                        WHEN produced_qty + :quantity >= planned_qty THEN CURDATE()
                        ELSE completion_date
                    END,
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :order_id
            """)
            
            conn.execute(update_query, {
                'quantity': produced_qty,
                'user_id': user_id,
                'order_id': order_id
            })
            
            logger.info(f"Completed production for order {order_id}, receipt no: {receipt_no}")
            
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
    """
    Get materials that can be returned for an order
    
    Args:
        order_id: Production order ID
        
    Returns:
        DataFrame with returnable materials and quantities
    """
    engine = get_db_engine()
    
    query = """
        SELECT 
            mid.id as issue_detail_id,
            mid.material_id,
            p.name as material_name,
            mid.batch_no,
            mid.quantity as issued_qty,
            mid.uom,
            mid.expired_date,
            COALESCE(SUM(mrd.quantity), 0) as returned_qty,
            (mid.quantity - COALESCE(SUM(mrd.quantity), 0)) as returnable_qty
        FROM material_issue_details mid
        JOIN material_issues mi ON mid.material_issue_id = mi.id
        JOIN products p ON mid.material_id = p.id
        LEFT JOIN material_return_details mrd 
            ON mrd.original_issue_detail_id = mid.id
        LEFT JOIN material_returns mr 
            ON mr.id = mrd.material_return_id AND mr.status = 'CONFIRMED'
        WHERE mi.manufacturing_order_id = %s
            AND mi.status = 'CONFIRMED'
        GROUP BY mid.id, mid.material_id, p.name, mid.batch_no, 
                 mid.quantity, mid.uom, mid.expired_date
        HAVING returnable_qty > 0
        ORDER BY p.name, mid.batch_no
    """
    
    try:
        return pd.read_sql(query, engine, params=(order_id,))
    except Exception as e:
        logger.error(f"Error getting returnable materials for order {order_id}: {e}")
        return pd.DataFrame()


# ==================== Internal Helper Functions ====================

def _get_order_info(conn, order_id: int) -> Optional[Dict]:
    """Get order information with lock"""
    query = text("""
        SELECT 
            id, order_no, status, warehouse_id, target_warehouse_id,
            product_id, planned_qty, uom, bom_header_id
        FROM manufacturing_orders
        WHERE id = :order_id AND delete_flag = 0
        FOR UPDATE
    """)
    
    result = conn.execute(query, {'order_id': order_id})
    row = result.fetchone()
    
    return dict(zip(result.keys(), row)) if row else None


def _get_pending_materials(conn, order_id: int) -> pd.DataFrame:
    """Get materials that still need to be issued"""
    query = text("""
        SELECT 
            m.id as order_material_id,
            m.material_id,
            p.name as material_name,
            m.required_qty,
            COALESCE(m.issued_qty, 0) as issued_qty,
            m.uom
        FROM manufacturing_order_materials m
        JOIN products p ON m.material_id = p.id
        WHERE m.manufacturing_order_id = :order_id
            AND m.required_qty > COALESCE(m.issued_qty, 0)
        ORDER BY p.name
    """)
    
    result = conn.execute(query, {'order_id': order_id})
    rows = result.fetchall()
    
    return pd.DataFrame([dict(row._mapping) for row in rows])


def _issue_material_with_alternatives(conn, issue_id: int, order_id: int,
                                     material: pd.Series, required_qty: float,
                                     warehouse_id: int, group_id: str,
                                     user_id: int) -> Dict[str, Any]:
    """
    Issue material using FEFO, automatically substituting alternatives if needed
    
    Returns:
        Dictionary with issued details and substitution info
    """
    issued_details = []
    substitutions = []
    remaining = required_qty
    
    # Try primary material first
    try:
        primary_issued = _issue_single_material_fefo(
            conn, issue_id, order_id, material, remaining,
            warehouse_id, group_id, user_id
        )
        issued_details.extend(primary_issued)
        remaining = 0
        
    except ValueError as e:
        # Insufficient stock for primary - try alternatives
        logger.warning(f"Insufficient stock for primary material {material['material_name']}: {e}")
        
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
            raise ValueError(f"No BOM detail found for material {material['material_name']}")
        
        bom_detail = dict(zip(result.keys(), bom_detail_row))  # Convert to dict
        
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
        
        alternatives_tried = []
        for alt in alternatives_list:
            try:
                # Create temporary material data for alternative
                alt_material = pd.Series({
                    'order_material_id': material['order_material_id'],
                    'material_id': alt['alternative_material_id'],
                    'material_name': alt['alternative_material_name'],
                    'uom': alt['uom']
                })
                
                # Try issuing alternative
                alt_issued = _issue_single_material_fefo(
                    conn, issue_id, order_id, alt_material, remaining,
                    warehouse_id, group_id, user_id
                )
                
                issued_details.extend(alt_issued)
                
                # Record substitution
                substitutions.append({
                    'original_material': material['material_name'],
                    'substitute_material': alt['alternative_material_name'],
                    'quantity': remaining,
                    'priority': alt['priority']
                })
                
                logger.info(
                    f"Substituted {material['material_name']} with "
                    f"{alt['alternative_material_name']} (priority {alt['priority']})"
                )
                
                remaining = 0
                break
                
            except ValueError as alt_error:
                alternatives_tried.append({
                    'material': alt['alternative_material_name'],
                    'error': str(alt_error)
                })
                logger.warning(
                    f"Alternative {alt['alternative_material_name']} also insufficient: {alt_error}"
                )
                continue
        
        # If still not fulfilled after trying all alternatives
        if remaining > 0:
            error_msg = (
                f"Insufficient stock for material '{material['material_name']}' "
                f"and all alternatives. Required: {required_qty} {material['uom']}, "
                f"Short by: {remaining} {material['uom']}."
            )
            if alternatives_tried:
                error_msg += f" Alternatives tried: {alternatives_tried}"
            raise ValueError(error_msg)
    
    return {
        'details': issued_details,
        'substitutions': substitutions
    }


def _issue_single_material_fefo(conn, issue_id: int, order_id: int,
                                material: pd.Series, required_qty: float,
                                warehouse_id: int, group_id: str,
                                user_id: int) -> List[Dict]:
    """
    Issue a single material using FEFO logic
    Raises ValueError if insufficient stock
    """
    # Get available batches using FEFO
    batch_query = text("""
        SELECT 
            id, batch_no, remain, expired_date, created_date
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
    
    batches_result = conn.execute(batch_query, {
        'material_id': material['material_id'],
        'warehouse_id': warehouse_id
    })
    
    # Convert batches to list of dicts
    batches_list = []
    for row in batches_result:
        batches_list.append(dict(zip(batches_result.keys(), row)))
    
    issued_details = []
    remaining = required_qty
    
    for batch in batches_list:
        if remaining <= 0:
            break
        
        # Skip expired batches
        expired_date = batch['expired_date']
        if expired_date:
            # Convert datetime to date if necessary
            if isinstance(expired_date, datetime):
                expired_date = expired_date.date()
            if expired_date < date.today():
                logger.warning(f"Skipping expired batch {batch['batch_no']}")
                continue
        
        take_qty = min(remaining, float(batch['remain']))
        
        # Create issue detail
        detail_query = text("""
            INSERT INTO material_issue_details (
                material_issue_id, manufacturing_order_material_id,
                material_id, quantity, uom, batch_no, 
                inventory_history_id, expired_date, created_date
            ) VALUES (
                :issue_id, :order_material_id,
                :material_id, :quantity, :uom, :batch_no,
                :inventory_id, :expired_date, NOW()
            )
        """)
        
        detail_result = conn.execute(detail_query, {
            'issue_id': issue_id,
            'order_material_id': material['order_material_id'],
            'material_id': material['material_id'],
            'quantity': take_qty,
            'uom': material['uom'],
            'batch_no': batch['batch_no'],
            'inventory_id': batch['id'],
            'expired_date': batch['expired_date']
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
                END
            WHERE id = :order_material_id
        """)
        
        conn.execute(update_material_query, {
            'quantity': take_qty,
            'order_material_id': material['order_material_id']
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
    
    # Raise error if insufficient stock
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
    row_data = result.fetchone()
    
    if not row_data:
        raise ValueError(f"Issue detail {issue_detail_id} not found")
    
    row = dict(zip(result.keys(), row_data))  # Convert to dict
    
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
    row = result.fetchone()
    next_num = row[0] if row else 1  # Use index instead of key
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
    row = result.fetchone()
    next_num = row[0] if row else 1  # Use index instead of key
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
    row = result.fetchone()
    next_num = row[0] if row else 1  # Use index instead of key
    next_num = int(next_num) if next_num is not None else 1
    
    return f"PR-{timestamp}-{next_num:04d}"