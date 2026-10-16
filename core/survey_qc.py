"""Survey data-quality checks for imported/edited survey tables (survey and offset wells)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.trajectory import minimum_curvature


def survey_quality_report(df, md_unit="ft", max_dls_deg_30m=10.0, max_gap_m=200.0):
    """Return a list of {severity, check, detail}. severity: ERROR (blocks use), WARN (review), INFO.

    ``md_unit`` is the unit of the MD column in ``df`` ('ft' or 'm'); Inc/Azi must be degrees.
    """
    issues = []
    def add(sev, check, detail): issues.append({"severity": sev, "check": check, "detail": detail})
    if df is None or len(df) == 0:
        return [{"severity": "ERROR", "check": "empty", "detail": "No survey stations."}]
    missing = {"MD", "Inc", "Azi"} - set(df.columns)
    if missing:
        return [{"severity": "ERROR", "check": "columns", "detail": f"Missing column(s): {', '.join(sorted(missing))}."}]
    num = df[["MD", "Inc", "Azi"]].apply(pd.to_numeric, errors="coerce")
    if num.isna().any().any():
        add("ERROR", "numeric", f"{int(num.isna().any(axis=1).sum())} row(s) contain missing or non-numeric values.")
        return issues
    if not np.isfinite(num.to_numpy(float)).all():
        add("ERROR", "finite", "Survey contains infinite values."); return issues
    f = 0.3048 if str(md_unit).lower().startswith("f") else 1.0
    md = num["MD"].to_numpy(float) * f
    if len(num) < 2:
        add("WARN", "stations", "Only one station: the well can be shown as a surface point but not screened for collision.")
    if (np.diff(md) <= 0).any():
        add("ERROR", "md_order", "MD must increase strictly (duplicate or out-of-order stations found).")
    if ((num["Inc"] < 0) | (num["Inc"] > 180)).any():
        add("ERROR", "inclination_range", "Inclination must be between 0 and 180 degrees.")
    if ((num["Azi"] < 0) | (num["Azi"] >= 360.0001)).any():
        add("WARN", "azimuth_range", "Azimuth outside 0-360 degrees (it will be wrapped).")
    if md[0] > 1e-6:
        add("WARN", "tie_in", f"First station is at MD {md[0]:.1f} m, not 0: a vertical hole from surface to the first station is assumed (TVD = MD). Provide a tie-in if that is wrong.")
    if num["Inc"].iloc[0] > 3.0 and md[0] <= 1e-6:
        add("WARN", "surface_inclination", "Inclination at the first station is above 3 degrees.")
    if len(md) > 1 and (np.diff(md) > max_gap_m).any():
        add("WARN", "station_gap", f"Station spacing up to {np.diff(md).max():.0f} m: tortuosity between stations is not captured.")
    if not any(i["severity"] == "ERROR" for i in issues) and len(num) > 1:
        try:
            p = minimum_curvature(num.assign(MD=md))
            if p["DLS"].max() > max_dls_deg_30m:
                add("WARN", "dls_spike", f"Maximum dogleg {p['DLS'].max():.1f} deg/30 m exceeds {max_dls_deg_30m:.1f}: check units (MD ft vs m) and station values.")
        except Exception as ex:
            add("ERROR", "calculation", str(ex))
    if not issues:
        add("INFO", "ok", "No data-quality issues found.")
    return issues
