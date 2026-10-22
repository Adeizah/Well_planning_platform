"""Stage 2: reconstruct a feasible trajectory into practical sections and re-optimise their parameters.

Stage 1 (core.general_optimizer) finds ANY feasible path through all required targets using free-form
control points. That path is usually not how a directional driller would plan the well. Stage 2:

  1. segments the Stage-1 path into a small number of constant-rate sections (dynamic programming on
     inclination / azimuth-swing, fewest sections that reproduce the path within ``rms_tol_deg``);
  2. re-optimises the section parameters (vertical length / KOP, section lengths, build-drop rates,
     turn rates, start azimuth) with SLSQP under hard target, DLS, rate, inclination, KOP and MD constraints;
  3. generates survey stations FROM THE SECTION PARAMETERS (boundaries are exact stations);
  4. hands the result to the independent validator. A reconstructed plan is only ever adopted if that
     validation passes; otherwise the original feasible trajectory is retained and the reason reported.

Section model: inclination and azimuth change linearly with MD inside a section
(``inc += build * L / 30``, ``azi += turn * L / 30``, rates in deg per 30 m), so every section is a
constant build / drop / turn / tangent / vertical arc and DLS is bounded by the rates.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core.trajectory import mc_core

RATE_SNAP_DEG_30M = 0.12        # rates below this are treated as zero when naming/fixing a section


# ------------------------------------------------------------------------------ section model
def sections_to_stations(azi0, sections, interval_m=30.0):
    """Survey stations (MD, Inc, Azi) generated from section parameters; every boundary is a station."""
    md0, inc, azi = 0.0, 0.0, float(azi0)
    mds, incs, azis = [0.0], [0.0], [azi]
    for s in sections:
        L, b, t = float(s["length_m"]), float(s["build_deg_30m"]), float(s["turn_deg_30m"])
        if L <= 0:
            continue
        n = max(1, int(math.ceil(L / float(interval_m) - 1e-9)))
        f = np.linspace(0.0, 1.0, n + 1)[1:]
        mds += list(md0 + f * L); incs += list(inc + b * f * L / 30.0); azis += list(azi + t * f * L / 30.0)
        md0 += L; inc += b * L / 30.0; azi += t * L / 30.0
    return np.asarray(mds), np.clip(np.asarray(incs), 0.0, 180.0), np.asarray(azis) % 360.0


def classify_section(build, turn, inc_start, inc_end, snap=RATE_SNAP_DEG_30M):
    if max(inc_start, inc_end) < 0.5 and abs(build) < snap:
        return "Vertical"
    if abs(turn) >= snap and abs(build) >= snap:
        return "Build & Turn" if build > 0 else "Drop & Turn"
    if abs(turn) >= snap:
        return "Turn"
    if build >= snap:
        return "Build"
    if build <= -snap:
        return "Drop"
    return "Tangent"


def describe_sections(azi0, sections):
    rows = []; md0, inc, azi = 0.0, 0.0, float(azi0)
    for i, s in enumerate(sections):
        L, b, t = float(s["length_m"]), float(s["build_deg_30m"]), float(s["turn_deg_30m"])
        inc1, azi1 = inc + b * L / 30.0, azi + t * L / 30.0
        rows.append({"section": i + 1, "type": classify_section(b, t, inc, inc1), "start_md_m": md0, "end_md_m": md0 + L, "length_m": L,
                     "start_inc_deg": inc, "end_inc_deg": inc1, "start_azi_deg": azi % 360.0, "end_azi_deg": azi1 % 360.0,
                     "build_drop_rate_deg_30m": b, "turn_rate_deg_30m": t})
        md0 += L; inc, azi = inc1, azi1
    return rows


# ------------------------------------------------------------------------------ segmentation
def _prefix(y, x):
    return [np.concatenate(([0.0], np.cumsum(v))) for v in (np.ones_like(x), x, y, x * x, x * y, y * y)]


def _sse(pref, i, j):
    S0, Sx, Sy, Sxx, Sxy, Syy = (p[j + 1] - p[i] for p in pref)
    n = S0; sxx = Sxx - Sx * Sx / n; sxy = Sxy - Sx * Sy / n; syy = Syy - Sy * Sy / n
    return max(0.0, syy - (sxy * sxy / sxx if sxx > 1e-12 else 0.0))


def segment_path(path, max_sections=8, rms_tol_deg=0.75, grid=90):
    """Breakpoint MDs of the fewest constant-rate sections that reproduce the path within ``rms_tol_deg``."""
    md = np.asarray(path["MD"], float); inc = np.asarray(path["Inc"], float)
    azi = np.degrees(np.unwrap(np.radians(np.asarray(path["Azi"], float))))
    g = np.linspace(md[0], md[-1], min(int(grid), max(6, len(md))))
    ig = np.interp(g, md, inc); ag = np.interp(g, md, azi)
    swing = (ag - ag[0]) * np.sin(np.radians(ig))                  # azimuth only matters when the hole is inclined
    m = len(g); pi = _prefix(ig, g); ps = _prefix(swing, g)
    cost = np.full((m, m), np.inf)
    for i in range(m - 1):
        for j in range(i + 1, m):
            cost[i, j] = _sse(pi, i, j) + _sse(ps, i, j)
    best_k = None
    for K in range(1, max_sections + 1):
        dp = np.full((K + 1, m), np.inf); arg = np.zeros((K + 1, m), int); dp[0, 0] = 0.0
        for k in range(1, K + 1):
            for j in range(1, m):
                c = dp[k - 1, :j] + cost[:j, j]; a = int(np.argmin(c)); dp[k, j] = c[a]; arg[k, j] = a
        rms = math.sqrt(dp[K, m - 1] / (2.0 * m))
        if rms <= rms_tol_deg or K == max_sections:
            best_k = K; break
    K = best_k; cuts = [m - 1]; j = m - 1
    for k in range(K, 0, -1):
        j = arg[k, j]; cuts.append(j)
    return [float(g[c]) for c in sorted(set(cuts))]


def initial_sections(path, breaks, min_length_m=30.0):
    """Initial (azi0, sections) fitted to the Stage-1 path at the given breakpoints."""
    md = np.asarray(path["MD"], float); inc = np.asarray(path["Inc"], float)
    azi = np.degrees(np.unwrap(np.radians(np.asarray(path["Azi"], float))))
    bi = np.interp(breaks, md, inc); ba = np.interp(breaks, md, azi)
    nz = np.flatnonzero(bi > 0.5)
    azi0 = float(ba[nz[0]] if len(nz) else ba[-1]) % 360.0
    sections = []
    for k in range(len(breaks) - 1):
        L = max(float(breaks[k + 1] - breaks[k]), min_length_m)
        b = (bi[k + 1] - bi[k]) * 30.0 / L
        t = (ba[k + 1] - ba[k]) * 30.0 / L if max(bi[k], bi[k + 1]) > 0.5 else 0.0
        sections.append({"length_m": L, "build_deg_30m": float(b), "turn_deg_30m": float(t)})
    if sections and bi[0] < 0.5 and abs(sections[0]["build_deg_30m"]) > 0 and bi[1] <= 0.5:
        sections[0]["build_deg_30m"] = 0.0
    return azi0, sections


# ------------------------------------------------------------------------------ optimisation
def reoptimize_sections(stage1_path, *, target_vectors, validate, limits, interval_m=30.0, time_budget_s=20.0,
                        max_sections=8, rms_tol_deg=0.75, min_section_length_m=30.0, max_md_increase_pct=10.0):
    """Stage 2 driver. Returns a result dict; ``adopted`` is True only for a validated, acceptable plan.

    target_vectors(path_dict) -> (eq, ineq, penalty): equality residuals (exact point targets: path - target, metres),
        inequality margins (>= 0 satisfied) for areal targets / vertical bands, and a centre-preference penalty (metres).
    validate(DataFrame[MD, Inc, Azi]) -> validation dict (core.validation.validate_trajectory output).
    limits: max_inclination_deg, max_dls_deg_30m, max_build_rate_deg_30m, max_drop_rate_deg_30m,
    max_turn_rate_deg_30m, max_md_m, min_kop_md_m.
    """
    t0 = time.time()
    out = {"attempted": True, "adopted": False, "status": "RETAINED_ORIGINAL_RECONSTRUCTION_FAILED", "message": "", "attempts": []}
    base_md = float(np.asarray(stage1_path["MD"], float)[-1])
    try:
        for max_sec, tol in ((max_sections, rms_tol_deg), (max_sections, rms_tol_deg * 0.5), (max_sections + 2, rms_tol_deg * 0.5)):
            if time.time() - t0 > time_budget_s:
                break
            breaks = segment_path(stage1_path, max_sec, tol)
            azi0, secs0 = initial_sections(stage1_path, breaks, min_section_length_m)
            for mode in ("practical", "free"):
                if time.time() - t0 > time_budget_s:
                    break
                res = _solve(azi0, secs0, mode, target_vectors, limits, interval_m, min_section_length_m, time_budget_s - (time.time() - t0))
                att = {"sections": len(secs0), "mode": mode, "solver_success": bool(res["success"]), "message": res["message"]}
                if res["azi0"] is None:
                    out["attempts"].append(att); continue
                mds, incs, azis = sections_to_stations(res["azi0"], res["sections"], interval_m)
                cand = pd.DataFrame({"MD": mds, "Inc": incs, "Azi": azis})
                val = validate(cand)
                att.update({"validation_status": val["status"], "violations": list(val.get("violations", [])), "final_md_m": float(mds[-1])})
                out["attempts"].append(att)
                if val["status"] == "PASS":
                    inc_pct = 100.0 * (float(mds[-1]) - base_md) / max(base_md, 1e-9)
                    out.update({"azi0": res["azi0"], "sections": res["sections"], "schedule": describe_sections(res["azi0"], res["sections"]), "path": cand,
                                "validation": val, "mode": mode, "md_change_pct": inc_pct})
                    if inc_pct <= max_md_increase_pct:
                        out.update({"adopted": True, "status": "REOPTIMIZED", "message": f"Section plan validated ({len(res['sections'])} sections, {mode} rates); MD change {inc_pct:+.1f}%."})
                    else:
                        out.update({"status": "RETAINED_ORIGINAL_SECTION_PLAN_TOO_LONG", "message": f"Section plan validated but is {inc_pct:+.1f}% longer than the original (limit {max_md_increase_pct:.0f}%); original retained."})
                    out["seconds"] = round(time.time() - t0, 2)
                    return out
        out["message"] = "No reconstructed section plan passed independent validation; the original feasible trajectory is retained."
    except Exception as ex:                                       # never let Stage 2 break Stage 1
        out["message"] = f"Section reconstruction raised {type(ex).__name__}: {ex}; the original feasible trajectory is retained."
    out["seconds"] = round(time.time() - t0, 2)
    return out


def _solve(azi0, secs0, mode, target_vectors, limits, interval_m, min_len, budget_s):
    K = len(secs0)
    x0 = np.concatenate(([azi0], [s["length_m"] for s in secs0], [s["build_deg_30m"] for s in secs0], [s["turn_deg_30m"] for s in secs0]))
    sc = np.concatenate(([30.0], np.full(K, 100.0), np.ones(K), np.ones(K)))
    # One common DLS ceiling governs build, drop, turn and combined sections.
    mdls = float(limits["max_dls_deg_30m"])
    mb = md = mt = mdls
    kop_min = float(limits.get("min_kop_md_m") or 0.0)
    bnds = [(azi0 - 180.0, azi0 + 180.0)] + [(min_len, float(limits["max_md_m"]))] * K
    fixed_b = [mode == "practical" and abs(s["build_deg_30m"]) < RATE_SNAP_DEG_30M for s in secs0]
    fixed_t = [mode == "practical" and abs(s["turn_deg_30m"]) < RATE_SNAP_DEG_30M for s in secs0]
    # Negative rates are drops and use their own configured limit; positive rates
    # are builds. Do not assume a symmetric build/drop envelope.
    bnds += [(0.0, 0.0) if fixed_b[i] else (-md, mb) for i in range(K)] + [(0.0, 0.0) if fixed_t[i] else (-mt, mt) for i in range(K)]
    if kop_min > 0 and abs(secs0[0]["build_deg_30m"]) < RATE_SNAP_DEG_30M:
        bnds[1] = (max(min_len, kop_min), bnds[1][1])
    x0 = np.array([min(max(v, lo), hi) for v, (lo, hi) in zip(x0, bnds)])
    cache = {}

    def unpack(u):
        x = u * sc
        return x[0], [{"length_m": x[1 + i], "build_deg_30m": x[1 + K + i], "turn_deg_30m": x[1 + 2 * K + i]} for i in range(K)]

    def built(u):
        if time.time() - t0 >= float(budget_s):
            raise TimeoutError('Section optimization time budget exhausted.')
        key = u.tobytes()
        if key not in cache:
            if len(cache) > 4000: cache.clear()
            a0, secs = unpack(u); mds, incs, azis = sections_to_stations(a0, secs, interval_m)
            n, e, z, d = mc_core(mds, incs, azis, 30.0)
            path = {"MD": mds, "Inc": incs, "Azi": azis, "Northing": n, "Easting": e, "TVD": z, "DLS": d}
            eq, ineq, pen = target_vectors(path)
            inc_end = np.concatenate(([0.0], np.cumsum([s["build_deg_30m"] * s["length_m"] / 30.0 for s in secs])))
            cache[key] = (path, np.asarray(eq, float), np.asarray(ineq, float), inc_end, float(pen))
        return cache[key]

    def f(u):
        if time.time() - t0 >= float(budget_s):
            raise TimeoutError('Section optimization time budget exhausted.')
        _, secs = unpack(u)
        total = sum(s["length_m"] for s in secs)
        return total + 0.05 * sum(s["length_m"] * (s["build_deg_30m"] ** 2 + s["turn_deg_30m"] ** 2) for s in secs) + built(u)[4]

    def c_eq(u): return built(u)[1]
    def c_ineq(u):
        """Fixed-size inequality vector (SLSQP requires it): targets, per-section DLS bound, inclination, total MD."""
        path, _, ineq, inc_end, _ = built(u)
        _, secs = unpack(u)
        # DLS inside a constant-rate section <= sqrt(build^2 + (turn * sin(inc_max))^2) (conservative bound); the
        # independent validator still checks the actual stations.
        dls_b = np.array([math.sqrt(s["build_deg_30m"] ** 2 + (s["turn_deg_30m"] * math.sin(math.radians(min(90.0, max(inc_end[i], inc_end[i + 1], 0.0))))) ** 2)
                          for i, s in enumerate(secs)])
        return np.concatenate((ineq, float(limits["max_dls_deg_30m"]) * 0.9995 - dls_b, float(limits["max_inclination_deg"]) * 0.9995 - inc_end[1:], inc_end[1:],
                               [float(limits["max_md_m"]) - path["MD"][-1]]))
    cons = []
    if len(built(x0 / sc)[1]): cons.append({"type": "eq", "fun": c_eq})
    cons.append({"type": "ineq", "fun": c_ineq})
    try:
        r = minimize(lambda u: f(u) / 100.0, x0 / sc, method="SLSQP", bounds=[(lo / s, hi / s) for (lo, hi), s in zip(bnds, sc)], constraints=cons,
                     options={"maxiter": 250, "ftol": 1e-12})
        a0, secs = unpack(r.x)
        return {"azi0": float(a0) % 360.0, "sections": [{k: float(v) for k, v in s.items()} for s in secs], "success": bool(r.success), "message": str(r.message)}
    except Exception as ex:
        return {"azi0": None, "sections": [], "success": False, "message": f"{type(ex).__name__}: {ex}"}
