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

# NWS Duluth Ship Data Endpoint
NWS_SHIP_URL = "https://www.weather.gov/source/dlh/shipdata_world.json?r=0.1917874013826375"

# Standard METAR sprite sheets via jsDelivr CDN
WIND_BARB_ICON_URL = "http://grlevelx.redteamwx.com/10m_wind_barbs.png"
SKY_COVER_ICON_URL = "https://cdn.jsdelivr.net/gh/ktrue/metar-placefile@master/cloudcover_new.png"

# Set lookback window to 4 hours for stationary mesonet/buoy looping animation
LOOKBACK_HOURS = 4

# Dedicated lookback window for moving vessels
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
    rot = int(round(direction_deg))
    if rot == 0:
        rot = 360
    return idx, rot

def get_sky_cover_icon(cloud_cov_str):
    return 5

def get_obs_val(observations, var_prefixes, index, allow_zero=True):
    candidates = []
    for prefix in var_prefixes:
        matching_keys = [k for k in observations.keys() if prefix in k]
        matching_keys.sort(key=lambda x: (0 if "set_1" in x or x == prefix else 1, x))
        
        for key in matching_keys:
            values = observations[key]
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
                        if fval == 0.0 and not allow_zero:
                            candidates.append(0.0)
                            continue
                        return fval
                except (ValueError, TypeError):
                    continue
                    
    return candidates[0] if candidates else None

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
            return f"{max_gust_kt}KT @ {max_gust_time_str}" if max_gust_time_str else f"{max_gust_kt}"
    except Exception:
        pass

    return "N/A"

# ==========================================
# NWS SHIP INGESTION ROUTINE
# ==========================================
def fetch_glos_ships(network_blocks, now_utc):
    print("Fetching live ship observations from NWS Duluth platform...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        res = requests.get(NWS_SHIP_URL, headers=headers, timeout=20)
        print(f"NWS Ship API response status: {res.status_code}")

        if res.status_code != 200:
            print(f"Warning: NWS Ship API returned status code {res.status_code}. Skipping ship obs.")
            return

        ship_data = res.json()
    except Exception as e:
        print(f"Warning: Failed to fetch NWS ship data ({e}). Skipping ship obs.")
        return

    vessels = ship_data if isinstance(ship_data, list) else ship_data.get("ships", ship_data.get("features", []))
    print(f"Retrieved {len(vessels)} total ship dataset records.")

    ship_count = 0
    skipped_old = 0
    skipped_bbox = 0
    cutoff_time = now_utc - timedelta(hours=SHIP_LOOKBACK_HOURS)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    ship_obs_list = []

    for vessel in vessels:
        if not isinstance(vessel, dict):
            continue

        props = vessel.get("properties", vessel)
        geom = vessel.get("geometry", {})

        ship_name = str(props.get("name") or props.get("ship_name") or props.get("id") or props.get("callsign") or "Unknown Vessel")

        obs_entries = []
        for pkey, pval in props.items():
            if isinstance(pval, dict) and ("T" in pkey or "-" in pkey):
                obs_entries.append((pkey, pval))

        if not obs_entries:
            obs_entries = [("flat", props)]

        for raw_time, obs in obs_entries:
            if not isinstance(obs, dict):
                continue

            lat, lon = None, None
            if "lat" in obs and "lon" in obs:
                try:
                    lat = float(obs["lat"])
                    lon = float(obs["lon"])
                except (TypeError, ValueError):
                    pass
            elif geom and isinstance(geom, dict) and geom.get("coordinates"):
                lon, lat = geom["coordinates"][0], geom["coordinates"][1]

            if lat is None or lon is None:
                continue

            if lon > 0 and 70.0 <= lon <= 100.0:
                lon = -lon

            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                skipped_bbox += 1
                continue

            dt_ob = None
            try:
                time_str = str(raw_time if raw_time != "flat" else obs.get("time", "")).strip()
                if time_str:
                    time_str_iso = time_str.replace("Z", "+00:00")
                    dt_ob = datetime.fromisoformat(time_str_iso)
                    if dt_ob.tzinfo is None:
                        dt_ob = dt_ob.replace(tzinfo=timezone.utc)

                if dt_ob is None or dt_ob < cutoff_time:
                    skipped_old += 1
                    continue
            except Exception:
                skipped_old += 1
                continue

            ship_obs_list.append((dt_ob, ship_name, lat, lon, obs))

    ship_obs_list.sort(key=lambda item: item[0])

    for i, (dt_ob, ship_name, lat, lon, obs) in enumerate(ship_obs_list):
        start_range = (dt_ob - timedelta(minutes=5)).strftime(fmt)
        
        end_range = (dt_ob + timedelta(hours=1.5)).strftime(fmt)
        for next_dt, next_name, _, _, _ in ship_obs_list[i + 1:]:
            if next_name == ship_name and next_dt > dt_ob:
                end_range = next_dt.strftime(fmt)
                break

        ob_time_str = dt_ob.strftime("%Y-%m-%d %H:%M UTC")

        temp_raw = obs.get("V-T") or obs.get("temp") or obs.get("air_temp")
        dew_raw = obs.get("V-TD") or obs.get("dewp") or obs.get("dew_point")
        speed_raw = obs.get("V-FF") or obs.get("wspd") or obs.get("wind_speed")
        gust_raw = obs.get("gust") or obs.get("wind_gust")
        wind_dir_raw = obs.get("V-DD") or obs.get("wdir") or obs.get("wind_dir")
        slp_raw = obs.get("V-SLP") or obs.get("slp") or obs.get("pressure")

        temp_f = None
        if temp_raw is not None:
            try:
                t_val = float(temp_raw)
                temp_f = int(round((t_val - 273.15) * 9 / 5 + 32)) if t_val > 200.0 else int(round(t_val))
            except (ValueError, TypeError):
                pass

        dew_f = None
        if dew_raw is not None:
            try:
                d_val = float(dew_raw)
                dew_f = int(round((d_val - 273.15) * 9 / 5 + 32)) if d_val > 200.0 else int(round(d_val))
            except (ValueError, TypeError):
                pass

        speed_kt = 0
        if speed_raw is not None:
            try:
                sp_val = float(speed_raw)
                speed_kt = int(round(sp_val * 1.94384)) if (sp_val < 100.0 and obs.get("V-FF") is not None) else int(round(sp_val))
            except (ValueError, TypeError):
                pass

        gust_kt = None
        if gust_raw is not None:
            try:
                gust_kt = int(round(float(gust_raw)))
            except (ValueError, TypeError):
                pass

        wind_dir = None
        if wind_dir_raw is not None:
            try:
                wind_dir = round(float(wind_dir_raw))
            except (ValueError, TypeError):
                pass

        slp_mb = normalize_pressure_to_mb(slp_raw)
        slp_str = sanitize_slp(slp_mb)

        tf_display = f"{temp_f}" if temp_f is not None else "M"
        df_display = f"{dew_f}" if dew_f is not None else "M"
        wind_dir_display = int(wind_dir) if wind_dir is not None else 0

        has_gust = (
            gust_kt is not None
            and gust_kt >= 10
            and gust_kt > (speed_kt + 3)
        )
        wind_display = f"{wind_dir_display:03d}@{speed_kt}G{gust_kt}KT" if has_gust else f"{wind_dir_display:03d}@{speed_kt}KT"

        hover_text = (
            f"Obs Time: {ob_time_str} | Ship: {ship_name} | Type: VOS/Freighter | "
            f"Temp: {tf_display}F | Dewpt: {df_display}F | Wind: {wind_display} | "
            f"SLP: {f'{slp_mb:.1f}' if slp_mb else 'M'}mb"
        )

        color_temp = "255 100 100"
        color_dew  = "100 255 100"
        color_slp  = "255 255 255"
        color_gust = "255 255 0"

        max_wind_kt = gust_kt if gust_kt is not None else speed_kt
        if max_wind_kt >= 39:
            color_temp = "255 50 255"
        elif max_wind_kt >= 30:
            color_temp = "255 200 0"

        station_lines = []
        station_lines.append(f"TimeRange: {start_range} {end_range}")
        station_lines.append(f"Object: {lat:.5f},{lon:.5f}")

        barb_speed = max(speed_kt, gust_kt if gust_kt is not None else 0)
        if barb_speed >= 3 and wind_dir is not None:
            barb_val, rot_angle = get_wind_barb_index(barb_speed, wind_dir)
            if barb_val > 0:
                station_lines.append("  Color: 255 255 255")
                station_lines.append(f'  Icon: 0,0,{rot_angle},1,{barb_val},1.25, ""')

        station_lines.append("  Color: 255 255 255")
        station_lines.append(f'  Icon: 0,0,0,2,5, "{hover_text}"')

        if tf_display != "M":
            station_lines.append(f"  Color: {color_temp}")
            station_lines.append(f'  Text: -16, 12, 1, "{tf_display}"')

        station_lines.append("  Color: 255 200 0")
        station_lines.append(f'  Text: 0, 22, 1, "{ship_name}"')

        if slp_str != "M":
            station_lines.append(f"  Color: {color_slp}")
            station_lines.append(f'  Text: 16, 12, 1, "{slp_str}"')

        if df_display != "M":
            station_lines.append(f"  Color: {color_dew}")
            station_lines.append(f'  Text: -16, -12, 1, "{df_display}"')

        if has_gust:
            station_lines.append(f"  Color: {color_gust}")
            station_lines.append(f'  Text: 0, -20, 1, "G{gust_kt}"')

        station_lines.append("End:")
        station_lines.append("")

        network_blocks.setdefault("Ships (GLOS)", []).extend(station_lines)
        ship_count += 1

    print(f"NWS Ship inspection breakdown: {skipped_bbox} out of bbox, {skipped_old} older than cutoff.")
    print(f"Successfully processed {ship_count} active ship observations from NWS Duluth within the {SHIP_LOOKBACK_HOURS}-hour window.")

# ==========================================
# MAIN IMPLEMENTATION LOGIC
# ==========================================
def main():
    print("Initializing dynamic telemetry download routine from Synoptic Networks (Marine Focus)...")
    
    api_token = os.environ.get("SYNOPTIC_API_TOKEN")
    if not api_token:
        print("Error: SYNOPTIC_API_TOKEN environment variable is missing!")
        sys.exit(1)
    
    now_utc = datetime.now(timezone.utc)
    run_time = now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
    cutoff_time = now_utc - timedelta(hours=LOOKBACK_HOURS)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    
    api_params = {
        "token": api_token,
        "bbox": f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}",
        "recent": LOOKBACK_HOURS * 60,
        "obtimezone": "UTC",
        "output": "json",
        "extra": "metadata,mnet,sensor_variables"
    }
    
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

    if "STATION" in data and data["STATION"]:
        for station in data["STATION"]:
            raw_stid = station.get("STID", "UNKNOWN").upper()
            
            if raw_stid.startswith("NDBC") and len(raw_stid) > 4:
                mapped_stid = raw_stid[4:]
            else:
                mapped_stid = raw_stid
                
            stid = STATION_MAP.get(raw_stid, STATION_MAP.get(mapped_stid, mapped_stid))

            if raw_stid in BLACKLIST_STATIONS or stid in BLACKLIST_STATIONS:
                continue

            if stid in seen_stations or raw_stid in seen_stations or mapped_stid in seen_stations:
                continue

            mnet = None
            if raw_stid in WHITELIST_STATION_MAP:
                mnet = WHITELIST_STATION_MAP[raw_stid]
            elif stid in WHITELIST_STATION_MAP:
                mnet = WHITELIST_STATION_MAP[stid]
            elif mapped_stid in WHITELIST_STATION_MAP:
                mnet = WHITELIST_STATION_MAP[mapped_stid]

            if not mnet:
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

            valid_obs = []
            for idx, ts_str in enumerate(timestamps):
                try:
                    dt_ob = datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
                    if dt_ob >= cutoff_time:
                        valid_obs.append((dt_ob, idx))
                except Exception:
                    continue

            valid_obs.sort(key=lambda item: item[0])

            for i, (dt_ob, idx) in enumerate(valid_obs):
                start_range = (dt_ob - timedelta(minutes=5)).strftime(fmt)
                
                if i < len(valid_obs) - 1:
                    next_dt, _ = valid_obs[i + 1]
                    end_range = next_dt.strftime(fmt)
                else:
                    end_range = (now_utc + timedelta(hours=3)).strftime(fmt)

                ob_time_str = dt_ob.strftime("%Y-%m-%d %H:%M UTC")

                temp_c = get_obs_val(observations, ["air_temp"], idx)
                dew_c = get_obs_val(observations, ["dew_point"], idx)
                rh_pct = get_obs_val(observations, ["relative_humidity"], idx)
                
                gust_ms = get_obs_val(observations, ["wind_gust"], idx)
                gust_kt = int(round(gust_ms * 1.94384)) if gust_ms is not None else None

                allow_zero_speed = True if (gust_kt is None or gust_kt < 10) else False
                speed_ms = get_obs_val(observations, ["wind_speed", "wind_u", "wind_v"], idx, allow_zero=allow_zero_speed)
                
                wind_dir = get_obs_val(observations, ["wind_direction", "wind_dir", "wdir", "V-DD"], idx)
                raw_vis = get_obs_val(observations, ["visibility", "vis"], idx)

                temp_f = int(round((temp_c * 9/5) + 32)) if temp_c is not None else None
                dew_f = int(round((dew_c * 9/5) + 32)) if dew_c is not None else None

                if dew_f is None and temp_f is not None and rh_pct is not None:
                    dew_f = calculate_dewpoint_f(temp_f, rh_pct)

                speed_kt = int(round(speed_ms * 1.94384)) if speed_ms is not None else 0

                slp_mb = get_best_slp(observations, idx, elev_meters, temp_c)
                p_tend_str = get_pressure_tendency_str(observations, idx, timestamps, elev_meters, temp_c)
                max_gust_1h_str = get_max_gust_1h(observations, idx, timestamps)
                vis_str = format_visibility_str(raw_vis)

                sky_code = get_obs_val(observations, ["cloud_layer_1_code"], idx)

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

                vis_hover = f"{vis_str}SM" if vis_str else "N/A"

                hover_text = (
                    f"Obs Time: {ob_time_str} | Station: {stid} | Type: {mnet} | "
                    f"Temp: {tf_display}F | Dewpt: {df_display}F | RH: {rh_display} | Wind: {wind_display} | "
                    f"Peak Gust 1hr: {max_gust_1h_str} | Vis: {vis_hover} | SLP: {f'{slp_mb:.1f}' if slp_mb else 'M'}mb | "
                    f"Pres Tend: {p_tend_str}"
                )

                station_lines = []
                station_lines.append(f"TimeRange: {start_range} {end_range}")
                station_lines.append(f"Object: {lat:.5f},{lon:.5f}")

                barb_speed = max(speed_kt, gust_kt if gust_kt is not None else 0)
                if barb_speed >= 3 and wind_dir is not None:
                    barb_val, rot_angle = get_wind_barb_index(barb_speed, wind_dir)
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

                if has_gust:
                    station_lines.append(f"  Color: {color_gust}")
                    station_lines.append(f'  Text: 0, -20, 1, "G{gust_kt}"')

                station_lines.append("End:")
                station_lines.append("")

                if station_lines:
                    network_blocks.setdefault(mnet, []).extend(station_lines)

    fetch_glos_ships(network_blocks, now_utc)

    header_lines = [
        "; Created by: Bryan J. Howell and Gemini",
        "; Last Updated: 10/13/26",
        f'Title: Marine Observations ({run_time})',
        "Refresh: 5",
        f'IconFile: 1, 30, 30, 15, 29, "{WIND_BARB_ICON_URL}"',
        f'IconFile: 2, 15, 15, 8, 8, "{SKY_COVER_ICON_URL}"',
        "Font: 1, 11, 400, 0",
        ""
    ]

    body_lines = []
    processed_nets = set()
    for net in NETWORK_ORDER:
        if net in network_blocks:
            threshold = NETWORK_THRESHOLDS.get(net, 999)
            body_lines.append(f"; --- Network: {net} (Threshold: {threshold} NM) ---")
            body_lines.append(f"Threshold: {threshold}\n")
            body_lines.extend(network_blocks[net])
            processed_nets.add(net)

    for net, lines in network_blocks.items():
        if net not in processed_nets:
            threshold = NETWORK_THRESHOLDS.get(net, 999)
            body_lines.append(f"; --- Network: {net} (Threshold: {threshold} NM) ---")
            body_lines.append(f"Threshold: {threshold}\n")
            body_lines.extend(lines)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    full_output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    temp_output_path = full_output_path + ".tmp"
    
    with open(temp_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header_lines + body_lines))
        f.flush()
        os.fsync(f.fileno())
        
    os.replace(temp_output_path, full_output_path)
        
    print(f"Success! Processed looping dataset.")
    print(f"Destination file compiled: {full_output_path}")

# ==========================================
# DIAGNOSTIC ENTRY POINT
# ==========================================
if __name__ == "__main__":
    api_token = os.environ.get("SYNOPTIC_API_TOKEN")
    if not api_token:
        print("Error: SYNOPTIC_API_TOKEN environment variable is missing!")
        sys.exit(1)

    print("Executing station diagnostic for STDM4 and 45213...")
    params = {
        "token": api_token,
        "stid": "STDM4,45213,NDBC45213",
        "recent": 60,
        "obtimezone": "UTC",
        "output": "json",
        "extra": "sensor_variables"
    }

    try:
        res = requests.get(SYNOPTIC_API_URL, params=params, timeout=20).json()
    except Exception as e:
        print(f"API diagnostic call failed: {e}")
        sys.exit(1)

    stations = res.get("STATION", [])
    if not stations:
        print("No stations returned by Synoptic! Check token or station IDs.")
    else:
        for station in stations:
            stid = station.get("STID")
            mnet = station.get("MNET_ID")
            print(f"\n=================== STATION: {stid} (MNET: {mnet}) ===================")
            obs = station.get("OBSERVATIONS", {})
            for key, vals in obs.items():
                if any(w in key.lower() for w in ["wind", "dir", "spd", "gust", "ff", "dd", "date"]):
                    recent_vals = vals[-3:] if isinstance(vals, list) else vals
                    print(f"  {key:40s} -> {recent_vals}")

    print("\n---------------------------------------------------------")
    print("Diagnostic complete. Now running normal placefile compile...")
    print("---------------------------------------------------------\n")
    
    # Run normal compiler routine
    main()
