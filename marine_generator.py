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

# Geographic Bounding Box for the Great Lakes Basin (Lakes Superior to Ontario)
LAT_MIN, LAT_MAX = 41.0, 51.5
LON_MIN, LON_MAX = -93.0, -75.0

SYNOPTIC_API_URL = "https://api.synopticdata.com/v2/stations/timeseries"

# GLOS Seagull Endpoints
GLOS_DATASETS_URL = "https://seagull-api.glos.org/api/v1/obs-datasets.geojson"
GLOS_OBS_URL = "https://seagull-api.glos.org/api/v1/obs-latest"

# Standard METAR sprite sheets via jsDelivr CDN
WIND_BARB_ICON_URL = "http://grlevelx.redteamwx.com/10m_wind_barbs.png"
SKY_COVER_ICON_URL = "https://cdn.jsdelivr.net/gh/ktrue/metar-placefile@master/cloudcover_new.png"

# Set lookback window to 2 hours for stationary mesonet/buoy looping animation
LOOKBACK_HOURS = 2

# Dedicated lookback window for moving vessels (accounts for 3-hour VOS reporting intervals)
SHIP_LOOKBACK_HOURS = 4

NETWORK_THRESHOLDS = {
    "NDBC": 999,
    "GLOS": 999,
    "Ships (GLOS)": 999,
    "C-MAN": 999,
    "NOS-WLON": 999,
    "NOS/CO-OPS": 999,
    "Marine": 999
}

NETWORK_ORDER = ["NDBC", "GLOS", "Ships (GLOS)", "C-MAN", "NOS-WLON", "Marine"]

# Categorized Whitelist Mapping (NDBC Buoys + Fixed Stations)
WHITELIST_STATION_MAP = {
    # Buoys (NDBC)
    "45194": "NDBC", "45002": "NDBC", "45014": "NDBC", "45210": "NDBC",
    "45013": "NDBC", "45007": "NDBC", "45214": "NDBC", "45187": "NDBC",
    "45186": "NDBC", "45174": "NDBC", "45198": "NDBC", "45170": "NDBC",
    "45026": "NDBC", "45168": "NDBC", "45029": "NDBC", "45161": "NDBC",
    "45024": "NDBC", "45183": "NDBC", "45022": "NDBC", "45162": "NDBC",
    "45163": "NDBC", "45008": "NDBC", "45209": "NDBC", "45147": "NDBC",
    "45149": "NDBC", "45143": "NDBC", "45137": "NDBC", "45003": "NDBC",
    "45212": "NDBC", "45199": "NDBC", "45177": "NDBC", "45175": "NDBC",
    "45027": "NDBC", "45028": "NDBC", "45001": "NDBC", "45136": "NDBC",
    "45004": "NDBC", "45213": "NDBC", "45211": "NDBC", "45025": "NDBC",
    "45023": "NDBC", "45216": "NDBC", "45006": "NDBC", "45219": "NDBC",

    # NOS-WLON
    "MACM4": "NOS-WLON", "MNMM4": "NOS-WLON", "KWNW3": "NOS-WLON", "CMTI2": "NOS-WLON",
    "HLNM4": "NOS-WLON", "LDTM4": "NOS-WLON", "LPNM4": "NOS-WLON", "HRBM4": "NOS-WLON",
    "FTGM4": "NOS-WLON", "MBRM4": "NOS-WLON", "AGCM4": "NOS-WLON", "GBWW3": "NOS-WLON",
    "DULM5": "NOS-WLON", "GDMM5": "NOS-WLON", "LTRM4": "NOS-WLON", "SWPM4": "NOS-WLON",
    "PTIM4": "NOS-WLON", "MCGM4": "NOS-WLON", "WNEM4": "NOS-WLON", "RCKM4": "NOS-WLON",
    "DTLM4": "NOS-WLON",

    # GLOS (Land/Fixed Stations)
    "CYGM4": "GLOS", "NABM4": "GLOS", "PNLM4": "GLOS", "FPTM4": "GLOS",
    "NPDW3": "GLOS", "CBRW3": "GLOS", "PWAW3": "GLOS", "WHRI2": "GLOS",
    "CNII2": "GLOS", "BSBM4": "GLOS", "MEEM4": "GLOS", "GTLM4": "GLOS",
    "PRIM4": "GLOS", "SPTM4": "GLOS", "TAWM4": "GLOS", "GSLM4": "GLOS",
    "SBLM4": "GLOS", "KP58": "GLOS", "PSCM4": "GLOS", "CLSM4": "GLOS",
    "BHRI3": "GLOS", "SJOM4": "GLOS", "PNGW3": "GLOS", "SLVM5": "GLOS",
    "WFPM4": "GLOS", "GRMM4": "GLOS", "BIGM4": "GLOS", "GTRM4": "GLOS",
    "OTNM4": "GLOS", "SXHW3": "GLOS",

    # C-MAN
    "SRLM4": "C-MAN", "SGNW3": "C-MAN", "MLWW3": "C-MAN", "CHII2": "C-MAN",
    "MCYI3": "C-MAN", "SVNM4": "C-MAN", "MKGM4": "C-MAN", "TBIM4": "C-MAN",
    "APNM4": "C-MAN", "KNSW3": "C-MAN", "FSTI2": "C-MAN", "OKSI2": "C-MAN",
    "JAKI2": "C-MAN", "WSLM4": "C-MAN", "DISW3": "C-MAN", "ROAM4": "C-MAN",
    "PILM4": "C-MAN", "STDM4": "C-MAN"
}

BLACKLIST_STATIONS = set()
STATION_MAP = {}
STATION_COORDINATE_OVERRIDES = {
    "OTNM4": (46.870, -89.330)
}

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

def get_pressure_tendency_str(observations, target_idx, timestamps, elev_meters, temp_c):
    current_p = get_best_slp(observations, target_idx, elev_meters, temp_c)
    if current_p is None or not timestamps or target_idx >= len(timestamps):
        return "N/A"

    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        target_dt = datetime.strptime(timestamps[target_idx], fmt).replace(tzinfo=timezone.utc)
        three_hr_prior = target_dt - timedelta(hours=3)
        
        best_idx = None
        best_diff = None
        for i, ts in enumerate(timestamps):
            if i == target_idx:
                continue
            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            diff = abs((dt - three_hr_prior).total_seconds())
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

def get_max_gust_1h(observations, target_idx, timestamps):
    if not timestamps or target_idx >= len(timestamps):
        return "N/A"
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        target_dt = datetime.strptime(timestamps[target_idx], fmt).replace(tzinfo=timezone.utc)
        start_dt = target_dt - timedelta(hours=1)
        max_gust_ms = None
        max_gust_time_str = None

        for i, ts in enumerate(timestamps):
            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            if start_dt <= dt <= target_dt:
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

def extract_glos_param(param_obs, possible_keys):
    """Extracts a value from GLOS parameter dictionary using string or integer keys."""
    for key in possible_keys:
        val_obj = param_obs.get(key) or param_obs.get(str(key))
        if isinstance(val_obj, dict) and "value" in val_obj and val_obj["value"] is not None:
            try:
                fval = float(val_obj["value"])
                if not math.isnan(fval):
                    return fval
            except (ValueError, TypeError):
                continue
    return None

# ==========================================
# GLOS SHIP INGESTION ROUTINE
# ==========================================
def fetch_glos_ships(network_blocks, now_utc):
    """Fetches real-time ship observations from GLOS Seagull and formats them to placefile syntax."""
    print("Fetching live ship observations from GLOS Seagull platform...")
    headers = {"User-Agent": "GRLevelX-Placefile-Script/1.0"}
    
    try:
        res_geo = requests.get(GLOS_DATASETS_URL, headers=headers, timeout=20)
        res_obs = requests.get(GLOS_OBS_URL, headers=headers, timeout=20)
        
        if res_geo.status_code != 200 or res_obs.status_code != 200:
            print(f"Warning: GLOS API returned status code {res_geo.status_code}/{res_obs.status_code}. Skipping ship obs.")
            return

        geojson_data = res_geo.json()
        obs_data = res_obs.json()
    except Exception as e:
        print(f"Warning: Failed to fetch GLOS ship data ({e}). Skipping ship obs.")
        return

    features = geojson_data.get("features", [])
    ship_count = 0
    cutoff_time = now_utc - timedelta(hours=SHIP_LOOKBACK_HOURS)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    for feature in features:
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})

        # Broadened inspection across GLOS metadata fields to identify all vessel types
        ship_name = str(props.get("name", props.get("title", props.get("label", "Unknown Vessel"))))
        platform_type = str(props.get("platform_type", "")).lower()
        platform_type_name = str(props.get("platform_type_name", "")).lower()
        node_category = str(props.get("node_category", "")).lower()
        dataset_type = str(props.get("dataset_type", "")).lower()
        description = str(props.get("description", "")).lower()

        search_str = f"{ship_name} {platform_type} {platform_type_name} {node_category} {dataset_type} {description}".lower()
        is_ship = any(kw in search_str for kw in ["ship", "vessel", "vos", "freighter", "ferry", "boat", "tug", "barge", "moving"])

        if not is_ship:
            continue

        if geom.get("type") != "Point" or not geom.get("coordinates"):
            continue

        lon, lat = geom["coordinates"][0], geom["coordinates"][1]

        # Bounding box filter for the Great Lakes Basin
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue

        dataset_id = str(props.get("id", ""))
        latest = obs_data.get(dataset_id)
        if not latest or "parameter_obs" not in latest:
            continue

        # Parse observation timestamp for loop time-bounding
        raw_time = latest.get("timestamp")
        if not raw_time:
            continue

        try:
            dt_ob = datetime.fromisoformat(raw_time
