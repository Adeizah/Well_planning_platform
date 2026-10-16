"""Independent trajectory validation.

A trajectory is never accepted because an optimizer reports success. Every candidate -
optimized, manual or imported - is passed through :func:`validate_trajectory`, which
rebuilds the wellbore from the raw MD / Inc / Azi stations (stored positions are only
*compared*, never trusted), evaluates every hard constraint between stations on the
minimum-curvature arcs, and returns PASS only if every required check passes.

Result classes (see :data:`STATUS_*`):
    PASS                          - all required checks passed.
    REVIEW                        - a check failed, is unresolved, unsupported or needs engineering review.
    NO FEASIBLE CANDIDATE FOUND   - used by optimizers when a search ended without a valid candidate.
                                    This is NOT a proof of infeasibility (see core.feasibility).

This is engineering-development software: PASS means "passed the checks implemented here",
not "certified for operational use".
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd

from core.geometry import target_boundary, target_contains, target_tolerances, DEFAULT_TOLERANCE_M
from core.trajectory import minimum_curvature, interpolate_path
from engineering.anti_collision import clearance_report

STATUS_PASS = "PASS"
STATUS_REVIEW = "REVIEW"
STATUS_NO_FEASIBLE = "NO FEASIBLE CANDIDATE FOUND"
VALIDATOR_VERSION = "1.0"


# --------------------------------------------------------------------------- helpers
def survey_hash(survey) -> str:
    """Stable fingerprint of the MD/Inc/Azi stations (used to detect stale validations)."""
    df = pd.DataFrame(survey)
    cols = [c for c in ("MD", "Inc", "Azi") if c in df.columns]
    if not cols:
        return ""
    arr = np.round(df[cols].to_numpy(float), 6)
    return hashlib.sha1(arr.tobytes()).hexdigest()[:16]


def _check(name, status, value=None, limit=None, detail=""):
    return {"check": name, "status": status, "value": value, "limit": limit, "detail": detail}


def plane_tvd(target, north, east):
    """TVD of the (optionally inclined) target plane at a horizontal position."""
    dip = math.radians(float(target.get("dip_deg", 0.0) or 0.0))
    dip_az = math.radians(float(target.get("dip_direction_deg", 0.0) or 0.0))
    dn = np.asarray(north, dtype=float) - float(target["north_m"])
    de = np.asarray(east, dtype=float) - float(target["east_m"])
    return float(target["tvd_m"]) + math.tan(dip) * (dn * math.cos(dip_az) + de * math.sin(dip_az))


def footprint_miss(target, north, east, default_tol=DEFAULT_TOLERANCE_M):
    """Distance outside the target footprint (0 = inside). Vectorised over north/east."""
    north = np.atleast_1d(np.asarray(north, dtype=float)); east = np.atleast_1d(np.asarray(east, dtype=float))
    geom = target.get("geometry") or (target if target.get("type") else None)
    lat_tol, _ = target_tolerances(target, default_tol)
    cn, ce = float(target["north_m"]), float(target["east_m"])
    center = np.hypot(north - cn, east - ce)
    if not geom or str(geom.get("type", "Point")).lower() == "point":
        return np.maximum(0.0, center - lat_tol)
    g = dict(geom); g.setdefault("north_m", cn); g.setdefault("east_m", ce)
    inside = np.array([target_contains(g, n, e) for n, e in zip(north, east)])
    bn, be = target_boundary(g)
    if len(bn) == 1:
        return np.where(inside, 0.0, np.hypot(north - float(bn[0]), east - float(be[0])))
    bn = np.asarray(bn, dtype=float); be = np.asarray(be, dtype=float)
    best = np.full(len(north), np.inf)
    for i in range(len(bn) - 1):
        dn, de = bn[i + 1] - bn[i], be[i + 1] - be[i]
        denom = dn * dn + de * de
        f = np.zeros(len(north)) if denom < 1e-12 else np.clip(((north - bn[i]) * dn + (east - be[i]) * de) / denom, 0.0, 1.0)
        best = np.minimum(best, np.hypot(north - (bn[i] + f * dn), east - (be[i] + f * de)))
    return np.where(inside, 0.0, np.where(np.isfinite(best), best, center))


def _dense(path, spacing_m=5.0):
    mds = path["MD"].to_numpy(float)
    grid = np.arange(mds[0], mds[-1], spacing_m)
    return interpolate_path(path, np.unique(np.concatenate([grid, mds])))


def _approach(dense, target):
    inc = dense["Inc"].to_numpy(float); azi = dense["Azi"].to_numpy(float)
    ai, aa = np.radians(inc), np.radians(azi)
    azi_diff = np.abs((azi - float(target.get("approach_azimuth_deg", 0.0)) + 180.0) % 360.0 - 180.0)
    inc_diff = np.abs(inc - float(target.get("approach_inclination_deg", 0.0)))
    dip = math.radians(float(target.get("dip_deg", 0.0) or 0.0)); dip_az = math.radians(float(target.get("dip_direction_deg", 0.0) or 0.0))
    tangent = np.stack([np.sin(ai) * np.cos(aa), np.sin(ai) * np.sin(aa), np.cos(ai)], axis=1)
    normal = np.array([-math.tan(dip) * math.cos(dip_az), -math.tan(dip) * math.sin(dip_az), 1.0]); normal /= np.linalg.norm(normal)
    plane_angle = np.degrees(np.arcsin(np.clip(np.abs(tangent @ normal), 0.0, 1.0)))
    ok = np.ones(len(inc), dtype=bool)
    if target.get("approach_azimuth_enabled"):
        ok &= azi_diff <= float(target.get("approach_azimuth_tolerance_deg", 10.0)) + 1e-6
    if target.get("approach_inclination_enabled"):
        ok &= inc_diff <= float(target.get("approach_inclination_tolerance_deg", 5.0)) + 1e-6
    if target.get("intersection_angle_enabled"):
        ok &= (plane_angle >= float(target.get("min_intersection_angle_deg", 0.0)) - 1e-6) & (plane_angle <= float(target.get("max_intersection_angle_deg", 90.0)) + 1e-6)
    return ok, azi_diff, inc_diff, plane_angle


def evaluate_target(dense, target, start_md=-1.0, endpoint_only=False, default_tol=DEFAULT_TOLERANCE_M):
    """Best valid interception of one target on the dense arc-resampled path."""
    md = dense["MD"].to_numpy(float); n = dense["Northing"].to_numpy(float); e = dense["Easting"].to_numpy(float); z = dense["TVD"].to_numpy(float)
    lat_tol, vert_tol = target_tolerances(target, default_tol)
    cand = np.arange(len(md))
    cand = cand[-1:] if endpoint_only else cand[md > start_md + 1e-3]
    if len(cand) == 0:
        return None
    miss = footprint_miss(target, n, e, default_tol)
    vert = z - plane_tvd(target, n, e)
    lat = np.hypot(n - float(target["north_m"]), e - float(target["east_m"]))
    appr_ok, azi_d, inc_d, plane_a = _approach(dense, target)
    footprint_ok = (miss <= 1e-3) & (np.abs(vert) <= vert_tol)
    good = np.zeros(len(md), dtype=bool); good[cand] = footprint_ok[cand] & appr_ok[cand]
    inside = np.zeros(len(md), dtype=bool); inside[cand] = footprint_ok[cand]
    if good.any():
        k = int(np.flatnonzero(good)[np.argmin(lat[good])])      # prefer the target centre
    elif inside.any():
        idx = np.flatnonzero(inside); k = int(idx[np.argmin(azi_d[idx] + inc_d[idx])])
    else:
        score = miss + 0.35 * lat + 4.0 * np.abs(vert)
        idx = cand; k = int(idx[np.argmin(score[idx])])
    return {"name": str(target.get("name", "Target")), "intercept_md_m": float(md[k]), "lateral_error_m": float(lat[k]),
            "vertical_error_m": float(vert[k]), "miss_distance_m": float(miss[k]),
            "within_tolerance": bool(footprint_ok[k]), "in_order": True,
            "approach_azimuth_deg": float(dense["Azi"].iloc[k]), "approach_inclination_deg": float(dense["Inc"].iloc[k]),
            "approach_azimuth_error_deg": float(azi_d[k]), "approach_inclination_error_deg": float(inc_d[k]),
            "plane_intersection_angle_deg": float(plane_a[k]), "approach_constraints_pass": bool(appr_ok[k]),
            "vertical_tolerance_m": float(vert_tol)}


def _numeric_arc_check(raw):
    """Independent check of the closed-form minimum-curvature positions by numerical integration
    of the slerp tangent along each arc (Simpson, 64 sub-steps). Returns max end-point deviation (m)."""
    md = raw["MD"].to_numpy(float); inc = np.radians(raw["Inc"].to_numpy(float)); azi = np.radians(raw["Azi"].to_numpy(float))
    t = np.stack([np.sin(inc) * np.cos(azi), np.sin(inc) * np.sin(azi), np.cos(inc)], axis=1)
    cosb = np.clip(np.sum(t[:-1] * t[1:], axis=1), -1.0, 1.0); beta = np.arccos(cosb); sb = np.sin(beta)
    steps = 64; f = np.linspace(0.0, 1.0, steps + 1)
    w = np.ones(steps + 1); w[1:-1:2] = 4.0; w[2:-1:2] = 2.0; w *= (1.0 / steps) / 3.0
    total = np.zeros((len(md) - 1, 3))
    for s in range(steps + 1):
        fs = f[s]
        a = np.where(sb < 1e-9, 1.0 - fs, np.sin((1 - fs) * beta) / np.where(sb < 1e-9, 1.0, sb))
        b = np.where(sb < 1e-9, fs, np.sin(fs * beta) / np.where(sb < 1e-9, 1.0, sb))
        v = a[:, None] * t[:-1] + b[:, None] * t[1:]
        v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-15)
        total += w[s] * v
    seg = total * np.diff(md)[:, None]
    return np.concatenate([np.zeros((1, 3)), np.cumsum(seg, axis=0)], axis=0)


def _brute_force_min_distance(main_xyz_fn, offset_xyz_fn, main_md, off_md, spacing_m=3.0, cap=1600):
    nm = int(min(cap, max(2, math.ceil((main_md[1] - main_md[0]) / spacing_m) + 1)))
    no = int(min(cap, max(2, math.ceil((off_md[1] - off_md[0]) / spacing_m) + 1)))
    a = main_xyz_fn(np.linspace(main_md[0], main_md[1], nm)); b = offset_xyz_fn(np.linspace(off_md[0], off_md[1], no))
    best = np.inf
    for s in range(0, len(a), 400):
        best = min(best, float(np.min(np.linalg.norm(a[s:s + 400, None, :] - b[None, :, :], axis=2))))
    return best


# --------------------------------------------------------------------------- main API
def validate_trajectory(survey, *, targets=None, constraints=None, offsets=None,
                        surface_easting_m=0.0, surface_northing_m=0.0, kb_m=None,
                        survey_error_model=None, required_separation_factor=2.0, anti_collision_criteria=None,
                        require_final_at_target=True, default_target_tolerance_m=DEFAULT_TOLERANCE_M,
                        max_station_spacing_m=100.0, position_tolerance_m=0.05, resample_spacing_m=5.0,
                        check_anti_collision=True):
    """Independently validate a trajectory. ``survey`` is a DataFrame/list with at least MD, Inc, Azi.

    ``targets`` are well-relative dicts (``north_m``, ``east_m``, ``tvd_m`` [+ optional geometry,
    tolerances, dip, approach constraints]) in required interception order. ``constraints`` may hold
    ``max_inclination_deg``, ``max_dls_deg_30m``, ``max_build_rate_deg_30m``, ``max_turn_rate_deg_30m``,
    ``max_md_m``, ``min_kop_md_m``, ``max_kop_md_m``. Unspecified limits are reported as not applicable.
    """
    constraints = dict(constraints or {}); targets = list(targets or []); offsets = list(offsets or [])
    checks = []; result = {"validator_version": VALIDATOR_VERSION, "survey_hash": survey_hash(survey)}
    raw = pd.DataFrame(survey)
    # ---- 1. survey integrity
    try:
        if not {"MD", "Inc", "Azi"}.issubset(raw.columns):
            raise ValueError("Survey needs MD, Inc and Azi columns.")
        base = raw[["MD", "Inc", "Azi"]].apply(pd.to_numeric, errors="raise")
        if not np.isfinite(base.to_numpy(float)).all():
            raise ValueError("Survey contains non-finite values.")
        if len(base) < 2:
            raise ValueError("At least two stations are required.")
        path = minimum_curvature(base)
    except Exception as ex:
        checks.append(_check("survey_integrity", STATUS_REVIEW, detail=f"Survey cannot be evaluated: {ex}"))
        return {**result, "status": STATUS_REVIEW, "checks": checks, "violations": ["survey_integrity"], "target_results": [], "collision": [], "metrics": {}}
    tie_note = " First station is not at MD 0: vertical tie-in from surface assumed." if path.attrs.get("tie_in_assumed") else ""
    checks.append(_check("survey_integrity", STATUS_REVIEW if tie_note else STATUS_PASS, detail="MD increases, inclination within 0-180°, values finite." + tie_note))

    md = path["MD"].to_numpy(float); inc = path["Inc"].to_numpy(float); azi = path["Azi"].to_numpy(float)
    dmd = np.diff(md)
    # ---- 2. stored positions vs rebuilt positions
    if {"Northing", "Easting", "TVD"}.issubset(raw.columns):
        stored = raw[["Northing", "Easting", "TVD"]].apply(pd.to_numeric, errors="coerce").to_numpy(float)
        order = np.argsort(pd.to_numeric(raw["MD"]).to_numpy(float))
        dev = float(np.nanmax(np.abs(stored[order] - path[["Northing", "Easting", "TVD"]].to_numpy(float))))
        checks.append(_check("stored_positions_match_rebuilt", STATUS_PASS if dev <= position_tolerance_m else STATUS_REVIEW, dev, position_tolerance_m,
                             "Stored coordinates agree with positions rebuilt from MD/Inc/Azi." if dev <= position_tolerance_m else "Stored N/E/TVD differ from the positions rebuilt from the angles - the stored table is stale or edited."))
    # ---- 3. independent numerical integration of the arcs
    try:
        num = _numeric_arc_check(path); closed = path[["Northing", "Easting", "TVD"]].to_numpy(float) - path[["Northing", "Easting", "TVD"]].to_numpy(float)[0]
        dev = float(np.max(np.abs(num - closed)))
        checks.append(_check("integration_cross_check", STATUS_PASS if dev <= 0.05 else STATUS_REVIEW, dev, 0.05, "Closed-form minimum curvature agrees with numerical integration of the arcs."))
    except Exception as ex:
        checks.append(_check("integration_cross_check", STATUS_REVIEW, detail=f"Could not run: {ex}"))

    # ---- 4. drilling constraints (continuous: DLS/build/turn are exact per arc segment)
    dls = path["DLS"].to_numpy(float)[1:]
    build = np.abs(np.diff(inc)) / dmd * 30.0
    az_un = np.degrees(np.unwrap(np.radians(azi)))
    turn = np.abs(np.diff(az_un)) / dmd * 30.0
    az_defined = np.maximum(inc[:-1], inc[1:]) >= 0.5          # azimuth is undefined in a (near-)vertical hole
    turn_eff = np.where(az_defined, turn, 0.0)
    metrics = {"max_inclination_deg": float(inc.max()), "max_dls_deg_30m": float(dls.max(initial=0.0)),
               "max_build_rate_deg_30m": float(build.max(initial=0.0)), "max_turn_rate_deg_30m": float(turn_eff.max(initial=0.0)),
               "final_md_m": float(md[-1]), "final_tvd_m": float(path.TVD.iloc[-1]), "final_north_m": float(path.Northing.iloc[-1]),
               "final_east_m": float(path.Easting.iloc[-1]), "final_inclination_deg": float(inc[-1]), "final_azimuth_deg": float(azi[-1]),
               "max_station_spacing_m": float(dmd.max(initial=0.0)), "station_count": int(len(md))}
    kop_idx = np.flatnonzero(inc > float(constraints.get("kop_inc_threshold_deg", 0.5)))
    metrics["kop_md_m"] = float(md[kop_idx[0] - 1] if len(kop_idx) and kop_idx[0] > 0 else (md[kop_idx[0]] if len(kop_idx) else md[-1]))
    for key, label, value, tol in (("max_inclination_deg", "maximum_inclination", metrics["max_inclination_deg"], 1e-3),
                                   ("max_dls_deg_30m", "maximum_DLS", metrics["max_dls_deg_30m"], 1e-3),
                                   ("max_build_rate_deg_30m", "maximum_build_rate", metrics["max_build_rate_deg_30m"], 1e-3),
                                   ("max_turn_rate_deg_30m", "maximum_turn_rate", metrics["max_turn_rate_deg_30m"], 1e-3)):
        if constraints.get(key) is None:
            checks.append(_check(label, "N/A", value, None, "No limit supplied."))
        else:
            lim = float(constraints[key]); checks.append(_check(label, STATUS_PASS if value <= lim + tol else STATUS_REVIEW, value, lim))
    if constraints.get("max_md_m") is not None:
        lim = float(constraints["max_md_m"]); checks.append(_check("maximum_MD", STATUS_PASS if md[-1] <= lim + 1e-3 else STATUS_REVIEW, float(md[-1]), lim))
    if constraints.get("min_kop_md_m") is not None or constraints.get("max_kop_md_m") is not None:
        lo = constraints.get("min_kop_md_m"); hi = constraints.get("max_kop_md_m"); k = metrics["kop_md_m"]
        okk = (lo is None or k >= float(lo) - 1e-3) and (hi is None or k <= float(hi) + 1e-3)
        checks.append(_check("KOP_restriction", STATUS_PASS if okk else STATUS_REVIEW, k, {"min": lo, "max": hi}))
    coarse = metrics["max_station_spacing_m"] > float(max_station_spacing_m)
    checks.append(_check("station_spacing_resolution", STATUS_REVIEW if coarse else STATUS_PASS, metrics["max_station_spacing_m"], float(max_station_spacing_m),
                         "Stations are too far apart: DLS/build/turn are averaged over the interval." if coarse else "Station spacing is fine enough for DLS/build/turn to be meaningful."))

    # ---- 5. targets (ordered, interception on the arcs between stations, final target ends the plan)
    dense = _dense(path, resample_spacing_m)
    target_results = []; prev_md = -1.0
    for idx, t in enumerate(targets):
        last = idx == len(targets) - 1
        r = evaluate_target(dense, t, start_md=prev_md, endpoint_only=(last and require_final_at_target), default_tol=default_target_tolerance_m)
        if r is None:
            r = {"name": str(t.get("name", "Target")), "intercept_md_m": float("nan"), "lateral_error_m": float("nan"), "vertical_error_m": float("nan"),
                 "miss_distance_m": float("nan"), "within_tolerance": False, "in_order": False, "approach_constraints_pass": False}
        else:
            prev_md = r["intercept_md_m"]
        target_results.append(r)
    for r in target_results:
        okt = r["within_tolerance"] and r["in_order"]
        checks.append(_check(f"target[{r['name']}]_intercept", STATUS_PASS if okt else STATUS_REVIEW, r.get("miss_distance_m"), 0.0,
                             f"intercept MD {r['intercept_md_m']:.1f} m, lateral {r['lateral_error_m']:.1f} m, vertical {r['vertical_error_m']:.1f} m" if np.isfinite(r["intercept_md_m"]) else "no point after the previous target"))
        if any(t.get("approach_azimuth_enabled") or t.get("approach_inclination_enabled") or t.get("intersection_angle_enabled") for t in targets if str(t.get("name", "Target")) == r["name"]):
            checks.append(_check(f"target[{r['name']}]_approach", STATUS_PASS if r["approach_constraints_pass"] else STATUS_REVIEW,
                                 {"azimuth_err": r.get("approach_azimuth_error_deg"), "inclination_err": r.get("approach_inclination_error_deg"), "plane_angle": r.get("plane_intersection_angle_deg")}))
    if targets and require_final_at_target and target_results and target_results[-1].get("within_tolerance"):
        extra = float(md[-1] - target_results[-1]["intercept_md_m"])
        checks.append(_check("terminates_at_final_target", STATUS_PASS if abs(extra) <= 1.0 else STATUS_REVIEW, extra, 1.0, "Plan ends at the final target interception." if abs(extra) <= 1.0 else "Plan extends beyond the final target interception."))
    result["target_results"] = target_results
    metrics["target_miss_distance_m"] = float(target_results[-1]["miss_distance_m"]) if target_results else None

    # ---- 6. anti-collision (covariance model + independent brute-force distance cross-check)
    collision = []
    if offsets and check_anti_collision:
        datum_notes = []
        shifted = []
        for off in offsets:
            o = dict(off)
            ok_kb = o.get("kb_m")
            if kb_m is not None and ok_kb is not None and abs(float(ok_kb) - float(kb_m)) > 1e-6 and len(o.get("surveys", [])) > 1:
                shift = float(kb_m) - float(ok_kb)       # elevation = KB - TVD, so TVD_in_main_datum = TVD + (KB_main - KB_off)
                s = pd.DataFrame(o["surveys"]);
                if {"Inc", "Azi"}.issubset(s.columns) and not {"TVD"}.issubset(s.columns):
                    s = minimum_curvature(s[["MD", "Inc", "Azi"]])
                s["TVD"] = pd.to_numeric(s["TVD"]) + shift; o["surveys"] = s.to_dict("records")
                datum_notes.append(f"{o.get('name', 'Offset')}: TVD shifted {shift:+.2f} m to the main-well datum")
            elif kb_m is not None and ok_kb is None:
                datum_notes.append(f"{o.get('name', 'Offset')}: no KB elevation recorded - assumed to share the main-well TVD datum")
            shifted.append(o)
        try:
            rep = clearance_report(path, shifted, survey_error_model=survey_error_model or {}, main_surface_easting_m=surface_easting_m,
                                   main_surface_northing_m=surface_northing_m, required_separation_factor=required_separation_factor, criteria=anti_collision_criteria)
            collision = rep.to_dict("records")
            for row in collision:
                st = row.get("status")
                checks.append(_check(f"anti_collision[{row.get('offset')}]", STATUS_PASS if st == "PASS" else STATUS_REVIEW, row.get("separation_factor"), float(required_separation_factor),
                                     f"{st}: min SF {row.get('separation_factor')}, closest approach {row.get('separation_m')} m" + (" | " + row.get("note", "") if st != "PASS" else "")))
            # independent brute-force closest-distance cross-check
            for off, row in zip(shifted, collision):
                if row.get("status") == "NOT CHECKED" or not np.isfinite(row.get("separation_m", np.nan)):
                    continue
                od = pd.DataFrame(off["surveys"])
                if not {"Easting", "Northing", "TVD"}.issubset(od.columns):
                    od = minimum_curvature(od[["MD", "Inc", "Azi"]])
                se, sn = float(off.get("surface_easting_m", 0.0) or 0.0), float(off.get("surface_northing_m", 0.0) or 0.0)
                shift = np.array([float(surface_northing_m), float(surface_easting_m), 0.0]); oshift = np.array([sn, se, 0.0])
                mx = lambda m: np.column_stack([interpolate_path(path, m)[c] for c in ("Northing", "Easting", "TVD")]) + shift
                ox = lambda m: np.column_stack([interpolate_path(od, m)[c] for c in ("Northing", "Easting", "TVD")]) + oshift
                bf = _brute_force_min_distance(mx, ox, (md[0], md[-1]), (float(od.MD.iloc[0]), float(od.MD.iloc[-1])))
                gap = float(row["separation_m"]) - bf
                checks.append(_check(f"closest_approach_cross_check[{row.get('offset')}]", STATUS_PASS if gap <= 1.0 else STATUS_REVIEW, gap, 1.0,
                                     f"Engine closest approach {row['separation_m']:.2f} m vs independent brute-force {bf:.2f} m."))
        except Exception as ex:
            collision = [{"offset": "(all)", "status": "REVIEW", "note": f"Independent clearance validation failed: {ex}"}]
            checks.append(_check("anti_collision", STATUS_REVIEW, detail=f"Clearance validation failed: {ex}"))
        if datum_notes:
            checks.append(_check("depth_datum_consistency", "NOTE", detail="; ".join(datum_notes)))
    result["collision"] = collision

    required = [c for c in checks if c["status"] not in ("N/A", "NOTE")]
    def _violation_name(name):
        if name.startswith("target[") and name.endswith("_intercept"):
            return "target_sequence"
        if name.startswith("target[") and name.endswith("_approach"):
            return "target_approach_constraints"
        if name.startswith("anti_collision"):
            return "anti_collision_review_required"
        if name.startswith("closest_approach_cross_check"):
            return "anti_collision_cross_check"
        return name
    violations = sorted({_violation_name(c["check"]) for c in required if c["status"] != STATUS_PASS})
    result.update({"status": STATUS_PASS if not violations else STATUS_REVIEW, "checks": checks, "violations": violations, "metrics": metrics, "path": path})
    return result


def search_outcome(validation, search_completed=True, proven_infeasible=False):
    """Map a validation + search state to the three platform result classes.

    A failed search is NOT a proof of infeasibility; ``proven_infeasible`` must come from
    core.feasibility.reachability_screen (an analytic necessary-condition test).
    """
    if validation and validation.get("status") == STATUS_PASS:
        return {"status": STATUS_PASS, "optimization_status": "FEASIBLE", "proof": None}
    if proven_infeasible:
        return {"status": STATUS_REVIEW, "optimization_status": "INFEASIBLE_PROVEN", "proof": "analytic reachability bound"}
    return {"status": STATUS_REVIEW, "optimization_status": "NO_FEASIBLE_CANDIDATE_FOUND",
            "proof": None if search_completed else "search interrupted"}


def to_jsonable(obj):
    """Recursively convert numpy / pandas / NaN values into plain JSON-safe Python objects."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, pd.DataFrame):
        return to_jsonable(obj.to_dict("records"))
    return obj
