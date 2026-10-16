import numpy as np

from core.general_optimizer import optimize_general_trajectory


def _base(**overrides):
    args = dict(
        targets=[{'name': 'Target-A', 'tvd_m': 900.0, 'north_m': 0.0, 'east_m': 900.0,
                  'tolerance_m': 30.48}],
        max_md_m=3000.0,
        max_inclination_deg=70.0,
        max_dls_deg_30m=3.0,
        max_build_rate_deg_30m=3.0,
        max_turn_rate_deg_30m=3.0,
        station_interval_m=30.0,
        maxiter=45,
        control_points=5,
    )
    args.update(overrides)
    return args


def test_general_optimizer_generates_variable_direction_path_and_reports_constraints():
    path, meta = optimize_general_trajectory(**_base())
    assert len(path) >= 25
    assert {'MD', 'Inc', 'Azi', 'Northing', 'Easting', 'TVD', 'DLS'}.issubset(path.columns)
    assert meta['planner'].startswith('General control-point')
    # A nearby, shallow, unobstructed target is an easy case: the optimizer MUST find a validated plan.
    # (This test used to accept either outcome, so it could not detect a broken optimizer.)
    assert meta['optimization_status'] == 'FEASIBLE' and meta['status'] == 'PASS'
    assert meta['validation_status'] == 'PASS'
    assert meta['max_inclination_deg'] <= 70.0 + 1e-3
    assert meta['max_dls_deg_30m'] <= 3.0 + 1e-3
    assert meta['target_miss_distance_m'] <= 1e-3
    assert abs(meta['target_vertical_error_m']) <= 30.48
    assert abs(float(path.iloc[-1]['MD']) - meta['target_intercept_md_m']) < 1e-3


def test_general_optimizer_marks_missing_offset_survey_for_review():
    offset = {'name': 'Offset-without-survey', 'surface_easting_m': 100.0,
              'surface_northing_m': 100.0, 'surveys': [{'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0}]}
    _, meta = optimize_general_trajectory(**_base(offsets=[offset], maxiter=5))
    assert meta['status'] == 'REVIEW'
    assert 'anti_collision_review_required' in meta['constraint_violations']
    assert meta['collision_validation'][0]['status'] == 'NOT CHECKED'


def test_general_optimizer_accepts_ordered_target_sequence_input():
    targets = [
        {'name': 'Shallow', 'tvd_m': 450.0, 'north_m': 0.0, 'east_m': 450.0, 'tolerance_m': 45.0},
        {'name': 'Final', 'tvd_m': 900.0, 'north_m': 0.0, 'east_m': 900.0, 'tolerance_m': 45.0},
    ]
    _, meta = optimize_general_trajectory(**_base(targets=targets, maxiter=5))
    assert meta['required_target_count'] == 2
    assert [x['name'] for x in meta['target_sequence_results']] == ['Shallow', 'Final']


def test_inclined_target_plane_uses_dip_and_dip_direction():
    from core.general_optimizer import _plane_residual
    target = {'north_m': 0.0, 'east_m': 0.0, 'tvd_m': 1000.0,
              'dip_deg': 30.0, 'dip_direction_deg': 0.0}
    expected_tvd = 1000.0 + np.tan(np.radians(30.0)) * 100.0
    assert abs(_plane_residual(100.0, 0.0, expected_tvd, target)) < 1e-8
    # Moving 100 m east is perpendicular to a north-directed dip direction.
    assert abs(_plane_residual(0.0, 100.0, 1000.0, target)) < 1e-8


def test_plane_intersection_angle_and_optional_approach_constraints():
    import pandas as pd
    from core.general_optimizer import _approach_metrics
    vertical = pd.DataFrame({'MD':[0.0, 100.0], 'Inc':[0.0, 0.0], 'Azi':[0.0, 0.0]})
    target = {'north_m':0.0, 'east_m':0.0, 'tvd_m':100.0, 'dip_deg':0.0,
              'dip_direction_deg':0.0, 'intersection_angle_enabled':True,
              'min_intersection_angle_deg':80.0, 'max_intersection_angle_deg':90.0}
    result = _approach_metrics(vertical, 100.0, target)
    assert abs(result['plane_intersection_angle_deg'] - 90.0) < 1e-8
    assert result['approach_constraints_pass'] is True
