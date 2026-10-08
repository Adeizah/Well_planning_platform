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
    s_i = math.radians(float(sigma_inc_deg))
    s_a = math.radians(float(sigma_azi_deg))
    s_i_sys = math.radians(float(sigma_inc_systematic_deg))
    s_a_sys = math.radians(float(sigma_azi_systematic_deg))
    s_surface = float(sigma_surface_ft) * 0.3048
    if min(s_md, s_i, s_a, s_i_sys, s_a_sys, s_surface) < 0:
        raise ValueError("Survey uncertainty values cannot be negative.")

    random_cov = np.eye(3, dtype=float) * s_surface**2
    records = [random_cov.copy()]

    # Random station-error contribution plus one correlated systematic-bias
    # contribution for the complete path to each station. The systematic term is
    # deliberately added once per station, not once per segment, because it is a
    # common-mode bias shared by the whole trajectory-to-date.
    for j in range(1, len(w)):
        row0, row1 = w.iloc[j - 1], w.iloc[j]
        x = np.array([row0.MD, row0.Inc, row0.Azi, row1.Inc, row1.Azi], dtype=float)
        steps = np.array([max(1e-4, s_md / 10.0), max(1e-6, s_i / 10.0),
                          max(1e-6, s_a / 10.0), max(1e-6, s_i / 10.0),
                          max(1e-6, s_a / 10.0)])

        def f(z):
            return _segment_position(z[0], z[1], z[2], row1.MD, z[3], z[4])

        J = _numeric_jacobian(f, x, steps)
        q = np.diag([s_md**2, s_i**2, s_a**2, s_i**2, s_a**2])
        random_cov = random_cov + J @ q @ J.T
        random_cov = 0.5 * (random_cov + random_cov.T)

        base = w.iloc[:j+1].copy()
        def endpoint(bi, ba):
            vals = base.copy()
            vals["Inc"] = vals["Inc"] + bi
            vals["Azi"] = vals["Azi"] + ba
            pos = np.zeros(3)
            for k in range(1, len(vals)):
                pos += _segment_position(vals.iloc[k-1].MD, vals.iloc[k-1].Inc,
                                         vals.iloc[k-1].Azi, vals.iloc[k].MD,
                                         vals.iloc[k].Inc, vals.iloc[k].Azi)
            return pos
        # endpoint() accepts angular biases in degrees, so compute numerical
        # derivatives per degree and apply the systematic standard deviations in degrees.
        s_i_sys_deg=float(sigma_inc_systematic_deg)
        s_a_sys_deg=float(sigma_azi_systematic_deg)
        h_i=max(1e-5, s_i_sys_deg/10.0)
        h_a=max(1e-5, s_a_sys_deg/10.0)
        ji=(endpoint(h_i,0.0)-endpoint(-h_i,0.0))/(2*h_i) if s_i_sys_deg>0 else np.zeros(3)
        ja=(endpoint(0.0,h_a)-endpoint(0.0,-h_a))/(2*h_a) if s_a_sys_deg>0 else np.zeros(3)
        sys_cov=np.outer(ji,ji)*s_i_sys_deg**2 + np.outer(ja,ja)*s_a_sys_deg**2
        cov=random_cov + sys_cov
        cov = 0.5 * (cov + cov.T)
        records.append(cov.copy())

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
