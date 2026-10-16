import math
import requests
from pyproj import CRS, Transformer, Proj
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_crs_info
from pyproj.enums import PJType
from pyproj.transformer import TransformerGroup

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


def common_crs_registry():
    """Curated CRSs commonly useful for well planning; units remain CRS-native."""
    return [
        {"label": "WGS 84 geographic (EPSG:4326)", "code": "EPSG:4326", "region": "Global"},
        {"label": "WGS 84 / UTM zone 31N (EPSG:32631)", "code": "EPSG:32631", "region": "Global"},
        {"label": "WGS 84 / UTM zone 32N (EPSG:32632)", "code": "EPSG:32632", "region": "Global"},
        {"label": "WGS 84 / UTM zone 33N (EPSG:32633)", "code": "EPSG:32633", "region": "Global"},
        {"label": "WGS 84 / UTM zone 31S (EPSG:32731)", "code": "EPSG:32731", "region": "Global"},
        {"label": "WGS 84 / UTM zone 32S (EPSG:32732)", "code": "EPSG:32732", "region": "Global"},
        {"label": "Minna geographic (EPSG:4263)", "code": "EPSG:4263", "region": "Nigeria"},
        {"label": "Minna / UTM zone 31N (EPSG:26331)", "code": "EPSG:26331", "region": "Nigeria / West Africa"},
        {"label": "Minna / UTM zone 32N (EPSG:26332)", "code": "EPSG:26332", "region": "Nigeria / West Africa"},
        {"label": "NAD83 geographic (EPSG:4269)", "code": "EPSG:4269", "region": "North America"},
        {"label": "ETRS89 geographic (EPSG:4258)", "code": "EPSG:4258", "region": "Europe"},
        {"label": "WGS 84 3D geographic (EPSG:4979)", "code": "EPSG:4979", "region": "Global / 3D"},
    ]


def search_crs_registry(query, limit=30):
    """Search the installed EPSG CRS database by name or authority code.

    This searches the local PROJ database and does not require a network request.
    """
    q = str(query or "").strip().casefold()
    if not q:
        return []
    results = []
    for item in query_crs_info(auth_name="EPSG", allow_deprecated=False):
        code = f"EPSG:{item.code}"
        name = item.name or ""
        if q in name.casefold() or q in code.casefold() or q == str(item.code).casefold():
            results.append({"label": f"{name} ({code})", "code": code, "type": str(item.type)} if hasattr(item, "type") else {"label": f"{name} ({code})", "code": code})
            if len(results) >= max(1, min(int(limit), 100)):
                break
    return results


def transformation_report(source_crs, target_crs, lon=None, lat=None):
    """Report available non-ballpark coordinate operations and missing-grid status.

    lon/lat, when supplied, define a small area of interest in geographic degrees.
    The report describes the locally installed PROJ resources; it is not a survey
    certification or a guarantee of field accuracy.
    """
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    aoi = None
    if lon is not None and lat is not None:
        lon, lat = float(lon), float(lat)
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            aoi = AreaOfInterest(lon - 0.05, max(-90, lat - 0.05), lon + 0.05, min(90, lat + 0.05))
    group = TransformerGroup(source, target, always_xy=True, area_of_interest=aoi, allow_ballpark=False)
    operations = []
    for tr in group.transformers:
        operations.append({
            "name": tr.name,
            "description": tr.description,
            "accuracy_m": None if tr.accuracy is None or tr.accuracy < 0 else float(tr.accuracy),
            "definition": tr.definition,
        })
    missing = []
    for op in group.unavailable_operations:
        grids = []
        for grid in getattr(op, "grids", []):
            grids.append({"name": grid.short_name, "available": bool(grid.available), "url": grid.url})
        missing.append({"name": op.name, "grids": grids})
    return {
        "source_crs": source.to_string(),
        "source_name": source.name,
        "target_crs": target.to_string(),
        "target_name": target.name,
        "operation_count": len(operations),
        "best_available": bool(group.best_available),
        "operations": operations,
        "unavailable_operations": missing,
        "has_missing_grids": bool(missing),
        "area_of_interest_used": aoi is not None,
    }


def transform_coordinates(x, y, source_crs, target_crs, *, strict=False, lon=None, lat=None):
    """Transform coordinates using PROJ; strict mode disallows ballpark operations.

    For strict transformations, pass lon/lat when the location is known so PROJ
    can choose a location-appropriate operation and report unavailable grids.
    """
    if strict:
        report = transformation_report(source_crs, target_crs, lon=lon, lat=lat)
        if report["operation_count"] == 0 or not report["best_available"]:
            details = " Required grid resources may be missing." if report["has_missing_grids"] else ""
            raise ValueError(f"No verified non-ballpark transformation is available from {source_crs} to {target_crs}.{details}")
        transformer = Transformer.from_pipeline(report["operations"][0]["definition"])
    else:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    xx, yy = transformer.transform(float(x), float(y), errcheck=True)
    if not (math.isfinite(xx) and math.isfinite(yy)):
        raise ValueError("Coordinate transformation returned non-finite coordinates.")
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
