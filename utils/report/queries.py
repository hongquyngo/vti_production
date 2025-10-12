# utils/report/queries.py
"""
Report Queries and Data Preparation
All SQL queries for production reports and analytics
"""

import logging
from datetime import date
from typing import Optional, Dict, Any, List
import pandas as pd

from ..db import get_db_engine

logger = logging.getLogger(__name__)


class ReportQueries:
    """Centralized report queries"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Production Dashboard ====================
    
    def get_production_orders(self, from_date: date, to_date: date) -> pd.DataFrame:
        """Get production orders for dashboard"""
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
                b.bom_type,
                w1.name as warehouse_name,
                w2.name as target_warehouse_name
            FROM manufacturing_orders o
            JOIN products p ON o.product_id = p.id
            JOIN bom_headers b ON o.bom_header_id = b.id
            JOIN warehouses w1 ON o.warehouse_id = w1.id
            JOIN warehouses w2 ON o.target_warehouse_id = w2.id
            WHERE o.order_date BETWEEN %s AND %s
                AND o.delete_flag = 0
            ORDER BY o.order_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(from_date, to_date))
        except Exception as e:
            logger.error(f"Error getting production orders: {e}")
            return pd.DataFrame()
    
    # ==================== Material Usage Analysis ====================
    
    def get_material_usage_tracking(self, order_id: Optional[int] = None,
                                   material_filter: str = "",
                                   usage_status: str = "All") -> pd.DataFrame:
        """Query v_material_usage_tracking view"""
        query = "SELECT * FROM v_material_usage_tracking WHERE 1=1"
        params = []
        
        if order_id:
            query += " AND mo_id = %s"
            params.append(order_id)
        
        if material_filter:
            query += " AND material_name LIKE %s"
            params.append(f"%{material_filter}%")
        
        if usage_status != "All":
            query += " AND usage_status = %s"
            params.append(usage_status)
        
        query += " ORDER BY order_no, material_name"
        
        try:
            return pd.read_sql(query, self.engine, params=tuple(params) if params else None)
        except Exception as e:
            logger.error(f"Error getting material usage tracking: {e}")
            return pd.DataFrame()
    
    # ==================== Efficiency Metrics ====================
    
    def get_production_efficiency(self, from_date: date, to_date: date) -> pd.DataFrame:
        """Query v_production_efficiency view"""
        query = """
            SELECT * FROM v_production_efficiency 
            WHERE order_date BETWEEN %s AND %s
            ORDER BY production_efficiency_pct DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(from_date, to_date))
        except Exception as e:
            logger.error(f"Error getting production efficiency: {e}")
            return pd.DataFrame()
    
    # ==================== Batch Tracking ====================
    
    def get_batch_info(self, batch_no: str) -> Optional[Dict[str, Any]]:
        """Get batch information and traceability"""
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
                MIN(ih.created_date) as created_date,
                CASE 
                    WHEN ih.expired_date IS NULL THEN 'OK'
                    WHEN ih.expired_date < CURDATE() THEN 'EXPIRED'
                    WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL 7 DAY) THEN 'CRITICAL'
                    WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'WARNING'
                    ELSE 'OK'
                END as expiry_status,
                DATEDIFF(ih.expired_date, CURDATE()) as days_to_expiry
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
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting batch info: {e}")
            return None
    
    def get_production_order_efficiency(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get efficiency metrics for specific order"""
        query = """
            SELECT 
                mo.id as order_id,
                mo.order_no,
                mo.planned_qty,
                mo.produced_qty,
                CASE 
                    WHEN mo.planned_qty > 0 
                    THEN ROUND((mo.produced_qty / mo.planned_qty * 100), 2)
                    ELSE 0 
                END as production_efficiency_pct,
                mo.status,
                mo.scheduled_date,
                mo.completion_date,
                DATEDIFF(mo.completion_date, mo.scheduled_date) as days_variance
            FROM manufacturing_orders mo
            WHERE mo.id = %s AND mo.delete_flag = 0
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            if result.empty:
                return None
            
            order_data = result.iloc[0].to_dict()
            
            # Get material details
            material_query = """
                SELECT 
                    p.name as material_name,
                    mom.required_qty,
                    COALESCE(mom.issued_qty, 0) as issued_qty,
                    COALESCE(returns.returned_qty, 0) as returned_qty,
                    COALESCE(mom.issued_qty, 0) - COALESCE(returns.returned_qty, 0) as actual_used_qty,
                    CASE 
                        WHEN mom.required_qty > 0 
                        THEN ROUND(((COALESCE(mom.issued_qty, 0) - COALESCE(returns.returned_qty, 0)) / mom.required_qty * 100), 2)
                        ELSE 0 
                    END as usage_efficiency_pct
                FROM manufacturing_order_materials mom
                JOIN products p ON p.id = mom.material_id
                LEFT JOIN (
                    SELECT 
                        mr.manufacturing_order_id,
                        mrd.material_id,
                        SUM(mrd.quantity) as returned_qty
                    FROM material_return_details mrd
                    JOIN material_returns mr ON mr.id = mrd.material_return_id
                    WHERE mr.status = 'CONFIRMED'
                    GROUP BY mr.manufacturing_order_id, mrd.material_id
                ) returns ON returns.manufacturing_order_id = mom.manufacturing_order_id
                    AND returns.material_id = mom.material_id
                WHERE mom.manufacturing_order_id = %s
            """
            
            materials = pd.read_sql(material_query, self.engine, params=(order_id,))
            order_data['material_details'] = materials.to_dict('records') if not materials.empty else []
            
            # Calculate material efficiency
            if not materials.empty and materials['usage_efficiency_pct'].notna().any():
                order_data['material_efficiency_pct'] = materials['usage_efficiency_pct'].mean()
            else:
                order_data['material_efficiency_pct'] = None
            
            return order_data
            
        except Exception as e:
            logger.error(f"Error getting order efficiency: {e}")
            return None
    
    def get_product_stock_by_batches(self, product_id: int) -> pd.DataFrame:
        """Get current stock by batches for a product"""
        query = """
            SELECT 
                ih.batch_no,
                ih.remain as quantity,
                ih.expired_date,
                w.name as warehouse,
                ih.created_date,
                CASE 
                    WHEN ih.expired_date < CURDATE() THEN 'EXPIRED'
                    WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'WARNING'
                    ELSE 'OK'
                END as status
            FROM inventory_histories ih
            JOIN warehouses w ON ih.warehouse_id = w.id
            WHERE ih.product_id = %s
                AND ih.remain > 0
                AND ih.delete_flag = 0
            ORDER BY ih.expired_date ASC, ih.created_date ASC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(product_id,))
        except Exception as e:
            logger.error(f"Error getting product stock: {e}")
            return pd.DataFrame()
    
    # ==================== Inventory Impact ====================
    
    def get_inventory_movements(self, from_date: date, to_date: date) -> pd.DataFrame:
        """Get inventory movements for production"""
        query = """
            SELECT 
                p.name as product_name,
                p.pt_code as product_code,
                ih.type as transaction_type,
                DATE(ih.created_date) as date,
                SUM(CASE 
                    WHEN ih.type IN ('stockInProduction', 'stockInProductionReturn') 
                    THEN ih.quantity 
                    WHEN ih.type = 'stockOutProduction' 
                    THEN -ih.quantity 
                    ELSE 0 
                END) as net_quantity,
                COUNT(DISTINCT ih.batch_no) as batch_count,
                w.name as warehouse
            FROM inventory_histories ih
            JOIN products p ON ih.product_id = p.id
            JOIN warehouses w ON ih.warehouse_id = w.id
            WHERE ih.type IN ('stockOutProduction', 'stockInProduction', 'stockInProductionReturn')
                AND DATE(ih.created_date) BETWEEN %s AND %s
                AND ih.delete_flag = 0
            GROUP BY p.id, p.name, p.pt_code, ih.type, DATE(ih.created_date), w.name
            ORDER BY DATE(ih.created_date) DESC, ABS(net_quantity) DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(from_date, to_date))
        except Exception as e:
            logger.error(f"Error getting inventory movements: {e}")
            return pd.DataFrame()
    
    # ==================== Return Analysis ====================
    
    def get_material_return_analysis(self, from_date: date, to_date: date) -> pd.DataFrame:
        """Query v_material_return_analysis view"""
        query = """
            SELECT * FROM v_material_return_analysis
            WHERE order_id IN (
                SELECT id FROM manufacturing_orders
                WHERE order_date BETWEEN %s AND %s
                    AND delete_flag = 0
            )
            ORDER BY return_rate_pct DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(from_date, to_date))
        except Exception as e:
            logger.error(f"Error getting return analysis: {e}")
            return pd.DataFrame()
    
    # ==================== Summary Statistics ====================
    
    def get_production_summary(self, from_date: date, to_date: date) -> Dict[str, Any]:
        """Get production summary statistics"""
        try:
            # Orders summary
            orders_query = """
                SELECT 
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_orders,
                    SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress_orders,
                    SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_orders,
                    AVG(CASE WHEN status = 'COMPLETED' AND planned_qty > 0 
                        THEN produced_qty / planned_qty * 100 ELSE NULL END) as avg_completion_rate
                FROM manufacturing_orders
                WHERE order_date BETWEEN %s AND %s
                    AND delete_flag = 0
            """
            
            orders_stats = pd.read_sql(orders_query, self.engine, params=(from_date, to_date))
            
            return {
                'period': {
                    'from_date': from_date.isoformat(),
                    'to_date': to_date.isoformat()
                },
                'orders': orders_stats.iloc[0].to_dict() if not orders_stats.empty else {}
            }
            
        except Exception as e:
            logger.error(f"Error getting production summary: {e}")
            return {}


# ==================== Helper Functions ====================

def get_orders_for_period(from_date: date, to_date: date, 
                         status: Optional[str] = None) -> pd.DataFrame:
    """Get orders for a specific period"""
    engine = get_db_engine()
    
    query = """
        SELECT 
            o.id,
            o.order_no,
            o.order_date,
            o.status,
            o.priority,
            o.planned_qty,
            o.produced_qty,
            p.name as product_name,
            b.bom_type
        FROM manufacturing_orders o
        JOIN products p ON o.product_id = p.id
        JOIN bom_headers b ON o.bom_header_id = b.id
        WHERE o.order_date BETWEEN %s AND %s
            AND o.delete_flag = 0
    """
    
    params = [from_date, to_date]
    
    if status:
        query += " AND o.status = %s"
        params.append(status)
    
    query += " ORDER BY o.order_date DESC"
    
    try:
        return pd.read_sql(query, engine, params=tuple(params))
    except Exception as e:
        logger.error(f"Error getting orders: {e}")
        return pd.DataFrame()


def get_products_list() -> pd.DataFrame:
    """Get products list for report filters"""
    engine = get_db_engine()
    
    query = """
        SELECT 
            id, 
            name, 
            pt_code as code
        FROM products 
        WHERE delete_flag = 0 
            AND approval_status = 1
        ORDER BY name
    """
    
    try:
        return pd.read_sql(query, engine)
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return pd.DataFrame()