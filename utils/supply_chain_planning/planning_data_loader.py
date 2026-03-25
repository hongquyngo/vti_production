# utils/supply_chain_planning/planning_data_loader.py

"""
Data Loader for Supply Chain Planning.
Loads vendor pricing, lead times, delivery performance, and pending POs.
"""

import pandas as pd
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class PlanningDataLoader:
    """
    Data loader for PO Planning.
    Queries:
      - vendor_product_pricing_view (best price per vendor × product)
      - vendor_delivery_performance_view (on-time rates)
      - quotation_leadtime_rules (transit + paperwork rules)
      - unified_supply_view (existing pending POs to avoid duplicates)
      - product_purchase_orders (last PO price fallback)
    """

    def __init__(self):
        self._engine = None
        self._init_connection()

    def _init_connection(self):
        """Initialize database connection (reuse existing db utility)"""
        try:
            from utils.db import get_db_engine
            self._engine = get_db_engine()
            logger.info("PlanningDataLoader: database connection established")
        except Exception as e:
            logger.error(f"PlanningDataLoader: failed to connect: {e}")
            raise

    def _ensure_connection(self):
        """Check connection health and reconnect if needed"""
        if self._engine is None:
            self._init_connection()
            return
        try:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.warning(f"PlanningDataLoader: reconnecting: {e}")
            try:
                self._engine.dispose()
            except Exception:
                pass
            self._init_connection()

    # =========================================================================
    # VENDOR PRODUCT PRICING (from vendor_product_pricing_view)
    # =========================================================================

    def load_vendor_pricing(
        self,
        product_ids: Optional[Tuple[int, ...]] = None,
        price_type: str = 'STANDARD'
    ) -> pd.DataFrame:
        """
        Load best vendor pricing for products.

        Returns one row per (vendor, product) — already deduped by view.
        Includes: vendor info, pricing, MOQ/SPQ, lead_time_max_days.

        Args:
            product_ids: Filter to specific products (None = all)
            price_type: STANDARD, SPECIAL, or SAMPLE
        """
        self._ensure_connection()

        query = """
        SELECT 
            vendor_id,
            vendor_name,
            vendor_code,
            vendor_type,
            vendor_location_type,
            vendor_country_code,
            
            product_id,
            pt_code,
            product_name,
            brand,
            package_size,
            
            costbook_detail_id,
            costbook_id,
            costbook_number,
            costbook_date,
            valid_to_date,
            
            standard_unit_price,
            buying_unit_price,
            standard_uom,
            buying_uom,
            uom_conversion,
            currency_code,
            vat_percent,
            standard_unit_price_usd,
            buying_unit_price_usd,
            exchange_rate_to_usd,
            
            moq,
            spq,
            moq_value,
            moq_value_usd,
            
            price_type,
            special_price_scope,
            
            lead_time_min,
            lead_time_max,
            lead_time_uom,
            lead_time_max_days,
            lead_time_min_days,
            costbook_default_lead_time,
            
            shipping_mode_code,
            shipping_mode_name,
            trade_term,
            payment_term,
            from_country_id,
            to_country_id,
            
            validity_status,
            days_until_expiry,
            is_approved,
            remarks
        FROM vendor_product_pricing_view
        WHERE price_type = %(price_type)s
        """
        params = {'price_type': price_type}

        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        query += " ORDER BY vendor_name, pt_code"

        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(
                f"Loaded {len(df)} vendor pricing records "
                f"({df['vendor_id'].nunique()} vendors, "
                f"{df['product_id'].nunique()} products)"
            )
            return df
        except Exception as e:
            logger.error(f"Failed to load vendor pricing: {e}")
            return pd.DataFrame()

    # =========================================================================
    # VENDOR DELIVERY PERFORMANCE
    # =========================================================================

    def load_vendor_performance(
        self,
        vendor_ids: Optional[List[int]] = None
    ) -> pd.DataFrame:
        """
        Load vendor delivery performance metrics.

        Returns one row per vendor with on_time_rate_pct, avg_delay_days, etc.
        """
        self._ensure_connection()

        query = """
        SELECT 
            vendor_id,
            vendor_name,
            vendor_code,
            total_po_count,
            total_arrival_count,
            total_arrived_quantity,
            on_time_count,
            late_count,
            on_time_rate_pct,
            avg_delay_days,
            max_delay_days,
            last_arrival_date,
            last_po_date,
            days_since_last_arrival
        FROM vendor_delivery_performance_view
        WHERE 1=1
        """
        params = {}

        if vendor_ids:
            query += " AND vendor_id IN %(vendor_ids)s"
            params['vendor_ids'] = tuple(vendor_ids)

        query += " ORDER BY on_time_rate_pct DESC"

        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(f"Loaded performance data for {len(df)} vendors")
            return df
        except Exception as e:
            logger.error(f"Failed to load vendor performance: {e}")
            return pd.DataFrame()

    # =========================================================================
    # QUOTATION LEADTIME RULES (transit + paperwork by region/ship_mode)
    # =========================================================================

    def load_leadtime_rules(self) -> pd.DataFrame:
        """
        Load quotation lead time rules (transit + paperwork weeks).

        Used to supplement costbook lead time with transit/paperwork estimates
        based on vendor region, trade term, and shipping mode.
        """
        self._ensure_connection()

        query = """
        SELECT 
            id,
            vendor_location_type,
            region_id,
            trade_term_prefix,
            ship_mode,
            transit_lead_time_weeks,
            paperwork_lead_time_weeks,
            (transit_lead_time_weeks + paperwork_lead_time_weeks) AS total_weeks,
            (transit_lead_time_weeks + paperwork_lead_time_weeks) * 7 AS total_days
        FROM quotation_leadtime_rules
        WHERE delete_flag = 0
        ORDER BY vendor_location_type, ship_mode
        """

        try:
            df = pd.read_sql(query, self._engine)
            logger.info(f"Loaded {len(df)} lead time rules")
            return df
        except Exception as e:
            logger.error(f"Failed to load lead time rules: {e}")
            return pd.DataFrame()

    # =========================================================================
    # EXISTING PENDING POs (to avoid duplicate ordering)
    # =========================================================================

    def load_pending_po_by_product(
        self,
        product_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """
        Load existing pending PO quantities per product.

        Uses unified_supply_view WHERE supply_source = 'PURCHASE_ORDER'.
        Returns aggregated pending qty per product.
        """
        self._ensure_connection()

        query = """
        SELECT 
            product_id,
            SUM(available_quantity) AS pending_po_qty,
            COUNT(*) AS pending_po_lines,
            MIN(availability_date) AS earliest_arrival,
            MAX(availability_date) AS latest_arrival
        FROM unified_supply_view
        WHERE supply_source = 'PURCHASE_ORDER'
          AND available_quantity > 0
        """
        params = {}

        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        query += " GROUP BY product_id"

        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(f"Loaded pending PO data for {len(df)} products")
            return df
        except Exception as e:
            logger.error(f"Failed to load pending POs: {e}")
            return pd.DataFrame()

    # =========================================================================
    # LAST PO PRICE FALLBACK (when costbook has no pricing for a product)
    # =========================================================================

    def load_last_po_prices(
        self,
        product_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """
        Load most recent PO price per product (fallback when no costbook).

        Returns one row per (vendor, product) — most recent PO.
        """
        self._ensure_connection()

        query = """
        SELECT 
            po.seller_company_id AS vendor_id,
            v.english_name AS vendor_name,
            ppo.product_id,
            p.pt_code,
            p.name AS product_name,
            p.uom AS standard_uom,
            ppo.unit_cost AS standard_unit_price,
            ppo.purchase_unit_cost AS buying_unit_price,
            ppo.purchaseuom AS buying_uom,
            ppo.conversion AS uom_conversion,
            c.code AS currency_code,
            po.usd_exchange_rate,
            CASE 
                WHEN po.usd_exchange_rate > 0 
                THEN ROUND(ppo.unit_cost / po.usd_exchange_rate, 4)
                ELSE NULL 
            END AS standard_unit_price_usd,
            ppo.quantity AS last_po_qty,
            CAST(po.po_date AS DATE) AS po_date,
            po.po_number,
            ROW_NUMBER() OVER (
                PARTITION BY po.seller_company_id, ppo.product_id
                ORDER BY po.po_date DESC, po.id DESC
            ) AS recency_rank
        FROM product_purchase_orders ppo
        JOIN purchase_orders po ON ppo.purchase_order_id = po.id
        JOIN products p ON ppo.product_id = p.id
        JOIN companies v ON po.seller_company_id = v.id
        LEFT JOIN currencies c ON po.currency_id = c.id
        WHERE ppo.delete_flag = 0
          AND po.delete_flag = 0
          AND ppo.unit_cost > 0
        """
        params = {}

        if product_ids:
            query += " AND ppo.product_id IN %(product_ids)s"
            params['product_ids'] = product_ids

        # Wrap to get only most recent PO per vendor × product
        full_query = f"""
        SELECT * FROM ({query}) ranked
        WHERE recency_rank = 1
        ORDER BY vendor_name, pt_code
        """

        try:
            df = pd.read_sql(full_query, self._engine, params=params)
            logger.info(f"Loaded last PO prices for {len(df)} vendor×product pairs")
            return df
        except Exception as e:
            logger.error(f"Failed to load last PO prices: {e}")
            return pd.DataFrame()


# =============================================================================
# SINGLETON
# =============================================================================
_planning_loader_instance = None


def get_planning_data_loader() -> PlanningDataLoader:
    """Get singleton planning data loader with connection health check"""
    global _planning_loader_instance
    if _planning_loader_instance is None:
        _planning_loader_instance = PlanningDataLoader()
    else:
        try:
            _planning_loader_instance._ensure_connection()
        except Exception as e:
            logger.error(f"Reconnect failed, creating new instance: {e}")
            _planning_loader_instance = PlanningDataLoader()
    return _planning_loader_instance
