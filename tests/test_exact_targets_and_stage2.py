"""Regression tests for exact point targets, ordered multi-target planning, section reconstruction (Stage 2)."""
import math

import numpy as np
import pandas as pd
import pytest

from core.exact_targets import closest_point_on_path, arc_position, POINT_NUMERIC_TOL_M, POINT_TARGET_ACCEPTANCE_TOL_M
from core.general_optimizer import optimize_general_trajectory
from core.geometry import target_contains
from core.section_optimizer import (sections_to_stations, segment_path, initial_sections, reoptimize_sections, describe_sections, classify_section)
from core.section_reconstruction import constraint_margin_rows
from core.trajectory import minimum_curvature, mc_core, lean_path
from core.validation import validate_trajectory

BASE = dict(max_md_m=3000.0, max_inclination_deg=70.0, max_dls_deg_30m=3.0, max_build_rate_deg_30m=3.0, max_turn_rate_deg_30m=3.0,
            station_interval_m=30.0, maxiter=45, control_points=5, time_budget_s=60.0)


def _arc_path():
    md = np.arange(0, 1400, 85.0)
    return minimum_curvature(pd.DataFrame({"MD": md, "Inc": np.clip((md - 200) * 0.05, 0, 60), "Azi": np.full(len(md), 70.0) + md * 0.01}))


def _plan(targets, **kw):
    return optimize_general_trajectory(**{**BASE, **kw}, targets=targets)


# ---------------------------------------------------------------- numerical kernel / speed path
def test_numpy_kernel_matches_validated_minimum_curvature_exactly():
    rng = np.random.default_rng(3); n = 80
    md = np.linspace(0, 2400, n); inc = np.clip(np.cumsum(rng.normal(0.5, 0.3, n)), 0, 80); azi = (np.cumsum(rng.normal(0, 2, n)) + 40) % 360
    full = minimum_curvature(pd.DataFrame({"MD": md, "Inc": inc, "Azi": azi})); lean = lean_path(md, inc, azi)
    for c in ("Northing", "Easting", "TVD", "DLS"):
        assert np.array_equal(full[c].to_numpy(), lean[c].to_numpy())


# ---------------------------------------------------------------- exact point targets
def test_closest_point_recovers_points_on_arcs_to_floating_point_precision():
    p = _arc_path()
    for k, f in [(9, 0.37), (3, 0.5), (12, 0.9), (7, 0.01)]:
        pos, _, md = arc_position(p, k, f)
        r = closest_point_on_path(p, pos)
        assert r["distance_m"] < 1e-9 and abs(r["md"] - md) < 1e-6


def test_point_target_uses_two_foot_acceptance_but_keeps_center_as_objective():
    raw = _arc_path()[["MD", "Inc", "Azi"]]; p = minimum_curvature(raw)
    on = {"name": "P", "tvd_m": float(p.TVD.iloc[-1]), "north_m": float(p.Northing.iloc[-1]), "east_m": float(p.Easting.iloc[-1])}
    assert validate_trajectory(raw, targets=[on], constraints={})["target_results"][0]["within_tolerance"]
    # 2 ft = 0.6096 m is the 3-D acceptance envelope; the optimizer still minimizes miss to centre.
    assert abs(POINT_TARGET_ACCEPTANCE_TOL_M - 0.6096) < 1e-12
    for off in (0.01, 0.3, 0.6095):
        t = {**on, "tvd_m": on["tvd_m"] + off}
        r = validate_trajectory(raw, targets=[t], constraints={})["target_results"][0]
        assert r["within_tolerance"], off
    for off in (0.6097, 0.8, 5.0):
        t = {**on, "tvd_m": on["tvd_m"] + off}
        r = validate_trajectory(raw, targets=[t], constraints={})["target_results"][0]
        assert not r["within_tolerance"], off
    assert POINT_NUMERIC_TOL_M <= 1e-3  # tight polishing criterion remains separate from acceptance


def test_optimizer_closes_a_point_target_exactly():
    path, meta = _plan([{"name": "A", "tvd_m": 900.0, "north_m": 0.0, "east_m": 900.0}])
    assert meta["result_class"] == "PASS"
    assert meta["target_sequence_results"][0]["miss_distance_m"] < 1e-4
    assert abs(path.iloc[-1].TVD - 900.0) < 1e-4 and abs(path.iloc[-1].Easting - 900.0) < 1e-4


# ---------------------------------------------------------------- ordered multi-target planning
def test_ordered_multi_target_interception_in_sequence():
    targets = [{"name": "T1", "tvd_m": 500.0, "north_m": 0.0, "east_m": 250.0}, {"name": "T2", "tvd_m": 1000.0, "north_m": 250.0, "east_m": 900.0}]
    path, meta = _plan(targets)
    res = meta["target_sequence_results"]
    assert meta["result_class"] == "PASS" and all(r["within_tolerance"] for r in res)
    assert res[0]["intercept_md_m"] < res[1]["intercept_md_m"]
    assert max(r["miss_distance_m"] for r in res) < 1e-4


def test_three_point_sequence_with_turns_is_recovered():
    targets = [{"name": "T1", "tvd_m": 600.0, "north_m": 150.0, "east_m": 200.0}, {"name": "T2", "tvd_m": 1100.0, "north_m": 200.0, "east_m": 600.0},
               {"name": "T3", "tvd_m": 1500.0, "north_m": -100.0, "east_m": 900.0}]
    _, meta = _plan(targets, time_budget_s=90.0)
    assert meta["result_class"] == "PASS" and len(meta["target_sequence_results"]) == 3
    assert all(r["within_tolerance"] for r in meta["target_sequence_results"])


def test_success_is_never_reported_when_a_later_required_target_is_missed():
    targets = [{"name": "T1", "tvd_m": 800.0, "north_m": 0.0, "east_m": 400.0}, {"name": "T2", "tvd_m": 300.0, "north_m": 0.0, "east_m": 700.0}]   # T2 is shallower than T1: unreachable in order
    _, meta = _plan(targets, time_budget_s=30.0)
    assert meta["result_class"] != "PASS" and meta["status"] != "PASS"
    assert not all(r["within_tolerance"] for r in meta["target_sequence_results"])
    assert len(meta["target_sequence_results"]) == 2                  # the full sequence is still evaluated and reported


# ---------------------------------------------------------------- circular / elliptical geometry preserved
def test_circular_target_is_satisfied_by_footprint_not_forced_to_a_point():
    t = {"name": "C", "type": "Circular", "radius_m": 50.0, "tvd_m": 900.0, "north_m": 0.0, "east_m": 900.0}
    path, meta = _plan([t])
    end = path.iloc[-1]
    assert meta["result_class"] == "PASS" and target_contains(t, end.Northing, end.Easting)


def test_elliptical_target_dimensions_and_orientation_are_respected():
    t = {"name": "E", "type": "Elliptical", "semi_major_m": 120.0, "semi_minor_m": 40.0, "orientation_deg": 60.0, "tvd_m": 900.0, "north_m": 0.0, "east_m": 900.0}
    path, meta = _plan([t])
    end = path.iloc[-1]
    assert meta["result_class"] == "PASS" and target_contains(t, end.Northing, end.Easting)
    rotated = {**t, "orientation_deg": 60.0 + 90.0}                   # same ellipse turned 90 deg is a different footprint
    assert target_contains(t, end.Northing, end.Easting) is True
    assert meta["target_sequence_results"][0]["within_tolerance"]


# ---------------------------------------------------------------- DLS violations and infeasible plans
def test_dls_limit_that_cannot_reach_the_target_is_reported_not_hidden():
    _, meta = _plan([{"name": "A", "tvd_m": 900.0, "north_m": 0.0, "east_m": 900.0}], max_dls_deg_30m=0.5, max_build_rate_deg_30m=0.5, time_budget_s=20.0)
    assert meta["result_class"] != "PASS"
    assert meta["proof_of_infeasibility"] or meta["constraint_violations"]


def test_analytic_infeasibility_is_proven_and_never_labelled_pass():
    _, meta = _plan([{"name": "A", "tvd_m": 500.0, "north_m": 0.0, "east_m": 2000.0}], time_budget_s=20.0)
    assert meta["optimization_status"] == "INFEASIBLE_PROVEN" and meta["result_class"] == "REVIEW"
    assert meta["proof_of_infeasibility"]["proven_infeasible"]


# ---------------------------------------------------------------- Stage 2 section reconstruction
def test_sections_to_stations_places_every_section_boundary_as_a_station_and_respects_rates():
    secs = [{"length_m": 300.0, "build_deg_30m": 0.0, "turn_deg_30m": 0.0}, {"length_m": 400.0, "build_deg_30m": 2.0, "turn_deg_30m": 0.0}, {"length_m": 500.0, "build_deg_30m": 0.0, "turn_deg_30m": 1.0}]
    md, inc, azi = sections_to_stations(90.0, secs, 30.0)
    assert 300.0 in md and 700.0 in md and abs(md[-1] - 1200.0) < 1e-9
    assert abs(np.interp(700.0, md, inc) - 400.0 * 2.0 / 30.0) < 1e-9
    assert abs(np.interp(1200.0, md, azi) - (90.0 + 500.0 / 30.0)) < 1e-9
    path = minimum_curvature(pd.DataFrame({"MD": md, "Inc": inc, "Azi": azi}))
    assert path.DLS.max() <= 2.0 + 1e-6 + 1.0                          # build 2 deg/30 m, turn 1 deg/30 m (small inc)


def test_segmentation_finds_the_few_sections_of_a_build_hold_build_path():
    md = np.linspace(0, 1500, 126)
    inc = np.interp(md, [0, 300, 700, 900, 1500], [0, 0, 40, 40, 62])
    path = pd.DataFrame({"MD": md, "Inc": inc, "Azi": np.full(len(md), 80.0)})
    cuts = segment_path(path, max_sections=8, rms_tol_deg=0.5)
    assert 3 <= len(cuts) - 1 <= 5
    assert any(abs(c - 300.0) < 40 for c in cuts) and any(abs(c - 700.0) < 40 for c in cuts)


def test_stage2_result_is_regenerated_from_section_parameters_and_independently_valid():
    t = {"name": "A", "tvd_m": 900.0, "north_m": 0.0, "east_m": 900.0}
    path, meta = _plan([t])
    assert meta["section_reconstruction_status"] == "REOPTIMIZED" and meta["final_trajectory_source"].startswith("section parameters")
    sched = meta["section_schedule"]
    azi0 = sched[0]["start_azi_deg"]
    secs = [{"length_m": r["length_m"], "build_deg_30m": r["build_drop_rate_deg_30m"], "turn_deg_30m": r["turn_rate_deg_30m"]} for r in sched]
    md, inc, azi = sections_to_stations(azi0, secs, 30.0)
    assert np.allclose(md, path.MD.to_numpy(), atol=1e-6) and np.allclose(inc, path.Inc.to_numpy(), atol=1e-6)
    val = validate_trajectory(path[["MD", "Inc", "Azi"]], targets=[t], constraints={"max_dls_deg_30m": 3.0, "max_inclination_deg": 70.0, "max_build_rate_deg_30m": 3.0, "max_turn_rate_deg_30m": 3.0}, require_final_at_target=True)
    assert val["status"] == "PASS"
    assert meta["stage1_metrics"] and meta["final_metrics"]["validation_status"] == "PASS"


def test_failed_reconstruction_keeps_the_original_and_is_never_labelled_success():
    base = pd.DataFrame({"MD": np.linspace(0, 1000, 34), "Inc": np.linspace(0, 40, 34), "Azi": np.full(34, 90.0)})
    out = reoptimize_sections(base, target_vectors=lambda p: ([0.0, 0.0, 0.0], [], 0.0), validate=lambda df: {"status": "REVIEW", "violations": ["target_sequence"]},
                              limits={"max_inclination_deg": 70.0, "max_dls_deg_30m": 3.0, "max_build_rate_deg_30m": 3.0, "max_turn_rate_deg_30m": 3.0, "max_md_m": 3000.0}, time_budget_s=5.0)
    assert out["adopted"] is False and out["status"].startswith("RETAINED_ORIGINAL")


def test_stage2_crash_cannot_break_stage1(monkeypatch):
    def boom(*a, **k): raise RuntimeError("synthetic failure")
    import core.section_optimizer as so
    monkeypatch.setattr(so, "segment_path", boom)
    path, meta = _plan([{"name": "A", "tvd_m": 900.0, "north_m": 0.0, "east_m": 900.0}])
    assert meta["result_class"] == "PASS" and meta["section_reconstruction_status"].startswith("RETAINED_ORIGINAL")
    assert meta["final_trajectory_source"] == "Stage-1 control-point trajectory"


def test_section_labels_and_constraint_margin_table():
    assert classify_section(0.0, 0.0, 0.0, 0.0) == "Vertical" and classify_section(2.0, 0.0, 0.0, 30.0) == "Build"
    assert classify_section(-2.0, 0.0, 30.0, 10.0) == "Drop" and classify_section(0.0, 1.5, 40.0, 40.0) == "Turn" and classify_section(0.0, 0.0, 40.0, 40.0) == "Tangent"
    rows = constraint_margin_rows([{"check": "maximum_DLS", "status": "PASS", "value": 2.5, "limit": 3.0}, {"check": "target[T1]_intercept", "status": "FAIL", "value": 12.0, "limit": 0.0}])
    assert rows[0]["margin"] == pytest.approx(0.5) and rows[1]["margin"] == pytest.approx(-12.0)
