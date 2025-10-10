# modules/bom.py - Complete BOM Management
"""
Bill of Materials (BOM) Management Module
Handles BOM creation, editing, and material management.
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import pandas as pd
from sqlalchemy import text
from utils.db import get_db_engine

logger = logging.getLogger(__name__)


class BOMManager:
    """BOM Management for Production"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== BOM List & Search ====================
    
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
                COUNT(DISTINCT d.id) as material_count,
                (SELECT COUNT(*) FROM manufacturing_orders mo 
                 WHERE mo.bom_header_id = h.id) as usage_count,
                h.created_date
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            LEFT JOIN bom_details d ON d.bom_header_id = h.id
            WHERE h.delete_flag = 0
        """
        
        params = []
        
        if bom_type:
            query += " AND h.bom_type = %s"
            params.append(bom_type)
        
        if status:
            query += " AND h.status = %s"
            params.append(status)
        
        if search:
            query += " AND (h.bom_code LIKE %s OR h.bom_name LIKE %s OR p.name LIKE %s)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        query += """ 
            GROUP BY h.id, h.bom_code, h.bom_name, h.bom_type, h.product_id,
                     p.name, h.output_qty, h.uom, h.status, h.version,
                     h.effective_date, h.created_date
            ORDER BY h.created_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, 
                             params=tuple(params) if params else None)
        except Exception as e:
            logger.error(f"Error getting BOMs: {e}")
            return pd.DataFrame()
    
    def get_active_boms(self, bom_type: Optional[str] = None) -> pd.DataFrame:
        """Get active BOMs only"""
        return self.get_boms(bom_type=bom_type, status='ACTIVE')
    
    # ==================== BOM Creation ====================
    
    def create_bom(self, bom_data: Dict) -> str:
        """Create new BOM"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
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
                    self._add_material(conn, bom_id, material)
            
            trans.commit()
            logger.info(f"Created BOM {bom_code}")
            return bom_code
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating BOM: {e}")
            raise
        finally:
            conn.close()
    
    # ==================== BOM Editing ====================
    
    def add_materials(self, bom_id: int, materials: List[Dict]) -> bool:
        """Add materials to existing BOM"""
        with self.engine.begin() as conn:
            try:
                for material in materials:
                    self._add_material(conn, bom_id, material)
                
                logger.info(f"Added {len(materials)} materials to BOM {bom_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error adding materials: {e}")
                raise
    
    def update_material(self, bom_id: int, material_id: int, 
                       updates: Dict) -> bool:
        """Update material in BOM"""
        with self.engine.begin() as conn:
            try:
                query = text("""
                    UPDATE bom_details
                    SET quantity = :quantity,
                        scrap_rate = :scrap_rate,
                        notes = :notes
                    WHERE bom_header_id = :bom_id 
                        AND material_id = :material_id
                """)
                
                result = conn.execute(query, {
                    'quantity': updates.get('quantity'),
                    'scrap_rate': updates.get('scrap_rate', 0),
                    'notes': updates.get('notes', ''),
                    'bom_id': bom_id,
                    'material_id': material_id
                })
                
                return result.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error updating material: {e}")
                return False
    
    def remove_material(self, bom_id: int, material_id: int) -> bool:
        """Remove material from BOM"""
        with self.engine.begin() as conn:
            try:
                # Check if BOM is in use
                if self._is_bom_in_use(conn, bom_id):
                    raise ValueError("Cannot modify BOM - currently in use")
                
                query = text("""
                    DELETE FROM bom_details
                    WHERE bom_header_id = :bom_id 
                        AND material_id = :material_id
                """)
                
                result = conn.execute(query, {
                    'bom_id': bom_id,
                    'material_id': material_id
                })
                
                return result.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error removing material: {e}")
                return False
    
    # ==================== BOM Info & Details ====================
    
    def get_bom_info(self, bom_id: int) -> Optional[Dict]:
        """Get BOM header information"""
        query = """
            SELECT 
                h.*,
                p.name as product_name,
                p.pt_code as product_code,
                (SELECT COUNT(*) FROM manufacturing_orders mo 
                 WHERE mo.bom_header_id = h.id) as total_usage,
                (SELECT COUNT(*) FROM manufacturing_orders mo 
                 WHERE mo.bom_header_id = h.id 
                 AND mo.status IN ('CONFIRMED', 'IN_PROGRESS')) as active_orders
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            WHERE h.id = %s AND h.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(bom_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting BOM info: {e}")
            return None
    
    def get_bom_details(self, bom_id: int) -> pd.DataFrame:
        """Get BOM materials"""
        query = """
            SELECT 
                d.*,
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
            WHERE d.bom_header_id = %s
            ORDER BY d.material_type, p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(bom_id,))
        except Exception as e:
            logger.error(f"Error getting BOM details: {e}")
            return pd.DataFrame()
    
    # ==================== BOM Status Management ====================
    
    def update_bom_status(self, bom_id: int, new_status: str, 
                         updated_by: Optional[int] = None) -> bool:
        """Update BOM status"""
        with self.engine.begin() as conn:
            try:
                # Validate BOM has materials if activating
                if new_status == 'ACTIVE':
                    check_query = text("""
                        SELECT COUNT(*) as count 
                        FROM bom_details 
                        WHERE bom_header_id = :bom_id
                    """)
                    
                    result = conn.execute(check_query, {'bom_id': bom_id})
                    if result.scalar() == 0:
                        raise ValueError("Cannot activate BOM without materials")
                
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
                
                return result.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error updating BOM status: {e}")
                raise
    
    # ==================== BOM Operations ====================
    
    def copy_bom(self, source_bom_id: int, new_name: str, 
                 created_by: Optional[int] = None) -> str:
        """Copy existing BOM"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Get source BOM
            source = self.get_bom_info(source_bom_id)
            if not source:
                raise ValueError(f"BOM {source_bom_id} not found")
            
            # Generate new code
            new_code = self._generate_bom_code(conn, source['bom_type'])
            
            # Copy header
            header_query = text("""
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id,
                    output_qty, uom, status, version,
                    effective_date, notes, created_by, created_date
                )
                SELECT 
                    :new_code, :new_name, bom_type, product_id,
                    output_qty, uom, 'DRAFT', 1,
                    CURDATE(), 
                    CONCAT('Copied from ', bom_code),
                    :created_by, NOW()
                FROM bom_headers
                WHERE id = :source_id
            """)
            
            result = conn.execute(header_query, {
                'new_code': new_code,
                'new_name': new_name,
                'created_by': created_by,
                'source_id': source_bom_id
            })
            
            new_bom_id = result.lastrowid
            
            # Copy details
            detail_query = text("""
                INSERT INTO bom_details (
                    bom_header_id, material_id, material_type,
                    quantity, uom, scrap_rate, notes
                )
                SELECT 
                    :new_bom_id, material_id, material_type,
                    quantity, uom, scrap_rate, notes
                FROM bom_details
                WHERE bom_header_id = :source_id
            """)
            
            conn.execute(detail_query, {
                'new_bom_id': new_bom_id,
                'source_id': source_bom_id
            })
            
            trans.commit()
            logger.info(f"Copied BOM to {new_code}")
            return new_code
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error copying BOM: {e}")
            raise
        finally:
            conn.close()
    
    def delete_bom(self, bom_id: int, deleted_by: Optional[int] = None) -> bool:
        """Soft delete BOM"""
        with self.engine.begin() as conn:
            try:
                # Check if BOM is in use
                if self._is_bom_in_use(conn, bom_id):
                    raise ValueError("Cannot delete BOM - currently in use")
                
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
                
                return result.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error deleting BOM: {e}")
                raise
    
    # ==================== Analysis & Validation ====================
    
    def validate_bom_materials(self, bom_id: int) -> Dict:
        """Validate BOM materials"""
        try:
            details = self.get_bom_details(bom_id)
            
            validation = {
                'valid': True,
                'errors': [],
                'warnings': []
            }
            
            if details.empty:
                validation['valid'] = False
                validation['errors'].append("BOM has no materials")
                return validation
            
            # Check for duplicates
            duplicates = details[details.duplicated(['material_id'], keep=False)]
            if not duplicates.empty:
                validation['warnings'].append("BOM contains duplicate materials")
            
            # Check stock availability
            for _, material in details.iterrows():
                if material['current_stock'] <= 0:
                    validation['warnings'].append(
                        f"{material['material_name']}: No stock available"
                    )
            
            # Check scrap rates
            high_scrap = details[details['scrap_rate'] > 20]
            if not high_scrap.empty:
                validation['warnings'].append(
                    f"{len(high_scrap)} material(s) have scrap rate > 20%"
                )
            
            return validation
            
        except Exception as e:
            logger.error(f"Error validating BOM: {e}")
            return {
                'valid': False,
                'errors': [str(e)],
                'warnings': []
            }
    
    def get_where_used(self, product_id: int) -> pd.DataFrame:
        """Get BOMs where product is used"""
        query = """
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.status as bom_status,
                h.bom_type,
                p.name as output_product_name,
                d.quantity,
                d.uom,
                d.material_type,
                d.scrap_rate
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON h.product_id = p.id
            WHERE d.material_id = %s AND h.delete_flag = 0
            ORDER BY h.status DESC, h.bom_name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id,))
        except Exception as e:
            logger.error(f"Error getting where used: {e}")
            return pd.DataFrame()
    
    def get_material_usage_summary(self) -> pd.DataFrame:
        """Get material usage summary"""
        query = """
            SELECT 
                p.id as material_id,
                p.name as material_name,
                p.pt_code as material_code,
                COUNT(DISTINCT d.bom_header_id) as usage_count,
                SUM(d.quantity) as total_base_quantity,
                AVG(d.scrap_rate) as avg_scrap_rate,
                SUM(CASE WHEN h.status = 'ACTIVE' THEN 1 ELSE 0 END) as active_bom_count
            FROM bom_details d
            JOIN products p ON d.material_id = p.id
            JOIN bom_headers h ON d.bom_header_id = h.id
            WHERE h.delete_flag = 0
            GROUP BY p.id, p.name, p.pt_code
            ORDER BY usage_count DESC
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting material usage summary: {e}")
            return pd.DataFrame()
    
    # ==================== Helper Methods ====================
    
    def _generate_bom_code(self, conn, bom_type: str) -> str:
        """Generate unique BOM code"""
        prefix = bom_type[:3].upper() if bom_type else "BOM"
        
        query = text("""
            SELECT COALESCE(MAX(CAST(
                SUBSTRING(bom_code, LENGTH(:prefix) + 2) AS UNSIGNED)
            ), 0) + 1 as next_seq
            FROM bom_headers
            WHERE bom_code LIKE CONCAT(:prefix, '-%')
        """)
        
        result = conn.execute(query, {'prefix': prefix})
        next_seq = result.scalar() or 1
        
        return f"{prefix}-{next_seq:04d}"
    
    def _add_material(self, conn, bom_id: int, material: Dict):
        """Add material to BOM"""
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
    
    def _is_bom_in_use(self, conn, bom_id: int) -> bool:
        """Check if BOM is used in any orders"""
        query = text("""
            SELECT COUNT(*) as count
            FROM manufacturing_orders
            WHERE bom_header_id = :bom_id
                AND delete_flag = 0
        """)
        
        result = conn.execute(query, {'bom_id': bom_id})
        return result.scalar() > 0