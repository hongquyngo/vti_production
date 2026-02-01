# utils/bom/state.py
"""
Centralized State Management for BOM Module - VERSION 2.2
Manages all UI state, dialog states, and user interactions

Changes in v2.2:
- Added Smart Filter Bar state management
- Filter keys: types, statuses, issues, date_range, creators, brands
- Default filter: ACTIVE status
- Auto-persist filters in session
- Added filter reset functionality

Changes in v2.1:
- Added DIALOG_EXPORT for export functionality
- Maintained all existing dialog support
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

import streamlit as st

logger = logging.getLogger(__name__)


class StateManager:
    """
    Centralized state management for BOM UI
    Single source of truth for all dialog and UI states
    """
    
    # State keys
    CURRENT_BOM_ID = 'bom_current_id'
    DIALOG_OPEN = 'bom_dialog_open'
    DIALOG_DATA = 'bom_dialog_data'
    UI_FLAGS = 'bom_ui_flags'
    LAST_ACTION = 'bom_last_action'
    
    # Filter state keys (v2.2)
    FILTER_TYPES = 'bom_filter_types'
    FILTER_STATUSES = 'bom_filter_statuses'
    FILTER_ISSUES = 'bom_filter_issues'
    FILTER_DATE_FROM = 'bom_filter_date_from'
    FILTER_DATE_TO = 'bom_filter_date_to'
    FILTER_CREATORS = 'bom_filter_creators'
    FILTER_BRANDS = 'bom_filter_brands'
    FILTER_BOM_CODES = 'bom_filter_bom_codes'
    FILTER_BOM_NAMES = 'bom_filter_bom_names'
    FILTER_PRODUCTS = 'bom_filter_products'
    FILTER_BOM_SEARCH = 'bom_filter_bom_search'        # BOM code/name search
    FILTER_PRODUCT_SEARCH = 'bom_filter_product_search'  # Product code/name search
    
    # Dialog names
    DIALOG_CREATE = 'create'
    DIALOG_VIEW = 'view'
    DIALOG_EDIT = 'edit'
    DIALOG_DELETE = 'delete'
    DIALOG_STATUS = 'status'
    DIALOG_WHERE_USED = 'where_used'
    DIALOG_CLONE = 'clone'
    DIALOG_EXPORT = 'export'  # New export dialog
    
    def __init__(self):
        """Initialize state manager"""
        self.init_state()
    
    def init_state(self):
        """Initialize all default states"""
        
        # Current BOM being worked on
        if self.CURRENT_BOM_ID not in st.session_state:
            st.session_state[self.CURRENT_BOM_ID] = None
        
        # Which dialog is currently open
        if self.DIALOG_OPEN not in st.session_state:
            st.session_state[self.DIALOG_OPEN] = None
        
        # Dialog-specific data
        if self.DIALOG_DATA not in st.session_state:
            st.session_state[self.DIALOG_DATA] = {
                self.DIALOG_CREATE: {
                    'step': 1,
                    'header_data': {},
                    'materials': []
                },
                self.DIALOG_EDIT: {
                    'active_tab': 'info',
                    'unsaved_changes': False,
                    'editing_material_id': None
                },
                self.DIALOG_DELETE: {
                    'confirmed': False
                },
                self.DIALOG_STATUS: {
                    'new_status': None
                },
                self.DIALOG_WHERE_USED: {
                    'product_id': None,
                    'results': None
                },
                self.DIALOG_VIEW: {},
                self.DIALOG_CLONE: {
                    'source_bom_id': None,
                    'step': 1,
                    'header_data': {},
                    'materials': []
                },
                self.DIALOG_EXPORT: {
                    'format': None  # 'pdf' or 'excel'
                }
            }
        
        # UI flags
        if self.UI_FLAGS not in st.session_state:
            st.session_state[self.UI_FLAGS] = {
                'loading': False,
                'show_success': False,
                'show_error': False,
                'message': ''
            }
        
        # Last action info
        if self.LAST_ACTION not in st.session_state:
            st.session_state[self.LAST_ACTION] = {
                'type': None,  # 'create', 'update', 'delete', 'clone', 'export', etc.
                'bom_id': None,
                'bom_code': None,
                'timestamp': None
            }
        
        # Cache for frequently used data
        if 'bom_cache' not in st.session_state:
            st.session_state['bom_cache'] = {
                'products': None,
                'products_timestamp': None,
                'cache_ttl': 300  # 5 minutes
            }
        
        # Smart Filter Bar state (v2.2)
        if self.FILTER_TYPES not in st.session_state:
            st.session_state[self.FILTER_TYPES] = []  # Empty = All types
        
        if self.FILTER_STATUSES not in st.session_state:
            st.session_state[self.FILTER_STATUSES] = ['ACTIVE']  # Default: ACTIVE
        
        if self.FILTER_ISSUES not in st.session_state:
            st.session_state[self.FILTER_ISSUES] = []  # Empty = All
        
        if self.FILTER_DATE_FROM not in st.session_state:
            st.session_state[self.FILTER_DATE_FROM] = None
        
        if self.FILTER_DATE_TO not in st.session_state:
            st.session_state[self.FILTER_DATE_TO] = None
        
        if self.FILTER_CREATORS not in st.session_state:
            st.session_state[self.FILTER_CREATORS] = []  # Empty = All
        
        if self.FILTER_BRANDS not in st.session_state:
            st.session_state[self.FILTER_BRANDS] = []  # Empty = All
        
        if self.FILTER_BOM_CODES not in st.session_state:
            st.session_state[self.FILTER_BOM_CODES] = []  # Empty = All
        
        if self.FILTER_BOM_NAMES not in st.session_state:
            st.session_state[self.FILTER_BOM_NAMES] = []  # Empty = All
        
        if self.FILTER_PRODUCTS not in st.session_state:
            st.session_state[self.FILTER_PRODUCTS] = []  # Empty = All
        
        if self.FILTER_BOM_SEARCH not in st.session_state:
            st.session_state[self.FILTER_BOM_SEARCH] = ""  # Empty = No filter
        
        if self.FILTER_PRODUCT_SEARCH not in st.session_state:
            st.session_state[self.FILTER_PRODUCT_SEARCH] = ""  # Empty = No filter
    
    # ==================== Current BOM Management ====================
    
    def get_current_bom(self) -> Optional[int]:
        """Get currently selected BOM ID"""
        return st.session_state.get(self.CURRENT_BOM_ID)
    
    def set_current_bom(self, bom_id: Optional[int]):
        """Set currently selected BOM"""
        st.session_state[self.CURRENT_BOM_ID] = bom_id
        logger.debug(f"Current BOM set to: {bom_id}")
    
    def clear_current_bom(self):
        """Clear current BOM selection"""
        st.session_state[self.CURRENT_BOM_ID] = None
    
    # ==================== Dialog State Management ====================
    
    def is_dialog_open(self, dialog_name: Optional[str] = None) -> bool:
        """
        Check if a dialog is open
        
        Args:
            dialog_name: Specific dialog to check, or None to check any
        
        Returns:
            True if specified dialog (or any dialog) is open
        """
        current = st.session_state.get(self.DIALOG_OPEN)
        
        if dialog_name is None:
            return current is not None
        
        return current == dialog_name
    
    def open_dialog(self, dialog_name: str, bom_id: Optional[int] = None):
        """
        Open a specific dialog
        
        Args:
            dialog_name: Name of dialog to open
            bom_id: Optional BOM ID to work with
        """
        st.session_state[self.DIALOG_OPEN] = dialog_name
        
        if bom_id is not None:
            self.set_current_bom(bom_id)
            
            # For clone dialog, set source BOM
            if dialog_name == self.DIALOG_CLONE:
                self.set_clone_source(bom_id)
        
        logger.info(f"Dialog opened: {dialog_name}, BOM ID: {bom_id}")
    
    def close_dialog(self):
        """Close current dialog and cleanup"""
        dialog_name = st.session_state.get(self.DIALOG_OPEN)
        
        if dialog_name:
            # Clear dialog-specific state
            self.clear_dialog_state(dialog_name)
            
            # Close dialog
            st.session_state[self.DIALOG_OPEN] = None
            
            logger.info(f"Dialog closed: {dialog_name}")
    
    def get_open_dialog(self) -> Optional[str]:
        """Get name of currently open dialog"""
        return st.session_state.get(self.DIALOG_OPEN)
    
    # ==================== Dialog Data Management ====================
    
    def get_dialog_state(self, dialog_name: str) -> Dict[str, Any]:
        """
        Get state for specific dialog
        
        Args:
            dialog_name: Name of dialog
        
        Returns:
            Dictionary with dialog state
        """
        dialog_data = st.session_state.get(self.DIALOG_DATA, {})
        return dialog_data.get(dialog_name, {})
    
    def set_dialog_state(self, dialog_name: str, data: Dict[str, Any]):
        """
        Set state for specific dialog
        
        Args:
            dialog_name: Name of dialog
            data: State data to set
        """
        if self.DIALOG_DATA not in st.session_state:
            st.session_state[self.DIALOG_DATA] = {}
        
        st.session_state[self.DIALOG_DATA][dialog_name] = data
        logger.debug(f"Dialog state updated: {dialog_name}")
    
    def update_dialog_state(self, dialog_name: str, updates: Dict[str, Any]):
        """
        Update specific fields in dialog state
        
        Args:
            dialog_name: Name of dialog
            updates: Fields to update
        """
        current = self.get_dialog_state(dialog_name)
        current.update(updates)
        self.set_dialog_state(dialog_name, current)
    
    def clear_dialog_state(self, dialog_name: str):
        """
        Clear/reset state for a specific dialog
        
        Args:
            dialog_name: Name of dialog to clear
        """
        default_states = {
            self.DIALOG_CREATE: {
                'step': 1,
                'header_data': {},
                'materials': []
            },
            self.DIALOG_EDIT: {
                'active_tab': 'info',
                'unsaved_changes': False,
                'editing_material_id': None
            },
            self.DIALOG_DELETE: {
                'confirmed': False
            },
            self.DIALOG_STATUS: {
                'new_status': None
            },
            self.DIALOG_WHERE_USED: {
                'product_id': None,
                'results': None
            },
            self.DIALOG_VIEW: {},
            self.DIALOG_CLONE: {
                'source_bom_id': None,
                'step': 1,
                'header_data': {},
                'materials': []
            },
            self.DIALOG_EXPORT: {
                'format': None
            }
        }
        
        if dialog_name in default_states:
            self.set_dialog_state(dialog_name, default_states[dialog_name])
    
    # ==================== Create Dialog State ====================
    
    def get_create_step(self) -> int:
        """Get current step in create wizard"""
        return self.get_dialog_state(self.DIALOG_CREATE).get('step', 1)
    
    def set_create_step(self, step: int):
        """Set current step in create wizard"""
        self.update_dialog_state(self.DIALOG_CREATE, {'step': step})
    
    def get_create_header_data(self) -> Dict[str, Any]:
        """Get header data from create wizard"""
        return self.get_dialog_state(self.DIALOG_CREATE).get('header_data', {})
    
    def set_create_header_data(self, data: Dict[str, Any]):
        """Set header data in create wizard"""
        self.update_dialog_state(self.DIALOG_CREATE, {'header_data': data})
    
    def get_create_materials(self) -> List[Dict[str, Any]]:
        """Get materials list from create wizard"""
        return self.get_dialog_state(self.DIALOG_CREATE).get('materials', [])
    
    def add_create_material(self, material: Dict[str, Any]):
        """Add material to create wizard"""
        materials = self.get_create_materials()
        materials.append(material)
        self.update_dialog_state(self.DIALOG_CREATE, {'materials': materials})
    
    def remove_create_material(self, index: int):
        """Remove material from create wizard by index"""
        materials = self.get_create_materials()
        if 0 <= index < len(materials):
            materials.pop(index)
            self.update_dialog_state(self.DIALOG_CREATE, {'materials': materials})
    
    # ==================== Clone Dialog State ====================
    
    def get_clone_source(self) -> Optional[int]:
        """Get source BOM ID for cloning"""
        return self.get_dialog_state(self.DIALOG_CLONE).get('source_bom_id')
    
    def set_clone_source(self, bom_id: int):
        """Set source BOM ID for cloning"""
        self.update_dialog_state(self.DIALOG_CLONE, {'source_bom_id': bom_id})
    
    def get_clone_step(self) -> int:
        """Get current step in clone wizard"""
        return self.get_dialog_state(self.DIALOG_CLONE).get('step', 1)
    
    def set_clone_step(self, step: int):
        """Set current step in clone wizard"""
        self.update_dialog_state(self.DIALOG_CLONE, {'step': step})
    
    def get_clone_header_data(self) -> Dict[str, Any]:
        """Get header data for clone"""
        return self.get_dialog_state(self.DIALOG_CLONE).get('header_data', {})
    
    def set_clone_header_data(self, data: Dict[str, Any]):
        """Set header data for clone"""
        self.update_dialog_state(self.DIALOG_CLONE, {'header_data': data})
    
    def get_clone_materials(self) -> List[Dict[str, Any]]:
        """Get materials list for clone"""
        return self.get_dialog_state(self.DIALOG_CLONE).get('materials', [])
    
    def set_clone_materials(self, materials: List[Dict[str, Any]]):
        """Set materials list for clone"""
        self.update_dialog_state(self.DIALOG_CLONE, {'materials': materials})
    
    # ==================== Edit Dialog State ====================
    
    def get_edit_tab(self) -> str:
        """Get active tab in edit dialog"""
        return self.get_dialog_state(self.DIALOG_EDIT).get('active_tab', 'info')
    
    def set_edit_tab(self, tab: str):
        """Set active tab in edit dialog"""
        self.update_dialog_state(self.DIALOG_EDIT, {'active_tab': tab})
    
    def has_unsaved_changes(self) -> bool:
        """Check if edit dialog has unsaved changes"""
        return self.get_dialog_state(self.DIALOG_EDIT).get('unsaved_changes', False)
    
    def mark_unsaved_changes(self, unsaved: bool = True):
        """Mark edit dialog as having unsaved changes"""
        self.update_dialog_state(self.DIALOG_EDIT, {'unsaved_changes': unsaved})
    
    # ==================== Where Used Dialog State ====================
    
    def get_where_used_product(self) -> Optional[int]:
        """Get product ID for where used search"""
        return self.get_dialog_state(self.DIALOG_WHERE_USED).get('product_id')
    
    def set_where_used_product(self, product_id: int):
        """Set product ID for where used search"""
        self.update_dialog_state(self.DIALOG_WHERE_USED, {'product_id': product_id})
    
    def get_where_used_results(self) -> Optional[Any]:
        """Get where used search results"""
        return self.get_dialog_state(self.DIALOG_WHERE_USED).get('results')
    
    def set_where_used_results(self, results: Any):
        """Set where used search results"""
        self.update_dialog_state(self.DIALOG_WHERE_USED, {'results': results})
    
    # ==================== Export Dialog State ====================
    
    def get_export_format(self) -> Optional[str]:
        """Get selected export format"""
        return self.get_dialog_state(self.DIALOG_EXPORT).get('format')
    
    def set_export_format(self, format_type: str):
        """Set export format ('pdf' or 'excel')"""
        self.update_dialog_state(self.DIALOG_EXPORT, {'format': format_type})
    
    # ==================== UI Flags Management ====================
    
    def set_loading(self, loading: bool = True):
        """Set loading state"""
        flags = st.session_state.get(self.UI_FLAGS, {})
        flags['loading'] = loading
        st.session_state[self.UI_FLAGS] = flags
    
    def is_loading(self) -> bool:
        """Check if in loading state"""
        return st.session_state.get(self.UI_FLAGS, {}).get('loading', False)
    
    def show_success(self, message: str):
        """Show success message"""
        flags = st.session_state.get(self.UI_FLAGS, {})
        flags.update({
            'show_success': True,
            'show_error': False,
            'message': message
        })
        st.session_state[self.UI_FLAGS] = flags
    
    def show_error(self, message: str):
        """Show error message"""
        flags = st.session_state.get(self.UI_FLAGS, {})
        flags.update({
            'show_success': False,
            'show_error': True,
            'message': message
        })
        st.session_state[self.UI_FLAGS] = flags
    
    def clear_messages(self):
        """Clear success/error messages"""
        flags = st.session_state.get(self.UI_FLAGS, {})
        flags.update({
            'show_success': False,
            'show_error': False,
            'message': ''
        })
        st.session_state[self.UI_FLAGS] = flags
    
    def get_message(self) -> tuple[bool, bool, str]:
        """
        Get current message state
        
        Returns:
            Tuple of (show_success, show_error, message)
        """
        flags = st.session_state.get(self.UI_FLAGS, {})
        return (
            flags.get('show_success', False),
            flags.get('show_error', False),
            flags.get('message', '')
        )
    
    # ==================== Last Action Management ====================
    
    def record_action(self, action_type: str, bom_id: Optional[int] = None, 
                     bom_code: Optional[str] = None):
        """
        Record last action for undo/history
        
        Args:
            action_type: Type of action (create, update, delete, clone, export, etc.)
            bom_id: BOM ID affected
            bom_code: BOM code affected
        """
        st.session_state[self.LAST_ACTION] = {
            'type': action_type,
            'bom_id': bom_id,
            'bom_code': bom_code,
            'timestamp': datetime.now()
        }
        logger.info(f"Action recorded: {action_type}, BOM: {bom_code}")
    
    def get_last_action(self) -> Dict[str, Any]:
        """Get last action info"""
        return st.session_state.get(self.LAST_ACTION, {})
    
    # ==================== Cache Management ====================
    
    def get_cached_products(self):
        """Get cached products list"""
        cache = st.session_state.get('bom_cache', {})
        
        # Check if cache is valid
        if cache.get('products') is not None:
            timestamp = cache.get('products_timestamp')
            if timestamp:
                age = (datetime.now() - timestamp).total_seconds()
                if age < cache.get('cache_ttl', 300):
                    return cache['products']
        
        return None
    
    def set_cached_products(self, products):
        """Set cached products list"""
        if 'bom_cache' not in st.session_state:
            st.session_state['bom_cache'] = {}
        
        st.session_state['bom_cache']['products'] = products
        st.session_state['bom_cache']['products_timestamp'] = datetime.now()
    
    def clear_cache(self):
        """Clear all cached data including BOM lists"""
        # Clear products cache
        if 'bom_cache' in st.session_state:
            st.session_state['bom_cache'] = {
                'products': None,
                'products_timestamp': None,
                'cache_ttl': 300
            }
        
        # Clear BOM list caches
        if 'all_boms' in st.session_state:
            del st.session_state['all_boms']
        
        if 'filtered_boms' in st.session_state:
            del st.session_state['filtered_boms']
        
        logger.info("All caches cleared (products, all_boms, filtered_boms)")
    
    def clear_bom_list_cache(self):
        """Clear only BOM list cache (for use after CRUD operations)"""
        if 'all_boms' in st.session_state:
            del st.session_state['all_boms']
        
        if 'filtered_boms' in st.session_state:
            del st.session_state['filtered_boms']
        
        logger.debug("BOM list cache cleared")
    
    # ==================== Smart Filter Bar Management (v2.2) ====================
    
    def get_filter_types(self) -> List[str]:
        """Get selected BOM types filter"""
        return st.session_state.get(self.FILTER_TYPES, [])
    
    def set_filter_types(self, types: List[str]):
        """Set BOM types filter"""
        st.session_state[self.FILTER_TYPES] = types
    
    def get_filter_statuses(self) -> List[str]:
        """Get selected statuses filter"""
        return st.session_state.get(self.FILTER_STATUSES, ['ACTIVE'])
    
    def set_filter_statuses(self, statuses: List[str]):
        """Set statuses filter"""
        st.session_state[self.FILTER_STATUSES] = statuses
    
    def get_filter_issues(self) -> List[str]:
        """Get selected issues filter"""
        return st.session_state.get(self.FILTER_ISSUES, [])
    
    def set_filter_issues(self, issues: List[str]):
        """Set issues filter"""
        st.session_state[self.FILTER_ISSUES] = issues
    
    def get_filter_date_range(self) -> tuple:
        """Get date range filter (from, to)"""
        return (
            st.session_state.get(self.FILTER_DATE_FROM),
            st.session_state.get(self.FILTER_DATE_TO)
        )
    
    def set_filter_date_range(self, date_from, date_to):
        """Set date range filter"""
        st.session_state[self.FILTER_DATE_FROM] = date_from
        st.session_state[self.FILTER_DATE_TO] = date_to
    
    def get_filter_creators(self) -> List[str]:
        """Get selected creators filter"""
        return st.session_state.get(self.FILTER_CREATORS, [])
    
    def set_filter_creators(self, creators: List[str]):
        """Set creators filter"""
        st.session_state[self.FILTER_CREATORS] = creators
    
    def get_filter_brands(self) -> List[str]:
        """Get selected brands filter"""
        return st.session_state.get(self.FILTER_BRANDS, [])
    
    def set_filter_brands(self, brands: List[str]):
        """Set brands filter"""
        st.session_state[self.FILTER_BRANDS] = brands
    
    def get_filter_bom_codes(self) -> List[str]:
        """Get selected BOM codes filter"""
        return st.session_state.get(self.FILTER_BOM_CODES, [])
    
    def set_filter_bom_codes(self, bom_codes: List[str]):
        """Set BOM codes filter"""
        st.session_state[self.FILTER_BOM_CODES] = bom_codes
    
    def get_filter_bom_names(self) -> List[str]:
        """Get selected BOM names filter"""
        return st.session_state.get(self.FILTER_BOM_NAMES, [])
    
    def set_filter_bom_names(self, bom_names: List[str]):
        """Set BOM names filter"""
        st.session_state[self.FILTER_BOM_NAMES] = bom_names
    
    def get_filter_products(self) -> List[str]:
        """Get selected products filter (product_id as string)"""
        return st.session_state.get(self.FILTER_PRODUCTS, [])
    
    def set_filter_products(self, products: List[str]):
        """Set products filter"""
        st.session_state[self.FILTER_PRODUCTS] = products
    
    def get_all_filters(self) -> Dict[str, Any]:
        """Get all current filter values"""
        return {
            'types': self.get_filter_types(),
            'statuses': self.get_filter_statuses(),
            'issues': self.get_filter_issues(),
            'date_from': st.session_state.get(self.FILTER_DATE_FROM),
            'date_to': st.session_state.get(self.FILTER_DATE_TO),
            'creators': self.get_filter_creators(),
            'brands': self.get_filter_brands(),
            'bom_codes': self.get_filter_bom_codes(),
            'bom_names': self.get_filter_bom_names(),
            'products': self.get_filter_products()
        }
    
    def reset_filters(self):
        """Reset all filters to default values"""
        st.session_state[self.FILTER_TYPES] = []
        st.session_state[self.FILTER_STATUSES] = ['ACTIVE']  # Default
        st.session_state[self.FILTER_ISSUES] = []
        st.session_state[self.FILTER_DATE_FROM] = None
        st.session_state[self.FILTER_DATE_TO] = None
        st.session_state[self.FILTER_CREATORS] = []
        st.session_state[self.FILTER_BRANDS] = []
        st.session_state[self.FILTER_BOM_CODES] = []
        st.session_state[self.FILTER_BOM_NAMES] = []
        st.session_state[self.FILTER_PRODUCTS] = []
        logger.info("All filters reset to defaults")
    
    def has_active_filters(self) -> bool:
        """Check if any non-default filters are active"""
        filters = self.get_all_filters()
        
        # Check if any filter differs from default
        if filters['types']:
            return True
        if filters['statuses'] != ['ACTIVE']:
            return True
        if filters['issues']:
            return True
        if filters['date_from'] or filters['date_to']:
            return True
        if filters['creators']:
            return True
        if filters['brands']:
            return True
        if filters['bom_codes']:
            return True
        if filters['bom_names']:
            return True
        if filters['products']:
            return True
        
        return False
    
    def get_active_filter_chips(self) -> List[Dict[str, str]]:
        """
        Get list of active filter chips for display
        
        Returns:
            List of dicts with keys: category, value, display_label
        """
        chips = []
        
        # BOM Code chips
        for code in self.get_filter_bom_codes():
            chips.append({
                'category': 'bom_code',
                'value': code,
                'label': f"🔖 {code}"
            })
        
        # BOM Name chips
        for name in self.get_filter_bom_names():
            display_name = name[:15] + "..." if len(name) > 15 else name
            chips.append({
                'category': 'bom_name',
                'value': name,
                'label': f"📝 {display_name}"
            })
        
        # Product chips
        for prod in self.get_filter_products():
            display_prod = prod[:20] + "..." if len(prod) > 20 else prod
            chips.append({
                'category': 'product',
                'value': prod,
                'label': f"📦 {display_prod}"
            })
        
        # Type chips
        for t in self.get_filter_types():
            chips.append({
                'category': 'type',
                'value': t,
                'label': f"🏭 {t}"
            })
        
        # Status chips
        for s in self.get_filter_statuses():
            chips.append({
                'category': 'status',
                'value': s,
                'label': f"📊 {s}"
            })
        
        # Issues chips
        for i in self.get_filter_issues():
            icon = "🔴" if i == "Conflicts" else "⚠️" if i == "Duplicates" else "✅"
            chips.append({
                'category': 'issue',
                'value': i,
                'label': f"{icon} {i}"
            })
        
        # Date range chips
        date_from, date_to = self.get_filter_date_range()
        if date_from:
            chips.append({
                'category': 'date_from',
                'value': str(date_from),
                'label': f"📅 From: {date_from.strftime('%d/%m/%Y') if hasattr(date_from, 'strftime') else date_from}"
            })
        if date_to:
            chips.append({
                'category': 'date_to',
                'value': str(date_to),
                'label': f"📅 To: {date_to.strftime('%d/%m/%Y') if hasattr(date_to, 'strftime') else date_to}"
            })
        
        # Creator chips
        for c in self.get_filter_creators():
            chips.append({
                'category': 'creator',
                'value': c,
                'label': f"👤 {c}"
            })
        
        # Brand chips
        for b in self.get_filter_brands():
            chips.append({
                'category': 'brand',
                'value': b,
                'label': f"🏷️ {b}"
            })
        
        return chips
    
    def remove_filter_chip(self, category: str, value: str):
        """Remove a specific filter chip"""
        if category == 'bom_code':
            codes = self.get_filter_bom_codes()
            if value in codes:
                codes.remove(value)
                self.set_filter_bom_codes(codes)
        
        elif category == 'bom_name':
            names = self.get_filter_bom_names()
            if value in names:
                names.remove(value)
                self.set_filter_bom_names(names)
        
        elif category == 'product':
            products = self.get_filter_products()
            if value in products:
                products.remove(value)
                self.set_filter_products(products)
        
        elif category == 'type':
            types = self.get_filter_types()
            if value in types:
                types.remove(value)
                self.set_filter_types(types)
        
        elif category == 'status':
            statuses = self.get_filter_statuses()
            if value in statuses:
                statuses.remove(value)
                self.set_filter_statuses(statuses)
        
        elif category == 'issue':
            issues = self.get_filter_issues()
            if value in issues:
                issues.remove(value)
                self.set_filter_issues(issues)
        
        elif category == 'date_from':
            st.session_state[self.FILTER_DATE_FROM] = None
        
        elif category == 'date_to':
            st.session_state[self.FILTER_DATE_TO] = None
        
        elif category == 'creator':
            creators = self.get_filter_creators()
            if value in creators:
                creators.remove(value)
                self.set_filter_creators(creators)
        
        elif category == 'brand':
            brands = self.get_filter_brands()
            if value in brands:
                brands.remove(value)
                self.set_filter_brands(brands)