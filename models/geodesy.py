
import requests

NOAA_GEOID_URL = "https://geodesy.noaa.gov/api/geoid/ght"

def noaa_geoid_height(lat, lon, model_id=14, timeout=15):
    params = {"lat": float(lat), "lon": float(lon), "model": int(model_id)}
    r = requests.get(NOAA_GEOID_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if "geoidHeight" not in data:
        raise RuntimeError(f"NOAA service returned no geoid height: {data}")
    return {
        "geoidModel": data.get("geoidModel"),
        "geoidHeight": float(data["geoidHeight"]),
        "error": float(data["error"]) if data.get("error") not in (None, "") else None,
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "service": NOAA_GEOID_URL
    }
