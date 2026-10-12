import pandas as pd
from core.optimizer import optimize_trajectory
from core.trajectory import generate_profile_candidate


def test_profile_optimizer_returns_profile_aware_parameters():
    # Keep the search small so this remains a quick regression test.
    path, meta = optimize_trajectory(
        profile='J-Profile', target_tvd_m=900, target_north_m=0, target_east_m=900,
        kop_initial_m=200, build_rate_initial_deg_30m=2.5,
        peak_inc_initial_deg=45, azimuth_initial_deg=90,
        max_inclination_deg=65, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, station_interval_m=120,
        max_md_m=3000, maxiter=2, popsize=4,
    )
    assert len(path) >= 2
    assert meta['optimized_parameters']['profile'] == 'J-Profile'
    assert 'KOP_MD_m' in meta['optimized_parameters']
    assert 'azimuth_deg_grid' in meta['optimized_parameters']
    assert meta['optimization_status'] in {'FEASIBLE', 'REVIEW'}


def test_vertical_profile_returns_review_for_lateral_target():
    path, meta = optimize_trajectory(
        profile='Vertical', target_tvd_m=1000, target_north_m=500, target_east_m=0,
        kop_initial_m=0, build_rate_initial_deg_30m=1,
        peak_inc_initial_deg=0, azimuth_initial_deg=0,
        max_inclination_deg=60, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, max_md_m=2000,
    )
    assert meta['optimization_status'] == 'NO_FEASIBLE_DIRECTIONAL_SOLUTION'
    assert meta['target_lateral_error_m'] > 400


def test_vertical_profile_candidate_does_not_raise_unbound_metadata():
    path, meta = generate_profile_candidate('Vertical', 0, 1, 0, 0, 1000, 0, 0)
    assert len(path) >= 2
    assert meta['profile'] == 'Vertical'


def test_optimizer_respects_circular_target_footprint():
    target = {'type':'Circular','north_m':0.0,'east_m':0.0,'radius_m':100.0}
    path, meta = optimize_trajectory(
        profile='J-Profile', target_tvd_m=900, target_north_m=0, target_east_m=900,
        kop_initial_m=200, build_rate_initial_deg_30m=2.5,
        peak_inc_initial_deg=45, azimuth_initial_deg=90,
        max_inclination_deg=65, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, target_geometry=target,
        station_interval_m=120, max_md_m=3000, maxiter=1, popsize=4,
    )
    assert 'target_miss_distance_m' in meta
    assert meta['optimized_parameters']['profile'] == 'J-Profile'


def test_custom_optimizer_exposes_drop_start_and_drop_rate():
    path, meta = optimize_trajectory(
        profile='Custom', target_tvd_m=900, target_north_m=0, target_east_m=900,
        kop_initial_m=200, build_rate_initial_deg_30m=2.5,
        peak_inc_initial_deg=45, azimuth_initial_deg=90,
        max_inclination_deg=65, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, station_interval_m=120,
        max_md_m=3000, maxiter=1, popsize=4,
    )
    params=meta['optimized_parameters']
    assert params['drop_start_md_m'] is not None
    assert params['drop_rate_deg_30m'] is not None


def test_target_residual_checks_lateral_hold_after_first_tvd_crossing():
    """A horizontal section can hit the target after the first TVD crossing."""
    from core.optimizer import _target_residual
    path = pd.DataFrame({
        'MD': [0.0, 100.0, 200.0, 300.0],
        'TVD': [0.0, 100.0, 200.0, 200.2],
        'Northing': [0.0, 50.0, 100.0, 300.0],
        'Easting': [0.0, 0.0, 0.0, 0.0],
    })
    lateral, vertical, md, miss = _target_residual(
        path, target_tvd_m=200.0, target_north_m=250.0, target_east_m=0.0,
        target_geometry={'type': 'Circular', 'north_m': 250.0, 'east_m': 0.0, 'radius_m': 10.0},
        point_tolerance_m=30.48,
    )
    assert lateral <= 1.0
    assert abs(vertical) <= 1.0
    assert 250.0 <= md <= 300.0
    assert miss == 0.0



def test_optimizer_can_hold_kop_fixed():
    _, meta = optimize_trajectory(
        profile='J-Profile', target_tvd_m=700, target_north_m=0, target_east_m=700,
        kop_initial_m=180, build_rate_initial_deg_30m=2,
        peak_inc_initial_deg=45, azimuth_initial_deg=90,
        max_inclination_deg=65, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, station_interval_m=120,
        max_md_m=2500, kop_mode='fixed', maxiter=1, popsize=4,
    )
    assert abs(meta['optimized_parameters']['KOP_MD_m'] - 180) < 1e-8
    assert meta['kop_mode'] == 'fixed'
    assert meta['kop_constraint_m']['fixed_m'] == 180


def test_optimizer_keeps_kop_inside_user_window():
    _, meta = optimize_trajectory(
        profile='J-Profile', target_tvd_m=700, target_north_m=0, target_east_m=700,
        kop_initial_m=180, build_rate_initial_deg_30m=2,
        peak_inc_initial_deg=45, azimuth_initial_deg=90,
        max_inclination_deg=65, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, station_interval_m=120,
        max_md_m=2500, kop_mode='window', kop_window_min_m=150,
        kop_window_max_m=220, maxiter=1, popsize=4,
    )
    kop = meta['optimized_parameters']['KOP_MD_m']
    assert 150 <= kop <= 220
    assert meta['kop_mode'] == 'window'


def test_optimizer_rejects_invalid_kop_window():
    import pytest
    with pytest.raises(ValueError, match='KOP window'):
        optimize_trajectory(
            profile='J-Profile', target_tvd_m=700, target_north_m=0, target_east_m=700,
            kop_initial_m=180, build_rate_initial_deg_30m=2,
            peak_inc_initial_deg=45, azimuth_initial_deg=90,
            max_inclination_deg=65, max_dls_deg_30m=3,
            max_build_rate_deg_30m=3, max_md_m=2500,
            kop_mode='window', kop_window_min_m=220, kop_window_max_m=150,
            maxiter=1, popsize=4,
        )


def test_azimuth_turn_rate_changes_azimuth_after_kop_and_respects_rate():
    path, meta = generate_profile_candidate(
        'J-Profile', kop_md=100.0, build_rate_deg_30m=2.0,
        hold_inc_deg=45.0, hold_azi_deg=20.0, target_tvd=700.0,
        target_north=0.0, target_east=500.0, station_interval=30.0,
        max_md=1800.0, truncate_at_target=False,
        azimuth_turn_rate_deg_30m=1.5)
    post_kop = path[path['MD'] >= 100.0]
    assert post_kop['Azi'].nunique() > 1
    # Azi wraps at 360; compare unwrapped differences per 30 m MD.
    import numpy as np
    azi = np.unwrap(np.radians(post_kop['Azi'].to_numpy()))
    rate = np.abs(np.degrees(np.diff(azi)) / np.diff(post_kop['MD'].to_numpy()) * 30.0)
    assert np.max(rate, initial=0.0) <= 1.5 + 1e-6
    assert meta['azimuth_turn_rate_deg_30m'] == 1.5
