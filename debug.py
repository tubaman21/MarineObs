import os
import json
import requests

SYNOPTIC_API_URL = "https://api.synopticdata.com/v2/stations/timeseries"
api_token = os.environ.get("SYNOPTIC_API_TOKEN")

params = {
    "token": api_token,
    "stid": "STDM4,45213",
    "recent": 60,
    "obtimezone": "UTC",
    "output": "json",
    "extra": "sensor_variables"
}

res = requests.get(SYNOPTIC_API_URL, params=params).json()

for station in res.get("STATION", []):
    stid = station.get("STID")
    print(f"\n=================== {stid} RAW KEYS ===================")
    obs = station.get("OBSERVATIONS", {})
    for key, vals in obs.items():
        if any(w in key.lower() for w in ["wind", "dir", "spd", "gust", "ff", "dd"]):
            recent_vals = vals[-3:] if isinstance(vals, list) else vals
            print(f"{key:35s} -> {recent_vals}")
