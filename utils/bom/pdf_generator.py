# utils/bom/pdf_generator.py
"""
BOM PDF Generator - Professional PDF export using ReportLab
Generates detailed BOM documents with materials and alternatives
"""

import logging
from io import BytesIO
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# ==================== Font Registration ====================

def register_fonts():
    """Register Unicode fonts for Vietnamese support"""
    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]
    
    try:
        pdfmetrics.registerFont(TTFont('DejaVuSans', font_paths[0]))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', font_paths[1]))
        return True
    except Exception as e:
        logger.warning(f"Could not register DejaVu fonts: {e}")
        return False


# Register fonts on module load
FONTS_REGISTERED = register_fonts()
FONT_NAME = 'DejaVuSans' if FONTS_REGISTERED else 'Helvetica'
FONT_NAME_BOLD = 'DejaVuSans-Bold' if FONTS_REGISTERED else 'Helvetica-Bold'


# ==================== Styles ====================

def get_custom_styles():
    """Get custom paragraph styles"""
    styles = getSampleStyleSheet()
    
    # Title style
    styles.add(ParagraphStyle(
        name='BOMTitle',
        fontName=FONT_NAME_BOLD,
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=12
    ))
    
    # Subtitle style
    styles.add(ParagraphStyle(
        name='BOMSubtitle',
        fontName=FONT_NAME,
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.grey,
        spaceAfter=20
    ))
    
    # Section header
    styles.add(ParagraphStyle(
        name='SectionHeader',
        fontName=FONT_NAME_BOLD,
        fontSize=12,
        leading=16,
        spaceBefore=12,
        spaceAfter=8,
        textColor=colors.HexColor('#1a5276')
    ))
    
    # Normal text
    styles.add(ParagraphStyle(
        name='BOMNormal',
        fontName=FONT_NAME,
        fontSize=9,
        leading=12
    ))
    
    # Small text
    styles.add(ParagraphStyle(
        name='BOMSmall',
        fontName=FONT_NAME,
        fontSize=8,
        leading=10,
        textColor=colors.grey
    ))
    
    # Field label
    styles.add(ParagraphStyle(
        name='FieldLabel',
        fontName=FONT_NAME_BOLD,
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#566573')
    ))
    
    # Field value
    styles.add(ParagraphStyle(
        name='FieldValue',
        fontName=FONT_NAME,
        fontSize=10,
        leading=13
    ))
    
    return styles


# ==================== Table Styles ====================

def get_header_table_style():
    """Style for header info tables"""
    return TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#566573')),
        ('FONTNAME', (0, 0), (0, -1), FONT_NAME_BOLD),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (0, -1), 8),
    ])


def get_materials_table_style():
    """Style for materials table"""
    return TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # No
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Type
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),   # Qty
        ('ALIGN', (4, 1), (4, -1), 'CENTER'),  # UOM
        ('ALIGN', (5, 1), (5, -1), 'RIGHT'),   # Scrap
        ('ALIGN', (6, 1), (6, -1), 'RIGHT'),   # Stock
        ('ALIGN', (7, 1), (7, -1), 'CENTER'),  # Alternatives
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#2c3e50')),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Vertical alignment
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])


def get_alternatives_table_style():
    """Style for alternatives sub-table"""
    return TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#85929e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        
        # Data
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Priority
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),   # Qty
        ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # UOM
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),   # Scrap
        ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Status
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d5d8dc')),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])


# ==================== PDF Generator Class ====================

class BOMPDFGenerator:
    """Generate professional PDF documents for BOMs"""
    
    def __init__(self):
        self.styles = get_custom_styles()
        self.page_width, self.page_height = A4
    
    def generate(self, bom_info: Dict[str, Any], 
                 materials: pd.DataFrame,
                 alternatives_data: Dict[int, pd.DataFrame],
                 company_name: str = "Prostech Asia") -> bytes:
        """
        Generate BOM PDF document
        
        Args:
            bom_info: BOM header information
            materials: DataFrame of BOM materials
            alternatives_data: Dict mapping detail_id to alternatives DataFrame
            company_name: Company name for header
            
        Returns:
            PDF as bytes
        """
        buffer = BytesIO()
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=15*mm,
            leftMargin=15*mm,
            topMargin=15*mm,
            bottomMargin=15*mm
        )
        
        story = []
        
        # Build document sections
        story.extend(self._build_header(bom_info, company_name))
        story.extend(self._build_bom_info(bom_info))
        story.extend(self._build_materials_section(materials, alternatives_data))
        story.extend(self._build_footer(bom_info))
        
        # Build PDF
        doc.build(story, onFirstPage=self._add_page_number, 
                  onLaterPages=self._add_page_number)
        
        buffer.seek(0)
        return buffer.getvalue()
    
    def _build_header(self, bom_info: Dict, company_name: str) -> List:
        """Build document header"""
        elements = []
        
        # Company name
        elements.append(Paragraph(company_name, self.styles['BOMSubtitle']))
        
        # Title
        elements.append(Paragraph(
            f"BILL OF MATERIALS",
            self.styles['BOMTitle']
        ))
        
        # BOM Code subtitle
        elements.append(Paragraph(
            f"{bom_info['bom_code']}",
            self.styles['BOMSubtitle']
        ))
        
        # Horizontal line
        elements.append(HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor('#2c3e50'),
            spaceBefore=5,
            spaceAfter=15
        ))
        
        return elements
    
    def _build_bom_info(self, bom_info: Dict) -> List:
        """Build BOM information section"""
        elements = []
        
        elements.append(Paragraph("BOM Information", self.styles['SectionHeader']))
        
        # Create info table with 2 columns
        col_width = (self.page_width - 30*mm) / 2
        
        left_data = [
            ['BOM Code:', bom_info.get('bom_code', 'N/A')],
            ['BOM Name:', bom_info.get('bom_name', 'N/A')],
            ['BOM Type:', bom_info.get('bom_type', 'N/A')],
            ['Status:', bom_info.get('status', 'N/A')],
        ]
        
        right_data = [
            ['Output Product:', f"{bom_info.get('product_code', '')} - {bom_info.get('product_name', 'N/A')}"],
            ['Output Quantity:', f"{bom_info.get('output_qty', 0):,.2f} {bom_info.get('uom', 'PCS')}"],
            ['Effective Date:', str(bom_info.get('effective_date', 'N/A'))],
            ['Version:', str(bom_info.get('version', 1))],
        ]
        
        # Left table
        left_table = Table(left_data, colWidths=[35*mm, col_width - 40*mm])
        left_table.setStyle(get_header_table_style())
        
        # Right table
        right_table = Table(right_data, colWidths=[40*mm, col_width - 45*mm])
        right_table.setStyle(get_header_table_style())
        
        # Combine in a wrapper table
        wrapper = Table([[left_table, right_table]], colWidths=[col_width, col_width])
        wrapper.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        elements.append(wrapper)
        
        # Notes if any
        if bom_info.get('notes'):
            elements.append(Spacer(1, 8))
            elements.append(Paragraph(
                f"<b>Notes:</b> {bom_info['notes']}", 
                self.styles['BOMNormal']
            ))
        
        elements.append(Spacer(1, 15))
        
        return elements
    
    def _build_materials_section(self, materials: pd.DataFrame,
                                  alternatives_data: Dict[int, pd.DataFrame]) -> List:
        """Build materials section with table"""
        elements = []
        
        elements.append(Paragraph(
            f"Materials ({len(materials)} items)", 
            self.styles['SectionHeader']
        ))
        
        if materials.empty:
            elements.append(Paragraph(
                "No materials defined for this BOM.",
                self.styles['BOMNormal']
            ))
            return elements
        
        # Summary by type
        type_counts = materials['material_type'].value_counts()
        summary_parts = []
        if 'RAW_MATERIAL' in type_counts:
            summary_parts.append(f"Raw Materials: {type_counts['RAW_MATERIAL']}")
        if 'PACKAGING' in type_counts:
            summary_parts.append(f"Packaging: {type_counts['PACKAGING']}")
        if 'CONSUMABLE' in type_counts:
            summary_parts.append(f"Consumables: {type_counts['CONSUMABLE']}")
        
        if summary_parts:
            elements.append(Paragraph(
                " | ".join(summary_parts),
                self.styles['BOMSmall']
            ))
            elements.append(Spacer(1, 8))
        
        # Materials table
        header = ['#', 'Material', 'Type', 'Qty', 'UOM', 'Scrap %', 'Stock', 'Alt']
        
        table_data = [header]
        
        for idx, (_, mat) in enumerate(materials.iterrows(), 1):
            alt_count = int(mat.get('alternatives_count', 0))
            stock = float(mat.get('current_stock', 0))
            
            row = [
                str(idx),
                f"{mat['material_code']}\n{mat['material_name'][:40]}",
                mat['material_type'][:3],  # RAW, PAC, CON
                f"{float(mat['quantity']):,.4f}",
                mat['uom'],
                f"{float(mat['scrap_rate']):.1f}%",
                f"{stock:,.0f}" if stock > 0 else "-",
                str(alt_count) if alt_count > 0 else "-"
            ]
            table_data.append(row)
        
        # Column widths
        col_widths = [8*mm, 55*mm, 12*mm, 20*mm, 12*mm, 15*mm, 18*mm, 10*mm]
        
        materials_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        materials_table.setStyle(get_materials_table_style())
        
        elements.append(materials_table)
        elements.append(Spacer(1, 15))
        
        # Alternatives section
        has_alternatives = any(
            not df.empty for df in alternatives_data.values()
        ) if alternatives_data else False
        
        if has_alternatives:
            elements.extend(self._build_alternatives_section(
                materials, alternatives_data
            ))
        
        return elements
    
    def _build_alternatives_section(self, materials: pd.DataFrame,
                                     alternatives_data: Dict[int, pd.DataFrame]) -> List:
        """Build alternatives detail section"""
        elements = []
        
        elements.append(Paragraph("Alternative Materials", self.styles['SectionHeader']))
        
        for _, mat in materials.iterrows():
            detail_id = int(mat['id'])
            alternatives = alternatives_data.get(detail_id)
            
            if alternatives is None or alternatives.empty:
                continue
            
            # Material header
            elements.append(Paragraph(
                f"<b>{mat['material_code']}</b> - {mat['material_name']}",
                self.styles['BOMNormal']
            ))
            elements.append(Spacer(1, 4))
            
            # Alternatives table
            alt_header = ['P', 'Alternative Material', 'Qty', 'UOM', 'Scrap %', 'Status']
            alt_data = [alt_header]
            
            for _, alt in alternatives.iterrows():
                status = "✓ Active" if alt['is_active'] else "○ Inactive"
                alt_row = [
                    str(alt['priority']),
                    f"{alt['material_code']} - {alt['material_name'][:35]}",
                    f"{float(alt['quantity']):,.4f}",
                    alt['uom'],
                    f"{float(alt['scrap_rate']):.1f}%",
                    status
                ]
                alt_data.append(alt_row)
            
            alt_col_widths = [8*mm, 70*mm, 20*mm, 12*mm, 15*mm, 18*mm]
            alt_table = Table(alt_data, colWidths=alt_col_widths)
            alt_table.setStyle(get_alternatives_table_style())
            
            elements.append(alt_table)
            elements.append(Spacer(1, 10))
        
        return elements
    
    def _build_footer(self, bom_info: Dict) -> List:
        """Build document footer section"""
        elements = []
        
        elements.append(Spacer(1, 20))
        elements.append(HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor('#bdc3c7'),
            spaceBefore=10,
            spaceAfter=10
        ))
        
        # Generation info
        now = datetime.now()
        footer_text = (
            f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"BOM Version: {bom_info.get('version', 1)} | "
            f"Status: {bom_info.get('status', 'N/A')}"
        )
        
        elements.append(Paragraph(footer_text, self.styles['BOMSmall']))
        
        return elements
    
    def _add_page_number(self, canvas, doc):
        """Add page number to each page"""
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.grey)
        
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        
        canvas.drawRightString(
            self.page_width - 15*mm,
            10*mm,
            text
        )
        canvas.restoreState()


# ==================== Helper Functions ====================

def generate_bom_pdf(bom_info: Dict[str, Any],
                     materials: pd.DataFrame,
                     alternatives_data: Dict[int, pd.DataFrame],
                     company_name: str = "Prostech Asia") -> bytes:
    """
    Convenience function to generate BOM PDF
    
    Args:
        bom_info: BOM header information
        materials: DataFrame of BOM materials
        alternatives_data: Dict mapping detail_id to alternatives DataFrame
        company_name: Company name for header
        
    Returns:
        PDF as bytes
    """
    generator = BOMPDFGenerator()
    return generator.generate(bom_info, materials, alternatives_data, company_name)
