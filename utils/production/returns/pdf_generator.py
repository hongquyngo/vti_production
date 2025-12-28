# utils/production/returns/pdf_generator.py
"""
PDF Generator for Material Returns
Generates return slip PDF with materials list, company logo, and signatures

Version: 1.0.0
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

from .queries import ReturnQueries
from .common import (
    format_number, get_vietnam_now, create_reason_display, format_datetime_vn,
    format_product_display_html
)

logger = logging.getLogger(__name__)


class ReturnPDFGenerator:
    """Generate PDF for Material Returns"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self.queries = ReturnQueries()
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
                     language: str = 'vi', layout: str = 'landscape'):
        """Create PDF header with company info and logo"""
        return_data = data['return']
        company_info = self.get_company_info(return_data['warehouse_id'])
        
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
        title = "PHIẾU TRẢ VẬT TƯ SẢN XUẤT" if language == 'vi' else "MATERIAL RETURN SLIP"
        story.append(Paragraph(f"<b>{title}</b>", styles['TitleViet']))
        story.append(Spacer(1, 5*mm))
    
    def create_return_info(self, story: list, data: Dict, styles: Any,
                          language: str = 'vi', layout: str = 'landscape'):
        """Create return information section"""
        return_data = data['return']
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        if layout == 'landscape':
            left_lw, left_vw = 45*mm, 90*mm
            right_lw, right_vw = 40*mm, 90*mm
        else:
            left_lw, left_vw = 40*mm, 50*mm
            right_lw, right_vw = 35*mm, 55*mm
        
        if language == 'vi':
            labels = {
                'return_no': 'Số phiếu trả:', 'return_date': 'Ngày trả:',
                'order': 'Lệnh sản xuất:', 'product': 'Sản phẩm:',
                'reason': 'Lý do trả:', 'warehouse': 'Kho nhận:',
                'returned_by': 'Người trả:', 'received_by': 'Người nhận:'
            }
        else:
            labels = {
                'return_no': 'Return No:', 'return_date': 'Return Date:',
                'order': 'Order:', 'product': 'Product:',
                'reason': 'Reason:', 'warehouse': 'Warehouse:',
                'returned_by': 'Returned By:', 'received_by': 'Received By:'
            }
        
        # Format date with Vietnam timezone
        return_date = return_data['return_date']
        return_date_str = format_datetime_vn(return_date, '%d/%m/%Y %H:%M')
        
        reason_display = create_reason_display(return_data['reason']).replace('📦 ', '').replace('⚠️ ', '').replace('❌ ', '').replace('📋 ', '').replace('📝 ', '')
        
        # Build product info with standardized format (multi-line for PDF)
        product_info = format_product_display_html(
            pt_code=return_data['pt_code'],
            name=return_data['product_name'],
            legacy_pt_code=return_data.get('legacy_pt_code'),
            package_size=return_data.get('package_size'),
            brand_name=return_data.get('brand_name'),
            is_alternative=False,
            original_name=None
        )
        
        left_data = [
            [Paragraph(f"<b>{labels['return_no']}</b>", styles['NormalViet']),
             Paragraph(str(return_data['return_no']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['return_date']}</b>", styles['NormalViet']),
             Paragraph(return_date_str, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['order']}</b>", styles['NormalViet']),
             Paragraph(str(return_data['order_no']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['product']}</b>", styles['NormalViet']),
             Paragraph(product_info, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['reason']}</b>", styles['NormalViet']),
             Paragraph(reason_display, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['warehouse']}</b>", styles['NormalViet']),
             Paragraph(str(return_data['warehouse_name']), styles['NormalViet'])],
        ]
        
        right_data = [
            [Paragraph(f"<b>{labels['returned_by']}</b>", styles['NormalViet']),
             Paragraph(return_data.get('returned_by_name', 'N/A') or 'N/A', styles['NormalViet'])],
            [Paragraph(f"<b>{labels['received_by']}</b>", styles['NormalViet']),
             Paragraph(return_data.get('received_by_name', '-') or '-', styles['NormalViet'])],
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
    
    def create_materials_table(self, story: list, data: Dict, styles: Any,
                              language: str = 'vi', layout: str = 'landscape'):
        """Create materials table"""
        details = data['details']
        header_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        if language == 'vi':
            headers = ['STT', 'Thông tin vật tư', 'SL', 'ĐVT', 'Tình trạng', 'HSD', 'Ghi chú']
            cond_good, cond_damaged = 'Tốt', 'Hư hỏng'
        else:
            headers = ['No.', 'Material Info', 'Qty', 'UOM', 'Condition', 'Expiry', 'Note']
            cond_good, cond_damaged = 'Good', 'Damaged'
        
        header_row = [Paragraph(f"<b>{h}</b>", styles['TableHeader']) for h in headers]
        table_data = [header_row]
        
        for idx, detail in enumerate(details, 1):
            # Expiry date
            exp_date = ''
            if detail.get('expired_date'):
                if isinstance(detail['expired_date'], str):
                    exp_date = datetime.strptime(detail['expired_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                else:
                    exp_date = detail['expired_date'].strftime('%d/%m/%Y')
            
            # Material info with standardized format (multi-line for PDF)
            mat_info = format_product_display_html(
                pt_code=detail.get('pt_code', ''),
                name=detail['material_name'],
                legacy_pt_code=detail.get('legacy_pt_code'),
                package_size=detail.get('package_size'),
                brand_name=detail.get('brand_name'),
                is_alternative=bool(detail.get('is_alternative')),
                original_name=detail.get('original_material_name')
            )
            # Add batch info
            if detail.get('batch_no'):
                mat_info += f"<br/><b>Batch:</b> {detail['batch_no']}"
            
            qty = detail['quantity']
            qty_str = f"{float(qty):,.4f}".rstrip('0').rstrip('.')
            
            condition = detail.get('condition', 'GOOD')
            cond_display = cond_good if condition == 'GOOD' else cond_damaged
            
            row = [
                Paragraph(str(idx), styles['TableCellCenter']),
                Paragraph(mat_info, styles['TableCell']),
                Paragraph(qty_str, styles['TableCellCenter']),
                Paragraph(str(detail['uom']), styles['TableCellCenter']),
                Paragraph(cond_display, styles['TableCellCenter']),
                Paragraph(exp_date, styles['TableCellCenter']),
                Paragraph('', styles['TableCell'])
            ]
            table_data.append(row)
        
        if layout == 'landscape':
            col_widths = [12*mm, 120*mm, 22*mm, 15*mm, 30*mm, 25*mm, 43*mm]
        else:
            col_widths = [10*mm, 75*mm, 18*mm, 12*mm, 25*mm, 20*mm, 30*mm]
        
        materials_table = Table(table_data, colWidths=col_widths)
        materials_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), header_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (6, 1), (6, -1), 'LEFT'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        story.append(materials_table)
        
        # Alternative note
        if any(d.get('is_alternative') for d in details):
            story.append(Spacer(1, 5*mm))
            note = "(*) Vật tư thay thế" if language == 'vi' else "(*) Alternative material"
            story.append(Paragraph(f"<i>{note}</i>", styles['Footer']))
    
    def create_signature_section(self, story: list, data: Dict, styles: Any,
                                language: str = 'vi', layout: str = 'landscape'):
        """Create signature section"""
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        return_data = data['return']
        returned_by = return_data.get('returned_by_name', '') or ''
        received_by = return_data.get('received_by_name', '') or ''
        
        if language == 'vi':
            headers = ['Người trả', 'Người nhận', 'Giám sát']
            labels = ['(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)']
        else:
            headers = ['Returned By', 'Received By', 'Supervisor']
            labels = ['(Sign & Full Name)', '(Sign & Full Name)', '(Sign & Full Name)']
        
        sig_data = [
            [Paragraph(f"<b>{headers[0]}</b>", styles['NormalViet']),
             Paragraph(f"<b>{headers[1]}</b>", styles['NormalViet']),
             Paragraph(f"<b>{headers[2]}</b>", styles['NormalViet'])],
            ['', '', ''],
            ['', '', ''],
            ['', '', ''],
            ['_________________', '_________________', '_________________'],
            [Paragraph(f"<b>{returned_by}</b>", styles['NormalViet']) if returned_by else '',
             Paragraph(f"<b>{received_by}</b>", styles['NormalViet']) if received_by else '',
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
    
    def generate_pdf(self, return_id: int, language: str = 'vi',
                    layout: str = 'landscape') -> Optional[bytes]:
        """Generate PDF for material return"""
        try:
            return_data = self.queries.get_return_details(return_id)
            if not return_data:
                logger.error(f"Return {return_id} not found")
                return None
            
            materials = self.queries.get_return_materials(return_id)
            
            data = {
                'return': return_data,
                'details': materials.to_dict('records')
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
            self.create_return_info(story, data, styles, language, layout)
            self.create_materials_table(story, data, styles, language, layout)
            self.create_signature_section(story, data, styles, language, layout)
            
            story.append(Spacer(1, 10*mm))
            timestamp = get_vietnam_now().strftime('%d/%m/%Y %H:%M:%S')
            story.append(Paragraph(f"Generated: {timestamp}", styles['Footer']))
            
            doc.build(story)
            
            pdf_content = buffer.getvalue()
            buffer.close()
            
            logger.info(f"✅ PDF generated for return {return_id}")
            return pdf_content
            
        except Exception as e:
            logger.error(f"❌ PDF generation failed: {e}", exc_info=True)
            return None


# Singleton
pdf_generator = ReturnPDFGenerator()