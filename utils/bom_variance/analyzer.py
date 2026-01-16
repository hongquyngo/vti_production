# utils/bom_variance/analyzer.py
"""
BOM Variance Analyzer - VERSION 2.0

Core analysis logic for comparing actual vs theoretical material consumption.
Provides analysis utilities and recommendation calculations.

Refactored: VarianceConfig moved to config.py
"""

import logging
from typing import Optional, List, Dict, Any

import pandas as pd

from .config import VarianceConfig
from .queries import VarianceQueries

logger = logging.getLogger(__name__)


class VarianceAnalyzer:
    """
    Main analyzer class for BOM variance analysis
    
    Provides methods for:
    - Getting variance data with configurable thresholds
    - Calculating recommendations
    - Generating dashboard summaries
    """
    
    def __init__(self, config: Optional[VarianceConfig] = None):
        """
        Initialize analyzer with configuration
        
        Args:
            config: VarianceConfig object, or None to use defaults
        """
        self.config = config or VarianceConfig()
        self.queries = VarianceQueries()
    
    def update_config(self, **kwargs):
        """Update configuration parameters"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
    
    # ==================== Dashboard Methods ====================
    
    def get_dashboard_metrics(self) -> Dict[str, Any]:
        """
        Get all metrics for dashboard display
        
        Returns:
            Dictionary with summary metrics
        """
        return self.queries.get_dashboard_summary(
            date_from=self.config.date_from,
            date_to=self.config.date_to,
            min_mo_count=self.config.min_mo_count,
            variance_threshold=self.config.variance_threshold
        )
    
    def get_variance_data(
        self,
        bom_id: Optional[int] = None,
        include_no_data: bool = False
    ) -> pd.DataFrame:
        """
        Get variance comparison data
        
        Args:
            bom_id: Filter by specific BOM
            include_no_data: Include BOMs with no actual data
            
        Returns:
            DataFrame with variance analysis
        """
        df = self.queries.get_variance_comparison(
            bom_id=bom_id,
            date_from=self.config.date_from,
            date_to=self.config.date_to,
            min_mo_count=self.config.min_mo_count,
            variance_threshold=self.config.variance_threshold
        )
        
        if not include_no_data and not df.empty:
            df = df[df['has_actual_data']]
        
        return df
    
    def get_top_variances(self, limit: int = 10) -> pd.DataFrame:
        """
        Get top N materials with highest variance
        
        Args:
            limit: Number of records to return
            
        Returns:
            DataFrame sorted by absolute variance
        """
        return self.queries.get_top_variances(
            date_from=self.config.date_from,
            date_to=self.config.date_to,
            min_mo_count=self.config.min_mo_count,
            variance_threshold=self.config.variance_threshold,
            limit=limit
        )
    
    def get_bom_list(self) -> pd.DataFrame:
        """
        Get list of BOMs available for analysis
        
        Returns:
            DataFrame with BOM list and MO counts
        """
        return self.queries.get_bom_list_for_analysis(
            date_from=self.config.date_from,
            date_to=self.config.date_to,
            min_mo_count=self.config.min_mo_count
        )
    
    # ==================== Variance Distribution ====================
    
    def get_variance_distribution(self) -> Dict[str, Any]:
        """
        Get variance distribution for chart display
        
        Returns:
            Dictionary with distribution data for charts
        """
        import numpy as np
        
        df = self.get_variance_data()
        
        if df.empty:
            return {
                'bins': [],
                'counts': [],
                'categories': {
                    'under_used': 0,
                    'on_target': 0,
                    'over_used': 0,
                    'high_variance': 0
                }
            }
        
        variance_pct = df['variance_pct'].dropna()
        
        if variance_pct.empty:
            return {
                'bins': [],
                'counts': [],
                'categories': {
                    'under_used': 0,
                    'on_target': 0,
                    'over_used': 0,
                    'high_variance': 0
                }
            }
        
        # Create histogram bins
        bins = [-50, -20, -10, -5, 0, 5, 10, 20, 50]
        counts, bin_edges = np.histogram(variance_pct.clip(-50, 50), bins=bins)
        
        # Categorize
        threshold = self.config.variance_threshold
        
        categories = {
            'under_used': int((variance_pct < -threshold).sum()),
            'on_target': int((variance_pct.abs() <= threshold).sum()),
            'over_used': int((variance_pct > threshold).sum()),
            'high_variance': int((variance_pct.abs() > self.config.high_variance_threshold).sum())
        }
        
        return {
            'bins': bins,
            'counts': counts.tolist(),
            'bin_labels': [f"{bins[i]} to {bins[i+1]}%" for i in range(len(bins)-1)],
            'categories': categories,
            'stats': {
                'mean': float(variance_pct.mean()),
                'median': float(variance_pct.median()),
                'std': float(variance_pct.std()),
                'min': float(variance_pct.min()),
                'max': float(variance_pct.max())
            }
        }
    
    # ==================== BOM Type Analysis ====================
    
    def get_variance_by_bom_type(self) -> pd.DataFrame:
        """
        Get variance summary grouped by BOM type
        
        Returns:
            DataFrame with variance stats per BOM type
        """
        df = self.get_variance_data()
        
        if df.empty:
            return pd.DataFrame()
        
        # Group by BOM type
        summary = df.groupby('bom_type').agg({
            'bom_header_id': 'nunique',
            'material_id': 'count',
            'variance_pct': ['mean', 'std', 'min', 'max'],
            'has_high_variance': 'sum',
            'mo_count': 'sum'
        }).reset_index()
        
        # Flatten column names
        summary.columns = [
            'bom_type', 'bom_count', 'material_count',
            'avg_variance', 'std_variance', 'min_variance', 'max_variance',
            'high_variance_count', 'total_mo_count'
        ]
        
        return summary
    
    # ==================== Recommendation Helpers ====================
    
    def calculate_suggestion(
        self,
        theoretical_qty: float,
        theoretical_qty_with_scrap: float,
        actual_avg: float,
        current_scrap_rate: float,
        bom_output_qty: float
    ) -> Dict[str, Any]:
        """
        Calculate suggested adjustments for a material
        
        Args:
            theoretical_qty: BOM quantity per output (without scrap)
            theoretical_qty_with_scrap: BOM quantity per output (with scrap)
            actual_avg: Actual average consumption per output
            current_scrap_rate: Current BOM scrap rate %
            bom_output_qty: BOM output quantity
            
        Returns:
            Dictionary with suggestion options
        """
        if theoretical_qty <= 0 or actual_avg <= 0:
            return {
                'has_suggestion': False,
                'reason': 'Insufficient data'
            }
        
        variance_pct = ((actual_avg - theoretical_qty_with_scrap) / theoretical_qty_with_scrap) * 100
        
        # Option 1: Adjust quantity, keep scrap rate
        suggested_qty_for_bom = actual_avg * bom_output_qty / (1 + current_scrap_rate/100)
        
        # Option 2: Adjust scrap rate, keep quantity
        suggested_scrap = ((actual_avg / theoretical_qty) - 1) * 100
        
        return {
            'has_suggestion': True,
            'variance_pct': variance_pct,
            'current': {
                'quantity': theoretical_qty * bom_output_qty,
                'scrap_rate': current_scrap_rate,
                'effective_per_output': theoretical_qty_with_scrap
            },
            'actual': {
                'avg_per_output': actual_avg
            },
            'option_adjust_quantity': {
                'quantity': round(suggested_qty_for_bom, 4),
                'scrap_rate': current_scrap_rate,
                'description': f"Change quantity from {theoretical_qty * bom_output_qty:.4f} to {suggested_qty_for_bom:.4f}"
            },
            'option_adjust_scrap': {
                'quantity': theoretical_qty * bom_output_qty,
                'scrap_rate': round(max(0, suggested_scrap), 2),
                'description': f"Change scrap rate from {current_scrap_rate:.2f}% to {max(0, suggested_scrap):.2f}%"
            }
        }
    
    def get_recommendations(
        self,
        bom_id: Optional[int] = None,
        only_high_variance: bool = True
    ) -> pd.DataFrame:
        """
        Get materials with recommendations for adjustment
        
        Args:
            bom_id: Filter by specific BOM
            only_high_variance: Only return materials above variance threshold
            
        Returns:
            DataFrame with recommendations
        """
        df = self.get_variance_data(bom_id=bom_id)
        
        if df.empty:
            return pd.DataFrame()
        
        if only_high_variance:
            df = df[df['has_high_variance']]
        
        if df.empty:
            return pd.DataFrame()
        
        # Add recommendation columns
        recommendations = []
        
        for _, row in df.iterrows():
            suggestion = self.calculate_suggestion(
                theoretical_qty=row['theoretical_qty'],
                theoretical_qty_with_scrap=row['theoretical_qty_with_scrap'],
                actual_avg=row['actual_avg_per_unit'],
                current_scrap_rate=row['scrap_rate'],
                bom_output_qty=row['bom_output_qty']
            )
            
            rec = row.to_dict()
            rec['suggestion'] = suggestion
            rec['suggested_qty'] = suggestion.get('option_adjust_quantity', {}).get('quantity', row['bom_quantity'])
            rec['suggested_scrap'] = suggestion.get('option_adjust_scrap', {}).get('scrap_rate', row['scrap_rate'])
            recommendations.append(rec)
        
        return pd.DataFrame(recommendations)
    
    # ==================== Formatting Helpers ====================
    
    @staticmethod
    def format_variance(value: float) -> str:
        """Format variance percentage with indicator"""
        if pd.isna(value):
            return "N/A"
        
        if value > 0:
            return f"▲ +{value:.1f}%"
        elif value < 0:
            return f"▼ {value:.1f}%"
        else:
            return "= 0.0%"
    
    @staticmethod
    def get_variance_color(value: float, threshold: float = 5.0) -> str:
        """Get color indicator for variance value"""
        if pd.isna(value):
            return "gray"
        
        abs_value = abs(value)
        
        if abs_value <= threshold:
            return "green"
        elif abs_value <= threshold * 2:
            return "orange"
        else:
            return "red"
    
    @staticmethod
    def format_quantity(value: float, decimals: int = 4) -> str:
        """Format quantity with appropriate decimals"""
        if pd.isna(value):
            return "N/A"
        return f"{value:,.{decimals}f}"
