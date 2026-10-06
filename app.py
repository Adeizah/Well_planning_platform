
import json
from datetime import date, datetime
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.project import (
    new_project, project_to_json, project_from_json, validate_project
)
from core.trajectory import minimum_curvature, trajectory_3d
from core.units import (
    sg_to_ppg, ppg_to_sg, hydrostatic_psi, annular_velocity_fps,
    pressure_gradient_psi_ft, psi_to_mpa, mpa_to_psi
)
from models.geomagnetic import wmm2025
from models.geodesy import noaa_geoid_height
from engineering.anti_collision import clearance_report
from engineering.casing import casing_screen
from engineering.hydraulics import hydraulic_screen
from engineering.well_control import well_control_screen
from engineering.cement import cement_screen
from engineering.torque_drag import torque_drag_screen

st.set_page_config(
    page_title="Well Planning Platform",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.small-muted {color:#6b7280; font-size:0.9rem;}
</style>
""", unsafe_allow_html=True)

if "project" not in st.session_state:
    st.session_state.project = new_project()

project = st.session_state.project

def save_project():
    st.session_state.project = project

def project_download():
    return json.dumps(project_to_json(project), indent=2).encode("utf-8")

# ---------- Sidebar ----------
st.sidebar.title("🛢️ Well Planning Platform")
st.sidebar.caption("General-purpose drilling & well-planning workspace")

project["project_name"] = st.sidebar.text_input(
    "Project", project.get("project_name", "New Project")
)
project["well_name"] = st.sidebar.text_input(
    "Well", project.get("well_name", "NEW-01")
)

page = st.sidebar.radio("Workspace", [
    "Dashboard",
    "Project",
    "Surveys & Trajectory",
    "Targets",
    "Geomagnetics",
    "Geodesy",
    "Offsets",
    "Anti-Collision",
    "Casing",
    "Hydraulics",
    "Well Control",
    "Cement",
    "Torque & Drag",
    "Reports",
    "QA/QC",
    "About",
])

st.sidebar.divider()
st.sidebar.download_button(
    "⬇️ Export project JSON",
    data=project_download(),
    file_name=f"{project['well_name']}_wellplan.json",
    mime="application/json",
)
upload = st.sidebar.file_uploader("⬆️ Load project JSON", type=["json"])
if upload is not None:
    try:
        loaded = json.load(upload)
        st.session_state.project = project_from_json(loaded)
        st.rerun()
    except Exception as exc:
        st.sidebar.error(f"Invalid project file: {exc}")

st.sidebar.divider()
st.sidebar.warning(
    "TRAINING / ENGINEERING-DEVELOPMENT SOFTWARE\n\n"
    "Do not use this application as the sole basis for operational drilling decisions."
)

# ---------- Dashboard ----------
if page == "Dashboard":
    st.title("Well Planning Platform")
    st.subheader(f"{project['project_name']}  •  {project['well_name']}")

    surveys = project.get("surveys", [])
    targets = project.get("targets", [])
    offsets = project.get("offsets", [])

    a,b,c,d = st.columns(4)
    a.metric("Project status", project.get("status", "Planning"))
    b.metric("Survey stations", len(surveys))
    c.metric("Targets", len(targets))
    d.metric("Offsets", len(offsets))

    st.markdown("### Well identity")
    a,b,c = st.columns(3)
    a.write(f"**Latitude:** {project.get('latitude', 0):.6f}°")
    b.write(f"**Longitude:** {project.get('longitude', 0):.6f}°")
    c.write(f"**CRS:** {project.get('crs', 'EPSG:4326')}")

    st.markdown("### Engineering workflow")
    st.code(
        "Project definition\n"
        "    ↓\n"
        "Reference systems + model selection\n"
        "    ↓\n"
        "Survey management / corrections / uncertainty\n"
        "    ↓\n"
        "Trajectory + targets + offsets\n"
        "    ↓\n"
        "Anti-collision\n"
        "    ↓\n"
        "Casing / hydraulics / torque & drag / well control / cement\n"
        "    ↓\n"
        "QA/QC + engineering report"
    )

    st.markdown("### Model provenance")
    meta = project.get("model_metadata", {})
    if meta:
        st.dataframe(pd.DataFrame(
            [{"Model": k, **v} if isinstance(v, dict) else {"Model": k, "Info": v}
             for k,v in meta.items()]
        ), use_container_width=True, hide_index=True)
    else:
        st.info("No model-derived results have been recorded yet.")

# ---------- Project ----------
elif page == "Project":
    st.title("Project & Well Definition")

    a,b,c = st.columns(3)
    project["latitude"] = a.number_input(
        "Latitude (°)", -90.0, 90.0, float(project["latitude"]), format="%.6f"
    )
    project["longitude"] = b.number_input(
        "Longitude (°)", -180.0, 180.0, float(project["longitude"]), format="%.6f"
    )
    project["elevation_m"] = c.number_input(
        "Wellhead elevation (m)", -2000.0, 10000.0, float(project["elevation_m"])
    )

    a,b,c = st.columns(3)
    project["kb_m"] = a.number_input(
        "KB elevation (m)", -2000.0, 10000.0, float(project["kb_m"])
    )
    project["crs"] = b.text_input("Project CRS", project.get("crs", "EPSG:4326"))
    project["planned_date"] = str(c.date_input(
        "Planning / survey date", date.fromisoformat(project["planned_date"])
    ))

    a,b,c = st.columns(3)
    project["north_reference"] = a.selectbox(
        "North reference",
        ["True North", "Grid North", "Magnetic North"],
        index=["True North","Grid North","Magnetic North"].index(
            project.get("north_reference", "True North")
        )
    )
    project["depth_reference"] = b.selectbox(
        "Depth reference",
        ["MD / TVDSS", "MD / TVD"],
        index=["MD / TVDSS","MD / TVD"].index(
            project.get("depth_reference", "MD / TVDSS")
        )
    )
    project["status"] = c.selectbox(
        "Status", ["Planning", "Draft", "Under Review", "Approved for Training"],
        index=["Planning","Draft","Under Review","Approved for Training"].index(
            project.get("status", "Planning")
        )
    )

    st.markdown("### Reference notes")
    project["notes"] = st.text_area("Project notes", project.get("notes", ""))

    if st.button("Save project settings", type="primary"):
        save_project()
        st.success("Project settings saved.")

# ---------- Surveys ----------
elif page == "Surveys & Trajectory":
    st.title("Survey Manager & Trajectory")
    st.caption("Minimum-curvature calculation using MD, inclination and azimuth.")

    df = pd.DataFrame(project.get("surveys", []))
    if df.empty:
        df = pd.DataFrame([{"MD":0.0,"Inc":0.0,"Azi":0.0}])

    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True,
        column_config={
            "MD": st.column_config.NumberColumn("MD", min_value=0.0),
            "Inc": st.column_config.NumberColumn("Inc (°)", min_value=0.0, max_value=180.0),
            "Azi": st.column_config.NumberColumn("Azi (°)", min_value=-360.0, max_value=720.0),
        }
    )

    c1,c2,c3 = st.columns(3)
    interval = c1.number_input("DLS interval (m)", 1.0, 1000.0, 30.0)
    tvdss_offset = c2.number_input("TVDSS reference offset (m)", -10000.0, 10000.0, 0.0)
    if c3.button("Calculate trajectory", type="primary"):
        try:
            result = minimum_curvature(edited, dls_interval=interval)
            result["TVDSS"] = result["TVD"] + tvdss_offset
            project["surveys"] = result.to_dict("records")
            project["trajectory_metadata"] = {
                "method": "Minimum Curvature",
                "dls_interval_m": interval,
                "tvdss_offset_m": tvdss_offset,
                "calculated_utc": datetime.utcnow().isoformat() + "Z",
            }
            save_project()
            st.success("Trajectory calculated and stored in the project.")
        except Exception as exc:
            st.error(str(exc))

    if project.get("surveys"):
        out = pd.DataFrame(project["surveys"])
        st.dataframe(out, use_container_width=True, hide_index=True)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=out["Easting"], y=out["Northing"],
            mode="lines+markers", name=project["well_name"]
        ))
        fig.update_layout(
            title="Plan View", xaxis_title="Easting / ΔE (m)",
            yaxis_title="Northing / ΔN (m)", height=500
        )
        st.plotly_chart(fig, use_container_width=True)

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=out["Northing"], y=out["TVD"],
            mode="lines+markers", name="Vertical Section"
        ))
        fig2.update_yaxes(autorange="reversed")
        fig2.update_layout(title="Northing vs TVD", xaxis_title="Northing (m)",
                           yaxis_title="TVD (m)", height=500)
        st.plotly_chart(fig2, use_container_width=True)

        with st.expander("3D trajectory"):
            xyz = trajectory_3d(out)
            fig3 = go.Figure(go.Scatter3d(
                x=xyz["Easting"], y=xyz["Northing"], z=-xyz["TVD"],
                mode="lines+markers", name=project["well_name"]
            ))
            fig3.update_layout(
                scene=dict(xaxis_title="Easting", yaxis_title="Northing",
                           zaxis_title="Elevation relative to surface"),
                height=650
            )
            st.plotly_chart(fig3, use_container_width=True)

    st.markdown("### Survey import")
    survey_file = st.file_uploader(
        "Upload CSV with columns MD, Inc, Azi", type=["csv"], key="survey_csv"
    )
    if survey_file is not None:
        imported = pd.read_csv(survey_file)
        st.dataframe(imported.head(), use_container_width=True)
        if st.button("Replace survey with uploaded CSV"):
            if not {"MD","Inc","Azi"}.issubset(imported.columns):
                st.error("CSV must contain MD, Inc and Azi.")
            else:
                project["surveys"] = imported[["MD","Inc","Azi"]].to_dict("records")
                save_project()
                st.success("Survey imported.")

# ---------- Targets ----------
elif page == "Targets":
    st.title("Targets & Well Objectives")
    df = pd.DataFrame(project.get("targets", []))
    if df.empty:
        df = pd.DataFrame(columns=[
            "name","north_m","east_m","tvdss_m","radius_m","priority"
        ])
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True)
    if st.button("Save targets", type="primary"):
        project["targets"] = edited.to_dict("records")
        save_project()
        st.success("Targets saved.")

# ---------- Geomagnetics ----------
elif page == "Geomagnetics":
    st.title("Geomagnetic Models")
    st.write(
        "WMM2025 is calculated locally from the model coefficients; the calculation "
        "is date-aware and records model provenance. WMM2025 is the current WMM "
        "epoch and is valid through 2029."
    )
    a,b,c = st.columns(3)
    lat = a.number_input("Latitude (°)", -90., 90., float(project["latitude"]), format="%.6f")
    lon = b.number_input("Longitude (°)", -180., 180., float(project["longitude"]), format="%.6f")
    alt_m = c.number_input("Ellipsoid height (m)", -2000., 100000., float(project["elevation_m"]))

    calc_date = st.date_input(
        "Model date", date.fromisoformat(project["planned_date"])
    )
    if st.button("Calculate WMM2025", type="primary"):
        try:
            result = wmm2025(lat, lon, alt_m, calc_date)
            a,b,c,d,e,f,g = st.columns(7)
            for col,key,label in [
                (a,"D","Declination °"),(b,"I","Dip °"),(c,"F","Total nT"),
                (d,"H","Horizontal nT"),(e,"X","North nT"),
                (f,"Y","East nT"),(g,"Z","Vertical nT")
            ]:
                col.metric(label, f"{result[key]:.3f}")
            project["model_metadata"]["WMM2025"] = result["metadata"]
            save_project()
            st.success("WMM2025 result recorded in project provenance.")
        except Exception as exc:
            st.error(str(exc))

    st.info(
        "For MWD survey work, this is the Earth's main field model. It is not a "
        "substitute for measured downhole magnetic data, local magnetic-interference "
        "assessment, or a full survey-error model."
    )

# ---------- Geodesy ----------
elif page == "Geodesy":
    st.title("Geodesy & Correction Services")
    st.write("Coordinate transformations are handled locally with PROJ/pyproj. "
             "The optional NOAA geoid lookup is a live public web service.")

    a,b,c = st.columns(3)
    lat = a.number_input("Latitude (°)", -90., 90., float(project["latitude"]), format="%.6f")
    lon = b.number_input("Longitude (°)", -180., 180., float(project["longitude"]), format="%.6f")
    model_id = c.selectbox("NOAA geoid model", [14, 13, 12, 11], index=0)

    if st.button("Query NOAA geoid service", type="primary"):
        try:
            r = noaa_geoid_height(lat, lon, model_id)
            st.metric("Geoid height (m)", f"{r['geoidHeight']:.3f}")
            st.write(r)
            project["model_metadata"]["NOAA Geoid"] = {
                "service": r.get("service"),
                "model": r.get("geoidModel"),
                "queried_utc": datetime.utcnow().isoformat()+"Z",
                "lat": lat, "lon": lon,
            }
            save_project()
        except Exception as exc:
            st.error(str(exc))
            st.info(
                "NOAA's NGS geoid models are primarily regional U.S./territory "
                "products. A failed result outside coverage is expected."
            )

    st.markdown("### CRS transformation")
    a,b,c,d = st.columns(4)
    x = a.number_input("X / longitude", value=float(lon))
    y = b.number_input("Y / latitude", value=float(lat))
    src = c.text_input("Source CRS", "EPSG:4326")
    dst = d.text_input("Target CRS", "EPSG:32632")
    if st.button("Transform coordinates"):
        try:
            from pyproj import Transformer
            tr = Transformer.from_crs(src, dst, always_xy=True)
            xx, yy = tr.transform(x, y)
            st.success(f"Result: X={xx:.6f}, Y={yy:.6f}")
        except Exception as exc:
            st.error(str(exc))

# ---------- Offsets ----------
elif page == "Offsets":
    st.title("Offset Wells")
    st.caption("Create a reusable offset-well inventory. Survey data can be attached to each offset as JSON/CSV in later workflow steps.")
    df = pd.DataFrame(project.get("offsets", []))
    if df.empty:
        df = pd.DataFrame(columns=[
            "name","surface_north_m","surface_east_m","td_md_m","status"
        ])
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True)
    if st.button("Save offsets", type="primary"):
        project["offsets"] = edited.to_dict("records")
        save_project()
        st.success("Offsets saved.")

# ---------- Anti-collision ----------
elif page == "Anti-Collision":
    st.title("Anti-Collision Screening")
    st.caption("Point-to-point / resampled trajectory clearance screening. A full ISCWSA implementation is a separate engineering module.")
    if not project.get("surveys"):
        st.warning("Calculate or import the main-well survey first.")
    else:
        main = pd.DataFrame(project["surveys"])
        st.dataframe(clearance_report(main, project.get("offsets", [])),
                     use_container_width=True, hide_index=True)
        st.info(
            "The present screen requires offset trajectory stations to be supplied "
            "before true separation factors and uncertainty ellipsoids can be calculated."
        )

# ---------- Casing ----------
elif page == "Casing":
    st.title("Casing Design Screening")
    st.write("Enter a casing string for quick burst/collapse screening.")
    a,b,c,d,e = st.columns(5)
    od = a.number_input("Casing OD (in)", 2.0, 30.0, 9.625)
    wt = b.number_input("Weight (lb/ft)", 5.0, 300.0, 47.0)
    shoe = c.number_input("Shoe depth MD (m)", 0.0, 15000.0, 2750.0)
    mw = d.number_input("Mud weight (ppg)", 5.0, 20.0, 10.0)
    pp = e.number_input("External pressure gradient (psi/ft)", 0.0, 2.0, 0.52)
    if st.button("Run casing screen", type="primary"):
        r = casing_screen(od, wt, shoe, mw, pp)
        st.dataframe(pd.DataFrame([r]), use_container_width=True, hide_index=True)
        st.caption("This is a screening calculation, not a tubular design qualification.")

# ---------- Hydraulics ----------
elif page == "Hydraulics":
    st.title("Hydraulics / ECD Screening")
    a,b,c,d = st.columns(4)
    flow = a.number_input("Flow rate (gpm)", 10., 3000., 500.)
    hole = b.number_input("Hole ID (in)", 2., 30., 8.5)
    pipe = c.number_input("Pipe OD (in)", 1., 20., 5.0)
    mw = d.number_input("Mud weight (ppg)", 5., 20., 10.)
    a,b = st.columns(2)
    tvd = a.number_input("TVD (ft)", 0., 50000., 10000.)
    ann_loss = b.number_input("Estimated annular pressure loss (psi)", 0., 10000., 400.)
    if st.button("Calculate hydraulics screen", type="primary"):
        r = hydraulic_screen(flow, hole, pipe, mw, tvd, ann_loss)
        for col,key,label in zip(st.columns(4),
            ["annular_velocity_fps","hydrostatic_psi","ecd_ppg","pressure_gradient_psi_ft"],
            ["Annular velocity (ft/s)","Hydrostatic (psi)","ECD (ppg)","Gradient (psi/ft)"]):
            col.metric(label, f"{r[key]:.3f}")
        st.json(r)

# ---------- Well control ----------
elif page == "Well Control":
    st.title("Well Control Screening")
    a,b,c,d = st.columns(4)
    sidpp = a.number_input("SIDPP (psi)", 0., 10000., 500.)
    tvd = b.number_input("TVD (ft)", 100., 50000., 10000.)
    mw = c.number_input("Current MW (ppg)", 5., 20., 10.)
    frac = d.number_input("MAASP / allowable surface pressure (psi)", 0., 10000., 1500.)
    if st.button("Calculate well-control screen", type="primary"):
        r = well_control_screen(sidpp, tvd, mw, frac)
        st.dataframe(pd.DataFrame([r]), use_container_width=True, hide_index=True)
        st.warning("Use approved well-control procedures and company-specific kill sheets for operations.")

# ---------- Cement ----------
elif page == "Cement":
    st.title("Cement Volume Screening")
    a,b,c,d = st.columns(4)
    hole = a.number_input("Hole diameter (in)", 2., 30., 12.25)
    casing_od = b.number_input("Casing OD (in)", 2., 30., 9.625)
    length = c.number_input("Annular cement length (m)", 0., 15000., 1000.)
    excess = d.number_input("Excess (%)", 0., 100., 20.)
    if st.button("Calculate cement screen", type="primary"):
        r = cement_screen(hole, casing_od, length, excess)
        st.dataframe(pd.DataFrame([r]), use_container_width=True, hide_index=True)

# ---------- Torque & Drag ----------
elif page == "Torque & Drag":
    st.title("Torque & Drag Screening")
    a,b,c,d = st.columns(4)
    depth = a.number_input("Measured depth (m)", 0., 15000., 4000.)
    friction = b.number_input("Friction factor", 0.0, 1.0, 0.25)
    buoyancy = c.number_input("Buoyancy factor", 0.0, 1.2, 0.82)
    weight = d.number_input("String weight (lb/ft)", 1., 300., 19.5)
    if st.button("Run T&D screen", type="primary"):
        r = torque_drag_screen(depth, friction, buoyancy, weight)
        st.dataframe(pd.DataFrame([r]), use_container_width=True, hide_index=True)
        st.caption("A real T&D model must use the actual well trajectory, string geometry, contact forces and operating conditions.")

# ---------- Reports ----------
elif page == "Reports":
    st.title("Project Report")
    st.write("Generate a compact project snapshot for review.")
    report = {
        "project": project["project_name"],
        "well": project["well_name"],
        "status": project.get("status"),
        "coordinates": {
            "latitude": project["latitude"],
            "longitude": project["longitude"],
            "crs": project["crs"],
        },
        "survey_stations": len(project.get("surveys", [])),
        "targets": len(project.get("targets", [])),
        "offsets": len(project.get("offsets", [])),
        "model_metadata": project.get("model_metadata", {}),
        "generated_utc": datetime.utcnow().isoformat()+"Z",
    }
    st.json(report)
    st.download_button(
        "Download report JSON",
        json.dumps(report, indent=2).encode(),
        file_name=f"{project['well_name']}_report.json",
        mime="application/json"
    )

# ---------- QA ----------
elif page == "QA/QC":
    st.title("Project QA/QC")
    results = validate_project(project)
    for check in results:
        if check["status"] == "PASS":
            st.success(f"PASS — {check['check']}: {check['message']}")
        elif check["status"] == "WARN":
            st.warning(f"WARN — {check['check']}: {check['message']}")
        else:
            st.error(f"FAIL — {check['check']}: {check['message']}")

# ---------- About ----------
else:
    st.title("About")
    st.markdown("""
    ## Well Planning Platform

    A browser-based, project-independent engineering workspace designed around
    the workflow of drilling engineering, directional drilling and well planning.

    ### Design principles

    - **Project-independent:** WN-01 is only an example project.
    - **Model-aware:** model name, date/epoch and provenance are retained.
    - **Browser-first:** intended for GitHub + Streamlit Community Cloud.
    - **Modular:** survey, geodesy, geomagnetics and engineering modules are separated.
    - **Transparent:** calculations are intended to expose assumptions rather than hide them.
    - **Not operational software:** engineering calculations require verification against
      company procedures, standards, specialist software and competent engineering review.

    ### Planned model ecosystem

    - WMM2025
    - IGRF
    - PROJ / EPSG
    - Public geoid and gravity services where geographically appropriate
    - ISCWSA survey-error concepts
    - Additional open models as they are verified
    """)

st.session_state.project = project
