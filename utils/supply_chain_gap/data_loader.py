# utils/supply_chain_gap/data_loader.py

"""
Data Loader for Supply Chain GAP Analysis
Loads all data: FG supply/demand, BOM, raw materials, safety stock
"""

import pandas as pd
import logging
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)


class SupplyChainDataLoader:
    """
    Unified data loader for Supply Chain GAP Analysis.
    Loads FG supply/demand, BOM data, raw material supply, and safety stock.
    """
    
    def __init__(self):
        self._engine = None
        self._init_connection()
    
    def _init_connection(self):
        """Initialize database connection"""
        try:
            from utils.db import get_db_engine
            self._engine = get_db_engine()
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
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
            logger.warning(f"Database connection lost, reconnecting: {e}")
            try:
                self._engine.dispose()
            except Exception:
                pass
            self._init_connection()
    
    # =========================================================================
    # FG SUPPLY DATA
    # =========================================================================
    
    def load_fg_supply(
        self,
        entity_name: Optional[str] = None,
        product_ids: Optional[Tuple[int, ...]] = None,
        brands: Optional[Tuple[str, ...]] = None,
        exclude_expired: bool = True
    ) -> pd.DataFrame:
        """Load FG/Output product supply from unified_supply_view"""
        
        query = """
        SELECT 
            supply_source,
            product_id,
            product_name,
            brand,
            pt_code,
            package_size,
            standard_uom,
            batch_number,
            expiry_date,
            days_to_expiry,
            available_quantity,
            availability_date,
            availability_status,
            warehouse_name,
            entity_name,
            unit_cost_usd,
            total_value_usd
        FROM unified_supply_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids
        
        if brands:
            query += " AND brand IN %(brands)s"
            params['brands'] = brands
        
        if exclude_expired:
            query += " AND (expiry_date IS NULL OR expiry_date > CURDATE())"
        
        df = pd.read_sql(query, self._engine, params=params)
        logger.info(f"Loaded {len(df)} FG supply records")
        return df
    
    # =========================================================================
    # FG DEMAND DATA
    # =========================================================================
    
    def load_fg_demand(
        self,
        entity_name: Optional[str] = None,
        product_ids: Optional[Tuple[int, ...]] = None,
        brands: Optional[Tuple[str, ...]] = None
    ) -> pd.DataFrame:
        """Load FG/Output product demand from unified_demand_view"""
        
        query = """
        SELECT 
            demand_source,
            demand_priority,
            product_id,
            product_name,
            brand,
            pt_code,
            package_size,
            standard_uom,
            customer,
            customer_code,
            required_quantity,
            required_date,
            days_to_required,
            selling_unit_price,
            total_value_usd,
            entity_name
        FROM unified_demand_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids
        
        if brands:
            query += " AND brand IN %(brands)s"
            params['brands'] = brands
        
        df = pd.read_sql(query, self._engine, params=params)
        logger.info(f"Loaded {len(df)} FG demand records")
        return df
    
    # =========================================================================
    # FG SAFETY STOCK
    # =========================================================================
    
    def load_fg_safety_stock(
        self,
        entity_name: Optional[str] = None,
        product_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """Load FG safety stock from safety_stock_current_view"""
        
        query = """
        SELECT 
            product_id,
            product_name,
            pt_code,
            brand,
            entity_name,
            safety_stock_qty,
            reorder_point,
            standard_uom,
            calculation_method
        FROM safety_stock_current_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            logger.info(f"Loaded {len(df)} FG safety stock records")
            return df
        except Exception as e:
            logger.warning(f"Could not load FG safety stock: {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # PRODUCT CLASSIFICATION
    # =========================================================================
    
    def load_product_classification(
        self,
        entity_name: Optional[str] = None,
        product_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """
        Load product classification (Manufacturing vs Trading).
        Uses product_classification_view.
        """
        
        query = """
        SELECT 
            product_id,
            pt_code,
            product_name,
            brand,
            standard_uom,
            has_bom,
            product_type,
            bom_id,
            bom_code,
            bom_type,
            bom_output_qty,
            primary_material_count,
            alternative_material_count
        FROM product_classification_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            # Try entity_name filter — view may or may not have this column
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if product_ids:
            query += " AND product_id IN %(product_ids)s"
            params['product_ids'] = product_ids
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency
            if 'bom_output_qty' in df.columns:
                df.rename(columns={'bom_output_qty': 'bom_output_quantity'}, inplace=True)
            logger.info(f"Loaded {len(df)} product classifications")
            return df
        except Exception as e:
            # Retry without entity_name filter (view may not have this column)
            if entity_name and 'entity_name' in str(e):
                logger.warning(f"product_classification_view has no entity_name column, retrying without entity filter")
                query_no_entity = """
                SELECT 
                    product_id, pt_code, product_name, brand, standard_uom,
                    has_bom, product_type, bom_id, bom_code, bom_type,
                    bom_output_qty, primary_material_count, alternative_material_count
                FROM product_classification_view
                WHERE 1=1
                """
                params_no_entity = {}
                if product_ids:
                    query_no_entity += " AND product_id IN %(product_ids)s"
                    params_no_entity['product_ids'] = product_ids
                try:
                    df = pd.read_sql(query_no_entity, self._engine, params=params_no_entity)
                    if 'bom_output_qty' in df.columns:
                        df.rename(columns={'bom_output_qty': 'bom_output_quantity'}, inplace=True)
                    logger.info(f"Loaded {len(df)} product classifications (without entity filter)")
                    return df
                except Exception as e2:
                    logger.warning(f"Could not load product classification: {e2}")
                    return pd.DataFrame()
            logger.warning(f"Could not load product classification (view may not exist): {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # BOM EXPLOSION
    # =========================================================================
    
    def load_bom_explosion(
        self,
        entity_name: Optional[str] = None,
        output_product_ids: Optional[Tuple[int, ...]] = None,
        include_alternatives: bool = True
    ) -> pd.DataFrame:
        """
        Load BOM explosion data.
        Uses bom_explosion_view.
        """
        
        query = """
        SELECT 
            bom_id,
            bom_code,
            bom_name,
            bom_type,
            output_product_id,
            output_qty,
            output_uom,
            bom_detail_id,
            material_id,
            material_pt_code,
            material_name,
            material_uom,
            material_brand,
            material_package_size,
            material_type,
            is_primary,
            alternative_priority,
            quantity_per_output,
            scrap_rate,
            effective_quantity_per_output,
            primary_material_id
        FROM bom_explosion_view
        WHERE 1=1
        """
        params = {}
        
        if output_product_ids:
            query += " AND output_product_id IN %(output_product_ids)s"
            params['output_product_ids'] = output_product_ids
        
        if not include_alternatives:
            query += " AND is_primary = 1"
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency
            if 'output_qty' in df.columns:
                df.rename(columns={'output_qty': 'bom_output_quantity'}, inplace=True)
            logger.info(f"Loaded {len(df)} BOM explosion records")
            return df
        except Exception as e:
            logger.warning(f"Could not load BOM explosion (view may not exist): {e}")
            return pd.DataFrame()
    
    def load_bom_full_explosion(
        self,
        root_product_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """
        Load multi-level BOM explosion from bom_full_explosion_view.
        Recursive CTE that walks entire BOM tree: FG → Semi-finished → Raw.
        
        Used for:
        - UI drill-down: show full BOM tree per FG product
        - Export: multi-level BOM details
        - Calculator: determine is_leaf for each material
        
        Columns include bom_level, is_leaf, cumulative_qty_per_root,
        material_category, bom_path, display_hierarchy.
        """
        
        query = """
        SELECT 
            root_bom_id,
            root_bom_code,
            root_product_id,
            bom_id,
            bom_code,
            bom_type,
            output_product_id,
            output_qty,
            output_uom,
            bom_detail_id,
            material_id,
            material_pt_code,
            material_name,
            material_uom,
            material_brand,
            material_package_size,
            material_type,
            is_primary,
            alternative_priority,
            primary_material_id,
            quantity_per_output,
            scrap_rate,
            effective_qty_per_output,
            cumulative_qty_per_root,
            bom_level,
            bom_path,
            is_leaf,
            display_hierarchy,
            material_category
        FROM bom_full_explosion_view
        WHERE 1=1
        """
        params = {}
        
        if root_product_ids:
            query += " AND root_product_id IN %(root_product_ids)s"
            params['root_product_ids'] = root_product_ids
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency with existing code
            if 'output_qty' in df.columns:
                df.rename(columns={'output_qty': 'bom_output_quantity'}, inplace=True)
            logger.info(f"Loaded {len(df)} multi-level BOM records "
                       f"(max depth: {df['bom_level'].max() if not df.empty else 0})")
            return df
        except Exception as e:
            logger.warning(f"Could not load bom_full_explosion_view (may not exist yet): {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # EXISTING MO DEMAND
    # =========================================================================
    
    def load_existing_mo_demand(
        self,
        entity_name: Optional[str] = None,
        material_ids: Optional[Tuple[int, ...]] = None,
        include_draft_mo: bool = False
    ) -> pd.DataFrame:
        """
        Load existing MO demand for raw materials.
        Uses manufacturing_raw_demand_view.
        
        Args:
            include_draft_mo: If True, include DRAFT MOs. Default False because:
                - DRAFT MO output is only in FG supply when user enables it
                - Both sides (FG supply + raw demand) must include the same MO set
                - DRAFT MOs are uncommitted and may be cancelled
        """
        
        # Build status list matching MO_EXPECTED in unified_supply_view
        mo_statuses = ['CONFIRMED', 'IN_PROGRESS']
        if include_draft_mo:
            mo_statuses.append('DRAFT')
        
        status_placeholders = ', '.join([f"'{s}'" for s in mo_statuses])
        
        query = f"""
        SELECT 
            material_id,
            material_pt_code,
            material_name,
            material_uom,
            material_brand,
            material_package_size,
            material_type,
            output_product_id,
            output_pt_code,
            output_product_name,
            manufacturing_order_id,
            order_no,
            mo_status,
            required_qty,
            issued_qty,
            returned_qty,
            pending_material_qty,
            scheduled_date,
            days_to_scheduled,
            urgency_level,
            entity_name
        FROM manufacturing_raw_demand_view
        WHERE mo_status IN ({status_placeholders})
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if material_ids:
            query += " AND material_id IN %(material_ids)s"
            params['material_ids'] = material_ids
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency
            if 'order_no' in df.columns:
                df.rename(columns={'order_no': 'mo_number'}, inplace=True)
            if 'pending_material_qty' in df.columns:
                df.rename(columns={'pending_material_qty': 'pending_qty'}, inplace=True)
            logger.info(f"Loaded {len(df)} existing MO demand records")
            return df
        except Exception as e:
            logger.warning(f"Could not load existing MO demand (view may not exist): {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # RAW MATERIAL SUPPLY
    # =========================================================================
    
    def load_raw_material_supply(
        self,
        entity_name: Optional[str] = None,
        material_ids: Optional[Tuple[int, ...]] = None,
        exclude_expired: bool = True
    ) -> pd.DataFrame:
        """
        Load raw material supply.
        Uses raw_material_supply_view (extends unified_supply_view).
        """
        
        query = """
        SELECT 
            product_id,
            pt_code,
            product_name,
            brand,
            package_size,
            standard_uom,
            supply_source,
            batch_number,
            expiry_date,
            days_to_expiry,
            available_quantity,
            warehouse_name,
            unit_cost_usd,
            entity_name,
            is_primary_in_bom,
            is_alternative_in_bom
        FROM raw_material_supply_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if material_ids:
            query += " AND product_id IN %(material_ids)s"
            params['material_ids'] = material_ids
        
        if exclude_expired:
            query += " AND (expiry_date IS NULL OR expiry_date > CURDATE())"
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency
            df.rename(columns={
                'product_id': 'material_id',
                'pt_code': 'material_pt_code',
                'product_name': 'material_name',
                'brand': 'material_brand',
                'package_size': 'material_package_size',
                'standard_uom': 'material_uom',
                'unit_cost_usd': 'unit_cost'
            }, inplace=True)
            logger.info(f"Loaded {len(df)} raw material supply records")
            return df
        except Exception as e:
            logger.warning(f"Could not load raw material supply (view may not exist): {e}")
            return pd.DataFrame()
    
    def load_raw_material_supply_summary(
        self,
        entity_name: Optional[str] = None,
        material_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """
        Load aggregated raw material supply.
        Uses raw_material_supply_summary_view.
        """
        
        query = """
        SELECT 
            product_id,
            pt_code,
            product_name,
            brand,
            package_size,
            standard_uom,
            entity_name,
            supply_inventory,
            supply_can_pending,
            supply_warehouse_transfer,
            supply_purchase_order,
            total_supply,
            is_primary_in_bom,
            is_alternative_in_bom
        FROM raw_material_supply_summary_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if material_ids:
            query += " AND product_id IN %(material_ids)s"
            params['material_ids'] = material_ids
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency
            df.rename(columns={
                'product_id': 'material_id',
                'pt_code': 'material_pt_code',
                'product_name': 'material_name',
                'brand': 'material_brand',
                'package_size': 'material_package_size',
                'standard_uom': 'material_uom',
                'supply_inventory': 'inventory_qty',
                'supply_can_pending': 'can_pending_qty',
                'supply_warehouse_transfer': 'warehouse_transfer_qty',
                'supply_purchase_order': 'purchase_order_qty'
            }, inplace=True)
            logger.info(f"Loaded {len(df)} raw material supply summaries")
            return df
        except Exception as e:
            logger.warning(f"Could not load raw material supply summary (view may not exist): {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # RAW MATERIAL SAFETY STOCK
    # =========================================================================
    
    def load_raw_material_safety_stock(
        self,
        entity_name: Optional[str] = None,
        material_ids: Optional[Tuple[int, ...]] = None
    ) -> pd.DataFrame:
        """
        Load raw material safety stock.
        Uses raw_material_safety_stock_view (extends safety_stock_current_view).
        """
        
        query = """
        SELECT 
            product_id,
            product_name,
            pt_code,
            brand,
            entity_name,
            safety_stock_qty,
            reorder_point,
            standard_uom,
            calculation_method
        FROM raw_material_safety_stock_view
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if material_ids:
            query += " AND product_id IN %(material_ids)s"
            params['material_ids'] = material_ids
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            # Rename for consistency
            df.rename(columns={
                'product_id': 'material_id',
                'pt_code': 'material_pt_code',
                'product_name': 'material_name'
            }, inplace=True)
            logger.info(f"Loaded {len(df)} raw material safety stock records")
            return df
        except Exception as e:
            logger.warning(f"Could not load raw material safety stock (view may not exist): {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def get_entities(self) -> List[str]:
        """Get list of available entities from supply/demand views"""
        query = """
        SELECT DISTINCT entity_name
        FROM (
            SELECT DISTINCT entity_name FROM unified_supply_view 
            WHERE entity_name IS NOT NULL
            UNION
            SELECT DISTINCT entity_name FROM unified_demand_view 
            WHERE entity_name IS NOT NULL
        ) AS entities
        ORDER BY entity_name
        """
        try:
            df = pd.read_sql(query, self._engine)
            return df['entity_name'].tolist()
        except Exception as e:
            logger.warning(f"Could not load entities: {e}")
            return []
    
    def get_brands(self, entity_name: Optional[str] = None) -> List[str]:
        """Get list of available brands from supply/demand views"""
        query = """
        SELECT DISTINCT brand
        FROM (
            SELECT DISTINCT brand, entity_name FROM unified_supply_view 
            WHERE brand IS NOT NULL
            UNION
            SELECT DISTINCT brand, entity_name FROM unified_demand_view 
            WHERE brand IS NOT NULL
        ) AS brands
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        query += " ORDER BY brand"
        
        try:
            df = pd.read_sql(query, self._engine, params=params)
            return df['brand'].tolist()
        except Exception as e:
            logger.warning(f"Could not load brands: {e}")
            return []
    
    def get_products(
        self,
        entity_name: Optional[str] = None,
        brand: Optional[str] = None
    ) -> pd.DataFrame:
        """Get list of products from supply/demand views"""
        query = """
        SELECT DISTINCT 
            product_id, 
            pt_code, 
            product_name, 
            brand
        FROM (
            SELECT product_id, product_name, pt_code, brand, entity_name
            FROM unified_supply_view
            WHERE pt_code IS NOT NULL
            UNION
            SELECT product_id, product_name, pt_code, brand, entity_name
            FROM unified_demand_view
            WHERE pt_code IS NOT NULL
        ) AS products
        WHERE 1=1
        """
        params = {}
        
        if entity_name:
            query += " AND entity_name = %(entity_name)s"
            params['entity_name'] = entity_name
        
        if brand:
            query += " AND brand = %(brand)s"
            params['brand'] = brand
        
        query += " ORDER BY pt_code, product_name"
        
        try:
            return pd.read_sql(query, self._engine, params=params)
        except Exception as e:
            logger.warning(f"Could not load products: {e}")
            return pd.DataFrame(columns=['product_id', 'pt_code', 'product_name', 'brand'])


# Singleton instance
_data_loader_instance = None

def get_data_loader() -> SupplyChainDataLoader:
    """Get singleton data loader instance with connection health check"""
    global _data_loader_instance
    if _data_loader_instance is None:
        _data_loader_instance = SupplyChainDataLoader()
    else:
        try:
            _data_loader_instance._ensure_connection()
        except Exception as e:
            logger.error(f"Failed to reconnect, creating new instance: {e}")
            _data_loader_instance = SupplyChainDataLoader()
    return _data_loader_instance