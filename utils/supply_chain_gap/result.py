# utils/supply_chain_gap/result.py

"""
Result Container for Supply Chain GAP Analysis
Holds all analysis results: FG GAP, Classification, Raw Material GAP, Actions
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime


@dataclass
class CustomerImpact:
    """Customer impact summary"""
    affected_count: int = 0
    affected_customers: List[str] = field(default_factory=list)
    at_risk_value: float = 0.0
    details: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class ActionRecommendation:
    """Single action recommendation"""
    action_type: str
    product_id: int
    pt_code: str
    product_name: str
    quantity: float
    uom: str
    priority: int
    reason: str
    brand: str = ''
    package_size: str = ''
    related_materials: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'action_type': self.action_type,
            'product_id': self.product_id,
            'pt_code': self.pt_code,
            'product_name': self.product_name,
            'package_size': self.package_size,
            'brand': self.brand,
            'quantity': self.quantity,
            'uom': self.uom,
            'priority': self.priority,
            'reason': self.reason,
            'related_materials': self.related_materials
        }


@dataclass
class SupplyChainGAPResult:
    """
    Complete result container for Supply Chain GAP Analysis.
    
    Contains:
    - Level 1: FG GAP analysis
    - Classification: Manufacturing vs Trading
    - Level 2+: Multi-level Material GAP (raw + semi-finished)
    - Actions: MO, PO-FG, PO-Raw recommendations
    """
    
    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Level 1: FG GAP
    fg_gap_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    fg_metrics: Dict[str, Any] = field(default_factory=dict)
    customer_impact: Optional[CustomerImpact] = None
    
    # Classification
    classification_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    manufacturing_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    trading_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    
    # Multi-level Material GAP
    bom_explosion_df: pd.DataFrame = field(default_factory=pd.DataFrame)      # Single-level BOM (all BOMs)
    raw_demand_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_supply_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_gap_df: pd.DataFrame = field(default_factory=pd.DataFrame)            # Leaf (raw material) GAP
    semi_finished_gap_df: pd.DataFrame = field(default_factory=pd.DataFrame)  # Semi-finished GAP per level
    raw_metrics: Dict[str, Any] = field(default_factory=dict)
    alternative_analysis_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    max_bom_depth: int = 0                                                    # Deepest BOM level reached
    
    # Actions
    mo_suggestions: List[ActionRecommendation] = field(default_factory=list)
    po_fg_suggestions: List[ActionRecommendation] = field(default_factory=list)
    po_raw_suggestions: List[ActionRecommendation] = field(default_factory=list)
    
    # Metadata
    filters_used: Dict[str, Any] = field(default_factory=dict)
    
    # Period-based GAP Analysis (v2.2)
    fg_period_gap_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    fg_period_metrics: Dict[str, Any] = field(default_factory=dict)
    period_type: str = 'Weekly'
    
    # =========================================================================
    # SUMMARY METHODS
    # =========================================================================
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of analysis"""
        return {
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M'),
            'fg_total_items': len(self.fg_gap_df),
            'fg_shortage_items': len(self.get_fg_shortage()),
            'fg_surplus_items': len(self.get_fg_surplus()),
            'manufacturing_count': len(self.manufacturing_df),
            'trading_count': len(self.trading_df),
            'raw_materials_count': len(self.raw_gap_df),
            'raw_shortage_count': len(self.get_raw_shortage()),
            'mo_count': len(self.mo_suggestions),
            'po_fg_count': len(self.po_fg_suggestions),
            'po_raw_count': len(self.po_raw_suggestions),
            'total_actions': len(self.mo_suggestions) + len(self.po_fg_suggestions) + len(self.po_raw_suggestions)
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get combined metrics"""
        metrics = {
            # FG metrics
            'fg_total': len(self.fg_gap_df),
            'fg_shortage': len(self.get_fg_shortage()),
            'fg_surplus': len(self.get_fg_surplus()),
            'fg_balanced': len(self.fg_gap_df[self.fg_gap_df['gap_status'] == 'BALANCED']) if 'gap_status' in self.fg_gap_df.columns else 0,
            
            # Classification
            'manufacturing_count': len(self.manufacturing_df),
            'trading_count': len(self.trading_df),
            
            # Raw material metrics
            'raw_total': len(self.raw_gap_df),
            'raw_shortage': len(self.get_raw_shortage()),
            'raw_sufficient': len(self.raw_gap_df) - len(self.get_raw_shortage()) if len(self.raw_gap_df) > 0 else 0,
            
            # Semi-finished metrics
            'semi_finished_total': len(self.semi_finished_gap_df),
            'semi_finished_shortage': len(self.get_semi_finished_shortage()),
            'max_bom_depth': self.max_bom_depth,
            
            # Value metrics
            'at_risk_value': self.fg_metrics.get('at_risk_value', 0),
            'affected_customers': self.customer_impact.affected_count if self.customer_impact else 0,
            
            # Action counts
            'mo_count': len(self.mo_suggestions),
            'po_fg_count': len(self.po_fg_suggestions),
            'po_raw_count': len(self.po_raw_suggestions),
            
            # Period analysis metrics (v2.2)
            'period_type': self.period_type,
            'has_period_data': self.has_period_data(),
        }
        
        # Merge period metrics if available
        if self.fg_period_metrics:
            for k, v in self.fg_period_metrics.items():
                metrics[f'period_{k}'] = v
        
        return metrics
    
    # =========================================================================
    # FG ACCESSORS
    # =========================================================================
    
    def get_fg_shortage(self) -> pd.DataFrame:
        """Get FG products with shortage"""
        if self.fg_gap_df.empty or 'net_gap' not in self.fg_gap_df.columns:
            return pd.DataFrame()
        return self.fg_gap_df[self.fg_gap_df['net_gap'] < 0].copy()
    
    def get_fg_surplus(self) -> pd.DataFrame:
        """Get FG products with surplus"""
        if self.fg_gap_df.empty or 'net_gap' not in self.fg_gap_df.columns:
            return pd.DataFrame()
        return self.fg_gap_df[self.fg_gap_df['net_gap'] > 0].copy()
    
    def get_manufacturing_shortage(self) -> pd.DataFrame:
        """Get manufacturing products with shortage"""
        if self.manufacturing_df.empty:
            return pd.DataFrame()
        
        fg_shortage = self.get_fg_shortage()
        if fg_shortage.empty:
            return pd.DataFrame()
        
        mfg_ids = self.manufacturing_df['product_id'].tolist()
        return fg_shortage[fg_shortage['product_id'].isin(mfg_ids)].copy()
    
    def get_trading_shortage(self) -> pd.DataFrame:
        """Get trading products with shortage"""
        if self.trading_df.empty:
            return pd.DataFrame()
        
        fg_shortage = self.get_fg_shortage()
        if fg_shortage.empty:
            return pd.DataFrame()
        
        trading_ids = self.trading_df['product_id'].tolist()
        return fg_shortage[fg_shortage['product_id'].isin(trading_ids)].copy()
    
    # =========================================================================
    # RAW MATERIAL ACCESSORS
    # =========================================================================
    
    def get_raw_shortage(self) -> pd.DataFrame:
        """Get raw materials with shortage"""
        if self.raw_gap_df.empty or 'net_gap' not in self.raw_gap_df.columns:
            return pd.DataFrame()
        return self.raw_gap_df[self.raw_gap_df['net_gap'] < 0].copy()
    
    def get_semi_finished_shortage(self) -> pd.DataFrame:
        """Get semi-finished materials with shortage"""
        if self.semi_finished_gap_df.empty or 'net_gap' not in self.semi_finished_gap_df.columns:
            return pd.DataFrame()
        return self.semi_finished_gap_df[self.semi_finished_gap_df['net_gap'] < 0].copy()
    
    def get_all_material_gap(self) -> pd.DataFrame:
        """Get combined GAP for all materials (raw + semi-finished)"""
        parts = []
        if not self.raw_gap_df.empty:
            parts.append(self.raw_gap_df)
        if not self.semi_finished_gap_df.empty:
            parts.append(self.semi_finished_gap_df)
        if parts:
            return pd.concat(parts, ignore_index=True)
        return pd.DataFrame()
    
    def get_raw_materials_for_fg(self, fg_product_id: int) -> pd.DataFrame:
        """Get raw materials required for a specific FG product"""
        if self.bom_explosion_df.empty:
            return pd.DataFrame()
        
        # Check column name
        id_col = 'output_product_id' if 'output_product_id' in self.bom_explosion_df.columns else 'fg_product_id'
        if id_col not in self.bom_explosion_df.columns:
            return pd.DataFrame()
        
        materials = self.bom_explosion_df[
            self.bom_explosion_df[id_col] == fg_product_id
        ].copy()
        
        if materials.empty or self.raw_gap_df.empty:
            return materials
        
        # Merge with GAP data if available
        if 'material_id' in materials.columns and 'material_id' in self.raw_gap_df.columns:
            merge_cols = ['material_id']
            gap_cols = [c for c in ['total_supply', 'net_gap', 'gap_status', 'coverage_ratio'] 
                       if c in self.raw_gap_df.columns]
            
            if gap_cols:
                materials = materials.merge(
                    self.raw_gap_df[merge_cols + gap_cols],
                    on='material_id',
                    how='left'
                )
        
        return materials
    
    def get_production_status(self, fg_product_id: int) -> Dict[str, Any]:
        """Get production status for a specific FG product"""
        
        # Check if manufacturing product
        if self.manufacturing_df.empty:
            return {'product_type': 'UNKNOWN', 'can_produce': False, 'reason': 'No classification data'}
        
        mfg_ids = self.manufacturing_df['product_id'].tolist()
        if fg_product_id not in mfg_ids:
            return {'product_type': 'TRADING', 'can_produce': False, 'reason': 'Trading product - no BOM'}
        
        # Get raw materials
        materials = self.get_raw_materials_for_fg(fg_product_id)
        
        if materials.empty:
            return {
                'product_type': 'MANUFACTURING',
                'can_produce': False,
                'reason': 'No BOM materials found',
                'bom_code': self._get_bom_code(fg_product_id)
            }
        
        # Check if net_gap exists
        if 'net_gap' not in materials.columns:
            return {
                'product_type': 'MANUFACTURING',
                'can_produce': True,
                'status': 'UNKNOWN',
                'reason': 'GAP data not available',
                'bom_code': self._get_bom_code(fg_product_id)
            }
        
        # Check for shortages
        materials_with_gap = materials[materials['net_gap'].notna()]
        if materials_with_gap.empty:
            return {
                'product_type': 'MANUFACTURING',
                'can_produce': True,
                'status': 'UNKNOWN',
                'reason': 'No GAP data for materials',
                'bom_code': self._get_bom_code(fg_product_id)
            }
        
        shortage_materials = materials_with_gap[materials_with_gap['net_gap'] < 0]
        
        if shortage_materials.empty:
            return {
                'product_type': 'MANUFACTURING',
                'can_produce': True,
                'status': 'SUFFICIENT',
                'reason': 'All materials available',
                'bom_code': self._get_bom_code(fg_product_id)
            }
        
        # Check alternatives
        if not self.alternative_analysis_df.empty and 'can_cover_shortage' in self.alternative_analysis_df.columns:
            for _, row in shortage_materials.iterrows():
                if row.get('is_primary', True):
                    mat_id = row.get('material_id')
                    if mat_id and 'primary_material_id' in self.alternative_analysis_df.columns:
                        alts = self.alternative_analysis_df[
                            self.alternative_analysis_df['primary_material_id'] == mat_id
                        ]
                        if not alts.empty and alts['can_cover_shortage'].any():
                            return {
                                'product_type': 'MANUFACTURING',
                                'can_produce': True,
                                'status': 'USE_ALTERNATIVE',
                                'reason': 'Alternative material available',
                                'bom_code': self._get_bom_code(fg_product_id),
                                'limiting_materials': self._get_material_codes(shortage_materials)
                            }
        
        return {
            'product_type': 'MANUFACTURING',
            'can_produce': False,
            'status': 'SHORTAGE',
            'reason': 'Raw materials insufficient',
            'bom_code': self._get_bom_code(fg_product_id),
            'limiting_materials': self._get_material_codes(shortage_materials)
        }
    
    def _get_bom_code(self, product_id: int) -> Optional[str]:
        """Get BOM code for product"""
        if self.classification_df.empty or 'product_id' not in self.classification_df.columns:
            return None
        match = self.classification_df[self.classification_df['product_id'] == product_id]
        if not match.empty and 'bom_code' in match.columns:
            return match.iloc[0].get('bom_code')
        return None
    
    def _get_material_codes(self, materials_df: pd.DataFrame) -> List[str]:
        """Get material codes from dataframe"""
        if 'material_pt_code' in materials_df.columns:
            return materials_df['material_pt_code'].tolist()
        return []
    
    def get_all_production_statuses(self) -> Dict[int, Dict[str, Any]]:
        """
        Get production status for ALL manufacturing shortage products at once.
        Caches result to avoid repeated per-row computation.
        
        Returns:
            Dict mapping product_id → production status dict
        """
        # Return cached result if available
        if hasattr(self, '_production_status_cache') and self._production_status_cache:
            return self._production_status_cache
        
        cache = {}
        mfg_shortage = self.get_manufacturing_shortage()
        
        for _, row in mfg_shortage.iterrows():
            product_id = row['product_id']
            cache[product_id] = self.get_production_status(product_id)
        
        self._production_status_cache = cache
        return cache
    
    # =========================================================================
    # ACTION ACCESSORS
    # =========================================================================
    
    def get_all_actions(self) -> List[Dict[str, Any]]:
        """Get all action recommendations as list of dicts"""
        actions = []
        
        for mo in self.mo_suggestions:
            d = mo.to_dict()
            d['category'] = 'Manufacturing Order'
            actions.append(d)
        
        for po in self.po_fg_suggestions:
            d = po.to_dict()
            d['category'] = 'PO for Finished Goods'
            actions.append(d)
        
        for po in self.po_raw_suggestions:
            d = po.to_dict()
            d['category'] = 'PO for Raw Material'
            actions.append(d)
        
        # Sort by priority
        actions.sort(key=lambda x: x['priority'])
        return actions
    
    def get_actions_dataframe(self) -> pd.DataFrame:
        """Get all actions as DataFrame"""
        actions = self.get_all_actions()
        if not actions:
            return pd.DataFrame()
        return pd.DataFrame(actions)
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    
    def has_fg_data(self) -> bool:
        return not self.fg_gap_df.empty
    
    def has_classification(self) -> bool:
        return not self.classification_df.empty
    
    def has_raw_data(self) -> bool:
        return not self.raw_gap_df.empty or not self.semi_finished_gap_df.empty
    
    def has_semi_finished_data(self) -> bool:
        return not self.semi_finished_gap_df.empty
    
    def has_actions(self) -> bool:
        return len(self.mo_suggestions) > 0 or len(self.po_fg_suggestions) > 0 or len(self.po_raw_suggestions) > 0
    
    def has_period_data(self) -> bool:
        return not self.fg_period_gap_df.empty
    
    # =========================================================================
    # PERIOD GAP ACCESSORS (v2.2)
    # =========================================================================
    
    def get_period_shortage(self) -> pd.DataFrame:
        """Get period rows with shortage (gap < 0)"""
        if self.fg_period_gap_df.empty or 'gap_quantity' not in self.fg_period_gap_df.columns:
            return pd.DataFrame()
        return self.fg_period_gap_df[self.fg_period_gap_df['gap_quantity'] < 0].copy()
    
    def get_period_gap_for_product(self, product_id: int) -> pd.DataFrame:
        """Get period timeline for a specific product"""
        if self.fg_period_gap_df.empty:
            return pd.DataFrame()
        return self.fg_period_gap_df[self.fg_period_gap_df['product_id'] == product_id].copy()