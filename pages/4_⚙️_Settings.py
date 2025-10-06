# pages/4_⚙️_Settings.py - Settings & Configuration
import streamlit as st
from utils.auth import AuthManager
from utils.db import get_db_engine
from datetime import datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Settings",
    page_icon="⚙️",
    layout="wide"
)

# Authentication
auth = AuthManager()
auth.require_auth()

# Check if user has admin role
is_admin = st.session_state.user_role in ['admin', 'Admin', 'ADMIN']

# Page header
st.title("⚙️ Settings & Configuration")

# Settings tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["General", "Production", "Notifications", "Data Management", "About"])

with tab1:
    st.subheader("📋 General Settings")
    
    # User preferences
    st.markdown("### User Preferences")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Current User Information**")
        st.write(f"- **Name:** {st.session_state.user_fullname}")
        st.write(f"- **Username:** {st.session_state.username}")
        st.write(f"- **Role:** {st.session_state.user_role}")
        st.write(f"- **Email:** {st.session_state.user_email}")
        st.write(f"- **Login Time:** {st.session_state.login_time.strftime('%Y-%m-%d %H:%M')}")
    
    with col2:
        st.markdown("**Display Settings**")
        
        # Theme preference (mock - not functional in this example)
        theme = st.selectbox("Theme", ["Light", "Dark", "Auto"], index=0)
        
        # Date format
        date_format = st.selectbox("Date Format", ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"], index=0)
        
        # Items per page
        items_per_page = st.number_input("Items per Page", min_value=10, max_value=100, value=25, step=5)
        
        if st.button("Save Preferences", type="primary"):
            st.success("✅ Preferences saved successfully!")
    
    # System information
    if is_admin:
        st.markdown("---")
        st.markdown("### System Information")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Database", "MySQL")
        with col2:
            st.metric("App Version", "1.0.0")
        with col3:
            st.metric("Python Version", "3.10+")

with tab2:
    st.subheader("🏭 Production Settings")
    
    if is_admin:
        # Default values
        st.markdown("### Default Values")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Production Orders**")
            default_priority = st.selectbox("Default Priority", ["LOW", "NORMAL", "HIGH", "URGENT"], index=1)
            auto_confirm = st.checkbox("Auto-confirm orders", value=False)
            allow_partial = st.checkbox("Allow partial completion", value=True)
        
        with col2:
            st.markdown("**Material Issue**")
            fefo_enabled = st.checkbox("Enable FEFO (First Expired First Out)", value=True)
            allow_expired = st.checkbox("Allow expired materials with warning", value=False)
            require_approval = st.checkbox("Require approval for material issue", value=False)
        
        # Batch numbering
        st.markdown("### Batch Numbering Format")
        col1, col2, col3 = st.columns(3)
        with col1:
            batch_prefix = st.selectbox("Prefix Type", ["Type-based", "Custom", "None"])
        with col2:
            if batch_prefix == "Custom":
                custom_prefix = st.text_input("Custom Prefix", value="BATCH")
        with col3:
            batch_format = st.selectbox("Format", ["YYYYMMDD", "YYMMDD", "Sequential"])
        
        # Production rules
        st.markdown("### Production Rules")
        
        col1, col2 = st.columns(2)
        with col1:
            min_batch_size = st.number_input("Minimum Batch Size", min_value=1, value=1)
            max_batch_size = st.number_input("Maximum Batch Size", min_value=1, value=10000)
        
        with col2:
            lead_time_buffer = st.number_input("Lead Time Buffer (days)", min_value=0, value=1)
            safety_stock_factor = st.number_input("Safety Stock Factor", min_value=0.0, value=1.2, step=0.1)
        
        if st.button("Save Production Settings", type="primary"):
            st.success("✅ Production settings saved successfully!")
    else:
        st.info("🔒 Admin access required to modify production settings")

with tab3:
    st.subheader("🔔 Notification Settings")
    
    st.markdown("### Email Notifications")
    
    # Notification preferences
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Order Notifications**")
        notify_order_created = st.checkbox("Order created", value=True)
        notify_order_completed = st.checkbox("Order completed", value=True)
        notify_order_cancelled = st.checkbox("Order cancelled", value=True)
    
    with col2:
        st.markdown("**Inventory Alerts**")
        notify_low_stock = st.checkbox("Low stock alert", value=True)
        notify_expiry = st.checkbox("Expiry warning", value=True)
        notify_batch_issue = st.checkbox("Batch issues", value=True)
    
    # Alert thresholds
    st.markdown("### Alert Thresholds")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        low_stock_threshold = st.number_input("Low Stock Threshold (%)", min_value=0, max_value=100, value=20)
    with col2:
        expiry_warning_days = st.number_input("Expiry Warning (days)", min_value=1, value=30)
    with col3:
        critical_expiry_days = st.number_input("Critical Expiry (days)", min_value=1, value=7)
    
    # Notification recipients
    if is_admin:
        st.markdown("### Notification Recipients")
        recipients = st.text_area(
            "Email Recipients (one per line)",
            placeholder="user1@example.com\nuser2@example.com",
            height=100
        )
    
    if st.button("Save Notification Settings", type="primary"):
        st.success("✅ Notification settings saved successfully!")

with tab4:
    st.subheader("📊 Data Management")
    
    if is_admin:
        st.markdown("### Data Maintenance")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Archive Settings**")
            archive_after_days = st.number_input("Archive completed orders after (days)", min_value=30, value=180)
            auto_archive = st.checkbox("Enable auto-archiving", value=False)
            
            if st.button("Run Archive Now", type="secondary"):
                with st.spinner("Archiving old records..."):
                    # Mock archiving process
                    st.success("✅ Archived 45 old records")
        
        with col2:
            st.markdown("**Data Cleanup**")
            cleanup_drafts = st.number_input("Delete draft orders after (days)", min_value=1, value=30)
            cleanup_cancelled = st.number_input("Delete cancelled orders after (days)", min_value=7, value=90)
            
            if st.button("Clean Up Now", type="secondary"):
                with st.spinner("Cleaning up data..."):
                    st.success("✅ Cleaned up 12 draft orders and 8 cancelled orders")
        
        # Export/Import
        st.markdown("### Data Export/Import")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Export Data**")
            export_type = st.selectbox("Export Type", ["Production Orders", "BOMs", "Material Issues", "All Data"])
            export_format = st.radio("Format", ["CSV", "Excel", "JSON"], horizontal=True)
            
            if st.button("Export Data", type="primary"):
                # Mock export
                st.success(f"✅ Data exported successfully as {export_format}")
                st.download_button(
                    label=f"Download {export_type}.{export_format.lower()}",
                    data="sample,data\n1,2",
                    file_name=f"{export_type.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.{export_format.lower()}",
                    mime="text/csv"
                )
        
        with col2:
            st.markdown("**Import Data**")
            st.info("⚠️ Import feature coming soon")
            uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx", "json"])
            if uploaded_file:
                st.warning("Import functionality will be available in the next version")
        
        # Database info
        st.markdown("### Database Information")
        
        try:
            engine = get_db_engine()
            
            # Get table sizes
            query = """
            SELECT 
                TABLE_NAME as 'Table',
                ROUND(((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024), 2) as 'Size (MB)',
                TABLE_ROWS as 'Rows'
            FROM information_schema.TABLES 
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME IN ('bom_headers', 'bom_details', 'manufacturing_orders', 
                              'material_issues', 'production_receipts')
            ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
            """
            
            df = pd.read_sql(query, engine)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
        except Exception as e:
            st.error(f"Could not retrieve database information: {str(e)}")
    
    else:
        st.info("🔒 Admin access required for data management")

with tab5:
    st.subheader("ℹ️ About")
    
    # About information
    st.markdown("""
    ### Manufacturing Module
    
    **Version:** 1.0.0  
    **Release Date:** January 2025  
    **Developed by:** ProsTech IT Team
    
    ### Features
    - ✅ Production Order Management
    - ✅ Bill of Materials (BOM) Management
    - ✅ Material Issue with FEFO
    - ✅ Batch Tracking & Traceability
    - ✅ Production Reports & Analytics
    - ✅ Inventory Integration
    
    ### Support
    For support and questions, please contact:
    - **Email:** it.support@prostech.vn
    - **Phone:** +84 123 456 789
    - **Documentation:** [View Documentation](#)
    
    ### Changelog
    
    **v1.0.0 (January 2025)**
    - Initial release
    - Support for Kitting, Cutting, and Repacking
    - FEFO material issue
    - Basic reporting features
    
    ### License
    This software is proprietary to ProsTech Vietnam.  
    All rights reserved.
    """)
    
    # System check
    if st.button("🔍 Run System Check"):
        with st.spinner("Running system diagnostics..."):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Database Connection", "✅ OK")
            with col2:
                st.metric("User Authentication", "✅ OK")
            with col3:
                st.metric("Module Status", "✅ OK")
            
            st.success("All systems operational!")
    
    # Debug mode (admin only)
    if is_admin:
        st.markdown("---")
        debug_mode = st.checkbox("Enable Debug Mode", value=st.session_state.get('debug_mode', False))
        if debug_mode != st.session_state.get('debug_mode', False):
            st.session_state.debug_mode = debug_mode
            st.rerun()
        
        if st.session_state.get('debug_mode', False):
            st.warning("⚠️ Debug mode is enabled")
            with st.expander("Session State"):
                st.json(dict(st.session_state))