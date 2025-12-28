# utils/production/completions/pdf_generator.py
"""
PDF Generator for Production Receipts
Generates receipt PDF with production details and quality status

Version: 1.0.1
Changes:
- Fixed MST display: Changed from tax_number to registration_code
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Any
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
        S3_AVAILABLE = False
        def get_company_logo_from_s3_enhanced(company_id, logo_path):
            return None

from .queries import CompletionQueries
from .common import format_number, get_vietnam_now, create_status_indicator, format_datetime_vn, format_product_display

logger = logging.getLogger(__name__)


class ReceiptPDFGenerator:
    """Generate PDF for Production Receipts"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self.queries = CompletionQueries()
        self._registered_fonts = set()
        self.font_available = self._setup_fonts()
    
    def _get_project_root(self) -> Path:
        """Get project root directory"""
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent.parent
        return project_root
    
    def _setup_fonts(self) -> bool:
        """Setup DejaVu fonts for Vietnamese text support"""
        try:
            project_root = self._get_project_root()
            fonts_dir = project_root / 'fonts'
            
            if not fonts_dir.exists():
                return False
            
            dejavu_regular = fonts_dir / 'DejaVuSans.ttf'
            dejavu_bold = fonts_dir / 'DejaVuSans-Bold.ttf'
            
            if not dejavu_regular.exists():
                return False
            
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
            
            return True
            
        except Exception as e:
            logger.error(f"Font setup error: {e}")
            return False
    
    def get_company_info(self, warehouse_id: int) -> Dict[str, Any]:
        """Get company information from warehouse"""
        query = """
            SELECT 
                c.id, c.english_name, c.local_name,
                c.street as address, c.registration_code,
                m.path as logo_path
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
        """Create custom paragraph styles"""
        styles = getSampleStyleSheet()
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        styles.add(ParagraphStyle(
            name='TitleViet', parent=styles['Title'],
            fontName=bold_font, fontSize=16, alignment=TA_CENTER,
            spaceAfter=6, textColor=colors.HexColor('#1a1a1a')
        ))
        
        styles.add(ParagraphStyle(
            name='NormalViet', parent=styles['Normal'],
            fontName=base_font, fontSize=10, leading=12
        ))
        
        styles.add(ParagraphStyle(
            name='CompanyInfo', parent=styles['Normal'],
            fontName=base_font, fontSize=10, alignment=TA_CENTER
        ))
        
        styles.add(ParagraphStyle(
            name='TableCell', parent=styles['Normal'],
            fontName=base_font, fontSize=9, leading=11, alignment=TA_LEFT
        ))
        
        styles.add(ParagraphStyle(
            name='TableCellCenter', parent=styles['Normal'],
            fontName=base_font, fontSize=9, leading=11, alignment=TA_CENTER
        ))
        
        styles.add(ParagraphStyle(
            name='TableHeader', parent=styles['Normal'],
            fontName=bold_font, fontSize=9, leading=11,
            alignment=TA_CENTER, textColor=colors.whitesmoke
        ))
        
        styles.add(ParagraphStyle(
            name='Footer', parent=styles['Normal'],
            fontName=base_font, fontSize=8, alignment=TA_CENTER,
            textColor=colors.grey
        ))
        
        return styles
    
    def create_header(self, story: list, data: Dict, styles: Any,
                     language: str = 'vi', layout: str = 'portrait'):
        """Create PDF header with company info and logo"""
        receipt = data['receipt']
        company_info = self.get_company_info(receipt['warehouse_id'])
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        
        # Logo
        logo_img = None
        if S3_AVAILABLE:
            try:
                logo_bytes = get_company_logo_from_s3_enhanced(
                    company_info['id'], company_info.get('logo_path')
                )
                if logo_bytes:
                    logo_buffer = BytesIO(logo_bytes)
                    logo_img = Image(logo_buffer, width=50*mm, height=15*mm, kind='proportional')
            except Exception as e:
                logger.warning(f"Could not load logo: {e}")
        
        company_name = company_info.get('local_name', company_info.get('english_name', ''))
        company_address = company_info.get('address', '')
        tax_number = company_info.get('registration_code', '')
        
        if logo_img:
            header_data = [[
                logo_img,
                Paragraph(f"<b>{company_name}</b><br/>{company_address}<br/>MST: {tax_number or 'N/A'}",
                         styles['CompanyInfo'])
            ]]
            header_table = Table(header_data, colWidths=[60*mm, page_width - 60*mm])
        else:
            header_data = [[
                Paragraph(f"<b>{company_name}</b><br/>{company_address}<br/>MST: {tax_number or 'N/A'}",
                         styles['CompanyInfo'])
            ]]
            header_table = Table(header_data, colWidths=[page_width])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(header_table)
        story.append(Spacer(1, 10*mm))
        
        # Title
        title = "PHIẾU NHẬP KHO THÀNH PHẨM" if language == 'vi' else "PRODUCTION RECEIPT"
        story.append(Paragraph(f"<b>{title}</b>", styles['TitleViet']))
        story.append(Spacer(1, 5*mm))
    
    def create_receipt_info(self, story: list, data: Dict, styles: Any,
                           language: str = 'vi', layout: str = 'portrait'):
        """Create receipt information section"""
        receipt = data['receipt']
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        if layout == 'landscape':
            left_lw, left_vw = 45*mm, 90*mm
            right_lw, right_vw = 40*mm, 90*mm
        else:
            left_lw, left_vw = 40*mm, 55*mm
            right_lw, right_vw = 35*mm, 50*mm
        
        if language == 'vi':
            labels = {
                'receipt_no': 'Số phiếu:', 'receipt_date': 'Ngày nhập:',
                'order': 'Lệnh SX:', 'product': 'Sản phẩm:',
                'batch': 'Số lô:', 'quantity': 'Số lượng:',
                'warehouse': 'Kho nhập:', 'quality': 'Chất lượng:',
                'expiry': 'Hạn sử dụng:', 'created_by': 'Người tạo:'
            }
        else:
            labels = {
                'receipt_no': 'Receipt No:', 'receipt_date': 'Receipt Date:',
                'order': 'Order:', 'product': 'Product:',
                'batch': 'Batch No:', 'quantity': 'Quantity:',
                'warehouse': 'Warehouse:', 'quality': 'Quality:',
                'expiry': 'Expiry Date:', 'created_by': 'Created By:'
            }
        
        # Format date with Vietnam timezone
        receipt_date = receipt['receipt_date']
        receipt_date_str = format_datetime_vn(receipt_date, '%d/%m/%Y %H:%M')
        
        expiry_str = ''
        if receipt.get('expired_date'):
            if isinstance(receipt['expired_date'], str):
                expiry_str = receipt['expired_date'][:10]
            else:
                expiry_str = receipt['expired_date'].strftime('%d/%m/%Y')
        
        quality_display = receipt['quality_status']
        if quality_display == 'PASSED':
            quality_display = 'Đạt / Passed' if language == 'vi' else 'Passed'
        elif quality_display == 'PENDING':
            quality_display = 'Chờ QC / Pending' if language == 'vi' else 'Pending'
        elif quality_display == 'FAILED':
            quality_display = 'Không đạt / Failed' if language == 'vi' else 'Failed'
        
        # Build product info with new standardized format (multiline for PDF)
        product_info = format_product_display(receipt, include_brand=True, multiline=True, language=language)
        
        left_data = [
            [Paragraph(f"<b>{labels['receipt_no']}</b>", styles['NormalViet']),
             Paragraph(str(receipt['receipt_no']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['receipt_date']}</b>", styles['NormalViet']),
             Paragraph(receipt_date_str, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['order']}</b>", styles['NormalViet']),
             Paragraph(str(receipt['order_no']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['product']}</b>", styles['NormalViet']),
             Paragraph(product_info, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['batch']}</b>", styles['NormalViet']),
             Paragraph(str(receipt['batch_no']), styles['NormalViet'])],
        ]
        
        right_data = [
            [Paragraph(f"<b>{labels['quantity']}</b>", styles['NormalViet']),
             Paragraph(f"{format_number(receipt['quantity'], 2)} {receipt['uom']}", styles['NormalViet'])],
            [Paragraph(f"<b>{labels['warehouse']}</b>", styles['NormalViet']),
             Paragraph(str(receipt['warehouse_name']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['quality']}</b>", styles['NormalViet']),
             Paragraph(quality_display, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['expiry']}</b>", styles['NormalViet']),
             Paragraph(expiry_str or 'N/A', styles['NormalViet'])],
            [Paragraph(f"<b>{labels['created_by']}</b>", styles['NormalViet']),
             Paragraph(receipt.get('created_by_name', 'N/A') or 'N/A', styles['NormalViet'])],
        ]
        
        left_table = Table(left_data, colWidths=[left_lw, left_vw])
        left_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        right_table = Table(right_data, colWidths=[right_lw, right_vw])
        right_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        main_table = Table([[left_table, right_table]], 
                          colWidths=[left_lw + left_vw, right_lw + right_vw])
        main_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        
        story.append(main_table)
        story.append(Spacer(1, 8*mm))
    
    def create_signature_section(self, story: list, data: Dict, styles: Any,
                                language: str = 'vi', layout: str = 'portrait'):
        """Create signature section"""
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        receipt = data['receipt']
        created_by = receipt.get('created_by_name', '') or ''
        
        if language == 'vi':
            headers = ['Người sản xuất', 'Kiểm tra chất lượng', 'Thủ kho']
            labels = ['(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)']
        else:
            headers = ['Production', 'Quality Control', 'Warehouse']
            labels = ['(Sign & Full Name)', '(Sign & Full Name)', '(Sign & Full Name)']
        
        sig_data = [
            [Paragraph(f"<b>{headers[0]}</b>", styles['NormalViet']),
             Paragraph(f"<b>{headers[1]}</b>", styles['NormalViet']),
             Paragraph(f"<b>{headers[2]}</b>", styles['NormalViet'])],
            ['', '', ''],
            ['', '', ''],
            ['', '', ''],
            ['_________________', '_________________', '_________________'],
            [Paragraph(f"<b>{created_by}</b>", styles['NormalViet']) if created_by else '',
             '',
             ''],
            [Paragraph(f"<i>{labels[0]}</i>", styles['Footer']),
             Paragraph(f"<i>{labels[1]}</i>", styles['Footer']),
             Paragraph(f"<i>{labels[2]}</i>", styles['Footer'])],
        ]
        
        sig_width = 85*mm if layout == 'landscape' else 60*mm
        
        sig_table = Table(sig_data, colWidths=[sig_width, sig_width, sig_width])
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
    
    def generate_pdf(self, receipt_id: int, language: str = 'vi',
                    layout: str = 'portrait') -> Optional[bytes]:
        """Generate PDF for production receipt"""
        try:
            receipt = self.queries.get_receipt_details(receipt_id)
            if not receipt:
                logger.error(f"Receipt {receipt_id} not found")
                return None
            
            data = {
                'receipt': receipt
            }
            
            page_size = landscape(A4) if layout == 'landscape' else A4
            
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer, pagesize=page_size,
                rightMargin=10*mm, leftMargin=10*mm,
                topMargin=10*mm, bottomMargin=10*mm
            )
            
            story = []
            styles = self.get_custom_styles()
            
            self.create_header(story, data, styles, language, layout)
            self.create_receipt_info(story, data, styles, language, layout)
            
            # Notes section
            if receipt.get('notes'):
                story.append(Spacer(1, 5*mm))
                notes_label = "Ghi chú:" if language == 'vi' else "Notes:"
                story.append(Paragraph(f"<b>{notes_label}</b> {receipt['notes']}", styles['NormalViet']))
            
            self.create_signature_section(story, data, styles, language, layout)
            
            story.append(Spacer(1, 10*mm))
            timestamp = get_vietnam_now().strftime('%d/%m/%Y %H:%M:%S')
            story.append(Paragraph(f"Generated: {timestamp}", styles['Footer']))
            
            doc.build(story)
            
            pdf_content = buffer.getvalue()
            buffer.close()
            
            logger.info(f"✅ PDF generated for receipt {receipt_id}")
            return pdf_content
            
        except Exception as e:
            logger.error(f"❌ PDF generation failed: {e}", exc_info=True)
            return None


# Singleton
pdf_generator = ReceiptPDFGenerator()