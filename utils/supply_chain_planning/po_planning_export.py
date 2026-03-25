# utils/supply_chain_planning/po_planning_export.py

"""
Export Module for PO Planning — multi-sheet Excel export.

Sheets:
1. Summary — metrics, urgency distribution, coverage
2. PO Lines — all PO line items with full detail
3. By Vendor — vendor-grouped summary
4. Unmatched — products without vendor
"""

import pandas as pd
from io import BytesIO
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from .po_result import POSuggestionResult
from .planning_constants import URGENCY_LEVELS, SHORTAGE_SOURCE, PRICE_SOURCE

logger = logging.getLogger(__name__)


def export_po_suggestions_to_excel(
    result: POSuggestionResult,
    gap_summary: Optional[Dict[str, Any]] = None,
) -> BytesIO:
    """
    Export PO suggestions to Excel workbook.

    Args:
        result: POSuggestionResult from POPlanner
        gap_summary: Optional summary from SCM GAP result for context

    Returns:
        BytesIO buffer with .xlsx content
    """
    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:

        # Sheet 1: Summary
        _write_summary_sheet(writer, result, gap_summary)

        # Sheet 2: All PO Lines
        _write_po_lines_sheet(writer, result)

        # Sheet 3: By Vendor
        _write_vendor_sheet(writer, result)

        # Sheet 4: Unmatched
        if result.has_unmatched():
            _write_unmatched_sheet(writer, result)

    buffer.seek(0)
    return buffer


def _write_summary_sheet(
    writer: pd.ExcelWriter,
    result: POSuggestionResult,
    gap_summary: Optional[Dict[str, Any]],
):
    """Write summary sheet with metrics."""
    metrics = result.get_summary()

    data = [
        ['PO Planning Summary', ''],
        ['Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        ['Strategy', metrics.get('strategy', 'CHEAPEST')],
        ['', ''],
        ['--- PO SUGGESTIONS ---', ''],
        ['Total PO Lines', metrics.get('total_po_lines', 0)],
        ['FG Trading Lines', metrics.get('fg_lines', 0)],
        ['Raw Material Lines', metrics.get('raw_lines', 0)],
        ['Total Vendors', metrics.get('total_vendors', 0)],
        ['Total Value (USD)', f"${metrics.get('total_value_usd', 0):,.2f}"],
        ['', ''],
        ['--- URGENCY ---', ''],
        ['Overdue (must order NOW)', metrics.get('overdue_count', 0)],
        ['Critical (≤3 days)', metrics.get('critical_count', 0)],
    ]

    # Urgency distribution
    dist = metrics.get('urgency_distribution', {})
    for level_key in ['OVERDUE', 'CRITICAL', 'URGENT', 'THIS_WEEK', 'PLANNED']:
        cnt = dist.get(level_key, 0)
        if cnt > 0:
            cfg = URGENCY_LEVELS.get(level_key, {})
            data.append([f"  {cfg.get('label', level_key)}", cnt])

    # Unmatched
    data.append(['', ''])
    data.append(['--- VENDOR MATCHING ---', ''])
    data.append(['Matched to Vendor', metrics.get('total_po_lines', 0)])
    data.append(['No Vendor Found', metrics.get('unmatched_count', 0)])

    # GAP context
    if gap_summary:
        data.append(['', ''])
        data.append(['--- SOURCE: SCM GAP ---', ''])
        for key in ['fg_shortage_items', 'po_fg_count', 'po_raw_count', 'at_risk_value']:
            if key in gap_summary:
                data.append([key.replace('_', ' ').title(), gap_summary[key]])

    df = pd.DataFrame(data, columns=['Metric', 'Value'])
    df.to_excel(writer, sheet_name='Summary', index=False)


def _write_po_lines_sheet(writer: pd.ExcelWriter, result: POSuggestionResult):
    """Write all PO lines detail sheet."""
    lines_df = result.get_all_lines_df()
    if lines_df.empty:
        pd.DataFrame({'Note': ['No PO suggestions']}).to_excel(
            writer, sheet_name='PO Lines', index=False)
        return

    # Sort by urgency
    lines_df = lines_df.sort_values(
        ['urgency_priority', 'vendor_name', 'pt_code']
    ).reset_index(drop=True)

    # Select and rename columns
    columns = [
        'urgency_level', 'shortage_source', 'vendor_name', 'vendor_code',
        'pt_code', 'product_name', 'brand', 'package_size', 'standard_uom',
        'shortage_qty', 'pending_po_qty', 'net_shortage_qty',
        'suggested_qty', 'moq', 'spq', 'moq_applied', 'spq_applied', 'excess_qty',
        'unit_price', 'unit_price_usd', 'currency_code', 'line_value_usd',
        'vat_percent',
        'price_source', 'costbook_number', 'last_po_number',
        'lead_time_days', 'lead_time_source', 'vendor_reliability',
        'demand_date', 'must_order_by', 'expected_arrival',
        'days_until_must_order', 'is_overdue',
        'trade_term', 'payment_term', 'shipping_mode',
        'match_notes', 'quantity_notes',
    ]

    available = [c for c in columns if c in lines_df.columns]
    export_df = lines_df[available].copy()

    rename = {
        'urgency_level': 'Urgency',
        'shortage_source': 'Source',
        'vendor_name': 'Vendor',
        'vendor_code': 'Vendor Code',
        'pt_code': 'Code',
        'product_name': 'Product',
        'brand': 'Brand',
        'package_size': 'Pkg Size',
        'standard_uom': 'UOM',
        'shortage_qty': 'GAP Shortage',
        'pending_po_qty': 'Pending PO',
        'net_shortage_qty': 'Net Need',
        'suggested_qty': 'Order Qty',
        'moq': 'MOQ',
        'spq': 'SPQ',
        'moq_applied': 'MOQ Applied',
        'spq_applied': 'SPQ Applied',
        'excess_qty': 'Excess Qty',
        'unit_price': 'Unit Price',
        'unit_price_usd': 'Unit Price (USD)',
        'currency_code': 'Currency',
        'line_value_usd': 'Line Value (USD)',
        'vat_percent': 'VAT %',
        'price_source': 'Price Source',
        'costbook_number': 'Costbook #',
        'last_po_number': 'Last PO #',
        'lead_time_days': 'Lead Time (days)',
        'lead_time_source': 'LT Source',
        'vendor_reliability': 'Reliability',
        'demand_date': 'Demand Date',
        'must_order_by': 'Must Order By',
        'expected_arrival': 'Expected Arrival',
        'days_until_must_order': 'Days to Order',
        'is_overdue': 'Overdue?',
        'trade_term': 'Trade Term',
        'payment_term': 'Payment Term',
        'shipping_mode': 'Shipping',
        'match_notes': 'Vendor Match Notes',
        'quantity_notes': 'Qty Notes',
    }
    export_df.rename(columns=rename, inplace=True)

    # Format booleans
    for col in ['MOQ Applied', 'SPQ Applied', 'Overdue?']:
        if col in export_df.columns:
            export_df[col] = export_df[col].apply(
                lambda x: 'Yes' if x else 'No'
            )

    export_df.to_excel(writer, sheet_name='PO Lines', index=False)


def _write_vendor_sheet(writer: pd.ExcelWriter, result: POSuggestionResult):
    """Write vendor summary sheet."""
    vendor_df = result.get_vendor_summary_df()
    if vendor_df.empty:
        pd.DataFrame({'Note': ['No vendor data']}).to_excel(
            writer, sheet_name='By Vendor', index=False)
        return

    vendor_df = vendor_df.sort_values('max_urgency_priority').reset_index(drop=True)

    rename = {
        'vendor_name': 'Vendor',
        'vendor_code': 'Code',
        'vendor_location_type': 'Location',
        'vendor_reliability': 'Reliability',
        'total_lines': 'PO Lines',
        'total_value_usd': 'Total Value (USD)',
        'primary_currency': 'Currency',
        'max_urgency_level': 'Max Urgency',
        'max_urgency_priority': 'Priority',
        'trade_term': 'Trade Term',
        'payment_term': 'Payment Term',
    }
    export_df = vendor_df.rename(columns=rename)

    export_df.to_excel(writer, sheet_name='By Vendor', index=False)


def _write_unmatched_sheet(writer: pd.ExcelWriter, result: POSuggestionResult):
    """Write unmatched items sheet."""
    unmatched_df = result.get_unmatched_df()
    if unmatched_df.empty:
        return

    rename = {
        'pt_code': 'Code',
        'product_name': 'Product',
        'brand': 'Brand',
        'shortage_source': 'Source',
        'shortage_qty': 'Shortage Qty',
        'uom': 'UOM',
        'reason': 'Reason',
    }
    export_df = unmatched_df.rename(columns=rename)
    export_df.to_excel(writer, sheet_name='Unmatched', index=False)


def get_po_export_filename(prefix: str = "po_suggestions") -> str:
    """Generate export filename with timestamp."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{prefix}_{ts}.xlsx"
