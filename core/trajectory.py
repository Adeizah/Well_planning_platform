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


def generate_profile_candidate(profile, kop_md, build_rate_deg_30m, hold_inc_deg,
                               hold_azi_deg, target_tvd, target_north, target_east,
                               drop_rate_deg_30m=None, final_inc_deg=0.0,
                               station_interval=30.0, max_md=15000.0, drop_start_md=None, truncate_at_target=True):
    """Generate a transparent piecewise-constant-rate trajectory profile.

    This is a planning candidate generator, not a full target-constrained
    directional optimizer. MD and coordinates are metres; DLS is per 30 m.
    Every profile selection changes the generated inclination-versus-MD path.
    """
    profile = str(profile or "Build & Hold")
    br = float(build_rate_deg_30m)
    dr = float(drop_rate_deg_30m if drop_rate_deg_30m is not None else br)
    kop = float(kop_md)
    hold = float(hold_inc_deg)
    azi = float(hold_azi_deg) % 360.0
    target_tvd = float(target_tvd)
    final_inc = float(final_inc_deg)
    if station_interval <= 0 or max_md <= 0:
        raise ValueError("Station interval and maximum MD must be positive.")
    if target_tvd <= 0:
        raise ValueError("Target TVD must be positive.")
    if profile != "Vertical" and (br <= 0 or hold <= 0):
        raise ValueError("Build rate and hold inclination must be positive for this profile.")
    if not 0 <= hold <= 180 or not 0 <= final_inc <= 180:
        raise ValueError("Inclinations must be between 0 and 180 degrees.")
    if kop < 0 or kop >= max_md:
        raise ValueError("KOP must be non-negative and below maximum MD.")

    if profile == "Vertical":
        peak_inc = 0.0
        post_profile = 'hold'
        build_len = 0.0
        build_end = 0.0
        drop_start = None
        end_md = min(max_md, max(target_tvd, station_interval))
        mds = np.arange(0.0, end_md, station_interval).tolist() + [end_md]
        incs = [0.0] * len(mds)
    else:
        if profile == "Horizontal":
            peak_inc = 90.0
            post_profile = "hold"
        elif profile == "ERD":
            peak_inc = min(max(hold, 75.0), 88.0)
            post_profile = "hold"
        else:
            peak_inc = hold
            post_profile = "drop" if profile in ("S-Profile", "Build-Hold-Drop", "Custom") else "hold"
        build_len = abs(peak_inc) / br * 30.0
        build_end = kop + build_len
        if build_end > max_md:
            raise ValueError("Build section exceeds maximum MD; reduce KOP/build angle or increase the planning MD limit.")
        drop_len = abs(peak_inc-final_inc) / dr * 30.0 if post_profile == "drop" else 0.0
        # For S and build-hold-drop, begin the drop after an initial hold period
        # that consumes about 70% of the remaining target TVD at peak inclination.
        drop_start = None
        if post_profile == "drop":
            cos_peak = max(abs(np.cos(np.radians(peak_inc))), 0.05)
            estimated_hold = max(0.0, (target_tvd - build_end * 0.8) / cos_peak)
            hold_len = max(0.0, 0.70 * estimated_hold)
            estimated_drop_start = min(max_md-drop_len, build_end + hold_len)
            drop_start = estimated_drop_start if drop_start_md is None else min(max_md-drop_len, max(build_end, float(drop_start_md)))
        mds = np.arange(0.0, max_md, station_interval).tolist()
        if not mds or mds[0] != 0.0: mds.insert(0, 0.0)
        mds = sorted(set([float(x) for x in mds] + [float(kop), float(build_end)] + ([float(drop_start), float(drop_start+drop_len)] if drop_start is not None else [])))
        mds = [x for x in mds if 0 <= x <= max_md]
        incs=[]
        build_rate_m = br/30.0
        drop_rate_m = dr/30.0
        for md in mds:
            if md < kop:
                inc=0.0
            elif md <= build_end:
                inc=min(peak_inc, max(0.0,(md-kop)*build_rate_m))
            elif drop_start is not None and md >= drop_start:
                inc=max(final_inc, peak_inc - (md-drop_start)*drop_rate_m)
            else:
                inc=peak_inc
            incs.append(float(inc))
        # Keep the complete design path by default for section inspection. Target
        # interception is evaluated independently from the displayed endpoint.
    azis = [azi] * len(mds)
    rows = pd.DataFrame({"MD": mds, "Inc": incs, "Azi": azis})
    out = minimum_curvature(rows, dls_interval=30.0)
    crossed = np.flatnonzero(out["TVD"].to_numpy() >= target_tvd)
    target_crossing = None
    if len(crossed):
        j = int(crossed[0])
        if j == 0:
            target_crossing = out.iloc[0]
        else:
            lo, hi = out.iloc[j-1], out.iloc[j]
            denom = float(hi['TVD'] - lo['TVD'])
            f = 0.0 if abs(denom) < 1e-12 else max(0.0, min(1.0, (target_tvd-float(lo['TVD']))/denom))
            target_crossing = {col: float(lo[col]) + f*(float(hi[col])-float(lo[col])) for col in ['MD','Northing','Easting','TVD','Inc','Azi']}
    if truncate_at_target and len(crossed):
        out = out.iloc[:int(crossed[0])+1].copy().reset_index(drop=True)
    end = out.iloc[-1]
    eval_point = target_crossing if target_crossing is not None else end
    lateral_error = float(np.hypot(float(eval_point["Northing"])-target_north, float(eval_point["Easting"])-target_east))
    tvd_error = float(eval_point["TVD"]-target_tvd) if target_crossing is not None else float(end["TVD"]-target_tvd)
    drop_end_for_check = (float(drop_start + drop_len)
                          if drop_start is not None and post_profile == "drop" else None)
    section_order_ok = (drop_end_for_check is None or target_crossing is None
                        or float(target_crossing["MD"]) + 1e-6 >= drop_end_for_check)
    target_hit = lateral_error <= 30.48 and abs(tvd_error) <= 30.48
    result = {
        "status": "PASS" if target_hit and section_order_ok else "REVIEW",
        "target_hit": bool(target_hit),
        "section_order_ok": bool(section_order_ok),
        "target_miss_distance_m": float(max(0.0, lateral_error - 30.48)),
        "profile": profile, "lateral_error_m": lateral_error, "tvd_error_m": tvd_error,
        "build_end_md_m": float(kop + abs(peak_inc)/br*30.0) if profile != "Vertical" else 0.0,
        "build_length_m": float(abs(peak_inc)/br*30.0) if profile != "Vertical" else 0.0,
        "hold_inclination_deg": float(peak_inc), "planning_azimuth_deg": float(azi),
        "endpoint_north_m": float(end["Northing"]), "endpoint_east_m": float(end["Easting"]),
        "endpoint_tvd_m": float(end["TVD"]), "final_md_m": float(end["MD"]),
        "drop_rate_deg_30m": float(dr) if post_profile == "drop" else None,
        "final_inclination_deg": float(end["Inc"]),
        "target_intercept_md_m": float(eval_point["MD"]) if target_crossing is not None else None,
        "target_intercept_north_m": float(eval_point["Northing"]),
        "target_intercept_east_m": float(eval_point["Easting"]),
        "target_intercept_found": target_crossing is not None,
        "section_end_md_m": {"KOP": float(kop), "EOB": float(kop + abs(peak_inc)/br*30.0) if profile != "Vertical" else 0.0,
                             "Drop start": float(drop_start) if drop_start is not None else None,
                             "Drop end": float(drop_start + drop_len) if drop_start is not None else None,
                             "Target intercept": float(eval_point["MD"]) if target_crossing is not None else None,
                             "Planned TD": float(out.iloc[-1]["MD"])},
        "note": "Practice-grade profile generation; target interception is evaluated separately from planned TD. Verify target fit, DLS, constraints and survey conventions before engineering use."
    }
    return out, result
