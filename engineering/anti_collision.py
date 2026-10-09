import numpy as np
import pandas as pd

from core.trajectory import minimum_curvature
from models.survey_uncertainty import station_covariances, interpolate_covariance


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


def clearance_report(main_df, offsets, survey_error_model=None, samples_per_well=300,
                    main_surface_easting_m=0.0, main_surface_northing_m=0.0):
    """Covariance-based anti-collision screening.

    Main and offset trajectories are normalized to the same project CRS before
    comparison. Position uncertainty is represented by a 3x3 North/East/TVD
    covariance propagated from illustrative survey measurement errors.

    This is an engineering-development implementation. It is deliberately NOT
    presented as an ISCWSA-certified error model or company separation rule.
    """
    main=_prepare_trajectory(main_df.to_dict("records") if isinstance(main_df,pd.DataFrame) else main_df)
    columns=["offset","main_md_m","offset_md_m","separation_m","horizontal_separation_m",
             "vertical_separation_m","directional_uncertainty_m","separation_factor","status","note"]
    if len(main)<2:
        return pd.DataFrame(columns=columns)

    # Backward compatibility for the old clearance_report(main, offsets, sigma_main, sigma_offset) API.
    if isinstance(survey_error_model, (int, float, np.integer, np.floating)):
        legacy_main=float(survey_error_model)
        legacy_offset=float(samples_per_well) if isinstance(samples_per_well, (int, float, np.integer, np.floating)) else legacy_main
        # Legacy sigma values were metres. Convert them to an illustrative equivalent
        # station-error scale for compatibility tests; the new UI uses explicit survey errors.
        model={"sigma_md_ft":max(0.1, legacy_main/2.0/0.3048),
               "sigma_inc_deg":0.10, "sigma_azi_deg":0.25}
        samples_per_well=300
    else:
        model = survey_error_model or {}

    def _survey_for_uncertainty(df):
        if {"MD","Inc","Azi"}.issubset(df.columns):
            return df[["MD","Inc","Azi"]].copy()
        # Positional trajectories can still be screened. Derive an approximate
        # orientation survey from consecutive N/E/TVD points for compatibility.
        w=df.sort_values("MD").reset_index(drop=True).copy()
        inc=np.zeros(len(w)); azi=np.zeros(len(w))
        for k in range(1,len(w)):
            dl=float(w.loc[k,"MD"]-w.loc[k-1,"MD"])
            dn=float(w.loc[k,"Northing"]-w.loc[k-1,"Northing"])
            de=float(w.loc[k,"Easting"]-w.loc[k-1,"Easting"])
            dz=float(w.loc[k,"TVD"]-w.loc[k-1,"TVD"])
            if dl>0:
                inc[k]=np.degrees(np.arccos(np.clip(dz/dl,-1,1)))
                azi[k]=np.degrees(np.arctan2(de,dn))%360.0
        if len(w)>1:
            inc[0]=inc[1]; azi[0]=azi[1]
        return pd.DataFrame({"MD":w["MD"].to_numpy(),"Inc":inc,"Azi":azi})

    def _cov_df(df):
        raw=_survey_for_uncertainty(df)
        return station_covariances(raw,
            sigma_md_ft=model.get("sigma_md_ft",0.5),
            sigma_inc_deg=model.get("sigma_inc_deg",0.10),
            sigma_azi_deg=model.get("sigma_azi_deg",0.25),
            sigma_inc_systematic_deg=model.get("sigma_inc_systematic_deg",0.10),
            sigma_azi_systematic_deg=model.get("sigma_azi_systematic_deg",0.25),
            sigma_surface_ft=model.get("sigma_surface_ft",5.0))

    main_cov_df=_cov_df(main)
    main_md, main_xyz=_sample(main,samples_per_well)
    main_xyz[:,0]+=float(main_surface_easting_m or 0.0)
    main_xyz[:,1]+=float(main_surface_northing_m or 0.0)
    rows=[]
    for off in offsets or []:
        odf=_prepare_trajectory(off.get("surveys",[]))
        if len(odf)<2:
            rows.append({"offset":off.get("name","Offset"),"main_md_m":np.nan,"offset_md_m":np.nan,
                         "separation_m":np.nan,"horizontal_separation_m":np.nan,"vertical_separation_m":np.nan,
                         "directional_uncertainty_m":np.nan,"separation_factor":np.nan,"status":"NOT CHECKED",
                         "note":"No valid offset trajectory with MD, Inc and Azi/position data."})
            continue
        off_cov_df=_cov_df(odf)
        off_md, off_xyz=_sample(odf,samples_per_well)
        off_xyz[:,0]+=float(off.get("surface_easting_m",0.0) or 0.0)
        off_xyz[:,1]+=float(off.get("surface_northing_m",0.0) or 0.0)

        diff=main_xyz[:,None,:]-off_xyz[None,:,:]
        dist=np.linalg.norm(diff,axis=2)
        i,j=np.unravel_index(np.argmin(dist),dist.shape)
        sep=float(dist[i,j])
        de=float(diff[i,j,0]); dn=float(diff[i,j,1]); dz=float(diff[i,j,2])
        horiz=float(np.hypot(de,dn))
        rel_cov=interpolate_covariance(main_cov_df, main_md[i]) + interpolate_covariance(off_cov_df, off_md[j])
        rel_cov=0.5*(rel_cov+rel_cov.T)
        if sep > 1e-9:
            u=diff[i,j]/sep
            directional_sigma=float(np.sqrt(max(0.0, u @ rel_cov @ u)))
        else:
            directional_sigma=float(np.sqrt(max(0.0, np.trace(rel_cov)/3.0)))
        sf=float(sep/directional_sigma) if directional_sigma>0 else np.inf
        if not np.isfinite(directional_sigma) or directional_sigma<=1e-12:
            status="REVIEW"
            if main_md[i] <= 1e-6 and off_md[j] <= 1e-6 and float(model.get("sigma_surface_ft", 5.0) or 0.0) <= 0.0:
                note="Closest approach is at the wellhead (MD≈0) and surface-position σ is set to 0 ft, so relative uncertainty evaluates to zero. Enter a justified non-zero surface-position uncertainty or verify the wellhead-positioning uncertainty; do not interpret this as clearance."
            else:
                note="Propagated uncertainty is zero or invalid. Check survey stations, angular-error propagation, and surface-position assumptions; do not interpret as clearance."
        else:
            status="PASS" if sf>=2.0 else ("WARNING" if sf>=1.0 else "ALERT")
            note="Covariance-based screening; threshold 2.0 is illustrative. Production work requires a validated ISCWSA error model and company-approved separation rules."
        rows.append({"offset":off.get("name","Offset"),"main_md_m":float(main_md[i]),"offset_md_m":float(off_md[j]),
                     "separation_m":sep,"horizontal_separation_m":horiz,"vertical_separation_m":abs(dz),
                     "directional_uncertainty_m":directional_sigma,"separation_factor":sf,"status":status,"note":note})
    return pd.DataFrame(rows,columns=columns)
