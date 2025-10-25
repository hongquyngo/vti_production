# utils/bom/manager.py
"""
Bill of Materials (BOM) Management - Complete CRUD with Alternatives Support
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
                ) as active_orders,
                COALESCE(
                    (SELECT COUNT(*) FROM bom_details d
                     WHERE d.bom_header_id = h.id),
                    0
                ) as material_count
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
            ORDER BY alt.priority ASC, p.name
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'bom_detail_id': bom_detail_id})
                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                return df
        except Exception as e:
            logger.error(f"Error getting alternatives: {e}")
            raise BOMException(f"Failed to get alternatives: {str(e)}")
    
    def get_bom_with_alternatives(self, bom_id: int) -> Dict:
        """Get complete BOM structure with all alternatives"""
        try:
            bom_info = self.get_bom_info(bom_id)
            if not bom_info:
                raise BOMNotFoundError(f"BOM {bom_id} not found")
            
            bom_details = self.get_bom_details(bom_id)
            
            # Get alternatives for each material
            materials_with_alts = []
            for _, material in bom_details.iterrows():
                mat_dict = material.to_dict()
                mat_dict['alternatives'] = self.get_material_alternatives(material['id']).to_dict('records')
                materials_with_alts.append(mat_dict)
            
            return {
                'header': bom_info,
                'materials': materials_with_alts
            }
        except Exception as e:
            logger.error(f"Error getting BOM with alternatives: {e}")
            raise BOMException(f"Failed to get BOM structure: {str(e)}")
    
    def get_where_used(self, product_id: int) -> pd.DataFrame:
        """Get BOMs where product is used as material or alternative"""
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
                d.scrap_rate,
                'PRIMARY' as usage_type,
                1 as priority
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON h.product_id = p.id
            WHERE d.material_id = :product_id 
                AND h.delete_flag = 0
            
            UNION
            
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.status as bom_status,
                h.bom_type,
                p.name as output_product_name,
                alt.material_type,
                alt.quantity,
                alt.uom,
                alt.scrap_rate,
                CONCAT('ALTERNATIVE (Priority ', alt.priority, ')') as usage_type,
                alt.priority
            FROM bom_material_alternatives alt
            JOIN bom_details d ON alt.bom_detail_id = d.id
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON h.product_id = p.id
            WHERE alt.alternative_material_id = :product_id
                AND alt.is_active = 1
                AND h.delete_flag = 0
            
            ORDER BY bom_status DESC, bom_name, priority
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
                        'notes': str,
                        'alternatives': [  # Optional
                            {
                                'alternative_material_id': int,
                                'material_type': str,
                                'quantity': float,
                                'uom': str,
                                'scrap_rate': float,
                                'priority': int,
                                'notes': str
                            }
                        ]
                    }
                ],
                'created_by': int
            }
        
        Returns:
            BOM code
        """
        try:
            self._validate_bom_data(bom_data)
            
            with self.engine.begin() as conn:
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
                    'created_by': bom_data['created_by']
                })
                
                bom_id = result.lastrowid
                
                # Insert materials with alternatives
                if 'materials' in bom_data and bom_data['materials']:
                    for material in bom_data['materials']:
                        detail_id = self._add_material_internal(conn, bom_id, material)
                        
                        # Add alternatives if provided
                        if 'alternatives' in material and material['alternatives']:
                            for alt in material['alternatives']:
                                self._add_alternative_internal(conn, detail_id, alt)
                
                logger.info(f"Created BOM {bom_code} (ID: {bom_id})")
                return bom_code
                
        except Exception as e:
            logger.error(f"Error creating BOM: {e}")
            raise
    
    # ==================== UPDATE Operations ====================
    
    def update_bom_header(self, bom_id: int, updates: Dict) -> bool:
        """Update BOM header information"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                allowed_fields = ['bom_name', 'output_qty', 'effective_date', 'notes', 'updated_by']
                update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
                
                if not update_fields:
                    return False
                
                update_fields['updated_date'] = 'NOW()'
                
                set_clause = ', '.join([f"{k} = :{k}" for k in update_fields.keys()])
                
                query = text(f"""
                    UPDATE bom_headers 
                    SET {set_clause}
                    WHERE id = :bom_id
                """)
                
                update_fields['bom_id'] = bom_id
                conn.execute(query, update_fields)
                
                logger.info(f"Updated BOM header {bom_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating BOM header: {e}")
            raise
    
    def update_bom_status(self, bom_id: int, new_status: str, updated_by: int) -> bool:
        """Update BOM status"""
        try:
            with self.engine.begin() as conn:
                # Get current status
                query = text("SELECT status FROM bom_headers WHERE id = :bom_id AND delete_flag = 0")
                result = conn.execute(query, {'bom_id': bom_id})
                row = result.fetchone()
                
                if not row:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                current_status = row[0]
                
                # Validate transition
                if not self._is_valid_status_transition(current_status, new_status):
                    raise BOMValidationError(
                        f"Cannot transition from {current_status} to {new_status}"
                    )
                
                # Update status
                update_query = text("""
                    UPDATE bom_headers 
                    SET status = :status,
                        updated_by = :updated_by,
                        updated_date = NOW()
                    WHERE id = :bom_id
                """)
                
                conn.execute(update_query, {
                    'bom_id': bom_id,
                    'status': new_status,
                    'updated_by': updated_by
                })
                
                logger.info(f"Updated BOM {bom_id} status: {current_status} -> {new_status}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating BOM status: {e}")
            raise
    
    def add_materials(self, bom_id: int, materials: List[Dict]) -> bool:
        """Add materials to BOM"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                for material in materials:
                    detail_id = self._add_material_internal(conn, bom_id, material)
                    
                    # Add alternatives if provided
                    if 'alternatives' in material and material['alternatives']:
                        for alt in material['alternatives']:
                            self._add_alternative_internal(conn, detail_id, alt)
                
                logger.info(f"Added {len(materials)} material(s) to BOM {bom_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error adding materials: {e}")
            raise
    
    def update_material(self, bom_id: int, material_id: int, updates: Dict) -> bool:
        """Update BOM material"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
                allowed_fields = ['quantity', 'scrap_rate', 'material_type', 'notes']
                update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
                
                if not update_fields:
                    return False
                
                set_clause = ', '.join([f"{k} = :{k}" for k in update_fields.keys()])
                
                query = text(f"""
                    UPDATE bom_details 
                    SET {set_clause}
                    WHERE bom_header_id = :bom_id 
                    AND material_id = :material_id
                """)
                
                update_fields['bom_id'] = bom_id
                update_fields['material_id'] = material_id
                
                result = conn.execute(query, update_fields)
                
                if result.rowcount == 0:
                    raise BOMValidationError("Material not found in BOM")
                
                logger.info(f"Updated material {material_id} in BOM {bom_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating material: {e}")
            raise
    
    def remove_material(self, bom_id: int, material_id: int) -> bool:
        """Remove material from BOM (also removes alternatives via CASCADE)"""
        try:
            with self.engine.begin() as conn:
                self._check_bom_editable(conn, bom_id)
                
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
                    raise BOMValidationError("Material not found in BOM")
                
                logger.info(f"Removed material {material_id} from BOM {bom_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error removing material: {e}")
            raise
    
    # ==================== ALTERNATIVES Operations ====================
    
    def add_alternative(self, bom_detail_id: int, alternative_data: Dict) -> int:
        """Add alternative material"""
        try:
            with self.engine.begin() as conn:
                # Get BOM ID to check editability
                query = text("SELECT bom_header_id FROM bom_details WHERE id = :detail_id")
                result = conn.execute(query, {'detail_id': bom_detail_id})
                row = result.fetchone()
                
                if not row:
                    raise BOMValidationError("BOM detail not found")
                
                bom_id = row[0]
                self._check_bom_editable(conn, bom_id)
                
                alt_id = self._add_alternative_internal(conn, bom_detail_id, alternative_data)
                
                logger.info(f"Added alternative to BOM detail {bom_detail_id}")
                return alt_id
                
        except Exception as e:
            logger.error(f"Error adding alternative: {e}")
            raise
    
    def update_alternative(self, alternative_id: int, updates: Dict) -> bool:
        """Update alternative material"""
        try:
            with self.engine.begin() as conn:
                # Get BOM ID via detail_id
                query = text("""
                    SELECT d.bom_header_id 
                    FROM bom_material_alternatives alt
                    JOIN bom_details d ON alt.bom_detail_id = d.id
                    WHERE alt.id = :alt_id
                """)
                result = conn.execute(query, {'alt_id': alternative_id})
                row = result.fetchone()
                
                if not row:
                    raise BOMValidationError("Alternative not found")
                
                bom_id = row[0]
                self._check_bom_editable(conn, bom_id)
                
                allowed_fields = ['quantity', 'scrap_rate', 'material_type', 'priority', 'is_active', 'notes']
                update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
                
                if not update_fields:
                    return False
                
                set_clause = ', '.join([f"{k} = :{k}" for k in update_fields.keys()])
                
                update_query = text(f"""
                    UPDATE bom_material_alternatives 
                    SET {set_clause}
                    WHERE id = :alt_id
                """)
                
                update_fields['alt_id'] = alternative_id
                conn.execute(update_query, update_fields)
                
                logger.info(f"Updated alternative {alternative_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating alternative: {e}")
            raise
    
    def remove_alternative(self, alternative_id: int) -> bool:
        """Remove alternative material"""
        try:
            with self.engine.begin() as conn:
                # Get BOM ID via detail_id
                query = text("""
                    SELECT d.bom_header_id 
                    FROM bom_material_alternatives alt
                    JOIN bom_details d ON alt.bom_detail_id = d.id
                    WHERE alt.id = :alt_id
                """)
                result = conn.execute(query, {'alt_id': alternative_id})
                row = result.fetchone()
                
                if not row:
                    raise BOMValidationError("Alternative not found")
                
                bom_id = row[0]
                self._check_bom_editable(conn, bom_id)
                
                delete_query = text("DELETE FROM bom_material_alternatives WHERE id = :alt_id")
                conn.execute(delete_query, {'alt_id': alternative_id})
                
                logger.info(f"Removed alternative {alternative_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error removing alternative: {e}")
            raise
    
    # ==================== DELETE Operations ====================
    
    def delete_bom(self, bom_id: int, deleted_by: int) -> bool:
        """Soft delete BOM"""
        try:
            with self.engine.begin() as conn:
                bom_info = self.get_bom_info(bom_id)
                
                if not bom_info:
                    raise BOMNotFoundError(f"BOM {bom_id} not found")
                
                if bom_info['status'] == 'ACTIVE':
                    raise BOMValidationError("Cannot delete ACTIVE BOM")
                
                if bom_info['total_usage'] > 0:
                    raise BOMValidationError(
                        f"Cannot delete BOM with {bom_info['total_usage']} usage records"
                    )
                
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