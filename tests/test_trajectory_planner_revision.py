import numpy as np

from core.trajectory import generate_profile_candidate


def test_j_profile_and_build_hold_are_same_geometry():
    common = dict(kop_md=300.0, build_rate_deg_30m=2.0, hold_inc_deg=40.0,
                  hold_azi_deg=120.0, target_tvd=900.0, target_north=400.0,
                  target_east=100.0, station_interval=30.0, max_md=1800.0,
                  truncate_at_target=False)
    j, _ = generate_profile_candidate('J-Profile', **common)
    bh, _ = generate_profile_candidate('Build & Hold', **common)
    assert len(j) == len(bh)
    assert np.allclose(j[['MD', 'Inc', 'Azi', 'TVD', 'Northing', 'Easting']],
                       bh[['MD', 'Inc', 'Azi', 'TVD', 'Northing', 'Easting']])


def test_s_profile_keeps_drop_section_when_full_path_requested():
    path, meta = generate_profile_candidate(
        'S-Profile', kop_md=300.0, build_rate_deg_30m=2.0,
        hold_inc_deg=40.0, hold_azi_deg=120.0, target_tvd=900.0,
        target_north=400.0, target_east=100.0, drop_rate_deg_30m=2.0,
        final_inc_deg=5.0, station_interval=30.0, max_md=1800.0,
        drop_start_md=1300.0, truncate_at_target=False)
    assert meta['target_intercept_found']
    assert path['MD'].iloc[-1] > meta['target_intercept_md_m']
    assert path['Inc'].iloc[-1] <= 5.01
    assert meta['section_end_md_m']['Drop start'] is not None
    assert meta['section_end_md_m']['Drop end'] is not None


def test_legacy_target_truncation_can_still_be_requested():
    common = dict(kop_md=300.0, build_rate_deg_30m=2.0, hold_inc_deg=40.0,
                  hold_azi_deg=120.0, target_tvd=900.0, target_north=400.0,
                  target_east=100.0, drop_rate_deg_30m=2.0, final_inc_deg=5.0,
                  station_interval=30.0, max_md=1800.0, drop_start_md=1300.0)
    full, _ = generate_profile_candidate('S-Profile', **common, truncate_at_target=False)
    truncated, _ = generate_profile_candidate('S-Profile', **common, truncate_at_target=True)
    assert len(full) > len(truncated)
