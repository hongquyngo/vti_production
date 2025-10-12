# utils/production/inventory.py
"""
Inventory Management for Production
Stock queries, FEFO logic, and inventory transactions
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional
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
        """Get current stock balance"""
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
            logger.error(f"Error getting stock balance: {e}")
            return Decimal('0')
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get active warehouses"""
        query = """
            SELECT 
                id,
                name,
                warehouse_type,
                is_active
            FROM warehouses
            WHERE delete_flag = 0 AND is_active = 1
            ORDER BY name
        """
        
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
            return pd.DataFrame()
    
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