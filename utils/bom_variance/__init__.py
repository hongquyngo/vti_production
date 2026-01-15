# utils/bom_variance/__init__.py
"""
BOM Variance Analysis Module - VERSION 1.0

Analyzes actual material consumption vs BOM theoretical values
to identify variances and suggest adjustments.

Location: utils/bom_variance/ (independent module)

Components:
- queries.py: SQL queries for variance data extraction
- analyzer.py: Core analysis and calculation logic
- recommendations.py: Recommendation engine (Phase 3)
- charts.py: Visualization helpers (Phase 2)
"""

from .queries import VarianceQueries
from .analyzer import VarianceAnalyzer, VarianceConfig

__all__ = [
    'VarianceQueries',
    'VarianceAnalyzer', 
    'VarianceConfig'
]
