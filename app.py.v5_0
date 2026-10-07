import json, math
from datetime import date, datetime
from io import BytesIO
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.project import new_project, project_to_json, project_from_json, validate_project
from core.trajectory import minimum_curvature, build_constant_build_hold
from core.geometry import target_boundary
from core.reference import magnetic_to_true, true_to_grid, grid_to_true, true_to_magnetic, magnetic_to_grid, grid_to_magnetic
from models.geomagnetic import wmm2025
from models.geodesy import crs_info, transform_coordinates, grid_convergence_deg, normal_gravity, noaa_geoid_height
from engineering.anti_collision import clearance_report
from engineering.casing import casing_screen, casing_program_summary, casing_geometry_checks, casing_design_checks
from engineering.hydraulics import hydraulic_screen, rheology_summary
from engineering.well_control import well_control_screen
from engineering.pressure import pressure_window
from engineering.cement import cement_screen
from engineering.torque_drag import torque_drag_screen

st.set_page_config(page_title='Well Planning Platform v5.0', page_icon='🛢️', layout='wide', initial_sidebar_state='expanded')

# -----------------------------------------------------------------------------
# v5.0 UI SYSTEM
# The UI layer deliberately does not alter the v4 engineering engines/data model.
# -----------------------------------------------------------------------------
st.markdown("""
<style>
/* Desktop-first engineering workspace */
.block-container { padding: 1.15rem 2rem 3rem; max-width: 1600px; }
section[data-testid="stSidebar"] { border-right: 1px solid rgba(128,128,128,.18); }
section[data-testid="stSidebar"] > div { padding-top: 1rem; }
.wpp-brand { font-size: 1.25rem; font-weight: 800; letter-spacing: -.02em; }
.wpp-version { color: #8b949e; font-size: .78rem; margin-top: -.25rem; }
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
    return json.dumps(project_to_json(project), indent=2).encode()


NAV = [
    ('HOME', ['Dashboard']),
    ('SETUP', ['Project & Reference', 'Well Architecture', 'Targets', 'Offsets']),
    ('DIRECTIONAL', ['Survey Manager', 'Trajectory Planner', 'Geomagnetics', 'Geodesy', 'Anti-Collision']),
    ('DRILLING ENGINEERING', ['Casing Design', 'Hydraulics & ECD', 'PP / FG & Mud Window', 'Torque & Drag', 'Cementing', 'Well Control', 'BHA & Drilling']),
    ('OUTPUTS', ['Visualization', 'QA/QC', 'Reports']),
    ('SYSTEM', ['About']),
]
NAV_OPTIONS = [item for group, items in NAV for item in items]
NAV_PREFIX = {
    'Dashboard':'01', 'Project & Reference':'10', 'Well Architecture':'11', 'Targets':'12', 'Offsets':'13',
    'Survey Manager':'20', 'Trajectory Planner':'21', 'Geomagnetics':'22', 'Geodesy':'23', 'Anti-Collision':'24',
    'Casing Design':'30', 'Hydraulics & ECD':'31', 'PP / FG & Mud Window':'32', 'Torque & Drag':'33', 'Cementing':'34', 'Well Control':'35', 'BHA & Drilling':'36',
    'Visualization':'40', 'QA/QC':'41', 'Reports':'42', 'About':'90'
}

# Keep navigation stable across reruns. The engineering model remains in session state.
if 'active_page' not in st.session_state:
    st.session_state.active_page = 'Dashboard'

with st.sidebar:
    st.markdown('<div class="wpp-brand">🛢️ Well Planning Platform</div><div class="wpp-version">v5.0 • desktop engineering workspace</div>', unsafe_allow_html=True)
    st.divider()
    project['project_name'] = st.text_input('Project', project.get('project_name', 'New Project'))
    project['well_name'] = st.text_input('Well', project.get('well_name', 'NEW-01'))
    st.markdown('**Workspace**')
    current_label = f"{NAV_PREFIX.get(st.session_state.active_page, '01')} • {st.session_state.active_page}"
    labels = [f"{NAV_PREFIX[x]} • {x}" for x in NAV_OPTIONS]
    try: current_index = labels.index(current_label)
    except ValueError: current_index = 0
    selected_label = st.selectbox('Module', labels, index=current_index, label_visibility='collapsed')
    selected_page = selected_label.split(' • ', 1)[1]
    st.session_state.active_page = selected_page
    st.divider()
    st.download_button('⬇️ Export project JSON', download_json(), file_name=f"{project['well_name']}_v5.json", mime='application/json', use_container_width=True)
    upload = st.file_uploader('⬆️ Import project JSON', type='json')
    if upload:
        try:
            st.session_state.project = project_from_json(json.load(upload))
            st.session_state.active_page = 'Dashboard'
            st.rerun()
        except Exception as e:
            st.error(str(e))
    st.divider()
    st.caption('DESKTOP-FIRST')
    st.caption('Optimized for laptop/workstation use. Mobile/tablet layouts are intentionally not a v5 target.')
    st.warning('PRACTICE / ENGINEERING-DEVELOPMENT SOFTWARE\n\nVerify calculations against approved procedures, standards, OEM data and specialist software before operational use.')

page = st.session_state.active_page


def page_header(title, section, description=None):
    st.markdown(f'<div class="wpp-module">{section}</div>', unsafe_allow_html=True)
    st.title(title)
    if description:
        st.markdown(f'<div class="wpp-help">{description}</div>', unsafe_allow_html=True)


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
    max_dls = max([float(x.get('DLS', 0)) for x in surveys], default=0)
    cols = st.columns(5)
    metrics = [
        ('STATUS', project.get('status', 'Planning'), project.get('well_type', '')),
        ('CURRENT MD', f'{float(td):,.0f} m' if td is not None else '—', f'{len(surveys)} survey stations'),
        ('TARGETS', str(len(targets)), 'geometry objects'),
        ('OFFSETS', str(len(offsets)), 'reference wells'),
        ('CASING', str(len(casing)), 'stored strings'),
    ]
    for col, (label, value, note) in zip(cols, metrics):
        col.markdown(card(label, value, note), unsafe_allow_html=True)

    st.markdown('<div class="wpp-section">Engineering pulse</div>', unsafe_allow_html=True)
    a,b,c,d = st.columns(4)
    a.metric('Max inclination', f'{max_inc:.1f}°')
    b.metric('Max DLS', f'{max_dls:.2f}°/30m')
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
    page_header('Project, CRS & Reference Frame', 'SETUP', 'Define the well identity, coordinate reference system, depth reference and design constraints used throughout the project.')
    a,b,c=st.columns(3); project['latitude']=a.number_input('Latitude (°)',-90.,90.,float(project['latitude']),format='%.6f'); project['longitude']=b.number_input('Longitude (°)',-180.,180.,float(project['longitude']),format='%.6f'); project['elevation_m']=c.number_input('Wellhead elevation (m)',-2000.,10000.,float(project['elevation_m']))
    a,b,c=st.columns(3); project['kb_m']=a.number_input('KB elevation (m)',-2000.,10000.,float(project['kb_m'])); project['crs']=b.text_input('Project CRS / EPSG',project.get('crs','EPSG:4326')); project['planned_date']=str(c.date_input('Planning date',date.fromisoformat(project['planned_date'])))
    a,b,c=st.columns(3); project['north_reference']=a.selectbox('Primary north reference',['True North','Grid North','Magnetic North'],index=['True North','Grid North','Magnetic North'].index(project.get('north_reference','Grid North'))); project['depth_reference']=b.selectbox('Depth reference',['MD / TVDSS','MD / TVD']); project['status']=c.selectbox('Project status',['Planning','Draft','Under Review','Approved for Training'],index=['Planning','Draft','Under Review','Approved for Training'].index(project.get('status','Planning')))
    a,b,c=st.columns(3); project['operator']=a.text_input('Operator',project.get('operator','')); project['field']=b.text_input('Field',project.get('field','')); project['well_type']=c.selectbox('Well type',['Exploration','Appraisal','Development Producer','Development Injector','Sidetrack','Horizontal','Other'],index=0)
    st.markdown('### CRS information')
    try: st.dataframe(pd.DataFrame([crs_info(project['crs'])]),use_container_width=True,hide_index=True)
    except Exception as e: st.error(f'CRS error: {e}')
    st.markdown('### Design constraints')
    dc=project['design_constraints']; a,b,c=st.columns(3); dc['max_dls_deg_30m']=a.number_input('Max DLS (°/30 m)',.1,20.,float(dc['max_dls_deg_30m'])); dc['max_inclination_deg']=b.number_input('Max inclination (°)',0.,180.,float(dc['max_inclination_deg'])); dc['max_build_rate_deg_30m']=c.number_input('Max build rate (°/30 m)',.1,20.,float(dc['max_build_rate_deg_30m']))
    if st.button('Save project/reference settings',type='primary'): save(); st.success('Saved.')

# Survey Manager
elif page=='Survey Manager':
    page_header('Survey Manager', 'DIRECTIONAL', 'Load, normalize and calculate survey trajectories while preserving the selected azimuth reference and uncertainty assumptions.')
    sm=project['survey_metadata']; ref=project['reference_data']
    a,b,c,d=st.columns(4); sm['azimuth_reference']=a.selectbox('Input azimuth reference',['Magnetic North','True North','Grid North'],index=['Magnetic North','True North','Grid North'].index(sm['azimuth_reference'])); sm['survey_tool']=b.selectbox('Survey tool',['MWD','Gyro','Wireline','Planned','Other']); sm['survey_method']=c.selectbox('Calculation method',['Minimum Curvature','Average Angle','Balanced Tangential']); sm['positional_sigma_m']=d.number_input('Screening sigma (m)',0.,500.,float(sm.get('positional_sigma_m',0)))
    st.caption('v4 supports north-reference conversion and screening uncertainty. Full ISCWSA covariance/tool-error models remain an engineering-validation task, not a cosmetic checkbox.')
    df=pd.DataFrame(project.get('surveys',[]));
    edited=st.data_editor(df if not df.empty else pd.DataFrame([{'MD':0.,'Inc':0.,'Azi':0.}]),num_rows='dynamic',use_container_width=True,hide_index=True,key='survey_editor')
    a,b,c=st.columns(3); interval=a.number_input('DLS interval (m)',1.,1000.,30.); tvdss_offset=b.number_input('TVDSS offset (m)',-10000.,10000.,float(project.get('kb_m',0))); do=c.button('Calculate & store trajectory',type='primary')
    if do:
        try:
            w=edited[['MD','Inc','Azi']].copy(); decl=float(ref.get('magnetic_declination_deg') or 0); conv=float(ref.get('grid_convergence_deg') or 0)
            if sm['azimuth_reference']=='Magnetic North': w['Azi']=w['Azi'].map(lambda x: magnetic_to_grid(x,decl,conv))
            elif sm['azimuth_reference']=='True North': w['Azi']=w['Azi'].map(lambda x: true_to_grid(x,conv))
            result=minimum_curvature(w,interval); result['TVDSS']=result['TVD']+tvdss_offset; project['surveys']=result.to_dict('records'); project['trajectory_metadata']={'method':sm['survey_method'],'calculated_utc':datetime.utcnow().isoformat()+'Z'}; save(); st.success('Trajectory calculated and stored.')
        except Exception as e: st.error(str(e))
    if project.get('surveys'): st.dataframe(pd.DataFrame(project['surveys']),use_container_width=True,hide_index=True)
    f=st.file_uploader('Import survey CSV (MD, Inc, Azi)',type='csv',key='survey_upload')
    if f:
        imp=pd.read_csv(f); st.dataframe(imp.head(),use_container_width=True)
        if st.button('Replace survey with CSV'):
            if {'MD','Inc','Azi'}.issubset(imp.columns): project['surveys']=imp[['MD','Inc','Azi']].to_dict('records'); save(); st.success('Imported.')
            else: st.error('CSV must contain MD, Inc and Azi.')

# Trajectory Planner
elif page=='Trajectory Planner':
    page_header('Trajectory Planner', 'DIRECTIONAL', 'Generate a planning candidate from target geometry and review the resulting trajectory before using it downstream.')
    st.caption('Practice-grade target-driven build/hold planner. Use the generated path as a planning candidate, then review drillability and engineering limits.')
    targets=project.get('targets',[])
    if not targets: st.warning('Define a target first.'); st.stop()
    names=[t.get('name','Target') for t in targets]; idx=st.selectbox('Target',range(len(names)),format_func=lambda i:names[i]); t=targets[idx]
    a,b,c,d=st.columns(4); kop=a.number_input('KOP MD (m)',0.,15000.,float(project['well_architecture'].get('kop_md_m') or 1000)); br=a.number_input('Build rate (°/30 m)',.1,15.,float(project['design_constraints']['max_build_rate_deg_30m'])) if False else b.number_input('Build rate (°/30 m)',.1,15.,3.0); hold=c.number_input('Hold inclination (°)',1.,120.,60.); az=d.number_input('Planning azimuth (°)',0.,360.,float(t.get('azimuth_deg',0)))
    a,b,c=st.columns(3); td=a.number_input('Target TVD (m)',0.,15000.,float(t.get('tvd_m',t.get('tvdss_m',3000)))); n=b.number_input('Target Northing (m)',-1e6,1e6,float(t.get('north_m',0))); e=c.number_input('Target Easting (m)',-1e6,1e6,float(t.get('east_m',0)))
    if st.button('Generate build/hold candidate',type='primary'):
        try:
            out,meta=build_constant_build_hold(kop,br,hold,az,td,n,e,station_interval=30)
            project['surveys']=out.to_dict('records'); project['trajectory_metadata']={'planner':'Constant Build + Hold','planner_result':meta,'calculated_utc':datetime.utcnow().isoformat()+'Z'}; save(); st.success(f"Planner status: {meta['status']} • lateral error {meta['lateral_error_m']:.1f} m • TVD error {meta['tvd_error_m']:.1f} m"); st.dataframe(out,use_container_width=True,hide_index=True)
        except Exception as ex: st.error(str(ex))

# Targets
elif page=='Targets':
    page_header('Target Management', 'SETUP', 'Create and manage point, circular, elliptical, rectangular, corridor and polygon target geometries.')
    st.caption('Targets are geometry objects, not limited to circular windows.')
    types=['Point','Circular','Elliptical','Rectangular','Corridor','Polygon']; typ=st.selectbox('New target type',types); a,b,c=st.columns(3); name=a.text_input('Target name','Target-01'); n=a.number_input('Center Northing (m)',-1e6,1e6,0.); e=b.number_input('Center Easting (m)',-1e6,1e6,0.); tvd=c.number_input('Target TVD/TVDSS (m)',-15000.,15000.,3000.)
    t={'name':name,'type':typ,'north_m':n,'east_m':e,'tvdss_m':tvd}
    if typ=='Circular': t['radius_m']=st.number_input('Radius (m)',.1,10000.,50.)
    elif typ=='Elliptical':
        a,b,c=st.columns(3); t['semi_major_m']=a.number_input('Semi-major (m)',.1,10000.,150.); t['semi_minor_m']=b.number_input('Semi-minor (m)',.1,10000.,50.); t['orientation_deg']=c.number_input('Orientation from North (°)',-360.,360.,0.)
    elif typ=='Rectangular':
        a,b=st.columns(2); t['length_m']=a.number_input('North-South length (m)',.1,10000.,200.); t['width_m']=b.number_input('East-West width (m)',.1,10000.,100.)
    elif typ=='Corridor':
        a,b,c=st.columns(3); t['half_length_m']=a.number_input('Half-length (m)',.1,20000.,1000.); t['half_width_m']=b.number_input('Half-width (m)',.1,5000.,50.); t['azimuth_deg']=c.number_input('Corridor azimuth (°)',0.,360.,0.)
    elif typ=='Polygon':
        txt=st.text_area('Polygon points as North,East per line','0,0\n0,100\n100,100\n100,0'); pts=[]
        for line in txt.splitlines():
            try: nn,ee=[float(x.strip()) for x in line.split(',')[:2]]; pts.append([nn,ee])
            except: pass
        t['points']=pts
    if st.button('Add target',type='primary'): project['targets'].append(t); save(); st.success('Target added.')
    if project['targets']: st.dataframe(pd.DataFrame(project['targets']),use_container_width=True,hide_index=True)

# Offsets
elif page=='Offsets':
    page_header('Offset Wells', 'SETUP', 'Create independent reference wells that can be visualized and screened for proximity to the planned well.')
    a,b,c=st.columns(3); name=a.text_input('Offset name','OW-01'); lat=b.number_input('Offset latitude',-90.,90.,project['latitude']); lon=c.number_input('Offset longitude',-180.,180.,project['longitude'])
    n,e=st.columns(2); en=n.number_input('Surface Northing relative to main (m)',-10000.,10000.,0.); ee=e.number_input('Surface Easting relative to main (m)',-10000.,10000.,0.)
    if st.button('Create offset well'): project['offsets'].append({'name':name,'latitude':lat,'longitude':lon,'surface_northing_m':en,'surface_easting_m':ee,'surveys':[{'MD':0.,'Inc':0.,'Azi':0.}]}); save(); st.success('Offset created.')
    for i,off in enumerate(project['offsets']):
        with st.expander(f"{i+1}. {off.get('name','Offset')}"):
            odf=pd.DataFrame(off.get('surveys',[])); ed=st.data_editor(odf,num_rows='dynamic',key=f'off{i}',use_container_width=True)
            if st.button(f'Save {off.get("name")}',key=f'saveoff{i}'):
                try: off['surveys']=minimum_curvature(ed[['MD','Inc','Azi']]).to_dict('records'); save(); st.success('Saved offset trajectory.')
                except Exception as ex: st.error(str(ex))
    if project['offsets']: st.dataframe(pd.DataFrame([{'Name':x.get('name'),'Lat':x.get('latitude'),'Lon':x.get('longitude')} for x in project['offsets']]),use_container_width=True,hide_index=True)

# Well Architecture
elif page=='Well Architecture':
    page_header('Well Architecture & Final Casing Program', 'SETUP', 'Store the final well architecture and casing program as shared master data for downstream engineering checks.')
    a,b,c=st.columns(3); wa=project['well_architecture']; wa['planned_td_md_m']=a.number_input('Planned TD MD (m)',0.,30000.,float(wa.get('planned_td_md_m') or 4250)); wa['planned_td_tvd_m']=b.number_input('Planned TD TVD (m)',0.,30000.,float(wa.get('planned_td_tvd_m') or 3700)); wa['kop_md_m']=c.number_input('KOP MD (m)',0.,30000.,float(wa.get('kop_md_m') or 1450))
    cols=['string_no','type','hole_size_in','casing_od_in','grade','weight_lbft','shoe_md_m','depth_type','shoe_tvd_m','shoe_tvdss_m','liner_top_md_m','top_md_m','remarks']; old=pd.DataFrame(project.get('casing_program',[]));
    if old.empty: old=pd.DataFrame([{'string_no':1,'type':'Conductor','hole_size_in':24.,'casing_od_in':18.625,'grade':'','weight_lbft':0.,'shoe_md_m':250.,'depth_type':'MD','shoe_tvd_m':250.,'shoe_tvdss_m':225.,'liner_top_md_m':0.,'top_md_m':0.,'remarks':''}])
    for col in cols:
        if col not in old.columns: old[col]=''
    ed=st.data_editor(old[cols],num_rows='dynamic',use_container_width=True,hide_index=True,key='arch')
    if st.button('Save final casing architecture',type='primary'): project['casing_program']=casing_program_summary(ed.to_dict('records')); save(); st.success('Saved.')
    if project['casing_program']: st.dataframe(pd.DataFrame(casing_geometry_checks(project['casing_program'])),use_container_width=True,hide_index=True)

# Geomagnetics
elif page=='Geomagnetics':
    page_header('Geomagnetics', 'DIRECTIONAL', 'Calculate magnetic-field quantities and convert between magnetic, true and grid north references.')
    st.caption('Live model calculation where the WMM package is available; model provenance is stored in the project.')
    a,b,c=st.columns(3); lat=a.number_input('Latitude (°)',-90.,90.,float(project['latitude']),format='%.6f'); lon=b.number_input('Longitude (°)',-180.,180.,float(project['longitude']),format='%.6f'); alt=c.number_input('Ellipsoidal height (m)',-1000.,20000.,float(project['elevation_m']))
    dt=st.date_input('Model calculation date',date.fromisoformat(project['planned_date']))
    if st.button('Calculate WMM2025',type='primary'):
        try:
            r=wmm2025(lat,lon,alt,dt); ref=project['reference_data']; ref.update({'magnetic_declination_deg':r['D'],'magnetic_dip_deg':r['I'],'magnetic_total_field_nT':r['F'],'magnetic_horizontal_field_nT':r['H'],'magnetic_x_nT':r['X'],'magnetic_y_nT':r['Y'],'magnetic_z_nT':r['Z']}); project['model_metadata']['WMM2025']=r['metadata']; save(); st.success('WMM2025 result stored.')
        except Exception as e: st.error(f'WMM calculation failed: {e}')
    r=project['reference_data']; st.dataframe(pd.DataFrame([{'Quantity':'Declination','Value':r.get('magnetic_declination_deg'),'Unit':'deg'},{'Quantity':'Dip','Value':r.get('magnetic_dip_deg'),'Unit':'deg'},{'Quantity':'Total field','Value':r.get('magnetic_total_field_nT'),'Unit':'nT'},{'Quantity':'Horizontal field','Value':r.get('magnetic_horizontal_field_nT'),'Unit':'nT'},{'Quantity':'X','Value':r.get('magnetic_x_nT'),'Unit':'nT'},{'Quantity':'Y','Value':r.get('magnetic_y_nT'),'Unit':'nT'},{'Quantity':'Z','Value':r.get('magnetic_z_nT'),'Unit':'nT'}]),use_container_width=True,hide_index=True)
    st.markdown('### North-reference converter'); a,b,c,d=st.columns(4); az=a.number_input('Azimuth (°)',0.,360.,0.); fr=b.selectbox('From',['Magnetic','True','Grid']); to=c.selectbox('To',['Magnetic','True','Grid']);
    if d.button('Convert'):
        dec=float(r.get('magnetic_declination_deg') or 0); conv=float(r.get('grid_convergence_deg') or 0); out=az if fr==to else magnetic_to_true(az,dec) if (fr,to)==('Magnetic','True') else true_to_magnetic(az,dec) if (fr,to)==('True','Magnetic') else true_to_grid(az,conv) if (fr,to)==('True','Grid') else grid_to_true(az,conv) if (fr,to)==('Grid','True') else magnetic_to_grid(az,dec,conv) if (fr,to)==('Magnetic','Grid') else grid_to_magnetic(az,dec,conv); st.metric(f'{to} azimuth',f'{out:.4f}°')

# Geodesy
elif page=='Geodesy':
    page_header('Geodesy, CRS, Convergence, Geoid & Gravity', 'DIRECTIONAL', 'Manage CRS transformations and reference quantities that support accurate survey and positional work.')
    try:
        info=crs_info(project['crs']); st.dataframe(pd.DataFrame([info]),use_container_width=True,hide_index=True)
        conv=grid_convergence_deg(project['latitude'],project['longitude'],project['crs']); project['reference_data']['grid_convergence_deg']=conv
        grav=normal_gravity(project['latitude'],project['elevation_m']); project['reference_data']['gravity_mps2']=grav
        st.metric('Grid convergence',f'{conv:.6f}°'); st.metric('Normal gravity',f'{grav:.9f} m/s²')
    except Exception as e: st.error(str(e))
    st.markdown('### Coordinate transformation'); a,b,c,d=st.columns(4); x=a.number_input('X / Easting',-1e8,1e8,float(project.get('surface_easting_m',0))); y=b.number_input('Y / Northing',-1e8,1e8,float(project.get('surface_northing_m',0))); src=c.text_input('Source CRS','EPSG:4326'); dst=d.text_input('Target CRS',project.get('crs','EPSG:4326'))
    if st.button('Transform coordinates'):
        try: xx,yy=transform_coordinates(x,y,src,dst); st.write({'x':xx,'y':yy})
        except Exception as e: st.error(str(e))
    if st.button('Query NOAA geoid service'):
        try:
            g=noaa_geoid_height(project['latitude'],project['longitude']); project['reference_data']['geoid_height_m']=g['geoidHeight']; project['reference_data']['geoid_model']=g.get('geoidModel'); save(); st.success(f"Geoid height: {g['geoidHeight']:.3f} m")
        except Exception as e: st.error(f'Geoid query failed: {e}')

# Anti collision
elif page=='Anti-Collision':
    page_header('Anti-Collision Screening', 'DIRECTIONAL', 'Run the current screening workflow against stored offset trajectories and uncertainty assumptions.')
    main=pd.DataFrame(project.get('surveys',[])); sigma=float(project['survey_metadata'].get('positional_sigma_m',0) or 0); off_sigma=st.number_input('Offset uncertainty sigma (m)',0.,500.,sigma)
    if st.button('Run clearance scan',type='primary'):
        try:
            rep=clearance_report(main,project.get('offsets',[]),sigma,off_sigma); st.dataframe(rep,use_container_width=True,hide_index=True); st.caption('Screening only. A production anti-collision workflow requires a validated ISCWSA error model, covariance propagation and company-approved separation rules.')
        except Exception as e: st.error(str(e))

# Casing
elif page=='Casing Design':
    page_header('Casing Design & Well Integrity Screening', 'DRILLING ENGINEERING', 'Review the stored casing architecture and run the current burst, collapse and tension screening calculations.')
    st.markdown('### Stored architecture');
    if project['casing_program']: st.dataframe(pd.DataFrame(project['casing_program']),use_container_width=True,hide_index=True)
    else: st.warning('Build the final casing program in Well Architecture first.')
    st.markdown('### Design screen'); a,b,c,d,e,f=st.columns(6); od=a.number_input('OD (in)',2.,30.,9.625); wt=b.number_input('Weight (lb/ft)',5.,300.,47.); grade=c.number_input('Yield strength (psi)',10000.,250000.,80000.); shoe=d.number_input('Shoe MD (m)',0.,20000.,2750.); mw=e.number_input('Mud weight (ppg)',5.,20.,10.); pore=f.number_input('Pore gradient (psi/ft)',.1,1.5,.5)
    frac=st.number_input('Fracture gradient (psi/ft)',.1,2.,.65)
    if st.button('Run casing design screen',type='primary'): st.dataframe(pd.DataFrame([casing_design_checks(od,wt,grade,shoe,mw,pore,frac)]),use_container_width=True,hide_index=True)

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
    page_header('Torque & Drag Screening', 'DRILLING ENGINEERING', 'Run the current soft-string screening calculation using the selected friction, buoyancy and drillstring assumptions.'); s=project.get('surveys',[]); depth=float(s[-1]['MD']) if s else 4000.; inc=float(s[-1]['Inc']) if s else 0.; dls=float(s[-1].get('DLS',0)) if s else 0.; a,b,c,d=st.columns(4); depth=a.number_input('Depth (m)',0.,30000.,depth); ff=b.number_input('Friction factor',0.,1.,.25); bf=c.number_input('Buoyancy factor',0.,1.2,.82); wt=d.number_input('String weight (lb/ft)',1.,300.,19.5)
    if st.button('Run T&D screen',type='primary'): st.dataframe(pd.DataFrame([torque_drag_screen(depth,ff,bf,wt,inc,dls)]),use_container_width=True,hide_index=True)

# Cement
elif page=='Cementing':
    page_header('Cementing Screening', 'DRILLING ENGINEERING', 'Estimate annular cement volume and slurry sacks from the stored casing geometry and selected assumptions.'); p=project.get('casing_program',[]); idx=st.selectbox('Casing string',range(len(p)),format_func=lambda i:f"{p[i].get('string_no')} • {p[i].get('type')}") if p else None; r=p[idx] if idx is not None else {}; a,b,c,d=st.columns(4); hole=a.number_input('Hole diameter (in)',2.,30.,float(r.get('hole_size_in') or 12.25)); od=b.number_input('Casing OD (in)',2.,30.,float(r.get('casing_od_in') or 9.625)); length=c.number_input('Cement length (m)',0.,20000.,max(1.,float(r.get('shoe_md_m') or 1000)-float(r.get('top_md_m') or 0))); excess=d.number_input('Excess (%)',0.,100.,20.); yieldv=st.number_input('Slurry yield (bbl/sack)',.1,5.,1.18)
    if st.button('Calculate cement screen',type='primary'): st.dataframe(pd.DataFrame([cement_screen(hole,od,length,excess,yieldv)]),use_container_width=True,hide_index=True)

# Well control
elif page=='Well Control':
    page_header('Well Control Screening', 'DRILLING ENGINEERING', 'Review basic kick/kill screening quantities; operational well control remains governed by approved procedures.'); a,b,c,d=st.columns(4); sid=a.number_input('SIDPP (psi)',0.,10000.,500.); tvd=b.number_input('TVD (ft)',100.,50000.,10000.); mw=c.number_input('Current MW (ppg)',5.,20.,10.); maasp=d.number_input('Allowable surface pressure (psi)',0.,20000.,1500.); fg=st.number_input('Fracture gradient (psi/ft)',0.,2.,.65)
    if st.button('Run well-control screen',type='primary'): st.dataframe(pd.DataFrame([well_control_screen(sid,tvd,mw,maasp,fg)]),use_container_width=True,hide_index=True); st.warning('Operational well control must follow approved company procedures.')

# BHA
elif page=='BHA & Drilling':
    page_header('BHA & Drilling Configuration', 'DRILLING ENGINEERING', 'Document the bit, motor/RSS, MWD/LWD, collars, HWDP and drillpipe configuration associated with the plan.')
    df=pd.DataFrame(project.get('bha',[]));
    if df.empty: df=pd.DataFrame([{'component':'Bit','type':'PDC','OD_in':8.5,'length_m':0.3,'weight_lbft':0,'role':'Drill'}])
    ed=st.data_editor(df,num_rows='dynamic',use_container_width=True,hide_index=True,key='bha');
    if st.button('Save BHA'): project['bha']=ed.to_dict('records'); save(); st.success('BHA saved.')
    st.info('Use this section to document bit, motor/RSS, MWD/LWD, collars, HWDP and drillpipe configuration. Mechanical design remains an engineering-development workflow.')

# Visualization
elif page=='Visualization':
    page_header('Integrated Well Visualization', 'OUTPUTS', 'Inspect the planned well, targets, offsets and screening uncertainty in plan, vertical-section and 3D views.')
    main=pd.DataFrame(project.get('surveys',[]));
    if main.empty: st.warning('No main-well trajectory.'); st.stop()
    view=st.selectbox('View',['Plan','Vertical Section','3D']); show_unc=st.checkbox('Show screening uncertainty',True); show_targets=st.checkbox('Show targets',True); show_offsets=st.checkbox('Show offsets',True)
    fig=go.Figure()
    if view=='Plan':
        fig.add_trace(go.Scatter(x=main['Easting'],y=main['Northing'],mode='lines+markers',name=project['well_name'],text=[f"MD {x:.0f} m" for x in main['MD']],hovertemplate='%{text}<extra></extra>'))
        if show_offsets:
            for off in project.get('offsets',[]):
                od=pd.DataFrame(off.get('surveys',[]));
                if {'Easting','Northing'}.issubset(od.columns): fig.add_trace(go.Scatter(x=od.Easting,y=od.Northing,mode='lines',name=off.get('name','Offset')))
        if show_targets:
            for t in project.get('targets',[]):
                n,e=target_boundary(t); fig.add_trace(go.Scatter(x=e,y=n,mode='lines+markers',name=t.get('name','Target'),line=dict(dash='dash')))
        if show_unc:
            sig=float(project['survey_metadata'].get('positional_sigma_m',0) or 0)
            if sig>0:
                a=np.linspace(0,2*np.pi,72); x=float(main.iloc[-1].Easting)+sig*np.cos(a); y=float(main.iloc[-1].Northing)+sig*np.sin(a); fig.add_trace(go.Scatter(x=x,y=y,mode='lines',name='Screening uncertainty'))
        fig.update_layout(xaxis_title='Easting (m)',yaxis_title='Northing (m)',height=700)
    elif view=='Vertical Section':
        fig.add_trace(go.Scatter(x=main['VS'],y=main['TVD'],mode='lines+markers',name=project['well_name'])); fig.update_yaxes(autorange='reversed'); fig.update_layout(xaxis_title='Vertical Section (m)',yaxis_title='TVD (m)',height=700)
    else:
        fig.add_trace(go.Scatter3d(x=main.Easting,y=main.Northing,z=-main.TVD,mode='lines+markers',name=project['well_name'],text=[f'MD {x:.0f} m' for x in main.MD],hovertemplate='%{text}<extra></extra>'))
        fig.add_trace(go.Scatter3d(x=[main.iloc[0].Easting],y=[main.iloc[0].Northing],z=[-main.iloc[0].TVD],mode='text',text=['WH'],name='Wellhead',showlegend=False))
        fig.add_trace(go.Scatter3d(x=[main.iloc[-1].Easting],y=[main.iloc[-1].Northing],z=[-main.iloc[-1].TVD],mode='text',text=['TD'],name='TD',showlegend=False))
        if show_offsets:
            for off in project.get('offsets',[]):
                od=pd.DataFrame(off.get('surveys',[]));
                if {'Easting','Northing','TVD'}.issubset(od.columns): fig.add_trace(go.Scatter3d(x=od.Easting,y=od.Northing,z=-od.TVD,mode='lines',name=off.get('name','Offset')))
        if show_targets:
            for t in project.get('targets',[]):
                tn=float(t.get('north_m',0)); te=float(t.get('east_m',0)); tz=-float(t.get('tvdss_m',0)); fig.add_trace(go.Scatter3d(x=[te],y=[tn],z=[tz],mode='markers+text',text=[t.get('name','Target')],textposition='top center',name=t.get('name','Target'),showlegend=False))
        fig.update_layout(scene=dict(xaxis_title='Easting',yaxis_title='Northing',zaxis_title='-TVD'),height=750)
    st.plotly_chart(fig,use_container_width=True)

# QA/QC
elif page=='QA/QC':
    page_header('Integrated QA/QC', 'OUTPUTS', 'Review project-level checks and geometry/survey statistics before treating the plan as complete.'); results=validate_project(project); st.dataframe(pd.DataFrame(results),use_container_width=True,hide_index=True)
    if project.get('casing_program'): st.markdown('### Casing geometry'); st.dataframe(pd.DataFrame(casing_geometry_checks(project['casing_program'])),use_container_width=True,hide_index=True)
    st.markdown('### Survey statistics'); s=pd.DataFrame(project.get('surveys',[]));
    if not s.empty: st.write({'MD min':float(s.MD.min()),'MD max':float(s.MD.max()),'max inclination':float(s.Inc.max()),'max DLS':float(s.get('DLS',pd.Series([0])).max())})

# Reports
elif page=='Reports':
    page_header('Engineering Practice Report', 'OUTPUTS', 'Export the shared project state and QA/QC results as a reproducible practice record.')
    report={'platform':'Well Planning Platform','version':'5.0','generated_utc':datetime.utcnow().isoformat()+'Z','project':project_to_json(project),'qa_qc':validate_project(project)}
    st.json({'platform':report['platform'],'version':report['version'],'well':project['well_name'],'qa_checks':len(report['qa_qc'])})
    st.download_button('Download full project report JSON',json.dumps(report,indent=2).encode(),file_name=f"{project['well_name']}_v4_report.json",mime='application/json')
    st.download_button('Download survey CSV',pd.DataFrame(project.get('surveys',[])).to_csv(index=False).encode(),file_name=f"{project['well_name']}_survey.csv",mime='text/csv')

# About
else:
    page_header('About v5.0', 'SYSTEM', 'Release notes, engineering scope and the distinction between practice screening and validated operational software.')
    st.markdown('''
## v5.0 UI / UX release

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
