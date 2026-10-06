import math
import requests
from pyproj import CRS, Transformer, Proj

NOAA_GEOID_URL = "https://geodesy.noaa.gov/api/geoid/ght"


def crs_info(crs_code):
    crs = CRS.from_user_input(crs_code)
    return {
        "name": crs.name,
        "type": "Projected" if crs.is_projected else ("Geographic" if crs.is_geographic else "Other"),
        "datum": crs.datum.name if crs.datum else "Unknown",
        "ellipsoid": crs.ellipsoid.name if crs.ellipsoid else "Unknown",
        "units": crs.axis_info[0].unit_name if crs.axis_info else "Unknown",
        "authority": crs.to_authority(),
        "epsg": crs.to_epsg(),
    }


def transform_coordinates(x, y, source_crs, target_crs):
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    xx, yy = transformer.transform(float(x), float(y))
    return float(xx), float(yy)


def grid_convergence_deg(lat, lon, crs_code):
    """Return meridian convergence from the selected projected CRS, where supported."""
    crs = CRS.from_user_input(crs_code)
    if not crs.is_projected:
        return 0.0
    proj = Proj(crs)
    factors = proj.get_factors(float(lon), float(lat))
    return float(factors.meridian_convergence)


def normal_gravity(lat_deg, height_m=0.0):
    """Approximate normal gravity using the WGS84 normal-gravity formula.

    This is a reference/normal gravity value, not a measured local gravity anomaly.
    """
    lat = math.radians(float(lat_deg))
    h = float(height_m)
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    gamma_e = 9.7803253359
    k = 0.00193185265241
    sin2 = math.sin(lat) ** 2
    gamma0 = gamma_e * (1 + k * sin2) / math.sqrt(1 - e2 * sin2)
    # First-order free-air height correction for reference gravity.
    return gamma0 - 3.086e-6 * h


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
        "service": NOAA_GEOID_URL,
    }
