# utils/bom/manager.py
"""
Bill of Materials (BOM) Management - Complete CRUD
"""

import logging
from datetime import date
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== Custom Exceptions ====================

class BOMException(Exception):
    """Base exception for BOM operations"""
    pass


class BOMValidationError(BOMException):
    """Validation error"""
    pass


class BOMNotFoundError(BOMException):
    """BOM not found"""
    pass


# ==================== BOM Manager ====================

class BOMManager:
    """Complete BOM Management with CRUD operations"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== READ Operations ====================
    
    def get_boms(self, bom_type: Optional[str] = None,
                 status: Optional[str] = None,
                 search: Optional[str] = None) -> pd.DataFrame:
        """Get BOMs with filters"""
        query = """
            SELECT 
                h.id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.product_id,
                p.name as product_name,
                h.output_qty,
                h.uom,
                h.status,
                h.version,
                h.effective_date,
                h.notes,
                COUNT(DISTINCT d.id) as material_count,
                COALESCE(
                    (SELECT COUNT(*) FROM manufacturing_orders mo 
                     WHERE mo.bom_header_id = h.id 
                     AND mo.delete_flag = 0), 
                    0
                ) as usage_count,
                h.created_date
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            LEFT JOIN bom_details d ON d.bom_header_id = h.id
            WHERE h.delete_flag = 0
        """
        
        params = {}
        
        if bom_type:
            query += " AND h.bom_type = :bom_type"
            params['bom_type'] = bom_type
        
        if status:
            query += " AND h.status = :status"
            params['status'] = status
        
        if search:
            query += """ AND (
                h.bom_code LIKE :search 
                OR h.bom_name LIKE :search 
                OR p.name LIKE :search
            )"""
            params['search'] = f"%{search}%"
        
        query += """ 
            GROUP BY h.id, h.bom_code, h.bom_name, h.bom_type, h.product_id,
                     p.name, h.output_qty, h.uom, h.status, h.version,
                     h.effective_date, h.notes, h.created_date
            ORDER BY h.created_date DESC
        """
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                return df
        except Exception as e:
            logger.error(f"Error getting BOMs: {e}")
            raise BOMException(f"Failed to retrieve BOMs: {str(e)}")
    
    def get_bom_info(self, bom_id: int) -> Optional[Dict]:
        """Get BOM header information"""
        query = text("""
            SELECT 
                h.*,
                p.name as product_name,
                p.pt_code as product_code,
                COALESCE(
                    (SELECT COUNT(*) FROM manufacturing_orders mo 
                     WHERE mo.bom_header_id = h.id 
                     AND mo.delete_flag = 0), 
                    0
                ) as total_usage,
                COALESCE(
                    (SELECT COUNT(*) FROM manufacturing_orders mo 
                     WHERE mo.bom_header_id = h.id 
                     AND mo.status IN ('CONFIRMED', 'IN_PROGRESS')
                     AND mo.delete_flag = 0), 
                    0
                ) as active_orders
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            WHERE h.id = :bom_id AND h.delete_flag = 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'bom_id': bom_id})
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.error(f"Error getting BOM info: {e}")
            raise BOMException(f"Failed to get BOM info: {str(e)}")
    
    def get_bom_details(self, bom_id: int) -> pd.DataFrame:
        """Get BOM materials"""
        query = text("""
            SELECT 
                d.id,
                d.bom_header_id,
                d.material_id,
                d.material_type,
                d.quantity,
                d.uom,
                d.scrap_rate,
                d.notes,
                p.name as material_name,
                p.pt_code as material_code,
                p.uom as material_uom,
                COALESCE(
                    (SELECT SUM(ih.remain) 
                     FROM inventory_histories ih 
                     WHERE ih.product_id = d.material_id 
                     AND ih.remain > 0 
                     AND ih.delete_flag = 0), 
                    0
                ) as current_stock
            FROM bom_details d
            JOIN products p ON d.material_id = p.id
            WHERE d.bom_header_id = :bom_id
            ORDER BY d.material_type, p.name
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'bom_id': bom_id})
                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                return df
        except Exception as e:
            logger.error(f"Error getting BOM details: {e}")
            raise BOMException(f"Failed to get BOM materials: {str(e)}")
    
    def get_where_used(self, product_id: int) -> pd.DataFrame:
        """Get BOMs where product is used as material"""
        query = text("""
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.status as bom_status,
                h.bom_type,
                p.name as output_product_name,
                d.material_type,
                d.quantity,
                d.uom,
                d.scrap_rate
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON h.product_id = p.id
            WHERE d.material_id = :product_id 
                AND h.delete_flag = 0
            ORDER BY h.status DESC, h.bom_name
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'product_id': product_id})
                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                return df
        except Exception as e:
            logger.error(f"Error getting where used: {e}")
            raise BOMException(f"Failed to get where used: {str(e)}")
    
    # ==================== CREATE Operations ====================
    
    def create_bom(self, bom_data: Dict) -> str:
        """
        Create new BOM with materials
        
        Args:
            bom_data: {
                'bom_name': str,
                'bom_type': str,
                'product_id': int,
                'output_qty': float,
                'uom': str,
                'effective_date': date,
                'notes': str,
                'materials': List[Dict],
                'created_by': int
            }
        
        Returns:
            BOM code
        """
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Validate input
            self._validate_bom_data(bom_data)
            
            # Generate BOM code
            bom_code = self._generate_bom_code(conn, bom_data['bom_type'])
            
            # Insert header
            header_query = text("""
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id,
                    output_qty, uom, status, version,
                    effective_date, notes, created_by, created_date
                ) VALUES (
                    :bom_code, :bom_name, :bom_type, :product_id,
                    :output_qty, :uom, 'DRAFT', 1,
                    :effective_date, :notes, :created_by, NOW()
                )
            """)
            
            result = conn.execute(header_query, {
                'bom_code': bom_code,
                'bom_name': bom_data['bom_name'],
                'bom_type': bom_data['bom_type'],
                'product_id': bom_data['product_id'],
                'output_qty': bom_data.get('output_qty', 1),
                'uom': bom_data.get('uom', 'PCS'),
                'effective_date': bom_data.get('effective_date', date.today()),
                'notes': bom_data.get('notes', ''),
                'created_by': bom_data.get('created_by', 1)
            })
            
            bom_id = result.lastrowid
            
            # Insert materials if provided
            if 'materials' in bom_data and bom_data['materials']:
                for material in bom_data['materials']:
                    self._add_material_internal(conn, bom_id, material)
            
            trans.commit()
            logger.info(f"Created BOM {bom_code} (ID: {bom_id})")
            return bom_code
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating BOM: {e}")
            raise BOMException(f"Failed to create BOM: {str(e)}")
        finally:
            conn.close()
    
    def add_materials(self, bom_id: int, materials: List[Dict]) -> bool:
        """
        Add materials to existing BOM
        
        Args:
            bom_id: BOM ID
            materials: List of material dicts
        """
        with self.engine.begin() as conn:
            try:
                # Check BOM exists and is editable
                self._check_bom_editable(conn, bom_id)
                
                # Get existing materials
                existing = self.get_bom_details(bom_id)
                
                for material in materials:
                    # Check duplicate
                    if not existing.empty and material['material_id'] in existing['material_id'].values:
                        raise BOMValidationError(
                            f"Material ID {material['material_id']} already exists in BOM"
                        )
                    
                    self._add_material_internal(conn, bom_id, material)
                
                logger.info(f"Added {len(materials)} materials to BOM {bom_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error adding materials: {e}")
                raise
    
    # ==================== UPDATE Operations ====================
    
    def update_bom_header(self, bom_id: int, updates: Dict) -> bool:
        """
        Update BOM header information
        
        Args:
            bom_id: BOM ID
            updates: {
                'bom_name': str (optional),
                'output_qty': float (optional),
                'effective_date': date (optional),
                'notes': str (optional),
                'updated_by': int
            }
        """
        with self.engine.begin() as conn:
            try:
                # Check BOM exists and is editable
                self._check_bom_editable(conn, bom_id)
                
                # Build update query dynamically
                update_fields = []
                params = {'bom_id': bom_id}
                
                if 'bom_name' in updates:
                    update_fields.append("bom_name = :bom_name")
                    params['bom_name'] = updates['bom_name']
                
                if 'output_qty' in updates:
                    update_fields.append("output_qty = :output_qty")
                    params['output_qty'] = updates['output_qty']
                
                if 'effective_date' in updates:
                    update_fields.append("effective_date = :effective_date")
                    params['effective_date'] = updates['effective_date']
                
                if 'notes' in updates:
                    update_fields.append("notes = :notes")
                    params['notes'] = updates['notes']
                
                if not update_fields:
                    return True  # Nothing to update
                
                # Always update updated_by and updated_date
                update_fields.append("updated_by = :updated_by")
                update_fields.append("updated_date = NOW()")
                params['updated_by'] = updates.get('updated_by', 1)
                
                query = text(f"""
                    UPDATE bom_headers
                    SET {', '.join(update_fields)}
                    WHERE id = :bom_id AND delete_flag = 0
                """)
                
                result = conn.execute(query, params)
                
                if result.rowcount == 0:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                logger.info(f"Updated BOM header {bom_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error updating BOM header: {e}")
                raise
    
    def update_material(self, bom_id: int, material_id: int, updates: Dict) -> bool:
        """
        Update material in BOM
        
        Args:
            bom_id: BOM ID
            material_id: Material/Product ID
            updates: {
                'quantity': float (optional),
                'scrap_rate': float (optional),
                'notes': str (optional)
            }
        """
        with self.engine.begin() as conn:
            try:
                # Check BOM exists and is editable
                self._check_bom_editable(conn, bom_id)
                
                # Build update query
                update_fields = []
                params = {
                    'bom_id': bom_id,
                    'material_id': material_id
                }
                
                if 'quantity' in updates:
                    if updates['quantity'] <= 0:
                        raise BOMValidationError("Quantity must be greater than 0")
                    update_fields.append("quantity = :quantity")
                    params['quantity'] = updates['quantity']
                
                if 'scrap_rate' in updates:
                    if updates['scrap_rate'] < 0 or updates['scrap_rate'] > 100:
                        raise BOMValidationError("Scrap rate must be between 0 and 100")
                    update_fields.append("scrap_rate = :scrap_rate")
                    params['scrap_rate'] = updates['scrap_rate']
                
                if 'notes' in updates:
                    update_fields.append("notes = :notes")
                    params['notes'] = updates['notes']
                
                if not update_fields:
                    return True
                
                query = text(f"""
                    UPDATE bom_details
                    SET {', '.join(update_fields)}
                    WHERE bom_header_id = :bom_id 
                        AND material_id = :material_id
                """)
                
                result = conn.execute(query, params)
                
                if result.rowcount == 0:
                    raise BOMValidationError(
                        f"Material {material_id} not found in BOM {bom_id}"
                    )
                
                logger.info(f"Updated material {material_id} in BOM {bom_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error updating material: {e}")
                raise
    
    def update_bom_status(self, bom_id: int, new_status: str, 
                         updated_by: Optional[int] = None) -> bool:
        """
        Update BOM status with validation
        
        Args:
            bom_id: BOM ID
            new_status: New status (DRAFT, ACTIVE, INACTIVE)
            updated_by: User ID
        """
        with self.engine.begin() as conn:
            try:
                # Get current status
                bom_info = self.get_bom_info(bom_id)
                if not bom_info:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                current_status = bom_info['status']
                
                # Validate status transition
                if not self._is_valid_status_transition(current_status, new_status):
                    raise BOMValidationError(
                        f"Invalid status transition: {current_status} → {new_status}"
                    )
                
                # Additional validation for ACTIVE status
                if new_status == 'ACTIVE':
                    # Check has materials
                    check_query = text("""
                        SELECT COUNT(*) as count 
                        FROM bom_details 
                        WHERE bom_header_id = :bom_id
                    """)
                    
                    result = conn.execute(check_query, {'bom_id': bom_id})
                    if result.scalar() == 0:
                        raise BOMValidationError(
                            "Cannot activate BOM without materials"
                        )
                
                # Additional validation for INACTIVE status
                if new_status == 'INACTIVE':
                    if bom_info['active_orders'] > 0:
                        raise BOMValidationError(
                            f"Cannot deactivate BOM with {bom_info['active_orders']} active orders"
                        )
                
                # Update status
                query = text("""
                    UPDATE bom_headers
                    SET status = :status,
                        updated_by = :updated_by,
                        updated_date = NOW()
                    WHERE id = :bom_id AND delete_flag = 0
                """)
                
                result = conn.execute(query, {
                    'status': new_status,
                    'updated_by': updated_by,
                    'bom_id': bom_id
                })
                
                if result.rowcount == 0:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                logger.info(f"Updated BOM {bom_id} status: {current_status} → {new_status}")
                return True
                
            except Exception as e:
                logger.error(f"Error updating BOM status: {e}")
                raise
    
    # ==================== DELETE Operations ====================
    
    def remove_material(self, bom_id: int, material_id: int) -> bool:
        """Remove material from BOM"""
        with self.engine.begin() as conn:
            try:
                # Check BOM is editable
                self._check_bom_editable(conn, bom_id)
                
                # Delete material
                query = text("""
                    DELETE FROM bom_details
                    WHERE bom_header_id = :bom_id 
                        AND material_id = :material_id
                """)
                
                result = conn.execute(query, {
                    'bom_id': bom_id,
                    'material_id': material_id
                })
                
                if result.rowcount == 0:
                    raise BOMValidationError(
                        f"Material {material_id} not found in BOM {bom_id}"
                    )
                
                logger.info(f"Removed material {material_id} from BOM {bom_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error removing material: {e}")
                raise
    
    def delete_bom(self, bom_id: int, deleted_by: Optional[int] = None) -> bool:
        """
        Soft delete BOM
        
        Args:
            bom_id: BOM ID
            deleted_by: User ID
        """
        with self.engine.begin() as conn:
            try:
                # Check BOM exists
                bom_info = self.get_bom_info(bom_id)
                if not bom_info:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                # Check if BOM is in use
                if bom_info['total_usage'] > 0:
                    raise BOMValidationError(
                        f"Cannot delete BOM - used in {bom_info['total_usage']} manufacturing orders"
                    )
                
                # Soft delete
                query = text("""
                    UPDATE bom_headers
                    SET delete_flag = 1,
                        updated_by = :deleted_by,
                        updated_date = NOW()
                    WHERE id = :bom_id
                """)
                
                result = conn.execute(query, {
                    'bom_id': bom_id,
                    'deleted_by': deleted_by
                })
                
                if result.rowcount == 0:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                logger.info(f"Deleted BOM {bom_id} ({bom_info['bom_code']})")
                return True
                
            except Exception as e:
                logger.error(f"Error deleting BOM: {e}")
                raise
    
    # ==================== Validation ====================
    
    def validate_bom(self, bom_id: int) -> Dict:
        """
        Comprehensive BOM validation
        
        Returns:
            {
                'valid': bool,
                'errors': List[str],
                'warnings': List[str]
            }
        """
        try:
            bom_info = self.get_bom_info(bom_id)
            bom_details = self.get_bom_details(bom_id)
            
            validation = {
                'valid': True,
                'errors': [],
                'warnings': []
            }
            
            # Check BOM exists
            if not bom_info:
                validation['valid'] = False
                validation['errors'].append("BOM not found")
                return validation
            
            # Check has materials
            if bom_details.empty:
                validation['valid'] = False
                validation['errors'].append("BOM has no materials")
                return validation
            
            # Check for duplicates
            duplicates = bom_details[bom_details.duplicated(['material_id'], keep=False)]
            if not duplicates.empty:
                validation['warnings'].append(
                    f"BOM contains {len(duplicates)} duplicate materials"
                )
            
            # Check stock availability
            no_stock = bom_details[bom_details['current_stock'] <= 0]
            if not no_stock.empty:
                validation['warnings'].append(
                    f"{len(no_stock)} material(s) have no stock available"
                )
            
            # Check high scrap rates
            high_scrap = bom_details[bom_details['scrap_rate'] > 20]
            if not high_scrap.empty:
                validation['warnings'].append(
                    f"{len(high_scrap)} material(s) have scrap rate > 20%"
                )
            
            # Check circular reference (basic check)
            if self._has_circular_reference(bom_id):
                validation['valid'] = False
                validation['errors'].append("Circular BOM reference detected")
            
            return validation
            
        except Exception as e:
            logger.error(f"Error validating BOM: {e}")
            return {
                'valid': False,
                'errors': [str(e)],
                'warnings': []
            }
    
    # ==================== Internal Helper Methods ====================
    
    def _validate_bom_data(self, bom_data: Dict):
        """Validate BOM creation data"""
        required_fields = ['bom_name', 'bom_type', 'product_id']
        
        for field in required_fields:
            if field not in bom_data or not bom_data[field]:
                raise BOMValidationError(f"Missing required field: {field}")
        
        if bom_data['bom_type'] not in ['KITTING', 'CUTTING', 'REPACKING']:
            raise BOMValidationError(f"Invalid BOM type: {bom_data['bom_type']}")
        
        if 'output_qty' in bom_data and bom_data['output_qty'] <= 0:
            raise BOMValidationError("Output quantity must be greater than 0")
    
    def _check_bom_editable(self, conn, bom_id: int):
        """Check if BOM can be edited"""
        query = text("""
            SELECT status 
            FROM bom_headers 
            WHERE id = :bom_id AND delete_flag = 0
        """)
        
        result = conn.execute(query, {'bom_id': bom_id})
        row = result.fetchone()
        
        if not row:
            raise BOMNotFoundError(f"BOM {bom_id} not found")
        
        if row[0] != 'DRAFT':
            raise BOMValidationError(
                f"Cannot edit BOM with status {row[0]}. Only DRAFT BOMs can be edited."
            )
    
    def _is_valid_status_transition(self, current: str, new: str) -> bool:
        """Check if status transition is valid"""
        # Define allowed transitions
        allowed_transitions = {
            'DRAFT': ['ACTIVE', 'INACTIVE'],
            'ACTIVE': ['INACTIVE'],
            'INACTIVE': ['ACTIVE']
        }
        
        if current == new:
            return False  # No need to transition to same status
        
        return new in allowed_transitions.get(current, [])
    
    def _generate_bom_code(self, conn, bom_type: str) -> str:
        """Generate unique BOM code with locking"""
        prefix = bom_type[:3].upper() if bom_type else "BOM"
        
        # Use FOR UPDATE to prevent race condition
        query = text("""
            SELECT COALESCE(MAX(CAST(
                SUBSTRING(bom_code, LENGTH(:prefix) + 2) AS UNSIGNED)
            ), 0) + 1 as next_seq
            FROM bom_headers
            WHERE bom_code LIKE CONCAT(:prefix, '-%')
            FOR UPDATE
        """)
        
        result = conn.execute(query, {'prefix': prefix})
        next_seq = result.scalar()
        
        if next_seq is None:
            next_seq = 1
        else:
            next_seq = int(next_seq)
        
        return f"{prefix}-{next_seq:04d}"
    
    def _add_material_internal(self, conn, bom_id: int, material: Dict):
        """Internal method to add material (called within transaction)"""
        # Validate material data
        if material.get('quantity', 0) <= 0:
            raise BOMValidationError("Material quantity must be greater than 0")
        
        if material.get('scrap_rate', 0) < 0 or material.get('scrap_rate', 0) > 100:
            raise BOMValidationError("Scrap rate must be between 0 and 100")
        
        query = text("""
            INSERT INTO bom_details (
                bom_header_id, material_id, material_type,
                quantity, uom, scrap_rate, notes
            ) VALUES (
                :bom_id, :material_id, :material_type,
                :quantity, :uom, :scrap_rate, :notes
            )
        """)
        
        conn.execute(query, {
            'bom_id': bom_id,
            'material_id': material['material_id'],
            'material_type': material.get('material_type', 'RAW_MATERIAL'),
            'quantity': material.get('quantity', 1),
            'uom': material.get('uom', 'PCS'),
            'scrap_rate': material.get('scrap_rate', 0),
            'notes': material.get('notes', '')
        })
    
    def _has_circular_reference(self, bom_id: int, visited: Optional[set] = None) -> bool:
        """Check for circular BOM references"""
        if visited is None:
            visited = set()
        
        if bom_id in visited:
            return True
        
        visited.add(bom_id)
        
        try:
            # Get BOM output product
            bom_info = self.get_bom_info(bom_id)
            if not bom_info:
                return False
            
            output_product_id = bom_info['product_id']
            
            # Check if output product is used as material in other BOMs
            where_used = self.get_where_used(output_product_id)
            
            for _, used_bom in where_used.iterrows():
                if self._has_circular_reference(used_bom['bom_id'], visited.copy()):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking circular reference: {e}")
            return False