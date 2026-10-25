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

from core.trajectory import minimum_curvature, truncate_trajectory_at_md, lean_path, mc_core
from core.geometry import target_tolerances
from core.validation import (validate_trajectory, search_outcome, footprint_miss, survey_hash, STATUS_PASS,
                             STATUS_REVIEW, VALIDATOR_VERSION)
from core.feasibility import reachability_screen
from core.exact_targets import closest_point_on_path, POINT_NUMERIC_TOL_M, POINT_TARGET_ACCEPTANCE_TOL_M
from scipy.optimize import least_squares
from core.section_reconstruction import build_section_schedule, validate_section_schedule
from core.section_optimizer import reoptimize_sections
from core.kop import estimate_kop_md
import time


def _arr(path, name):
    """Float array for a path column; ``path`` may be a DataFrame or a plain dict of arrays (lean inner loop)."""
    return np.asarray(path[name], dtype=float)


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
    return np.interp(md, _arr(path, 'MD'), path[column].to_numpy(float))


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
    n = _arr(path, 'Northing'); e = _arr(path, 'Easting')
    tvd = _arr(path, 'TVD'); md = _arr(path, 'MD')
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
    inc = float(np.interp(md, _arr(path, 'MD'), _arr(path, 'Inc')))
    azis = np.unwrap(np.radians(_arr(path, 'Azi')))
    azi = float(np.degrees(np.interp(md, _arr(path, 'MD'), azis)) % 360.0)
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


def _path_summary(path, val):
    """Headline numbers of a path for the Stage-1 vs final comparison table."""
    m = val.get('metrics', {}) if val else {}
    return {'final_md_m': float(path.MD.iloc[-1]), 'final_tvd_m': float(path.TVD.iloc[-1]), 'max_inclination_deg': float(m.get('max_inclination_deg', path.Inc.max())),
            'max_dls_deg_30m': float(m.get('max_dls_deg_30m', path.DLS.max())), 'max_build_rate_deg_30m': float(m.get('max_build_rate_deg_30m', 0.0)),
            'max_turn_rate_deg_30m': float(m.get('max_turn_rate_deg_30m', 0.0)), 'kop_md_m': float(m.get('kop_md_m', 0.0)), 'stations': int(len(path)),
            'validation_status': (val or {}).get('status')}


def optimize_general_trajectory(*, targets: list[dict], max_md_m: float,
                                max_inclination_deg: float = 70.0,
                                max_dls_deg_30m: float = 3.0,
                                max_build_rate_deg_30m: float = 3.0,
                                max_drop_rate_deg_30m: float | None = None,
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
                                max_kop_md_m: float | None = None,
                                section_reoptimize: bool = True,
                                section_time_budget_s: float = 20.0,
                                section_max_md_increase_pct: float = 10.0) -> tuple[pd.DataFrame, dict]:
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
    # Directional-change-rate policy: max DLS is the sole rate constraint. Legacy rate arguments remain accepted for API compatibility but are not enforced.
    max_build_rate_deg_30m = float(max_dls_deg_30m)
    max_drop_rate_deg_30m = float(max_dls_deg_30m)
    max_turn_rate_deg_30m = float(max_dls_deg_30m)
    targets = [dict(t) for t in (targets or [])]
    offsets = list(offsets or [])
    if not targets:
        raise ValueError('General trajectory optimization requires at least one target.')
    if any(not all(k in t for k in ('tvd_m', 'north_m', 'east_m')) for t in targets):
        raise ValueError('Each target requires tvd_m, north_m and east_m in well-relative metres.')
    if max_md_m <= 0 or station_interval_m <= 0 or control_points < 4:
        raise ValueError('Maximum MD and station interval must be positive; use at least four control points.')
    if min(max_inclination_deg, max_dls_deg_30m) <= 0:
        raise ValueError('Inclination and DLS limits must be positive.')
    final = targets[-1]
    target_tvd = float(final['tvd_m'])
    if target_tvd <= 0:
        raise ValueError('Final target TVD must be positive.')
    if float(max_md_m) < target_tvd:
        raise ValueError('Maximum permitted MD is shallower than the final target TVD; no trajectory can reach that depth within the MD limit.')
    for t in targets:                                  # explicit per-target tolerance defaults
        t.setdefault('tolerance_m', float(target_tolerance_m))

    constraints = {'max_inclination_deg': float(max_inclination_deg), 'max_dls_deg_30m': float(max_dls_deg_30m), 'max_md_m': float(max_md_m)}
    if min_kop_md_m is not None: constraints['min_kop_md_m'] = float(min_kop_md_m)
    if max_kop_md_m is not None: constraints['max_kop_md_m'] = float(max_kop_md_m)
    # Hard-KOP mode: when bounds are supplied, choose a deterministic KOP inside
    # the interval and structurally keep the path vertical through that MD. The
    # lower bound is used when both bounds exist (earliest allowed build onset).
    planned_kop_md_m = None
    if min_kop_md_m is not None or max_kop_md_m is not None:
        planned_kop_md_m = float(min_kop_md_m if min_kop_md_m is not None else max_kop_md_m)
        if planned_kop_md_m < 0 or planned_kop_md_m >= float(max_md_m):
            raise ValueError('KOP must be non-negative and shallower than the maximum permitted MD.')
        constraints['planned_kop_md_m'] = planned_kop_md_m
    sigma = dict(uncertainty_parameters or {})

    # ---- analytic necessary-condition screen: can PROVE infeasibility (a failed search cannot)
    screen = reachability_screen(targets, max_inclination_deg=max_inclination_deg, max_dls_deg_30m=max_dls_deg_30m,
                                 max_md_m=max_md_m,
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
        pts = np.column_stack([_arr(path, 'Northing'), _arr(path, 'Easting'), _arr(path, 'TVD')]) + shift
        md = _arr(path, 'MD'); total = 0.0
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
        if planned_kop_md_m is not None:
            # The path must reach KOP before it can deviate. Ensure the candidate
            # endpoint lies beyond KOP and include KOP as an exact survey station.
            end_md = max(end_md, planned_kop_md_m + 1e-6)
        mds = np.linspace(0.0, end_md, count)
        if planned_kop_md_m is not None:
            mds = np.unique(np.concatenate([mds, [planned_kop_md_m]]))
            post_span = max(end_md - planned_kop_md_m, 1e-9)
            post_s = np.clip((mds - planned_kop_md_m) / post_span, 0.0, 1.0)
            # Inclination controls are mapped over the post-KOP interval; the
            # first control is exactly vertical at KOP and all pre-KOP inclinations
            # are structurally fixed to zero (not encouraged by a penalty).
            inc = np.where(mds <= planned_kop_md_m, 0.0, np.interp(post_s, frac, inc_c))
        else:
            inc = np.interp(mds / end_md, frac, inc_c)
        if planned_kop_md_m is not None:
            # Azimuth is undefined on a vertical well. Carry a constant reference
            # bearing through the vertical section; only allow steering at/after KOP.
            # Interpolate steering controls over the post-KOP interval, not full MD.
            post_azi = np.degrees(np.interp(post_s, frac, np.unwrap(np.radians(azi_c)))) % 360.0
            azi = np.where(mds < planned_kop_md_m, float(final_bearing) % 360.0, post_azi)
        else:
            azi = np.degrees(np.interp(mds / end_md, frac, np.unwrap(np.radians(azi_c)))) % 360.0
        n_, e_, z_, d_ = mc_core(mds, inc, azi, 30.0)    # numpy kernel: identical numbers, ~15x cheaper than a validated DataFrame call
        return {'MD': mds, 'Inc': inc, 'Azi': azi, 'Northing': n_, 'Easting': e_, 'TVD': z_, 'DLS': d_}

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
        if len(targets) > 1:                                  # bearings steer through the ordered targets
            pts = [(0.0, 0.0)] + [(float(t['north_m']), float(t['east_m'])) for t in targets]
            legs = [_bearing(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
            unwrapped = np.degrees(np.unwrap(np.radians(legs)))
            # Build several distinct target-directed azimuth schedules. A single
            # generic schedule can steer toward the final target too early and
            # trap a local optimizer in a basin that misses an earlier waypoint.
            depth_marks = np.asarray([max(1.0, float(t.get('tvd_m', 0.0))) for t in targets], dtype=float)
            if depth_marks.size and depth_marks[-1] > 0:
                raw_depth_fracs = np.clip(depth_marks / max(float(final['tvd_m']), 1.0), 0.12, 0.94)
                # Keep interpolation knots strictly increasing even for targets at
                # similar TVDs or targets whose TVD ordering is non-monotonic.
                index_fracs = np.linspace(0.25, 0.88, len(targets))
                depth_fracs = np.maximum.accumulate(0.65 * raw_depth_fracs + 0.35 * index_fracs)
                for j in range(1, len(depth_fracs)):
                    depth_fracs[j] = max(depth_fracs[j], depth_fracs[j - 1] + 0.015)
                if depth_fracs[-1] > 0.96:
                    depth_fracs = np.linspace(0.25, 0.92, len(targets))
            else:
                depth_fracs = np.linspace(0.3, 0.85, len(targets))
            fallback_fracs = np.linspace(0.35, 0.85, len(legs))
            # First schedule follows the approximate depth of each required target;
            # other schedules deliberately delay/advance the turns to diversify starts.
            for shift_frac in (0.0, -0.12, 0.12):
                marks = np.clip(depth_fracs + shift_frac, 0.08, 0.96)
                x_marks = np.concatenate(([0.0], marks))
                y_marks = np.concatenate(([unwrapped[0]], unwrapped))
                if len(x_marks) > 1:
                    base_az = np.interp(fr, x_marks, y_marks)
                    # Keep the schedules distinct; optimizer can refine them afterward.
                    if shift_frac == 0.0:
                        target_azimuth_schedules = [base_az.copy()]
                    else:
                        target_azimuth_schedules.append(base_az.copy())
            if 'target_azimuth_schedules' not in locals() or not target_azimuth_schedules:
                target_azimuth_schedules = [np.interp(fr, np.concatenate(([0.0], fallback_fracs)),
                    np.concatenate(([unwrapped[0]], unwrapped))) ]
        else:
            target_azimuth_schedules = [base_az.copy()]
        for peak in sorted({min(imax, 65.0), min(imax, 45.0), min(imax, 30.0), min(imax, 80.0)}, reverse=True):
            ramp = np.linspace(0.0, peak, N)[1:]
            jprof = (peak * np.clip((fr - 0.12) / 0.30, 0.0, 1.0))[1:]
            for inc_c in (ramp, jprof):
                for md_scale in (1.0, 1.4):
                    for az_schedule in target_azimuth_schedules:
                        out.append(np.concatenate(([min(max_md_m, max(lo_z, est_md * md_scale))], inc_c, az_schedule, np.ones(N - 1) if adaptive else [])))
        # KOP-aware patterns: stay vertical until the (minimum) KOP, then build - and a build-hold-build variant.
        kop_fracs = {0.12, 0.25}
        if min_kop_md_m:
            kop_fracs |= {min(0.8, 1.05 * float(min_kop_md_m) / max(est_md, 1.0)), min(0.8, 1.35 * float(min_kop_md_m) / max(est_md, 1.0))}
        for kf in sorted(kop_fracs):
            for peak in sorted({min(imax, 60.0), min(imax, 40.0)}, reverse=True):
                for width in (0.25, 0.5):
                    delayed = (peak * np.clip((fr - kf) / width, 0.0, 1.0))[1:]
                    bhb = delayed + 0.35 * peak * np.clip((fr - (kf + width + 0.12)) / 0.3, 0.0, 1.0)[1:]
                    for inc_c in (delayed, np.minimum(bhb, min(imax, 85.0))):
                        out.append(np.concatenate(([min(max_md_m, max(lo_z, est_md * 1.15))], inc_c, target_azimuth_schedules[0], np.ones(N - 1) if adaptive else [])))
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
    def is_point(t):
        return str((t.get('geometry') or t).get('type', 'Point')).lower() == 'point'
    has_point = any(is_point(t) for t in targets)

    def target_metrics(path, exact=False):
        results = []; previous_md = -1.0
        for index, t in enumerate(targets):
            tol_lat, tol_vert = target_tolerances(t, target_tolerance_m)
            if exact and is_point(t):
                # continuous closest approach on the arcs (3-D distance); no engineering radius
                pr = closest_point_on_path(path, [float(t['north_m']), float(t['east_m']), float(t['tvd_m'])], start_md=previous_md,
                                           endpoint_only=(index == len(targets) - 1))
                if pr is None:
                    results.append({'name': str(t.get('name', 'Target')), 'intercept_md_m': float('nan'), 'lateral_error_m': 1e6, 'vertical_error_m': 1e6,
                                    'miss_distance_m': 1e6, 'within_tolerance': False, 'in_order': False, 'vertical_tolerance_m': POINT_TARGET_ACCEPTANCE_TOL_M, 'acceptance_tolerance_m': POINT_TARGET_ACCEPTANCE_TOL_M,
                                    'approach_constraints_pass': False, 'approach_azimuth_error_deg': 0.0, 'approach_inclination_error_deg': 0.0, 'plane_intersection_angle_deg': 0.0})
                    continue
                md = pr['md']; approach = _approach_metrics(path, md, t)
                results.append({'name': str(t.get('name', 'Target')), 'intercept_md_m': float(md), 'lateral_error_m': pr['lateral_m'], 'vertical_error_m': pr['vertical_m'],
                                'miss_distance_m': pr['distance_m'], 'within_tolerance': bool(pr['distance_m'] <= POINT_TARGET_ACCEPTANCE_TOL_M), 'in_order': True,
                                'vertical_tolerance_m': POINT_TARGET_ACCEPTANCE_TOL_M, 'acceptance_tolerance_m': POINT_TARGET_ACCEPTANCE_TOL_M, 'exact_point_target': True, **approach})
                previous_md = md
                continue
            if index == len(targets) - 1:
                eN, eE, eZ, md = float(_arr(path, 'Northing')[-1]), float(_arr(path, 'Easting')[-1]), float(_arr(path, 'TVD')[-1]), float(_arr(path, 'MD')[-1])
                lat = math.hypot(eN - float(t['north_m']), eE - float(t['east_m']))
                vert = _plane_residual(eN, eE, eZ, t)
                miss = float(footprint_miss(t, [eN], [eE], target_tolerance_m)[0])
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

    def evaluate(x, N, exact=False):
        path = make_path(x, N)
        inc = _arr(path, 'Inc'); azi = np.unwrap(np.radians(_arr(path, 'Azi')))
        md = _arr(path, 'MD'); dmd = np.maximum(np.diff(md), 1e-9)
        dls = _arr(path, 'DLS')[1:]
        inc_rate = np.diff(inc) / dmd * 30.0
        build = np.maximum(inc_rate, 0.0)
        drop = np.maximum(-inc_rate, 0.0)
        turn = np.abs(np.degrees(np.diff(azi))) / dmd * 30.0
        results = target_metrics(path, exact=exact and has_point)
        score = 0.0
        center_dist = results[-1]['lateral_error_m']; depth_err = abs(results[-1]['vertical_error_m'])
        score += 100.0 * center_dist ** 2 + 100.0 * depth_err ** 2 + 0.02 * float(x[0])
        sequence_misses = []
        for target_index, (r, t) in enumerate(zip(results, targets)):
            tol_vert = r['vertical_tolerance_m']
            # Required targets are lexicographically prioritized: missing an early
            # target is more expensive than a comparable miss at a later target.
            # This is still a penalty-based search, so independent validation remains
            # the only acceptance gate.
            sequence_weight = float((len(targets) - target_index) ** 2)
            lateral_miss = max(0.0, float(r['miss_distance_m']))
            vertical_miss = max(0.0, abs(float(r['vertical_error_m'])) - tol_vert)
            sequence_misses.append(max(lateral_miss, vertical_miss))
            score += sequence_weight * 1e8 * lateral_miss ** 2
            score += sequence_weight * 1e8 * vertical_miss ** 2
            if not r['in_order']:
                score += 1e12 * (target_index + 1)
            # Every target's approach constraints must contribute to the search
            # objective; validation remains the final hard acceptance gate.
            if not r['approach_constraints_pass']:
                score += sequence_weight * 1e5 * (r['approach_azimuth_error_deg'] ** 2 + r['approach_inclination_error_deg'] ** 2 + 100.0)
                if t.get('intersection_angle_enabled'):
                    angle = r['plane_intersection_angle_deg']
                    score += sequence_weight * 1e5 * (max(0.0, float(t.get('min_intersection_angle_deg', 0.0)) - angle) ** 2 + max(0.0, angle - float(t.get('max_intersection_angle_deg', 90.0))) ** 2)
        if sequence_misses:
            # Strongly discourage sacrificing any required waypoint to improve the terminal objective.
            score += 1e8 * max(sequence_misses) ** 2
        margin = 0.995
        score += 1e5 * float(np.sum(np.maximum(0.0, dls - max_dls_deg_30m * margin) ** 2))
        score += 1e5 * float(np.sum(np.maximum(0.0, inc - max_inclination_deg * margin) ** 2))
        kop_md = estimate_kop_md(md, inc, build_rate_threshold_deg_30m=0.02, sustained_intervals=2)
        kop_bad = False
        if min_kop_md_m is not None:
            score += 1e5 * max(0.0, float(min_kop_md_m) - kop_md) ** 2
            kop_bad = kop_bad or kop_md < float(min_kop_md_m) - 1e-3
        if max_kop_md_m is not None:
            score += 1e5 * max(0.0, kop_md - float(max_kop_md_m)) ** 2
            kop_bad = kop_bad or kop_md > float(max_kop_md_m) + 1e-3
        score += 0.02 * float(np.sum(np.diff(inc, n=2) ** 2) + np.sum(np.diff(azi, n=2) ** 2) * 100.0)
        score += 2.0 * float(np.mean(dls ** 2)) if len(dls) else 0.0   # prefer gentler curvature among feasible shapes
        score += 1e5 * collision_penalty(path)
        viol = (not all(r['within_tolerance'] and r['in_order'] for r in results)) or dls.max(initial=0) > max_dls_deg_30m + 1e-3 \
            or inc.max() > max_inclination_deg + 1e-3 or not all(r['approach_constraints_pass'] for r in results) or kop_bad
        return {'score': float(score), 'path': path, 'results': results, 'station_ok': not viol}

    def run_validation(path):
        return validate_trajectory(pd.DataFrame({k: _arr(path, k) for k in ('MD', 'Inc', 'Azi')}), targets=targets, constraints=constraints, offsets=offsets,
                                   surface_easting_m=surface_easting_m, surface_northing_m=surface_northing_m, kb_m=kb_m,
                                   survey_error_model=sigma, required_separation_factor=required_separation_factor,
                                   default_target_tolerance_m=target_tolerance_m)

    def local_solve(x0, N, iters, bnds=None):
        # Variables are rescaled (metres / degrees / weights have very different magnitudes) so the
        # quasi-Newton step sees a balanced problem; this markedly improves convergence.
        sc = np.array([100.0] + [10.0] * (N - 1) + [30.0] * N + ([1.0] * (N - 1) if adaptive else []))
        b = bnds or bounds_for(N)
        def f(u):
            if time.time() - t_start >= float(time_budget_s):
                return 1e15
            try:
                return evaluate(u * sc, N)['score']          # chord-level (fast) inside the search
            except Exception:
                return 1e15
        def stop_at_global_deadline(_xk):
            # SciPy treats StopIteration from a callback as a controlled early stop.
            if time.time() - t_start >= float(time_budget_s):
                raise StopIteration
        res = minimize(f, np.asarray(x0, float) / sc, method='L-BFGS-B', bounds=[(lo_ / k, hi_ / k) for (lo_, hi_), k in zip(b, sc)],
                       callback=stop_at_global_deadline,
                       options={'maxiter': int(iters), 'ftol': 1e-12, 'gtol': 1e-8, 'maxls': 30})
        res.x = res.x * sc
        return res

    def exact_polish(x0, N, iters=80):
        """Closure step: least-squares on the exact (arc) point-target residuals, minimal change to the design.

        Residuals are (path - target) components at the continuous closest approach for every point target, plus
        hinge terms for rate/inclination limits and a weak pull toward the starting design. Point targets are
        driven to floating-point closure; non-point targets contribute only footprint/vertical excess.
        """
        sc = np.array([100.0] + [10.0] * (N - 1) + [30.0] * N + ([1.0] * (N - 1) if adaptive else []))
        b = bounds_for(N); lo = np.array([bb[0] for bb in b]) / sc; hi = np.array([bb[1] for bb in b]) / sc
        u0 = np.clip(np.asarray(x0, float) / sc, lo, hi)

        def resid(u):
            if time.time() - t_start >= float(time_budget_s):
                raise TimeoutError('Global optimizer time budget exhausted during exact-target polishing.')
            path = make_path(u * sc, N); res = []; prev = -1.0
            for index, t in enumerate(targets):
                last = index == len(targets) - 1
                if is_point(t):
                    pr = closest_point_on_path(path, [float(t['north_m']), float(t['east_m']), float(t['tvd_m'])], start_md=prev, endpoint_only=last)
                    if pr is None:
                        res += [1e3, 1e3, 1e3]; continue
                    res += [pr['d_north'], pr['d_east'], pr['d_tvd']]; prev = pr['md']
                else:
                    if last:
                        eN, eE, eZ, md_t = (float(_arr(path, c)[-1]) for c in ('Northing', 'Easting', 'TVD', 'MD'))
                        miss = float(footprint_miss(t, [eN], [eE], target_tolerance_m)[0]); vert = _plane_residual(eN, eE, eZ, t)
                    else:
                        _, vert, md_t, miss = _oriented_target_residual(path, t, target_tolerance_m)
                    res += [miss, max(0.0, abs(vert) - target_tolerances(t, target_tolerance_m)[1])]; prev = md_t
            inc = _arr(path, 'Inc'); azi = np.unwrap(np.radians(_arr(path, 'Azi'))); md = _arr(path, 'MD'); dmd = np.maximum(np.diff(md), 1e-9)
            res += list(10.0 * np.maximum(0.0, _arr(path, 'DLS')[1:] - max_dls_deg_30m * 0.999))
            res += list(10.0 * np.maximum(0.0, inc - max_inclination_deg * 0.999))
            res += list(0.02 * (u - u0))
            return np.asarray(res, float)
        try:
            sol = least_squares(resid, u0, bounds=(lo, hi), method='trf', xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=int(iters))
            return sol.x * sc
        except Exception:
            return np.asarray(x0, float)

    def settle(x, N):
        """Exact-mode evaluation; if a point target is not yet closed, apply the closure step and keep it if better."""
        ev = evaluate(x, N, exact=True)
        if has_point and not ev['station_ok']:
            worst = max((r['miss_distance_m'] for r in ev['results'] if not r['within_tolerance']), default=0.0)
            if worst < 250.0:
                xp = exact_polish(x, N); evp = evaluate(xp, N, exact=True)
                if evp['station_ok'] or evp['score'] < ev['score']:
                    return evp, xp
        return ev, np.asarray(x, float)

    def target_vectors(path):
        """Constraint vectors for the Stage-2 section optimizer (exact point equalities, areal margins, centre preference)."""
        eq = []; ineq = []; pen = 0.0; prev = -1.0
        for index, t in enumerate(targets):
            last = index == len(targets) - 1
            if is_point(t):
                pr = closest_point_on_path(path, [float(t['north_m']), float(t['east_m']), float(t['tvd_m'])], start_md=prev, endpoint_only=last)
                if pr is None:
                    eq += [1e3, 1e3, 1e3]; continue
                eq += [pr['d_north'], pr['d_east'], pr['d_tvd']]; prev = pr['md']
            else:
                if last:
                    eN, eE, eZ, md_t = (float(_arr(path, c)[-1]) for c in ('Northing', 'Easting', 'TVD', 'MD'))
                    miss = float(footprint_miss(t, [eN], [eE], target_tolerance_m)[0]); vert = _plane_residual(eN, eE, eZ, t)
                    lat = math.hypot(eN - float(t['north_m']), eE - float(t['east_m']))
                else:
                    lat, vert, md_t, miss = _oriented_target_residual(path, t, target_tolerance_m)
                tv = target_tolerances(t, target_tolerance_m)[1]
                ineq += [-miss, 0.9 * tv - abs(vert)]; pen += 0.02 * lat ** 2; prev = md_t
        return eq, ineq, pen

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
            if over_budget():
                break
            try:
                scored.append((evaluate(x, N)['score'], x))
            except Exception:
                continue
        scored.sort(key=lambda p: p[0])
        # Explore the full shortlist (up to six starts). A preliminary-feasible
        # candidate is not enough: each candidate must pass the independent
        # validator, otherwise the search continues to the next start.
        starts = [x for _, x in scored[:6]]
        stage_best = None
        validated_candidates = []
        for x0 in starts:
            if over_budget():
                break
            res = local_solve(x0, N, maxiter)
            total_iters += int(getattr(res, 'nit', 0)); total_solves += 1
            ev, xs = settle(res.x, N); res.x = xs
            better = stage_best is None or (ev['station_ok'] and not stage_best[0]['station_ok']) or \
                (ev['station_ok'] == stage_best[0]['station_ok'] and ev['score'] < stage_best[0]['score'])
            if better:
                stage_best = (ev, res.x, res)
            if ev['station_ok']:
                validated_candidates.append((ev['score'], ev, res.x, res))
        if stage_best is None:
            continue
        if not stage_best[0]['station_ok'] and not over_budget():
            # Bounded recovery: nudge inclination/azimuth of the best infeasible design inside the variable bounds and re-solve.
            rng_n = np.random.default_rng(seed + 17 * N); b_n = bounds_for(N)
            for scale in (0.5, 1.0, 1.6, 2.4):
                if over_budget(): break
                xn = np.asarray(stage_best[1], float).copy()
                xn[1:N] += rng_n.normal(0.0, 4.0 * scale, N - 1)           # inclination nudge (deg)
                xn[N:2 * N] += rng_n.normal(0.0, 8.0 * scale, N)           # azimuth nudge (deg)
                xn[0] *= 1.0 + rng_n.normal(0.0, 0.06 * scale)             # MD nudge
                xn = np.array([min(max(v, lo_), hi_) for v, (lo_, hi_) in zip(xn, b_n)])
                resn = local_solve(xn, N, maxiter); total_iters += int(getattr(resn, 'nit', 0)); total_solves += 1
                evn, xsn = settle(resn.x, N); resn.x = xsn
                if (evn['station_ok'] and not stage_best[0]['station_ok']) or (evn['station_ok'] == stage_best[0]['station_ok'] and evn['score'] < stage_best[0]['score']):
                    stage_best = (evn, resn.x, resn)
                if stage_best[0]['station_ok']:
                    break
        ev, x_best, res = stage_best
        history.append({'control_points': N, 'objective': ev['score'], 'station_level_feasible': ev['station_ok']})
        if ev['score'] < best['score']:
            best = {'score': ev['score'], 'x': x_best, 'N': N, 'res': res, 'ev': ev}
        prev_x, prev_N = x_best, N
        # Validate each preliminary-feasible candidate in score order. If one fails
        # independent validation, do not let it hide a later candidate that passes.
        for _, ev_cand, x_cand, res_cand in sorted(validated_candidates, key=lambda q: q[0]):
            if over_budget():
                break
            val_cand = run_validation(ev_cand['path'])
            if val_cand['status'] == STATUS_PASS:
                accepted = {'x': x_cand, 'N': N, 'ev': ev_cand, 'val': val_cand, 'res': res_cand}
                break
            # A narrowly scoped collision recovery may retry the same candidate,
            # but never relaxes final validation requirements.
            tries = 0
            while val_cand['status'] != STATUS_PASS and tries < 2 and not over_budget() and prepared and \
                    set(val_cand['violations']) <= {'anti_collision_review_required', 'anti_collision_cross_check'}:
                safety['value'] *= 1.5; tries += 1
                res2 = local_solve(x_cand, N, maxiter); total_iters += int(getattr(res2, 'nit', 0)); total_solves += 1
                ev2, x2 = settle(res2.x, N); res2.x = x2
                if not ev2['station_ok']:
                    break
                val_cand = run_validation(ev2['path'])
                if val_cand['status'] == STATUS_PASS:
                    accepted = {'x': x2, 'N': N, 'ev': ev2, 'val': val_cand, 'res': res2}
                    break
                x_cand, ev_cand, res_cand = x2, ev2, res2
            if accepted is not None:
                break
        if accepted is not None:
            break
        if stage_best[0]['score'] < best['score']:
            best = {'score': stage_best[0]['score'], 'x': stage_best[1], 'N': N, 'res': stage_best[2], 'ev': stage_best[0]}

    # ---- Stage 2: section reconstruction + re-optimisation (only from a validated Stage-1 plan) ------------
    section_result = {'attempted': False, 'status': 'NOT_ATTEMPTED_INFEASIBLE_BASE' if accepted is None else 'NOT_REQUESTED'}
    baseline_metrics = None
    if accepted is not None:
        stage1_df = minimum_curvature(pd.DataFrame({k: accepted['ev']['path'][k] for k in ('MD', 'Inc', 'Azi')}))
        baseline_metrics = _path_summary(stage1_df, accepted['val'])
        if section_reoptimize:
            limits = {'max_inclination_deg': max_inclination_deg, 'max_dls_deg_30m': max_dls_deg_30m, 'max_md_m': max_md_m, 'min_kop_md_m': min_kop_md_m}
            remaining_global_s = max(0.0, float(time_budget_s) - (time.time() - t_start))
            allocated_section_s = min(float(section_time_budget_s), remaining_global_s)
            if allocated_section_s > 0.5:
                section_result = reoptimize_sections(stage1_df, target_vectors=target_vectors, validate=run_validation, limits=limits, interval_m=station_interval_m,
                                                     time_budget_s=allocated_section_s, max_md_increase_pct=section_max_md_increase_pct)
            else:
                section_result = {'attempted': False, 'adopted': False, 'status': 'SKIPPED_TIME_BUDGET', 'message': 'No global search time remained for section reconstruction.'}
            if section_result.get('adopted'):
                accepted = {**accepted, 'val': section_result['validation'], 'section_path': section_result['path']}

    # ---- challenger: one more control point (more shape freedom) may give a shorter / gentler plan.
    #      It replaces the simpler plan only if it validates AND wins after a complexity charge.
    complexity_charge = 3.0
    stage2_adopted = bool(section_result.get('adopted'))
    if accepted is not None and adaptive and not over_budget() and not stage2_adopted:
        bigger = [n for n in stages if n > accepted['N']]
        if bigger:
            N2 = bigger[0]
            try:
                cands = [resample_x(accepted['x'], accepted['N'], N2)] + seeds(N2)[:6]
                sc = []
                for x in cands:
                    if over_budget():
                        break
                    try:
                        sc.append((evaluate(x, N2)['score'], x))
                    except Exception:
                        continue
                if not sc:
                    raise TimeoutError('Global search budget exhausted before challenger evaluation.')
                sc.sort(key=lambda p: p[0])
                res_c = local_solve(sc[0][1], N2, maxiter); total_iters += int(getattr(res_c, 'nit', 0)); total_solves += 1
                ev_c, xc = settle(res_c.x, N2); res_c.x = xc
                history.append({'control_points': N2, 'objective': ev_c['score'], 'station_level_feasible': ev_c['station_ok'], 'role': 'challenger'})
                if ev_c['station_ok'] and ev_c['score'] + complexity_charge * N2 < accepted['ev']['score'] + complexity_charge * accepted['N'] - 1e-6:
                    v_c = run_validation(ev_c['path'])
                    if v_c['status'] == STATUS_PASS:
                        accepted = {'x': res_c.x, 'N': N2, 'ev': ev_c, 'val': v_c, 'res': res_c}
            except Exception:
                pass

    # ---- continuation polish: more iterations on the accepted solution (shorter / smoother / nearer the
    #      target centre). Kept only if the independent validation still passes AND the objective improves.
    if accepted is not None and not over_budget() and not stage2_adopted:
        N = accepted['N']
        try:
            res3 = local_solve(accepted['x'], N, int(maxiter) * 2); ev3, x3 = settle(res3.x, N); res3.x = x3; total_iters += int(getattr(res3, 'nit', 0))
            if ev3['station_ok'] and ev3['score'] < accepted['ev']['score'] - 1e-6:
                v3 = run_validation(ev3['path'])
                if v3['status'] == STATUS_PASS:
                    accepted = {'x': res3.x, 'N': N, 'ev': ev3, 'val': v3, 'res': res3}
        except Exception:
            pass

    if skip_search:                                       # proven infeasible: still return a best-effort candidate for review
        N = int(control_points); x0 = seeds(N)[0]
        try:
            res0 = local_solve(x0, N, 25); best = {'x': res0.x, 'N': N, 'res': res0, 'ev': evaluate(res0.x, N, exact=True), 'score': 0.0}
        except Exception:
            pass
    # ---- result assembly ----------------------------------------------------------------------
    if accepted is not None:
        chosen = accepted; val = accepted['val']; ev = accepted['ev']
        path = minimum_curvature(accepted['section_path'] if 'section_path' in accepted else pd.DataFrame({k: ev['path'][k] for k in ('MD', 'Inc', 'Azi')}))      # full column set for callers
    else:
        if 'x' not in best:                                  # nothing evaluated (proven infeasible / no time)
            N = int(control_points); x0 = seeds(N)[0]; ev = evaluate(x0, N, exact=True); best = {'x': x0, 'N': N, 'ev': ev, 'res': None}
        chosen = best; ev = best['ev']; path = minimum_curvature(pd.DataFrame({k: ev['path'][k] for k in ('MD', 'Inc', 'Azi')}))
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
    # Single-target failures can be clipped near their approach for readability.
    # For multi-target failures, retain the full best-effort candidate so the user
    # can inspect why a later target was not reached; do not visually imply that
    # the well plan physically terminates at the first failed target.
    clip_md = None
    if not feasible and len(targets) == 1 and target_results:
        bad = next((r for r in target_results if not (r.get('within_tolerance') and r.get('in_order'))), target_results[-1])
        if bad.get('intercept_md_m') is not None and np.isfinite(bad['intercept_md_m']):
            clip_md = float(bad['intercept_md_m']) + 30.48
    collision_rows = val.get('collision', [])
    checks_public = [{k: v for k, v in c.items()} for c in val['checks']]
    res_obj = chosen.get('res')
    if section_result.get('adopted'):
        section_schedule = []
        md_arr = path.MD.to_numpy(float); dls_arr = path.DLS.to_numpy(float)
        for row in section_result['schedule']:
            sel = (md_arr > row['start_md_m'] + 1e-6) & (md_arr <= row['end_md_m'] + 1e-6)
            section_schedule.append({**row, 'max_dls_deg_30m': float(dls_arr[sel].max()) if sel.any() else 0.0})
        sec_status = 'REOPTIMIZED'
    else:
        section_schedule = build_section_schedule(path, max_dls_deg_30m=max_dls_deg_30m)
        sec_status = section_result.get('status') if feasible else 'NOT_ATTEMPTED_INFEASIBLE_BASE'
        if feasible and not section_reoptimize:
            sec_status = 'CLASSIFIED_ONLY'
    section_check = validate_section_schedule(section_schedule, max_dls_deg_30m=max_dls_deg_30m)
    final_metrics = _path_summary(path, val)
    meta = {
        'planner': 'Independent profile-free control-point trajectory optimizer (engineering-development)',
        'optimizer_mode': 'independent_profile_free', 'random_seed': int(seed),
        'section_schedule': section_schedule,
        'section_reconstruction_status': sec_status,
        'section_reconstruction_note': section_result.get('message') or ('Sections classified from the accepted trajectory.' if sec_status == 'CLASSIFIED_ONLY' else 'Not attempted because Stage 1 did not produce a validated trajectory.'),
        'stage1_summary': ('Validated trajectory found; all configured checks passed.' if feasible else ('Geometry screen indicates infeasibility under the current limits.' if screen['proven_infeasible'] else ('Search budget exhausted before a validated trajectory was found.' if over_budget() else 'No candidate passed all target and trajectory checks. This does not prove that no solution exists.'))),
        'stage2_summary': ('Sectionized trajectory validated and adopted.' if section_result.get('adopted') else ('Not run because Stage 1 has no validated trajectory.' if not feasible else ('Sectionization time budget was exhausted.' if section_result.get('status') == 'SKIPPED_TIME_BUDGET' else 'Sectionization did not produce a valid replacement; the Stage 1 trajectory was retained.'))),
        'section_reoptimization': {k: v for k, v in section_result.items() if k in ('attempted', 'adopted', 'status', 'attempts', 'seconds', 'md_change_pct', 'mode')},
        'stage1_metrics': baseline_metrics, 'final_metrics': final_metrics,
        'final_trajectory_source': 'section parameters (Stage 2)' if section_result.get('adopted') else ('Stage-1 control-point trajectory' if feasible else 'best-effort candidate (not valid)'),
        'section_schedule_constraint_check': section_check,
        'optimizer': 'Independent multi-seed SciPy L-BFGS-B search with adaptive variable-inclination/azimuth control points; profile templates are not used to parameterize the search; final acceptance uses core.validation',
        'optimization_status': outcome['optimization_status'],
        'status': outcome['status'],
        'result_class': 'PASS' if feasible else ('REVIEW' if outcome['optimization_status'] == 'INFEASIBLE_PROVEN' else 'NO FEASIBLE CANDIDATE FOUND'),
        'proof_of_infeasibility': screen if screen['proven_infeasible'] else None,
        'optimizer_success': bool(getattr(res_obj, 'success', False)) if res_obj is not None else False,
        'optimizer_message': str(getattr(res_obj, 'message', 'not run (analytic infeasibility screen fired)' if skip_search else 'not run')),
        'optimizer_iterations': int(total_iters), 'optimizer_solves': int(total_solves), 'objective_value': float(ev['score']),
        'search_history': history, 'search_seconds': round(time.time() - t_start, 2), 'search_budget_s': float(time_budget_s), 'search_budget_exhausted': bool(over_budget()), 'search_solves': int(total_solves), 'search_iterations': int(total_iters),
        'control_points_used': int(chosen['N']), 'adaptive_control_points': bool(adaptive),
        'target_sequence_results': target_results, 'required_target_count': len(targets),
        'target_sequence_feasible': all(r['within_tolerance'] and r['in_order'] for r in target_results),
        'constraint_violations': sorted(set(val['violations'])),
        'max_inclination_deg': float(m['max_inclination_deg']), 'max_dls_deg_30m': float(m['max_dls_deg_30m']),
        'max_build_rate_actual_deg_30m': float(m['max_build_rate_deg_30m']), 'max_drop_rate_actual_deg_30m': float(m.get('max_drop_rate_deg_30m', 0.0)), 'max_turn_rate_actual_deg_30m': float(m['max_turn_rate_deg_30m']),
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
