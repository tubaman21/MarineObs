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
            mnet_short = str(station.get("MNET_SHORTNAME", "")).upper()
            mnet_name = str(station.get("MNET_NAME", "")).upper()
            sensor_keys = set(station.get("SENSOR_VARIABLES", {}).keys())

            # Explicitly exclude Iowa I4 suffix sites
            if raw_stid.endswith("I4") or stid.endswith("I4") or mapped_stid.endswith("I4"):
                if raw_stid not in WHITELIST_STATIONS and stid not in WHITELIST_STATIONS:
                    continue

            # Explicitly exclude RAWS stations
            if raw_stid not in WHITELIST_STATIONS and stid not in WHITELIST_STATIONS:
                if mnet_id == "2" or "RAWS" in mnet_short or "RAWS" in mnet_name:
                    continue

            # Explicitly exclude river/stream/hydrology gages first
            if raw_stid not in WHITELIST_STATIONS and stid not in WHITELIST_STATIONS:
                if mnet_id in HYDRO_MNET_IDS or mnet_short in ["HADS", "USGS", "USACE", "NWS-HYDRO"]:
                    continue

                padded_name = f" {mnet_name} "
                if any(kw in padded_name for kw in HYDRO_NAME_KEYWORDS):
                    continue

            # Standard METAR / Airport / ASOS / AWOS filtering (exclude 4-letter ICAO ICAOs starting with K or C)
            if raw_stid not in WHITELIST_STATIONS and stid not in WHITELIST_STATIONS:
                if len(stid) == 4 and stid.isalpha() and stid[0] in ['K', 'C']:
                    continue

            # Explicitly exclude pure land networks
            LAND_NETWORKS_EXCLUDE = [
                "MNDOT", "MN_DOT", "WISDOT", "WI_DOT", "WIS_DOT", "RWIS",
                "WISCONET", "RAWS", "WEATHERXM", "UNION PACIFIC", "UPRR", "XCEL", "CWOP",
                "IADOT", "IA_DOT", "IOWA"
            ]
            if raw_stid not in WHITELIST_STATIONS and stid not in WHITELIST_STATIONS:
                if (
                    mnet_id in ["64", "66", "67", "153", "172", "173", "280"]
                    or any(net in mnet_short for net in LAND_NETWORKS_EXCLUDE)
                    or any(net in mnet_name for net in LAND_NETWORKS_EXCLUDE)
                    or stid.startswith(("DW", "CW", "EW", "FW", "GW", "WCN", "WISC", "WIDOT", "RWIS", "MN", "XL", "UP", "IA"))
                ):
                    continue

            # Marine classification logic
            is_marine = False
            
            is_hydro_gauge = (
                mnet_id in HYDRO_MNET_IDS
                or mnet_short in ["HADS", "USGS", "USACE", "NWS-HYDRO"]
                or any(kw in f" {mnet_name} " for kw in HYDRO_NAME_KEYWORDS)
            )

            if (
                mnet_id == "132"
                or "NOS" in mnet_short or "CO-OPS" in mnet_short or "COOPS" in mnet_short or "WLON" in mnet_short
                or "NOS" in mnet_name or "CO-OPS" in mnet_name or "WLON" in mnet_name
            ):
                mnet = "NOS/CO-OPS"
                is_marine = True
            elif (
                (mnet_id == "235"
                or "C-MAN" in mnet_short or "CMAN" in mnet_short or "C-MAN" in mnet_name
                or stid.endswith(MARINE_SUFFIXES)
                or raw_stid.endswith(MARINE_SUFFIXES))
                and not is_hydro_gauge
            ):
                mnet = "C-MAN"
                is_marine = True
            elif (
                mnet_id in ["117", "234"]
                or "NDBC" in mnet_short or "NDBC" in mnet_name
                or raw_stid.startswith("NDBC") or stid.startswith("NDBC")
                or (len(stid) in [5, 7] and stid.isdigit())
            ):
                mnet = "NDBC"
                is_marine = True
            elif (
                mnet_id in ["229", "274"]
                or "GLOS" in mnet_short or "GLOS" in mnet_name
                or "GREAT LAKES" in mnet_name
                or stid.startswith("GLOS")
            ):
                mnet = "GLOS"
                is_marine = True
            elif (
                mnet_id in MARINE_MNET_IDS
                or any(kw in mnet_name for kw in [
                    "MARINE", "BUOY", "COAST", "MARITIME", "HARBOR", "PIER", 
                    "LIGHT", "LAKE", "BAY", "ISLAND", "POINT", "PORT", "LOCK", "BREAKWATER"
                ])
                or any(kw in mnet_short for kw in ["MAR", "BUOY", "COAST", "LAKE", "BAY"])
                or any(v in sensor_keys for v in ["sea_surface_temp", "wave_height", "water_level", "sea_surface_temperature"])
                or raw_stid in WHITELIST_STATIONS
                or stid in WHITELIST_STATIONS
            ):
                mnet = "Marine"
                is_marine = True

            if not is_marine:
                continue

            seen_stations.add(stid)
            seen_stations.add(raw_stid)
            seen_stations.add(mapped_stid)

            try:
                lat = float(station.get("LATITUDE"))
                lon = float(station.get("LONGITUDE"))
            except (TypeError, ValueError):
                continue

            elev_meters = None
            raw_elev = station.get("ELEVATION")
            if raw_elev is not None:
                try:
                    elev_meters = float(raw_elev) * 0.3048
                except (ValueError, TypeError):
                    pass

            if stid in STATION_COORDINATE_OVERRIDES:
                lat, lon = STATION_COORDINATE_OVERRIDES[stid]
            elif raw_stid in STATION_COORDINATE_OVERRIDES:
                lat, lon = STATION_COORDINATE_OVERRIDES[raw_stid]
                
            observations = station.get("OBSERVATIONS", {})
            timestamps = observations.get("date_time", [])

            if not timestamps:
                continue

            latest_idx = len(timestamps) - 1
            ts_str = timestamps[latest_idx]

            try:
                dt_ob = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                start_range = (dt_ob - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
                end_range = (dt_ob + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
                ob_time_str = dt_ob.strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                continue

            temp_c = get_obs_val(observations, ["air_temp"], latest_idx)
            dew_c = get_obs_val(observations, ["dew_point"], latest_idx)
            rh_pct = get_obs_val(observations, ["relative_humidity"], latest_idx)
            speed_ms = get_obs_val(observations, ["wind_speed"], latest_idx)
            gust_ms = get_obs_val(observations, ["wind_gust"], latest_idx)
            wind_dir = get_obs_val(observations, ["wind_direction"], latest_idx)
            raw_vis = get_obs_val(observations, ["visibility", "vis"], latest_idx)

            temp_f = int(round((temp_c * 9/5) + 32)) if temp_c is not None else None
            dew_f = int(round((dew_c * 9/5) + 32)) if dew_c is not None else None

            if dew_f is None and temp_f is not None and rh_pct is not None:
                dew_f = calculate_dewpoint_f(temp_f, rh_pct)

            speed_kt = int(round(speed_ms * 1.94384)) if speed_ms is not None else 0
            gust_kt = int(round(gust_ms * 1.94384)) if gust_ms is not None else None

            slp_mb = get_best_slp(observations, latest_idx, elev_meters, temp_c)
            p_tend_str = get_pressure_tendency_str(observations, latest_idx, timestamps, elev_meters, temp_c)
            max_gust_1h_str = get_max_gust_1h(observations, latest_idx, timestamps)
            vis_str = format_visibility_str(raw_vis)

            raw_p1h = get_obs_val(observations, ["precip_accum_one_hour"], latest_idx)
            raw_p24h = get_obs_val(observations, ["precip_accum_24_hour"], latest_idx)

            p1h_in = clean_rain_value_to_inches(raw_p1h) if raw_p1h is not None else 0.0
            p24h_in = clean_rain_value_to_inches(raw_p24h) if raw_p24h is not None else 0.0

            p1h_str = format_precip_str(p1h_in)
            p24h_str = format_precip_str(p24h_in)

            if p1h_str:
                rain_counter += 1

            sky_code = get_obs_val(observations, ["cloud_layer_1_code"], latest_idx)

            # Quality Control Bounds
            if temp_f is not None and (temp_f < -50 or temp_f > 130): temp_f = None
            if dew_f is not None and (dew_f < -60 or dew_f > 100): dew_f = None
            if temp_f is not None and dew_f is not None and dew_f > temp_f: dew_f = None

            slp_str = sanitize_slp(slp_mb)
            sky_icon_idx = get_sky_cover_icon(sky_code)

            tf_display = f"{temp_f}" if temp_f is not None else "M"
            df_display = f"{dew_f}" if dew_f is not None else "M"
            rh_display = f"{int(round(rh_pct))}%" if rh_pct is not None and not math.isnan(rh_pct) else "M"
            wind_dir_display = int(wind_dir) if wind_dir is not None else 0

            color_temp = "255 100 100"
            color_dew  = "100 255 100"
            color_slp  = "255 255 255"
            color_rain = "0 255 255"
            color_gust = "255 255 0"

            max_wind_kt = gust_kt if gust_kt is not None else speed_kt

            if max_wind_kt >= 39:
                color_temp = "255 50 255"
            elif max_wind_kt >= 30:
                color_temp = "255 200 0"

            has_gust = (
                gust_kt is not None 
                and gust_kt >= 10 
                and gust_kt > (speed_kt + 3)
            )

            wind_display = f"{wind_dir_display:03d}@{speed_kt}G{gust_kt}KT" if has_gust else f"{wind_dir_display:03d}@{speed_kt}KT"

            p1h_hover = f"{p1h_str}\"" if p1h_str else "0.00\""
            p24h_hover = f"{p24h_str}\"" if p24h_str else "0.00\""
            vis_hover = f"{vis_str}SM" if vis_str else "N/A"

            hover_text = (
                f"Obs Time: {ob_time_str} | Station: {stid} | Type: {mnet} | "
                f"Temp: {tf_display}F | Dewpt: {df_display}F | RH: {rh_display} | Wind: {wind_display} | "
                f"Peak Gust 1hr: {max_gust_1h_str} | Vis: {vis_hover} | SLP: {f'{slp_mb:.1f}' if slp_mb else 'M'}mb | "
                f"Pres Tend: {p_tend_str} | Rain 1hr: {p1h_hover} | Rain 24hr: {p24h_hover}"
            )

            station_lines = []
            station_lines.append(f"TimeRange: {start_range} {end_range}")
            station_lines.append(f"Object: {lat:.5f},{lon:.5f}")

            if speed_kt >= 3 and wind_dir is not None:
                barb_val, rot_angle = get_wind_barb_index(speed_kt, wind_dir)
                if barb_val > 0:
                    station_lines.append("  Color: 255 255 255")
                    station_lines.append(f'  Icon: 0,0,{rot_angle},1,{barb_val},1.25, ""')

            station_lines.append("  Color: 255 255 255")
            station_lines.append(f'  Icon: 0,0,0,2,{sky_icon_idx}, "{hover_text}"')

            if tf_display != "M":
                station_lines.append(f"  Color: {color_temp}")
                station_lines.append(f'  Text: -16, 12, 1, "{tf_display}"')

            if raw_vis is not None and vis_str:
                try:
                    v_num = float(raw_vis)
                    if v_num > 50.0: v_num *= 0.000621371
                    color_vis = "255 0 255" if v_num <= 1.0 else ("255 255 0" if v_num <= 3.0 else "180 180 180")

                    station_lines.append(f"  Color: {color_vis}")
                    station_lines.append(f'  Text: -32, 0, 1, "{vis_str}"')
                except Exception:
                    pass

            if slp_str != "M":
                station_lines.append(f"  Color: {color_slp}")
                station_lines.append(f'  Text: 16, 12, 1, "{slp_str}"')

            if df_display != "M":
                station_lines.append(f"  Color: {color_dew}")
                station_lines.append(f'  Text: -16, -12, 1, "{df_display}"')

            if p1h_str:
                station_lines.append(f"  Color: {color_rain}")
                station_lines.append(f'  Text: 16, -12, 1, "{p1h_str}"')

            if has_gust:
                station_lines.append(f"  Color: {color_gust}")
                station_lines.append(f'  Text: 0, -20, 1, "G{gust_kt}"')

            station_lines.append("End:")
            station_lines.append("")

            if station_lines:
                network_blocks.setdefault(mnet, []).extend(station_lines)

    header_lines = [
        "; Created by: Bryan J. Howell and Gemini",
        "; Last Updated: 10/09/26",
        f'Title: Marine Surface Observations ({run_time})',
        "Refresh: 5",
        f'IconFile: 1, 30, 30, 15, 29, "{WIND_BARB_ICON_URL}"',
        f'IconFile: 2, 15, 15, 8, 8, "{SKY_COVER_ICON_URL}"',
        "Font: 1, 11, 400, 0",
        ""
    ]

    body_lines = []
