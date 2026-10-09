import numpy as np
import pandas as pd

from models.survey_uncertainty import station_covariances, interpolate_covariance


def test_station_covariance_shapes_and_growth():
    df = pd.DataFrame([
        {'MD':0.0,'Inc':0.0,'Azi':0.0},
        {'MD':100.0,'Inc':10.0,'Azi':20.0},
        {'MD':200.0,'Inc':20.0,'Azi':30.0},
    ])
    out = station_covariances(df, sigma_md_ft=0.5, sigma_inc_deg=0.1, sigma_azi_deg=0.25)
    assert len(out) == 3
    assert out.iloc[0]['Cov_NN_m2'] > 0
    assert out.iloc[-1]['Cov_NN_m2'] >= 0
    c = interpolate_covariance(out, 150.0)
    assert c.shape == (3,3)
    assert np.allclose(c, c.T)
    assert np.linalg.eigvalsh(c).min() > -1e-10


def test_covariance_clearance_returns_directional_uncertainty():
    from engineering.anti_collision import clearance_report
    main = pd.DataFrame([
        {'MD':0.0,'Inc':0.0,'Azi':0.0},
        {'MD':1000.0,'Inc':30.0,'Azi':90.0},
        {'MD':2000.0,'Inc':45.0,'Azi':90.0},
    ])
    offsets = [{
        'name':'OW-01', 'surface_easting_m':100.0, 'surface_northing_m':0.0,
        'surveys':[
            {'MD':0.0,'Inc':0.0,'Azi':0.0},
            {'MD':1000.0,'Inc':30.0,'Azi':90.0},
            {'MD':2000.0,'Inc':45.0,'Azi':90.0},
        ]
    }]
    rep = clearance_report(main, offsets, survey_error_model={
        'sigma_md_ft':0.5, 'sigma_inc_deg':0.1, 'sigma_azi_deg':0.25,
        'sigma_inc_systematic_deg':0.1, 'sigma_azi_systematic_deg':0.25,
        'sigma_surface_ft':5.0})
    assert len(rep) == 1
    assert rep.iloc[0]['directional_uncertainty_m'] > 0
    assert np.isfinite(rep.iloc[0]['separation_factor'])


def test_vertical_trajectory_with_nonzero_angular_errors_has_nonzero_uncertainty():
    df = pd.DataFrame([
        {'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0},
        {'MD': 1000.0, 'Inc': 0.0, 'Azi': 0.0},
        {'MD': 2000.0, 'Inc': 0.0, 'Azi': 0.0},
    ])
    out = station_covariances(df, sigma_md_ft=0.0, sigma_inc_deg=0.05,
                              sigma_azi_deg=0.50, sigma_inc_systematic_deg=0.20,
                              sigma_azi_systematic_deg=1.00, sigma_surface_ft=0.0)
    assert out.iloc[-1]['Unc_major_1sigma_m'] > 0.0
    assert out.iloc[-1]['Unc_vertical_1sigma_m'] >= 0.0


def test_zero_surface_uncertainty_at_wellhead_is_review_not_clearance():
    from engineering.anti_collision import clearance_report
    main = pd.DataFrame([
        {'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0},
        {'MD': 1000.0, 'Inc': 0.0, 'Azi': 0.0},
    ])
    offsets = [{
        'name': 'OW-surface', 'surface_easting_m': 100.0, 'surface_northing_m': 0.0,
        'surveys': [
            {'MD': 0.0, 'Inc': 0.0, 'Azi': 0.0},
            {'MD': 1000.0, 'Inc': 0.0, 'Azi': 0.0},
        ]
    }]
    rep = clearance_report(main, offsets, survey_error_model={
        'sigma_md_ft': 0.0, 'sigma_inc_deg': 0.05, 'sigma_azi_deg': 0.5,
        'sigma_inc_systematic_deg': 0.2, 'sigma_azi_systematic_deg': 1.0,
        'sigma_surface_ft': 0.0,
    })
    assert rep.iloc[0]['status'] == 'REVIEW'
    assert 'wellhead' in rep.iloc[0]['note'].lower()
