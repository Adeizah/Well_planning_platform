import pandas as pd
from core.section_reconstruction import build_section_schedule, validate_section_schedule
from core.geometry import target_tolerances


def test_point_targets_have_no_engineering_tolerance():
    assert target_tolerances({'type':'Point','tolerance_m':50}, 30.48) == (0.0, 0.0)


def test_section_schedule_classifies_vertical_build_and_tangent():
    path = pd.DataFrame({'MD':[0,30,60,90,120], 'Inc':[0,0,3,6,6], 'Azi':[0,0,0,0,0]})
    schedule=build_section_schedule(path, min_section_length_m=1)
    assert any(s['type']=='Vertical' for s in schedule)
    assert any(s['type']=='Build' for s in schedule)
    assert any(s['type']=='Tangent' for s in schedule)


def test_section_validator_flags_rate_limit():
    report=validate_section_schedule([{'max_dls_deg_30m':4,'build_drop_rate_deg_30m':4,'turn_rate_deg_30m':4}],
        max_dls_deg_30m=3,max_build_rate_deg_30m=3,max_turn_rate_deg_30m=3)
    assert report['status']=='REVIEW' and len(report['violations'])==1
    assert 'DLS limit exceeded' in report['violations'][0]
