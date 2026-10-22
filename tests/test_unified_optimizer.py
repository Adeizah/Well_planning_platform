import inspect
import pandas as pd

from core.general_optimizer import optimize_general_trajectory
from core.validation import validate_trajectory


def test_validator_uses_single_dls_limit_and_reports_components_diagnostically():
    # A 10 degree build followed by a 10 degree drop over 30 m intervals.
    survey = pd.DataFrame({'MD': [0.0, 30.0, 60.0], 'Inc': [0.0, 10.0, 0.0], 'Azi': [0.0, 0.0, 0.0]})
    result = validate_trajectory(
        survey,
        targets=[],
        constraints={
            'max_inclination_deg': 70.0,
            'max_dls_deg_30m': 15.0,
            'max_build_rate_deg_30m': 12.0,
            'max_drop_rate_deg_30m': 5.0,
            'max_turn_rate_deg_30m': 15.0,
        },
        check_anti_collision=False,
    )
    checks = {c['check']: c for c in result['checks']}
    assert checks['maximum_DLS']['status'] == 'PASS'
    assert 'maximum_build_rate' not in checks and 'maximum_drop_rate' not in checks
    assert result['metrics']['max_build_rate_deg_30m'] > 0
    assert result['metrics']['max_drop_rate_deg_30m'] > 0


def test_general_optimizer_exposes_distinct_drop_and_kop_constraints():
    params = inspect.signature(optimize_general_trajectory).parameters
    assert 'max_drop_rate_deg_30m' in params
    assert 'min_kop_md_m' in params
    assert 'max_kop_md_m' in params
    assert 'time_budget_s' in params


def test_unified_optimizer_ui_has_single_mode_and_global_effort_presets():
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / 'app.py'
    text = app.read_text()
    assert "planning_mode='Trajectory Optimizer'" in text
    assert "['Fast','Balanced','Thorough']" in text
    assert "['Automatic','Fixed MD','Within tolerance']" in text
    assert "max_drop_rate_deg_30m=dls_100ft_to_30m(max_drop_ft)" not in text
    assert "Maximum DLS (°/100 ft)" in text
    assert "Maximum build rate (°/100 ft)" not in text
    assert "Maximum drop rate (°/100 ft)" not in text
    assert "min_kop_md_m=min_kop_m, max_kop_md_m=max_kop_m" in text


def test_search_explores_shortlist_and_validates_candidates_individually():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'core' / 'general_optimizer.py').read_text()
    assert 'if n_feasible >= 2' not in source
    assert 'validated_candidates.append' in source
    assert 'for _, ev_cand, x_cand, res_cand in sorted(validated_candidates' in source
    assert "'stage1_summary'" in source
    assert "'stage2_summary'" in source


def test_section_optimizer_uses_distinct_drop_bound():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'core' / 'section_optimizer.py').read_text()
    assert 'mdls = float(limits["max_dls_deg_30m"])' in source
    assert 'mb = md = mt = mdls' in source


def test_planner_quantizes_accepted_angles_before_revalidation_and_rebuilds_geometry():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text()
    inc_round = "out['Inc']=pd.to_numeric(out['Inc'],errors='raise').round(2)"
    azi_round = "out['Azi']=(pd.to_numeric(out['Azi'],errors='raise').round(2) % 360.0).round(2)"
    rebuild = "out=minimum_curvature(out[['MD','Inc','Azi']])"
    validator = "_val=validate_trajectory(out[['MD','Inc','Azi']]"
    assert inc_round in source
    assert azi_round in source
    assert rebuild in source
    assert source.index(inc_round) < source.index(validator)
    assert source.index(azi_round) < source.index(validator)
    assert source.index(rebuild) < source.index(validator)
    assert "meta['trajectory_angle_precision_deg']=2" in source
