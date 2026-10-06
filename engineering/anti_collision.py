import numpy as np
import pandas as pd


def _interp_xyz(df, md):
    return np.array([np.interp(md, df["MD"], df[c]) for c in ["Easting","Northing","TVD"]], dtype=float)


def clearance_report(main_df, offsets, sigma_main=0.0, sigma_offset=0.0):
    rows=[]
    if main_df is None or len(main_df) < 2:
        return pd.DataFrame(columns=["offset","main_md_m","offset_md_m","separation_m","combined_uncertainty_m","separation_factor","status"])
    for off in offsets:
        odf = pd.DataFrame(off.get("surveys", []))
        if not {"MD","Easting","Northing","TVD"}.issubset(odf.columns):
            continue
        lo=max(float(main_df.MD.min()), float(odf.MD.min())); hi=min(float(main_df.MD.max()), float(odf.MD.max()))
        if hi <= lo: continue
        grid=np.linspace(lo,hi, max(25, int((hi-lo)/30)+1))
        best=None
        for md in grid:
            p=_interp_xyz(main_df,md)
            q=_interp_xyz(odf,md)
            sep=float(np.linalg.norm(p-q)); u=float(np.hypot(sigma_main,sigma_offset)); sf=sep/u if u>0 else np.inf
            cand=(sep,md,sf)
            if best is None or sep<best[0]: best=cand
        sep,md,sf=best
        rows.append({"offset":off.get("name","Offset"),"main_md_m":md,"offset_md_m":md,"separation_m":sep,"combined_uncertainty_m":u,"separation_factor":sf,"status":"REVIEW" if sf < 2.0 else "PASS"})
    return pd.DataFrame(rows)
