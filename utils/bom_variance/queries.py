# utils/bom_variance/queries.py
"""
SQL Queries for BOM Variance Analysis - VERSION 2.1

Provides data extraction queries for:
- Actual consumption from completed Manufacturing Orders
- Theoretical values from BOM definitions (primary + alternative materials)
- Variance calculations and aggregations

IMPORTANT CHANGES:

v2.1 - Usage Mode Support:
- Classifies MOs into: PRIMARY_ONLY, ALTERNATIVE_ONLY, MIXED
- Variance is calculated from PURE MOs only (not mixed)
- Mixed MO stats reported separately for context
- New columns: mo_count_pure, mo_count_mixed, avg_per_unit_mixed, has_mixed_usage

v2.0 - Actual Data Source Fix:
- Actual consumption is now calculated from:
  * material_issue_details.quantity (actual issued)
  * material_return_details.quantity (actual returned)
  * NET consumed = issued - returned
- NOT from manufacturing_order_materials.issued_qty (which is equivalent/converted)
- This provides accurate tracking per actual material (primary vs alternative)
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any

import pandas as pd
from sqlalchemy import text

from utils.db import get_db_engine

logger = logging.getLogger(__name__)


class VarianceQueries:
    """
    SQL query provider for variance analysis
    
    Data flow (v2.0):
    1. material_issue_details (CONFIRMED) → actual issued qty
    2. material_return_details (CONFIRMED) → actual returned qty
    3. production_receipts (PASSED) → actual output qty
    4. NET consumed = issued - returned
    5. bom_details + bom_material_alternatives → theoretical values
    6. Compare and calculate variance
    """
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== Actual Consumption Queries ====================
    
    def get_mo_consumption_summary(
        self,
        bom_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_mo_count: int = 1
    ) -> pd.DataFrame:
        """
        Get aggregated actual consumption per BOM per Material
        
        IMPORTANT: Actual consumption is calculated from:
        - material_issue_details.quantity (actual issued)
        - material_return_details.quantity (actual returned)
        - NET consumed = issued - returned
        
        Args:
            bom_id: Filter by specific BOM (None for all)
            date_from: Start date filter
            date_to: End date filter
            min_mo_count: Minimum completed MOs required
            
        Returns:
            DataFrame with columns:
            - bom_header_id, bom_code, bom_name, bom_type
            - material_id, material_code, material_name, is_alternative
            - mo_count, total_produced, total_consumed
            - avg_per_unit, stddev_per_unit, cv_percent (coefficient of variation)
        """
        query = """
            WITH 
            -- Get actual issued quantities
            issued_data AS (
                SELECT 
                    mo.id as mo_id,
                    mo.bom_header_id,
                    mid.material_id,
                    mid.is_alternative,
                    SUM(mid.quantity) as issued_qty
                FROM manufacturing_orders mo
                JOIN material_issues mi ON mo.id = mi.manufacturing_order_id
                JOIN material_issue_details mid ON mi.id = mid.material_issue_id
                WHERE mo.status = 'COMPLETED' 
                  AND mo.delete_flag = 0
                  AND mi.status = 'CONFIRMED'
                GROUP BY mo.id, mo.bom_header_id, mid.material_id, mid.is_alternative
            ),
            -- Get returned quantities
            returned_data AS (
                SELECT 
                    mo.id as mo_id,
                    mrd.material_id,
                    SUM(mrd.quantity) as returned_qty
                FROM manufacturing_orders mo
                JOIN material_returns mr ON mo.id = mr.manufacturing_order_id
                JOIN material_return_details mrd ON mr.id = mrd.material_return_id
                WHERE mo.status = 'COMPLETED'
                  AND mo.delete_flag = 0
                  AND mr.status = 'CONFIRMED'
                GROUP BY mo.id, mrd.material_id
            ),
            -- Get production data
            production_data AS (
                SELECT 
                    manufacturing_order_id as mo_id,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ),
            -- Calculate net consumption per MO
            mo_consumption AS (
                SELECT 
                    i.mo_id,
                    i.bom_header_id,
                    i.material_id,
                    i.is_alternative,
                    p.passed_qty,
                    (i.issued_qty - COALESCE(r.returned_qty, 0)) as net_consumed,
                    CASE 
                        WHEN p.passed_qty > 0 
                        THEN (i.issued_qty - COALESCE(r.returned_qty, 0)) / p.passed_qty
                        ELSE 0 
                    END as consumption_per_unit
                FROM issued_data i
                LEFT JOIN returned_data r ON i.mo_id = r.mo_id AND i.material_id = r.material_id
                LEFT JOIN production_data p ON i.mo_id = p.mo_id
                WHERE COALESCE(p.passed_qty, 0) > 0
            )
            SELECT 
                mc.bom_header_id,
                bh.bom_code,
                bh.bom_name,
                bh.bom_type,
                bh.output_qty as bom_output_qty,
                mc.material_id,
                mc.is_alternative,
                p.pt_code as material_code,
                p.name as material_name,
                p.uom as material_uom,
                COUNT(DISTINCT mc.mo_id) as mo_count,
                SUM(mc.passed_qty) as total_produced,
                SUM(mc.net_consumed) as total_consumed,
                -- Average consumption per output unit
                CASE 
                    WHEN SUM(mc.passed_qty) > 0 
                    THEN SUM(mc.net_consumed) / SUM(mc.passed_qty)
                    ELSE 0 
                END as avg_per_unit,
                -- Standard deviation (sample)
                STDDEV_SAMP(mc.consumption_per_unit) as stddev_per_unit
            FROM mo_consumption mc
            JOIN bom_headers bh ON mc.bom_header_id = bh.id
            JOIN products p ON mc.material_id = p.id
            WHERE bh.delete_flag = 0
        """
        
        params = {}
        
        if bom_id:
            query += " AND mc.bom_header_id = :bom_id"
            params['bom_id'] = int(bom_id)
        
        if date_from:
            query += """ AND mc.mo_id IN (
                SELECT id FROM manufacturing_orders 
                WHERE completion_date >= :date_from
            )"""
            params['date_from'] = date_from
        
        if date_to:
            query += """ AND mc.mo_id IN (
                SELECT id FROM manufacturing_orders 
                WHERE completion_date <= :date_to
            )"""
            params['date_to'] = date_to
        
        query += """
            GROUP BY 
                mc.bom_header_id, bh.bom_code, bh.bom_name, bh.bom_type, bh.output_qty,
                mc.material_id, mc.is_alternative, p.pt_code, p.name, p.uom
            HAVING COUNT(DISTINCT mc.mo_id) >= :min_mo_count
            ORDER BY bh.bom_code, mc.is_alternative, p.pt_code
        """
        params['min_mo_count'] = min_mo_count
        
        try:
            df = pd.read_sql(text(query), self.engine, params=params)
            
            # Calculate coefficient of variation (CV%)
            if not df.empty:
                df['cv_percent'] = df.apply(
                    lambda row: (row['stddev_per_unit'] / row['avg_per_unit'] * 100) 
                    if row['avg_per_unit'] > 0 and pd.notna(row['stddev_per_unit'])
                    else 0,
                    axis=1
                )
            
            return df
        except Exception as e:
            logger.error(f"Error getting MO consumption summary: {e}")
            raise
    
    def get_mo_consumption_detail(
        self,
        bom_id: int,
        material_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Get detailed consumption per MO for a specific BOM
        
        Used for trend analysis and drilling into specific materials
        
        IMPORTANT: Actual consumption is calculated from:
        - material_issue_details.quantity (actual issued)
        - material_return_details.quantity (actual returned)
        - NET consumed = issued - returned
        
        Returns:
            DataFrame with per-MO consumption data
        """
        query = """
            WITH 
            -- Get actual issued quantities per MO per material
            issued_data AS (
                SELECT 
                    mo.id as mo_id,
                    mid.material_id,
                    mid.is_alternative,
                    SUM(mid.quantity) as issued_qty
                FROM manufacturing_orders mo
                JOIN material_issues mi ON mo.id = mi.manufacturing_order_id
                JOIN material_issue_details mid ON mi.id = mid.material_issue_id
                WHERE mo.bom_header_id = :bom_id
                  AND mo.status = 'COMPLETED'
                  AND mo.delete_flag = 0
                  AND mi.status = 'CONFIRMED'
                GROUP BY mo.id, mid.material_id, mid.is_alternative
            ),
            -- Get returned quantities per MO per material
            returned_data AS (
                SELECT 
                    mo.id as mo_id,
                    mrd.material_id,
                    SUM(mrd.quantity) as returned_qty
                FROM manufacturing_orders mo
                JOIN material_returns mr ON mo.id = mr.manufacturing_order_id
                JOIN material_return_details mrd ON mr.id = mrd.material_return_id
                WHERE mo.bom_header_id = :bom_id
                  AND mo.status = 'COMPLETED'
                  AND mo.delete_flag = 0
                  AND mr.status = 'CONFIRMED'
                GROUP BY mo.id, mrd.material_id
            ),
            -- Get production data
            production_data AS (
                SELECT 
                    manufacturing_order_id as mo_id,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            )
            SELECT 
                mo.id as mo_id,
                mo.order_no,
                mo.order_date,
                mo.completion_date,
                mo.planned_qty,
                COALESCE(pr.passed_qty, 0) as produced_qty,
                i.material_id,
                i.is_alternative,
                p.pt_code as material_code,
                p.name as material_name,
                i.issued_qty as gross_issued,
                COALESCE(r.returned_qty, 0) as returned_qty,
                (i.issued_qty - COALESCE(r.returned_qty, 0)) as net_consumed,
                -- Consumption per output unit
                CASE 
                    WHEN pr.passed_qty > 0 
                    THEN (i.issued_qty - COALESCE(r.returned_qty, 0)) / pr.passed_qty
                    ELSE 0 
                END as consumption_per_unit
            FROM manufacturing_orders mo
            JOIN issued_data i ON mo.id = i.mo_id
            JOIN products p ON i.material_id = p.id
            LEFT JOIN returned_data r ON mo.id = r.mo_id AND i.material_id = r.material_id
            LEFT JOIN production_data pr ON mo.id = pr.mo_id
            WHERE mo.bom_header_id = :bom_id
              AND mo.status = 'COMPLETED'
              AND mo.delete_flag = 0
              AND COALESCE(pr.passed_qty, 0) > 0
        """
        
        params = {'bom_id': int(bom_id)}
        
        if material_id:
            query += " AND i.material_id = :material_id"
            params['material_id'] = int(material_id)
        
        if date_from:
            query += " AND mo.completion_date >= :date_from"
            params['date_from'] = date_from
        
        if date_to:
            query += " AND mo.completion_date <= :date_to"
            params['date_to'] = date_to
        
        query += " ORDER BY mo.completion_date DESC, i.is_alternative, p.pt_code"
        
        try:
            return pd.read_sql(text(query), self.engine, params=params)
        except Exception as e:
            logger.error(f"Error getting MO consumption detail: {e}")
            raise
    
    # ==================== Alternative Material Tracking ====================
    
    def get_alternative_usage_summary(
        self,
        bom_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Get summary of alternative material usage
        
        Tracks when alternatives were used instead of primary materials
        for variance analysis separation
        
        Returns:
            DataFrame with alternative usage statistics
        """
        query = """
            SELECT 
                mo.bom_header_id,
                bh.bom_code,
                mom.material_id as primary_material_id,
                pm.pt_code as primary_material_code,
                pm.name as primary_material_name,
                mid.material_id as used_material_id,
                um.pt_code as used_material_code,
                um.name as used_material_name,
                mid.is_alternative,
                COUNT(DISTINCT mo.id) as mo_count,
                SUM(mid.quantity) as total_issued_qty,
                -- Get BOM quantity for conversion reference
                bd.quantity as bom_primary_qty,
                COALESCE(bma.quantity, bd.quantity) as bom_used_qty
            FROM material_issue_details mid
            JOIN material_issues mi ON mid.material_issue_id = mi.id
            JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            JOIN manufacturing_order_materials mom ON mid.manufacturing_order_material_id = mom.id
            JOIN products pm ON mom.material_id = pm.id
            JOIN products um ON mid.material_id = um.id
            JOIN bom_details bd ON bd.bom_header_id = mo.bom_header_id 
                AND bd.material_id = mom.material_id
            LEFT JOIN bom_material_alternatives bma ON bma.bom_detail_id = bd.id
                AND bma.alternative_material_id = mid.material_id
            WHERE mo.status = 'COMPLETED'
              AND mo.delete_flag = 0
              AND mi.status = 'CONFIRMED'
        """
        
        params = {}
        
        if bom_id:
            query += " AND mo.bom_header_id = :bom_id"
            params['bom_id'] = int(bom_id)
        
        if date_from:
            query += " AND mo.completion_date >= :date_from"
            params['date_from'] = date_from
        
        if date_to:
            query += " AND mo.completion_date <= :date_to"
            params['date_to'] = date_to
        
        query += """
            GROUP BY 
                mo.bom_header_id, bh.bom_code,
                mom.material_id, pm.pt_code, pm.name,
                mid.material_id, um.pt_code, um.name,
                mid.is_alternative, bd.quantity, bma.quantity
            ORDER BY bh.bom_code, pm.pt_code, mid.is_alternative
        """
        
        try:
            return pd.read_sql(text(query), self.engine, params=params)
        except Exception as e:
            logger.error(f"Error getting alternative usage summary: {e}")
            raise
    
    # ==================== BOM Theoretical Values ====================
    
    def get_bom_theoretical_values(
        self,
        bom_id: Optional[int] = None,
        status: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Get theoretical material requirements from BOM definitions
        
        Returns:
            DataFrame with BOM theoretical values per material
        """
        query = """
            SELECT 
                bh.id as bom_header_id,
                bh.bom_code,
                bh.bom_name,
                bh.bom_type,
                bh.product_id as output_product_id,
                op.pt_code as output_product_code,
                op.name as output_product_name,
                bh.output_qty,
                bh.uom as output_uom,
                bh.status,
                bd.id as bom_detail_id,
                bd.material_id,
                mp.pt_code as material_code,
                mp.name as material_name,
                bd.material_type,
                bd.quantity as bom_quantity,
                bd.uom as material_uom,
                bd.scrap_rate,
                -- Calculated fields
                (bd.quantity / bh.output_qty) as qty_per_output,
                (bd.quantity / bh.output_qty) * (1 + bd.scrap_rate/100) as qty_per_output_with_scrap,
                -- Count alternatives
                (SELECT COUNT(*) FROM bom_material_alternatives bma 
                 WHERE bma.bom_detail_id = bd.id AND bma.is_active = 1) as alternatives_count,
                -- Usage count
                (SELECT COUNT(DISTINCT mo.id) FROM manufacturing_orders mo 
                 WHERE mo.bom_header_id = bh.id 
                 AND mo.status = 'COMPLETED' 
                 AND mo.delete_flag = 0) as completed_mo_count
            FROM bom_headers bh
            JOIN products op ON bh.product_id = op.id
            JOIN bom_details bd ON bd.bom_header_id = bh.id
            JOIN products mp ON bd.material_id = mp.id
            WHERE bh.delete_flag = 0
        """
        
        params = {}
        
        if bom_id:
            query += " AND bh.id = :bom_id"
            params['bom_id'] = int(bom_id)
        
        if status:
            query += " AND bh.status = :status"
            params['status'] = status
        
        query += " ORDER BY bh.bom_code, bd.material_type, mp.pt_code"
        
        try:
            return pd.read_sql(text(query), self.engine, params=params)
        except Exception as e:
            logger.error(f"Error getting BOM theoretical values: {e}")
            raise
    
    # ==================== Variance Comparison Query ====================
    
    def get_variance_comparison(
        self,
        bom_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_mo_count: int = 3,
        variance_threshold: float = 5.0
    ) -> pd.DataFrame:
        """
        Get comprehensive variance comparison: BOM theoretical vs actual consumption
        
        VERSION 2.1 - Usage Mode Support:
        - Classifies MOs into: PRIMARY_ONLY, ALTERNATIVE_ONLY, MIXED
        - Variance is calculated from PURE MOs only (PRIMARY_ONLY or ALTERNATIVE_ONLY)
        - Mixed MOs are reported separately for context
        
        IMPORTANT: Actual consumption is calculated from:
        - material_issue_details.quantity (actual issued)
        - material_return_details.quantity (actual returned)
        - NET consumed = issued - returned
        
        Args:
            bom_id: Filter by specific BOM
            date_from: Start date for actual data
            date_to: End date for actual data
            min_mo_count: Minimum MOs required for reliable statistics
            variance_threshold: Flag items with variance above this % 
            
        Returns:
            DataFrame with variance analysis including:
            - BOM info, material info
            - Theoretical values (qty_per_output, scrap_rate)
            - Pure MO stats (mo_count_pure, variance from pure only)
            - Mixed MO stats (mo_count_mixed, avg consumption in mixed)
            - Flags (has_high_variance, has_mixed_usage)
        """
        query = """
            WITH 
            -- Step 1: Get actual issued quantities from material_issue_details
            issued_data AS (
                SELECT 
                    mo.id as mo_id,
                    mo.bom_header_id,
                    mo.completion_date,
                    mid.material_id,
                    mid.is_alternative,
                    COALESCE(mid.original_material_id, mom.material_id) as primary_material_id,
                    SUM(mid.quantity) as issued_qty
                FROM manufacturing_orders mo
                JOIN material_issues mi ON mo.id = mi.manufacturing_order_id
                JOIN material_issue_details mid ON mi.id = mid.material_issue_id
                JOIN manufacturing_order_materials mom ON mid.manufacturing_order_material_id = mom.id
                WHERE mo.status = 'COMPLETED' 
                  AND mo.delete_flag = 0
                  AND mi.status = 'CONFIRMED'
                GROUP BY mo.id, mo.bom_header_id, mo.completion_date, 
                         mid.material_id, mid.is_alternative, 
                         mid.original_material_id, mom.material_id
            ),
            -- Step 2: Get returned quantities from material_return_details
            returned_data AS (
                SELECT 
                    mo.id as mo_id,
                    mrd.material_id,
                    SUM(mrd.quantity) as returned_qty
                FROM manufacturing_orders mo
                JOIN material_returns mr ON mo.id = mr.manufacturing_order_id
                JOIN material_return_details mrd ON mr.id = mrd.material_return_id
                WHERE mo.status = 'COMPLETED'
                  AND mo.delete_flag = 0
                  AND mr.status = 'CONFIRMED'
                GROUP BY mo.id, mrd.material_id
            ),
            -- Step 3: Get passed production qty per MO
            production_data AS (
                SELECT 
                    manufacturing_order_id as mo_id,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ),
            -- Step 4: Calculate net consumption per MO per material
            mo_consumption AS (
                SELECT 
                    i.mo_id,
                    i.bom_header_id,
                    i.completion_date,
                    i.material_id,
                    i.is_alternative,
                    i.primary_material_id,
                    p.passed_qty,
                    (i.issued_qty - COALESCE(r.returned_qty, 0)) as net_consumed,
                    CASE 
                        WHEN p.passed_qty > 0 
                        THEN (i.issued_qty - COALESCE(r.returned_qty, 0)) / p.passed_qty
                        ELSE 0 
                    END as consumption_per_unit
                FROM issued_data i
                LEFT JOIN returned_data r ON i.mo_id = r.mo_id AND i.material_id = r.material_id
                LEFT JOIN production_data p ON i.mo_id = p.mo_id
                WHERE COALESCE(p.passed_qty, 0) > 0
            ),
            -- Step 5: Determine usage_mode per MO per primary_material
            -- A MO is MIXED if it uses both primary (is_alternative=0) and alternative (is_alternative=1)
            -- for the same primary_material_id
            mo_usage_mode AS (
                SELECT 
                    mo_id,
                    bom_header_id,
                    primary_material_id,
                    MAX(CASE WHEN is_alternative = 0 THEN 1 ELSE 0 END) as has_primary,
                    MAX(CASE WHEN is_alternative = 1 THEN 1 ELSE 0 END) as has_alternative,
                    CASE 
                        WHEN MAX(CASE WHEN is_alternative = 0 THEN 1 ELSE 0 END) = 1 
                         AND MAX(CASE WHEN is_alternative = 1 THEN 1 ELSE 0 END) = 1 
                        THEN 'MIXED'
                        WHEN MAX(CASE WHEN is_alternative = 0 THEN 1 ELSE 0 END) = 1 
                        THEN 'PRIMARY_ONLY'
                        ELSE 'ALTERNATIVE_ONLY'
                    END as usage_mode
                FROM mo_consumption
                GROUP BY mo_id, bom_header_id, primary_material_id
            ),
            -- Step 6: Join usage_mode back to consumption data
            mo_consumption_with_mode AS (
                SELECT 
                    mc.*,
                    um.usage_mode
                FROM mo_consumption mc
                JOIN mo_usage_mode um ON mc.mo_id = um.mo_id 
                                     AND mc.bom_header_id = um.bom_header_id
                                     AND mc.primary_material_id = um.primary_material_id
            ),
            -- Step 7: Aggregate PURE MO stats (for variance calculation)
            -- Primary materials: only from PRIMARY_ONLY MOs
            -- Alternative materials: only from ALTERNATIVE_ONLY MOs
            pure_stats AS (
                SELECT 
                    bom_header_id,
                    material_id,
                    is_alternative,
                    primary_material_id,
                    COUNT(DISTINCT mo_id) as mo_count_pure,
                    SUM(passed_qty) as total_produced_pure,
                    SUM(net_consumed) as total_consumed_pure,
                    CASE 
                        WHEN SUM(passed_qty) > 0 
                        THEN SUM(net_consumed) / SUM(passed_qty)
                        ELSE 0 
                    END as avg_per_unit_pure,
                    STDDEV_SAMP(consumption_per_unit) as stddev_per_unit_pure,
                    MIN(completion_date) as first_mo_date,
                    MAX(completion_date) as last_mo_date
                FROM mo_consumption_with_mode
                WHERE (is_alternative = 0 AND usage_mode = 'PRIMARY_ONLY')
                   OR (is_alternative = 1 AND usage_mode = 'ALTERNATIVE_ONLY')
        """
        
        params = {'min_mo_count': min_mo_count}
        
        # Date filters for pure_stats
        if bom_id:
            query += " AND bom_header_id = :bom_id"
            params['bom_id'] = int(bom_id)
        
        if date_from:
            query += " AND completion_date >= :date_from"
            params['date_from'] = date_from
        
        if date_to:
            query += " AND completion_date <= :date_to"
            params['date_to'] = date_to
        
        query += """
                GROUP BY bom_header_id, material_id, is_alternative, primary_material_id
            ),
            -- Step 8: Aggregate MIXED MO stats (for context, not variance)
            mixed_stats AS (
                SELECT 
                    bom_header_id,
                    material_id,
                    is_alternative,
                    primary_material_id,
                    COUNT(DISTINCT mo_id) as mo_count_mixed,
                    SUM(passed_qty) as total_produced_mixed,
                    SUM(net_consumed) as total_consumed_mixed,
                    CASE 
                        WHEN SUM(passed_qty) > 0 
                        THEN SUM(net_consumed) / SUM(passed_qty)
                        ELSE 0 
                    END as avg_per_unit_mixed
                FROM mo_consumption_with_mode
                WHERE usage_mode = 'MIXED'
        """
        
        # Same date filters for mixed_stats
        if bom_id:
            query += " AND bom_header_id = :bom_id"
        
        if date_from:
            query += " AND completion_date >= :date_from"
        
        if date_to:
            query += " AND completion_date <= :date_to"
        
        query += """
                GROUP BY bom_header_id, material_id, is_alternative, primary_material_id
            ),
            -- Step 9: Theoretical data from BOM (primary materials)
            theoretical_primary AS (
                SELECT 
                    bh.id as bom_header_id,
                    bh.bom_code,
                    bh.bom_name,
                    bh.bom_type,
                    bh.status as bom_status,
                    bh.output_qty as bom_output_qty,
                    op.pt_code as output_product_code,
                    op.name as output_product_name,
                    op.legacy_pt_code as output_product_legacy_code,
                    op.package_size as output_product_package_size,
                    ob.brand_name as output_product_brand,
                    bd.material_id,
                    bd.material_id as primary_material_id,
                    0 as is_alternative,
                    mp.pt_code as material_code,
                    mp.name as material_name,
                    mp.uom as material_uom,
                    mp.legacy_pt_code as material_legacy_code,
                    mp.package_size as material_package_size,
                    mb.brand_name as material_brand,
                    bd.material_type,
                    bd.quantity as bom_quantity,
                    bd.scrap_rate,
                    (bd.quantity / bh.output_qty) as qty_per_output,
                    (bd.quantity / bh.output_qty) * (1 + bd.scrap_rate/100) as qty_per_output_with_scrap
                FROM bom_headers bh
                JOIN products op ON bh.product_id = op.id
                LEFT JOIN brands ob ON op.brand_id = ob.id
                JOIN bom_details bd ON bd.bom_header_id = bh.id
                JOIN products mp ON bd.material_id = mp.id
                LEFT JOIN brands mb ON mp.brand_id = mb.id
                WHERE bh.delete_flag = 0
        """
        
        if bom_id:
            query += " AND bh.id = :bom_id"
        
        query += """
            ),
            -- Step 10: Theoretical data for alternative materials
            theoretical_alternative AS (
                SELECT 
                    bh.id as bom_header_id,
                    bh.bom_code,
                    bh.bom_name,
                    bh.bom_type,
                    bh.status as bom_status,
                    bh.output_qty as bom_output_qty,
                    op.pt_code as output_product_code,
                    op.name as output_product_name,
                    op.legacy_pt_code as output_product_legacy_code,
                    op.package_size as output_product_package_size,
                    ob.brand_name as output_product_brand,
                    bma.alternative_material_id as material_id,
                    bd.material_id as primary_material_id,
                    1 as is_alternative,
                    mp.pt_code as material_code,
                    mp.name as material_name,
                    mp.uom as material_uom,
                    mp.legacy_pt_code as material_legacy_code,
                    mp.package_size as material_package_size,
                    mb.brand_name as material_brand,
                    bma.material_type,
                    bma.quantity as bom_quantity,
                    bma.scrap_rate,
                    (bma.quantity / bh.output_qty) as qty_per_output,
                    (bma.quantity / bh.output_qty) * (1 + bma.scrap_rate/100) as qty_per_output_with_scrap
                FROM bom_headers bh
                JOIN products op ON bh.product_id = op.id
                LEFT JOIN brands ob ON op.brand_id = ob.id
                JOIN bom_details bd ON bd.bom_header_id = bh.id
                JOIN bom_material_alternatives bma ON bd.id = bma.bom_detail_id
                JOIN products mp ON bma.alternative_material_id = mp.id
                LEFT JOIN brands mb ON mp.brand_id = mb.id
                WHERE bh.delete_flag = 0
                  AND bma.is_active = 1
        """
        
        if bom_id:
            query += " AND bh.id = :bom_id"
        
        query += """
            ),
            -- Step 11: Union primary and alternative theoretical data
            theoretical_data AS (
                SELECT * FROM theoretical_primary
                UNION ALL
                SELECT * FROM theoretical_alternative
            )
            -- Final: Join theoretical with pure and mixed stats
            SELECT 
                t.bom_header_id,
                t.bom_code,
                t.bom_name,
                t.bom_type,
                t.bom_status,
                t.bom_output_qty,
                t.output_product_code,
                t.output_product_name,
                t.output_product_legacy_code,
                t.output_product_package_size,
                t.output_product_brand,
                t.material_id,
                t.primary_material_id,
                t.is_alternative,
                t.material_code,
                t.material_name,
                t.material_uom,
                t.material_legacy_code,
                t.material_package_size,
                t.material_brand,
                t.material_type,
                t.bom_quantity,
                t.scrap_rate,
                t.qty_per_output as theoretical_qty,
                t.qty_per_output_with_scrap as theoretical_qty_with_scrap,
                -- Total MO counts
                (COALESCE(p.mo_count_pure, 0) + COALESCE(m.mo_count_mixed, 0)) as mo_count,
                COALESCE(p.mo_count_pure, 0) as mo_count_pure,
                COALESCE(m.mo_count_mixed, 0) as mo_count_mixed,
                -- Pure MO stats (for variance calculation)
                COALESCE(p.total_produced_pure, 0) as total_produced,
                COALESCE(p.total_consumed_pure, 0) as total_consumed,
                COALESCE(p.avg_per_unit_pure, 0) as actual_avg_per_unit,
                COALESCE(p.stddev_per_unit_pure, 0) as actual_stddev,
                p.first_mo_date,
                p.last_mo_date,
                -- Mixed MO stats (for context)
                COALESCE(m.total_produced_mixed, 0) as total_produced_mixed,
                COALESCE(m.total_consumed_mixed, 0) as total_consumed_mixed,
                COALESCE(m.avg_per_unit_mixed, 0) as avg_per_unit_mixed,
                -- Variance calculations (from PURE MOs only)
                CASE 
                    WHEN p.avg_per_unit_pure IS NOT NULL AND p.avg_per_unit_pure > 0 
                         AND t.qty_per_output_with_scrap > 0
                    THEN (p.avg_per_unit_pure - t.qty_per_output_with_scrap)
                    ELSE NULL
                END as variance_qty,
                CASE 
                    WHEN p.avg_per_unit_pure IS NOT NULL AND p.avg_per_unit_pure > 0 
                         AND t.qty_per_output_with_scrap > 0
                    THEN ((p.avg_per_unit_pure - t.qty_per_output_with_scrap) / t.qty_per_output_with_scrap) * 100
                    ELSE NULL
                END as variance_pct,
                -- Coefficient of variation (from PURE MOs)
                CASE 
                    WHEN p.avg_per_unit_pure > 0 AND p.stddev_per_unit_pure IS NOT NULL
                    THEN (p.stddev_per_unit_pure / p.avg_per_unit_pure) * 100
                    ELSE 0
                END as cv_percent,
                -- Suggested values (based on PURE MOs)
                CASE 
                    WHEN p.avg_per_unit_pure IS NOT NULL AND p.avg_per_unit_pure > 0 
                         AND (1 + t.scrap_rate/100) > 0
                    THEN p.avg_per_unit_pure / (1 + t.scrap_rate/100) * t.bom_output_qty
                    ELSE t.bom_quantity
                END as suggested_quantity,
                CASE 
                    WHEN p.avg_per_unit_pure IS NOT NULL AND p.avg_per_unit_pure > 0 
                         AND t.qty_per_output > 0
                    THEN ((p.avg_per_unit_pure / t.qty_per_output) - 1) * 100
                    ELSE t.scrap_rate
                END as suggested_scrap_rate
            FROM theoretical_data t
            LEFT JOIN pure_stats p ON t.bom_header_id = p.bom_header_id 
                                  AND t.material_id = p.material_id
                                  AND t.is_alternative = p.is_alternative
            LEFT JOIN mixed_stats m ON t.bom_header_id = m.bom_header_id 
                                   AND t.material_id = m.material_id
                                   AND t.is_alternative = m.is_alternative
            WHERE (COALESCE(p.mo_count_pure, 0) + COALESCE(m.mo_count_mixed, 0)) >= :min_mo_count
            ORDER BY t.bom_code, t.primary_material_id, t.is_alternative, t.material_code
        """
        
        try:
            df = pd.read_sql(text(query), self.engine, params=params)
            
            # Add flag columns
            if not df.empty:
                # High variance flag (from pure MOs only)
                df['has_high_variance'] = df['variance_pct'].apply(
                    lambda x: abs(x) > variance_threshold if pd.notna(x) else False
                )
                
                # High variability flag (CV > 15%)
                df['has_high_variability'] = df['cv_percent'].apply(
                    lambda x: x > 15 if pd.notna(x) else False
                )
                
                # Has actual data flag (from pure MOs)
                df['has_actual_data'] = df['mo_count_pure'] > 0
                
                # Has mixed usage flag
                df['has_mixed_usage'] = df['mo_count_mixed'] > 0
            
            return df
        except Exception as e:
            logger.error(f"Error getting variance comparison: {e}")
            raise
    
    # ==================== Dashboard Summary Queries ====================
    
    def get_dashboard_summary(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_mo_count: int = 3,
        variance_threshold: float = 5.0
    ) -> Dict[str, Any]:
        """
        Get summary statistics for dashboard metrics
        
        Returns:
            Dictionary with summary metrics
        """
        # Get variance data
        variance_df = self.get_variance_comparison(
            date_from=date_from,
            date_to=date_to,
            min_mo_count=min_mo_count,
            variance_threshold=variance_threshold
        )
        
        if variance_df.empty:
            return {
                'total_boms_analyzed': 0,
                'total_materials_analyzed': 0,
                'boms_with_variance': 0,
                'materials_with_variance': 0,
                'total_mos_in_period': 0,
                'avg_variance_pct': 0,
                'max_variance_pct': 0,
                'boms_needing_review': 0
            }
        
        # Filter to rows with actual data
        with_data = variance_df[variance_df['has_actual_data']]
        
        if with_data.empty:
            return {
                'total_boms_analyzed': 0,
                'total_materials_analyzed': 0,
                'boms_with_variance': 0,
                'materials_with_variance': 0,
                'total_mos_in_period': 0,
                'avg_variance_pct': 0,
                'max_variance_pct': 0,
                'boms_needing_review': 0
            }
        
        # Calculate metrics
        high_variance = with_data[with_data['has_high_variance']]
        
        return {
            'total_boms_analyzed': with_data['bom_header_id'].nunique(),
            'total_materials_analyzed': len(with_data),
            'boms_with_variance': high_variance['bom_header_id'].nunique(),
            'materials_with_variance': len(high_variance),
            'total_mos_in_period': int(with_data['mo_count'].sum() / with_data['bom_header_id'].nunique()) if with_data['bom_header_id'].nunique() > 0 else 0,
            'avg_variance_pct': float(with_data['variance_pct'].abs().mean()) if not with_data['variance_pct'].isna().all() else 0,
            'max_variance_pct': float(with_data['variance_pct'].abs().max()) if not with_data['variance_pct'].isna().all() else 0,
            'boms_needing_review': high_variance['bom_header_id'].nunique()
        }
    
    def get_top_variances(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_mo_count: int = 3,
        variance_threshold: float = 5.0,
        limit: int = 10
    ) -> pd.DataFrame:
        """
        Get top N materials with highest variance for quick review
        
        Returns:
            DataFrame sorted by absolute variance percentage
        """
        variance_df = self.get_variance_comparison(
            date_from=date_from,
            date_to=date_to,
            min_mo_count=min_mo_count,
            variance_threshold=variance_threshold
        )
        
        if variance_df.empty:
            return pd.DataFrame()
        
        # Filter to rows with actual data and sort by absolute variance
        with_data = variance_df[variance_df['has_actual_data']].copy()
        
        if with_data.empty:
            return pd.DataFrame()
        
        with_data['abs_variance_pct'] = with_data['variance_pct'].abs()
        with_data = with_data.sort_values('abs_variance_pct', ascending=False)
        
        return with_data.head(limit)
    
    def get_bom_list_for_analysis(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_mo_count: int = 1
    ) -> pd.DataFrame:
        """
        Get list of BOMs that have completed MOs for analysis
        
        Returns:
            DataFrame with BOM list and MO counts
        """
        query = """
            SELECT 
                bh.id as bom_header_id,
                bh.bom_code,
                bh.bom_name,
                bh.bom_type,
                bh.status,
                op.pt_code as output_product_code,
                op.name as output_product_name,
                COUNT(DISTINCT mo.id) as completed_mo_count,
                SUM(pr.passed_qty) as total_produced,
                MIN(mo.completion_date) as first_completion,
                MAX(mo.completion_date) as last_completion
            FROM bom_headers bh
            JOIN products op ON bh.product_id = op.id
            JOIN manufacturing_orders mo ON mo.bom_header_id = bh.id
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) pr ON mo.id = pr.manufacturing_order_id
            WHERE mo.status = 'COMPLETED'
              AND mo.delete_flag = 0
              AND bh.delete_flag = 0
        """
        
        params = {'min_mo_count': min_mo_count}
        
        if date_from:
            query += " AND mo.completion_date >= :date_from"
            params['date_from'] = date_from
        
        if date_to:
            query += " AND mo.completion_date <= :date_to"
            params['date_to'] = date_to
        
        query += """
            GROUP BY bh.id, bh.bom_code, bh.bom_name, bh.bom_type, bh.status,
                     op.pt_code, op.name
            HAVING COUNT(DISTINCT mo.id) >= :min_mo_count
            ORDER BY completed_mo_count DESC, bh.bom_code
        """
        
        try:
            return pd.read_sql(text(query), self.engine, params=params)
        except Exception as e:
            logger.error(f"Error getting BOM list for analysis: {e}")
            raise