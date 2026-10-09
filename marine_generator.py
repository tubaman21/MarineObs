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
MARINE_SUFFIXES = ("M5", "W3", "N6", "S2", "M4", "O1", "I3", "N7")

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

# Specific network IDs for river gauges/HADS/USGS/RAWS that frequently leak into general queries
RIVER_GAUGE_MNET_IDS = {"2", "128", "130", "180", "208", "236", "64", "66", "67", "153", "172", "173", "280"}

# Key terms wrapped in spaces to target water/river-only gauge metadata safely
HYDRO_NAME_KEYWORDS = (
    " RIVER ", " CREEK ", " STREAM ", " POND ", 
    " RESERVOIR ", " DAM ", " GAGE ", " DRAIN ", " FLUME ", " CANAL "
)

EXCLUDE_KEYWORDS = [
    "RIVER", "CREEK", "STREAM", "GAGE", "GAUGE", "DAM", "RESERVOIR", 
    "DRAIN", "FLUME", "CANAL", "FORK", "SLOUGH", "RAWS", "RWIS", "DOT"
]

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
    if vis_val is None or math.isnan(vis_val):
        return None
    try:
        vis = float(vis_val)
        if vis > 50.0:
            vis *= 0.000621371
            
        if vis <= 0.125: return "1/8"
        elif vis <= 0.25: return "1/4"
        elif vis <= 0.5: return "1/2"
        elif vis <= 0.75: return "3/4"
        elif vis < 10.0: return f"{vis:.1f}".rstrip('0').rstrip('.')
        else: return "10"
    except Exception:
        return None

def calculate_dewpoint_f(temp_f, rh_percent):
    if temp_f is None or rh_percent is None or rh_percent <= 0:
        return None
    try:
        rh_clamped = max(rh_percent, 0.1)
        temp_c = (temp_f - 32) * 5 / 9
        a, b = 17.625, 243.04
        alpha = ((a * temp_c) / (b + temp_c)) + math.log(rh_clamped / 100.0)
        dew_c = (b * alpha) / (a - alpha)
        return int(round((dew_c * 9 / 5) + 32))
    except Exception:
        return None

def get_wind_barb_index(speed_knots, direction_deg):
    if speed_knots is None or speed_knots < 3 or direction_deg is None:
        return 0, 0
    idx = max(1, min(26, int(round(speed_knots / 5.0)) + 1))
    return idx, int(direction_deg)

def get_sky_cover_icon(cloud_cov_str):
    return 5

def get_obs_val(observations, var_prefixes, index):
    for key, values in observations.items():
        if any(prefix in key for prefix in var_prefixes):
            val = None
            if isinstance(values, list):
                if index < len(values):
                    val = values[index]
            else:
                val = values
            if val is not None:
                try:
                    fval = float(val)
                    if not math.isnan(fval):
                        return fval
                except (ValueError, TypeError):
                    continue
    return None

def get_best_slp(observations, index, elev_meters, temp_c):
    raw_p = get_obs_val(observations, ["sea_level_pressure", "altimeter"], index)
    if raw_p is not None:
        p_mb = normalize_pressure_to_mb(raw_p)
        if p_mb and 950.0 <= p_mb <= 1050.0:
            return p_mb

    stn_p = get_obs_val(observations, ["pressure", "barometric_pressure"], index)
    if stn_p is not None:
        p_mb = normalize_pressure_to_mb(stn_p)
        if p_mb:
            if p_mb >= 950.0:
                return p_mb
            return station_pressure_to_slp(p_mb, elev_meters, temp_c)

    return None

def get_pressure_tendency_str(observations, latest_idx, timestamps, elev_meters, temp_c):
    current_p = get_best_slp(observations, latest_idx, elev_meters, temp_c)
    if current_p is None or not timestamps or latest_idx >= len(timestamps):
        return "N/A"

    try:
        latest_dt = datetime.strptime(timestamps[latest_idx], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        target_dt = latest_dt - timedelta(hours=3)
        
        best_idx = None
        best_diff = None
        for i, ts in enumerate(timestamps):
            if i == latest_idx:
                continue
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            diff = abs((dt - target_dt).total_seconds())
            if diff <= 3600:
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_idx = i

        if best_idx is not None:
            past_p = get_best_slp(observations, best_idx, elev_meters, temp_c)
            if past_p is not None:
                diff_mb = current_p - past_p
                sign = "+" if diff_mb >= 0 else ""
                return f"{sign}{diff_mb:.1f}mb/3hr"
    except Exception:
        pass

    return "N/A"

def get_max_gust_1h(observations, latest_idx, timestamps):
    if not timestamps or latest_idx >= len(timestamps):
        return "N/A"
    try:
        latest_dt = datetime.strptime(timestamps[latest_idx], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        start_dt = latest_dt - timedelta(hours=1)
        max_gust_ms = None
        max_gust_time_str = None

        for i, ts in enumerate(timestamps):
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if start_dt <= dt <= latest_dt:
                g_ms = get_obs_val(observations, ["wind_gust"], i)
                if g_ms is not None:
                    if max_gust_ms is None or g_ms > max_gust_ms:
                        max_gust_ms = g_ms
                        max_gust_time_str = dt.strftime("%H:%MZ")

        if max_gust_ms is not None:
            max_gust_kt = int(round(max_gust_ms * 1.94384))
            return f"{max_gust_kt}KT @ {max_gust_time_str}" if max_gust_time_str else f"{max_gust_kt}KT"
    except Exception:
        pass

    return "N/A"

def clean_rain_value_to_inches(val):
    if val is None or math.isnan(val) or val < 0:
        return 0.0
    try:
        val = float(val)
        if 0.254 <= val < 100.0:
            return val * 0.0393701
        elif val >= 100.0:
            return val / 100.0
        return val
    except Exception:
        return 0.0

# ==========================================
# MAIN IMPLEMENTATION LOGIC
# ==========================================
def main():
    print("Initializing dynamic telemetry download routine from Synoptic Networks (Marine Focus)...")
    
    api_token = os.environ.get("SYNOPTIC_API_TOKEN")
    if not api_token:
        print("Error: SYNOPTIC_API_TOKEN environment variable is missing!")
        sys.exit(1)
    
    run_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    api_params = {
        "token": api_token,
        "bbox": f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}",
        "mnet": ",".join(sorted(MARINE_MNET_IDS)),
        "recent": LOOKBACK_HOURS * 60,
        "obtimezone": "UTC",
        "output": "json",
        "extra": "metadata,mnet,sensor_variables"
    }
    
    # Retry loop for transient Synoptic outages / rate limits
    data = None
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(SYNOPTIC_API_URL, params=api_params, timeout=25)
            if response.status_code == 200:
                data = response.json()
                break
            else:
                print(f"Attempt {attempt}/{max_retries}: Synoptic HTTP {response.status_code}. Retrying...")
        except Exception as e:
            print(f"Attempt {attempt}/{max_retries}: Network exception ({e}). Retrying...")
        
        time.sleep(5 * attempt)

    if not data:
        print("Warning: Unable to retrieve Synoptic data after retries. Proceeding gracefully with empty Synoptic payload.")
        data = {}

    response_code = data.get("SUMMARY", {}).get("RESPONSE_CODE") or data.get("RESPONSE_CODE")
    if response_code and response_code != 1:
        error_msg = data.get("SUMMARY", {}).get("RESPONSE_MESSAGE") or data.get("RESPONSE_MESSAGE")
        print(f"Warning: Synoptic API Error Code [{response_code}]: {error_msg}")

    network_blocks = {}
    seen_stations = set()
    rain_counter = 0

    if "STATION" in data and data["STATION"]:
        for station in data["STATION"]:
            raw_stid = station.get("STID", "UNKNOWN").upper()
            
            # Normalize NDBC prefix duplication (e.g. NDBC45006 -> 45006)
            if raw_stid.startswith("NDBC") and len(raw_stid) > 4:
                mapped_stid = raw_stid[4:]
            else:
                mapped_stid = raw_stid
                
            stid = STATION_MAP.get(raw_stid, STATION_MAP.get(mapped_stid, mapped_stid))

            if raw_stid in BLACKLIST_STATIONS or stid in BLACKLIST_STATIONS:
                continue

            if stid in seen_stations or raw_stid in seen_stations or mapped_stid in seen_stations:
                continue

            mnet_id = str(station.get("MNET_ID", ""))
            mnet_short = str(station.get("MNET_SHORTNAME", "")).
