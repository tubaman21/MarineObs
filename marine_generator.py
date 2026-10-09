import os
import sys
import json
import math
import time
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("Error: The 'requests' library is required to run this script.")
    print("Please install it using: pip install requests")
    sys.exit(1)

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
OUTPUT_DIR = "placefiles"
OUTPUT_FILE = "marine_observations.txt"

LAT_MIN, LAT_MAX = 41.0, 51.5
LON_MIN, LON_MAX = -98.0, -82.0

SYNOPTIC_API_URL = "https://api.synopticdata.com/v2/stations/timeseries"

# Standard METAR sprite sheets via jsDelivr CDN
WIND_BARB_ICON_URL = "http://grlevelx.redteamwx.com/10m_wind_barbs.png"
SKY_COVER_ICON_URL = "https://cdn.jsdelivr.net/gh/ktrue/metar-placefile@master/cloudcover_new.png"

LOOKBACK_HOURS = 6

NETWORK_THRESHOLDS = {
    "NDBC": 999,
    "GLOS": 999,
    "C-MAN": 999,
    "NOS/CO-OPS": 999,
    "Marine": 999
}

NETWORK_ORDER = ["NDBC", "GLOS", "C-MAN", "NOS/CO-OPS", "Marine"]

# Suffixes typically assigned to C-MAN, Coastal, and Marine sites
MARINE_SUFFIXES = ("M5", "W3", "I4", "N6", "S2", "M4", "O1", "I3", "N7")

# Network IDs explicitly designated for Marine / Coastal / Buoy telemetry by Synoptic
MARINE_MNET_IDS = {
    "117",  # NDBC
    "132",  # NOS / CO-OPS
    "229",  # Great Lakes Observing System (GLOS)
    "230",  # Maritime
    "231",  # Marine
    "232",  # Coastal
    "233",  # Offshore
    "234",  # Buoy
    "235",  # C-MAN
    "256",  # MARACOOS / IOOS Marine Networks
    "274",  # GLOS Regional
    "282",  # Marine Mesonet
    "283",  # Coastal Marine
    "284"   # Great Lakes Coastal
}

# Network IDs explicitly designated for hydrology/water level telemetry by Synoptic (Inland River/Creek Gages)
HYDRO_MNET_IDS = {
    "128",  # USGS River Gages
    "130",  # NWS Hydro / HADS
    "180",  # US Army Corps of Engineers (USACE)
    "208",  # USBR Hydro
    "236",  # CoCoRaHS
}

# Key terms wrapped in spaces to target water/river-only gauge metadata safely
HYDRO_NAME_KEYWORDS = (
    " RIVER ", " CREEK ", " STREAM ", " POND ", 
    " RESERVOIR ", " DAM ", " GAGE ", " DRAIN ", " FLUME ", " CANAL "
)

# Explicitly Whitelisted marine stations
WHITELIST_STATIONS = {
    "SEAM5", "HWDW3", "MRZW3", "SILW3", "WSHW3", "GDNW3", "SMRW3", 
    "PLPW3", "DMLW3", "LDYW3", "LNDW3", "AFWW3"
}

# Explicitly hidden/blacklisted station IDs
BLACKLIST_STATIONS = set()

STATION_MAP = {}

STATION_COORDINATE_OVERRIDES = {}

# ==========================================
# UTILITY HELPER FUNCTIONS
# ==========================================
def normalize_pressure_to_mb(val):
    if val is None or math.isnan(val) or val <= 0:
        return None
    try:
        val = float(val)
        if val > 50000:                   # Pascals (Pa)
            val /= 100.0
        elif 2800.0 <= val <= 3200.0:     # Hundredths of inHg
            val = (val / 100.0) * 33.8639
        elif 27.0 <= val <= 32.5:         # Standard inHg
            val *= 33.8639
        elif 8000.0 <= val <= 11000.0:    # Hundredths of hPa
            val /= 10.0
        
        return val if 920.0 <= val <= 1050.0 else None
    except Exception:
        return None

def station_pressure_to_slp(station_press_mb, elev_meters, temp_c=15.0):
    if station_press_mb is None or elev_meters is None or elev_meters < 0:
        return None
    try:
        temp_k = (temp_c if temp_c is not None else 15.0) + 273.15
        factor = math.exp((0.034163 * elev_meters) / temp_k)
        slp = station_press_mb * factor
        return slp if 920.0 <= slp <= 1050.0 else None
    except Exception:
        return None

def sanitize_slp(pressure_mb):
    if pressure_mb is None or math.isnan(pressure_mb) or not (950.0 <= pressure_mb <= 1050.0):
        return "M"
    try:
        val = int(round(pressure_mb * 10))
        return str(val)[-3:]
    except Exception:
        return "M"

def format_precip_str(precip_in):
    if precip_in is None or math.isnan(precip_in) or precip_in < 0.01:
        return None
    return f"{precip_in:.2f}".lstrip('0') if precip_in < 1.0 else f"{precip_in:.2f}"

def format_visibility_str(vis_val):
    if vis_val is None or math.isnan(vis_val)
