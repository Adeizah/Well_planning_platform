from datetime import date, datetime


def wmm2025(lat, lon, altitude_m, calc_date):
    try:
        from pywmm import WMMv2
    except ImportError as exc:
        raise RuntimeError("pywmm is not installed.") from exc
    dt = calc_date if isinstance(calc_date, (date, datetime)) else date.fromisoformat(str(calc_date))
    year = dt.year + (dt.timetuple().tm_yday - 1) / 365.25
    wmm = WMMv2()
    wmm.calculate_geomagnetic(float(lat), float(lon), year, float(altitude_m) / 1000.0)
    return {
        "D": float(wmm.dec), "I": float(wmm.dip), "F": float(wmm.ti),
        "H": float(wmm.bh), "X": float(wmm.bx), "Y": float(wmm.by), "Z": float(wmm.bz),
        "metadata": {"model": "WMM2025", "validity": "2025-2030", "source": "NOAA/NCEI WMM2025 via pywmm"}
    }


def igrf14(lat, lon, altitude_m, calc_date):
    """IGRF-14 main-field calculation. Returns D, I, H, X, Y, Z and F."""
    try:
        import ppigrf
    except ImportError as exc:
        raise RuntimeError("ppigrf is not installed.") from exc
    dt = calc_date if isinstance(calc_date, (date, datetime)) else date.fromisoformat(str(calc_date))
    Be, Bn, Bu = ppigrf.igrf(float(lon), float(lat), float(altitude_m) / 1000.0, dt)
    # ppigrf returns east, north, up in nT.
    X = float(Bn); Y = float(Be); Z = float(-Bu)
    H = (X * X + Y * Y) ** 0.5
    F = (H * H + Z * Z) ** 0.5
    import math
    D = math.degrees(math.atan2(Y, X))
    I = math.degrees(math.atan2(Z, H))
    return {
        "D": D, "I": I, "F": F, "H": H, "X": X, "Y": Y, "Z": Z,
        "metadata": {"model": "IGRF-14", "validity": "2025-2030 forecast interval", "source": "IAGA-VMOD ppigrf implementation"}
    }


def north_reference_conversions(magnetic_azimuth_deg, declination_deg, convergence_deg):
    true_az = (float(magnetic_azimuth_deg) + float(declination_deg)) % 360.0
    grid_az = (true_az - float(convergence_deg)) % 360.0
    return {"true": true_az, "grid": grid_az}
