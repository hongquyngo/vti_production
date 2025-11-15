# utils/production/pdf_generator.py
"""
PDF Generator for Material Issues with Multi-language Support - REFACTORED v5.1
FIXED: Font loading from project fonts/ directory for Streamlit Cloud deployment

CHANGES v5.1:
- ✅ CRITICAL FIX: Load DejaVu fonts from project fonts/ directory
- ✅ STREAMLIT CLOUD COMPATIBLE: Works with fonts bundled in project
- ✅ Added proper path resolution for fonts/ folder
- ✅ Simplified font setup logic
- ✅ All v5.0 fixes maintained (Vietnamese support, cell wrapping)
"""

import logging
import os
from datetime import datetime
from typing import Dict, Optional, Any, List
from io import BytesIO
import uuid
import pandas as pd
from decimal import Decimal
from pathlib import Path

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, 
    PageBreak, Image, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate
from reportlab.platypus.frames import Frame
from reportlab.lib.utils import ImageReader

# Import database and S3 utilities with proper error handling
try:
    from ..db import get_db_engine
    from ..s3_utils import get_company_logo_from_s3_enhanced
    S3_AVAILABLE = True
except ImportError as e:
    # Alternative import for testing or when running as standalone
    import sys
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(parent_dir)
    
    try:
        from db import get_db_engine
        from s3_utils import get_company_logo_from_s3_enhanced
        S3_AVAILABLE = True
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.warning("Could not import S3 utilities - logo functionality disabled")
        S3_AVAILABLE = False
        def get_company_logo_from_s3_enhanced(company_id, logo_path):
            return None

logger = logging.getLogger(__name__)


class MaterialIssuePDFGenerator:
    """Generate PDF for Material Issue transactions"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self._registered_fonts = set()  # Track registered fonts
        self.font_available = self._setup_fonts()
    
    def _get_project_root(self) -> Path:
        """
        Get project root directory
        From utils/production/pdf_generator.py -> project root is 3 levels up
        """
        current_file = Path(__file__).resolve()
        # Go up: pdf_generator.py -> production -> utils -> project_root
        project_root = current_file.parent.parent.parent
        return project_root
    
    def _setup_fonts(self) -> bool:
        """
        Setup DejaVu fonts for Vietnamese text support
        FIXED v5.1: Load from project fonts/ directory for Streamlit Cloud
        
        Returns:
            True if fonts registered successfully, False otherwise
        """
        try:
            # Get project root and fonts directory
            project_root = self._get_project_root()
            fonts_dir = project_root / 'fonts'
            
            logger.info(f"Project root: {project_root}")
            logger.info(f"Looking for fonts in: {fonts_dir}")
            
            # Check if fonts directory exists
            if not fonts_dir.exists():
                logger.warning(f"⚠️ Fonts directory not found: {fonts_dir}")
                logger.warning("Vietnamese text may not display correctly")
                return False
            
            # Define font file paths
            dejavu_regular = fonts_dir / 'DejaVuSans.ttf'
            dejavu_bold = fonts_dir / 'DejaVuSans-Bold.ttf'
            
            # Check if font files exist
            if not dejavu_regular.exists():
                logger.warning(f"⚠️ DejaVuSans.ttf not found in {fonts_dir}")
                return False
            
            # Register fonts with ReportLab (use try-except to avoid duplicate registration)
            try:
                if 'DejaVuSans' not in self._registered_fonts:
                    pdfmetrics.registerFont(TTFont('DejaVuSans', str(dejavu_regular)))
                    self._registered_fonts.add('DejaVuSans')
                    logger.info(f"✅ Registered DejaVuSans from: {dejavu_regular}")
            except Exception as e:
                if 'already registered' not in str(e).lower():
                    raise
                self._registered_fonts.add('DejaVuSans')
            
            # Register bold font
            try:
                if dejavu_bold.exists():
                    if 'DejaVuSans-Bold' not in self._registered_fonts:
                        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', str(dejavu_bold)))
                        self._registered_fonts.add('DejaVuSans-Bold')
                        logger.info(f"✅ Registered DejaVuSans-Bold from: {dejavu_bold}")
                else:
                    # Use regular font as bold if bold not found
                    logger.warning("⚠️ DejaVuSans-Bold.ttf not found, using regular font")
                    if 'DejaVuSans-Bold' not in self._registered_fonts:
                        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', str(dejavu_regular)))
                        self._registered_fonts.add('DejaVuSans-Bold')
            except Exception as e:
                if 'already registered' not in str(e).lower():
                    raise
                self._registered_fonts.add('DejaVuSans-Bold')
            
            logger.info("✅ DejaVu fonts registered successfully")
            return True
                
        except Exception as e:
            logger.error(f"❌ Font setup error: {e}", exc_info=True)
            logger.warning("Vietnamese text may not display correctly")
            return False
    
    def get_company_info(self, warehouse_id: int) -> Dict[str, Any]:
        """Get company information from warehouse - matches actual schema"""
        query = """
            SELECT 
                c.id,
                c.english_name,
                c.local_name,
                c.street as address,
                c.tax_number,
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
        
        # Fallback data
        return {
            'id': 0,
            'english_name': 'PROSTECH VIETNAM',
            'local_name': 'CÔNG TY TNHH PROSTECH VIỆT NAM',
            'address': 'Vietnam',
            'tax_number': '',
            'logo_path': None
        }
    
    def get_custom_styles(self) -> Dict[str, Any]:
        """Create custom paragraph styles with DejaVu fonts"""
        styles = getSampleStyleSheet()
        
        # Use DejaVu fonts if available, otherwise fall back to Helvetica
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
        
        # Normal text style
        styles.add(ParagraphStyle(
            name='NormalViet',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=10,
            leading=12
        ))
        
        # Header info style
        styles.add(ParagraphStyle(
            name='HeaderInfo',
            parent=styles['Normal'],
            fontName=base_font,
            fontSize=9,
            leading=11,
            alignment=TA_LEFT
        ))
        
        # Company info style (for header)
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
    
    def validate_issue_data(self, issue_id: int) -> bool:
        """Validate that issue has all required data"""
        try:
            # Check if issue exists
            check_query = """
                SELECT COUNT(*) as count 
                FROM material_issues 
                WHERE id = %s
            """
            result = pd.read_sql(check_query, self.engine, params=(issue_id,))
            if result.iloc[0]['count'] == 0:
                logger.error(f"Issue {issue_id} not found")
                return False
            
            # Check if has details
            details_query = """
                SELECT COUNT(*) as count 
                FROM material_issue_details 
                WHERE material_issue_id = %s
            """
            result = pd.read_sql(details_query, self.engine, params=(issue_id,))
            if result.iloc[0]['count'] == 0:
                logger.error(f"Issue {issue_id} has no details")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating issue data: {e}")
            return False
    
    def get_issue_data(self, issue_id: int) -> Dict[str, Any]:
        """Get material issue data from database - FIXED to match actual schema"""
        # Main issue info
        issue_query = """
            SELECT 
                mi.id,
                mi.issue_no,
                mi.issue_date,
                mi.status,
                mi.notes,
                mo.order_no,
                mo.product_id,
                p.name as product_name,
                mo.planned_qty,
                mo.uom as product_uom,
                w.name as warehouse_name,
                w.id as warehouse_id,
                CONCAT(u.username, ' - ', COALESCE(e.first_name, ''), ' ', COALESCE(e.last_name, '')) as issued_by
            FROM material_issues mi
            JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            JOIN warehouses w ON mi.warehouse_id = w.id
            LEFT JOIN users u ON mi.issued_by = u.id
            LEFT JOIN employees e ON u.employee_id = e.id
            WHERE mi.id = %s
        """
        
        issue_df = pd.read_sql(issue_query, self.engine, params=(issue_id,))
        if issue_df.empty:
            raise ValueError(f"Issue {issue_id} not found")
        
        issue_info = issue_df.iloc[0].to_dict()
        
        # Issue details - FIXED to work with current schema (products table)
        details_query = """
            SELECT 
                mid.material_id,
                p.name as material_name,
                p.pt_code,
                p.package_size,
                mid.batch_no,
                mid.quantity,
                mid.uom,
                mid.expired_date,
                -- Check if columns exist, otherwise use defaults
                COALESCE(mid.is_alternative, 0) as is_alternative,
                mid.original_material_id,
                op.name as original_material_name
            FROM material_issue_details mid
            JOIN products p ON mid.material_id = p.id
            LEFT JOIN products op ON mid.original_material_id = op.id
            WHERE mid.material_issue_id = %s
            ORDER BY mid.id
        """
        
        # Try with new columns first, fallback to basic query if fail
        try:
            details_df = pd.read_sql(details_query, self.engine, params=(issue_id,))
        except Exception as e:
            logger.warning(f"New columns not found, using basic query: {e}")
            # Fallback query without new columns
            details_query_basic = """
                SELECT 
                    mid.material_id,
                    p.name as material_name,
                    p.pt_code,
                    p.package_size,
                    mid.batch_no,
                    mid.quantity,
                    mid.uom,
                    mid.expired_date,
                    0 as is_alternative,
                    NULL as original_material_id,
                    NULL as original_material_name
                FROM material_issue_details mid
                JOIN products p ON mid.material_id = p.id
                WHERE mid.material_issue_id = %s
                ORDER BY mid.id
            """
            details_df = pd.read_sql(details_query_basic, self.engine, params=(issue_id,))
        
        return {
            'issue': issue_info,
            'details': details_df.to_dict('records')
        }
    
    def create_header(self, story: list, data: Dict, styles: Any, language: str = 'vi'):
        """Create PDF header with company info and logo"""
        company_info = self.get_company_info(data['issue']['warehouse_id'])
        
        # Try to get logo with enhanced function
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
                        logger.error(f"Error creating image from bytes: {img_error}")
            except Exception as e:
                logger.warning(f"Could not load logo: {e}")
        
        # Company name and info
        company_name = company_info.get('local_name', company_info.get('english_name', ''))
        company_address = company_info.get('address', '')
        tax_number = company_info.get('tax_number', '')
        
        if logo_img:
            # With logo
            header_data = [[
                logo_img,
                Paragraph(f"""
                    <b>{company_name}</b><br/>
                    {company_address}<br/>
                    MST/Tax: {tax_number if tax_number else 'N/A'}
                """, styles['CompanyInfo'])
            ]]
            header_table = Table(header_data, colWidths=[60*mm, 130*mm])
        else:
            # Without logo - text only
            header_data = [[
                Paragraph(f"""
                    <b>{company_name}</b><br/>
                    {company_address}<br/>
                    MST/Tax: {tax_number if tax_number else 'N/A'}
                """, styles['CompanyInfo'])
            ]]
            header_table = Table(header_data, colWidths=[190*mm])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(header_table)
        story.append(Spacer(1, 10*mm))
        
        # Title - FIXED: Vietnamese vs English
        if language == 'vi':
            title = "PHIẾU XUẤT KHO VẬT TƯ SẢN XUẤT"
        else:
            title = "MATERIAL ISSUE SLIP FOR PRODUCTION"
        
        story.append(Paragraph(f"<b>{title}</b>", styles['TitleViet']))
        story.append(Spacer(1, 5*mm))
    
    def create_issue_info(self, story: list, data: Dict, styles: Any, language: str = 'vi'):
        """Create issue information section"""
        issue = data['issue']
        
        # Use DejaVu fonts
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        # FIXED: Vietnamese vs English labels
        if language == 'vi':
            labels = {
                'issue_no': 'Số phiếu xuất:',
                'issue_date': 'Ngày xuất:',
                'order': 'Lệnh sản xuất:',
                'product': 'Sản phẩm:',
                'planned_qty': 'Số lượng kế hoạch:',
                'warehouse': 'Kho:',
                'issued_by': 'Người xuất:'
            }
        else:
            labels = {
                'issue_no': 'Issue No:',
                'issue_date': 'Issue Date:',
                'order': 'Production Order:',
                'product': 'Product:',
                'planned_qty': 'Planned Qty:',
                'warehouse': 'Warehouse:',
                'issued_by': 'Issued By:'
            }
        
        # Format issue date
        issue_date = issue['issue_date']
        if isinstance(issue_date, str):
            issue_date_str = datetime.strptime(issue_date, '%Y-%m-%d').strftime('%d/%m/%Y %H:%M')
        else:
            issue_date_str = issue_date.strftime('%d/%m/%Y %H:%M')
        
        # Create info table
        info_data = [
            [Paragraph(f"<b>{labels['issue_no']}</b>", styles['NormalViet']), 
             Paragraph(issue['issue_no'], styles['NormalViet'])],
            [Paragraph(f"<b>{labels['issue_date']}</b>", styles['NormalViet']), 
             Paragraph(issue_date_str, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['order']}</b>", styles['NormalViet']), 
             Paragraph(issue['order_no'], styles['NormalViet'])],
            [Paragraph(f"<b>{labels['product']}</b>", styles['NormalViet']), 
             Paragraph(issue['product_name'], styles['NormalViet'])],
            [Paragraph(f"<b>{labels['planned_qty']}</b>", styles['NormalViet']), 
             Paragraph(f"{issue['planned_qty']} {issue['product_uom']}", styles['NormalViet'])],
            [Paragraph(f"<b>{labels['warehouse']}</b>", styles['NormalViet']), 
             Paragraph(issue['warehouse_name'], styles['NormalViet'])],
            [Paragraph(f"<b>{labels['issued_by']}</b>", styles['NormalViet']), 
             Paragraph(issue['issued_by'], styles['NormalViet'])],
        ]
        
        info_table = Table(info_data, colWidths=[45*mm, 145*mm])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 8*mm))
    
    def create_materials_table(self, story: list, data: Dict, styles: Any, language: str = 'vi'):
        """Create materials table with proper text wrapping"""
        details = data['details']
        
        # Use DejaVu fonts
        header_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        # FIXED: Vietnamese vs English table headers
        if language == 'vi':
            headers = ['STT', 'Mã VT', 'Tên vật tư', 'Batch/Lot', 'SL', 'ĐVT', 'HSD', 'Ghi chú']
        else:
            headers = ['No.', 'Code', 'Material Name', 'Batch/Lot', 'Qty', 'UOM', 'Expiry', 'Note']
        
        # Create header row with Paragraphs
        header_row = [Paragraph(f"<b>{h}</b>", styles['TableHeader']) for h in headers]
        table_data = [header_row]
        
        # Add detail rows
        for idx, detail in enumerate(details, 1):
            # Format expiry date - FIXED: use expired_date field
            exp_date = ''
            if detail.get('expired_date'):
                if isinstance(detail['expired_date'], str):
                    exp_date = datetime.strptime(detail['expired_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                else:
                    exp_date = detail['expired_date'].strftime('%d/%m/%Y')
            
            # Material name with alternative indicator
            material_name = detail['material_name']
            if detail.get('is_alternative'):
                material_name = f"{material_name} (*)"
            
            # Note field - alternative materials
            note = ''
            if detail.get('is_alternative') and detail.get('original_material_name'):
                if language == 'vi':
                    note = f"Thay cho: {detail['original_material_name']}"
                else:
                    note = f"Alternative for: {detail['original_material_name']}"
            
            # CRITICAL: Wrap long text in Paragraph to prevent overflow
            # FIXED: Use pt_code and batch_no fields
            row = [
                Paragraph(str(idx), styles['TableCellCenter']),
                Paragraph(detail.get('pt_code', ''), styles['TableCellCenter']),
                Paragraph(material_name, styles['TableCell']),  # Wrapped
                Paragraph(detail.get('batch_no', ''), styles['TableCellCenter']),
                Paragraph(f"{detail['quantity']:.4f}", styles['TableCellCenter']),
                Paragraph(detail['uom'], styles['TableCellCenter']),
                Paragraph(exp_date, styles['TableCellCenter']),
                Paragraph(note if note else '', styles['TableCell'])  # Wrapped
            ]
            table_data.append(row)
        
        # Create table with adjusted column widths
        materials_table = Table(table_data, colWidths=[
            10*mm,  # No.
            22*mm,  # Code
            52*mm,  # Name
            22*mm,  # Batch
            18*mm,  # Qty
            12*mm,  # UOM
            20*mm,  # Expiry
            34*mm   # Note
        ])
        
        # Enhanced table style
        materials_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),  # Material name left aligned
            ('ALIGN', (7, 1), (7, -1), 'LEFT'),  # Note left aligned
            ('FONTNAME', (0, 0), (-1, 0), header_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(materials_table)
        
        # Add note if there are substitutions
        if any(d.get('is_alternative') for d in details):
            story.append(Spacer(1, 5*mm))
            if language == 'vi':
                note_text = "(*) Vật tư thay thế được sử dụng do không đủ vật tư chính"
            else:
                note_text = "(*) Alternative materials used due to insufficient primary materials"
            story.append(Paragraph(f"<i>{note_text}</i>", styles['Footer']))
    
    def create_signature_section(self, story: list, styles: Any, language: str = 'vi'):
        """Create signature section"""
        sig_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        if language == 'vi':
            sig_headers = ['Người xuất', 'Người nhận', 'Giám sát']
            sig_labels = ['Ký, họ tên', 'Ký, họ tên', 'Ký, họ tên']
            date_label = 'Ngày:'
        else:
            sig_headers = ['Issued By', 'Received By', 'Supervisor']
            sig_labels = ['Sign & Name', 'Sign & Name', 'Sign & Name']
            date_label = 'Date:'
        
        sig_data = [
            sig_headers,
            ['', '', ''],
            ['', '', ''],
            ['', '', ''],
            ['_____________', '_____________', '_____________'],
            sig_labels,
            [f'{date_label} ___/___/_____', f'{date_label} ___/___/_____', f'{date_label} ___/___/_____']
        ]
        
        sig_table = Table(sig_data, colWidths=[60*mm, 60*mm, 60*mm])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 1), sig_font),
            ('FONTNAME', (0, 2), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('LINEBELOW', (0, 4), (-1, 4), 0.5, colors.black),
            ('FONTSIZE', (0, -1), (-1, -1), 8),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(Spacer(1, 15*mm))
        story.append(sig_table)
    
    def generate_pdf(self, issue_id: int, language: str = 'vi') -> Optional[bytes]:
        """
        Generate PDF for material issue
        
        Args:
            issue_id: Material issue ID
            language: 'vi' for Vietnamese, 'en' for English
            
        Returns:
            PDF content as bytes or None if failed
        """
        try:
            logger.info(f"🔧 Generating PDF for issue {issue_id} with language: {language}")
            
            # Validate data first
            if not self.validate_issue_data(issue_id):
                logger.error(f"Invalid issue data for ID {issue_id}")
                return None
            
            # Get data
            data = self.get_issue_data(issue_id)
            
            # Create PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=10*mm,
                leftMargin=10*mm,
                topMargin=10*mm,
                bottomMargin=10*mm
            )
            
            # Build story
            story = []
            styles = self.get_custom_styles()
            
            # Add content
            self.create_header(story, data, styles, language)
            self.create_issue_info(story, data, styles, language)
            self.create_materials_table(story, data, styles, language)
            
            # Notes section if exists
            if data['issue'].get('notes'):
                story.append(Spacer(1, 5*mm))
                if language == 'vi':
                    story.append(Paragraph(f"<b>Ghi chú:</b> {data['issue']['notes']}", 
                                         styles['NormalViet']))
                else:
                    story.append(Paragraph(f"<b>Notes:</b> {data['issue']['notes']}", 
                                         styles['NormalViet']))
                story.append(Spacer(1, 10*mm))
            
            # Signature section
            logger.info(f"🔧 Creating signature section with language: {language}")
            self.create_signature_section(story, styles, language)
            
            # Footer
            story.append(Spacer(1, 10*mm))
            footer_text = f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            story.append(Paragraph(footer_text, styles['Footer']))
            
            # Build PDF
            doc.build(story)
            
            # Get PDF bytes
            pdf_bytes = buffer.getvalue()
            buffer.close()
            
            logger.info(f"✅ PDF generated successfully for issue {issue_id} (language: {language})")
            return pdf_bytes
            
        except Exception as e:
            logger.error(f"❌ Failed to generate PDF for issue {issue_id}: {e}", exc_info=True)
            return None
    
    def generate_pdf_with_options(self, issue_id: int, 
                                 options: Dict[str, Any]) -> Optional[bytes]:
        """
        Generate PDF with custom options
        
        Args:
            issue_id: Material issue ID
            options: Dictionary with options:
                - language: 'vi' or 'en'
                - include_signatures: bool
                
        Returns:
            PDF bytes or None if failed
        """
        language = options.get('language', 'vi')
        include_signatures = options.get('include_signatures', True)
        
        logger.info(f"🔧 generate_pdf_with_options called with language: {language}, include_signatures: {include_signatures}")
        
        # Generate standard PDF (signature control can be added later if needed)
        return self.generate_pdf(issue_id, language)


# Create singleton instance
pdf_generator = MaterialIssuePDFGenerator()