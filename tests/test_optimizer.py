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
