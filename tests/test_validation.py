"""Independent validation, feasibility proofs, dependency tracking and optimizer acceptance."""
import copy

import numpy as np
import pandas as pd

from core.dependencies import dependency_snapshot, stale_dependencies, refresh_plan_staleness, attach_snapshot
from core.feasibility import reachability_screen, max_horizontal_reach
from core.general_optimizer import optimize_general_trajectory
from core.survey_qc import survey_quality_report
from core.trajectory import minimum_curvature
from core.validation import (validate_trajectory, search_outcome, survey_hash, to_jsonable,
                             STATUS_PASS, STATUS_REVIEW, STATUS_NO_FEASIBLE)
from core.visual import clip_failed_candidate_for_display, display_path

LIMITS = {'max_inclination_deg': 70.0, 'max_dls_deg_30m': 3.0, 'max_build_rate_deg_30m': 3.0, 'max_turn_rate_deg_30m': 3.0}


def T(name, tvd, n, e, **kw):
    return {'name': name, 'tvd_m': tvd, 'north_m': n, 'east_m': e, 'tolerance_m': 30.48, **kw}


def _j_profile(end_inc=45.0, build_md=450.0, end_md=1800.0, azi=90.0, step=30.0):
    """Simple J: vertical to 300 m, build to end_inc, hold. Returns raw MD/Inc/Azi."""
    md = np.unique(np.concatenate([np.arange(0, end_md, step), [end_md]]))
    inc = np.interp(md, [0, 300.0, 300.0 + build_md, end_md], [0, 0, end_inc, end_inc])
    return pd.DataFrame({'MD': md, 'Inc': inc, 'Azi': azi})


def _target_at_end(raw, tol=30.48, **kw):
    p = minimum_curvature(raw)
    return T('T', float(p.TVD.iloc[-1]), float(p.Northing.iloc[-1]), float(p.Easting.iloc[-1]), tolerance_m=tol, **kw)


# ---------------------------------------------------------------- the validator
def test_validator_passes_a_good_plan_and_reports_checks():
    raw = _j_profile(); v = validate_trajectory(raw, targets=[_target_at_end(raw)], constraints=LIMITS)
    assert v['status'] == STATUS_PASS, v['violations']
    names = {c['check'] for c in v['checks']}
    assert {'survey_integrity', 'integration_cross_check', 'maximum_DLS', 'maximum_inclination', 'terminates_at_final_target'} <= names
    assert v['metrics']['max_dls_deg_30m'] <= 3.0 + 1e-6


def test_validator_rejects_edited_stored_positions():
    raw = _j_profile(); p = minimum_curvature(raw); p.loc[10, 'TVD'] += 5.0
    v = validate_trajectory(p, targets=[_target_at_end(raw)], constraints=LIMITS)
    assert v['status'] == STATUS_REVIEW and 'stored_positions_match_rebuilt' in v['violations']


def test_validator_flags_dls_and_inclination_violations_without_component_rate_limits():
    raw = _j_profile(end_inc=60.0, build_md=150.0)                  # 60 deg in 150 m = 12 deg/30 m
    v = validate_trajectory(raw, targets=[_target_at_end(raw)], constraints={**LIMITS, 'max_inclination_deg': 50.0})
    assert {'maximum_DLS', 'maximum_inclination'} <= set(v['violations'])
    assert 'maximum_build_rate' not in v['violations']


def test_validator_flags_missed_target_and_wrong_order():
    raw = _j_profile(); far = T('Far', 1500.0, 0.0, 2500.0)
    assert 'target_sequence' in validate_trajectory(raw, targets=[far], constraints=LIMITS)['violations']
    p = minimum_curvature(raw); end = (float(p.TVD.iloc[-1]), float(p.Easting.iloc[-1]))
    mid = T('Mid', float(p.TVD.iloc[30]), float(p.Northing.iloc[30]), float(p.Easting.iloc[30]))
    fin = T('Fin', end[0], 0.0, end[1])
    assert validate_trajectory(raw, targets=[mid, fin], constraints=LIMITS)['status'] == STATUS_PASS
    assert validate_trajectory(raw, targets=[fin, mid], constraints=LIMITS)['status'] == STATUS_REVIEW


def test_validator_requires_plan_to_end_at_the_final_target():
    raw = _j_profile(end_md=1800.0); p = minimum_curvature(raw)
    t = T('T', float(p.TVD.iloc[40]), float(p.Northing.iloc[40]), float(p.Easting.iloc[40]))   # hit mid-way, plan keeps going
    v = validate_trajectory(raw, targets=[t], constraints=LIMITS)
    assert v['status'] == STATUS_REVIEW
    assert validate_trajectory(raw, targets=[t], constraints=LIMITS, require_final_at_target=False)['status'] == STATUS_PASS


def test_validator_finds_interceptions_between_stations():
    """Stations 150 m apart: the target lies between two stations and is only found on the arc."""
    raw = _j_profile(step=150.0, end_md=1800.0); p = minimum_curvature(raw)
    from core.trajectory import interpolate_path
    q = interpolate_path(p, [975.0]).iloc[0]
    mid = T('Between', float(q.TVD), float(q.Northing), float(q.Easting), tolerance_m=5.0)
    fin = _target_at_end(raw)
    v = validate_trajectory(raw, targets=[mid, fin], constraints=LIMITS, max_station_spacing_m=200.0)
    assert v['target_results'][0]['within_tolerance'] and abs(v['target_results'][0]['intercept_md_m'] - 975.0) < 2.0


def test_validator_marks_coarse_stations_and_bad_surveys_for_review():
    raw = _j_profile(step=250.0)
    assert 'station_spacing_resolution' in validate_trajectory(raw, constraints=LIMITS)['violations']
    bad = pd.DataFrame({'MD': [0, 100, 100.0], 'Inc': [0, 5, 6.0], 'Azi': 0.0})
    assert validate_trajectory(bad, constraints=LIMITS)['status'] == STATUS_REVIEW
    assert validate_trajectory(pd.DataFrame({'MD': [0, 100.0], 'Inc': [0, np.nan], 'Azi': 0.0}))['status'] == STATUS_REVIEW


def test_validator_approach_constraints_and_tie_in():
    raw = _j_profile(azi=90.0); t = _target_at_end(raw, approach_azimuth_enabled=True, approach_azimuth_deg=270.0, approach_azimuth_tolerance_deg=10.0)
    assert 'target_approach_constraints' in validate_trajectory(raw, targets=[t], constraints=LIMITS)['violations']
    shifted = raw.assign(MD=raw.MD + 100.0)
    assert 'survey_integrity' in validate_trajectory(shifted, constraints=LIMITS)['violations']


def test_validator_collision_check_uses_the_corrected_engine():
    raw = _j_profile(); t = _target_at_end(raw)
    close = {'name': 'Close', 'surface_easting_m': 0.0, 'surface_northing_m': 8.0, 'surveys': raw.to_dict('records')}
    v = validate_trajectory(raw, targets=[t], constraints=LIMITS, offsets=[close])
    assert v['status'] == STATUS_REVIEW and 'anti_collision_review_required' in v['violations']
    far = {'name': 'Far', 'surface_easting_m': 0.0, 'surface_northing_m': 400.0, 'surveys': raw.to_dict('records')}
    assert validate_trajectory(raw, targets=[t], constraints=LIMITS, offsets=[far])['status'] == STATUS_PASS
    surface_only = {'name': 'S', 'surface_easting_m': 100.0, 'surface_northing_m': 0.0, 'surveys': [{'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0}]}
    assert validate_trajectory(raw, targets=[t], constraints=LIMITS, offsets=[surface_only])['status'] == STATUS_REVIEW


def test_validator_notes_unrecorded_offset_datum_and_applies_known_kb():
    raw = _j_profile(); t = _target_at_end(raw)
    far = {'name': 'Far', 'surface_easting_m': 0.0, 'surface_northing_m': 400.0, 'surveys': raw.to_dict('records')}
    v = validate_trajectory(raw, targets=[t], constraints=LIMITS, offsets=[far], kb_m=25.0)
    note = [c for c in v['checks'] if c['check'] == 'depth_datum_consistency']
    assert note and 'no KB elevation recorded' in note[0]['detail']
    far2 = dict(far, kb_m=45.0)
    v2 = validate_trajectory(raw, targets=[t], constraints=LIMITS, offsets=[far2], kb_m=25.0)
    assert 'shifted' in [c for c in v2['checks'] if c['check'] == 'depth_datum_consistency'][0]['detail']


def test_search_outcome_separates_failed_search_from_proof():
    ok = {'status': STATUS_PASS}; bad = {'status': STATUS_REVIEW}
    assert search_outcome(ok)['optimization_status'] == 'FEASIBLE'
    assert search_outcome(bad)['optimization_status'] == 'NO_FEASIBLE_CANDIDATE_FOUND' and search_outcome(bad)['proof'] is None
    assert search_outcome(bad, proven_infeasible=True)['optimization_status'] == 'INFEASIBLE_PROVEN'
    assert STATUS_NO_FEASIBLE == 'NO FEASIBLE CANDIDATE FOUND'


def test_survey_hash_and_jsonable():
    raw = _j_profile(); assert survey_hash(raw) == survey_hash(raw.copy()) and survey_hash(raw) != survey_hash(raw.assign(Inc=raw.Inc + 0.01))
    j = to_jsonable({'a': np.float64(1.5), 'b': np.bool_(True), 'c': [np.int64(2), float('nan')]})
    assert j == {'a': 1.5, 'b': True, 'c': [2, None]}


# ---------------------------------------------------------------- feasibility proofs
def test_reachability_screen_proves_only_what_it_can_prove():
    kw = dict(max_inclination_deg=70, max_dls_deg_30m=3, max_build_rate_deg_30m=3)
    assert reachability_screen([T('A', 400, 0, 3000)], **kw)['proven_infeasible']                      # too far out for its depth
    assert reachability_screen([T('B', 2200, 600, 1200), T('A', 1200, 600, 0)], **kw)['proven_infeasible']   # reversed depth order
    assert reachability_screen([T('A', 2000, 0, 1200)], max_md_m=1500.0, **kw)['proven_infeasible']    # MD limit shallower than target
    assert not reachability_screen([T('A', 2500, 0, 2800)], **kw)['proven_infeasible']
    assert not reachability_screen([T('A', 1200, 600, 0), T('B', 2200, 600, 1200)], **kw)['proven_infeasible']
    assert max_horizontal_reach(2500, 70, 3) > 2800


# ---------------------------------------------------------------- dependency tracking / display
def _project():
    return {'targets': [T('T1', 1500, 100, 200)], 'offsets': [], 'surface_easting_m': 1.0, 'surface_northing_m': 2.0, 'kb_m': 25.0,
            'design_constraints': {'max_dls_deg_30m': 3.0}, 'survey_metadata': {'survey_error_parameters': {}},
            'planned_surveys': _j_profile().to_dict('records'),
            'planned_trajectory_metadata': {'planner_result': {'status': 'PASS', 'optimization_status': 'FEASIBLE', 'constraint_violations': []}}}


def test_dependency_changes_downgrade_the_plan_to_review():
    p = _project(); attach_snapshot(p, p['planned_trajectory_metadata'], ['T1'])
    assert refresh_plan_staleness(p) == [] and p['planned_trajectory_metadata']['planner_result']['status'] == 'PASS'
    q = copy.deepcopy(p); q['targets'][0]['east_m'] += 10
    assert refresh_plan_staleness(q) and q['planned_trajectory_metadata']['planner_result']['status'] == 'REVIEW'
    assert 'dependency_changed_after_planning' in q['planned_trajectory_metadata']['planner_result']['constraint_violations']
    for mutate in (lambda x: x['targets'].clear(), lambda x: x.update(kb_m=30.0), lambda x: x['design_constraints'].update(max_dls_deg_30m=4.0),
                   lambda x: x['offsets'].append({'name': 'O', 'surveys': []}), lambda x: x['planned_surveys'][5].update(Inc=9.0)):
        r = copy.deepcopy(p); mutate(r); assert refresh_plan_staleness(r), mutate


def test_failed_candidates_are_clipped_for_display_only():
    raw = pd.DataFrame({'MD': np.arange(0, 3001, 30.0), 'Inc': 30.0, 'Azi': 90.0}); raw.loc[0, 'Inc'] = 0.0
    path = minimum_curvature(raw); original_end = float(path.MD.iloc[-1])
    clipped = clip_failed_candidate_for_display(path, 1000.0)
    assert abs(float(clipped.MD.iloc[-1]) - 1030.48) < 1e-6 and float(path.MD.iloc[-1]) == original_end
    assert display_path(path, {'status': 'PASS'}) is path
    assert abs(float(display_path(path, {'status': 'REVIEW', 'display_clip_md_m': 1030.48}).MD.iloc[-1]) - 1030.48) < 1e-6


def test_survey_quality_report():
    ok = survey_quality_report(pd.DataFrame({'MD': [0, 100, 200.0], 'Inc': [0, 2, 3.0], 'Azi': [0, 10, 12.0]}), 'm')
    assert [i['severity'] for i in ok] == ['INFO']
    assert any(i['check'] == 'tie_in' for i in survey_quality_report(pd.DataFrame({'MD': [300, 600.0], 'Inc': 0.0, 'Azi': 0.0}), 'ft'))
    assert any(i['severity'] == 'ERROR' for i in survey_quality_report(pd.DataFrame({'MD': [0, 100, 100.0], 'Inc': [0, 1, 2.0], 'Azi': 0.0})))
    assert any(i['check'] == 'dls_spike' for i in survey_quality_report(pd.DataFrame({'MD': [0, 10.0, 20.0], 'Inc': [0, 40, 0.0], 'Azi': 0.0}), 'm'))


# ---------------------------------------------------------------- optimizer end to end (each solve is seconds-long)
def _opt(targets, **kw):
    args = dict(targets=targets, max_md_m=6000.0, max_inclination_deg=70.0, max_dls_deg_30m=3.0, max_build_rate_deg_30m=3.0,
                max_turn_rate_deg_30m=3.0, maxiter=40, time_budget_s=60.0)
    args.update(kw); return optimize_general_trajectory(**args)


def _independent_recheck(path, targets, offsets=None, **kw):
    """Re-validate the returned path from scratch - exactly what a reviewer would do."""
    return validate_trajectory(path[['MD', 'Inc', 'Azi']], targets=targets, constraints=LIMITS, offsets=offsets or [], **kw)


def test_optimizer_pass_is_confirmed_by_independent_validation():
    targets = [T('A', 1500, 0, 900)]
    path, meta = _opt(targets)
    assert meta['status'] == 'PASS' and meta['result_class'] == 'PASS' and meta['validation_status'] == 'PASS'
    again = _independent_recheck(path, targets)
    assert again['status'] == STATUS_PASS and again['target_results'][-1]['miss_distance_m'] <= 1e-3
    assert abs(path.MD.iloc[-1] - meta['target_intercept_md_m']) < 1e-3


def test_optimizer_handles_multiple_ordered_targets_and_proves_reversed_order_infeasible():
    a, b = T('A', 1200, 600, 0), T('B', 2200, 600, 1200)
    path, meta = _opt([a, b])
    assert meta['status'] == 'PASS' and [r['name'] for r in meta['target_sequence_results']] == ['A', 'B']
    assert meta['target_sequence_results'][0]['intercept_md_m'] < meta['target_sequence_results'][1]['intercept_md_m']
    assert _independent_recheck(path, [a, b])['status'] == STATUS_PASS
    _, bad = _opt([b, a])
    assert bad['status'] == 'REVIEW' and bad['optimization_status'] == 'INFEASIBLE_PROVEN' and bad['proof_of_infeasibility']['reasons']


def test_optimizer_inclined_target_with_approach_constraint():
    t = T('P', 2000, 0, 1200, dip_deg=25.0, dip_direction_deg=90.0)
    path, meta = _opt([t], max_md_m=5000.0)
    assert meta['status'] == 'PASS' and _independent_recheck(path, [t])['status'] == STATUS_PASS


def test_optimizer_avoids_an_offset_well_and_the_result_survives_independent_clearance_check():
    off = {'name': 'OW-1', 'surface_easting_m': 600.0, 'surface_northing_m': 0.0, 'surveys': [{'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0}, {'MD': 3000.0, 'Inc': 0.0, 'Azi': 0.0}]}
    t = T('A', 2000, 0, 1200)
    path, meta = _opt([t], max_md_m=5000.0, offsets=[off], time_budget_s=90.0)
    assert meta['status'] == 'PASS', meta['constraint_violations']
    again = _independent_recheck(path, [t], [off])
    assert again['status'] == STATUS_PASS and again['collision'][0]['separation_factor'] >= 2.0


def test_unreachable_target_is_proven_infeasible_not_just_failed():
    _, meta = _opt([T('A', 400, 0, 3000)], max_md_m=5000.0)
    assert meta['status'] == 'REVIEW' and meta['optimization_status'] == 'INFEASIBLE_PROVEN' and meta['result_class'] == 'REVIEW'


def test_exhausted_search_is_reported_as_no_feasible_candidate_not_as_proof():
    _, meta = _opt([T('A', 1500, 0, 900)], time_budget_s=0.0)          # no time to search at all
    assert meta['status'] == 'REVIEW' and meta['optimization_status'] == 'NO_FEASIBLE_CANDIDATE_FOUND'
    assert meta['result_class'] == 'NO FEASIBLE CANDIDATE FOUND' and meta['proof_of_infeasibility'] is None
    assert meta['display_clip_md_m'] is not None             # failed candidates carry a display window (~100 ft past approach)


def test_optimizer_respects_kop_and_max_md_constraints():
    path, meta = _opt([T('A', 1500, 0, 900)], min_kop_md_m=400.0)
    assert meta['status'] == 'PASS' and _independent_recheck(path, [T('A', 1500, 0, 900)])['metrics']['kop_md_m'] >= 400.0 - 1.0


def test_failed_multi_target_candidate_is_not_clipped_before_later_targets():
    """Keep the full failed candidate visible so later-target attempts remain diagnosable."""
    import pandas as pd
    from core.visual import display_path
    path = pd.DataFrame({
        'MD': [0.0, 100.0, 200.0, 300.0],
        'Inc': [0.0, 10.0, 20.0, 30.0],
        'Azi': [0.0, 10.0, 20.0, 30.0],
        'Northing': [0.0, 1.0, 2.0, 3.0],
        'Easting': [0.0, 1.0, 2.0, 3.0],
        'TVD': [0.0, 99.0, 196.0, 290.0],
    })
    result = {'status': 'REVIEW', 'required_target_count': 2,
              'target_sequence_feasible': False, 'display_clip_md_m': 120.0,
              'target_intercept_md_m': 100.0}
    shown = display_path(path, result)
    assert float(shown.MD.iloc[-1]) == float(path.MD.iloc[-1])


def test_kop_estimator_uses_start_of_sustained_build_not_half_degree_crossing():
    from core.kop import estimate_kop_md
    md = np.arange(0.0, 1000.0 + 20.0, 20.0)
    inc = np.linspace(0.0, 2.0, len(md))
    assert estimate_kop_md(md, inc, build_rate_threshold_deg_30m=0.02, sustained_intervals=2) == 0.0


def test_kop_estimator_finds_delayed_build_onset():
    from core.kop import estimate_kop_md
    md = np.arange(0.0, 1000.0 + 20.0, 20.0)
    inc = np.zeros_like(md)
    inc[25:] = np.linspace(0.0, 20.0, len(md) - 25)
    assert estimate_kop_md(md, inc, build_rate_threshold_deg_30m=0.02, sustained_intervals=2) == 500.0


def test_validator_reports_geometric_kop_at_build_onset():
    raw = _j_profile(end_inc=45.0, build_md=450.0, end_md=1800.0, step=30.0)
    result = validate_trajectory(raw, constraints={**LIMITS, 'min_kop_md_m': 299.0, 'max_kop_md_m': 301.0})
    assert abs(result['metrics']['kop_md_m'] - 300.0) < 1e-6
    check = next(c for c in result['checks'] if c['check'] == 'KOP_restriction')
    assert check['status'] == STATUS_PASS
