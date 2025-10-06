# modules/inventory.py - Enhanced Inventory Management Integration
import pandas as pd
from datetime import datetime, date, timedelta
from utils.db import get_db_engine
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class InventoryManager:
    """Enhanced Inventory Management for Manufacturing"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    def get_stock_balance(self, product_id, warehouse_id=None):
        """Get current stock balance for a product"""
        query = """
        SELECT 
            COALESCE(SUM(remain), 0) as stock_balance
        FROM inventory_histories
        WHERE product_id = %s
        AND remain > 0
        AND delete_flag = 0
        """
        
        params = [product_id]
        
        if warehouse_id:
            query += " AND warehouse_id = %s"
            params.append(warehouse_id)
        
        try:
            result = pd.read_sql(query, self.engine, params=tuple(params))
            return float(result['stock_balance'].iloc[0]) if not result.empty else 0.0
        except Exception as e:
            logger.error(f"Error getting stock balance: {e}")
            return 0.0
    
    def get_stock_by_batch(self, product_id, warehouse_id):
        """Get stock details by batch with FEFO order"""
        query = """
        SELECT 
            batch_no,
            SUM(remain) as available_qty,
            expired_date,
            CASE 
                WHEN expired_date < CURDATE() THEN 'EXPIRED'
                WHEN expired_date <= DATE_ADD(CURDATE(), INTERVAL 7 DAY) THEN 'CRITICAL'
                WHEN expired_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'WARNING'
                ELSE 'OK'
            END as expiry_status
        FROM inventory_histories
        WHERE product_id = %s
        AND warehouse_id = %s
        AND remain > 0
        AND delete_flag = 0
        GROUP BY batch_no, expired_date
        ORDER BY expired_date ASC, batch_no ASC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id, warehouse_id))
        except Exception as e:
            logger.error(f"Error getting stock by batch: {e}")
            return pd.DataFrame()
    
    def preview_fefo_issue(self, product_id, quantity, warehouse_id):
        """Preview which batches would be issued using FEFO"""
        try:
            # Get available batches
            batches = self.get_stock_by_batch(product_id, warehouse_id)
            
            if batches.empty:
                return pd.DataFrame()
            
            remaining_qty = quantity
            selected_batches = []
            
            for _, batch in batches.iterrows():
                if remaining_qty <= 0:
                    break
                
                # Skip expired if not allowed (configuration based)
                if batch['expiry_status'] == 'EXPIRED':
                    logger.warning(f"Skipping expired batch {batch['batch_no']}")
                    continue
                
                take_qty = min(remaining_qty, batch['available_qty'])
                selected_batches.append({
                    'batch_no': batch['batch_no'],
                    'quantity': take_qty,
                    'expired_date': batch['expired_date'],
                    'expiry_status': batch['expiry_status']
                })
                
                remaining_qty -= take_qty
            
            return pd.DataFrame(selected_batches)
            
        except Exception as e:
            logger.error(f"Error in FEFO preview: {e}")
            return pd.DataFrame()
    
    def get_warehouses(self):
        """Get list of active warehouses"""
        query = """
        SELECT 
            w.id,
            w.name,
            w.address,
            w.company_id,
            c.english_name as company_name
        FROM warehouses w
        LEFT JOIN companies c ON w.company_id = c.id
        WHERE w.delete_flag = 0
        ORDER BY w.name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
            return pd.DataFrame()
    
    def check_stock_availability(self, materials_list, warehouse_id):
        """Check if multiple materials are available"""
        availability_results = []
        
        for material in materials_list:
            stock = self.get_stock_balance(material['product_id'], warehouse_id)
            required = material.get('quantity', 0)
            
            availability_results.append({
                'product_id': material['product_id'],
                'product_name': material.get('product_name', ''),
                'required_qty': required,
                'available_qty': stock,
                'is_sufficient': stock >= required,
                'shortage': max(0, required - stock)
            })
        
        return pd.DataFrame(availability_results)
    
    def get_batch_info(self, batch_no):
        """Get comprehensive batch information"""
        query = """
        SELECT 
            ih.batch_no,
            ih.product_id,
            p.name as product_name,
            p.pt_code as product_code,
            ih.warehouse_id,
            w.name as warehouse_name,
            SUM(CASE WHEN ih.type LIKE 'stockIn%' THEN ih.quantity ELSE 0 END) as total_in,
            SUM(CASE WHEN ih.type LIKE 'stockOut%' THEN ABS(ih.quantity) ELSE 0 END) as total_out,
            MAX(ih.remain) as current_qty,
            ih.expired_date,
            MIN(ih.created_date) as created_date,
            ih.uom
        FROM inventory_histories ih
        JOIN products p ON ih.product_id = p.id
        JOIN warehouses w ON ih.warehouse_id = w.id
        WHERE ih.batch_no = %s
        GROUP BY ih.batch_no, ih.product_id, p.name, p.pt_code, 
                 ih.warehouse_id, w.name, ih.expired_date, ih.uom
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(batch_no,))
            if not result.empty:
                batch_data = result.iloc[0].to_dict()
                # Calculate actual remaining
                batch_data['quantity'] = batch_data['current_qty']
                return batch_data
            return None
        except Exception as e:
            logger.error(f"Error getting batch info: {e}")
            return None
    
    def get_batch_sources(self, batch_no):
        """Get source materials for a production batch (genealogy)"""
        query = """
        SELECT 
            p.name as material_name,
            p.pt_code as material_code,
            mid.quantity,
            mid.batch_no as source_batch,
            ih_source.expired_date
        FROM production_receipts pr
        JOIN material_issue_details mid ON mid.manufacturing_order_id = pr.manufacturing_order_id
        JOIN products p ON mid.material_id = p.id
        LEFT JOIN inventory_histories ih_source ON ih_source.id = mid.inventory_history_id
        WHERE pr.batch_no = %s
        ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(batch_no,))
        except Exception as e:
            logger.error(f"Error getting batch sources: {e}")
            return pd.DataFrame()
    
    def get_batch_locations(self, batch_no):
        """Get current locations and quantities of a batch"""
        query = """
        SELECT 
            w.name as warehouse,
            SUM(ih.remain) as quantity,
            CASE 
                WHEN MAX(ih.expired_date) < CURDATE() THEN 'EXPIRED'
                WHEN SUM(ih.remain) = 0 THEN 'CONSUMED'
                ELSE 'AVAILABLE'
            END as status,
            MAX(ih.updated_date) as last_updated
        FROM inventory_histories ih
        JOIN warehouses w ON ih.warehouse_id = w.id
        WHERE ih.batch_no = %s
        AND ih.remain > 0
        GROUP BY w.id, w.name
        ORDER BY quantity DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(batch_no,))
        except Exception as e:
            logger.error(f"Error getting batch locations: {e}")
            return pd.DataFrame()
    
    def get_expiry_status(self, days_ahead=30):
        """Get products approaching expiry"""
        query = """
        SELECT 
            p.name as product_name,
            p.pt_code as product_code,
            ih.batch_no,
            SUM(ih.remain) as quantity,
            ih.expired_date,
            w.name as warehouse,
            CASE 
                WHEN ih.expired_date < CURDATE() THEN 'EXPIRED'
                WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL 7 DAY) THEN 'CRITICAL'
                WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY) THEN 'WARNING'
                ELSE 'OK'
            END as expiry_status,
            DATEDIFF(ih.expired_date, CURDATE()) as days_to_expiry
        FROM inventory_histories ih
        JOIN products p ON ih.product_id = p.id
        JOIN warehouses w ON ih.warehouse_id = w.id
        WHERE ih.remain > 0
        AND ih.delete_flag = 0
        AND ih.expired_date IS NOT NULL
        AND ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
        GROUP BY p.name, p.pt_code, ih.batch_no, ih.expired_date, w.name
        ORDER BY ih.expired_date ASC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(days_ahead, days_ahead))
        except Exception as e:
            logger.error(f"Error getting expiry status: {e}")
            return pd.DataFrame()
    
    def get_production_impact(self, start_date, end_date):
        """Analyze inventory impact from production"""
        query = """
        SELECT 
            p.id as product_id,
            p.name as product_name,
            p.pt_code as product_code,
            SUM(CASE 
                WHEN ih.type = 'stockInProduction' THEN ih.quantity 
                ELSE 0 
            END) as produced,
            SUM(CASE 
                WHEN ih.type = 'stockOutProduction' THEN ABS(ih.quantity) 
                ELSE 0 
            END) as consumed,
            SUM(CASE 
                WHEN ih.type = 'stockInProductionReturn' THEN ih.quantity
                ELSE 0
            END) as returned,
            SUM(CASE 
                WHEN ih.type = 'stockInProduction' THEN ih.quantity
                WHEN ih.type = 'stockOutProduction' THEN ih.quantity
                WHEN ih.type = 'stockInProductionReturn' THEN ih.quantity
                ELSE 0
            END) as net_change
        FROM inventory_histories ih
        JOIN products p ON ih.product_id = p.id
        WHERE ih.type IN ('stockInProduction', 'stockOutProduction', 'stockInProductionReturn')
        AND DATE(ih.created_date) BETWEEN %s AND %s
        AND ih.delete_flag = 0
        GROUP BY p.id, p.name, p.pt_code
        HAVING net_change != 0
        ORDER BY ABS(net_change) DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(start_date, end_date))
        except Exception as e:
            logger.error(f"Error getting production impact: {e}")
            return pd.DataFrame()
    
    def get_low_stock_items(self, threshold_qty=50):
        """Get items below minimum stock level"""
        query = """
        WITH current_stock AS (
            SELECT 
                p.id as product_id,
                p.name as product_name,
                p.pt_code as product_code,
                p.uom,
                w.id as warehouse_id,
                w.name as warehouse,
                COALESCE(SUM(ih.remain), 0) as current_stock
            FROM products p
            CROSS JOIN warehouses w
            LEFT JOIN inventory_histories ih ON ih.product_id = p.id 
                AND ih.warehouse_id = w.id 
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE p.delete_flag = 0
            AND p.approval_status = 1
            AND p.is_service = 0
            AND w.delete_flag = 0
            GROUP BY p.id, p.name, p.pt_code, p.uom, w.id, w.name
        )
        SELECT 
            product_name,
            product_code,
            warehouse,
            current_stock,
            uom,
            %s as threshold,
            (%s - current_stock) as shortage
        FROM current_stock
        WHERE current_stock < %s
        ORDER BY shortage DESC, product_name
        """
        
        try:
            return pd.read_sql(query, self.engine, 
                             params=(threshold_qty, threshold_qty, threshold_qty))
        except Exception as e:
            logger.error(f"Error getting low stock items: {e}")
            return pd.DataFrame()
    
    def get_batches_by_date(self, start_date, end_date):
        """Get batches created within date range"""
        query = """
        SELECT 
            pr.batch_no,
            pr.receipt_date,
            p.name as product_name,
            p.pt_code as product_code,
            pr.quantity,
            pr.uom,
            pr.quality_status,
            mo.order_no,
            b.bom_type,
            w.name as warehouse
        FROM production_receipts pr
        JOIN products p ON pr.product_id = p.id
        JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
        JOIN bom_headers b ON mo.bom_header_id = b.id
        JOIN warehouses w ON pr.warehouse_id = w.id
        WHERE DATE(pr.receipt_date) BETWEEN %s AND %s
        ORDER BY pr.receipt_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(start_date, end_date))
        except Exception as e:
            logger.error(f"Error getting batches by date: {e}")
            return pd.DataFrame()
    
    def get_inventory_turnover(self, product_id, warehouse_id, days=30):
        """Calculate inventory turnover rate"""
        query = """
        WITH movements AS (
            SELECT 
                DATE(created_date) as movement_date,
                SUM(CASE 
                    WHEN type LIKE 'stockOut%' THEN ABS(quantity) 
                    ELSE 0 
                END) as daily_consumption
            FROM inventory_histories
            WHERE product_id = %s
            AND warehouse_id = %s
            AND created_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            AND delete_flag = 0
            GROUP BY DATE(created_date)
        ),
        avg_stock AS (
            SELECT AVG(remain) as avg_inventory
            FROM inventory_histories
            WHERE product_id = %s
            AND warehouse_id = %s
            AND remain > 0
            AND delete_flag = 0
        )
        SELECT 
            COALESCE(SUM(m.daily_consumption), 0) as total_consumption,
            COALESCE(a.avg_inventory, 0) as average_inventory,
            CASE 
                WHEN a.avg_inventory > 0 
                THEN (SUM(m.daily_consumption) * 365 / %s) / a.avg_inventory
                ELSE 0 
            END as turnover_rate,
            CASE 
                WHEN SUM(m.daily_consumption) > 0
                THEN a.avg_inventory / (SUM(m.daily_consumption) / %s)
                ELSE 999
            END as days_of_stock
        FROM movements m
        CROSS JOIN avg_stock a
        GROUP BY a.avg_inventory
        """
        
        try:
            result = pd.read_sql(query, self.engine, 
                               params=(product_id, warehouse_id, days, 
                                     product_id, warehouse_id, days, days))
            return result.iloc[0].to_dict() if not result.empty else {
                'total_consumption': 0,
                'average_inventory': 0,
                'turnover_rate': 0,
                'days_of_stock': 999
            }
        except Exception as e:
            logger.error(f"Error calculating inventory turnover: {e}")
            return {
                'total_consumption': 0,
                'average_inventory': 0,
                'turnover_rate': 0,
                'days_of_stock': 999
            }
    
    def validate_batch_availability(self, batch_no, warehouse_id):
        """Validate if a specific batch is available"""
        query = """
        SELECT 
            SUM(remain) as available_qty,
            expired_date,
            CASE 
                WHEN expired_date < CURDATE() THEN 'EXPIRED'
                ELSE 'OK'
            END as status
        FROM inventory_histories
        WHERE batch_no = %s
        AND warehouse_id = %s
        AND remain > 0
        AND delete_flag = 0
        GROUP BY expired_date
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(batch_no, warehouse_id))
            if not result.empty:
                return {
                    'available': True,
                    'quantity': float(result['available_qty'].iloc[0]),
                    'expired_date': result['expired_date'].iloc[0],
                    'status': result['status'].iloc[0]
                }
            return {
                'available': False,
                'quantity': 0,
                'expired_date': None,
                'status': 'NOT_FOUND'
            }
        except Exception as e:
            logger.error(f"Error validating batch: {e}")
            return {
                'available': False,
                'quantity': 0,
                'expired_date': None,
                'status': 'ERROR'
            }