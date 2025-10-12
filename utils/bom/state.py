# utils/bom/state.py
"""
Centralized State Management for BOM Module - CLEANED VERSION
Manages all UI state, dialog states, and user interactions
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
    
    # Dialog names
    DIALOG_CREATE = 'create'
    DIALOG_VIEW = 'view'
    DIALOG_EDIT = 'edit'
    DIALOG_DELETE = 'delete'
    DIALOG_STATUS = 'status'
    DIALOG_WHERE_USED = 'where_used'
    
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
                self.DIALOG_VIEW: {}
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
                'type': None,  # 'create', 'update', 'delete', etc.
                'bom_id': None,
                'bom_code': None,
                'timestamp': None
            }
    
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
        Clear state for specific dialog (reset to defaults)
        
        Args:
            dialog_name: Name of dialog to clear
        """
        defaults = {
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
            self.DIALOG_VIEW: {}
        }
        
        if dialog_name in defaults:
            self.set_dialog_state(dialog_name, defaults[dialog_name])
            logger.debug(f"Dialog state cleared: {dialog_name}")
    
    # ==================== Create Dialog State ====================
    
    def get_create_step(self) -> int:
        """Get current step in create wizard"""
        return self.get_dialog_state(self.DIALOG_CREATE).get('step', 1)
    
    def set_create_step(self, step: int):
        """Set current step in create wizard"""
        self.update_dialog_state(self.DIALOG_CREATE, {'step': step})
    
    def get_create_header_data(self) -> Dict[str, Any]:
        """Get header data from create wizard step 1"""
        return self.get_dialog_state(self.DIALOG_CREATE).get('header_data', {})
    
    def set_create_header_data(self, data: Dict[str, Any]):
        """Set header data for create wizard"""
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
            action_type: Type of action (create, update, delete, etc.)
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