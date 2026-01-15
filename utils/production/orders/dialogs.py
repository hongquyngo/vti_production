# utils/production/orders/dialogs.py
"""
Dialog components for Orders domain
Confirm, Cancel, Detail, Edit, Delete, PDF dialogs with comprehensive validation

Version: 2.0.0
Changes:
- v2.0.0: Integrated comprehensive validation with warning acknowledgment
          + Dialogs now show both BLOCK errors and WARNINGs
          + Users must acknowledge warnings before proceeding
          + Consistent validation UI across all dialogs
"""

import logging
from typing import Dict, Any, Optional
import time

import streamlit as st
import pandas as pd

from .queries import OrderQueries
from .manager import OrderManager
from .validators import ValidationResults
from .validation_ui import (
    render_validation_blocks, render_validation_warnings,
    render_warning_acknowledgment, ValidationUI
)
from .common import (
    format_number, create_status_indicator, calculate_percentage,
    format_material_display, format_date, get_vietnam_now,
    format_product_display
)

logger = logging.getLogger(__name__)


# ==================== Confirm Order Dialog ====================

@st.dialog("✅ Confirm Production Order", width="large")
def show_confirm_dialog(order_id: int, order_no: str):
    """
    Dialog to confirm a DRAFT order with validation
    
    Args:
        order_id: Order ID to confirm
        order_no: Order number for display
    """
    manager = OrderManager()
    
    # Run validation
    results = manager.validate_confirm(order_id)
    
    st.markdown(f"### Confirm Order: **{order_no}**")
    
    # Check for blocking errors
    if results.has_blocks:
        render_validation_blocks(results, language='en')
        
        st.markdown("---")
        if st.button("❌ Close", use_container_width=True, key="dialog_close_confirm"):
            st.rerun()
        return
    
    # Show order info
    st.markdown("""
    This action will change the order status from **DRAFT** to **CONFIRMED**.
    
    ⚠️ **Important:**
    - Once confirmed, the order cannot be reverted to DRAFT
    - Materials can be issued after confirmation
    """)
    
    # Show warnings if any
    if results.has_warnings:
        st.markdown("---")
        st.markdown("### ⚠️ Warnings")
        render_validation_warnings(results, language='en')
        
        # Acknowledgment checkbox
        st.markdown("---")
        acknowledged = st.checkbox(
            "☑️ I understand the warnings and want to proceed",
            key="confirm_dialog_ack"
        )
    else:
        acknowledged = True
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Confirm Order", type="primary", use_container_width=True,
                    disabled=not acknowledged, key="dialog_confirm_btn"):
            try:
                user_id = st.session_state.get('user_id', 1)
                success, _ = manager.confirm_order(order_id, user_id, skip_warnings=True)
                
                if success:
                    st.success(f"✅ Order {order_no} confirmed successfully!")
                    logger.info(f"User {user_id} confirmed order {order_id}")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("❌ Failed to confirm order")
                    
            except ValueError as e:
                st.error(f"❌ Validation error: {str(e)}")
            except Exception as e:
                st.error(f"❌ System error: {str(e)}")
                logger.error(f"Error confirming order {order_id}: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True, key="dialog_cancel_confirm"):
            st.rerun()


# ==================== Cancel Order Dialog ====================

@st.dialog("❌ Cancel Production Order", width="large")
def show_cancel_dialog(order_id: int, order_no: str):
    """
    Dialog to cancel an order with validation
    
    Args:
        order_id: Order ID to cancel
        order_no: Order number for display
    """
    manager = OrderManager()
    
    st.markdown(f"### Cancel Order: **{order_no}**")
    
    # Cancel reason input (needed for validation)
    cancel_reason = st.text_area(
        "Cancel Reason",
        placeholder="Please provide a reason for cancellation...",
        key="cancel_reason_input"
    )
    
    # Run validation with reason
    results = manager.validate_cancel(order_id, cancel_reason)
    
    # Check for blocking errors
    if results.has_blocks:
        st.markdown("---")
        render_validation_blocks(results, language='en')
        
        st.markdown("---")
        if st.button("❌ Close", use_container_width=True, key="dialog_close_cancel"):
            st.rerun()
        return
    
    st.markdown("""
    ⚠️ **Warning:** This action will:
    - Change status to CANCELLED
    - Prevent any further material issues
    - Cannot be undone
    """)
    
    # Show warnings if any
    if results.has_warnings:
        st.markdown("---")
        st.markdown("### ⚠️ Warnings")
        render_validation_warnings(results, language='en')
        
        # Acknowledgment checkbox
        st.markdown("---")
        acknowledged = st.checkbox(
            "☑️ I understand the warnings and want to proceed",
            key="cancel_dialog_ack"
        )
    else:
        acknowledged = True
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("❌ Cancel Order", type="primary", use_container_width=True,
                    disabled=not acknowledged, key="dialog_cancel_order_btn"):
            try:
                user_id = st.session_state.get('user_id', 1)
                success, _ = manager.cancel_order(order_id, cancel_reason, user_id, skip_warnings=True)
                
                if success:
                    st.success(f"✅ Order {order_no} cancelled")
                    logger.info(f"User {user_id} cancelled order {order_id}")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("❌ Failed to cancel order")
                    
            except ValueError as e:
                st.error(f"❌ Validation error: {str(e)}")
            except Exception as e:
                st.error(f"❌ System error: {str(e)}")
                logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
    
    with col2:
        if st.button("✖️ Close", use_container_width=True, key="dialog_close_cancel_btn"):
            st.rerun()


# ==================== Delete Order Dialog ====================

@st.dialog("🗑️ Delete Production Order", width="large")
def show_delete_dialog(order_id: int, order_no: str):
    """
    Dialog to delete an order with validation
    
    Args:
        order_id: Order ID to delete
        order_no: Order number for display
    """
    manager = OrderManager()
    
    # Run validation
    results = manager.validate_delete(order_id)
    
    st.markdown(f"### Delete Order: **{order_no}**")
    
    # Check for blocking errors
    if results.has_blocks:
        render_validation_blocks(results, language='en')
        
        st.markdown("---")
        if st.button("❌ Close", use_container_width=True, key="dialog_close_delete"):
            st.rerun()
        return
    
    st.markdown("""
    ⚠️ **Warning:** This action will:
    - Mark this order as deleted
    - Remove it from the active orders list
    - This action cannot be undone
    """)
    
    # Show warnings if any
    if results.has_warnings:
        st.markdown("---")
        st.markdown("### ⚠️ Warnings")
        render_validation_warnings(results, language='en')
        
        # Acknowledgment checkbox
        st.markdown("---")
        acknowledged = st.checkbox(
            "☑️ I understand the warnings and want to proceed",
            key="delete_dialog_ack"
        )
    else:
        acknowledged = True
    
    st.warning("Are you sure you want to delete this order?")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🗑️ Delete Order", type="primary", use_container_width=True,
                    disabled=not acknowledged, key="dialog_delete_btn"):
            try:
                user_id = st.session_state.get('user_id', 1)
                success, _ = manager.delete_order(order_id, user_id, skip_warnings=True)
                
                if success:
                    st.success(f"✅ Order {order_no} deleted")
                    logger.info(f"User {user_id} deleted order {order_id}")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("❌ Failed to delete order")
                    
            except ValueError as e:
                st.error(f"❌ Validation error: {str(e)}")
            except Exception as e:
                st.error(f"❌ System error: {str(e)}")
                logger.error(f"Error deleting order {order_id}: {e}", exc_info=True)
    
    with col2:
        if st.button("✖️ Close", use_container_width=True, key="dialog_close_delete_btn"):
            st.rerun()


# ==================== Order Detail Dialog ====================

@st.dialog("📋 Order Details", width="large")
def show_detail_dialog(order_id: int):
    """
    Show order details dialog
    
    Args:
        order_id: Order ID to display
    """
    queries = OrderQueries()
    order = queries.get_order_details(order_id)
    
    if not order:
        st.error("❌ Order not found")
        return
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### 📋 {order['order_no']}")
    with col2:
        st.markdown(f"**{create_status_indicator(order['status'])}**")
    
    st.markdown("---")
    
    # Order Info
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📦 Product Information**")
        # Format: PT_CODE (LEGACY) | NAME | PKG_SIZE (BRAND)
        legacy_code = order.get('legacy_pt_code', '') or ''
        legacy_display = legacy_code if legacy_code else 'NEW'
        st.write(f"• **Code:** {order.get('pt_code', 'N/A')} ({legacy_display})")
        st.write(f"• **Product:** {order['product_name']}")
        pkg_size = order.get('package_size', '') or ''
        brand = order.get('brand_name', '') or ''
        if pkg_size or brand:
            size_brand = pkg_size
            if brand:
                size_brand = f"{pkg_size} ({brand})" if pkg_size else f"({brand})"
            st.write(f"• **Package/Brand:** {size_brand}")
        st.write(f"• **BOM:** {order['bom_name']} ({order['bom_type']})")
    
    with col2:
        st.markdown("**📊 Quantity**")
        st.write(f"• **Planned:** {format_number(order['planned_qty'], 2)} {order['uom']}")
        st.write(f"• **Produced:** {format_number(order.get('produced_qty', 0), 2)} {order['uom']}")
        progress = calculate_percentage(order.get('produced_qty', 0), order['planned_qty'])
        st.progress(progress / 100)
        st.caption(f"{progress}% Complete")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**🏭 Warehouses**")
        st.write(f"• **Source:** {order['warehouse_name']}")
        st.write(f"• **Target:** {order['target_warehouse_name']}")
    
    with col2:
        st.markdown("**📅 Dates**")
        st.write(f"• **Order Date:** {format_date(order.get('order_date'))}")
        st.write(f"• **Scheduled:** {format_date(order.get('scheduled_date'))}")
        if order.get('completion_date'):
            st.write(f"• **Completed:** {format_date(order.get('completion_date'))}")
    
    # Priority
    st.markdown(f"**Priority:** {create_status_indicator(order['priority'])}")
    
    # Notes
    if order.get('notes'):
        st.markdown("---")
        st.markdown("**📝 Notes**")
        st.text(order['notes'])
    
    # Materials
    st.markdown("---")
    st.markdown("### 📦 Required Materials")
    
    materials = queries.get_order_materials(order_id)
    
    if not materials.empty:
        display_df = materials.copy()
        display_df['material_info'] = display_df.apply(format_material_display, axis=1)
        display_df['required'] = display_df['required_qty'].apply(lambda x: format_number(x, 4))
        display_df['issued'] = display_df['issued_qty'].apply(lambda x: format_number(x, 4))
        display_df['pending'] = display_df['pending_qty'].apply(lambda x: format_number(x, 4))
        display_df['status_display'] = display_df['status'].apply(create_status_indicator)
        
        st.dataframe(
            display_df[['material_info', 'required', 'issued', 'pending', 'status_display', 'uom']].rename(columns={
                'material_info': 'Material',
                'required': 'Required',
                'issued': 'Issued',
                'pending': 'Pending',
                'status_display': 'Status',
                'uom': 'UOM'
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No materials found for this order")
    
    st.markdown("---")
    
    # Action buttons - Use session state to avoid nested dialogs
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if order['status'] == 'DRAFT':
            if st.button("✅ Confirm", type="primary", use_container_width=True,
                        key="detail_confirm_btn"):
                # Set session state to open confirm dialog after rerun
                st.session_state['open_order_confirm_dialog'] = True
                st.session_state['order_action_id'] = order_id
                st.session_state['order_action_no'] = order['order_no']
                st.rerun()
    
    with col2:
        if order['status'] in ['DRAFT', 'CONFIRMED']:
            if st.button("❌ Cancel Order", use_container_width=True,
                        key="detail_cancel_btn"):
                # Set session state to open cancel dialog after rerun
                st.session_state['open_order_cancel_dialog'] = True
                st.session_state['order_action_id'] = order_id
                st.session_state['order_action_no'] = order['order_no']
                st.rerun()
    
    with col3:
        if st.button("✖️ Close", use_container_width=True, key="detail_close_btn"):
            st.rerun()


# ==================== Edit Order Dialog ====================

@st.dialog("✏️ Edit Production Order", width="large")
def show_edit_dialog(order_id: int):
    """
    Dialog to edit an order
    
    Args:
        order_id: Order ID to edit
    """
    queries = OrderQueries()
    order = queries.get_order_details(order_id)
    
    if not order:
        st.error("❌ Order not found")
        return
    
    # Import and render edit form
    from .forms import render_edit_form
    render_edit_form(order)


# ==================== PDF Export Dialog ====================

@st.dialog("📄 Export Order PDF", width="medium")
def show_pdf_dialog(order_id: int, order_no: str):
    """
    Dialog to export order as PDF
    
    Args:
        order_id: Order ID
        order_no: Order number for filename
    """
    st.markdown(f"### 📄 Export: {order_no}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        language = st.selectbox(
            "🌐 Language / Ngôn ngữ",
            options=['vi', 'en'],
            format_func=lambda x: "🇻🇳 Tiếng Việt" if x == 'vi' else "🇬🇧 English",
            index=0,
            key="pdf_language"
        )
    
    with col2:
        layout = st.selectbox(
            "📐 Layout",
            options=['landscape', 'portrait'],
            format_func=lambda x: "🖼️ Landscape (Ngang)" if x == 'landscape' else "📄 Portrait (Dọc)",
            index=0,  # Default landscape
            key="pdf_layout"
        )
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📥 Generate PDF", type="primary", use_container_width=True,
                    key="pdf_gen_btn"):
            try:
                from .pdf_generator import OrderPDFGenerator
                
                with st.spinner("Generating PDF..."):
                    generator = OrderPDFGenerator()
                    pdf_content = generator.generate_pdf(
                        order_id,
                        language=language,
                        layout=layout
                    )
                
                if pdf_content:
                    timestamp = get_vietnam_now().strftime('%Y%m%d_%H%M%S')
                    filename = f"Order_{order_no}_{timestamp}.pdf"
                    
                    st.success("✅ PDF Generated!")
                    st.download_button(
                        label="💾 Download PDF",
                        data=pdf_content,
                        file_name=filename,
                        mime="application/pdf",
                        use_container_width=True,
                        key="pdf_download_btn"
                    )
                else:
                    st.error("❌ Failed to generate PDF")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"PDF generation failed: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True, key="pdf_cancel_btn"):
            st.rerun()


# ==================== Check for pending dialogs ====================

def check_pending_dialogs():
    """
    Check if there's a pending dialog to open.
    Call this at the start of the page render.
    """
    if st.session_state.get('open_order_confirm_dialog'):
        order_id = st.session_state.pop('order_action_id', None)
        order_no = st.session_state.pop('order_action_no', '')
        st.session_state.pop('open_order_confirm_dialog', None)
        if order_id:
            show_confirm_dialog(order_id, order_no)
    
    elif st.session_state.get('open_order_cancel_dialog'):
        order_id = st.session_state.pop('order_action_id', None)
        order_no = st.session_state.pop('order_action_no', '')
        st.session_state.pop('open_order_cancel_dialog', None)
        if order_id:
            show_cancel_dialog(order_id, order_no)
    
    elif st.session_state.get('open_order_pdf_dialog'):
        order_id = st.session_state.pop('order_pdf_id', None)
        order_no = st.session_state.pop('order_pdf_no', '')
        st.session_state.pop('open_order_pdf_dialog', None)
        if order_id:
            show_pdf_dialog(order_id, order_no)


# ==================== Quick Action Functions ====================

def handle_row_action(action: str, order_id: int, order_no: str, status: str = ''):
    """
    Handle row action button clicks
    
    Args:
        action: Action type (view, edit, confirm, cancel, pdf, delete)
        order_id: Order ID
        order_no: Order number
        status: Order status (for validation)
    """
    if action == 'view':
        show_detail_dialog(order_id)
    elif action == 'edit':
        show_edit_dialog(order_id)
    elif action == 'confirm':
        show_confirm_dialog(order_id, order_no)
    elif action == 'cancel':
        show_cancel_dialog(order_id, order_no)
    elif action == 'pdf':
        show_pdf_dialog(order_id, order_no)
    elif action == 'delete':
        show_delete_dialog(order_id, order_no)