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
                query += " AND (product_name LIKE :search OR pt_code LIKE :search OR package_size LIKE :search)"
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
                query += " AND (p.name LIKE :search OR p.pt_code LIKE :search)"
                params['search'] = f"%{product_search}%"
            
            query += """
                GROUP BY ih.product_id, p.pt_code, p.name, p.uom, 
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