# pages/3_👤_User_Management.py
"""
👤 User Management Module

Admin-only access for managing system users.
Features:
- List users with search/filter
- Create new user (dialog)
- Edit user details (dialog)
- Soft delete user (dialog)
- Toggle active status (fragment — no full rerun)
- Reset password (dialog)
- Email notifications: welcome, password reset, status change, account deleted

Version: 2.2.0 — Dialog + Fragment + Full email notifications
"""

import streamlit as st
from datetime import datetime
import pandas as pd
import logging
import re as _re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

if not auth.check_session():
    st.warning("⚠️ Please login to access this page")
    st.info("Go to the main page to login")
    st.stop()

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

ROLE_GROUPS = {
    '🔴 Executive': ['admin', 'GM', 'MD'],
    '🟠 Sales': ['sales_manager', 'sales'],
    '🟠 Supply Chain': ['supply_chain_manager', 'supply_chain', 'inbound_manager',
                        'outbound_manager', 'warehouse_manager', 'buyer', 'allocator'],
    '🟠 Finance': ['fa_manager', 'accountant'],
    '🟠 Project': ['project_manager', 'product_manager'],
    '🟢 Production': ['production_manager', 'production_planner',
                      'production_supervisor', 'production_operator'],
    '🟢 Quality': ['qc_manager', 'qc_inspector'],
    '🟣 R&D Software': ['rd_manager', 'sw_engineer', 'sw_lead', 'sw_developer', 'sw_tester'],
    '🟣 R&D Hardware': ['hw_lead', 'hw_engineer', 'fw_engineer', 'pcb_designer'],
    '🟣 R&D Engineering': ['system_architect', 'me_engineer', 'ee_engineer'],
    '🟡 Implementation': ['fae', 'implement_engineer'],
    '🟢 WMS & RCS': ['wms_supervisor', 'wms_operator', 'rcs_operator', 'maintenance'],
    '🔵 External': ['client_admin', 'client_viewer', 'customer', 'vendor'],
    '⚪ General': ['viewer'],
}

AVAILABLE_ROLES = [role for roles in ROLE_GROUPS.values() for role in roles]

ROLE_TO_GROUP = {role: group for group, roles in ROLE_GROUPS.items() for role in roles}

ROLE_COLORS = {
    'admin': '🔴', 'GM': '🔴', 'MD': '🔴',
    'sales_manager': '🟠', 'supply_chain_manager': '🟠', 'inbound_manager': '🟠',
    'outbound_manager': '🟠', 'warehouse_manager': '🟠', 'fa_manager': '🟠',
    'project_manager': '🟠', 'product_manager': '🟠', 'production_manager': '🟠',
    'qc_manager': '🟠', 'rd_manager': '🟠',
    'sales': '🟡', 'supply_chain': '🟡', 'buyer': '🟡', 'allocator': '🟡',
    'accountant': '🟡', 'production_planner': '🟡',
    'system_architect': '🟣', 'sw_engineer': '🟣', 'sw_lead': '🟣',
    'sw_developer': '🟣', 'sw_tester': '🟣', 'hw_lead': '🟣',
    'hw_engineer': '🟣', 'fw_engineer': '🟣', 'pcb_designer': '🟣',
    'me_engineer': '🟣', 'ee_engineer': '🟣',
    'fae': '🟡', 'implement_engineer': '🟡',
    'production_supervisor': '🟢', 'production_operator': '🟢',
    'qc_inspector': '🟢', 'wms_supervisor': '🟢', 'wms_operator': '🟢',
    'rcs_operator': '🟢', 'maintenance': '🟢',
    'client_admin': '🔵', 'client_viewer': '🔵', 'customer': '🔵', 'vendor': '🔵',
    'viewer': '⚪',
}

# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

@st.cache_data(ttl=60)
def get_users_list(search_term: str = None, role_filter: str = None,
                   status_filter: str = None) -> pd.DataFrame:
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
            u.id, u.username, u.email, u.role, u.is_active,
            u.employee_id, u.last_login, u.created_date,
            u.created_by, u.modified_date, u.modified_by
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
        if check_username_exists(username):
            return False, "Username already exists"
        if check_email_exists(email):
            return False, "Email already exists"

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
        return False, "Failed to create user"

    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return False, str(e)


def update_user(user_id: int, email: str, role: str,
                employee_id: int = None, is_active: bool = None) -> tuple:
    """Update user details"""
    try:
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
            if not is_active and user_id == st.session_state.get('user_id'):
                return False, "Cannot deactivate your own account"
            set_clause += ", is_active = :is_active"
            params['is_active'] = 1 if is_active else 0

        query = f"UPDATE users SET {set_clause} WHERE id = :user_id AND delete_flag = 0"
        rows = execute_update(query, params)

        if rows > 0:
            logger.info(f"User {user_id} updated by {params['modified_by']}")
            return True, "User updated successfully"
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
        if user_id == st.session_state.get('user_id'):
            return False, "Cannot delete your own account"

        query = """
            UPDATE users 
            SET delete_flag = 1, is_active = 0,
                modified_date = NOW(), modified_by = :modified_by
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
            SET password_hash = :pwd_hash, password_salt = :salt,
                modified_date = NOW(), modified_by = :modified_by
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

def is_valid_email(email: str) -> bool:
    return bool(_re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email.strip()))


def format_datetime(dt):
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


def _cleanup_keys(prefix: str):
    """Remove all session_state keys starting with prefix"""
    keys = [k for k in st.session_state if k.startswith(prefix)]
    for k in keys:
        del st.session_state[k]


# =============================================================================
# EMAIL NOTIFICATIONS — non-blocking, failures logged but never crash app
# =============================================================================

def _get_email_config() -> dict:
    """Load outbound email config from utils.config."""
    try:
        from utils.config import config
        if not config.is_feature_enabled("EMAIL_NOTIFICATIONS"):
            logger.info("Email notifications disabled by feature flag.")
            return {}
        return config.get_email_config("outbound")
    except Exception as e:
        logger.warning(f"Could not load email config: {e}")
        return {}


def _get_app_url() -> str:
    """Get app base URL for deep links."""
    try:
        from utils.config import config
        return (config.get_app_setting('APP_BASE_URL', '') or '').rstrip('/')
    except Exception:
        return ''


def _email_template(title: str, body_html: str, app_url: str = '') -> str:
    """Wrap body in a clean HTML email template (shared by all notifications)."""
    action_btn = ''
    if app_url:
        action_btn = f'''
        <div style="text-align:center;margin:24px 0;">
            <a href="{app_url}"
               style="background:#2563eb;color:#fff;padding:12px 28px;
                      border-radius:6px;text-decoration:none;font-weight:600;
                      display:inline-block;">
                Login to ERP
            </a>
        </div>'''

    return f'''
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;
                background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <div style="background:#1e3a5f;padding:16px 24px;">
            <h2 style="color:#fff;margin:0;font-size:18px;">{title}</h2>
        </div>
        <div style="padding:24px;">
            {body_html}
            {action_btn}
        </div>
        <div style="background:#f9fafb;padding:12px 24px;border-top:1px solid #e5e7eb;
                    font-size:12px;color:#6b7280;">
            Rozitek ERP System<br>
            This is an automated notification. Please do not reply to this email.
        </div>
    </div>'''


def _info_row(label: str, value: str) -> str:
    return f'''<tr>
        <td style="padding:4px 0;color:#6b7280;width:140px;">{label}</td>
        <td style="padding:4px 0;font-weight:500;">{value}</td>
    </tr>'''


def _send_user_email(to_email: str, subject: str,
                     html_body: str) -> tuple[bool, str]:
    """
    Core send function. Non-blocking.
    Returns (True, 'sent to ...') or (False, reason).
    """
    cfg = _get_email_config()
    if not cfg.get('sender') or not cfg.get('password'):
        return False, "Email not configured — notification skipped"

    if not to_email or '@' not in to_email:
        return False, "No valid recipient email"

    sender = cfg['sender']
    smtp_pwd = cfg['password']
    host = cfg.get('host', 'smtp.gmail.com')
    port = cfg.get('port', 587)

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Rozitek ERP <{sender}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, smtp_pwd)
            server.sendmail(sender, [to_email], msg.as_string())

        logger.info(f"📧 Email sent: '{subject}' → {to_email}")
        return True, f"Email sent to {to_email}"

    except smtplib.SMTPAuthenticationError:
        logger.error("📧 SMTP auth failed — check email credentials in .env")
        return False, "SMTP authentication failed"
    except smtplib.SMTPException as e:
        logger.error(f"📧 SMTP error: {e}")
        return False, f"SMTP error: {e}"
    except Exception as e:
        logger.error(f"📧 Email send failed: {e}")
        return False, str(e)


# ── 1. Welcome email (after user creation) ──────────────────────────

def send_welcome_email(email: str, username: str, password: str,
                       role: str) -> tuple[bool, str]:
    role_group = ROLE_TO_GROUP.get(role, '⚪ General')
    role_icon = ROLE_COLORS.get(role, '⚪')

    body = f'''
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your account has been created. Here are your login credentials:</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Username', f'<strong>{username}</strong>')}
        {_info_row('Password',
            f'<code style="background:#f3f4f6;padding:2px 8px;border-radius:4px;'
            f'font-family:monospace;font-size:14px;">{password}</code>')}
        {_info_row('Role', f'{role_icon} {role} <span style="color:#9ca3af;">({role_group})</span>')}
    </table>

    <div style="background:#fffbeb;border-left:3px solid #f59e0b;padding:12px;margin:16px 0;font-size:13px;">
        <strong>⚠️ Important:</strong> Please change your password after your first login.
    </div>'''

    html = _email_template('👤 Welcome to Rozitek ERP', body, _get_app_url())
    return _send_user_email(
        email,
        f"[Rozitek ERP] Your account has been created — {username}",
        html,
    )


# ── 2. Password reset email ─────────────────────────────────────────

def send_reset_password_email(email: str, username: str,
                              new_password: str) -> tuple[bool, str]:
    admin_name = st.session_state.get('username', 'System')

    body = f'''
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your password has been reset by an administrator (<strong>{admin_name}</strong>).</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Username', f'<strong>{username}</strong>')}
        {_info_row('New Password',
            f'<code style="background:#f3f4f6;padding:2px 8px;border-radius:4px;'
            f'font-family:monospace;font-size:14px;">{new_password}</code>')}
    </table>

    <div style="background:#fef2f2;border-left:3px solid #ef4444;padding:12px;margin:16px 0;font-size:13px;">
        <strong>🔐 Security:</strong> Please change your password immediately after logging in.
    </div>'''

    html = _email_template('🔐 Password Reset', body, _get_app_url())
    return _send_user_email(
        email,
        f"[Rozitek ERP] Your password has been reset — {username}",
        html,
    )


# ── 3. Account status change email (activate / deactivate) ──────────

def send_status_change_email(email: str, username: str,
                             is_now_active: bool) -> tuple[bool, str]:
    admin_name = st.session_state.get('username', 'System')

    if is_now_active:
        status_badge = '<span style="color:#16a34a;font-weight:700;">✅ ACTIVATED</span>'
        message = 'Your account has been re-activated. You can now log in to the ERP system.'
        note = ''
    else:
        status_badge = '<span style="color:#dc2626;font-weight:700;">🚫 DEACTIVATED</span>'
        message = 'Your account has been deactivated. You will no longer be able to log in.'
        note = '''
        <div style="background:#fef2f2;border-left:3px solid #ef4444;padding:12px;margin:16px 0;font-size:13px;">
            If you believe this is a mistake, please contact your administrator.
        </div>'''

    body = f'''
    <p>Hi <strong>{username}</strong>,</p>
    <p>{message}</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Account', f'<strong>{username}</strong>')}
        {_info_row('Status', status_badge)}
        {_info_row('Changed by', admin_name)}
    </table>
    {note}'''

    action = "activated" if is_now_active else "deactivated"
    html = _email_template(f'👤 Account {action.title()}', body,
                           _get_app_url() if is_now_active else '')
    return _send_user_email(
        email,
        f"[Rozitek ERP] Your account has been {action} — {username}",
        html,
    )


# ── 4. Account deleted email ────────────────────────────────────────

def send_account_deleted_email(email: str, username: str) -> tuple[bool, str]:
    admin_name = st.session_state.get('username', 'System')

    body = f'''
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your account has been removed from the ERP system.</p>

    <table style="width:100%;margin:16px 0;">
        {_info_row('Account', f'<strong>{username}</strong>')}
        {_info_row('Status', '<span style="color:#6b7280;font-weight:700;">⬛ DELETED</span>')}
        {_info_row('Removed by', admin_name)}
    </table>

    <div style="background:#f3f4f6;border-left:3px solid #9ca3af;padding:12px;margin:16px 0;font-size:13px;">
        If you believe this is a mistake, please contact your administrator.
    </div>'''

    html = _email_template('👤 Account Removed', body)
    return _send_user_email(
        email,
        f"[Rozitek ERP] Your account has been removed — {username}",
        html,
    )


def role_group_selector(key_prefix: str, default_role: str = 'viewer') -> str:
    """
    Two-step role selector: department/group → role.
    Works inside dialogs — cascade reruns only the dialog, not the page.
    """
    default_group = ROLE_TO_GROUP.get(default_role, '⚪ General')
    group_list = list(ROLE_GROUPS.keys())
    default_group_idx = group_list.index(default_group) if default_group in group_list else 0

    gcol, rcol = st.columns(2)

    with gcol:
        selected_group = st.selectbox(
            "Department *",
            group_list,
            index=default_group_idx,
            key=f"{key_prefix}_role_group",
        )

    roles_in_group = ROLE_GROUPS[selected_group]
    default_role_idx = (roles_in_group.index(default_role)
                        if default_role in roles_in_group else 0)

    with rcol:
        selected_role = st.selectbox(
            "Role *",
            roles_in_group,
            index=default_role_idx,
            key=f"{key_prefix}_role_select",
        )

    return selected_role


def _employee_info_caption(employees_df: pd.DataFrame, emp_id: int):
    """Show employee info caption"""
    emp_row = employees_df[employees_df['id'] == emp_id]
    if emp_row.empty:
        return
    r = emp_row.iloc[0]
    parts = [r['full_name']]
    if r.get('position'):  parts.append(r['position'])
    if r.get('department'): parts.append(r['department'])
    if r.get('company'):   parts.append(r['company'])
    st.caption("👤 " + " · ".join(str(p) for p in parts if p and str(p) != 'nan'))


# =============================================================================
# DIALOGS — interactions rerun ONLY the dialog, not the full page
# =============================================================================

# ─────────────────────────────────────────────────
# CREATE USER DIALOG
# ─────────────────────────────────────────────────
@st.dialog("➕ Create New User", width="large")
def open_create_dialog():
    employees_df = get_employees_dropdown()
    emp_options = ['-- No Employee Link --'] + employees_df['full_name'].tolist()

    # ── Init dialog state (once) ──
    if '_cu_emp_id' not in st.session_state:
        st.session_state['_cu_emp_id'] = None

    # ── Employee picker (on_change reruns dialog only) ──
    def _on_emp_change():
        sel = st.session_state.get('_cu_emp_sel')
        if not sel or sel == '-- No Employee Link --':
            st.session_state['_cu_emp_id'] = None
            st.session_state['_cu_uname'] = ''
            st.session_state['_cu_email'] = ''
            return
        row = employees_df[employees_df['full_name'] == sel]
        if row.empty:
            return
        r = row.iloc[0]
        email = str(r.get('email', '') or '')
        st.session_state['_cu_emp_id'] = int(r['id'])
        st.session_state['_cu_email'] = email
        st.session_state['_cu_uname'] = email.split('@')[0] if '@' in email else ''

    st.selectbox(
        "🔗 Link to Employee",
        emp_options,
        key='_cu_emp_sel',
        on_change=_on_emp_change,
        help="Select an employee to auto-fill username and email"
    )

    # Show employee info
    if st.session_state.get('_cu_emp_id'):
        _employee_info_caption(employees_df, st.session_state['_cu_emp_id'])

    # ── Role cascade (reruns dialog only — no full-page rerun!) ──
    new_role = role_group_selector('_cu', default_role='viewer')

    st.divider()

    # ── Form for text inputs (batched submit, no rerun per keystroke) ──
    with st.form("dlg_create_form", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            new_username = st.text_input(
                "Username *", max_chars=50, key='_cu_uname',
                placeholder="e.g. anne.ninh"
            )
            new_password = st.text_input("Password *", type="password")
            confirm_password = st.text_input("Confirm Password *", type="password")

        with col2:
            new_email = st.text_input(
                "Email *", max_chars=255, key='_cu_email',
                placeholder="e.g. anne.ninh@rozitek.com"
            )
            new_is_active = st.checkbox("Active", value=True)
            st.info(f"🏷️ Selected Role: **{new_role}**")

        col_s, col_c = st.columns(2)
        with col_s:
            submitted = st.form_submit_button(
                "✅ Create User", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button(
                "❌ Cancel", use_container_width=True)

        if submitted:
            errors = []
            if not new_username or len(new_username.strip()) < 3:
                errors.append("Username must be at least 3 characters")
            if not new_password or len(new_password) < 8:
                errors.append("Password must be at least 8 characters")
            if new_password != confirm_password:
                errors.append("Passwords do not match")
            if not new_email or not is_valid_email(new_email):
                errors.append("Invalid email address")

            if errors:
                for err in errors:
                    st.error(f"❌ {err}")
            else:
                success, msg = create_user(
                    username=new_username.strip(),
                    password=new_password,
                    email=new_email.strip(),
                    role=new_role,
                    employee_id=st.session_state.get('_cu_emp_id'),
                    is_active=new_is_active
                )
                if success:
                    # Send welcome email (non-blocking)
                    email_ok, email_msg = send_welcome_email(
                        email=new_email.strip(),
                        username=new_username.strip(),
                        password=new_password,
                        role=new_role,
                    )
                    if email_ok:
                        st.toast(f"📧 {email_msg}", icon="✅")
                    else:
                        st.toast(f"📧 {email_msg}", icon="⚠️")

                    st.toast(f"User **{new_username.strip()}** created!", icon="✅")
                    get_users_list.clear()
                    _cleanup_keys('_cu')
                    st.rerun()  # → closes dialog, refreshes page
                else:
                    st.error(f"❌ {msg}")

        if cancelled:
            _cleanup_keys('_cu')
            st.rerun()


# ─────────────────────────────────────────────────
# EDIT USER DIALOG
# ─────────────────────────────────────────────────
@st.dialog("✏️ Edit User", width="large")
def open_edit_dialog(user_id: int):
    user = get_user_by_id(user_id)
    if not user:
        st.error("User not found")
        return

    employees_df = get_employees_dropdown()

    st.markdown(f"Editing user: **{user['username']}**")

    # ── Role cascade (reruns dialog only) ──
    edit_role = role_group_selector('_ed', default_role=user['role'])

    st.divider()

    # ── Form for remaining fields ──
    with st.form("dlg_edit_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.text_input("Username", value=user['username'], disabled=True)
            edit_email = st.text_input("Email *", value=user['email'], max_chars=255)
            edit_is_active = st.checkbox("Active", value=bool(user['is_active']))

        with col2:
            st.info(f"🏷️ Selected Role: **{edit_role}**")

            # Employee dropdown
            emp_options = ['-- No Employee Link --'] + employees_df['full_name'].tolist()
            current_emp_idx = 0
            if user['employee_id']:
                emp_row = employees_df[employees_df['id'] == user['employee_id']]
                if not emp_row.empty:
                    emp_name = emp_row.iloc[0]['full_name']
                    if emp_name in emp_options:
                        current_emp_idx = emp_options.index(emp_name)

            edit_employee = st.selectbox(
                "Link to Employee", emp_options, index=current_emp_idx)

        # Meta info
        st.caption(
            f"Created: {format_datetime(user['created_date'])} by {user['created_by'] or 'N/A'} · "
            f"Modified: {format_datetime(user['modified_date'])} by {user['modified_by'] or 'N/A'}"
        )

        col_s, col_c = st.columns(2)
        with col_s:
            submitted = st.form_submit_button(
                "✅ Save Changes", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button(
                "❌ Cancel", use_container_width=True)

        if submitted:
            if not edit_email or not is_valid_email(edit_email):
                st.error("❌ Invalid email address")
            else:
                emp_id = None
                if edit_employee != '-- No Employee Link --':
                    emp_row = employees_df[employees_df['full_name'] == edit_employee]
                    if not emp_row.empty:
                        emp_id = int(emp_row.iloc[0]['id'])

                success, msg = update_user(
                    user_id=user_id,
                    email=edit_email,
                    role=edit_role,
                    employee_id=emp_id,
                    is_active=edit_is_active
                )
                if success:
                    st.success(f"✅ {msg}")
                    get_users_list.clear()
                    _cleanup_keys('_ed')
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

        if cancelled:
            _cleanup_keys('_ed')
            st.rerun()


# ─────────────────────────────────────────────────
# RESET PASSWORD DIALOG
# ─────────────────────────────────────────────────
@st.dialog("🔐 Reset Password")
def open_reset_pwd_dialog(user_id: int, username: str, email: str):
    st.info(f"Resetting password for: **{username}** ({email})")

    with st.form("dlg_reset_pwd_form"):
        new_pwd = st.text_input("New Password *", type="password")
        confirm_pwd = st.text_input("Confirm Password *", type="password")

        col_s, col_c = st.columns(2)
        with col_s:
            submitted = st.form_submit_button(
                "✅ Reset Password", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button(
                "❌ Cancel", use_container_width=True)

        if submitted:
            if len(new_pwd) < 8:
                st.error("❌ Password must be at least 8 characters")
            elif new_pwd != confirm_pwd:
                st.error("❌ Passwords do not match")
            else:
                success, msg = reset_password(user_id, new_pwd)
                if success:
                    # Send password reset email (non-blocking)
                    email_ok, email_msg = send_reset_password_email(
                        email=email, username=username, new_password=new_pwd)
                    if email_ok:
                        st.toast(f"📧 {email_msg}", icon="✅")
                    else:
                        st.toast(f"📧 {email_msg}", icon="⚠️")

                    st.toast(f"Password reset for **{username}**", icon="🔐")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

        if cancelled:
            st.rerun()


# ─────────────────────────────────────────────────
# DELETE CONFIRM DIALOG
# ─────────────────────────────────────────────────
@st.dialog("⚠️ Confirm Delete")
def open_delete_dialog(user_id: int, username: str, email: str):
    st.warning(f"Are you sure you want to delete user **{username}**?")
    st.caption("This action will deactivate and soft-delete the user.")

    col_yes, col_no = st.columns(2)

    with col_yes:
        if st.button("✅ Yes, Delete", type="primary", use_container_width=True):
            success, msg = soft_delete_user(user_id)
            if success:
                # Send account deleted email (non-blocking)
                email_ok, email_msg = send_account_deleted_email(
                    email=email, username=username)
                if email_ok:
                    st.toast(f"📧 {email_msg}", icon="✅")
                else:
                    st.toast(f"📧 {email_msg}", icon="⚠️")

                st.toast(f"User **{username}** deleted", icon="🗑️")
                get_users_list.clear()
                st.rerun()
            else:
                st.error(msg)

    with col_no:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()


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

    filter_group = st.selectbox(
        "Department", ['All'] + list(ROLE_GROUPS.keys()), key='filter_group')

    if filter_group == 'All':
        role_filter = st.selectbox(
            "Role", ['All'] + AVAILABLE_ROLES, key='filter_role')
    else:
        roles_in_grp = ROLE_GROUPS[filter_group]
        role_filter = st.selectbox(
            "Role", ['All'] + roles_in_grp, key='filter_role')

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
        open_create_dialog()

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
# USERS TABLE — @st.fragment (toggle status reruns only this fragment)
# =============================================================================

@st.fragment
def users_table_fragment(search_term, role_filter, status_filter):
    """
    Renders the users table.
    
    - Toggle status: reruns fragment only (st.rerun(scope="fragment"))
    - Edit / Reset pwd / Delete: sets session_state flag → full rerun → opens dialog
    """
    users_df = get_users_list(search_term, role_filter, status_filter)

    st.subheader("📋 Users List")

    if users_df.empty:
        st.info("No users found matching the filters")
        return

    st.caption(f"Showing **{len(users_df)}** users")

    # ── Table header ──
    hdr = st.columns([0.5, 2, 3, 1.5, 1, 1.5, 2])
    hdr[0].markdown("**⬤**")
    hdr[1].markdown("**Username**")
    hdr[2].markdown("**Email**")
    hdr[3].markdown("**Role**")
    hdr[4].markdown("**Last Login**")
    hdr[5].markdown("**Company**")
    hdr[6].markdown("**Actions**")
    st.divider()

    # ── Table rows ──
    for idx, row in users_df.iterrows():
        cols = st.columns([0.5, 2, 3, 1.5, 1, 1.5, 2])

        # Status
        with cols[0]:
            st.markdown("🟢" if row['is_active'] else "🔴")

        # Username + employee name
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
                st.caption(str(row['company_name'])[:20])

        # Actions
        with cols[6]:
            a1, a2, a3, a4 = st.columns(4)

            with a1:
                if st.button("✏️", key=f"edit_{row['id']}", help="Edit user"):
                    st.session_state['_dlg'] = ('edit', int(row['id']))
                    st.rerun()

            with a2:
                if st.button("🔐", key=f"pwd_{row['id']}", help="Reset password"):
                    st.session_state['_dlg'] = ('reset_pwd', int(row['id']),
                                                 row['username'], row['email'])
                    st.rerun()

            with a3:
                status_icon = "🚫" if row['is_active'] else "✅"
                status_help = "Deactivate" if row['is_active'] else "Activate"
                if st.button(status_icon, key=f"status_{row['id']}",
                             help=status_help):
                    success, msg = toggle_user_status(int(row['id']))
                    if success:
                        # Send status change email (non-blocking)
                        is_now_active = not bool(row['is_active'])
                        email_ok, email_msg = send_status_change_email(
                            email=row['email'],
                            username=row['username'],
                            is_now_active=is_now_active,
                        )
                        if email_ok:
                            st.toast(f"📧 {email_msg}", icon="✅")
                        else:
                            st.toast(f"📧 {email_msg}", icon="⚠️")

                        get_users_list.clear()
                        st.rerun(scope="fragment")   # ← fragment-only rerun!
                    else:
                        st.error(msg)

            with a4:
                if int(row['id']) != st.session_state.get('user_id'):
                    if st.button("🗑️", key=f"del_{row['id']}",
                                 help="Delete user"):
                        st.session_state['_dlg'] = ('delete', int(row['id']),
                                                     row['username'], row['email'])
                        st.rerun()

        st.divider()


# Render the fragment
st.divider()
users_table_fragment(search_term, role_filter, status_filter)

# ── Open dialog if requested by table actions ──
_dlg = st.session_state.pop('_dlg', None)
if _dlg:
    action = _dlg[0]
    if action == 'edit':
        open_edit_dialog(_dlg[1])
    elif action == 'reset_pwd':
        open_reset_pwd_dialog(_dlg[1], _dlg[2], _dlg[3])
    elif action == 'delete':
        open_delete_dialog(_dlg[1], _dlg[2], _dlg[3])

# =============================================================================
# STATISTICS — @st.fragment (independent of table reruns)
# =============================================================================

@st.fragment
def statistics_fragment():
    st.subheader("📊 Statistics")

    all_users_df = get_users_list()

    if all_users_df.empty:
        st.info("No users in the system")
        return

    stat_cols = st.columns(4)

    with stat_cols[0]:
        st.metric("Total Users", len(all_users_df))

    with stat_cols[1]:
        active_count = int(all_users_df['is_active'].sum())
        st.metric("Active Users", active_count)

    with stat_cols[2]:
        st.metric("Inactive Users", len(all_users_df) - active_count)

    with stat_cols[3]:
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


st.divider()
statistics_fragment()

# =============================================================================
# FOOTER
# =============================================================================

st.divider()
st.caption(
    f"User Management Module v2.2.0 | "
    f"Admin: {st.session_state.get('username', 'Unknown')} | "
    f"Session: {format_datetime(st.session_state.get('login_time'))}"
)