import pytest
from core.optimizer import optimize_trajectory


def _base(**extra):
    args = dict(profile='J-Profile', target_tvd_m=900, target_north_m=0, target_east_m=900,
                kop_initial_m=200, build_rate_initial_deg_30m=2.5,
                peak_inc_initial_deg=45, azimuth_initial_deg=90,
                max_inclination_deg=65, max_dls_deg_30m=3,
                max_build_rate_deg_30m=3, max_turn_rate_deg_30m=3,
                station_interval_m=120, max_md_m=3000, maxiter=1, popsize=4)
    args.update(extra)
    return args


def test_target_sequence_requires_well_relative_coordinates():
    with pytest.raises(ValueError, match='Each sequence target requires'):
        optimize_trajectory(**_base(target_sequence=[{'name': 'A', 'tvd_m': 500}]))


def test_target_sequence_metadata_is_defined_for_vertical_profile():
    _, meta = optimize_trajectory(profile='Vertical', target_tvd_m=1000,
        target_north_m=0, target_east_m=0, kop_initial_m=0,
        build_rate_initial_deg_30m=1, peak_inc_initial_deg=0,
        azimuth_initial_deg=0, max_inclination_deg=60, max_dls_deg_30m=3,
        max_build_rate_deg_30m=3, max_turn_rate_deg_30m=3, max_md_m=2000,
        target_sequence=[{'name':'A','tvd_m':500,'north_m':0,'east_m':0},
                         {'name':'B','tvd_m':1000,'north_m':0,'east_m':0}])
    assert meta['required_target_count'] == 2
    assert len(meta['target_sequence_results']) == 2
    assert meta['target_sequence_feasible'] is True
