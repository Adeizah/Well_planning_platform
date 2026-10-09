
import pandas as pd
from core.trajectory import minimum_curvature

def test_vertical_well():
    df = pd.DataFrame([
        {"MD":0,"Inc":0,"Azi":0},
        {"MD":1000,"Inc":0,"Azi":0}
    ])
    out = minimum_curvature(df)
    assert abs(out.iloc[-1]["TVD"] - 1000) < 1e-8
    assert abs(out.iloc[-1]["Northing"]) < 1e-8
    assert abs(out.iloc[-1]["Easting"]) < 1e-8

def test_build():
    df = pd.DataFrame([
        {"MD":0,"Inc":0,"Azi":0},
        {"MD":100,"Inc":10,"Azi":0}
    ])
    out = minimum_curvature(df)
    assert out.iloc[-1]["TVD"] > 95
    assert out.iloc[-1]["Northing"] > 5


def test_profile_shape_selection_changes_trajectory_geometry():
    from core.trajectory import generate_profile_candidate
    common = dict(kop_md=300.0, build_rate_deg_30m=3.0, hold_inc_deg=50.0,
                  hold_azi_deg=90.0, target_tvd=2500.0, target_north=0.0,
                  target_east=1000.0, station_interval=30.0, max_md=5000.0)
    j, jm = generate_profile_candidate('J-Profile', **common)
    s, sm = generate_profile_candidate('S-Profile', **common, drop_rate_deg_30m=3.0, final_inc_deg=0.0)
    assert len(j) > 2 and len(s) > 2
    assert not j['Inc'].equals(s['Inc'])
    assert jm['profile'] == 'J-Profile'
    assert sm['profile'] == 'S-Profile'
