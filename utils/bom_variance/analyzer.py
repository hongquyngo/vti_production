# utils/bom/variance/analyzer.py
"""
BOM Variance Analyzer - VERSION 1.0

Core analysis logic for comparing actual vs theoretical material consumption.
Provides configuration management and analysis utilities.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

import pandas as pd
import numpy as np

from .queries import VarianceQueries

logger = logging.getLogger(__name__)


# ==================== Configuration ====================

class ApplyMode(Enum):
    """How to apply recommendations"""
    CLONE = "clone"          # Clone BOM with adjusted values (creates DRAFT)
    DIRECT_UPDATE = "update" # Direct update if BOM has no usage


@dataclass
class VarianceConfig:
    """
    Configuration for variance analysis
    
    Attributes:
        variance_threshold: Flag materials with variance above this % (default: 5%)
        high_variance_threshold: Urgent attention threshold % (default: 10%)
        min_mo_count: Minimum completed MOs for reliable statistics (default: 3)
        cv_threshold: Coefficient of variation threshold for high variability flag (default: 15%)
        date_from: Start date for analysis window
        date_to: End date for analysis window
        default_months: Default analysis window in months (default: 3)
    """
    variance_threshold: float = 5.0
    high_variance_threshold: float = 10.0
    min_mo_count: int = 3
    cv_threshold: float = 15.0
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    default_months: int = 3
    
    def __post_init__(self):
        """Set default date range if not provided"""
        if self.date_to is None:
            self.date_to = date.today()
        
        if self.date_from is None:
            self.date_from = self.date_to - timedelta(days=self.default_months * 30)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            'variance_threshold': self.variance_threshold,
            'high_variance_threshold': self.high_variance_threshold,
            'min_mo_count': self.min_mo_count,
            'cv_threshold': self.cv_threshold,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'default_months': self.default_months
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VarianceConfig':
        """Create config from dictionary"""
        return cls(
            variance_threshold=data.get('variance_threshold', 5.0),
            high_variance_threshold=data.get('high_variance_threshold', 10.0),
            min_mo_count=data.get('min_mo_count', 3),
            cv_threshold=data.get('cv_threshold', 15.0),
            date_from=data.get('date_from'),
            date_to=data.get('date_to'),
            default_months=data.get('default_months', 3)
        )


# ==================== Variance Analyzer ====================

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
            'under_used': int((variance_pct < -threshold).sum()),  # Less than expected (saving)
            'on_target': int((variance_pct.abs() <= threshold).sum()),  # Within threshold
            'over_used': int((variance_pct > threshold).sum()),  # More than expected (waste)
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
        # actual = new_qty / output_qty * (1 + scrap/100)
        # new_qty = actual * output_qty / (1 + scrap/100)
        suggested_qty_for_bom = actual_avg * bom_output_qty / (1 + current_scrap_rate/100)
        
        # Option 2: Adjust scrap rate, keep quantity
        # actual = qty / output * (1 + new_scrap/100)
        # new_scrap = (actual * output / qty - 1) * 100
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
            return f"▲ +{value:.1f}%"  # Over-consumption
        elif value < 0:
            return f"▼ {value:.1f}%"   # Under-consumption
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
