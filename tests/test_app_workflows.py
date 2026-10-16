"""Executes app.py page code offline (see tests/app_harness.py for what this does and does not prove)."""
import copy, json, os, warnings

from app_harness import run_app
from core.project import new_project, project_from_json

warnings.filterwarnings('ignore', category=DeprecationWarning)
NAV = ['Dashboard', 'Project & Reference', 'Well Architecture', 'Targets', 'Offsets', 'Survey Manager', 'Trajectory Planner', 'Geomagnetics',
       'Geodesy', 'Anti-Collision', 'Casing Design', 'Hydraulics & ECD', 'PP / FG & Mud Window', 'Torque & Drag', 'Cementing', 'Well Control',
       'Visualization', 'QA/QC', 'Reports', 'About']
MEASURED = [{'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0}, {'MD': 300.0, 'Inc': 2.0, 'Azi': 10.0}, {'MD': 600.0, 'Inc': 3.0, 'Azi': 12.0}]


def _project():
    p = new_project(); p.update(crs='EPSG:32632', surface_easting_m=500000.0, surface_northing_m=5000000.0, kb_m=25.0, surveys=copy.deepcopy(MEASURED))
    p['targets'] = [{'name': 'T1', 'type': 'Circular', 'north_m': 5000500.0, 'east_m': 500300.0, 'tvdss_m': 25.0 - 1500.0, 'radius_m': 30.0, 'tolerance_m': 30.48}]
    return p


def test_every_page_executes_for_new_and_example_projects():
    example = project_from_json(json.load(open(os.path.join(os.path.dirname(__file__), '..', 'data', 'example_project.json'))))
    for proj in (new_project(), example):
        for page in NAV:
            fake, err = run_app(page, copy.deepcopy(proj))
            assert err is None, (page, getattr(fake, 'traceback', ''))


def test_target_can_be_added_and_edited_and_editing_marks_the_plan_for_review():
    p = _project(); p['targets'] = []
    fake, err = run_app('Targets', p, overrides={'Target name': 'T-new'}, clicks=['Add target'])
    assert err is None and [t['name'] for t in fake.session_state['project']['targets']] == ['T-new']
    p = _project()
    fake, err = run_app('Targets', p, overrides={'edit_name_0': 'T1-renamed', 'edit_tol_0': 60.0}, clicks=['edit_save_0'])
    t = fake.session_state['project']['targets'][0]
    assert err is None and t['name'] == 'T1-renamed' and abs(t['tolerance_m'] - 60.0 * 0.3048) < 1e-6


def test_failed_manual_candidate_never_overwrites_the_measured_survey():
    fake, err = run_app('Trajectory Planner', _project(), overrides={'Planning mode': 'Manual profile', 'Well trajectory shape': 'J-Profile', 'Peak/hold inclination (°)': 20.0},
                        clicks=['Generate trajectory for selected shape'])
    pr = fake.session_state['project']; res = pr['planned_trajectory_metadata']['planner_result']
    assert err is None and res['status'] == 'REVIEW' and res['validation_status'] == 'REVIEW'
    assert pr['surveys'] == MEASURED and len(pr['planned_surveys']) > 3


def test_validated_general_plan_becomes_active_and_measured_survey_is_backed_up():
    fake, err = run_app('Trajectory Planner', _project(), overrides={'Planning mode': 'General trajectory optimizer (experimental)', 'general_time_budget': 60, 'general_max_iter': 40},
                        clicks=['Generate trajectory for selected shape'])
    pr = fake.session_state['project']; res = pr['planned_trajectory_metadata']['planner_result']
    assert err is None and res['status'] == 'PASS' and res['validation_status'] == 'PASS'
    assert len(pr['surveys']) > 3 and pr['survey_backup']['surveys'] == MEASURED
    # later edits to a dependency flag the saved plan on the very next run
    changed = copy.deepcopy(pr); changed['targets'][0]['east_m'] += 50.0
    fake2, err2 = run_app('Dashboard', changed)
    b = fake2.session_state['project']['planned_trajectory_metadata']
    assert err2 is None and b['planner_result']['status'] == 'REVIEW' and any("'T1' was edited" in r for r in b['stale_reasons'])
    for page in ('Visualization', 'QA/QC', 'Reports', 'Anti-Collision'):
        _, e = run_app(page, copy.deepcopy(pr)); assert e is None, page
