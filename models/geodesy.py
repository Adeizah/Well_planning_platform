import math
import requests
from pyproj import CRS, Transformer, Proj, database

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


def transform_coordinates(x, y, source_crs, target_crs, strict=False, lon=None, lat=None):
    """Transform coordinates, optionally refusing unavailable/ballpark operations.

    Coordinates are always in the native axis units of the supplied CRSs. The
    caller must not label coordinates with a new CRS without transforming them.
    """
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    kwargs = {"always_xy": True}
    if lon is not None and lat is not None:
        from pyproj.aoi import AreaOfInterest
        kwargs["area_of_interest"] = AreaOfInterest(float(lon)-0.05, float(lat)-0.05, float(lon)+0.05, float(lat)+0.05)
    if strict:
        kwargs.update({"allow_ballpark": False, "only_best": True})
    transformer = Transformer.from_crs(source, target, **kwargs)
    xx, yy = transformer.transform(float(x), float(y), errcheck=True)
    if not (math.isfinite(xx) and math.isfinite(yy)):
        raise ValueError("Coordinate transformation returned a non-finite result.")
    if strict and transformer.accuracy < 0:
        raise ValueError("No stated-accuracy coordinate operation is available; use a suitable transformation/grid resource.")
    return float(xx), float(yy)


def projected_unit_to_metre_factor(crs_code):
    """Return metres per native coordinate unit for a projected CRS."""
    crs = CRS.from_user_input(crs_code)
    if not crs.is_projected:
        raise ValueError("A projected CRS is required for grid coordinates.")
    if not crs.axis_info:
        raise ValueError("The projected CRS does not define coordinate units.")
    factor = crs.axis_info[0].unit_conversion_factor
    if factor is None or not math.isfinite(float(factor)) or float(factor) <= 0:
        raise ValueError("The projected CRS has an unsupported coordinate-unit conversion.")
    return float(factor)


def projected_coordinates_to_metres(x, y, crs_code):
    """Convert projected CRS-native Easting/Northing values to metres."""
    factor = projected_unit_to_metre_factor(crs_code)
    return float(x) * factor, float(y) * factor


def metres_to_projected_coordinates(easting_m, northing_m, crs_code):
    """Convert metre-based project grid coordinates to CRS-native coordinates."""
    factor = projected_unit_to_metre_factor(crs_code)
    return float(easting_m) / factor, float(northing_m) / factor


def transform_projected_grid_metres(easting_m, northing_m, source_crs, target_crs):
    """Transform stored metre-normalized grid coordinates between projected CRSs."""
    x_src, y_src = metres_to_projected_coordinates(easting_m, northing_m, source_crs)
    x_dst, y_dst = transform_coordinates(x_src, y_src, source_crs, target_crs, strict=True)
    return projected_coordinates_to_metres(x_dst, y_dst, target_crs)


def common_crs_registry():
    """Curated geographic and projected CRSs commonly relevant to well planning."""
    codes = ["EPSG:4326", "EPSG:4263", "EPSG:26331", "EPSG:26332", "EPSG:26333",
             "EPSG:32631", "EPSG:32632", "EPSG:32633", "EPSG:32731", "EPSG:32732", "EPSG:32733",
             "EPSG:4258", "EPSG:4269"]
    rows = []
    for code in codes:
        try:
            info = crs_info(code)
            rows.append({"code": code, "name": info["name"], "datum": info["datum"],
                         "type": info["type"], "units": info["units"]})
        except Exception:
            continue
    # Include useful common CRSs where available in the installed PROJ database.
    return rows


def search_crs_registry(query, limit=50):
    """Search installed EPSG CRS database by authority code, name, or datum."""
    q = str(query or "").strip().casefold()
    if not q:
        return []
    try:
        infos = database.query_crs_info(auth_name="EPSG")
    except Exception:
        infos = []
    rows = []
    for info in infos:
        code = f"{info.auth_name}:{info.code}"
        try:
            crs = CRS.from_authority(info.auth_name, info.code)
            datum = crs.datum.name if crs.datum else "Unknown"
            text = f"{code} {info.name} {datum}".casefold()
            if q in text:
                rows.append({"code": code, "name": info.name, "datum": datum,
                             "type": "Projected" if crs.is_projected else ("Geographic" if crs.is_geographic else "Other"),
                             "units": crs.axis_info[0].unit_name if crs.axis_info else "Unknown"})
        except Exception:
            continue
        if len(rows) >= max(1, min(int(limit), 200)):
            break
    return rows


def transformation_report(source_crs, target_crs, lon=None, lat=None):
    """Summarize available transformation operations at an optional area of interest."""
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    kwargs = {"always_xy": True}
    if lon is not None and lat is not None:
        from pyproj.aoi import AreaOfInterest
        kwargs["area_of_interest"] = AreaOfInterest(float(lon)-0.05, float(lat)-0.05, float(lon)+0.05, float(lat)+0.05)
    group = Transformer.from_crs(source, target, **kwargs)
    try:
        operations = group.operations
    except Exception:
        operations = ()
    best_kwargs = dict(kwargs)
    best_kwargs.update({"allow_ballpark": False, "only_best": True})
    best = Transformer.from_crs(source, target, **best_kwargs)
    accuracy = best.accuracy
    return {"source_crs": source.to_string(), "target_crs": target.to_string(),
            "operation_count": max(1, len(operations)), "best_available": accuracy >= 0,
            "accuracy_m": accuracy if accuracy >= 0 else None,
            "description": best.description, "area_of_interest_used": lon is not None and lat is not None}


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
