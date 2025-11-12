# utils/bom/manager.py
"""
Bill of Materials (BOM) Management - FIXED V2 FOR MYSQL
Complete CRUD operations with proper type handling for MySQL
Fixed numpy.int64 and parameter binding issues
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
                     h.effective_date, h.notes, h.created_date
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
        """Get BOM header information"""
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
            WHERE h.id = %s AND h.delete_flag = 0
            GROUP BY h.id, h.bom_code, h.bom_name, h.bom_type, 
                     h.product_id, p.name, p.pt_code, h.output_qty,
                     h.uom, h.status, h.version, h.effective_date, h.notes
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
                     AND inv.delete_flag = 0), 
                    0
                ) as current_stock,
                COUNT(DISTINCT a.id) as alternatives_count
            FROM bom_details d
            JOIN products p ON d.material_id = p.id
            LEFT JOIN bom_material_alternatives a ON a.bom_detail_id = d.id
            WHERE d.bom_header_id = %s
            GROUP BY d.id, d.material_id, p.name, p.pt_code, 
                     d.material_type, d.quantity, d.uom, d.scrap_rate
            ORDER BY d.material_type, p.pt_code
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(bom_id,))
        except Exception as e:
            logger.error(f"Error getting BOM details: {e}")
            raise BOMException(f"Failed to get BOM details: {str(e)}")
    
    def get_material_alternatives(self, detail_id: int) -> pd.DataFrame:
        """Get alternatives for a BOM material"""
        # Convert numpy types to native Python types
        detail_id = convert_to_native(detail_id)
        
        query = """
            SELECT 
                a.id,
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
                     AND inv.delete_flag = 0), 
                    0
                ) as current_stock
            FROM bom_material_alternatives a
            JOIN products p ON a.alternative_material_id = p.id
            WHERE a.bom_detail_id = %s
            ORDER BY a.priority, p.pt_code
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(detail_id,))
        except Exception as e:
            logger.error(f"Error getting material alternatives: {e}")
            return pd.DataFrame()
    
    def get_where_used(self, product_id: int) -> pd.DataFrame:
        """Get BOMs where product is used (as primary or alternative)"""
        # Convert numpy types to native Python types
        product_id = convert_to_native(product_id)
        
        query = """
            -- Primary material usage
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.status as bom_status,
                p.name as output_product_name,
                d.material_type,
                d.quantity,
                p2.uom,
                d.scrap_rate,
                'PRIMARY' as usage_type
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON h.product_id = p.id
            JOIN products p2 ON d.material_id = p2.id
            WHERE d.material_id = %s
            AND h.delete_flag = 0
            
            UNION ALL
            
            -- Alternative material usage
            SELECT 
                h.id as bom_id,
                h.bom_code,
                h.bom_name,
                h.bom_type,
                h.status as bom_status,
                p.name as output_product_name,
                d.material_type,
                a.quantity,
                p2.uom,
                a.scrap_rate,
                CONCAT('ALTERNATIVE P', a.priority) as usage_type
            FROM bom_material_alternatives a
            JOIN bom_details d ON a.bom_detail_id = d.id
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON h.product_id = p.id
            JOIN products p2 ON a.alternative_material_id = p2.id
            WHERE a.alternative_material_id = %s
            AND h.delete_flag = 0
            
            ORDER BY bom_code
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id, product_id))
        except Exception as e:
            logger.error(f"Error getting where used: {e}")
            raise BOMException(f"Failed to get where used: {str(e)}")
    
    def get_bom_complete_data(self, bom_id: int) -> Dict:
        """Get complete BOM data for cloning"""
        try:
            # Convert numpy types
            bom_id = convert_to_native(bom_id)
            
            # Get header info
            bom_info = self.get_bom_info(bom_id)
            if not bom_info:
                raise BOMNotFoundError(f"BOM with ID {bom_id} not found")
            
            # Get materials
            bom_details = self.get_bom_details(bom_id)
            
            # Build materials list with alternatives
            materials = []
            for _, detail in bom_details.iterrows():
                # Get alternatives for this material
                detail_id = convert_to_native(detail['id'])
                alternatives = self.get_material_alternatives(detail_id)
                
                alt_list = []
                for _, alt in alternatives.iterrows():
                    alt_list.append({
                        'alternative_material_id': convert_to_native(alt['material_id']),
                        'quantity': float(alt['quantity']),
                        'uom': str(alt['uom']),
                        'scrap_rate': float(alt['scrap_rate']),
                        'priority': convert_to_native(alt['priority']),
                        'is_active': convert_to_native(alt['is_active']),
                        'notes': str(alt.get('notes', ''))
                    })
                
                materials.append({
                    'material_id': convert_to_native(detail['material_id']),
                    'material_type': str(detail['material_type']),
                    'quantity': float(detail['quantity']),
                    'uom': str(detail['uom']),
                    'scrap_rate': float(detail['scrap_rate']),
                    'alternatives': alt_list
                })
            
            return {
                'header': bom_info,
                'materials': materials
            }
        
        except Exception as e:
            logger.error(f"Error getting complete BOM data: {e}")
            raise BOMException(f"Failed to get complete BOM data: {str(e)}")
    
    # ==================== CREATE Operations ====================
    
    def generate_bom_code(self) -> str:
        """Generate next BOM code with format BOM-YYYYMM-XXX"""
        try:
            current_month = datetime.now().strftime('%Y%m')
            
            # Get max code for current month
            query = """
                SELECT MAX(CAST(SUBSTRING(bom_code, 13, 3) AS UNSIGNED)) as max_seq
                FROM bom_headers
                WHERE bom_code LIKE %s
            """
            
            pattern = f'BOM-{current_month}-%'
            result = pd.read_sql(query, self.engine, params=(pattern,))
            
            max_seq = result['max_seq'].iloc[0] if not pd.isna(result['max_seq'].iloc[0]) else 0
            next_seq = int(max_seq) + 1
            
            return f"BOM-{current_month}-{next_seq:03d}"
        
        except Exception as e:
            logger.error(f"Error generating BOM code: {e}")
            # Fallback to timestamp-based code
            return f"BOM-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    def create_bom(self, bom_data: Dict) -> str:
        """Create new BOM with materials and alternatives"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Generate BOM code
            bom_code = self.generate_bom_code()
            
            # Convert all numpy types in bom_data
            product_id = convert_to_native(bom_data['product_id'])
            output_qty = float(bom_data['output_qty'])
            created_by = convert_to_native(bom_data['created_by'])
            
            # Insert BOM header
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
                'bom_name': str(bom_data['bom_name']),
                'bom_type': str(bom_data['bom_type']),
                'product_id': product_id,
                'output_qty': output_qty,
                'uom': str(bom_data['uom']),
                'effective_date': bom_data.get('effective_date', date.today()),
                'notes': str(bom_data.get('notes', '')),
                'created_by': created_by
            })
            
            bom_id = result.lastrowid
            
            # Insert materials and alternatives
            for material in bom_data['materials']:
                material_id = convert_to_native(material['material_id'])
                
                # Get UOM from product
                uom_query = "SELECT uom FROM products WHERE id = %s"
                uom_result = pd.read_sql(uom_query, self.engine, params=(material_id,))
                material_uom = uom_result['uom'].iloc[0] if not uom_result.empty else material.get('uom', 'PCS')
                
                # Insert material
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
                for alt in material.get('alternatives', []):
                    alt_material_id = convert_to_native(alt['alternative_material_id'])
                    
                    # Get UOM for alternative
                    alt_uom_result = pd.read_sql(uom_query, self.engine, params=(alt_material_id,))
                    alt_uom = alt_uom_result['uom'].iloc[0] if not alt_uom_result.empty else alt.get('uom', 'PCS')
                    
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
                        'is_active': convert_to_native(alt.get('is_active', 1)),
                        'notes': str(alt.get('notes', ''))
                    })
            
            trans.commit()
            logger.info(f"BOM created successfully: {bom_code}")
            return bom_code
        
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating BOM: {e}")
            raise BOMException(f"Failed to create BOM: {str(e)}")
        finally:
            conn.close()
    
    def clone_bom(self, source_bom_id: int, clone_data: Dict) -> str:
        """Clone existing BOM with new header information"""
        try:
            # Convert numpy types
            source_bom_id = convert_to_native(source_bom_id)
            
            # Get complete source BOM data
            source_data = self.get_bom_complete_data(source_bom_id)
            
            # Prepare new BOM data
            new_bom_data = {
                'bom_name': str(clone_data.get('bom_name', f"{source_data['header']['bom_name']} - Copy")),
                'bom_type': str(clone_data.get('bom_type', source_data['header']['bom_type'])),
                'product_id': convert_to_native(clone_data.get('product_id', source_data['header']['product_id'])),
                'output_qty': float(clone_data.get('output_qty', source_data['header']['output_qty'])),
                'uom': str(clone_data.get('uom', source_data['header']['uom'])),
                'effective_date': clone_data.get('effective_date', date.today()),
                'notes': str(clone_data.get('notes', f"Cloned from {source_data['header']['bom_code']}")),
                'materials': source_data['materials'],
                'created_by': convert_to_native(clone_data['created_by'])
            }
            
            # Create the new BOM
            new_bom_code = self.create_bom(new_bom_data)
            
            logger.info(f"BOM cloned successfully: {source_data['header']['bom_code']} → {new_bom_code}")
            return new_bom_code
        
        except Exception as e:
            logger.error(f"Error cloning BOM: {e}")
            raise BOMException(f"Failed to clone BOM: {str(e)}")
    
    # ==================== UPDATE Operations ====================
    
    def update_bom_header(self, bom_id: int, update_data: Dict):
        """Update BOM header information"""
        try:
            bom_id = convert_to_native(bom_id)
            
            query = text("""
                UPDATE bom_headers
                SET bom_name = :bom_name,
                    output_qty = :output_qty,
                    effective_date = :effective_date,
                    notes = :notes,
                    updated_by = :updated_by,
                    updated_date = NOW()
                WHERE id = :bom_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'bom_id': bom_id,
                    'bom_name': str(update_data['bom_name']),
                    'output_qty': float(update_data['output_qty']),
                    'effective_date': update_data['effective_date'],
                    'notes': str(update_data.get('notes', '')),
                    'updated_by': convert_to_native(update_data['updated_by'])
                })
                conn.commit()
            
            logger.info(f"BOM header updated: {bom_id}")
        
        except Exception as e:
            logger.error(f"Error updating BOM header: {e}")
            raise BOMException(f"Failed to update BOM header: {str(e)}")
    
    def update_bom_status(self, bom_id: int, new_status: str, user_id: int):
        """Update BOM status"""
        try:
            bom_id = convert_to_native(bom_id)
            user_id = convert_to_native(user_id)
            
            query = text("""
                UPDATE bom_headers
                SET status = :status,
                    updated_by = :updated_by,
                    updated_date = NOW()
                WHERE id = :bom_id
            """)
            
            with self.engine.connect() as conn:
                conn.execute(query, {
                    'bom_id': bom_id,
                    'status': str(new_status),
                    'updated_by': user_id
                })
                conn.commit()
            
            logger.info(f"BOM status updated: {bom_id} → {new_status}")
        
        except Exception as e:
            logger.error(f"Error updating BOM status: {e}")
            raise BOMException(f"Failed to update BOM status: {str(e)}")
    
    def update_bom_material(self, detail_id: int, update_data: Dict):
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