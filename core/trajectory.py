import math
import numpy as np
import pandas as pd


def _dogleg(inc1, azi1, inc2, azi2):
    i1, i2 = np.radians([inc1, inc2])
    a1, a2 = np.radians([azi1, azi2])
    c = np.cos(i1)*np.cos(i2) + np.sin(i1)*np.sin(i2)*np.cos(a2-a1)
    c = np.clip(c, -1.0, 1.0)
    return np.degrees(np.arccos(c))


def minimum_curvature(df, dls_interval=30.0):
    required = {"MD", "Inc", "Azi"}
    if not required.issubset(df.columns):
        raise ValueError("Survey requires MD, Inc and Azi columns.")
    w = df.copy().sort_values("MD").reset_index(drop=True)
    for c in required:
        w[c] = pd.to_numeric(w[c], errors="raise")
    if len(w) == 0:
        return w
    if not w["MD"].diff().dropna().gt(0).all():
        raise ValueError("MD must increase strictly.")
    if not w["Inc"].between(0, 180).all():
        raise ValueError("Inclination must be between 0 and 180 degrees.")
    n = [0.0]; e = [0.0]; tvd = [0.0]; dls = [0.0]
    for j in range(1, len(w)):
        md1, md2 = float(w.loc[j-1,"MD"]), float(w.loc[j,"MD"])
        dl = md2-md1
        i1, i2 = np.radians([w.loc[j-1,"Inc"], w.loc[j,"Inc"]])
        a1, a2 = np.radians([w.loc[j-1,"Azi"], w.loc[j,"Azi"]])
        dog = np.radians(_dogleg(w.loc[j-1,"Inc"], w.loc[j-1,"Azi"], w.loc[j,"Inc"], w.loc[j,"Azi"]))
        rf = 1.0 if abs(dog) < 1e-12 else 2.0/dog*np.tan(dog/2.0)
        dn = dl/2.0*(np.sin(i1)*np.cos(a1)+np.sin(i2)*np.cos(a2))*rf
        de = dl/2.0*(np.sin(i1)*np.sin(a1)+np.sin(i2)*np.sin(a2))*rf
        dz = dl/2.0*(np.cos(i1)+np.cos(i2))*rf
        n.append(n[-1]+dn); e.append(e[-1]+de); tvd.append(tvd[-1]+dz)
        dls.append(np.degrees(dog)/dl*dls_interval if dl > 0 else 0.0)
    out = w.copy()
    out["Northing"] = n; out["Easting"] = e; out["TVD"] = tvd; out["DLS"] = dls
    out["VS"] = np.hypot(out["Northing"], out["Easting"])
    out["Closure"] = out["VS"]
    out["ClosureAzi"] = (np.degrees(np.arctan2(out["Easting"], out["Northing"])) % 360.0)
    return out


def _build_hold_candidate(kop_md, build_rate_deg_30m, hold_inc_deg, hold_azi_deg,
                          target_tvd, station_interval=30.0, max_md=15000.0):
    """Generate a constant-build/constant-hold candidate in metres internally."""
    if target_tvd <= 0 or station_interval <= 0 or build_rate_deg_30m <= 0 or hold_inc_deg <= 0:
        raise ValueError("Target TVD, station interval, build rate and hold inclination must be positive.")
    build_rad_per_m = np.radians(build_rate_deg_30m) / 30.0
    build_len = np.radians(hold_inc_deg) / build_rad_per_m
    build_end = kop_md + build_len
    if build_end > max_md:
        raise ValueError("Build section exceeds the planner maximum MD.")
    n_steps = max(2, int(np.ceil((build_end)/station_interval))+1)
    mds = np.linspace(0.0, build_end, n_steps)
    incs = np.zeros_like(mds)
    mask = mds >= kop_md
    incs[mask] = np.clip((mds[mask]-kop_md)*build_rad_per_m, 0, np.radians(hold_inc_deg))
    azis = np.full_like(incs, np.radians(hold_azi_deg))
    rows = [{"MD":float(m),"Inc":float(np.degrees(i)),"Azi":float(hold_azi_deg)} for m,i in zip(mds,incs)]
    candidate = minimum_curvature(pd.DataFrame(rows), dls_interval=30.0)
    tvd_now = float(candidate.iloc[-1].TVD)
    hold_inc = np.radians(hold_inc_deg)
    if np.cos(hold_inc) <= 1e-9:
        hold_extra = 0.0
    else:
        hold_extra = max(0.0, (target_tvd-tvd_now)/np.cos(hold_inc))
    hold_extra = min(hold_extra, max(0.0, max_md-build_end))
    if hold_extra > 0:
        more = np.arange(build_end+station_interval, build_end+hold_extra+station_interval/2, station_interval)
        rows.extend({"MD":float(m),"Inc":float(hold_inc_deg),"Azi":float(hold_azi_deg)} for m in more)
    out = minimum_curvature(pd.DataFrame(rows), dls_interval=30.0)
    return out, build_end, build_len


def build_constant_build_hold(kop_md, build_rate_deg_30m, hold_inc_deg, hold_azi_deg,
                               target_tvd, target_north, target_east, start_md=0.0,
                               station_interval=30.0, max_md=15000.0):
    """Practice-grade constant-build/hold candidate.

    Internal distances are metres; DLS is expressed on a 30 m basis internally.
    The hold section is extended toward the requested target TVD and the endpoint
    is then evaluated against target north/east offsets.
    """
    if start_md != 0.0:
        # Preserve the public argument while keeping the generated trajectory anchored at MD 0.
        raise ValueError("The planner currently requires start_md=0 for a well-relative trajectory.")
    out, build_end, build_len = _build_hold_candidate(
        kop_md, build_rate_deg_30m, hold_inc_deg, hold_azi_deg, target_tvd,
        station_interval=station_interval, max_md=max_md
    )
    end = out.iloc[-1]
    lateral_error = float(np.hypot(end["Northing"]-target_north, end["Easting"]-target_east))
    tvd_err = float(end["TVD"]-target_tvd)
    return out, {
        "status":"PASS" if lateral_error < 30.48 and abs(tvd_err) < 30.48 else "REVIEW",
        "lateral_error_m":lateral_error,
        "tvd_error_m":tvd_err,
        "build_end_md_m":build_end,
        "build_length_m":build_len,
        "hold_inclination_deg":float(hold_inc_deg),
        "planning_azimuth_deg":float(hold_azi_deg),
        "endpoint_north_m":float(end["Northing"]),
        "endpoint_east_m":float(end["Easting"]),
        "endpoint_tvd_m":float(end["TVD"]),
        "final_md_m":float(end["MD"]),
    }


def solve_build_hold_hold_inclination(kop_md, build_rate_deg_30m, max_hold_inc_deg,
                                      hold_azi_deg, target_tvd, target_north, target_east,
                                      min_hold_inc_deg=1.0, station_interval=30.0,
                                      max_md=15000.0, step_deg=0.25):
    """Find the hold inclination that minimizes lateral error while the hold is
    extended to target TVD. This is a transparent one-variable search, not a full
    directional-trajectory optimizer.
    """
    lo=max(float(min_hold_inc_deg), 0.1); hi=float(max_hold_inc_deg)
    if hi <= lo:
        raise ValueError("Maximum hold inclination must exceed the minimum hold inclination.")
    best=None
    angles=np.arange(lo, hi+step_deg/2, step_deg)
    for ang in angles:
        try:
            out, meta = build_constant_build_hold(kop_md, build_rate_deg_30m, float(ang), hold_azi_deg,
                                                   target_tvd, target_north, target_east,
                                                   station_interval=station_interval, max_md=max_md)
        except ValueError:
            continue
        score=meta["lateral_error_m"]
        if best is None or score < best[0]:
            best=(score, float(ang), out, meta)
    if best is None:
        raise ValueError("No feasible build/hold candidate exists within the selected inclination and MD limits.")
    # Refine around the best coarse result.
    _, coarse, _, _ = best
    fine_lo=max(lo, coarse-step_deg); fine_hi=min(hi, coarse+step_deg)
    for ang in np.arange(fine_lo, fine_hi+step_deg/20, step_deg/10):
        try:
            out, meta = build_constant_build_hold(kop_md, build_rate_deg_30m, float(ang), hold_azi_deg,
                                                   target_tvd, target_north, target_east,
                                                   station_interval=station_interval, max_md=max_md)
        except ValueError:
            continue
        score=meta["lateral_error_m"]
        if score < best[0]:
            best=(score, float(ang), out, meta)
    _, angle, out, meta = best
    meta=dict(meta)
    meta.update({"solver":"target-fit hold inclination search", "max_hold_inclination_deg":hi,
                 "hold_inclination_margin_deg":hi-angle})
    return out, meta


def trajectory_3d(df):
    return df[["Easting", "Northing", "TVD"]].copy()
