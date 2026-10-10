"""Profile-aware, practice-grade multi-parameter trajectory optimization.

Uses SciPy differential evolution to search the parameterization for the selected
profile. This is a candidate optimizer, not a certified directional design engine.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import differential_evolution
from core.trajectory import generate_profile_candidate
from core.geometry import target_contains, target_boundary

DROPPING = {'S-Profile', 'Build-Hold-Drop', 'Custom'}


def _target_residual(path, target_tvd_m, target_north_m, target_east_m, target_geometry=None, point_tolerance_m=30.48):
    """Interpolate the path at target TVD to avoid station-interval bias."""
    tvd = np.asarray(path['TVD'], dtype=float)
    north = np.asarray(path['Northing'], dtype=float)
    east = np.asarray(path['Easting'], dtype=float)
    if len(tvd) == 0:
        return 1e9, 1e9, 1e9, 1e9
    # Candidate generator may stop at the first TVD crossing.
    ix = np.flatnonzero(tvd >= target_tvd_m)
    if len(ix):
        j = int(ix[0])
        if j == 0:
            n, e, md = north[0], east[0], float(path.iloc[0]['MD'])
        else:
            t0, t1 = tvd[j-1], tvd[j]
            f = 0.0 if abs(t1-t0) < 1e-12 else (target_tvd_m-t0)/(t1-t0)
            f = min(1.0, max(0.0, f))
            n = north[j-1] + f*(north[j]-north[j-1])
            e = east[j-1] + f*(east[j]-east[j-1])
            md0, md1 = float(path.iloc[j-1]['MD']), float(path.iloc[j]['MD'])
            md = md0 + f*(md1-md0)
        lat = math.hypot(n-target_north_m, e-target_east_m)
        miss = _shape_miss(n, e, lat, target_geometry, point_tolerance_m)
        return lat, 0.0, md, miss
    end = path.iloc[-1]
    vert = float(target_tvd_m - end['TVD'])
    lat = math.hypot(float(end['Northing'])-target_north_m,
                     float(end['Easting'])-target_east_m)
    miss = _shape_miss(float(end['Northing']), float(end['Easting']), lat, target_geometry, point_tolerance_m)
    return lat, vert, float(end['MD']), miss


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
                        maxiter=18, popsize=7, seed=17):
    """Optimize KOP, build rate, peak inclination and azimuth; for S profiles,
    also optimize drop rate and final inclination. Objective balances target miss,
    DLS/inclination feasibility, and excessive MD. All distances are metres.
    """
    profile = str(profile)
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
        inc = np.asarray(path['Inc'], dtype=float)
        dls = np.asarray(path['DLS'], dtype=float)
        max_inc = float(np.max(inc, initial=0.0))
        max_dls = float(np.max(dls, initial=0.0))
        violations = []
        if miss > 1.0 or abs(vert) > 30.48:
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
                     'target_intercept_md_m':meta.get('target_intercept_md_m'),
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
    if max_br <= 0:
        raise ValueError('Maximum build rate must be positive.')
    kop_hi = min(max(100.0, target_tvd_m*0.85), max_md_m*0.6)
    bounds = [(0.0, kop_hi), (0.25, max_br), (peak_lo, peak_hi), (0.0, 360.0)]
    if profile in DROPPING:
        bounds.extend([(0.25, min(float(max_dls_deg_30m), float(max_build_rate_deg_30m))), (0.0, peak_hi), (0.2, 0.95)])
    elif profile == 'Custom':
        # The current Custom profile is a user-selected build/hold candidate with
        # configurable peak inclination/azimuth; explicit arbitrary section editing
        # is a separate future feature.
        pass

    def unpack(x):
        kop, br, peak, azi = x[:4]
        dr = x[4] if profile in DROPPING else float(drop_rate_initial_deg_30m)
        # A genuine S / build-hold-drop needs a meaningful inclination reduction.
        fin = min(float(x[5]), max(0.0, peak - 5.0)) if profile in DROPPING else float(final_inc_initial_deg)
        drop_fraction = float(x[6]) if profile in DROPPING else 0.70
        return float(kop), float(br), float(peak), float(azi), float(dr), float(fin), drop_fraction

    def evaluate(x, detailed=False, interval=station_interval_m):
        kop, br, peak, azi, dr, fin, drop_fraction = unpack(x)
        try:
            drop_len = abs(peak-fin)/max(dr, 1e-9)*30.0 if profile in DROPPING else 0.0
            build_end = kop + abs(peak)/max(br, 1e-9)*30.0
            drop_start_md = build_end + drop_fraction*max(0.0, max_md_m-drop_len-build_end) if profile in DROPPING else None
            path, meta = generate_profile_candidate(profile, kop, br, peak, azi,
                target_tvd_m, target_north_m, target_east_m,
                drop_rate_deg_30m=dr, final_inc_deg=fin, drop_start_md=drop_start_md,
                station_interval=interval, max_md=max_md_m, truncate_at_target=False)
            lat, vert, md, miss = _target_residual(path, target_tvd_m, target_north_m, target_east_m, target_geometry, point_tolerance_m)
            inc = np.asarray(path['Inc'], dtype=float)
            dls = np.asarray(path['DLS'], dtype=float)
            inc_pen = max(0.0, float(np.max(inc, initial=0))-max_inclination_deg)
            dls_pen = max(0.0, float(np.max(dls, initial=0))-max_dls_deg_30m)
            # Miss distance dominates; vertical miss is weighted because target
            # depth is normally a hard target constraint. MD is a modest tie-breaker.
            # For a drop profile, the target should not be intercepted before
            # the planned drop has completed. Otherwise an apparently good target
            # score can hide an S-profile whose defining section lies below target.
            section_order_penalty = 0.0
            if profile in DROPPING and drop_start_md is not None:
                drop_end_md = float(drop_start_md) + drop_len
                section_order_penalty = max(0.0, drop_end_md - float(md)) * 3.0
            score = (miss + 4.0*abs(vert) + 500.0*inc_pen + 150.0*dls_pen
                     + section_order_penalty + 0.001*md)
            if detailed:
                meta.update({'target_lateral_error_m':lat,'target_miss_distance_m':miss,'target_vertical_error_m':vert,
                    'objective_m':score,'section_order_penalty_m':section_order_penalty,'max_inclination_deg':float(np.max(inc, initial=0)),
                    'max_dls_deg_30m':float(np.max(dls, initial=0)),
                    'optimized_parameters':{'profile':profile,'KOP_MD_m':kop,'build_rate_deg_30m':br,
                        'peak_inclination_deg':peak,'azimuth_deg_grid':azi,
                        'drop_rate_deg_30m':dr if profile in DROPPING else None,
                        'final_inclination_deg':fin if profile in DROPPING else None,
                        'drop_start_md_m':drop_start_md if profile in DROPPING else None},
                    'optimizer':'SciPy differential_evolution','constraint_violations':([name for name, failed in [('target_intersection', miss > 1.0 or abs(vert) > 30.48), ('maximum_inclination', inc_pen > 0), ('maximum_DLS', dls_pen > 0), ('drop_section_before_target', section_order_penalty > 1e-6)] if failed]),
                    'optimization_status':'FEASIBLE' if miss <= 1.0 and abs(vert) <= 30.48 and inc_pen == 0 and dls_pen == 0 and section_order_penalty <= 1e-6 else 'REVIEW'})
                return path, meta
            return score
        except (ValueError, TypeError, KeyError, FloatingPointError):
            return 1e9

    # Keep the user's current settings in the initial population where compatible.
    result = differential_evolution(evaluate, bounds, maxiter=int(maxiter), popsize=int(popsize),
                                    seed=int(seed), polish=True, updating='immediate', workers=1,
                                    x0=[min(max(float(kop_initial_m), bounds[0][0]), bounds[0][1]),
                                        min(max(float(build_rate_initial_deg_30m), bounds[1][0]), bounds[1][1]),
                                        min(max(float(peak_inc_initial_deg), bounds[2][0]), bounds[2][1]),
                                        float(azimuth_initial_deg)%360.0] + ([min(max(float(drop_rate_initial_deg_30m), bounds[4][0]), bounds[4][1]),
                                        min(max(float(final_inc_initial_deg), bounds[5][0]), bounds[5][1]), 0.70] if profile in DROPPING else []))
    # Rebuild at finer station interval and report final feasibility honestly.
    best_x = result.x
    fine_interval = min(15.0, max(5.0, float(station_interval_m)/4.0))
    path, meta = evaluate(best_x, detailed=True, interval=fine_interval)
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
