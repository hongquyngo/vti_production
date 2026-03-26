# utils/supply_chain_production/production_data_loader.py

"""
Data Loader for Production Planning.

Queries:
  - existing_mo_summary_view (active MOs per product — deduplication)
  - production_lead_time_stats_view (historical lead time + yield)
  - mo_material_readiness_view (material fulfillment for active MOs)

Does NOT load config — that's handled by production_config.py.
Does NOT load BOM/supply/demand — that comes from GAP result.
"""

import pandas as pd
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


class ProductionDataLoader:
    """
    Data loader for Production Planning.
    Loads supplementary data not available in GAP result.
    """

    def __init__(self, engine=None):
        self._engine = engine
        if engine is None:
            self._init_connection()

    def _init_connection(self):
        try:
            from utils.db import get_db_engine
            self._engine = get_db_engine()
            logger.info("ProductionDataLoader: database connection established")
        except Exception as e:
            logger.error(f"ProductionDataLoader: failed to connect: {e}")
            raise

    def _ensure_connection(self):
        if self._engine is None:
            self._init_connection()
            return
        try:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.warning(f"ProductionDataLoader: reconnecting: {e}")
            try:
                self._engine.dispose()
            except Exception:
                pass
            self._init_connection()

    # =========================================================================
    # EXISTING MO SUMMARY (for deduplication)
    # =========================================================================

    def load_existing_mo_summary(
        self,
        product_ids: Optional[Tuple[int, ...]] = None,
        entity_id: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Load active MO summary per product from existing_mo_summary_view.

        Returns one row per product_id with:
        - active_mo_count, total_planned_qty, total_remaining_qty
        - earliest/latest scheduled dates
        - status breakdown (draft/confirmed/in_progress)
        - sales order linkage count

        Used to:
        1. Show existing MOs as context (not deducted — GAP already includes MO_EXPECTED)
        2. Detect sales_order linkage for priority scoring
        """
        self._ensure_connection()

        query = """
        SELECT
            product_id,
            pt_code,
            product_name,
            brand,
            standard_uom,
            active_mo_count,
            total_planned_qty,
            total_produced_qty,
            total_remaining_qty,
            earliest_scheduled,
            latest_scheduled,
            draft_count,
            confirmed_count,
            in_progress_count,
            max_priority,
            linked_to_so_count,
            entity_id
        FROM existing_mo_summary_view
        WHERE 1=1
        """
        params = {}

        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        if entity_id is not None:
            query += " AND entity_id = %(entity_id)s"
            params['entity_id'] = entity_id

        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(
                f"Loaded existing MO summary: {len(df)} products "
                f"with active MOs"
            )
            return df
        except Exception as e:
            logger.error(f"Failed to load existing MO summary: {e}")
            return pd.DataFrame()

    # =========================================================================
    # HISTORICAL LEAD TIME + YIELD STATS
    # =========================================================================

    def load_lead_time_stats(
        self,
        bom_types: Optional[List[str]] = None,
        product_ids: Optional[Tuple[int, ...]] = None,
    ) -> pd.DataFrame:
        """
        Load historical production stats from production_lead_time_stats_view.

        Returns per (bom_type, product_id):
        - completed_mo_count, avg/min/max/stddev lead_time_days
        - avg_schedule_deviation_days
        - avg_yield_pct
        - qc_pass_rate_pct, total_receipts

        Used by scheduling engine for historical override (Tier 2)
        when config.lead_time_use_historical = true.
        """
        self._ensure_connection()

        query = """
        SELECT
            bom_type,
            product_id,
            pt_code,
            completed_mo_count,
            avg_lead_time_days,
            min_lead_time_days,
            max_lead_time_days,
            stddev_lead_time_days,
            avg_schedule_deviation_days,
            avg_yield_pct,
            qc_pass_rate_pct,
            total_receipts,
            last_completed_date
        FROM production_lead_time_stats_view
        WHERE 1=1
        """
        params = {}

        if bom_types:
            query += " AND bom_type IN %(bom_types)s"
            params['bom_types'] = tuple(bom_types)

        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        query += " ORDER BY bom_type, pt_code"

        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(
                f"Loaded lead time stats: {len(df)} rows "
                f"({df['bom_type'].nunique() if not df.empty else 0} BOM types, "
                f"{df['product_id'].nunique() if not df.empty else 0} products)"
            )
            return df
        except Exception as e:
            logger.error(f"Failed to load lead time stats: {e}")
            return pd.DataFrame()

    # =========================================================================
    # MO MATERIAL READINESS (active MOs — informational)
    # =========================================================================

    def load_mo_material_readiness(
        self,
        product_ids: Optional[Tuple[int, ...]] = None,
    ) -> pd.DataFrame:
        """
        Load material fulfillment status for active MOs.

        Returns per (manufacturing_order_id, material_id):
        - required_qty, issued_qty, pending_qty
        - fulfillment_pct, material_status

        Used to show existing MO material status as context.
        """
        self._ensure_connection()

        query = """
        SELECT
            manufacturing_order_id,
            order_no,
            mo_status,
            mo_priority,
            output_product_id,
            output_pt_code,
            output_product_name,
            mo_material_id,
            material_id,
            material_pt_code,
            material_name,
            material_uom,
            required_qty,
            issued_qty,
            pending_qty,
            material_status,
            fulfillment_pct,
            bom_type,
            bom_code,
            scheduled_date,
            entity_id
        FROM mo_material_readiness_view
        WHERE 1=1
        """
        params = {}

        if product_ids:
            query += " AND output_product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(
                f"Loaded MO material readiness: {len(df)} rows "
                f"({df['manufacturing_order_id'].nunique() if not df.empty else 0} MOs)"
            )
            return df
        except Exception as e:
            logger.error(f"Failed to load MO material readiness: {e}")
            return pd.DataFrame()

    # =========================================================================
    # SALES ORDER LINKAGE — which products have MOs linked to SO?
    # =========================================================================

    def load_product_so_linkage(
        self,
        product_ids: Optional[Tuple[int, ...]] = None,
    ) -> pd.DataFrame:
        """
        Load product → sales order linkage from active MOs.

        Returns product_id, has_so (bool), so_count.
        Used for priority scoring (customer linkage factor).
        """
        self._ensure_connection()

        query = """
        SELECT
            product_id,
            linked_to_so_count,
            (linked_to_so_count > 0) AS has_sales_order
        FROM existing_mo_summary_view
        WHERE 1=1
        """
        params = {}

        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        try:
            df = pd.read_sql(query, self._engine, params=params)
            return df
        except Exception as e:
            logger.warning(f"Could not load SO linkage: {e}")
            return pd.DataFrame()


# =============================================================================
# SINGLETON
# =============================================================================

_production_loader_instance: Optional[ProductionDataLoader] = None


def get_production_data_loader() -> ProductionDataLoader:
    """Get singleton production data loader with connection health check."""
    global _production_loader_instance
    if _production_loader_instance is None:
        _production_loader_instance = ProductionDataLoader()
    else:
        try:
            _production_loader_instance._ensure_connection()
        except Exception as e:
            logger.error(f"Reconnect failed, creating new instance: {e}")
            _production_loader_instance = ProductionDataLoader()
    return _production_loader_instance
