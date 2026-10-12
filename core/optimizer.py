"""Profile-aware, practice-grade multi-parameter trajectory optimization.

Uses SciPy differential evolution to search the parameterization for the selected
profile. This is a candidate optimizer, not a certified directional design engine.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import differential_evolution
from core.trajectory import generate_profile_candidate, truncate_trajectory_at_md
from core.geometry import target_contains, target_boundary

DROPPING = {'S-Profile', 'Build-Hold-Drop', 'Custom'}


def _target_residual(path, target_tvd_m, target_north_m, target_east_m, target_geometry=None, point_tolerance_m=30.48):
    """Find the best target-plane/footprint approach anywhere along the path.

    Do not stop at the *first* TVD crossing: a horizontal section can remain at
    target TVD while continuing laterally, and that later station may be the
    actual target hit. Candidate points include target-TVD segment crossings,
    horizontal projections of the target centre onto every segment, and stations.
    Vertical error is retained as a separate feasibility condition.
    """
    tvd = np.asarray(path['TVD'], dtype=float)
    north = np.asarray(path['Northing'], dtype=float)
    east = np.asarray(path['Easting'], dtype=float)
    md_values = np.asarray(path['MD'], dtype=float)
    if len(tvd) == 0:
        return 1e9, 1e9, 1e9, 1e9

    candidates = []
    def add_candidate(n, e, v, md):
        lat = math.hypot(float(n) - target_north_m, float(e) - target_east_m)
        miss = _shape_miss(float(n), float(e), lat, target_geometry, point_tolerance_m)
        # Target-plane adherence is a hard design requirement; the miss term
        # measures distance outside the permitted footprint.
        # Once inside a target footprint, distance-to-boundary is zero everywhere.
        # Retain a small centre-distance tie-breaker so optimization does not
        # treat an edge hit as equally desirable as a centre hit.
        vertical_error = abs(float(v) - target_tvd_m)
        # A point outside the allowed target-depth band must not outrank an
        # actual target-plane crossing merely because its horizontal position is closer.
        vertical_penalty = 4.0 * vertical_error + 100.0 * max(0.0, vertical_error - point_tolerance_m)
        score = miss + 0.35 * lat + vertical_penalty
        candidates.append((score, lat, float(v) - target_tvd_m, float(md), miss))

    for i in range(len(tvd)):
        add_candidate(north[i], east[i], tvd[i], md_values[i])

    for i in range(len(tvd) - 1):
        n0, n1 = north[i], north[i + 1]
        e0, e1 = east[i], east[i + 1]
        v0, v1 = tvd[i], tvd[i + 1]
        m0, m1 = md_values[i], md_values[i + 1]
        dn, de = n1 - n0, e1 - e0
        denom = dn * dn + de * de
        # Point on this segment closest to the target in horizontal projection.
        fxy = 0.0 if denom < 1e-15 else max(0.0, min(1.0,
            ((target_north_m - n0) * dn + (target_east_m - e0) * de) / denom))
        add_candidate(n0 + fxy * dn, e0 + fxy * de,
                      v0 + fxy * (v1 - v0), m0 + fxy * (m1 - m0))
        # Exact TVD crossing, when the segment crosses the target plane.
        if (v0 - target_tvd_m) * (v1 - target_tvd_m) <= 0 and abs(v1 - v0) > 1e-12:
            fz = max(0.0, min(1.0, (target_tvd_m - v0) / (v1 - v0)))
            add_candidate(n0 + fz * dn, e0 + fz * de, target_tvd_m,
                          m0 + fz * (m1 - m0))
        # If a segment is essentially horizontal and lies close to target TVD,
        # its lateral projection is already evaluated above. This is the key case
        # that first-crossing-only logic missed.

    best = min(candidates, key=lambda item: item[0])
    _, lat, vert, md, miss = best
    return float(lat), float(vert), float(md), float(miss)


def _shape_miss(north, east, center_distance, target_geometry=None, point_tolerance_m=30.48):
    """Distance outside the allowed target footprint; zero means inside tolerance."""
    if not target_geometry:
        return max(0.0, float(center_distance)-float(point_tolerance_m))
    typ=str(target_geometry.get('type','Point')).lower()
    if typ == 'point':
        return max(0.0, float(center_distance)-float(point_tolerance_m))
    if target_contains(target_geometry, north, east):
        return 0.0
    bn, be = target_boundary(target_geometry)
    if len(bn) == 1:
        return math.hypot(north-float(bn[0]), east-float(be[0]))
    best=float('inf')
    for i in range(len(bn)-1):
        n1,e1=float(bn[i]),float(be[i]); n2,e2=float(bn[i+1]),float(be[i+1])
        dn,de=n2-n1,e2-e1
        denom=dn*dn+de*de
        f=0.0 if denom < 1e-12 else max(0.0,min(1.0,((north-n1)*dn+(east-e1)*de)/denom))
        best=min(best,math.hypot(north-(n1+f*dn),east-(e1+f*de)))
    return best if math.isfinite(best) else float(center_distance)


def optimize_trajectory(profile, target_tvd_m, target_north_m, target_east_m,
                        kop_initial_m, build_rate_initial_deg_30m,
                        peak_inc_initial_deg, azimuth_initial_deg,
                        max_inclination_deg=70.0, max_dls_deg_30m=3.0,
                        max_build_rate_deg_30m=3.0, max_turn_rate_deg_30m=3.0,
                        drop_rate_initial_deg_30m=3.0, final_inc_initial_deg=0.0,
                        target_geometry=None, point_tolerance_m=30.48,
                        station_interval_m=60.0, max_md_m=15000.0,
                        kop_mode="free", kop_window_min_m=None, kop_window_max_m=None,
                        target_sequence=None, maxiter=22, popsize=8, seed=17):
    """Optimize KOP, build rate, peak inclination and azimuth; for S profiles,
    also optimize drop rate and final inclination. Objective balances target miss,
    DLS/inclination feasibility, and excessive MD. All distances are metres.
    """
    profile = str(profile)
    # Ordered required target sequence. Coordinates are well-relative metres.
    sequence = list(target_sequence or [])
    if sequence:
        for item in sequence:
            if not all(k in item for k in ("tvd_m", "north_m", "east_m")):
                raise ValueError("Each sequence target requires tvd_m, north_m and east_m.")
        # The final required target defines the target-driven planned TD.
        target_tvd_m = float(sequence[-1]["tvd_m"])
        target_north_m = float(sequence[-1]["north_m"])
        target_east_m = float(sequence[-1]["east_m"])
        target_geometry = sequence[-1].get("geometry", target_geometry)
    kop_mode = str(kop_mode).lower().replace(" ", "_").replace("-", "_")
    if kop_mode not in {"free", "fixed", "window"}:
        raise ValueError("KOP mode must be free, fixed, or window.")
    supported = {'Vertical','J-Profile','S-Profile','Build & Hold','Build-Hold-Drop','Horizontal','ERD','Custom'}
    if profile not in supported:
        raise ValueError(f'Unsupported profile for optimization: {profile}')
    if target_tvd_m <= 0:
        raise ValueError('Target TVD must be positive.')
    if max_inclination_deg <= 0 or max_dls_deg_30m <= 0 or max_build_rate_deg_30m <= 0:
        raise ValueError('Inclination, DLS and build-rate constraints must be positive.')
    if profile == 'Vertical':
        path, meta = generate_profile_candidate('Vertical', 0, 1, 0, 0,
            target_tvd_m, target_north_m, target_east_m,
            station_interval=station_interval_m, max_md=max_md_m, truncate_at_target=False)
        lat, vert, md, miss = _target_residual(path, target_tvd_m, target_north_m, target_east_m, target_geometry, point_tolerance_m)
        vertical_sequence_results=[]
        if sequence:
            prev=-1.0
            for item in sequence:
                ilat, ivert, imd, imiss = _target_residual(path, float(item['tvd_m']), float(item['north_m']), float(item['east_m']), item.get('geometry'), float(item.get('tolerance_m', point_tolerance_m)))
                ordered=imd>prev+1e-3
                vertical_sequence_results.append({'name':str(item.get('name','Target')),'intercept_md_m':float(imd),'lateral_error_m':float(ilat),'vertical_error_m':float(ivert),'miss_distance_m':float(imiss),'within_tolerance':bool(imiss<=1.0 and abs(ivert)<=30.48),'in_order':bool(ordered)})
                prev=imd
            if vertical_sequence_results:
                lat,vert,md,miss=(vertical_sequence_results[-1]['lateral_error_m'],vertical_sequence_results[-1]['vertical_error_m'],vertical_sequence_results[-1]['intercept_md_m'],vertical_sequence_results[-1]['miss_distance_m'])
        inc = np.asarray(path['Inc'], dtype=float)
        dls = np.asarray(path['DLS'], dtype=float)
        max_inc = float(np.max(inc, initial=0.0))
        max_dls = float(np.max(dls, initial=0.0))
        violations = []
        sequence_ok = all(x['within_tolerance'] and x['in_order'] for x in vertical_sequence_results) if sequence else True
        if miss > 1.0 or abs(vert) > 30.48 or not sequence_ok:
            violations.append('target_intersection')
        if max_inc > max_inclination_deg + 1e-6:
            violations.append('maximum_inclination')
        if max_dls > max_dls_deg_30m + 1e-6:
            violations.append('maximum_DLS')
        feasible = not violations
        meta.update({'optimizer':'profile feasibility check','optimization_status':'FEASIBLE' if feasible else 'NO_FEASIBLE_DIRECTIONAL_SOLUTION',
                     'status':'PASS' if feasible else 'REVIEW', 'constraint_violations':violations,
                     'max_inclination_deg':max_inc, 'max_dls_deg_30m':max_dls,
                     'objective_m':miss+abs(vert)*4+md*0.001,'target_lateral_error_m':lat,'target_miss_distance_m':miss,'target_vertical_error_m':vert,
                     'target_intercept_md_m':md,
                     'target_sequence_results':vertical_sequence_results if sequence else [],
                     'required_target_count':len(sequence) if sequence else 1,
                     'target_sequence_feasible':bool(sequence_ok),
                     'optimized_parameters':{'profile':'Vertical'}})
        return path, meta

    peak_lo = 5.0 if profile in DROPPING else 1.0
    peak_hi = min(90.0, float(max_inclination_deg))
    if profile == 'Horizontal':
        if max_inclination_deg < 89.0:
            raise ValueError('Horizontal profile requires a maximum inclination constraint of at least 89°. Increase the constraint or choose another profile.')
        peak_lo = peak_hi = 90.0
    elif profile == 'ERD':
        peak_lo, peak_hi = min(75.0, peak_hi), min(88.0, peak_hi)
        if peak_hi < peak_lo:
            raise ValueError('ERD profile is incompatible with the maximum-inclination constraint.')
    max_br = min(float(max_build_rate_deg_30m), float(max_dls_deg_30m))
    # Optimize azimuth as a signed deviation from the direct wellhead-to-target
    # bearing. This avoids placing a due-north target at the 0/360 search boundary.
    target_azimuth = math.degrees(math.atan2(float(target_east_m), float(target_north_m))) % 360.0
    if max_br <= 0:
        raise ValueError('Maximum build rate must be positive.')
    kop_hi = min(max(100.0, target_tvd_m*0.85), max_md_m*0.6)
    if kop_mode == "fixed":
        kop_lo = kop_upper = float(kop_initial_m)
        if kop_lo < 0 or kop_lo > max_md_m:
            raise ValueError("Fixed KOP must be between 0 and the maximum planned MD.")
    elif kop_mode == "window":
        if kop_window_min_m is None or kop_window_max_m is None:
            raise ValueError("Provide both minimum and maximum KOP for KOP-window optimization.")
        kop_lo, kop_upper = float(kop_window_min_m), float(kop_window_max_m)
        if kop_lo < 0 or kop_upper < kop_lo or kop_upper > max_md_m:
            raise ValueError("KOP window must satisfy 0 ≤ minimum ≤ maximum ≤ maximum planned MD.")
    else:
        kop_lo, kop_upper = 0.0, kop_hi
    max_turn = float(max_turn_rate_deg_30m)
    if max_turn <= 0:
        raise ValueError("Maximum turn rate must be positive.")
    bounds = [(kop_lo, kop_upper), (0.25, max_br), (peak_lo, peak_hi), (-180.0, 180.0), (-max_turn, max_turn)]
    if profile in DROPPING:
        bounds.extend([(0.25, min(float(max_dls_deg_30m), float(max_build_rate_deg_30m))), (0.0, peak_hi), (0.2, 0.95)])
    elif profile == 'Custom':
        # The current Custom profile is a user-selected build/hold candidate with
        # configurable peak inclination/azimuth; explicit arbitrary section editing
        # is a separate future feature.
        pass

    def unpack(x):
        kop, br, peak, azimuth_delta, turn_rate = x[:5]
        azi = (target_azimuth + float(azimuth_delta)) % 360.0
        dr = x[5] if profile in DROPPING else float(drop_rate_initial_deg_30m)
        # A genuine S / build-hold-drop needs a meaningful inclination reduction.
        fin = min(float(x[6]), max(0.0, peak - 5.0)) if profile in DROPPING else float(final_inc_initial_deg)
        drop_fraction = float(x[7]) if profile in DROPPING else 0.70
        return float(kop), float(br), float(peak), float(azi), float(dr), float(fin), drop_fraction, float(turn_rate)

    def evaluate(x, detailed=False, interval=station_interval_m):
        kop, br, peak, azi, dr, fin, drop_fraction, turn_rate = unpack(x)
        try:
            drop_len = abs(peak-fin)/max(dr, 1e-9)*30.0 if profile in DROPPING else 0.0
            build_end = kop + abs(peak)/max(br, 1e-9)*30.0
            drop_start_md = build_end + drop_fraction*max(0.0, max_md_m-drop_len-build_end) if profile in DROPPING else None
            path, meta = generate_profile_candidate(profile, kop, br, peak, azi,
                target_tvd_m, target_north_m, target_east_m,
                drop_rate_deg_30m=dr, final_inc_deg=fin, drop_start_md=drop_start_md,
                station_interval=interval, max_md=max_md_m, truncate_at_target=False,
                azimuth_turn_rate_deg_30m=turn_rate)
            lat, vert, md, miss = _target_residual(path, target_tvd_m, target_north_m, target_east_m, target_geometry, point_tolerance_m)
            sequence_results = []
            sequence_penalty = 0.0
            if sequence:
                previous_md = -1.0
                for item in sequence:
                    geom = item.get("geometry")
                    ilat, ivert, imd, imiss = _target_residual(path, float(item["tvd_m"]), float(item["north_m"]), float(item["east_m"]), geom, float(item.get("tolerance_m", point_tolerance_m)))
                    ordered = imd > previous_md + 1e-3
                    sequence_results.append({"name": str(item.get("name", "Target")), "intercept_md_m": float(imd), "lateral_error_m": float(ilat), "vertical_error_m": float(ivert), "miss_distance_m": float(imiss), "within_tolerance": bool(imiss <= 1.0 and abs(ivert) <= 30.48), "in_order": bool(ordered)})
                    sequence_penalty += imiss + 4.0 * abs(ivert) + (0.0 if ordered else 100000.0)
                    previous_md = imd
                # The final required target governs the endpoint and feasibility.
                lat, vert, md, miss = (sequence_results[-1]["lateral_error_m"], sequence_results[-1]["vertical_error_m"], sequence_results[-1]["intercept_md_m"], sequence_results[-1]["miss_distance_m"])
            inc = np.asarray(path['Inc'], dtype=float)
            dls = np.asarray(path['DLS'], dtype=float)
            inc_pen = max(0.0, float(np.max(inc, initial=0))-max_inclination_deg)
            dls_pen = max(0.0, float(np.max(dls, initial=0))-max_dls_deg_30m-1e-6)
            # Independently enforce azimuth turn rate per 30 m measured depth.
            azi_values = np.unwrap(np.radians(np.asarray(path["Azi"], dtype=float)))
            md_values = np.asarray(path["MD"], dtype=float)
            turn_rates = np.abs(np.degrees(np.diff(azi_values)) / np.maximum(np.diff(md_values), 1e-12) * 30.0)
            max_turn_actual = float(np.max(turn_rates, initial=0.0))
            turn_pen = max(0.0, max_turn_actual-max_turn-1e-6)
            # Miss distance dominates; vertical miss is weighted because target
            # depth is normally a hard target constraint. MD is a modest tie-breaker.
            # For a drop profile, the target should not be intercepted before
            # the planned drop has completed. Otherwise an apparently good target
            # score can hide an S-profile whose defining section lies below target.
            build_end_md = kop + abs(peak) / max(br, 1e-9) * 30.0
            required_section_end_md = build_end_md
            if profile in DROPPING and drop_start_md is not None:
                required_section_end_md = float(drop_start_md) + drop_len
            # Do not accept a target reached during build when the selected profile
            # requires the build to finish first (especially Horizontal/ERD).
            section_order_penalty = max(0.0, required_section_end_md - float(md)) * 3.0
            # Treat physical limits as hard constraints for search purposes. A candidate that
            # hits the target by violating inclination/DLS must not beat a feasible
            # candidate merely because its geometric miss is smaller.
            target_score = sequence_penalty if sequence else (miss + 4.0*abs(vert))
            score = (target_score + 100000.0*inc_pen + 100000.0*dls_pen
                     + 100000.0*turn_pen + section_order_penalty + 0.001*md)
            if detailed:
                sequence_ok = all(x['within_tolerance'] and x['in_order'] for x in sequence_results) if sequence else True
                meta.update({'target_lateral_error_m':lat,'target_miss_distance_m':miss,'target_vertical_error_m':vert,
                    'target_tvd_crossing_md_m':md, 'target_intercept_md_m':md,
                    'target_sequence_results': sequence_results if sequence else [],
                    'required_target_count': len(sequence) if sequence else 1,
                    'target_sequence_feasible': bool(sequence_ok),
                    'objective_m':score,'section_order_penalty_m':section_order_penalty,'max_inclination_deg':float(np.max(inc, initial=0)),
                    'max_dls_deg_30m':float(np.max(dls, initial=0)), 'max_turn_rate_actual_deg_30m':max_turn_actual,
                    'optimized_parameters':{'profile':profile,'KOP_MD_m':kop,'build_rate_deg_30m':br,
                        'peak_inclination_deg':peak,'azimuth_deg_grid':azi, 'azimuth_turn_rate_deg_30m':turn_rate,
                        'drop_rate_deg_30m':dr if profile in DROPPING else None,
                        'final_inclination_deg':fin if profile in DROPPING else None,
                        'drop_start_md_m':drop_start_md if profile in DROPPING else None},
                    'optimizer':'SciPy differential_evolution','constraint_violations':([name for name, failed in [('target_intersection', miss > 1.0 or abs(vert) > 30.48 or not sequence_ok), ('maximum_inclination', inc_pen > 0), ('maximum_DLS', dls_pen > 0), ('maximum_turn_rate', turn_pen > 0), ('drop_section_before_target', section_order_penalty > 1e-6)] if failed]),
                    'optimization_status':'FEASIBLE' if miss <= 1.0 and abs(vert) <= 30.48 and sequence_ok and inc_pen == 0 and dls_pen == 0 and turn_pen == 0 and section_order_penalty <= 1e-6 else 'REVIEW'})
                return path, meta
            return score
        except (ValueError, TypeError, KeyError, FloatingPointError):
            return 1e9

    # Keep the user's current settings in the initial population where compatible.
    result = differential_evolution(evaluate, bounds, maxiter=(int(math.ceil(int(maxiter)*2.5)) if int(maxiter) >= 5 else int(maxiter)), popsize=int(popsize),
                                    seed=int(seed), polish=True, updating='immediate', workers=1,
                                    x0=[min(max(float(kop_initial_m), bounds[0][0]), bounds[0][1]),
                                        min(max(float(build_rate_initial_deg_30m), bounds[1][0]), bounds[1][1]),
                                        min(max(float(peak_inc_initial_deg), bounds[2][0]), bounds[2][1]),
                                        ((float(azimuth_initial_deg) - target_azimuth + 180.0) % 360.0) - 180.0, 0.0] + ([min(max(float(drop_rate_initial_deg_30m), bounds[5][0]), bounds[5][1]),
                                        min(max(float(final_inc_initial_deg), bounds[6][0]), bounds[6][1]), 0.70] if profile in DROPPING else []))
    # Rebuild at finer station interval and report final feasibility honestly.
    best_x = result.x
    fine_interval = min(15.0, max(5.0, float(station_interval_m)/4.0))
    path, meta = evaluate(best_x, detailed=True, interval=fine_interval)
    # A candidate is feasible only when the target footprint/depth and required
    # profile section are satisfied and all physical constraints pass. Only then
    # terminate the trajectory at the selected target-intercept MD; failed
    # candidates retain their full path for diagnosis and never masquerade as TD.
    if meta.get('optimization_status') == 'FEASIBLE' and meta.get('target_intercept_md_m') is not None:
        path = truncate_trajectory_at_md(path, meta['target_intercept_md_m'])
        meta['final_md_is_target_intercept'] = True
    else:
        meta['final_md_is_target_intercept'] = False
    meta['kop_mode'] = kop_mode
    meta['kop_constraint_m'] = ({'fixed_m': float(kop_initial_m)} if kop_mode == 'fixed' else
                                {'minimum_m': float(kop_lo), 'maximum_m': float(kop_upper)} if kop_mode == 'window' else
                                {'minimum_m': 0.0, 'maximum_m': float(kop_hi)})
    meta['optimizer_success'] = bool(result.success)
    meta['optimizer_message'] = str(result.message)
    meta['optimizer_iterations'] = int(getattr(result, 'nit', 0))
    meta['optimizer_evaluations'] = int(getattr(result, 'nfev', 0))
    meta['status'] = 'PASS' if meta['optimization_status'] == 'FEASIBLE' else 'REVIEW'
    # Existing downstream UI expects these metadata keys.
    params = meta.get('optimized_parameters', {})
    meta['build_end_md_m'] = float(params.get('KOP_MD_m', 0)) + (float(params.get('peak_inclination_deg', 0))/max(float(params.get('build_rate_deg_30m', 1)), 1e-9))*30.0
    meta['build_length_m'] = meta['build_end_md_m']-float(params.get('KOP_MD_m', 0))
    meta['hold_inclination_deg'] = float(params.get('peak_inclination_deg', 0))
    meta['planning_azimuth_deg'] = float(params.get('azimuth_deg_grid', 0))
    meta['azimuth_turn_rate_deg_30m'] = float(params.get('azimuth_turn_rate_deg_30m', 0.0))
    meta['drop_start_md_m'] = params.get('drop_start_md_m')
    meta['final_inclination_deg'] = float(path.iloc[-1]['Inc'])
    meta['final_md_m'] = float(path.iloc[-1]['MD'])
    meta['endpoint_north_m'] = float(path.iloc[-1]['Northing'])
    meta['endpoint_east_m'] = float(path.iloc[-1]['Easting'])
    meta['endpoint_tvd_m'] = float(path.iloc[-1]['TVD'])
    meta['lateral_error_m'] = float(meta.get('target_lateral_error_m', 0))
    meta['target_miss_distance_m'] = float(meta.get('target_miss_distance_m', 0))
    meta['tvd_error_m'] = float(meta.get('target_vertical_error_m', 0))
    return path, meta
