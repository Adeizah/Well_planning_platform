import json, math
from datetime import date, datetime
from io import BytesIO
import zipfile
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from core.project import new_project, project_to_json, project_from_json, validate_project
from core.trajectory import minimum_curvature, build_constant_build_hold, solve_build_hold_hold_inclination, generate_profile_candidate
from core.optimizer import optimize_trajectory
from core.geometry import target_boundary
from core.reference import magnetic_to_true, true_to_grid, grid_to_true, true_to_magnetic, magnetic_to_grid, grid_to_magnetic, reference_requirements, convert_to_project_reference
from models.geomagnetic import wmm2025, igrf14
from models.geodesy import crs_info, transform_coordinates, grid_convergence_deg, normal_gravity, noaa_geoid_height
from engineering.anti_collision import clearance_report
from models.survey_uncertainty import station_covariances
from engineering.casing import casing_screen, casing_program_summary, casing_geometry_checks, casing_design_checks
from engineering.hydraulics import hydraulic_screen, rheology_summary
from engineering.well_control import well_control_screen
from engineering.pressure import pressure_window
from engineering.cement import cement_screen
from engineering.torque_drag import torque_drag_screen
from core.units import M_TO_FT, FT_TO_M, dls_30m_to_100ft, dls_100ft_to_30m, dls_for_interval_to_100ft

st.set_page_config(page_title='Well Planning Platform', page_icon='🛢️', layout='wide', initial_sidebar_state='expanded')

# -----------------------------------------------------------------------------
# UI SYSTEM
# The UI layer deliberately does not alter the v4 engineering engines/data model.
# -----------------------------------------------------------------------------
st.markdown("""
<style>
/* Desktop-first engineering workspace */
.block-container { padding: 1.15rem 2rem 3rem; max-width: 1600px; }
section[data-testid="stSidebar"] { border-right: 1px solid rgba(128,128,128,.18); }
section[data-testid="stSidebar"] > div { padding-top: 1rem; }
.wpp-brand { font-size: 1.25rem; font-weight: 800; letter-spacing: -.02em; }
.wpp-topbar { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.65rem 0 .9rem; border-bottom:1px solid rgba(128,128,128,.16); margin-bottom:1.2rem; }
.wpp-breadcrumb { color:#8b949e; font-size:.82rem; }
.wpp-well { font-weight:750; font-size:1rem; }
.wpp-badge { display:inline-block; padding:.22rem .55rem; border-radius:999px; font-size:.72rem; font-weight:700; background:rgba(49,130,206,.12); }
.wpp-card { border:1px solid rgba(128,128,128,.18); border-radius:12px; padding:1rem 1.05rem; min-height:94px; background:rgba(127,127,127,.035); }
.wpp-card-label { color:#8b949e; font-size:.76rem; text-transform:uppercase; letter-spacing:.06em; }
.wpp-card-value { font-size:1.35rem; font-weight:800; margin-top:.25rem; }
.wpp-card-note { color:#8b949e; font-size:.76rem; margin-top:.2rem; }
.wpp-section { margin-top:1.15rem; margin-bottom:.45rem; font-size:1.02rem; font-weight:800; }
.wpp-help { border-left:3px solid #6b7280; padding:.65rem .8rem; background:rgba(127,127,127,.045); border-radius:0 8px 8px 0; color:#a0a8b3; }
.wpp-module { color:#8b949e; font-size:.78rem; text-transform:uppercase; letter-spacing:.07em; margin-bottom:.2rem; }
div[data-testid="stMetric"] { border:1px solid rgba(128,128,128,.16); border-radius:10px; padding:.65rem .8rem; }
button[kind="primary"] { font-weight:700; }
[data-testid="stDataFrame"] { border-radius:10px; overflow:hidden; }
</style>
""", unsafe_allow_html=True)

if 'project' not in st.session_state:
    st.session_state.project = new_project()
project = st.session_state.project


def save():
    st.session_state.project = project


def download_json():
    # Export the shared engineering model, not transient Streamlit widget state.
    return json.dumps(project_to_json(project), indent=2, ensure_ascii=False).encode('utf-8')


NAV = [
    ('HOME', ['Dashboard']),
    ('SETUP', ['Project & Reference', 'Well Architecture', 'Targets', 'Offsets']),
    ('DIRECTIONAL', ['Survey Manager', 'Trajectory Planner', 'Geomagnetics', 'Geodesy', 'Anti-Collision']),
    ('DRILLING ENGINEERING', ['Casing Design', 'Hydraulics & ECD', 'PP / FG & Mud Window', 'Torque & Drag', 'Cementing', 'Well Control', 'BHA & Drilling']),
    ('OUTPUTS', ['Visualization', 'QA/QC', 'Reports']),
    ('SYSTEM', ['About']),
]
NAV_OPTIONS = [item for group, items in NAV for item in items]
# Hard-coded sequential navigation numbering. These are display labels only;
# page identity remains the underlying page name so reordering does not alter routing.
NAV_PREFIX = {
    'Dashboard': '01',
    'Project & Reference': '02',
    'Well Architecture': '03',
    'Targets': '04',
    'Offsets': '05',
    'Survey Manager': '06',
    'Trajectory Planner': '07',
    'Geomagnetics': '08',
    'Geodesy': '09',
    'Anti-Collision': '10',
    'Casing Design': '11',
    'Hydraulics & ECD': '12',
    'PP / FG & Mud Window': '13',
    'Torque & Drag': '14',
    'Cementing': '15',
    'Well Control': '16',
    'BHA & Drilling': '17',
    'Visualization': '18',
    'QA/QC': '19',
    'Reports': '20',
    'About': '21',
}

# Keep navigation stable across reruns. The engineering model remains in session state.
if 'active_page' not in st.session_state:
    st.session_state.active_page = 'Dashboard'

with st.sidebar:
    st.markdown('<div class="wpp-brand">🛢️ Well Planning Platform</div><div class="wpp-breadcrumb">Desktop engineering workspace</div>', unsafe_allow_html=True)
    st.divider()
    project['project_name'] = st.text_input('Project', project.get('project_name', 'New Project'))
    project['well_name'] = st.text_input('Well', project.get('well_name', 'NEW-01'))
    project['well_number'] = st.text_input('Well number', project.get('well_number', project.get('well_name', 'NEW-01')))
    if 'workspace_theme' not in st.session_state:
        st.session_state.workspace_theme = 'Light'
    theme = st.selectbox('App theme', ['Light', 'Dark'], index=['Light','Dark'].index(st.session_state.workspace_theme), key='workspace_theme_select')
    st.session_state.workspace_theme = theme
    if theme == 'Dark':
        st.markdown('''<style>
        .stApp, [data-testid="stAppViewContainer"] {background:#0e1117;color:#e6edf3;}
        section[data-testid="stSidebar"] {background:#151a23;color:#e6edf3;border-right:1px solid #303846;}
        [data-testid="stHeader"] {background:rgba(14,17,23,.92);}
        .wpp-card {background:#171d27;border-color:#303846;}
        .wpp-help {background:#171d27;color:#c9d1d9;border-left-color:#64748b;}
        .wpp-topbar {border-bottom-color:#303846;}
        div[data-testid="stMetric"] {background:#171d27;border-color:#303846;}
        div[data-testid="stDataFrame"] {filter:brightness(.92);}
        </style>''', unsafe_allow_html=True)
    else:
        st.markdown('''<style>
        .stApp, [data-testid="stAppViewContainer"] {background:#ffffff;color:#1f2937;}
        section[data-testid="stSidebar"] {background:#f8fafc;color:#1f2937;}
        .wpp-card {background:#f8fafc;}
        .wpp-help {background:#f8fafc;color:#475569;}
        </style>''', unsafe_allow_html=True)
    st.markdown('**Workspace**')
    current_label = f"{NAV_PREFIX.get(st.session_state.active_page, '01')} • {st.session_state.active_page}"
    labels = [f"{NAV_PREFIX[x]} • {x}" for x in NAV_OPTIONS]
    try: current_index = labels.index(current_label)
    except ValueError: current_index = 0
    selected_label = st.selectbox('Module', labels, index=current_index, label_visibility='collapsed')
    selected_page = selected_label.split(' • ', 1)[1]
    st.session_state.active_page = selected_page
    st.divider()
    st.download_button('⬇️ Export project JSON', download_json(), file_name=f"{project['well_name']}_project.json", mime='application/json', use_container_width=True)
    upload = st.file_uploader('⬆️ Import project JSON', type='json', key='project_import')
    if upload:
        try:
            raw = upload.getvalue()
            import hashlib
            upload_hash = hashlib.sha256(raw).hexdigest()
            # Streamlit keeps the uploaded file in the widget state across reruns.
            # Without this guard, every navigation click re-imports the file and resets the page.
            if st.session_state.get('last_import_hash') != upload_hash:
                candidate = project_from_json(json.loads(raw.decode('utf-8')))
                checks = validate_project(candidate)
                hard_failures = [c for c in checks if c.get('status') == 'FAIL']
                if hard_failures:
                    raise ValueError('Project file failed validation: ' + '; '.join(c['message'] for c in hard_failures))
                st.session_state.project = candidate
                st.session_state.last_import_hash = upload_hash
                st.session_state.active_page = 'Dashboard'
                st.success(f"Imported {candidate.get('well_name','project')} successfully.")
                st.rerun()
        except Exception as e:
            st.error(str(e))
    st.divider()
    st.caption('DESKTOP-FIRST')
    st.caption('Optimized for laptop/workstation use. The workspace is optimized for laptop/workstation use.')
    st.warning('PRACTICE / ENGINEERING-DEVELOPMENT SOFTWARE\n\nVerify calculations against approved procedures, standards, OEM data and specialist software before operational use.')

page = st.session_state.active_page


def page_header(title, section, description=None):
    st.markdown(f'<div class="wpp-module">{section}</div>', unsafe_allow_html=True)
    st.title(title)
    if description:
        st.markdown(f'<div class="wpp-help">{description}</div>', unsafe_allow_html=True)
    req=reference_requirements(project.get('north_reference','Grid North'))
    ref=project.get('reference_data',{})
    dec=ref.get('magnetic_declination_deg')
    conv=ref.get('grid_convergence_deg')
    dec_txt=f'{float(dec):.3f}°' if dec is not None else 'Not calculated'
    conv_txt=f'{float(conv):.3f}°' if conv is not None else 'Not calculated'
    if req['needs_convergence']:
        st.caption(f"North reference: **{req['reference']}**  •  Declination: **{dec_txt}**  •  Grid convergence: **{conv_txt}**")
    elif req['needs_declination']:
        st.caption(f"North reference: **{req['reference']}**  •  Declination: **{dec_txt}**  •  Grid convergence: not required for this primary reference")
    else:
        st.caption(f"North reference: **{req['reference']}**  •  No magnetic correction required for the primary reference")


def status_badge(status):
    return f'<span class="wpp-badge">{status}</span>'


def card(label, value, note=''):
    return f'<div class="wpp-card"><div class="wpp-card-label">{label}</div><div class="wpp-card-value">{value}</div><div class="wpp-card-note">{note}</div></div>'


# Persistent application header: same identity/context on every module.
st.markdown(
    f'<div class="wpp-topbar"><div><div class="wpp-breadcrumb">{page}</div><div class="wpp-well">{project.get("project_name", "New Project")} · {project.get("well_name", "NEW-01")}</div></div><div>{status_badge(project.get("status", "Planning"))}</div></div>',
    unsafe_allow_html=True,
)

# Dashboard
if page=='Dashboard':
    page_header('Well Planning Dashboard', 'HOME', 'Single-screen project overview. All values below are read from the shared project model used by the engineering modules.')
    surveys = project.get('surveys', []); targets = project.get('targets', []); offsets = project.get('offsets', []); casing = project.get('casing_program', [])
    td = surveys[-1].get('MD') if surveys else None
    max_inc = max([float(x.get('Inc', 0)) for x in surveys], default=0)
    max_dls = max([float(x.get('DLS', 0)) for x in surveys], default=0); dls_interval_m=float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0) or 30.0)
    cols = st.columns(5)
    metrics = [
        ('STATUS', project.get('status', 'Planning'), project.get('well_type', '')),
        ('CURRENT MD', f'{float(td)*3.280839895:,.0f} ft' if td is not None else '—', f'{len(surveys)} survey stations'),
        ('TARGETS', str(len(targets)), 'geometry objects'),
        ('OFFSETS', str(len(offsets)), 'reference wells'),
        ('CASING', str(len(casing)), 'stored strings'),
    ]
    for col, (label, value, note) in zip(cols, metrics):
        col.markdown(card(label, value, note), unsafe_allow_html=True)

    st.markdown('<div class="wpp-section">Engineering pulse</div>', unsafe_allow_html=True)
    a,b,c,d = st.columns(4)
    a.metric('Max inclination', f'{max_inc:.1f}°')
    b.metric('Max DLS', f'{dls_for_interval_to_100ft(max_dls,dls_interval_m):.2f}°/100ft')
    r = project.get('reference_data', {})
    c.metric('Declination', f'{float(r["magnetic_declination_deg"]):.2f}°' if r.get('magnetic_declination_deg') is not None else 'Not calculated')
    d.metric('Grid convergence', f'{float(r["grid_convergence_deg"]):.2f}°' if r.get('grid_convergence_deg') is not None else 'Not calculated')

    st.markdown('<div class="wpp-section">Workflow</div>', unsafe_allow_html=True)
    st.code('PROJECT → REFERENCE → SURVEY → TARGET → TRAJECTORY → OFFSETS → ANTI-COLLISION → CASING → HYDRAULICS / T&D / CEMENT / WELL CONTROL → QA/QC → REPORT', language='text')
    st.markdown('<div class="wpp-section">Master reference state</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([
        {'Parameter':'CRS','Value':project.get('crs')},
        {'Parameter':'North reference','Value':project.get('north_reference')},
        {'Parameter':'Declination (°)','Value':r.get('magnetic_declination_deg')},
        {'Parameter':'Dip (°)','Value':r.get('magnetic_dip_deg')},
        {'Parameter':'Total field (nT)','Value':r.get('magnetic_total_field_nT')},
        {'Parameter':'Grid convergence (°)','Value':r.get('grid_convergence_deg')},
        {'Parameter':'Normal gravity (m/s²)','Value':r.get('gravity_mps2')},
        {'Parameter':'Geoid height (m)','Value':r.get('geoid_height_m')},
    ]), use_container_width=True, hide_index=True)

# Project & Reference
elif page=='Project & Reference':
    page_header('Well Setup & Reference Frame', 'SETUP', 'Define the well identity and design first. Coordinate-system, projection and model details are derived where possible rather than treated as fixed assumptions.')
    st.markdown('### Well identity')
    a,b,c,d=st.columns(4)
    project['project_name']=a.text_input('Project name',project.get('project_name','New Well Planning Project'))
    project['well_name']=b.text_input('Well name',project.get('well_name','NEW-01'))
    project['well_number']=c.text_input('Well number',project.get('well_number',project.get('well_name','NEW-01')))
    project['operator']=d.text_input('Operator',project.get('operator',''))
    a,b,c,d=st.columns(4)
    project['field']=a.text_input('Field / Asset',project.get('field',''))
    project['site_pad']=b.text_input('Site / Pad',project.get('site_pad',''))
    project['well_purpose']=c.selectbox('Well purpose',['Exploration','Appraisal','Development','Injection','Sidetrack','Other'],index=['Exploration','Appraisal','Development','Injection','Sidetrack','Other'].index(project.get('well_purpose','Development')))
    project['well_design']=d.selectbox('Well design',['Vertical','J-Profile','S-Profile','Build & Hold','Build-Hold-Drop','Horizontal','ERD','Custom'],index=['Vertical','J-Profile','S-Profile','Build & Hold','Build-Hold-Drop','Horizontal','ERD','Custom'].index(project.get('well_design','Build & Hold')))

    st.markdown('### Location & coordinate system')
    a,b,c=st.columns(3); project['latitude']=a.number_input('Latitude (°)',-90.,90.,float(project['latitude']),format='%.6f'); project['longitude']=b.number_input('Longitude (°)',-180.,180.,float(project['longitude']),format='%.6f'); project['elevation_m']=c.number_input('Wellhead elevation (ft)',-6500.,33000.,float(project['elevation_m'])*3.280839895) / 3.280839895
    crs_mode=st.selectbox('Coordinate system',['Auto UTM from location','Geographic WGS84','Custom CRS / EPSG'],index=0 if project.get('crs','EPSG:4326').startswith('EPSG:326') or project.get('crs','') in ('EPSG:4326','') else 2)
    if crs_mode=='Auto UTM from location':
        zone=int((float(project['longitude'])+180)//6)+1; epsg=32600+zone if float(project['latitude'])>=0 else 32700+zone; project['crs']=f'EPSG:{epsg}'
    elif crs_mode=='Geographic WGS84':
        project['crs']='EPSG:4326'
    else:
        project['crs']=st.text_input('Custom CRS / EPSG',project.get('crs','EPSG:4326'))
    # Derive the wellhead projected coordinates from the authoritative lat/lon when the project CRS is projected.
    try:
        from pyproj import CRS
        if CRS.from_user_input(project['crs']).is_projected:
            project['surface_easting_m'], project['surface_northing_m'] = transform_coordinates(project['longitude'], project['latitude'], 'EPSG:4326', project['crs'])
    except Exception:
        pass
    a,b,c=st.columns(3); project['kb_m']=a.number_input('KB elevation (ft)',-6500.,33000.,float(project['kb_m'])*3.280839895) / 3.280839895; project['planned_date']=str(b.date_input('Planning date',date.fromisoformat(project['planned_date']))); project['units']=c.selectbox('Display units',['Field','Metric'],index=0 if project.get('units','Field')=='Field' else 1)
    st.markdown('### Derived reference information')
    try:
        ci=crs_info(project['crs']); conv=grid_convergence_deg(project['latitude'],project['longitude'],project['crs']); project['reference_data']['grid_convergence_deg']=conv; project['reference_data']['project_crs']=project['crs']; project['reference_data']['datum']=ci.get('datum'); project['reference_data']['ellipsoid']=ci.get('ellipsoid')
        if ci.get('epsg'):
            st.success(f"Active CRS: {ci['name']} • EPSG:{ci['epsg']} • Grid convergence: {conv:.4f}°")
        else: st.success(f"Active CRS: {ci['name']} • Grid convergence: {conv:.4f}°")
        st.dataframe(pd.DataFrame([ci]),use_container_width=True,hide_index=True)
        if ci.get('type') == 'Projected':
            st.info(f"Wellhead projected position: Easting {project.get('surface_easting_m',0):,.3f} m ({project.get('surface_easting_m',0)*M_TO_FT:,.2f} ft) • Northing {project.get('surface_northing_m',0):,.3f} m ({project.get('surface_northing_m',0)*M_TO_FT:,.2f} ft)")
    except Exception as e: st.error(f'CRS/reference calculation error: {e}')
    a,b,c=st.columns(3); project['north_reference']=a.selectbox('Primary north reference',['True North','Grid North','Magnetic North'],index=['True North','Grid North','Magnetic North'].index(project.get('north_reference','Grid North'))); depth_options=['MD / TVDSS','MD / TVD']; project['depth_reference']=b.selectbox('Depth reference',depth_options,index=depth_options.index(project.get('depth_reference','MD / TVDSS'))); project['status']=c.selectbox('Project status',['Planning','Draft','Under Review','Approved for Training'],index=['Planning','Draft','Under Review','Approved for Training'].index(project.get('status','Planning')))
    st.markdown('### Design constraints')
    dc=project['design_constraints']; a,b,c=st.columns(3); dc['max_dls_deg_30m']=dls_100ft_to_30m(a.number_input('Max DLS (°/100 ft)',.1,20.,dls_30m_to_100ft(float(dc['max_dls_deg_30m'])))); dc['max_inclination_deg']=b.number_input('Max inclination (°)',0.,180.,float(dc['max_inclination_deg'])); dc['max_build_rate_deg_30m']=dls_100ft_to_30m(c.number_input('Max build rate (°/100 ft)',.1,20.,dls_30m_to_100ft(float(dc['max_build_rate_deg_30m']))))
    if st.button('Save project/reference settings',type='primary'): save(); st.success('Saved.')

# Survey Manager
elif page=='Survey Manager':
    page_header('Survey Manager', 'DIRECTIONAL', 'Load, normalize and calculate survey trajectories while preserving the selected azimuth reference and uncertainty assumptions.')
    sm=project['survey_metadata']; ref=project['reference_data']
    req=reference_requirements(project.get('north_reference','Grid North')); st.info(f"**Primary reference: {req['reference']}** — {req['label']}")
    a,b,c=st.columns(3); sm['azimuth_reference']=a.selectbox('Input azimuth reference',['Magnetic North','True North','Grid North'],index=['Magnetic North','True North','Grid North'].index(sm['azimuth_reference'])); tool_options=['MWD','Gyro','Wireline','Planned','Other']; sm['survey_tool']=b.selectbox('Survey tool',tool_options,index=tool_options.index(sm.get('survey_tool','MWD'))); method_options=['Minimum Curvature','Average Angle','Balanced Tangential']; sm['survey_method']=c.selectbox('Calculation method',method_options,index=method_options.index(sm.get('survey_method','Minimum Curvature')))
    st.caption('Survey position uncertainty is now represented by a covariance-based development model. Configure the survey error parameters on the Anti-Collision page; a legacy scalar sigma remains in the project schema only for backward compatibility.')
    df=pd.DataFrame(project.get('surveys',[])); display_df=(df.copy() if not df.empty else pd.DataFrame([{'MD':0.,'Inc':0.,'Azi':0.}]))
    if 'MD' in display_df.columns: display_df['MD']=display_df['MD']*M_TO_FT
    edited=st.data_editor(display_df,num_rows='dynamic',use_container_width=True,hide_index=True,key='survey_editor')
    a,b,c=st.columns(3); interval_ft=a.number_input('DLS interval (ft)',10.,3280.,100.); interval=interval_ft*FT_TO_M; st.metric('TVDSS reference',f"KB {project.get('kb_m',0)*M_TO_FT:.2f} ft MSL"); do=c.button('Calculate & store trajectory',type='primary')
    if do:
        try:
            w=edited[['MD','Inc','Azi']].copy(); w['MD']=w['MD']*FT_TO_M
            dec=ref.get('magnetic_declination_deg'); conv=ref.get('grid_convergence_deg')
            input_ref=sm['azimuth_reference']
            project_ref=project.get('north_reference','Grid North')
            needs_declination=(input_ref != project_ref and 'Magnetic North' in (input_ref, project_ref))
            needs_convergence=(input_ref != project_ref and 'Grid North' in (input_ref, project_ref))
            if needs_declination and dec is None:
                raise ValueError('Magnetic declination is not calculated. Run Geomagnetics before converting magnetic/true survey azimuths.')
            if needs_convergence and conv is None:
                raise ValueError('Grid convergence is not calculated. Run Geodesy before converting grid/true survey azimuths.')
            w['Azi']=w['Azi'].map(lambda x: convert_to_project_reference(x,input_ref,project_ref,float(dec or 0.0) if needs_declination else 0.0,float(conv or 0.0) if needs_convergence else 0.0))
            result=minimum_curvature(w,interval); result['TVDSS']=float(project.get('kb_m',0))-result['TVD']
            uparams=sm.setdefault('survey_error_parameters', {'sigma_md_ft':0.5,'sigma_inc_deg':0.10,'sigma_azi_deg':0.25,'sigma_inc_systematic_deg':0.10,'sigma_azi_systematic_deg':0.25,'sigma_surface_ft':5.0})
            cov=station_covariances(w, **uparams)
            for col in [c for c in cov.columns if c.startswith('Cov_') or c.startswith('Unc_')]: result[col]=cov[col].to_numpy()
            sm['uncertainty_model']='Covariance-based stationwise screening (engineering-development)'
            project['surveys']=result.to_dict('records'); project['trajectory_metadata']={'method':sm['survey_method'],'dls_interval_m':interval,'dls_interval_ft':interval_ft,'uncertainty_model':'Covariance-based stationwise screening (engineering-development)','calculated_utc':datetime.utcnow().isoformat()+'Z'}; save(); st.success('Trajectory and covariance profile calculated and stored.')
        except Exception as e: st.error(str(e))
    if project.get('surveys'):
        sv=pd.DataFrame(project['surveys']).copy()
        for col in ['MD','TVD','TVDSS','Northing','Easting','VS']:
            if col in sv.columns: sv[col]=sv[col]*M_TO_FT
        if 'DLS' in sv.columns:
            stored_interval=float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0))
            sv['DLS']=sv['DLS'].map(lambda x: dls_for_interval_to_100ft(x, stored_interval))
        cov_cols=[c for c in sv.columns if c.startswith('Cov_')]
        uncertainty_cols=[c for c in sv.columns if c.startswith('Unc_')]
        display_cols=[c for c in sv.columns if c not in cov_cols+uncertainty_cols]
        st.dataframe(sv[display_cols],use_container_width=True,hide_index=True)
        if {'Unc_major_1sigma_m','Unc_minor_1sigma_m','Unc_vertical_1sigma_m'}.issubset(project.get('surveys',[{}])[-1].keys()):
            last=project['surveys'][-1]
            st.info(f"End-of-survey 1σ uncertainty: major {float(last['Unc_major_1sigma_m'])*M_TO_FT:.1f} ft • minor {float(last['Unc_minor_1sigma_m'])*M_TO_FT:.1f} ft • vertical {float(last['Unc_vertical_1sigma_m'])*M_TO_FT:.1f} ft • ellipse azimuth {float(last['Unc_azimuth_deg']):.1f}° Grid")
            with st.expander('Covariance / uncertainty details'):
                uview=sv[['MD']+[c for c in uncertainty_cols if c in sv.columns]].copy()
                st.dataframe(uview,use_container_width=True,hide_index=True)
                st.caption('The stored covariance fields are in m²; the summary above is displayed in field units. The uncertainty model is an engineering-development model, not an ISCWSA-certified error model.')
    f=st.file_uploader('Import survey CSV (MD, Inc, Azi) — MD interpreted as ft',type='csv',key='survey_upload')
    if f:
        imp=pd.read_csv(f); st.dataframe(imp.head(),use_container_width=True)
        if st.button('Replace survey with CSV'):
            if {'MD','Inc','Azi'}.issubset(imp.columns): imp['MD']=imp['MD']*FT_TO_M; project['surveys']=imp[['MD','Inc','Azi']].to_dict('records'); save(); st.success('Imported. Calculate & store trajectory to generate positions, TVDSS and DLS.')
            else: st.error('CSV must contain MD, Inc and Azi.')

# Trajectory Planner
elif page=='Trajectory Planner':
    page_header('Trajectory Planner', 'DIRECTIONAL', 'Generate a planning candidate from target geometry and review the resulting trajectory before using it downstream.')
    st.caption('Practice-grade target-driven build/hold planner. The planner works in a well-relative local frame derived from the target and wellhead coordinates.')
    targets=project.get('targets',[])
    valid_targets=[t for t in targets if t.get('name')]
    if not valid_targets: st.warning('Define a valid target first on the Targets page.'); st.stop()
    names=[t.get('name','Target') for t in valid_targets]; idx=st.selectbox('Target',range(len(names)),format_func=lambda i:names[i]); t=valid_targets[idx]
    surface_n=float(project.get('surface_northing_m',0)); surface_e=float(project.get('surface_easting_m',0))
    target_n=float(t.get('north_m',0)); target_e=float(t.get('east_m',0)); rel_n=target_n-surface_n; rel_e=target_e-surface_e
    target_tvdss=float(t.get('tvdss_m',0)); target_tvd=float(project.get('kb_m',0))-target_tvdss
    default_az=(math.degrees(math.atan2(rel_e,rel_n))%360.0) if abs(rel_n)+abs(rel_e)>1e-9 else 0.0
    max_inc=float(project.get('design_constraints',{}).get('max_inclination_deg',57.0) or 57.0)
    default_hold=min(57.0,max_inc)
    profile_options=['Vertical','J-Profile','S-Profile','Build & Hold','Build-Hold-Drop','Horizontal','ERD','Custom']
    saved_profile=project.get('well_design','Build & Hold')
    profile_default=saved_profile if saved_profile in profile_options else 'Build & Hold'
    profile=st.selectbox('Well trajectory shape',profile_options,index=profile_options.index(profile_default),help='This selection controls the inclination-versus-MD profile generated when you press Generate trajectory.')
    if profile=='Custom': st.info('Custom currently uses a configurable build–hold–drop template. Optimization searches KOP, build rate, peak inclination, azimuth, drop start, drop rate and final inclination. Arbitrary user-defined multi-section control points are not yet implemented.')
    planning_mode=st.radio('Planning mode',['Manual profile','Optimize selected profile to target'],horizontal=True,help='The optimizer searches profile-specific parameters including KOP, build rate, peak inclination and azimuth; S/Build-Hold-Drop also optimize drop rate and final inclination. It reports REVIEW if the target or constraints are not satisfied.')
    a,b,c,d=st.columns(4); kop_ft=a.number_input('KOP MD (ft)',0.,49213.,float(project['well_architecture'].get('kop_md_m') or 1450)*M_TO_FT); br_ft=b.number_input('Build rate (°/100 ft)',.1,15.,3.0); hold=c.number_input('Peak/hold inclination (°)',1.,max(1.0,max_inc),default_hold,help='Peak inclination for the selected profile. Horizontal uses 90°; ERD uses at least 75° and is capped at 88°. In optimization mode this is the initial/default inclination; the optimizer searches within the permitted range.'); az=d.number_input('Planning azimuth (° Grid)',0.,360.,default_az)
    a,b=st.columns(2); dr_ft=a.number_input('Drop rate (°/100 ft)',.1,15.,3.0,help='Used by S-Profile and Build-Hold-Drop.'); final_inc=b.number_input('Final inclination after drop (°)',0.,max(1.0,max_inc),0.0,help='Used by S-Profile and Build-Hold-Drop.')
    a,b,c=st.columns(3); a.number_input('Target TVD (ft)',0.,49213.,target_tvd*M_TO_FT,disabled=True); b.number_input('Target Northing offset (ft)',-3280840.,3280840.,rel_n*M_TO_FT,disabled=True); c.number_input('Target Easting offset (ft)',-3280840.,3280840.,rel_e*M_TO_FT,disabled=True)
    st.caption(f'Maximum inclination constraint: **{max_inc:.1f}°** • Target azimuth from project-grid geometry: **{default_az:.2f}° Grid**')
    kop=kop_ft*FT_TO_M; br=dls_100ft_to_30m(br_ft); td=target_tvd; n=rel_n; e=rel_e
    if target_tvd <= 0: st.error('Target TVD must be positive after applying the KB/TVDSS reference conversion.'); st.stop()
    max_build_ft=dls_30m_to_100ft(float(project.get('design_constraints',{}).get('max_build_rate_deg_30m',br)))
    if br_ft > max_build_ft+1e-9: st.warning(f'Build rate exceeds the project maximum build-rate constraint of {max_build_ft:.2f}°/100 ft.')
    if profile not in ('Vertical',) and hold > max_inc and profile not in ('Horizontal',): st.error('Peak/hold inclination exceeds the project maximum inclination constraint.')
    if abs(az-default_az)>0.05: st.warning(f'Planning azimuth differs from the target-center azimuth by {abs(az-default_az):.2f}°. The candidate may not be target-center aligned.')
    st.caption(f'Current design preset: **{saved_profile}**. Selected calculation profile: **{profile}**. The stored survey changes only when you generate the trajectory.')
    if st.button('Generate trajectory for selected shape',type='primary'):
        try:
            requested_peak = 0.0 if profile == 'Vertical' else (90.0 if profile == 'Horizontal' else (min(max(hold,75.0),88.0) if profile == 'ERD' else hold))
            if requested_peak > max_inc + 1e-9:
                raise ValueError(f'{profile} requires a peak inclination of {requested_peak:.1f}°, above the project maximum inclination of {max_inc:.1f}°. Update the design constraint first if this profile is intended.')
            if planning_mode=='Optimize selected profile to target':
                target_geometry=dict(t)
                target_geometry['north_m']=rel_n
                target_geometry['east_m']=rel_e
                out,meta=optimize_trajectory(
                    profile=profile, target_tvd_m=td, target_north_m=n, target_east_m=e,
                    kop_initial_m=kop, build_rate_initial_deg_30m=br,
                    peak_inc_initial_deg=requested_peak, azimuth_initial_deg=az,
                    max_inclination_deg=max_inc,
                    max_dls_deg_30m=float(project.get('design_constraints',{}).get('max_dls_deg_30m',3.0) or 3.0),
                    max_build_rate_deg_30m=float(project.get('design_constraints',{}).get('max_build_rate_deg_30m',3.0) or 3.0),
                    max_turn_rate_deg_30m=float(project.get('design_constraints',{}).get('max_turn_rate_deg_30m',3.0) or 3.0),
                    drop_rate_initial_deg_30m=dls_100ft_to_30m(dr_ft), final_inc_initial_deg=final_inc,
                    target_geometry=target_geometry, point_tolerance_m=30.48,
                    station_interval_m=60.0, max_md_m=float(project.get('well_architecture',{}).get('planned_td_md_m') or 15000.0),
                )
                meta=dict(meta); meta['planning_mode']='Optimize selected profile to target'
            else:
                out,meta=generate_profile_candidate(profile,kop,br,hold,az,td,n,e,drop_rate_deg_30m=dls_100ft_to_30m(dr_ft),final_inc_deg=final_inc,station_interval=30)
                meta=dict(meta); meta['planning_mode']='Manual profile'
            project['surveys']=out.to_dict('records'); project['well_design']=profile; project['trajectory_metadata']={'planner':'Profile-aware multi-parameter optimizer' if planning_mode=='Optimize selected profile to target' else 'Piecewise profile candidate','planner_result':meta,'profile':profile,'planning_mode':planning_mode,'dls_interval_m':30.0,'dls_interval_ft':30.0*M_TO_FT,'calculated_utc':datetime.utcnow().isoformat()+'Z'}; save()
            st.success(f"Profile: {profile} • status {meta['status']} • lateral error {meta['lateral_error_m']*M_TO_FT:.1f} ft • TVD error {meta['tvd_error_m']*M_TO_FT:.1f} ft • final inclination {meta['final_inclination_deg']:.2f}°")
            if planning_mode=='Optimize selected profile to target':
                st.metric('Optimization outcome', meta.get('optimization_status','REVIEW'))
                st.caption(f"Objective score: {meta.get('objective_m', float('nan')):.2f} m • Evaluations: {meta.get('optimizer_evaluations','—')} • Max DLS: {meta.get('max_dls_deg_30m', float('nan')):.2f}°/30 m")
                if meta.get('optimization_status') != 'FEASIBLE': st.warning('No candidate met all current target and trajectory constraints. The best candidate is shown for review; constraints have not been relaxed.')
            b1,b2,b3,b4=st.columns(4); b1.metric('Build end / EOB',f"{meta['build_end_md_m']*M_TO_FT:,.0f} ft"); b2.metric('Build length',f"{meta['build_length_m']*M_TO_FT:,.0f} ft"); b3.metric('Final MD',f"{meta['final_md_m']*M_TO_FT:,.0f} ft"); b4.metric('Final inclination',f"{meta['final_inclination_deg']:.1f}°")
            out_display=out.copy(); [out_display.__setitem__(cc,out_display[cc]*M_TO_FT) for cc in ['MD','TVD','Northing','Easting','VS'] if cc in out_display.columns]; out_display['TVDSS']=(float(project.get('kb_m',0))-out['TVD'])*M_TO_FT; out_display['DLS']=out_display['DLS'].map(lambda x:dls_for_interval_to_100ft(x,30.0)); st.dataframe(out_display,use_container_width=True,hide_index=True)
        except Exception as ex: st.error(str(ex))

# Targets
elif page=='Targets':
    page_header('Target Management', 'SETUP', 'Create and manage target geometries in the project CRS. Absolute Easting/Northing are stored internally in the CRS native units (metres for EPSG:32632).')
    st.caption('Target coordinates are absolute project coordinates; the trajectory planner converts them to offsets from the wellhead automatically.')
    types=['Point','Circular','Elliptical','Rectangular','Corridor','Polygon']; typ=st.selectbox('New target type',types); a,b,c=st.columns(3); name=a.text_input('Target name','Target-01'); n=a.number_input('Center Northing (ft)',-10000000.,10000000.,float(project.get('surface_northing_m',0))*M_TO_FT); e=b.number_input('Center Easting (ft)',-10000000.,10000000.,float(project.get('surface_easting_m',0))*M_TO_FT);
    if project.get('depth_reference','MD / TVDSS')=='MD / TVDSS':
        tvdss=c.number_input('Target TVDSS (ft)',-50000.,50000.,-12000.)
    else:
        tvd=c.number_input('Target TVD (ft)',0.,50000.,12000.); tvdss=(float(project.get('kb_m',0))-tvd*FT_TO_M)*M_TO_FT
    t={'name':name,'type':typ,'north_m':n*FT_TO_M,'east_m':e*FT_TO_M,'tvdss_m':tvdss*FT_TO_M}
    if typ=='Circular': t['radius_m']=st.number_input('Radius (ft)',.1,10000.,50.)*FT_TO_M
    elif typ=='Elliptical':
        a,b,c=st.columns(3); t['semi_major_m']=a.number_input('Semi-major axis (ft)',.1,10000.,131.); t['semi_major_m']*=FT_TO_M; t['semi_minor_m']=b.number_input('Semi-minor axis (ft)',.1,10000.,66.)*FT_TO_M; t['orientation_deg']=c.number_input('Orientation from North (°)',-360.,360.,45.)
    elif typ=='Rectangular':
        a,b=st.columns(2); t['length_m']=a.number_input('North-South length (ft)',.1,10000.,200.)*FT_TO_M; t['width_m']=b.number_input('East-West width (ft)',.1,10000.,100.)*FT_TO_M
    elif typ=='Corridor':
        a,b,c=st.columns(3); t['half_length_m']=a.number_input('Half-length (ft)',.1,20000.,1000.)*FT_TO_M; t['half_width_m']=b.number_input('Half-width (ft)',.1,5000.,50.)*FT_TO_M; t['azimuth_deg']=c.number_input('Corridor azimuth (°)',0.,360.,0.)
    elif typ=='Polygon':
        txt=st.text_area('Polygon points as North,East per line','0,0\n0,100\n100,100\n100,0'); pts=[]
        for line in txt.splitlines():
            try: nn,ee=[float(x.strip()) for x in line.split(',')[:2]]; pts.append([nn,ee])
            except Exception: pass
        t['points']=pts
    if st.button('Add target',type='primary'):
        if not name.strip(): st.error('Target name is required.')
        elif project.get('crs','').upper()=='EPSG:4326': st.error('Select a projected project CRS before creating an absolute-coordinate target.')
        else: project['targets'].append(t); save(); st.success('Target added.')
    if project['targets']:
        td=pd.DataFrame(project['targets']).copy()
        for col in ['north_m','east_m','tvdss_m','radius_m','semi_major_m','semi_minor_m','length_m','width_m','half_length_m','half_width_m']:
            if col in td.columns: td[col.replace('_m','_ft')]=td[col]*M_TO_FT; td.drop(columns=[col],inplace=True)
        st.dataframe(td,use_container_width=True,hide_index=True)

# Offsets
elif page=='Offsets':
    page_header('Offset Wells', 'SETUP', 'Create independent reference wells. Surface latitude/longitude are transformed automatically into the project CRS; relative project-grid offsets are then derived.')
    a,b,c=st.columns(3); name=a.text_input('Offset name','OW-01'); lat=b.number_input('Offset latitude',-90.,90.,float(project['latitude']),format='%.6f'); lon=c.number_input('Offset longitude',-180.,180.,float(project['longitude']),format='%.6f')
    try:
        off_e,off_n=transform_coordinates(lon,lat,'EPSG:4326',project.get('crs','EPSG:4326'))
        main_n=float(project.get('surface_northing_m',0.0)); main_e=float(project.get('surface_easting_m',0.0))
        st.info(f'Automatically transformed to project CRS {project.get("crs")}: Easting {off_e*M_TO_FT:,.2f} ft • Northing {off_n*M_TO_FT:,.2f} ft • Relative ΔN {(off_n-main_n)*M_TO_FT:,.2f} ft • ΔE {(off_e-main_e)*M_TO_FT:,.2f} ft')
    except Exception as ex:
        off_e=off_n=None; st.error(f'Offset coordinate transformation failed: {ex}')
    if st.button('Create offset well'):
        if off_e is None: st.error('Cannot create offset without a valid project-coordinate transformation.')
        else:
            project['offsets'].append({'name':name,'latitude':lat,'longitude':lon,'surface_northing_m':off_n,'surface_easting_m':off_e,'crs':project.get('crs'),'north_reference':project.get('north_reference','Grid North'),'azimuth_reference':project.get('north_reference','Grid North'),'surveys':[{'MD':0.,'Inc':0.,'Azi':0.}]}); save(); st.success('Offset created in the project CRS.')
    for i,off in enumerate(project['offsets']):
        with st.expander(f"{i+1}. {off.get('name','Offset')}"):
            main_n=float(project.get('surface_northing_m',0.0)); main_e=float(project.get('surface_easting_m',0.0)); off_n=float(off.get('surface_northing_m',main_n)); off_e=float(off.get('surface_easting_m',main_e))
            st.write(f"**Surface location:** {float(off.get('latitude',float('nan'))):.6f}°, {float(off.get('longitude',float('nan'))):.6f}°")
            st.write(f"**Project CRS:** {off.get('crs',project.get('crs'))}  •  **Relative to WN-01:** Northing {((off_n-main_n)*M_TO_FT):.2f} ft, Easting {((off_e-main_e)*M_TO_FT):.2f} ft")
            st.caption(f"Trajectory status: {'Subsurface survey available' if len(off.get('surveys', [])) > 1 else 'Surface location only — add/import survey stations to display the well path'}")
            template_csv=pd.DataFrame([{'MD':0.0,'Inc':0.0,'Azi':0.0},{'MD':1000.0,'Inc':10.0,'Azi':float(off.get('surveys',[{'Azi':0}])[-1].get('Azi',0))}]).to_csv(index=False).encode('utf-8')
            st.download_button('Download offset survey CSV template',template_csv,file_name=f"{off.get('name','offset').replace(' ','_')}_survey_template.csv",mime='text/csv',key=f'offset_template_{i}')
            off_upload=st.file_uploader('Import offset survey CSV (MD ft, Inc deg, Azi deg)', type='csv', key=f'offset_csv_{i}')
            if off_upload is not None:
                try:
                    imp_off=pd.read_csv(off_upload)
                    if not {'MD','Inc','Azi'}.issubset(imp_off.columns):
                        st.error('Offset CSV must contain MD, Inc and Azi columns. MD must be in ft; inclination and azimuth in degrees.')
                    elif st.button(f'Import survey for {off.get("name", "offset")}', key=f'import_offset_{i}'):
                        raw_off=imp_off[['MD','Inc','Azi']].copy(); raw_off['MD']=pd.to_numeric(raw_off['MD'],errors='raise')*FT_TO_M
                        calc_off=minimum_curvature(raw_off, dls_interval=30.0)
                        uparams=project.get('survey_metadata',{}).get('survey_error_parameters', {})
                        cov_off=station_covariances(raw_off, **uparams)
                        for cc in cov_off.columns:
                            if cc.startswith('Cov_') or cc.startswith('Unc_'): calc_off[cc]=cov_off[cc].to_numpy()
                        off['surveys']=calc_off.to_dict('records'); off['survey_source']='Imported survey CSV'; off['survey_method']='Minimum Curvature'; off['north_reference']=project.get('north_reference','Grid North'); off['crs']=project.get('crs'); save(); st.success(f"Imported {len(calc_off)} survey stations for {off.get('name','offset')}"); st.rerun()
                except Exception as ex: st.error(f'Offset survey import failed: {ex}')
            odf=pd.DataFrame(off.get('surveys',[])); od_display=odf.copy();
            if 'MD' in od_display.columns: od_display['MD']=od_display['MD']*M_TO_FT
            ed=st.data_editor(od_display,num_rows='dynamic',key=f'off{i}',use_container_width=True)
            if st.button(f'Save {off.get("name")}',key=f'saveoff{i}'):
                try:
                    ed_calc=ed[['MD','Inc','Azi']].copy(); ed_calc['MD']=ed_calc['MD']*FT_TO_M; off_result=minimum_curvature(ed_calc); uparams=project.get('survey_metadata',{}).get('survey_error_parameters', {'sigma_md_ft':0.5,'sigma_inc_deg':0.10,'sigma_azi_deg':0.25,'sigma_inc_systematic_deg':0.10,'sigma_azi_systematic_deg':0.25,'sigma_surface_ft':5.0}); cov=station_covariances(ed_calc, **uparams); [off_result.__setitem__(col,cov[col].to_numpy()) for col in cov.columns if col.startswith('Cov_') or col.startswith('Unc_')]; off['surveys']=off_result.to_dict('records'); off['crs']=project.get('crs'); off['north_reference']=project.get('north_reference','Grid North'); save(); st.success('Saved offset trajectory and covariance profile.')
                except Exception as ex: st.error(str(ex))
    if project['offsets']:
        main_n=float(project.get('surface_northing_m',0.0)); main_e=float(project.get('surface_easting_m',0.0)); rows=[]
        for x in project['offsets']:
            on=float(x.get('surface_northing_m',main_n)); oe=float(x.get('surface_easting_m',main_e)); rows.append({'Name':x.get('name'),'Lat':x.get('latitude'),'Lon':x.get('longitude'),'CRS':x.get('crs',project.get('crs')),'Δ Northing (ft)':(on-main_n)*M_TO_FT,'Δ Easting (ft)':(oe-main_e)*M_TO_FT})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

# Well Architecture
elif page=='Well Architecture':
    page_header('Well Architecture & Final Casing Program', 'SETUP', 'Store the final well architecture and casing program as shared master data for downstream engineering checks.')
    a,b,c=st.columns(3); wa=project['well_architecture']; wa['planned_td_md_m']=a.number_input('Planned TD MD (ft)',0.,98425.,float(wa.get('planned_td_md_m') or 4250)*M_TO_FT)*FT_TO_M; wa['planned_td_tvd_m']=b.number_input('Planned TD TVD (ft)',0.,98425.,float(wa.get('planned_td_tvd_m') or 3700)*M_TO_FT)*FT_TO_M; wa['kop_md_m']=c.number_input('KOP MD (ft)',0.,98425.,float(wa.get('kop_md_m') or 1450)*M_TO_FT)*FT_TO_M
    cols=['string_no','type','hole_size_in','casing_od_in','grade','weight_lbft','shoe_md_m','depth_type','shoe_tvd_m','shoe_tvdss_m','liner_top_md_m','top_md_m','remarks']; old=pd.DataFrame(project.get('casing_program',[]));
    if old.empty: old=pd.DataFrame([{'string_no':1,'type':'Conductor','hole_size_in':24.,'casing_od_in':18.625,'grade':'','weight_lbft':0.,'shoe_md_m':250.,'depth_type':'MD','shoe_tvd_m':250.,'shoe_tvdss_m':225.,'liner_top_md_m':0.,'top_md_m':0.,'remarks':''}])
    for col in cols:
        if col not in old.columns: old[col]=''
    arch_display=old[cols].copy()
    for col in ['shoe_md_m','shoe_tvd_m','shoe_tvdss_m','liner_top_md_m','top_md_m']:
        if col in arch_display.columns: arch_display[col.replace('_m','_ft')]=arch_display[col].apply(lambda x: float(x)*M_TO_FT if x not in ('',None) else x); arch_display.drop(columns=[col],inplace=True)
    ed=st.data_editor(arch_display,num_rows='dynamic',use_container_width=True,hide_index=True,key='arch')
    if st.button('Save final casing architecture',type='primary'):
        arch_save=ed.copy()
        for col in ['shoe_md_ft','shoe_tvd_ft','shoe_tvdss_ft','liner_top_md_ft','top_md_ft']:
            if col in arch_save.columns: arch_save[col.replace('_ft','_m')]=arch_save[col].apply(lambda x: float(x)*FT_TO_M if x not in ('',None) else x); arch_save.drop(columns=[col],inplace=True)
        project['casing_program']=casing_program_summary(arch_save.to_dict('records')); save(); st.success('Saved.')
    if project['casing_program']: st.dataframe(pd.DataFrame(casing_geometry_checks(project['casing_program'])),use_container_width=True,hide_index=True)

# Geomagnetics
elif page=='Geomagnetics':
    page_header('Geomagnetics', 'DIRECTIONAL', 'Calculate magnetic-field quantities and convert between magnetic, true and grid north references.')
    st.caption('Select the geomagnetic reference model used for declination, dip and total field. The selected model and provenance are stored in the project.')
    a,b,c,d=st.columns(4); lat=a.number_input('Latitude (°)',-90.,90.,float(project['latitude']),format='%.6f'); lon=b.number_input('Longitude (°)',-180.,180.,float(project['longitude']),format='%.6f'); alt_ft=c.number_input('Ellipsoidal height (ft)',-3280.,65617.,float(project['elevation_m'])*M_TO_FT); alt=alt_ft*FT_TO_M; model=d.selectbox('Geomagnetic model',['WMM2025','IGRF-14'],index=0 if project.get('model_metadata',{}).get('active_geomagnetic_model','WMM2025')=='WMM2025' else 1)
    dt=st.date_input('Model calculation date',date.fromisoformat(project['planned_date']))
    if st.button(f'Calculate {model}',type='primary'):
        try:
            r=wmm2025(lat,lon,alt,dt) if model=='WMM2025' else igrf14(lat,lon,alt,dt)
            ref=project['reference_data']; ref.update({'magnetic_declination_deg':r['D'],'magnetic_dip_deg':r['I'],'magnetic_total_field_nT':r['F'],'magnetic_horizontal_field_nT':r['H'],'magnetic_x_nT':r['X'],'magnetic_y_nT':r['Y'],'magnetic_z_nT':r['Z']})
            project.setdefault('model_metadata',{}).setdefault('results',{})[model] = r
            project['model_metadata'][model]=r['metadata']; project['model_metadata']['active_geomagnetic_model']=model; ref['geomagnetic_model']=model; ref['geomagnetic_model_metadata']=r['metadata']
            save(); st.success(f'{model} result stored.')
        except Exception as e: st.error(f'{model} calculation failed: {e}')
    stored=project.get('model_metadata',{}).get('results',{}).get(model)
    if stored:
        r=stored
    else:
        # Only show legacy shared values for WMM; never present WMM values as IGRF output.
        r=project['reference_data'] if model=='WMM2025' else {'D':None,'I':None,'F':None,'H':None,'X':None,'Y':None,'Z':None}
    st.dataframe(pd.DataFrame([{'Quantity':'Declination','Value':r.get('D') if 'D' in r else r.get('magnetic_declination_deg'),'Unit':'deg'},{'Quantity':'Dip','Value':r.get('I') if 'I' in r else r.get('magnetic_dip_deg'),'Unit':'deg'},{'Quantity':'Total field','Value':r.get('F') if 'F' in r else r.get('magnetic_total_field_nT'),'Unit':'nT'}]),use_container_width=True,hide_index=True)
    with st.expander('Advanced model details — field components'):
        st.dataframe(pd.DataFrame([{'Component':'X','Value':r.get('X') if 'X' in r else r.get('magnetic_x_nT'),'Unit':'nT'},{'Component':'Y','Value':r.get('Y') if 'Y' in r else r.get('magnetic_y_nT'),'Unit':'nT'},{'Component':'Z','Value':r.get('Z') if 'Z' in r else r.get('magnetic_z_nT'),'Unit':'nT'},{'Component':'Horizontal field H','Value':r.get('H') if 'H' in r else r.get('magnetic_horizontal_field_nT'),'Unit':'nT'}]),use_container_width=True,hide_index=True)
    st.markdown('### North-reference converter')
    st.caption('Use this when an azimuth from a survey, MWD report or external dataset is expressed relative to a different north than the project. It changes the reference of the direction; it does not change the physical direction.')
    st.markdown('**Magnetic → True → Grid** is the normal path when an MWD azimuth must be compared with a Grid North well plan.')
    a,b,c,d=st.columns(4); az=a.number_input('Input azimuth (°)',0.,360.,0.); fr=b.selectbox('From reference',['Magnetic','True','Grid']); to=c.selectbox('To reference',['Magnetic','True','Grid']);
    if d.button('Convert azimuth'):
        needs_dec=fr!=to and ('Magnetic' in (fr,to)); needs_conv=fr!=to and ('Grid' in (fr,to)); dec=r.get('D') if r.get('D') is not None else r.get('magnetic_declination_deg'); conv=project.get('reference_data',{}).get('grid_convergence_deg')
        if needs_dec and dec is None: st.error('Magnetic declination is not calculated. Run the selected geomagnetic model first.')
        elif needs_conv and conv is None: st.error('Grid convergence is not calculated. Run Geodesy first.')
        else:
            dec=float(dec or 0); conv=float(conv or 0); out=az if fr==to else magnetic_to_true(az,dec) if (fr,to)==('Magnetic','True') else true_to_magnetic(az,dec) if (fr,to)==('True','Magnetic') else true_to_grid(az,conv) if (fr,to)==('True','Grid') else grid_to_true(az,conv) if (fr,to)==('Grid','True') else magnetic_to_grid(az,dec,conv) if (fr,to)==('Magnetic','Grid') else grid_to_magnetic(az,dec,conv); st.success(f'{az:.4f}° {fr} → **{out:.4f}° {to}**')
            if fr!=to: st.write({'magnetic_declination_deg':dec if needs_dec else None,'grid_convergence_deg':conv if needs_conv else None,'input_reference':fr,'output_reference':to})

# Geodesy
elif page=='Geodesy':
    page_header('Geodesy, CRS, Convergence, Geoid & Gravity', 'DIRECTIONAL', 'Manage CRS transformations and reference quantities that support accurate survey and positional work.')
    try:
        info=crs_info(project['crs']); req=reference_requirements(project.get('north_reference','Grid North')); st.info(f"**Primary reference: {req['reference']}** — {req['label']}")
        conv=grid_convergence_deg(project['latitude'],project['longitude'],project['crs']); project['reference_data']['grid_convergence_deg']=conv
        grav=normal_gravity(project['latitude'],project['elevation_m']); project['reference_data']['gravity_mps2']=grav; project['reference_data']['project_crs']=project['crs']
        st.metric('Grid convergence',f'{conv:.6f}°'); st.metric('Normal gravity',f'{grav:.9f} m/s²'); st.dataframe(pd.DataFrame([info]),use_container_width=True,hide_index=True)
    except Exception as e: st.error(str(e))
    st.markdown('### Automatic project-coordinate normalization')
    st.caption('The normal planning workflow performs required coordinate transformations automatically. The project CRS is the authoritative spatial frame; users do not need to run a transformation manually before targets, offsets or anti-collision can be used.')
    from pyproj import CRS
    try:
        project_crs=CRS.from_user_input(project.get('crs','EPSG:4326'))
        if project_crs.is_projected:
            ex=float(project.get('surface_easting_m',0)); ny=float(project.get('surface_northing_m',0))
            st.success(f'Wellhead normalized to project CRS: **{project.get("crs")}** • Easting {ex:.3f} m ({ex*M_TO_FT:.2f} ft) • Northing {ny:.3f} m ({ny*M_TO_FT:.2f} ft)')
        else:
            st.info('The selected project CRS is geographic. Absolute project-grid calculations are unavailable until a projected CRS is selected.')
    except Exception as e: st.error(f'Project CRS normalization error: {e}')
    with st.expander('Advanced coordinate transformation utility'):
        src_default='EPSG:4326'; dst_default=project.get('crs','EPSG:4326')
        try:
            src_crs=CRS.from_user_input(src_default)
            x_default=float(project['longitude']); y_default=float(project['latitude'])
            x_label='Input X / Longitude (°)' if src_crs.is_geographic else 'Input X / Easting (native units)'; y_label='Input Y / Latitude (°)' if src_crs.is_geographic else 'Input Y / Northing (native units)'
        except Exception:
            x_default=float(project.get('surface_easting_m',0)); y_default=float(project.get('surface_northing_m',0)); x_label='Input X'; y_label='Input Y'
        a,b,c,d=st.columns(4); x=a.number_input(x_label,-1e8,1e8,x_default); y=b.number_input(y_label,-1e8,1e8,y_default); src=c.text_input('Source CRS',src_default); dst=d.text_input('Target CRS',dst_default)
        if st.button('Transform coordinates (advanced)'):
            try:
                xx,yy=transform_coordinates(x,y,src,dst); st.success(f'Transformed X = {xx:.3f}, Y = {yy:.3f}')
            except Exception as e: st.error(str(e))
    st.caption('NOAA GEOID18 is a U.S./territory geoid service. It is not a global geoid model and is not applicable to this Nigeria training location.')
    if st.button('Query NOAA geoid service'):
        lat=float(project['latitude']); lon=float(project['longitude'])
        if not (24.0 <= lat <= 58.0 and -130.0 <= lon <= -60.0):
            st.warning('NOAA GEOID18 does not cover this location. No external geoid value was stored.')
        else:
            try:
                g=noaa_geoid_height(lat,lon); project['reference_data']['geoid_height_m']=g['geoidHeight']; project['reference_data']['geoid_model']=g.get('geoidModel'); save(); st.success(f"Geoid height: {g['geoidHeight']:.3f} m")
            except Exception as e: st.error(f'Geoid query failed: {e}')

# Anti collision
elif page=='Anti-Collision':
    page_header('Anti-Collision Screening', 'DIRECTIONAL', 'Compare the current well trajectory with stored offset trajectories using stationwise covariance-based position uncertainty.')
    main=pd.DataFrame(project.get('surveys',[]))
    offsets=project.get('offsets',[])
    valid_main=bool({'MD','Inc','Azi'}.issubset(main.columns)) and len(main)>=2
    params=project.setdefault('survey_metadata',{}).setdefault('survey_error_parameters', {'sigma_md_ft':0.5,'sigma_inc_deg':0.10,'sigma_azi_deg':0.25,'sigma_inc_systematic_deg':0.10,'sigma_azi_systematic_deg':0.25,'sigma_surface_ft':5.0})
    st.markdown('### Survey uncertainty model')
    st.info('Covariance-based engineering-development screening. The model propagates illustrative MD, inclination and azimuth measurement errors into a 3D position covariance at each survey station. It is **not** an ISCWSA-certified error model.')
    a,b,c=st.columns(3)
    sigma_md_ft=a.number_input('Random MD σ (ft)',0.0,100.0,float(params.get('sigma_md_ft',0.5)),step=0.1,help='Illustrative independent MD standard deviation at each station.')
    sigma_inc_deg=b.number_input('Random inclination σ (°)',0.0,5.0,float(params.get('sigma_inc_deg',0.10)),step=0.01,help='Illustrative independent inclination standard deviation at each station.')
    sigma_azi_deg=c.number_input('Random azimuth σ (°)',0.0,10.0,float(params.get('sigma_azi_deg',0.25)),step=0.05,help='Illustrative independent azimuth standard deviation at each station.')
    a,b,c=st.columns(3)
    sigma_inc_sys=a.number_input('Systematic inclination σ (°)',0.0,5.0,float(params.get('sigma_inc_systematic_deg',0.10)),step=0.01,help='Illustrative correlated inclination bias applied coherently along the trajectory.')
    sigma_azi_sys=b.number_input('Systematic azimuth σ (°)',0.0,10.0,float(params.get('sigma_azi_systematic_deg',0.25)),step=0.05,help='Illustrative correlated azimuth bias applied coherently along the trajectory.')
    sigma_surface_ft=c.number_input('Surface position σ (ft)',0.0,100.0,float(params.get('sigma_surface_ft',5.0)),step=0.5,help='Illustrative 1-sigma surface-position uncertainty. A production workflow should derive this from the wellhead positioning/reference survey.')
    if sigma_surface_ft <= 0.0:
        st.warning('Surface position σ is 0 ft. If the closest approach occurs at MD = 0, propagated relative uncertainty will be zero and the result must remain REVIEW. Enter a non-zero value only when justified by the wellhead positioning uncertainty.')
    params.update({'sigma_md_ft':sigma_md_ft,'sigma_inc_deg':sigma_inc_deg,'sigma_azi_deg':sigma_azi_deg,'sigma_inc_systematic_deg':sigma_inc_sys,'sigma_azi_systematic_deg':sigma_azi_sys,'sigma_surface_ft':sigma_surface_ft})
    st.caption('The model combines independent station errors with correlated systematic inclination/azimuth biases and a surface-position covariance. It produces stationwise 3D covariance/uncertainty ellipses, but remains an engineering-development model rather than an ISCWSA error model.')
    st.markdown('### Screening readiness')
    checks=[
        {'Item':'Main trajectory','Status':'PASS' if valid_main else 'FAIL','Detail':f'{len(main)} stored stations' if valid_main else 'Need at least two valid survey stations.'},
        {'Item':'Offset wells','Status':'PASS' if offsets else 'WARN','Detail':f'{len(offsets)} offset well(s) stored.'},
        {'Item':'Project CRS','Status':'PASS' if project.get('crs') else 'FAIL','Detail':project.get('crs') or 'Missing project CRS.'},
        {'Item':'Uncertainty model','Status':'PASS' if max(sigma_md_ft,sigma_inc_deg,sigma_azi_deg,sigma_inc_sys,sigma_azi_sys,sigma_surface_ft)>0 else 'FAIL','Detail':f'Random: MD {sigma_md_ft:.2f} ft • Inc {sigma_inc_deg:.2f}° • Azi {sigma_azi_deg:.2f}°; systematic: Inc {sigma_inc_sys:.2f}° • Azi {sigma_azi_sys:.2f}°; surface {sigma_surface_ft:.1f} ft'},
    ]
    st.dataframe(pd.DataFrame(checks),use_container_width=True,hide_index=True)
    if st.button('Run covariance clearance scan',type='primary'):
        if not valid_main: st.error('No valid main-well trajectory is available. Calculate a trajectory in Survey Manager or Trajectory Planner first.')
        elif not offsets: st.warning('No offset wells are stored. Create/import offset trajectories before running anti-collision.')
        elif max(sigma_md_ft,sigma_inc_deg,sigma_azi_deg,sigma_inc_sys,sigma_azi_sys,sigma_surface_ft)<=0: st.error('At least one non-zero survey uncertainty parameter is required.')
        else:
            try:
                rep=clearance_report(main,offsets,
                    survey_error_model={'sigma_md_ft':sigma_md_ft,'sigma_inc_deg':sigma_inc_deg,'sigma_azi_deg':sigma_azi_deg,'sigma_inc_systematic_deg':sigma_inc_sys,'sigma_azi_systematic_deg':sigma_azi_sys,'sigma_surface_ft':sigma_surface_ft},
                    main_surface_easting_m=float(project.get('surface_easting_m',0.0) or 0.0),
                    main_surface_northing_m=float(project.get('surface_northing_m',0.0) or 0.0))
                if rep.empty: st.warning('No valid offset comparisons were produced. Check offset survey structure and project coordinates.')
                else:
                    disp=rep.copy()
                    for col in ['main_md_m','offset_md_m','separation_m','horizontal_separation_m','vertical_separation_m','directional_uncertainty_m']:
                        if col in disp: disp[col.replace('_m','_ft')]=disp[col]*M_TO_FT; disp.drop(columns=[col],inplace=True)
                    disp=disp.rename(columns={'main_md_ft':'Main MD (ft)','offset_md_ft':'Offset MD (ft)','separation_ft':'Min separation (ft)','horizontal_separation_ft':'Horizontal separation (ft)','vertical_separation_ft':'Vertical separation (ft)','directional_uncertainty_ft':'Directional 1σ uncertainty (ft)','separation_factor':'Separation factor','status':'Status','offset':'Offset well'})
                    st.dataframe(disp,use_container_width=True,hide_index=True)
                    review_statuses={'ALERT','WARNING','REVIEW','NOT CHECKED'}
                    alerts=disp[disp['Status'].isin(review_statuses)]
                    passed=int((disp['Status']=='PASS').sum())
                    incomplete=int(disp['Status'].isin(['REVIEW','NOT CHECKED']).sum())
                    if incomplete:
                        st.error(f'Screening incomplete: {passed} comparison(s) passed; {incomplete} comparison(s) have missing/invalid uncertainty or trajectory data and require review.')
                    elif len(alerts):
                        st.warning(f'{passed} comparison(s) passed; {len(alerts)} comparison(s) are WARNING/ALERT and require review.')
                    else:
                        st.success(f'All {passed} valid offset comparisons meet the illustrative covariance screening threshold. This is not operational clearance.')
                    st.caption('Screening only. Production anti-collision requires a validated ISCWSA error model, covariance propagation and company-approved separation rules.')
            except Exception as e: st.error(f'Covariance clearance scan failed: {e}')

# Casing
elif page=='Casing Design':
    page_header('Casing Design & Well Integrity Screening', 'DRILLING ENGINEERING', 'Review the stored casing architecture and run transparent burst, collapse and tension screening against the selected string.')
    pgr=project.get('casing_program',[])
    if pgr:
        st.markdown('### Stored architecture'); st.dataframe(pd.DataFrame(pgr),use_container_width=True,hide_index=True)
        idx=st.selectbox('Casing string',range(len(pgr)),format_func=lambda i:f"{pgr[i].get('string_no')} • {pgr[i].get('type')} • {float(pgr[i].get('casing_od_in') or 0):g} in")
        r=pgr[idx]
    else:
        st.warning('Build the final casing program in Well Architecture first.'); r={}
    st.markdown('### Design screen')
    a,b,c,d,e,f=st.columns(6); od=a.number_input('OD (in)',2.,30.,float(r.get('casing_od_in') or 9.625)); wt=b.number_input('Weight (lb/ft)',5.,300.,float(r.get('weight_lbft') or 47)); grade=c.number_input('Yield strength (psi)',10000.,250000.,80000.); shoe=d.number_input('Shoe MD (ft)',0.,20000.,float(r.get('shoe_md_m') or 2750)*M_TO_FT); mw=e.number_input('Mud weight (ppg)',5.,20.,10.); pore=f.number_input('Pore gradient (psi/ft)',.1,1.5,.5); frac=st.number_input('Fracture gradient (psi/ft)',.1,2.,.65)
    if pgr and st.button('Use stored string assumptions'):
        st.info('The selected architecture string is the authoritative geometry for this screen; edit assumptions only where a design scenario requires it.')
    if st.button('Run casing design screen',type='primary'):
        rcalc=casing_design_checks(od,wt,grade,shoe*FT_TO_M,mw,pore,frac); st.dataframe(pd.DataFrame([rcalc]),use_container_width=True,hide_index=True)
        st.caption('Screening only. Final casing design requires certified tubular properties, connection ratings, applicable API/ISO criteria, temperature effects and company design factors.')

# Hydraulics
elif page=='Hydraulics & ECD':
    page_header('Hydraulics & ECD', 'DRILLING ENGINEERING', 'Screen hydraulics, pressure loss and equivalent circulating density using the selected simplified rheology model.'); a,b,c,d=st.columns(4); q=a.number_input('Flow rate (gpm)',10.,3000.,500.); hole=b.number_input('Hole ID (in)',2.,30.,8.5); pipe=c.number_input('Pipe OD (in)',1.,20.,5.); mw=d.number_input('Mud weight (ppg)',5.,20.,10.); a,b,c=st.columns(3); tvd=a.number_input('TVD (ft)',100.,50000.,10000.); loss=b.number_input('Annular pressure loss (psi)',0.,20000.,400.); rheo=c.selectbox('Rheology model',['Bingham Plastic','Power Law','Herschel-Bulkley']); pv=st.number_input('PV (cP)',0.,500.,20.); yp=st.number_input('YP / n proxy',0.,200.,10.)
    if st.button('Run hydraulics screen',type='primary'):
        r=hydraulic_screen(q,hole,pipe,mw,tvd,loss,pv,yp); st.dataframe(pd.DataFrame([r]),use_container_width=True,hide_index=True); st.json(rheo_summary(rheo,pv,yp,q))

# PP/FG
elif page=='PP / FG & Mud Window':
    page_header('Pore Pressure / Fracture Gradient & Mud Window', 'DRILLING ENGINEERING', 'Integrate PP/FG assumptions into a transparent mud-window screening calculation.')
    st.caption('Practice workflow for integrating formation pressure assumptions with mud-weight and casing-shoe planning. These are screening calculations; actual PP/FG should come from approved geological/geomechanical workflows and field data.')
    a,b,c,d=st.columns(4); tvd=a.number_input('TVD (ft)',100.,50000.,10000.); mw=b.number_input('Mud weight (ppg)',5.,20.,10.); pp=c.number_input('Pore pressure gradient (psi/ft)',.1,1.5,.5); fg=d.number_input('Fracture gradient (psi/ft)',.1,2.,.65)
    margin=st.number_input('Design margin (ppg)',0.,2.,0.)
    if st.button('Calculate pressure window',type='primary'):
        r=pressure_window(tvd,mw,pp,fg,margin); st.dataframe(pd.DataFrame([r]),use_container_width=True,hide_index=True)
        if r['status']=='PASS': st.success('Screening mud window is positive.')
        else: st.error('Screening mud window is closed or negative.')

# T&D
elif page=='Torque & Drag':
    page_header('Torque & Drag Screening', 'DRILLING ENGINEERING', 'Run the current soft-string screening calculation using the selected friction, buoyancy and drillstring assumptions.'); s=project.get('surveys',[]); depth=float(s[-1]['MD']) if s else 4000.; inc=float(s[-1]['Inc']) if s else 0.; dls=float(s[-1].get('DLS',0)) if s else 0.; dls_interval_m=float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0) or 30.0); dls=dls_for_interval_to_100ft(dls,dls_interval_m) if s else dls; dls=dls_100ft_to_30m(dls); a,b,c,d=st.columns(4); depth_ft=a.number_input('Depth (ft)',0.,98425.,depth*M_TO_FT); depth=depth_ft*FT_TO_M; ff=b.number_input('Friction factor',0.,1.,.25); bf=c.number_input('Buoyancy factor',0.,1.2,.82); wt=d.number_input('String weight (lb/ft)',1.,300.,19.5)
    if st.button('Run T&D screen',type='primary'): st.dataframe(pd.DataFrame([torque_drag_screen(depth,ff,bf,wt,inc,dls)]),use_container_width=True,hide_index=True)

# Cement
elif page=='Cementing':
    page_header('Cementing Screening', 'DRILLING ENGINEERING', 'Estimate annular cement volume and slurry sacks using an explicit top-of-cement and casing-shoe interval.')
    p=project.get('casing_program',[]); idx=st.selectbox('Casing string',range(len(p)),format_func=lambda i:f"{p[i].get('string_no')} • {p[i].get('type')}") if p else None; r=p[idx] if idx is not None else {}
    a,b,c,d=st.columns(4); hole=a.number_input('Hole diameter (in)',2.,30.,float(r.get('hole_size_in') or 12.25)); od=b.number_input('Casing OD (in)',2.,30.,float(r.get('casing_od_in') or 9.625)); shoe_ft=c.number_input('Casing shoe MD (ft)',0.,65617.,float(r.get('shoe_md_m') or 1000)*M_TO_FT); toc_ft=d.number_input('Top of cement MD (ft)',0.,65617.,float(r.get('top_md_m') or 0)*M_TO_FT)
    a,b=st.columns(2); excess=a.number_input('Excess (%)',0.,100.,20.); yieldv=b.number_input('Slurry yield (bbl/sack)',.1,5.,1.18)
    if toc_ft>=shoe_ft: st.error('Top of cement must be shallower than the casing shoe.')
    length_ft=max(0.0,shoe_ft-toc_ft); st.metric('Cemented interval',f'{length_ft:,.1f} ft')
    if st.button('Calculate cement screen',type='primary') and toc_ft<shoe_ft:
        length=length_ft*FT_TO_M; rcalc=cement_screen(hole,od,length,excess,yieldv); rcalc.update({'shoe_md_ft':shoe_ft,'top_of_cement_md_ft':toc_ft,'cement_length_ft':length_ft}); st.dataframe(pd.DataFrame([rcalc]),use_container_width=True,hide_index=True)
        st.caption('Screening volume only; final cement design requires slurry properties, centralization, displacement, losses, contamination, temperature/pressure and approved cementing procedures.')

# Well control
elif page=='Well Control':
    page_header('Well Control Screening', 'DRILLING ENGINEERING', 'Review basic kick/kill screening quantities and their relationship to formation pressure and MAASP.')
    a,b,c,d=st.columns(4); sid=a.number_input('SIDPP (psi)',0.,10000.,500.); sicp=b.number_input('SICP (psi)',0.,10000.,500.); tvd=c.number_input('TVD (ft)',100.,50000.,10000.); mw=d.number_input('Current MW (ppg)',5.,20.,10.)
    a,b=st.columns(2); maasp=a.number_input('Allowable surface pressure (psi)',0.,20000.,1500.); fg=b.number_input('Fracture gradient (psi/ft)',0.,2.,.65)
    if st.button('Run well-control screen',type='primary'):
        r=well_control_screen(sid,tvd,mw,maasp,fg); r['SICP_psi']=sicp; r['SIDPP_SICP_difference_psi']=sid-sicp; st.dataframe(pd.DataFrame([r]),use_container_width=True,hide_index=True)
        st.info('SIDPP is used for the basic kill-MW estimate in this screening engine. SICP is displayed for comparison; operational kill calculations must follow approved company procedures and kill sheets.')

# BHA
elif page=='BHA & Drilling':
    page_header('BHA & Drilling Configuration', 'DRILLING ENGINEERING', 'Document the bit, motor/RSS, MWD/LWD, collars, HWDP and drillpipe configuration associated with the plan.')
    df=pd.DataFrame(project.get('bha',[]));
    if df.empty: df=pd.DataFrame([{'component':'Bit','type':'PDC','OD_in':8.5,'length_m':0.3,'weight_lbft':0,'role':'Drill'}])
    bha_display=df.copy();
    if 'length_m' in bha_display.columns: bha_display['length_ft']=bha_display['length_m']*M_TO_FT; bha_display.drop(columns=['length_m'],inplace=True)
    ed=st.data_editor(bha_display,num_rows='dynamic',use_container_width=True,hide_index=True,key='bha');
    if st.button('Save BHA'):
        bha_save=ed.copy();
        if 'length_ft' in bha_save.columns: bha_save['length_m']=bha_save['length_ft']*FT_TO_M; bha_save.drop(columns=['length_ft'],inplace=True)
        project['bha']=bha_save.to_dict('records'); save(); st.success('BHA saved.')
    st.info('Use this section to document bit, motor/RSS, MWD/LWD, collars, HWDP and drillpipe configuration. Mechanical design remains an engineering-development workflow.')

# Visualization
elif page=='Visualization':
    page_header('Integrated Well Visualization', 'OUTPUTS', 'Professional plan, vertical-section, 3D and wall-plot views using a well-relative project frame. Targets, offsets and covariance uncertainty are explicitly plotted and included in the wall-plot export.')
    main=pd.DataFrame(project.get('surveys',[]))
    required_cols={'Easting','Northing','TVD','MD'}

    def _surface_xy(obj=None):
        obj=obj or project
        return float(obj.get('surface_easting_m',0.0) or 0.0), float(obj.get('surface_northing_m',0.0) or 0.0)

    def _target_relative(t):
        main_e,main_n=_surface_xy()
        rt=dict(t)
        rt['north_m']=float(t.get('north_m',0.0) or 0.0)-main_n
        rt['east_m']=float(t.get('east_m',0.0) or 0.0)-main_e
        return rt

    def _trajectory_relative(df, surface_e=None, surface_n=None):
        out=pd.DataFrame(df).copy()
        if out.empty:
            return out
        # Offset surveys are commonly stored as MD/Inc/Azi only. Derive their
        # local coordinates before translating them into the common project frame.
        if not {'Easting','Northing','TVD'}.issubset(out.columns):
            if {'MD','Inc','Azi'}.issubset(out.columns):
                try:
                    interval=float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0) or 30.0)
                    out=minimum_curvature(out, dls_interval=interval)
                except (ValueError, TypeError, KeyError):
                    return out
            else:
                return out
        main_e,main_n=_surface_xy()
        se=main_e if surface_e is None else float(surface_e)
        sn=main_n if surface_n is None else float(surface_n)
        # Survey coordinates are well-relative. Add the well surface position for
        # offsets, then subtract the main-well surface position to obtain a common
        # local plotting frame with WN-01 wellhead at (0,0).
        out['E_rel_m']=pd.to_numeric(out['Easting'],errors='coerce')+se-main_e
        out['N_rel_m']=pd.to_numeric(out['Northing'],errors='coerce')+sn-main_n
        return out

    def _vs_project(n_m,e_m,az_deg):
        a=math.radians(float(az_deg))
        return float(n_m)*math.cos(a)+float(e_m)*math.sin(a), float(e_m)*math.cos(a)-float(n_m)*math.sin(a)

    def _target_tvd(t):
        # Stored target TVDSS is relative to MSL; KB elevation is the positive
        # KB-to-MSL datum used by the project.
        return float(project.get('kb_m',0.0) or 0.0)-float(t.get('tvdss_m',0.0) or 0.0)

    def _uncertainty_df():
        try:
            params=project.get('survey_metadata',{}).get('survey_error_parameters',{})
            cov=station_covariances(main[['MD','Inc','Azi']].copy(),**params)
            return cov
        except Exception as ex:
            st.warning(f'Uncertainty ellipses could not be generated: {ex}')
            return pd.DataFrame()

    def _add_uncertainty_plan(fig, cov, row=None, col=None, showlegend=True):
        if cov.empty: return
        # Plot a modest number of station ellipses so the uncertainty remains
        # readable. Coordinates are in the same local frame as the main well.
        idxs=np.unique(np.linspace(0,len(main)-1,min(8,len(main)),dtype=int))
        theta=np.linspace(0,2*np.pi,96)
        for k,idx in enumerate(idxs):
            r=cov.iloc[int(idx)]
            maj=float(r.get('Unc_major_1sigma_m',0.0)); minor=float(r.get('Unc_minor_1sigma_m',0.0))
            if maj<=0 or minor<=0: continue
            alpha=math.radians(float(r.get('Unc_azimuth_deg',0.0)))
            dn=maj*np.cos(theta)*math.cos(alpha)-minor*np.sin(theta)*math.sin(alpha)
            de=maj*np.cos(theta)*math.sin(alpha)+minor*np.sin(theta)*math.cos(alpha)
            x=(float(main.iloc[int(idx)]['Easting'])+de)*M_TO_FT
            y=(float(main.iloc[int(idx)]['Northing'])+dn)*M_TO_FT
            trace=go.Scatter(x=x,y=y,mode='lines',name='1σ positional uncertainty',legendgroup='uncertainty',showlegend=(showlegend and k==0),line=dict(dash='dot',width=1.5),hoverinfo='skip')
            if row is None: fig.add_trace(trace)
            else: fig.add_trace(trace,row=row,col=col)

    def _add_target_plan(fig,t,row=None,col=None):
        rt=_target_relative(t); n,e=target_boundary(rt); nm=t.get('name','Target')
        boundary=go.Scatter(x=np.asarray(e)*M_TO_FT,y=np.asarray(n)*M_TO_FT,mode='lines',name=nm,legendgroup=f'target-{nm}',line=dict(dash='dash',width=2),hovertemplate=f'{nm}<extra></extra>')
        center=go.Scatter(x=[float(rt.get('east_m',0))*M_TO_FT],y=[float(rt.get('north_m',0))*M_TO_FT],mode='markers+text',text=[nm],textposition='top center',name=f'{nm} center',legendgroup=f'target-{nm}',showlegend=False,marker=dict(size=10,symbol='diamond'),hovertemplate=f'{nm} center<extra></extra>')
        if row is None:
            fig.add_trace(boundary); fig.add_trace(center)
        else:
            fig.add_trace(boundary,row=row,col=col); fig.add_trace(center,row=row,col=col)

    def _add_offset_plan(fig,off,row=None,col=None):
        nm=off.get('name','Offset')
        od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
        if {'E_rel_m','N_rel_m'}.issubset(od.columns) and len(od):
            line=go.Scatter(x=od['E_rel_m']*M_TO_FT,y=od['N_rel_m']*M_TO_FT,mode='lines',name=nm,legendgroup=f'offset-{nm}',line=dict(width=2),hovertemplate=f'{nm}<extra></extra>')
            sx=float(od.iloc[0]['E_rel_m'])*M_TO_FT; sy=float(od.iloc[0]['N_rel_m'])*M_TO_FT
        else:
            # Surface location remains useful even when the subsurface survey is missing.
            main_e,main_n=_surface_xy()
            sx=(float(off.get('surface_easting_m',main_e) or main_e)-main_e)*M_TO_FT
            sy=(float(off.get('surface_northing_m',main_n) or main_n)-main_n)*M_TO_FT
            line=None
        surf=go.Scatter(x=[sx],y=[sy],mode='markers+text',text=[nm],textposition='bottom center',name=f'{nm} surface',legendgroup=f'offset-{nm}',showlegend=(line is None),marker=dict(size=10,symbol='circle-open'),hovertemplate=f'{nm} surface<extra></extra>')
        if row is None:
            if line is not None: fig.add_trace(line)
            fig.add_trace(surf)
        else:
            if line is not None: fig.add_trace(line,row=row,col=col)
            fig.add_trace(surf,row=row,col=col)

    def _plan_bounds():
        xs=[]; ys=[]
        mr=_trajectory_relative(main)
        xs.extend((mr['E_rel_m']*M_TO_FT).tolist()); ys.extend((mr['N_rel_m']*M_TO_FT).tolist())
        for off in project.get('offsets',[]):
            od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
            if {'E_rel_m','N_rel_m'}.issubset(od.columns):
                xs.extend((od['E_rel_m']*M_TO_FT).tolist()); ys.extend((od['N_rel_m']*M_TO_FT).tolist())
        for t in project.get('targets',[]):
            rt=_target_relative(t); n,e=target_boundary(rt)
            xs.extend((np.asarray(e)*M_TO_FT).tolist()); ys.extend((np.asarray(n)*M_TO_FT).tolist())
        cov=_uncertainty_df() if len(main)>=2 else pd.DataFrame()
        if not cov.empty:
            for idx in np.unique(np.linspace(0,len(main)-1,min(8,len(main)),dtype=int)):
                r=cov.iloc[int(idx)]; pad=float(r.get('Unc_major_1sigma_m',0))*M_TO_FT
                ex=float(main.iloc[int(idx)]['Easting'])*M_TO_FT; ny=float(main.iloc[int(idx)]['Northing'])*M_TO_FT
                xs += [ex-pad,ex+pad]; ys += [ny-pad,ny+pad]
        if not xs: return (-100,100,-100,100)
        xmin,xmax=min(xs),max(xs); ymin,ymax=min(ys),max(ys)
        span=max(xmax-xmin,ymax-ymin,100.0); pad=max(50.0,span*0.08)
        return xmin-pad,xmax+pad,ymin-pad,ymax+pad

    if main.empty or not required_cols.issubset(main.columns):
        st.info('No calculated trajectory is available yet. Import surveys or create and calculate a trajectory in **Survey Manager** / **Trajectory Planner**.')
    else:
        targets=project.get('targets',[])
        target_options=[t for t in targets if t.get('name')]
        selected_target=None
        if target_options:
            target_idx=st.selectbox('Vertical-section target',range(len(target_options)),format_func=lambda i:target_options[i].get('name','Target'))
            selected_target=target_options[target_idx]

        target_az=None
        if selected_target is not None:
            rt=_target_relative(selected_target)
            if abs(float(rt.get('north_m',0)))+abs(float(rt.get('east_m',0)))>1e-9:
                target_az=math.degrees(math.atan2(float(rt['east_m']),float(rt['north_m'])))%360.0
            else: target_az=0.0
        planner_az=None
        try: planner_az=float(project.get('trajectory_metadata',{}).get('planner_result',{}).get('planning_azimuth_deg'))
        except Exception: planner_az=None
        if planner_az is None and 'Azi' in main.columns: planner_az=float(main.iloc[-1]['Azi'])
        source_options=[]
        if target_az is not None: source_options.append('Target azimuth')
        if planner_az is not None: source_options.append('Planning/final well azimuth')
        source_options.append('Custom')
        source=st.selectbox('Vertical-section azimuth source',source_options)
        if source=='Target azimuth': vs_az=float(target_az)
        elif source=='Planning/final well azimuth': vs_az=float(planner_az)
        else: vs_az=st.number_input('Vertical-section azimuth (° Grid)',0.0,360.0,float(target_az if target_az is not None else (planner_az or 0.0)),step=0.1)
        st.caption(f'Vertical-section azimuth: **{vs_az:.2f}° Grid** • All horizontal plots use WN-01 wellhead = (0, 0) ft.')

        view=st.selectbox('View',['Plan','Vertical Section','3D','Wall Plot'])
        show_unc=st.checkbox('Show covariance uncertainty',True)
        show_targets=st.checkbox('Show targets',True)
        show_offsets=st.checkbox('Show offsets',True)
        if project.get('offsets'):
            offset_diag=[]
            for off in project.get('offsets',[]):
                od_diag=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
                valid_xy={'E_rel_m','N_rel_m'}.issubset(od_diag.columns) and len(od_diag)>0
                valid_path=valid_xy and {'TVD','MD'}.issubset(od_diag.columns) and len(od_diag)>1
                offset_diag.append({'Offset':off.get('name','Offset'),'Survey stations':len(off.get('surveys',[])),
                    'Surface plotted':'Yes' if valid_xy or off.get('surface_easting_m') is not None else 'No',
                    'Subsurface path':'Ready' if valid_path else 'Needs survey stations',
                    'CRS':off.get('crs',project.get('crs','—'))})
            with st.expander('Offset plotting diagnostics', expanded=False):
                st.dataframe(pd.DataFrame(offset_diag), use_container_width=True, hide_index=True)
                st.caption('Offsets with only a surface location are shown as markers. Import at least two ordered survey stations to display their subsurface trajectories.')
        cov=_uncertainty_df()
        if show_unc and cov.empty:
            st.warning('Survey uncertainty ellipses are unavailable. Check that MD, Inc and Azi are present and that uncertainty parameters are valid.')
        plot_template='plotly_dark' if st.session_state.get('workspace_theme')=='Dark' else 'plotly_white'
        mr=_trajectory_relative(main)
        main_vs=np.array([_vs_project(n,e,vs_az)[0] for n,e in zip(mr['N_rel_m'],mr['E_rel_m'])])*M_TO_FT
        main_tvd_ft=pd.to_numeric(main['TVD'],errors='coerce')*M_TO_FT
        fig=go.Figure()

        if view=='Plan':
            fig.add_trace(go.Scatter(x=mr['E_rel_m']*M_TO_FT,y=mr['N_rel_m']*M_TO_FT,mode='lines+markers',name=project['well_name'],line=dict(width=3),marker=dict(size=4)))
            if show_offsets:
                for off in project.get('offsets',[]): _add_offset_plan(fig,off)
            if show_targets:
                for t in targets: _add_target_plan(fig,t)
            if show_unc: _add_uncertainty_plan(fig,cov)
            xmin,xmax,ymin,ymax=_plan_bounds()
            fig.update_xaxes(title_text='Relative Easting (ft)',range=[xmin,xmax],zeroline=True,showgrid=True)
            fig.update_yaxes(title_text='Relative Northing (ft)',range=[ymin,ymax],zeroline=True,showgrid=True,scaleanchor='x',scaleratio=1)
            fig.update_layout(height=700,title=f"{project['well_name']} — Plan View",margin=dict(l=60,r=30,t=70,b=60),legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='left',x=0),template=plot_template)

        elif view=='Vertical Section':
            fig.add_trace(go.Scatter(x=main_vs,y=main_tvd_ft,mode='lines+markers',name=project['well_name'],line=dict(width=3),marker=dict(size=4)))
            vs_x=[]; vs_y=[]
            vs_x.extend(main_vs.tolist()); vs_y.extend((main['TVD']*M_TO_FT).tolist())
            if show_offsets:
                for off in project.get('offsets',[]):
                    od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
                    if {'N_rel_m','E_rel_m','TVD'}.issubset(od.columns) and len(od):
                        ovs=np.array([_vs_project(n,e,vs_az)[0] for n,e in zip(od['N_rel_m'],od['E_rel_m'])])*M_TO_FT
                        fig.add_trace(go.Scatter(x=ovs,y=od['TVD']*M_TO_FT,mode='lines+markers',name=off.get('name','Offset'),line=dict(width=1.5)))
                        vs_x.extend(ovs.tolist()); vs_y.extend((od['TVD']*M_TO_FT).tolist())
                    else:
                        main_e,main_n=_surface_xy(); on=float(off.get('surface_northing_m',main_n) or main_n)-main_n; oe=float(off.get('surface_easting_m',main_e) or main_e)-main_e
                        surf_vs=_vs_project(on,oe,vs_az)[0]*M_TO_FT
                        fig.add_trace(go.Scatter(x=[surf_vs],y=[0],mode='markers+text',text=[off.get('name','Offset')],textposition='top center',name=f"{off.get('name','Offset')} surface",marker=dict(size=9,symbol='circle-open')))
                        vs_x.append(surf_vs); vs_y.append(0.0)
            if show_targets:
                for t in targets:
                    rt=_target_relative(t); n,e=target_boundary(rt); tx=np.array([_vs_project(nn,ee,vs_az)[0] for nn,ee in zip(n,e)])*M_TO_FT; ty=np.full(len(tx),_target_tvd(t)*M_TO_FT)
                    nm=t.get('name','Target'); fig.add_trace(go.Scatter(x=tx,y=ty,mode='lines+markers',name=nm,line=dict(dash='dash',width=2))); fig.add_trace(go.Scatter(x=[float(np.mean(tx))],y=[float(ty[0])],mode='markers+text',text=[nm],textposition='top center',name=f'{nm} center',showlegend=False,marker=dict(size=9,symbol='diamond')))
                    vs_x.extend(tx.tolist()); vs_y.extend(ty.tolist())
            xmin,xmax=(min(vs_x),max(vs_x)) if vs_x else (-100,100); ymin,ymax=(min(vs_y),max(vs_y)) if vs_y else (0,100)
            spanx=max(xmax-xmin,100.0); spany=max(ymax-ymin,100.0); px=max(50,0.08*spanx); py=max(50,0.05*spany)
            fig.update_xaxes(title_text=f'Vertical Section @ {vs_az:.2f}° Grid (ft)',range=[xmin-px,xmax+px])
            fig.update_yaxes(title_text='TVD (ft)',range=[ymax+py,ymin-py])
            fig.update_layout(height=700,title=f"{project['well_name']} — Vertical Section",margin=dict(l=60,r=30,t=70,b=60),legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='left',x=0),template=plot_template)

        elif view=='3D':
            fig=go.Figure()
            fig.add_trace(go.Scatter3d(x=mr['E_rel_m']*M_TO_FT,y=mr['N_rel_m']*M_TO_FT,z=-main['TVD']*M_TO_FT,mode='lines+markers',name=project['well_name'],line=dict(width=6),marker=dict(size=2)))
            if show_offsets:
                for off in project.get('offsets',[]):
                    od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
                    if {'E_rel_m','N_rel_m','TVD'}.issubset(od.columns) and len(od):
                        fig.add_trace(go.Scatter3d(x=od['E_rel_m']*M_TO_FT,y=od['N_rel_m']*M_TO_FT,z=-od['TVD']*M_TO_FT,mode='lines+markers',name=off.get('name','Offset'),line=dict(width=3)))
                    else:
                        main_e,main_n=_surface_xy(); ox=(float(off.get('surface_easting_m',main_e) or main_e)-main_e)*M_TO_FT; oy=(float(off.get('surface_northing_m',main_n) or main_n)-main_n)*M_TO_FT
                        fig.add_trace(go.Scatter3d(x=[ox],y=[oy],z=[0],mode='markers+text',text=[off.get('name','Offset')],name=f"{off.get('name','Offset')} surface",marker=dict(size=5,symbol='circle-open')))
            if show_targets:
                for t in targets:
                    rt=_target_relative(t); n,e=target_boundary(rt); tvd=_target_tvd(t); nm=t.get('name','Target')
                    fig.add_trace(go.Scatter3d(x=np.asarray(e)*M_TO_FT,y=np.asarray(n)*M_TO_FT,z=np.full(len(e),-tvd*M_TO_FT),mode='lines+markers',name=nm,line=dict(dash='dash',width=4),marker=dict(size=3)))
            xmin,xmax,ymin,ymax=_plan_bounds(); fig.update_layout(height=750,title=f"{project['well_name']} — 3D",scene=dict(xaxis=dict(title='Relative Easting (ft)',range=[xmin,xmax]),yaxis=dict(title='Relative Northing (ft)',range=[ymin,ymax]),zaxis=dict(title='TVD (ft)')),margin=dict(l=10,r=10,t=60,b=10),template=plot_template)

        else:  # Wall Plot
            wall=make_subplots(rows=1,cols=2,subplot_titles=('Plan View','Vertical Section'),horizontal_spacing=0.10)
            wall.add_trace(go.Scatter(x=mr['E_rel_m']*M_TO_FT,y=mr['N_rel_m']*M_TO_FT,mode='lines+markers',name=project['well_name'],legendgroup='main',line=dict(width=3),marker=dict(size=3)),row=1,col=1)
            wall.add_trace(go.Scatter(x=main_vs,y=main_tvd_ft,mode='lines+markers',name=project['well_name'],legendgroup='main',showlegend=False,line=dict(width=3),marker=dict(size=3)),row=1,col=2)
            if show_offsets:
                for off in project.get('offsets',[]):
                    _add_offset_plan(wall,off,row=1,col=1)
                    od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
                    if {'N_rel_m','E_rel_m','TVD'}.issubset(od.columns):
                        ovs=np.array([_vs_project(n,e,vs_az)[0] for n,e in zip(od['N_rel_m'],od['E_rel_m'])])*M_TO_FT
                        wall.add_trace(go.Scatter(x=ovs,y=od['TVD']*M_TO_FT,mode='lines+markers',name=off.get('name','Offset'),legendgroup=f"offset-{off.get('name','Offset')}",showlegend=False,line=dict(width=1.5)),row=1,col=2)
                    else:
                        main_e,main_n=_surface_xy(); on=float(off.get('surface_northing_m',main_n) or main_n)-main_n; oe=float(off.get('surface_easting_m',main_e) or main_e)-main_e
                        surf_vs=_vs_project(on,oe,vs_az)[0]*M_TO_FT
                        wall.add_trace(go.Scatter(x=[surf_vs],y=[0],mode='markers+text',text=[off.get('name','Offset')],textposition='top center',name=f"{off.get('name','Offset')} surface",showlegend=False,marker=dict(size=8,symbol='circle-open')),row=1,col=2)
            if show_targets:
                for t in targets:
                    _add_target_plan(wall,t,row=1,col=1)
                    rt=_target_relative(t); n,e=target_boundary(rt); tx=np.array([_vs_project(nn,ee,vs_az)[0] for nn,ee in zip(n,e)])*M_TO_FT; ty=np.full(len(tx),_target_tvd(t)*M_TO_FT); nm=t.get('name','Target')
                    wall.add_trace(go.Scatter(x=tx,y=ty,mode='lines+markers',name=nm,legendgroup=f'target-{nm}',showlegend=False,line=dict(dash='dash',width=2)),row=1,col=2)
            if show_unc: _add_uncertainty_plan(wall,cov,row=1,col=1,showlegend=True)
            xmin,xmax,ymin,ymax=_plan_bounds()
            wall.update_xaxes(title_text='Relative Easting (ft)',range=[xmin,xmax],row=1,col=1)
            wall.update_yaxes(title_text='Relative Northing (ft)',range=[ymin,ymax],scaleanchor='x',scaleratio=1,row=1,col=1)
            allvs=main_vs.tolist(); alltvd=(main['TVD']*M_TO_FT).tolist()
            for off in project.get('offsets',[]):
                od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
                if {'N_rel_m','E_rel_m','TVD'}.issubset(od.columns):
                    allvs.extend((np.array([_vs_project(n,e,vs_az)[0] for n,e in zip(od['N_rel_m'],od['E_rel_m'])])*M_TO_FT).tolist()); alltvd.extend((od['TVD']*M_TO_FT).tolist())
            for t in targets:
                rt=_target_relative(t); n,e=target_boundary(rt); allvs.extend((np.array([_vs_project(nn,ee,vs_az)[0] for nn,ee in zip(n,e)])*M_TO_FT).tolist()); alltvd.append(_target_tvd(t)*M_TO_FT)
            vxmin,vxmax=min(allvs),max(allvs); vymin,vymax=min(alltvd),max(alltvd); vpx=max(50,0.08*(vxmax-vxmin)); vpy=max(50,0.05*(vymax-vymin))
            wall.update_xaxes(title_text=f'Vertical Section @ {vs_az:.2f}° Grid (ft)',range=[vxmin-vpx,vxmax+vpx],row=1,col=2)
            wall.update_yaxes(title_text='TVD (ft)',range=[vymax+vpy,vymin-vpy],row=1,col=2)
            wall.update_layout(height=760,title=f"{project['well_name']} — Wall Plot",margin=dict(l=50,r=30,t=90,b=85),legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='left',x=0),template=plot_template)
            wall.add_annotation(text=f"CRS: {project.get('crs','—')} | North reference: {project.get('north_reference','Grid North')} | VS azimuth: {vs_az:.2f}° Grid | Declination: {project.get('reference_data',{}).get('magnetic_declination_deg','—')}° | Convergence: {project.get('reference_data',{}).get('grid_convergence_deg','—')}° | 1σ uncertainty: {'shown' if show_unc else 'hidden'}",xref='paper',yref='paper',x=0,y=-0.13,showarrow=False,align='left')
            fig=wall

        st.plotly_chart(fig,use_container_width=True)

        st.markdown('### Export')
        metadata={
            'well':project.get('well_name'),'project':project.get('project_name'),'crs':project.get('crs'),
            'north_reference':project.get('north_reference','Grid North'),'vertical_section_azimuth_deg_grid':round(float(vs_az),6),
            'target':selected_target.get('name') if selected_target else None,
            'declination_deg':project.get('reference_data',{}).get('magnetic_declination_deg'),'grid_convergence_deg':project.get('reference_data',{}).get('grid_convergence_deg'),
            'geomagnetic_model':project.get('reference_data',{}).get('geomagnetic_model'),
            'geomagnetic_model_metadata':project.get('reference_data',{}).get('geomagnetic_model_metadata'),
            'trajectory_stations':int(len(main)),
            'offset_wells':int(len(project.get('offsets',[]))),'targets':int(len(targets)),'uncertainty_model':project.get('survey_metadata',{}).get('uncertainty_model',''),
            'uncertainty_plotted':bool(show_unc and not cov.empty),'uncertainty_available':bool(not cov.empty),
            'wall_plot_coordinate_frame':'Well-relative local grid; WN-01 wellhead = (0,0) ft','export_generated_utc':datetime.utcnow().isoformat()+'Z'
        }
        # Always export the full wall plot with all three optional engineering layers,
        # independent of the current interactive checkbox state, so the package is a
        # reproducible deliverable rather than a screenshot of the current UI state.
        # Export geometry and bounds are computed independently of the selected interactive view.
        ex_xmin,ex_xmax,ex_ymin,ex_ymax=_plan_bounds()
        ex_vs=main_vs.tolist()
        ex_tvd=(pd.to_numeric(main['TVD'],errors='coerce')*M_TO_FT).tolist()
        for off in project.get('offsets',[]):
            od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
            if {'N_rel_m','E_rel_m','TVD'}.issubset(od.columns):
                ovs=np.array([_vs_project(n,e,vs_az)[0] for n,e in zip(od['N_rel_m'],od['E_rel_m'])])*M_TO_FT
                ex_vs.extend(ovs.tolist())
                ex_tvd.extend((pd.to_numeric(od['TVD'],errors='coerce')*M_TO_FT).tolist())
        for t in targets:
            rt=_target_relative(t); n,e=target_boundary(rt)
            ex_vs.extend((np.array([_vs_project(nn,ee,vs_az)[0] for nn,ee in zip(n,e)])*M_TO_FT).tolist())
            ex_tvd.append(_target_tvd(t)*M_TO_FT)
        ex_vs=[float(v) for v in ex_vs if pd.notna(v)]
        ex_tvd=[float(v) for v in ex_tvd if pd.notna(v)]
        ex_vxmin,ex_vxmax=min(ex_vs),max(ex_vs)
        ex_vymin,ex_vymax=min(ex_tvd),max(ex_tvd)
        ex_vpx=max(50.0,0.08*(ex_vxmax-ex_vxmin))
        ex_vpy=max(50.0,0.05*(ex_vymax-ex_vymin))
        export_wall=make_subplots(rows=1,cols=2,subplot_titles=('Plan View','Vertical Section'),horizontal_spacing=0.10)
        export_wall.add_trace(go.Scatter(x=mr['E_rel_m']*M_TO_FT,y=mr['N_rel_m']*M_TO_FT,mode='lines+markers',name=project['well_name'],line=dict(width=3)),row=1,col=1)
        export_wall.add_trace(go.Scatter(x=main_vs,y=main['TVD']*M_TO_FT,mode='lines+markers',name=project['well_name'],showlegend=False,line=dict(width=3)),row=1,col=2)
        for off in project.get('offsets',[]):
            _add_offset_plan(export_wall,off,row=1,col=1)
            od=_trajectory_relative(pd.DataFrame(off.get('surveys',[])),off.get('surface_easting_m',0.0),off.get('surface_northing_m',0.0))
            if {'N_rel_m','E_rel_m','TVD'}.issubset(od.columns):
                ovs=np.array([_vs_project(n,e,vs_az)[0] for n,e in zip(od['N_rel_m'],od['E_rel_m'])])*M_TO_FT
                export_wall.add_trace(go.Scatter(x=ovs,y=od['TVD']*M_TO_FT,mode='lines+markers',name=off.get('name','Offset'),showlegend=False,line=dict(width=1.5)),row=1,col=2)
            else:
                main_e,main_n=_surface_xy(); on=float(off.get('surface_northing_m',main_n) or main_n)-main_n; oe=float(off.get('surface_easting_m',main_e) or main_e)-main_e
                surf_vs=_vs_project(on,oe,vs_az)[0]*M_TO_FT
                export_wall.add_trace(go.Scatter(x=[surf_vs],y=[0],mode='markers+text',text=[off.get('name','Offset')],name=f"{off.get('name','Offset')} surface",showlegend=False,marker=dict(size=8,symbol='circle-open')),row=1,col=2)
        for t in targets:
            _add_target_plan(export_wall,t,row=1,col=1)
            rt=_target_relative(t); n,e=target_boundary(rt); tx=np.array([_vs_project(nn,ee,vs_az)[0] for nn,ee in zip(n,e)])*M_TO_FT; ty=np.full(len(tx),_target_tvd(t)*M_TO_FT); nm=t.get('name','Target')
            export_wall.add_trace(go.Scatter(x=tx,y=ty,mode='lines+markers',name=nm,showlegend=False,line=dict(dash='dash',width=2)),row=1,col=2)
        _add_uncertainty_plan(export_wall,cov,row=1,col=1,showlegend=True)
        export_wall.update_xaxes(title_text='Relative Easting (ft)',range=[ex_xmin,ex_xmax],row=1,col=1); export_wall.update_yaxes(title_text='Relative Northing (ft)',range=[ex_ymin,ex_ymax],scaleanchor='x',scaleratio=1,row=1,col=1)
        export_wall.update_xaxes(title_text=f'Vertical Section @ {vs_az:.2f}° Grid (ft)',range=[ex_vxmin-ex_vpx,ex_vxmax+ex_vpx],row=1,col=2); export_wall.update_yaxes(title_text='TVD (ft)',range=[ex_vymax+ex_vpy,ex_vymin-ex_vpy],row=1,col=2)
        export_wall.update_layout(height=760,title=f"{project['well_name']} — Wall Plot",margin=dict(l=50,r=30,t=90,b=85),legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='left',x=0),template=plot_template)
        export_wall.add_annotation(text=f"CRS: {project.get('crs','—')} | North reference: {project.get('north_reference','Grid North')} | VS azimuth: {vs_az:.2f}° Grid | Declination: {project.get('reference_data',{}).get('magnetic_declination_deg','—')}° | Convergence: {project.get('reference_data',{}).get('grid_convergence_deg','—')}°",xref='paper',yref='paper',x=0,y=-0.13,showarrow=False,align='left')
        html=export_wall.to_html(full_html=True,include_plotlyjs=True)
        buf=BytesIO()
        with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{project['well_name']}_wall_plot.html",html)
            z.writestr(f"{project['well_name']}_visualization_metadata.json",json.dumps(metadata,indent=2,ensure_ascii=False))
        st.download_button('⬇️ Export wall plot + visualization summary',data=buf.getvalue(),file_name=f"{project['well_name']}_wall_plot_package.zip",mime='application/zip',type='primary')

# QA/QC
elif page=='QA/QC':
    page_header('Integrated QA/QC', 'OUTPUTS', 'Review reference, survey, trajectory, target, offset and casing checks before treating the plan as complete.')
    results=validate_project(project)
    s=pd.DataFrame(project.get('surveys',[])); dc=project.get('design_constraints',{}); extra=[]
    if not s.empty:
        interval_m=float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0) or 30.0); max_dls_100=dls_for_interval_to_100ft(float(s.get('DLS',pd.Series([0])).max()),interval_m); max_inc=float(s.Inc.max()); max_inc_allowed=float(dc.get('max_inclination_deg',180)); max_dls_allowed=dls_30m_to_100ft(float(dc.get('max_dls_deg_30m',999)))
        extra += [{'check':'Max inclination constraint','status':'PASS' if max_inc<=max_inc_allowed+1e-6 else 'FAIL','message':f'Max {max_inc:.2f}° vs limit {max_inc_allowed:.2f}°.'},{'check':'Max DLS constraint','status':'PASS' if max_dls_100<=max_dls_allowed+1e-6 else 'FAIL','message':f'Max {max_dls_100:.2f}°/100ft vs limit {max_dls_allowed:.2f}°/100ft.'}]
    meta=project.get('trajectory_metadata',{}).get('planner_result',{})
    if meta:
        laterr=float(meta.get('lateral_error_m',0))*M_TO_FT; tvderr=abs(float(meta.get('tvd_error_m',0)))*M_TO_FT; extra += [{'check':'Trajectory target lateral error','status':'PASS' if laterr<=100 else 'WARN','message':f'{laterr:.1f} ft.'},{'check':'Trajectory target TVD error','status':'PASS' if tvderr<=100 else 'WARN','message':f'{tvderr:.1f} ft.'}]
    results.extend(extra); st.dataframe(pd.DataFrame(results),use_container_width=True,hide_index=True)
    if project.get('casing_program'): st.markdown('### Casing geometry'); st.dataframe(pd.DataFrame(casing_geometry_checks(project['casing_program'])),use_container_width=True,hide_index=True)
    if not s.empty: st.markdown('### Survey statistics'); st.write({'MD min (ft)':float(s.MD.min())*M_TO_FT,'MD max (ft)':float(s.MD.max())*M_TO_FT,'max inclination (°)':float(s.Inc.max()),'max DLS (°/100 ft)':dls_for_interval_to_100ft(float(s.get('DLS',pd.Series([0])).max()),float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0)))})

# Reports
elif page=='Reports':
    page_header('Engineering Practice Report', 'OUTPUTS', 'Export the shared project state and QA/QC results as a reproducible practice record.')
    report={'platform':'Well Planning Platform','generated_utc':datetime.utcnow().isoformat()+'Z','project':project_to_json(project),'qa_qc':validate_project(project)}
    st.json({'platform':report['platform'],'well':project['well_name'],'qa_checks':len(report['qa_qc'])})
    st.download_button('Download full project report JSON',json.dumps(report,indent=2).encode(),file_name=f"{project['well_name']}_report.json",mime='application/json')
    st.download_button('Download survey CSV',pd.DataFrame(project.get('surveys',[])).to_csv(index=False).encode(),file_name=f"{project['well_name']}_survey.csv",mime='text/csv')

# About
else:
    page_header('About', 'SYSTEM', 'Engineering scope and the distinction between practice screening and validated operational software.')
    st.markdown('''
## Well Planning Platform

Well Planning Platform is a browser-first, project-independent workspace for learning and practicing drilling engineering and well planning.

### Integrated domains

- Project, CRS and geodesy
- WMM2025 geomagnetics and north-reference conversions
- Survey management and QA/QC
- Minimum-curvature trajectory calculations
- Target geometry: point, circle, ellipse, rectangle, corridor and polygon
- Target-driven build/hold planning
- Offset-well management
- Screening anti-collision
- Well architecture and casing program
- Casing design screening
- Hydraulics and ECD screening
- Torque & drag screening
- Cement-volume screening
- Well-control screening
- BHA/drilling documentation
- Integrated plan, vertical-section and 3D visualization
- Project JSON and engineering-practice report export

### Engineering status

The platform intentionally distinguishes **transparent practice/screening calculations** from **validated operational engineering software**. Simplified modules must be independently checked against applicable standards, company procedures, OEM data and specialist software before field use.

### Recommended use

Use the platform to build complete synthetic wells, compare trajectories, practice survey/reference handling, construct casing programs, test engineering assumptions, and learn how drilling disciplines interact.
''')

st.session_state.project=project
