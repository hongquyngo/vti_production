# utils/production/pdf_generator.py
"""
PDF Generator for Material Issues with Multi-language Support - REFACTORED v5.0
FIXED: Vietnamese font support + Cell text wrapping + Table overflow

CHANGES v5.0:
- ✅ CRITICAL FIX: Use DejaVuSans for ALL text (not Helvetica) - fixes Vietnamese display
- ✅ CRITICAL FIX: Wrap long text (Material Name, Note) in Paragraph objects - prevents cell overflow
- ✅ Enhanced table padding and layout for better readability
- ✅ Improved font fallback mechanism
- ✅ All existing features preserved
"""

import logging
import os
from datetime import datetime
from typing import Dict, Optional, Any, List
from io import BytesIO
import uuid
import pandas as pd
from decimal import Decimal

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
        self.font_available = self._setup_fonts()
    
    def _setup_fonts(self) -> bool:
        """Setup fonts for PDF with proper fallback - returns True if DejaVu fonts registered"""
        try:
            # Try multiple possible font locations
            font_paths = [
                "fonts/",
                "/usr/share/fonts/truetype/dejavu/",
                os.path.join(os.path.dirname(__file__), "fonts/"),
                "/app/fonts/",  # For Docker
                "/usr/share/fonts/",
                os.path.expanduser("~/.fonts/")
            ]
            
            font_registered = False
            for path in font_paths:
                if os.path.exists(path):
                    try:
                        # Look for DejaVu fonts
                        dejavu_path = os.path.join(path, 'DejaVuSans.ttf')
                        dejavu_bold_path = os.path.join(path, 'DejaVuSans-Bold.ttf')
                        
                        # Also check in subdirectories
                        if not os.path.exists(dejavu_path):
                            for subdir in ['truetype/dejavu', 'dejavu', 'truetype']:
                                test_path = os.path.join(path, subdir, 'DejaVuSans.ttf')
                                if os.path.exists(test_path):
                                    dejavu_path = test_path
                                    dejavu_bold_path = os.path.join(path, subdir, 'DejaVuSans-Bold.ttf')
                                    break
                        
                        if os.path.exists(dejavu_path):
                            if not pdfmetrics.registered('DejaVuSans'):
                                pdfmetrics.registerFont(TTFont('DejaVuSans', dejavu_path))
                                if os.path.exists(dejavu_bold_path):
                                    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', dejavu_bold_path))
                                else:
                                    # Use regular font as bold if bold not found
                                    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', dejavu_path))
                                logger.info(f"✅ DejaVu fonts registered successfully from: {path}")
                                font_registered = True
                                break
                    except Exception as e:
                        logger.warning(f"Failed to register fonts from {path}: {e}")
            
            if not font_registered:
                logger.warning("⚠️ DejaVu fonts not found - Vietnamese text may not display correctly")
                logger.warning("Consider installing: sudo apt-get install fonts-dejavu")
                return False
            
            return True
                
        except Exception as e:
            logger.error(f"Font setup error: {e}")
            return False
    
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
        """Get material issue data from database - FIXED SCHEMA"""
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
        
        # Issue details - FIXED to work with current schema
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
    
    def get_custom_styles(self):
        """Get custom paragraph styles with Vietnamese font support"""
        styles = getSampleStyleSheet()
        
        # FIXED: Determine font to use - prefer DejaVu for Vietnamese support
        if self.font_available and pdfmetrics.registered('DejaVuSans'):
            base_font = 'DejaVuSans'
            bold_font = 'DejaVuSans-Bold'
            logger.debug("Using DejaVu fonts for Vietnamese support")
        else:
            base_font = 'Helvetica'
            bold_font = 'Helvetica-Bold'
            logger.warning("Falling back to Helvetica - Vietnamese may not display correctly")
        
        # Title style
        styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=styles['Title'],
            fontSize=16,
            textColor=colors.HexColor('#1f4788'),
            fontName=bold_font,
            alignment=TA_CENTER
        ))
        
        # Company info style
        styles.add(ParagraphStyle(
            name='CompanyInfo',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            fontName=base_font
        ))
        
        # Section header style
        styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#333333'),
            fontName=bold_font,
            spaceAfter=6
        ))
        
        # Normal Vietnamese style
        styles.add(ParagraphStyle(
            name='NormalViet',
            parent=styles['Normal'],
            fontSize=10,
            fontName=base_font
        ))
        
        # FIXED: Table cell style for wrapping text
        styles.add(ParagraphStyle(
            name='TableCell',
            parent=styles['Normal'],
            fontSize=9,
            fontName=base_font,
            leading=11,  # Line height
            alignment=TA_LEFT
        ))
        
        # Table cell centered
        styles.add(ParagraphStyle(
            name='TableCellCenter',
            parent=styles['Normal'],
            fontSize=9,
            fontName=base_font,
            leading=11,
            alignment=TA_CENTER
        ))
        
        # Footer style
        styles.add(ParagraphStyle(
            name='Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.gray,
            alignment=TA_CENTER,
            fontName=base_font
        ))
        
        return styles
    
    def get_company_info(self, warehouse_id: int) -> Dict[str, Any]:
        """Get company information from warehouse"""
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
        
        return {
            'id': 0,
            'english_name': 'PROSTECH VIETNAM',
            'local_name': 'CÔNG TY TNHH PROSTECH VIỆT NAM',
            'address': 'Vietnam',
            'tax_number': '',
            'logo_path': None
        }
    
    def create_header(self, story: list, data: Dict[str, Any], 
                     styles: Any, language: str = 'vi'):
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
        else:
            # Without logo - text only
            header_data = [[
                Paragraph(f"""
                    <b>{company_name}</b><br/>
                    {company_address}<br/>
                    MST/Tax: {tax_number if tax_number else 'N/A'}
                """, styles['CompanyInfo'])
            ]]
        
        header_table = Table(header_data, colWidths=[60*mm, 130*mm] if logo_img else [190*mm])
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
        
        story.append(Paragraph(title, styles['CustomTitle']))
        story.append(Spacer(1, 8*mm))
    
    def create_issue_info(self, story: list, data: Dict[str, Any], 
                         styles: Any, language: str = 'vi'):
        """Create issue information section"""
        issue = data['issue']
        
        # Format date
        issue_date = issue['issue_date']
        if isinstance(issue_date, str):
            issue_date = datetime.strptime(issue_date, '%Y-%m-%d %H:%M:%S')
        formatted_date = issue_date.strftime('%d/%m/%Y %H:%M')
        
        # FIXED: Use DejaVu font (from styles) instead of hardcoded Helvetica
        base_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        # Issue info table
        if language == 'vi':
            info_data = [
                ['Số phiếu / Issue No:', issue['issue_no']],
                ['Ngày xuất / Issue Date:', formatted_date],
                ['Lệnh SX / Production Order:', issue['order_no']],
                ['Sản phẩm / Product:', issue['product_name']],
                ['SL kế hoạch / Planned Qty:', f"{issue['planned_qty']} {issue['product_uom']}"],
                ['Kho xuất / Warehouse:', issue['warehouse_name']],
                ['Người xuất / Issued By:', issue.get('issued_by', 'N/A')],
            ]
        else:
            info_data = [
                ['Issue No:', issue['issue_no']],
                ['Issue Date:', formatted_date],
                ['Production Order:', issue['order_no']],
                ['Product:', issue['product_name']],
                ['Planned Qty:', f"{issue['planned_qty']} {issue['product_uom']}"],
                ['Warehouse:', issue['warehouse_name']],
                ['Issued By:', issue.get('issued_by', 'N/A')],
            ]
        
        info_table = Table(info_data, colWidths=[60*mm, 130*mm])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), base_font),  # FIXED: Use DejaVu
            ('FONTNAME', (1, 0), (1, -1), normal_font),  # FIXED: Use DejaVu
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),  # Increased padding
            ('TOPPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 10*mm))
    
    def create_materials_table(self, story: list, data: Dict[str, Any], 
                              styles: Any, language: str = 'vi'):
        """Create materials table with substitution info - FIXED CELL WRAPPING"""
        details = data['details']
        
        # Table headers
        if language == 'vi':
            headers = ['STT', 'Mã VT', 'Tên vật tư', 'Batch/Lot', 'SL', 'ĐVT', 'HSD', 'Ghi chú']
        else:
            headers = ['No.', 'Code', 'Material Name', 'Batch/Lot', 'Qty', 'UOM', 'Expiry', 'Note']
        
        # FIXED: Use DejaVu font for header
        header_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        # Create header as Paragraphs for font consistency
        header_row = [Paragraph(f'<b>{h}</b>', styles['TableCellCenter']) for h in headers]
        table_data = [header_row]
        
        for idx, detail in enumerate(details, 1):
            # Format expiry date
            exp_date = detail.get('expired_date', '')
            if exp_date and exp_date != 'None':
                if isinstance(exp_date, str):
                    try:
                        exp_date = datetime.strptime(exp_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        try:
                            exp_date = datetime.strptime(exp_date, '%Y-%m-%d')
                        except:
                            exp_date = ''
                if exp_date:
                    exp_date = exp_date.strftime('%d/%m/%Y')
            else:
                exp_date = 'N/A'
            
            # Check if alternative
            note = ''
            material_name = detail['material_name']
            if detail.get('is_alternative') and detail.get('original_material_name'):
                if language == 'vi':
                    note = f"Thay thế cho: {detail['original_material_name']}"
                else:
                    note = f"Substitute for: {detail['original_material_name']}"
                material_name = f"* {material_name}"  # Mark with asterisk
            
            # CRITICAL FIX: Wrap long text in Paragraph objects to prevent cell overflow
            row = [
                Paragraph(str(idx), styles['TableCellCenter']),
                Paragraph(detail.get('pt_code', 'N/A'), styles['TableCellCenter']),
                Paragraph(material_name, styles['TableCell']),  # FIXED: Wrapped in Paragraph
                Paragraph(detail.get('batch_no', 'N/A'), styles['TableCellCenter']),
                Paragraph(f"{detail['quantity']:,.2f}", styles['TableCellCenter']),
                Paragraph(detail['uom'], styles['TableCellCenter']),
                Paragraph(exp_date, styles['TableCellCenter']),
                Paragraph(note if note else '', styles['TableCell'])  # FIXED: Wrapped in Paragraph
            ]
            table_data.append(row)
        
        # Create table with adjusted column widths
        materials_table = Table(table_data, colWidths=[
            10*mm,  # STT
            22*mm,  # Code
            52*mm,  # Name - slightly reduced to fit better
            22*mm,  # Batch
            18*mm,  # Qty
            12*mm,  # UOM
            20*mm,  # Expiry
            34*mm   # Note - slightly increased for wrapped text
        ])
        
        # FIXED: Enhanced table style with better padding
        materials_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),  # Material name left aligned
            ('ALIGN', (7, 1), (7, -1), 'LEFT'),  # Note left aligned
            ('FONTNAME', (0, 0), (-1, 0), header_font),  # FIXED: Use DejaVu
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # FIXED: TOP alignment for wrapped text
            ('TOPPADDING', (0, 0), (-1, -1), 4),  # Increased padding
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
        # FIXED: Use DejaVu font for signatures
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
            ('FONTNAME', (0, 0), (-1, 1), sig_font),  # FIXED: Use DejaVu
            ('FONTNAME', (0, 2), (-1, -1), normal_font),  # FIXED: Use DejaVu
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
        Generate PDF for material issue with error handling
        
        Args:
            issue_id: Material issue ID
            language: 'vi' for Vietnamese, 'en' for English
            
        Returns:
            PDF content as bytes or None if failed
        """
        try:
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
                - doc_type: 'issue_slip' or 'detailed_report'
                - include_signatures: bool
                - notes: custom notes string
                
        Returns:
            PDF bytes or None if failed
        """
        language = options.get('language', 'vi')
        doc_type = options.get('doc_type', 'issue_slip')
        include_signatures = options.get('include_signatures', True)
        custom_notes = options.get('notes', '')
        
        # For now, generate standard PDF
        # Can be extended for different doc types
        return self.generate_pdf(issue_id, language)


# Create singleton instance
pdf_generator = MaterialIssuePDFGenerator()