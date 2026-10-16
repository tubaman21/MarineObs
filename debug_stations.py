import os
import sys
import json
import requests

SYNOPTIC_API_URL = "https://api.synopticdata.com/v2/stations/timeseries"

def run_debug():
    api_token = os.environ.get("SYNOPTIC_API_TOKEN")
    if not api_token:
        print("Error: SYNOPTIC_API_TOKEN environment variable is missing!")
        sys.exit(1)

    params = {
        "token": api_token,
        "stid": "STDM4,45213,NDBC45213",
        "recent": 60,
        "obtimezone": "UTC",
        "output": "json",
        "extra": "sensor_variables"
    }

    print("Fetching raw Synoptic API JSON keys for STDM4 and 45213...")
    try:
        res = requests.get(SYNOPTIC_API_URL, params=params, timeout=20).json()
    except Exception as e:
        print(f"Request failed: {e}")
        sys.exit(1)

    stations = res.get("STATION", [])
    if not stations:
        print("No stations returned by Synoptic! Check token or STID.")
        return

    for station in stations:
        stid = station.get("STID")
        mnet = station.get("MNET_ID")
        print(f"\n=================== STATION: {stid} (MNET: {mnet}) ===================")
        obs = station.get("OBSERVATIONS", {})
        
        if not obs:
            print("No OBSERVATIONS object found.")
            continue

        for key, vals in obs.items():
            # Filter specifically for wind, direction, and time keys
            if any(w in key.lower() for w in ["wind", "dir", "spd", "gust", "ff", "dd", "date_time"]):
                recent_vals = vals[-3:] if isinstance(vals, list) else vals
                print(f"  {key:40s} -> {recent_vals}")

if __name__ == "__main__":
    run_debug()
