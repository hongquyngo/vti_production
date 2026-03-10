# utils/supply_chain_gap/constants.py

"""
Constants for Supply Chain GAP Analysis
Independent module for full multi-level analysis
"""

# =============================================================================
# VERSION
# =============================================================================
VERSION = "2.3.0"

# =============================================================================
# MULTI-LEVEL BOM CONFIGURATION
# =============================================================================
MAX_BOM_LEVELS = 10  # Safety limit for recursive BOM explosion

MATERIAL_LEVEL_TYPES = {
    'SEMI_FINISHED': {
        'label': 'Semi-Finished',
        'icon': '🔶',
        'color': '#F59E0B',
        'description': 'Material with own BOM — can be produced from sub-materials'
    },
    'RAW_MATERIAL': {
        'label': 'Raw Material',
        'icon': '🧪',
        'color': '#8B5CF6',
        'description': 'Leaf material — no BOM, must be purchased'
    }
}

# =============================================================================
# GAP STATUS CATEGORIES
# =============================================================================
GAP_CATEGORIES = {
    'SHORTAGE': {
        'statuses': [
            'CRITICAL_SHORTAGE',   # coverage < 25%
            'SEVERE_SHORTAGE',     # coverage < 50%
            'HIGH_SHORTAGE',       # coverage < 75%
            'MODERATE_SHORTAGE',   # coverage < 90%
            'LIGHT_SHORTAGE'       # coverage < 100%
        ],
        'color': '#DC2626',
        'label': 'Shortage',
        'icon': '🔴'
    },
    'OPTIMAL': {
        'statuses': ['BALANCED'],
        'color': '#10B981',
        'label': 'Optimal',
        'icon': '✅'
    },
    'SURPLUS': {
        'statuses': [
            'LIGHT_SURPLUS',
            'MODERATE_SURPLUS',
            'HIGH_SURPLUS',
            'SEVERE_SURPLUS'
        ],
        'color': '#3B82F6',
        'label': 'Surplus',
        'icon': '📦'
    },
    'INACTIVE': {
        'statuses': ['NO_DEMAND', 'NO_ACTIVITY'],
        'color': '#9CA3AF',
        'label': 'Inactive',
        'icon': '⭕'
    }
}

# =============================================================================
# THRESHOLDS
# =============================================================================
THRESHOLDS = {
    'shortage': {
        'critical': 0.25,
        'severe': 0.50,
        'high': 0.75,
        'moderate': 0.90,
        'light': 1.00
    },
    'surplus': {
        'light': 1.25,
        'moderate': 1.75,
        'high': 2.50,
        # Note: SEVERE_SURPLUS = coverage > high threshold (else branch in classifier)
    }
}

# =============================================================================
# STATUS CONFIGURATION
# =============================================================================
STATUS_CONFIG = {
    'CRITICAL_SHORTAGE': {'icon': '🚨', 'color': '#7F1D1D', 'priority': 1},
    'SEVERE_SHORTAGE': {'icon': '🔴', 'color': '#DC2626', 'priority': 1},
    'HIGH_SHORTAGE': {'icon': '🟠', 'color': '#EA580C', 'priority': 2},
    'MODERATE_SHORTAGE': {'icon': '🟡', 'color': '#CA8A04', 'priority': 3},
    'LIGHT_SHORTAGE': {'icon': '⚠️', 'color': '#EAB308', 'priority': 4},
    'BALANCED': {'icon': '✅', 'color': '#10B981', 'priority': 99},
    'LIGHT_SURPLUS': {'icon': '🔵', 'color': '#3B82F6', 'priority': 4},
    'MODERATE_SURPLUS': {'icon': '🟣', 'color': '#8B5CF6', 'priority': 3},
    'HIGH_SURPLUS': {'icon': '🟠', 'color': '#F97316', 'priority': 2},
    'SEVERE_SURPLUS': {'icon': '🔴', 'color': '#DC2626', 'priority': 1},
    'NO_DEMAND': {'icon': '⚪', 'color': '#9CA3AF', 'priority': 99},
    'NO_ACTIVITY': {'icon': '⚪', 'color': '#D1D5DB', 'priority': 99}
}

# =============================================================================
# SUPPLY & DEMAND SOURCES
# =============================================================================
SUPPLY_SOURCES = {
    'INVENTORY': {'label': '📦 Inventory', 'icon': '📦', 'priority': 1},
    'CAN_PENDING': {'label': '📋 CAN Pending', 'icon': '📋', 'priority': 2},
    'WAREHOUSE_TRANSFER': {'label': '🚛 Transfer', 'icon': '🚛', 'priority': 3},
    'PURCHASE_ORDER': {'label': '📝 Purchase Order', 'icon': '📝', 'priority': 4},
    'MO_EXPECTED': {'label': '🏭 MO Expected', 'icon': '🏭', 'priority': 5}
}

DEMAND_SOURCES = {
    'OC_PENDING': {'label': '✔ Confirmed Orders', 'icon': '✔', 'priority': 1},
    'FORECAST': {'label': '📊 Forecast', 'icon': '📊', 'priority': 2}
}

# =============================================================================
# PRODUCT CLASSIFICATION
# =============================================================================
PRODUCT_TYPES = {
    'MANUFACTURING': {
        'label': 'Manufacturing',
        'icon': '🏭',
        'color': '#3B82F6',
        'description': 'Products with BOM - can be produced'
    },
    'TRADING': {
        'label': 'Trading',
        'icon': '🛒',
        'color': '#10B981',
        'description': 'Products without BOM - need to purchase'
    }
}

# =============================================================================
# BOM TYPES
# =============================================================================
BOM_TYPES = {
    'CUTTING': {'label': 'Cutting', 'icon': '✂️', 'scrap_rate': 2.0},
    'REPACKING': {'label': 'Repacking', 'icon': '📦', 'scrap_rate': 0.5},
    'KITTING': {'label': 'Kitting', 'icon': '🔧', 'scrap_rate': 0.0},
    'ASSEMBLY': {'label': 'Assembly', 'icon': '🔩', 'scrap_rate': 1.0}
}

# =============================================================================
# MATERIAL TYPES
# =============================================================================
MATERIAL_TYPES = {
    'RAW_MATERIAL': {'label': 'Raw Material', 'icon': '🧪', 'priority': 1},
    'PACKAGING': {'label': 'Packaging', 'icon': '📦', 'priority': 2},
    'CONSUMABLE': {'label': 'Consumable', 'icon': '🔧', 'priority': 3}
}

# =============================================================================
# MULTI-LEVEL BOM CONFIGURATION
# =============================================================================
MAX_BOM_LEVELS = 10  # Safety limit for recursive BOM explosion

MATERIAL_CATEGORIES = {
    'RAW_MATERIAL': {
        'label': 'Raw Material',
        'icon': '🧪',
        'description': 'Leaf node — no BOM, must purchase'
    },
    'SEMI_FINISHED': {
        'label': 'Semi-Finished',
        'icon': '🔶',
        'description': 'Has its own BOM — can be produced from lower-level materials'
    }
}

# =============================================================================
# ACTION TYPES
# =============================================================================
ACTION_TYPES = {
    'CREATE_MO': {
        'label': 'Create MO',
        'icon': '🏭',
        'color': '#3B82F6',
        'category': 'Manufacturing'
    },
    'CREATE_MO_SEMI': {
        'label': 'Create MO (Semi)',
        'icon': '🔶',
        'color': '#6366F1',
        'category': 'Manufacturing'
    },
    'WAIT_RAW': {
        'label': 'Wait for Raw',
        'icon': '⏳',
        'color': '#F59E0B',
        'category': 'Manufacturing'
    },
    'CREATE_PO_FG': {
        'label': 'Create PO (FG)',
        'icon': '🛒',
        'color': '#10B981',
        'category': 'Purchase'
    },
    'CREATE_PO_RAW': {
        'label': 'Create PO (Raw)',
        'icon': '📦',
        'color': '#8B5CF6',
        'category': 'Purchase'
    },
    'USE_ALTERNATIVE': {
        'label': 'Use Alternative',
        'icon': '🔄',
        'color': '#06B6D4',
        'category': 'Alternative'
    }
}

# =============================================================================
# RAW MATERIAL STATUS
# =============================================================================
RAW_MATERIAL_STATUS = {
    'SUFFICIENT': {'label': 'Sufficient', 'icon': '✅', 'color': '#10B981'},
    'PARTIAL': {'label': 'Partial', 'icon': '⚠️', 'color': '#F59E0B'},
    'ALTERNATIVE_AVAILABLE': {'label': 'Alt Available', 'icon': '🔄', 'color': '#06B6D4'},
    'SHORTAGE': {'label': 'Shortage', 'icon': '🔴', 'color': '#DC2626'},
    'NO_SUPPLY': {'label': 'No Supply', 'icon': '❌', 'color': '#7F1D1D'}
}

# =============================================================================
# UI CONFIGURATION
# =============================================================================
UI_CONFIG = {
    'items_per_page_options': [10, 25, 50, 100],
    'default_items_per_page': 25,
    'max_chart_items': 20,
    'chart_height': 400,
    'chart_height_compact': 300
}

# =============================================================================
# FIELD TOOLTIPS
# =============================================================================
FIELD_TOOLTIPS = {
    # FG GAP Fields
    'total_supply': 'Tổng nguồn cung = ∑ available_quantity (theo từng product)',
    'total_demand': 'Tổng nhu cầu = ∑ required_quantity (theo từng product)',
    'safety_stock_qty': 'Mức tồn kho an toàn được thiết lập cho sản phẩm',
    'safety_gap': 'Total Supply - Safety Stock Qty',
    'available_supply': 'MAX(0, Total Supply - Safety Stock) - Nguồn cung khả dụng sau khi trừ safety stock',
    'net_gap': 'Available Supply - Total Demand - Chênh lệch giữa cung và cầu',
    'true_gap': 'Total Supply - Total Demand - Chênh lệch thực tế không tính safety stock',
    'coverage_ratio': '(Available Supply ÷ Total Demand) × 100% - Tỷ lệ đáp ứng nhu cầu',
    'at_risk_value': '|Net GAP| × avg_unit_price_usd - Giá trị rủi ro khi shortage (USD)',
    'customer_count': 'Số lượng khách hàng bị ảnh hưởng bởi shortage',
    
    # Raw Material Fields
    'required_qty': '(FG Shortage ÷ BOM Output Qty) × Qty Per Output × (1 + Scrap Rate%)',
    'existing_mo_demand': 'Nhu cầu từ các MO đang pending chưa xuất kho',
    'total_required_qty': 'Required Qty + Existing MO Demand',
    'bom_output_quantity': 'Số lượng output từ 1 lần sản xuất theo BOM',
    'quantity_per_output': 'Số lượng nguyên liệu cần cho 1 đơn vị output',
    'scrap_rate': 'Tỷ lệ hao hụt trong quá trình sản xuất (%)',
    
    # Classification
    'can_produce': 'Có đủ nguyên liệu để sản xuất hay không',
    'limiting_materials': 'Nguyên liệu gây ra bottleneck trong sản xuất',
    'is_primary': 'Nguyên liệu chính (không phải alternative)',
    'alternative_priority': 'Thứ tự ưu tiên của nguyên liệu thay thế',
    
    # Status
    'gap_status': 'Trạng thái GAP dựa trên coverage ratio',
    'gap_group': 'Nhóm trạng thái: SHORTAGE / OPTIMAL / SURPLUS / INACTIVE',
    
    # MO Expected
    'mo_expected': 'Sản lượng dự kiến từ MO CONFIRMED/IN_PROGRESS chưa hoàn thành (planned_qty - produced_qty)',
    'supply_mo_expected': 'Nguồn cung từ MO đang sản xuất — bật/tắt để bao gồm hoặc loại trừ'
}

# =============================================================================
# FORMULA HELP - Chi tiết công thức tính toán
# =============================================================================
FORMULA_HELP = {
    'level_1': {
        'title': '📊 Level 1: FG GAP (Finished Goods)',
        'description': 'Phân tích chênh lệch cung-cầu sản phẩm thành phẩm',
        'formulas': [
            ('total_supply', '∑ available_quantity (incl. MO Expected)', 
             'Tổng nguồn cung = Inventory + CAN + Transfer + PO + MO Expected Output'),
            ('total_demand', '∑ required_quantity', 'Tổng nhu cầu theo từng product'),
            ('safety_gap', 'total_supply - safety_stock_qty', 'Nguồn cung sau khi trừ tồn kho an toàn'),
            ('available_supply', 'MAX(0, safety_gap)', 'Nguồn cung khả dụng (không âm)'),
            ('net_gap', 'available_supply - total_demand', 'Chênh lệch cung-cầu'),
            ('coverage_ratio', 'available_supply / total_demand', 'Tỷ lệ đáp ứng (%)'),
            ('at_risk_value', '|net_gap| × avg_unit_price_usd', 'Giá trị rủi ro nếu shortage (USD)')
        ]
    },
    'level_2': {
        'title': '🧪 Level 2: Raw Material GAP',
        'description': (
            'Phân tích nguyên vật liệu cho các sản phẩm Manufacturing có shortage. '
            'Lưu ý: Khi bật MO Expected ở FG supply, FG shortage giảm đi → raw demand '
            'chỉ tính cho phần chưa có MO cover, tránh double-count.'
        ),
        'formulas': [
            ('required_qty', '(fg_shortage / bom_output_qty) × qty_per_output × (1 + scrap_rate%)', 
             'Số lượng NVL cần để bù shortage FG (chỉ phần chưa có MO)'),
            ('total_required', 'required_qty + existing_mo_demand', 
             'Tổng nhu cầu bao gồm MO đang pending'),
            ('net_gap', 'available_supply - total_required', 
             'Chênh lệch cung-cầu NVL')
        ]
    },
    'classification': {
        'title': '🏭 Product Classification',
        'description': 'Phân loại sản phẩm dựa trên BOM',
        'items': [
            ('Manufacturing', 'Sản phẩm có BOM - có thể sản xuất'),
            ('Trading', 'Sản phẩm không có BOM - cần mua trực tiếp')
        ]
    },
    'status_thresholds': {
        'title': '📈 GAP Status Thresholds',
        'description': 'Ngưỡng phân loại trạng thái dựa trên Coverage Ratio',
        'shortage': [
            ('CRITICAL_SHORTAGE', '< 25%', '🚨'),
            ('SEVERE_SHORTAGE', '< 50%', '🔴'),
            ('HIGH_SHORTAGE', '< 75%', '🟠'),
            ('MODERATE_SHORTAGE', '< 90%', '🟡'),
            ('LIGHT_SHORTAGE', '< 100%', '⚠️')
        ],
        'surplus': [
            ('BALANCED', '= 100%', '✅'),
            ('LIGHT_SURPLUS', '≤ 125%', '🔵'),
            ('MODERATE_SURPLUS', '≤ 175%', '🟣'),
            ('HIGH_SURPLUS', '> 175%', '🟠'),
            ('SEVERE_SURPLUS', '> 250%', '🔴')
        ]
    },
    'actions': {
        'title': '📋 Action Recommendations',
        'description': 'Đề xuất hành động dựa trên kết quả phân tích',
        'items': [
            ('CREATE_MO', 'Manufacturing + NVL đủ', '🏭 Tạo lệnh sản xuất'),
            ('WAIT_RAW', 'Manufacturing + NVL thiếu', '⏳ Chờ NVL'),
            ('USE_ALTERNATIVE', 'Manufacturing + có NVL thay thế', '🔄 Dùng NVL thay thế'),
            ('CREATE_PO_FG', 'Trading product thiếu', '🛒 Tạo PO mua FG'),
            ('CREATE_PO_RAW', 'NVL thiếu (không có alternative)', '📦 Tạo PO mua NVL')
        ]
    }
}

# =============================================================================
# PERIOD ANALYSIS CONFIGURATION
# =============================================================================
PERIOD_TYPES = {
    'Weekly': {'label': 'Weekly', 'icon': '📅', 'description': 'Group by ISO week'},
    'Monthly': {'label': 'Monthly', 'icon': '📆', 'description': 'Group by calendar month'}
}

PERIOD_CONFIG = {
    'default_period_type': 'Weekly',
    'default_track_backlog': True,
    'max_periods_display': 52,       # Max periods shown in table
    'chart_max_products': 15,        # Max products in timeline chart
    'shortage_highlight_threshold': 0,  # GAP < 0 = shortage
}

# =============================================================================
# EXPORT CONFIGURATION
# =============================================================================
EXPORT_CONFIG = {
    'sheets': [
        'Summary',
        'FG GAP',
        'Manufacturing',
        'Trading',
        'Raw Material GAP',
        'Actions',
        'Period GAP'
    ],
    'max_rows': 10000
}