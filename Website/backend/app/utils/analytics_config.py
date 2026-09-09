"""Column labels and DB metadata for the analytics dashboard."""

from __future__ import annotations

VEHICLE_CLASSES: dict[str, str] = {
    "3WHEELER": "vc_3wheeler",
    "BUS-2-AXLE": "vc_bus_2_axle",
    "CAR/JEEP": "vc_car_jeep",
    "LCV": "vc_lcv",
    "TRACTOR": "vc_tractor",
    "TRUCK 4-6 AXLE": "vc_truck_4_6_axle",
    "TRUCK-2-AXLE": "vc_truck_2_axle",
    "TRUCK-3-AXLE": "vc_truck_3_axle",
}

LANES: dict[str, str] = {f"L{i:02d}": f"l{i:02d}" for i in range(1, 13)}

MOP_TYPES: dict[str, str] = {
    "FASTag": "mop_fastag",
    "Cash": "mop_cash",
    "UPI": "mop_upi",
    "Exempt": "mop_exempt",
}

MIN_HOUR_WINDOW = 3
MAX_HOUR_WINDOW = 24
MIN_DAY_WINDOW = 3
MAX_DAY_WINDOW = 50
DEFAULT_TOP_LANES = 5
CHART_HEIGHT = 760  # 30% taller than previous 585px layout height
TOLL_ANALYSIS_MAIN_TABLE = "toll_analysis_main"
GAP_DISTRIBUTION_TABLE = "gap_distribution_per_lane"
EXEMPT_DISTRIBUTION_TABLE = "exempt_distribution_per_lane"
