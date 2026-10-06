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


def build_constant_build_hold(kop_md, build_rate_deg_30m, hold_inc_deg, hold_azi_deg, target_tvd, target_north, target_east, start_md=0.0, station_interval=30.0, max_md=15000.0):
    """Practice-grade planner for a simple build/hold path. Returns a feasible trajectory candidate and status.
    It solves a constant-build section followed by a constant-inclination hold toward the target azimuth.
    The final target is approximated by extending the hold; this is intentionally not a full 3D optimizer.
    """
    if target_tvd <= 0 or station_interval <= 0 or build_rate_deg_30m <= 0 or hold_inc_deg <= 0:
        raise ValueError("Target TVD, station interval, build rate and hold inclination must be positive.")
    build_rad_per_m = np.radians(build_rate_deg_30m)/30.0
    build_len = np.radians(hold_inc_deg)/build_rad_per_m
    build_end = kop_md + build_len
    # Approximate build-section TVD and horizontal displacement.
    n_steps = max(2, int(np.ceil((build_end-start_md)/station_interval))+1)
    mds = np.linspace(start_md, build_end, n_steps)
    incs = np.clip((mds-kop_md)*build_rad_per_m, 0, np.radians(hold_inc_deg))
    incs[mds < kop_md] = 0
    azis = np.full_like(incs, np.radians(hold_azi_deg))
    rows = [{"MD":float(m),"Inc":float(np.degrees(i)),"Azi":float(hold_azi_deg)} for m,i in zip(mds,incs)]
    # Extend hold until target TVD or max MD.
    candidate = minimum_curvature(pd.DataFrame(rows), dls_interval=30.0)
    tvd_now = float(candidate.iloc[-1].TVD)
    hold_inc = np.radians(hold_inc_deg)
    if np.cos(hold_inc) <= 1e-9:
        hold_extra = 0.0
    else:
        hold_extra = max(0.0, (target_tvd-tvd_now)/np.cos(hold_inc))
    hold_extra = min(hold_extra, max_md-build_end)
    if hold_extra > 0:
        more = np.arange(build_end+station_interval, build_end+hold_extra+station_interval/2, station_interval)
        rows.extend({"MD":float(m),"Inc":float(hold_inc_deg),"Azi":float(hold_azi_deg)} for m in more)
    out = minimum_curvature(pd.DataFrame(rows), dls_interval=30.0)
    end = out.iloc[-1]
    err = float(np.hypot(end["Northing"]-target_north, end["Easting"]-target_east))
    tvd_err = float(end["TVD"]-target_tvd)
    return out, {"status":"PASS" if err < 100 and abs(tvd_err) < 100 else "REVIEW", "lateral_error_m":err, "tvd_error_m":tvd_err, "build_end_md_m":build_end}


def trajectory_3d(df):
    return df[["Easting", "Northing", "TVD"]].copy()
