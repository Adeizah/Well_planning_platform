
import pandas as pd
import numpy as np

def clearance_report(main_df, offsets):
    rows = []
    if not offsets:
        return pd.DataFrame([{
            "Offset":"—",
            "Minimum separation (m)":None,
            "Status":"No offset trajectories supplied"
        }])
    for o in offsets:
        name = o.get("name", "Offset")
        if not o.get("surveys"):
            rows.append({"Offset":name,"Minimum separation (m)":None,
                         "Status":"No survey attached"})
            continue
        try:
            off = pd.DataFrame(o["surveys"])
            if not {"MD","Northing","Easting","TVD"}.issubset(off.columns):
                rows.append({"Offset":name,"Minimum separation (m)":None,
                             "Status":"Offset needs calculated coordinates"})
                continue
            common = np.unique(np.concatenate([
                main_df["MD"].to_numpy(float), off["MD"].to_numpy(float)
            ]))
            mn = np.interp(common, main_df["MD"], main_df["Northing"])
            me = np.interp(common, main_df["MD"], main_df["Easting"])
            mt = np.interp(common, main_df["MD"], main_df["TVD"])
            on = np.interp(common, off["MD"], off["Northing"])
            oe = np.interp(common, off["MD"], off["Easting"])
            ot = np.interp(common, off["MD"], off["TVD"])
            sep = np.sqrt((mn-on)**2+(me-oe)**2+(mt-ot)**2)
            rows.append({"Offset":name,"Minimum separation (m)":float(np.min(sep)),
                         "MD at minimum (m)":float(common[np.argmin(sep)]),
                         "Status":"Screened"})
        except Exception as exc:
            rows.append({"Offset":name,"Minimum separation (m)":None,
                         "Status":f"Error: {exc}"})
    return pd.DataFrame(rows)
