# utils/production/inventory.py
"""
Inventory Management for Production
Stock queries, FEFO logic, and inventory transactions with alternatives support
BACKWARD COMPATIBLE - Does not require is_primary column
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
    """Inventory Management for Production with Alternatives Support"""
    
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
    
    def check_material_availability(self, bom_id: int, quantity: float, 
                                   warehouse_id: int) -> pd.DataFrame:
        """
        Check material availability for a BOM including alternatives
        All materials in bom_details are primary materials
        
        Args:
            bom_id: BOM header ID
            quantity: Planned production quantity
            warehouse_id: Source warehouse ID
            
        Returns:
            DataFrame with material availability status including alternatives
        """
        query = """
            SELECT 
                d.id as bom_detail_id,
                d.material_id,
                p.name as material_name,
                d.quantity * %s / h.output_qty * (1 + d.scrap_rate/100) as required_qty,
                d.uom,
                COALESCE(SUM(ih.remain), 0) as available_qty,
                CASE 
                    WHEN COALESCE(SUM(ih.remain), 0) >= 
                         d.quantity * %s / h.output_qty * (1 + d.scrap_rate/100)
                    THEN 'SUFFICIENT'
                    WHEN COALESCE(SUM(ih.remain), 0) > 0
                    THEN 'PARTIAL'
                    ELSE 'INSUFFICIENT'
                END as availability_status
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            JOIN products p ON d.material_id = p.id
            LEFT JOIN inventory_histories ih 
                ON ih.product_id = d.material_id 
                AND ih.warehouse_id = %s
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE h.id = %s
            GROUP BY d.id, d.material_id, p.name, d.quantity, d.uom, 
                     d.scrap_rate, h.output_qty
            ORDER BY p.name
        """
        
        try:
            df = pd.read_sql(query, self.engine, 
                           params=(quantity, quantity, warehouse_id, bom_id))
            
            # For materials with insufficient stock, check alternatives
            for idx, row in df.iterrows():
                if row['availability_status'] != 'SUFFICIENT':
                    alternatives = self.get_alternative_availability(
                        row['bom_detail_id'], 
                        row['required_qty'] - row['available_qty'],
                        warehouse_id
                    )
                    if not alternatives.empty:
                        df.at[idx, 'has_alternatives'] = True
                        df.at[idx, 'alternative_count'] = len(alternatives)
                    else:
                        df.at[idx, 'has_alternatives'] = False
                        df.at[idx, 'alternative_count'] = 0
                else:
                    df.at[idx, 'has_alternatives'] = False
                    df.at[idx, 'alternative_count'] = 0
            
            return df
            
        except Exception as e:
            logger.error(f"Error checking material availability for BOM {bom_id}: {e}")
            return pd.DataFrame()
    
    def get_alternative_availability(self, bom_detail_id: int, 
                                    required_qty: float,
                                    warehouse_id: int) -> pd.DataFrame:
        """
        Get available alternatives for a BOM detail
        
        Args:
            bom_detail_id: Primary material's BOM detail ID
            required_qty: Quantity needed
            warehouse_id: Warehouse to check
            
        Returns:
            DataFrame with alternative materials and their availability
        """
        query = """
            SELECT 
                alt.id as alternative_id,
                alt.alternative_material_id,
                p.name as alternative_material_name,
                alt.quantity,
                alt.uom,
                alt.scrap_rate,
                alt.priority,
                COALESCE(SUM(ih.remain), 0) as available_qty,
                CASE 
                    WHEN COALESCE(SUM(ih.remain), 0) >= %s
                    THEN 'SUFFICIENT'
                    WHEN COALESCE(SUM(ih.remain), 0) > 0
                    THEN 'PARTIAL'
                    ELSE 'INSUFFICIENT'
                END as availability_status
            FROM bom_material_alternatives alt
            JOIN products p ON alt.alternative_material_id = p.id
            LEFT JOIN inventory_histories ih 
                ON ih.product_id = alt.alternative_material_id
                AND ih.warehouse_id = %s
                AND ih.remain > 0
                AND ih.delete_flag = 0
            WHERE alt.bom_detail_id = %s
                AND alt.is_active = 1
            GROUP BY alt.id, alt.alternative_material_id, p.name, 
                     alt.quantity, alt.uom, alt.scrap_rate, alt.priority
            ORDER BY alt.priority ASC
        """
        
        try:
            df = pd.read_sql(query, self.engine, 
                           params=(required_qty, warehouse_id, bom_detail_id))
            logger.info(f"Found {len(df)} active alternatives for BOM detail {bom_detail_id}")
            return df
        except Exception as e:
            logger.error(f"Error getting alternatives for BOM detail {bom_detail_id}: {e}")
            return pd.DataFrame()
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get active warehouses"""
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
    
    def get_material_stock_summary(self, bom_id: int, warehouse_id: int,
                                   quantity: float) -> Dict[str, any]:
        """
        Get comprehensive stock summary for BOM materials including alternatives
        
        Args:
            bom_id: BOM header ID
            warehouse_id: Source warehouse ID
            quantity: Planned production quantity
            
        Returns:
            Dictionary with summary information
        """
        availability = self.check_material_availability(bom_id, quantity, warehouse_id)
        
        if availability.empty:
            return {
                'all_sufficient': False,
                'total_materials': 0,
                'sufficient_materials': 0,
                'insufficient_materials': 0,
                'materials_with_alternatives': 0,
                'details': []
            }
        
        sufficient = len(availability[availability['availability_status'] == 'SUFFICIENT'])
        insufficient = len(availability[availability['availability_status'] != 'SUFFICIENT'])
        with_alternatives = len(availability[availability.get('has_alternatives', False) == True])
        
        return {
            'all_sufficient': insufficient == 0,
            'total_materials': len(availability),
            'sufficient_materials': sufficient,
            'insufficient_materials': insufficient,
            'materials_with_alternatives': with_alternatives,
            'details': availability.to_dict('records')
        }