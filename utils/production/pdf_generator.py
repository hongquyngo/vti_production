# utils/production/pdf_generator.py
"""
PDF Generator for Material Issues with Multi-language Support - REFACTORED v5.3
FIXED: Font loading from project fonts/ directory for Streamlit Cloud deployment

CHANGES v5.3:
- ✅ NEW: Consolidated material info column (Name, Code, Batch, Size in one column)
- ✅ NEW: Added Return Quantity column (SL Trả) before Note
- ✅ ADJUSTED: Column widths for better layout

CHANGES v5.2:
- ✅ NEW: Display package_size under material name in table
- ✅ Format: Material Name<br/>(package_size)

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
        # Main issue info - FIXED: issued_by/received_by are employee_id, created_by is user_id
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
                -- Người xuất kho (warehouse staff)
                mi.issued_by as issued_by_id,
                COALESCE(
                    TRIM(CONCAT(COALESCE(e_issued.first_name, ''), ' ', COALESCE(e_issued.last_name, ''))),
                    'N/A'
                ) as issued_by_name,
                -- Người nhận (production staff)
                mi.received_by as received_by_id,
                COALESCE(
                    TRIM(CONCAT(COALESCE(e_received.first_name, ''), ' ', COALESCE(e_received.last_name, ''))),
                    ''
                ) as received_by_name,
                -- Người lập phiếu (user who created the document)
                mi.created_by as created_by_id,
                COALESCE(u.username, 'N/A') as created_by_username,
                COALESCE(
                    TRIM(CONCAT(COALESCE(e_created.first_name, ''), ' ', COALESCE(e_created.last_name, ''))),
                    u.username
                ) as created_by_name,
                mi.created_date
            FROM material_issues mi
            JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
            JOIN products p ON mo.product_id = p.id
            JOIN warehouses w ON mi.warehouse_id = w.id
            -- Join for issued_by (employee)
            LEFT JOIN employees e_issued ON mi.issued_by = e_issued.id
            -- Join for received_by (employee)
            LEFT JOIN employees e_received ON mi.received_by = e_received.id
            -- Join for created_by (user -> employee)
            LEFT JOIN users u ON mi.created_by = u.id
            LEFT JOIN employees e_created ON u.employee_id = e_created.id
            WHERE mi.id = %s
        """
        
        issue_df = pd.read_sql(issue_query, self.engine, params=(issue_id,))
        if issue_df.empty:
            raise ValueError(f"Issue {issue_id} not found")
        
        issue_info = issue_df.iloc[0].to_dict()
        
        # Issue details
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
                COALESCE(mid.is_alternative, 0) as is_alternative,
                mid.original_material_id,
                op.name as original_material_name
            FROM material_issue_details mid
            JOIN products p ON mid.material_id = p.id
            LEFT JOIN products op ON mid.original_material_id = op.id
            WHERE mid.material_issue_id = %s
            ORDER BY mid.id
        """
        
        try:
            details_df = pd.read_sql(details_query, self.engine, params=(issue_id,))
        except Exception as e:
            logger.warning(f"New columns not found, using basic query: {e}")
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

    def create_header(self, story: list, data: Dict, styles: Any, language: str = 'vi', layout: str = 'landscape'):
        """Create PDF header with company info and logo"""
        company_info = self.get_company_info(data['issue']['warehouse_id'])
        
        # Calculate page width based on layout
        if layout == 'landscape':
            page_width = 277*mm  # A4 landscape width minus margins
        else:
            page_width = 190*mm  # A4 portrait width minus margins
        
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
            header_table = Table(header_data, colWidths=[60*mm, page_width - 60*mm])
        else:
            # Without logo - text only
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
            title = "PHIẾU XUẤT KHO VẬT TƯ SẢN XUẤT"
        else:
            title = "MATERIAL ISSUE SLIP FOR PRODUCTION"
        
        story.append(Paragraph(f"<b>{title}</b>", styles['TitleViet']))
        story.append(Spacer(1, 5*mm))


    def create_issue_info(self, story: list, data: Dict, styles: Any, language: str = 'vi', layout: str = 'landscape'):
        """Create issue information section with clear issued/received/created info"""
        issue = data['issue']
        
        # Use DejaVu fonts
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        # Calculate widths based on layout
        if layout == 'landscape':
            left_label_width = 45*mm
            left_value_width = 90*mm
            right_label_width = 40*mm
            right_value_width = 90*mm
        else:
            left_label_width = 40*mm
            left_value_width = 50*mm
            right_label_width = 35*mm
            right_value_width = 55*mm
        
        # Vietnamese vs English labels
        if language == 'vi':
            labels = {
                'issue_no': 'Số phiếu xuất:',
                'issue_date': 'Ngày xuất:',
                'order': 'Lệnh sản xuất:',
                'product': 'Sản phẩm:',
                'planned_qty': 'Số lượng kế hoạch:',
                'warehouse': 'Kho xuất:',
                'issued_by': 'Người xuất kho:',
                'received_by': 'Người nhận:',
                'created_by': 'Người lập phiếu:',
                'created_date': 'Ngày lập:'
            }
        else:
            labels = {
                'issue_no': 'Issue No:',
                'issue_date': 'Issue Date:',
                'order': 'Production Order:',
                'product': 'Product:',
                'planned_qty': 'Planned Qty:',
                'warehouse': 'Warehouse:',
                'issued_by': 'Issued By:',
                'received_by': 'Received By:',
                'created_by': 'Created By:',
                'created_date': 'Created Date:'
            }
        
        # Format issue date
        issue_date = issue['issue_date']
        if isinstance(issue_date, str):
            try:
                issue_date_str = datetime.strptime(issue_date, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
            except:
                issue_date_str = datetime.strptime(issue_date, '%Y-%m-%d').strftime('%d/%m/%Y')
        else:
            issue_date_str = issue_date.strftime('%d/%m/%Y %H:%M')
        
        # Format created date
        created_date = issue.get('created_date')
        if created_date:
            if isinstance(created_date, str):
                try:
                    created_date_str = datetime.strptime(created_date, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
                except:
                    created_date_str = created_date
            else:
                created_date_str = created_date.strftime('%d/%m/%Y %H:%M')
        else:
            created_date_str = 'N/A'
        
        # Get names with fallback
        issued_by_name = issue.get('issued_by_name', 'N/A') or 'N/A'
        received_by_name = issue.get('received_by_name', '') or ''
        created_by_name = issue.get('created_by_name', 'N/A') or 'N/A'
        
        # Create info table - Left column
        left_data = [
            [Paragraph(f"<b>{labels['issue_no']}</b>", styles['NormalViet']), 
            Paragraph(str(issue['issue_no']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['issue_date']}</b>", styles['NormalViet']), 
            Paragraph(issue_date_str, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['order']}</b>", styles['NormalViet']), 
            Paragraph(str(issue['order_no']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['product']}</b>", styles['NormalViet']), 
            Paragraph(str(issue['product_name']), styles['NormalViet'])],
            [Paragraph(f"<b>{labels['planned_qty']}</b>", styles['NormalViet']), 
            Paragraph(f"{issue['planned_qty']} {issue['product_uom']}", styles['NormalViet'])],
            [Paragraph(f"<b>{labels['warehouse']}</b>", styles['NormalViet']), 
            Paragraph(str(issue['warehouse_name']), styles['NormalViet'])],
        ]
        
        # Create info table - Right column (personnel info)
        right_data = [
            [Paragraph(f"<b>{labels['issued_by']}</b>", styles['NormalViet']), 
            Paragraph(issued_by_name, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['received_by']}</b>", styles['NormalViet']), 
            Paragraph(received_by_name if received_by_name else '-', styles['NormalViet'])],
            [Paragraph(f"<b>{labels['created_by']}</b>", styles['NormalViet']), 
            Paragraph(created_by_name, styles['NormalViet'])],
            [Paragraph(f"<b>{labels['created_date']}</b>", styles['NormalViet']), 
            Paragraph(created_date_str, styles['NormalViet'])],
        ]
        
        # Create two-column layout
        left_table = Table(left_data, colWidths=[left_label_width, left_value_width])
        left_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        right_table = Table(right_data, colWidths=[right_label_width, right_value_width])
        right_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        # Combine into main table
        total_left = left_label_width + left_value_width
        total_right = right_label_width + right_value_width
        main_table = Table([[left_table, right_table]], colWidths=[total_left, total_right])
        main_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        story.append(main_table)
        story.append(Spacer(1, 8*mm))


    def create_materials_table(self, story: list, data: Dict, styles: Any, language: str = 'vi', layout: str = 'landscape'):
        """Create materials table with consolidated material info column"""
        details = data['details']
        
        # Use DejaVu fonts
        header_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        # Vietnamese vs English table headers (consolidated layout)
        if language == 'vi':
            headers = ['STT', 'Thông tin vật tư', 'SL', 'ĐVT', 'HSD', 'SL Trả', 'Ghi chú']
        else:
            headers = ['No.', 'Material Info', 'Qty', 'UOM', 'Expiry', 'Return', 'Note']
        
        # Create header row with Paragraphs
        header_row = [Paragraph(f"<b>{h}</b>", styles['TableHeader']) for h in headers]
        table_data = [header_row]
        
        # Labels for material info
        if language == 'vi':
            lbl_name = "Tên VT"
            lbl_code = "Mã VT"
            lbl_batch = "Batch"
            lbl_size = "Size"
        else:
            lbl_name = "Name"
            lbl_code = "Code"
            lbl_batch = "Batch"
            lbl_size = "Size"
        
        # Add detail rows
        for idx, detail in enumerate(details, 1):
            # Format expiry date
            exp_date = ''
            if detail.get('expired_date'):
                if isinstance(detail['expired_date'], str):
                    exp_date = datetime.strptime(detail['expired_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                else:
                    exp_date = detail['expired_date'].strftime('%d/%m/%Y')
            
            # Build consolidated material info
            mat_name = detail['material_name']
            pt_code = detail.get('pt_code', '')
            batch_no = detail.get('batch_no', '')
            package_size = detail.get('package_size', '')
            
            # Add alternative indicator
            if detail.get('is_alternative'):
                mat_name = f"(*) {mat_name}"
            
            # Build multi-line material info
            mat_info_lines = [f"<b>{lbl_name}:</b> {mat_name}"]
            if pt_code:
                mat_info_lines.append(f"<b>{lbl_code}:</b> {pt_code}")
            if batch_no:
                mat_info_lines.append(f"<b>{lbl_batch}:</b> {batch_no}")
            if package_size:
                mat_info_lines.append(f"<b>{lbl_size}:</b> {package_size}")
            
            mat_info = "<br/>".join(mat_info_lines)
            
            # Format quantity
            qty = detail['quantity']
            if isinstance(qty, (int, float, Decimal)):
                qty_str = f"{float(qty):,.2f}".rstrip('0').rstrip('.')
            else:
                qty_str = str(qty)
            
            row = [
                Paragraph(str(idx), styles['TableCellCenter']),
                Paragraph(mat_info, styles['TableCell']),
                Paragraph(qty_str, styles['TableCellCenter']),
                Paragraph(str(detail['uom']), styles['TableCellCenter']),
                Paragraph(exp_date, styles['TableCellCenter']),
                Paragraph('', styles['TableCellCenter']),  # Return Qty - empty for manual entry
                Paragraph('', styles['TableCell'])  # Note column for manual entry
            ]
            table_data.append(row)
        
        # Set column widths based on layout
        if layout == 'landscape':
            # Landscape: wider material info column
            col_widths = [
                12*mm,   # No.
                130*mm,  # Material Info (consolidated - wider)
                22*mm,   # Qty
                15*mm,   # UOM
                25*mm,   # Expiry
                25*mm,   # Return Qty
                38*mm    # Note
            ]
        else:
            # Portrait: narrower columns
            col_widths = [
                10*mm,   # No.
                85*mm,   # Material Info (consolidated)
                18*mm,   # Qty
                12*mm,   # UOM
                20*mm,   # Expiry
                20*mm,   # Return Qty
                25*mm    # Note
            ]
        
        materials_table = Table(table_data, colWidths=col_widths)
        
        # Enhanced table style
        materials_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),  # Material info left aligned
            ('ALIGN', (6, 1), (6, -1), 'LEFT'),  # Note left aligned
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


    def create_signature_section(self, story: list, data: Dict, styles: Any, language: str = 'vi', layout: str = 'landscape'):
        """Create signature section with pre-filled names from data"""
        sig_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        issue = data['issue']
        
        # Get names from data
        issued_by_name = issue.get('issued_by_name', '') or ''
        received_by_name = issue.get('received_by_name', '') or ''
        
        if language == 'vi':
            sig_headers = ['Người xuất kho', 'Người nhận', 'Giám sát']
            sig_labels = ['(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)', '(Ký, ghi rõ họ tên)']
        else:
            sig_headers = ['Issued By', 'Received By', 'Supervisor']
            sig_labels = ['(Sign & Full Name)', '(Sign & Full Name)', '(Sign & Full Name)']
        
        sig_data = [
            # Headers
            [Paragraph(f"<b>{sig_headers[0]}</b>", styles['NormalViet']),
            Paragraph(f"<b>{sig_headers[1]}</b>", styles['NormalViet']),
            Paragraph(f"<b>{sig_headers[2]}</b>", styles['NormalViet'])],
            # Empty space for signature
            ['', '', ''],
            ['', '', ''],
            ['', '', ''],
            # Signature line
            ['_________________', '_________________', '_________________'],
            # Pre-filled names
            [Paragraph(f"<b>{issued_by_name}</b>", styles['NormalViet']) if issued_by_name else '',
            Paragraph(f"<b>{received_by_name}</b>", styles['NormalViet']) if received_by_name else '',
            ''],
            # Labels
            [Paragraph(f"<i>{sig_labels[0]}</i>", styles['Footer']),
            Paragraph(f"<i>{sig_labels[1]}</i>", styles['Footer']),
            Paragraph(f"<i>{sig_labels[2]}</i>", styles['Footer'])],
        ]
        
        # Set column widths based on layout
        if layout == 'landscape':
            sig_col_width = 85*mm  # Wider for landscape
        else:
            sig_col_width = 60*mm  # Portrait
        
        sig_table = Table(sig_data, colWidths=[sig_col_width, sig_col_width, sig_col_width])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), sig_font),
            ('FONTNAME', (0, 1), (-1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(Spacer(1, 15*mm))
        story.append(sig_table)


    def generate_pdf(self, issue_id: int, language: str = 'vi', layout: str = 'landscape') -> Optional[bytes]:
        """
        Generate PDF for material issue
        
        Args:
            issue_id: Material issue ID
            language: 'vi' for Vietnamese, 'en' for English
            layout: 'landscape' or 'portrait' (default: landscape)
            
        Returns:
            PDF content as bytes or None if failed
        """
        try:
            logger.info(f"🔧 Generating PDF for issue {issue_id} with language: {language}, layout: {layout}")
            
            # Validate data first
            if not self.validate_issue_data(issue_id):
                logger.error(f"Invalid issue data for ID {issue_id}")
                return None
            
            # Get data
            data = self.get_issue_data(issue_id)
            
            # Set page size based on layout
            if layout == 'landscape':
                from reportlab.lib.pagesizes import A4, landscape
                page_size = landscape(A4)
            else:
                from reportlab.lib.pagesizes import A4
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
            
            # Build story
            story = []
            styles = self.get_custom_styles()
            
            # Add content - pass layout for responsive sizing
            self.create_header(story, data, styles, language, layout)
            self.create_issue_info(story, data, styles, language, layout)
            self.create_materials_table(story, data, styles, language, layout)
            
            # Notes section if exists
            if data['issue'].get('notes'):
                story.append(Spacer(1, 5*mm))
                if language == 'vi':
                    notes_label = "Ghi chú:"
                else:
                    notes_label = "Notes:"
                story.append(Paragraph(f"<b>{notes_label}</b> {data['issue']['notes']}", styles['NormalViet']))
            
            # Signature section
            self.create_signature_section(story, data, styles, language, layout)
            
            # Build PDF
            doc.build(story)
            
            pdf_content = buffer.getvalue()
            buffer.close()
            
            logger.info(f"✅ PDF generated successfully for issue {issue_id}, size: {len(pdf_content)} bytes")
            return pdf_content
            
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