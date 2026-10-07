import pandas as pd
from core.project import new_project, project_from_json
from core.geometry import target_contains, target_boundary
from core.trajectory import build_constant_build_hold
from engineering.casing import casing_geometry_checks, casing_design_checks
from engineering.anti_collision import clearance_report


def test_target_geometries():
    assert target_contains({'type':'Circular','north_m':0,'east_m':0,'radius_m':10}, 5, 5)
    assert target_contains({'type':'Elliptical','north_m':0,'east_m':0,'semi_major_m':20,'semi_minor_m':10,'orientation_deg':0}, 10, 0)
    n,e=target_boundary({'type':'Rectangular','north_m':0,'east_m':0,'length_m':20,'width_m':10})
    assert len(n)==5 and len(e)==5


def test_project_migration_to_v4():
    p=project_from_json({'project_name':'Old','well_name':'W-01','schema_version':'2.0'})
    assert p['schema_version']=='4.0'
    assert 'casing_program' in p and 'reference_data' in p


def test_planner_returns_candidate():
    out, meta = build_constant_build_hold(1000, 3, 60, 90, 2500, 0, 1200)
    assert len(out)>1
    assert 'lateral_error_m' in meta


def test_casing_checks():
    rows=casing_geometry_checks([{'string_no':1,'hole_size_in':12.25,'casing_od_in':9.625,'shoe_md_m':2000}])
    assert rows[0]['geometry']=='PASS'
    r=casing_design_checks(9.625,47,80000,2000,10,.5,.65)
    assert r['burst_capacity_psi']>0


def test_anti_collision_same_well_is_zero():
    main=pd.DataFrame([{'MD':0,'Easting':0,'Northing':0,'TVD':0},{'MD':1000,'Easting':100,'Northing':0,'TVD':900}])
    off={'name':'OW-01','surveys':[{'MD':0,'Easting':0,'Northing':0,'TVD':0},{'MD':1000,'Easting':100,'Northing':0,'TVD':900}]}
    rep=clearance_report(main,[off],1,1)
    assert not rep.empty and rep.iloc[0]['separation_m'] < 1e-8


def test_grid_convergence_is_not_hardcoded():
    from models.geodesy import grid_convergence_deg
    assert abs(grid_convergence_deg(9.0466, 9.0, 'EPSG:32632')) < 1e-9
    assert abs(grid_convergence_deg(9.0466, 10.0, 'EPSG:32632')) > 0.1


def test_offset_surface_shift_in_anticollision():
    import pandas as pd
    from engineering.anti_collision import clearance_report
    main=pd.DataFrame([{'MD':0,'Easting':0,'Northing':0,'TVD':0},{'MD':1000,'Easting':100,'Northing':0,'TVD':900}])
    off={'name':'OW-01','surface_easting_m':100,'surface_northing_m':0,'surveys':[{'MD':0,'Easting':0,'Northing':0,'TVD':0},{'MD':1000,'Easting':100,'Northing':0,'TVD':900}]}
    rep=clearance_report(main,[off],1,1)
    assert not rep.empty and rep.iloc[0]['separation_m'] > 50
