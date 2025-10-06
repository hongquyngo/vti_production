# modules/bom.py - Enhanced Bill of Materials Management
import pandas as pd
from datetime import datetime, date
from utils.db import get_db_engine
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class BOMManager:
    """Enhanced Bill of Materials Management"""
    
    def __init__(self):
        self.engine = get_db_engine()
        # Configuration - embedded directly
        self.config = {
            'auto_activate_first': False,
            'max_scrap_rate': 50.0,
            'allow_duplicate_materials': False,
            'material_types': ['RAW_MATERIAL', 'PACKAGING', 'CONSUMABLE', 'SEMI_FINISHED'],
            'default_material_type': 'RAW_MATERIAL'
        }
    
    def validate_bom_data(self, bom_data):
        """Validate BOM data before creation"""
        errors = []
        
        # Required fields
        required_fields = ['bom_name', 'bom_type', 'product_id', 'output_qty', 'uom']
        for field in required_fields:
            if field not in bom_data or not bom_data[field]:
                errors.append(f"{field} is required")
        
        # Output quantity validation
        if 'output_qty' in bom_data:
            qty = bom_data.get('output_qty', 0)
            if not isinstance(qty, (int, float)) or qty <= 0:
                errors.append("Output quantity must be greater than 0")
        
        # BOM type validation
        valid_types = ['KITTING', 'CUTTING', 'REPACKING']
        if bom_data.get('bom_type') not in valid_types:
            errors.append(f"Invalid BOM type. Must be one of: {', '.join(valid_types)}")
        
        # Materials validation
        materials = bom_data.get('materials', [])
        if not materials:
            errors.append("At least one material is required")
        else:
            material_ids = set()
            for idx, mat in enumerate(materials):
                # Check required fields
                if not mat.get('material_id'):
                    errors.append(f"Material {idx+1}: material_id is required")
                
                if not mat.get('quantity') or mat['quantity'] <= 0:
                    errors.append(f"Material {idx+1}: quantity must be greater than 0")
                
                # Check scrap rate
                scrap = mat.get('scrap_rate', 0)
                if scrap < 0 or scrap > self.config['max_scrap_rate']:
                    errors.append(
                        f"Material {idx+1}: scrap rate must be between 0 and {self.config['max_scrap_rate']}%"
                    )
                
                # Check duplicates
                mat_id = mat.get('material_id')
                if mat_id in material_ids and not self.config['allow_duplicate_materials']:
                    errors.append(f"Material {idx+1}: duplicate material not allowed")
                material_ids.add(mat_id)
        
        return len(errors) == 0, errors
    
    def get_boms(self, bom_type=None, status=None, search=None, product_id=None):
        """Get BOMs with comprehensive filters"""
        query = """
        SELECT 
            h.id,
            h.bom_code,
            h.bom_name,
            h.bom_type,
            h.status,
            h.version,
            h.output_qty,
            h.uom,
            h.effective_date,
            h.expiry_date,
            h.notes,
            p.name as product_name,
            p.pt_code as product_code,
            p.id as product_id,
            u.username as created_by_name,
            h.created_date,
            h.updated_date,
            -- Calculate material count
            (SELECT COUNT(*) FROM bom_details d WHERE d.bom_header_id = h.id) as material_count,
            -- Check if in use
            (SELECT COUNT(*) FROM manufacturing_orders mo 
             WHERE mo.bom_header_id = h.id AND mo.delete_flag = 0) as usage_count
        FROM bom_headers h
        JOIN products p ON h.product_id = p.id
        LEFT JOIN users u ON h.created_by = u.id
        WHERE h.delete_flag = 0
        """
        
        params = []
        
        if bom_type:
            query += " AND h.bom_type = %s"
            params.append(bom_type)
        
        if status:
            query += " AND h.status = %s"
            params.append(status)
        
        if product_id:
            query += " AND h.product_id = %s"
            params.append(product_id)
        
        if search:
            query += """ AND (h.bom_code LIKE %s 
                        OR h.bom_name LIKE %s 
                        OR p.name LIKE %s
                        OR p.pt_code LIKE %s)"""
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 4)
        
        query += " ORDER BY h.created_date DESC"
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params) if params else None)
        except Exception as e:
            logger.error(f"Error getting BOMs: {e}")
            return pd.DataFrame()
    
    def get_active_boms(self, bom_type=None):
        """Get only active BOMs for production"""
        return self.get_boms(bom_type=bom_type, status='ACTIVE')
    
    def get_bom_info(self, bom_id):
        """Get comprehensive BOM information"""
        query = """
        SELECT 
            h.*,
            p.name as product_name,
            p.pt_code as product_code,
            p.uom as product_uom,
            u1.username as created_by_name,
            u2.username as updated_by_name,
            -- Usage statistics
            (SELECT COUNT(*) FROM manufacturing_orders mo 
             WHERE mo.bom_header_id = h.id AND mo.delete_flag = 0) as total_usage,
            (SELECT COUNT(*) FROM manufacturing_orders mo 
             WHERE mo.bom_header_id = h.id 
             AND mo.status = 'IN_PROGRESS' 
             AND mo.delete_flag = 0) as active_orders
        FROM bom_headers h
        JOIN products p ON h.product_id = p.id
        LEFT JOIN users u1 ON h.created_by = u1.id
        LEFT JOIN users u2 ON h.updated_by = u2.id
        WHERE h.id = %s AND h.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(bom_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting BOM info: {e}")
            return None
    
    def get_bom_details(self, bom_id):
        """Get BOM materials with enhanced information"""
        query = """
        SELECT 
            d.id,
            d.material_id,
            d.material_type,
            d.quantity,
            d.uom,
            d.scrap_rate,
            d.notes as material_notes,
            p.name as material_name,
            p.pt_code as material_code,
            p.package_size,
            -- Calculate with scrap
            d.quantity * (1 + d.scrap_rate/100) as total_qty_with_scrap,
            -- Get current stock
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
    
    def create_bom(self, bom_data):
        """Create new BOM with validation"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Validate inputs using embedded validation
            is_valid, errors = self.validate_bom_data(bom_data)
            if not is_valid:
                raise ValueError("; ".join(errors))
            
            # Check for duplicate active BOMs
            if self._check_duplicate_active_bom(conn, bom_data):
                raise ValueError("An active BOM already exists for this product and type")
            
            # Generate BOM code
            bom_code = self._generate_bom_code(bom_data['bom_type'])
            
            # Insert BOM header
            header_query = text("""
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id, 
                    output_qty, uom, status, version, 
                    effective_date, expiry_date, notes, 
                    created_by, created_date
                ) VALUES (
                    :bom_code, :bom_name, :bom_type, :product_id,
                    :output_qty, :uom, :status, :version,
                    :effective_date, :expiry_date, :notes,
                    :created_by, NOW()
                )
            """)
            
            result = conn.execute(header_query, {
                'bom_code': bom_code,
                'bom_name': bom_data['bom_name'],
                'bom_type': bom_data['bom_type'],
                'product_id': bom_data['product_id'],
                'output_qty': bom_data['output_qty'],
                'uom': bom_data['uom'],
                'status': 'DRAFT',  # Always start as DRAFT
                'version': 1,
                'effective_date': bom_data.get('effective_date', date.today()),
                'expiry_date': bom_data.get('expiry_date'),
                'notes': bom_data.get('notes', ''),
                'created_by': bom_data['created_by']
            })
            
            bom_id = result.lastrowid
            
            # Insert BOM details
            if bom_data.get('materials'):
                self._insert_bom_materials(conn, bom_id, bom_data['materials'])
            
            trans.commit()
            logger.info(f"Created BOM {bom_code}")
            return bom_code
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating BOM: {e}")
            raise
        finally:
            conn.close()
    
    def _check_duplicate_active_bom(self, conn, bom_data):
        """Check if active BOM already exists"""
        query = text("""
            SELECT COUNT(*) as count
            FROM bom_headers
            WHERE product_id = :product_id
            AND bom_type = :bom_type
            AND status = 'ACTIVE'
            AND delete_flag = 0
        """)
        
        result = conn.execute(query, {
            'product_id': bom_data['product_id'],
            'bom_type': bom_data['bom_type']
        })
        
        return result.fetchone()[0] > 0
    
    def _insert_bom_materials(self, conn, bom_id, materials):
        """Insert BOM materials"""
        detail_query = text("""
            INSERT INTO bom_details (
                bom_header_id, material_id, material_type, 
                quantity, uom, scrap_rate, notes
            ) VALUES (
                :bom_header_id, :material_id, :material_type,
                :quantity, :uom, :scrap_rate, :notes
            )
        """)
        
        for material in materials:
            # Use default material type if not specified
            material_type = material.get('material_type', self.config['default_material_type'])
            
            # Validate material type
            if material_type not in self.config['material_types']:
                material_type = self.config['default_material_type']
            
            conn.execute(detail_query, {
                'bom_header_id': bom_id,
                'material_id': material['material_id'],
                'material_type': material_type,
                'quantity': material['quantity'],
                'uom': material['uom'],
                'scrap_rate': material.get('scrap_rate', 0),
                'notes': material.get('notes', '')
            })
    
    def update_bom(self, bom_id, update_data, updated_by):
        """Update BOM header information"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Build dynamic update query
            update_fields = []
            params = {'bom_id': bom_id, 'updated_by': updated_by}
            
            allowed_fields = ['bom_name', 'output_qty', 'uom', 'effective_date', 
                            'expiry_date', 'notes']
            
            for field in allowed_fields:
                if field in update_data:
                    update_fields.append(f"{field} = :{field}")
                    params[field] = update_data[field]
            
            if not update_fields:
                raise ValueError("No fields to update")
            
            query = text(f"""
                UPDATE bom_headers 
                SET {', '.join(update_fields)},
                    updated_by = :updated_by,
                    updated_date = NOW()
                WHERE id = :bom_id
                AND delete_flag = 0
            """)
            
            result = conn.execute(query, params)
            
            if result.rowcount == 0:
                raise ValueError("BOM not found or already deleted")
            
            trans.commit()
            logger.info(f"Updated BOM {bom_id}")
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error updating BOM: {e}")
            raise
        finally:
            conn.close()
    
    def update_bom_status(self, bom_id, new_status, updated_by):
        """Update BOM status with validation"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Get current BOM info
            current = self.get_bom_info(bom_id)
            if not current:
                raise ValueError("BOM not found")
            
            # Validate status transition
            valid_transitions = {
                'DRAFT': ['ACTIVE', 'INACTIVE'],
                'ACTIVE': ['INACTIVE'],
                'INACTIVE': ['ACTIVE', 'DRAFT']
            }
            
            if new_status not in valid_transitions.get(current['status'], []):
                raise ValueError(
                    f"Invalid status transition from {current['status']} to {new_status}"
                )
            
            # Check if making active
            if new_status == 'ACTIVE':
                # Deactivate other active BOMs for same product/type
                deactivate_query = text("""
                    UPDATE bom_headers
                    SET status = 'INACTIVE',
                        updated_by = :updated_by,
                        updated_date = NOW()
                    WHERE product_id = :product_id
                    AND bom_type = :bom_type
                    AND status = 'ACTIVE'
                    AND id != :bom_id
                    AND delete_flag = 0
                """)
                
                conn.execute(deactivate_query, {
                    'product_id': current['product_id'],
                    'bom_type': current['bom_type'],
                    'bom_id': bom_id,
                    'updated_by': updated_by
                })
            
            # Update status
            update_query = text("""
                UPDATE bom_headers 
                SET status = :status, 
                    updated_by = :updated_by,
                    updated_date = NOW()
                WHERE id = :bom_id
                AND delete_flag = 0
            """)
            
            conn.execute(update_query, {
                'status': new_status,
                'updated_by': updated_by,
                'bom_id': bom_id
            })
            
            trans.commit()
            logger.info(f"Updated BOM {bom_id} status to {new_status}")
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error updating BOM status: {e}")
            raise
        finally:
            conn.close()
    
    def create_new_version(self, bom_id, created_by):
        """Create new version of existing BOM"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Get current BOM
            current = self.get_bom_info(bom_id)
            if not current:
                raise ValueError("BOM not found")
            
            # Get current materials
            materials = self.get_bom_details(bom_id)
            
            # Generate new BOM code
            new_code = self._generate_bom_code(current['bom_type'])
            new_version = current['version'] + 1
            
            # Create new BOM header
            header_query = text("""
                INSERT INTO bom_headers (
                    bom_code, bom_name, bom_type, product_id,
                    output_qty, uom, status, version,
                    effective_date, notes, created_by, created_date,
                    parent_bom_id
                ) VALUES (
                    :bom_code, :bom_name, :bom_type, :product_id,
                    :output_qty, :uom, 'DRAFT', :version,
                    :effective_date, :notes, :created_by, NOW(),
                    :parent_id
                )
            """)
            
            result = conn.execute(header_query, {
                'bom_code': new_code,
                'bom_name': f"{current['bom_name']} v{new_version}",
                'bom_type': current['bom_type'],
                'product_id': current['product_id'],
                'output_qty': current['output_qty'],
                'uom': current['uom'],
                'version': new_version,
                'effective_date': date.today(),
                'notes': f"Version {new_version} created from {current['bom_code']}",
                'created_by': created_by,
                'parent_id': bom_id
            })
            
            new_bom_id = result.lastrowid
            
            # Copy materials
            if not materials.empty:
                material_list = []
                for _, mat in materials.iterrows():
                    material_list.append({
                        'material_id': mat['material_id'],
                        'material_type': mat['material_type'],
                        'quantity': mat['quantity'],
                        'uom': mat['uom'],
                        'scrap_rate': mat['scrap_rate'],
                        'notes': mat.get('material_notes', '')
                    })
                
                self._insert_bom_materials(conn, new_bom_id, material_list)
            
            trans.commit()
            logger.info(f"Created new BOM version {new_code} from {current['bom_code']}")
            return new_code
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating new BOM version: {e}")
            raise
        finally:
            conn.close()
    
    def delete_bom(self, bom_id, deleted_by):
        """Soft delete BOM"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Check if BOM is in use
            usage_query = text("""
                SELECT COUNT(*) as count
                FROM manufacturing_orders
                WHERE bom_header_id = :bom_id
                AND delete_flag = 0
            """)
            
            result = conn.execute(usage_query, {'bom_id': bom_id})
            if result.fetchone()[0] > 0:
                raise ValueError("Cannot delete BOM that is in use")
            
            # Soft delete
            delete_query = text("""
                UPDATE bom_headers
                SET delete_flag = 1,
                    deleted_by = :deleted_by,
                    deleted_date = NOW()
                WHERE id = :bom_id
            """)
            
            conn.execute(delete_query, {
                'bom_id': bom_id,
                'deleted_by': deleted_by
            })
            
            trans.commit()
            logger.info(f"Deleted BOM {bom_id}")
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error deleting BOM: {e}")
            raise
        finally:
            conn.close()
    
    def get_material_usage_summary(self):
        """Get material usage across all BOMs"""
        query = """
        SELECT 
            p.id as material_id,
            p.name as material_name,
            p.pt_code as material_code,
            p.uom,
            COUNT(DISTINCT d.bom_header_id) as usage_count,
            SUM(d.quantity) as total_base_quantity,
            AVG(d.scrap_rate) as avg_scrap_rate,
            GROUP_CONCAT(DISTINCT h.bom_type) as bom_types,
            -- Get active BOM count
            SUM(CASE WHEN h.status = 'ACTIVE' THEN 1 ELSE 0 END) as active_bom_count
        FROM bom_details d
        JOIN products p ON d.material_id = p.id
        JOIN bom_headers h ON d.bom_header_id = h.id
        WHERE h.delete_flag = 0
        GROUP BY p.id, p.name, p.pt_code, p.uom
        ORDER BY usage_count DESC, total_base_quantity DESC
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting material usage summary: {e}")
            return pd.DataFrame()
    
    def get_where_used(self, product_id):
        """Find where a product/material is used"""
        query = """
        SELECT 
            h.id as bom_id,
            h.bom_code,
            h.bom_name,
            h.bom_type,
            h.status as bom_status,
            h.version,
            p.name as output_product_name,
            p.pt_code as output_product_code,
            d.quantity,
            d.uom,
            d.scrap_rate,
            d.material_type,
            -- Calculate total requirement with scrap
            d.quantity * (1 + d.scrap_rate/100) as total_requirement,
            -- Check if currently in production
            (SELECT COUNT(*) FROM manufacturing_orders mo 
             WHERE mo.bom_header_id = h.id 
             AND mo.status IN ('CONFIRMED', 'IN_PROGRESS')
             AND mo.delete_flag = 0) as active_orders
        FROM bom_details d
        JOIN bom_headers h ON d.bom_header_id = h.id
        JOIN products p ON h.product_id = p.id
        WHERE d.material_id = %s
        AND h.delete_flag = 0
        ORDER BY h.status DESC, h.bom_type, h.bom_name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id,))
        except Exception as e:
            logger.error(f"Error getting where used: {e}")
            return pd.DataFrame()
    
    def calculate_bom_cost(self, bom_id, include_labor=False):
        """Calculate BOM cost (placeholder for future implementation)"""
        # TODO: Implement when cost tables are available
        logger.info(f"BOM cost calculation not yet implemented for BOM {bom_id}")
        return {
            'material_cost': 0,
            'labor_cost': 0,
            'overhead_cost': 0,
            'total_cost': 0,
            'cost_per_unit': 0
        }
    
    def validate_bom_materials(self, bom_id):
        """Validate BOM materials availability"""
        materials = self.get_bom_details(bom_id)
        
        if materials.empty:
            return {
                'valid': False,
                'errors': ['No materials defined for BOM']
            }
        
        errors = []
        warnings = []
        
        for _, mat in materials.iterrows():
            # Check if material exists and is active
            if mat['current_stock'] <= 0:
                warnings.append(f"{mat['material_name']}: No stock available")
            
            # Check for circular reference
            if self._check_circular_reference(bom_id, mat['material_id']):
                errors.append(f"{mat['material_name']}: Circular reference detected")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    def _check_circular_reference(self, bom_id, material_id):
        """Check for circular BOM references"""
        # Get BOM info
        bom_info = self.get_bom_info(bom_id)
        if not bom_info:
            return False
        
        # If material is same as BOM output, it's circular
        if material_id == bom_info['product_id']:
            return True
        
        # Check if material has its own BOM that references this product
        # TODO: Implement recursive check
        return False
    
    def _generate_bom_code(self, bom_type):
        """Generate unique BOM code with date"""
        prefix = f"BOM-{bom_type[:3]}"
        date_str = datetime.now().strftime('%Y%m')
        
        # Get latest number for this month
        query = """
        SELECT MAX(CAST(SUBSTRING_INDEX(bom_code, '-', -1) AS UNSIGNED)) as max_num
        FROM bom_headers
        WHERE bom_code LIKE %s
        """
        
        pattern = f"{prefix}-{date_str}-%"
        
        try:
            result = pd.read_sql(query, self.engine, params=(pattern,))
            max_num = result['max_num'].iloc[0] if not result.empty and result['max_num'].iloc[0] else 0
            new_num = (max_num or 0) + 1
            
            return f"{prefix}-{date_str}-{new_num:03d}"
            
        except Exception as e:
            logger.error(f"Error generating BOM code: {e}")
            # Fallback to timestamp
            return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}"