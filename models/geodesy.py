import math
import requests
from pyproj import CRS, Transformer, Proj, database
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


def transform_coordinates(x, y, source_crs, target_crs, strict=False, lon=None, lat=None):
    """Transform coordinates with location-aware operation selection.

    Inputs and outputs use each CRS's native axis units. In strict mode, do not
    silently fall back to ballpark operations. If the needed high-accuracy
    operation/grid is unavailable, return an actionable error rather than
    presenting an approximate result as authoritative.
    """
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    x, y = float(x), float(y)
    kwargs = {"always_xy": True}
    probe_lon, probe_lat = lon, lat
    # Determine an area of interest from the actual coordinate where possible.
    if probe_lon is None or probe_lat is None:
        try:
            if source.is_geographic:
                probe_lon, probe_lat = x, y
            else:
                to_geo = Transformer.from_crs(source, "EPSG:4326", always_xy=True)
                probe_lon, probe_lat = to_geo.transform(x, y, errcheck=True)
        except Exception:
            probe_lon = probe_lat = None
    if probe_lon is not None and probe_lat is not None:
        try:
            from pyproj.aoi import AreaOfInterest
            kwargs["area_of_interest"] = AreaOfInterest(float(probe_lon)-0.05, float(probe_lat)-0.05,
                                                         float(probe_lon)+0.05, float(probe_lat)+0.05)
        except Exception:
            pass
    if strict:
        from pyproj.transformer import TransformerGroup
        group = TransformerGroup(source, target, always_xy=True,
                                 area_of_interest=kwargs.get("area_of_interest"),
                                 allow_ballpark=False)
        if not group.transformers:
            missing = []
            for op in getattr(group, "unavailable_operations", []):
                for grid in getattr(op, "grids", []):
                    if not getattr(grid, "available", True):
                        missing.append(getattr(grid, "short_name", getattr(grid, "name", "required grid")))
            detail = (" Missing transformation grid(s): " + ", ".join(sorted(set(missing))) + "."
                      if missing else " No non-ballpark coordinate operation is available for this CRS pair/location.")
            raise ValueError("Suitable datum transformation unavailable." + detail +
                             " Install the authoritative grid resource or supply a verified transformation; coordinates were not converted.")
        transformer = group.transformers[0]
        if transformer.accuracy < 0:
            raise ValueError("A non-ballpark operation exists, but its accuracy is not stated. Strict mode will not certify this transformation.")
    else:
        transformer = Transformer.from_crs(source, target, **kwargs)
    xx, yy = transformer.transform(x, y, errcheck=True)
    if not (math.isfinite(xx) and math.isfinite(yy)):
        raise ValueError("Coordinate transformation returned a non-finite result.")
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
    """Report transformation availability without making the UI fail on AOI issues.

    An area of interest can make PROJ reject operation construction when the
    supplied location is outside the source CRS area or is itself derived from
    invalid coordinates. Try the location-specific operation first, then retry
    without an AOI for diagnostic purposes. This fallback is diagnostic only;
    it does not certify a transformation for operational use.
    """
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    attempts = []
    if lon is not None and lat is not None:
        try:
            from pyproj.aoi import AreaOfInterest
            aoi = AreaOfInterest(float(lon)-0.05, float(lat)-0.05,
                                 float(lon)+0.05, float(lat)+0.05)
            attempts.append({"always_xy": True, "area_of_interest": aoi})
        except Exception:
            pass
    attempts.append({"always_xy": True})
    errors = []
    for kwargs in attempts:
        try:
            group = Transformer.from_crs(source, target, **kwargs)
            try:
                operations = group.operations
            except Exception:
                operations = ()
            strict_kwargs = dict(kwargs)
            strict_kwargs.update({"allow_ballpark": False, "only_best": True})
            try:
                best = Transformer.from_crs(source, target, **strict_kwargs)
                # Force PROJ to resolve the operation now, not lazily in a later page.
                if lon is not None and lat is not None:
                    if source.is_geographic:
                        best.transform(float(lon), float(lat), errcheck=True)
                    elif target.is_geographic:
                        # Only a diagnostic probe; actual projected coordinates
                        # are not available to this report function.
                        pass
                accuracy = float(best.accuracy)
                description = best.description
                available = accuracy >= 0
            except Exception as exc:
                accuracy = -1.0
                description = str(exc)
                available = False
            return {"source_crs": source.to_string(), "target_crs": target.to_string(),
                    "operation_count": max(1, len(operations)), "best_available": available,
                    "accuracy_m": accuracy if accuracy >= 0 else None,
                    "description": description,
                    "area_of_interest_used": "area_of_interest" in kwargs,
                    "diagnostic_fallback_used": "area_of_interest" not in kwargs and lon is not None and lat is not None}
        except Exception as exc:
            errors.append(str(exc))
    return {"source_crs": source.to_string(), "target_crs": target.to_string(),
            "operation_count": 0, "best_available": False, "accuracy_m": None,
            "description": "; ".join(errors) or "No coordinate operation could be constructed.",
            "area_of_interest_used": False, "diagnostic_fallback_used": True}



def transformation_operations(source_crs, target_crs, lon=None, lat=None):
    """Enumerate usable and unavailable PROJ operations and missing grids."""
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    kwargs = {"always_xy": True, "allow_ballpark": False}
    if lon is not None and lat is not None:
        from pyproj.aoi import AreaOfInterest
        kwargs["area_of_interest"] = AreaOfInterest(float(lon)-0.05, float(lat)-0.05,
                                                     float(lon)+0.05, float(lat)+0.05)
    group = TransformerGroup(source, target, **kwargs)
    usable = [{"description": t.description, "accuracy_m": t.accuracy} for t in group.transformers]
    missing = []
    for operation in group.unavailable_operations:
        grids = [getattr(g, "short_name", getattr(g, "name", "grid"))
                 for g in getattr(operation, "grids", []) if not getattr(g, "available", True)]
        missing.append({"operation": operation.name, "missing_grids": grids})
    return {"source_crs": source.to_string(), "target_crs": target.to_string(),
            "available_operations": usable, "unavailable_operations": missing,
            "best_available": bool(group.best_available and usable),
            "message": "Suitable operation available" if group.best_available and usable else
                       "One or more preferred operations unavailable; inspect missing grids and accuracy before use."}

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
