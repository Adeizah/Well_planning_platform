import numpy as np
import pandas as pd

from core.trajectory import minimum_curvature


def _prepare_trajectory(raw):
    df=pd.DataFrame(raw or []).copy()
    if df.empty or 'MD' not in df.columns:
        return pd.DataFrame()
    # Accept either already-calculated positional trajectories or raw survey stations.
    if not {"Easting","Northing","TVD"}.issubset(df.columns):
        if not {"Inc","Azi"}.issubset(df.columns):
            return pd.DataFrame()
        try:
            df=minimum_curvature(df[["MD","Inc","Azi"]].copy())
        except Exception:
            return pd.DataFrame()
    for c in ["MD","Easting","Northing","TVD"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=["MD","Easting","Northing","TVD"]).sort_values("MD").reset_index(drop=True)
    if len(df)<2 or not df["MD"].diff().dropna().gt(0).all():
        return pd.DataFrame()
    return df


def _sample(df, n=300):
    md=np.linspace(float(df.MD.min()), float(df.MD.max()), max(2,int(n)))
    xyz=np.column_stack([np.interp(md,df.MD,df[c]) for c in ["Easting","Northing","TVD"]])
    return md, xyz


def clearance_report(main_df, offsets, sigma_main=0.0, sigma_offset=0.0, samples_per_well=300):
    """Screen minimum 3D separation between the main trajectory and each offset.

    Distances and uncertainties are metres internally. Offset surface coordinates are
    expected in the same project CRS as the main well. This is a screening workflow,
    not an ISCWSA covariance/separation-rule implementation.
    """
    main=_prepare_trajectory(main_df.to_dict("records") if isinstance(main_df,pd.DataFrame) else main_df)
    columns=["offset","main_md_m","offset_md_m","separation_m","horizontal_separation_m",
             "vertical_separation_m","combined_uncertainty_m","separation_factor","status","note"]
    if len(main)<2:
        return pd.DataFrame(columns=columns)
    main_md, main_xyz=_sample(main,samples_per_well)
    rows=[]
    sigma_main=float(sigma_main or 0.0); sigma_offset=float(sigma_offset or 0.0)
    combined=float(np.hypot(sigma_main,sigma_offset))
    for off in offsets or []:
        odf=_prepare_trajectory(off.get("surveys",[]))
        if len(odf)<2:
            rows.append({"offset":off.get("name","Offset"),"main_md_m":np.nan,"offset_md_m":np.nan,
                         "separation_m":np.nan,"horizontal_separation_m":np.nan,"vertical_separation_m":np.nan,
                         "combined_uncertainty_m":combined,"separation_factor":np.nan,"status":"NOT CHECKED",
                         "note":"No valid offset trajectory with MD, Inc and Azi/position data."})
            continue
        off_md, off_xyz=_sample(odf,samples_per_well)
        # Offset survey coordinates are local to its surface location. Translate into
        # the project frame before comparison.
        off_xyz[:,0]+=float(off.get("surface_easting_m",0.0) or 0.0)
        off_xyz[:,1]+=float(off.get("surface_northing_m",0.0) or 0.0)
        # Pairwise screening search. Sampling keeps this transparent and deterministic.
        diff=main_xyz[:,None,:]-off_xyz[None,:,:]
        dist=np.linalg.norm(diff,axis=2)
        i,j=np.unravel_index(np.argmin(dist),dist.shape)
        sep=float(dist[i,j])
        de=float(diff[i,j,0]); dn=float(diff[i,j,1]); dz=float(diff[i,j,2])
        horiz=float(np.hypot(de,dn))
        sf=float(sep/combined) if combined>0 else np.inf
        if combined<=0:
            status="PASS" if sep>0 else "REVIEW"
            note="Zero uncertainty entered; separation factor is not meaningful."
        else:
            status="PASS" if sf>=2.0 else ("WARNING" if sf>=1.0 else "ALERT")
            note="Screening threshold: separation factor 2.0. Production work requires validated error models and company rules."
        rows.append({"offset":off.get("name","Offset"),"main_md_m":float(main_md[i]),"offset_md_m":float(off_md[j]),
                     "separation_m":sep,"horizontal_separation_m":horiz,"vertical_separation_m":abs(dz),
                     "combined_uncertainty_m":combined,"separation_factor":sf,"status":status,"note":note})
    return pd.DataFrame(rows,columns=columns)
