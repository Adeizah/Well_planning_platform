from datetime import date, datetime, time
import math


def _as_date(value):
    """Normalize Streamlit/pandas/Python date-like values to datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return value.to_pydatetime().date()
    except AttributeError:
        return date.fromisoformat(str(value))


def _decimal_year(d):
    d = _as_date(d)
    start = date(d.year, 1, 1)
    end = date(d.year + 1, 1, 1)
    return d.year + (d - start).days / ((end - start).days)


def wmm2025(lat, lon, altitude_m, calc_date):
    """Calculate WMM2025 magnetic elements using the installed pywmm API.

    pywmm 1.1.1 exposes both individual getters and a calculate_geomagnetic
    convenience method. The individual getters are used as the primary path
    so the application remains compatible with builds where the convenience
    method is absent.
    """
    try:
        from pywmm import WMMv2
    except ImportError as exc:
        raise RuntimeError("pywmm is not installed.") from exc

    year = _decimal_year(calc_date)
    lat = float(lat); lon = float(lon); alt_km = float(altitude_m) / 1000.0
    wmm = WMMv2()

    if all(hasattr(wmm, name) for name in (
        'get_declination', 'get_dip_angle', 'get_intensity',
        'get_horizontal_intensity', 'get_north_intensity', 'get_east_intensity'
    )):
        D = float(wmm.get_declination(lat, lon, year, alt_km))
        I = float(wmm.get_dip_angle(lat, lon, year, alt_km))
        F = float(wmm.get_intensity(lat, lon, year, alt_km))
        H = float(wmm.get_horizontal_intensity(lat, lon, year, alt_km))
        X = float(wmm.get_north_intensity(lat, lon, year, alt_km))
        Y = float(wmm.get_east_intensity(lat, lon, year, alt_km))
        # WMM convention used by pywmm reports the vertical component as down.
        Z = math.copysign(max(F * F - H * H, 0.0) ** 0.5, math.sin(math.radians(I)))
    elif hasattr(wmm, 'calculate_geomagnetic'):
        wmm.calculate_geomagnetic(lat, lon, year, alt_km)
        D = float(wmm.dec); I = float(wmm.dip); F = float(wmm.ti)
        H = float(wmm.bh); X = float(wmm.bx); Y = float(wmm.by); Z = float(wmm.bz)
    else:
        raise RuntimeError('Installed pywmm WMMv2 API exposes neither the documented field getters nor calculate_geomagnetic().')

    return {
        'D': D, 'I': I, 'F': F, 'H': H, 'X': X, 'Y': Y, 'Z': Z,
        'metadata': {
            'model': 'WMM2025',
            'validity': '2025-2030',
            'source': 'NOAA/NCEI WMM2025 via pywmm',
            'calculation_date': _as_date(calc_date).isoformat(),
        }
    }


def igrf14(lat, lon, altitude_m, calc_date):
    """IGRF-14 main-field calculation. Returns D, I, H, X, Y, Z and F."""
    try:
        import ppigrf
    except ImportError as exc:
        raise RuntimeError("ppigrf is not installed.") from exc

    # ppigrf expects datetime-like values. Passing a plain date/Timestamp can
    # trigger date-vs-Timestamp comparisons in some releases. Normalize it.
    d = _as_date(calc_date)
    calc_dt = datetime.combine(d, time.min)
    Be, Bn, Bu = ppigrf.igrf(float(lon), float(lat), float(altitude_m) / 1000.0, calc_dt)
    # ppigrf returns 1-element NumPy arrays even for scalar coordinates.
    # Extract the single value before using Python math/scalar conversion.
    def _scalar(value, name):
        arr = __import__('numpy').asarray(value)
        if arr.size != 1:
            raise ValueError(f'IGRF returned unexpected {name} shape {arr.shape}; expected one value.')
        return float(arr.reshape(-1)[0])
    Be = _scalar(Be, 'east component')
    Bn = _scalar(Bn, 'north component')
    Bu = _scalar(Bu, 'up component')
    X = Bn; Y = Be; Z = -Bu
    H = math.hypot(X, Y)
    F = math.hypot(H, Z)
    D = math.degrees(math.atan2(Y, X))
    I = math.degrees(math.atan2(Z, H))
    return {
        'D': D, 'I': I, 'F': F, 'H': H, 'X': X, 'Y': Y, 'Z': Z,
        'metadata': {
            'model': 'IGRF-14',
            'validity': '2025-2030 forecast interval',
            'source': 'IAGA-VMOD ppigrf implementation',
            'calculation_date': d.isoformat(),
        }
    }


def north_reference_conversions(magnetic_azimuth_deg, declination_deg, convergence_deg):
    true_az = (float(magnetic_azimuth_deg) + float(declination_deg)) % 360.0
    grid_az = (true_az - float(convergence_deg)) % 360.0
    return {'true': true_az, 'grid': grid_az}
