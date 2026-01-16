# utils/bom_variance/actions.py
"""
BOM Variance - Actions Module - VERSION 2.0

Phase 4 Implementation - Contains:
- Clone BOM with adjusted values (creates DRAFT)
- Direct update BOM (if no usage history)
- Audit trail for applied changes
- Validation helpers
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from utils.db import get_db_engine
from .config import ApplyMode

logger = logging.getLogger(__name__)


# ==================== Result Classes ====================

@dataclass
class ApplyResult:
    """Result of applying recommendation"""
    success: bool
    message: str
    new_bom_id: Optional[int] = None
    new_bom_code: Optional[str] = None
    changes_applied: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def __repr__(self):
        return f"ApplyResult(success={self.success}, message='{self.message}', new_bom_id={self.new_bom_id})"


@dataclass
class ValidationResult:
    """Result of validation check"""
    is_valid: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


# ==================== Validation Functions ====================

def validate_bom_exists(bom_id: int) -> ValidationResult:
    """Check if BOM exists and is not deleted"""
    engine = get_db_engine()
    
    query = """
        SELECT id, bom_code, bom_name, status, version, delete_flag
        FROM bom_headers
        WHERE id = :bom_id
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), {'bom_id': bom_id}).fetchone()
            
            if not result:
                return ValidationResult(
                    is_valid=False,
                    message=f"BOM with ID {bom_id} not found"
                )
            
            if result[5] == 1:  # delete_flag
                return ValidationResult(
                    is_valid=False,
                    message=f"BOM {result[1]} has been deleted"
                )
            
            return ValidationResult(
                is_valid=True,
                message="BOM exists and is active",
                details={
                    'bom_id': result[0],
                    'bom_code': result[1],
                    'bom_name': result[2],
                    'status': result[3],
                    'version': result[4]
                }
            )
    except Exception as e:
        logger.error(f"Error validating BOM: {e}")
        return ValidationResult(
            is_valid=False,
            message=f"Database error: {str(e)}"
        )


def can_direct_update(bom_id: int) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Check if BOM can be directly updated (no usage history)
    
    Args:
        bom_id: BOM header ID to check
        
    Returns:
        Tuple of (can_update, reason, details)
    """
    engine = get_db_engine()
    
    # Check for completed MOs
    query = """
        SELECT 
            COUNT(*) as mo_count,
            MIN(order_date) as first_mo_date,
            MAX(completion_date) as last_completion
        FROM manufacturing_orders
        WHERE bom_header_id = :bom_id
          AND status = 'COMPLETED'
          AND delete_flag = 0
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), {'bom_id': bom_id}).fetchone()
            
            mo_count = result[0] if result else 0
            
            if mo_count > 0:
                return (
                    False,
                    f"BOM has {mo_count} completed MOs. Use Clone instead.",
                    {
                        'mo_count': mo_count,
                        'first_mo_date': str(result[1]) if result[1] else None,
                        'last_completion': str(result[2]) if result[2] else None
                    }
                )
            
            # Check for in-progress MOs
            query_pending = """
                SELECT COUNT(*) 
                FROM manufacturing_orders
                WHERE bom_header_id = :bom_id
                  AND status IN ('DRAFT', 'CONFIRMED', 'IN_PROGRESS')
                  AND delete_flag = 0
            """
            pending_result = conn.execute(text(query_pending), {'bom_id': bom_id}).fetchone()
            pending_count = pending_result[0] if pending_result else 0
            
            if pending_count > 0:
                return (
                    False,
                    f"BOM has {pending_count} pending/in-progress MOs. Complete or cancel them first.",
                    {'pending_mo_count': pending_count}
                )
            
            return (
                True,
                "BOM can be directly updated (no usage history)",
                {'mo_count': 0, 'pending_mo_count': 0}
            )
            
    except Exception as e:
        logger.error(f"Error checking BOM usage: {e}")
        return (False, f"Database error: {str(e)}", {})


def validate_material_in_bom(bom_id: int, material_id: int, is_alternative: int = 0) -> ValidationResult:
    """Check if material exists in BOM"""
    engine = get_db_engine()
    
    if is_alternative == 0:
        # Check in bom_details
        query = """
            SELECT bd.id, bd.quantity, bd.scrap_rate
            FROM bom_details bd
            WHERE bd.bom_header_id = :bom_id
              AND bd.material_id = :material_id
        """
    else:
        # Check in bom_material_alternatives
        query = """
            SELECT bma.id, bma.quantity, bma.scrap_rate
            FROM bom_material_alternatives bma
            JOIN bom_details bd ON bma.bom_detail_id = bd.id
            WHERE bd.bom_header_id = :bom_id
              AND bma.alternative_material_id = :material_id
        """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), {
                'bom_id': bom_id,
                'material_id': material_id
            }).fetchone()
            
            if not result:
                return ValidationResult(
                    is_valid=False,
                    message=f"Material {material_id} not found in BOM {bom_id}"
                )
            
            return ValidationResult(
                is_valid=True,
                message="Material found in BOM",
                details={
                    'detail_id': result[0],
                    'current_quantity': float(result[1]),
                    'current_scrap_rate': float(result[2])
                }
            )
    except Exception as e:
        logger.error(f"Error validating material in BOM: {e}")
        return ValidationResult(
            is_valid=False,
            message=f"Database error: {str(e)}"
        )


# ==================== Clone BOM Functions ====================

def generate_clone_bom_code(original_code: str) -> str:
    """Generate new BOM code for clone"""
    engine = get_db_engine()
    
    # Pattern: ORIGINAL-ADJ-001, ORIGINAL-ADJ-002, etc.
    base_code = f"{original_code}-ADJ"
    
    query = """
        SELECT bom_code FROM bom_headers
        WHERE bom_code LIKE :pattern
        ORDER BY bom_code DESC
        LIMIT 1
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), {'pattern': f"{base_code}%"}).fetchone()
            
            if result:
                # Extract number and increment
                existing_code = result[0]
                try:
                    num = int(existing_code.split('-')[-1])
                    return f"{base_code}-{num + 1:03d}"
                except (ValueError, IndexError):
                    return f"{base_code}-001"
            else:
                return f"{base_code}-001"
    except Exception as e:
        logger.error(f"Error generating BOM code: {e}")
        # Fallback with timestamp
        return f"{base_code}-{datetime.now().strftime('%H%M%S')}"


def clone_bom_with_adjustments(
    source_bom_id: int,
    adjustments: List[Dict[str, Any]],
    new_bom_code: Optional[str] = None,
    new_bom_name: Optional[str] = None,
    created_by: Optional[int] = None,
    notes: Optional[str] = None
) -> ApplyResult:
    """
    Clone BOM with adjusted material quantities/scrap rates
    
    Args:
        source_bom_id: Source BOM header ID
        adjustments: List of adjustments, each dict contains:
            - material_id: Material to adjust
            - is_alternative: 0 for primary, 1 for alternative
            - new_quantity: New BOM quantity (optional)
            - new_scrap_rate: New scrap rate % (optional)
        new_bom_code: Optional new BOM code (auto-generated if None)
        new_bom_name: Optional new BOM name
        created_by: User ID who created the clone
        notes: Optional notes about the clone
        
    Returns:
        ApplyResult with new BOM ID if successful
    """
    engine = get_db_engine()
    
    # Validate source BOM
    validation = validate_bom_exists(source_bom_id)
    if not validation.is_valid:
        return ApplyResult(
            success=False,
            message=validation.message,
            errors=[validation.message]
        )
    
    source_bom = validation.details
    
    # Generate new BOM code if not provided
    if not new_bom_code:
        new_bom_code = generate_clone_bom_code(source_bom['bom_code'])
    
    # Generate new BOM name if not provided
    if not new_bom_name:
        new_bom_name = f"{source_bom['bom_name']} (Adjusted)"
    
    # Prepare adjustment lookup
    adjustment_map = {}
    for adj in adjustments:
        key = (adj['material_id'], adj.get('is_alternative', 0))
        adjustment_map[key] = adj
    
    try:
        with engine.begin() as conn:
            # Step 1: Clone bom_headers
            clone_header_query = """
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id, output_qty, uom,
                    status, version, effective_date, expiry_date, notes,
                    created_by, created_date
                )
                SELECT 
                    :new_bom_code,
                    :new_bom_name,
                    bom_type,
                    product_id,
                    output_qty,
                    uom,
                    'DRAFT',
                    1,
                    NULL,
                    NULL,
                    :notes,
                    :created_by,
                    NOW()
                FROM bom_headers
                WHERE id = :source_bom_id
            """
            
            clone_notes = notes or f"Cloned from {source_bom['bom_code']} with variance adjustments on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            conn.execute(text(clone_header_query), {
                'new_bom_code': new_bom_code,
                'new_bom_name': new_bom_name,
                'notes': clone_notes,
                'created_by': created_by or 1,
                'source_bom_id': source_bom_id
            })
            
            # Get new BOM ID
            new_bom_id = conn.execute(text("SELECT LAST_INSERT_ID()")).fetchone()[0]
            
            # Step 2: Clone bom_details with adjustments
            get_details_query = """
                SELECT id, material_id, material_type, quantity, uom, scrap_rate, notes
                FROM bom_details
                WHERE bom_header_id = :source_bom_id
            """
            
            details = conn.execute(text(get_details_query), {'source_bom_id': source_bom_id}).fetchall()
            
            detail_id_map = {}  # old_detail_id -> new_detail_id
            changes_applied = []
            
            for detail in details:
                old_detail_id = detail[0]
                material_id = detail[1]
                material_type = detail[2]
                original_qty = float(detail[3])
                uom = detail[4]
                original_scrap = float(detail[5])
                detail_notes = detail[6]
                
                # Check if this material has adjustment
                adj_key = (material_id, 0)  # Primary material
                adjustment = adjustment_map.get(adj_key)
                
                if adjustment:
                    new_qty = adjustment.get('new_quantity', original_qty)
                    new_scrap = adjustment.get('new_scrap_rate', original_scrap)
                    
                    changes_applied.append({
                        'material_id': material_id,
                        'is_alternative': 0,
                        'change_type': 'PRIMARY',
                        'old_quantity': original_qty,
                        'new_quantity': new_qty,
                        'old_scrap_rate': original_scrap,
                        'new_scrap_rate': new_scrap
                    })
                else:
                    new_qty = original_qty
                    new_scrap = original_scrap
                
                # Insert new detail
                insert_detail_query = """
                    INSERT INTO bom_details (
                        bom_header_id, material_id, material_type, quantity, uom, scrap_rate, notes
                    ) VALUES (
                        :bom_header_id, :material_id, :material_type, :quantity, :uom, :scrap_rate, :notes
                    )
                """
                
                conn.execute(text(insert_detail_query), {
                    'bom_header_id': new_bom_id,
                    'material_id': material_id,
                    'material_type': material_type,
                    'quantity': new_qty,
                    'uom': uom,
                    'scrap_rate': new_scrap,
                    'notes': detail_notes
                })
                
                new_detail_id = conn.execute(text("SELECT LAST_INSERT_ID()")).fetchone()[0]
                detail_id_map[old_detail_id] = new_detail_id
            
            # Step 3: Clone bom_material_alternatives with adjustments
            get_alternatives_query = """
                SELECT 
                    bma.id, bma.bom_detail_id, bma.alternative_material_id,
                    bma.material_type, bma.quantity, bma.uom, bma.scrap_rate,
                    bma.priority, bma.is_active, bma.notes
                FROM bom_material_alternatives bma
                JOIN bom_details bd ON bma.bom_detail_id = bd.id
                WHERE bd.bom_header_id = :source_bom_id
            """
            
            alternatives = conn.execute(text(get_alternatives_query), {'source_bom_id': source_bom_id}).fetchall()
            
            for alt in alternatives:
                old_detail_id = alt[1]
                new_detail_id = detail_id_map.get(old_detail_id)
                
                if not new_detail_id:
                    continue
                
                alt_material_id = alt[2]
                material_type = alt[3]
                original_qty = float(alt[4])
                uom = alt[5]
                original_scrap = float(alt[6])
                priority = alt[7]
                is_active = alt[8]
                alt_notes = alt[9]
                
                # Check if this alternative has adjustment
                adj_key = (alt_material_id, 1)  # Alternative material
                adjustment = adjustment_map.get(adj_key)
                
                if adjustment:
                    new_qty = adjustment.get('new_quantity', original_qty)
                    new_scrap = adjustment.get('new_scrap_rate', original_scrap)
                    
                    changes_applied.append({
                        'material_id': alt_material_id,
                        'is_alternative': 1,
                        'change_type': 'ALTERNATIVE',
                        'old_quantity': original_qty,
                        'new_quantity': new_qty,
                        'old_scrap_rate': original_scrap,
                        'new_scrap_rate': new_scrap
                    })
                else:
                    new_qty = original_qty
                    new_scrap = original_scrap
                
                # Insert new alternative
                insert_alt_query = """
                    INSERT INTO bom_material_alternatives (
                        bom_detail_id, alternative_material_id, material_type,
                        quantity, uom, scrap_rate, priority, is_active, notes
                    ) VALUES (
                        :bom_detail_id, :alternative_material_id, :material_type,
                        :quantity, :uom, :scrap_rate, :priority, :is_active, :notes
                    )
                """
                
                conn.execute(text(insert_alt_query), {
                    'bom_detail_id': new_detail_id,
                    'alternative_material_id': alt_material_id,
                    'material_type': material_type,
                    'quantity': new_qty,
                    'uom': uom,
                    'scrap_rate': new_scrap,
                    'priority': priority,
                    'is_active': is_active,
                    'notes': alt_notes
                })
            
            # Step 4: Log audit trail
            log_variance_adjustment(
                conn=conn,
                source_bom_id=source_bom_id,
                target_bom_id=new_bom_id,
                action_type='CLONE',
                changes=changes_applied,
                performed_by=created_by,
                notes=clone_notes
            )
            
            logger.info(f"Successfully cloned BOM {source_bom['bom_code']} to {new_bom_code} with {len(changes_applied)} adjustments")
            
            return ApplyResult(
                success=True,
                message=f"Successfully created new BOM: {new_bom_code}",
                new_bom_id=new_bom_id,
                new_bom_code=new_bom_code,
                changes_applied=changes_applied
            )
            
    except SQLAlchemyError as e:
        logger.error(f"Database error cloning BOM: {e}")
        return ApplyResult(
            success=False,
            message=f"Database error: {str(e)}",
            errors=[str(e)]
        )
    except Exception as e:
        logger.error(f"Error cloning BOM: {e}")
        return ApplyResult(
            success=False,
            message=f"Error: {str(e)}",
            errors=[str(e)]
        )


# ==================== Direct Update Functions ====================

def direct_update_bom(
    bom_id: int,
    adjustments: List[Dict[str, Any]],
    updated_by: Optional[int] = None,
    notes: Optional[str] = None
) -> ApplyResult:
    """
    Directly update BOM with adjusted values (only if no usage)
    
    Args:
        bom_id: BOM header ID to update
        adjustments: List of adjustments (same format as clone)
        updated_by: User ID who made the update
        notes: Optional notes
        
    Returns:
        ApplyResult
    """
    engine = get_db_engine()
    
    # Validate BOM exists
    validation = validate_bom_exists(bom_id)
    if not validation.is_valid:
        return ApplyResult(
            success=False,
            message=validation.message,
            errors=[validation.message]
        )
    
    bom_info = validation.details
    
    # Check if direct update is allowed
    can_update, reason, details = can_direct_update(bom_id)
    if not can_update:
        return ApplyResult(
            success=False,
            message=reason,
            errors=[reason]
        )
    
    # Prepare adjustment lookup
    adjustment_map = {}
    for adj in adjustments:
        key = (adj['material_id'], adj.get('is_alternative', 0))
        adjustment_map[key] = adj
    
    try:
        with engine.begin() as conn:
            changes_applied = []
            
            # Update primary materials in bom_details
            for (material_id, is_alt), adj in adjustment_map.items():
                if is_alt == 0:
                    # Update bom_details
                    # First, get current values
                    get_current_query = """
                        SELECT id, quantity, scrap_rate
                        FROM bom_details
                        WHERE bom_header_id = :bom_id AND material_id = :material_id
                    """
                    current = conn.execute(text(get_current_query), {
                        'bom_id': bom_id,
                        'material_id': material_id
                    }).fetchone()
                    
                    if not current:
                        continue
                    
                    old_qty = float(current[1])
                    old_scrap = float(current[2])
                    new_qty = adj.get('new_quantity', old_qty)
                    new_scrap = adj.get('new_scrap_rate', old_scrap)
                    
                    # Update
                    update_query = """
                        UPDATE bom_details
                        SET quantity = :quantity, scrap_rate = :scrap_rate
                        WHERE bom_header_id = :bom_id AND material_id = :material_id
                    """
                    conn.execute(text(update_query), {
                        'bom_id': bom_id,
                        'material_id': material_id,
                        'quantity': new_qty,
                        'scrap_rate': new_scrap
                    })
                    
                    changes_applied.append({
                        'material_id': material_id,
                        'is_alternative': 0,
                        'change_type': 'PRIMARY',
                        'old_quantity': old_qty,
                        'new_quantity': new_qty,
                        'old_scrap_rate': old_scrap,
                        'new_scrap_rate': new_scrap
                    })
                    
                else:
                    # Update bom_material_alternatives
                    get_current_query = """
                        SELECT bma.id, bma.quantity, bma.scrap_rate
                        FROM bom_material_alternatives bma
                        JOIN bom_details bd ON bma.bom_detail_id = bd.id
                        WHERE bd.bom_header_id = :bom_id 
                          AND bma.alternative_material_id = :material_id
                    """
                    current = conn.execute(text(get_current_query), {
                        'bom_id': bom_id,
                        'material_id': material_id
                    }).fetchone()
                    
                    if not current:
                        continue
                    
                    alt_id = current[0]
                    old_qty = float(current[1])
                    old_scrap = float(current[2])
                    new_qty = adj.get('new_quantity', old_qty)
                    new_scrap = adj.get('new_scrap_rate', old_scrap)
                    
                    # Update
                    update_query = """
                        UPDATE bom_material_alternatives
                        SET quantity = :quantity, scrap_rate = :scrap_rate
                        WHERE id = :alt_id
                    """
                    conn.execute(text(update_query), {
                        'alt_id': alt_id,
                        'quantity': new_qty,
                        'scrap_rate': new_scrap
                    })
                    
                    changes_applied.append({
                        'material_id': material_id,
                        'is_alternative': 1,
                        'change_type': 'ALTERNATIVE',
                        'old_quantity': old_qty,
                        'new_quantity': new_qty,
                        'old_scrap_rate': old_scrap,
                        'new_scrap_rate': new_scrap
                    })
            
            # Update BOM header (version, updated_by, updated_date)
            update_header_query = """
                UPDATE bom_headers
                SET version = version + 1,
                    updated_by = :updated_by,
                    updated_date = NOW(),
                    notes = CONCAT(COALESCE(notes, ''), :notes_append)
                WHERE id = :bom_id
            """
            
            notes_append = f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Variance adjustment applied: {len(changes_applied)} materials updated."
            if notes:
                notes_append += f" Note: {notes}"
            
            conn.execute(text(update_header_query), {
                'bom_id': bom_id,
                'updated_by': updated_by or 1,
                'notes_append': notes_append
            })
            
            # Log audit trail
            log_variance_adjustment(
                conn=conn,
                source_bom_id=bom_id,
                target_bom_id=bom_id,
                action_type='DIRECT_UPDATE',
                changes=changes_applied,
                performed_by=updated_by,
                notes=notes
            )
            
            logger.info(f"Successfully updated BOM {bom_info['bom_code']} with {len(changes_applied)} adjustments")
            
            return ApplyResult(
                success=True,
                message=f"Successfully updated BOM: {bom_info['bom_code']} (v{bom_info.get('version', 1) + 1})",
                new_bom_id=bom_id,
                new_bom_code=bom_info['bom_code'],
                changes_applied=changes_applied
            )
            
    except SQLAlchemyError as e:
        logger.error(f"Database error updating BOM: {e}")
        return ApplyResult(
            success=False,
            message=f"Database error: {str(e)}",
            errors=[str(e)]
        )
    except Exception as e:
        logger.error(f"Error updating BOM: {e}")
        return ApplyResult(
            success=False,
            message=f"Error: {str(e)}",
            errors=[str(e)]
        )


# ==================== Apply Recommendations ====================

def apply_recommendation(
    bom_id: int,
    material_id: int,
    is_alternative: int,
    new_quantity: Optional[float] = None,
    new_scrap_rate: Optional[float] = None,
    mode: ApplyMode = ApplyMode.CLONE,
    applied_by: Optional[int] = None,
    notes: Optional[str] = None
) -> ApplyResult:
    """
    Apply a single recommendation
    
    Args:
        bom_id: BOM header ID
        material_id: Material ID to adjust
        is_alternative: 0 for primary, 1 for alternative
        new_quantity: New BOM quantity (optional)
        new_scrap_rate: New scrap rate % (optional)
        mode: ApplyMode.CLONE or ApplyMode.DIRECT_UPDATE
        applied_by: User applying the change
        notes: Optional notes
        
    Returns:
        ApplyResult
    """
    adjustment = {
        'material_id': material_id,
        'is_alternative': is_alternative
    }
    
    if new_quantity is not None:
        adjustment['new_quantity'] = new_quantity
    if new_scrap_rate is not None:
        adjustment['new_scrap_rate'] = new_scrap_rate
    
    if mode == ApplyMode.CLONE:
        return clone_bom_with_adjustments(
            source_bom_id=bom_id,
            adjustments=[adjustment],
            created_by=applied_by,
            notes=notes
        )
    else:
        return direct_update_bom(
            bom_id=bom_id,
            adjustments=[adjustment],
            updated_by=applied_by,
            notes=notes
        )


def apply_bulk_recommendations(
    bom_id: int,
    adjustments: List[Dict[str, Any]],
    mode: ApplyMode = ApplyMode.CLONE,
    applied_by: Optional[int] = None,
    notes: Optional[str] = None
) -> ApplyResult:
    """
    Apply multiple recommendations for a single BOM
    
    Args:
        bom_id: BOM header ID
        adjustments: List of adjustment dicts, each containing:
            - material_id: Material ID
            - is_alternative: 0 or 1
            - new_quantity: New quantity (optional)
            - new_scrap_rate: New scrap rate (optional)
        mode: ApplyMode.CLONE or ApplyMode.DIRECT_UPDATE
        applied_by: User applying the changes
        notes: Optional notes
        
    Returns:
        ApplyResult
    """
    if mode == ApplyMode.CLONE:
        return clone_bom_with_adjustments(
            source_bom_id=bom_id,
            adjustments=adjustments,
            created_by=applied_by,
            notes=notes
        )
    else:
        return direct_update_bom(
            bom_id=bom_id,
            adjustments=adjustments,
            updated_by=applied_by,
            notes=notes
        )


def apply_multi_bom_recommendations(
    recommendations_by_bom: Dict[int, List[Dict[str, Any]]],
    mode: ApplyMode = ApplyMode.CLONE,
    applied_by: Optional[int] = None
) -> Dict[int, ApplyResult]:
    """
    Apply recommendations across multiple BOMs
    
    Args:
        recommendations_by_bom: Dict mapping bom_id -> list of adjustments
        mode: ApplyMode
        applied_by: User applying
        
    Returns:
        Dict mapping bom_id -> ApplyResult
    """
    results = {}
    
    for bom_id, adjustments in recommendations_by_bom.items():
        result = apply_bulk_recommendations(
            bom_id=bom_id,
            adjustments=adjustments,
            mode=mode,
            applied_by=applied_by
        )
        results[bom_id] = result
    
    return results


# ==================== Audit Trail ====================

def log_variance_adjustment(
    conn,
    source_bom_id: int,
    target_bom_id: int,
    action_type: str,
    changes: List[Dict[str, Any]],
    performed_by: Optional[int] = None,
    notes: Optional[str] = None
) -> bool:
    """
    Log variance adjustment to audit trail
    
    Uses bom_headers notes field for now. Can be extended to a separate audit table.
    """
    try:
        # Create audit log entry
        audit_entry = {
            'timestamp': datetime.now().isoformat(),
            'action_type': action_type,
            'source_bom_id': source_bom_id,
            'target_bom_id': target_bom_id,
            'performed_by': performed_by,
            'changes_count': len(changes),
            'notes': notes
        }
        
        logger.info(f"Audit log: {audit_entry}")
        
        # For detailed tracking, you could create a separate table:
        # variance_adjustment_log (id, timestamp, source_bom_id, target_bom_id, 
        #                          action_type, material_id, old_qty, new_qty, 
        #                          old_scrap, new_scrap, performed_by)
        
        return True
        
    except Exception as e:
        logger.error(f"Error logging audit trail: {e}")
        return False


def get_adjustment_history(
    bom_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Get adjustment history from audit trail
    
    Note: Currently returns empty as audit table is not implemented.
    Extend this when variance_adjustment_log table is created.
    """
    # TODO: Implement when audit table is created
    logger.info(f"Getting adjustment history for BOM {bom_id}")
    return []


# ==================== UI Integration Helpers ====================

def prepare_adjustments_from_selection(
    selected_items: List[Dict[str, Any]],
    adjustment_method: str = "Adjust Quantity"
) -> Dict[int, List[Dict[str, Any]]]:
    """
    Prepare adjustments grouped by BOM from UI selection
    
    Args:
        selected_items: List from tab_recommendations selection
        adjustment_method: "Adjust Quantity" or "Adjust Scrap Rate"
        
    Returns:
        Dict mapping bom_id -> list of adjustments
    """
    adjustments_by_bom = {}
    
    for item in selected_items:
        bom_id = item['bom_header_id']
        
        if bom_id not in adjustments_by_bom:
            adjustments_by_bom[bom_id] = []
        
        adjustment = {
            'material_id': item['material_id'],
            'is_alternative': item.get('is_alternative', 0)
        }
        
        if adjustment_method == "Adjust Quantity":
            adjustment['new_quantity'] = item.get('suggested_qty')
        else:
            adjustment['new_scrap_rate'] = item.get('suggested_scrap')
        
        adjustments_by_bom[bom_id].append(adjustment)
    
    return adjustments_by_bom


def get_apply_summary(
    selected_items: List[Dict[str, Any]],
    mode: ApplyMode
) -> Dict[str, Any]:
    """
    Get summary of what will be applied
    
    Args:
        selected_items: Selected items from UI
        mode: Apply mode
        
    Returns:
        Summary dict for preview
    """
    # Group by BOM
    bom_groups = {}
    for item in selected_items:
        bom_code = item.get('bom_code', 'Unknown')
        if bom_code not in bom_groups:
            bom_groups[bom_code] = {
                'bom_id': item['bom_header_id'],
                'materials': [],
                'can_direct_update': None
            }
        bom_groups[bom_code]['materials'].append(item)
    
    # Check direct update eligibility
    for bom_code, group in bom_groups.items():
        can_update, reason, _ = can_direct_update(group['bom_id'])
        group['can_direct_update'] = can_update
        group['update_reason'] = reason
    
    return {
        'total_items': len(selected_items),
        'total_boms': len(bom_groups),
        'mode': mode.value,
        'bom_groups': bom_groups
    }
