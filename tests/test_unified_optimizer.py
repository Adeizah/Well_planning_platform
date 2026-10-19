import inspect
import pandas as pd

from core.general_optimizer import optimize_general_trajectory
from core.validation import validate_trajectory


def test_validator_separates_build_and_drop_limits():
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
    assert checks['maximum_build_rate']['status'] == 'PASS'
    assert checks['maximum_drop_rate']['status'] == 'REVIEW'
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
    assert "max_drop_rate_deg_30m=dls_100ft_to_30m(max_drop_ft)" in text
    assert "min_kop_md_m=min_kop_m, max_kop_md_m=max_kop_m" in text
