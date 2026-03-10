# utils/supply_chain_gap/calculator.py

"""
Calculator for Supply Chain GAP Analysis
Performs full multi-level GAP calculation: FG + Raw Materials

VERSION: 2.0.0
CHANGELOG:
- v2.0: Multi-level BOM support with supply netting at intermediate levels
- v1.1: Fixed At Risk Value, is_primary comparison, avg_unit_price_usd
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from .constants import THRESHOLDS, STATUS_CONFIG, ACTION_TYPES, MAX_BOM_LEVELS
from .result import SupplyChainGAPResult, CustomerImpact, ActionRecommendation

logger = logging.getLogger(__name__)


class SupplyChainGAPCalculator:
    """
    Calculator for Supply Chain GAP Analysis.
    
    Performs:
    1. FG GAP calculation (supply vs demand)
    2. Product classification (manufacturing vs trading)
    3. BOM explosion for manufacturing products
    4. Raw material GAP calculation
    5. Action recommendations
    """
    
    def __init__(self):
        pass
    
    def calculate(
        self,
        # FG Data
        fg_supply_df: pd.DataFrame,
        fg_demand_df: pd.DataFrame,
        fg_safety_stock_df: Optional[pd.DataFrame] = None,
        
        # Classification & BOM
        classification_df: Optional[pd.DataFrame] = None,
        bom_explosion_df: Optional[pd.DataFrame] = None,
        existing_mo_demand_df: Optional[pd.DataFrame] = None,
        
        # Raw Material Data
        raw_supply_df: Optional[pd.DataFrame] = None,
        raw_safety_stock_df: Optional[pd.DataFrame] = None,
        
        # Options
        selected_supply_sources: Optional[List[str]] = None,
        selected_demand_sources: Optional[List[str]] = None,
        include_fg_safety: bool = True,
        include_raw_safety: bool = True,
        include_alternatives: bool = True,
        include_existing_mo: bool = True,
        include_draft_mo: bool = False,
        
        # Period Analysis (v2.2)
        period_type: str = 'Weekly',
        track_backlog: bool = True
    ) -> SupplyChainGAPResult:
        """
        Perform full Supply Chain GAP calculation.
        
        Returns:
            SupplyChainGAPResult with all analysis data
        """
        logger.info("Starting Supply Chain GAP calculation")
        
        # Detect MO Expected in supply sources
        include_mo_expected = (
            selected_supply_sources is not None and 'MO_EXPECTED' in selected_supply_sources
        )
        
        # Filter DRAFT MO from FG supply if not included
        # unified_supply_view returns DRAFT+CONFIRMED+IN_PROGRESS for MO_EXPECTED;
        # availability_status column holds the MO status.
        if not include_draft_mo and not fg_supply_df.empty and 'availability_status' in fg_supply_df.columns:
            before = len(fg_supply_df)
            fg_supply_df = fg_supply_df[
                ~((fg_supply_df['supply_source'] == 'MO_EXPECTED') & 
                  (fg_supply_df['availability_status'] == 'DRAFT'))
            ].copy()
            filtered = before - len(fg_supply_df)
            if filtered > 0:
                logger.info(f"Excluded {filtered} DRAFT MO rows from FG supply")
        
        # Double-count detection: MO output NOT in FG supply but MO raw demand IS included
        if not include_mo_expected and include_existing_mo:
            logger.warning(
                "⚠️ DOUBLE-COUNT RISK: MO_EXPECTED not in supply_sources but "
                "include_existing_mo=True. FG shortage is not reduced by in-flight MOs, "
                "so BOM explosion raw demand will overlap with existing MO demand."
            )
        
        result = SupplyChainGAPResult(
            timestamp=datetime.now(),
            period_type=period_type,
            filters_used={
                'supply_sources': selected_supply_sources,
                'demand_sources': selected_demand_sources,
                'include_fg_safety': include_fg_safety,
                'include_raw_safety': include_raw_safety,
                'include_mo_expected': include_mo_expected,
                'include_existing_mo': include_existing_mo,
                'include_draft_mo': include_draft_mo,
                'period_type': period_type,
                'track_backlog': track_backlog
            }
        )
        
        # =====================================================================
        # LEVEL 1: FG GAP
        # =====================================================================
        logger.info("Level 1: Calculating FG GAP...")
        
        fg_gap_df, fg_metrics, customer_impact = self._calculate_fg_gap(
            supply_df=fg_supply_df,
            demand_df=fg_demand_df,
            safety_stock_df=fg_safety_stock_df,
            selected_supply_sources=selected_supply_sources,
            selected_demand_sources=selected_demand_sources,
            include_safety=include_fg_safety
        )
        
        result.fg_gap_df = fg_gap_df
        result.fg_metrics = fg_metrics
        result.customer_impact = customer_impact
        
        logger.info(f"FG GAP: {len(fg_gap_df)} products, {fg_metrics.get('shortage_count', 0)} shortages")
        
        # =====================================================================
        # CLASSIFICATION
        # =====================================================================
        if classification_df is not None and not classification_df.empty:
            logger.info("Classifying products (Manufacturing vs Trading)...")
            
            # Scope classification to only products present in FG GAP
            # (prevents inflated counts when classification view returns all entities)
            if not fg_gap_df.empty and 'product_id' in fg_gap_df.columns:
                fg_product_ids = fg_gap_df['product_id'].tolist()
                classification_df = classification_df[
                    classification_df['product_id'].isin(fg_product_ids)
                ].copy()
            
            result.classification_df = classification_df
            result.manufacturing_df = classification_df[classification_df['has_bom'] == 1].copy()
            result.trading_df = classification_df[classification_df['has_bom'] == 0].copy()
            
            logger.info(f"Classification: {len(result.manufacturing_df)} MFG, {len(result.trading_df)} Trading")
        
        # =====================================================================
        # MULTI-LEVEL MATERIAL GAP (for manufacturing products with shortage)
        # =====================================================================
        # Replaces old single-level "Level 2" approach.
        # Iterates BOM levels: FG → Semi-Finished → ... → Raw Material
        # Supply netting at each intermediate level determines actual demand propagation.
        # =====================================================================
        if (bom_explosion_df is not None and not bom_explosion_df.empty and
            raw_supply_df is not None and not raw_supply_df.empty):
            
            logger.info("Multi-level: Calculating Material GAP (all BOM levels)...")
            
            mfg_shortage = result.get_manufacturing_shortage()
            
            if not mfg_shortage.empty:
                result.bom_explosion_df = bom_explosion_df
                result.raw_supply_df = raw_supply_df
                
                raw_gap_df, semi_gap_df, raw_metrics, alt_analysis, max_depth = \
                    self._calculate_multilevel_material_gap(
                        mfg_shortage_df=mfg_shortage,
                        bom_explosion_df=bom_explosion_df,
                        existing_mo_demand_df=existing_mo_demand_df if include_existing_mo else None,
                        raw_supply_df=raw_supply_df,
                        raw_safety_stock_df=raw_safety_stock_df if include_raw_safety else None,
                        include_alternatives=include_alternatives,
                        selected_supply_sources=selected_supply_sources
                    )
                
                result.raw_gap_df = raw_gap_df
                result.semi_finished_gap_df = semi_gap_df
                result.raw_metrics = raw_metrics
                result.alternative_analysis_df = alt_analysis
                result.max_bom_depth = max_depth
                
                logger.info(
                    f"Material GAP: {len(raw_gap_df)} raw materials, "
                    f"{len(semi_gap_df)} semi-finished, "
                    f"max depth={max_depth}, "
                    f"{raw_metrics.get('shortage_count', 0)} raw shortages"
                )
        
        # =====================================================================
        # ACTION RECOMMENDATIONS
        # =====================================================================
        logger.info("Generating action recommendations...")
        
        mo_suggestions, po_fg_suggestions, po_raw_suggestions = self._generate_actions(result)
        
        result.mo_suggestions = mo_suggestions
        result.po_fg_suggestions = po_fg_suggestions
        result.po_raw_suggestions = po_raw_suggestions
        
        logger.info(f"Actions: {len(mo_suggestions)} MO, {len(po_fg_suggestions)} PO-FG, {len(po_raw_suggestions)} PO-Raw")
        
        # =====================================================================
        # PERIOD-BASED GAP ANALYSIS (v2.2)
        # Uses the original (pre-aggregated) supply/demand with dates
        # =====================================================================
        try:
            from .period_calculator import PeriodGAPCalculator
            
            logger.info(f"Period GAP: calculating {period_type} periods...")
            
            period_calc = PeriodGAPCalculator(period_type=period_type)
            period_gap_df, period_metrics = period_calc.calculate_fg_period_gap(
                fg_supply_df=fg_supply_df,
                fg_demand_df=fg_demand_df,
                fg_safety_stock_df=fg_safety_stock_df,
                selected_supply_sources=selected_supply_sources,
                selected_demand_sources=selected_demand_sources,
                include_safety=include_fg_safety,
                track_backlog=track_backlog,
                include_draft_mo=include_draft_mo
            )
            
            result.fg_period_gap_df = period_gap_df
            result.fg_period_metrics = period_metrics
            
            logger.info(
                f"Period GAP: {len(period_gap_df)} rows, "
                f"{period_metrics.get('shortage_periods', 0)} shortage periods"
            )
        except Exception as e:
            logger.error(f"Period GAP calculation failed (non-fatal): {e}", exc_info=True)
            # Period GAP failure is non-fatal — net GAP + actions are still valid
        
        return result
    
    # =========================================================================
    # LEVEL 1: FG GAP CALCULATION
    # =========================================================================
    
    def _calculate_fg_gap(
        self,
        supply_df: pd.DataFrame,
        demand_df: pd.DataFrame,
        safety_stock_df: Optional[pd.DataFrame],
        selected_supply_sources: Optional[List[str]],
        selected_demand_sources: Optional[List[str]],
        include_safety: bool
    ) -> Tuple[pd.DataFrame, Dict[str, Any], CustomerImpact]:
        """Calculate FG GAP"""
        
        # Filter by sources
        if selected_supply_sources and not supply_df.empty:
            supply_df = supply_df[supply_df['supply_source'].isin(selected_supply_sources)]
        
        if selected_demand_sources and not demand_df.empty:
            demand_df = demand_df[demand_df['demand_source'].isin(selected_demand_sources)]
        
        # Aggregate supply by product
        if supply_df.empty:
            supply_agg = pd.DataFrame(columns=['product_id', 'total_supply'])
        else:
            supply_agg = supply_df.groupby('product_id').agg({
                'available_quantity': 'sum',
                'product_name': 'first',
                'pt_code': 'first',
                'brand': 'first',
                'package_size': 'first',
                'standard_uom': 'first',
                'unit_cost_usd': 'mean'
            }).reset_index()
            supply_agg.rename(columns={'available_quantity': 'total_supply'}, inplace=True)
            
            # Add supply by source
            if 'supply_source' in supply_df.columns:
                for source in ['INVENTORY', 'CAN_PENDING', 'WAREHOUSE_TRANSFER', 'PURCHASE_ORDER', 'MO_EXPECTED']:
                    source_sum = supply_df[supply_df['supply_source'] == source].groupby('product_id')['available_quantity'].sum()
                    supply_agg[f'supply_{source.lower()}'] = supply_agg['product_id'].map(source_sum).fillna(0)
        
        # Aggregate demand by product
        # FIXED: Use total_value_usd instead of selling_unit_price for USD calculation
        if demand_df.empty:
            demand_agg = pd.DataFrame(columns=['product_id', 'total_demand'])
        else:
            # Build aggregation dict dynamically based on available columns
            agg_dict = {
                'required_quantity': 'sum',
                'product_name': 'first',
                'pt_code': 'first',
                'brand': 'first',
                'package_size': 'first',
                'standard_uom': 'first',
                'customer': lambda x: x.nunique()
            }
            
            # Add total_value_usd for proper USD calculation
            if 'total_value_usd' in demand_df.columns:
                agg_dict['total_value_usd'] = 'sum'
            
            # Keep selling_unit_price for reference (original currency)
            if 'selling_unit_price' in demand_df.columns:
                agg_dict['selling_unit_price'] = 'mean'
            
            demand_agg = demand_df.groupby('product_id').agg(agg_dict).reset_index()
            
            demand_agg.rename(columns={
                'required_quantity': 'total_demand',
                'customer': 'customer_count'
            }, inplace=True)
            
            # FIXED: Calculate avg_unit_price_usd from total_value_usd / total_demand
            # This ensures we use USD values, not original currency (VND/EUR/etc.)
            if 'total_value_usd' in demand_agg.columns:
                demand_agg['avg_unit_price_usd'] = np.where(
                    demand_agg['total_demand'] > 0,
                    demand_agg['total_value_usd'] / demand_agg['total_demand'],
                    0
                )
            else:
                # Fallback: if no total_value_usd, set to 0 (at_risk_value will be 0)
                demand_agg['avg_unit_price_usd'] = 0
                logger.warning("total_value_usd not found in demand data - at_risk_value will be 0")
            
            # Add demand by source
            if 'demand_source' in demand_df.columns:
                for source in ['OC_PENDING', 'FORECAST']:
                    source_sum = demand_df[demand_df['demand_source'] == source].groupby('product_id')['required_quantity'].sum()
                    demand_agg[f'demand_{source.lower()}'] = demand_agg['product_id'].map(source_sum).fillna(0)
        
        # Merge supply and demand
        all_products = set(supply_agg['product_id'].tolist() if not supply_agg.empty else []) | \
                       set(demand_agg['product_id'].tolist() if not demand_agg.empty else [])
        
        if not all_products:
            return pd.DataFrame(), {}, CustomerImpact()
        
        gap_df = pd.DataFrame({'product_id': list(all_products)})
        
        if not supply_agg.empty:
            gap_df = gap_df.merge(supply_agg, on='product_id', how='left')
        
        if not demand_agg.empty:
            gap_df = gap_df.merge(demand_agg, on='product_id', how='left', suffixes=('', '_demand'))
            # Clean up duplicate columns
            for col in ['product_name', 'pt_code', 'brand', 'package_size', 'standard_uom']:
                if f'{col}_demand' in gap_df.columns:
                    gap_df[col] = gap_df[col].fillna(gap_df[f'{col}_demand'])
                    gap_df.drop(columns=[f'{col}_demand'], inplace=True)
        
        # Fill NaN
        gap_df['total_supply'] = gap_df['total_supply'].fillna(0) if 'total_supply' in gap_df.columns else 0
        gap_df['total_demand'] = gap_df['total_demand'].fillna(0) if 'total_demand' in gap_df.columns else 0
        gap_df['avg_unit_price_usd'] = gap_df['avg_unit_price_usd'].fillna(0) if 'avg_unit_price_usd' in gap_df.columns else 0
        
        # Add safety stock
        if include_safety and safety_stock_df is not None and not safety_stock_df.empty:
            gap_df = gap_df.merge(
                safety_stock_df[['product_id', 'safety_stock_qty', 'reorder_point']],
                on='product_id',
                how='left'
            )
            gap_df['safety_stock_qty'] = gap_df['safety_stock_qty'].fillna(0) if 'safety_stock_qty' in gap_df.columns else 0
        else:
            gap_df['safety_stock_qty'] = 0
        
        # Calculate GAP
        gap_df['safety_gap'] = gap_df['total_supply'] - gap_df['safety_stock_qty']
        gap_df['available_supply'] = gap_df['safety_gap'].clip(lower=0)
        gap_df['net_gap'] = gap_df['available_supply'] - gap_df['total_demand']
        gap_df['true_gap'] = gap_df['total_supply'] - gap_df['total_demand']
        
        # Coverage ratio
        gap_df['coverage_ratio'] = np.where(
            gap_df['total_demand'] > 0,
            gap_df['available_supply'] / gap_df['total_demand'],
            np.where(gap_df['total_supply'] > 0, 999, 0)
        )
        
        # Classify status
        gap_df['gap_status'] = gap_df.apply(self._classify_gap_status, axis=1)
        gap_df['gap_group'] = gap_df['gap_status'].apply(self._get_gap_group)
        gap_df['priority'] = gap_df['gap_status'].apply(lambda x: STATUS_CONFIG.get(x, {}).get('priority', 99))
        
        # FIXED: At risk value - Use avg_unit_price_usd (already in USD)
        # OLD (WRONG): selling_price = gap_df['selling_unit_price'].fillna(0) - This is original currency (VND)!
        # NEW (CORRECT): Use avg_unit_price_usd calculated from total_value_usd / total_demand
        gap_df['at_risk_value'] = np.where(
            gap_df['net_gap'] < 0,
            abs(gap_df['net_gap']) * gap_df['avg_unit_price_usd'],
            0
        )
        
        # Sort by priority
        gap_df = gap_df.sort_values(['priority', 'net_gap']).reset_index(drop=True)
        
        # Calculate metrics
        metrics = self._calculate_fg_metrics(gap_df)
        
        # Customer impact
        customer_impact = self._calculate_customer_impact(demand_df, gap_df)
        
        return gap_df, metrics, customer_impact
    
    def _classify_gap_status(self, row) -> str:
        """Classify GAP status based on net_gap sign and coverage"""
        net_gap = row.get('net_gap', 0)
        total_demand = row.get('total_demand', 0)
        total_supply = row.get('total_supply', 0)
        coverage = row.get('coverage_ratio', 0)
        
        # No activity cases
        if total_demand == 0 and total_supply == 0:
            return 'NO_ACTIVITY'
        if total_demand == 0:
            return 'NO_DEMAND'
        
        # Shortage
        if net_gap < 0:
            if coverage < THRESHOLDS['shortage']['critical']:
                return 'CRITICAL_SHORTAGE'
            elif coverage < THRESHOLDS['shortage']['severe']:
                return 'SEVERE_SHORTAGE'
            elif coverage < THRESHOLDS['shortage']['high']:
                return 'HIGH_SHORTAGE'
            elif coverage < THRESHOLDS['shortage']['moderate']:
                return 'MODERATE_SHORTAGE'
            else:
                return 'LIGHT_SHORTAGE'
        
        # Balanced
        if net_gap == 0:
            return 'BALANCED'
        
        # Surplus
        if coverage <= THRESHOLDS['surplus']['light']:
            return 'LIGHT_SURPLUS'
        elif coverage <= THRESHOLDS['surplus']['moderate']:
            return 'MODERATE_SURPLUS'
        elif coverage <= THRESHOLDS['surplus']['high']:
            return 'HIGH_SURPLUS'
        else:
            return 'SEVERE_SURPLUS'
    
    def _get_gap_group(self, status: str) -> str:
        """Get GAP group from status"""
        if 'SHORTAGE' in status:
            return 'SHORTAGE'
        elif status == 'BALANCED':
            return 'OPTIMAL'
        elif 'SURPLUS' in status:
            return 'SURPLUS'
        else:
            return 'INACTIVE'
    
    def _calculate_fg_metrics(self, gap_df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate FG metrics"""
        if gap_df.empty:
            return {}
        
        return {
            'total_items': len(gap_df),
            'shortage_count': len(gap_df[gap_df['net_gap'] < 0]),
            'surplus_count': len(gap_df[gap_df['net_gap'] > 0]),
            'balanced_count': len(gap_df[gap_df['net_gap'] == 0]),
            'at_risk_value': gap_df['at_risk_value'].sum(),
            'total_supply': gap_df['total_supply'].sum(),
            'total_demand': gap_df['total_demand'].sum()
        }
    
    def _calculate_customer_impact(
        self,
        demand_df: pd.DataFrame,
        gap_df: pd.DataFrame
    ) -> CustomerImpact:
        """
        Calculate customer impact from shortages with proportional at-risk allocation.
        
        Each customer × product line gets:
        - demand_qty: customer's demand for this product
        - shortage_qty: product-level shortage = |net_gap|
        - total_demand: product-level total demand (denominator for proportion)
        - at_risk_qty: customer's proportional share = demand_qty / total_demand × shortage_qty
        - at_risk_value_usd: at_risk_qty × avg_unit_price_usd
        - demand_value_usd: customer's total demand value (for context)
        - gap_status: severity level of the product shortage
        """
        if demand_df.empty or gap_df.empty:
            return CustomerImpact()
        
        # Only shortage products
        shortage_gap = gap_df[gap_df['net_gap'] < 0].copy()
        if shortage_gap.empty:
            return CustomerImpact()
        
        shortage_products = shortage_gap['product_id'].tolist()
        affected_demand = demand_df[demand_df['product_id'].isin(shortage_products)]
        
        if affected_demand.empty or 'customer' not in affected_demand.columns:
            return CustomerImpact()
        
        affected_customers = affected_demand['customer'].dropna().unique().tolist()
        at_risk_value = shortage_gap['at_risk_value'].sum()
        
        # Build line-level detail with proportional at-risk allocation
        details = pd.DataFrame()
        try:
            # Prepare product-level info from gap_df (shortage products only)
            product_cols = ['product_id', 'total_demand', 'net_gap', 'gap_status', 'avg_unit_price_usd']
            for opt_col in ['pt_code', 'product_name', 'brand', 'package_size', 'standard_uom']:
                if opt_col in gap_df.columns:
                    product_cols.append(opt_col)
            
            available_product_cols = [c for c in product_cols if c in shortage_gap.columns]
            product_info = shortage_gap[available_product_cols].copy()
            product_info['shortage_qty'] = product_info['net_gap'].abs()
            
            # Aggregate demand per customer × product
            line_agg = {'required_quantity': 'sum'}
            if 'total_value_usd' in affected_demand.columns:
                line_agg['total_value_usd'] = 'sum'
            
            lines = affected_demand.groupby(['customer', 'product_id']).agg(line_agg).reset_index()
            lines.rename(columns={
                'required_quantity': 'demand_qty',
                'total_value_usd': 'demand_value_usd'
            }, inplace=True)
            
            # Merge with product info
            details = lines.merge(product_info, on='product_id', how='left')
            
            # Proportional at-risk allocation
            # at_risk_qty = (customer_demand / product_total_demand) × shortage_qty
            details['total_demand'] = details['total_demand'].fillna(0)
            details['shortage_qty'] = details['shortage_qty'].fillna(0)
            details['avg_unit_price_usd'] = details['avg_unit_price_usd'].fillna(0)
            
            details['at_risk_qty'] = np.where(
                details['total_demand'] > 0,
                (details['demand_qty'] / details['total_demand']) * details['shortage_qty'],
                0
            ).round(0)
            
            # Cap: customer can't be at risk for more than they ordered
            details['at_risk_qty'] = details[['at_risk_qty', 'demand_qty']].min(axis=1)
            
            details['at_risk_value_usd'] = (
                details['at_risk_qty'] * details['avg_unit_price_usd']
            ).round(2)
            
            # Sort: highest at-risk value first within each customer
            details = details.sort_values(
                ['at_risk_value_usd', 'customer'],
                ascending=[False, True]
            ).reset_index(drop=True)
            
        except Exception as e:
            logger.warning(f"Could not build customer impact details: {e}")
        
        return CustomerImpact(
            affected_count=len(affected_customers),
            affected_customers=affected_customers,
            at_risk_value=at_risk_value,
            details=details
        )
    
    # =========================================================================
    # LEVEL 2: RAW MATERIAL GAP CALCULATION
    # =========================================================================
    
    def _calculate_raw_demand(
        self,
        fg_shortage_df: pd.DataFrame,
        bom_explosion_df: pd.DataFrame,
        existing_mo_demand_df: Optional[pd.DataFrame]
    ) -> pd.DataFrame:
        """Calculate raw material demand from FG shortage + BOM explosion"""
        
        if fg_shortage_df.empty or bom_explosion_df.empty:
            return pd.DataFrame()
        
        # Identify the FG product ID column
        id_col = 'output_product_id' if 'output_product_id' in bom_explosion_df.columns else 'fg_product_id'
        
        # Merge shortage with BOM
        merged = bom_explosion_df.merge(
            fg_shortage_df[['product_id', 'net_gap']].rename(columns={'product_id': id_col, 'net_gap': 'fg_shortage'}),
            on=id_col,
            how='inner'
        )
        
        if merged.empty:
            return pd.DataFrame()
        
        # Calculate required quantity
        # required_qty = (fg_shortage / output_qty) * quantity_per_output * (1 + scrap_rate/100)
        merged['fg_shortage'] = merged['fg_shortage'].abs()
        merged['bom_output_quantity'] = merged['bom_output_quantity'].fillna(1).replace(0, 1) if 'bom_output_quantity' in merged.columns else 1
        merged['quantity_per_output'] = merged['quantity_per_output'].fillna(1) if 'quantity_per_output' in merged.columns else 1
        merged['scrap_rate'] = merged['scrap_rate'].fillna(0) if 'scrap_rate' in merged.columns else 0
        
        merged['required_qty'] = (
            (merged['fg_shortage'] / merged['bom_output_quantity']) *
            merged['quantity_per_output'] *
            (1 + merged['scrap_rate'] / 100)
        )
        
        # Build aggregation dict with only existing columns
        agg_cols = {
            'required_qty': 'sum',
            id_col: 'nunique'
        }
        
        # Add optional columns if they exist
        optional_cols = {
            'material_pt_code': 'first',
            'material_name': 'first',
            'material_brand': 'first',
            'material_package_size': 'first',
            'material_uom': 'first',
            'material_type': 'first',
            'is_primary': 'first',
            'alternative_priority': 'first',
            'primary_material_id': 'first'
        }
        
        for col, agg_func in optional_cols.items():
            if col in merged.columns:
                agg_cols[col] = agg_func
        
        raw_demand = merged.groupby('material_id').agg(agg_cols).reset_index()
        raw_demand.rename(columns={id_col: 'fg_product_count'}, inplace=True)
        
        # Add existing MO demand
        # Note: manufacturing_raw_demand_view returns 'pending_material_qty', 
        # data_loader renames it to 'pending_qty'
        if existing_mo_demand_df is not None and not existing_mo_demand_df.empty:
            # Check for column name variants
            pending_col = 'pending_qty' if 'pending_qty' in existing_mo_demand_df.columns else 'pending_material_qty'
            
            if pending_col in existing_mo_demand_df.columns:
                mo_demand = existing_mo_demand_df.groupby('material_id')[pending_col].sum().reset_index()
                mo_demand.rename(columns={pending_col: 'existing_mo_demand'}, inplace=True)
                
                raw_demand = raw_demand.merge(mo_demand, on='material_id', how='left')
                raw_demand['existing_mo_demand'] = raw_demand['existing_mo_demand'].fillna(0)
                raw_demand['total_required_qty'] = raw_demand['required_qty'] + raw_demand['existing_mo_demand']
            else:
                logger.warning(f"pending_qty column not found in existing_mo_demand_df. Available: {existing_mo_demand_df.columns.tolist()}")
                raw_demand['existing_mo_demand'] = 0
                raw_demand['total_required_qty'] = raw_demand['required_qty']
        else:
            raw_demand['existing_mo_demand'] = 0
            raw_demand['total_required_qty'] = raw_demand['required_qty']
        
        return raw_demand
    
    def _calculate_raw_gap(
        self,
        raw_demand_df: pd.DataFrame,
        raw_supply_df: pd.DataFrame,
        raw_safety_stock_df: Optional[pd.DataFrame],
        include_alternatives: bool,
        selected_supply_sources: Optional[List[str]] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
        """Calculate raw material GAP"""
        
        if raw_demand_df.empty:
            return pd.DataFrame(), {}, pd.DataFrame()
        
        # Map supply source to column names in raw_material_supply_summary_view
        SOURCE_TO_COLUMN = {
            'INVENTORY': 'inventory_qty',
            'CAN_PENDING': 'can_pending_qty',
            'WAREHOUSE_TRANSFER': 'warehouse_transfer_qty',
            'PURCHASE_ORDER': 'purchase_order_qty'
        }
        
        # Aggregate supply by material
        # Note: raw_supply_df comes from raw_material_supply_summary_view which already has total_supply
        if raw_supply_df.empty:
            supply_agg = pd.DataFrame(columns=['material_id', 'total_supply'])
        else:
            # FIXED: Recalculate total_supply based on selected supply sources
            supply_agg = raw_supply_df.copy()
            
            if selected_supply_sources:
                # Get columns for selected sources
                selected_cols = [SOURCE_TO_COLUMN[s] for s in selected_supply_sources 
                               if s in SOURCE_TO_COLUMN]
                
                if selected_cols:
                    # Ensure columns exist (fill with 0 if missing)
                    for col in selected_cols:
                        if col not in supply_agg.columns:
                            supply_agg[col] = 0
                    
                    # Recalculate total_supply from selected sources only
                    supply_agg['total_supply'] = supply_agg[selected_cols].fillna(0).sum(axis=1)
                    logger.info(f"Raw material supply recalculated with sources: {selected_supply_sources}")
            
            # If no selected sources or total_supply already exists, use it
            if 'total_supply' in supply_agg.columns:
                # Group by material_id in case of duplicates
                supply_agg = supply_agg.groupby('material_id')['total_supply'].sum().reset_index()
            elif 'available_quantity' in supply_agg.columns:
                # Detail view - need to aggregate
                supply_agg = supply_agg.groupby('material_id').agg({
                    'available_quantity': 'sum'
                }).reset_index()
                supply_agg.rename(columns={'available_quantity': 'total_supply'}, inplace=True)
            else:
                # Fallback - empty
                supply_agg = pd.DataFrame(columns=['material_id', 'total_supply'])
        
        # Merge demand with supply
        raw_gap = raw_demand_df.merge(supply_agg, on='material_id', how='left')
        raw_gap['total_supply'] = raw_gap['total_supply'].fillna(0) if 'total_supply' in raw_gap.columns else 0
        
        # Add safety stock
        if raw_safety_stock_df is not None and not raw_safety_stock_df.empty:
            raw_gap = raw_gap.merge(
                raw_safety_stock_df[['material_id', 'safety_stock_qty']],
                on='material_id',
                how='left'
            )
            raw_gap['safety_stock_qty'] = raw_gap['safety_stock_qty'].fillna(0) if 'safety_stock_qty' in raw_gap.columns else 0
        else:
            raw_gap['safety_stock_qty'] = 0
        
        # Calculate GAP
        raw_gap['safety_gap'] = raw_gap['total_supply'] - raw_gap['safety_stock_qty']
        raw_gap['available_supply'] = raw_gap['safety_gap'].clip(lower=0)
        raw_gap['net_gap'] = raw_gap['available_supply'] - raw_gap['total_required_qty']
        
        # Coverage ratio
        raw_gap['coverage_ratio'] = np.where(
            raw_gap['total_required_qty'] > 0,
            raw_gap['available_supply'] / raw_gap['total_required_qty'],
            np.where(raw_gap['total_supply'] > 0, 999, 0)
        )
        
        # Classify status
        raw_gap['gap_status'] = raw_gap.apply(self._classify_gap_status, axis=1)
        raw_gap['priority'] = raw_gap['gap_status'].apply(lambda x: STATUS_CONFIG.get(x, {}).get('priority', 99))
        
        # Sort
        raw_gap = raw_gap.sort_values(['priority', 'net_gap']).reset_index(drop=True)
        
        # Metrics
        metrics = {
            'total_materials': len(raw_gap),
            'shortage_count': len(raw_gap[raw_gap['net_gap'] < 0]),
            'sufficient_count': len(raw_gap[raw_gap['net_gap'] >= 0])
        }
        
        # Alternative analysis
        alt_analysis = pd.DataFrame()
        if include_alternatives and 'is_primary' in raw_gap.columns:
            alt_analysis = self._analyze_alternatives(raw_gap)
            if not alt_analysis.empty and 'can_cover_shortage' in alt_analysis.columns:
                metrics['alternative_available'] = len(alt_analysis[alt_analysis['can_cover_shortage'] == True])
            else:
                metrics['alternative_available'] = 0
        
        return raw_gap, metrics, alt_analysis
    
    def _analyze_alternatives(self, raw_gap_df: pd.DataFrame) -> pd.DataFrame:
        """Analyze alternative materials for shortage primaries"""
        
        if raw_gap_df.empty or 'is_primary' not in raw_gap_df.columns:
            return pd.DataFrame()
        
        # FIXED: Use 1/0 comparison instead of True/False for SQL compatibility
        # SQL returns is_primary as 1 or 0, not Python True/False
        primary_shortage = raw_gap_df[
            (raw_gap_df['is_primary'].isin([1, True])) & 
            (raw_gap_df['net_gap'] < 0)
        ]
        
        if primary_shortage.empty:
            return pd.DataFrame()
        
        # Get alternative materials
        alternatives = raw_gap_df[raw_gap_df['is_primary'].isin([0, False])].copy()
        
        if alternatives.empty:
            return pd.DataFrame()
        
        # Match alternatives to primaries by primary_material_id
        # (alternative materials have primary_material_id pointing to their primary)
        if 'primary_material_id' not in alternatives.columns:
            return pd.DataFrame()
        
        results = []
        for _, primary in primary_shortage.iterrows():
            primary_id = primary.get('material_id')
            if pd.isna(primary_id):
                continue
            
            # Find alternatives that reference this primary
            group_alts = alternatives[alternatives['primary_material_id'] == primary_id]
            for _, alt in group_alts.iterrows():
                can_cover = alt.get('net_gap', 0) >= abs(primary.get('net_gap', 0))
                results.append({
                    'primary_material_id': primary_id,
                    'primary_pt_code': primary.get('material_pt_code'),
                    'primary_net_gap': primary.get('net_gap'),
                    'alternative_material_id': alt['material_id'],
                    'material_pt_code': alt.get('material_pt_code'),
                    'material_name': alt.get('material_name'),
                    'net_gap': alt.get('net_gap'),
                    'alternative_priority': alt.get('alternative_priority', 99),
                    'can_cover_shortage': can_cover
                })
        
        return pd.DataFrame(results) if results else pd.DataFrame()
    
    # =========================================================================
    # MULTI-LEVEL MATERIAL GAP (iterative BOM explosion with supply netting)
    # =========================================================================
    
    def _calculate_multilevel_material_gap(
        self,
        mfg_shortage_df: pd.DataFrame,
        bom_explosion_df: pd.DataFrame,
        existing_mo_demand_df: Optional[pd.DataFrame],
        raw_supply_df: pd.DataFrame,
        raw_safety_stock_df: Optional[pd.DataFrame],
        include_alternatives: bool,
        selected_supply_sources: Optional[List[str]]
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any], pd.DataFrame, int]:
        """
        Multi-level material GAP with supply netting at intermediate levels.
        
        Algorithm:
        1. Start with FG manufacturing shortage as demand drivers
        2. For each BOM level:
           a. Explode BOM: parent shortage × BOM → material demand
           b. Classify materials: leaf (raw) vs semi-finished (has own BOM)
           c. Leaf materials: accumulate demand for final GAP calculation
           d. Semi-finished: calculate immediate GAP with supply netting
              - If shortage: net shortage propagates to next level
              - If sufficient: no further propagation (supply covers demand)
        3. After all levels: calculate final raw material GAP (aggregated leaf demand)
        4. Return combined results
        
        Returns:
            (raw_gap_df, semi_finished_gap_df, raw_metrics, alt_analysis, max_depth)
        """
        
        id_col = 'output_product_id' if 'output_product_id' in bom_explosion_df.columns else 'fg_product_id'
        
        # Determine which materials have their own BOM (semi-finished)
        products_with_bom = set(bom_explosion_df[id_col].unique())
        
        # Pre-process supply data for quick lookup
        supply_by_material = self._prepare_supply_lookup(
            raw_supply_df, selected_supply_sources
        )
        
        # Pre-process safety stock for quick lookup
        safety_by_material = {}
        if raw_safety_stock_df is not None and not raw_safety_stock_df.empty:
            safety_id = 'material_id' if 'material_id' in raw_safety_stock_df.columns else 'product_id'
            for _, row in raw_safety_stock_df.iterrows():
                safety_by_material[row[safety_id]] = row.get('safety_stock_qty', 0) or 0
        
        # Iteration state
        leaf_demand_parts = []       # Raw material demand accumulated across all levels
        semi_finished_gaps = []      # GAP results for semi-finished materials
        max_depth = 0
        
        current_shortage = mfg_shortage_df[['product_id', 'net_gap']].copy()
        current_shortage['net_gap'] = current_shortage['net_gap'].abs()  # work with positive qty
        
        for level in range(1, MAX_BOM_LEVELS + 1):
            if current_shortage.empty:
                break
            
            max_depth = level
            logger.info(f"  Level {level}: {len(current_shortage)} parent products with shortage")
            
            # --- Step A: Explode BOM for current shortage products ---
            shortage_ids = current_shortage['product_id'].tolist()
            level_bom = bom_explosion_df[bom_explosion_df[id_col].isin(shortage_ids)].copy()
            
            if level_bom.empty:
                logger.info(f"  Level {level}: No BOM found for shortage products")
                break
            
            # --- Step B: Calculate demand per material ---
            level_demand = self._calculate_level_demand(
                parent_shortage_df=current_shortage,
                bom_df=level_bom,
                id_col=id_col
            )
            
            if level_demand.empty:
                break
            
            # --- Step C: Tag leaf vs semi-finished ---
            level_demand['is_leaf'] = ~level_demand['material_id'].isin(products_with_bom)
            level_demand['bom_level'] = level
            level_demand['material_category'] = np.where(
                level_demand['is_leaf'], 'RAW_MATERIAL', 'SEMI_FINISHED'
            )
            
            leaf_materials = level_demand[level_demand['is_leaf']].copy()
            semi_materials = level_demand[~level_demand['is_leaf']].copy()
            
            # --- Step D: Accumulate leaf demand ---
            if not leaf_materials.empty:
                leaf_demand_parts.append(leaf_materials)
                logger.info(f"  Level {level}: {len(leaf_materials)} leaf (raw) materials")
            
            # --- Step E: Semi-finished → immediate GAP with supply netting ---
            next_shortage_rows = []
            
            if not semi_materials.empty:
                logger.info(f"  Level {level}: {len(semi_materials)} semi-finished materials")
                
                semi_gap = self._calculate_material_gap_core(
                    demand_df=semi_materials,
                    supply_lookup=supply_by_material,
                    safety_lookup=safety_by_material,
                    bom_level=level,
                    material_category='SEMI_FINISHED'
                )
                semi_finished_gaps.append(semi_gap)
                
                # Propagate: semi-finished with net shortage → next level
                semi_with_shortage = semi_gap[semi_gap['net_gap'] < 0].copy()
                if not semi_with_shortage.empty:
                    next_shortage = semi_with_shortage[['material_id', 'net_gap']].copy()
                    next_shortage.rename(columns={'material_id': 'product_id'}, inplace=True)
                    next_shortage['net_gap'] = next_shortage['net_gap'].abs()
                    next_shortage_rows.append(next_shortage)
            
            if not next_shortage_rows:
                break
            
            current_shortage = pd.concat(next_shortage_rows, ignore_index=True)
        
        # =====================================================================
        # FINAL: Calculate raw material GAP (all leaf demand aggregated)
        # =====================================================================
        raw_gap_df = pd.DataFrame()
        alt_analysis = pd.DataFrame()
        
        if leaf_demand_parts:
            all_leaf_demand = pd.concat(leaf_demand_parts, ignore_index=True)
            
            # Aggregate by material_id (same raw material from multiple BOM paths/levels)
            raw_demand_agg = self._aggregate_leaf_demand(all_leaf_demand, id_col)
            
            # Add existing MO demand (once, for all raw materials)
            raw_demand_agg = self._add_existing_mo_demand(raw_demand_agg, existing_mo_demand_df)
            
            # Calculate final GAP
            raw_gap_df = self._calculate_material_gap_core(
                demand_df=raw_demand_agg,
                supply_lookup=supply_by_material,
                safety_lookup=safety_by_material,
                bom_level=0,  # 0 = aggregated across levels
                material_category='RAW_MATERIAL'
            )
            # Restore actual min bom_level from accumulated demand
            if 'min_bom_level' in raw_demand_agg.columns:
                level_map = raw_demand_agg.set_index('material_id')['min_bom_level']
                raw_gap_df['bom_level'] = raw_gap_df['material_id'].map(level_map).fillna(1).astype(int)
            
            # Alternative analysis
            if include_alternatives and 'is_primary' in raw_gap_df.columns:
                alt_analysis = self._analyze_alternatives(raw_gap_df)
        
        # Build semi-finished combined df
        semi_gap_df = pd.DataFrame()
        if semi_finished_gaps:
            semi_gap_df = pd.concat(semi_finished_gaps, ignore_index=True)
        
        # Metrics
        raw_metrics = {
            'total_materials': len(raw_gap_df),
            'shortage_count': len(raw_gap_df[raw_gap_df['net_gap'] < 0]) if not raw_gap_df.empty else 0,
            'sufficient_count': len(raw_gap_df[raw_gap_df['net_gap'] >= 0]) if not raw_gap_df.empty else 0,
            'semi_finished_count': len(semi_gap_df),
            'semi_finished_shortage': len(semi_gap_df[semi_gap_df['net_gap'] < 0]) if not semi_gap_df.empty else 0,
            'max_bom_depth': max_depth,
        }
        if not alt_analysis.empty and 'can_cover_shortage' in alt_analysis.columns:
            raw_metrics['alternative_available'] = len(alt_analysis[alt_analysis['can_cover_shortage'] == True])
        else:
            raw_metrics['alternative_available'] = 0
        
        logger.info(
            f"  Multi-level complete: {max_depth} levels, "
            f"{raw_metrics['total_materials']} raw, "
            f"{raw_metrics['semi_finished_count']} semi-finished"
        )
        
        return raw_gap_df, semi_gap_df, raw_metrics, alt_analysis, max_depth
    
    def _prepare_supply_lookup(
        self,
        raw_supply_df: pd.DataFrame,
        selected_supply_sources: Optional[List[str]]
    ) -> Dict[int, float]:
        """
        Pre-process supply data into material_id → total_supply lookup.
        Respects selected_supply_sources filter.
        """
        if raw_supply_df.empty:
            return {}
        
        SOURCE_TO_COLUMN = {
            'INVENTORY': 'inventory_qty',
            'CAN_PENDING': 'can_pending_qty',
            'WAREHOUSE_TRANSFER': 'warehouse_transfer_qty',
            'PURCHASE_ORDER': 'purchase_order_qty'
        }
        
        supply_df = raw_supply_df.copy()
        mat_id_col = 'material_id' if 'material_id' in supply_df.columns else 'product_id'
        
        # Recalculate total_supply if specific sources selected
        if selected_supply_sources:
            selected_cols = [SOURCE_TO_COLUMN[s] for s in selected_supply_sources 
                           if s in SOURCE_TO_COLUMN]
            if selected_cols:
                for col in selected_cols:
                    if col not in supply_df.columns:
                        supply_df[col] = 0
                supply_df['total_supply'] = supply_df[selected_cols].fillna(0).sum(axis=1)
        
        if 'total_supply' in supply_df.columns:
            lookup = supply_df.groupby(mat_id_col)['total_supply'].sum().to_dict()
        else:
            lookup = {}
        
        return lookup
    
    def _calculate_level_demand(
        self,
        parent_shortage_df: pd.DataFrame,
        bom_df: pd.DataFrame,
        id_col: str
    ) -> pd.DataFrame:
        """
        Calculate material demand from parent shortage × BOM.
        
        Args:
            parent_shortage_df: columns [product_id, net_gap] (net_gap = positive shortage qty)
            bom_df: BOM explosion for these products
            id_col: column name for output product ID in bom_df
        
        Returns:
            DataFrame with required_qty per material (not yet aggregated by material_id
            to allow leaf/semi classification before aggregation)
        """
        if parent_shortage_df.empty or bom_df.empty:
            return pd.DataFrame()
        
        # Merge: parent shortage × BOM
        merged = bom_df.merge(
            parent_shortage_df[['product_id', 'net_gap']].rename(
                columns={'product_id': id_col, 'net_gap': 'parent_shortage_qty'}
            ),
            on=id_col,
            how='inner'
        )
        
        if merged.empty:
            return pd.DataFrame()
        
        # Calculate required_qty per material per BOM line
        bom_out = merged['bom_output_quantity'].fillna(1).replace(0, 1) \
            if 'bom_output_quantity' in merged.columns else 1
        qty_per = merged['quantity_per_output'].fillna(1) \
            if 'quantity_per_output' in merged.columns else 1
        scrap = merged['scrap_rate'].fillna(0) \
            if 'scrap_rate' in merged.columns else 0
        
        merged['required_qty'] = (
            (merged['parent_shortage_qty'] / bom_out) * qty_per * (1 + scrap / 100)
        )
        
        # Aggregate by material_id (same material may appear in multiple parent BOMs)
        agg_cols = {
            'required_qty': 'sum',
            id_col: 'nunique'
        }
        optional = {
            'material_pt_code': 'first', 'material_name': 'first',
            'material_brand': 'first', 'material_package_size': 'first',
            'material_uom': 'first',
            'material_type': 'first', 'is_primary': 'first',
            'alternative_priority': 'first', 'primary_material_id': 'first'
        }
        for col, func in optional.items():
            if col in merged.columns:
                agg_cols[col] = func
        
        demand = merged.groupby('material_id').agg(agg_cols).reset_index()
        demand.rename(columns={id_col: 'parent_product_count'}, inplace=True)
        
        return demand
    
    def _aggregate_leaf_demand(
        self,
        leaf_demand_df: pd.DataFrame,
        id_col: str
    ) -> pd.DataFrame:
        """Aggregate leaf (raw material) demand across all BOM levels."""
        
        if leaf_demand_df.empty:
            return pd.DataFrame()
        
        agg_cols = {
            'required_qty': 'sum',
            'bom_level': 'min'  # min level where this material first appears
        }
        optional = {
            'material_pt_code': 'first', 'material_name': 'first',
            'material_brand': 'first', 'material_package_size': 'first',
            'material_uom': 'first',
            'material_type': 'first', 'is_primary': 'first',
            'alternative_priority': 'first', 'primary_material_id': 'first',
            'parent_product_count': 'sum'
        }
        for col, func in optional.items():
            if col in leaf_demand_df.columns:
                agg_cols[col] = func
        
        agg = leaf_demand_df.groupby('material_id').agg(agg_cols).reset_index()
        agg.rename(columns={
            'bom_level': 'min_bom_level',
            'parent_product_count': 'fg_product_count'
        }, inplace=True)
        
        return agg
    
    def _add_existing_mo_demand(
        self,
        demand_df: pd.DataFrame,
        existing_mo_demand_df: Optional[pd.DataFrame]
    ) -> pd.DataFrame:
        """Add existing MO demand to aggregated material demand."""
        
        if demand_df.empty:
            demand_df['existing_mo_demand'] = 0
            demand_df['total_required_qty'] = 0
            return demand_df
        
        if existing_mo_demand_df is not None and not existing_mo_demand_df.empty:
            pending_col = 'pending_qty' if 'pending_qty' in existing_mo_demand_df.columns \
                else 'pending_material_qty'
            
            if pending_col in existing_mo_demand_df.columns:
                mo_agg = existing_mo_demand_df.groupby('material_id')[pending_col].sum().reset_index()
                mo_agg.rename(columns={pending_col: 'existing_mo_demand'}, inplace=True)
                demand_df = demand_df.merge(mo_agg, on='material_id', how='left')
        
        demand_df['existing_mo_demand'] = demand_df.get('existing_mo_demand', pd.Series(dtype=float)).fillna(0)
        demand_df['total_required_qty'] = demand_df['required_qty'] + demand_df['existing_mo_demand']
        
        return demand_df
    
    def _calculate_material_gap_core(
        self,
        demand_df: pd.DataFrame,
        supply_lookup: Dict[int, float],
        safety_lookup: Dict[int, float],
        bom_level: int,
        material_category: str
    ) -> pd.DataFrame:
        """
        Core GAP calculation for any set of materials (raw or semi-finished).
        
        Args:
            demand_df: must have material_id, required_qty (or total_required_qty)
            supply_lookup: material_id → total_supply
            safety_lookup: material_id → safety_stock_qty
            bom_level: level tag for these materials
            material_category: 'RAW_MATERIAL' or 'SEMI_FINISHED'
        """
        if demand_df.empty:
            return pd.DataFrame()
        
        gap = demand_df.copy()
        
        # Map supply
        gap['total_supply'] = gap['material_id'].map(supply_lookup).fillna(0)
        
        # Map safety stock
        gap['safety_stock_qty'] = gap['material_id'].map(safety_lookup).fillna(0)
        
        # Use total_required_qty if available (has existing MO), else required_qty
        if 'total_required_qty' not in gap.columns:
            gap['total_required_qty'] = gap['required_qty']
        
        # GAP calculation (same formula as existing)
        gap['safety_gap'] = gap['total_supply'] - gap['safety_stock_qty']
        gap['available_supply'] = gap['safety_gap'].clip(lower=0)
        gap['net_gap'] = gap['available_supply'] - gap['total_required_qty']
        
        # Coverage ratio
        gap['coverage_ratio'] = np.where(
            gap['total_required_qty'] > 0,
            gap['available_supply'] / gap['total_required_qty'],
            np.where(gap['total_supply'] > 0, 999, 0)
        )
        
        # Status classification
        gap['gap_status'] = gap.apply(self._classify_gap_status, axis=1)
        gap['priority'] = gap['gap_status'].apply(
            lambda x: STATUS_CONFIG.get(x, {}).get('priority', 99)
        )
        
        # Tags
        gap['bom_level'] = bom_level
        gap['material_category'] = material_category
        gap['is_leaf'] = (material_category == 'RAW_MATERIAL')
        
        gap = gap.sort_values(['priority', 'net_gap']).reset_index(drop=True)
        
        return gap
    
    # =========================================================================
    # ACTION RECOMMENDATIONS
    # =========================================================================
    
    def _generate_actions(
        self,
        result: SupplyChainGAPResult
    ) -> Tuple[List[ActionRecommendation], List[ActionRecommendation], List[ActionRecommendation]]:
        """Generate action recommendations"""
        
        mo_suggestions = []
        po_fg_suggestions = []
        po_raw_suggestions = []
        
        # MO suggestions for manufacturing products
        mfg_shortage = result.get_manufacturing_shortage()
        # Pre-compute all statuses at once (also populates cache for UI/export later)
        all_statuses = result.get_all_production_statuses()
        
        for _, row in mfg_shortage.iterrows():
            product_id = row['product_id']
            status = all_statuses.get(product_id, result.get_production_status(product_id))
            
            if status.get('can_produce', False):
                action_type = 'USE_ALTERNATIVE' if status.get('status') == 'USE_ALTERNATIVE' else 'CREATE_MO'
                reason = status.get('reason', 'Raw materials available')
            else:
                action_type = 'WAIT_RAW'
                reason = status.get('reason', 'Raw materials insufficient')
            
            mo_suggestions.append(ActionRecommendation(
                action_type=action_type,
                product_id=product_id,
                pt_code=row.get('pt_code', ''),
                product_name=row.get('product_name', ''),
                quantity=abs(row.get('net_gap', 0)),
                uom=row.get('standard_uom', ''),
                priority=row.get('priority', 99),
                reason=reason,
                brand=row.get('brand', ''),
                package_size=str(row.get('package_size', '')) if pd.notna(row.get('package_size')) else '',
                related_materials=status.get('limiting_materials', [])
            ))
        
        # PO-FG suggestions for trading products
        trading_shortage = result.get_trading_shortage()
        for _, row in trading_shortage.iterrows():
            po_fg_suggestions.append(ActionRecommendation(
                action_type='CREATE_PO_FG',
                product_id=row['product_id'],
                pt_code=row.get('pt_code', ''),
                product_name=row.get('product_name', ''),
                quantity=abs(row.get('net_gap', 0)),
                uom=row.get('standard_uom', ''),
                priority=row.get('priority', 99),
                reason='Trading product - no BOM',
                brand=row.get('brand', ''),
                package_size=str(row.get('package_size', '')) if pd.notna(row.get('package_size')) else ''
            ))
        
        # PO-Raw suggestions for raw material shortage
        raw_shortage = result.get_raw_shortage()
        for _, row in raw_shortage.iterrows():
            # Check if alternative can cover
            has_alternative = False
            if not result.alternative_analysis_df.empty:
                mat_id = row.get('material_id')
                if 'primary_material_id' in result.alternative_analysis_df.columns:
                    alts = result.alternative_analysis_df[
                        result.alternative_analysis_df['primary_material_id'] == mat_id
                    ]
                    if not alts.empty and 'can_cover_shortage' in alts.columns:
                        has_alternative = alts['can_cover_shortage'].any()
            
            # FIXED: Use 1/0 comparison for is_primary
            is_primary = row.get('is_primary', 1)
            if not has_alternative and is_primary in [1, True]:
                po_raw_suggestions.append(ActionRecommendation(
                    action_type='CREATE_PO_RAW',
                    product_id=row.get('material_id', 0),
                    pt_code=row.get('material_pt_code', ''),
                    product_name=row.get('material_name', ''),
                    quantity=abs(row.get('net_gap', 0)),
                    uom=row.get('material_uom', ''),
                    priority=row.get('priority', 99),
                    reason='Raw material shortage',
                    brand=row.get('material_brand', '') if pd.notna(row.get('material_brand')) else '',
                    package_size=str(row.get('material_package_size', '')) if pd.notna(row.get('material_package_size')) else ''
                ))
        
        # MO suggestions for semi-finished products with shortage
        semi_shortage = result.get_semi_finished_shortage()
        for _, row in semi_shortage.iterrows():
            mo_suggestions.append(ActionRecommendation(
                action_type='CREATE_MO_SEMI',
                product_id=row.get('material_id', 0),
                pt_code=row.get('material_pt_code', ''),
                product_name=row.get('material_name', ''),
                quantity=abs(row.get('net_gap', 0)),
                uom=row.get('material_uom', ''),
                priority=row.get('priority', 99),
                reason=f"Semi-finished shortage at BOM level {row.get('bom_level', '?')}",
                brand=row.get('material_brand', '') if pd.notna(row.get('material_brand')) else '',
                package_size=str(row.get('material_package_size', '')) if pd.notna(row.get('material_package_size')) else ''
            ))
        
        return mo_suggestions, po_fg_suggestions, po_raw_suggestions


# Singleton
_calculator_instance = None

def get_calculator() -> SupplyChainGAPCalculator:
    """Get singleton calculator instance"""
    global _calculator_instance
    if _calculator_instance is None:
        _calculator_instance = SupplyChainGAPCalculator()
    return _calculator_instance