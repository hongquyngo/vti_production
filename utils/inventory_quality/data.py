# utils/inventory_quality/data.py
"""
Data loading functions for Inventory Quality module
Loads data from inventory_quality_unified_view and related tables

Version: 1.0.0
"""

import logging
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import streamlit as st
from sqlalchemy import text

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


class InventoryQualityData:
    """Data access layer for Inventory Quality module"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Main Data Loading ====================
    
    @st.cache_data(ttl=300, show_spinner=False)
    def get_unified_inventory(_self, 
                              category: Optional[str] = None,
                              warehouse_id: Optional[int] = None,
                              product_search: Optional[str] = None) -> pd.DataFrame:
        """
        Get unified inventory data from all categories
        
        Args:
            category: Filter by category (GOOD, QUARANTINE, DEFECTIVE) or None for all
            warehouse_id: Filter by warehouse ID or None for all
            product_search: Search string for product name/code
        
        Returns:
            DataFrame with unified inventory data
        """
        try:
            query = """
                SELECT * FROM inventory_quality_unified_view
                WHERE 1=1
            """
            params = {}
            
            if category and category != 'All':
                query += " AND category = :category"
                params['category'] = category
            
            if warehouse_id:
                query += " AND warehouse_id = :warehouse_id"
                params['warehouse_id'] = warehouse_id
            
            if product_search:
                query += " AND (product_name LIKE :search OR pt_code LIKE :search OR legacy_pt_code LIKE :search OR package_size LIKE :search)"
                params['search'] = f"%{product_search}%"
            
            query += " ORDER BY category, product_name, batch_number"
            
            with _self.engine.connect() as conn:
                df = pd.read_sql(text(query), conn, params=params)
            
            return df
            
        except Exception as e:
            logger.error(f"Error loading unified inventory: {e}")
            return pd.DataFrame()
    
    @st.cache_data(ttl=300, show_spinner=False)
    def get_summary_metrics(_self) -> Dict[str, Any]:
        """
        Get summary metrics for dashboard cards
        
        Returns:
            Dict with counts and values by category
        """
        try:
            query = """
                SELECT 
                    category,
                    COUNT(*) as item_count,
                    SUM(quantity) as total_quantity,
                    SUM(COALESCE(inventory_value_usd, 0)) as total_value
                FROM inventory_quality_unified_view
                GROUP BY category
            """
            
            with _self.engine.connect() as conn:
                result = conn.execute(text(query))
                rows = result.fetchall()
            
            metrics = {
                'GOOD': {'count': 0, 'quantity': 0, 'value': 0},
                'QUARANTINE': {'count': 0, 'quantity': 0, 'value': 0},
                'DEFECTIVE': {'count': 0, 'quantity': 0, 'value': 0}
            }
            
            for row in rows:
                category = row[0]
                if category in metrics:
                    metrics[category] = {
                        'count': int(row[1] or 0),
                        'quantity': float(row[2] or 0),
                        'value': float(row[3] or 0)
                    }
            
            # Calculate totals
            metrics['TOTAL'] = {
                'count': sum(m['count'] for m in metrics.values() if isinstance(m, dict) and 'count' in m),
                'quantity': sum(m['quantity'] for m in metrics.values() if isinstance(m, dict) and 'quantity' in m),
                'value': sum(m['value'] for m in metrics.values() if isinstance(m, dict) and 'value' in m)
            }
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error loading summary metrics: {e}")
            return {
                'GOOD': {'count': 0, 'quantity': 0, 'value': 0},
                'QUARANTINE': {'count': 0, 'quantity': 0, 'value': 0},
                'DEFECTIVE': {'count': 0, 'quantity': 0, 'value': 0},
                'TOTAL': {'count': 0, 'quantity': 0, 'value': 0}
            }
    
    @st.cache_data(ttl=300, show_spinner=False)
    def get_expiry_metrics(_self, near_expiry_days: int = 90) -> Dict[str, Any]:
        """
        Get expiry-related value metrics for dashboard.
        
        Breaks down GOOD inventory value by expiry status:
        - expired: expiry_date < today
        - near_expiry: expiry_date between today and today + N days
        - healthy: not expired and not near expiry
        
        Args:
            near_expiry_days: Number of days threshold for near-expiry warning
        
        Returns:
            Dict with expired/near_expiry/healthy counts and values
        """
        try:
            query = """
                SELECT 
                    -- Expired items (GOOD category, past expiry date)
                    SUM(CASE 
                        WHEN category = 'GOOD' 
                             AND expiry_date IS NOT NULL 
                             AND expiry_date < CURDATE()
                        THEN 1 ELSE 0 END) AS expired_count,
                    SUM(CASE 
                        WHEN category = 'GOOD' 
                             AND expiry_date IS NOT NULL 
                             AND expiry_date < CURDATE()
                        THEN COALESCE(inventory_value_usd, 0) ELSE 0 END) AS expired_value,
                    SUM(CASE 
                        WHEN category = 'GOOD' 
                             AND expiry_date IS NOT NULL 
                             AND expiry_date < CURDATE()
                        THEN quantity ELSE 0 END) AS expired_qty,
                    
                    -- Near expiry items (GOOD, expiry within N days from today)
                    SUM(CASE 
                        WHEN category = 'GOOD' 
                             AND expiry_date IS NOT NULL 
                             AND expiry_date >= CURDATE()
                             AND expiry_date <= DATE_ADD(CURDATE(), INTERVAL :near_days DAY)
                        THEN 1 ELSE 0 END) AS near_expiry_count,
                    SUM(CASE 
                        WHEN category = 'GOOD' 
                             AND expiry_date IS NOT NULL 
                             AND expiry_date >= CURDATE()
                             AND expiry_date <= DATE_ADD(CURDATE(), INTERVAL :near_days DAY)
                        THEN COALESCE(inventory_value_usd, 0) ELSE 0 END) AS near_expiry_value,
                    SUM(CASE 
                        WHEN category = 'GOOD' 
                             AND expiry_date IS NOT NULL 
                             AND expiry_date >= CURDATE()
                             AND expiry_date <= DATE_ADD(CURDATE(), INTERVAL :near_days DAY)
                        THEN quantity ELSE 0 END) AS near_expiry_qty,
                    
                    -- Total value (all categories)
                    SUM(COALESCE(inventory_value_usd, 0)) AS total_value,
                    COUNT(*) AS total_count
                    
                FROM inventory_quality_unified_view
            """
            
            with _self.engine.connect() as conn:
                result = conn.execute(text(query), {'near_days': near_expiry_days})
                row = result.fetchone()
            
            if row:
                expired_value = float(row[1] or 0)
                near_expiry_value = float(row[4] or 0)
                total_value = float(row[6] or 0)
                
                return {
                    'expired': {
                        'count': int(row[0] or 0),
                        'value': expired_value,
                        'quantity': float(row[2] or 0),
                    },
                    'near_expiry': {
                        'count': int(row[3] or 0),
                        'value': near_expiry_value,
                        'quantity': float(row[5] or 0),
                    },
                    'total_value': total_value,
                    'total_count': int(row[7] or 0),
                    'near_expiry_days': near_expiry_days,
                }
            
            return {
                'expired': {'count': 0, 'value': 0, 'quantity': 0},
                'near_expiry': {'count': 0, 'value': 0, 'quantity': 0},
                'total_value': 0,
                'total_count': 0,
                'near_expiry_days': near_expiry_days,
            }
            
        except Exception as e:
            logger.error(f"Error loading expiry metrics: {e}")
            return {
                'expired': {'count': 0, 'value': 0, 'quantity': 0},
                'near_expiry': {'count': 0, 'value': 0, 'quantity': 0},
                'total_value': 0,
                'total_count': 0,
                'near_expiry_days': near_expiry_days,
            }
    
    # ==================== Detail Data Loading ====================
    
    def get_good_item_detail(self, inventory_history_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed info for GOOD inventory item"""
        try:
            query = """
                SELECT * FROM inventory_detailed_view
                WHERE inventory_history_id = :id
            """
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query), {'id': inventory_history_id})
                row = result.fetchone()
            
            if row:
                return dict(zip(result.keys(), row))
            return None
            
        except Exception as e:
            logger.error(f"Error loading GOOD item detail: {e}")
            return None
    
    def get_quarantine_item_detail(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed info for QUARANTINE item (production receipt pending QC)"""
        try:
            query = """
                SELECT 
                    pr.id,
                    pr.receipt_no,
                    pr.receipt_date,
                    pr.product_id,
                    p.name as product_name,
                    p.pt_code,
                    p.description as product_description,
                    b.brand_name as brand,
                    pr.batch_no,
                    pr.quantity,
                    pr.uom,
                    pr.expired_date,
                    pr.warehouse_id,
                    wh.name as warehouse_name,
                    pr.quality_status,
                    pr.notes,
                    pr.created_date,
                    pr.created_by,
                    mo.id as manufacturing_order_id,
                    mo.order_no as manufacturing_order_no,
                    mo.planned_qty,
                    mo.produced_qty,
                    bh.bom_name,
                    DATEDIFF(CURDATE(), pr.created_date) as days_pending
                FROM production_receipts pr
                JOIN products p ON pr.product_id = p.id
                LEFT JOIN brands b ON p.brand_id = b.id
                LEFT JOIN warehouses wh ON pr.warehouse_id = wh.id
                LEFT JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
                LEFT JOIN bom_headers bh ON mo.bom_header_id = bh.id
                WHERE pr.id = :id AND pr.quality_status = 'PENDING'
            """
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query), {'id': receipt_id})
                row = result.fetchone()
            
            if row:
                return dict(zip(result.keys(), row))
            return None
            
        except Exception as e:
            logger.error(f"Error loading QUARANTINE item detail: {e}")
            return None
    
    def get_defective_item_detail(self, item_id: int, source_table: str) -> Optional[Dict[str, Any]]:
        """Get detailed info for DEFECTIVE item"""
        try:
            if source_table == 'production_receipts':
                query = """
                    SELECT 
                        pr.id,
                        'production_receipts' as source_table,
                        pr.receipt_no as reference_no,
                        pr.receipt_date as defect_date,
                        pr.product_id,
                        p.name as product_name,
                        p.pt_code,
                        b.brand_name as brand,
                        pr.batch_no,
                        pr.quantity,
                        pr.uom,
                        pr.expired_date,
                        pr.warehouse_id,
                        wh.name as warehouse_name,
                        'QC_FAILED' as defect_type,
                        pr.notes,
                        mo.order_no as manufacturing_order_no,
                        DATEDIFF(CURDATE(), pr.created_date) as days_since_defect
                    FROM production_receipts pr
                    JOIN products p ON pr.product_id = p.id
                    LEFT JOIN brands b ON p.brand_id = b.id
                    LEFT JOIN warehouses wh ON pr.warehouse_id = wh.id
                    LEFT JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
                    WHERE pr.id = :id AND pr.quality_status = 'FAILED'
                """
            else:  # material_return_details
                query = """
                    SELECT 
                        mrd.id,
                        'material_return_details' as source_table,
                        mr.return_no as reference_no,
                        mr.return_date as defect_date,
                        mrd.material_id as product_id,
                        p.name as product_name,
                        p.pt_code,
                        b.brand_name as brand,
                        mrd.batch_no,
                        mrd.quantity,
                        mrd.uom,
                        mrd.expired_date,
                        mr.warehouse_id,
                        wh.name as warehouse_name,
                        mrd.condition as defect_type,
                        mr.reason as notes,
                        mo.order_no as manufacturing_order_no,
                        mi.issue_no as original_issue_no,
                        DATEDIFF(CURDATE(), mr.created_date) as days_since_defect
                    FROM material_return_details mrd
                    JOIN material_returns mr ON mrd.material_return_id = mr.id
                    JOIN products p ON mrd.material_id = p.id
                    LEFT JOIN brands b ON p.brand_id = b.id
                    LEFT JOIN warehouses wh ON mr.warehouse_id = wh.id
                    LEFT JOIN manufacturing_orders mo ON mr.manufacturing_order_id = mo.id
                    LEFT JOIN material_issues mi ON mr.material_issue_id = mi.id
                    WHERE mrd.id = :id AND mrd.condition != 'GOOD'
                """
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query), {'id': item_id})
                row = result.fetchone()
            
            if row:
                return dict(zip(result.keys(), row))
            return None
            
        except Exception as e:
            logger.error(f"Error loading DEFECTIVE item detail: {e}")
            return None
    
    # ==================== Reference Data ====================
    
    @st.cache_data(ttl=600, show_spinner=False)
    def get_warehouses(_self) -> List[Dict[str, Any]]:
        """Get list of warehouses for filter"""
        try:
            query = """
                SELECT id, name
                FROM warehouses
                WHERE delete_flag = 0
                ORDER BY name
            """
            
            with _self.engine.connect() as conn:
                result = conn.execute(text(query))
                return [dict(zip(result.keys(), row)) for row in result.fetchall()]
            
        except Exception as e:
            logger.error(f"Error loading warehouses: {e}")
            return []
    
    @st.cache_data(ttl=600, show_spinner=False)
    def get_products(_self) -> List[Dict[str, Any]]:
        """Get list of products for filter"""
        try:
            query = """
                SELECT DISTINCT 
                    p.id, 
                    p.name,
                    p.pt_code
                FROM inventory_quality_unified_view iq
                JOIN products p ON iq.product_id = p.id
                ORDER BY p.name
            """
            
            with _self.engine.connect() as conn:
                result = conn.execute(text(query))
                return [dict(zip(result.keys(), row)) for row in result.fetchall()]
            
        except Exception as e:
            logger.error(f"Error loading products: {e}")
            return []
    
    # ==================== Period Summary ====================
    
    @st.cache_data(ttl=300, show_spinner=False)
    def get_inventory_period_summary(_self, 
                                      from_date,
                                      to_date,
                                      warehouse_id: Optional[int] = None,
                                      product_search: Optional[str] = None) -> pd.DataFrame:
        """
        Get inventory period summary (Tổng hợp tồn kho theo kỳ).
        
        Calculates opening balance, stock in, stock out, and closing balance
        for each product within the specified date range.
        
        Logic:
        - Stock In types: inventory_histories.type LIKE 'stockIn%'
        - Stock Out types: all other types
        - Opening = sum(stock_in before period) - sum(stock_out before period)
        - Closing = Opening + Period Stock In - Period Stock Out
        
        Args:
            from_date: Period start date
            to_date: Period end date
            warehouse_id: Filter by warehouse or None for all
            product_search: Search by product name/code
        
        Returns:
            DataFrame with columns: product_code, product_name, uom, 
            opening_qty, stock_in_qty, stock_out_qty, closing_qty
        """
        try:
            from datetime import timedelta
            to_date_next = to_date + timedelta(days=1)
            
            query = """
                SELECT 
                    ih.product_id,
                    p.pt_code AS product_code,
                    p.legacy_pt_code AS legacy_code,
                    p.name AS product_name,
                    p.uom,
                    p.package_size,
                    b.brand_name AS brand,
                    
                    ROUND(
                        COALESCE(SUM(CASE 
                            WHEN ih.type LIKE :sin_pattern 
                                 AND ih.created_date < :from_date 
                            THEN ih.quantity ELSE 0 END), 0)
                        - COALESCE(SUM(CASE 
                            WHEN ih.type NOT LIKE :sin_pattern 
                                 AND ih.created_date < :from_date 
                            THEN ih.quantity ELSE 0 END), 0)
                    , 5) AS opening_qty,
                    
                    ROUND(COALESCE(SUM(CASE 
                        WHEN ih.type LIKE :sin_pattern
                             AND ih.created_date >= :from_date 
                             AND ih.created_date < :to_date_next
                        THEN ih.quantity ELSE 0 END), 0), 5) AS stock_in_qty,
                    
                    ROUND(COALESCE(SUM(CASE 
                        WHEN ih.type NOT LIKE :sin_pattern
                             AND ih.created_date >= :from_date 
                             AND ih.created_date < :to_date_next
                        THEN ih.quantity ELSE 0 END), 0), 5) AS stock_out_qty
                    
                FROM inventory_histories ih
                JOIN products p ON ih.product_id = p.id
                LEFT JOIN brands b ON p.brand_id = b.id
                WHERE ih.delete_flag = 0
            """
            params = {
                'sin_pattern': 'stockIn%',
                'from_date': from_date,
                'to_date_next': to_date_next,
            }
            
            if warehouse_id:
                query += " AND ih.warehouse_id = :warehouse_id"
                params['warehouse_id'] = warehouse_id
            
            if product_search:
                query += " AND (p.name LIKE :search OR p.pt_code LIKE :search OR p.legacy_pt_code LIKE :search OR p.package_size LIKE :search)"
                params['search'] = f"%{product_search}%"
            
            query += """
                GROUP BY ih.product_id, p.pt_code, p.legacy_pt_code, p.name, p.uom, 
                         p.package_size, b.brand_name
                ORDER BY p.name
            """
            
            with _self.engine.connect() as conn:
                df = pd.read_sql(text(query), conn, params=params)
            
            if not df.empty:
                # Calculate closing balance
                df['closing_qty'] = df['opening_qty'] + df['stock_in_qty'] - df['stock_out_qty']
                
                # Filter out rows with no activity (all zeros)
                df = df[
                    (df['opening_qty'].abs() > 0.001) | 
                    (df['stock_in_qty'].abs() > 0.001) | 
                    (df['stock_out_qty'].abs() > 0.001)
                ].reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Error loading inventory period summary: {e}")
            return pd.DataFrame()
    
    # ==================== Period Detail ====================
    
    @st.cache_data(ttl=300, show_spinner=False)
    def get_product_period_detail(_self,
                                   product_id: int,
                                   from_date,
                                   to_date,
                                   warehouse_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get detailed stock in/out transactions for a specific product within a period.
        
        Joins to source tables to resolve reference numbers:
        - stockIn           → stock_in_details → arrival_details → purchase_orders (PO number)
        - stockInProduction → production_receipts (receipt_no) → manufacturing_orders
        - stockInProductionReturn → material_return_details → material_returns (return_no)
        - stockOutDelivery  → stock_out_delivery (dn_number) via delivery_id FK
        - stockOutProduction → material_issue_details → material_issues (issue_no)
        - stockOutWarehouseTransfer → stock_out_warehouse_transfer (transfer_number)
        - stockOutInternalUse → stock_out_internal_use (internal_use_number)
        
        Args:
            product_id: Product ID
            from_date: Period start date
            to_date: Period end date
            warehouse_id: Filter by warehouse or None for all
        
        Returns:
            DataFrame with individual transactions including reference_no, related_order
        """
        try:
            from datetime import timedelta
            to_date_next = to_date + timedelta(days=1)
            
            query = """
                SELECT 
                    ih.id,
                    ih.created_date AS transaction_date,
                    ih.type AS transaction_type,
                    CASE WHEN ih.type LIKE :sin_pattern 
                         THEN 'Stock In' ELSE 'Stock Out' END AS direction,
                    ih.quantity,
                    p.uom,
                    ih.batch_no,
                    wh.name AS warehouse_name,
                    
                    -- Reference number: pick the most meaningful doc number
                    COALESCE(
                        pr.receipt_no,
                        mr.return_no,
                        po.po_number,
                        a.arrival_note_number,
                        sod.dn_number,
                        mi.issue_no,
                        sowt.warehouse_transfer_number,
                        soiu.internal_use_number,
                        CASE WHEN ih.type = 'stockInOpeningBalance' 
                             THEN 'Opening Balance' ELSE NULL END
                    ) AS reference_no,
                    
                    -- Related manufacturing order (if applicable)
                    COALESCE(
                        mo_prod.order_no, 
                        mo_return.order_no, 
                        mo_issue.order_no
                    ) AS related_order,
                    
                    -- Created by (employee name)
                    CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
                    
                FROM inventory_histories ih
                JOIN products p ON ih.product_id = p.id
                LEFT JOIN warehouses wh ON ih.warehouse_id = wh.id
                LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
                
                -- === Stock In: Production Receipt ===
                LEFT JOIN production_receipts pr 
                    ON ih.action_detail_id = pr.id 
                   AND ih.type = 'stockInProduction'
                LEFT JOIN manufacturing_orders mo_prod 
                    ON pr.manufacturing_order_id = mo_prod.id
                
                -- === Stock In: Production Return ===
                LEFT JOIN material_return_details mrd 
                    ON ih.action_detail_id = mrd.id 
                   AND ih.type = 'stockInProductionReturn'
                LEFT JOIN material_returns mr 
                    ON mrd.material_return_id = mr.id
                LEFT JOIN manufacturing_orders mo_return 
                    ON mr.manufacturing_order_id = mo_return.id
                
                -- === Stock In: Purchase (PO traceability) ===
                LEFT JOIN stock_in_details sid 
                    ON ih.action_detail_id = sid.id 
                   AND ih.type = 'stockIn'
                LEFT JOIN arrival_details ad 
                    ON sid.arrival_detail_id = ad.id
                LEFT JOIN arrivals a 
                    ON ad.arrival_id = a.id
                LEFT JOIN purchase_orders po 
                    ON ad.purchase_order_id = po.id
                
                -- === Stock Out: Delivery ===
                LEFT JOIN stock_out_delivery sod 
                    ON ih.delivery_id = sod.id
                
                -- === Stock Out: Production (Material Issue) ===
                LEFT JOIN material_issue_details mid_out 
                    ON ih.action_detail_id = mid_out.id 
                   AND ih.type = 'stockOutProduction'
                LEFT JOIN material_issues mi 
                    ON mid_out.material_issue_id = mi.id
                LEFT JOIN manufacturing_orders mo_issue 
                    ON mi.manufacturing_order_id = mo_issue.id
                
                -- === Stock Out: Warehouse Transfer ===
                LEFT JOIN stock_out_warehouse_transfer sowt 
                    ON ih.warehouse_transfer_stock_out_id = sowt.id
                
                -- === Stock Out: Internal Use ===
                LEFT JOIN stock_out_internal_use soiu 
                    ON ih.internal_stock_out_id = soiu.id
                
                WHERE ih.product_id = :product_id
                  AND ih.delete_flag = 0
                  AND ih.created_date >= :from_date
                  AND ih.created_date < :to_date_next
            """
            params = {
                'sin_pattern': 'stockIn%',
                'product_id': product_id,
                'from_date': from_date,
                'to_date_next': to_date_next,
            }
            
            if warehouse_id:
                query += " AND ih.warehouse_id = :warehouse_id"
                params['warehouse_id'] = warehouse_id
            
            query += " ORDER BY ih.created_date, ih.id"
            
            with _self.engine.connect() as conn:
                df = pd.read_sql(text(query), conn, params=params)
            
            return df
            
        except Exception as e:
            logger.error(f"Error loading product period detail: {e}")
            return pd.DataFrame()
    
    # ==================== Reference Detail ====================
    
    def get_reference_detail(self, ih_id: int, transaction_type: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed reference document info for a specific inventory history record.
        Routes to the appropriate query based on transaction_type.
        
        Args:
            ih_id: inventory_histories.id
            transaction_type: ih.type value (e.g. 'stockIn', 'stockInProduction', etc.)
        
        Returns:
            Dict with reference detail fields, or None
        """
        try:
            query_map = {
                'stockIn': self._ref_query_purchase,
                'stockInProduction': self._ref_query_production_receipt,
                'stockInProductionReturn': self._ref_query_material_return,
                'stockInOpeningBalance': self._ref_query_opening_balance,
                'stockOutProduction': self._ref_query_material_issue,
                'stockOutDelivery': self._ref_query_delivery,
                'stockOutWarehouseTransfer': self._ref_query_warehouse_transfer,
                'stockOutInternalUse': self._ref_query_internal_use,
            }
            
            query_func = query_map.get(transaction_type)
            if not query_func:
                return {'_type': transaction_type, '_note': 'Detail not available for this transaction type'}
            
            return query_func(ih_id)
            
        except Exception as e:
            logger.error(f"Error loading reference detail: {e}", exc_info=True)
            return None
    
    def _ref_query_purchase(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Purchase stock-in detail: PO → Arrival → Stock In"""
        query = """
            SELECT 
                'Purchase' AS doc_type,
                po.po_number,
                po.po_date,
                po.po_type,
                po.external_ref_number,
                seller.english_name AS vendor_name,
                a.arrival_note_number,
                a.arrival_date,
                a.status AS arrival_status,
                a.landed_cost,
                lc_cur.code AS landed_cost_currency,
                a.ship_method,
                ad.arrival_quantity,
                sid.quantity AS stocked_in_qty,
                sid.batch_no,
                sid.exp_date,
                wh.name AS warehouse_name,
                CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
            FROM inventory_histories ih
            JOIN stock_in_details sid ON ih.action_detail_id = sid.id
            LEFT JOIN arrival_details ad ON sid.arrival_detail_id = ad.id
            LEFT JOIN arrivals a ON ad.arrival_id = a.id
            LEFT JOIN currencies lc_cur ON a.landed_cost_currency_id = lc_cur.id
            LEFT JOIN purchase_orders po ON ad.purchase_order_id = po.id
            LEFT JOIN companies seller ON po.seller_company_id = seller.id
            LEFT JOIN warehouses wh ON ih.warehouse_id = wh.id
            LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_production_receipt(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Production receipt detail"""
        query = """
            SELECT 
                'Production Receipt' AS doc_type,
                pr.receipt_no,
                pr.receipt_date,
                pr.quality_status,
                pr.defect_type,
                pr.batch_no,
                pr.quantity,
                pr.uom,
                pr.expired_date,
                pr.notes,
                p.name AS product_name,
                p.pt_code,
                mo.order_no AS mo_number,
                mo.planned_qty,
                mo.produced_qty,
                mo.status AS mo_status,
                bh.bom_name,
                wh.name AS warehouse_name,
                CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
            FROM inventory_histories ih
            JOIN production_receipts pr ON ih.action_detail_id = pr.id
            JOIN products p ON pr.product_id = p.id
            LEFT JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            LEFT JOIN bom_headers bh ON mo.bom_header_id = bh.id
            LEFT JOIN warehouses wh ON pr.warehouse_id = wh.id
            LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_material_return(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Material return detail"""
        query = """
            SELECT 
                'Material Return' AS doc_type,
                mr.return_no,
                mr.return_date,
                mr.status,
                mr.reason,
                mrd.batch_no,
                mrd.quantity,
                mrd.uom,
                mrd.condition,
                mrd.expired_date,
                p.name AS material_name,
                p.pt_code,
                mo.order_no AS mo_number,
                mi.issue_no AS original_issue_no,
                wh.name AS warehouse_name,
                CONCAT(ret_emp.first_name, ' ', ret_emp.last_name) AS returned_by_name,
                CONCAT(rec_emp.first_name, ' ', rec_emp.last_name) AS received_by_name
            FROM inventory_histories ih
            JOIN material_return_details mrd ON ih.action_detail_id = mrd.id
            JOIN material_returns mr ON mrd.material_return_id = mr.id
            JOIN products p ON mrd.material_id = p.id
            LEFT JOIN manufacturing_orders mo ON mr.manufacturing_order_id = mo.id
            LEFT JOIN material_issues mi ON mr.material_issue_id = mi.id
            LEFT JOIN warehouses wh ON mr.warehouse_id = wh.id
            LEFT JOIN employees ret_emp ON mr.returned_by = ret_emp.id
            LEFT JOIN employees rec_emp ON mr.received_by = rec_emp.id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_opening_balance(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Opening balance detail"""
        query = """
            SELECT 
                'Opening Balance' AS doc_type,
                ih.created_date,
                ih.quantity,
                ih.batch_no,
                p.name AS product_name,
                p.uom,
                wh.name AS warehouse_name,
                CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
            FROM inventory_histories ih
            JOIN products p ON ih.product_id = p.id
            LEFT JOIN warehouses wh ON ih.warehouse_id = wh.id
            LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_material_issue(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Material issue (stock out for production) detail"""
        query = """
            SELECT 
                'Material Issue' AS doc_type,
                mi.issue_no,
                mi.issue_date,
                mi.status,
                mi.notes,
                mid_out.batch_no,
                mid_out.quantity,
                mid_out.uom,
                mid_out.expired_date,
                mid_out.is_alternative,
                p.name AS material_name,
                p.pt_code,
                orig_p.name AS original_material_name,
                mo.order_no AS mo_number,
                mo.status AS mo_status,
                wh.name AS warehouse_name,
                CONCAT(issued_emp.first_name, ' ', issued_emp.last_name) AS issued_by_name,
                CONCAT(recv_emp.first_name, ' ', recv_emp.last_name) AS received_by_name
            FROM inventory_histories ih
            JOIN material_issue_details mid_out ON ih.action_detail_id = mid_out.id
            JOIN material_issues mi ON mid_out.material_issue_id = mi.id
            JOIN products p ON mid_out.material_id = p.id
            LEFT JOIN products orig_p ON mid_out.original_material_id = orig_p.id
            LEFT JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            LEFT JOIN warehouses wh ON mi.warehouse_id = wh.id
            LEFT JOIN employees issued_emp ON mi.issued_by = issued_emp.id
            LEFT JOIN employees recv_emp ON mi.received_by = recv_emp.id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_delivery(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Delivery (stock out) detail"""
        query = """
            SELECT 
                'Delivery' AS doc_type,
                sod.dn_number,
                sod.dispatch_date,
                sod.date_delivered,
                sod.shipment_status,
                sod.delivery_method,
                sod.status,
                sod.referencepl,
                buyer.english_name AS buyer_name,
                seller.english_name AS seller_name,
                carrier.english_name AS carrier_name,
                wh.name AS warehouse_name,
                CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
            FROM inventory_histories ih
            LEFT JOIN stock_out_delivery sod ON ih.delivery_id = sod.id
            LEFT JOIN companies buyer ON sod.buyer_company_id = buyer.id
            LEFT JOIN companies seller ON sod.seller_company_id = seller.id
            LEFT JOIN companies carrier ON sod.carrier_id = carrier.id
            LEFT JOIN warehouses wh ON sod.warehouse_id = wh.id
            LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_warehouse_transfer(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Warehouse transfer detail"""
        query = """
            SELECT 
                'Warehouse Transfer' AS doc_type,
                sowt.warehouse_transfer_number,
                sowt.created_date,
                sowt.finish AS is_finished,
                c.english_name AS company_name,
                wh.name AS warehouse_name,
                CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
            FROM inventory_histories ih
            JOIN stock_out_warehouse_transfer sowt ON ih.warehouse_transfer_stock_out_id = sowt.id
            LEFT JOIN companies c ON sowt.company_id = c.id
            LEFT JOIN warehouses wh ON ih.warehouse_id = wh.id
            LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    def _ref_query_internal_use(self, ih_id: int) -> Optional[Dict[str, Any]]:
        """Internal use detail"""
        query = """
            SELECT 
                'Internal Use' AS doc_type,
                soiu.internal_use_number,
                soiu.created_date,
                c.english_name AS company_name,
                CONCAT(req.first_name, ' ', req.last_name) AS requester_name,
                wh.name AS warehouse_name,
                CONCAT(emp.first_name, ' ', emp.last_name) AS created_by_name
            FROM inventory_histories ih
            JOIN stock_out_internal_use soiu ON ih.internal_stock_out_id = soiu.id
            LEFT JOIN companies c ON soiu.company_id = c.id
            LEFT JOIN employees req ON soiu.requester_id = req.id
            LEFT JOIN warehouses wh ON ih.warehouse_id = wh.id
            LEFT JOIN employees emp ON ih.created_by = emp.keycloak_id
            WHERE ih.id = :ih_id
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'ih_id': ih_id})
            row = result.fetchone()
        if row:
            return dict(zip(result.keys(), row))
        return None
    
    # ==================== Reference Document Lines ====================
    
    def get_reference_lines(self, ih_id: int, transaction_type: str) -> pd.DataFrame:
        """
        Get all line items of the parent document for a given inventory history record.
        E.g. for a Purchase stock-in, returns all items in the same Arrival.
        """
        try:
            query_map = {
                'stockIn': self._ref_lines_purchase,
                'stockInProduction': self._ref_lines_production_receipt,
                'stockInProductionReturn': self._ref_lines_material_return,
                'stockOutProduction': self._ref_lines_material_issue,
                'stockOutDelivery': self._ref_lines_delivery,
            }
            query_func = query_map.get(transaction_type)
            if not query_func:
                return pd.DataFrame()
            return query_func(ih_id)
        except Exception as e:
            logger.error(f"Error loading reference lines: {e}", exc_info=True)
            return pd.DataFrame()
    
    def _ref_lines_purchase(self, ih_id: int) -> pd.DataFrame:
        """All arrival detail lines for the same arrival"""
        query = """
            SELECT 
                p.pt_code AS 'PT Code',
                p.name AS 'Product',
                p.package_size AS 'Pkg Size',
                po.po_number AS 'PO Number',
                ad.arrival_quantity AS 'Arrival Qty',
                ad.stocked_in AS 'Stocked In',
                ad.landed_cost AS 'Landed Cost',
                ad.import_tax AS 'Import Tax'
            FROM arrival_details ad
            JOIN products p ON ad.product_id = p.id
            LEFT JOIN purchase_orders po ON ad.purchase_order_id = po.id
            WHERE ad.arrival_id = (
                SELECT ad2.arrival_id 
                FROM inventory_histories ih
                JOIN stock_in_details sid ON ih.action_detail_id = sid.id
                JOIN arrival_details ad2 ON sid.arrival_detail_id = ad2.id
                WHERE ih.id = :ih_id
            )
            AND COALESCE(ad.delete_flag, 0) = 0
            ORDER BY p.name
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params={'ih_id': ih_id})
    
    def _ref_lines_material_issue(self, ih_id: int) -> pd.DataFrame:
        """All material issue detail lines for the same issue"""
        query = """
            SELECT 
                p.pt_code AS 'PT Code',
                p.name AS 'Material',
                mid_all.batch_no AS 'Batch',
                mid_all.quantity AS 'Quantity',
                mid_all.uom AS 'UOM',
                DATE_FORMAT(mid_all.expired_date, '%%d/%%m/%%Y') AS 'Expiry',
                CASE WHEN mid_all.is_alternative = 1 
                     THEN CONCAT('⚠️ Alt for: ', orig_p.name) 
                     ELSE '' END AS 'Note'
            FROM material_issue_details mid_all
            JOIN products p ON mid_all.material_id = p.id
            LEFT JOIN products orig_p ON mid_all.original_material_id = orig_p.id
            WHERE mid_all.material_issue_id = (
                SELECT mid2.material_issue_id
                FROM inventory_histories ih
                JOIN material_issue_details mid2 ON ih.action_detail_id = mid2.id
                WHERE ih.id = :ih_id
            )
            ORDER BY p.name, mid_all.batch_no
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params={'ih_id': ih_id})
    
    def _ref_lines_material_return(self, ih_id: int) -> pd.DataFrame:
        """All material return detail lines for the same return"""
        query = """
            SELECT 
                p.pt_code AS 'PT Code',
                p.name AS 'Material',
                mrd_all.batch_no AS 'Batch',
                mrd_all.quantity AS 'Quantity',
                mrd_all.uom AS 'UOM',
                mrd_all.condition AS 'Condition',
                DATE_FORMAT(mrd_all.expired_date, '%%d/%%m/%%Y') AS 'Expiry'
            FROM material_return_details mrd_all
            JOIN products p ON mrd_all.material_id = p.id
            WHERE mrd_all.material_return_id = (
                SELECT mrd2.material_return_id
                FROM inventory_histories ih
                JOIN material_return_details mrd2 ON ih.action_detail_id = mrd2.id
                WHERE ih.id = :ih_id
            )
            ORDER BY p.name, mrd_all.batch_no
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params={'ih_id': ih_id})
    
    def _ref_lines_production_receipt(self, ih_id: int) -> pd.DataFrame:
        """All production receipts from the same MO"""
        query = """
            SELECT 
                pr_all.receipt_no AS 'Receipt No',
                DATE_FORMAT(pr_all.receipt_date, '%%d/%%m/%%Y %%H:%%i') AS 'Receipt Date',
                pr_all.batch_no AS 'Batch',
                pr_all.quantity AS 'Quantity',
                pr_all.uom AS 'UOM',
                pr_all.quality_status AS 'QC Status',
                COALESCE(pr_all.defect_type, '') AS 'Defect Type',
                DATE_FORMAT(pr_all.expired_date, '%%d/%%m/%%Y') AS 'Expiry'
            FROM production_receipts pr_all
            WHERE pr_all.manufacturing_order_id = (
                SELECT pr2.manufacturing_order_id
                FROM inventory_histories ih
                JOIN production_receipts pr2 ON ih.action_detail_id = pr2.id
                WHERE ih.id = :ih_id
            )
            ORDER BY pr_all.receipt_date
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params={'ih_id': ih_id})
    
    def _ref_lines_delivery(self, ih_id: int) -> pd.DataFrame:
        """All inventory history lines for the same delivery"""
        query = """
            SELECT 
                p.pt_code AS 'PT Code',
                p.name AS 'Product',
                ih_all.batch_no AS 'Batch',
                ih_all.quantity AS 'Quantity',
                p.uom AS 'UOM',
                wh.name AS 'Warehouse'
            FROM inventory_histories ih_all
            JOIN products p ON ih_all.product_id = p.id
            LEFT JOIN warehouses wh ON ih_all.warehouse_id = wh.id
            WHERE ih_all.delivery_id = (
                SELECT ih2.delivery_id FROM inventory_histories ih2 WHERE ih2.id = :ih_id
            )
            AND ih_all.delete_flag = 0
            ORDER BY p.name, ih_all.batch_no
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params={'ih_id': ih_id})
    
    # ==================== Export Functions ====================
    
    def get_export_data(self, category: Optional[str] = None,
                        warehouse_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get data formatted for Excel export
        
        Args:
            category: Filter by category or None for all
            warehouse_id: Filter by warehouse or None for all
        
        Returns:
            DataFrame formatted for export
        """
        df = self.get_unified_inventory(category=category, warehouse_id=warehouse_id)
        
        if df.empty:
            return df
        
        # Select and rename columns for export
        export_columns = {
            'category': 'Category',
            'product_name': 'Product Name',
            'pt_code': 'PT Code',
            'package_size': 'Package Size',
            'brand': 'Brand',
            'batch_number': 'Batch Number',
            'expiry_date': 'Expiry Date',
            'quantity': 'Quantity',
            'uom': 'UOM',
            'warehouse_name': 'Warehouse',
            'source_type': 'Source Type',
            'defect_type': 'Defect Type',
            'days_in_warehouse': 'Days in Warehouse',
            'age_category': 'Age Category',
            'expiry_status': 'Expiry Status',
            'inventory_value_usd': 'Value (USD)',
            'po_number': 'PO Number',
            'vendor_name': 'Vendor',
            'related_order_no': 'Related Order',
            'notes': 'Notes'
        }
        
        # Filter existing columns
        existing_cols = [c for c in export_columns.keys() if c in df.columns]
        export_df = df[existing_cols].copy()
        export_df.rename(columns={k: v for k, v in export_columns.items() if k in existing_cols}, inplace=True)
        
        return export_df