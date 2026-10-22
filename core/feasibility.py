"""Analytic necessary-condition screens that can PROVE a target plan infeasible.

A failed optimizer run only means "no valid candidate was found in this search". These
screens are different: they use exact geometric bounds, so when one fires the plan is
infeasible for *any* trajectory obeying the stated limits - not merely for this search.
If no screen fires, feasibility is simply undecided (the optimizer may still have missed a
solution). All bounds assume inclination limit < 90 deg (TVD strictly increasing).
"""
from __future__ import annotations

import math

import numpy as np

from core.geometry import target_boundary, target_tolerances, DEFAULT_TOLERANCE_M
from core.validation import footprint_miss, plane_tvd


def max_horizontal_reach(tvd_m, max_inc_deg, max_curvature_deg_30m, kop_min_m=0.0):
    """Largest horizontal departure achievable at a given TVD (planar upper bound).

    Optimal path: vertical to ``kop_min_m``, then build at the maximum curvature to the maximum
    inclination as early as possible, then hold. dH/dTVD = tan(inc), so any lower inclination at
    any depth can only reduce departure.
    """
    z = float(tvd_m) - float(kop_min_m)
    if z <= 0:
        return 0.0
    imax = math.radians(float(max_inc_deg))
    r = math.radians(float(max_curvature_deg_30m)) / 30.0
    if r <= 0:
        return 0.0
    R = 1.0 / r
    z_build = R * math.sin(imax)
    if z <= z_build:
        return R - math.sqrt(max(R * R - z * z, 0.0))
    return R * (1.0 - math.cos(imax)) + (z - z_build) * math.tan(imax)


def _bounding_radius(target):
    geom = target.get("geometry") or (target if target.get("type") else None)
    lat_tol, _ = target_tolerances(target)
    if not geom or str(geom.get("type", "Point")).lower() == "point":
        return lat_tol
    g = dict(geom); g.setdefault("north_m", target["north_m"]); g.setdefault("east_m", target["east_m"])
    n, e = target_boundary(g)
    return float(np.max(np.hypot(np.asarray(n, dtype=float) - float(target["north_m"]), np.asarray(e, dtype=float) - float(target["east_m"])))) if len(n) > 1 else lat_tol


def _z_band(target):
    """(shallowest, deepest) TVD at which the target can be intercepted."""
    _, vert_tol = target_tolerances(target)
    slope = math.tan(math.radians(min(float(target.get("dip_deg", 0.0) or 0.0), 89.0)))
    r = _bounding_radius(target)
    z0 = float(target["tvd_m"])
    return z0 - vert_tol - slope * r, z0 + vert_tol + slope * r


def reachability_screen(targets, *, max_inclination_deg, max_dls_deg_30m, max_build_rate_deg_30m=None,
                        max_md_m=None, min_kop_md_m=0.0):
    """Return {'proven_infeasible': bool, 'reasons': [...], 'bounds': {...}}."""
    reasons = []; bounds = {}
    targets = list(targets or [])
    if not targets:
        return {"proven_infeasible": False, "reasons": [], "bounds": {}}
    # DLS is the sole directional-change-rate constraint. Legacy build-rate input is ignored.
    curvature = float(max_dls_deg_30m)
    imax = float(max_inclination_deg)
    # ---- depth vs MD limit (MD >= TVD for any path)
    if max_md_m is not None:
        for t in targets:
            lo, _ = _z_band(t)
            if float(max_md_m) < lo:
                reasons.append(f"Maximum MD {float(max_md_m):.0f} m is shallower than target '{t.get('name', 'Target')}' (shallowest interception TVD {lo:.0f} m); MD can never be less than TVD.")
    if imax >= 90.0 - 1e-6:
        return {"proven_infeasible": bool(reasons), "reasons": reasons, "bounds": bounds,
                "note": "Inclination limit >= 90 deg: TVD-monotonic and reach bounds do not apply."}
    # ---- first target: planar reach bound from the wellhead (origin of the well-relative frame)
    first = targets[0]
    lo, hi = _z_band(first)
    need = float(footprint_miss(first, [0.0], [0.0])[0])
    reach = max_horizontal_reach(hi, imax, curvature, min_kop_md_m)
    bounds["first_target_required_departure_m"] = need
    bounds["first_target_max_reachable_departure_m"] = reach
    if need > reach + 1e-6:
        reasons.append(f"Target '{first.get('name', 'Target')}' needs {need:.0f} m of horizontal departure but at most {reach:.0f} m is reachable by TVD {hi:.0f} m "
                       f"with inclination <= {imax:.1f} deg, curvature <= {curvature:.2f} deg/30 m and KOP >= {float(min_kop_md_m):.0f} m.")
    # ---- consecutive targets: TVD must increase, horizontal change bounded by dH <= dZ * tan(imax)
    for a, b in zip(targets[:-1], targets[1:]):
        a_lo, a_hi = _z_band(a); b_lo, b_hi = _z_band(b)
        if b_hi < a_lo - 1e-9:
            reasons.append(f"Target '{b.get('name', 'Target')}' (TVD <= {b_hi:.0f} m) is shallower than the earlier required target '{a.get('name', 'Target')}' "
                           f"(TVD >= {a_lo:.0f} m); with inclination < 90 deg TVD only increases along the well.")
            continue
        dz = max(b_hi - a_lo, 0.0)
        centre = math.hypot(float(b["north_m"]) - float(a["north_m"]), float(b["east_m"]) - float(a["east_m"]))
        gap = centre - _bounding_radius(a) - _bounding_radius(b)
        if gap > dz * math.tan(math.radians(imax)) + 1e-6:
            reasons.append(f"Targets '{a.get('name', 'Target')}' -> '{b.get('name', 'Target')}' are {gap:.0f} m apart horizontally but only {dz:.0f} m apart in TVD; "
                           f"inclination <= {imax:.1f} deg allows at most {dz * math.tan(math.radians(imax)):.0f} m.")
    return {"proven_infeasible": bool(reasons), "reasons": reasons, "bounds": bounds}
