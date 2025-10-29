# utils/bom/manager.py
"""
Bill of Materials (BOM) Management - Complete CRUD with Alternatives Support
Enhanced with full product information
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
    """Complete BOM Management with CRUD operations and Alternatives"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== READ Operations ====================
    
    def get_boms(self, bom_type: Optional[str] = None,
                 status: Optional[str] = None,
                 search: Optional[str] = None) -> pd.DataFrame:
        """Get BOMs with filters and full product info"""
        query = """
            SELECT 
                h.id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.product_id,
                p.name as product_name,
                p.pt_code as product_code,
                p.package_size,
                b.brand_name as brand,
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
            LEFT JOIN brands b ON p.brand_id = b.id
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
                     p.name, p.pt_code, p.package_size, b.brand_name,
                     h.output_qty, h.uom, h.status, h.version,
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
        """Get BOM header information with full product info"""
        query = text("""
            SELECT 
                h.*,
                p.name as product_name,
                p.pt_code as product_code,
                p.package_size,
                b.brand_name as brand,
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
                ) as active_orders,
                COALESCE(
                    (SELECT COUNT(*) FROM bom_details d
                     WHERE d.bom_header_id = h.id),
                    0
                ) as material_count
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
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
        """Get BOM materials with alternatives count"""
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
                ) as current_stock,
                COALESCE(
                    (SELECT COUNT(*) FROM bom_material_alternatives alt
                     WHERE alt.bom_detail_id = d.id
                     AND alt.is_active = 1),
                    0
                ) as alternatives_count
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
    
    def get_material_alternatives(self, bom_detail_id: int) -> pd.DataFrame:
        """Get alternatives for a specific BOM material"""
        query = text("""
            SELECT 
                alt.id,
                alt.bom_detail_id,
                alt.alternative_material_id,
                alt.material_type,
                alt.quantity,
                alt.uom,
                alt.scrap_rate,
                alt.priority,
                alt.is_active,
                alt.notes,
                p.name as material_name,
                p.pt_code as material_code,
                p.uom as material_uom,
                COALESCE(
                    (SELECT SUM(ih.remain) 
                     FROM inventory_histories ih 
                     WHERE ih.product_id = alt.alternative_material_id 
                     AND ih.remain > 0 
                     AND ih.delete_flag = 0), 
                    0
                ) as current_stock
            FROM bom_material_alternatives alt
            JOIN products p ON alt.alternative_material_id = p.id
            WHERE alt.bom_detail_id = :bom_detail_id
            ORDER BY alt.priority, p.name
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'bom_detail_id': bom_detail_id})
                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                return df
        except Exception as e:
            logger.error(f"Error getting alternatives: {e}")
            raise BOMException(f"Failed to get alternatives: {str(e)}")
    
    def get_where_used(self, product_id: int) -> pd.DataFrame:
        """
        Find where a product is used (as primary material or alternative)
        
        Returns DataFrame with columns:
        - bom_id, bom_code, bom_name, bom_type, bom_status
        - usage_type: 'PRIMARY' or 'ALTERNATIVE (Priority N)'
        - output_product_name, material_type, quantity, uom, scrap_rate
        """
        query = text("""
            -- Primary materials
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.status as bom_status,
                'PRIMARY' as usage_type,
                p_out.name as output_product_name,
                d.material_type,
                d.quantity,
                d.uom,
                d.scrap_rate
            FROM bom_headers h
            JOIN bom_details d ON d.bom_header_id = h.id
            JOIN products p_out ON h.product_id = p_out.id
            WHERE d.material_id = :product_id
            AND h.delete_flag = 0
            
            UNION ALL
            
            -- Alternative materials
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.status as bom_status,
                CONCAT('ALTERNATIVE (Priority ', alt.priority, ')') as usage_type,
                p_out.name as output_product_name,
                alt.material_type,
                alt.quantity,
                alt.uom,
                alt.scrap_rate
            FROM bom_headers h
            JOIN bom_details d ON d.bom_header_id = h.id
            JOIN bom_material_alternatives alt ON alt.bom_detail_id = d.id
            JOIN products p_out ON h.product_id = p_out.id
            WHERE alt.alternative_material_id = :product_id
            AND alt.is_active = 1
            AND h.delete_flag = 0
            
            ORDER BY bom_code, usage_type
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
        Create new BOM with materials and alternatives
        
        Args:
            bom_data: {
                'bom_name': str,
                'bom_type': str,
                'product_id': int,
                'output_qty': float,
                'uom': str,
                'effective_date': date,
                'notes': str,
                'materials': [
                    {
                        'material_id': int,
                        'material_type': str,
                        'quantity': float,
                        'uom': str,
                        'scrap_rate': float,
                        'alternatives': [
                            {
                                'alternative_material_id': int,
                                'quantity': float,
                                'uom': str,
                                'scrap_rate': float,
                                'priority': int
                            }
                        ]
                    }
                ],
                'created_by': int
            }
        
        Returns:
            str: BOM code
        """
        self._validate_bom_data(bom_data)
        
        try:
            with self.engine.begin() as conn:
                # Generate BOM code
                bom_code = self._generate_bom_code(conn, bom_data['bom_type'])
                
                # Insert header
                header_query = text("""
                    INSERT INTO bom_headers (
                        bom_code, bom_name, bom_type, product_id,
                        output_qty, uom, effective_date, notes,
                        status, version, created_by
                    ) VALUES (
                        :bom_code, :bom_name, :bom_type, :product_id,
                        :output_qty, :uom, :effective_date, :notes,
                        'DRAFT', 1, :created_by
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
                
                # Insert materials with alternatives
                materials = bom_data.get('materials', [])
                for material in materials:
                    # Insert material
                    detail_id = self._add_material_internal(conn, bom_id, material)
                    
                    # Insert alternatives if any
                    alternatives = material.get('alternatives', [])
                    for alternative in alternatives:
                        self._add_alternative_internal(conn, detail_id, alternative)
                
                logger.info(f"BOM created: {bom_code}")
                return bom_code
        
        except Exception as e:
            logger.error(f"Error creating BOM: {e}")
            raise BOMException(f"Failed to create BOM: {str(e)}")
    
    # ==================== UPDATE Operations ====================
    
    def update_bom_header(self, bom_id: int, updates: Dict):
        """Update BOM header information (DRAFT only)"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                set_clauses = []
                params = {'bom_id': bom_id}
                
                allowed_fields = [
                    'bom_name', 'output_qty', 'effective_date', 
                    'notes', 'updated_by'
                ]
                
                for field in allowed_fields:
                    if field in updates:
                        set_clauses.append(f"{field} = :{field}")
                        params[field] = updates[field]
                
                if not set_clauses:
                    return
                
                set_clauses.append("updated_date = NOW()")
                
                query = text(f"""
                    UPDATE bom_headers
                    SET {', '.join(set_clauses)}
                    WHERE id = :bom_id AND delete_flag = 0
                """)
                
                conn.execute(query, params)
                logger.info(f"BOM header updated: {bom_id}")
        
        except Exception as e:
            logger.error(f"Error updating BOM header: {e}")
            raise BOMException(f"Failed to update BOM header: {str(e)}")
    
    def update_bom_status(self, bom_id: int, new_status: str, user_id: int):
        """Update BOM status with validation"""
        try:
            with self.engine.begin() as conn:
                # Get current status
                query = text("""
                    SELECT status FROM bom_headers 
                    WHERE id = :bom_id AND delete_flag = 0
                """)
                result = conn.execute(query, {'bom_id': bom_id})
                row = result.fetchone()
                
                if not row:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                current_status = row[0]
                
                # Validate transition
                if not self._is_valid_status_transition(current_status, new_status):
                    raise BOMValidationError(
                        f"Invalid status transition: {current_status} → {new_status}"
                    )
                
                # Update status
                update_query = text("""
                    UPDATE bom_headers
                    SET status = :new_status,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :bom_id AND delete_flag = 0
                """)
                
                conn.execute(update_query, {
                    'bom_id': bom_id,
                    'new_status': new_status,
                    'user_id': user_id
                })
                
                logger.info(f"BOM status updated: {bom_id} → {new_status}")
        
        except Exception as e:
            logger.error(f"Error updating BOM status: {e}")
            raise BOMException(f"Failed to update BOM status: {str(e)}")
    
    def update_material(self, bom_id: int, material_id: int, updates: Dict):
        """Update material in BOM (DRAFT only)"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                set_clauses = []
                params = {'bom_id': bom_id, 'material_id': material_id}
                
                allowed_fields = ['quantity', 'scrap_rate', 'notes']
                
                for field in allowed_fields:
                    if field in updates:
                        set_clauses.append(f"{field} = :{field}")
                        params[field] = updates[field]
                
                if not set_clauses:
                    return
                
                query = text(f"""
                    UPDATE bom_details
                    SET {', '.join(set_clauses)}
                    WHERE bom_header_id = :bom_id 
                    AND material_id = :material_id
                """)
                
                conn.execute(query, params)
                logger.info(f"Material updated in BOM {bom_id}")
        
        except Exception as e:
            logger.error(f"Error updating material: {e}")
            raise BOMException(f"Failed to update material: {str(e)}")
    
    def add_materials(self, bom_id: int, materials: List[Dict]):
        """Add materials to BOM (DRAFT only)"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                for material in materials:
                    self._add_material_internal(conn, bom_id, material)
                
                logger.info(f"Materials added to BOM {bom_id}")
        
        except Exception as e:
            logger.error(f"Error adding materials: {e}")
            raise BOMException(f"Failed to add materials: {str(e)}")
    
    def remove_material(self, bom_id: int, material_id: int):
        """Remove material from BOM (DRAFT only)"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                query = text("""
                    DELETE FROM bom_details
                    WHERE bom_header_id = :bom_id 
                    AND material_id = :material_id
                """)
                
                conn.execute(query, {
                    'bom_id': bom_id,
                    'material_id': material_id
                })
                
                logger.info(f"Material removed from BOM {bom_id}")
        
        except Exception as e:
            logger.error(f"Error removing material: {e}")
            raise BOMException(f"Failed to remove material: {str(e)}")
    
    # ==================== ALTERNATIVE Operations ====================
    
    def add_alternative(self, bom_detail_id: int, alternative_data: Dict):
        """Add alternative material"""
        try:
            with self.engine.begin() as conn:
                self._add_alternative_internal(conn, bom_detail_id, alternative_data)
                logger.info(f"Alternative added to detail {bom_detail_id}")
        
        except Exception as e:
            logger.error(f"Error adding alternative: {e}")
            raise BOMException(f"Failed to add alternative: {str(e)}")
    
    def update_alternative(self, alternative_id: int, updates: Dict):
        """Update alternative material"""
        try:
            with self.engine.begin() as conn:
                set_clauses = []
                params = {'alternative_id': alternative_id}
                
                allowed_fields = [
                    'quantity', 'scrap_rate', 'priority', 
                    'is_active', 'notes'
                ]
                
                for field in allowed_fields:
                    if field in updates:
                        set_clauses.append(f"{field} = :{field}")
                        params[field] = updates[field]
                
                if not set_clauses:
                    return
                
                query = text(f"""
                    UPDATE bom_material_alternatives
                    SET {', '.join(set_clauses)}
                    WHERE id = :alternative_id
                """)
                
                conn.execute(query, params)
                logger.info(f"Alternative updated: {alternative_id}")
        
        except Exception as e:
            logger.error(f"Error updating alternative: {e}")
            raise BOMException(f"Failed to update alternative: {str(e)}")
    
    def remove_alternative(self, alternative_id: int):
        """Remove alternative material"""
        try:
            with self.engine.begin() as conn:
                query = text("""
                    DELETE FROM bom_material_alternatives
                    WHERE id = :alternative_id
                """)
                
                conn.execute(query, {'alternative_id': alternative_id})
                logger.info(f"Alternative removed: {alternative_id}")
        
        except Exception as e:
            logger.error(f"Error removing alternative: {e}")
            raise BOMException(f"Failed to remove alternative: {str(e)}")
    
    # ==================== DELETE Operations ====================
    
    def delete_bom(self, bom_id: int, user_id: int):
        """Soft delete BOM (only if not used and not ACTIVE)"""
        try:
            with self.engine.begin() as conn:
                # Check if can delete
                check_query = text("""
                    SELECT 
                        h.status,
                        COALESCE(
                            (SELECT COUNT(*) FROM manufacturing_orders mo 
                             WHERE mo.bom_header_id = h.id 
                             AND mo.delete_flag = 0), 
                            0
                        ) as usage_count
                    FROM bom_headers h
                    WHERE h.id = :bom_id AND h.delete_flag = 0
                """)
                
                result = conn.execute(check_query, {'bom_id': bom_id})
                row = result.fetchone()
                
                if not row:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                if row[0] == 'ACTIVE':
                    raise BOMValidationError("Cannot delete ACTIVE BOM")
                
                if row[1] > 0:
                    raise BOMValidationError(
                        f"Cannot delete BOM with {row[1]} manufacturing order(s)"
                    )
                
                # Soft delete
                delete_query = text("""
                    UPDATE bom_headers
                    SET delete_flag = 1,
                        updated_by = :user_id,
                        updated_date = NOW()
                    WHERE id = :bom_id
                """)
                
                conn.execute(delete_query, {
                    'bom_id': bom_id,
                    'user_id': user_id
                })
                
                logger.info(f"BOM deleted: {bom_id}")
        
        except Exception as e:
            logger.error(f"Error deleting BOM: {e}")
            raise BOMException(f"Failed to delete BOM: {str(e)}")
    
    # ==================== VALIDATION Operations ====================
    
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
        validation = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            bom_info = self.get_bom_info(bom_id)
            bom_details = self.get_bom_details(bom_id)
            
            if not bom_info:
                validation['valid'] = False
                validation['errors'].append("BOM not found")
                return validation
            
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
                # Check if alternatives have stock
                for _, mat in no_stock.iterrows():
                    alts = self.get_material_alternatives(mat['id'])
                    alts_with_stock = alts[alts['current_stock'] > 0]
                    
                    if alts_with_stock.empty:
                        validation['warnings'].append(
                            f"Material '{mat['material_name']}' and its alternatives have no stock"
                        )
            
            # Check high scrap rates
            high_scrap = bom_details[bom_details['scrap_rate'] > 20]
            if not high_scrap.empty:
                validation['warnings'].append(
                    f"{len(high_scrap)} material(s) have scrap rate > 20%"
                )
            
            # Check circular reference
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
        allowed_transitions = {
            'DRAFT': ['ACTIVE', 'INACTIVE'],
            'ACTIVE': ['INACTIVE'],
            'INACTIVE': ['ACTIVE']
        }
        
        if current == new:
            return False
        
        return new in allowed_transitions.get(current, [])
    
    def _generate_bom_code(self, conn, bom_type: str) -> str:
        """Generate unique BOM code with locking"""
        prefix = bom_type[:3].upper() if bom_type else "BOM"
        
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
    
    def _add_material_internal(self, conn, bom_id: int, material: Dict) -> int:
        """Internal method to add material (returns detail_id)"""
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
        
        result = conn.execute(query, {
            'bom_id': bom_id,
            'material_id': material['material_id'],
            'material_type': material.get('material_type', 'RAW_MATERIAL'),
            'quantity': material.get('quantity', 1),
            'uom': material.get('uom', 'PCS'),
            'scrap_rate': material.get('scrap_rate', 0),
            'notes': material.get('notes', '')
        })
        
        return result.lastrowid
    
    def _add_alternative_internal(self, conn, bom_detail_id: int, alternative: Dict) -> int:
        """Internal method to add alternative (returns alternative_id)"""
        if alternative.get('quantity', 0) <= 0:
            raise BOMValidationError("Alternative quantity must be greater than 0")
        
        if alternative.get('scrap_rate', 0) < 0 or alternative.get('scrap_rate', 0) > 100:
            raise BOMValidationError("Alternative scrap rate must be between 0 and 100")
        
        query = text("""
            INSERT INTO bom_material_alternatives (
                bom_detail_id, alternative_material_id, material_type,
                quantity, uom, scrap_rate, priority, is_active, notes
            ) VALUES (
                :bom_detail_id, :alternative_material_id, :material_type,
                :quantity, :uom, :scrap_rate, :priority, :is_active, :notes
            )
        """)
        
        result = conn.execute(query, {
            'bom_detail_id': bom_detail_id,
            'alternative_material_id': alternative['alternative_material_id'],
            'material_type': alternative.get('material_type', 'RAW_MATERIAL'),
            'quantity': alternative.get('quantity', 1),
            'uom': alternative.get('uom', 'PCS'),
            'scrap_rate': alternative.get('scrap_rate', 0),
            'priority': alternative.get('priority', 1),
            'is_active': alternative.get('is_active', 1),
            'notes': alternative.get('notes', '')
        })
        
        return result.lastrowid
    
    def _has_circular_reference(self, bom_id: int, visited: Optional[set] = None) -> bool:
        """Check for circular BOM references"""
        if visited is None:
            visited = set()
        
        if bom_id in visited:
            return True
        
        visited.add(bom_id)
        
        try:
            bom_info = self.get_bom_info(bom_id)
            if not bom_info:
                return False
            
            output_product_id = bom_info['product_id']
            where_used = self.get_where_used(output_product_id)
            
            for _, used_bom in where_used.iterrows():
                if self._has_circular_reference(used_bom['bom_id'], visited.copy()):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking circular reference: {e}")
            return False