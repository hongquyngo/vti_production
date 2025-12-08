# utils/bom/excel_generator.py
"""
Professional Excel Generator for BOM
Creates styled Excel workbooks with multiple sheets

Version: 1.0.0
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import (
    Font, Fill, PatternFill, Border, Side, Alignment,
    NamedStyle
)
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)


# ==================== Style Definitions ====================

# Colors
HEADER_BG = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
HEADER_BG_LIGHT = PatternFill(start_color="34495E", end_color="34495E", fill_type="solid")
SUBHEADER_BG = PatternFill(start_color="85929E", end_color="85929E", fill_type="solid")
ALT_ROW_BG = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
TITLE_BG = PatternFill(start_color="1ABC9C", end_color="1ABC9C", fill_type="solid")
INFO_BG = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid")

# Fonts
TITLE_FONT = Font(name='Arial', size=16, bold=True, color="FFFFFF")
HEADER_FONT = Font(name='Arial', size=10, bold=True, color="FFFFFF")
SUBHEADER_FONT = Font(name='Arial', size=9, bold=True, color="FFFFFF")
LABEL_FONT = Font(name='Arial', size=10, bold=True, color="2C3E50")
VALUE_FONT = Font(name='Arial', size=10, color="000000")
NORMAL_FONT = Font(name='Arial', size=9, color="000000")
SMALL_FONT = Font(name='Arial', size=8, color="7F8C8D")

# Borders
THIN_BORDER = Border(
    left=Side(style='thin', color='BDC3C7'),
    right=Side(style='thin', color='BDC3C7'),
    top=Side(style='thin', color='BDC3C7'),
    bottom=Side(style='thin', color='BDC3C7')
)

MEDIUM_BORDER = Border(
    left=Side(style='medium', color='2C3E50'),
    right=Side(style='medium', color='2C3E50'),
    top=Side(style='medium', color='2C3E50'),
    bottom=Side(style='medium', color='2C3E50')
)

# Alignments
CENTER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT_ALIGN = Alignment(horizontal='left', vertical='center', wrap_text=True)
RIGHT_ALIGN = Alignment(horizontal='right', vertical='center', wrap_text=True)


class BOMExcelGenerator:
    """Generate professional Excel workbook for BOM export"""
    
    def __init__(self):
        self.wb = None
    
    def generate(self, bom_info: Dict[str, Any],
                 materials: pd.DataFrame,
                 alternatives_data: Dict[int, pd.DataFrame]) -> bytes:
        """
        Generate Excel workbook for BOM
        
        Args:
            bom_info: BOM header information
            materials: DataFrame of BOM materials
            alternatives_data: Dict mapping detail_id to alternatives DataFrame
            
        Returns:
            Excel file as bytes
        """
        self.wb = Workbook()
        
        # Remove default sheet
        default_sheet = self.wb.active
        self.wb.remove(default_sheet)
        
        # Create sheets
        self._create_summary_sheet(bom_info, materials)
        self._create_materials_sheet(materials)
        self._create_alternatives_sheet(materials, alternatives_data)
        self._create_metadata_sheet(bom_info)
        
        # Save to bytes
        buffer = BytesIO()
        self.wb.save(buffer)
        buffer.seek(0)
        
        return buffer.getvalue()
    
    def _create_summary_sheet(self, bom_info: Dict, materials: pd.DataFrame):
        """Create summary sheet with BOM overview"""
        ws = self.wb.create_sheet("Summary", 0)
        
        # Set column widths
        ws.column_dimensions['A'].width = 5
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 45
        ws.column_dimensions['D'].width = 20
        ws.column_dimensions['E'].width = 45
        
        row = 1
        
        # Title row
        ws.merge_cells(f'B{row}:E{row}')
        title_cell = ws.cell(row=row, column=2, value="BILL OF MATERIALS (BOM)")
        title_cell.font = TITLE_FONT
        title_cell.fill = TITLE_BG
        title_cell.alignment = CENTER_ALIGN
        ws.row_dimensions[row].height = 30
        row += 2
        
        # BOM Code subtitle
        ws.merge_cells(f'B{row}:E{row}')
        ws.cell(row=row, column=2, value=bom_info.get('bom_code', '')).font = Font(size=14, bold=True)
        ws.cell(row=row, column=2).alignment = CENTER_ALIGN
        row += 2
        
        # BOM Information Section
        ws.merge_cells(f'B{row}:E{row}')
        section_cell = ws.cell(row=row, column=2, value="📋 BOM Information")
        section_cell.font = Font(size=12, bold=True, color="2C3E50")
        row += 1
        
        # Info grid - 2 columns
        info_rows = [
            ('BOM Code', bom_info.get('bom_code', ''), 'Output Product', f"{bom_info.get('product_code', '')} - {bom_info.get('product_name', '')}"),
            ('BOM Name', bom_info.get('bom_name', ''), 'Output Quantity', f"{bom_info.get('output_qty', 0):,.2f} {bom_info.get('uom', '')}"),
            ('BOM Type', bom_info.get('bom_type', ''), 'Effective Date', str(bom_info.get('effective_date', 'N/A'))),
            ('Status', bom_info.get('status', ''), 'Version', str(bom_info.get('version', 1))),
            ('Created By', bom_info.get('creator_name', 'Unknown'), 'Created Date', self._format_datetime(bom_info.get('created_date'))),
        ]
        
        for label1, value1, label2, value2 in info_rows:
            # Left column
            cell_label1 = ws.cell(row=row, column=2, value=label1)
            cell_label1.font = LABEL_FONT
            cell_label1.fill = INFO_BG
            cell_label1.border = THIN_BORDER
            
            cell_value1 = ws.cell(row=row, column=3, value=value1)
            cell_value1.font = VALUE_FONT
            cell_value1.border = THIN_BORDER
            
            # Right column
            cell_label2 = ws.cell(row=row, column=4, value=label2)
            cell_label2.font = LABEL_FONT
            cell_label2.fill = INFO_BG
            cell_label2.border = THIN_BORDER
            
            cell_value2 = ws.cell(row=row, column=5, value=value2)
            cell_value2.font = VALUE_FONT
            cell_value2.border = THIN_BORDER
            
            row += 1
        
        # Notes row
        if bom_info.get('notes'):
            ws.merge_cells(f'C{row}:E{row}')
            ws.cell(row=row, column=2, value='Notes').font = LABEL_FONT
            ws.cell(row=row, column=2).fill = INFO_BG
            ws.cell(row=row, column=2).border = THIN_BORDER
            ws.cell(row=row, column=3, value=bom_info.get('notes', '')).border = THIN_BORDER
            row += 1
        
        row += 1
        
        # Materials Summary Section
        ws.merge_cells(f'B{row}:E{row}')
        section_cell = ws.cell(row=row, column=2, value="🧱 Materials Summary")
        section_cell.font = Font(size=12, bold=True, color="2C3E50")
        row += 1
        
        if not materials.empty:
            # Summary statistics
            type_counts = materials['material_type'].value_counts()
            total_materials = len(materials)
            total_alts = int(materials['alternatives_count'].sum()) if 'alternatives_count' in materials.columns else 0
            
            summary_data = [
                ('Total Materials', total_materials, 'Total Alternatives', total_alts),
                ('Raw Materials', type_counts.get('RAW_MATERIAL', 0), 'Packaging', type_counts.get('PACKAGING', 0)),
                ('Consumables', type_counts.get('CONSUMABLE', 0), '', ''),
            ]
            
            for label1, value1, label2, value2 in summary_data:
                if label1:
                    ws.cell(row=row, column=2, value=label1).font = LABEL_FONT
                    ws.cell(row=row, column=2).fill = INFO_BG
                    ws.cell(row=row, column=2).border = THIN_BORDER
                    ws.cell(row=row, column=3, value=value1).font = VALUE_FONT
                    ws.cell(row=row, column=3).border = THIN_BORDER
                    
                if label2:
                    ws.cell(row=row, column=4, value=label2).font = LABEL_FONT
                    ws.cell(row=row, column=4).fill = INFO_BG
                    ws.cell(row=row, column=4).border = THIN_BORDER
                    ws.cell(row=row, column=5, value=value2).font = VALUE_FONT
                    ws.cell(row=row, column=5).border = THIN_BORDER
                
                row += 1
        else:
            ws.cell(row=row, column=2, value="No materials in this BOM").font = SMALL_FONT
            row += 1
        
        row += 2
        
        # Footer
        ws.merge_cells(f'B{row}:E{row}')
        footer_cell = ws.cell(row=row, column=2, 
                              value=f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        footer_cell.font = SMALL_FONT
        footer_cell.alignment = CENTER_ALIGN
    
    def _create_materials_sheet(self, materials: pd.DataFrame):
        """Create materials sheet with detailed list"""
        ws = self.wb.create_sheet("Materials")
        
        if materials.empty:
            ws.cell(row=1, column=1, value="No materials in this BOM")
            return
        
        # Headers
        headers = ['#', 'Material Code', 'Material Name', 'Type', 'Quantity', 
                   'UOM', 'Scrap Rate', 'Current Stock', 'Alternatives']
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = HEADER_FONT
            cell.fill = HEADER_BG
            cell.alignment = CENTER_ALIGN
            cell.border = THIN_BORDER
        
        # Set column widths
        col_widths = [5, 18, 45, 15, 12, 10, 12, 15, 12]
        for i, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width
        
        # Data rows
        for idx, (_, mat) in enumerate(materials.iterrows(), 1):
            row_num = idx + 1
            
            # Alternate row coloring
            fill = ALT_ROW_BG if idx % 2 == 0 else None
            
            row_data = [
                idx,
                mat.get('material_code', ''),
                mat.get('material_name', ''),
                mat.get('material_type', ''),
                float(mat.get('quantity', 0)),
                mat.get('uom', ''),
                f"{float(mat.get('scrap_rate', 0)):.2f}%",
                float(mat.get('current_stock', 0)),
                int(mat.get('alternatives_count', 0))
            ]
            
            alignments = [CENTER_ALIGN, LEFT_ALIGN, LEFT_ALIGN, CENTER_ALIGN, 
                         RIGHT_ALIGN, CENTER_ALIGN, RIGHT_ALIGN, RIGHT_ALIGN, CENTER_ALIGN]
            
            for col, (value, align) in enumerate(zip(row_data, alignments), 1):
                cell = ws.cell(row=row_num, column=col, value=value)
                cell.font = NORMAL_FONT
                cell.alignment = align
                cell.border = THIN_BORDER
                if fill:
                    cell.fill = fill
        
        # Freeze header row
        ws.freeze_panes = 'A2'
        
        # Auto-filter
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(materials) + 1}"
    
    def _create_alternatives_sheet(self, materials: pd.DataFrame,
                                    alternatives_data: Dict[int, pd.DataFrame]):
        """Create alternatives sheet with all alternatives"""
        ws = self.wb.create_sheet("Alternatives")
        
        # Collect all alternatives
        all_alts = []
        for _, mat in materials.iterrows():
            detail_id = int(mat['id'])
            alternatives = alternatives_data.get(detail_id)
            
            if alternatives is not None and not alternatives.empty:
                for _, alt in alternatives.iterrows():
                    all_alts.append({
                        'Primary Code': mat['material_code'],
                        'Primary Name': mat['material_name'],
                        'Priority': alt['priority'],
                        'Alt Code': alt['material_code'],
                        'Alt Name': alt['material_name'],
                        'Quantity': float(alt['quantity']),
                        'UOM': alt['uom'],
                        'Scrap Rate': f"{float(alt.get('scrap_rate', 0)):.2f}%",
                        'Status': 'Active' if alt['is_active'] else 'Inactive',
                        'Notes': alt.get('notes', '')
                    })
        
        if not all_alts:
            ws.cell(row=1, column=1, value="No alternatives defined for this BOM")
            return
        
        # Headers
        headers = ['Primary Code', 'Primary Name', 'Priority', 'Alt Code', 'Alt Name',
                   'Quantity', 'UOM', 'Scrap Rate', 'Status', 'Notes']
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = HEADER_FONT
            cell.fill = SUBHEADER_BG
            cell.alignment = CENTER_ALIGN
            cell.border = THIN_BORDER
        
        # Set column widths
        col_widths = [15, 35, 8, 15, 35, 12, 8, 12, 10, 25]
        for i, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width
        
        # Data rows
        for idx, alt in enumerate(all_alts, 1):
            row_num = idx + 1
            fill = ALT_ROW_BG if idx % 2 == 0 else None
            
            for col, header in enumerate(headers, 1):
                value = alt.get(header, '')
                cell = ws.cell(row=row_num, column=col, value=value)
                cell.font = NORMAL_FONT
                cell.border = THIN_BORDER
                if fill:
                    cell.fill = fill
                
                # Alignment based on column type
                if header in ['Priority', 'UOM', 'Status']:
                    cell.alignment = CENTER_ALIGN
                elif header in ['Quantity', 'Scrap Rate']:
                    cell.alignment = RIGHT_ALIGN
                else:
                    cell.alignment = LEFT_ALIGN
        
        # Freeze header row
        ws.freeze_panes = 'A2'
        
        # Auto-filter
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(all_alts) + 1}"
    
    def _create_metadata_sheet(self, bom_info: Dict):
        """Create metadata sheet with export information"""
        ws = self.wb.create_sheet("Metadata")
        
        # Set column widths
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 50
        
        metadata = [
            ('Document Type', 'Bill of Materials (BOM)'),
            ('BOM Code', bom_info.get('bom_code', '')),
            ('BOM Name', bom_info.get('bom_name', '')),
            ('Export Date', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            ('Export Format', 'Microsoft Excel (XLSX)'),
            ('', ''),
            ('Created By', bom_info.get('creator_name', 'Unknown')),
            ('Created Date', self._format_datetime(bom_info.get('created_date'))),
            ('Last Updated By', bom_info.get('updater_name', '') or 'N/A'),
            ('Last Updated', self._format_datetime(bom_info.get('updated_date')) or 'N/A'),
            ('', ''),
            ('BOM Status', bom_info.get('status', '')),
            ('BOM Version', bom_info.get('version', 1)),
            ('Effective Date', str(bom_info.get('effective_date', 'N/A'))),
            ('', ''),
            ('Output Product', f"{bom_info.get('product_code', '')} - {bom_info.get('product_name', '')}"),
            ('Output Quantity', f"{bom_info.get('output_qty', 0):,.2f} {bom_info.get('uom', '')}"),
            ('Material Count', bom_info.get('material_count', 0)),
            ('Total Alternatives', bom_info.get('total_alternatives', 0)),
            ('', ''),
            ('Notes', bom_info.get('notes', '') or 'N/A'),
        ]
        
        for row, (label, value) in enumerate(metadata, 1):
            if label:
                cell_label = ws.cell(row=row, column=1, value=label)
                cell_label.font = LABEL_FONT
                cell_label.fill = INFO_BG
                cell_label.border = THIN_BORDER
                
                cell_value = ws.cell(row=row, column=2, value=value)
                cell_value.font = VALUE_FONT
                cell_value.border = THIN_BORDER
    
    def _format_datetime(self, dt) -> str:
        """Format datetime for display"""
        if dt is None:
            return 'N/A'
        if hasattr(dt, 'strftime'):
            return dt.strftime('%d/%m/%Y %H:%M:%S')
        return str(dt) if dt else 'N/A'


# ==================== Helper Function ====================

def generate_bom_excel(bom_info: Dict[str, Any],
                       materials: pd.DataFrame,
                       alternatives_data: Dict[int, pd.DataFrame]) -> bytes:
    """
    Convenience function to generate BOM Excel
    
    Args:
        bom_info: BOM header information
        materials: DataFrame of BOM materials
        alternatives_data: Dict mapping detail_id to alternatives DataFrame
        
    Returns:
        Excel file as bytes
    """
    generator = BOMExcelGenerator()
    return generator.generate(bom_info, materials, alternatives_data)
