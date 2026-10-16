"""Control-point trajectory optimizer for engineering-development well planning.

This module generates variable-inclination/azimuth trajectories rather than being
restricted to one named profile. It is intentionally conservative: candidate
feasibility is independently rechecked, and uncertainty-based anti-collision
screening is reported as REVIEW if the selected model cannot be evaluated.
It is not a certified operational well-planning or ISCWSA implementation.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core.trajectory import minimum_curvature, truncate_trajectory_at_md
from core.geometry import target_tolerances
from core.validation import (validate_trajectory, search_outcome, footprint_miss, survey_hash, STATUS_PASS,
                             STATUS_REVIEW, VALIDATOR_VERSION)
from core.feasibility import reachability_screen
import time


def _offset_path(offset: dict) -> pd.DataFrame:
    raw = pd.DataFrame(offset.get('surveys', []))
    if raw.empty or not {'MD', 'Inc', 'Azi'}.issubset(raw.columns):
        return pd.DataFrame()
    try:
        path = minimum_curvature(raw[['MD', 'Inc', 'Azi']].copy())
    except Exception:
        return pd.DataFrame()
    path['Easting'] += float(offset.get('surface_easting_m', 0.0) or 0.0)
    path['Northing'] += float(offset.get('surface_northing_m', 0.0) or 0.0)
    return path


def _interp_path(path: pd.DataFrame, column: str, md: np.ndarray) -> np.ndarray:
    return np.interp(md, path['MD'].to_numpy(float), path[column].to_numpy(float))


def _plane_residual(north: float, east: float, tvd: float, target: dict) -> float:
    """Signed vertical residual from an optional inclined target plane."""
    dip = math.radians(float(target.get('dip_deg', 0.0) or 0.0))
    dip_az = math.radians(float(target.get('dip_direction_deg', 0.0) or 0.0))
    dn = float(north) - float(target['north_m'])
    de = float(east) - float(target['east_m'])
    down_dip_projection = dn * math.cos(dip_az) + de * math.sin(dip_az)
    plane_tvd = float(target['tvd_m']) + math.tan(dip) * down_dip_projection
    return float(tvd) - plane_tvd


def _oriented_target_residual(path: pd.DataFrame, target: dict, default_tolerance_m: float):
    """Best intersection with an oriented target plane and footprint (vectorised).

    Candidates are every station plus the linear plane-crossing point on every segment. Returns
    (lateral_error, vertical_error, md, miss). Station-resolution only: the final acceptance
    decision is made by core.validation on the arc-resampled path.
    """
    n = path['Northing'].to_numpy(float); e = path['Easting'].to_numpy(float)
    tvd = path['TVD'].to_numpy(float); md = path['MD'].to_numpy(float)
    residual = np.array([_plane_residual(n[i], e[i], tvd[i], target) for i in range(len(md))]) if len(md) < 3 else (
        tvd - (float(target['tvd_m']) + math.tan(math.radians(float(target.get('dip_deg', 0.0) or 0.0))) *
               ((n - float(target['north_m'])) * math.cos(math.radians(float(target.get('dip_direction_deg', 0.0) or 0.0))) +
                (e - float(target['east_m'])) * math.sin(math.radians(float(target.get('dip_direction_deg', 0.0) or 0.0))))))
    cross = np.flatnonzero(residual[:-1] * residual[1:] < 0)
    if len(cross):
        denom = residual[cross] - residual[cross + 1]
        f = np.where(np.abs(denom) < 1e-12, 0.0, np.clip(residual[cross] / np.where(np.abs(denom) < 1e-12, 1.0, denom), 0.0, 1.0))
        cn = n[cross] + f * (n[cross + 1] - n[cross]); ce = e[cross] + f * (e[cross + 1] - e[cross])
        cz = tvd[cross] + f * (tvd[cross + 1] - tvd[cross]); cm = md[cross] + f * (md[cross + 1] - md[cross])
        n2, e2, z2, m2 = np.concatenate([n, cn]), np.concatenate([e, ce]), np.concatenate([tvd, cz]), np.concatenate([md, cm])
    else:
        n2, e2, z2, m2 = n, e, tvd, md
    lat = np.hypot(n2 - float(target['north_m']), e2 - float(target['east_m']))
    miss = footprint_miss(target, n2, e2, default_tolerance_m)
    vert = np.array([_plane_residual(a, b, c, target) for a, b, c in zip(n2, e2, z2)]) if len(n2) < 3 else (
        z2 - (float(target['tvd_m']) + math.tan(math.radians(float(target.get('dip_deg', 0.0) or 0.0))) *
              ((n2 - float(target['north_m'])) * math.cos(math.radians(float(target.get('dip_direction_deg', 0.0) or 0.0))) +
               (e2 - float(target['east_m'])) * math.sin(math.radians(float(target.get('dip_direction_deg', 0.0) or 0.0))))))
    score = miss + 0.35 * lat + 4.0 * np.abs(vert)
    k = int(np.argmin(score))
    return float(lat[k]), float(vert[k]), float(m2[k]), float(miss[k])


def _approach_metrics(path: pd.DataFrame, md: float, target: dict):
    inc = float(np.interp(md, path['MD'].to_numpy(float), path['Inc'].to_numpy(float)))
    azis = np.unwrap(np.radians(path['Azi'].to_numpy(float)))
    azi = float(np.degrees(np.interp(md, path['MD'].to_numpy(float), azis)) % 360.0)
    azi_diff = abs((azi - float(target.get('approach_azimuth_deg', azi)) + 180.0) % 360.0 - 180.0)
    inc_diff = abs(inc - float(target.get('approach_inclination_deg', inc)))
    dip = math.radians(float(target.get('dip_deg', 0.0) or 0.0))
    dip_az = math.radians(float(target.get('dip_direction_deg', 0.0) or 0.0))
    # Coordinates are [North, East, TVD], with azimuth clockwise from north.
    tangent = np.array([math.sin(math.radians(inc))*math.cos(math.radians(azi)),
                        math.sin(math.radians(inc))*math.sin(math.radians(azi)),
                        math.cos(math.radians(inc))])
    normal = np.array([-math.tan(dip)*math.cos(dip_az), -math.tan(dip)*math.sin(dip_az), 1.0])
    normal /= max(float(np.linalg.norm(normal)), 1e-12)
    plane_angle = math.degrees(math.asin(float(np.clip(abs(np.dot(tangent, normal)), 0.0, 1.0))))
    valid = True
    if target.get('approach_azimuth_enabled'):
        valid = valid and azi_diff <= float(target.get('approach_azimuth_tolerance_deg', 10.0)) + 1e-6
    if target.get('approach_inclination_enabled'):
        valid = valid and inc_diff <= float(target.get('approach_inclination_tolerance_deg', 5.0)) + 1e-6
    if target.get('intersection_angle_enabled'):
        low = float(target.get('min_intersection_angle_deg', 0.0))
        high = float(target.get('max_intersection_angle_deg', 90.0))
        valid = valid and low-1e-6 <= plane_angle <= high+1e-6
    return {'approach_azimuth_deg': azi, 'approach_inclination_deg': inc,
            'approach_azimuth_error_deg': azi_diff, 'approach_inclination_error_deg': inc_diff,
            'plane_intersection_angle_deg': plane_angle, 'approach_constraints_pass': bool(valid)}


def _sample_min_distance(path: pd.DataFrame, offsets: list[dict], surface_e: float, surface_n: float,
                         samples: int = 80) -> tuple[float, str | None, float | None, float | None]:
    if not offsets:
        return float('inf'), None, None, None
    main_md = np.linspace(float(path.MD.iloc[0]), float(path.MD.iloc[-1]), max(10, samples))
    main_xyz = np.column_stack([_interp_path(path, c, main_md) for c in ('Easting', 'Northing', 'TVD')])
    main_xyz[:, 0] += surface_e
    main_xyz[:, 1] += surface_n
    best = (float('inf'), None, None, None)
    for offset in offsets:
        off_path = _offset_path(offset)
        if len(off_path) < 2:
            continue
        off_md = np.linspace(float(off_path.MD.iloc[0]), float(off_path.MD.iloc[-1]), max(10, samples))
        off_xyz = np.column_stack([_interp_path(off_path, c, off_md) for c in ('Easting', 'Northing', 'TVD')])
        diff = main_xyz[:, None, :] - off_xyz[None, :, :]
        dists = np.linalg.norm(diff, axis=2)
        i, j = np.unravel_index(int(np.argmin(dists)), dists.shape)
        if float(dists[i, j]) < best[0]:
            best = (float(dists[i, j]), str(offset.get('name', 'Offset')), float(main_md[i]), float(off_md[j]))
    return best




def _prepare_offsets(offsets, surface_n, surface_e):
    """Offset polylines [N, E, TVD] + MD, in the main-well frame (computed once, not per evaluation)."""
    prepared = []
    for off in offsets or []:
        p = _offset_path(off)
        if len(p) < 2:
            continue
        pts = np.column_stack([p['Northing'].to_numpy(float) - float(off.get('surface_northing_m', 0.0) or 0.0) * 0 ,
                               p['Easting'].to_numpy(float), p['TVD'].to_numpy(float)])
        # _offset_path already added the offset surface position; express the main well in the same frame
        pts = np.column_stack([p['Northing'].to_numpy(float), p['Easting'].to_numpy(float), p['TVD'].to_numpy(float)])
        prepared.append({'name': str(off.get('name', 'Offset')), 'pts': pts, 'md': p['MD'].to_numpy(float)})
    return prepared


def _polyline_distance(points: np.ndarray, pts: np.ndarray, md: np.ndarray):
    """Distance from each point to an offset polyline, and the offset MD at the closest point."""
    a, b = pts[:-1], pts[1:]
    ab = b - a
    denom = np.maximum(np.sum(ab * ab, axis=1), 1e-12)
    out_d = np.full(len(points), np.inf); out_md = np.zeros(len(points))
    for s in range(0, len(points), 128):
        q = points[s:s + 128, None, :]
        t = np.clip(np.sum((q - a[None]) * ab[None], axis=2) / denom[None], 0.0, 1.0)
        closest = a[None] + t[..., None] * ab[None]
        d = np.linalg.norm(q - closest, axis=2)
        j = np.argmin(d, axis=1); r = np.arange(len(j))
        out_d[s:s + 128] = d[r, j]
        out_md[s:s + 128] = md[:-1][j] + t[r, j] * (md[1:] - md[:-1])[j]
    return out_d, out_md


def _bearing(n, e):
    return math.degrees(math.atan2(e, n)) % 360.0 if abs(n) + abs(e) > 1e-9 else 0.0


def optimize_general_trajectory(*, targets: list[dict], max_md_m: float,
                                max_inclination_deg: float = 70.0,
                                max_dls_deg_30m: float = 3.0,
                                max_build_rate_deg_30m: float = 3.0,
                                max_turn_rate_deg_30m: float = 3.0,
                                station_interval_m: float = 30.0,
                                maxiter: int = 100,
                                surface_easting_m: float = 0.0,
                                surface_northing_m: float = 0.0,
                                offsets: list[dict] | None = None,
                                min_centerline_separation_m: float = 30.0,
                                required_separation_factor: float = 2.0,
                                uncertainty_parameters: dict | None = None,
                                target_tolerance_m: float = 30.48,
                                control_points: int = 6,
                                adaptive: bool = True,
                                min_control_points: int = 4,
                                max_control_points: int = 10,
                                time_budget_s: float = 90.0,
                                seed: int = 7,
                                kb_m: float | None = None,
                                min_kop_md_m: float | None = None,
                                max_kop_md_m: float | None = None) -> tuple[pd.DataFrame, dict]:
    """Optimize a free-form, piecewise directional trajectory to ordered targets.

    Distances are metres. Inclination and azimuth are control values interpolated along MD (control
    positions are themselves optimised when ``adaptive``) and integrated by minimum curvature.

    Search strategy (new): several physically motivated seeds (J-profile, shallow/steep ramps,
    per-target bearings, left/right detours around offsets) -> bounded L-BFGS-B from the best seeds ->
    if no valid candidate, the number of control points grows (``min_control_points`` ->
    ``max_control_points``) warm-started from the previous best, so the simplest feasible shape wins ->
    collision failures re-run with a larger uncertainty buffer -> a final centre-ward polish.

    ACCEPTANCE: a candidate is PASS only when ``core.validation.validate_trajectory`` passes on the
    arc-resampled path. The optimizer's own success flag, objective value or internal checks never
    decide validity. A failed search is reported as NO_FEASIBLE_CANDIDATE_FOUND (not a proof);
    ``core.feasibility.reachability_screen`` can additionally prove infeasibility analytically.
    """
    t_start = time.time()
    targets = [dict(t) for t in (targets or [])]
    offsets = list(offsets or [])
    if not targets:
        raise ValueError('General trajectory optimization requires at least one target.')
    if any(not all(k in t for k in ('tvd_m', 'north_m', 'east_m')) for t in targets):
        raise ValueError('Each target requires tvd_m, north_m and east_m in well-relative metres.')
    if max_md_m <= 0 or station_interval_m <= 0 or control_points < 4:
        raise ValueError('Maximum MD and station interval must be positive; use at least four control points.')
    if min(max_inclination_deg, max_dls_deg_30m, max_build_rate_deg_30m, max_turn_rate_deg_30m) <= 0:
        raise ValueError('Inclination, DLS, build-rate and turn-rate limits must be positive.')
    final = targets[-1]
    target_tvd = float(final['tvd_m'])
    if target_tvd <= 0:
        raise ValueError('Final target TVD must be positive.')
    if float(max_md_m) < target_tvd:
        raise ValueError('Maximum permitted MD is shallower than the final target TVD; no trajectory can reach that depth within the MD limit.')
    for t in targets:                                  # explicit per-target tolerance defaults
        t.setdefault('tolerance_m', float(target_tolerance_m))

    constraints = {'max_inclination_deg': float(max_inclination_deg), 'max_dls_deg_30m': float(max_dls_deg_30m),
                   'max_build_rate_deg_30m': float(max_build_rate_deg_30m), 'max_turn_rate_deg_30m': float(max_turn_rate_deg_30m),
                   'max_md_m': float(max_md_m)}
    if min_kop_md_m is not None: constraints['min_kop_md_m'] = float(min_kop_md_m)
    if max_kop_md_m is not None: constraints['max_kop_md_m'] = float(max_kop_md_m)
    sigma = dict(uncertainty_parameters or {})

    # ---- analytic necessary-condition screen: can PROVE infeasibility (a failed search cannot)
    screen = reachability_screen(targets, max_inclination_deg=max_inclination_deg, max_dls_deg_30m=max_dls_deg_30m,
                                 max_build_rate_deg_30m=max_build_rate_deg_30m, max_md_m=max_md_m,
                                 min_kop_md_m=float(min_kop_md_m or 0.0))

    lo_z = min(max(1.0, float(final['tvd_m']) - target_tolerances(final, target_tolerance_m)[1]), float(max_md_m))
    bearings = [_bearing(float(t['north_m']), float(t['east_m'])) for t in targets]
    final_bearing = bearings[-1]
    last_h = math.hypot(float(final['north_m']), float(final['east_m']))
    est_md = min(float(max_md_m), max(math.hypot(target_tvd, last_h) * 1.25 + 150.0, target_tvd * 1.15))
    count = int(max(25, min(300, math.ceil(est_md * 1.4 / station_interval_m) + 1)))

    # ---- offset-avoidance model used INSIDE the search only (final decision = independent validator)
    prepared = _prepare_offsets(offsets, surface_northing_m, surface_easting_m)
    s_surface = max(0.0, float(sigma.get('sigma_surface_ft', 5.0)) * 0.3048)
    s_inc = math.radians(max(0.0, float(sigma.get('sigma_inc_systematic_deg', sigma.get('sigma_inc_deg', 0.10)))))
    s_azi = math.radians(max(0.0, float(sigma.get('sigma_azi_systematic_deg', sigma.get('sigma_azi_deg', 0.25)))))
    theta = math.sqrt(s_inc ** 2 + s_azi ** 2)
    shift = np.array([float(surface_northing_m), float(surface_easting_m), 0.0])
    safety = {'value': 1.15}

    def collision_penalty(path):
        if not prepared:
            return 0.0
        pts = np.column_stack([path['Northing'].to_numpy(float), path['Easting'].to_numpy(float), path['TVD'].to_numpy(float)]) + shift
        md = path['MD'].to_numpy(float); total = 0.0
        for off in prepared:
            d, omd = _polyline_distance(pts, off['pts'], off['md'])
            sig = np.sqrt(2.0 * s_surface ** 2 + (md * theta) ** 2 + (omd * theta) ** 2)
            req = float(required_separation_factor) * safety['value'] * sig
            floor = np.where((md > 150.0) & (omd > 150.0), float(min_centerline_separation_m), 0.0)
            total += float(np.sum(np.maximum(0.0, np.maximum(req, floor) - d) ** 2))
        return total

    # ---- parameterisation -------------------------------------------------------------------
    def layout(N):
        return {'N': N, 'n_inc': N - 1, 'ia': 1, 'aa': 1 + (N - 1), 'wa': 1 + (N - 1) + N}

    def split(x, N):
        L = layout(N)
        end_md = float(x[0]); inc = np.concatenate(([0.0], np.asarray(x[1:L['aa']], float)))
        azi = np.asarray(x[L['aa']:L['wa']], float)
        w = np.asarray(x[L['wa']:L['wa'] + N - 1], float) if adaptive else np.ones(N - 1)
        frac = np.concatenate(([0.0], np.cumsum(w) / np.sum(w)))
        return end_md, inc, azi, frac

    def make_path(x, N):
        end_md, inc_c, azi_c, frac = split(x, N)
        mds = np.linspace(0.0, end_md, count)
        s = mds / end_md
        inc = np.interp(s, frac, inc_c)
        azi = np.degrees(np.interp(s, frac, np.unwrap(np.radians(azi_c)))) % 360.0
        return minimum_curvature(pd.DataFrame({'MD': mds, 'Inc': inc, 'Azi': azi}), dls_interval=30.0)

    def bounds_for(N):
        b = [(lo_z, float(max_md_m))] + [(0.0, float(max_inclination_deg))] * (N - 1) + [(final_bearing - 180.0, final_bearing + 180.0)] * N
        if adaptive:
            b += [(0.2, 5.0)] * (N - 1)
        return b

    def resample_x(x, N_from, N_to):
        """Re-express a solution with a different number of control points (same curve, more freedom)."""
        end_md, inc_c, azi_c, frac = split(x, N_from)
        new_frac = np.linspace(0.0, 1.0, N_to)
        inc_n = np.interp(new_frac, frac, inc_c)[1:]
        azi_n = np.degrees(np.interp(new_frac, frac, np.unwrap(np.radians(azi_c))))
        parts = [[end_md], inc_n, azi_n]
        if adaptive:
            parts.append(np.ones(N_to - 1))
        return np.concatenate(parts)

    def seeds(N):
        fr = np.linspace(0.0, 1.0, N)
        out = []
        imax = float(max_inclination_deg)
        base_az = np.full(N, final_bearing)
        if len(targets) > 1:                                  # bearing steers through the ordered targets
            pts = [(0.0, 0.0)] + [(float(t['north_m']), float(t['east_m'])) for t in targets]
            legs = [_bearing(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
            frac_leg = np.linspace(0.35, 0.85, len(legs))
            unwrapped = np.degrees(np.unwrap(np.radians(legs)))
            base_az = np.interp(fr, np.concatenate(([0.0], frac_leg)), np.concatenate(([unwrapped[0]], unwrapped)))
        for peak in sorted({min(imax, 65.0), min(imax, 45.0), min(imax, 30.0), min(imax, 80.0)}, reverse=True):
            ramp = np.linspace(0.0, peak, N)[1:]
            jprof = (peak * np.clip((fr - 0.12) / 0.30, 0.0, 1.0))[1:]
            for inc_c in (ramp, jprof):
                for md_scale in (1.0, 1.4):
                    out.append(np.concatenate(([min(max_md_m, max(lo_z, est_md * md_scale))], inc_c, base_az, np.ones(N - 1) if adaptive else [])))
        if prepared:                                          # swing left/right of the offsets early, then return
            for sgn in (1.0, -1.0):
                for amp in (20.0, 45.0, 80.0):
                    az = base_az + sgn * amp * np.sin(np.pi * np.clip(fr * 1.25, 0.0, 1.0))
                    for peak in (min(imax, 55.0), min(imax, 70.0)):
                        out.append(np.concatenate(([min(max_md_m, max(lo_z, est_md * 1.3))], np.linspace(0.0, peak, N)[1:], az, np.ones(N - 1) if adaptive else [])))
        rng = np.random.default_rng(seed)
        b = bounds_for(N)
        for _ in range(6):
            x = out[int(rng.integers(0, len(out)))].copy()
            x = x + rng.normal(0.0, 1.0, len(x)) * np.array([0.1 * est_md] + [6.0] * (N - 1) + [20.0] * N + ([0.3] * (N - 1) if adaptive else []))
            out.append(np.array([min(max(v, lo_), hi_) for v, (lo_, hi_) in zip(x, b)]))
        return out

    # ---- evaluation ---------------------------------------------------------------------------
    def target_metrics(path):
        results = []; previous_md = -1.0
        for index, t in enumerate(targets):
            tol_lat, tol_vert = target_tolerances(t, target_tolerance_m)
            if index == len(targets) - 1:
                end = path.iloc[-1]
                lat = math.hypot(float(end.Northing) - float(t['north_m']), float(end.Easting) - float(t['east_m']))
                vert = _plane_residual(float(end.Northing), float(end.Easting), float(end.TVD), t)
                miss = float(footprint_miss(t, [float(end.Northing)], [float(end.Easting)], target_tolerance_m)[0])
                md = float(end.MD)
            else:
                lat, vert, md, miss = _oriented_target_residual(path, t, target_tolerance_m)
            in_order = md > previous_md + 1e-3
            approach = _approach_metrics(path, md, t)
            results.append({'name': str(t.get('name', 'Target')), 'intercept_md_m': float(md), 'lateral_error_m': float(lat),
                            'vertical_error_m': float(vert), 'miss_distance_m': float(miss),
                            'within_tolerance': bool(miss <= 1e-3 and abs(vert) <= tol_vert), 'in_order': bool(in_order),
                            'vertical_tolerance_m': float(tol_vert), **approach})
            previous_md = md
        return results

    def evaluate(x, N):
        path = make_path(x, N)
        inc = path.Inc.to_numpy(float); azi = np.unwrap(np.radians(path.Azi.to_numpy(float)))
        md = path.MD.to_numpy(float); dmd = np.maximum(np.diff(md), 1e-9)
        dls = path.DLS.to_numpy(float)[1:]
        build = np.abs(np.diff(inc)) / dmd * 30.0
        turn = np.abs(np.degrees(np.diff(azi))) / dmd * 30.0
        results = target_metrics(path)
        score = 0.0
        center_dist = results[-1]['lateral_error_m']; depth_err = abs(results[-1]['vertical_error_m'])
        score += 100.0 * center_dist ** 2 + 100.0 * depth_err ** 2 + 0.02 * float(x[0])
        for r, t in zip(results, targets):
            tol_vert = r['vertical_tolerance_m']
            score += 1e5 * max(0.0, r['miss_distance_m']) ** 2 + 1e5 * max(0.0, abs(r['vertical_error_m']) - tol_vert) ** 2
            if not r['in_order']:
                score += 1e9
            if not r['approach_constraints_pass']:
                score += 1e5 * (r['approach_azimuth_error_deg'] ** 2 + r['approach_inclination_error_deg'] ** 2 + 100.0)
                if t.get('intersection_angle_enabled'):
                    angle = r['plane_intersection_angle_deg']
                    score += 1e5 * (max(0.0, float(t.get('min_intersection_angle_deg', 0.0)) - angle) ** 2 + max(0.0, angle - float(t.get('max_intersection_angle_deg', 90.0))) ** 2)
        margin = 0.995
        score += 1e5 * float(np.sum(np.maximum(0.0, dls - max_dls_deg_30m * margin) ** 2))
        score += 1e5 * float(np.sum(np.maximum(0.0, build - max_build_rate_deg_30m * margin) ** 2))
        score += 1e5 * float(np.sum(np.maximum(0.0, turn - max_turn_rate_deg_30m * margin) ** 2))
        score += 1e5 * float(np.sum(np.maximum(0.0, inc - max_inclination_deg * margin) ** 2))
        if min_kop_md_m is not None:
            first_build = md[np.argmax(inc > 0.5)] if (inc > 0.5).any() else md[-1]
            score += 1e5 * max(0.0, float(min_kop_md_m) - float(first_build)) ** 2
        score += 0.02 * float(np.sum(np.diff(inc, n=2) ** 2) + np.sum(np.diff(azi, n=2) ** 2) * 100.0)
        score += 2.0 * float(np.mean(dls ** 2)) if len(dls) else 0.0   # prefer gentler curvature among feasible shapes
        score += 1e5 * collision_penalty(path)
        viol = (not all(r['within_tolerance'] and r['in_order'] for r in results)) or dls.max(initial=0) > max_dls_deg_30m + 1e-3 \
            or build.max(initial=0) > max_build_rate_deg_30m + 1e-3 or turn.max(initial=0) > max_turn_rate_deg_30m + 1e-3 \
            or inc.max() > max_inclination_deg + 1e-3 or not all(r['approach_constraints_pass'] for r in results)
        return {'score': float(score), 'path': path, 'results': results, 'station_ok': not viol}

    def run_validation(path):
        return validate_trajectory(path[['MD', 'Inc', 'Azi']], targets=targets, constraints=constraints, offsets=offsets,
                                   surface_easting_m=surface_easting_m, surface_northing_m=surface_northing_m, kb_m=kb_m,
                                   survey_error_model=sigma, required_separation_factor=required_separation_factor,
                                   default_target_tolerance_m=target_tolerance_m)

    def local_solve(x0, N, iters, bnds=None):
        # Variables are rescaled (metres / degrees / weights have very different magnitudes) so the
        # quasi-Newton step sees a balanced problem; this markedly improves convergence.
        sc = np.array([100.0] + [10.0] * (N - 1) + [30.0] * N + ([1.0] * (N - 1) if adaptive else []))
        b = bnds or bounds_for(N)
        def f(u):
            try:
                return evaluate(u * sc, N)['score']
            except Exception:
                return 1e15
        res = minimize(f, np.asarray(x0, float) / sc, method='L-BFGS-B', bounds=[(lo_ / k, hi_ / k) for (lo_, hi_), k in zip(b, sc)],
                       options={'maxiter': int(iters), 'ftol': 1e-12, 'gtol': 1e-8, 'maxls': 30})
        res.x = res.x * sc
        return res

    def over_budget():
        return (time.time() - t_start) > float(time_budget_s)

    # ---- search -------------------------------------------------------------------------------
    stages = [int(control_points)] if not adaptive else sorted({n for n in (min_control_points, 6, 8, max_control_points) if min_control_points <= n <= max_control_points} | {int(control_points)})
    best = {'score': float('inf')}; accepted = None; history = []; total_iters = 0; total_solves = 0
    prev_x = prev_N = None
    skip_search = bool(screen['proven_infeasible'])
    for N in ([] if skip_search else stages):
        if over_budget():
            break
        cands = seeds(N)
        if prev_x is not None:
            cands.insert(0, resample_x(prev_x, prev_N, N))
        scored = []
        for x in cands:
            try:
                scored.append((evaluate(x, N)['score'], x))
            except Exception:
                continue
        scored.sort(key=lambda p: p[0])
        starts = [x for _, x in scored[:3]]
        stage_best = None
        for x0 in starts:                                   # compare every start: the first feasible one is rarely the best
            if over_budget() and stage_best is not None:
                break
            res = local_solve(x0, N, maxiter); total_iters += int(getattr(res, 'nit', 0)); total_solves += 1
            ev = evaluate(res.x, N)
            better = stage_best is None or (ev['station_ok'] and not stage_best[0]['station_ok']) or \
                (ev['station_ok'] == stage_best[0]['station_ok'] and ev['score'] < stage_best[0]['score'])
            if better:
                stage_best = (ev, res.x, res)
        if stage_best is None:
            continue
        ev, x_best, res = stage_best
        history.append({'control_points': N, 'objective': ev['score'], 'station_level_feasible': ev['station_ok']})
        if ev['score'] < best['score']:
            best = {'score': ev['score'], 'x': x_best, 'N': N, 'res': res, 'ev': ev}
        prev_x, prev_N = x_best, N
        if ev['station_ok']:
            val = run_validation(ev['path'])
            tries = 0
            while val['status'] != STATUS_PASS and tries < 3 and not over_budget() and prepared and \
                    set(val['violations']) <= {'anti_collision_review_required', 'anti_collision_cross_check'}:
                safety['value'] *= 1.5; tries += 1               # wider internal buffer, then re-solve from the best point
                res2 = local_solve(x_best, N, maxiter); total_iters += int(getattr(res2, 'nit', 0)); total_solves += 1
                ev = evaluate(res2.x, N); x_best, res = res2.x, res2
                if not ev['station_ok']:
                    break
                val = run_validation(ev['path'])
            if val['status'] == STATUS_PASS:
                accepted = {'x': x_best, 'N': N, 'ev': ev, 'val': val, 'res': res}
                break
            if ev['score'] < best['score']:
                best = {'score': ev['score'], 'x': x_best, 'N': N, 'res': res, 'ev': ev}

    # ---- challenger: one more control point (more shape freedom) may give a shorter / gentler plan.
    #      It replaces the simpler plan only if it validates AND wins after a complexity charge.
    complexity_charge = 3.0
    if accepted is not None and adaptive and not over_budget():
        bigger = [n for n in stages if n > accepted['N']]
        if bigger:
            N2 = bigger[0]
            try:
                cands = [resample_x(accepted['x'], accepted['N'], N2)] + seeds(N2)[:6]
                sc = sorted(((evaluate(x, N2)['score'], x) for x in cands), key=lambda p: p[0])
                res_c = local_solve(sc[0][1], N2, maxiter); total_iters += int(getattr(res_c, 'nit', 0)); total_solves += 1
                ev_c = evaluate(res_c.x, N2)
                history.append({'control_points': N2, 'objective': ev_c['score'], 'station_level_feasible': ev_c['station_ok'], 'role': 'challenger'})
                if ev_c['station_ok'] and ev_c['score'] + complexity_charge * N2 < accepted['ev']['score'] + complexity_charge * accepted['N'] - 1e-6:
                    v_c = run_validation(ev_c['path'])
                    if v_c['status'] == STATUS_PASS:
                        accepted = {'x': res_c.x, 'N': N2, 'ev': ev_c, 'val': v_c, 'res': res_c}
            except Exception:
                pass

    # ---- continuation polish: more iterations on the accepted solution (shorter / smoother / nearer the
    #      target centre). Kept only if the independent validation still passes AND the objective improves.
    if accepted is not None and not over_budget():
        N = accepted['N']
        try:
            res3 = local_solve(accepted['x'], N, int(maxiter) * 2); ev3 = evaluate(res3.x, N); total_iters += int(getattr(res3, 'nit', 0))
            if ev3['station_ok'] and ev3['score'] < accepted['ev']['score'] - 1e-6:
                v3 = run_validation(ev3['path'])
                if v3['status'] == STATUS_PASS:
                    accepted = {'x': res3.x, 'N': N, 'ev': ev3, 'val': v3, 'res': res3}
        except Exception:
            pass

    if skip_search:                                       # proven infeasible: still return a best-effort candidate for review
        N = int(control_points); x0 = seeds(N)[0]
        try:
            res0 = local_solve(x0, N, 25); best = {'x': res0.x, 'N': N, 'res': res0, 'ev': evaluate(res0.x, N), 'score': 0.0}
        except Exception:
            pass
    # ---- result assembly ----------------------------------------------------------------------
    if accepted is not None:
        chosen = accepted; val = accepted['val']; ev = accepted['ev']
        path = ev['path']
    else:
        if 'x' not in best:                                  # nothing evaluated (proven infeasible / no time)
            N = int(control_points); x0 = seeds(N)[0]; ev = evaluate(x0, N); best = {'x': x0, 'N': N, 'ev': ev, 'res': None}
        chosen = best; ev = best['ev']; path = ev['path']
        val = run_validation(path)
    outcome = search_outcome(val, search_completed=not over_budget(), proven_infeasible=bool(screen['proven_infeasible']))
    feasible = outcome['status'] == STATUS_PASS
    m = val['metrics']; target_results = val['target_results'] if val.get('target_results') else ev['results']
    # keep optimiser-internal station metrics in addition for transparency
    final_md = float(path.MD.iloc[-1])
    if feasible:
        try:
            path = truncate_trajectory_at_md(path, float(target_results[-1]['intercept_md_m']))
        except ValueError:
            pass
    # display window for failed candidates: ~100 ft beyond the relevant target approach (display only)
    clip_md = None
    if not feasible and target_results:
        bad = next((r for r in target_results if not (r.get('within_tolerance') and r.get('in_order'))), target_results[-1])
        if bad.get('intercept_md_m') is not None and np.isfinite(bad['intercept_md_m']):
            clip_md = float(bad['intercept_md_m']) + 30.48
    collision_rows = val.get('collision', [])
    checks_public = [{k: v for k, v in c.items()} for c in val['checks']]
    res_obj = chosen.get('res')
    meta = {
        'planner': 'General control-point trajectory optimizer (engineering-development)',
        'optimizer': 'Multi-seed SciPy L-BFGS-B penalty refinement with adaptive variable-inclination/azimuth control points, validated by core.validation',
        'optimization_status': outcome['optimization_status'],
        'status': outcome['status'],
        'result_class': 'PASS' if feasible else ('REVIEW' if outcome['optimization_status'] == 'INFEASIBLE_PROVEN' else 'NO FEASIBLE CANDIDATE FOUND'),
        'proof_of_infeasibility': screen if screen['proven_infeasible'] else None,
        'optimizer_success': bool(getattr(res_obj, 'success', False)) if res_obj is not None else False,
        'optimizer_message': str(getattr(res_obj, 'message', 'not run (analytic infeasibility screen fired)' if skip_search else 'not run')),
        'optimizer_iterations': int(total_iters), 'optimizer_solves': int(total_solves), 'objective_value': float(ev['score']),
        'search_history': history, 'search_seconds': round(time.time() - t_start, 2), 'search_budget_s': float(time_budget_s),
        'control_points_used': int(chosen['N']), 'adaptive_control_points': bool(adaptive),
        'target_sequence_results': target_results, 'required_target_count': len(targets),
        'target_sequence_feasible': all(r['within_tolerance'] and r['in_order'] for r in target_results),
        'constraint_violations': sorted(set(val['violations'])),
        'max_inclination_deg': float(m['max_inclination_deg']), 'max_dls_deg_30m': float(m['max_dls_deg_30m']),
        'max_build_rate_actual_deg_30m': float(m['max_build_rate_deg_30m']), 'max_turn_rate_actual_deg_30m': float(m['max_turn_rate_deg_30m']),
        'target_lateral_error_m': float(target_results[-1]['lateral_error_m']), 'target_vertical_error_m': float(target_results[-1]['vertical_error_m']),
        'target_miss_distance_m': float(target_results[-1]['miss_distance_m']), 'target_intercept_md_m': float(target_results[-1]['intercept_md_m']),
        'final_md_m': float(path.MD.iloc[-1]), 'final_md_is_target_intercept': bool(feasible),
        'final_inclination_deg': float(path.Inc.iloc[-1]), 'final_azimuth_deg': float(path.Azi.iloc[-1]),
        'endpoint_north_m': float(path.Northing.iloc[-1]), 'endpoint_east_m': float(path.Easting.iloc[-1]), 'endpoint_tvd_m': float(path.TVD.iloc[-1]),
        'control_points': int(chosen['N']), 'collision_screening_min_centerline_m': float(min_centerline_separation_m),
        'collision_screening_required_sf': float(required_separation_factor), 'collision_validation': collision_rows,
        'validation_status': val['status'], 'validation_checks': checks_public, 'validator_version': VALIDATOR_VERSION,
        'survey_hash': survey_hash(path[['MD', 'Inc', 'Azi']]), 'display_clip_md_m': clip_md,
        'uncertainty_note': 'Optimization uses a conservative approximate uncertainty buffer for route search; acceptance uses the independent covariance-based screening, which is development-grade, not ISCWSA-certified.',
    }
    return path, meta
