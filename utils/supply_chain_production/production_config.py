# utils/supply_chain_production/production_config.py

"""
Configuration loader and validator for Production Planning.

ZERO ASSUMPTION: All parameters come from production_planning_config table.
If required config is missing → system CANNOT run. No silent fallback.

Responsibilities:
1. Load all config rows from DB
2. Cast string values to typed Python values
3. Validate completeness (all is_required=1 must have non-empty value)
4. Validate constraints (e.g., priority weights sum to 100)
5. Gate check: can the system run?
6. Save updated config values from Settings UI
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIG DATACLASS
# =============================================================================

@dataclass
class ProductionConfig:
    """
    Loaded and validated config from production_planning_config table.

    All fields start as None. After load(), populated fields have values;
    None fields indicate missing config. After validate(), missing_required
    and validation_errors are populated, and is_ready is set.
    """

    # -- LEAD_TIME --
    lead_time_cutting_days: Optional[int] = None
    lead_time_repacking_days: Optional[int] = None
    lead_time_kitting_days: Optional[int] = None
    lead_time_use_historical: bool = False
    lead_time_min_history_product: Optional[int] = None
    lead_time_min_history_bom_type: Optional[int] = None

    # -- YIELD --
    yield_use_historical: bool = False
    yield_min_history_count: Optional[int] = None
    yield_cutting_default_scrap_pct: Optional[float] = None
    yield_repacking_default_scrap_pct: Optional[float] = None
    yield_kitting_default_scrap_pct: Optional[float] = None

    # -- PRIORITY (must sum to 100) --
    priority_weight_time: Optional[int] = None
    priority_weight_readiness: Optional[int] = None
    priority_weight_value: Optional[int] = None
    priority_weight_customer: Optional[int] = None

    # -- PLANNING --
    planning_horizon_days: Optional[int] = None
    allow_partial_production: bool = False

    # -- Validation state --
    missing_required: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    is_ready: bool = False

    # -- Raw data (for Settings UI display) --
    raw_rows: List[Dict[str, Any]] = field(default_factory=list)

    def get_lead_time_days(self, bom_type: str) -> Optional[int]:
        """Get configured lead time for a BOM type. Returns None if not set."""
        mapping = {
            'CUTTING': self.lead_time_cutting_days,
            'REPACKING': self.lead_time_repacking_days,
            'KITTING': self.lead_time_kitting_days,
        }
        return mapping.get(bom_type)

    def get_yield_default_scrap_pct(self, bom_type: str) -> Optional[float]:
        """Get default scrap % for a BOM type. Returns None if not set."""
        mapping = {
            'CUTTING': self.yield_cutting_default_scrap_pct,
            'REPACKING': self.yield_repacking_default_scrap_pct,
            'KITTING': self.yield_kitting_default_scrap_pct,
        }
        return mapping.get(bom_type)


# =============================================================================
# CONFIG FIELD MAPPING — DB key → dataclass field + cast function
# =============================================================================

_FIELD_MAP: Dict[Tuple[str, str], Tuple[str, type]] = {
    # (config_group, config_key): (field_name, cast_type)
    ('LEAD_TIME', 'CUTTING.DAYS'):              ('lead_time_cutting_days', int),
    ('LEAD_TIME', 'REPACKING.DAYS'):            ('lead_time_repacking_days', int),
    ('LEAD_TIME', 'KITTING.DAYS'):              ('lead_time_kitting_days', int),
    ('LEAD_TIME', 'USE_HISTORICAL'):            ('lead_time_use_historical', bool),
    ('LEAD_TIME', 'MIN_HISTORY_COUNT_PRODUCT'):  ('lead_time_min_history_product', int),
    ('LEAD_TIME', 'MIN_HISTORY_COUNT_BOM_TYPE'): ('lead_time_min_history_bom_type', int),

    ('YIELD', 'USE_HISTORICAL'):                ('yield_use_historical', bool),
    ('YIELD', 'MIN_HISTORY_COUNT'):             ('yield_min_history_count', int),
    ('YIELD', 'CUTTING.DEFAULT_SCRAP_PCT'):     ('yield_cutting_default_scrap_pct', float),
    ('YIELD', 'REPACKING.DEFAULT_SCRAP_PCT'):   ('yield_repacking_default_scrap_pct', float),
    ('YIELD', 'KITTING.DEFAULT_SCRAP_PCT'):     ('yield_kitting_default_scrap_pct', float),

    ('PRIORITY', 'WEIGHT.TIME_URGENCY'):        ('priority_weight_time', int),
    ('PRIORITY', 'WEIGHT.MATERIAL_READINESS'):  ('priority_weight_readiness', int),
    ('PRIORITY', 'WEIGHT.AT_RISK_VALUE'):       ('priority_weight_value', int),
    ('PRIORITY', 'WEIGHT.CUSTOMER_LINKAGE'):    ('priority_weight_customer', int),

    ('PLANNING', 'DEFAULT_HORIZON_DAYS'):       ('planning_horizon_days', int),
    ('PLANNING', 'ALLOW_PARTIAL_PRODUCTION'):   ('allow_partial_production', bool),
}


def _cast_value(raw: str, target_type: type):
    """
    Cast string config_value to Python type.
    Returns None if raw is empty or cast fails.
    """
    if raw is None or str(raw).strip() == '':
        return None

    raw_str = str(raw).strip()

    if target_type == bool:
        return raw_str.lower() in ('true', '1', 'yes')
    if target_type == int:
        return int(float(raw_str))
    if target_type == float:
        return float(raw_str)
    return raw_str


# =============================================================================
# CONFIG LOADER
# =============================================================================

class ProductionConfigLoader:
    """
    Load config from DB, validate completeness, gate execution, save changes.

    Usage:
        loader = ProductionConfigLoader(engine)
        config = loader.load_and_validate()
        if not config.is_ready:
            show_missing(config.missing_required, config.validation_errors)
    """

    def __init__(self, engine=None):
        self._engine = engine

    def _ensure_engine(self):
        if self._engine is None:
            from utils.db import get_db_engine
            self._engine = get_db_engine()

    # -----------------------------------------------------------------
    # LOAD
    # -----------------------------------------------------------------

    def load(self) -> ProductionConfig:
        """Load all config rows from DB and map to ProductionConfig."""
        self._ensure_engine()

        query = """
        SELECT id, config_group, config_key, config_value, value_type,
               description, is_required, validation_rule, display_order
        FROM production_planning_config
        ORDER BY config_group, display_order
        """
        try:
            df = pd.read_sql(query, self._engine)
        except Exception as e:
            logger.error(f"Failed to load production config: {e}")
            config = ProductionConfig()
            config.validation_errors.append(f"Cannot read config table: {e}")
            return config

        config = ProductionConfig()
        config.raw_rows = df.to_dict('records')

        for _, row in df.iterrows():
            group = row['config_group']
            key = row['config_key']
            raw_value = row.get('config_value', '')

            mapping = _FIELD_MAP.get((group, key))
            if mapping is None:
                continue

            field_name, cast_type = mapping
            typed_value = _cast_value(raw_value, cast_type)

            if typed_value is not None:
                setattr(config, field_name, typed_value)

        logger.info(f"Production config loaded: {len(df)} rows")
        return config

    # -----------------------------------------------------------------
    # VALIDATE
    # -----------------------------------------------------------------

    def validate(self, config: ProductionConfig) -> ProductionConfig:
        """
        Validate loaded config:
        1. All is_required=1 rows have non-empty config_value
        2. Priority weights sum to 100
        3. Value constraints (min/max)
        """
        missing = []
        errors = []

        # Check required fields from raw_rows
        for row in config.raw_rows:
            if row.get('is_required') and str(row.get('config_value', '')).strip() == '':
                missing.append(f"{row['config_group']}.{row['config_key']}")

        # Priority weight sum
        weights = [
            config.priority_weight_time,
            config.priority_weight_readiness,
            config.priority_weight_value,
            config.priority_weight_customer,
        ]
        if all(w is not None for w in weights):
            weight_sum = sum(weights)
            if weight_sum != 100:
                errors.append(
                    f"Priority weights sum to {weight_sum}%, must be exactly 100%. "
                    f"Current: Time={weights[0]}, Readiness={weights[1]}, "
                    f"Value={weights[2]}, Customer={weights[3]}"
                )

        # Min/max validation on populated fields
        range_checks = [
            ('lead_time_cutting_days', 1, 365, 'LEAD_TIME.CUTTING.DAYS'),
            ('lead_time_repacking_days', 1, 365, 'LEAD_TIME.REPACKING.DAYS'),
            ('lead_time_kitting_days', 1, 365, 'LEAD_TIME.KITTING.DAYS'),
            ('lead_time_min_history_product', 1, 500, 'LEAD_TIME.MIN_HISTORY_COUNT_PRODUCT'),
            ('lead_time_min_history_bom_type', 1, 1000, 'LEAD_TIME.MIN_HISTORY_COUNT_BOM_TYPE'),
            ('yield_min_history_count', 1, 500, 'YIELD.MIN_HISTORY_COUNT'),
            ('planning_horizon_days', 14, 365, 'PLANNING.DEFAULT_HORIZON_DAYS'),
        ]
        for field_name, min_val, max_val, config_key in range_checks:
            val = getattr(config, field_name, None)
            if val is not None:
                if val < min_val or val > max_val:
                    errors.append(
                        f"{config_key}: value {val} outside allowed range [{min_val}, {max_val}]"
                    )

        # Scrap pct range
        for bom_type in ('cutting', 'repacking', 'kitting'):
            val = getattr(config, f'yield_{bom_type}_default_scrap_pct', None)
            if val is not None and (val < 0 or val > 50):
                errors.append(f"YIELD.{bom_type.upper()}.DEFAULT_SCRAP_PCT: {val}% outside [0, 50]")

        config.missing_required = missing
        config.validation_errors = errors
        config.is_ready = (len(missing) == 0 and len(errors) == 0)

        if config.is_ready:
            logger.info("Production config validated: READY")
        else:
            logger.warning(
                f"Production config validation: "
                f"{len(missing)} missing, {len(errors)} errors"
            )
            for m in missing:
                logger.warning(f"  MISSING: {m}")
            for e in errors:
                logger.warning(f"  ERROR: {e}")

        return config

    # -----------------------------------------------------------------
    # COMBINED LOAD + VALIDATE
    # -----------------------------------------------------------------

    def load_and_validate(self) -> ProductionConfig:
        """Load config from DB and validate in one call."""
        config = self.load()
        return self.validate(config)

    # -----------------------------------------------------------------
    # GATE STATUS (for UI)
    # -----------------------------------------------------------------

    def get_gate_status(self, config: ProductionConfig) -> Dict[str, Any]:
        """
        Gate check for UI. Returns structured status for display.

        {
            'can_run': bool,
            'missing_configs': ['LEAD_TIME.CUTTING.DAYS', ...],
            'validation_errors': ['Priority weights sum to 85%', ...],
            'summary': 'Ready to run' | '3 required configs missing'
        }
        """
        if config.is_ready:
            return {
                'can_run': True,
                'missing_configs': [],
                'validation_errors': [],
                'summary': 'All required settings configured. Ready to run.',
            }

        parts = []
        if config.missing_required:
            parts.append(f"{len(config.missing_required)} required config(s) missing")
        if config.validation_errors:
            parts.append(f"{len(config.validation_errors)} validation error(s)")

        return {
            'can_run': False,
            'missing_configs': list(config.missing_required),
            'validation_errors': list(config.validation_errors),
            'summary': '; '.join(parts) if parts else 'Configuration incomplete',
        }

    # -----------------------------------------------------------------
    # SAVE (from Settings UI)
    # -----------------------------------------------------------------

    def save_config(
        self,
        config_group: str,
        config_key: str,
        value: str,
        user_id: Optional[int] = None
    ) -> bool:
        """
        Update a single config value. Called from Settings UI.

        Returns True on success, False on failure.
        """
        self._ensure_engine()

        from sqlalchemy import text

        query = text("""
            UPDATE production_planning_config
            SET config_value = :value,
                updated_by = :user_id,
                updated_date = NOW()
            WHERE config_group = :config_group
              AND config_key = :config_key
        """)

        try:
            with self._engine.begin() as conn:
                result = conn.execute(query, {
                    'value': str(value).strip(),
                    'config_group': config_group,
                    'config_key': config_key,
                    'user_id': user_id,
                })
                if result.rowcount == 0:
                    logger.warning(
                        f"Config save: no row matched {config_group}.{config_key}"
                    )
                    return False
                logger.info(f"Config saved: {config_group}.{config_key} = '{value}'")
                return True
        except Exception as e:
            logger.error(f"Config save failed: {e}")
            return False

    def save_config_batch(
        self,
        updates: Dict[Tuple[str, str], str],
        user_id: Optional[int] = None
    ) -> Tuple[int, List[str]]:
        """
        Save multiple config values at once (from Settings form submit).

        Args:
            updates: {(config_group, config_key): value, ...}

        Returns: (success_count, error_messages)
        """
        success = 0
        errors = []
        for (group, key), value in updates.items():
            if self.save_config(group, key, value, user_id):
                success += 1
            else:
                errors.append(f"Failed to save {group}.{key}")

        logger.info(f"Batch config save: {success}/{len(updates)} succeeded")
        return success, errors

    # -----------------------------------------------------------------
    # HISTORICAL STATS (read-only, for Settings UI reference column)
    # -----------------------------------------------------------------

    def load_historical_lead_time_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        Load aggregated historical lead time per BOM type for Settings display.

        Returns: {
            'CUTTING': {'avg_days': 1.8, 'total_mos': 45, 'product_count': 12},
            'REPACKING': {...},
            ...
        }
        """
        self._ensure_engine()

        query = """
        SELECT bom_type,
               COUNT(DISTINCT product_id) AS product_count,
               SUM(completed_mo_count) AS total_mos,
               ROUND(
                   SUM(avg_lead_time_days * completed_mo_count) /
                   NULLIF(SUM(completed_mo_count), 0), 1
               ) AS weighted_avg_days,
               ROUND(AVG(avg_yield_pct), 1) AS avg_yield_pct,
               ROUND(AVG(qc_pass_rate_pct), 1) AS avg_qc_pass_rate_pct
        FROM production_lead_time_stats_view
        GROUP BY bom_type
        """
        try:
            df = pd.read_sql(query, self._engine)
            result = {}
            for _, row in df.iterrows():
                result[row['bom_type']] = {
                    'avg_days': row.get('weighted_avg_days'),
                    'total_mos': int(row.get('total_mos', 0) or 0),
                    'product_count': int(row.get('product_count', 0) or 0),
                    'avg_yield_pct': row.get('avg_yield_pct'),
                    'avg_qc_pass_rate_pct': row.get('avg_qc_pass_rate_pct'),
                }
            return result
        except Exception as e:
            logger.warning(f"Could not load historical summary: {e}")
            return {}


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================

_config_loader_instance: Optional[ProductionConfigLoader] = None


def get_config_loader() -> ProductionConfigLoader:
    """Get singleton config loader."""
    global _config_loader_instance
    if _config_loader_instance is None:
        _config_loader_instance = ProductionConfigLoader()
    return _config_loader_instance
