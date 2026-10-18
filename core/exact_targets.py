"""Exact (continuous) point-target interception on minimum-curvature arcs.

A point target is a geometric constraint, not an area: the wellbore must pass through it. Station
sampling (even every 0.5 m) only brackets the closest approach, so the solver here refines it on the
true circular arcs between stations until the distance is at floating-point precision.

``POINT_NUMERIC_TOL_M`` is NOT an engineering tolerance radius. It is the closure criterion for the
numerical solve (0.1 mm, six orders of magnitude below any survey accuracy), needed because two
floating-point positions are never identically equal.
"""
from __future__ import annotations

import math

import numpy as np

POINT_NUMERIC_TOL_M = 1.0e-4


def _col(path, name):
    return np.asarray(path[name], dtype=float)


def _ratio(x):
    x = float(x)
    return 1.0 + x * x / 12.0 if abs(x) < 1e-9 else 2.0 / x * math.tan(x / 2.0)


def arc_position(path, k, f):
    """Position (N, E, TVD), tangent and MD at fraction ``f`` (0-1) of segment ``k`` of a calculated path."""
    md = _col(path, "MD"); inc = np.radians(_col(path, "Inc")); azi = np.radians(_col(path, "Azi"))
    L = md[k + 1] - md[k]
    t1 = np.array([math.sin(inc[k]) * math.cos(azi[k]), math.sin(inc[k]) * math.sin(azi[k]), math.cos(inc[k])])
    t2 = np.array([math.sin(inc[k + 1]) * math.cos(azi[k + 1]), math.sin(inc[k + 1]) * math.sin(azi[k + 1]), math.cos(inc[k + 1])])
    beta = math.acos(float(np.clip(t1 @ t2, -1.0, 1.0)))
    sb = math.sin(beta)
    if sb < 1e-9:
        tf = (1.0 - f) * t1 + f * t2
    else:
        tf = (math.sin((1.0 - f) * beta) * t1 + math.sin(f * beta) * t2) / sb
    tf = tf / max(float(np.linalg.norm(tf)), 1e-15)
    base = np.array([_col(path, "Northing")[k], _col(path, "Easting")[k], _col(path, "TVD")[k]])
    pos = base + (f * L / 2.0) * (t1 + tf) * _ratio(f * beta)
    return pos, tf, float(md[k] + f * L)


def _segment_model(md, inc, azi, N, E, Z, k):
    """Scalar (pure-math) arc model for segment k: returns fn(f) -> (pos tuple, tangent tuple)."""
    i1, i2, a1, a2 = inc[k], inc[k + 1], azi[k], azi[k + 1]
    t1 = (math.sin(i1) * math.cos(a1), math.sin(i1) * math.sin(a1), math.cos(i1))
    t2 = (math.sin(i2) * math.cos(a2), math.sin(i2) * math.sin(a2), math.cos(i2))
    c = min(1.0, max(-1.0, t1[0] * t2[0] + t1[1] * t2[1] + t1[2] * t2[2]))
    beta = math.acos(c); sb = math.sin(beta); L = md[k + 1] - md[k]
    base = (N[k], E[k], Z[k])

    def at(f):
        if sb < 1e-9:
            w1, w2 = 1.0 - f, f
        else:
            w1, w2 = math.sin((1.0 - f) * beta) / sb, math.sin(f * beta) / sb
        tf = (w1 * t1[0] + w2 * t2[0], w1 * t1[1] + w2 * t2[1], w1 * t1[2] + w2 * t2[2])
        nrm = math.sqrt(tf[0] ** 2 + tf[1] ** 2 + tf[2] ** 2) or 1e-15
        tf = (tf[0] / nrm, tf[1] / nrm, tf[2] / nrm)
        x = f * beta
        rf = 1.0 + x * x / 12.0 if abs(x) < 1e-9 else 2.0 / x * math.tan(x / 2.0)
        h = f * L / 2.0 * rf
        return (base[0] + h * (t1[0] + tf[0]), base[1] + h * (t1[1] + tf[1]), base[2] + h * (t1[2] + tf[2])), tf
    return at, L


def closest_point_on_path(path, target_nez, start_md=-1.0, endpoint_only=False, top=3):
    """Closest approach of the wellbore (arcs) to a point, at a continuous MD after ``start_md``.

    ``path`` needs MD, Inc, Azi, Northing, Easting, TVD (DataFrame or dict of arrays). Candidate segments
    are pre-screened on their chords, then each is refined with Newton steps on the arc parameter
    (d(pos)/df = L * tangent, so the step is -(d . tangent) / L); convergence is quadratic, so a handful of
    iterations reach floating-point precision. Returns a dict with md, distance_m (3-D),
    d_north/d_east/d_tvd (path minus target), lateral_m, vertical_m.
    """
    md = _col(path, "MD"); N = _col(path, "Northing"); E = _col(path, "Easting"); Z = _col(path, "TVD")
    tgt = np.asarray(target_nez, dtype=float)
    if endpoint_only:
        pos = np.array([N[-1], E[-1], Z[-1]]); d = pos - tgt
        return _pack(float(md[-1]), pos, d, len(md) - 2, 1.0)
    P = np.column_stack([N, E, Z]); A, B = P[:-1], P[1:]; AB = B - A
    denom = np.maximum(np.sum(AB * AB, axis=1), 1e-12)
    t = np.clip(np.sum((tgt - A) * AB, axis=1) / denom, 0.0, 1.0)
    chord = np.linalg.norm(A + t[:, None] * AB - tgt, axis=1)
    valid = md[1:] > start_md + 1e-9
    if not valid.any():
        return None
    chord = np.where(valid, chord, np.inf)
    inc = np.radians(_col(path, "Inc")); azi = np.radians(_col(path, "Azi"))
    tg = (float(tgt[0]), float(tgt[1]), float(tgt[2]))
    best = None
    for k in np.argsort(chord)[:max(1, top)]:
        if not np.isfinite(chord[k]):
            continue
        k = int(k); at, L = _segment_model(md, inc, azi, N, E, Z, k)
        lo = max(0.0, (start_md + 1e-9 - md[k]) / L) if start_md > md[k] else 0.0
        if lo >= 1.0:
            continue
        f = min(1.0, max(lo, float(t[k])))
        for _ in range(12):
            pos, tf = at(f)
            d = (pos[0] - tg[0], pos[1] - tg[1], pos[2] - tg[2])
            step = (d[0] * tf[0] + d[1] * tf[1] + d[2] * tf[2]) / L
            fn = min(1.0, max(lo, f - step))
            if abs(fn - f) < 1e-15:
                f = fn; break
            f = fn
        pos, _ = at(f)
        dv = np.array([pos[0] - tg[0], pos[1] - tg[1], pos[2] - tg[2]])
        cand = _pack(float(md[k] + f * L), pos, dv, k, f)
        if best is None or cand["distance_m"] < best["distance_m"]:
            best = cand
    return best


def _pack(md, pos, d, k, f):
    return {"md": float(md), "distance_m": float(np.linalg.norm(d)), "d_north": float(d[0]), "d_east": float(d[1]), "d_tvd": float(d[2]),
            "lateral_m": float(math.hypot(d[0], d[1])), "vertical_m": float(d[2]), "segment": int(k), "fraction": float(f)}
