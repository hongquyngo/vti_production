# utils/bom/manager.py
"""
Bill of Materials (BOM) Management - VERSION 2.1
Complete CRUD operations with creator info support

Changes in v2.1:
- Added creator info (created_by, creator_name) to all queries
- Support for employee lookup via users table
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== Helper Functions ====================

def convert_to_native(value: Any) -> Any:
    """Convert numpy types to Python native types"""
    if isinstance(value, (np.int64, np.int32, np.int16, np.int8)):
        return int(value)
    elif isinstance(value, (np.float64, np.float32)):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    elif isinstance(value, np.ndarray):
        return value.tolist()
    else:
        return value


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
    """Complete BOM Management with CRUD operations, Alternatives and Clone support"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== READ Operations ====================
    
    def get_boms(self, bom_type: Optional[str] = None,
                 status: Optional[str] = None,
                 search: Optional[str] = None) -> pd.DataFrame:
        """Get BOMs with filters, full product info and creator info"""
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
                h.created_by,
                h.created_date,
                h.updated_by,
                h.updated_date,
                COALESCE(
                    CONCAT(e.first_name, ' ', e.last_name),
                    u.username,
                    'Unknown'
                ) as creator_name
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN bom_details d ON d.bom_header_id = h.id
            LEFT JOIN users u ON h.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE h.delete_flag = 0
        """
        
        params = []
        
        if bom_type:
            query += " AND h.bom_type = %s"
            params.append(str(bom_type))
        
        if status:
            query += " AND h.status = %s"
            params.append(str(status))
        
        if search:
            query += """ AND (
                h.bom_code LIKE %s 
                OR h.bom_name LIKE %s 
                OR p.name LIKE %s
            )"""
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        query += """ 
            GROUP BY h.id, h.bom_code, h.bom_name, h.bom_type, h.product_id,
                     p.name, p.pt_code, p.package_size, b.brand_name,
                     h.output_qty, h.uom, h.status, h.version, 
                     h.effective_date, h.notes, h.created_by, h.created_date,
                     h.updated_by, h.updated_date, e.first_name, e.last_name, u.username
            ORDER BY h.created_date DESC
        """
        
        try:
            if params:
                return pd.read_sql(query, self.engine, params=tuple(params))
            else:
                return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting BOMs: {e}")
            raise BOMException(f"Failed to get BOMs: {str(e)}")
    
    def get_bom_info(self, bom_id: int) -> Optional[dict]:
        """Get BOM header information with creator info"""
        # Convert numpy types to native Python types
        bom_id = convert_to_native(bom_id)
        
        query = """
            SELECT 
                h.id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.product_id,
                p.name as product_name,
                p.pt_code as product_code,
                h.output_qty,
                h.uom,
                h.status,
                h.version,
                h.effective_date,
                h.notes,
                h.created_by,
                h.created_date,
                h.updated_by,
                h.updated_date,
                COALESCE(
                    CONCAT(e.first_name, ' ', e.last_name),
                    u.username,
                    'Unknown'
                ) as creator_name,
                COALESCE(
                    CONCAT(e2.first_name, ' ', e2.last_name),
                    u2.username,
                    ''
                ) as updater_name,
                COUNT(DISTINCT d.id) as material_count,
                COALESCE(SUM(a.id IS NOT NULL), 0) as total_alternatives,
                COALESCE(
                    (SELECT COUNT(*) FROM manufacturing_orders mo 
                     WHERE mo.bom_header_id = h.id 
                     AND mo.delete_flag = 0), 
                    0
                ) as total_usage,
                COALESCE(
                    (SELECT COUNT(*) FROM manufacturing_orders mo 
                     WHERE mo.bom_header_id = h.id 
                     AND mo.status IN ('PENDING', 'IN_PROGRESS')
                     AND mo.delete_flag = 0), 
                    0
                ) as active_orders
            FROM bom_headers h
            JOIN products p ON h.product_id = p.id
            LEFT JOIN bom_details d ON d.bom_header_id = h.id
            LEFT JOIN bom_material_alternatives a ON a.bom_detail_id = d.id
            LEFT JOIN users u ON h.created_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            LEFT JOIN users u2 ON h.updated_by = u2.id
            LEFT JOIN employees e2 ON u2.employee_id = e2.id
            WHERE h.id = %s AND h.delete_flag = 0
            GROUP BY h.id, h.bom_code, h.bom_name, h.bom_type, 
                     h.product_id, p.name, p.pt_code, h.output_qty,
                     h.uom, h.status, h.version, h.effective_date, h.notes,
                     h.created_by, h.created_date, h.updated_by, h.updated_date,
                     e.first_name, e.last_name, u.username,
                     e2.first_name, e2.last_name, u2.username
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(bom_id,))
            if not result.empty:
                return result.iloc[0].to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting BOM info: {e}")
            raise BOMException(f"Failed to get BOM info: {str(e)}")
    
    def get_bom_details(self, bom_id: int) -> pd.DataFrame:
        """Get BOM materials with stock info and alternatives count"""
        # Convert numpy types to native Python types
        bom_id = convert_to_native(bom_id)
        
        query = """
            SELECT 
                d.id,
                d.material_id,
                p.name as material_name,
                p.pt_code as material_code,
                d.material_type,
                d.quantity,
                d.uom,
                d.scrap_rate,
                COALESCE(
                    (SELECT SUM(inv.remain) 
                     FROM inventory_histories inv 
                     WHERE inv.product_id = d.material_id 
                     AND inv.remain > 0
                     AND inv.delete_flag = 0), 
                    0
                ) as current_stock,
                (SELECT COUNT(*) 
                 FROM bom_material_alternatives alt 
                 WHERE alt.bom_detail_id = d.id) as alternatives_count
            FROM bom_details d
            JOIN products p ON d.material_id = p.id
            WHERE d.bom_header_id = %s
            ORDER BY 
                CASE d.material_type 
                    WHEN 'RAW_MATERIAL' THEN 1 
                    WHEN 'PACKAGING' THEN 2 
                    ELSE 3 
                END,
                d.id
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(bom_id,))
        except Exception as e:
            logger.error(f"Error getting BOM details: {e}")
            raise BOMException(f"Failed to get BOM details: {str(e)}")
    
    def get_material_alternatives(self, detail_id: int) -> pd.DataFrame:
        """Get alternatives for a specific material"""
        detail_id = convert_to_native(detail_id)
        
        query = """
            SELECT 
                a.id,
                a.bom_detail_id,
                a.alternative_material_id as material_id,
                p.name as material_name,
                p.pt_code as material_code,
                a.material_type,
                a.quantity,
                a.uom,
                a.scrap_rate,
                a.priority,
                a.is_active,
                a.notes,
                COALESCE(
                    (SELECT SUM(inv.remain) 
                     FROM inventory_histories inv 
                     WHERE inv.product_id = a.alternative_material_id 
                     AND inv.remain > 0
                     AND inv.delete_flag = 0), 
                    0
                ) as current_stock
            FROM bom_material_alternatives a
            JOIN products p ON a.alternative_material_id = p.id
            WHERE a.bom_detail_id = %s
            ORDER BY a.priority
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(detail_id,))
        except Exception as e:
            logger.error(f"Error getting alternatives: {e}")
            raise BOMException(f"Failed to get alternatives: {str(e)}")
    
    # ==================== CREATE Operations ====================
    
    def create_bom(self, bom_data: Dict, materials: List[Dict] = None, user_id: int = None) -> str:
        """
        Create new BOM with materials and alternatives
        
        Supports two calling conventions:
        1. create_bom(bom_data) where bom_data contains 'materials' and 'created_by'
        2. create_bom(bom_data, materials, user_id) with separate arguments
        
        Returns:
            bom_code: The generated BOM code (e.g., 'BOM-202512-001')
        """
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Support both calling conventions
            if materials is None:
                materials = bom_data.get('materials', [])
            if user_id is None:
                user_id = bom_data.get('created_by', 1)
            
            user_id = convert_to_native(user_id)
            product_id = convert_to_native(bom_data['product_id'])
            
            # Generate BOM code
            bom_code = self._generate_bom_code(conn, bom_data['bom_type'])
            
            # Insert header
            header_query = text("""
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id, output_qty,
                    uom, status, version, effective_date, notes,
                    created_by, created_date
                ) VALUES (
                    :bom_code, :bom_name, :bom_type, :product_id, :output_qty,
                    :uom, :status, :version, :effective_date, :notes,
                    :created_by, NOW()
                )
            """)
            
            result = conn.execute(header_query, {
                'bom_code': bom_code,
                'bom_name': str(bom_data['bom_name']),
                'bom_type': str(bom_data['bom_type']),
                'product_id': product_id,
                'output_qty': float(bom_data['output_qty']),
                'uom': str(bom_data['uom']),
                'status': str(bom_data.get('status', 'DRAFT')),
                'version': 1,
                'effective_date': bom_data.get('effective_date'),
                'notes': str(bom_data.get('notes', '') or ''),
                'created_by': user_id
            })
            
            bom_id = result.lastrowid
            
            # Insert materials
            for material in materials:
                material_id = convert_to_native(material['material_id'])
                
                # Get UOM from product
                uom_query = text("SELECT uom FROM products WHERE id = :material_id")
                uom_result = conn.execute(uom_query, {'material_id': material_id})
                uom_row = uom_result.fetchone()
                material_uom = uom_row[0] if uom_row else 'PCS'
                
                detail_query = text("""
                    INSERT INTO bom_details (
                        bom_header_id, material_id, material_type,
                        quantity, uom, scrap_rate
                    ) VALUES (
                        :bom_header_id, :material_id, :material_type,
                        :quantity, :uom, :scrap_rate
                    )
                """)
                
                detail_result = conn.execute(detail_query, {
                    'bom_header_id': bom_id,
                    'material_id': material_id,
                    'material_type': str(material['material_type']),
                    'quantity': float(material['quantity']),
                    'uom': str(material_uom),
                    'scrap_rate': float(material.get('scrap_rate', 0))
                })
                
                detail_id = detail_result.lastrowid
                
                # Insert alternatives if any
                alternatives = material.get('alternatives', [])
                for alt in alternatives:
                    # Support both 'material_id' and 'alternative_material_id' keys
                    alt_mat_id = alt.get('alternative_material_id') or alt.get('material_id')
                    alt_material_id = convert_to_native(alt_mat_id)
                    
                    # Get UOM for alternative
                    alt_uom_result = conn.execute(uom_query, {'material_id': alt_material_id})
                    alt_uom_row = alt_uom_result.fetchone()
                    alt_uom = alt_uom_row[0] if alt_uom_row else 'PCS'
                    
                    alt_query = text("""
                        INSERT INTO bom_material_alternatives (
                            bom_detail_id, alternative_material_id,
                            material_type, quantity, uom, scrap_rate,
                            priority, is_active, notes, created_date
                        ) VALUES (
                            :bom_detail_id, :alternative_material_id,
                            :material_type, :quantity, :uom, :scrap_rate,
                            :priority, :is_active, :notes, NOW()
                        )
                    """)
                    
                    conn.execute(alt_query, {
                        'bom_detail_id': detail_id,
                        'alternative_material_id': alt_material_id,
                        'material_type': str(material['material_type']),
                        'quantity': float(alt['quantity']),
                        'uom': str(alt_uom),
                        'scrap_rate': float(alt.get('scrap_rate', 0)),
                        'priority': convert_to_native(alt.get('priority', 1)),
                        'is_active': 1,
                        'notes': str(alt.get('notes', '') or '')
                    })
            
            trans.commit()
            logger.info(f"BOM created: {bom_code} (ID: {bom_id})")
            return bom_code
        
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating BOM: {e}")
            raise BOMException(f"Failed to create BOM: {str(e)}")
        finally:
            conn.close()
    
    def _generate_bom_code(self, conn, bom_type: str) -> str:
        """Generate unique BOM code"""
        today = date.today()
        prefix = f"BOM-{today.strftime('%Y%m')}-"
        
        query = text("""
            SELECT bom_code FROM bom_headers 
            WHERE bom_code LIKE :prefix
            ORDER BY bom_code DESC 
            LIMIT 1
        """)
        
        result = conn.execute(query, {'prefix': f"{prefix}%"})
        row = result.fetchone()
        
        if row:
            last_code = row[0]
            last_num = int(last_code.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        return f"{prefix}{new_num:03d}"
    
    # ==================== UPDATE Operations ====================
    
    def update_bom_status(self, bom_id: int, new_status: str, user_id: int):
        """Update BOM status"""
        try:
            bom_id = convert_to_native(bom_id)
            user_id = convert_to_native(user_id)
            
            query = text("""
                UPDATE bom_headers
                SET status = :status,
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :bom_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'bom_id': bom_id,
                    'status': str(new_status),
                    'user_id': user_id
                })
                conn.commit()
            
            logger.info(f"BOM status updated: {bom_id} -> {new_status}")
        
        except Exception as e:
            logger.error(f"Error updating BOM status: {e}")
            raise BOMException(f"Failed to update status: {str(e)}")
    
    def update_bom_header(self, bom_id: int, update_data: Dict, user_id: int):
        """Update BOM header fields"""
        try:
            bom_id = convert_to_native(bom_id)
            user_id = convert_to_native(user_id)
            
            query = text("""
                UPDATE bom_headers
                SET bom_name = :bom_name,
                    effective_date = :effective_date,
                    notes = :notes,
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :bom_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'bom_id': bom_id,
                    'bom_name': str(update_data['bom_name']),
                    'effective_date': update_data.get('effective_date'),
                    'notes': str(update_data.get('notes', '') or ''),
                    'user_id': user_id
                })
                conn.commit()
            
            logger.info(f"BOM header updated: {bom_id}")
        
        except Exception as e:
            logger.error(f"Error updating BOM header: {e}")
            raise BOMException(f"Failed to update BOM: {str(e)}")
    
    def update_bom_material(self, detail_id: int, update_data: Dict, user_id: int):
        """Update BOM material"""
        try:
            detail_id = convert_to_native(detail_id)
            
            query = text("""
                UPDATE bom_details
                SET material_type = :material_type,
                    quantity = :quantity,
                    scrap_rate = :scrap_rate
                WHERE id = :detail_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'detail_id': detail_id,
                    'material_type': str(update_data['material_type']),
                    'quantity': float(update_data['quantity']),
                    'scrap_rate': float(update_data['scrap_rate'])
                })
                conn.commit()
            
            logger.info(f"BOM material updated: {detail_id}")
        
        except Exception as e:
            logger.error(f"Error updating BOM material: {e}")
            raise BOMException(f"Failed to update BOM material: {str(e)}")
    
    def add_bom_material(self, material_data: Dict):
        """Add material to existing BOM"""
        try:
            bom_header_id = convert_to_native(material_data['bom_header_id'])
            material_id = convert_to_native(material_data['material_id'])
            
            # Check if material already exists
            check_query = """
                SELECT COUNT(*) as count
                FROM bom_details
                WHERE bom_header_id = %s
                AND material_id = %s
            """
            
            with self.engine.connect() as conn:
                result = pd.read_sql(check_query, conn, params=(bom_header_id, material_id))
                
                if result['count'].iloc[0] > 0:
                    raise BOMValidationError("Material already exists in BOM")
                
                # Get UOM from product
                uom_query = "SELECT uom FROM products WHERE id = %s"
                uom_result = pd.read_sql(uom_query, conn, params=(material_id,))
                material_uom = uom_result['uom'].iloc[0] if not uom_result.empty else 'PCS'
                
                # Insert new material
                insert_query = text("""
                    INSERT INTO bom_details (
                        bom_header_id, material_id, material_type,
                        quantity, uom, scrap_rate
                    ) VALUES (
                        :bom_header_id, :material_id, :material_type,
                        :quantity, :uom, :scrap_rate
                    )
                """)
                
                conn.execute(insert_query, {
                    'bom_header_id': bom_header_id,
                    'material_id': material_id,
                    'material_type': str(material_data['material_type']),
                    'quantity': float(material_data['quantity']),
                    'uom': str(material_uom),
                    'scrap_rate': float(material_data.get('scrap_rate', 0))
                })
                conn.commit()
            
            logger.info(f"Material added to BOM: {bom_header_id}")
        
        except Exception as e:
            logger.error(f"Error adding material to BOM: {e}")
            raise BOMException(f"Failed to add material: {str(e)}")
    
    def add_material_alternative(self, alternative_data: Dict):
        """Add alternative to BOM material"""
        try:
            bom_detail_id = convert_to_native(alternative_data['bom_detail_id'])
            alt_material_id = convert_to_native(alternative_data['alternative_material_id'])
            
            # Get UOM from product
            uom_query = "SELECT uom FROM products WHERE id = %s"
            with self.engine.connect() as conn:
                uom_result = pd.read_sql(uom_query, conn, params=(alt_material_id,))
                alt_uom = uom_result['uom'].iloc[0] if not uom_result.empty else 'PCS'
                
                # Get material type from primary material
                type_query = "SELECT material_type FROM bom_details WHERE id = %s"
                type_result = pd.read_sql(type_query, conn, params=(bom_detail_id,))
                material_type = type_result['material_type'].iloc[0] if not type_result.empty else 'RAW_MATERIAL'
                
                query = text("""
                    INSERT INTO bom_material_alternatives (
                        bom_detail_id, alternative_material_id,
                        material_type, quantity, uom, scrap_rate, 
                        priority, is_active, notes, created_date
                    ) VALUES (
                        :bom_detail_id, :alternative_material_id,
                        :material_type, :quantity, :uom, :scrap_rate,
                        :priority, :is_active, :notes, NOW()
                    )
                """)
                
                conn.execute(query, {
                    'bom_detail_id': bom_detail_id,
                    'alternative_material_id': alt_material_id,
                    'material_type': str(material_type),
                    'quantity': float(alternative_data['quantity']),
                    'uom': str(alt_uom),
                    'scrap_rate': float(alternative_data['scrap_rate']),
                    'priority': convert_to_native(alternative_data['priority']),
                    'is_active': convert_to_native(alternative_data.get('is_active', 1)),
                    'notes': str(alternative_data.get('notes', ''))
                })
                conn.commit()
            
            logger.info(f"Alternative added to material: {bom_detail_id}")
        
        except Exception as e:
            logger.error(f"Error adding alternative: {e}")
            raise BOMException(f"Failed to add alternative: {str(e)}")
    
    def update_material_alternative(self, alternative_id: int, update_data: Dict):
        """Update alternative material"""
        try:
            alternative_id = convert_to_native(alternative_id)
            
            query = text("""
                UPDATE bom_material_alternatives
                SET quantity = :quantity,
                    scrap_rate = :scrap_rate,
                    priority = :priority,
                    is_active = :is_active,
                    notes = :notes
                WHERE id = :alternative_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'alternative_id': alternative_id,
                    'quantity': float(update_data['quantity']),
                    'scrap_rate': float(update_data['scrap_rate']),
                    'priority': convert_to_native(update_data['priority']),
                    'is_active': convert_to_native(update_data.get('is_active', 1)),
                    'notes': str(update_data.get('notes', ''))
                })
                conn.commit()
            
            logger.info(f"Alternative updated: {alternative_id}")
        
        except Exception as e:
            logger.error(f"Error updating alternative: {e}")
            raise BOMException(f"Failed to update alternative: {str(e)}")
    
    # ==================== DELETE Operations ====================
    
    def delete_bom(self, bom_id: int, user_id: int):
        """Soft delete BOM"""
        try:
            bom_id = convert_to_native(bom_id)
            user_id = convert_to_native(user_id)
            
            query = text("""
                UPDATE bom_headers
                SET delete_flag = 1,
                    updated_by = :user_id,
                    updated_date = NOW()
                WHERE id = :bom_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'bom_id': bom_id,
                    'user_id': user_id
                })
                conn.commit()
            
            logger.info(f"BOM deleted: {bom_id}")
        
        except Exception as e:
            logger.error(f"Error deleting BOM: {e}")
            raise BOMException(f"Failed to delete BOM: {str(e)}")
    
    def delete_bom_material(self, detail_id: int, user_id: int):
        """Delete material from BOM (also deletes alternatives)"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            detail_id = convert_to_native(detail_id)
            
            # Delete alternatives first
            alt_query = text("""
                DELETE FROM bom_material_alternatives
                WHERE bom_detail_id = :detail_id
            """)
            conn.execute(alt_query, {'detail_id': detail_id})
            
            # Delete material
            mat_query = text("""
                DELETE FROM bom_details
                WHERE id = :detail_id
            """)
            conn.execute(mat_query, {'detail_id': detail_id})
            
            trans.commit()
            logger.info(f"Material deleted: {detail_id}")
        
        except Exception as e:
            trans.rollback()
            logger.error(f"Error deleting material: {e}")
            raise BOMException(f"Failed to delete material: {str(e)}")
        finally:
            conn.close()
    
    def delete_material_alternative(self, alternative_id: int, user_id: int):
        """Delete alternative from material"""
        try:
            alternative_id = convert_to_native(alternative_id)
            
            query = text("""
                DELETE FROM bom_material_alternatives
                WHERE id = :alternative_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {'alternative_id': alternative_id})
                conn.commit()
            
            logger.info(f"Alternative deleted: {alternative_id}")
        
        except Exception as e:
            logger.error(f"Error deleting alternative: {e}")
            raise BOMException(f"Failed to delete alternative: {str(e)}")
    
    # ==================== CLONE Operations ====================
    
    def _get_clone_materials(self, source_bom_id: int) -> List[Dict]:
        """Get materials from source BOM for cloning"""
        # Get materials
        materials_query = """
            SELECT 
                d.material_id, d.material_type, d.quantity, d.uom, d.scrap_rate
            FROM bom_details d
            WHERE d.bom_header_id = %s
        """
        materials_df = pd.read_sql(materials_query, self.engine, params=(source_bom_id,))
        
        materials = []
        for _, mat in materials_df.iterrows():
            material_data = {
                'material_id': int(mat['material_id']),
                'material_type': str(mat['material_type']),
                'quantity': float(mat['quantity']),
                'uom': str(mat['uom']),
                'scrap_rate': float(mat.get('scrap_rate', 0)),
                'alternatives': []
            }
            
            # Get alternatives for this material
            alt_query = """
                SELECT 
                    a.alternative_material_id as material_id,
                    a.material_type, a.quantity, a.uom, a.scrap_rate,
                    a.priority, a.is_active, a.notes
                FROM bom_material_alternatives a
                JOIN bom_details d ON a.bom_detail_id = d.id
                WHERE d.bom_header_id = %s AND d.material_id = %s
                ORDER BY a.priority
            """
            alts_df = pd.read_sql(alt_query, self.engine, 
                                  params=(source_bom_id, mat['material_id']))
            
            for _, alt in alts_df.iterrows():
                material_data['alternatives'].append({
                    'material_id': int(alt['material_id']),
                    'material_type': str(alt['material_type']),
                    'quantity': float(alt['quantity']),
                    'uom': str(alt['uom']),
                    'scrap_rate': float(alt.get('scrap_rate', 0)),
                    'priority': int(alt.get('priority', 1)),
                    'is_active': int(alt.get('is_active', 1)),
                    'notes': str(alt.get('notes', '') or '')
                })
            
            materials.append(material_data)
        
        return materials
    
    def clone_bom(self, source_bom_id: int, new_bom_data: Dict, 
                  materials: List[Dict] = None, user_id: int = None) -> str:
        """
        Clone existing BOM with modifications
        
        Supports two calling conventions:
        1. clone_bom(source_bom_id, new_bom_data) - materials loaded from source
        2. clone_bom(source_bom_id, new_bom_data, materials, user_id) with separate arguments
        
        Returns:
            bom_code: The generated BOM code for the new BOM
        """
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Support flexible calling conventions
            if user_id is None:
                user_id = new_bom_data.get('created_by', 1)
            
            user_id = convert_to_native(user_id)
            source_bom_id = convert_to_native(source_bom_id)
            product_id = convert_to_native(new_bom_data['product_id'])
            
            # If materials not provided, load from source BOM
            if materials is None:
                materials = self._get_clone_materials(source_bom_id)
            
            # Generate new BOM code
            bom_code = self._generate_bom_code(conn, new_bom_data['bom_type'])
            
            # Insert new header
            header_query = text("""
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id, output_qty,
                    uom, status, version, effective_date, notes,
                    created_by, created_date
                ) VALUES (
                    :bom_code, :bom_name, :bom_type, :product_id, :output_qty,
                    :uom, 'DRAFT', 1, :effective_date, :notes,
                    :created_by, NOW()
                )
            """)
            
            result = conn.execute(header_query, {
                'bom_code': bom_code,
                'bom_name': str(new_bom_data['bom_name']),
                'bom_type': str(new_bom_data['bom_type']),
                'product_id': product_id,
                'output_qty': float(new_bom_data['output_qty']),
                'uom': str(new_bom_data['uom']),
                'effective_date': new_bom_data.get('effective_date'),
                'notes': str(new_bom_data.get('notes', '') or ''),
                'created_by': user_id
            })
            
            new_bom_id = result.lastrowid
            
            # Clone materials
            for material in materials:
                material_id = convert_to_native(material['material_id'])
                
                detail_query = text("""
                    INSERT INTO bom_details (
                        bom_header_id, material_id, material_type,
                        quantity, uom, scrap_rate
                    ) VALUES (
                        :bom_header_id, :material_id, :material_type,
                        :quantity, :uom, :scrap_rate
                    )
                """)
                
                detail_result = conn.execute(detail_query, {
                    'bom_header_id': new_bom_id,
                    'material_id': material_id,
                    'material_type': str(material['material_type']),
                    'quantity': float(material['quantity']),
                    'uom': str(material['uom']),
                    'scrap_rate': float(material.get('scrap_rate', 0))
                })
                
                new_detail_id = detail_result.lastrowid
                
                # Clone alternatives
                alternatives = material.get('alternatives', [])
                for alt in alternatives:
                    # Support both 'material_id' and 'alternative_material_id' keys
                    alt_mat_id = alt.get('alternative_material_id') or alt.get('material_id')
                    alt_material_id = convert_to_native(alt_mat_id)
                    
                    alt_query = text("""
                        INSERT INTO bom_material_alternatives (
                            bom_detail_id, alternative_material_id,
                            material_type, quantity, uom, scrap_rate,
                            priority, is_active, notes, created_date
                        ) VALUES (
                            :bom_detail_id, :alternative_material_id,
                            :material_type, :quantity, :uom, :scrap_rate,
                            :priority, :is_active, :notes, NOW()
                        )
                    """)
                    
                    conn.execute(alt_query, {
                        'bom_detail_id': new_detail_id,
                        'alternative_material_id': alt_material_id,
                        'material_type': str(alt.get('material_type', material['material_type'])),
                        'quantity': float(alt['quantity']),
                        'uom': str(alt['uom']),
                        'scrap_rate': float(alt.get('scrap_rate', 0)),
                        'priority': convert_to_native(alt.get('priority', 1)),
                        'is_active': convert_to_native(alt.get('is_active', 1)),
                        'notes': str(alt.get('notes', '') or '')
                    })
            
            trans.commit()
            logger.info(f"BOM cloned: {source_bom_id} -> {new_bom_id} ({bom_code})")
            return bom_code
        
        except Exception as e:
            trans.rollback()
            logger.error(f"Error cloning BOM: {e}")
            raise BOMException(f"Failed to clone BOM: {str(e)}")
        finally:
            conn.close()