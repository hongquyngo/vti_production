# pages/5_📦_Production_Receipts.py
"""
Production Receipts Management
Track finished goods output, quality status, yield rates, and inventory impact
Version 1.0 - New Module
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any
import logging

# Production domain imports
from utils.auth import AuthManager
from utils.db import get_db_engine
from utils.production.common import (
    format_number,
    format_currency,
    create_status_indicator,
    export_to_excel,
    get_date_filter_presets,
    calculate_percentage,
    UIHelpers,
    SystemConstants
)

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="Production Receipts",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Database Manager ====================

class ProductionReceiptManager:
    """Manager for production receipts queries"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    def get_receipts(self, from_date: Optional[date] = None,
                    to_date: Optional[date] = None,
                    quality_status: Optional[str] = None,
                    product_id: Optional[int] = None,
                    warehouse_id: Optional[int] = None,
                    order_no: Optional[str] = None,
                    batch_no: Optional[str] = None) -> pd.DataFrame:
        """Get production receipts with filters"""
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                DATE(pr.receipt_date) as receipt_date,
                pr.manufacturing_order_id,
                mo.order_no,
                pr.product_id,
                p.name as product_name,
                p.package_size,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                DATE(pr.expired_date) as expired_date,
                pr.warehouse_id,
                w.name as warehouse_name,
                pr.quality_status,
                pr.notes,
                mo.planned_qty,
                mo.produced_qty,
                ROUND((pr.quantity / mo.planned_qty * 100), 1) as yield_rate,
                mo.scheduled_date,
                DATE(mo.completion_date) as completion_date,
                DATEDIFF(mo.completion_date, mo.scheduled_date) as production_days,
                pr.created_by,
                pr.created_date
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN products p ON pr.product_id = p.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            WHERE 1=1
        """
        
        params = []
        
        if from_date:
            query += " AND DATE(pr.receipt_date) >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(pr.receipt_date) <= %s"
            params.append(to_date)
        
        if quality_status and quality_status != "All":
            query += " AND pr.quality_status = %s"
            params.append(quality_status)
        
        if product_id:
            query += " AND pr.product_id = %s"
            params.append(product_id)
        
        if warehouse_id:
            query += " AND pr.warehouse_id = %s"
            params.append(warehouse_id)
        
        if order_no:
            query += " AND mo.order_no LIKE %s"
            params.append(f"%{order_no}%")
        
        if batch_no:
            query += " AND pr.batch_no LIKE %s"
            params.append(f"%{batch_no}%")
        
        query += " ORDER BY pr.receipt_date DESC, pr.created_date DESC"
        
        try:
            df = pd.read_sql(query, self.engine, params=tuple(params) if params else None)
            return df
        except Exception as e:
            logger.error(f"Error getting production receipts: {e}")
            return pd.DataFrame()
    
    def get_receipt_details(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific receipt"""
        query = """
            SELECT 
                pr.*,
                mo.order_no,
                mo.order_date,
                mo.bom_header_id,
                mo.planned_qty,
                mo.produced_qty,
                mo.scheduled_date,
                mo.completion_date,
                mo.priority,
                mo.notes as order_notes,
                mo.warehouse_id as source_warehouse_id,
                mo.target_warehouse_id,
                p.name as product_name,
                p.description as product_description,
                p.package_size,
                p.pt_code,
                b.bom_name,
                b.bom_type,
                w.name as warehouse_name,
                w.address as warehouse_address,
                sw.name as source_warehouse_name,
                ROUND((pr.quantity / mo.planned_qty * 100), 1) as yield_rate,
                (mo.planned_qty - pr.quantity) as scrap_qty,
                DATEDIFF(mo.completion_date, mo.scheduled_date) as production_days
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN products p ON pr.product_id = p.id
            JOIN bom_headers b ON mo.bom_header_id = b.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            JOIN warehouses sw ON mo.warehouse_id = sw.id
            WHERE pr.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(receipt_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting receipt details for {receipt_id}: {e}")
            return None
    
    def get_receipt_materials(self, manufacturing_order_id: int) -> pd.DataFrame:
        """Get materials used for this production order"""
        query = """
            SELECT 
                mid.material_id,
                p.name as material_name,
                p.pt_code,
                mid.batch_no,
                SUM(mid.quantity) as quantity_used,
                mid.uom,
                DATE(mid.expired_date) as expired_date,
                mi.issue_no,
                DATE(mi.issue_date) as issue_date,
                w.name as source_warehouse
            FROM material_issue_details mid
            JOIN material_issues mi ON mid.material_issue_id = mi.id
            JOIN products p ON mid.material_id = p.id
            JOIN warehouses w ON mi.warehouse_id = w.id
            WHERE mi.manufacturing_order_id = %s
                AND mi.status = 'CONFIRMED'
            GROUP BY 
                mid.material_id, p.name, p.pt_code, mid.batch_no, 
                mid.uom, mid.expired_date, mi.issue_no, mi.issue_date, w.name
            ORDER BY p.name
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(manufacturing_order_id,))
        except Exception as e:
            logger.error(f"Error getting receipt materials: {e}")
            return pd.DataFrame()
    
    def get_inventory_impact(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        """Get inventory impact of this receipt"""
        query = """
            SELECT 
                ih.id as inventory_history_id,
                ih.quantity as stock_in_qty,
                ih.remain as current_remain,
                DATE(ih.created_date) as stock_in_date,
                ih.warehouse_id,
                w.name as warehouse_name,
                -- Calculate current stock level for this product
                (SELECT COALESCE(SUM(remain), 0) 
                 FROM inventory_histories 
                 WHERE product_id = pr.product_id 
                   AND warehouse_id = ih.warehouse_id 
                   AND delete_flag = 0
                   AND remain > 0) as current_stock_level,
                -- Location info
                COALESCE(CONCAT(z.name, '-', r.name, '-', b.name), 'Not assigned') as location
            FROM production_receipts pr
            JOIN inventory_histories ih 
                ON ih.action_detail_id = pr.id 
                AND ih.type = 'stockInProduction'
                AND ih.delete_flag = 0
            JOIN warehouses w ON ih.warehouse_id = w.id
            LEFT JOIN zone_locations z ON ih.zone_id = z.id
            LEFT JOIN rack_locations r ON ih.rack_id = r.id
            LEFT JOIN bin_locations b ON ih.bin_id = b.id
            WHERE pr.id = %s
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(receipt_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting inventory impact: {e}")
            return None
    
    def get_products(self) -> pd.DataFrame:
        """Get all products for filter"""
        query = """
            SELECT DISTINCT
                p.id,
                p.name,
                p.pt_code
            FROM products p
            JOIN production_receipts pr ON p.id = pr.product_id
            WHERE p.delete_flag = 0
            ORDER BY p.name
        """
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting products: {e}")
            return pd.DataFrame()
    
    def get_warehouses(self) -> pd.DataFrame:
        """Get all warehouses for filter"""
        query = """
            SELECT 
                id,
                name
            FROM warehouses
            WHERE delete_flag = 0
            ORDER BY name
        """
        try:
            return pd.read_sql(query, self.engine)
        except Exception as e:
            logger.error(f"Error getting warehouses: {e}")
            return pd.DataFrame()
    
    def update_quality_status(self, receipt_id: int, new_status: str, 
                            notes: Optional[str] = None, 
                            user_id: Optional[int] = None) -> bool:
        """Update quality status of a receipt"""
        from sqlalchemy import text
        
        with self.engine.begin() as conn:
            try:
                query = text("""
                    UPDATE production_receipts
                    SET quality_status = :status,
                        notes = CASE 
                            WHEN :notes IS NOT NULL THEN :notes 
                            ELSE notes 
                        END,
                        created_date = created_date
                    WHERE id = :receipt_id
                """)
                
                result = conn.execute(query, {
                    'status': new_status,
                    'notes': notes,
                    'receipt_id': receipt_id
                })
                
                success = result.rowcount > 0
                if success:
                    logger.info(f"Updated receipt {receipt_id} quality to {new_status}")
                return success
                
            except Exception as e:
                logger.error(f"Error updating quality status: {e}")
                raise


# ==================== Initialize Manager ====================

@st.cache_resource
def get_receipt_manager():
    """Initialize and cache receipt manager"""
    return ProductionReceiptManager()

receipt_mgr = get_receipt_manager()

# ==================== Session State ====================

def initialize_session_state():
    """Initialize session state variables"""
    defaults = {
        'current_view': 'list',
        'selected_receipt_id': None,
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

def set_view(view: str, receipt_id: Optional[int] = None):
    """Set current view and optionally selected receipt"""
    st.session_state.current_view = view
    if receipt_id is not None:
        st.session_state.selected_receipt_id = receipt_id

initialize_session_state()

# ==================== Header ====================

def render_header():
    """Render page header"""
    col1, col2, col3 = st.columns([2, 3, 1])
    
    with col1:
        st.title("📦 Production Receipts")
    
    with col2:
        if st.session_state.current_view == 'details':
            if st.button("← Back to List", key="back_receipts_filter", use_container_width=True):
                set_view('list')
                st.rerun()
    
    with col3:
        if st.button("🔄 Refresh", key="refresh_receipts", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

# ==================== List View ====================

def render_receipts_list():
    """Render production receipts list with filters"""
    st.subheader("📋 Production Output Records")
    
    # Filters
    st.markdown("### 🔍 Filters")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        presets = get_date_filter_presets()
        date_range = st.selectbox(
            "Date Range",
            list(presets.keys()),
            index=6  # Last 7 Days
        )
        from_date, to_date = presets[date_range]
    
    with col2:
        quality_status = st.selectbox(
            "Quality Status",
            ["All", "PENDING", "PASSED", "FAILED"],
            index=0
        )
    
    with col3:
        products = receipt_mgr.get_products()
        product_options = ["All Products"] + products['name'].tolist() if not products.empty else ["All Products"]
        selected_product = st.selectbox("Product", product_options)
        product_id = None
        if selected_product != "All Products" and not products.empty:
            product_id = products[products['name'] == selected_product]['id'].iloc[0]
    
    with col4:
        warehouses = receipt_mgr.get_warehouses()
        warehouse_options = ["All Warehouses"] + warehouses['name'].tolist() if not warehouses.empty else ["All Warehouses"]
        selected_warehouse = st.selectbox("Warehouse", warehouse_options)
        warehouse_id = None
        if selected_warehouse != "All Warehouses" and not warehouses.empty:
            warehouse_id = warehouses[warehouses['name'] == selected_warehouse]['id'].iloc[0]
    
    # Additional filters
    col5, col6 = st.columns([1, 1])
    with col5:
        order_no = st.text_input("🔍 Order No.", placeholder="Search by order number...")
    with col6:
        batch_no = st.text_input("🔍 Batch No.", placeholder="Search by batch number...")
    
    st.markdown("---")
    
    # Get receipts
    receipts = receipt_mgr.get_receipts(
        from_date=from_date,
        to_date=to_date,
        quality_status=quality_status if quality_status != "All" else None,
        product_id=product_id,
        warehouse_id=warehouse_id,
        order_no=order_no if order_no else None,
        batch_no=batch_no if batch_no else None
    )
    
    if receipts.empty:
        st.info("📭 No production receipts found for the selected filters")
        return
    
    # Summary Metrics
    st.markdown("### 📊 Summary Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_receipts = len(receipts)
        st.metric("Total Receipts", total_receipts)
    
    with col2:
        total_qty = receipts['quantity'].sum()
        st.metric("Total Quantity", f"{format_number(total_qty, 0)}")
    
    with col3:
        passed = len(receipts[receipts['quality_status'] == 'PASSED'])
        pass_rate = calculate_percentage(passed, total_receipts, 1)
        quality_delta = "✅" if pass_rate >= 95 else "⚠️" if pass_rate >= 90 else "❌"
        st.metric("Pass Rate", f"{pass_rate}% {quality_delta}")
    
    with col4:
        avg_yield = receipts['yield_rate'].mean()
        yield_delta = "✅" if avg_yield >= 95 else "⚠️" if avg_yield >= 90 else "❌"
        st.metric("Avg Yield Rate", f"{avg_yield:.1f}% {yield_delta}")
    
    st.markdown("---")
    
    # Quality Breakdown
    with st.expander("📈 Quality Breakdown", expanded=False):
        col1, col2, col3 = st.columns(3)
        
        passed_count = len(receipts[receipts['quality_status'] == 'PASSED'])
        pending_count = len(receipts[receipts['quality_status'] == 'PENDING'])
        failed_count = len(receipts[receipts['quality_status'] == 'FAILED'])
        
        with col1:
            st.metric("✅ PASSED", passed_count, 
                     f"{calculate_percentage(passed_count, total_receipts)}%")
        with col2:
            st.metric("⚠️ PENDING", pending_count,
                     f"{calculate_percentage(pending_count, total_receipts)}%")
        with col3:
            st.metric("❌ FAILED", failed_count,
                     f"{calculate_percentage(failed_count, total_receipts)}%")
    
    st.markdown("---")
    
    # Data Table
    st.markdown("### 📋 Receipts List")
    
    # Prepare display dataframe
    display_df = receipts.copy()
    
    # Format columns
    display_df['receipt_date'] = pd.to_datetime(display_df['receipt_date']).dt.strftime('%d-%b-%Y')
    display_df['quality_status'] = display_df['quality_status'].apply(create_status_indicator)
    display_df['yield'] = display_df['yield_rate'].apply(lambda x: f"{x:.1f}%")
    
    # Add yield indicator
    display_df['yield_indicator'] = display_df['yield_rate'].apply(
        lambda x: "✅" if x >= 95 else "⚠️" if x >= 85 else "❌"
    )
    display_df['yield_display'] = display_df['yield'] + " " + display_df['yield_indicator']
    
    # Format quantity
    display_df['qty_display'] = display_df.apply(
        lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1
    )
    
    # Select columns to display
    columns_to_show = [
        'receipt_no', 'receipt_date', 'order_no', 'product_name',
        'qty_display', 'batch_no', 'quality_status', 'yield_display', 'warehouse_name'
    ]
    
    # Rename for display
    display_columns = {
        'receipt_no': 'Receipt No',
        'receipt_date': 'Date',
        'order_no': 'Order No',
        'product_name': 'Product',
        'qty_display': 'Quantity',
        'batch_no': 'Batch',
        'quality_status': 'Quality',
        'yield_display': 'Yield',
        'warehouse_name': 'Warehouse'
    }
    
    display_df = display_df[columns_to_show].rename(columns=display_columns)
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )
    
    # Quick Actions
    st.markdown("---")
    st.markdown("### ⚡ Quick Actions")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        receipt_options = receipts['receipt_no'].tolist()
        selected_receipt_no = st.selectbox(
            "Select Receipt",
            receipt_options,
            key="receipt_list_select"
        )
    
    with col2:
        action = st.selectbox(
            "Action",
            ["View Details", "Update Quality", "View Order", "View Inventory"],
            key="receipt_action"
        )
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Execute", type="primary", use_container_width=True):
            if selected_receipt_no:
                receipt_row = receipts[receipts['receipt_no'] == selected_receipt_no].iloc[0]
                execute_action(action, receipt_row['id'])
    
    # Export option
    if st.button("📥 Export to Excel", use_container_width=False):
        excel_data = export_to_excel(receipts)
        st.download_button(
            label="Download Excel",
            data=excel_data,
            file_name=f"production_receipts_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

def execute_action(action: str, receipt_id: int):
    """Execute action on selected receipt"""
    if action == "View Details":
        set_view('details', receipt_id)
        st.rerun()
    elif action == "Update Quality":
        set_view('update_quality', receipt_id)
        st.rerun()
    elif action == "View Order":
        receipt = receipt_mgr.get_receipt_details(receipt_id)
        if receipt:
            st.info(f"Navigate to Order: {receipt['order_no']}")
    elif action == "View Inventory":
        st.info("Navigate to Inventory module (to be implemented)")

# ==================== Detail View ====================

def render_receipt_details():
    """Render detailed receipt information"""
    if not st.session_state.selected_receipt_id:
        st.warning("No receipt selected")
        if st.button("← Back to List", key="back_no_receipt"):
            set_view('list')
            st.rerun()
        return
    
    receipt_id = st.session_state.selected_receipt_id
    receipt = receipt_mgr.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("Receipt not found")
        if st.button("← Back to List", key="back_receipt_not_found"):
            set_view('list')
            st.rerun()
        return
    
    st.subheader(f"📦 Receipt Details: {receipt['receipt_no']}")
    
    # Section 1: Output Information
    with st.expander("📦 OUTPUT INFORMATION", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Receipt No:** {receipt['receipt_no']}")
            st.markdown(f"**Receipt Date:** {receipt['receipt_date']}")
            st.markdown(f"**Batch No:** {receipt['batch_no']}")
            st.markdown(f"**Product:** {receipt['product_name']}")
        
        with col2:
            st.markdown(f"**Quantity:** {format_number(receipt['quantity'], 2)} {receipt['uom']}")
            st.markdown(f"**Warehouse:** {receipt['warehouse_name']}")
            st.markdown(f"**Quality Status:** {create_status_indicator(receipt['quality_status'])}")
            st.markdown(f"**Created By:** {receipt.get('created_by_name', 'N/A')}")
    
    # Section 2: Related Order
    with st.expander("📋 ORDER INFORMATION", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Order No:** {receipt['order_no']}")
            st.markdown(f"**Order Date:** {receipt['order_date']}")
            st.markdown(f"**BOM:** {receipt.get('bom_name', 'N/A')}")
        
        with col2:
            st.markdown(f"**Planned Qty:** {format_number(receipt['planned_qty'], 2)} {receipt['uom']}")
            st.markdown(f"**Produced Qty:** {format_number(receipt['produced_qty'], 2)} {receipt['uom']}")
            st.markdown(f"**Order Status:** {create_status_indicator(receipt['order_status'])}")
        
        # Production efficiency
        if receipt['planned_qty'] > 0:
            efficiency = calculate_percentage(receipt['produced_qty'], receipt['planned_qty'])
            st.progress(efficiency / 100)
            st.caption(f"Production Efficiency: {efficiency}%")
    
    # Section 3: Notes
    if receipt.get('notes'):
        with st.expander("📝 NOTES", expanded=False):
            st.text(receipt['notes'])
    
    # Section 4: Material Usage (if available)
    with st.expander("📦 MATERIAL USAGE", expanded=False):
        materials = receipt_mgr.get_receipt_materials(receipt_id)
        
        if not materials.empty:
            st.dataframe(
                materials,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No material usage data available")
    
    # Action Buttons
    st.markdown("---")
    st.markdown("### Actions")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        if st.button("✏️ Update Quality", key="update_quality_btn", use_container_width=True):
            set_view('update_quality', receipt_id)
            st.rerun()
    
    with col2:
        if st.button("🖨️ Print Receipt", key="print_receipt_btn", use_container_width=True):
            st.info("Print functionality (to be implemented)")
    
    with col3:
        if st.button("📧 Send Email", key="send_email_btn", use_container_width=True):
            st.info("Email functionality (to be implemented)")
    
    with col4:
        if st.button("🔍 View Full Order Details", key="view_order_details_btn", use_container_width=True):
            st.session_state.selected_order = receipt.get('order_id')
            st.switch_page("pages/2___Production.py")
    
    with col5:
        if st.button("📦 View Inventory", key="view_inventory_btn", use_container_width=True):
            st.info("Navigate to inventory (to be implemented)")

# ==================== Update Quality View ====================

def render_update_quality():
    """Render quality status update form"""
    if not st.session_state.selected_receipt_id:
        st.warning("No receipt selected")
        if st.button("← Back to List", key="back_from_update_no_receipt"):
            set_view('list')
            st.rerun()
        return
    
    receipt_id = st.session_state.selected_receipt_id
    receipt = receipt_mgr.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("Receipt not found")
        if st.button("← Back to List", key="back_from_update_not_found"):
            set_view('list')
            st.rerun()
        return
    
    st.subheader(f"✏️ Update Quality Status: {receipt['receipt_no']}")
    
    # Show current info
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Product:** {receipt['product_name']}")
        st.info(f"**Quantity:** {format_number(receipt['quantity'], 2)} {receipt['uom']}")
    with col2:
        st.info(f"**Batch:** {receipt['batch_no']}")
        st.info(f"**Current Status:** {create_status_indicator(receipt['quality_status'])}")
    
    st.markdown("---")
    
    # Update form
    with st.form("update_quality_form"):
        st.markdown("### Quality Information")
        
        new_status = st.selectbox(
            "New Quality Status",
            ["PENDING", "PASSED", "FAILED"],
            index=["PENDING", "PASSED", "FAILED"].index(receipt['quality_status'])
        )
        
        notes = st.text_area(
            "Quality Notes",
            value=receipt['notes'] or "",
            height=150,
            placeholder="Enter quality inspection notes, issues found, corrective actions, etc."
        )
        
        st.markdown("---")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            submitted = st.form_submit_button(
                "✅ Update Quality Status",
                type="primary",
                use_container_width=True
            )
        
        with col2:
            cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            try:
                success = receipt_mgr.update_quality_status(
                    receipt_id,
                    new_status,
                    notes,
                    st.session_state.user_id
                )
                
                if success:
                    UIHelpers.show_message(
                        f"✅ Quality status updated to {new_status}",
                        "success"
                    )
                    set_view('details', receipt_id)
                    st.rerun()
                else:
                    UIHelpers.show_message("❌ Failed to update quality status", "error")
                    
            except Exception as e:
                UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                logger.error(f"Quality update failed: {e}", exc_info=True)
        
        if cancel:
            set_view('details', receipt_id)
            st.rerun()

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    try:
        # Render header
        render_header()
        
        st.markdown("---")
        
        # Route to appropriate view
        view_map = {
            'list': render_receipts_list,
            'details': render_receipt_details,
            'update_quality': render_update_quality
        }
        
        # Get current view handler
        view_handler = view_map.get(st.session_state.current_view, render_receipts_list)
        view_handler()
        
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("← Back to List", key="back_from_error"):
            set_view('list')
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Production Receipts Management System")

if __name__ == "__main__":
    main()