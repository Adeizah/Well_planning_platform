"""Covariance-based anti-collision screening (engineering-development grade).

NOT an ISCWSA-certified implementation and NOT a company separation rule. The
separation factor here is centre-to-centre distance divided by the 1-sigma
relative position uncertainty projected onto the line joining the two wells.

Changes in this revision (see CHANGELOG):
* FIXED: the centre-to-centre unit vector was built in (East, North, TVD) order
  but contracted with a covariance matrix ordered (North, East, TVD). North and
  East were therefore swapped in the directional sigma, which could turn a
  WARNING into a PASS for wells separated North-South (and vice versa).
* Wellbore positions between stations now follow the minimum-curvature arc
  (exact), not straight chords, and sample spacing is bounded (default 10 m).
* The closest-approach and minimum-SF pairs are refined continuously after the
  grid search, so the reported values no longer depend on the sample spacing.
* Optional hole/casing radii and a hard minimum centre-to-centre distance.
* Collision-risk MD intervals and a per-sample clearance profile are reported.
"""
import math
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core.trajectory import minimum_curvature, interpolate_path
from models.survey_uncertainty import station_covariances, interpolate_covariance

_COV_COLS = ["Cov_NN_m2", "Cov_NE_m2", "Cov_NT_m2", "Cov_EE_m2", "Cov_ET_m2", "Cov_TT_m2"]


def _prepare_trajectory(raw):
    df = pd.DataFrame(raw or []).copy()
    if df.empty or 'MD' not in df.columns:
        return pd.DataFrame()
    # Accept either already-calculated positional trajectories or raw survey stations.
    if not {"Easting", "Northing", "TVD"}.issubset(df.columns):
        if not {"Inc", "Azi"}.issubset(df.columns):
            return pd.DataFrame()
        try:
            df = minimum_curvature(df[["MD", "Inc", "Azi"]].copy())
        except Exception:
            return pd.DataFrame()
    for c in ["MD", "Easting", "Northing", "TVD"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["MD", "Easting", "Northing", "TVD"]).sort_values("MD").reset_index(drop=True)
    if len(df) < 2 or not df["MD"].diff().dropna().gt(0).all():
        return pd.DataFrame()
    return df


def _sample_count(df, samples, max_spacing_m=10.0, cap=700):
    length = float(df.MD.max() - df.MD.min())
    return int(min(cap, max(2, int(samples), int(math.ceil(length / max_spacing_m)) + 1)))


def _xyz_at(df, md):
    """[North, East, TVD] at arbitrary MDs, on the minimum-curvature arc when angles exist."""
    md = np.atleast_1d(np.asarray(md, dtype=float))
    if {"Inc", "Azi"}.issubset(df.columns) and df[["Inc", "Azi"]].notna().all().all():
        p = interpolate_path(df, md)
        return np.column_stack([p["Northing"], p["Easting"], p["TVD"]])
    return np.column_stack([np.interp(md, df.MD, df[c]) for c in ("Northing", "Easting", "TVD")])


def _sample(df, n=300):
    md = np.linspace(float(df.MD.min()), float(df.MD.max()), max(2, int(n)))
    return md, _xyz_at(df, md)  # columns: North, East, TVD (same order as the covariance matrices)


def _cov_at(cov_df, md):
    """Covariance matrices (n,3,3) in (North, East, TVD) order, linearly interpolated in MD."""
    x = cov_df["MD"].to_numpy(float)
    m = np.clip(np.asarray(md, dtype=float), x.min(), x.max())
    v = {c: np.interp(m, x, cov_df[c].to_numpy(float)) for c in _COV_COLS}
    out = np.empty((len(m), 3, 3))
    out[:, 0, 0] = v["Cov_NN_m2"]; out[:, 0, 1] = out[:, 1, 0] = v["Cov_NE_m2"]; out[:, 0, 2] = out[:, 2, 0] = v["Cov_NT_m2"]
    out[:, 1, 1] = v["Cov_EE_m2"]; out[:, 1, 2] = out[:, 2, 1] = v["Cov_ET_m2"]; out[:, 2, 2] = v["Cov_TT_m2"]
    return out


def _directional_sigma(diff_net, cov_main, cov_off):
    """1-sigma of the relative position along the centre-to-centre direction.

    ``diff_net`` is main - offset in (North, East, TVD) order and the covariances are
    in the same order. Returns (distance, sigma).
    """
    dist = np.linalg.norm(diff_net, axis=-1)
    unit = np.divide(diff_net, dist[..., None], out=np.zeros_like(diff_net), where=dist[..., None] > 1e-9)
    rel = cov_main + cov_off
    var = np.einsum('...i,...ij,...j->...', unit, rel, unit)
    coincident = dist <= 1e-9
    if np.any(coincident):
        trace = np.trace(rel, axis1=-2, axis2=-1) / 3.0
        var = np.where(coincident, trace, var)
    return dist, np.sqrt(np.maximum(var, 0.0))


def _legacy_error_model(survey_error_model, samples_per_well):
    if isinstance(survey_error_model, (int, float, np.integer, np.floating)):
        legacy_main = float(survey_error_model)
        # Legacy sigma values were metres; convert to an illustrative station-error scale.
        return ({"sigma_md_ft": max(0.1, legacy_main / 2.0 / 0.3048), "sigma_inc_deg": 0.10, "sigma_azi_deg": 0.25}, 300)
    return (survey_error_model or {}), samples_per_well


def _survey_for_uncertainty(df):
    if {"MD", "Inc", "Azi"}.issubset(df.columns):
        return df[["MD", "Inc", "Azi"]].copy()
    # Positional trajectories can still be screened: derive approximate orientation from chords.
    w = df.sort_values("MD").reset_index(drop=True).copy()
    inc = np.zeros(len(w)); azi = np.zeros(len(w))
    for k in range(1, len(w)):
        dl = float(w.loc[k, "MD"] - w.loc[k - 1, "MD"])
        dn = float(w.loc[k, "Northing"] - w.loc[k - 1, "Northing"])
        de = float(w.loc[k, "Easting"] - w.loc[k - 1, "Easting"])
        dz = float(w.loc[k, "TVD"] - w.loc[k - 1, "TVD"])
        if dl > 0:
            inc[k] = np.degrees(np.arccos(np.clip(dz / dl, -1, 1)))
            azi[k] = np.degrees(np.arctan2(de, dn)) % 360.0
    if len(w) > 1:
        inc[0] = inc[1]; azi[0] = azi[1]
    return pd.DataFrame({"MD": w["MD"].to_numpy(), "Inc": inc, "Azi": azi})


def _cov_df(df, model):
    return station_covariances(
        _survey_for_uncertainty(df),
        sigma_md_ft=model.get("sigma_md_ft", 0.5), sigma_inc_deg=model.get("sigma_inc_deg", 0.10),
        sigma_azi_deg=model.get("sigma_azi_deg", 0.25),
        sigma_inc_systematic_deg=model.get("sigma_inc_systematic_deg", 0.10),
        sigma_azi_systematic_deg=model.get("sigma_azi_systematic_deg", 0.25),
        sigma_surface_ft=model.get("sigma_surface_ft", 5.0))


def _refine(fun, x0, lo, hi):
    """Bounded local refinement of a 2-variable (main MD, offset MD) objective."""
    try:
        res = minimize(fun, x0, method="L-BFGS-B", bounds=list(zip(lo, hi)),
                       options={"maxiter": 60, "ftol": 1e-12, "gtol": 1e-9})
        if np.isfinite(res.fun) and res.fun <= fun(x0) + 1e-12:
            return np.asarray(res.x, dtype=float), float(res.fun)
    except Exception:
        pass
    return np.asarray(x0, dtype=float), float(fun(x0))


class _PairContext:
    """Everything needed to evaluate separation / SF for one main-offset pair."""

    def __init__(self, main, main_cov, main_shift_ne, off, off_cov, off_shift_ne, n_main, n_off):
        self.main, self.off, self.main_cov, self.off_cov = main, off, main_cov, off_cov
        self.ms, self.os_ = np.asarray([main_shift_ne[0], main_shift_ne[1], 0.0]), np.asarray([off_shift_ne[0], off_shift_ne[1], 0.0])
        self.main_md = np.linspace(float(main.MD.min()), float(main.MD.max()), n_main)
        self.off_md = np.linspace(float(off.MD.min()), float(off.MD.max()), n_off)
        self.main_xyz = _xyz_at(main, self.main_md) + self.ms
        self.off_xyz = _xyz_at(off, self.off_md) + self.os_
        self.main_covs = _cov_at(main_cov, self.main_md)
        self.off_covs = _cov_at(off_cov, self.off_md)

    def point_distance(self, x):
        a = _xyz_at(self.main, [x[0]])[0] + self.ms
        b = _xyz_at(self.off, [x[1]])[0] + self.os_
        return float(np.linalg.norm(a - b))

    def point_sf(self, x, r_sum):
        a = _xyz_at(self.main, [x[0]])[0] + self.ms
        b = _xyz_at(self.off, [x[1]])[0] + self.os_
        d, s = _directional_sigma((a - b)[None, :], _cov_at(self.main_cov, [x[0]]), _cov_at(self.off_cov, [x[1]]))
        if s[0] <= 1e-12:
            return float('inf')
        return float(max(d[0] - r_sum, 0.0) / s[0])


def _risk_intervals(main_md, sf_per_main, off_md_at_min, threshold):
    out = []; start = None
    for k, v in enumerate(sf_per_main):
        bad = np.isfinite(v) and v < threshold
        if bad and start is None:
            start = k
        if (not bad or k == len(sf_per_main) - 1) and start is not None:
            end = k if bad else k - 1
            seg = sf_per_main[start:end + 1]; j = int(np.nanargmin(seg)) + start
            out.append({"main_md_start_m": float(main_md[start]), "main_md_end_m": float(main_md[end]),
                        "min_sf": float(sf_per_main[j]), "main_md_at_min_m": float(main_md[j]),
                        "offset_md_at_min_m": float(off_md_at_min[j])})
            start = None
    return out


def clearance_report(main_df, offsets, survey_error_model=None, samples_per_well=300,
                     main_surface_easting_m=0.0, main_surface_northing_m=0.0,
                     required_separation_factor=2.0, criteria=None, main_kb_m=None):
    """Covariance-based anti-collision screening.

    Main and offset trajectories are normalized to the same project CRS before
    comparison. Position uncertainty is represented by a 3x3 North/East/TVD
    covariance propagated from illustrative survey measurement errors.

    ``criteria`` (all optional): ``warning_fraction`` (default 0.5 of the required SF),
    ``main_radius_m`` / ``offset_radius_m`` (hole or casing radius subtracted from the
    centre-to-centre distance before dividing by sigma), ``min_separation_m`` (hard
    minimum centre-to-centre distance; below it the status is ALERT whatever the SF),
    ``max_sample_spacing_m`` (default 10 m).

    ``main_kb_m``: KB elevation (m above MSL) of the main well. When given and an offset carries
    its own ``kb_m``, the offset TVD is shifted by (main KB - offset KB) so both wells share one
    TVD datum (TVD is measured from each well's own KB). Without it the two TVDs are assumed to
    share a datum, which is only correct when the KB elevations are equal.

    This is an engineering-development implementation. It is deliberately NOT
    presented as an ISCWSA-certified error model or company separation rule.
    """
    crit = dict(criteria or {})
    warn_fraction = float(crit.get("warning_fraction", 0.5))
    r_sum = float(crit.get("main_radius_m", 0.0) or 0.0) + float(crit.get("offset_radius_m", 0.0) or 0.0)
    min_sep = crit.get("min_separation_m")
    spacing = float(crit.get("max_sample_spacing_m", 10.0))
    threshold = max(0.1, float(required_separation_factor))

    main = _prepare_trajectory(main_df.to_dict("records") if isinstance(main_df, pd.DataFrame) else main_df)
    columns = ["offset", "main_md_m", "offset_md_m", "separation_m", "horizontal_separation_m",
               "vertical_separation_m", "directional_uncertainty_m", "separation_factor",
               "minimum_sf_separation_m", "minimum_sf_directional_uncertainty_m",
               "minimum_sf_main_md_m", "minimum_sf_offset_md_m", "separation_factor_at_closest_approach",
               "status", "note", "required_separation_factor", "risk_intervals"]
    if len(main) < 2:
        return pd.DataFrame(columns=columns)
    model, samples_per_well = _legacy_error_model(survey_error_model, samples_per_well)

    main_cov_df = _cov_df(main, model)
    rows = []
    for off in offsets or []:
        odf = _prepare_trajectory(off.get("surveys", []))
        if len(odf) < 2:
            rows.append({"offset": off.get("name", "Offset"), "main_md_m": np.nan, "offset_md_m": np.nan,
                         "separation_m": np.nan, "horizontal_separation_m": np.nan, "vertical_separation_m": np.nan,
                         "directional_uncertainty_m": np.nan, "separation_factor": np.nan,
                         "minimum_sf_separation_m": np.nan, "minimum_sf_directional_uncertainty_m": np.nan,
                         "minimum_sf_main_md_m": np.nan, "minimum_sf_offset_md_m": np.nan, "status": "NOT CHECKED",
                         "note": "No valid offset trajectory with MD, Inc and Azi/position data.",
                         "required_separation_factor": threshold, "risk_intervals": []})
            continue
        if main_kb_m is not None and off.get("kb_m") is not None and abs(float(off["kb_m"]) - float(main_kb_m)) > 1e-9:
            odf = odf.copy(); odf["TVD"] = odf["TVD"] + (float(main_kb_m) - float(off["kb_m"]))
        off_cov_df = _cov_df(odf, model)
        n_main = _sample_count(main, samples_per_well, spacing); n_off = _sample_count(odf, samples_per_well, spacing)
        ctx = _PairContext(main, main_cov_df, (float(main_surface_northing_m or 0.0), float(main_surface_easting_m or 0.0)),
                           odf, off_cov_df, (float(off.get("surface_northing_m", 0.0) or 0.0), float(off.get("surface_easting_m", 0.0) or 0.0)),
                           n_main, n_off)
        diff = ctx.main_xyz[:, None, :] - ctx.off_xyz[None, :, :]               # (N, E, TVD)
        dist, sigma_grid = _directional_sigma(diff, ctx.main_covs[:, None, :, :], ctx.off_covs[None, :, :, :])
        sf_grid = np.divide(np.maximum(dist - r_sum, 0.0), sigma_grid, out=np.full_like(dist, np.inf), where=sigma_grid > 1e-12)
        sf_grid = np.where(np.isfinite(sigma_grid), sf_grid, np.nan)

        # ---- geometric closest approach: grid seed, then continuous refinement on the arcs
        i, j = np.unravel_index(np.argmin(dist), dist.shape)
        d_step_m = float(ctx.main_md[1] - ctx.main_md[0]); d_step_o = float(ctx.off_md[1] - ctx.off_md[0])
        xr, dr = _refine(ctx.point_distance, [ctx.main_md[i], ctx.off_md[j]],
                         [max(ctx.main_md[0], ctx.main_md[i] - d_step_m), max(ctx.off_md[0], ctx.off_md[j] - d_step_o)],
                         [min(ctx.main_md[-1], ctx.main_md[i] + d_step_m), min(ctx.off_md[-1], ctx.off_md[j] + d_step_o)])
        a = _xyz_at(main, [xr[0]])[0] + ctx.ms; b = _xyz_at(odf, [xr[1]])[0] + ctx.os_
        dn, de, dz = (a - b)
        sep = float(np.linalg.norm(a - b)); horiz = float(math.hypot(de, dn))
        d_cl, s_cl = _directional_sigma((a - b)[None, :], _cov_at(main_cov_df, [xr[0]]), _cov_at(off_cov_df, [xr[1]]))
        directional_sigma = float(s_cl[0])
        sf_at_closest = float(max(d_cl[0] - r_sum, 0.0) / directional_sigma) if directional_sigma > 1e-12 else np.inf
        closest_main_md, closest_off_md = float(xr[0]), float(xr[1])

        # ---- minimum separation factor: grid seed, then refinement
        if np.all(np.isnan(sf_grid)):
            si, sj = i, j; min_sf = float('nan'); min_sf_sep = sep; min_sf_sigma = float('nan')
            sf_main_md, sf_off_md = closest_main_md, closest_off_md
        else:
            si, sj = np.unravel_index(np.nanargmin(sf_grid), sf_grid.shape)
            xs, fs = _refine(lambda x: ctx.point_sf(x, r_sum), [ctx.main_md[si], ctx.off_md[sj]],
                             [max(ctx.main_md[0], ctx.main_md[si] - d_step_m), max(ctx.off_md[0], ctx.off_md[sj] - d_step_o)],
                             [min(ctx.main_md[-1], ctx.main_md[si] + d_step_m), min(ctx.off_md[-1], ctx.off_md[sj] + d_step_o)])
            a2 = _xyz_at(main, [xs[0]])[0] + ctx.ms; b2 = _xyz_at(odf, [xs[1]])[0] + ctx.os_
            d2, s2 = _directional_sigma((a2 - b2)[None, :], _cov_at(main_cov_df, [xs[0]]), _cov_at(off_cov_df, [xs[1]]))
            min_sf = float(fs); min_sf_sep = float(d2[0]); min_sf_sigma = float(s2[0])
            sf_main_md, sf_off_md = float(xs[0]), float(xs[1])

        surface_sigma_zero_at_closest = (closest_main_md <= 1e-6 and closest_off_md <= 1e-6 and
                                         float(model.get("sigma_surface_ft", 5.0) or 0.0) <= 0.0)
        intervals = []
        if (not np.isfinite(min_sf_sigma) or min_sf_sigma <= 1e-12 or not np.isfinite(min_sf) or surface_sigma_zero_at_closest):
            status = "REVIEW"
            if surface_sigma_zero_at_closest:
                note = "Geometric closest approach is at the wellhead (MD≈0) and surface-position σ is set to 0 ft. Wellhead-position uncertainty is therefore not represented; verify a justified non-zero surface-position uncertainty before interpreting clearance."
            else:
                note = "Propagated uncertainty is zero or invalid at the minimum-SF pair. Check survey stations, angular-error propagation, and surface-position assumptions; do not interpret as clearance."
        else:
            status = "PASS" if min_sf >= threshold else ("WARNING" if min_sf >= threshold * warn_fraction else "ALERT")
            hard = min_sep is not None and sep < float(min_sep)
            if hard:
                status = "ALERT"
            sf_main = np.where(np.all(np.isnan(sf_grid), axis=1), np.nan, np.nanmin(np.where(np.isnan(sf_grid), np.inf, sf_grid), axis=1))
            arg_off = np.nanargmin(np.where(np.isnan(sf_grid), np.inf, sf_grid), axis=1)
            intervals = _risk_intervals(ctx.main_md, sf_main, ctx.off_md[arg_off], threshold)
            note = (f"Classified using minimum covariance-based SF {min_sf:.2f} at MD pair {sf_main_md:.1f}/{sf_off_md:.1f} m; "
                    f"threshold {threshold:.2f} is configurable, not universal"
                    + (f"; hard minimum centre-to-centre distance {float(min_sep):.1f} m {'VIOLATED' if hard else 'met'}" if min_sep is not None else "")
                    + (f"; hole/casing radii {r_sum:.3f} m subtracted" if r_sum else "")
                    + ". Sampling/model limitations apply; production work requires validated uncertainty models and company-approved separation rules.")
        rows.append({"offset": off.get("name", "Offset"), "main_md_m": closest_main_md, "offset_md_m": closest_off_md,
                     "separation_m": sep, "horizontal_separation_m": horiz, "vertical_separation_m": abs(float(dz)),
                     "directional_uncertainty_m": directional_sigma, "separation_factor": min_sf,
                     "minimum_sf_separation_m": min_sf_sep, "minimum_sf_directional_uncertainty_m": min_sf_sigma,
                     "minimum_sf_main_md_m": sf_main_md, "minimum_sf_offset_md_m": sf_off_md,
                     "separation_factor_at_closest_approach": sf_at_closest, "status": status, "note": note,
                     "required_separation_factor": threshold, "risk_intervals": intervals})
    return pd.DataFrame(rows, columns=columns)


def clearance_profile(main_df, offset, survey_error_model=None, main_surface_easting_m=0.0,
                      main_surface_northing_m=0.0, samples=300, criteria=None):
    """Per-MD clearance of the main well against ONE offset (centre distance, sigma, SF).

    Gives the between-station view required for collision-risk interval reports and plots.
    """
    crit = dict(criteria or {}); r_sum = float(crit.get("main_radius_m", 0.0) or 0.0) + float(crit.get("offset_radius_m", 0.0) or 0.0)
    main = _prepare_trajectory(main_df.to_dict("records") if isinstance(main_df, pd.DataFrame) else main_df)
    odf = _prepare_trajectory(offset.get("surveys", []))
    if len(main) < 2 or len(odf) < 2:
        return pd.DataFrame(columns=["main_md_m", "min_separation_m", "offset_md_at_min_separation_m", "min_sf", "offset_md_at_min_sf_m"])
    model = survey_error_model or {}
    ctx = _PairContext(main, _cov_df(main, model), (float(main_surface_northing_m or 0.0), float(main_surface_easting_m or 0.0)), odf, _cov_df(odf, model),
                       (float(offset.get("surface_northing_m", 0.0) or 0.0), float(offset.get("surface_easting_m", 0.0) or 0.0)),
                       _sample_count(main, samples, float(crit.get("max_sample_spacing_m", 10.0))), _sample_count(odf, samples, float(crit.get("max_sample_spacing_m", 10.0))))
    diff = ctx.main_xyz[:, None, :] - ctx.off_xyz[None, :, :]
    dist, sig = _directional_sigma(diff, ctx.main_covs[:, None, :, :], ctx.off_covs[None, :, :, :])
    sf = np.divide(np.maximum(dist - r_sum, 0.0), sig, out=np.full_like(dist, np.inf), where=sig > 1e-12)
    jd = np.argmin(dist, axis=1); js = np.argmin(sf, axis=1); idx = np.arange(len(ctx.main_md))
    return pd.DataFrame({"main_md_m": ctx.main_md, "min_separation_m": dist[idx, jd], "offset_md_at_min_separation_m": ctx.off_md[jd],
                         "min_sf": sf[idx, js], "offset_md_at_min_sf_m": ctx.off_md[js]})
