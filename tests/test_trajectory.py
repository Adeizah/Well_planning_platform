
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
