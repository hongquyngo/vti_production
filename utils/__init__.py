# utils/__init__.py
"""
Shared Utilities Package for Streamlit Apps

Version: 3.0.0 (Combined)

This package contains common utilities shared across all pages:
- auth: Authentication and session management  
- config: Configuration management (local + Streamlit Cloud)
- db: Database connection management with pooling
- s3_utils: AWS S3 operations (if available)

Compatibility:
- V1: Full exports with s3_utils
- V2: Dict-based config, detailed logging
- V3: Basic functionality

Usage:
    # Import specific modules
    from utils.auth import AuthManager
    from utils.db import get_db_engine, execute_query
    from utils.config import config
    
    # Or import commonly used items directly
    from utils import AuthManager, get_db_engine, config
    
    # V2 style - direct constant imports
    from utils import DB_CONFIG, APP_CONFIG
    
    # V1 style - with query helpers
    from utils import execute_query, execute_update, get_transaction
"""

# Authentication
from .auth import (
    AuthManager,
    require_login,
    require_roles,
)

# Configuration  
from .config import (
    config,
    Config,
    IS_RUNNING_ON_CLOUD,
    DB_CONFIG,
    AWS_CONFIG,
    APP_CONFIG,
    APP_BASE_URL,
    EXCHANGE_RATE_API_KEY,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    EMAIL_SENDER,
    EMAIL_PASSWORD,
    INBOUND_EMAIL_CONFIG,
    OUTBOUND_EMAIL_CONFIG,
)

# Database
from .db import (
    get_db_engine,
    check_db_connection,
    reset_db_engine,
    get_connection,
    get_transaction,
    execute_query,
    execute_query_df,
    execute_update,
    execute_many,
    get_connection_pool_status,
)

# S3 - Optional import (may not exist in all deployments)
try:
    from .s3_utils import (  # type: ignore[import]
        S3Manager,
        get_s3_manager,
        reset_s3_manager,
        upload_pdf,
        upload_image,
        get_company_logo,
        validate_s3_connection,
    )
    _S3_AVAILABLE = True
except ImportError:
    _S3_AVAILABLE = False
    # Create placeholder exports
    S3Manager = None
    get_s3_manager = None
    reset_s3_manager = None
    upload_pdf = None
    upload_image = None
    get_company_logo = None
    validate_s3_connection = None

__all__ = [
    # Auth
    'AuthManager',
    'require_login',
    'require_roles',
    
    # Config
    'config',
    'Config',
    'IS_RUNNING_ON_CLOUD',
    'DB_CONFIG',
    'AWS_CONFIG',
    'APP_CONFIG',
    'APP_BASE_URL',
    'EXCHANGE_RATE_API_KEY',
    'GOOGLE_SERVICE_ACCOUNT_JSON',
    'EMAIL_SENDER',
    'EMAIL_PASSWORD',
    'INBOUND_EMAIL_CONFIG',
    'OUTBOUND_EMAIL_CONFIG',
    
    # Database
    'get_db_engine',
    'check_db_connection',
    'reset_db_engine',
    'get_connection',
    'get_transaction',
    'execute_query',
    'execute_query_df',
    'execute_update',
    'execute_many',
    'get_connection_pool_status',
    
    # S3 (optional)
    'S3Manager',
    'get_s3_manager',
    'reset_s3_manager',
    'upload_pdf',
    'upload_image',
    'get_company_logo',
    'validate_s3_connection',
]

__version__ = '3.0.0'