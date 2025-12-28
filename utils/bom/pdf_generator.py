# utils/bom/pdf_generator.py
"""
PDF Generator for BOM - Following Issue Material template
Generates BOM PDF with materials list, company logo, and professional layout

VERSION: 2.3.0
Based on: IssuePDFGenerator v5.3

CHANGES in v2.3.0:
- Changed legacy code display from "N/A" to "NEW" for products without legacy code
- Format: code (legacy|NEW) | name | pkg (brand)

CHANGES in v2.2.0:
- Updated product display format: code (legacy | N/A) | name | pkg (brand)
- Added legacy_code, package_size, brand to materials and alternatives display

CHANGES in v2.1.0:
- Company info now passed directly via company_id/company_info parameters
- Removed auto-detection from creator (BOM can be shared across entities)
- User selects company at export time in UI
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
        from ..db import get_db_engine
        from ..s3_utils import get_company_logo_from_s3_enhanced
        S3_AVAILABLE = True
    except ImportError:
        S3_AVAILABLE = False
        def get_company_logo_from_s3_enhanced(company_id, logo_path):
            return None

logger = logging.getLogger(__name__)


# ==================== Vietnamese Diacritics Removal ====================

def remove_vietnamese_diacritics(text: str) -> str:
    """
    Remove Vietnamese diacritics from text
    Used for English language output where Vietnamese addresses should be ASCII
    
    Args:
        text: Vietnamese text with diacritics
        
    Returns:
        Text with diacritics removed
    """
    if not text:
        return text
    
    # Vietnamese character mapping
    vietnamese_map = {
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'đ': 'd',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        # Uppercase
        'À': 'A', 'Á': 'A', 'Ả': 'A', 'Ã': 'A', 'Ạ': 'A',
        'Ă': 'A', 'Ằ': 'A', 'Ắ': 'A', 'Ẳ': 'A', 'Ẵ': 'A', 'Ặ': 'A',
        'Â': 'A', 'Ầ': 'A', 'Ấ': 'A', 'Ẩ': 'A', 'Ẫ': 'A', 'Ậ': 'A',
        'Đ': 'D',
        'È': 'E', 'É': 'E', 'Ẻ': 'E', 'Ẽ': 'E', 'Ẹ': 'E',
        'Ê': 'E', 'Ề': 'E', 'Ế': 'E', 'Ể': 'E', 'Ễ': 'E', 'Ệ': 'E',
        'Ì': 'I', 'Í': 'I', 'Ỉ': 'I', 'Ĩ': 'I', 'Ị': 'I',
        'Ò': 'O', 'Ó': 'O', 'Ỏ': 'O', 'Õ': 'O', 'Ọ': 'O',
        'Ô': 'O', 'Ồ': 'O', 'Ố': 'O', 'Ổ': 'O', 'Ỗ': 'O', 'Ộ': 'O',
        'Ơ': 'O', 'Ờ': 'O', 'Ớ': 'O', 'Ở': 'O', 'Ỡ': 'O', 'Ợ': 'O',
        'Ù': 'U', 'Ú': 'U', 'Ủ': 'U', 'Ũ': 'U', 'Ụ': 'U',
        'Ư': 'U', 'Ừ': 'U', 'Ứ': 'U', 'Ử': 'U', 'Ữ': 'U', 'Ự': 'U',
        'Ỳ': 'Y', 'Ý': 'Y', 'Ỷ': 'Y', 'Ỹ': 'Y', 'Ỵ': 'Y',
    }
    
    result = []
    for char in text:
        result.append(vietnamese_map.get(char, char))
    
    return ''.join(result)


# ==================== Product Display Formatting ====================

def format_product_code_with_legacy(code: str, legacy_code: Optional[str] = None) -> str:
    """
    Format product code with legacy code: code (legacy | NEW)
    
    Args:
        code: Product code (pt_code)
        legacy_code: Legacy product code
        
    Returns:
        Formatted string like "VTI001 (OLD-001)" or "VTI001 (NEW)"
    """
    legacy_display = "NEW"
    if legacy_code and str(legacy_code).strip() and str(legacy_code).strip() != '-':
        legacy_display = str(legacy_code).strip()
    
    return f"{code} ({legacy_display})"


def format_product_name_with_details(name: str, 
                                     package_size: Optional[str] = None,
                                     brand: Optional[str] = None) -> str:
    """
    Format product name with package and brand: name | pkg (brand)
    
    Args:
        name: Product name
        package_size: Package size
        brand: Brand name
        
    Returns:
        Formatted string like "Product ABC | 100g (Brand)" or "Product ABC"
    """
    result = name or ""
    
    extra_parts = []
    if package_size and str(package_size).strip() and str(package_size).strip() != '-':
        extra_parts.append(str(package_size).strip())
    
    if brand and str(brand).strip() and str(brand).strip() != '-':
        if extra_parts:
            extra_parts[0] = f"{extra_parts[0]} ({str(brand).strip()})"
        else:
            extra_parts.append(f"({str(brand).strip()})")
    
    if extra_parts:
        result += " | " + " ".join(extra_parts)
    
    return result


class BOMPDFGenerator:
    """Generate PDF for Bill of Materials"""
    
    def __init__(self):
        self.engine = get_db_engine()
        self._registered_fonts = set()
        self.font_available = self._setup_fonts()
    
    def _get_project_root(self) -> Path:
        """Get project root directory"""
        current_file = Path(__file__).resolve()
        # utils/bom/pdf_generator.py -> project root
        project_root = current_file.parent.parent.parent
        return project_root
    
    def _setup_fonts(self) -> bool:
        """Setup DejaVu fonts for Vietnamese text support"""
        try:
            project_root = self._get_project_root()
            fonts_dir = project_root / 'fonts'
            
            if not fonts_dir.exists():
                logger.warning(f"Fonts directory not found: {fonts_dir}")
                return False
            
            dejavu_regular = fonts_dir / 'DejaVuSans.ttf'
            dejavu_bold = fonts_dir / 'DejaVuSans-Bold.ttf'
            
            if not dejavu_regular.exists():
                logger.warning(f"DejaVuSans.ttf not found in {fonts_dir}")
                return False
            
            # Register regular font
            try:
                if 'DejaVuSans' not in self._registered_fonts:
                    pdfmetrics.registerFont(TTFont('DejaVuSans', str(dejavu_regular)))
                    self._registered_fonts.add('DejaVuSans')
                    logger.info("DejaVuSans font registered")
            except Exception as e:
                if 'already registered' not in str(e).lower():
                    raise
                self._registered_fonts.add('DejaVuSans')
            
            # Register bold font
            try:
                if dejavu_bold.exists() and 'DejaVuSans-Bold' not in self._registered_fonts:
                    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', str(dejavu_bold)))
                    self._registered_fonts.add('DejaVuSans-Bold')
                    logger.info("DejaVuSans-Bold font registered")
            except Exception as e:
                if 'already registered' not in str(e).lower():
                    raise
                self._registered_fonts.add('DejaVuSans-Bold')
            
            return True
            
        except Exception as e:
            logger.error(f"Font setup error: {e}")
            return False
    
    def get_company_info(self, company_id: Optional[int] = None, 
                         company_info: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Get company information for PDF header
        
        NEW LOGIC (v2.1.0):
        1. Use company_info dict if provided directly (from UI selection)
        2. Fetch by company_id if provided
        3. Fallback to session state company_id
        4. Fallback to default
        
        Args:
            company_id: Selected company ID from export dialog
            company_info: Pre-fetched company info dict from export dialog
            
        Returns:
            Company info dict with id, english_name, local_name, address, logo_path
        """
        import streamlit as st
        
        # Priority 1: Pre-fetched company_info from UI
        if company_info and company_info.get('id'):
            return company_info
        
        # Priority 2: Fetch by company_id
        if company_id:
            fetched = self._fetch_company_by_id(company_id)
            if fetched:
                return fetched
        
        # Priority 3: From session state (logged in user's default company)
        session_company_id = st.session_state.get('company_id')
        if session_company_id:
            fetched = self._fetch_company_by_id(session_company_id)
            if fetched:
                return fetched
        
        # Priority 4: Fallback default
        return {
            'id': 1,
            'english_name': 'PROSTECH ASIA',
            'local_name': 'CÔNG TY TNHH PROSTECH VIỆT NAM',
            'address': 'Vietnam',
            'registration_code': '',
            'logo_path': None
        }
    
    def _fetch_company_by_id(self, company_id: int) -> Optional[Dict[str, Any]]:
        """Fetch company by ID"""
        query = """
            SELECT 
                c.id, c.english_name, c.local_name,
                c.street as address, c.registration_code,
                m.path as logo_path
            FROM companies c
            LEFT JOIN medias m ON c.logo_id = m.id
            WHERE c.id = %s AND c.delete_flag = 0
        """
        try:
            df = pd.read_sql(query, self.engine, params=(company_id,))
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            logger.error(f"Error fetching company by ID: {e}")
        return None
    
    def get_custom_styles(self) -> Dict[str, Any]:
        """Create custom paragraph styles"""
        styles = getSampleStyleSheet()
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        # Title style
        styles.add(ParagraphStyle(
            name='TitleViet', parent=styles['Title'],
            fontName=bold_font, fontSize=16, alignment=TA_CENTER,
            spaceAfter=6, textColor=colors.HexColor('#1a1a1a')
        ))
        
        # Normal Vietnamese text
        styles.add(ParagraphStyle(
            name='NormalViet', parent=styles['Normal'],
            fontName=base_font, fontSize=10, leading=12
        ))
        
        # Company info style
        styles.add(ParagraphStyle(
            name='CompanyInfo', parent=styles['Normal'],
            fontName=base_font, fontSize=10, alignment=TA_CENTER
        ))
        
        # Table cell styles
        styles.add(ParagraphStyle(
            name='TableCell', parent=styles['Normal'],
            fontName=base_font, fontSize=9, leading=11, alignment=TA_LEFT
        ))
        
        styles.add(ParagraphStyle(
            name='TableCellCenter', parent=styles['Normal'],
            fontName=base_font, fontSize=9, leading=11, alignment=TA_CENTER
        ))
        
        styles.add(ParagraphStyle(
            name='TableCellRight', parent=styles['Normal'],
            fontName=base_font, fontSize=9, leading=11, alignment=TA_RIGHT
        ))
        
        styles.add(ParagraphStyle(
            name='TableHeader', parent=styles['Normal'],
            fontName=bold_font, fontSize=9, leading=11,
            alignment=TA_CENTER, textColor=colors.whitesmoke
        ))
        
        # Footer style
        styles.add(ParagraphStyle(
            name='Footer', parent=styles['Normal'],
            fontName=base_font, fontSize=8, alignment=TA_CENTER,
            textColor=colors.grey
        ))
        
        # Section header
        styles.add(ParagraphStyle(
            name='SectionHeader', parent=styles['Normal'],
            fontName=bold_font, fontSize=11, leading=14,
            textColor=colors.HexColor('#2c3e50'), spaceBefore=6, spaceAfter=4
        ))
        
        return styles
    
    def create_header(self, story: list, bom_info: Dict, styles: Any,
                     company_id: Optional[int], company_info: Optional[Dict],
                     language: str = 'vi', layout: str = 'landscape'):
        """
        Create PDF header with company info and logo
        
        Layout follows template:
        - Logo on LEFT
        - Company info on RIGHT: Name (based on language) + Address + MST
        
        Args:
            story: PDF story list
            bom_info: BOM information
            styles: Paragraph styles
            company_id: Selected company ID (from export dialog)
            company_info: Pre-fetched company info (from export dialog)
            language: 'vi' or 'en'
            layout: 'landscape' or 'portrait'
        """
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        # Get company info - use provided company_id/company_info, not from creator
        resolved_company = self.get_company_info(
            company_id=company_id, 
            company_info=company_info
        )
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        
        # Try to get logo from S3
        logo_img = None
        if S3_AVAILABLE:
            try:
                logo_bytes = get_company_logo_from_s3_enhanced(
                    resolved_company['id'], resolved_company.get('logo_path')
                )
                if logo_bytes:
                    logo_buffer = BytesIO(logo_bytes)
                    logo_img = Image(logo_buffer, width=35*mm, height=18*mm, kind='proportional')
                    logger.info("Logo loaded from S3")
            except Exception as e:
                logger.warning(f"Could not load logo: {e}")
        
        # Company name based on language selection
        if language == 'vi':
            # Vietnamese: prefer local_name, fallback to english_name
            company_name = resolved_company.get('local_name') or resolved_company.get('english_name', 'COMPANY')
        else:
            # English: prefer english_name, fallback to local_name
            company_name = resolved_company.get('english_name') or resolved_company.get('local_name', 'COMPANY')
        
        # Address and MST (registration code)
        address = resolved_company.get('address', '')
        mst = resolved_company.get('registration_code', '')
        
        # Remove Vietnamese diacritics from address when language is English
        if language == 'en' and address:
            address = remove_vietnamese_diacritics(address)
        
        # Build company info text (right-aligned)
        company_info_style = ParagraphStyle(
            name='CompanyHeader',
            fontName=bold_font,
            fontSize=11,
            leading=14,
            alignment=TA_RIGHT,
            textColor=colors.HexColor('#1a5276')
        )
        
        company_detail_style = ParagraphStyle(
            name='CompanyDetail',
            fontName=base_font,
            fontSize=9,
            leading=11,
            alignment=TA_RIGHT,
            textColor=colors.HexColor('#2c3e50')
        )
        
        # Build header table: Logo (left) | Company Info (right)
        if logo_img:
            # Build company text block
            company_lines = [f"<b>{company_name}</b>"]
            if address:
                company_lines.append(f"<font size='9'>{address}</font>")
            if mst:
                company_lines.append(f"<font size='9'>MST: {mst}</font>")
            
            company_text = "<br/>".join(company_lines)
            
            header_data = [[
                logo_img,
                Paragraph(company_text, company_info_style)
            ]]
            
            # Logo column narrower, company info takes rest
            col_widths = [40*mm, page_width - 50*mm]
            
            header_table = Table(header_data, colWidths=col_widths)
            header_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),      # Logo left
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),    # Company info right
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
        else:
            # Without logo: Company info right-aligned
            company_lines = [f"<b>{company_name}</b>"]
            if address:
                company_lines.append(f"<font size='9'>{address}</font>")
            if mst:
                company_lines.append(f"<font size='9'>MST: {mst}</font>")
            
            company_text = "<br/>".join(company_lines)
            
            header_data = [[
                '',  # Empty left cell
                Paragraph(company_text, company_info_style)
            ]]
            
            col_widths = [page_width * 0.3, page_width * 0.7]
            
            header_table = Table(header_data, colWidths=col_widths)
            header_table.setStyle(TableStyle([
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
        
        story.append(header_table)
        story.append(Spacer(1, 10*mm))
        
        # Document title
        if language == 'vi':
            doc_title = "ĐỊNH MỨC SẢN XUẤT"
            doc_subtitle = "BILL OF MATERIALS"
        else:
            doc_title = "BILL OF MATERIALS"
            doc_subtitle = ""
        
        story.append(Paragraph(f"<b>{doc_title}</b>", styles['TitleViet']))
        if doc_subtitle:
            story.append(Paragraph(doc_subtitle, styles['CompanyInfo']))
        
        # BOM Code as subtitle
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(f"<b>{bom_info.get('bom_code', '')}</b>", styles['CompanyInfo']))
        story.append(Spacer(1, 5*mm))
    
    def create_bom_info(self, story: list, bom_info: Dict, styles: Any,
                       language: str = 'vi', layout: str = 'landscape'):
        """Create BOM information section with creator info"""
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        # Content width matches materials table (page_width - 10mm for balance)
        content_width = page_width - 10*mm
        
        # Section title
        if language == 'vi':
            section_title = "THÔNG TIN BOM"
        else:
            section_title = "BOM INFORMATION"
        
        story.append(Paragraph(f"<b>{section_title}</b>", styles['SectionHeader']))
        story.append(Spacer(1, 2*mm))
        
        # Info table - 2 columns layout
        if language == 'vi':
            labels = {
                'code': 'Mã BOM',
                'name': 'Tên BOM',
                'type': 'Loại',
                'product': 'Sản phẩm',
                'output': 'Sản lượng',
                'status': 'Trạng thái',
                'effective': 'Ngày hiệu lực',
                'version': 'Phiên bản',
                'creator': 'Người tạo',
                'created_date': 'Ngày tạo'
            }
        else:
            labels = {
                'code': 'BOM Code',
                'name': 'BOM Name',
                'type': 'Type',
                'product': 'Product',
                'output': 'Output Qty',
                'status': 'Status',
                'effective': 'Effective Date',
                'version': 'Version',
                'creator': 'Created By',
                'created_date': 'Created Date'
            }
        
        # Format values
        product_name = f"{bom_info.get('product_code', '')} - {bom_info.get('product_name', '')}"
        output_qty = bom_info.get('output_qty', 0)
        if output_qty == int(output_qty):
            output_str = f"{int(output_qty):,} {bom_info.get('uom', '')}"
        else:
            output_str = f"{output_qty:,.2f} {bom_info.get('uom', '')}"
        
        effective_date = bom_info.get('effective_date', 'N/A')
        if effective_date and hasattr(effective_date, 'strftime'):
            effective_date = effective_date.strftime('%d/%m/%Y')
        
        # Creator info
        creator_name = bom_info.get('creator_name', 'Unknown')
        created_date = bom_info.get('created_date', '')
        if created_date and hasattr(created_date, 'strftime'):
            created_date = created_date.strftime('%d/%m/%Y %H:%M')
        else:
            created_date = str(created_date) if created_date else 'N/A'
        
        info_data = [
            [
                Paragraph(f"<b>{labels['code']}:</b> {bom_info.get('bom_code', '')}", styles['NormalViet']),
                Paragraph(f"<b>{labels['product']}:</b> {product_name}", styles['NormalViet'])
            ],
            [
                Paragraph(f"<b>{labels['name']}:</b> {bom_info.get('bom_name', '')}", styles['NormalViet']),
                Paragraph(f"<b>{labels['output']}:</b> {output_str}", styles['NormalViet'])
            ],
            [
                Paragraph(f"<b>{labels['type']}:</b> {bom_info.get('bom_type', '')}", styles['NormalViet']),
                Paragraph(f"<b>{labels['status']}:</b> {bom_info.get('status', '')}", styles['NormalViet'])
            ],
            [
                Paragraph(f"<b>{labels['effective']}:</b> {effective_date}", styles['NormalViet']),
                Paragraph(f"<b>{labels['version']}:</b> {bom_info.get('version', 1)}", styles['NormalViet'])
            ],
            [
                Paragraph(f"<b>{labels['creator']}:</b> {creator_name}", styles['NormalViet']),
                Paragraph(f"<b>{labels['created_date']}:</b> {created_date}", styles['NormalViet'])
            ],
        ]
        
        col_width = content_width / 2
        info_table = Table(info_data, colWidths=[col_width, col_width])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 5*mm))
    
    def create_materials_table(self, story: list, materials: pd.DataFrame,
                               alternatives_data: Dict[int, pd.DataFrame],
                               styles: Any, language: str = 'vi',
                               layout: str = 'landscape'):
        """Create materials table with expandable alternatives"""
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        header_font = bold_font
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        # Content width matches BOM info table (page_width - 10mm for balance)
        content_width = page_width - 10*mm
        
        # Section title
        if language == 'vi':
            section_title = "DANH SÁCH NGUYÊN VẬT LIỆU"
        else:
            section_title = "MATERIALS LIST"
        
        story.append(Paragraph(f"<b>{section_title}</b>", styles['SectionHeader']))
        story.append(Spacer(1, 3*mm))
        
        if materials.empty:
            story.append(Paragraph("Không có nguyên vật liệu" if language == 'vi' else "No materials", 
                                  styles['NormalViet']))
            return
        
        # Table headers
        if language == 'vi':
            headers = ['STT', 'Mã NVL', 'Tên nguyên vật liệu', 'Loại', 'Số lượng', 'ĐVT', 'Hao hụt', 'Alt']
        else:
            headers = ['#', 'Code', 'Material Name', 'Type', 'Quantity', 'UOM', 'Scrap', 'Alt']
        
        # Column widths as percentage of content_width (total = 100%)
        # STT: 4%, Code: 12%, Name: 40%, Type: 14%, Qty: 10%, UOM: 8%, Scrap: 7%, Alt: 5%
        if layout == 'landscape':
            col_ratios = [0.04, 0.12, 0.40, 0.14, 0.10, 0.08, 0.07, 0.05]
        else:
            col_ratios = [0.05, 0.12, 0.36, 0.14, 0.11, 0.09, 0.08, 0.05]
        
        col_widths = [content_width * ratio for ratio in col_ratios]
        
        # Build table data
        header_row = [Paragraph(f"<b>{h}</b>", styles['TableHeader']) for h in headers]
        table_data = [header_row]
        
        for idx, (_, mat) in enumerate(materials.iterrows(), 1):
            # Format quantity
            qty = float(mat['quantity'])
            if qty == int(qty):
                qty_str = f"{int(qty):,}"
            else:
                qty_str = f"{qty:,.4f}".rstrip('0').rstrip('.')
            
            # Format scrap rate
            scrap = float(mat.get('scrap_rate', 0))
            scrap_str = f"{scrap:.1f}%" if scrap > 0 else "-"
            
            # Alternative count
            alt_count = int(mat.get('alternatives_count', 0))
            alt_str = str(alt_count) if alt_count > 0 else "-"
            
            # Format code with legacy: code (legacy | N/A)
            code_display = format_product_code_with_legacy(
                str(mat.get('material_code', '')),
                mat.get('legacy_code')
            )
            
            # Format name with details: name | pkg (brand)
            name_display = format_product_name_with_details(
                str(mat.get('material_name', '')),
                mat.get('package_size'),
                mat.get('brand')
            )
            
            row = [
                Paragraph(str(idx), styles['TableCellCenter']),
                Paragraph(code_display, styles['TableCell']),
                Paragraph(name_display, styles['TableCell']),
                Paragraph(str(mat['material_type']), styles['TableCellCenter']),
                Paragraph(qty_str, styles['TableCellRight']),
                Paragraph(str(mat['uom']), styles['TableCellCenter']),
                Paragraph(scrap_str, styles['TableCellCenter']),
                Paragraph(alt_str, styles['TableCellCenter']),
            ]
            table_data.append(row)
        
        # Create table with full content width
        main_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        main_table.setStyle(TableStyle([
            # Header style
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), header_font),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            
            # Data style
            ('FONTNAME', (0, 1), (-1, -1), base_font),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            
            # Alignment
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),  # Header center
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # STT center
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # Code left
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),    # Name left
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # Type center
            ('ALIGN', (4, 1), (4, -1), 'RIGHT'),   # Qty right
            ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # UOM center
            ('ALIGN', (6, 1), (6, -1), 'CENTER'),  # Scrap center
            ('ALIGN', (7, 1), (7, -1), 'CENTER'),  # Alt center
            
            # Borders and padding
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            
            # Alternating row colors
            *[('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f8f9fa')) 
              for i in range(2, len(table_data), 2)],
        ]))
        
        story.append(main_table)
        story.append(Spacer(1, 5*mm))
        
        # Add alternatives sections
        self._add_alternatives_sections(story, materials, alternatives_data, 
                                        styles, language, layout)
    
    def _add_alternatives_sections(self, story: list, materials: pd.DataFrame,
                                   alternatives_data: Dict[int, pd.DataFrame],
                                   styles: Any, language: str, layout: str):
        """Add alternatives for materials that have them"""
        base_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        header_font = bold_font
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        # Content width matches materials table
        content_width = page_width - 10*mm
        
        # Check if any alternatives exist
        has_alternatives = False
        for _, mat in materials.iterrows():
            detail_id = int(mat['id'])
            if detail_id in alternatives_data and not alternatives_data[detail_id].empty:
                has_alternatives = True
                break
        
        if not has_alternatives:
            return
        
        # Section title
        if language == 'vi':
            section_title = "NGUYÊN VẬT LIỆU THAY THẾ"
        else:
            section_title = "ALTERNATIVE MATERIALS"
        
        story.append(Spacer(1, 5*mm))
        story.append(Paragraph(f"<b>{section_title}</b>", styles['SectionHeader']))
        story.append(Spacer(1, 3*mm))
        
        # Column widths as percentage of content_width
        # Priority: 5%, Material: 52%, Qty: 10%, UOM: 8%, Scrap: 10%, Status: 15%
        if layout == 'landscape':
            alt_col_ratios = [0.05, 0.52, 0.10, 0.08, 0.10, 0.15]
        else:
            alt_col_ratios = [0.06, 0.46, 0.12, 0.10, 0.10, 0.16]
        
        alt_col_widths = [content_width * ratio for ratio in alt_col_ratios]
        
        # Process each material with alternatives
        for _, mat in materials.iterrows():
            detail_id = int(mat['id'])
            alternatives = alternatives_data.get(detail_id)
            
            if alternatives is None or alternatives.empty:
                continue
            
            # Material header - format with new display format
            mat_code_display = format_product_code_with_legacy(
                str(mat.get('material_code', '')),
                mat.get('legacy_code')
            )
            mat_name_display = format_product_name_with_details(
                str(mat.get('material_name', '')),
                mat.get('package_size'),
                mat.get('brand')
            )
            
            # Material header - create a table with same content width
            mat_header_data = [[
                Paragraph(
                    f"<b>{mat_code_display}</b> - {mat_name_display}",
                    styles['NormalViet']
                )
            ]]
            mat_header_table = Table(mat_header_data, colWidths=[content_width])
            mat_header_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('TOPPADDING', (0, 0), (0, 0), 4),
                ('BOTTOMPADDING', (0, 0), (0, 0), 2),
            ]))
            story.append(mat_header_table)
            
            # Alternatives table headers
            if language == 'vi':
                alt_headers = ['ƯT', 'Vật tư thay thế', 'SL', 'ĐVT', 'Hao hụt', 'Trạng thái']
            else:
                alt_headers = ['P', 'Alternative Material', 'Qty', 'UOM', 'Scrap', 'Status']
            
            alt_header_row = [Paragraph(f"<b>{h}</b>", styles['TableHeader']) for h in alt_headers]
            alt_table_data = [alt_header_row]
            
            for _, alt in alternatives.iterrows():
                status_icon = "✓" if alt['is_active'] else "○"
                if language == 'vi':
                    status_text = f"{status_icon} Hoạt động" if alt['is_active'] else f"{status_icon} Ngừng"
                else:
                    status_text = f"{status_icon} Active" if alt['is_active'] else f"{status_icon} Inactive"
                
                qty = float(alt['quantity'])
                if qty == int(qty):
                    qty_str = f"{int(qty):,}"
                else:
                    qty_str = f"{qty:,.2f}".rstrip('0').rstrip('.')
                
                scrap = float(alt.get('scrap_rate', 0))
                scrap_str = f"{scrap:.1f}%" if scrap > 0 else "-"
                
                # Format alternative with new display format
                alt_code_display = format_product_code_with_legacy(
                    str(alt.get('material_code', '')),
                    alt.get('legacy_code')
                )
                alt_name_display = format_product_name_with_details(
                    str(alt.get('material_name', '')),
                    alt.get('package_size'),
                    alt.get('brand')
                )
                
                alt_row = [
                    Paragraph(str(alt['priority']), styles['TableCellCenter']),
                    Paragraph(f"{alt_code_display} - {alt_name_display}", styles['TableCell']),
                    Paragraph(qty_str, styles['TableCellRight']),
                    Paragraph(str(alt['uom']), styles['TableCellCenter']),
                    Paragraph(scrap_str, styles['TableCellCenter']),
                    Paragraph(status_text, styles['TableCellCenter']),
                ]
                alt_table_data.append(alt_row)
            
            alt_table = Table(alt_table_data, colWidths=alt_col_widths, repeatRows=1)
            alt_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#85929e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), header_font),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                
                # Alignment
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),  # Header center
                ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Priority center
                ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # Material left
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),   # Qty right
                ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # UOM center
                ('ALIGN', (4, 1), (4, -1), 'CENTER'),  # Scrap center
                ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Status center
                
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d5d8dc')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, 0), 5),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
                ('TOPPADDING', (0, 1), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]))
            
            story.append(alt_table)
            story.append(Spacer(1, 4*mm))
    
    def create_notes_section(self, story: list, bom_info: Dict, styles: Any,
                            language: str = 'vi'):
        """Create notes section if notes exist"""
        notes = bom_info.get('notes', '')
        if not notes:
            return
        
        story.append(Spacer(1, 5*mm))
        
        if language == 'vi':
            label = "Ghi chú:"
        else:
            label = "Notes:"
        
        story.append(Paragraph(f"<b>{label}</b> {notes}", styles['NormalViet']))
    
    def create_footer(self, story: list, bom_info: Dict, styles: Any,
                      exported_by: Optional[str] = None, language: str = 'vi'):
        """Create document footer with export info"""
        story.append(Spacer(1, 10*mm))
        
        # Horizontal line
        line_data = [['_' * 120]]
        line_table = Table(line_data)
        line_table.setStyle(TableStyle([
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#bdc3c7')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
        ]))
        story.append(line_table)
        story.append(Spacer(1, 3*mm))
        
        # Generation info
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        version = bom_info.get('version', 1)
        status = bom_info.get('status', 'N/A')
        
        # Build footer text with exported_by
        if language == 'vi':
            if exported_by:
                footer_text = f"Xuất bởi: {exported_by} | Ngày xuất: {timestamp} | Phiên bản: {version} | Trạng thái: {status}"
            else:
                footer_text = f"Ngày xuất: {timestamp} | Phiên bản: {version} | Trạng thái: {status}"
        else:
            if exported_by:
                footer_text = f"Exported by: {exported_by} | Generated: {timestamp} | Version: {version} | Status: {status}"
            else:
                footer_text = f"Generated: {timestamp} | Version: {version} | Status: {status}"
        
        story.append(Paragraph(footer_text, styles['Footer']))
    
    def generate_pdf(self, bom_info: Dict[str, Any],
                    materials: pd.DataFrame,
                    alternatives_data: Dict[int, pd.DataFrame],
                    company_id: Optional[int] = None,
                    company_info: Optional[Dict] = None,
                    language: str = 'vi',
                    layout: str = 'landscape',
                    exported_by: Optional[str] = None) -> Optional[bytes]:
        """
        Generate PDF for Bill of Materials
        
        Args:
            bom_info: BOM header information
            materials: DataFrame of BOM materials
            alternatives_data: Dict mapping detail_id to alternatives DataFrame
            company_id: Selected company ID from export dialog
            company_info: Pre-fetched company info from export dialog
            language: 'vi' for Vietnamese, 'en' for English
            layout: 'landscape' (default) or 'portrait'
            exported_by: Name of user exporting the PDF
            
        Returns:
            PDF as bytes or None on error
        """
        try:
            page_size = landscape(A4) if layout == 'landscape' else A4
            
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer, pagesize=page_size,
                rightMargin=10*mm, leftMargin=10*mm,
                topMargin=10*mm, bottomMargin=10*mm
            )
            
            story = []
            styles = self.get_custom_styles()
            
            # Build document sections - pass company_id/company_info to header
            self.create_header(story, bom_info, styles, company_id, company_info, language, layout)
            self.create_bom_info(story, bom_info, styles, language, layout)
            self.create_materials_table(story, materials, alternatives_data, styles, language, layout)
            self.create_notes_section(story, bom_info, styles, language)
            self.create_footer(story, bom_info, styles, exported_by, language)
            
            # Build PDF
            doc.build(story)
            
            pdf_content = buffer.getvalue()
            buffer.close()
            
            logger.info(f"✅ BOM PDF generated: {bom_info.get('bom_code', 'N/A')}")
            return pdf_content
            
        except Exception as e:
            logger.error(f"❌ BOM PDF generation failed: {e}", exc_info=True)
            return None


# ==================== Helper Functions ====================

def generate_bom_pdf(bom_info: Dict[str, Any],
                     materials: pd.DataFrame,
                     alternatives_data: Dict[int, pd.DataFrame],
                     company_id: Optional[int] = None,
                     company_info: Optional[Dict] = None,
                     language: str = 'vi',
                     layout: str = 'landscape',
                     exported_by: Optional[str] = None) -> Optional[bytes]:
    """
    Convenience function to generate BOM PDF
    
    Args:
        bom_info: BOM header information
        materials: DataFrame of BOM materials
        alternatives_data: Dict mapping detail_id to alternatives DataFrame
        company_id: Selected company ID from export dialog
        company_info: Pre-fetched company info from export dialog
        language: 'vi' for Vietnamese, 'en' for English
        layout: 'landscape' (default) or 'portrait'
        exported_by: Name of user exporting the PDF
        
    Returns:
        PDF as bytes or None on error
    """
    generator = BOMPDFGenerator()
    return generator.generate_pdf(
        bom_info, materials, alternatives_data,
        company_id=company_id,
        company_info=company_info,
        language=language,
        layout=layout,
        exported_by=exported_by
    )


# Singleton instance
_pdf_generator = None

def get_pdf_generator() -> BOMPDFGenerator:
    """Get singleton PDF generator instance"""
    global _pdf_generator
    if _pdf_generator is None:
        _pdf_generator = BOMPDFGenerator()
    return _pdf_generator