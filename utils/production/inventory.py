# utils/production/inventory.py
"""
Inventory Management for Production
Stock queries, FEFO logic, and inventory transactions
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict
import pandas as pd
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


class InventoryManager:
    """Inventory Management for Production"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    def get_stock_balance(self, product_id: int, 
                         warehouse_id: Optional[int] = None) -> Decimal:
        """Get current stock balance for a product"""
        query = """
            SELECT COALESCE(SUM(remain), 0) as stock_balance
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
            return Decimal(str(result['stock_balance'].iloc[0]))
        except Exception as e:
            logger.error(f"Error getting stock balance for product {product_id}: {e}")
            return Decimal('0')
    
    def get_stock_balances(self, product_ids: List[int], 
                          warehouse_id: int) -> Dict[int, Decimal]:
        """Get stock balances for multiple products at once (batch query)"""
        if not product_ids:
            return {}
        
        query = """
            SELECT 
                product_id,
                COALESCE(SUM(remain), 0) as stock_balance
            FROM inventory_histories
            WHERE product_id IN %s
                AND warehouse_id = %s
                AND remain > 0
                AND delete_flag = 0
            GROUP BY product_id
        """
        
        try:
            result = pd.read_sql(query, self.engine, 
                               params=(tuple(product_ids), warehouse_id))
            return dict(zip(result['product_id'], 
                          [Decimal(str(x)) for x in result['stock_balance']]))
        except Exception as e:
            logger.error(f"Error getting batch stock balances: {e}")
            return {}
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get active warehouses (based on actual schema)"""
        query = """
            SELECT 
                id,
                name,
                address,
                company_id,
                manager_id
            FROM warehouses
            WHERE delete_flag = 0
            ORDER BY name
        """
        
        try:
            df = pd.read_sql(query, self.engine)
            
            if df.empty:
                logger.warning("No warehouses found in database")
            else:
                logger.info(f"Retrieved {len(df)} warehouses")
            
            return df
            
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
            # Return empty DataFrame with correct columns
            return pd.DataFrame(columns=['id', 'name', 'address', 'company_id', 'manager_id'])
    
    def get_stock_by_batch(self, product_id: int, warehouse_id: int) -> pd.DataFrame:
        """Get stock by batch with FEFO order"""
        query = """
            SELECT 
                id,
                batch_no,
                remain as available_qty,
                expired_date,
                CASE 
                    WHEN expired_date IS NULL THEN 'OK'
                    WHEN expired_date < CURDATE() THEN 'EXPIRED'
                    WHEN expired_date <= DATE_ADD(CURDATE(), INTERVAL 7 DAY) THEN 'CRITICAL'
                    WHEN expired_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'WARNING'
                    ELSE 'OK'
                END as expiry_status,
                DATEDIFF(expired_date, CURDATE()) as days_to_expiry
            FROM inventory_histories
            WHERE product_id = %s
                AND warehouse_id = %s
                AND remain > 0
                AND delete_flag = 0
            ORDER BY 
                CASE WHEN expired_date IS NULL THEN 1 ELSE 0 END,
                expired_date ASC,
                created_date ASC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id, warehouse_id))
        except Exception as e:
            logger.error(f"Error getting stock by batch: {e}")
            return pd.DataFrame()
    
    def validate_warehouse_exists(self, warehouse_id: int) -> bool:
        """Validate warehouse exists and is not deleted"""
        query = """
            SELECT 1 FROM warehouses 
            WHERE id = %s AND delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(warehouse_id,))
            return not result.empty
        except Exception as e:
            logger.error(f"Error validating warehouse {warehouse_id}: {e}")
            return False