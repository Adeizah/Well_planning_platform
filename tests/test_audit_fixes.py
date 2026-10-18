"""Regression tests for defects found in the project audit (see docs/GAP_ANALYSIS.md)."""
import importlib.util, math, os, sys

import numpy as np
import pandas as pd

from core.geometry import target_boundary, target_contains, target_tolerances
from core.optimizer import _shape_miss
from core.trajectory import minimum_curvature, truncate_trajectory_at_md, interpolate_path, vertical_section
from engineering.anti_collision import clearance_report, clearance_profile
from models.survey_uncertainty import station_covariances, interpolate_covariance


def _vert(md=3000.0, n=61):
    return pd.DataFrame({'MD': np.linspace(0, md, n), 'Inc': 0.0, 'Azi': 0.0})


def _legacy_uncertainty():
    path = os.path.join(os.path.dirname(__file__), 'legacy_survey_uncertainty.py')
    spec = importlib.util.spec_from_file_location('legacy_survey_uncertainty', path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------- anti-collision axis swap
def test_separation_factor_uses_correct_north_east_axes():
    """Wells 10 m apart, uncertainty dominated by the North direction (vertical well, azimuth 0).
    North-South separation must be the WARNING case; East-West the safe one. The old code swapped them."""
    main = minimum_curvature(_vert())
    cov = station_covariances(_vert()); C = interpolate_covariance(cov, 3000.0)
    out = {}
    for label, (de, dn) in {'EW': (10.0, 0.0), 'NS': (0.0, 10.0)}.items():
        off = {'name': 'OW', 'surface_easting_m': de, 'surface_northing_m': dn, 'surveys': _vert().to_dict('records')}
        r = clearance_report(main, [off], survey_error_model={}).iloc[0]
        u = np.array([dn, de, 0.0]) / 10.0                    # (North, East, TVD), same order as the covariance
        expected_sf = 10.0 / math.sqrt(u @ (2 * C) @ u)
        assert abs(r.separation_factor - expected_sf) < 0.05, (label, r.separation_factor, expected_sf)
        out[label] = r
    assert out['NS'].separation_factor < out['EW'].separation_factor
    assert out['NS'].status in ('WARNING', 'ALERT') and out['EW'].status == 'PASS'


def test_closest_approach_is_continuous_not_sample_limited():
    """Two skew straight wells with an exact minimum distance of 40 m, whatever the sampling."""
    main = minimum_curvature(pd.DataFrame({'MD': [0.0, 3000.0], 'Inc': [0.0, 0.0], 'Azi': [0.0, 0.0]}))
    off = {'name': 'S', 'surface_easting_m': -1000.0, 'surface_northing_m': 40.0,
           'surveys': [{'MD': 0.0, 'Inc': 45.0, 'Azi': 90.0}, {'MD': 2000.0, 'Inc': 45.0, 'Azi': 90.0}]}
    for samples in (20, 60, 600):
        r = clearance_report(main, [off], survey_error_model={}, samples_per_well=samples).iloc[0]
        assert abs(r.separation_m - 40.0) < 0.05, (samples, r.separation_m)


def test_clearance_reports_risk_intervals_and_profile():
    main = minimum_curvature(_vert())
    off = {'name': 'OW', 'surface_easting_m': 0.0, 'surface_northing_m': 10.0, 'surveys': _vert().to_dict('records')}   # N-S: the weak direction
    r = clearance_report(main, [off], survey_error_model={}, required_separation_factor=2.0).iloc[0]
    assert r.risk_intervals and r.risk_intervals[0]['min_sf'] < 2.0
    prof = clearance_profile(main, off, survey_error_model={})
    assert len(prof) > 100 and prof.min_sf.min() < 2.0


def test_hard_minimum_distance_and_radii_are_applied():
    main = minimum_curvature(_vert())
    off = {'name': 'OW', 'surface_easting_m': 60.0, 'surface_northing_m': 0.0, 'surveys': _vert().to_dict('records')}
    base = clearance_report(main, [off], survey_error_model={}).iloc[0]
    hard = clearance_report(main, [off], survey_error_model={}, criteria={'min_separation_m': 100.0}).iloc[0]
    radii = clearance_report(main, [off], survey_error_model={}, criteria={'main_radius_m': 0.3, 'offset_radius_m': 0.3}).iloc[0]
    assert hard.status == 'ALERT' and base.status != 'ALERT'
    assert radii.separation_factor < base.separation_factor


def test_offset_kb_datum_shift_is_applied():
    main = minimum_curvature(_vert(1000.0, 21))
    off = {'name': 'OW', 'surface_easting_m': 0.0, 'surface_northing_m': 0.0, 'kb_m': 40.0,
           'surveys': [{'MD': 0.0, 'Inc': 90.0, 'Azi': 90.0}, {'MD': 100.0, 'Inc': 90.0, 'Azi': 90.0}]}   # horizontal line at TVD 0..0
    same = clearance_report(main, [off], survey_error_model={}, main_kb_m=40.0).iloc[0]
    shifted = clearance_report(main, [off], survey_error_model={}, main_kb_m=55.0).iloc[0]      # offset TVD moves 15 m deeper (55 - 40)
    assert abs(same.separation_m - 0.0) < 0.05
    assert abs(shifted.separation_m - 0.0) < 0.05           # the vertical main well still crosses the horizontal line
    assert abs(shifted.main_md_m - 15.0) < 0.5               # ...but now at MD 15 m, not 0


# --------------------------------------------------------------------- targets
def test_polygon_boundary_and_miss_use_the_target_centre():
    poly = {'type': 'Polygon', 'north_m': 1000.0, 'east_m': 1000.0, 'points': [[-50, -50], [-50, 50], [50, 50], [50, -50]]}
    n, e = target_boundary(poly)
    assert min(n) == 950.0 and max(n) == 1050.0 and min(e) == 950.0 and max(e) == 1050.0
    assert target_contains(poly, 1000.0, 1000.0)
    assert abs(_shape_miss(1000.0, 1060.0, 60.0, poly, 30.48) - 10.0) < 1e-9


def test_rectangular_target_orientation():
    rect = {'type': 'Rectangular', 'north_m': 0.0, 'east_m': 0.0, 'length_m': 200.0, 'width_m': 50.0, 'orientation_deg': 90.0}
    assert target_contains(rect, 0.0, 90.0) and not target_contains(rect, 90.0, 0.0)
    legacy = dict(rect); legacy.pop('orientation_deg')
    assert target_contains(legacy, 90.0, 0.0) and not target_contains(legacy, 0.0, 90.0)   # unchanged default


def test_target_tolerance_and_thickness():
    assert target_tolerances({}) == (0.0, 0.0)                                   # Point targets are exact geometric constraints (no tolerance radius)
    assert target_tolerances({'type': 'Point', 'tolerance_m': 25.0}) == (0.0, 0.0)  # a stray tolerance value never turns a point into an area
    assert target_tolerances({'type': 'Circular'}) == (30.48, 30.48)             # areal targets keep their default band
    assert target_tolerances({'type': 'Circular', 'tolerance_m': 10.0, 'vertical_tolerance_m': 5.0}) == (10.0, 5.0)
    assert abs(target_tolerances({'type': 'Circular', 'tolerance_m': 5.0, 'thickness_m': 40.0})[1] - 20.0) < 1e-9
    assert target_tolerances({'type': 'Circular', 'tolerance_m': 5.0, 'thickness_m': 40.0, 'dip_deg': 60.0})[1] > 39.9


# --------------------------------------------------------------------- survey calculations
def _textbook_min_curv(md, inc, azi):
    n = e = z = 0.0; out = [(0.0, 0.0, 0.0)]
    for k in range(1, len(md)):
        i1, i2, a1, a2 = map(math.radians, (inc[k - 1], inc[k], azi[k - 1], azi[k]))
        dl = md[k] - md[k - 1]
        beta = math.acos(min(1.0, max(-1.0, math.cos(i2 - i1) - math.sin(i1) * math.sin(i2) * (1 - math.cos(a2 - a1)))))
        rf = 1.0 if beta < 1e-9 else 2 / beta * math.tan(beta / 2)
        n += dl / 2 * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * rf
        e += dl / 2 * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * rf
        z += dl / 2 * (math.cos(i1) + math.cos(i2)) * rf
        out.append((n, e, z))
    return np.array(out)


def test_vectorised_minimum_curvature_matches_textbook_formula():
    rng = np.random.default_rng(5)
    md = np.concatenate([[0.0], np.cumsum(rng.uniform(10, 80, 40))]); inc = np.clip(np.cumsum(rng.normal(0, 3, 41)) + 20, 0, 110)
    azi = (np.cumsum(rng.normal(0, 8, 41)) + 100) % 360
    ref = _textbook_min_curv(md, inc, azi)
    got = minimum_curvature(pd.DataFrame({'MD': md, 'Inc': inc, 'Azi': azi}))[['Northing', 'Easting', 'TVD']].to_numpy()
    assert np.max(np.abs(got - ref)) < 1e-8


def test_survey_not_starting_at_md_zero_gets_vertical_tie_in():
    r = minimum_curvature(pd.DataFrame({'MD': [100.0, 200.0, 300.0], 'Inc': 0.0, 'Azi': 0.0}))
    assert list(r.TVD) == [100.0, 200.0, 300.0] and r.attrs['tie_in_assumed'] is True
    explicit = minimum_curvature(pd.DataFrame({'MD': [100.0, 200.0], 'Inc': 0.0, 'Azi': 0.0}), tie_in={'tvd': 90.0, 'north': 5.0, 'east': 6.0})
    assert explicit.TVD.iloc[0] == 90.0 and explicit.Northing.iloc[0] == 5.0 and explicit.Easting.iloc[0] == 6.0
    assert minimum_curvature(pd.DataFrame({'MD': [0.0, 100.0], 'Inc': 0.0, 'Azi': 0.0})).attrs['tie_in_assumed'] is False


def test_truncation_places_the_final_station_on_the_arc():
    raw = pd.DataFrame({'MD': [0, 500, 1000, 1500.0], 'Inc': [0, 30, 60, 90.0], 'Azi': 0.0})
    cut = truncate_trajectory_at_md(minimum_curvature(raw), 750.0)
    fine_md = np.arange(0, 751.0, 1.0)
    dense = minimum_curvature(pd.DataFrame({'MD': fine_md, 'Inc': np.interp(fine_md, raw.MD, raw.Inc), 'Azi': 0.0}))
    assert abs(cut.Northing.iloc[-1] - dense.Northing.iloc[-1]) < 0.01 and abs(cut.TVD.iloc[-1] - dense.TVD.iloc[-1]) < 0.01
    assert cut.MD.iloc[-1] == 750.0


def test_interpolate_path_is_exact_at_stations_and_on_the_arc():
    raw = pd.DataFrame({'MD': [0, 100.0, 200.0, 300.0], 'Inc': [0, 20, 40, 40.0], 'Azi': [0, 0, 40, 40.0]})
    p = minimum_curvature(raw)
    at = interpolate_path(p, p.MD.to_numpy())
    assert np.max(np.abs(at[['Northing', 'Easting', 'TVD']].to_numpy() - p[['Northing', 'Easting', 'TVD']].to_numpy())) < 1e-9
    mid = interpolate_path(p, [150.0]).iloc[0]
    split = minimum_curvature(pd.DataFrame({'MD': [0, 100.0, 150.0], 'Inc': [0, 20, mid.Inc], 'Azi': [0, 0, mid.Azi]})).iloc[-1]
    assert abs(split.Northing - mid.Northing) < 1e-6 and abs(split.Easting - mid.Easting) < 1e-6 and abs(split.TVD - mid.TVD) < 1e-6


def test_vertical_section_is_a_projection_not_closure():
    p = minimum_curvature(pd.DataFrame({'MD': [0, 500, 1000.0], 'Inc': [0, 45, 45.0], 'Azi': [0, 90, 90.0]}))
    assert abs(vertical_section(p, 90.0)[-1] - p.Easting.iloc[-1]) < 1e-9 and abs(vertical_section(p, 0.0)[-1]) < 1e-9


def test_vectorised_covariance_matches_the_original_loop_implementation():
    legacy = _legacy_uncertainty(); rng = np.random.default_rng(2)
    n = 25; md = np.concatenate([[0.0], np.cumsum(rng.uniform(15, 90, n - 1))]); inc = np.clip(np.cumsum(rng.normal(0, 3, n)) + 10, 0, 90); inc[0] = 0
    azi = (np.cumsum(rng.normal(0, 6, n)) + 50) % 360
    df = pd.DataFrame({'MD': md, 'Inc': inc, 'Azi': azi})
    for kw in ({}, {'sigma_surface_ft': 0.0, 'sigma_md_ft': 0.0}, {'sigma_inc_deg': 0.3, 'sigma_azi_deg': 1.0, 'sigma_azi_systematic_deg': 1.5}):
        a, b = legacy.station_covariances(df, **kw), station_covariances(df, **kw)
        for c in [c for c in a.columns if c.startswith(('Cov_', 'Unc_'))]:
            assert np.max(np.abs(a[c] - b[c])) <= 1e-8 * max(1.0, np.abs(a[c]).max()), c


def test_covariance_scales_linearly_with_station_count():
    import time
    df = pd.DataFrame({'MD': np.linspace(0, 6000, 1500), 'Inc': np.linspace(0, 60, 1500), 'Azi': 45.0})
    t = time.time(); station_covariances(df)
    assert time.time() - t < 5.0        # was ~minutes (O(n^2) with pandas row access)
