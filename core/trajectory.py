
import numpy as np
import pandas as pd

def _dogleg(inc1, azi1, inc2, azi2):
    return np.arccos(np.clip(
        np.cos(inc1)*np.cos(inc2) +
        np.sin(inc1)*np.sin(inc2)*np.cos(azi2-azi1),
        -1.0, 1.0
    ))

def minimum_curvature(df, dls_interval=30.0):
    required = {"MD","Inc","Azi"}
    if not required.issubset(df.columns):
        raise ValueError("Survey must contain MD, Inc and Azi.")
    d = df.copy()
    d = d[["MD","Inc","Azi"]].dropna().sort_values("MD").reset_index(drop=True)
    for c in ["MD","Inc","Azi"]:
        d[c] = pd.to_numeric(d[c], errors="raise")
    if len(d) < 1:
        raise ValueError("At least one survey station is required.")
    if (d["MD"].diff().dropna() <= 0).any():
        raise ValueError("MD must increase strictly.")
    if ((d["Inc"] < 0) | (d["Inc"] > 180)).any():
        raise ValueError("Inclination must be between 0 and 180 degrees.")

    north = [0.0]
    east = [0.0]
    tvd = [0.0]
    dls = [np.nan]
    dogleg_rad = [np.nan]

    for i in range(1, len(d)):
        md1, md2 = d.loc[i-1,"MD"], d.loc[i,"MD"]
        inc1, inc2 = np.radians(d.loc[i-1,"Inc"]), np.radians(d.loc[i,"Inc"])
        azi1, azi2 = np.radians(d.loc[i-1,"Azi"]), np.radians(d.loc[i,"Azi"])
        delta_md = md2 - md1
        dog = _dogleg(inc1, azi1, inc2, azi2)
        rf = 1.0 if abs(dog) < 1e-12 else (2.0/dog)*np.tan(dog/2.0)

        dn = (delta_md/2.0) * (
            np.sin(inc1)*np.cos(azi1) + np.sin(inc2)*np.cos(azi2)
        ) * rf
        de = (delta_md/2.0) * (
            np.sin(inc1)*np.sin(azi1) + np.sin(inc2)*np.sin(azi2)
        ) * rf
        dt = (delta_md/2.0) * (np.cos(inc1)+np.cos(inc2)) * rf

        north.append(north[-1] + dn)
        east.append(east[-1] + de)
        tvd.append(tvd[-1] + dt)
        dogleg_rad.append(dog)
        dls.append(np.degrees(dog)/delta_md*dls_interval)

    d["Northing"] = north
    d["Easting"] = east
    d["TVD"] = tvd
    d["DLS"] = dls
    d["DoglegRad"] = dogleg_rad
    d["VS"] = np.sqrt(d["Northing"]**2 + d["Easting"]**2)
    d["ClosureAzimuth"] = np.degrees(
        np.arctan2(d["Easting"], d["Northing"])
    ) % 360
    return d

def trajectory_3d(df):
    return df[["Easting","Northing","TVD"]].copy()
