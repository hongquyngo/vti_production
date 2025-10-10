# modules/inventory.py - Simplified Inventory Management
"""
Inventory Management Module
Essential functions for production stock tracking and FEFO management.
"""

import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


# ==================== Enums ====================

class TransactionType(Enum):
    """Inventory transaction types"""
    STOCK_IN_PRODUCTION = "stockInProduction"
    STOCK_OUT_PRODUCTION = "stockOutProduction"
    STOCK_IN_RETURN = "stockInProductionReturn"


class ExpiryStatus(Enum):
    """Expiry status"""
    OK = "OK"
    WARNING = "WARNING"  # Within 30 days
    CRITICAL = "CRITICAL"  # Within 7 days
    EXPIRED = "EXPIRED"


# ==================== Main Manager ====================

class InventoryManager:
    """Inventory Management for Production"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self.expiry_warning_days = 30
        self.expiry_critical_days = 7
    
    # ==================== Stock Balance ====================
    
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
    
    def get_stock_by_batch(self, product_id: int, warehouse_id: int) -> pd.DataFrame:
        """Get stock by batch with FEFO order"""
        query = """
            SELECT 
                id,
                batch_no,
                SUM(remain) as available_qty,
                expired_date,
                CASE 
                    WHEN expired_date IS NULL THEN 'OK'
                    WHEN expired_date < CURDATE() THEN 'EXPIRED'
                    WHEN expired_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY) THEN 'CRITICAL'
                    WHEN expired_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY) THEN 'WARNING'
                    ELSE 'OK'
                END as expiry_status,
                DATEDIFF(expired_date, CURDATE()) as days_to_expiry
            FROM inventory_histories
            WHERE product_id = %s
                AND warehouse_id = %s
                AND remain > 0
                AND delete_flag = 0
            GROUP BY id, batch_no, expired_date
            ORDER BY 
                CASE WHEN expired_date IS NULL THEN 1 ELSE 0 END,
                expired_date ASC,
                created_date ASC
        """
        
        try:
            return pd.read_sql(
                query, 
                self.engine, 
                params=(
                    self.expiry_critical_days,
                    self.expiry_warning_days,
                    product_id,
                    warehouse_id
                )
            )
        except Exception as e:
            logger.error(f"Error getting stock by batch: {e}")
            return pd.DataFrame()
    
    # ==================== FEFO Preview ====================
    
    def preview_fefo_issue(self, product_id: int, quantity: Decimal,
                          warehouse_id: int) -> pd.DataFrame:
        """Preview FEFO batch selection"""
        try:
            batches = self.get_stock_by_batch(product_id, warehouse_id)
            
            if batches.empty:
                return pd.DataFrame()
            
            remaining_qty = float(quantity)
            selected_batches = []
            
            for _, batch in batches.iterrows():
                if remaining_qty <= 0:
                    break
                
                # Skip expired batches
                if batch['expiry_status'] == 'EXPIRED':
                    logger.warning(f"Skipping expired batch {batch['batch_no']}")
                    continue
                
                take_qty = min(remaining_qty, float(batch['available_qty']))
                
                selected_batches.append({
                    'batch_id': batch['id'],
                    'batch_no': batch['batch_no'],
                    'quantity': take_qty,
                    'available': batch['available_qty'],
                    'expired_date': batch['expired_date'],
                    'expiry_status': batch['expiry_status'],
                    'days_to_expiry': batch['days_to_expiry']
                })
                
                remaining_qty -= take_qty
            
            result_df = pd.DataFrame(selected_batches)
            
            # Add warning if insufficient stock
            if remaining_qty > 0:
                logger.warning(
                    f"Insufficient stock: requested {quantity}, "
                    f"available {quantity - Decimal(str(remaining_qty))}"
                )
            
            return result_df
            
        except Exception as e:
            logger.error(f"Error in FEFO preview: {e}")
            return pd.DataFrame()
    
    # ==================== Stock Movement ====================
    
    def record_stock_out(self, product_id: int, warehouse_id: int,
                        quantity: float, batch_no: str,
                        reference_type: str, reference_id: int,
                        created_by: Optional[str] = None) -> int:
        """Record stock out for production"""
        with self.engine.begin() as conn:
            try:
                query = text("""
                    INSERT INTO inventory_histories (
                        type, product_id, warehouse_id, quantity, remain,
                        batch_no, reference_type, reference_id,
                        created_by, created_date, delete_flag
                    ) VALUES (
                        :type, :product_id, :warehouse_id, :quantity, 0,
                        :batch_no, :ref_type, :ref_id,
                        :created_by, NOW(), 0
                    )
                """)
                
                result = conn.execute(query, {
                    'type': TransactionType.STOCK_OUT_PRODUCTION.value,
                    'product_id': product_id,
                    'warehouse_id': warehouse_id,
                    'quantity': -abs(quantity),  # Negative for stock out
                    'batch_no': batch_no,
                    'ref_type': reference_type,
                    'ref_id': reference_id,
                    'created_by': created_by
                })
                
                return result.lastrowid
                
            except Exception as e:
                logger.error(f"Error recording stock out: {e}")
                raise
    
    def record_stock_in(self, product_id: int, warehouse_id: int,
                       quantity: float, batch_no: str,
                       expired_date: Optional[date],
                       reference_type: str, reference_id: int,
                       transaction_type: str = "stockInProduction",
                       created_by: Optional[str] = None) -> int:
        """Record stock in for production or return"""
        with self.engine.begin() as conn:
            try:
                query = text("""
                    INSERT INTO inventory_histories (
                        type, product_id, warehouse_id, quantity, remain,
                        batch_no, expired_date, reference_type, reference_id,
                        created_by, created_date, delete_flag
                    ) VALUES (
                        :type, :product_id, :warehouse_id, :quantity, :quantity,
                        :batch_no, :expired_date, :ref_type, :ref_id,
                        :created_by, NOW(), 0
                    )
                """)
                
                result = conn.execute(query, {
                    'type': transaction_type,
                    'product_id': product_id,
                    'warehouse_id': warehouse_id,
                    'quantity': abs(quantity),  # Positive for stock in
                    'batch_no': batch_no,
                    'expired_date': expired_date,
                    'ref_type': reference_type,
                    'ref_id': reference_id,
                    'created_by': created_by
                })
                
                return result.lastrowid
                
            except Exception as e:
                logger.error(f"Error recording stock in: {e}")
                raise
    
    def update_batch_remain(self, inventory_history_id: int, 
                           quantity_used: float) -> bool:
        """Update batch remaining quantity after issue"""
        with self.engine.begin() as conn:
            try:
                query = text("""
                    UPDATE inventory_histories
                    SET remain = GREATEST(0, remain - :quantity),
                        updated_date = NOW()
                    WHERE id = :id
                """)
                
                result = conn.execute(query, {
                    'quantity': abs(quantity_used),
                    'id': inventory_history_id
                })
                
                return result.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error updating batch remain: {e}")
                return False
    
    # ==================== Warehouse Methods ====================
    
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
    
    # ==================== Expiry Analysis ====================
    
    def get_expiring_items(self, days_ahead: int = 30,
                          warehouse_id: Optional[int] = None) -> pd.DataFrame:
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
                    WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY) THEN 'CRITICAL'
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
        """
        
        params = [self.expiry_critical_days, 
                 self.expiry_warning_days,
                 days_ahead]
        
        if warehouse_id:
            query += " AND ih.warehouse_id = %s"
            params.append(warehouse_id)
        
        query += """
            GROUP BY p.name, p.pt_code, ih.batch_no, ih.expired_date, w.name
            ORDER BY ih.expired_date ASC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params))
        except Exception as e:
            logger.error(f"Error getting expiring items: {e}")
            return pd.DataFrame()
    
    # ==================== Batch Info ====================
    
    def get_batch_info(self, batch_no: str) -> Optional[Dict[str, Any]]:
        """Get batch information"""
        query = """
            SELECT 
                ih.batch_no,
                ih.product_id,
                p.name as product_name,
                p.pt_code as product_code,
                ih.warehouse_id,
                w.name as warehouse_name,
                SUM(ih.remain) as current_qty,
                ih.expired_date,
                MIN(ih.created_date) as created_date
            FROM inventory_histories ih
            JOIN products p ON ih.product_id = p.id
            JOIN warehouses w ON ih.warehouse_id = w.id
            WHERE ih.batch_no = %s
                AND ih.delete_flag = 0
            GROUP BY 
                ih.batch_no, ih.product_id, p.name, p.pt_code,
                ih.warehouse_id, w.name, ih.expired_date
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(batch_no,))
            
            if not result.empty:
                batch_data = result.iloc[0].to_dict()
                
                # Add expiry status
                if batch_data['expired_date']:
                    days_to_expiry = (batch_data['expired_date'] - date.today()).days
                    if days_to_expiry < 0:
                        batch_data['expiry_status'] = ExpiryStatus.EXPIRED.value
                    elif days_to_expiry <= self.expiry_critical_days:
                        batch_data['expiry_status'] = ExpiryStatus.CRITICAL.value
                    elif days_to_expiry <= self.expiry_warning_days:
                        batch_data['expiry_status'] = ExpiryStatus.WARNING.value
                    else:
                        batch_data['expiry_status'] = ExpiryStatus.OK.value
                else:
                    batch_data['expiry_status'] = ExpiryStatus.OK.value
                
                return batch_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting batch info: {e}")
            return None