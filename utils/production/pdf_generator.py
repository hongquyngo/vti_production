# utils/production/pdf_generator.py
"""
PDF Generator for Material Issues with Multi-language Support
"""

import logging
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
    from ..s3_utils import get_company_logo_from_s3
    S3_AVAILABLE = True
except ImportError as e:
    # Alternative import for testing or when running as standalone
    import sys
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(parent_dir)
    
    try:
        from db import get_db_engine
        from s3_utils import get_company_logo_from_s3
        S3_AVAILABLE = True
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.warning("Could not import S3 utilities - logo functionality disabled")
        S3_AVAILABLE = False
        # Create dummy function
        def get_company_logo_from_s3(company_id, logo_path):
            return None

logger = logging.getLogger(__name__)


class MaterialIssuePDFGenerator:
    """Generate PDF for Material Issue transactions"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self._setup_fonts()
    
    def _setup_fonts(self):
        """Setup fonts for PDF with fallback"""
        try:
            # Try to register Vietnamese fonts
            font_path = "fonts/"
            if not pdfmetrics.registered('DejaVuSans'):
                pdfmetrics.registerFont(TTFont('DejaVuSans', font_path + 'DejaVuSans.ttf'))
                pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', font_path + 'DejaVuSans-Bold.ttf'))
            logger.info("Custom fonts registered successfully")
        except Exception as e:
            logger.warning(f"Could not register custom fonts, using defaults: {e}")
    
    def get_issue_data(self, issue_id: int) -> Dict[str, Any]:
        """Get material issue data from database"""
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
        
        # Issue details
        details_query = """
            SELECT 
                mid.material_id,
                p.name as material_name,
                mid.batch_no,
                mid.quantity,
                mid.uom,
                mid.expired_date,
                mid.is_alternative,
                mid.original_material_id,
                op.name as original_material_name
            FROM material_issue_details mid
            JOIN products p ON mid.material_id = p.id
            LEFT JOIN products op ON mid.original_material_id = op.id
            WHERE mid.material_issue_id = %s
            ORDER BY mid.id
        """
        
        details_df = pd.read_sql(details_query, self.engine, params=(issue_id,))
        
        return {
            'issue': issue_info,
            'details': details_df.to_dict('records')
        }
    
    def get_custom_styles(self):
        """Get custom paragraph styles"""
        styles = getSampleStyleSheet()
        
        # Title style
        styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=styles['Title'],
            fontSize=16,
            textColor=colors.HexColor('#1f4788'),
            fontName='Helvetica-Bold'
        ))
        
        # Company info style
        styles.add(ParagraphStyle(
            name='CompanyInfo',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            fontName='Helvetica'
        ))
        
        # Section header style
        styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#333333'),
            fontName='Helvetica-Bold',
            spaceAfter=6
        ))
        
        # Footer style
        styles.add(ParagraphStyle(
            name='Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.gray,
            alignment=TA_CENTER
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
        
        # Header table data
        header_data = []
        
        # Try to get logo
        logo_img = None
        if company_info.get('logo_path') and S3_AVAILABLE:
            try:
                # Logo path from DB like: company-logo/173613389453-logo.png
                logger.info(f"Attempting to download logo: {company_info['logo_path']}")
                logo_bytes = get_company_logo_from_s3(
                    company_info['id'], 
                    company_info['logo_path']
                )
                if logo_bytes:
                    # Create image from bytes
                    logo_buffer = BytesIO(logo_bytes)
                    try:
                        logo_img = Image(logo_buffer, width=50*mm, height=15*mm, kind='proportional')
                    except Exception as img_error:
                        logger.error(f"Error creating image from bytes: {img_error}")
            except Exception as e:
                logger.error(f"Error loading logo: {e}")
        
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
                    {'MST: ' + tax_number if tax_number else ''}
                """, styles['CompanyInfo'])
            ]]
        else:
            # Without logo - just company name
            header_data = [[
                Paragraph(f"""
                    <b>{company_name}</b><br/>
                    {company_address}<br/>
                    {'MST: ' + tax_number if tax_number else ''}
                """, styles['CompanyInfo'])
            ]]
        
        header_table = Table(header_data, colWidths=[80*mm, 110*mm] if logo_img else [190*mm])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(header_table)
        story.append(Spacer(1, 10*mm))
        
        # Document title
        title = "PHIẾU XUẤT VẬT TƯ" if language == 'vi' else "MATERIAL ISSUE SLIP"
        story.append(Paragraph(title, styles['CustomTitle']))
        story.append(Spacer(1, 5*mm))
    
    def create_issue_info(self, story: list, data: Dict[str, Any], 
                         styles: Any, language: str = 'vi'):
        """Create issue information section"""
        issue = data['issue']
        
        # Format date
        issue_date = issue['issue_date']
        if isinstance(issue_date, str):
            issue_date = datetime.strptime(issue_date, '%Y-%m-%d %H:%M:%S')
        formatted_date = issue_date.strftime('%d/%m/%Y %H:%M')
        
        # Issue information
        info_data = [
            ["Số phiếu / Issue No:", issue['issue_no'], 
             "Ngày / Date:", formatted_date],
            ["Lệnh SX / Production Order:", issue['order_no'],
             "Kho / Warehouse:", issue['warehouse_name']],
            ["Sản phẩm / Product:", issue['product_name'],
             "SL kế hoạch / Planned Qty:", f"{issue['planned_qty']} {issue['product_uom']}"],
            ["Người xuất / Issued by:", issue['issued_by'],
             "Trạng thái / Status:", issue['status']]
        ]
        
        info_table = Table(info_data, colWidths=[45*mm, 50*mm, 45*mm, 50*mm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('BACKGROUND', (2, 0), (2, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 10*mm))
    
    def create_materials_table(self, story: list, data: Dict[str, Any], 
                              styles: Any, language: str = 'vi'):
        """Create materials table"""
        # Table headers
        if language == 'vi':
            headers = ["STT\nNo", "Mã VT\nMaterial Code", "Tên vật liệu\nMaterial Name",
                      "Số lô\nBatch", "SL\nQuantity", "ĐVT\nUOM", "HSD\nExpiry", "Ghi chú\nNotes"]
        else:
            headers = ["No", "Material Code", "Material Name", "Batch", 
                      "Quantity", "UOM", "Expiry Date", "Notes"]
        
        # Prepare table data
        table_data = [headers]
        for i, row in enumerate(data['details'], 1):
            table_data.append([
                str(i),
                str(row['material_id']),
                row['material_name'] or '',
                row['batch_no'] or '',
                f"{row['quantity']:.2f}" if pd.notna(row['quantity']) else '',
                row['uom'] or '',
                row['expired_date'] or '',
                'Vật liệu thay thế' if row.get('is_alternative') else ''
            ])
        
        # Add totals row
        total_items = len(data['details'])
        table_data.append(['', '', f'Tổng/Total: {total_items} items', '', '', '', '', ''])
        
        # Create table
        mat_table = Table(table_data, colWidths=[15*mm, 25*mm, 65*mm, 25*mm, 20*mm, 15*mm, 25*mm, 15*mm])
        mat_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -2), 9),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (3, 1), (5, -1), 'CENTER'),
            
            # Total row
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 3),
            
            # Highlight alternative materials
            *[(('BACKGROUND', (0, i), (-1, i), colors.lightyellow) 
               for i, detail in enumerate(data['details'], 1) 
               if detail.get('is_alternative'))]
        ]))
        
        story.append(Paragraph("CHI TIẾT VẬT LIỆU / MATERIAL DETAILS", styles['SectionHeader']))
        story.append(mat_table)
        story.append(Spacer(1, 10*mm))
    
    def create_signature_section(self, story: list, styles: Any, language: str = 'vi'):
        """Create signature section"""
        if language == 'vi':
            sig_data = [
                ['Người lập phiếu', 'Thủ kho', 'Người nhận', 'Phê duyệt'],
                ['Prepared by', 'Warehouse keeper', 'Receiver', 'Approved by'],
                ['', '', '', ''],
                ['', '', '', ''],
                ['', '', '', ''],
                ['Ký, ghi rõ họ tên', 'Ký, ghi rõ họ tên', 'Ký, ghi rõ họ tên', 'Ký, ghi rõ họ tên'],
            ]
        else:
            sig_data = [
                ['Prepared by', 'Warehouse keeper', 'Receiver', 'Approved by'],
                ['', '', '', ''],
                ['', '', '', ''],
                ['', '', '', ''],
                ['', '', '', ''],
                ['Sign & Name', 'Sign & Name', 'Sign & Name', 'Sign & Name'],
            ]
        
        sig_table = Table(sig_data, colWidths=[47.5*mm]*4)
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('LINEBELOW', (0, 4), (-1, 4), 0.5, colors.black),
            ('FONTSIZE', (0, -1), (-1, -1), 8),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.grey),
        ]))
        
        story.append(Spacer(1, 15*mm))
        story.append(sig_table)
    
    def generate_pdf(self, issue_id: int, language: str = 'vi') -> bytes:
        """
        Generate PDF for material issue
        
        Args:
            issue_id: Material issue ID
            language: 'vi' for Vietnamese, 'en' for English
            
        Returns:
            PDF content as bytes
        """
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
            story.append(Paragraph(f"<b>Ghi chú / Notes:</b> {data['issue']['notes']}", 
                                 styles['Normal']))
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
        
        return pdf_bytes
    
    def generate_pdf_with_options(self, issue_id: int, 
                                 options: Dict[str, Any]) -> bytes:
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
            PDF bytes
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