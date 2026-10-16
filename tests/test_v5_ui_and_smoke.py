from pathlib import Path

import pandas as pd

from core.project import new_project, project_from_json
from core.reference import magnetic_to_grid, grid_to_magnetic
from models.geodesy import crs_info, grid_convergence_deg, normal_gravity
from engineering.hydraulics import hydraulic_screen, rheology_summary
from engineering.pressure import pressure_window
from engineering.cement import cement_screen
from engineering.torque_drag import torque_drag_screen
from engineering.well_control import well_control_screen


def test_v5_ui_contract_and_navigation():
    app = Path(__file__).parents[1] / "app.py"
    text = app.read_text()
    assert "Well Planning Platform" in text
    assert "Well Planning Platform v5.1" not in text
    assert "v5.1 • desktop engineering workspace" not in text
    for label in [
        "Dashboard", "Project & Reference", "Survey Manager", "Trajectory Planner",
        "Targets", "Offsets", "Well Architecture", "Geomagnetics", "Geodesy",
        "Anti-Collision", "Casing Design", "Hydraulics & ECD", "PP / FG & Mud Window",
        "Torque & Drag", "Cementing", "Well Control", "BHA & Drilling",
        "Visualization", "QA/QC", "Reports", "About",
    ]:
        assert f"'{label}'" in text


def test_v5_shared_model_roundtrip():
    p = new_project()
    p["project_name"] = "UI Regression"
    p["well_name"] = "W-05"
    q = project_from_json(p)
    assert q["project_name"] == "UI Regression"
    assert q["well_name"] == "W-05"
    assert q["schema_version"] == "4.0"  # UI release does not break the engineering schema.
    assert q["units"] == "Field"
    assert "site_pad" in q and "well_design" in q


def test_v5_engineering_smoke_chain():
    grid = magnetic_to_grid(100, 2, 0.5)
    assert abs(grid_to_magnetic(grid, 2, 0.5) - 100) < 1e-9
    assert "name" in crs_info("EPSG:4326")
    assert isinstance(grid_convergence_deg(4.8, 6.9, "EPSG:4326"), float)
    assert normal_gravity(4.8, 25) > 9.7

    h = hydraulic_screen(500, 8.5, 5.0, 10.0, 10000, 400, 20, 10)
    assert h["ecd_ppg"] > 0
    assert rheology_summary("Bingham Plastic", 20, 10, 500)["model"] == "bingham plastic"

    pw = pressure_window(10000, 10, 0.5, 0.65, 0)
    assert pw["status"] == "PASS"
    assert cement_screen(12.25, 9.625, 1000, 20, 1.18)["annular_volume_bbl"] > 0
    assert torque_drag_screen(4000, 0.25, 0.82, 19.5, 45, 2)["surface_torque_screen_ftlb"] >= 0
    assert well_control_screen(500, 10000, 10, 1500, 0.65)["kill_mud_weight_ppg"] > 0


def test_reference_requirements_and_conversion():
    from core.reference import reference_requirements, convert_to_project_reference
    assert reference_requirements('True North')['needs_declination'] is True
    assert reference_requirements('True North')['needs_convergence'] is False
    assert reference_requirements('Grid North')['needs_declination'] is True
    assert reference_requirements('Grid North')['needs_convergence'] is True
    assert abs(convert_to_project_reference(0, 'Magnetic North', 'True North', 5, 2) - 5) < 1e-9
    assert abs(convert_to_project_reference(0, 'Magnetic North', 'Grid North', 5, 2) - 3) < 1e-9


def test_field_unit_conversions():
    from core.units import M_TO_FT, FT_TO_M, dls_30m_to_100ft, dls_100ft_to_30m
    assert abs(1.0 * M_TO_FT - 3.280839895013123) < 1e-12
    assert abs(100.0 * FT_TO_M - 30.48) < 1e-12
    assert abs(dls_30m_to_100ft(3.0) - 3.048) < 1e-12
    assert abs(dls_100ft_to_30m(dls_30m_to_100ft(3.0)) - 3.0) < 1e-12
    # Compatibility aliases prevent older deployed app revisions from
    # failing at import time while the repository transitions to explicit
    # 30 m / 100 ft DLS naming.
    from core.units import dls_m_to_ft, dls_ft_to_m
    assert abs(dls_m_to_ft(3.0) - 3.048) < 1e-12
    assert abs(dls_ft_to_m(3.048) - 3.0) < 1e-12


def test_anti_collision_accepts_raw_offset_surveys_and_returns_pairwise_md():
    import pandas as pd
    from engineering.anti_collision import clearance_report
    main=pd.DataFrame([{'MD':0,'Inc':0,'Azi':0},{'MD':1000,'Inc':30,'Azi':90},{'MD':2000,'Inc':45,'Azi':90}])
    offsets=[{'name':'OW-01','surface_easting_m':100,'surface_northing_m':0,'surveys':[{'MD':0,'Inc':0,'Azi':0},{'MD':1000,'Inc':30,'Azi':90},{'MD':2000,'Inc':45,'Azi':90}]}]
    rep=clearance_report(main,offsets,1.0,1.0)
    assert len(rep)==1
    assert rep.iloc[0]['offset']=='OW-01'
    assert rep.iloc[0]['main_md_m'] >= 0
    assert rep.iloc[0]['offset_md_m'] >= 0
    assert rep.iloc[0]['separation_m'] > 0


def test_target_fit_hold_solver_respects_max_inclination():
    from core.trajectory import solve_build_hold_hold_inclination
    out, meta = solve_build_hold_hold_inclination(
        kop_md=1450.0,
        build_rate_deg_30m=3.0,
        max_hold_inc_deg=57.0,
        hold_azi_deg=26.36,
        target_tvd=3745.0,
        target_north=1739.9,
        target_east=860.0,
        station_interval=30.0,
    )
    assert len(out) > 2
    assert meta['hold_inclination_deg'] <= 57.0 + 1e-9
    assert meta['hold_inclination_deg'] > 0
    assert meta['final_md_m'] == out.iloc[-1]['MD']


def test_anti_collision_translates_main_and_offset_into_common_project_frame():
    import pandas as pd
    from engineering.anti_collision import clearance_report
    # Identical local trajectories, but offset wellhead is 100 m east of main wellhead.
    main=pd.DataFrame([{'MD':0,'Inc':0,'Azi':0},{'MD':1000,'Inc':0,'Azi':0},{'MD':2000,'Inc':0,'Azi':0}])
    offsets=[{'name':'OW-01','surface_easting_m':1100,'surface_northing_m':2000,'surveys':[{'MD':0,'Inc':0,'Azi':0},{'MD':1000,'Inc':0,'Azi':0},{'MD':2000,'Inc':0,'Azi':0}]}]
    rep=clearance_report(main,offsets,1.0,1.0,main_surface_easting_m=1000,main_surface_northing_m=2000)
    assert len(rep)==1
    assert abs(float(rep.iloc[0]['separation_m'])-100.0) < 1.0
