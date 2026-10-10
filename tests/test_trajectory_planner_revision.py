import numpy as np

from core.trajectory import generate_profile_candidate


def test_j_profile_and_build_hold_are_same_geometry():
    common = dict(kop_md=300.0, build_rate_deg_30m=2.0, hold_inc_deg=40.0,
                  hold_azi_deg=120.0, target_tvd=900.0, target_north=400.0,
                  target_east=100.0, station_interval=30.0, max_md=1800.0,
                  truncate_at_target=False)
    j, _ = generate_profile_candidate('J-Profile', **common)
    bh, _ = generate_profile_candidate('Build & Hold', **common)
    assert len(j) == len(bh)
    assert np.allclose(j[['MD', 'Inc', 'Azi', 'TVD', 'Northing', 'Easting']],
                       bh[['MD', 'Inc', 'Azi', 'TVD', 'Northing', 'Easting']])


def test_s_profile_keeps_drop_section_when_full_path_requested():
    path, meta = generate_profile_candidate(
        'S-Profile', kop_md=300.0, build_rate_deg_30m=2.0,
        hold_inc_deg=40.0, hold_azi_deg=120.0, target_tvd=900.0,
        target_north=400.0, target_east=100.0, drop_rate_deg_30m=2.0,
        final_inc_deg=5.0, station_interval=30.0, max_md=1800.0,
        drop_start_md=1300.0, truncate_at_target=False)
    assert meta['target_intercept_found']
    assert path['MD'].iloc[-1] > meta['target_intercept_md_m']
    assert path['Inc'].iloc[-1] <= 5.01
    assert meta['section_end_md_m']['Drop start'] is not None
    assert meta['section_end_md_m']['Drop end'] is not None


def test_legacy_target_truncation_can_still_be_requested():
    common = dict(kop_md=300.0, build_rate_deg_30m=2.0, hold_inc_deg=40.0,
                  hold_azi_deg=120.0, target_tvd=900.0, target_north=400.0,
                  target_east=100.0, drop_rate_deg_30m=2.0, final_inc_deg=5.0,
                  station_interval=30.0, max_md=1800.0, drop_start_md=1300.0)
    full, _ = generate_profile_candidate('S-Profile', **common, truncate_at_target=False)
    truncated, _ = generate_profile_candidate('S-Profile', **common, truncate_at_target=True)
    assert len(full) > len(truncated)


def test_manual_profile_marks_target_miss_as_review():
    path, meta = generate_profile_candidate(
        'J-Profile', kop_md=300.0, build_rate_deg_30m=2.0,
        hold_inc_deg=57.0, hold_azi_deg=26.0, target_tvd=3745.0,
        target_north=1736.0, target_east=860.0, station_interval=30.0,
        max_md=7000.0, truncate_at_target=False)
    assert meta['target_intercept_found']
    assert meta['lateral_error_m'] > 30.48
    assert meta['status'] == 'REVIEW'
    assert meta['target_hit'] is False


def test_optimizer_can_find_a_target_constrained_j_profile():
    from core.optimizer import optimize_trajectory
    path, meta = optimize_trajectory(
        profile='J-Profile', target_tvd_m=900, target_north_m=0, target_east_m=900,
        kop_initial_m=200, build_rate_initial_deg_30m=2.5,
        peak_inc_initial_deg=45, azimuth_initial_deg=90,
        max_inclination_deg=65, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, station_interval_m=60,
        max_md_m=1800, maxiter=10, popsize=6, seed=17)
    assert meta['optimization_status'] == 'FEASIBLE'
    assert meta['target_lateral_error_m'] <= 30.48
    assert abs(meta['target_vertical_error_m']) <= 30.48
    assert meta['final_md_m'] <= 1800


def test_all_six_profile_generators_respect_depth_and_report_target_status():
    """Regression matrix: every advertised profile must return an auditable path."""
    profiles = ['Vertical', 'J-Profile', 'S-Profile', 'Horizontal', 'ERD', 'Custom']
    for profile in profiles:
        path, meta = generate_profile_candidate(
            profile, kop_md=200.0, build_rate_deg_30m=2.5,
            hold_inc_deg=90.0 if profile == 'Horizontal' else (80.0 if profile == 'ERD' else 45.0),
            hold_azi_deg=90.0, target_tvd=900.0, target_north=0.0,
            target_east=900.0, drop_rate_deg_30m=2.5, final_inc_deg=5.0,
            station_interval=60.0, max_md=3000.0, truncate_at_target=False)
        assert len(path) >= 2, profile
        assert path['MD'].is_monotonic_increasing, profile
        assert float(path['MD'].iloc[-1]) <= 3000.0 + 1e-8, profile
        assert 'target_hit' in meta and 'target_intercept_found' in meta, profile
        assert meta['status'] in {'PASS', 'REVIEW'}, profile
        assert meta['section_end_md_m']['Planned TD'] <= 3000.0 + 1e-8, profile


def test_all_six_optimizer_profiles_return_constraint_diagnostics():
    """Smoke-test every profile through the common optimizer/feasibility path."""
    from core.optimizer import optimize_trajectory
    profiles = ['Vertical', 'J-Profile', 'S-Profile', 'Horizontal', 'ERD', 'Custom']
    for profile in profiles:
        _, meta = optimize_trajectory(
            profile=profile, target_tvd_m=900.0, target_north_m=0.0,
            target_east_m=900.0, kop_initial_m=200.0,
            build_rate_initial_deg_30m=2.5, peak_inc_initial_deg=45.0,
            azimuth_initial_deg=90.0, max_inclination_deg=90.0,
            max_dls_deg_30m=3.0, max_build_rate_deg_30m=3.0,
            max_turn_rate_deg_30m=3.0, station_interval_m=120.0,
            max_md_m=3000.0, maxiter=1, popsize=4, seed=17)
        assert meta['optimization_status'] in {
            'FEASIBLE', 'REVIEW', 'NO_FEASIBLE_DIRECTIONAL_SOLUTION'
        }, profile
        assert 'constraint_violations' in meta, profile
        assert meta['final_md_m'] <= 3000.0 + 1e-8, profile
        assert meta['max_dls_deg_30m'] >= 0.0, profile
