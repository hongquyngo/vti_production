# utils/supply_chain_gap/export.py

"""
Export Module for Supply Chain GAP Analysis
Multi-sheet Excel export
"""

import pandas as pd
from io import BytesIO
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from .result import SupplyChainGAPResult

logger = logging.getLogger(__name__)


def export_to_excel(
    result: SupplyChainGAPResult,
    filter_values: Optional[Dict[str, Any]] = None,
    include_raw_materials: bool = True,
    include_actions: bool = True
) -> BytesIO:
    """
    Export Supply Chain GAP results to Excel.
    
    Sheets:
    - Summary
    - FG GAP
    - Manufacturing
    - Trading
    - Raw Material GAP (optional)
    - Actions (optional)
    
    Returns:
        BytesIO buffer containing Excel file
    """
    
    buffer = BytesIO()
    
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        
        # Sheet 1: Summary
        _write_summary_sheet(writer, result, filter_values)
        
        # Sheet 2: FG GAP
        if not result.fg_gap_df.empty:
            _write_fg_gap_sheet(writer, result)
        
        # Sheet 3: Manufacturing
        if not result.manufacturing_df.empty:
            _write_manufacturing_sheet(writer, result)
        
        # Sheet 4: Trading
        if not result.trading_df.empty:
            _write_trading_sheet(writer, result)
        
        # Sheet 5: Semi-Finished Materials (if multi-level)
        if include_raw_materials and not result.semi_finished_gap_df.empty:
            _write_semi_finished_sheet(writer, result)
        
        # Sheet 6: Raw Material GAP
        if include_raw_materials and not result.raw_gap_df.empty:
            _write_raw_gap_sheet(writer, result)
        
        # Sheet 6: Actions
        if include_actions and result.has_actions():
            _write_actions_sheet(writer, result)
        
        # Sheet 7: Period GAP (v2.2)
        if result.has_period_data():
            _write_period_gap_sheet(writer, result)
    
    buffer.seek(0)
    return buffer


def _write_summary_sheet(
    writer: pd.ExcelWriter,
    result: SupplyChainGAPResult,
    filter_values: Optional[Dict[str, Any]]
):
    """Write summary sheet"""
    
    summary = result.get_summary()
    metrics = result.get_metrics()
    
    data = [
        ['Supply Chain GAP Analysis - Summary', ''],
        ['Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        ['', ''],
        ['--- FINISHED GOODS ---', ''],
        ['Total Products', metrics.get('fg_total', 0)],
        ['Shortage Count', metrics.get('fg_shortage', 0)],
        ['Surplus Count', metrics.get('fg_surplus', 0)],
        ['At Risk Value (USD)', f"${metrics.get('at_risk_value', 0):,.2f}"],
        ['Affected Customers', metrics.get('affected_customers', 0)],
        ['', ''],
        ['--- CLASSIFICATION ---', ''],
        ['Manufacturing Products', metrics.get('manufacturing_count', 0)],
        ['Trading Products', metrics.get('trading_count', 0)],
        ['', ''],
        ['--- RAW MATERIALS ---', ''],
        ['Total Raw Materials', metrics.get('raw_total', 0)],
        ['Raw Materials with Shortage', metrics.get('raw_shortage', 0)],
        ['Semi-Finished Products', metrics.get('semi_finished_total', 0)],
        ['Semi-Finished with Shortage', metrics.get('semi_finished_shortage', 0)],
        ['Max BOM Depth', metrics.get('max_bom_depth', 1)],
        ['', ''],
        ['--- ACTIONS ---', ''],
        ['MO to Create', metrics.get('mo_count', 0)],
        ['PO for Finished Goods', metrics.get('po_fg_count', 0)],
        ['PO for Raw Materials', metrics.get('po_raw_count', 0)]
    ]
    
    # Period analysis section
    if metrics.get('has_period_data'):
        data.append(['', ''])
        data.append(['--- PERIOD ANALYSIS ---', ''])
        data.append(['Period Type', metrics.get('period_type', 'Weekly')])
        data.append(['Total Periods', metrics.get('period_total_periods', 0)])
        data.append(['Shortage Periods', metrics.get('period_shortage_periods', 0)])
        data.append(['Shortage Products (Period)', metrics.get('period_shortage_products', 0)])
        data.append(['Total Shortage Qty', f"{metrics.get('period_total_shortage_qty', 0):,.0f}"])
        data.append(['Avg Fulfillment Rate', f"{metrics.get('period_avg_fulfillment_rate', 0):.1f}%"])
    
    # Add filter info
    if filter_values:
        data.append(['', ''])
        data.append(['--- FILTERS APPLIED ---', ''])
        data.append(['Entity', filter_values.get('entity', 'All')])
        data.append(['Include FG Safety', 'Yes' if filter_values.get('include_fg_safety') else 'No'])
        data.append(['Include Raw Safety', 'Yes' if filter_values.get('include_raw_safety') else 'No'])
        data.append(['Exclude Expired', 'Yes' if filter_values.get('exclude_expired') else 'No'])
        data.append(['MO Expected in Supply', 'Yes' if filter_values.get('include_mo_expected') else 'No'])
        data.append(['Existing MO Demand', 'Yes' if filter_values.get('include_existing_mo') else 'No'])
        data.append(['Include DRAFT MO', 'Yes' if filter_values.get('include_draft_mo') else 'No'])
        
        # Double-count warning in export
        if not filter_values.get('include_mo_expected') and filter_values.get('include_existing_mo'):
            data.append(['', ''])
            data.append(['⚠️ WARNING', 'Double-count risk: MO Expected OFF + Existing MO ON'])
    
    df = pd.DataFrame(data, columns=['Metric', 'Value'])
    df.to_excel(writer, sheet_name='Summary', index=False)


def _write_fg_gap_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write FG GAP sheet"""
    
    df = result.fg_gap_df.copy()
    
    # Select columns
    columns = [
        'pt_code', 'product_name', 'package_size', 'brand', 'standard_uom',
        'total_supply', 'supply_mo_expected', 'total_demand', 'safety_stock_qty',
        'available_supply', 'net_gap', 'true_gap',
        'coverage_ratio', 'gap_status', 'at_risk_value', 'customer_count'
    ]
    
    available = [c for c in columns if c in df.columns]
    export_df = df[available].copy()
    
    # Rename columns
    rename_map = {
        'pt_code': 'Code',
        'product_name': 'Part Number',
        'package_size': 'Pkg Size',
        'brand': 'Brand',
        'standard_uom': 'UOM',
        'total_supply': 'Total Supply',
        'supply_mo_expected': 'MO Expected',
        'total_demand': 'Total Demand',
        'safety_stock_qty': 'Safety Stock',
        'available_supply': 'Available Supply',
        'net_gap': 'Net GAP',
        'true_gap': 'True GAP',
        'coverage_ratio': 'Coverage',
        'gap_status': 'Status',
        'at_risk_value': 'At Risk Value',
        'customer_count': 'Customers'
    }
    export_df.rename(columns=rename_map, inplace=True)
    
    export_df.to_excel(writer, sheet_name='FG GAP', index=False)


def _write_manufacturing_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write manufacturing products sheet"""
    
    mfg_shortage = result.get_manufacturing_shortage()
    
    if mfg_shortage.empty:
        pd.DataFrame({'Note': ['No manufacturing products with shortage']}).to_excel(
            writer, sheet_name='Manufacturing', index=False
        )
        return
    
    # Add production status (use batch method for performance)
    all_statuses = result.get_all_production_statuses()
    
    data = []
    for _, row in mfg_shortage.iterrows():
        status = all_statuses.get(row['product_id'], result.get_production_status(row['product_id']))
        data.append({
            'Code': row.get('pt_code', ''),
            'Part Number': row.get('product_name', ''),
            'Pkg Size': row.get('package_size', '') if pd.notna(row.get('package_size')) else '',
            'Brand': row.get('brand', ''),
            'UOM': row.get('standard_uom', ''),
            'Net GAP': row.get('net_gap', 0),
            'Can Produce': 'Yes' if status.get('can_produce') else 'No',
            'Status': status.get('status', ''),
            'Reason': status.get('reason', ''),
            'BOM Code': status.get('bom_code', ''),
            'Limiting Materials': ', '.join(status.get('limiting_materials', [])[:3])
        })
    
    pd.DataFrame(data).to_excel(writer, sheet_name='Manufacturing', index=False)


def _write_trading_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write trading products sheet"""
    
    trading_shortage = result.get_trading_shortage()
    
    if trading_shortage.empty:
        pd.DataFrame({'Note': ['No trading products with shortage']}).to_excel(
            writer, sheet_name='Trading', index=False
        )
        return
    
    columns = ['pt_code', 'product_name', 'package_size', 'brand', 'standard_uom', 'net_gap', 'gap_status', 'at_risk_value']
    available = [c for c in columns if c in trading_shortage.columns]
    
    export_df = trading_shortage[available].copy()
    export_df['Action'] = 'Create PO'
    
    export_df.rename(columns={
        'pt_code': 'Code',
        'product_name': 'Part Number',
        'package_size': 'Pkg Size',
        'brand': 'Brand',
        'standard_uom': 'UOM',
        'net_gap': 'Net GAP',
        'gap_status': 'Status',
        'at_risk_value': 'At Risk Value'
    }, inplace=True)
    
    export_df.to_excel(writer, sheet_name='Trading', index=False)


def _write_semi_finished_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write semi-finished material GAP sheet (multi-level BOM intermediates)"""
    
    df = result.semi_finished_gap_df.copy()
    
    if df.empty:
        pd.DataFrame({'Note': ['No semi-finished materials']}).to_excel(
            writer, sheet_name='Semi-Finished', index=False
        )
        return
    
    columns = [
        'material_pt_code', 'material_name', 'material_package_size', 'material_brand', 'material_uom',
        'bom_level', 'required_qty', 'total_supply', 'safety_stock_qty',
        'net_gap', 'coverage_ratio', 'gap_status'
    ]
    available = [c for c in columns if c in df.columns]
    export_df = df[available].copy()
    
    # Add netting status
    if 'net_gap' in export_df.columns:
        export_df['Supply Netting'] = export_df['net_gap'].apply(
            lambda x: 'Supply covers' if x >= 0 else 'Shortage propagates to next level'
        )
    
    export_df.rename(columns={
        'material_pt_code': 'Code',
        'material_name': 'Part Number',
        'material_package_size': 'Pkg Size',
        'material_brand': 'Brand',
        'material_uom': 'UOM',
        'bom_level': 'BOM Level',
        'required_qty': 'Required Qty',
        'total_supply': 'Total Supply',
        'safety_stock_qty': 'Safety Stock',
        'net_gap': 'Net GAP',
        'coverage_ratio': 'Coverage',
        'gap_status': 'Status'
    }, inplace=True)
    
    export_df.to_excel(writer, sheet_name='Semi-Finished', index=False)


def _write_raw_gap_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write raw material GAP sheet"""
    
    df = result.raw_gap_df.copy()
    
    if df.empty:
        pd.DataFrame({'Note': ['No raw material data']}).to_excel(
            writer, sheet_name='Raw Materials', index=False
        )
        return
    
    columns = [
        'material_pt_code', 'material_name', 'material_package_size', 'material_brand', 'material_uom',
        'material_type', 'is_primary', 'bom_level', 'fg_product_count',
        'required_qty', 'existing_mo_demand', 'total_required_qty',
        'total_supply', 'safety_stock_qty', 'net_gap', 'coverage_ratio', 'gap_status'
    ]
    
    available = [c for c in columns if c in df.columns]
    export_df = df[available].copy()
    
    # Format is_primary
    if 'is_primary' in export_df.columns:
        export_df['is_primary'] = export_df['is_primary'].apply(lambda x: 'Yes' if x else 'No')
    
    export_df.rename(columns={
        'material_pt_code': 'Code',
        'material_name': 'Part Number',
        'material_package_size': 'Pkg Size',
        'material_brand': 'Brand',
        'material_uom': 'UOM',
        'material_type': 'Type',
        'is_primary': 'Is Primary',
        'bom_level': 'BOM Level',
        'fg_product_count': 'FG Products',
        'required_qty': 'New Demand',
        'existing_mo_demand': 'Existing MO',
        'total_required_qty': 'Total Required',
        'total_supply': 'Total Supply',
        'safety_stock_qty': 'Safety Stock',
        'net_gap': 'Net GAP',
        'coverage_ratio': 'Coverage',
        'gap_status': 'Status'
    }, inplace=True)
    
    export_df.to_excel(writer, sheet_name='Raw Materials', index=False)


def _write_actions_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write actions sheet"""
    
    actions = result.get_all_actions()
    
    if not actions:
        pd.DataFrame({'Note': ['No actions required']}).to_excel(
            writer, sheet_name='Actions', index=False
        )
        return
    
    df = pd.DataFrame(actions)
    
    # Select columns
    columns = ['action_type', 'category', 'pt_code', 'product_name', 'package_size', 'brand', 'quantity', 'uom', 'priority', 'reason']
    available = [c for c in columns if c in df.columns]
    
    export_df = df[available].copy()
    
    export_df.rename(columns={
        'action_type': 'Action Type',
        'category': 'Category',
        'pt_code': 'Code',
        'product_name': 'Part Number',
        'package_size': 'Pkg Size',
        'brand': 'Brand',
        'quantity': 'Quantity',
        'uom': 'UOM',
        'priority': 'Priority',
        'reason': 'Reason'
    }, inplace=True)
    
    export_df.to_excel(writer, sheet_name='Actions', index=False)


def _write_period_gap_sheet(writer: pd.ExcelWriter, result: SupplyChainGAPResult):
    """Write period GAP sheet (v2.2)"""
    
    df = result.fg_period_gap_df.copy()
    
    if df.empty:
        pd.DataFrame({'Note': ['No period GAP data']}).to_excel(
            writer, sheet_name='Period GAP', index=False
        )
        return
    
    columns = [
        'pt_code', 'product_name', 'brand', 'standard_uom', 'period',
        'begin_inventory', 'supply_in_period', 'total_available',
        'demand_in_period', 'backlog_from_prev', 'effective_demand',
        'gap_quantity', 'fulfillment_rate', 'fulfillment_status',
        'backlog_to_next', 'customer_count'
    ]
    available = [c for c in columns if c in df.columns]
    export_df = df[available].copy()
    
    # Use period_display if available
    if 'period_display' in df.columns:
        export_df['period'] = df['period_display']
    
    rename_map = {
        'pt_code': 'Code', 'product_name': 'Part Number',
        'brand': 'Brand', 'standard_uom': 'UOM', 'period': 'Period',
        'begin_inventory': 'Begin Inv', 'supply_in_period': 'Supply In',
        'total_available': 'Available', 'demand_in_period': 'Demand',
        'backlog_from_prev': 'Backlog In', 'effective_demand': 'Total Need',
        'gap_quantity': 'GAP', 'fulfillment_rate': 'Fill %',
        'fulfillment_status': 'Status', 'backlog_to_next': 'Backlog Out',
        'customer_count': 'Customers'
    }
    export_df.rename(columns=rename_map, inplace=True)
    
    export_df.to_excel(writer, sheet_name='Period GAP', index=False)


def get_export_filename(prefix: str = "supply_chain_gap") -> str:
    """Generate export filename with timestamp"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{prefix}_{timestamp}.xlsx"