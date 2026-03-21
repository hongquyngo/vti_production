# pages/3_👤_User_Management.py
"""
👤 User Management Module

Admin-only access for managing system users.
Features:
- List users with search/filter
- Create new user
- Edit user details
- Soft delete user
- Toggle active status
- Reset password

Version: 1.0.0
"""

import streamlit as st
from datetime import datetime
import pandas as pd
import logging

# Shared utilities
from utils.auth import AuthManager
from utils.db import check_db_connection, get_db_engine, execute_query, execute_update
from sqlalchemy import text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title="User Management",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# AUTHENTICATION & AUTHORIZATION
# =============================================================================

auth = AuthManager()

# Check session
if not auth.check_session():
    st.warning("⚠️ Please login to access this page")
    st.info("Go to the main page to login")
    st.stop()

# Check admin role
if not auth.require_role(['admin']):
    st.stop()

# =============================================================================
# DATABASE CONNECTION CHECK
# =============================================================================

db_connected, db_error = check_db_connection()

if not db_connected:
    st.error(f"❌ Database connection failed: {db_error}")
    st.info("Please check your network connection or VPN")
    st.stop()

# =============================================================================
# CONSTANTS
# =============================================================================

AVAILABLE_ROLES = [
    'admin',
    'GM',
    'MD',
    'sales_manager',
    'sales',
    'supply_chain_manager',
    'supply_chain',
    'inbound_manager',
    'outbound_manager',
    'warehouse_manager',
    'buyer',
    'allocator',
    'fa_manager',
    'accountant',
    'project_manager',
    'production_manager',
    'qc_manager',
    'sw_engineer',
    'fae',
    'implement_engineer',
    'production_planner',
    'production_supervisor',
    'production_operator',
    'qc_inspector',
    'wms_supervisor',
    'wms_operator',
    'rcs_operator',
    'maintenance',
    'client_admin',
    'client_viewer',
    'customer',
    'vendor',
    'viewer',
]

ROLE_COLORS = {
    'admin':                '🔴',
    'GM':                   '🔴',
    'MD':                   '🔴',
    'sales_manager':        '🟠',
    'supply_chain_manager': '🟠',
    'inbound_manager':      '🟠',
    'outbound_manager':     '🟠',
    'warehouse_manager':    '🟠',
    'fa_manager':           '🟠',
    'project_manager':      '🟠',
    'production_manager':   '🟠',
    'qc_manager':           '🟠',
    'sales':                '🟡',
    'supply_chain':         '🟡',
    'buyer':                '🟡',
    'allocator':            '🟡',
    'accountant':           '🟡',
    'sw_engineer':          '🟡',
    'fae':                  '🟡',
    'implement_engineer':   '🟡',
    'production_planner':   '🟡',
    'production_supervisor':'🟢',
    'production_operator':  '🟢',
    'qc_inspector':         '🟢',
    'wms_supervisor':       '🟢',
    'wms_operator':         '🟢',
    'rcs_operator':         '🟢',
    'maintenance':          '🟢',
    'client_admin':         '🔵',
    'client_viewer':        '🔵',
    'customer':             '🔵',
    'vendor':               '🔵',
    'viewer':               '⚪',
}

# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

@st.cache_data(ttl=60)
def get_users_list(search_term: str = None, role_filter: str = None, status_filter: str = None) -> pd.DataFrame:
    """Get list of users with optional filters"""
    query = """
        SELECT 
            u.id,
            u.username,
            u.email,
            u.role,
            u.is_active,
            u.last_login,
            u.created_date,
            u.employee_id,
            CONCAT(e.first_name, ' ', e.last_name) as employee_name,
            e.keycloak_id,
            p.name as position_name,
            c.english_name as company_name
        FROM users u
        LEFT JOIN employees e ON u.employee_id = e.id
        LEFT JOIN positions p ON e.position_id = p.id
        LEFT JOIN companies c ON e.company_id = c.id
        WHERE u.delete_flag = 0
    """
    
    params = {}
    
    if search_term:
        query += """
            AND (u.username LIKE :search 
                 OR u.email LIKE :search 
                 OR e.first_name LIKE :search 
                 OR e.last_name LIKE :search)
        """
        params['search'] = f"%{search_term}%"
    
    if role_filter and role_filter != 'All':
        query += " AND u.role = :role"
        params['role'] = role_filter
    
    if status_filter == 'Active':
        query += " AND u.is_active = 1"
    elif status_filter == 'Inactive':
        query += " AND u.is_active = 0"
    
    query += " ORDER BY u.created_date DESC"
    
    engine = get_db_engine()
    return pd.read_sql(text(query), engine, params=params)


@st.cache_data(ttl=300)
def get_employees_dropdown() -> pd.DataFrame:
    """Get employees for dropdown selection"""
    query = """
        SELECT
            e.id,
            e.keycloak_id,
            e.first_name,
            e.last_name,
            CONCAT(e.first_name, ' ', e.last_name) AS full_name,
            e.email,
            e.phone,
            e.status,
            p.name   AS position,
            c.english_name AS company,
            d.name   AS department
        FROM employees e
        LEFT JOIN positions   p ON e.position_id   = p.id
        LEFT JOIN companies   c ON e.company_id    = c.id
        LEFT JOIN departments d ON e.department_id = d.id
        WHERE e.delete_flag = b'0'
          AND e.status = 'ACTIVE'
        ORDER BY e.first_name, e.last_name
    """
    engine = get_db_engine()
    return pd.read_sql(text(query), engine)


def get_user_by_id(user_id: int) -> dict:
    """Get single user details"""
    query = """
        SELECT 
            u.id,
            u.username,
            u.email,
            u.role,
            u.is_active,
            u.employee_id,
            u.last_login,
            u.created_date,
            u.created_by,
            u.modified_date,
            u.modified_by
        FROM users u
        WHERE u.id = :user_id AND u.delete_flag = 0
    """
    results = execute_query(query, {'user_id': user_id})
    return results[0] if results else None


def check_username_exists(username: str, exclude_id: int = None) -> bool:
    """Check if username already exists"""
    query = "SELECT COUNT(*) as cnt FROM users WHERE username = :username AND delete_flag = 0"
    params = {'username': username}
    
    if exclude_id:
        query += " AND id != :exclude_id"
        params['exclude_id'] = exclude_id
    
    result = execute_query(query, params)
    return result[0]['cnt'] > 0 if result else False


def check_email_exists(email: str, exclude_id: int = None) -> bool:
    """Check if email already exists"""
    query = "SELECT COUNT(*) as cnt FROM users WHERE email = :email AND delete_flag = 0"
    params = {'email': email}
    
    if exclude_id:
        query += " AND id != :exclude_id"
        params['exclude_id'] = exclude_id
    
    result = execute_query(query, params)
    return result[0]['cnt'] > 0 if result else False


def create_user(username: str, password: str, email: str, role: str, 
                employee_id: int = None, is_active: bool = True) -> tuple:
    """Create new user"""
    try:
        # Check username
        if check_username_exists(username):
            return False, "Username already exists"
        
        # Check email
        if check_email_exists(email):
            return False, "Email already exists"
        
        # Hash password
        pwd_hash, salt = auth.hash_password(password)
        
        query = """
            INSERT INTO users (username, password_hash, password_salt, email, role, 
                              employee_id, is_active, created_date, created_by)
            VALUES (:username, :pwd_hash, :salt, :email, :role, 
                    :employee_id, :is_active, NOW(), :created_by)
        """
        
        params = {
            'username': username,
            'pwd_hash': pwd_hash,
            'salt': salt,
            'email': email,
            'role': role,
            'employee_id': employee_id if employee_id else None,
            'is_active': 1 if is_active else 0,
            'created_by': st.session_state.get('username', 'system')
        }
        
        rows = execute_update(query, params)
        
        if rows > 0:
            logger.info(f"User created: {username} by {params['created_by']}")
            return True, "User created successfully"
        else:
            return False, "Failed to create user"
            
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return False, str(e)


def update_user(user_id: int, email: str, role: str, employee_id: int = None, is_active: bool = None) -> tuple:
    """Update user details"""
    try:
        # Check email
        if check_email_exists(email, exclude_id=user_id):
            return False, "Email already exists"
        
        set_clause = """
                email = :email,
                role = :role,
                employee_id = :employee_id,
                modified_date = NOW(),
                modified_by = :modified_by
        """
        params = {
            'user_id': user_id,
            'email': email,
            'role': role,
            'employee_id': employee_id if employee_id else None,
            'modified_by': st.session_state.get('username', 'system')
        }

        if is_active is not None:
            # Prevent self-deactivation
            if not is_active and user_id == st.session_state.get('user_id'):
                return False, "Cannot deactivate your own account"
            set_clause += ", is_active = :is_active"
            params['is_active'] = 1 if is_active else 0

        query = f"UPDATE users SET {set_clause} WHERE id = :user_id AND delete_flag = 0"
        
        rows = execute_update(query, params)
        
        if rows > 0:
            logger.info(f"User {user_id} updated by {params['modified_by']}")
            return True, "User updated successfully"
        else:
            return False, "User not found or no changes made"
            
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return False, str(e)


def toggle_user_status(user_id: int) -> tuple:
    """Toggle user active status"""
    try:
        if user_id == st.session_state.get('user_id'):
            return False, "Cannot deactivate your own account"

        query = """
            UPDATE users 
            SET is_active = NOT is_active,
                modified_date = NOW(),
                modified_by = :modified_by
            WHERE id = :user_id AND delete_flag = 0
        """
        
        rows = execute_update(query, {
            'user_id': user_id,
            'modified_by': st.session_state.get('username', 'system')
        })
        
        if rows > 0:
            return True, "Status updated"
        return False, "User not found"
        
    except Exception as e:
        logger.error(f"Error toggling status: {e}")
        return False, str(e)


def soft_delete_user(user_id: int) -> tuple:
    """Soft delete user"""
    try:
        # Prevent self-deletion
        if user_id == st.session_state.get('user_id'):
            return False, "Cannot delete your own account"
        
        query = """
            UPDATE users 
            SET delete_flag = 1,
                is_active = 0,
                modified_date = NOW(),
                modified_by = :modified_by
            WHERE id = :user_id
        """
        
        rows = execute_update(query, {
            'user_id': user_id,
            'modified_by': st.session_state.get('username', 'system')
        })
        
        if rows > 0:
            logger.info(f"User {user_id} deleted by {st.session_state.get('username')}")
            return True, "User deleted successfully"
        return False, "User not found"
        
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return False, str(e)


def reset_password(user_id: int, new_password: str) -> tuple:
    """Reset user password"""
    try:
        pwd_hash, salt = auth.hash_password(new_password)
        
        query = """
            UPDATE users 
            SET password_hash = :pwd_hash,
                password_salt = :salt,
                modified_date = NOW(),
                modified_by = :modified_by
            WHERE id = :user_id AND delete_flag = 0
        """
        
        rows = execute_update(query, {
            'user_id': user_id,
            'pwd_hash': pwd_hash,
            'salt': salt,
            'modified_by': st.session_state.get('username', 'system')
        })
        
        if rows > 0:
            logger.info(f"Password reset for user {user_id}")
            return True, "Password reset successfully"
        return False, "User not found"
        
    except Exception as e:
        logger.error(f"Error resetting password: {e}")
        return False, str(e)


# =============================================================================
# UI HELPER FUNCTIONS
# =============================================================================

import re as _re

def is_valid_email(email: str) -> bool:
    """Basic email format validation"""
    return bool(_re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email.strip()))


def clear_form_state():
    """Clear form-related session state"""
    keys_to_clear = ['edit_user_id', 'show_create_form', 'show_edit_form', 
                     'delete_confirm', 'reset_pwd_user_id']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]


def format_datetime(dt):
    """Format datetime for display"""
    if dt is None:
        return "Never"
    try:
        if pd.isna(dt):
            return "Never"
    except (TypeError, ValueError):
        pass
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)


# =============================================================================
# PAGE HEADER
# =============================================================================

st.title("👤 User Management")
st.caption(f"Logged in as: **{auth.get_user_display_name()}** (Admin)")

# =============================================================================
# SIDEBAR FILTERS
# =============================================================================

with st.sidebar:
    st.header("🔍 Filters")
    
    search_term = st.text_input("Search", placeholder="Username, email, name...")
    role_filter = st.selectbox("Role", ['All'] + AVAILABLE_ROLES)
    status_filter = st.selectbox("Status", ['All', 'Active', 'Inactive'])
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        get_users_list.clear()
        get_employees_dropdown.clear()
        st.rerun()

# =============================================================================
# ACTION BUTTONS
# =============================================================================

col_actions = st.columns([1, 1, 4])

with col_actions[0]:
    if st.button("➕ Create User", type="primary", use_container_width=True):
        st.session_state['show_create_form'] = True
        st.session_state['show_edit_form'] = False

with col_actions[1]:
    _export_df = get_users_list(search_term, role_filter, status_filter)
    if not _export_df.empty:
        st.download_button(
            label="📥 Export CSV",
            data=_export_df.to_csv(index=False),
            file_name=f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.button("📥 Export CSV", use_container_width=True, disabled=True)

# =============================================================================
# CREATE USER FORM
# =============================================================================

# Session state defaults for create form fields
for _k, _v in [
    ('cu_username', ''), ('cu_email', ''), ('cu_employee_id', None), ('cu_role', 'viewer')
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _on_employee_change():
    """Auto-populate username & email when employee is selected."""
    employees_df = get_employees_dropdown()
    sel = st.session_state.get('cu_employee_select', '-- No Employee Link --')
    if sel == '-- No Employee Link --':
        st.session_state['cu_employee_id'] = None
        return
    row = employees_df[employees_df['full_name'] == sel]
    if row.empty:
        return
    row = row.iloc[0]
    email = str(row.get('email', '') or '')
    st.session_state['cu_email']        = email
    st.session_state['cu_employee_id']  = int(row['id'])
    # Default username = part before @
    if email and '@' in email:
        st.session_state['cu_username'] = email.split('@')[0]


if st.session_state.get('show_create_form', False):
    st.divider()
    st.subheader("➕ Create New User")

    employees_df = get_employees_dropdown()
    emp_options  = ['-- No Employee Link --'] + employees_df['full_name'].tolist()

    # ── Employee picker (OUTSIDE form so on_change fires immediately) ──────
    st.selectbox(
        "🔗 Link to Employee",
        emp_options,
        key='cu_employee_select',
        on_change=_on_employee_change,
        help="Select an employee to auto-fill username and email"
    )

    if st.session_state.get('cu_employee_id'):
        emp_row = employees_df[employees_df['id'] == st.session_state['cu_employee_id']]
        if not emp_row.empty:
            r = emp_row.iloc[0]
            parts = [r['full_name']]
            if r.get('position'):  parts.append(r['position'])
            if r.get('department'): parts.append(r['department'])
            if r.get('company'):   parts.append(r['company'])
            st.caption("👤 " + " · ".join(str(p) for p in parts if p and str(p) != 'nan'))

    st.markdown("")  # spacing

    with st.form("create_user_form", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            new_username = st.text_input(
                "Username *", max_chars=50,
                value=st.session_state.get('cu_username', ''),
                placeholder="e.g. anne.ninh"
            )
            new_password         = st.text_input("Password *", type="password")
            new_password_confirm = st.text_input("Confirm Password *", type="password")

        with col2:
            new_email = st.text_input(
                "Email *", max_chars=255,
                value=st.session_state.get('cu_email', ''),
                placeholder="e.g. anne.ninh@rozitek.com"
            )
            default_role_idx = AVAILABLE_ROLES.index(
                st.session_state.get('cu_role', 'viewer')
            ) if st.session_state.get('cu_role', 'viewer') in AVAILABLE_ROLES else AVAILABLE_ROLES.index('viewer')
            new_role = st.selectbox("Role *", AVAILABLE_ROLES, index=default_role_idx)

        new_is_active = st.checkbox("Active", value=True)
        
        col_submit, col_cancel = st.columns([1, 1])
        
        with col_submit:
            submitted = st.form_submit_button("✅ Create User", type="primary", use_container_width=True)
        
        with col_cancel:
            cancelled = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            # Validation
            errors = []
            
            if not new_username or len(new_username) < 3:
                errors.append("Username must be at least 3 characters")
            
            if not new_password or len(new_password) < 8:
                errors.append("Password must be at least 8 characters")
            
            if new_password != new_password_confirm:
                errors.append("Passwords do not match")
            
            if not new_email or not is_valid_email(new_email):
                errors.append("Invalid email address")
            
            if errors:
                for err in errors:
                    st.error(f"❌ {err}")
            else:
                # Get employee_id from session state (resolved by on_change)
                emp_id = st.session_state.get('cu_employee_id')
                
                success, message = create_user(
                    username=new_username.strip(),
                    password=new_password,
                    email=new_email.strip(),
                    role=new_role,
                    employee_id=emp_id,
                    is_active=new_is_active
                )
                
                if success:
                    st.success(f"✅ {message}")
                    get_users_list.clear()
                    # Clear create-form state
                    for _k in ['cu_username', 'cu_email', 'cu_employee_id', 'cu_role', 'cu_employee_select']:
                        st.session_state.pop(_k, None)
                    st.session_state['show_create_form'] = False
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        
        if cancelled:
            for _k in ['cu_username', 'cu_email', 'cu_employee_id', 'cu_role', 'cu_employee_select']:
                st.session_state.pop(_k, None)
            st.session_state['show_create_form'] = False
            st.rerun()

# =============================================================================
# EDIT USER FORM
# =============================================================================

if st.session_state.get('show_edit_form', False) and st.session_state.get('edit_user_id'):
    st.divider()
    st.subheader("✏️ Edit User")
    
    edit_user = get_user_by_id(st.session_state['edit_user_id'])
    
    if edit_user:
        employees_df = get_employees_dropdown()
        
        with st.form("edit_user_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.text_input("Username", value=edit_user['username'], disabled=True)
                edit_email = st.text_input("Email *", value=edit_user['email'], max_chars=255)
                edit_is_active = st.checkbox("Active", value=bool(edit_user['is_active']))
            
            with col2:
                current_role_idx = AVAILABLE_ROLES.index(edit_user['role']) if edit_user['role'] in AVAILABLE_ROLES else 0
                edit_role = st.selectbox("Role *", AVAILABLE_ROLES, index=current_role_idx)
                
                # Employee dropdown
                emp_options = ['-- No Employee Link --'] + employees_df['full_name'].tolist()
                current_emp_idx = 0
                if edit_user['employee_id']:
                    emp_row = employees_df[employees_df['id'] == edit_user['employee_id']]
                    if not emp_row.empty:
                        current_emp_name = emp_row.iloc[0]['full_name']
                        if current_emp_name in emp_options:
                            current_emp_idx = emp_options.index(current_emp_name)
                
                edit_employee = st.selectbox("Link to Employee", emp_options, index=current_emp_idx)
            
            # Meta info
            st.caption(f"Created: {format_datetime(edit_user['created_date'])} by {edit_user['created_by'] or 'N/A'}")
            st.caption(f"Last Modified: {format_datetime(edit_user['modified_date'])} by {edit_user['modified_by'] or 'N/A'}")
            
            col_submit, col_cancel = st.columns([1, 1])
            
            with col_submit:
                submitted = st.form_submit_button("✅ Save Changes", type="primary", use_container_width=True)
            
            with col_cancel:
                cancelled = st.form_submit_button("❌ Cancel", use_container_width=True)
            
            if submitted:
                if not edit_email or not is_valid_email(edit_email):
                    st.error("❌ Invalid email address")
                else:
                    # Get employee_id if selected
                    emp_id = None
                    if edit_employee != '-- No Employee Link --':
                        emp_row = employees_df[employees_df['full_name'] == edit_employee]
                        if not emp_row.empty:
                            emp_id = int(emp_row.iloc[0]['id'])
                    
                    success, message = update_user(
                        user_id=st.session_state['edit_user_id'],
                        email=edit_email,
                        role=edit_role,
                        employee_id=emp_id,
                        is_active=edit_is_active
                    )
                    
                    if success:
                        st.success(f"✅ {message}")
                        get_users_list.clear()
                        st.session_state['show_edit_form'] = False
                        st.session_state['edit_user_id'] = None
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
            
            if cancelled:
                st.session_state['show_edit_form'] = False
                st.session_state['edit_user_id'] = None
                st.rerun()
    else:
        st.error("User not found")
        st.session_state['show_edit_form'] = False

# =============================================================================
# RESET PASSWORD DIALOG
# =============================================================================

if st.session_state.get('reset_pwd_user_id'):
    st.divider()
    st.subheader("🔐 Reset Password")
    
    reset_user = get_user_by_id(st.session_state['reset_pwd_user_id'])
    
    if reset_user:
        st.info(f"Resetting password for: **{reset_user['username']}**")
        
        with st.form("reset_pwd_form"):
            new_pwd = st.text_input("New Password *", type="password")
            confirm_pwd = st.text_input("Confirm Password *", type="password")
            
            col_submit, col_cancel = st.columns([1, 1])
            
            with col_submit:
                submitted = st.form_submit_button("✅ Reset Password", type="primary", use_container_width=True)
            
            with col_cancel:
                cancelled = st.form_submit_button("❌ Cancel", use_container_width=True)
            
            if submitted:
                if len(new_pwd) < 8:
                    st.error("❌ Password must be at least 8 characters")
                elif new_pwd != confirm_pwd:
                    st.error("❌ Passwords do not match")
                else:
                    success, message = reset_password(st.session_state['reset_pwd_user_id'], new_pwd)
                    
                    if success:
                        st.success(f"✅ {message}")
                        st.session_state['reset_pwd_user_id'] = None
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
            
            if cancelled:
                st.session_state['reset_pwd_user_id'] = None
                st.rerun()

# =============================================================================
# USERS TABLE
# =============================================================================

st.divider()
st.subheader("📋 Users List")

users_df = get_users_list(search_term, role_filter, status_filter)

if users_df.empty:
    st.info("No users found matching the filters")
else:
    st.caption(f"Showing **{len(users_df)}** users")
    
    # Display table with actions
    for idx, row in users_df.iterrows():
        with st.container():
            cols = st.columns([0.5, 2, 3, 1.5, 1, 1.5, 2])
            
            # Status indicator
            with cols[0]:
                if row['is_active']:
                    st.markdown("🟢")
                else:
                    st.markdown("🔴")
            
            # Username
            with cols[1]:
                st.markdown(f"**{row['username']}**")
                if row['employee_name'] and pd.notna(row['employee_name']):
                    st.caption(row['employee_name'])
            
            # Email
            with cols[2]:
                st.text(row['email'])
            
            # Role
            with cols[3]:
                role_icon = ROLE_COLORS.get(row['role'], '⚪')
                st.text(f"{role_icon} {row['role']}")
            
            # Last Login
            with cols[4]:
                st.caption(format_datetime(row['last_login']))
            
            # Company
            with cols[5]:
                if row['company_name'] and pd.notna(row['company_name']):
                    st.caption(row['company_name'][:20])
            
            # Actions
            with cols[6]:
                action_cols = st.columns(4)
                
                with action_cols[0]:
                    if st.button("✏️", key=f"edit_{row['id']}", help="Edit user"):
                        st.session_state['edit_user_id'] = row['id']
                        st.session_state['show_edit_form'] = True
                        st.session_state['show_create_form'] = False
                        st.rerun()
                
                with action_cols[1]:
                    if st.button("🔐", key=f"pwd_{row['id']}", help="Reset password"):
                        st.session_state['reset_pwd_user_id'] = row['id']
                        st.rerun()
                
                with action_cols[2]:
                    # Toggle status
                    status_icon = "🚫" if row['is_active'] else "✅"
                    status_help = "Deactivate" if row['is_active'] else "Activate"
                    if st.button(status_icon, key=f"status_{row['id']}", help=status_help):
                        success, msg = toggle_user_status(row['id'])
                        if success:
                            get_users_list.clear()
                            st.rerun()
                        else:
                            st.error(msg)
                
                with action_cols[3]:
                    # Delete (not self)
                    if row['id'] != st.session_state.get('user_id'):
                        if st.button("🗑️", key=f"del_{row['id']}", help="Delete user"):
                            st.session_state['delete_confirm'] = row['id']
            
            st.divider()

# =============================================================================
# DELETE CONFIRMATION DIALOG
# =============================================================================

if st.session_state.get('delete_confirm'):
    del_user = get_user_by_id(st.session_state['delete_confirm'])
    
    if del_user:
        st.warning(f"⚠️ Are you sure you want to delete user **{del_user['username']}**?")
        
        col_yes, col_no = st.columns([1, 1])
        
        with col_yes:
            if st.button("✅ Yes, Delete", type="primary", use_container_width=True):
                success, msg = soft_delete_user(st.session_state['delete_confirm'])
                if success:
                    st.success(msg)
                    get_users_list.clear()
                    st.session_state['delete_confirm'] = None
                    st.rerun()
                else:
                    st.error(msg)
        
        with col_no:
            if st.button("❌ Cancel", use_container_width=True):
                st.session_state['delete_confirm'] = None
                st.rerun()

# =============================================================================
# STATISTICS
# =============================================================================

st.divider()
st.subheader("📊 Statistics")

all_users_df = get_users_list()

if not all_users_df.empty:
    stat_cols = st.columns(4)
    
    with stat_cols[0]:
        st.metric("Total Users", len(all_users_df))
    
    with stat_cols[1]:
        active_count = all_users_df['is_active'].sum()
        st.metric("Active Users", int(active_count))
    
    with stat_cols[2]:
        inactive_count = len(all_users_df) - active_count
        st.metric("Inactive Users", int(inactive_count))
    
    with stat_cols[3]:
        # Users logged in last 7 days
        recent_logins = all_users_df[
            pd.to_datetime(all_users_df['last_login'], errors='coerce') > 
            (datetime.now() - pd.Timedelta(days=7))
        ]
        st.metric("Active Last 7 Days", len(recent_logins))
    
    # Role distribution
    st.markdown("#### Role Distribution")
    role_counts = all_users_df['role'].value_counts().reset_index()
    role_counts.columns = ['Role', 'Count']
    
    col_chart, col_table = st.columns([2, 1])
    
    with col_chart:
        st.bar_chart(role_counts.set_index('Role'))
    
    with col_table:
        st.dataframe(role_counts, use_container_width=True, hide_index=True)

# =============================================================================
# FOOTER
# =============================================================================

st.divider()
st.caption(
    f"User Management Module v1.0.0 | "
    f"Admin: {st.session_state.get('username', 'Unknown')} | "
    f"Session: {format_datetime(st.session_state.get('login_time'))}"
)