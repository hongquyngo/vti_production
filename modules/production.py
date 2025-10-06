# modules/production.py - Enhanced Production Order Management
import pandas as pd
from datetime import datetime, date
from utils.db import get_db_engine
from sqlalchemy import text
import uuid
import logging

logger = logging.getLogger(__name__)


class ProductionManager:
    """Enhanced Production Order Management"""
    
    def __init__(self):
        self.engine = get_db_engine()
        # Configuration - embedded directly
        self.config = {
            'over_production_tolerance': 1.1,  # 10% tolerance
            'allow_expired_materials': False,
            'auto_confirm_orders': False,
            'require_material_check': True,
            'allow_partial_completion': True,
            'default_priority': 'NORMAL'
        }
        self._keycloak_cache = {}  # Cache keycloak_id

    def get_keycloak_id_cached(self, user_id):
        """Get keycloak_id with caching"""
        if user_id not in self._keycloak_cache:
            self._keycloak_cache[user_id] = self.get_keycloak_id(user_id)
        return self._keycloak_cache[user_id]

    def get_keycloak_id(self, user_id):
        """Get keycloak_id from user_id"""
        query = text("""
            SELECT e.keycloak_id 
            FROM users u
            JOIN employees e ON u.employee_id = e.id
            WHERE u.id = :user_id
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'user_id': user_id}).fetchone()
            return result[0] if result else None

    def validate_production_order(self, order_data):
        """Validate production order data"""
        errors = []
        
        # Required fields
        required_fields = [
            'bom_header_id', 'product_id', 'planned_qty', 
            'warehouse_id', 'target_warehouse_id', 'scheduled_date'
        ]
        
        for field in required_fields:
            if field not in order_data or not order_data[field]:
                errors.append(f"{field} is required")
        
        # Quantity validation
        if 'planned_qty' in order_data:
            qty = order_data['planned_qty']
            if not isinstance(qty, (int, float)) or qty <= 0:
                errors.append("Planned quantity must be greater than 0")
        
        return len(errors) == 0, errors
    
    def validate_material_issue(self, materials, warehouse_id):
        """Validate materials can be issued"""
        errors = []
        
        for _, mat in materials.iterrows():
            remaining_qty = mat['required_qty'] - mat.get('issued_qty', 0)
            if remaining_qty > 0:
                # Check stock using inventory manager
                from modules.inventory import InventoryManager
                inv_manager = InventoryManager()
                stock = inv_manager.get_stock_balance(mat['material_id'], warehouse_id)
                
                if stock < remaining_qty:
                    errors.append(
                        f"{mat['material_name']}: Insufficient stock "
                        f"(need {remaining_qty:.2f}, have {stock:.2f})"
                    )
        
        return len(errors) == 0, errors
    
    def validate_production_completion(self, order_info, produced_qty, batch_no):
        """Validate production completion"""
        errors = []
        
        # Status check
        if order_info.get('status') != 'IN_PROGRESS':
            errors.append(f"Cannot complete order in {order_info.get('status')} status")
        
        # Quantity validation
        if produced_qty <= 0:
            errors.append("Produced quantity must be greater than 0")
        
        planned = order_info.get('planned_qty', 0)
        max_allowed = planned * self.config['over_production_tolerance']
        
        if produced_qty > max_allowed:
            tolerance_pct = (self.config['over_production_tolerance'] - 1) * 100
            errors.append(
                f"Produced quantity {produced_qty} exceeds maximum allowed "
                f"{max_allowed:.2f} (with {tolerance_pct:.0f}% tolerance)"
            )
        
        # Batch number validation
        if not batch_no or not batch_no.strip():
            errors.append("Batch number is required")
        elif len(batch_no) > 50:
            errors.append("Batch number too long (max 50 characters)")
        
        return len(errors) == 0, errors
    
    def get_orders(self, status=None, order_type=None, from_date=None, to_date=None):
        """Get production orders with enhanced filters"""
        query = """
        SELECT 
            o.id,
            o.order_no,
            o.order_date,
            o.scheduled_date,
            o.completion_date,
            o.status,
            o.priority,
            o.planned_qty,
            o.produced_qty,
            o.uom,
            p.name as product_name,
            p.pt_code as product_code,
            b.bom_type,
            b.bom_code,
            b.bom_name,
            w1.name as warehouse_name,
            w2.name as target_warehouse_name
        FROM manufacturing_orders o
        JOIN products p ON o.product_id = p.id
        JOIN bom_headers b ON o.bom_header_id = b.id
        JOIN warehouses w1 ON o.warehouse_id = w1.id
        JOIN warehouses w2 ON o.target_warehouse_id = w2.id
        WHERE o.delete_flag = 0
        """
        
        params = []
        
        if status:
            query += " AND o.status = %s"
            params.append(status)
        
        if order_type:
            query += " AND b.bom_type = %s"
            params.append(order_type)
        
        if from_date:
            query += " AND o.order_date >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND o.order_date <= %s"
            params.append(to_date)
        
        query += " ORDER BY o.created_date DESC"
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params) if params else None)
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return pd.DataFrame()
    
    def get_order_details(self, order_id):
        """Get comprehensive order details"""
        query = """
        SELECT 
            o.*,
            p.name as product_name,
            p.pt_code as product_code,
            b.bom_code,
            b.bom_name,
            b.bom_type,
            b.output_qty as bom_output_qty,
            w1.name as warehouse_name,
            w2.name as target_warehouse_name,
            w1.id as warehouse_id,
            w2.id as target_warehouse_id
        FROM manufacturing_orders o
        JOIN products p ON o.product_id = p.id
        JOIN bom_headers b ON o.bom_header_id = b.id
        JOIN warehouses w1 ON o.warehouse_id = w1.id
        JOIN warehouses w2 ON o.target_warehouse_id = w2.id
        WHERE o.id = %s AND o.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting order details: {e}")
            return None
    
    def get_order_materials(self, order_id):
        """Get materials for order with issued/returned status"""
        query = """
        SELECT 
            m.id,
            m.material_id,
            m.required_qty,
            m.issued_qty,
            m.uom,
            m.status,
            p.name as material_name,
            p.pt_code as material_code,
            COALESCE(returns.returned_qty, 0) as returned_qty
        FROM manufacturing_order_materials m
        JOIN products p ON m.material_id = p.id
        LEFT JOIN (
            SELECT 
                mrd.material_id,
                SUM(mrd.quantity) as returned_qty
            FROM material_return_details mrd
            JOIN material_returns mr ON mr.id = mrd.material_return_id
            WHERE mr.manufacturing_order_id = %s
            AND mr.status = 'CONFIRMED'
            GROUP BY mrd.material_id
        ) returns ON returns.material_id = m.material_id
        WHERE m.manufacturing_order_id = %s
        ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id, order_id))
        except Exception as e:
            logger.error(f"Error getting order materials: {e}")
            return pd.DataFrame()
    
    def get_order_material_summary(self, order_id):
        """Get material usage summary with efficiency"""
        materials = self.get_order_materials(order_id)
        if not materials.empty:
            # Calculate actual used
            materials['actual_used_qty'] = materials['issued_qty'] - materials['returned_qty']
            return materials
        return materials
    
    def calculate_material_requirements(self, bom_id, quantity):
        """Calculate material requirements based on BOM"""
        query = """
        SELECT 
            d.material_id,
            p.name as material_name,
            p.pt_code as material_code,
            h.output_qty as bom_output_qty,
            d.quantity as base_qty,
            d.scrap_rate,
            d.uom,
            d.material_type,
            -- Calculate required quantity
            CEILING((%(quantity)s / h.output_qty) * d.quantity * (1 + d.scrap_rate/100)) as required_qty
        FROM bom_details d
        JOIN products p ON d.material_id = p.id
        JOIN bom_headers h ON d.bom_header_id = h.id
        WHERE d.bom_header_id = %(bom_id)s
        AND h.output_qty > 0
        ORDER BY d.material_type, p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params={
                'quantity': quantity,
                'bom_id': bom_id
            })
        except Exception as e:
            logger.error(f"Error calculating requirements: {e}")
            return pd.DataFrame()
    
    def create_order(self, order_data):
        """Create production order with validation"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Validate inputs using embedded validation
            is_valid, errors = self.validate_production_order(order_data)
            if not is_valid:
                raise ValueError("; ".join(errors))
            
            # Generate order number
            order_no = self._generate_order_number()
            
            # Get entity_id from warehouse
            entity_query = text("""
                SELECT company_id FROM warehouses WHERE id = :warehouse_id
            """)
            result = conn.execute(entity_query, {'warehouse_id': order_data['warehouse_id']})
            entity_id = result.fetchone()[0] if result.rowcount > 0 else None
            
            # Insert manufacturing order
            order_query = text("""
                INSERT INTO manufacturing_orders (
                    entity_id, order_no, order_date, bom_header_id, 
                    product_id, planned_qty, uom, warehouse_id, 
                    target_warehouse_id, scheduled_date, status, 
                    priority, notes, created_by, created_date
                ) VALUES (
                    :entity_id, :order_no, CURDATE(), :bom_header_id,
                    :product_id, :planned_qty, :uom, :warehouse_id,
                    :target_warehouse_id, :scheduled_date, :status,
                    :priority, :notes, :created_by, NOW()
                )
            """)
            
            status = 'CONFIRMED' if self.config['auto_confirm_orders'] else 'DRAFT'
            
            result = conn.execute(order_query, {
                'entity_id': entity_id,
                'order_no': order_no,
                'bom_header_id': order_data['bom_header_id'],
                'product_id': order_data['product_id'],
                'planned_qty': order_data['planned_qty'],
                'uom': order_data['uom'],
                'warehouse_id': order_data['warehouse_id'],
                'target_warehouse_id': order_data['target_warehouse_id'],
                'scheduled_date': order_data['scheduled_date'],
                'status': status,
                'priority': order_data.get('priority', self.config['default_priority']),
                'notes': order_data.get('notes', ''),
                'created_by': order_data['created_by']
            })
            
            order_id = result.lastrowid
            
            # Auto-calculate and insert material requirements
            self._create_material_requirements(conn, order_id, order_data)
            
            trans.commit()
            logger.info(f"Created production order {order_no}")
            return order_no
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating order: {e}")
            raise
        finally:
            conn.close()
    
    def _create_material_requirements(self, conn, order_id, order_data):
        """Create material requirements for order"""
        materials_query = text("""
            INSERT INTO manufacturing_order_materials (
                manufacturing_order_id, material_id, required_qty, 
                uom, warehouse_id, status
            )
            SELECT 
                :order_id,
                d.material_id,
                CEILING((:planned_qty / h.output_qty) * d.quantity * (1 + d.scrap_rate/100)),
                d.uom,
                :warehouse_id,
                'PENDING'
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            WHERE d.bom_header_id = :bom_id
            AND h.output_qty > 0
        """)
        
        conn.execute(materials_query, {
            'order_id': order_id,
            'planned_qty': order_data['planned_qty'],
            'warehouse_id': order_data['warehouse_id'],
            'bom_id': order_data['bom_header_id']
        })
    
    def issue_materials(self, order_id, user_id):
        """Issue materials with FEFO and validation"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Validate order status
            order = self.get_order_details(order_id)
            if not order:
                raise ValueError("Order not found")
            
            if order['status'] not in ['CONFIRMED', 'DRAFT']:
                raise ValueError(f"Cannot issue materials for order in {order['status']} status")
            
            # Generate issue number and group ID
            issue_no = self._generate_issue_number()
            group_id = str(uuid.uuid4())
            
            # Create material issue header
            issue_query = text("""
                INSERT INTO material_issues (
                    issue_no, manufacturing_order_id, issue_date, 
                    warehouse_id, status, issued_by, created_by, 
                    group_id, created_date
                ) VALUES (
                    :issue_no, :order_id, NOW(), :warehouse_id,
                    'CONFIRMED', :user_id, :user_id, :group_id, NOW()
                )
            """)
            
            result = conn.execute(issue_query, {
                'issue_no': issue_no,
                'order_id': order_id,
                'warehouse_id': order['warehouse_id'],
                'user_id': user_id,
                'group_id': group_id
            })
            
            issue_id = result.lastrowid
            
            # Get materials to issue
            materials = self.get_order_materials(order_id)
            issue_details = []
            
            for _, mat in materials.iterrows():
                remaining_qty = mat['required_qty'] - mat['issued_qty']
                if remaining_qty > 0:
                    # Issue using FEFO
                    issued_qty = self._issue_material_fefo(
                        conn, issue_id, order_id, mat, remaining_qty, 
                        order['warehouse_id'], group_id, user_id
                    )
                    
                    if issued_qty > 0:
                        issue_details.append({
                            'material_name': mat['material_name'],
                            'quantity': issued_qty,
                            'uom': mat['uom']
                        })
            
            # Update order materials status
            update_query = text("""
                UPDATE manufacturing_order_materials m
                SET m.status = CASE 
                    WHEN m.issued_qty >= m.required_qty THEN 'ISSUED'
                    WHEN m.issued_qty > 0 THEN 'PARTIAL'
                    ELSE 'PENDING'
                END
                WHERE m.manufacturing_order_id = :order_id
            """)
            
            conn.execute(update_query, {'order_id': order_id})
            
            # Update order status if not already confirmed
            if order['status'] == 'DRAFT':
                self._update_order_status(conn, order_id, 'CONFIRMED', user_id)
            
            trans.commit()
            logger.info(f"Issued materials for order {order_id}")
            
            return {
                'issue_no': issue_no,
                'details': issue_details
            }
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error issuing materials: {e}")
            raise
        finally:
            conn.close()
    
    def _issue_material_fefo(self, conn, issue_id, order_id, material, 
                            required_qty, warehouse_id, group_id, user_id):
        """Issue material using FEFO algorithm"""

        keycloak_id = self.get_keycloak_id_cached(user_id)

        # Get available stock ordered by expiry (FEFO)
        fefo_query = text("""
            SELECT 
                id,
                batch_no,
                remain,
                expired_date,
                CASE 
                    WHEN expired_date < CURDATE() THEN 'EXPIRED'
                    ELSE 'OK'
                END as status
            FROM inventory_histories
            WHERE product_id = :material_id
            AND warehouse_id = :warehouse_id
            AND remain > 0
            AND delete_flag = 0
            ORDER BY expired_date ASC, created_date ASC
            FOR UPDATE
        """)
        
        available_stock = conn.execute(fefo_query, {
            'material_id': material['material_id'],
            'warehouse_id': warehouse_id
        }).fetchall()
        
        total_issued = 0
        qty_to_issue = required_qty
        
        for stock in available_stock:
            if qty_to_issue <= 0:
                break
            
            # Check if expired
            if stock.status == 'EXPIRED' and not self.config['allow_expired_materials']:
                logger.warning(f"Skipping expired batch {stock.batch_no}")
                continue
            
            take_qty = min(qty_to_issue, stock.remain)
            
            # Create issue detail
            detail_query = text("""
                INSERT INTO material_issue_details (
                    material_issue_id, material_id, manufacturing_order_id,
                    inventory_history_id, batch_no, quantity, uom
                ) VALUES (
                    :issue_id, :material_id, :order_id,
                    :inv_hist_id, :batch_no, :quantity, :uom
                )
            """)
            
            result = conn.execute(detail_query, {
                'issue_id': issue_id,
                'material_id': material['material_id'],
                'order_id': order_id,
                'inv_hist_id': stock.id,
                'batch_no': stock.batch_no,
                'quantity': take_qty,
                'uom': material['uom']
            })
            
            detail_id = result.lastrowid
            
            # Update inventory - reduce stock
            update_inv_query = text("""
                UPDATE inventory_histories
                SET remain = remain - :quantity,
                    updated_date = NOW()
                WHERE id = :inv_hist_id
            """)
            
            conn.execute(update_inv_query, {
                'quantity': take_qty,
                'inv_hist_id': stock.id
            })
            
            # Create inventory history for stockOut
            inv_out_query = text("""
                INSERT INTO inventory_histories (
                    type, product_id, warehouse_id, quantity, remain,
                    batch_no, expired_date, action_detail_id, group_id,
                    created_by, created_date, delete_flag
                ) VALUES (
                    'stockOutProduction', :product_id, :warehouse_id, 
                    :quantity, 0, :batch_no, :expired_date, :detail_id, 
                    :group_id, :created_by, NOW(), 0
                )
            """)
            
            conn.execute(inv_out_query, {
                'product_id': material['material_id'],
                'warehouse_id': warehouse_id,
                'quantity': take_qty,
                'batch_no': stock.batch_no,
                'expired_date': stock.expired_date,
                'detail_id': detail_id,
                'group_id': group_id,
                'created_by': keycloak_id
            })
            
            # Update material issued quantity
            update_mat_query = text("""
                UPDATE manufacturing_order_materials
                SET issued_qty = issued_qty + :quantity
                WHERE manufacturing_order_id = :order_id
                AND material_id = :material_id
            """)
            
            conn.execute(update_mat_query, {
                'quantity': take_qty,
                'order_id': order_id,
                'material_id': material['material_id']
            })
            
            total_issued += take_qty
            qty_to_issue -= take_qty
        
        return total_issued
    
    def get_issued_materials(self, order_id):
        """Get materials that can be returned"""
        query = """
        SELECT 
            mid.id as issue_detail_id,
            mid.material_id,
            p.name as material_name,
            p.pt_code as material_code,
            mid.batch_no,
            mid.quantity as issued_qty,
            mid.uom,
            COALESCE(returns.returned_qty, 0) as returned_qty,
            mid.quantity - COALESCE(returns.returned_qty, 0) as returnable_qty,
            mi.issue_no,
            mi.issue_date
        FROM material_issue_details mid
        JOIN material_issues mi ON mid.material_issue_id = mi.id
        JOIN products p ON mid.material_id = p.id
        LEFT JOIN (
            SELECT 
                mrd.original_issue_detail_id,
                SUM(mrd.quantity) as returned_qty
            FROM material_return_details mrd
            JOIN material_returns mr ON mr.id = mrd.material_return_id
            WHERE mr.status = 'CONFIRMED'
            GROUP BY mrd.original_issue_detail_id
        ) returns ON returns.original_issue_detail_id = mid.id
        WHERE mid.manufacturing_order_id = %s
        AND mi.status = 'CONFIRMED'
        HAVING returnable_qty > 0
        ORDER BY p.name, mid.batch_no
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting issued materials: {e}")
            return pd.DataFrame()
    
    def create_material_return(self, return_data, user_id):
        """Create material return with validation"""
        keycloak_id = self.get_keycloak_id_cached(user_id)

        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Generate return number
            return_no = self._generate_return_number()
            group_id = str(uuid.uuid4())
            
            # Create return header
            header_query = text("""
                INSERT INTO material_returns (
                    return_no, material_issue_id, manufacturing_order_id,
                    warehouse_id, reason, notes, status, created_by, created_date
                ) VALUES (
                    :return_no, :issue_id, :order_id, :warehouse_id,
                    :reason, :notes, 'CONFIRMED', :created_by, NOW()
                )
            """)
            
            result = conn.execute(header_query, {
                'return_no': return_no,
                'issue_id': return_data['material_issue_id'],
                'order_id': return_data['manufacturing_order_id'],
                'warehouse_id': return_data['warehouse_id'],
                'reason': return_data['reason'],
                'notes': return_data.get('notes', ''),
                'created_by': user_id
            })
            
            return_id = result.lastrowid
            return_details = []
            
            # Process each return item
            for item in return_data['items']:
                # Validate returnable quantity
                validation = self._validate_return_quantity(
                    conn, item['original_issue_detail_id'], item['quantity']
                )
                
                if not validation['valid']:
                    raise ValueError(validation['error'])
                
                # Create return detail
                detail_query = text("""
                    INSERT INTO material_return_details (
                        material_return_id, original_issue_detail_id,
                        material_id, quantity, batch_no, uom, condition
                    ) VALUES (
                        :return_id, :issue_detail_id, :material_id,
                        :quantity, :batch_no, :uom, :condition
                    )
                """)
                
                result = conn.execute(detail_query, {
                    'return_id': return_id,
                    'issue_detail_id': item['original_issue_detail_id'],
                    'material_id': item['material_id'],
                    'quantity': item['quantity'],
                    'batch_no': validation['batch_no'],
                    'uom': item['uom'],
                    'condition': item.get('condition', 'GOOD')
                })
                
                detail_id = result.lastrowid
                
                # Return to inventory if condition is GOOD
                if item.get('condition', 'GOOD') == 'GOOD':
                    # Get original inventory info
                    orig_inv = self._get_original_inventory_info(
                        conn, validation['inventory_history_id']
                    )
                    
                    # Create inventory return
                    inv_return_query = text("""
                        INSERT INTO inventory_histories (
                            type, product_id, warehouse_id, quantity, remain,
                            batch_no, expired_date, action_detail_id, group_id,
                            created_by, created_date, delete_flag
                        ) VALUES (
                            'stockInProductionReturn', :product_id, :warehouse_id,
                            :quantity, :quantity, :batch_no, :expired_date,
                            :detail_id, :group_id, :created_by, NOW(), 0
                        )
                    """)
                    
                    conn.execute(inv_return_query, {
                        'product_id': item['material_id'],
                        'warehouse_id': return_data['warehouse_id'],
                        'quantity': item['quantity'],
                        'batch_no': validation['batch_no'],
                        'expired_date': orig_inv['expired_date'] if orig_inv else None,
                        'detail_id': detail_id,
                        'group_id': group_id,
                        'created_by': keycloak_id
                    })
                
                # Update material issued quantity
                update_mat_query = text("""
                    UPDATE manufacturing_order_materials
                    SET issued_qty = issued_qty - :quantity
                    WHERE manufacturing_order_id = :order_id
                    AND material_id = :material_id
                    AND issued_qty >= :quantity
                """)
                
                conn.execute(update_mat_query, {
                    'quantity': item['quantity'],
                    'order_id': return_data['manufacturing_order_id'],
                    'material_id': item['material_id']
                })
                
                return_details.append({
                    'material_id': item['material_id'],
                    'material_name': item.get('material_name', ''),
                    'quantity': item['quantity'],
                    'batch_no': validation['batch_no']
                })
            
            trans.commit()
            logger.info(f"Created material return {return_no}")
            
            return {
                'return_no': return_no,
                'details': return_details
            }
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error creating material return: {e}")
            raise
        finally:
            conn.close()
    
    def _validate_return_quantity(self, conn, issue_detail_id, return_qty):
        """Validate return quantity against issued quantity"""
        query = text("""
            SELECT 
                mid.quantity as issued_qty,
                mid.batch_no,
                mid.inventory_history_id,
                COALESCE(SUM(mrd2.quantity), 0) as already_returned
            FROM material_issue_details mid
            LEFT JOIN material_return_details mrd2 ON mrd2.original_issue_detail_id = mid.id
            LEFT JOIN material_returns mr2 ON mr2.id = mrd2.material_return_id 
                AND mr2.status = 'CONFIRMED'
            WHERE mid.id = :issue_detail_id
            GROUP BY mid.id, mid.quantity, mid.batch_no, mid.inventory_history_id
        """)
        
        result = conn.execute(query, {'issue_detail_id': issue_detail_id}).fetchone()
        
        if not result:
            return {
                'valid': False,
                'error': f"Invalid issue detail ID: {issue_detail_id}"
            }
        
        returnable = result.issued_qty - result.already_returned
        if return_qty > returnable:
            return {
                'valid': False,
                'error': f"Return quantity {return_qty} exceeds returnable {returnable}"
            }
        
        return {
            'valid': True,
            'batch_no': result.batch_no,
            'inventory_history_id': result.inventory_history_id
        }
    
    def _get_original_inventory_info(self, conn, inv_hist_id):
        """Get original inventory information"""
        query = text("""
            SELECT expired_date, batch_no 
            FROM inventory_histories
            WHERE id = :inv_hist_id
        """)
        
        result = conn.execute(query, {'inv_hist_id': inv_hist_id}).fetchone()
        return {
            'expired_date': result.expired_date,
            'batch_no': result.batch_no
        } if result else None
    
    def get_material_returns(self, order_id):
        """Get all returns for an order"""
        query = """
        SELECT 
            mr.id,
            mr.return_no,
            mr.created_date as return_date,
            mr.reason,
            mr.status,
            COUNT(mrd.id) as item_count,
            SUM(mrd.quantity) as total_quantity
        FROM material_returns mr
        LEFT JOIN material_return_details mrd ON mrd.material_return_id = mr.id
        WHERE mr.manufacturing_order_id = %s
        GROUP BY mr.id, mr.return_no, mr.created_date, mr.reason, mr.status
        ORDER BY mr.created_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting material returns: {e}")
            return pd.DataFrame()

    def _calculate_production_expiry(self, conn, order_id, bom_type):
        """Calculate expiry date based on production type"""
        
        if bom_type == 'KITTING':
            # Lấy expiry date ngắn nhất từ các components
            return self._calculate_kit_expiry(conn, order_id)
        
        elif bom_type == 'CUTTING':
            # Kế thừa từ nguyên liệu nguồn
            query = text("""
                SELECT MIN(ih.expired_date) as expired_date
                FROM material_issue_details mid
                JOIN inventory_histories ih ON ih.id = mid.inventory_history_id
                WHERE mid.manufacturing_order_id = :order_id
                AND ih.expired_date IS NOT NULL
            """)
            result = conn.execute(query, {'order_id': order_id}).fetchone()
            return result[0] if result and result[0] else None
        
        elif bom_type == 'REPACKING':
            # Kế thừa từ sản phẩm gốc, có thể giảm shelf life
            query = text("""
                SELECT MIN(ih.expired_date) as expired_date
                FROM material_issue_details mid
                JOIN inventory_histories ih ON ih.id = mid.inventory_history_id
                WHERE mid.manufacturing_order_id = :order_id
                AND ih.expired_date IS NOT NULL
            """)
            result = conn.execute(query, {'order_id': order_id}).fetchone()
            
            if result and result[0]:
                # Có thể áp dụng reduction factor nếu cần
                # Ví dụ: giảm 10% shelf life còn lại do quá trình đóng gói lại
                # days_remaining = (result[0] - date.today()).days
                # reduced_days = int(days_remaining * 0.9)
                # return date.today() + timedelta(days=reduced_days)
                return result[0]
            return None

    def get_calculated_expiry_date(self, order_id):
        """Get calculated expiry date for production order"""
        conn = self.engine.connect()
        try:
            order = self.get_order_details(order_id)
            if not order:
                return None
                
            return self._calculate_production_expiry(conn, order_id, order['bom_type'])
        finally:
            conn.close()

    def complete_production(self, order_id, produced_qty, batch_no, 
                        quality_status, notes, created_by, expired_date=None):
        """Complete production order với expired_date"""
        keycloak_id = self.get_keycloak_id_cached(created_by)

        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            # Get order details
            order = self.get_order_details(order_id)
            if not order:
                raise ValueError("Order not found")
            
            # Validate
            is_valid, errors = self.validate_production_completion(
                order, produced_qty, batch_no
            )
            if not is_valid:
                raise ValueError("; ".join(errors))
            
            # Calculate expiry date nếu không được cung cấp
            if expired_date is None:
                expired_date = self._calculate_production_expiry(conn, order_id, order['bom_type'])
            
            # Generate receipt number
            receipt_no = self._generate_receipt_number()
            
            # Create production receipt với expired_date
            receipt_query = text("""
                INSERT INTO production_receipts (
                    receipt_no, manufacturing_order_id, receipt_date, 
                    product_id, quantity, uom, batch_no, expired_date,
                    warehouse_id, quality_status, notes, created_by, created_date
                ) VALUES (
                    :receipt_no, :order_id, NOW(), :product_id,
                    :quantity, :uom, :batch_no, :expired_date,
                    :warehouse_id, :quality_status, :notes, :created_by, NOW()
                )
            """)
            
            result = conn.execute(receipt_query, {
                'receipt_no': receipt_no,
                'order_id': order_id,
                'product_id': order['product_id'],
                'quantity': produced_qty,
                'uom': order['uom'],
                'batch_no': batch_no,
                'expired_date': expired_date,  # Lưu vào production_receipts
                'warehouse_id': order['target_warehouse_id'],
                'quality_status': quality_status,
                'notes': notes,
                'created_by': created_by
            })
            
            receipt_id = result.lastrowid
            
            # Get group_id
            group_id = self._get_order_group_id(conn, order_id)
            
            # Add to inventory với expired_date
            inventory_query = text("""
                INSERT INTO inventory_histories (
                    type, product_id, warehouse_id, quantity, remain,
                    batch_no, expired_date, action_detail_id, group_id,
                    created_by, created_date, delete_flag
                ) VALUES (
                    'stockInProduction', :product_id, :warehouse_id,
                    :quantity, :quantity, :batch_no, :expired_date,
                    :receipt_id, :group_id, :created_by, NOW(), 0
                )
            """)
            
            conn.execute(inventory_query, {
                'product_id': order['product_id'],
                'warehouse_id': order['target_warehouse_id'],
                'quantity': produced_qty,
                'batch_no': batch_no,
                'expired_date': expired_date,  # Lưu vào inventory_histories
                'receipt_id': receipt_id,
                'group_id': group_id,
                'created_by': keycloak_id
            })
            
            # Update production order
            update_query = text("""
                UPDATE manufacturing_orders
                SET produced_qty = :produced_qty,
                    status = 'COMPLETED',
                    completion_date = NOW(),
                    updated_by = :updated_by,
                    updated_date = NOW()
                WHERE id = :order_id
            """)
            
            conn.execute(update_query, {
                'produced_qty': produced_qty,
                'updated_by': created_by,
                'order_id': order_id
            })
            
            trans.commit()
            logger.info(f"Completed production order {order_id} with expiry date {expired_date}")
            
            return {
                'receipt_no': receipt_no,
                'batch_no': batch_no,
                'quantity': produced_qty,
                'expired_date': expired_date
            }
            
        except Exception as e:
            trans.rollback()
            logger.error(f"Error completing production: {e}")
            raise
        finally:
            conn.close()

    def preview_production_expiry(self, order_id):
        """Preview expiry date calculation với details"""
        conn = self.engine.connect()
        try:
            order = self.get_order_details(order_id)
            if not order:
                return None
            
            # Get material expiry details
            query = text("""
                SELECT 
                    p.name as material_name,
                    ih.batch_no,
                    ih.expired_date,
                    DATEDIFF(ih.expired_date, CURDATE()) as days_remaining
                FROM material_issue_details mid
                JOIN inventory_histories ih ON ih.id = mid.inventory_history_id
                JOIN products p ON p.id = mid.material_id
                WHERE mid.manufacturing_order_id = :order_id
                AND ih.expired_date IS NOT NULL
                ORDER BY ih.expired_date ASC
            """)
            
            materials = pd.read_sql(query, conn, params={'order_id': order_id})
            
            calculated_expiry = self._calculate_production_expiry(conn, order_id, order['bom_type'])
            
            return {
                'calculated_expiry': calculated_expiry,
                'bom_type': order['bom_type'],
                'materials': materials
            }
        finally:
            conn.close()

    def _get_order_group_id(self, conn, order_id):
        """Get or generate group ID for order"""
        query = text("""
            SELECT group_id FROM material_issues 
            WHERE manufacturing_order_id = :order_id 
            LIMIT 1
        """)
        
        result = conn.execute(query, {'order_id': order_id}).fetchone()
        return result[0] if result else str(uuid.uuid4())
    
    def _calculate_kit_expiry(self, conn, order_id):
        """Calculate expiry date for kit (shortest component expiry)"""
        query = text("""
            SELECT MIN(ih.expired_date) as min_expiry
            FROM material_issue_details mid
            JOIN inventory_histories ih ON ih.id = mid.inventory_history_id
            WHERE mid.manufacturing_order_id = :order_id
            AND ih.expired_date IS NOT NULL
        """)
        
        result = conn.execute(query, {'order_id': order_id}).fetchone()
        return result[0] if result and result[0] else None
    
    def update_order_status(self, order_id, new_status, user_id=None):
        """Update order status"""
        conn = self.engine.connect()
        trans = conn.begin()
        
        try:
            self._update_order_status(conn, order_id, new_status, user_id)
            trans.commit()
        except Exception as e:
            trans.rollback()
            logger.error(f"Error updating order status: {e}")
            raise
        finally:
            conn.close()
    
    def _update_order_status(self, conn, order_id, new_status, user_id=None):
        """Internal method to update order status"""
        query = text("""
            UPDATE manufacturing_orders
            SET status = :status,
                updated_date = NOW(),
                updated_by = :user_id
            WHERE id = :order_id
        """)
        
        conn.execute(query, {
            'status': new_status,
            'user_id': user_id,
            'order_id': order_id
        })
    
    def get_production_stats(self, start_date, end_date):
        """Get production statistics"""
        query = """
        SELECT 
            COUNT(*) as total_orders,
            SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_orders,
            SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress_orders,
            SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_orders,
            COALESCE(SUM(produced_qty), 0) as total_output,
            COALESCE(AVG(CASE 
                WHEN status = 'COMPLETED' AND completion_date IS NOT NULL
                THEN DATEDIFF(completion_date, order_date) 
                ELSE NULL 
            END), 0) as avg_lead_time,
            CASE 
                WHEN COUNT(*) > 0 
                THEN (SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))
                ELSE 0 
            END as completion_rate
        FROM manufacturing_orders
        WHERE order_date BETWEEN %s AND %s
        AND delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(start_date, end_date))
            
            if not result.empty:
                stats = result.iloc[0].to_dict()
                # Add mock trend data
                stats['vs_previous_period'] = 15.5
                stats['lead_time_trend'] = -5.2
                return stats
            
            return self._empty_stats()
            
        except Exception as e:
            logger.error(f"Error getting production stats: {e}")
            return self._empty_stats()
    
    def _empty_stats(self):
        """Return empty statistics"""
        return {
            'total_orders': 0,
            'completed_orders': 0,
            'in_progress_orders': 0,
            'cancelled_orders': 0,
            'total_output': 0,
            'avg_lead_time': 0,
            'completion_rate': 0,
            'vs_previous_period': 0,
            'lead_time_trend': 0
        }
    
    def get_orders_by_type(self, start_date, end_date):
        """Get order count by type"""
        query = """
        SELECT 
            b.bom_type,
            COUNT(*) as count
        FROM manufacturing_orders o
        JOIN bom_headers b ON o.bom_header_id = b.id
        WHERE o.order_date BETWEEN %s AND %s
        AND o.delete_flag = 0
        GROUP BY b.bom_type
        ORDER BY count DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(start_date, end_date))
        except Exception as e:
            logger.error(f"Error getting orders by type: {e}")
            return pd.DataFrame()
    
    def get_orders_by_status(self, start_date, end_date):
        """Get order count by status"""
        query = """
        SELECT 
            status,
            COUNT(*) as count
        FROM manufacturing_orders
        WHERE order_date BETWEEN %s AND %s
        AND delete_flag = 0
        GROUP BY status
        ORDER BY FIELD(status, 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(start_date, end_date))
        except Exception as e:
            logger.error(f"Error getting orders by status: {e}")
            return pd.DataFrame()
    
    def get_material_consumption(self, start_date, end_date, warehouse_id=None):
        """Get material consumption report"""
        query = """
        SELECT 
            p.name as material_name,
            SUM(ABS(mid.quantity)) as total_issued,
            COALESCE(returns.total_returned, 0) as total_returned,
            SUM(ABS(mid.quantity)) - COALESCE(returns.total_returned, 0) as total_consumed,
            mid.uom,
            COUNT(DISTINCT mo.id) as product_count
        FROM material_issue_details mid
        JOIN material_issues mi ON mid.material_issue_id = mi.id
        JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
        JOIN products p ON mid.material_id = p.id
        LEFT JOIN (
            SELECT 
                mrd.material_id,
                SUM(mrd.quantity) as total_returned
            FROM material_return_details mrd
            JOIN material_returns mr ON mr.id = mrd.material_return_id
            WHERE mr.status = 'CONFIRMED'
            AND DATE(mr.created_date) BETWEEN %s AND %s
            GROUP BY mrd.material_id
        ) returns ON returns.material_id = mid.material_id
        WHERE DATE(mi.issue_date) BETWEEN %s AND %s
        AND mi.status = 'CONFIRMED'
        """
        
        params = [start_date, end_date, start_date, end_date]
        
        if warehouse_id:
            query += " AND mi.warehouse_id = %s"
            params.append(warehouse_id)
        
        query += """
        GROUP BY p.name, mid.uom, returns.total_returned 
        ORDER BY total_consumed DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params))
        except Exception as e:
            logger.error(f"Error getting material consumption: {e}")
            return pd.DataFrame()
    
    def get_recent_activities(self, limit=10):
        """Get recent production activities"""
        query = f"""
        SELECT * FROM (
            SELECT 
                'Order Created' as activity,
                order_no as reference,
                created_date as timestamp,
                created_by as user_id
            FROM manufacturing_orders
            WHERE delete_flag = 0
            
            UNION ALL
            
            SELECT 
                'Materials Issued' as activity,
                issue_no as reference,
                created_date as timestamp,
                created_by as user_id
            FROM material_issues
            WHERE status = 'CONFIRMED'
            
            UNION ALL
            
            SELECT 
                'Materials Returned' as activity,
                return_no as reference,
                created_date as timestamp,
                created_by as user_id
            FROM material_returns
            WHERE status = 'CONFIRMED'
            
            UNION ALL
            
            SELECT 
                'Production Completed' as activity,
                receipt_no as reference,
                created_date as timestamp,
                created_by as user_id
            FROM production_receipts
        ) activities
        ORDER BY timestamp DESC
        LIMIT {limit}
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting recent activities: {e}")
            return pd.DataFrame()
    
    def _generate_order_number(self):
        """Generate unique order number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        # Get today's count
        query = text("""
            SELECT COUNT(*) + 1 as next_num
            FROM manufacturing_orders
            WHERE order_no LIKE :pattern
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'pattern': f'MO-{timestamp}%'})
            next_num = result.fetchone()[0]
        
        return f"MO-{timestamp}-{next_num:03d}"
    
    def _generate_issue_number(self):
        """Generate unique issue number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COUNT(*) + 1 as next_num
            FROM material_issues
            WHERE issue_no LIKE :pattern
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'pattern': f'MI-{timestamp}%'})
            next_num = result.fetchone()[0]
        
        return f"MI-{timestamp}-{next_num:03d}"
    
    def _generate_receipt_number(self):
        """Generate unique receipt number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COUNT(*) + 1 as next_num
            FROM production_receipts
            WHERE receipt_no LIKE :pattern
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'pattern': f'PR-{timestamp}%'})
            next_num = result.fetchone()[0]
        
        return f"PR-{timestamp}-{next_num:03d}"
    
    def _generate_return_number(self):
        """Generate unique return number"""
        timestamp = datetime.now().strftime('%Y%m%d')
        
        query = text("""
            SELECT COUNT(*) + 1 as next_num
            FROM material_returns
            WHERE return_no LIKE :pattern
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'pattern': f'MR-{timestamp}%'})
            next_num = result.fetchone()[0]
        
        return f"MR-{timestamp}-{next_num:03d}"