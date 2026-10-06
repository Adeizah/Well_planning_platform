from datetime import date


def _decimal_year(d):
    start = date(d.year, 1, 1)
    end = date(d.year + 1, 1, 1)
    return d.year + (d - start).total_seconds() / ((end - start).total_seconds())


def wmm2025(lat, lon, altitude_m, calc_date):
    try:
        from pywmm import WMMv2
    except ImportError as exc:
        raise RuntimeError("pywmm is not installed.") from exc

    year = _decimal_year(calc_date)
    wmm = WMMv2()
    wmm.calculate_geomagnetic(float(lat), float(lon), year, float(altitude_m) / 1000.0)
    return {
        "D": float(wmm.dec),
        "I": float(wmm.dip),
        "F": float(wmm.ti),
        "H": float(wmm.bh),
        "X": float(wmm.bx),
        "Y": float(wmm.by),
        "Z": float(wmm.bz),
        "metadata": {
            "model": "WMM2025",
            "epoch": "2025.0",
            "validity": "2025.0–2030.0",
            "date": calc_date.isoformat(),
            "latitude": float(lat),
            "longitude": float(lon),
            "ellipsoid_height_m": float(altitude_m),
            "source": "NOAA/NCEI WMM2025 via pywmm",
        },
    }


def north_reference_conversions(magnetic_azimuth_deg, declination_deg, convergence_deg):
    """Convert magnetic azimuth to true and grid azimuth using east-positive angles.

    Convention: True = Magnetic + Declination; Grid = True - Grid Convergence.
    """
    true_az = (float(magnetic_azimuth_deg) + float(declination_deg)) % 360.0
    grid_az = (true_az - float(convergence_deg)) % 360.0
    return {
        "magnetic_azimuth_deg": float(magnetic_azimuth_deg) % 360.0,
        "true_azimuth_deg": true_az,
        "grid_azimuth_deg": grid_az,
    }
