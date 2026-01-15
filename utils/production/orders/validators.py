# utils/production/orders/validators.py
"""
Comprehensive validation module for Production Orders
Implements all business rules for Create, Edit, Confirm, Cancel, Delete

Version: 1.0.0

Validation Rules:
- BLOCK: Hard stop, operation cannot proceed
- WARNING: Soft warning, user can override/acknowledge

Rule IDs:
- C1-C12: Create validations
- E1-E8: Edit validations
- F1-F5: Confirm validations
- X1-X4: Cancel validations
- D1-D3: Delete validations
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from sqlalchemy import text

from utils.db import get_db_engine
from .common import get_vietnam_today, get_vietnam_now

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Validation severity levels"""
    BLOCK = "BLOCK"      # Hard stop - cannot proceed
    WARNING = "WARNING"  # Soft warning - can proceed with acknowledgment


@dataclass
class ValidationResult:
    """Single validation result"""
    rule_id: str
    level: ValidationLevel
    message: str
    message_vi: str = ""  # Vietnamese message
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_blocking(self) -> bool:
        return self.level == ValidationLevel.BLOCK
    
    @property
    def is_warning(self) -> bool:
        return self.level == ValidationLevel.WARNING


@dataclass
class ValidationResults:
    """Collection of validation results"""
    results: List[ValidationResult] = field(default_factory=list)
    
    def add(self, result: ValidationResult):
        """Add a validation result"""
        self.results.append(result)
    
    def add_block(self, rule_id: str, message: str, message_vi: str = "", **details):
        """Add a blocking validation"""
        self.results.append(ValidationResult(
            rule_id=rule_id,
            level=ValidationLevel.BLOCK,
            message=message,
            message_vi=message_vi or message,
            details=details
        ))
    
    def add_warning(self, rule_id: str, message: str, message_vi: str = "", **details):
        """Add a warning validation"""
        self.results.append(ValidationResult(
            rule_id=rule_id,
            level=ValidationLevel.WARNING,
            message=message,
            message_vi=message_vi or message,
            details=details
        ))
    
    @property
    def has_blocks(self) -> bool:
        """Check if any blocking validations exist"""
        return any(r.is_blocking for r in self.results)
    
    @property
    def has_warnings(self) -> bool:
        """Check if any warnings exist"""
        return any(r.is_warning for r in self.results)
    
    @property
    def blocks(self) -> List[ValidationResult]:
        """Get all blocking validations"""
        return [r for r in self.results if r.is_blocking]
    
    @property
    def warnings(self) -> List[ValidationResult]:
        """Get all warning validations"""
        return [r for r in self.results if r.is_warning]
    
    @property
    def is_valid(self) -> bool:
        """Check if no blocking validations"""
        return not self.has_blocks
    
    def __bool__(self) -> bool:
        return self.is_valid
    
    def __len__(self) -> int:
        return len(self.results)


class OrderValidators:
    """
    Comprehensive validation for Production Orders
    
    Usage:
        validator = OrderValidators()
        results = validator.validate_create(order_data)
        if results.has_blocks:
            # Show blocking errors
        if results.has_warnings:
            # Show warnings, allow user to acknowledge
    """
    
    def __init__(self):
        self.engine = get_db_engine()
    
    # ==================== CREATE Validations (C1-C12) ====================
    
    def validate_create(self, order_data: Dict[str, Any]) -> ValidationResults:
        """
        Validate order creation
        
        Args:
            order_data: Dictionary containing:
                - bom_header_id: BOM to use
                - product_id: Product to produce
                - planned_qty: Planned quantity
                - warehouse_id: Source warehouse
                - target_warehouse_id: Target warehouse
                - scheduled_date: Scheduled production date
                
        Returns:
            ValidationResults with all applicable validations
        """
        results = ValidationResults()
        
        # C1: Required fields check
        self._validate_c1_required_fields(order_data, results)
        
        # If required fields missing, skip other validations
        if results.has_blocks:
            return results
        
        # Get BOM info for further validations
        bom_info = self._get_bom_info(order_data.get('bom_header_id'))
        
        # C2: Planned quantity > 0
        self._validate_c2_positive_quantity(order_data, results)
        
        # C3: Planned qty divisible by output_qty
        if bom_info:
            self._validate_c3_qty_divisibility(order_data, bom_info, results)
        
        # C4: BOM conflict (multiple active BOMs)
        self._validate_c4_bom_conflict(order_data, results)
        
        # C5: BOM status must be ACTIVE
        if bom_info:
            self._validate_c5_bom_status(bom_info, results)
        
        # C6: Scheduled date not in past
        self._validate_c6_scheduled_date_past(order_data, results)
        
        # C7: Scheduled date not too far in future
        self._validate_c7_scheduled_date_future(order_data, results)
        
        # C8: Source != Target warehouse
        self._validate_c8_warehouse_same(order_data, results)
        
        # C9 & C10: Material availability
        if bom_info:
            self._validate_c9_c10_material_availability(order_data, results)
        
        # C11: Duplicate order check
        self._validate_c11_duplicate_order(order_data, results)
        
        # C12: Quantity too large (> 10x output_qty)
        if bom_info:
            self._validate_c12_qty_too_large(order_data, bom_info, results)
        
        return results
    
    def _validate_c1_required_fields(self, data: Dict, results: ValidationResults):
        """C1: Check required fields"""
        required = {
            'bom_header_id': 'BOM',
            'product_id': 'Product',
            'planned_qty': 'Planned Quantity',
            'warehouse_id': 'Source Warehouse',
            'target_warehouse_id': 'Target Warehouse',
            'scheduled_date': 'Scheduled Date'
        }
        
        missing = []
        for field_key, field_name in required.items():
            if field_key not in data or data[field_key] is None:
                missing.append(field_name)
        
        if missing:
            results.add_block(
                rule_id="C1",
                message=f"Required fields missing: {', '.join(missing)}",
                message_vi=f"Thiếu thông tin bắt buộc: {', '.join(missing)}",
                missing_fields=missing
            )
    
    def _validate_c2_positive_quantity(self, data: Dict, results: ValidationResults):
        """C2: Planned quantity must be positive"""
        qty = data.get('planned_qty', 0)
        if qty <= 0:
            results.add_block(
                rule_id="C2",
                message="Planned quantity must be greater than 0",
                message_vi="Số lượng kế hoạch phải lớn hơn 0",
                value=qty
            )
    
    def _validate_c3_qty_divisibility(self, data: Dict, bom_info: Dict, results: ValidationResults):
        """C3: Check if planned_qty is divisible by output_qty"""
        planned_qty = Decimal(str(data.get('planned_qty', 0)))
        output_qty = Decimal(str(bom_info.get('output_qty', 1)))
        
        if output_qty > 0 and planned_qty % output_qty != 0:
            results.add_warning(
                rule_id="C3",
                message=f"Planned quantity ({planned_qty}) is not divisible by BOM output ({output_qty}). This may cause material wastage.",
                message_vi=f"Số lượng ({planned_qty}) không chia hết cho output BOM ({output_qty}). Có thể gây lãng phí nguyên vật liệu.",
                planned_qty=float(planned_qty),
                output_qty=float(output_qty),
                remainder=float(planned_qty % output_qty)
            )
    
    def _validate_c4_bom_conflict(self, data: Dict, results: ValidationResults):
        """C4: Check for multiple active BOMs for product"""
        product_id = data.get('product_id')
        if not product_id:
            return
        
        query = text("""
            SELECT COUNT(*) as bom_count
            FROM bom_headers
            WHERE product_id = :product_id
            AND status = 'ACTIVE'
            AND delete_flag = 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'product_id': product_id}).fetchone()
                bom_count = result[0] if result else 0
                
                if bom_count > 1:
                    results.add_block(
                        rule_id="C4",
                        message=f"Product has {bom_count} active BOMs. Please resolve conflict before creating order.",
                        message_vi=f"Sản phẩm có {bom_count} BOM đang active. Vui lòng giải quyết conflict trước khi tạo order.",
                        bom_count=bom_count
                    )
        except Exception as e:
            logger.error(f"Error checking BOM conflict: {e}")
    
    def _validate_c5_bom_status(self, bom_info: Dict, results: ValidationResults):
        """C5: BOM must be ACTIVE"""
        bom_status = bom_info.get('status', '')
        if bom_status != 'ACTIVE':
            results.add_block(
                rule_id="C5",
                message=f"BOM status is '{bom_status}', must be 'ACTIVE'",
                message_vi=f"BOM có status '{bom_status}', phải là 'ACTIVE'",
                bom_status=bom_status
            )
    
    def _validate_c6_scheduled_date_past(self, data: Dict, results: ValidationResults):
        """C6: Scheduled date should not be in the past"""
        scheduled_date = data.get('scheduled_date')
        if not scheduled_date:
            return
        
        if isinstance(scheduled_date, str):
            scheduled_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        elif isinstance(scheduled_date, datetime):
            scheduled_date = scheduled_date.date()
        
        today = get_vietnam_today()
        
        if scheduled_date < today:
            days_past = (today - scheduled_date).days
            results.add_warning(
                rule_id="C6",
                message=f"Scheduled date is {days_past} day(s) in the past. Consider updating to a future date.",
                message_vi=f"Ngày lên lịch đã qua {days_past} ngày. Nên cân nhắc cập nhật lại.",
                scheduled_date=str(scheduled_date),
                today=str(today),
                days_past=days_past
            )
    
    def _validate_c7_scheduled_date_future(self, data: Dict, results: ValidationResults):
        """C7: Scheduled date should not be > 365 days in future"""
        scheduled_date = data.get('scheduled_date')
        if not scheduled_date:
            return
        
        if isinstance(scheduled_date, str):
            scheduled_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        elif isinstance(scheduled_date, datetime):
            scheduled_date = scheduled_date.date()
        
        today = get_vietnam_today()
        max_future = today + timedelta(days=365)
        
        if scheduled_date > max_future:
            days_future = (scheduled_date - today).days
            results.add_warning(
                rule_id="C7",
                message=f"Scheduled date is {days_future} days in the future (> 365 days). Is this intentional?",
                message_vi=f"Ngày lên lịch cách hôm nay {days_future} ngày (> 365 ngày). Có thể nhầm lẫn?",
                scheduled_date=str(scheduled_date),
                days_future=days_future
            )
    
    def _validate_c8_warehouse_same(self, data: Dict, results: ValidationResults):
        """C8: Source and target warehouse should be different"""
        source_wh = data.get('warehouse_id')
        target_wh = data.get('target_warehouse_id')
        
        if source_wh and target_wh and source_wh == target_wh:
            results.add_warning(
                rule_id="C8",
                message="Source and target warehouse are the same. This is unusual but allowed for repacking.",
                message_vi="Kho nguồn và kho đích giống nhau. Không thường gặp nhưng có thể hợp lệ (repacking tại chỗ).",
                warehouse_id=source_wh
            )
    
    def _validate_c9_c10_material_availability(self, data: Dict, results: ValidationResults):
        """C9 & C10: Check material availability"""
        bom_id = data.get('bom_header_id')
        quantity = data.get('planned_qty', 0)
        warehouse_id = data.get('warehouse_id')
        
        if not all([bom_id, quantity, warehouse_id]):
            return
        
        availability = self._check_material_availability(bom_id, quantity, warehouse_id)
        
        if availability['total'] == 0:
            return
        
        # C9: All materials INSUFFICIENT
        if availability['insufficient'] == availability['total']:
            results.add_warning(
                rule_id="C9",
                message=f"All {availability['total']} materials are INSUFFICIENT. Materials may need to be procured first.",
                message_vi=f"Tất cả {availability['total']} nguyên vật liệu đều THIẾU. Có thể cần nhập thêm nguyên vật liệu.",
                total=availability['total'],
                insufficient=availability['insufficient']
            )
        # C10: Some materials PARTIAL/INSUFFICIENT
        elif availability['partial'] > 0 or availability['insufficient'] > 0:
            results.add_warning(
                rule_id="C10",
                message=f"Material availability: {availability['sufficient']} sufficient, {availability['partial']} partial, {availability['insufficient']} insufficient",
                message_vi=f"Tình trạng NVL: {availability['sufficient']} đủ, {availability['partial']} thiếu một phần, {availability['insufficient']} không đủ",
                **availability
            )
    
    def _validate_c11_duplicate_order(self, data: Dict, results: ValidationResults):
        """C11: Check for duplicate order (same product + BOM + scheduled_date)"""
        product_id = data.get('product_id')
        bom_id = data.get('bom_header_id')
        scheduled_date = data.get('scheduled_date')
        
        if not all([product_id, bom_id, scheduled_date]):
            return
        
        query = text("""
            SELECT order_no, planned_qty, status
            FROM manufacturing_orders
            WHERE product_id = :product_id
            AND bom_header_id = :bom_id
            AND scheduled_date = :scheduled_date
            AND delete_flag = 0
            AND status NOT IN ('CANCELLED')
            LIMIT 5
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {
                    'product_id': product_id,
                    'bom_id': bom_id,
                    'scheduled_date': scheduled_date
                }).fetchall()
                
                if result:
                    existing_orders = [{'order_no': r[0], 'planned_qty': r[1], 'status': r[2]} for r in result]
                    results.add_warning(
                        rule_id="C11",
                        message=f"Found {len(existing_orders)} existing order(s) with same product, BOM, and date. Is this intentional?",
                        message_vi=f"Đã có {len(existing_orders)} order với cùng sản phẩm, BOM và ngày. Có chắc muốn tạo thêm?",
                        existing_orders=existing_orders
                    )
        except Exception as e:
            logger.error(f"Error checking duplicate order: {e}")
    
    def _validate_c12_qty_too_large(self, data: Dict, bom_info: Dict, results: ValidationResults):
        """C12: Check if quantity is unusually large (> 10x output_qty)"""
        planned_qty = float(data.get('planned_qty', 0))
        output_qty = float(bom_info.get('output_qty', 1))
        
        if output_qty > 0 and planned_qty > output_qty * 10:
            multiplier = planned_qty / output_qty
            results.add_warning(
                rule_id="C12",
                message=f"Planned quantity ({planned_qty:,.0f}) is {multiplier:.1f}x the BOM output ({output_qty:,.0f}). Please verify.",
                message_vi=f"Số lượng ({planned_qty:,.0f}) gấp {multiplier:.1f} lần output BOM ({output_qty:,.0f}). Vui lòng kiểm tra lại.",
                planned_qty=planned_qty,
                output_qty=output_qty,
                multiplier=multiplier
            )
    
    # ==================== EDIT Validations (E1-E8) ====================
    
    def validate_edit(self, order_id: int, update_data: Dict[str, Any]) -> ValidationResults:
        """
        Validate order edit
        
        Args:
            order_id: ID of order to edit
            update_data: Dictionary of fields to update
            
        Returns:
            ValidationResults with all applicable validations
        """
        results = ValidationResults()
        
        # Get current order info
        order = self._get_order_info(order_id)
        if not order:
            results.add_block(
                rule_id="E0",
                message=f"Order {order_id} not found",
                message_vi=f"Không tìm thấy order {order_id}"
            )
            return results
        
        # E1: Status check
        self._validate_e1_status(order, results)
        
        # If status invalid, skip other validations
        if results.has_blocks:
            return results
        
        # E2: New planned_qty > 0
        if 'planned_qty' in update_data:
            self._validate_e2_positive_quantity(update_data, results)
            
            # E3: New planned_qty >= produced_qty
            self._validate_e3_qty_vs_produced(order, update_data, results)
            
            # E4: New planned_qty vs issued_qty
            self._validate_e4_qty_vs_issued(order_id, order, update_data, results)
            
            # E7: Quantity reduction > 50%
            self._validate_e7_qty_reduction(order, update_data, results)
            
            # E8: Material availability for new qty
            self._validate_e8_material_availability(order, update_data, results)
        
        # E5: Warehouse change when materials issued
        if 'warehouse_id' in update_data:
            self._validate_e5_warehouse_change(order_id, order, update_data, results)
        
        # E6: Scheduled date in past
        if 'scheduled_date' in update_data:
            self._validate_e6_scheduled_date_past(update_data, results)
        
        return results
    
    def _validate_e1_status(self, order: Dict, results: ValidationResults):
        """E1: Only DRAFT or CONFIRMED orders can be edited"""
        status = order.get('status', '')
        if status not in ['DRAFT', 'CONFIRMED']:
            results.add_block(
                rule_id="E1",
                message=f"Cannot edit order with status '{status}'. Only DRAFT or CONFIRMED orders can be edited.",
                message_vi=f"Không thể sửa order có status '{status}'. Chỉ có thể sửa order DRAFT hoặc CONFIRMED.",
                current_status=status
            )
    
    def _validate_e2_positive_quantity(self, data: Dict, results: ValidationResults):
        """E2: New planned quantity must be positive"""
        qty = data.get('planned_qty', 0)
        if qty <= 0:
            results.add_block(
                rule_id="E2",
                message="Planned quantity must be greater than 0",
                message_vi="Số lượng kế hoạch phải lớn hơn 0",
                value=qty
            )
    
    def _validate_e3_qty_vs_produced(self, order: Dict, update_data: Dict, results: ValidationResults):
        """E3: New planned_qty cannot be less than produced_qty"""
        new_qty = float(update_data.get('planned_qty', 0))
        produced_qty = float(order.get('produced_qty', 0))
        
        if produced_qty > 0 and new_qty < produced_qty:
            results.add_block(
                rule_id="E3",
                message=f"Cannot reduce planned quantity ({new_qty:,.2f}) below produced quantity ({produced_qty:,.2f})",
                message_vi=f"Không thể giảm số lượng ({new_qty:,.2f}) dưới số đã sản xuất ({produced_qty:,.2f})",
                new_qty=new_qty,
                produced_qty=produced_qty
            )
    
    def _validate_e4_qty_vs_issued(self, order_id: int, order: Dict, update_data: Dict, results: ValidationResults):
        """E4: Warning if new planned_qty < total issued materials"""
        new_qty = float(update_data.get('planned_qty', 0))
        
        # Get total issued materials
        query = text("""
            SELECT COALESCE(SUM(issued_qty), 0) as total_issued
            FROM manufacturing_order_materials
            WHERE manufacturing_order_id = :order_id
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'order_id': order_id}).fetchone()
                total_issued = float(result[0]) if result else 0
                
                if total_issued > 0:
                    # Calculate what the new required qty would be
                    bom_info = self._get_bom_info(order.get('bom_header_id'))
                    if bom_info:
                        output_qty = float(bom_info.get('output_qty', 1))
                        # This is a simplified check - actual calculation depends on BOM details
                        if new_qty < order.get('planned_qty', 0) and total_issued > 0:
                            results.add_warning(
                                rule_id="E4",
                                message=f"Materials have been issued ({total_issued:,.2f}). Reducing quantity may require material returns.",
                                message_vi=f"Đã xuất nguyên vật liệu ({total_issued:,.2f}). Giảm số lượng có thể cần hoàn trả NVL.",
                                total_issued=total_issued,
                                new_qty=new_qty
                            )
        except Exception as e:
            logger.error(f"Error checking issued qty: {e}")
    
    def _validate_e5_warehouse_change(self, order_id: int, order: Dict, update_data: Dict, results: ValidationResults):
        """E5: Cannot change source_warehouse if materials have been issued"""
        new_warehouse = update_data.get('warehouse_id')
        current_warehouse = order.get('warehouse_id')
        
        if new_warehouse == current_warehouse:
            return
        
        # Check if any materials have been issued
        query = text("""
            SELECT COUNT(*) as issued_count
            FROM manufacturing_order_materials
            WHERE manufacturing_order_id = :order_id
            AND issued_qty > 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'order_id': order_id}).fetchone()
                issued_count = result[0] if result else 0
                
                if issued_count > 0:
                    results.add_block(
                        rule_id="E5",
                        message=f"Cannot change source warehouse - {issued_count} material(s) have been issued from current warehouse",
                        message_vi=f"Không thể đổi kho nguồn - đã xuất {issued_count} loại nguyên vật liệu từ kho hiện tại",
                        issued_count=issued_count
                    )
        except Exception as e:
            logger.error(f"Error checking warehouse change: {e}")
    
    def _validate_e6_scheduled_date_past(self, data: Dict, results: ValidationResults):
        """E6: Warning if new scheduled_date is in the past"""
        scheduled_date = data.get('scheduled_date')
        if not scheduled_date:
            return
        
        if isinstance(scheduled_date, str):
            scheduled_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        elif isinstance(scheduled_date, datetime):
            scheduled_date = scheduled_date.date()
        
        today = get_vietnam_today()
        
        if scheduled_date < today:
            days_past = (today - scheduled_date).days
            results.add_warning(
                rule_id="E6",
                message=f"New scheduled date is {days_past} day(s) in the past",
                message_vi=f"Ngày lên lịch mới đã qua {days_past} ngày",
                scheduled_date=str(scheduled_date),
                days_past=days_past
            )
    
    def _validate_e7_qty_reduction(self, order: Dict, update_data: Dict, results: ValidationResults):
        """E7: Warning if quantity reduced by more than 50%"""
        new_qty = float(update_data.get('planned_qty', 0))
        original_qty = float(order.get('planned_qty', 0))
        
        if original_qty > 0 and new_qty < original_qty:
            reduction_pct = ((original_qty - new_qty) / original_qty) * 100
            
            if reduction_pct > 50:
                results.add_warning(
                    rule_id="E7",
                    message=f"Quantity reduced by {reduction_pct:.1f}% (from {original_qty:,.2f} to {new_qty:,.2f}). Is this correct?",
                    message_vi=f"Số lượng giảm {reduction_pct:.1f}% (từ {original_qty:,.2f} xuống {new_qty:,.2f}). Có chắc không?",
                    original_qty=original_qty,
                    new_qty=new_qty,
                    reduction_pct=reduction_pct
                )
    
    def _validate_e8_material_availability(self, order: Dict, update_data: Dict, results: ValidationResults):
        """E8: Warning if materials insufficient for new quantity"""
        new_qty = float(update_data.get('planned_qty', 0))
        bom_id = order.get('bom_header_id')
        warehouse_id = order.get('warehouse_id')
        
        if not all([bom_id, warehouse_id]):
            return
        
        availability = self._check_material_availability(bom_id, new_qty, warehouse_id)
        
        if availability['total'] > 0 and (availability['partial'] > 0 or availability['insufficient'] > 0):
            results.add_warning(
                rule_id="E8",
                message=f"Material shortage for new quantity: {availability['partial']} partial, {availability['insufficient']} insufficient",
                message_vi=f"Thiếu NVL cho số lượng mới: {availability['partial']} thiếu một phần, {availability['insufficient']} không đủ",
                **availability
            )
    
    # ==================== CONFIRM Validations (F1-F5) ====================
    
    def validate_confirm(self, order_id: int) -> ValidationResults:
        """
        Validate order confirmation
        
        Args:
            order_id: ID of order to confirm
            
        Returns:
            ValidationResults with all applicable validations
        """
        results = ValidationResults()
        
        # Get current order info
        order = self._get_order_info(order_id)
        if not order:
            results.add_block(
                rule_id="F0",
                message=f"Order {order_id} not found",
                message_vi=f"Không tìm thấy order {order_id}"
            )
            return results
        
        # F1: Status check
        self._validate_f1_status(order, results)
        
        # If status invalid, skip other validations
        if results.has_blocks:
            return results
        
        # F2: BOM still active
        self._validate_f2_bom_still_active(order, results)
        
        # F3: Scheduled date check
        self._validate_f3_scheduled_date(order, results)
        
        # F4: Material availability
        self._validate_f4_material_availability(order, results)
        
        # F5: BOM conflict check
        self._validate_f5_bom_conflict(order, results)
        
        return results
    
    def _validate_f1_status(self, order: Dict, results: ValidationResults):
        """F1: Only DRAFT orders can be confirmed"""
        status = order.get('status', '')
        if status != 'DRAFT':
            results.add_block(
                rule_id="F1",
                message=f"Cannot confirm order with status '{status}'. Only DRAFT orders can be confirmed.",
                message_vi=f"Không thể confirm order có status '{status}'. Chỉ có thể confirm order DRAFT.",
                current_status=status
            )
    
    def _validate_f2_bom_still_active(self, order: Dict, results: ValidationResults):
        """F2: BOM must still be ACTIVE"""
        bom_id = order.get('bom_header_id')
        if not bom_id:
            return
        
        bom_info = self._get_bom_info(bom_id)
        if bom_info and bom_info.get('status') != 'ACTIVE':
            results.add_block(
                rule_id="F2",
                message=f"BOM has been deactivated (status: {bom_info.get('status')}). Cannot confirm order.",
                message_vi=f"BOM đã bị deactivate (status: {bom_info.get('status')}). Không thể confirm order.",
                bom_status=bom_info.get('status')
            )
    
    def _validate_f3_scheduled_date(self, order: Dict, results: ValidationResults):
        """F3: Warning if scheduled_date is in the past"""
        scheduled_date = order.get('scheduled_date')
        if not scheduled_date:
            return
        
        if isinstance(scheduled_date, str):
            scheduled_date = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
        elif isinstance(scheduled_date, datetime):
            scheduled_date = scheduled_date.date()
        
        today = get_vietnam_today()
        
        if scheduled_date < today:
            days_past = (today - scheduled_date).days
            results.add_warning(
                rule_id="F3",
                message=f"Scheduled date is {days_past} day(s) overdue. Consider updating before confirming.",
                message_vi=f"Ngày lên lịch đã quá hạn {days_past} ngày. Nên cập nhật trước khi confirm.",
                scheduled_date=str(scheduled_date),
                days_past=days_past
            )
    
    def _validate_f4_material_availability(self, order: Dict, results: ValidationResults):
        """F4: Warning if material availability < 50%"""
        bom_id = order.get('bom_header_id')
        planned_qty = order.get('planned_qty', 0)
        warehouse_id = order.get('warehouse_id')
        
        if not all([bom_id, planned_qty, warehouse_id]):
            return
        
        availability = self._check_material_availability(bom_id, planned_qty, warehouse_id)
        
        if availability['total'] > 0:
            availability_pct = (availability['sufficient'] / availability['total']) * 100
            
            if availability_pct < 50:
                results.add_warning(
                    rule_id="F4",
                    message=f"Only {availability_pct:.1f}% of materials are fully available. Production may be delayed.",
                    message_vi=f"Chỉ có {availability_pct:.1f}% nguyên vật liệu đủ. Sản xuất có thể bị trì hoãn.",
                    availability_pct=availability_pct,
                    **availability
                )
    
    def _validate_f5_bom_conflict(self, order: Dict, results: ValidationResults):
        """F5: Check if BOM conflict has developed since order creation"""
        product_id = order.get('product_id')
        if not product_id:
            return
        
        query = text("""
            SELECT COUNT(*) as bom_count
            FROM bom_headers
            WHERE product_id = :product_id
            AND status = 'ACTIVE'
            AND delete_flag = 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'product_id': product_id}).fetchone()
                bom_count = result[0] if result else 0
                
                if bom_count > 1:
                    results.add_block(
                        rule_id="F5",
                        message=f"Product now has {bom_count} active BOMs. Please resolve conflict before confirming.",
                        message_vi=f"Sản phẩm hiện có {bom_count} BOM active. Vui lòng giải quyết conflict trước khi confirm.",
                        bom_count=bom_count
                    )
        except Exception as e:
            logger.error(f"Error checking BOM conflict on confirm: {e}")
    
    # ==================== CANCEL Validations (X1-X4) ====================
    
    def validate_cancel(self, order_id: int, reason: str = None) -> ValidationResults:
        """
        Validate order cancellation
        
        Args:
            order_id: ID of order to cancel
            reason: Cancellation reason
            
        Returns:
            ValidationResults with all applicable validations
        """
        results = ValidationResults()
        
        # Get current order info
        order = self._get_order_info(order_id)
        if not order:
            results.add_block(
                rule_id="X0",
                message=f"Order {order_id} not found",
                message_vi=f"Không tìm thấy order {order_id}"
            )
            return results
        
        # X1: Status check
        self._validate_x1_status(order, results)
        
        # If status invalid, skip other validations
        if results.has_blocks:
            return results
        
        # X2: Cancel reason
        self._validate_x2_reason(reason, results)
        
        # X3: Materials issued check
        self._validate_x3_materials_issued(order_id, results)
        
        # X4: Recently created check
        self._validate_x4_recent_order(order, results)
        
        return results
    
    def _validate_x1_status(self, order: Dict, results: ValidationResults):
        """X1: Only DRAFT or CONFIRMED orders can be cancelled"""
        status = order.get('status', '')
        if status not in ['DRAFT', 'CONFIRMED']:
            results.add_block(
                rule_id="X1",
                message=f"Cannot cancel order with status '{status}'. Only DRAFT or CONFIRMED orders can be cancelled.",
                message_vi=f"Không thể hủy order có status '{status}'. Chỉ có thể hủy order DRAFT hoặc CONFIRMED.",
                current_status=status
            )
    
    def _validate_x2_reason(self, reason: str, results: ValidationResults):
        """X2: Warning if no cancellation reason provided"""
        if not reason or not reason.strip():
            results.add_warning(
                rule_id="X2",
                message="No cancellation reason provided. Reason is recommended for audit trail.",
                message_vi="Chưa có lý do hủy. Nên có lý do để tiện tra cứu sau này."
            )
    
    def _validate_x3_materials_issued(self, order_id: int, results: ValidationResults):
        """X3: Warning if materials have been issued"""
        query = text("""
            SELECT COUNT(*) as issued_count, COALESCE(SUM(issued_qty), 0) as total_issued
            FROM manufacturing_order_materials
            WHERE manufacturing_order_id = :order_id
            AND issued_qty > 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'order_id': order_id}).fetchone()
                issued_count = result[0] if result else 0
                total_issued = float(result[1]) if result else 0
                
                if issued_count > 0:
                    results.add_warning(
                        rule_id="X3",
                        message=f"{issued_count} material type(s) have been issued (total: {total_issued:,.2f}). Please return materials after cancellation.",
                        message_vi=f"Đã xuất {issued_count} loại NVL (tổng: {total_issued:,.2f}). Cần hoàn trả NVL sau khi hủy.",
                        issued_count=issued_count,
                        total_issued=total_issued
                    )
        except Exception as e:
            logger.error(f"Error checking materials issued: {e}")
    
    def _validate_x4_recent_order(self, order: Dict, results: ValidationResults):
        """X4: Warning if order was created less than 1 hour ago"""
        created_date = order.get('created_date')
        if not created_date:
            return
        
        if isinstance(created_date, str):
            created_date = datetime.strptime(created_date, '%Y-%m-%d %H:%M:%S')
        
        now = get_vietnam_now()
        
        # Handle timezone-naive datetime
        if created_date.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        
        time_diff = now - created_date
        hours_diff = time_diff.total_seconds() / 3600
        
        if hours_diff < 1:
            minutes_diff = time_diff.total_seconds() / 60
            results.add_warning(
                rule_id="X4",
                message=f"Order was created only {minutes_diff:.0f} minutes ago. Is cancellation intentional?",
                message_vi=f"Order mới được tạo {minutes_diff:.0f} phút trước. Có chắc muốn hủy?",
                created_date=str(created_date),
                minutes_ago=minutes_diff
            )
    
    # ==================== DELETE Validations (D1-D3) ====================
    
    def validate_delete(self, order_id: int) -> ValidationResults:
        """
        Validate order deletion
        
        Args:
            order_id: ID of order to delete
            
        Returns:
            ValidationResults with all applicable validations
        """
        results = ValidationResults()
        
        # Get current order info
        order = self._get_order_info(order_id)
        if not order:
            results.add_block(
                rule_id="D0",
                message=f"Order {order_id} not found",
                message_vi=f"Không tìm thấy order {order_id}"
            )
            return results
        
        # D1: Status check
        self._validate_d1_status(order, results)
        
        # If status invalid, skip other validations
        if results.has_blocks:
            return results
        
        # D2: Linked transactions check
        self._validate_d2_linked_transactions(order_id, results)
        
        # D3: Old order check
        self._validate_d3_old_order(order, results)
        
        return results
    
    def _validate_d1_status(self, order: Dict, results: ValidationResults):
        """D1: Only DRAFT or CANCELLED orders can be deleted"""
        status = order.get('status', '')
        if status not in ['DRAFT', 'CANCELLED']:
            results.add_block(
                rule_id="D1",
                message=f"Cannot delete order with status '{status}'. Only DRAFT or CANCELLED orders can be deleted.",
                message_vi=f"Không thể xóa order có status '{status}'. Chỉ có thể xóa order DRAFT hoặc CANCELLED.",
                current_status=status
            )
    
    def _validate_d2_linked_transactions(self, order_id: int, results: ValidationResults):
        """D2: Check for linked transactions (issues, returns)"""
        # Check for material issues
        issue_query = text("""
            SELECT COUNT(*) as issue_count
            FROM manufacturing_order_materials
            WHERE manufacturing_order_id = :order_id
            AND issued_qty > 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(issue_query, {'order_id': order_id}).fetchone()
                issue_count = result[0] if result else 0
                
                if issue_count > 0:
                    results.add_block(
                        rule_id="D2",
                        message=f"Cannot delete - order has {issue_count} material issue transaction(s). Data integrity would be compromised.",
                        message_vi=f"Không thể xóa - order có {issue_count} giao dịch xuất NVL. Sẽ ảnh hưởng tính toàn vẹn dữ liệu.",
                        issue_count=issue_count
                    )
        except Exception as e:
            logger.error(f"Error checking linked transactions: {e}")
    
    def _validate_d3_old_order(self, order: Dict, results: ValidationResults):
        """D3: Warning if order is more than 30 days old"""
        created_date = order.get('created_date')
        if not created_date:
            return
        
        if isinstance(created_date, str):
            created_date = datetime.strptime(created_date, '%Y-%m-%d %H:%M:%S')
        
        if isinstance(created_date, datetime):
            created_date = created_date.date()
        
        today = get_vietnam_today()
        days_old = (today - created_date).days
        
        if days_old > 30:
            results.add_warning(
                rule_id="D3",
                message=f"Order is {days_old} days old. Consider archiving for audit purposes instead of deleting.",
                message_vi=f"Order đã {days_old} ngày. Nên cân nhắc lưu trữ thay vì xóa để tiện kiểm tra sau.",
                created_date=str(created_date),
                days_old=days_old
            )
    
    # ==================== Helper Methods ====================
    
    def _get_order_info(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get order information"""
        query = text("""
            SELECT 
                o.id, o.order_no, o.status, o.planned_qty, o.produced_qty,
                o.product_id, o.bom_header_id, o.warehouse_id, o.target_warehouse_id,
                o.scheduled_date, o.created_date
            FROM manufacturing_orders o
            WHERE o.id = :order_id AND o.delete_flag = 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'order_id': order_id}).fetchone()
                if result:
                    return {
                        'id': result[0],
                        'order_no': result[1],
                        'status': result[2],
                        'planned_qty': result[3],
                        'produced_qty': result[4],
                        'product_id': result[5],
                        'bom_header_id': result[6],
                        'warehouse_id': result[7],
                        'target_warehouse_id': result[8],
                        'scheduled_date': result[9],
                        'created_date': result[10]
                    }
        except Exception as e:
            logger.error(f"Error getting order info: {e}")
        return None
    
    def _get_bom_info(self, bom_id: int) -> Optional[Dict[str, Any]]:
        """Get BOM information"""
        if not bom_id:
            return None
        
        query = text("""
            SELECT id, bom_name, bom_type, output_qty, uom, status, product_id
            FROM bom_headers
            WHERE id = :bom_id AND delete_flag = 0
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {'bom_id': bom_id}).fetchone()
                if result:
                    return {
                        'id': result[0],
                        'bom_name': result[1],
                        'bom_type': result[2],
                        'output_qty': result[3],
                        'uom': result[4],
                        'status': result[5],
                        'product_id': result[6]
                    }
        except Exception as e:
            logger.error(f"Error getting BOM info: {e}")
        return None
    
    def _check_material_availability(self, bom_id: int, quantity: float, 
                                     warehouse_id: int) -> Dict[str, int]:
        """Check material availability summary"""
        query = text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE 
                    WHEN COALESCE(avail.available, 0) >= 
                         d.quantity * :qty / h.output_qty * (1 + d.scrap_rate/100)
                    THEN 1 ELSE 0 
                END) as sufficient,
                SUM(CASE 
                    WHEN COALESCE(avail.available, 0) > 0 
                         AND COALESCE(avail.available, 0) < 
                             d.quantity * :qty / h.output_qty * (1 + d.scrap_rate/100)
                    THEN 1 ELSE 0 
                END) as partial,
                SUM(CASE 
                    WHEN COALESCE(avail.available, 0) = 0 
                    THEN 1 ELSE 0 
                END) as insufficient
            FROM bom_details d
            JOIN bom_headers h ON d.bom_header_id = h.id
            LEFT JOIN (
                SELECT product_id, SUM(remain) as available
                FROM inventory_histories
                WHERE warehouse_id = :warehouse_id
                AND remain > 0 AND delete_flag = 0
                GROUP BY product_id
            ) avail ON avail.product_id = d.material_id
            WHERE h.id = :bom_id
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {
                    'bom_id': bom_id,
                    'qty': quantity,
                    'warehouse_id': warehouse_id
                }).fetchone()
                
                if result:
                    return {
                        'total': int(result[0] or 0),
                        'sufficient': int(result[1] or 0),
                        'partial': int(result[2] or 0),
                        'insufficient': int(result[3] or 0)
                    }
        except Exception as e:
            logger.error(f"Error checking material availability: {e}")
        
        return {'total': 0, 'sufficient': 0, 'partial': 0, 'insufficient': 0}


# ==================== Convenience Functions ====================

def validate_create_order(order_data: Dict[str, Any]) -> ValidationResults:
    """Convenience function to validate order creation"""
    validator = OrderValidators()
    return validator.validate_create(order_data)


def validate_edit_order(order_id: int, update_data: Dict[str, Any]) -> ValidationResults:
    """Convenience function to validate order edit"""
    validator = OrderValidators()
    return validator.validate_edit(order_id, update_data)


def validate_confirm_order(order_id: int) -> ValidationResults:
    """Convenience function to validate order confirmation"""
    validator = OrderValidators()
    return validator.validate_confirm(order_id)


def validate_cancel_order(order_id: int, reason: str = None) -> ValidationResults:
    """Convenience function to validate order cancellation"""
    validator = OrderValidators()
    return validator.validate_cancel(order_id, reason)


def validate_delete_order(order_id: int) -> ValidationResults:
    """Convenience function to validate order deletion"""
    validator = OrderValidators()
    return validator.validate_delete(order_id)
