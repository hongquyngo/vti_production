# utils/production/orders/pdf_generator.py
"""
PDF Generator for Production Orders - Following Issue template style
Generates order summary PDF with materials list, company logo, and signatures

Version: 1.0.0
Based on: MaterialIssuePDFGenerator template
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Any, List
from io import BytesIO
from pathlib import Path
from decimal import Decimal

import pandas as pd

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Import database and S3 utilities
try:
    from utils.db import get_db_engine
    from utils.s3_utils import get_company_logo_from_s3_enhanced
    S3_AVAILABLE = True
except ImportError:
    try:
        from ...db import get_db_engine
        from ...s3_utils import get_company_logo_from_s3_enhanced
        S3_AVAILABLE = True
    except ImportError:
        import sys
        import os
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.append(parent_dir)
        try:
            from db import get_db_engine
            from s3_utils import get_company_logo_from_s3_enhanced
            S3_AVAILABLE = True
        except ImportError:
            S3_AVAILABLE = False
            def get_company_logo_from_s3_enhanced(company_id, logo_path):
                return None

from .queries import OrderQueries
from .common import format_number, get_vietnam_now, format_datetime_vn, format_product_display_html

logger = logging.getLogger(__name__)


class OrderPDFGenerator:
    """Generate PDF for Production Orders - Following Issue template style"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self.queries = OrderQueries()
        self._registered_fonts = set()
        self.font_available = self._setup_fonts()
    
    def _get_project_root(self) -> Path:
        """Get project root directory"""
        current_file = Path(__file__).resolve()
        # Go up: pdf_generator.py -> orders -> production -> utils -> project_root
        project_root = current_file.parent.parent.parent.parent
        return project_root
    
    def _setup_fonts(self) -> bool:
        """Setup DejaVu fonts for Vietnamese text support"""
        try:
            project_root = self._get_project_root()
            fonts_dir = project_root / 'fonts'
            
            if not fonts_dir.exists():
                logger.warning(f"⚠️ Fonts directory not found: {fonts_dir}")
                return False
            
            dejavu_regular = fonts_dir / 'DejaVuSans.ttf'
            dejavu_bold = fonts_dir / 'DejaVuSans-Bold.ttf'
            
            if not dejavu_regular.exists():
                logger.warning(f"⚠️ DejaVuSans.ttf not found")
                return False
            
            # Register fonts
            try:
                if 'DejaVuSans' not in self._registered_fonts:
                    pdfmetrics.registerFont(TTFont('DejaVuSans', str(dejavu_regular)))
                    self._registered_fonts.add('DejaVuSans')
            except Exception as e:
                if 'already registered' not in str(e).lower():
                    raise
                self._registered_fonts.add('DejaVuSans')
            
            try:
                if dejavu_bold.exists() and 'DejaVuSans-Bold' not in self._registered_fonts:
                    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', str(dejavu_bold)))
                    self._registered_fonts.add('DejaVuSans-Bold')
            except Exception as e:
                if 'already registered' not in str(e).lower():
                    raise
                self._registered_fonts.add('DejaVuSans-Bold')
            
            logger.info("✅ DejaVu fonts registered successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Font setup error: {e}")
            return False
    
    def get_company_info(self, warehouse_id: int) -> Dict[str, Any]:
        """Get company information from warehouse"""
        query = """
            SELECT 
                c.id,
                c.english_name,
                c.local_name,
                c.street as address,
                c.registration_code,
                c.registration_code,
                m.path as logo_path,
                c.slogan
            FROM warehouses w
            JOIN companies c ON w.company_id = c.id
            LEFT JOIN medias m ON c.logo_id = m.id
            WHERE w.id = %s
        """
        
        try:
            df = pd.read_sql(query, self.engine, params=(warehouse_id,))
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            logger.error(f"Error getting company info: {e}")
        
        return {
            'id': 0,
            'english_name': 'PROSTECH VIETNAM',
            'local_name': 'CÔNG TY TNHH PROSTECH VIỆT NAM',
            'address': 'Vietnam',
            'registration_code': '',
            'logo_path': None
        }
    
    def get_custom_styles(self) -> Dict[str, Any]:
        """Create custom paragraph styles with DejaVu fonts"""
        styles = getSampleStyleSheet()
        
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        # Title style
        styles.add(ParagraphStyle(
            name='TitleViet',
            parent=styles['Title'],
            fontName=bold_font,
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=6,
            textColor=colors.HexColor('#1a1a1a')
        ))
        
        # Subtitle style
        styles.add(ParagraphStyle(
            name='SubtitleViet',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=11,
            alignment=TA_CENTER,
            spaceAfter=10,
            textColor=colors.HexColor('#666666')
        ))
        
        # Normal text style
        styles.add(ParagraphStyle(
            name='NormalViet',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=10,
            leading=12
        ))
        
        # Company info style
        styles.add(ParagraphStyle(
            name='CompanyInfo',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=10,
            alignment=TA_CENTER
        ))
        
        # Table cell styles
        styles.add(ParagraphStyle(
            name='TableCell',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=9,
            leading=11,
            alignment=TA_LEFT
        ))
        
        styles.add(ParagraphStyle(
            name='TableCellCenter',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=9,
            leading=11,
            alignment=TA_CENTER
        ))
        
        styles.add(ParagraphStyle(
            name='TableHeader',
            parent=styles['Normal'],
            fontName=bold_font,
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.whitesmoke
        ))
        
        # Footer style
        styles.add(ParagraphStyle(
            name='Footer',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=8,
            alignment=TA_CENTER,
            textColor=colors.grey
        ))
        
        return styles
    
    def create_header(self, story: list, data: Dict, styles: Any, 
                     language: str = 'vi', layout: str = 'landscape'):
        """Create PDF header with company info and logo"""
        order = data['order']
        company_info = self.get_company_info(order['warehouse_id'])
        
        # Calculate page width based on layout
        if layout == 'landscape':
            page_width = 277*mm
        else:
            page_width = 190*mm
        
        # Try to get logo
        logo_img = None
        if S3_AVAILABLE:
            try:
                logo_bytes = get_company_logo_from_s3_enhanced(
                    company_info['id'],
                    company_info.get('logo_path')
                )
                if logo_bytes:
                    logo_buffer = BytesIO(logo_bytes)
                    try:
                        logo_img = Image(logo_buffer, width=50*mm, height=15*mm, kind='proportional')
                    except Exception as img_error:
                        logger.error(f"Error creating image: {img_error}")
            except Exception as e:
                logger.warning(f"Could not load logo: {e}")
        
        # Company name and info
        company_name = company_info.get('local_name', company_info.get('english_name', ''))
        company_address = company_info.get('address', '')
        tax_number = company_info.get('registration_code', '')
        
        if logo_img:
            header_data = [[
                logo_img,
                Paragraph(f"""
                    <b>{company_name}</b><br/>
                    {company_address}<br/>
                    MST/Tax: {tax_number if tax_number else 'N/A'}
                """, styles['CompanyInfo'])
            ]]
            header_table = Table(header_data, colWidths=[60*mm, page_width - 60*mm])
        else:
            header_data = [[
                Paragraph(f"""
                    <b>{company_name}</b><br/>
                    {company_address}<br/>
                    MST/Tax: {tax_number if tax_number else 'N/A'}
                """, styles['CompanyInfo'])
            ]]
            header_table = Table(header_data, colWidths=[page_width])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(header_table)
        story.append(Spacer(1, 10*mm))
        
        # Title
        if language == 'vi':
            title = "LỆNH SẢN XUẤT"
            subtitle = "Production Order"
        else:
            title = "PRODUCTION ORDER"
            subtitle = ""
        
        story.append(Paragraph(f"<b>{title}</b>", styles['TitleViet']))
        if subtitle:
            story.append(Paragraph(subtitle, styles['SubtitleViet']))
        story.append(Spacer(1, 3*mm))
        
        # Order No
        story.append(Paragraph(f"Order No: <b>{order['order_no']}</b>", styles['NormalViet']))
        story.append(Spacer(1, 8*mm))
    
    def create_order_info(self, story: list, data: Dict, styles: Any,
                         language: str = 'vi', layout: str = 'landscape'):
        """Create order information section"""
        order = data['order']
        
        # Calculate widths based on layout
        if layout == 'landscape':
            label_width = 45*mm
            value_width = 100*mm
        else:
            label_width = 40*mm
            value_width = 70*mm
        
        # Labels
        if language == 'vi':
            labels = {
                'product': 'Sản phẩm:',
                'bom': 'BOM:',
                'quantity': 'Số lượng:',
                'status': 'Trạng thái:',
                'priority': 'Ưu tiên:',
                'order_date': 'Ngày tạo:',
                'scheduled': 'Ngày dự kiến:',
                'source': 'Kho nguồn:',
                'target': 'Kho đích:'
            }
        else:
            labels = {
                'product': 'Product:',
                'bom': 'BOM:',
                'quantity': 'Quantity:',
                'status': 'Status:',
                'priority': 'Priority:',
                'order_date': 'Order Date:',
                'scheduled': 'Scheduled Date:',
                'source': 'Source Warehouse:',
                'target': 'Target Warehouse:'
            }
        
        # Format dates
        def format_date(dt):
            if dt is None:
                return 'N/A'
            if isinstance(dt, str):
                return dt[:10]
            return dt.strftime('%Y-%m-%d')
        
        # Build product info with unified format:
        # PT_CODE (LEGACY or NEW) | NAME | PKG_SIZE (BRAND)
        pt_code = order.get('pt_code', '') or ''
        legacy_code = order.get('legacy_pt_code', '') or ''
        legacy_display = legacy_code if legacy_code else 'NEW'
        product_name = str(order['product_name'])
        package_size = order.get('package_size', '') or ''
        brand = order.get('brand_name', '') or ''
        
        # Build multi-line product info for PDF
        product_lines = []
        product_lines.append(f"<b>{product_name}</b>")
        
        if pt_code:
            if language == 'vi':
                product_lines.append(f"Mã VT: {pt_code} ({legacy_display})")
            else:
                product_lines.append(f"Code: {pt_code} ({legacy_display})")
        
        # Size and Brand line
        size_brand_parts = []
        if package_size:
            size_brand_parts.append(f"Size: {package_size}")
        if brand:
            size_brand_parts.append(f"Brand: {brand}")
        if size_brand_parts:
            product_lines.append(" | ".join(size_brand_parts))
        
        product_info = "<br/>".join(product_lines)
        
        # Build info data - single column, right-aligned labels
        info_data = [
            [Paragraph(f"<b>{labels['product']}</b>", styles['NormalViet']),
             Paragraph(product_info, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['bom']}</b>", styles['NormalViet']),
             Paragraph(f"{order['bom_name']} ({order['bom_type']})", styles['NormalViet'])],
            [Paragraph(f"<b>{labels['quantity']}</b>", styles['NormalViet']),
             Paragraph(f"{format_number(order['planned_qty'], 2)} {order['uom']}", styles['NormalViet'])],
            [Paragraph(f"<b>{labels['status']}</b>", styles['NormalViet']),
             Paragraph(str(order['status']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['priority']}</b>", styles['NormalViet']),
             Paragraph(str(order['priority']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['order_date']}</b>", styles['NormalViet']),
             Paragraph(format_date(order.get('order_date')), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['scheduled']}</b>", styles['NormalViet']),
             Paragraph(format_date(order.get('scheduled_date')), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['source']}</b>", styles['NormalViet']),
             Paragraph(str(order['warehouse_name']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['target']}</b>", styles['NormalViet']),
             Paragraph(str(order['target_warehouse_name']), styles['NormalViet'])],
        ]
        
        info_table = Table(info_data, colWidths=[label_width, value_width])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 10*mm))
    
    def create_materials_table(self, story: list, data: Dict, styles: Any,
                              language: str = 'vi', layout: str = 'landscape'):
        """Create materials table with detailed info"""
        materials = data['materials']
        
        if materials.empty:
            return
        
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        # Section header
        if language == 'vi':
            story.append(Paragraph("<b>DANH SÁCH VẬT TƯ</b>", styles['NormalViet']))
            headers = ['STT', 'Thông tin vật tư', 'Yêu cầu', 'Đã xuất', 'Còn lại', 'ĐVT', 'Trạng thái']
        else:
            story.append(Paragraph("<b>MATERIALS LIST</b>", styles['NormalViet']))
            headers = ['No.', 'Material Info', 'Required', 'Issued', 'Pending', 'UOM', 'Status']
        
        story.append(Spacer(1, 3*mm))
        
        # Build table data with detailed material info
        # Format: PT_CODE (LEGACY or NEW) | NAME | PKG_SIZE (BRAND)
        table_data = [headers]
        
        for idx, row in materials.iterrows():
            # Get material info fields
            material_name = str(row['material_name'])[:50]
            pt_code = row.get('pt_code', '') or ''
            legacy_code = row.get('legacy_pt_code', '') or ''
            legacy_display = legacy_code if legacy_code else 'NEW'
            package_size = row.get('package_size', '') or ''
            brand = row.get('brand_name', '') or ''
            
            # Build multi-line material info for PDF
            # Line 1: Name (bold)
            # Line 2: Code: PT_CODE (LEGACY)
            # Line 3: Size: PKG_SIZE | Brand: BRAND
            material_lines = [f"<b>{material_name}</b>"]
            
            if pt_code:
                if language == 'vi':
                    material_lines.append(f"Mã VT: {pt_code} ({legacy_display})")
                else:
                    material_lines.append(f"Code: {pt_code} ({legacy_display})")
            
            # Size and Brand line
            size_brand_parts = []
            if package_size:
                size_brand_parts.append(f"Size: {package_size}")
            if brand:
                size_brand_parts.append(f"Brand: {brand}")
            if size_brand_parts:
                material_lines.append(" | ".join(size_brand_parts))
            
            material_info = "<br/>".join(material_lines)
            
            table_data.append([
                str(idx + 1),
                Paragraph(material_info, styles['TableCell']),
                format_number(row['required_qty'], 4),
                format_number(row['issued_qty'], 4),
                format_number(row['pending_qty'], 4),
                row['uom'],
                row['status']
            ])
        
        # Column widths based on layout
        if layout == 'landscape':
            col_widths = [12*mm, 95*mm, 25*mm, 25*mm, 25*mm, 18*mm, 25*mm]
        else:
            col_widths = [10*mm, 60*mm, 20*mm, 20*mm, 20*mm, 15*mm, 20*mm]
        
        materials_table = Table(table_data, colWidths=col_widths)
        
        materials_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), bold_font),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            # Body
            ('FONTNAME', (0, 1), (-1, -1), normal_font),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),   # STT
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),     # Material info
            ('ALIGN', (2, 1), (4, -1), 'RIGHT'),    # Numbers
            ('ALIGN', (5, 1), (6, -1), 'CENTER'),   # UOM, Status
            # Grid and colors
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(materials_table)
    
    def create_signature_section(self, story: list, data: Dict, styles: Any,
                                language: str = 'vi', layout: str = 'landscape'):
        """Create signature section"""
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        if language == 'vi':
            sig_headers = ['Người lập', 'Quản lý sản xuất', 'Phê duyệt']
            sig_labels = ['(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)']
        else:
            sig_headers = ['Created By', 'Production Manager', 'Approved By']
            sig_labels = ['(Sign & Full Name)', '(Sign & Full Name)', '(Sign & Full Name)']
        
        sig_data = [
            # Headers
            [Paragraph(f"<b>{sig_headers[0]}</b>", styles['NormalViet']),
             Paragraph(f"<b>{sig_headers[1]}</b>", styles['NormalViet']),
             Paragraph(f"<b>{sig_headers[2]}</b>", styles['NormalViet'])],
            # Empty rows for signature
            ['', '', ''],
            ['', '', ''],
            ['', '', ''],
            # Signature lines
            ['_________________', '_________________', '_________________'],
            # Labels
            [Paragraph(f"<i>{sig_labels[0]}</i>", styles['Footer']),
             Paragraph(f"<i>{sig_labels[1]}</i>", styles['Footer']),
             Paragraph(f"<i>{sig_labels[2]}</i>", styles['Footer'])],
        ]
        
        # Column width based on layout
        if layout == 'landscape':
            sig_col_width = 85*mm
        else:
            sig_col_width = 60*mm
        
        sig_table = Table(sig_data, colWidths=[sig_col_width, sig_col_width, sig_col_width])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), bold_font),
            ('FONTNAME', (0, 1), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(Spacer(1, 15*mm))
        story.append(sig_table)
    
    def generate_pdf(self, order_id: int, language: str = 'vi',
                    layout: str = 'landscape',
                    include_materials: bool = True) -> Optional[bytes]:
        """
        Generate PDF for a production order
        
        Args:
            order_id: Order ID
            language: 'vi' for Vietnamese, 'en' for English
            layout: 'portrait' or 'landscape'
            include_materials: Include materials list
            
        Returns:
            PDF content as bytes or None if failed
        """
        try:
            logger.info(f"🔧 Generating PDF for order {order_id}")
            
            # Get order data
            order = self.queries.get_order_details(order_id)
            if not order:
                logger.error(f"Order {order_id} not found")
                return None
            
            # Get materials
            materials = self.queries.get_order_materials(order_id) if include_materials else pd.DataFrame()
            
            data = {
                'order': order,
                'materials': materials
            }
            
            # Set page size
            if layout == 'landscape':
                page_size = landscape(A4)
            else:
                page_size = A4
            
            # Create PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=page_size,
                rightMargin=10*mm,
                leftMargin=10*mm,
                topMargin=10*mm,
                bottomMargin=10*mm
            )
            
            story = []
            styles = self.get_custom_styles()
            
            # Build content
            self.create_header(story, data, styles, language, layout)
            self.create_order_info(story, data, styles, language, layout)
            
            if include_materials and not materials.empty:
                self.create_materials_table(story, data, styles, language, layout)
            
            # Notes
            if order.get('notes'):
                story.append(Spacer(1, 5*mm))
                if language == 'vi':
                    notes_label = "Ghi chú:"
                else:
                    notes_label = "Notes:"
                story.append(Paragraph(f"<b>{notes_label}</b> {order['notes']}", styles['NormalViet']))
            
            # Signature section
            self.create_signature_section(story, data, styles, language, layout)
            
            # Footer with timestamp
            story.append(Spacer(1, 10*mm))
            timestamp = get_vietnam_now().strftime('%d/%m/%Y %H:%M:%S')
            story.append(Paragraph(f"Generated: {timestamp}", styles['Footer']))
            
            # Build PDF
            doc.build(story)
            
            pdf_content = buffer.getvalue()
            buffer.close()
            
            logger.info(f"✅ PDF generated for order {order_id}, size: {len(pdf_content)} bytes")
            return pdf_content
            
        except Exception as e:
            logger.error(f"❌ Failed to generate PDF for order {order_id}: {e}", exc_info=True)
            return None


# Singleton instance
pdf_generator = OrderPDFGenerator()