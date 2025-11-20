# utils/production/receipts.py
"""
Production Receipts Manager - Extracted from Production_Receipts page
For use as utility in Production module

Version 1.0 - Refactored for UI/UX improvement
"""

import pandas as pd
from datetime import date
from typing import Optional, Dict, Any
import logging

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


class ProductionReceiptManager:
    """Manager for production receipts queries"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    def get_receipts(self, from_date: Optional[date] = None,
                    to_date: Optional[date] = None,
                    quality_status: Optional[str] = None,
                    product_id: Optional[int] = None,
                    warehouse_id: Optional[int] = None,
                    order_no: Optional[str] = None,
                    batch_no: Optional[str] = None,
                    order_id: Optional[int] = None) -> pd.DataFrame:
        """Get production receipts with filters"""
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                DATE(pr.receipt_date) as receipt_date,
                pr.manufacturing_order_id,
                mo.order_no,
                pr.product_id,
                p.name as product_name,
                p.package_size,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                DATE(pr.expired_date) as expired_date,
                pr.warehouse_id,
                w.name as warehouse_name,
                pr.quality_status,
                pr.notes,
                mo.planned_qty,
                mo.produced_qty,
                ROUND((pr.quantity / mo.planned_qty * 100), 1) as yield_rate,
                mo.scheduled_date,
                DATE(mo.completion_date) as completion_date,
                DATEDIFF(mo.completion_date, mo.scheduled_date) as production_days,
                pr.created_by,
                pr.created_date
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN products p ON pr.product_id = p.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            WHERE 1=1
        """
        
        params = []
        
        if order_id:
            query += " AND mo.id = %s"
            params.append(order_id)
        
        if from_date:
            query += " AND DATE(pr.receipt_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(pr.receipt_date) <= %s"
            params.append(to_date)
        
        if quality_status and quality_status != "All":
            query += " AND pr.quality_status = %s"
            params.append(quality_status)
        
        if product_id:
            query += " AND pr.product_id = %s"
            params.append(product_id)
        
        if warehouse_id:
            query += " AND pr.warehouse_id = %s"
            params.append(warehouse_id)
        
        if order_no:
            query += " AND mo.order_no LIKE %s"
            params.append(f"%{order_no}%")
        
        if batch_no:
            query += " AND pr.batch_no LIKE %s"
            params.append(f"%{batch_no}%")
        
        query += " ORDER BY pr.receipt_date DESC, pr.created_date DESC"
        
        try:
            df = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return df
        except Exception as e:
            logger.error(f"Error getting production receipts: {e}")
            return pd.DataFrame()
    
    def get_receipt_details(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific receipt"""
        query = """
            SELECT 
                pr.*,
                mo.order_no,
                mo.order_date,
                mo.bom_header_id,
                mo.planned_qty,
                mo.produced_qty,
                mo.scheduled_date,
                mo.completion_date,
                mo.priority,
                mo.notes as order_notes,
                mo.warehouse_id as source_warehouse_id,
                mo.target_warehouse_id,
                mo.status as order_status,
                p.name as product_name,
                p.description as product_description,
                p.package_size,
                p.pt_code,
                b.bom_name,
                b.bom_type,
                w.name as warehouse_name,
                w.address as warehouse_address,
                sw.name as source_warehouse_name,
                ROUND((pr.quantity / mo.planned_qty * 100), 1) as yield_rate,
                (mo.planned_qty - pr.quantity) as scrap_qty,
                DATEDIFF(mo.completion_date, mo.scheduled_date) as production_days
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN products p ON pr.product_id = p.id
            JOIN bom_headers b ON mo.bom_header_id = b.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            JOIN warehouses sw ON mo.warehouse_id = sw.id
            WHERE pr.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(receipt_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting receipt details for {receipt_id}: {e}")
            return None
    
    def get_receipt_materials(self, manufacturing_order_id: int) -> pd.DataFrame:
        """Get materials used for this production order"""
        query = """
            SELECT 
                mid.material_id,
                p.name as material_name,
                p.pt_code,
                mid.batch_no,
                SUM(mid.quantity) as quantity_used,
                mid.uom,
                DATE(mid.expired_date) as expired_date,
                mi.issue_no,
                DATE(mi.issue_date) as issue_date,
                w.name as source_warehouse
            FROM material_issue_details mid
            JOIN material_issues mi ON mid.material_issue_id = mi.id
            JOIN products p ON mid.material_id = p.id
            JOIN warehouses w ON mi.warehouse_id = w.id
            WHERE mi.manufacturing_order_id = %s
                AND mi.status = 'CONFIRMED'
            GROUP BY 
                mid.material_id, p.name, p.pt_code, mid.batch_no, 
                mid.uom, mid.expired_date, mi.issue_no, mi.issue_date, w.name
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(manufacturing_order_id,))
        except Exception as e:
            logger.error(f"Error getting receipt materials: {e}")
            return pd.DataFrame()
    
    def get_inventory_impact(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        """Get inventory impact of this receipt"""
        query = """
            SELECT 
                ih.id as inventory_history_id,
                ih.quantity as stock_in_qty,
                ih.remain as current_remain,
                DATE(ih.created_date) as stock_in_date,
                ih.warehouse_id,
                w.name as warehouse_name,
                -- Calculate current stock level for this product
                (SELECT COALESCE(SUM(remain), 0) 
                 FROM inventory_histories 
                 WHERE product_id = pr.product_id 
                   AND warehouse_id = ih.warehouse_id 
                   AND delete_flag = 0
                   AND remain > 0) as current_stock_level,
                -- Location info
                COALESCE(CONCAT(z.name, '-', r.name, '-', b.name), 'Not assigned') as location
            FROM production_receipts pr
            JOIN inventory_histories ih 
                ON ih.action_detail_id = pr.id 
                AND ih.type = 'stockInProduction'
                AND ih.delete_flag = 0
            JOIN warehouses w ON ih.warehouse_id = w.id
            LEFT JOIN zone_locations z ON ih.zone_id = z.id
            LEFT JOIN rack_locations r ON ih.rack_id = r.id
            LEFT JOIN bin_locations b ON ih.bin_id = b.id
            WHERE pr.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(receipt_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting inventory impact: {e}")
            return None
    
    def get_products(self) -> pd.DataFrame:
        """Get all products for filter"""
        query = """
            SELECT DISTINCT
                p.id,
                p.name,
                p.pt_code
            FROM products p
            JOIN production_receipts pr ON p.id = pr.product_id
            WHERE p.delete_flag = 0
            ORDER BY p.name
        """
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting products: {e}")
            return pd.DataFrame()
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get all warehouses for filter"""
        query = """
            SELECT 
                id,
                name
            FROM warehouses
            WHERE delete_flag = 0
            ORDER BY name
        """
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
            return pd.DataFrame()
    
    def update_quality_status(self, receipt_id: int, new_status: str, 
                            notes: Optional[str] = None, 
                            user_id: Optional[int] = None) -> bool:
        """Update quality status of a receipt"""
        from sqlalchemy import text
        
        with self.engine.begin() as conn:
            try:
                query = text("""
                    UPDATE production_receipts
                    SET quality_status = :status,
                        notes = CASE 
                            WHEN :notes IS NOT NULL THEN :notes 
                            ELSE notes 
                        END,
                        created_date = created_date
                    WHERE id = :receipt_id
                """)
                
                result = conn.execute(query, {
                    'status': new_status,
                    'notes': notes,
                    'receipt_id': receipt_id
                })
                
                success = result.rowcount > 0
                if success:
                    logger.info(f"Updated receipt {receipt_id} quality to {new_status}")
                return success
                
            except Exception as e:
                logger.error(f"Error updating quality status: {e}")
                raise
    
    def get_receipts_summary(self, from_date: Optional[date] = None,
                            to_date: Optional[date] = None) -> Dict[str, Any]:
        """Get summary statistics for receipts"""
        receipts = self.get_receipts(from_date=from_date, to_date=to_date)
        
        if receipts.empty:
            return {
                'total_receipts': 0,
                'total_quantity': 0,
                'pass_rate': 0,
                'avg_yield': 0,
                'passed_count': 0,
                'pending_count': 0,
                'failed_count': 0
            }
        
        total = len(receipts)
        passed = len(receipts[receipts['quality_status'] == 'PASSED'])
        pending = len(receipts[receipts['quality_status'] == 'PENDING'])
        failed = len(receipts[receipts['quality_status'] == 'FAILED'])
        
        return {
            'total_receipts': total,
            'total_quantity': receipts['quantity'].sum(),
            'pass_rate': (passed / total * 100) if total > 0 else 0,
            'avg_yield': receipts['yield_rate'].mean() if not receipts.empty else 0,
            'passed_count': passed,
            'pending_count': pending,
            'failed_count': failed
        }