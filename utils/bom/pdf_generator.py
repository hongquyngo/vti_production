# utils/bom/pdf_generator.py
"""
PDF Generator for BOM - Following Issue Material template
Generates BOM PDF with materials list, company logo, and professional layout

Version: 2.0.0
Based on: IssuePDFGenerator v5.3
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
    
    def get_company_info(self, company_id: int = None, created_by: int = None) -> Dict[str, Any]:
        """
        Get company information
        Priority:
        1. company_id if provided
        2. From created_by user's employee → company
        3. From session state
        4. Fallback to default
        """
        import streamlit as st
        
        # Priority 1: Direct company_id
        if company_id:
            return self._fetch_company_by_id(company_id)
        
        # Priority 2: From BOM creator's company
        if created_by:
            company = self._fetch_company_by_user(created_by)
            if company:
                return company
        
        # Priority 3: From session state (logged in user)
        session_company_id = st.session_state.get('company_id')
        if session_company_id:
            return self._fetch_company_by_id(session_company_id)
        
        # Try to get from current user's employee
        keycloak_id = st.session_state.get('keycloak_id')
        if keycloak_id:
            company = self._fetch_company_by_keycloak(keycloak_id)
            if company:
                return company
        
        # Priority 4: Fallback default
        return {
            'id': 1,
            'english_name': 'PROSTECH ASIA',
            'local_name': 'CÔNG TY TNHH PROSTECH VIỆT NAM',
            'address': 'Vietnam',
            'registration_code': '',
            'logo_path': None
        }
    
    def _fetch_company_by_id(self, company_id: int) -> Dict[str, Any]:
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
    
    def _fetch_company_by_user(self, user_id: int) -> Dict[str, Any]:
        """Fetch company from user's employee record"""
        query = """
            SELECT 
                c.id, c.english_name, c.local_name,
                c.street as address, c.registration_code,
                m.path as logo_path
            FROM users u
            JOIN employees e ON u.employee_id = e.id
            JOIN companies c ON e.company_id = c.id
            LEFT JOIN medias m ON c.logo_id = m.id
            WHERE u.id = %s AND c.delete_flag = 0
        """
        try:
            df = pd.read_sql(query, self.engine, params=(user_id,))
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            logger.error(f"Error fetching company by user: {e}")
        return None
    
    def _fetch_company_by_keycloak(self, keycloak_id: str) -> Dict[str, Any]:
        """Fetch company from employee's keycloak_id"""
        query = """
            SELECT 
                c.id, c.english_name, c.local_name,
                c.street as address, c.registration_code,
                m.path as logo_path
            FROM employees e
            JOIN companies c ON e.company_id = c.id
            LEFT JOIN medias m ON c.logo_id = m.id
            WHERE e.keycloak_id = %s AND c.delete_flag = 0
        """
        try:
            df = pd.read_sql(query, self.engine, params=(keycloak_id,))
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            logger.error(f"Error fetching company by keycloak: {e}")
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
                     language: str = 'vi', layout: str = 'landscape'):
        """Create PDF header with company info and logo"""
        # Get company from BOM creator
        created_by = bom_info.get('created_by')
        company_info = self.get_company_info(created_by=created_by)
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        
        # Try to get logo from S3
        logo_img = None
        if S3_AVAILABLE:
            try:
                logo_bytes = get_company_logo_from_s3_enhanced(
                    company_info['id'], company_info.get('logo_path')
                )
                if logo_bytes:
                    logo_buffer = BytesIO(logo_bytes)
                    logo_img = Image(logo_buffer, width=50*mm, height=15*mm, kind='proportional')
                    logger.info("Logo loaded from S3")
            except Exception as e:
                logger.warning(f"Could not load logo: {e}")
        
        # Company name and document title
        company_name = company_info.get('english_name', 'PROSTECH ASIA')
        local_name = company_info.get('local_name', '')
        
        if language == 'vi':
            doc_title = "ĐỊNH MỨC SẢN XUẤT"
            doc_subtitle = "BILL OF MATERIALS"
        else:
            doc_title = "BILL OF MATERIALS"
            doc_subtitle = ""
        
        # Build header table
        if logo_img:
            # With logo: Logo | Company Info | Empty (for balance)
            company_text = f"""
                <b>{company_name}</b><br/>
                <font size="8">{local_name}</font>
            """
            
            header_data = [[
                logo_img,
                Paragraph(company_text, styles['CompanyInfo']),
                ''
            ]]
            
            col_widths = [55*mm, page_width - 110*mm, 55*mm]
        else:
            # Without logo: Centered company info
            company_text = f"""
                <b>{company_name}</b><br/>
                <font size="8">{local_name}</font>
            """
            
            header_data = [[Paragraph(company_text, styles['CompanyInfo'])]]
            col_widths = [page_width]
        
        header_table = Table(header_data, colWidths=col_widths)
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(header_table)
        story.append(Spacer(1, 8*mm))
        
        # Document title
        story.append(Paragraph(f"<b>{doc_title}</b>", styles['TitleViet']))
        if doc_subtitle:
            story.append(Paragraph(doc_subtitle, styles['CompanyInfo']))
        
        # BOM Code as subtitle
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(f"<b>{bom_info.get('bom_code', '')}</b>", styles['CompanyInfo']))
        story.append(Spacer(1, 6*mm))
    
    def create_bom_info(self, story: list, bom_info: Dict, styles: Any,
                       language: str = 'vi', layout: str = 'landscape'):
        """Create BOM information section with creator info"""
        bold_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        page_width = 277*mm if layout == 'landscape' else 190*mm
        
        # Labels based on language
        if language == 'vi':
            labels = {
                'bom_code': 'Mã BOM',
                'bom_name': 'Tên BOM',
                'bom_type': 'Loại BOM',
                'status': 'Trạng thái',
                'product': 'Sản phẩm',
                'output_qty': 'SL đầu ra',
                'effective_date': 'Ngày hiệu lực',
                'version': 'Phiên bản',
                'creator': 'Người tạo',
                'created_date': 'Ngày tạo'
            }
        else:
            labels = {
                'bom_code': 'BOM Code',
                'bom_name': 'BOM Name',
                'bom_type': 'BOM Type',
                'status': 'Status',
                'product': 'Output Product',
                'output_qty': 'Output Qty',
                'effective_date': 'Effective Date',
                'version': 'Version',
                'creator': 'Created By',
                'created_date': 'Created Date'
            }
        
        # Format output quantity
        output_qty = bom_info.get('output_qty', 0)
        uom = bom_info.get('uom', 'PCS')
        qty_str = f"{float(output_qty):,.2f} {uom}"
        
        # Product display
        product_display = f"{bom_info.get('product_code', '')} - {bom_info.get('product_name', '')}"
        
        # Effective date
        eff_date = bom_info.get('effective_date', '')
        if eff_date and hasattr(eff_date, 'strftime'):
            eff_date = eff_date.strftime('%d/%m/%Y')
        
        # Created date
        created_date = bom_info.get('created_date', '')
        if created_date and hasattr(created_date, 'strftime'):
            created_date = created_date.strftime('%d/%m/%Y %H:%M')
        
        # Creator name
        creator_name = bom_info.get('creator_name', 'Unknown')
        
        # Left column data
        left_data = [
            [f"{labels['bom_code']}:", bom_info.get('bom_code', '')],
            [f"{labels['bom_name']}:", bom_info.get('bom_name', '')],
            [f"{labels['bom_type']}:", bom_info.get('bom_type', '')],
            [f"{labels['status']}:", bom_info.get('status', '')],
            [f"{labels['creator']}:", creator_name],
        ]
        
        # Right column data
        right_data = [
            [f"{labels['product']}:", product_display],
            [f"{labels['output_qty']}:", qty_str],
            [f"{labels['effective_date']}:", str(eff_date) if eff_date else 'N/A'],
            [f"{labels['version']}:", str(bom_info.get('version', 1))],
            [f"{labels['created_date']}:", str(created_date) if created_date else 'N/A'],
        ]
        
        # Column widths
        left_lw = 25*mm  # Label width
        left_vw = 65*mm  # Value width
        right_lw = 30*mm
        right_vw = 60*mm
        
        if layout == 'landscape':
            left_vw = 85*mm
            right_vw = 80*mm
        
        # Create left table
        left_table = Table(left_data, colWidths=[left_lw, left_vw])
        left_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), bold_font),
            ('FONTNAME', (1, 0), (1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        # Create right table
        right_table = Table(right_data, colWidths=[right_lw, right_vw])
        right_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), bold_font),
            ('FONTNAME', (1, 0), (1, -1), normal_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        # Combine into main table
        main_table = Table([[left_table, right_table]], 
                          colWidths=[left_lw + left_vw, right_lw + right_vw])
        main_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        
        story.append(main_table)
        story.append(Spacer(1, 8*mm))
    
    def create_materials_table(self, story: list, materials: pd.DataFrame, 
                               alternatives_data: Dict[int, pd.DataFrame],
                               styles: Any, language: str = 'vi', 
                               layout: str = 'landscape'):
        """Create materials table with proper alignment"""
        header_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        # Calculate total table width
        if layout == 'landscape':
            # Total width ~267mm (A4 landscape - margins)
            col_widths = [12*mm, 140*mm, 18*mm, 22*mm, 18*mm, 18*mm, 22*mm, 17*mm]
        else:
            # Total width ~180mm (A4 portrait - margins)
            col_widths = [10*mm, 80*mm, 14*mm, 18*mm, 14*mm, 16*mm, 18*mm, 14*mm]
        
        total_width = sum(col_widths)
        
        # Section header with summary on same line
        mat_count = len(materials) if not materials.empty else 0
        if language == 'vi':
            section_title = f"Danh sách vật tư ({mat_count} mục)"
        else:
            section_title = f"Materials ({mat_count} items)"
        
        # Summary by type
        type_counts = materials['material_type'].value_counts() if not materials.empty else {}
        summary_parts = []
        
        type_labels = {
            'RAW_MATERIAL': 'Nguyên liệu' if language == 'vi' else 'Raw',
            'PACKAGING': 'Bao bì' if language == 'vi' else 'Pkg',
            'CONSUMABLE': 'Tiêu hao' if language == 'vi' else 'Con'
        }
        
        for mat_type, label in type_labels.items():
            if mat_type in type_counts:
                summary_parts.append(f"{label}: {type_counts[mat_type]}")
        
        summary_text = " | ".join(summary_parts) if summary_parts else ""
        
        # Create section header table (title left, summary right)
        section_header_data = [[
            Paragraph(f"<b>{section_title}</b>", styles['SectionHeader']),
            Paragraph(summary_text, styles['Footer'])
        ]]
        section_header_table = Table(
            section_header_data, 
            colWidths=[total_width * 0.6, total_width * 0.4]
        )
        section_header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        story.append(section_header_table)
        story.append(Spacer(1, 2*mm))
        
        if materials.empty:
            if language == 'vi':
                story.append(Paragraph("Không có vật tư trong BOM này.", styles['NormalViet']))
            else:
                story.append(Paragraph("No materials in this BOM.", styles['NormalViet']))
            return
        
        # Table headers
        if language == 'vi':
            headers = ['STT', 'Thông tin vật tư', 'Loại', 'SL', 'ĐVT', 'Hao hụt', 'Tồn kho', 'T.Thế']
        else:
            headers = ['No.', 'Material Info', 'Type', 'Qty', 'UOM', 'Scrap', 'Stock', 'Alt']
        
        header_row = [Paragraph(f"<b>{h}</b>", styles['TableHeader']) for h in headers]
        table_data = [header_row]
        
        # Material rows
        for idx, (_, mat) in enumerate(materials.iterrows(), 1):
            # Material info with code and name - wrap text
            mat_name = mat['material_name']
            mat_code = mat['material_code']
            
            if language == 'vi':
                mat_info = f"{mat_name}<br/><font size='7'>Mã: {mat_code}</font>"
            else:
                mat_info = f"{mat_name}<br/><font size='7'>Code: {mat_code}</font>"
            
            # Type abbreviation
            type_abbr = {
                'RAW_MATERIAL': 'RAW',
                'PACKAGING': 'PKG',
                'CONSUMABLE': 'CON'
            }.get(mat['material_type'], mat['material_type'][:3])
            
            # Quantity - format nicely
            qty = float(mat['quantity'])
            if qty == int(qty):
                qty_str = f"{int(qty):,}"
            else:
                qty_str = f"{qty:,.2f}".rstrip('0').rstrip('.')
            
            # Scrap rate
            scrap = float(mat.get('scrap_rate', 0))
            scrap_str = f"{scrap:.1f}%" if scrap > 0 else "-"
            
            # Stock
            stock = float(mat.get('current_stock', 0))
            stock_str = f"{stock:,.0f}" if stock > 0 else "-"
            
            # Alternatives count
            alt_count = int(mat.get('alternatives_count', 0))
            alt_str = str(alt_count) if alt_count > 0 else "-"
            
            row = [
                Paragraph(str(idx), styles['TableCellCenter']),
                Paragraph(mat_info, styles['TableCell']),
                Paragraph(type_abbr, styles['TableCellCenter']),
                Paragraph(qty_str, styles['TableCellRight']),
                Paragraph(str(mat['uom']), styles['TableCellCenter']),
                Paragraph(scrap_str, styles['TableCellCenter']),
                Paragraph(stock_str, styles['TableCellRight']),
                Paragraph(alt_str, styles['TableCellCenter']),
            ]
            table_data.append(row)
        
        materials_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        materials_table.setStyle(TableStyle([
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), header_font),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            
            # Alignment
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),  # Header center
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # STT center
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # Material info left
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Type center
            ('ALIGN', (3, 1), (3, -1), 'RIGHT'),   # Qty right
            ('ALIGN', (4, 1), (4, -1), 'CENTER'),  # UOM center
            ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Scrap center
            ('ALIGN', (6, 1), (6, -1), 'RIGHT'),   # Stock right
            ('ALIGN', (7, 1), (7, -1), 'CENTER'),  # Alt center
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#2c3e50')),
            
            # Padding - increased for better readability
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),     # Header padding
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 5),    # Data padding
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        story.append(materials_table)
        
        # Add alternatives section if any
        has_alternatives = any(
            not df.empty for df in alternatives_data.values()
        ) if alternatives_data else False
        
        if has_alternatives:
            self._create_alternatives_section(
                story, materials, alternatives_data, styles, language, layout
            )
    
    def _create_alternatives_section(self, story: list, materials: pd.DataFrame,
                                     alternatives_data: Dict[int, pd.DataFrame],
                                     styles: Any, language: str = 'vi',
                                     layout: str = 'landscape'):
        """Create alternatives detail section with proper alignment"""
        header_font = 'DejaVuSans-Bold' if self.font_available else 'Helvetica-Bold'
        normal_font = 'DejaVuSans' if self.font_available else 'Helvetica'
        
        # Calculate total table width (same as materials table)
        if layout == 'landscape':
            alt_col_widths = [15*mm, 155*mm, 22*mm, 18*mm, 20*mm, 37*mm]
        else:
            alt_col_widths = [12*mm, 90*mm, 18*mm, 14*mm, 18*mm, 28*mm]
        
        total_width = sum(alt_col_widths)
        
        story.append(Spacer(1, 6*mm))
        
        if language == 'vi':
            section_title = "Vật tư thay thế"
        else:
            section_title = "Alternative Materials"
        
        # Section header aligned with table
        section_header_data = [[
            Paragraph(f"<b>{section_title}</b>", styles['SectionHeader']),
            Paragraph("", styles['Footer'])
        ]]
        section_header_table = Table(
            section_header_data, 
            colWidths=[total_width * 0.6, total_width * 0.4]
        )
        section_header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(section_header_table)
        
        for _, mat in materials.iterrows():
            detail_id = int(mat['id'])
            alternatives = alternatives_data.get(detail_id)
            
            if alternatives is None or alternatives.empty:
                continue
            
            # Material header - create a table with same width
            mat_header_data = [[
                Paragraph(
                    f"<b>{mat['material_code']}</b> - {mat['material_name']}",
                    styles['NormalViet']
                )
            ]]
            mat_header_table = Table(mat_header_data, colWidths=[total_width])
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
                
                alt_row = [
                    Paragraph(str(alt['priority']), styles['TableCellCenter']),
                    Paragraph(f"{alt['material_code']} - {alt['material_name']}", styles['TableCell']),
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
    
    def create_footer(self, story: list, bom_info: Dict, styles: Any):
        """Create document footer"""
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
        
        footer_text = f"Generated: {timestamp} | BOM Version: {version} | Status: {status}"
        story.append(Paragraph(footer_text, styles['Footer']))
    
    def generate_pdf(self, bom_info: Dict[str, Any],
                    materials: pd.DataFrame,
                    alternatives_data: Dict[int, pd.DataFrame],
                    language: str = 'vi',
                    layout: str = 'landscape') -> Optional[bytes]:
        """
        Generate PDF for Bill of Materials
        
        Args:
            bom_info: BOM header information
            materials: DataFrame of BOM materials
            alternatives_data: Dict mapping detail_id to alternatives DataFrame
            language: 'vi' for Vietnamese, 'en' for English
            layout: 'landscape' (default) or 'portrait'
            
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
            
            # Build document sections
            self.create_header(story, bom_info, styles, language, layout)
            self.create_bom_info(story, bom_info, styles, language, layout)
            self.create_materials_table(story, materials, alternatives_data, styles, language, layout)
            self.create_notes_section(story, bom_info, styles, language)
            self.create_footer(story, bom_info, styles)
            
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
                     language: str = 'vi',
                     layout: str = 'landscape') -> Optional[bytes]:
    """
    Convenience function to generate BOM PDF
    
    Args:
        bom_info: BOM header information
        materials: DataFrame of BOM materials
        alternatives_data: Dict mapping detail_id to alternatives DataFrame
        language: 'vi' for Vietnamese, 'en' for English
        layout: 'landscape' (default) or 'portrait'
        
    Returns:
        PDF as bytes or None on error
    """
    generator = BOMPDFGenerator()
    return generator.generate_pdf(bom_info, materials, alternatives_data, language, layout)


# Singleton instance
_pdf_generator = None

def get_pdf_generator() -> BOMPDFGenerator:
    """Get singleton PDF generator instance"""
    global _pdf_generator
    if _pdf_generator is None:
        _pdf_generator = BOMPDFGenerator()
    return _pdf_generator