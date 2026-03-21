# utils/db.py
"""
Database Connection Management

Version: 3.0.0 (Combined)
Features:
- Singleton pattern with thread-safe double-checked locking
- Connection pooling with auto-reconnect
- Health check utilities
- Query execution helpers (V1)
- Context managers for transactions (V1)
- Pool status with invalidatedcount (V2)

Compatibility:
- V1: context managers, query helpers (execute_query, execute_update, etc.)
- V2/V3: direct DB_CONFIG/APP_CONFIG imports, invalidatedcount in pool status
"""

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, DatabaseError
from urllib.parse import quote_plus
import logging
import threading
from typing import Tuple, Optional, Dict, Any, List
from contextlib import contextmanager

from .config import config, DB_CONFIG, APP_CONFIG

logger = logging.getLogger(__name__)

# ==================== SINGLETON ENGINE ====================

_engine = None
_engine_lock = threading.Lock()


def get_db_engine():
    """
    Get SQLAlchemy database engine (singleton pattern)
    
    Thread-safe implementation using double-checked locking.
    Reuses the same engine across all calls to prevent
    connection pool exhaustion.
    
    Returns:
        SQLAlchemy Engine instance
    """
    global _engine
    
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = _create_engine()
    
    return _engine


def _create_engine():
    """Create new database engine with configured settings"""
    # Support both config object (V1) and direct imports (V2/V3)
    db_config = config.get_db_config() if hasattr(config, 'get_db_config') else DB_CONFIG
    app_config = config.app_config if hasattr(config, 'app_config') else APP_CONFIG
    
    # Build connection URL
    user = db_config["user"]
    password = quote_plus(str(db_config["password"]))
    host = db_config["host"]
    port = db_config["port"]
    database = db_config["database"]
    
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    
    logger.info(f"🔌 Creating database engine: mysql+pymysql://{user}:***@{host}:{port}/{database}")
    
    # Pool settings
    pool_size = app_config.get("DB_POOL_SIZE", 5)
    pool_recycle = app_config.get("DB_POOL_RECYCLE", 3600)
    
    engine = create_engine(
        url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,  # Auto-reconnect on stale connections
        echo=False
    )
    
    logger.info(f"✅ Database engine created (pool_size={pool_size}, recycle={pool_recycle}s)")
    
    return engine


# ==================== CONNECTION MANAGEMENT ====================

def check_db_connection() -> Tuple[bool, Optional[str]]:
    """
    Check if database connection is healthy
    
    Returns:
        Tuple of (is_connected: bool, error_message: str or None)
    """
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except OperationalError as e:
        error_msg = "Cannot connect to database. Please check your network/VPN connection."
        logger.error(f"❌ Database connection failed: {e}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Database error: {str(e)}"
        logger.error(f"❌ Database error: {e}")
        return False, error_msg


def reset_db_engine():
    """
    Reset the database engine (force new connection)
    
    Call this after persistent connection errors or
    when you need to reconnect with different settings.
    """
    global _engine
    
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.dispose()
                logger.info("🔄 Database engine disposed")
            except Exception as e:
                logger.error(f"Error disposing engine: {e}")
            _engine = None
    
    logger.info("🔄 Database engine reset - will reconnect on next query")


def get_connection_pool_status() -> Dict[str, Any]:
    """
    Get connection pool statistics for monitoring
    
    Returns:
        Dictionary with pool statistics
    """
    if _engine is None:
        return {"status": "not_initialized"}
    
    try:
        pool = _engine.pool
        status = {
            "status": "active",
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
        # V2: Add invalidatedcount if available
        if hasattr(pool, 'invalidatedcount'):
            status["invalid"] = pool.invalidatedcount()
        return status
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ==================== CONTEXT MANAGERS (V1) ====================

@contextmanager
def get_connection():
    """
    Context manager for database connections
    
    Usage:
        with get_connection() as conn:
            result = conn.execute(text("SELECT * FROM table"))
    """
    engine = get_db_engine()
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_transaction():
    """
    Context manager for database transactions
    
    Usage:
        with get_transaction() as conn:
            conn.execute(text("INSERT INTO ..."))
            conn.execute(text("UPDATE ..."))
            # Auto-commit on success, auto-rollback on exception
    """
    engine = get_db_engine()
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


# ==================== QUERY HELPERS (V1) ====================

def execute_query(query: str, params: Dict = None) -> List[Dict]:
    """
    Execute SELECT query and return results as list of dicts
    
    Args:
        query: SQL query string
        params: Query parameters
        
    Returns:
        List of dictionaries
    """
    engine = get_db_engine()
    
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        return [dict(row._mapping) for row in result]


def execute_query_df(query: str, params: Dict = None) -> pd.DataFrame:
    """
    Execute SELECT query and return results as DataFrame
    
    Args:
        query: SQL query string
        params: Query parameters
        
    Returns:
        pandas DataFrame
    """
    engine = get_db_engine()
    return pd.read_sql(text(query), engine, params=params or {})


def execute_update(query: str, params: Dict = None) -> int:
    """
    Execute INSERT/UPDATE/DELETE query
    
    Args:
        query: SQL query string
        params: Query parameters
        
    Returns:
        Number of affected rows
    """
    engine = get_db_engine()
    
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        conn.commit()
        return result.rowcount


def execute_many(query: str, params_list: List[Dict]) -> int:
    """
    Execute query with multiple parameter sets
    
    Args:
        query: SQL query string
        params_list: List of parameter dictionaries
        
    Returns:
        Total number of affected rows
    """
    engine = get_db_engine()
    total_rows = 0
    
    with engine.connect() as conn:
        for params in params_list:
            result = conn.execute(text(query), params)
            total_rows += result.rowcount
        conn.commit()
    
    return total_rows


# ==================== EXPORTS ====================

__all__ = [
    'get_db_engine',
    'check_db_connection',
    'reset_db_engine',
    'get_connection_pool_status',
    'get_connection',
    'get_transaction',
    'execute_query',
    'execute_query_df',
    'execute_update',
    'execute_many',
]