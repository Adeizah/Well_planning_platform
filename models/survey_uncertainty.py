"""Transparent covariance-based survey position uncertainty.

This module intentionally implements an engineering-development model, not an
ISCWSA-certified error model. It propagates independent station measurement
errors (MD, inclination and azimuth) through minimum-curvature segment
increments and returns a 3x3 North/East/TVD position covariance at each station.
"""
import math
import numpy as np
import pandas as pd

from core.trajectory import _dogleg


def _segment_position(md1, inc1, azi1, md2, inc2, azi2):
    """Minimum-curvature displacement [N,E,TVD] for one survey interval."""
    dl = float(md2 - md1)
    if dl <= 0:
        raise ValueError("Survey MD must increase strictly.")
    i1, i2 = np.radians([inc1, inc2])
    a1, a2 = np.radians([azi1, azi2])
    dog = np.radians(_dogleg(inc1, azi1, inc2, azi2))
    rf = 1.0 if abs(dog) < 1e-12 else 2.0 / dog * np.tan(dog / 2.0)
    dn = dl / 2.0 * (np.sin(i1) * np.cos(a1) + np.sin(i2) * np.cos(a2)) * rf
    de = dl / 2.0 * (np.sin(i1) * np.sin(a1) + np.sin(i2) * np.sin(a2)) * rf
    dz = dl / 2.0 * (np.cos(i1) + np.cos(i2)) * rf
    return np.array([dn, de, dz], dtype=float)


def _numeric_jacobian(fun, x, steps):
    x = np.asarray(x, dtype=float)
    y0 = np.asarray(fun(x), dtype=float)
    J = np.zeros((len(y0), len(x)), dtype=float)
    for k, h in enumerate(steps):
        xp = x.copy(); xm = x.copy()
        xp[k] += h; xm[k] -= h
        J[:, k] = (np.asarray(fun(xp)) - np.asarray(fun(xm))) / (2.0 * h)
    return J


def _segment_positions_vec(md0, inc0, azi0, md1, inc1, azi1):
    """Vectorised minimum-curvature displacement [N, E, TVD] for many intervals (angles in degrees)."""
    dl = np.asarray(md1, dtype=float) - np.asarray(md0, dtype=float)
    i1, i2 = np.radians(inc0), np.radians(inc1)
    a1, a2 = np.radians(azi0), np.radians(azi1)
    dog = np.radians(_dogleg(inc0, azi0, inc1, azi1))
    rf = np.ones_like(dog)
    nz = np.abs(dog) >= 1e-12
    rf[nz] = 2.0 / dog[nz] * np.tan(dog[nz] / 2.0)
    dn = dl / 2.0 * (np.sin(i1) * np.cos(a1) + np.sin(i2) * np.cos(a2)) * rf
    de = dl / 2.0 * (np.sin(i1) * np.sin(a1) + np.sin(i2) * np.sin(a2)) * rf
    dz = dl / 2.0 * (np.cos(i1) + np.cos(i2)) * rf
    return np.stack([dn, de, dz], axis=1)


def station_covariances(df, sigma_md_ft=0.5, sigma_inc_deg=0.10, sigma_azi_deg=0.25,
                        sigma_inc_systematic_deg=0.10, sigma_azi_systematic_deg=0.25,
                        sigma_surface_ft=5.0, units="m"):
    """Return stationwise position covariance using a transparent development model.

    The model has two parts:
      1) independent station measurement errors, accumulated segment-by-segment;
      2) correlated systematic inclination/azimuth biases applied coherently along
         the trajectory, plus a surface-position covariance.

    This produces a 3x3 North/East/TVD covariance and 1-sigma horizontal ellipse
    summaries. It is deliberately NOT an ISCWSA error model and must not be
    described as such without separate validation.

    Implementation note: the numerical model is unchanged from the original
    per-station loop, but is now evaluated for all segments at once (O(n) instead
    of O(n^2)), so a 300-station survey takes milliseconds instead of ~45 s.
    Known model limitation (unchanged): random errors of adjacent segments are
    treated as independent although each station error is shared by two segments.
    """
    w = pd.DataFrame(df).copy().sort_values("MD").reset_index(drop=True)
    required = {"MD", "Inc", "Azi"}
    if not required.issubset(w.columns):
        raise ValueError("Survey requires MD, Inc and Azi columns.")
    if len(w) < 2:
        raise ValueError("At least two survey stations are required for covariance propagation.")
    for c in required:
        w[c] = pd.to_numeric(w[c], errors="raise")
    if not w["MD"].diff().dropna().gt(0).all():
        raise ValueError("MD must increase strictly.")

    s_md = float(sigma_md_ft) * 0.3048
    s_surface = float(sigma_surface_ft) * 0.3048
    s_i_deg, s_a_deg = float(sigma_inc_deg), float(sigma_azi_deg)
    s_i_sys_deg, s_a_sys_deg = float(sigma_inc_systematic_deg), float(sigma_azi_systematic_deg)
    if min(s_md, s_i_deg, s_a_deg, s_i_sys_deg, s_a_sys_deg, s_surface) < 0:
        raise ValueError("Survey uncertainty values cannot be negative.")

    md = w["MD"].to_numpy(float); inc = w["Inc"].to_numpy(float); azi = w["Azi"].to_numpy(float)
    n = len(w)

    # ---- random (independent) part: Jacobian of every segment w.r.t. [MD0, inc0, azi0, inc1, azi1]
    x = np.stack([md[:-1], inc[:-1], azi[:-1], inc[1:], azi[1:]], axis=1)          # (n-1, 5)
    steps = np.array([max(1e-4, s_md / 10.0), max(1e-4, s_i_deg / 10.0), max(1e-4, s_a_deg / 10.0),
                      max(1e-4, s_i_deg / 10.0), max(1e-4, s_a_deg / 10.0)])

    def seg(z):
        return _segment_positions_vec(z[:, 0], z[:, 1], z[:, 2], md[1:], z[:, 3], z[:, 4])

    J = np.zeros((n - 1, 3, 5))
    for k, h in enumerate(steps):
        xp = x.copy(); xm = x.copy()
        xp[:, k] += h; xm[:, k] -= h
        J[:, :, k] = (seg(xp) - seg(xm)) / (2.0 * h)
    q = np.diag([s_md ** 2, s_i_deg ** 2, s_a_deg ** 2, s_i_deg ** 2, s_a_deg ** 2])
    seg_cov = np.einsum('sik,kl,sjl->sij', J, q, J)                                # (n-1, 3, 3)
    random_cov = np.concatenate([np.zeros((1, 3, 3)), np.cumsum(seg_cov, axis=0)], axis=0)
    random_cov = random_cov + np.eye(3)[None, :, :] * s_surface ** 2

    # ---- systematic (common-mode) part: endpoint sensitivity to angular bias for every station at once
    def cumulative_endpoint(bi, ba):
        d = _segment_positions_vec(md[:-1], inc[:-1] + bi, azi[:-1] + ba, md[1:], inc[1:] + bi, azi[1:] + ba)
        return np.concatenate([np.zeros((1, 3)), np.cumsum(d, axis=0)], axis=0)

    h_i = max(1e-5, s_i_sys_deg / 10.0); h_a = max(1e-5, s_a_sys_deg / 10.0)
    ji = (cumulative_endpoint(h_i, 0.0) - cumulative_endpoint(-h_i, 0.0)) / (2 * h_i) if s_i_sys_deg > 0 else np.zeros((n, 3))
    ja = (cumulative_endpoint(0.0, h_a) - cumulative_endpoint(0.0, -h_a)) / (2 * h_a) if s_a_sys_deg > 0 else np.zeros((n, 3))
    sys_cov = (np.einsum('si,sj->sij', ji, ji) * s_i_sys_deg ** 2 +
               np.einsum('si,sj->sij', ja, ja) * s_a_sys_deg ** 2)
    cov = random_cov + sys_cov
    cov = 0.5 * (cov + np.transpose(cov, (0, 2, 1)))
    records = [cov[i] for i in range(n)]

    out = w.copy()
    for name, idx in [("NN", (0, 0)), ("NE", (0, 1)), ("NT", (0, 2)),
                      ("EE", (1, 1)), ("ET", (1, 2)), ("TT", (2, 2))]:
        out[f"Cov_{name}_m2"] = [c[idx] for c in records]

    major, minor, orient, vert = [], [], [], []
    for c in records:
        horiz = c[:2, :2]
        vals, vecs = np.linalg.eigh(horiz)
        vals = np.maximum(vals, 0.0)
        order = np.argsort(vals)[::-1]
        vals = vals[order]; vec = vecs[:, order[0]]
        major.append(math.sqrt(vals[0]))
        minor.append(math.sqrt(vals[1]))
        orient.append(math.degrees(math.atan2(vec[1], vec[0])) % 180.0)
        vert.append(math.sqrt(max(c[2, 2], 0.0)))
    out["Unc_major_1sigma_m"] = major
    out["Unc_minor_1sigma_m"] = minor
    out["Unc_azimuth_deg"] = orient
    out["Unc_vertical_1sigma_m"] = vert
    return out

def covariance_columns():
    return ["Cov_NN_m2", "Cov_NE_m2", "Cov_NT_m2", "Cov_EE_m2", "Cov_ET_m2", "Cov_TT_m2"]


def interpolate_covariance(df, md):
    """Linearly interpolate each covariance component at an arbitrary MD."""
    if df.empty or "MD" not in df.columns:
        raise ValueError("Covariance dataframe is empty or missing MD.")
    x = df["MD"].to_numpy(dtype=float)
    md = float(np.clip(md, x.min(), x.max()))
    vals = [float(np.interp(md, x, df[c].to_numpy(dtype=float))) for c in covariance_columns()]
    return np.array([[vals[0], vals[1], vals[2]],
                     [vals[1], vals[3], vals[4]],
                     [vals[2], vals[4], vals[5]]], dtype=float)
