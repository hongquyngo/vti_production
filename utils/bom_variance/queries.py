# utils/bom_variance/queries.py
"""
SQL Queries for BOM Variance Analysis - VERSION 1.0

Provides data extraction queries for:
- Actual consumption from completed Manufacturing Orders
- Theoretical values from BOM definitions
- Variance calculations and aggregations
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
    
    Data flow:
    1. Manufacturing Orders (COMPLETED) → actual consumption
    2. BOM Details → theoretical values
    3. Compare and calculate variance
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
        
        Args:
            bom_id: Filter by specific BOM (None for all)
            date_from: Start date filter
            date_to: End date filter
            min_mo_count: Minimum completed MOs required
            
        Returns:
            DataFrame with columns:
            - bom_header_id, bom_code, bom_name, bom_type
            - material_id, material_code, material_name
            - mo_count, total_produced, total_consumed
            - avg_per_unit, stddev_per_unit, cv_percent (coefficient of variation)
        """
        query = """
            SELECT 
                mo.bom_header_id,
                bh.bom_code,
                bh.bom_name,
                bh.bom_type,
                bh.output_qty as bom_output_qty,
                mom.material_id,
                p.pt_code as material_code,
                p.name as material_name,
                p.uom as material_uom,
                COUNT(DISTINCT mo.id) as mo_count,
                SUM(pr.passed_qty) as total_produced,
                SUM(mom.issued_qty) as total_consumed,
                -- Average consumption per output unit
                CASE 
                    WHEN SUM(pr.passed_qty) > 0 
                    THEN SUM(mom.issued_qty) / SUM(pr.passed_qty)
                    ELSE 0 
                END as avg_per_unit,
                -- Standard deviation (sample)
                STDDEV_SAMP(
                    CASE 
                        WHEN pr.passed_qty > 0 
                        THEN mom.issued_qty / pr.passed_qty 
                        ELSE NULL 
                    END
                ) as stddev_per_unit
            FROM manufacturing_orders mo
            JOIN bom_headers bh ON mo.bom_header_id = bh.id
            JOIN manufacturing_order_materials mom ON mo.id = mom.manufacturing_order_id
            JOIN products p ON mom.material_id = p.id
            -- Get passed production quantity per MO
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
              AND COALESCE(pr.passed_qty, 0) > 0
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
                mo.bom_header_id, bh.bom_code, bh.bom_name, bh.bom_type, bh.output_qty,
                mom.material_id, p.pt_code, p.name, p.uom
            HAVING COUNT(DISTINCT mo.id) >= :min_mo_count
            ORDER BY bh.bom_code, p.pt_code
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
        
        Returns:
            DataFrame with per-MO consumption data
        """
        query = """
            SELECT 
                mo.id as mo_id,
                mo.order_no,
                mo.order_date,
                mo.completion_date,
                mo.planned_qty,
                pr.passed_qty as produced_qty,
                mom.material_id,
                p.pt_code as material_code,
                p.name as material_name,
                mom.required_qty,
                mom.issued_qty,
                -- Consumption per output unit
                CASE 
                    WHEN pr.passed_qty > 0 
                    THEN mom.issued_qty / pr.passed_qty
                    ELSE 0 
                END as consumption_per_unit,
                -- Check if alternative was used
                CASE 
                    WHEN EXISTS (
                        SELECT 1 FROM material_issue_details mid
                        JOIN material_issues mi ON mid.material_issue_id = mi.id
                        WHERE mi.manufacturing_order_id = mo.id
                        AND mid.manufacturing_order_material_id = mom.id
                        AND mid.is_alternative = 1
                    ) THEN 1
                    ELSE 0
                END as used_alternative
            FROM manufacturing_orders mo
            JOIN manufacturing_order_materials mom ON mo.id = mom.manufacturing_order_id
            JOIN products p ON mom.material_id = p.id
            LEFT JOIN (
                SELECT 
                    manufacturing_order_id,
                    SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty
                FROM production_receipts
                GROUP BY manufacturing_order_id
            ) pr ON mo.id = pr.manufacturing_order_id
            WHERE mo.bom_header_id = :bom_id
              AND mo.status = 'COMPLETED'
              AND mo.delete_flag = 0
              AND COALESCE(pr.passed_qty, 0) > 0
        """
        
        params = {'bom_id': int(bom_id)}
        
        if material_id:
            query += " AND mom.material_id = :material_id"
            params['material_id'] = int(material_id)
        
        if date_from:
            query += " AND mo.completion_date >= :date_from"
            params['date_from'] = date_from
        
        if date_to:
            query += " AND mo.completion_date <= :date_to"
            params['date_to'] = date_to
        
        query += " ORDER BY mo.completion_date DESC, p.pt_code"
        
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
        
        This is the main query for variance analysis dashboard
        
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
            - Actual values (avg consumption, stddev)
            - Variance calculations (variance_qty, variance_pct)
            - Flags (high_variance, high_variability)
        """
        query = """
            WITH actual_data AS (
                SELECT 
                    mo.bom_header_id,
                    mom.material_id,
                    COUNT(DISTINCT mo.id) as mo_count,
                    SUM(pr.passed_qty) as total_produced,
                    SUM(mom.issued_qty) as total_consumed,
                    CASE 
                        WHEN SUM(pr.passed_qty) > 0 
                        THEN SUM(mom.issued_qty) / SUM(pr.passed_qty)
                        ELSE 0 
                    END as avg_per_unit,
                    STDDEV_SAMP(
                        CASE 
                            WHEN pr.passed_qty > 0 
                            THEN mom.issued_qty / pr.passed_qty 
                            ELSE NULL 
                        END
                    ) as stddev_per_unit,
                    MIN(mo.completion_date) as first_mo_date,
                    MAX(mo.completion_date) as last_mo_date
                FROM manufacturing_orders mo
                JOIN manufacturing_order_materials mom ON mo.id = mom.manufacturing_order_id
                LEFT JOIN (
                    SELECT 
                        manufacturing_order_id,
                        SUM(CASE WHEN quality_status = 'PASSED' THEN quantity ELSE 0 END) as passed_qty
                    FROM production_receipts
                    GROUP BY manufacturing_order_id
                ) pr ON mo.id = pr.manufacturing_order_id
                WHERE mo.status = 'COMPLETED' 
                  AND mo.delete_flag = 0
                  AND COALESCE(pr.passed_qty, 0) > 0
        """
        
        params = {'min_mo_count': min_mo_count}
        
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
                GROUP BY mo.bom_header_id, mom.material_id
                HAVING COUNT(DISTINCT mo.id) >= :min_mo_count
            ),
            theoretical_data AS (
                SELECT 
                    bh.id as bom_header_id,
                    bh.bom_code,
                    bh.bom_name,
                    bh.bom_type,
                    bh.status as bom_status,
                    bh.output_qty as bom_output_qty,
                    op.pt_code as output_product_code,
                    op.name as output_product_name,
                    bd.material_id,
                    mp.pt_code as material_code,
                    mp.name as material_name,
                    mp.uom as material_uom,
                    bd.material_type,
                    bd.quantity as bom_quantity,
                    bd.scrap_rate,
                    (bd.quantity / bh.output_qty) as qty_per_output,
                    (bd.quantity / bh.output_qty) * (1 + bd.scrap_rate/100) as qty_per_output_with_scrap
                FROM bom_headers bh
                JOIN products op ON bh.product_id = op.id
                JOIN bom_details bd ON bd.bom_header_id = bh.id
                JOIN products mp ON bd.material_id = mp.id
                WHERE bh.delete_flag = 0
        """
        
        if bom_id:
            query += " AND bh.id = :bom_id"
        
        query += """
            )
            SELECT 
                t.bom_header_id,
                t.bom_code,
                t.bom_name,
                t.bom_type,
                t.bom_status,
                t.bom_output_qty,
                t.output_product_code,
                t.output_product_name,
                t.material_id,
                t.material_code,
                t.material_name,
                t.material_uom,
                t.material_type,
                t.bom_quantity,
                t.scrap_rate,
                t.qty_per_output as theoretical_qty,
                t.qty_per_output_with_scrap as theoretical_qty_with_scrap,
                COALESCE(a.mo_count, 0) as mo_count,
                COALESCE(a.total_produced, 0) as total_produced,
                COALESCE(a.total_consumed, 0) as total_consumed,
                COALESCE(a.avg_per_unit, 0) as actual_avg_per_unit,
                COALESCE(a.stddev_per_unit, 0) as actual_stddev,
                a.first_mo_date,
                a.last_mo_date,
                -- Variance calculations
                CASE 
                    WHEN a.avg_per_unit IS NOT NULL AND t.qty_per_output_with_scrap > 0
                    THEN (a.avg_per_unit - t.qty_per_output_with_scrap)
                    ELSE NULL
                END as variance_qty,
                CASE 
                    WHEN a.avg_per_unit IS NOT NULL AND t.qty_per_output_with_scrap > 0
                    THEN ((a.avg_per_unit - t.qty_per_output_with_scrap) / t.qty_per_output_with_scrap) * 100
                    ELSE NULL
                END as variance_pct,
                -- Coefficient of variation
                CASE 
                    WHEN a.avg_per_unit > 0 AND a.stddev_per_unit IS NOT NULL
                    THEN (a.stddev_per_unit / a.avg_per_unit) * 100
                    ELSE 0
                END as cv_percent,
                -- Suggested values
                CASE 
                    WHEN a.avg_per_unit IS NOT NULL AND (1 + t.scrap_rate/100) > 0
                    THEN a.avg_per_unit / (1 + t.scrap_rate/100) * t.bom_output_qty
                    ELSE t.bom_quantity
                END as suggested_quantity,
                CASE 
                    WHEN a.avg_per_unit IS NOT NULL AND t.qty_per_output > 0
                    THEN ((a.avg_per_unit / t.qty_per_output) - 1) * 100
                    ELSE t.scrap_rate
                END as suggested_scrap_rate
            FROM theoretical_data t
            LEFT JOIN actual_data a ON t.bom_header_id = a.bom_header_id 
                                   AND t.material_id = a.material_id
            ORDER BY t.bom_code, t.material_type, t.material_code
        """
        
        try:
            df = pd.read_sql(text(query), self.engine, params=params)
            
            # Add flag columns
            if not df.empty:
                # High variance flag
                df['has_high_variance'] = df['variance_pct'].apply(
                    lambda x: abs(x) > variance_threshold if pd.notna(x) else False
                )
                
                # High variability flag (CV > 15%)
                df['has_high_variability'] = df['cv_percent'].apply(
                    lambda x: x > 15 if pd.notna(x) else False
                )
                
                # Has data flag
                df['has_actual_data'] = df['mo_count'] > 0
            
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
