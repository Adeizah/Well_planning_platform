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
from core.trajectory import minimum_curvature, build_constant_build_hold, solve_build_hold_hold_inclination, generate_profile_candidate, truncate_trajectory_at_md
from core.optimizer import optimize_trajectory, _target_residual
from core.general_optimizer import optimize_general_trajectory
from core.section_reconstruction import constraint_margin_rows
from core.geometry import target_boundary
from core.validation import validate_trajectory, to_jsonable
from core.dependencies import refresh_plan_staleness, attach_snapshot
from core.visual import display_path
from core.survey_qc import survey_quality_report
from core.trajectory import interpolate_path
from core.reference import magnetic_to_true, true_to_grid, grid_to_true, true_to_magnetic, magnetic_to_grid, grid_to_magnetic, reference_requirements, convert_to_project_reference
from models.geomagnetic import igrf14
from models.geodesy import crs_info, transform_coordinates, grid_convergence_deg, normal_gravity, noaa_geoid_height, common_crs_registry, search_crs_registry, transformation_report, transformation_operations, projected_coordinates_to_metres, metres_to_projected_coordinates, transform_projected_grid_metres
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
# A saved plan is downgraded to REVIEW (never silently kept valid) when a target, offset,
# surface/KB, constraint or uncertainty input it depended on has changed.
_stale_reasons = refresh_plan_staleness(project)


def save():
    st.session_state.project = project


def download_json():
    # Export the shared engineering model, not transient Streamlit widget state.
    return json.dumps(project_to_json(project), indent=2, ensure_ascii=False).encode('utf-8')


NAV = [
    ('HOME', ['Dashboard']),
    ('SETUP', ['Project & Reference', 'Well Architecture', 'Targets', 'Offsets']),
    ('DIRECTIONAL', ['Survey Manager', 'Trajectory Planner', 'Anti-Collision']),
    ('DRILLING ENGINEERING', ['Casing Design', 'Hydraulics & ECD', 'PP / FG & Mud Window', 'Torque & Drag', 'Cementing', 'Well Control', 'BHA & Drilling']),
    ('OUTPUTS', ['Visualization', 'QA/QC', 'Reports']),
    ('SYSTEM', ['About']),
]
# ---- cached wrappers: these only depend on their arguments, so recomputing them on every Streamlit rerun is wasted time.
_cache_data = getattr(st, 'cache_data', None) or (lambda *a, **k: (lambda f: f))


@_cache_data(show_spinner=False, max_entries=64)
def cached_geomagnetic(model, lat, lon, elevation_m, iso_date):
    d = date.fromisoformat(iso_date)
    return igrf14(lat, lon, elevation_m, d)


@_cache_data(show_spinner=False, max_entries=64)
def cached_transformation_report(source_crs, target_crs, lon, lat):
    return transformation_report(source_crs, target_crs, lon=lon, lat=lat)


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
    if _stale_reasons and title in ('Trajectory Planner','Integrated Well Visualization','Anti-Collision Screening','Integrated QA/QC','Engineering Practice Report','Well Planning Dashboard'):
        st.warning('Saved trajectory plan needs review — ' + ' '.join(_stale_reasons) + ' Regenerate and revalidate it before relying on it.')


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
    profile_options=['Vertical','J-Profile','S-Profile','Horizontal','ERD','Custom']
    profile_labels={'J-Profile':'J-profile / Build & Hold','S-Profile':'S-profile / Build-Hold-Drop'}
    saved_design=project.get('well_design','J-Profile')
    saved_design={'Build & Hold':'J-Profile','Build-Hold-Drop':'S-Profile'}.get(saved_design,saved_design)
    if saved_design not in profile_options: saved_design='J-Profile'
    project['well_design']=d.selectbox('Well design',profile_options,index=profile_options.index(saved_design),format_func=lambda x:profile_labels.get(x,x),help='This is the shared well-design preset used by the Trajectory Planner. J-profile and Build & Hold are treated as the same profile; S-profile and Build-Hold-Drop are treated as the same profile.')

    st.markdown('### Geodetic reference and location')
    st.caption('Choose the project CRS first. Coordinate inputs are transformed into this reference; projected grid coordinates are stored in metres, while drilling lengths and depths remain in the engineering model’s SI base units and are converted for display as needed.')

    # The selected CRS is the authoritative horizontal reference for the project.
    common = common_crs_registry()
    query = st.text_input('Search CRS registry by EPSG code, CRS name or datum', value='', key='crs_registry_search')
    matches = search_crs_registry(query, limit=60) if query.strip() else []
    by_code = {x['code']: x for x in common + matches}
    previous_crs = str(project.get('crs', 'EPSG:32632'))
    current_code = previous_crs
    if current_code not in by_code:
        try:
            current_info = crs_info(current_code)
            by_code[current_code] = {'code': current_code, 'name': current_info['name'], 'datum': current_info['datum'], 'type': current_info['type'], 'units': current_info['units']}
        except Exception:
            current_code = 'EPSG:32632'
            previous_crs = current_code
            project['crs'] = current_code
    crs_items = list(by_code.values())
    crs_codes = [x['code'] for x in crs_items]
    if current_code not in crs_codes:
        crs_codes.append(current_code)
        by_code[current_code] = {'code': current_code, 'name': current_code, 'datum': 'Unknown', 'type': 'Unknown', 'units': 'Unknown'}
    # Searching should make the matching CRS easy to select. If the current CRS
    # is not among the search matches, preselect the first match rather than
    # leaving an unrelated CRS (e.g. ETRS89) active without an obvious cue.
    select_index = crs_codes.index(current_code)
    if query.strip() and matches and current_code not in {item['code'] for item in matches}:
        select_index = crs_codes.index(matches[0]['code'])
    chosen_code = st.selectbox('Project coordinate reference system (CRS)', crs_codes,
        index=select_index, format_func=lambda code: f"{code} — {by_code.get(code, {}).get('name', code)} [{by_code.get(code, {}).get('datum', 'datum unknown')}]",
        help='The CRS includes the datum/reference frame and, for projected systems, the projection and coordinate units. Search to find other installed EPSG CRSs.')
    try:
        from pyproj import CRS
        previous_crs_obj = CRS.from_user_input(previous_crs)
        chosen_crs_obj = CRS.from_user_input(chosen_code)
        if chosen_code != previous_crs:
            if (project.get('targets') or project.get('offsets')) and not chosen_crs_obj.is_projected:
                st.error('This project already contains absolute grid targets or offset coordinates. Keep a projected project CRS so those coordinates remain unambiguous; you can still enter the wellhead as latitude/longitude.')
                chosen_code = previous_crs
                chosen_crs_obj = previous_crs_obj
            elif previous_crs_obj.is_projected and chosen_crs_obj.is_projected:
                # Stage every transformation first. Commit only if all are valid, so a
                # missing datum grid cannot leave the project half-reprojected.
                try:
                    new_surface = transform_projected_grid_metres(
                        project.get('surface_easting_m', 0.0), project.get('surface_northing_m', 0.0), previous_crs, chosen_code)
                    new_targets = []
                    for target in project.get('targets', []):
                        source_code = target.get('crs', previous_crs)
                        if not CRS.from_user_input(source_code).is_projected:
                            raise ValueError(f"Target {target.get('name', 'unnamed')} has no valid projected source CRS.")
                        new_targets.append((target, *transform_projected_grid_metres(
                            target.get('east_m', 0.0), target.get('north_m', 0.0), source_code, chosen_code)))
                    new_offsets = []
                    for offset in project.get('offsets', []):
                        source_code = offset.get('crs', previous_crs)
                        if offset.get('surface_easting_m') is not None and offset.get('surface_northing_m') is not None:
                            if not CRS.from_user_input(source_code).is_projected:
                                raise ValueError(f"Offset {offset.get('name', 'unnamed')} has no valid projected source CRS.")
                            new_offsets.append((offset, *transform_projected_grid_metres(
                                offset['surface_easting_m'], offset['surface_northing_m'], source_code, chosen_code)))
                except Exception as transform_error:
                    st.error(f'CRS change cancelled to protect project consistency: {transform_error}. Keep the current CRS until a suitable datum transformation/grid is available.')
                    chosen_code = previous_crs
                    chosen_crs_obj = previous_crs_obj
                else:
                    project['surface_easting_m'], project['surface_northing_m'] = new_surface
                    for target, east_m, north_m in new_targets:
                        target['east_m'], target['north_m'], target['crs'] = east_m, north_m, chosen_code
                    for offset, east_m, north_m in new_offsets:
                        offset['surface_easting_m'], offset['surface_northing_m'], offset['crs'] = east_m, north_m, chosen_code
            elif chosen_crs_obj.is_projected:
                # Previous reference was geographic/non-projected: seed the grid from the saved lat/lon.
                _e_native, _n_native = transform_coordinates(project.get('longitude', 0.0), project.get('latitude', 0.0), 'EPSG:4326', chosen_code, strict=True, lon=project.get('longitude', 0.0), lat=project.get('latitude', 0.0))
                project['surface_easting_m'], project['surface_northing_m'] = projected_coordinates_to_metres(_e_native, _n_native, chosen_code)
                for target in project.get('targets', []):
                    target['crs'] = chosen_code
            project['crs'] = chosen_code
            project.setdefault('reference_data', {})['project_crs'] = chosen_code
        else:
            project['crs'] = chosen_code
        active_crs = CRS.from_user_input(project['crs'])
        active_info = crs_info(project['crs'])
        project.setdefault('reference_data', {})['datum'] = active_info.get('datum')
        project['reference_data']['ellipsoid'] = active_info.get('ellipsoid')
        project['reference_data']['project_crs'] = project['crs']
        project['reference_data']['source_crs'] = 'EPSG:4326' if project.get('coordinate_input_mode') == 'Latitude / Longitude' else project['crs']
        project['reference_data']['input_coordinate_crs'] = project['reference_data']['source_crs']
        if not active_crs.is_projected:
            st.warning('The selected CRS is not projected. Latitude/longitude can be used, but absolute grid Northing/Easting targets and grid-based trajectory planning require a projected CRS.')
    except Exception as exc:
        active_crs = None
        st.error(f'Invalid project CRS: {exc}')

    input_modes = ['Latitude / Longitude', 'Grid Northing / Easting (m)']
    saved_mode = project.get('coordinate_input_mode', input_modes[0])
    if saved_mode not in input_modes: saved_mode = input_modes[0]
    mode = st.radio('Wellhead coordinate input', input_modes, index=input_modes.index(saved_mode), horizontal=True,
                    help='Choose either geographic coordinates or projected grid coordinates. Grid Easting/Northing are entered in metres and stored in metres.')
    project['coordinate_input_mode'] = mode
    if mode == 'Latitude / Longitude':
        a,b,c = st.columns(3)
        project['latitude'] = a.number_input('Latitude (°)', -90.0, 90.0, float(project.get('latitude', 4.8)), format='%.7f')
        project['longitude'] = b.number_input('Longitude (°)', -180.0, 180.0, float(project.get('longitude', 6.9)), format='%.7f')
        project['elevation_m'] = c.number_input('Wellhead elevation (ft)', -6500.0, 33000.0, float(project.get('elevation_m', 25.0))*M_TO_FT) * FT_TO_M
        if active_crs is not None and active_crs.is_projected:
            try:
                _e_native, _n_native = transform_coordinates(project['longitude'], project['latitude'], 'EPSG:4326', project['crs'], strict=True, lon=project['longitude'], lat=project['latitude'])
                project['surface_easting_m'], project['surface_northing_m'] = projected_coordinates_to_metres(_e_native, _n_native, project['crs'])
                # Keep the alternate grid-input widgets synchronized when users switch modes.
                st.session_state[f'surface_easting_m_{project.get("crs", "crs")}'] = project['surface_easting_m']
                st.session_state[f'surface_northing_m_{project.get("crs", "crs")}'] = project['surface_northing_m']
            except Exception as exc:
                st.error(f'Could not transform latitude/longitude to the selected project CRS: {exc}')
    else:
        if active_crs is not None and active_crs.is_projected:
            a,b,c = st.columns(3)
            project['surface_northing_m'] = a.number_input('Grid Northing (m)', -100000000.0, 100000000.0, float(project.get('surface_northing_m', 0.0)), format='%.3f', key=f'surface_northing_m_{project.get("crs", "crs")}')
            project['surface_easting_m'] = b.number_input('Grid Easting (m)', -100000000.0, 100000000.0, float(project.get('surface_easting_m', 0.0)), format='%.3f', key=f'surface_easting_m_{project.get("crs", "crs")}')
            project['elevation_m'] = c.number_input('Wellhead elevation (ft)', -6500.0, 33000.0, float(project.get('elevation_m', 25.0))*M_TO_FT) * FT_TO_M
            try:
                _e_native, _n_native = metres_to_projected_coordinates(project['surface_easting_m'], project['surface_northing_m'], project['crs'])
                project['longitude'], project['latitude'] = transform_coordinates(_e_native, _n_native, project['crs'], 'EPSG:4326')
            except Exception as exc:
                st.error(f'Could not transform grid coordinates to latitude/longitude: {exc}')
        else:
            st.info('Select a projected CRS to enter Northing/Easting. The current CRS uses geographic coordinates.')

    a,b,c=st.columns(3)
    project['kb_m']=a.number_input('KB elevation (ft)',-6500.,33000.,float(project.get('kb_m',25.0))*M_TO_FT) * FT_TO_M
    project['planned_date']=str(b.date_input('Planning date',date.fromisoformat(project['planned_date'])))
    project['units']=c.selectbox('Engineering display units',['Field','Metric'],index=0 if project.get('units','Field')=='Field' else 1)

    st.markdown('### Active reference details')
    try:
        ci = crs_info(project['crs'])
        if project.get('reference_data', {}).get('grid_convergence_source') != 'User supplied':
            conv = grid_convergence_deg(project['latitude'], project['longitude'], project['crs'])
            project['reference_data']['grid_convergence_deg'] = conv
        else:
            conv = float(project['reference_data'].get('grid_convergence_deg', 0.0))
        project['reference_data']['project_crs'] = project['crs']
        project['reference_data']['datum'] = ci.get('datum')
        project['reference_data']['ellipsoid'] = ci.get('ellipsoid')
        st.success(f"Active CRS: {ci['name']} • {project['crs']} • Datum/reference frame: {ci.get('datum')} • Grid convergence: {conv:.4f}°")
        st.dataframe(pd.DataFrame([ci]), use_container_width=True, hide_index=True)
        if ci.get('type') == 'Projected':
            st.info(f"Wellhead grid position: Northing {project.get('surface_northing_m',0):,.3f} m • Easting {project.get('surface_easting_m',0):,.3f} m • Geographic position: {project.get('latitude',0):.7f}°, {project.get('longitude',0):.7f}°")
        if mode == 'Latitude / Longitude':
            report = cached_transformation_report('EPSG:4326', project['crs'], project['longitude'], project['latitude'])
        elif ci.get('type') == 'Projected':
            report = cached_transformation_report(project['crs'], 'EPSG:4326', project['longitude'], project['latitude'])
        else:
            report = None
        if report and not report.get('best_available'):
            st.warning(f"No suitable non-ballpark transformation with stated accuracy was confirmed for this CRS pair at the well location. Current displayed coordinates may require local grid resources or control data. Details: {report.get('description', 'No operation details available')}")
        elif report:
            st.caption(f"Transformation check: {report.get('description', 'Operation selected by PROJ')} • stated accuracy: {report.get('accuracy_m') if report.get('accuracy_m') is not None else 'not stated'} m. Verify datum suitability and local control before operational use.")
    except Exception as e:
        st.error(f'CRS/reference calculation error: {e}')
    a,b,c=st.columns(3); project['north_reference']=a.selectbox('Primary north reference',['True North','Grid North','Magnetic North'],index=['True North','Grid North','Magnetic North'].index(project.get('north_reference','Grid North'))); depth_options=['MD / TVDSS','MD / TVD']; project['depth_reference']=b.selectbox('Depth reference',depth_options,index=depth_options.index(project.get('depth_reference','MD / TVDSS'))); project['status']=c.selectbox('Project status',['Planning','Draft','Under Review','Approved for Training'],index=['Planning','Draft','Under Review','Approved for Training'].index(project.get('status','Planning')))
    st.markdown('### Design constraints')
    dc=project['design_constraints']; a,b=st.columns(2); dc['max_dls_deg_30m']=dls_100ft_to_30m(a.number_input('Maximum DLS (°/100 ft)',.1,20.,dls_30m_to_100ft(float(dc.get('max_dls_deg_30m',3.0))))); dc['max_inclination_deg']=b.number_input('Max inclination (°)',0.,180.,float(dc.get('max_inclination_deg',70.0)))
    st.markdown('### Reference calculations')
    st.caption('IGRF is the only geomagnetic model used by this project. Calculated or manually supplied reference values are stored centrally and reused by survey and trajectory workflows.')
    refdata = project.setdefault('reference_data', {})
    model_mode = st.radio('Magnetic reference values', ['Calculate using IGRF-14', 'Enter values manually'], horizontal=True, key='magnetic_input_mode')
    dt_calc = date.fromisoformat(str(project['planned_date']))
    if model_mode == 'Calculate using IGRF-14':
        try:
            mag = dict(cached_geomagnetic('IGRF-14', float(project['latitude']), float(project['longitude']), float(project.get('elevation_m', 0.0)), dt_calc.isoformat()))
            refdata.update({'geomagnetic_model':'IGRF-14', 'geomagnetic_model_metadata':mag['metadata'],
                'magnetic_declination_deg':mag['D'], 'magnetic_dip_deg':mag['I'], 'magnetic_total_field_nT':mag['F'],
                'magnetic_horizontal_field_nT':mag['H'], 'magnetic_x_nT':mag['X'], 'magnetic_y_nT':mag['Y'], 'magnetic_z_nT':mag['Z']})
            project.setdefault('model_metadata', {})['active_geomagnetic_model'] = 'IGRF-14'
            project['model_metadata']['IGRF-14'] = mag['metadata']
            project['model_metadata'].setdefault('results', {})['IGRF-14'] = mag
            st.caption(f"IGRF-14 calculation date: {dt_calc.isoformat()} • {mag['metadata'].get('source', 'ppigrf')} • height {float(project.get('elevation_m', 0.0)):.2f} m")
        except Exception as exc:
            st.error(f'IGRF-14 calculation failed: {exc}. Enter verified values manually if you have an authoritative source.')
    else:
        st.caption('Enter values from a verified source. Manual values are tagged as user-supplied and are not represented as calculated IGRF results.')
        fields = [
            ('magnetic_declination_deg','Magnetic declination (°)',-180.0,180.0),
            ('magnetic_dip_deg','Magnetic dip (°)',-90.0,90.0),
            ('magnetic_total_field_nT','Total field strength (nT)',0.0,100000.0),
            ('magnetic_horizontal_field_nT','Horizontal field strength (nT)',0.0,100000.0),
            ('magnetic_x_nT','X — north component (nT)',-100000.0,100000.0),
            ('magnetic_y_nT','Y — east component (nT)',-100000.0,100000.0),
            ('magnetic_z_nT','Z — down component (nT)',-100000.0,100000.0),
        ]
        cols = st.columns(4)
        manual_values = {}
        for i, (key, label, low, high) in enumerate(fields):
            existing = refdata.get(key)
            default = float(existing) if existing is not None else 0.0
            manual_values[key] = cols[i % 4].number_input(label, min_value=low, max_value=high, value=default, format='%.4f' if 'deg' in key else '%.2f', key='manual_'+key)
        if st.button('Apply manual magnetic values'):
            refdata.update(manual_values)
            refdata['geomagnetic_model'] = 'Manual input'
            refdata['geomagnetic_model_metadata'] = {'model':'Manual input','source':'User supplied','calculation_date':dt_calc.isoformat()}
            project.setdefault('model_metadata', {})['active_geomagnetic_model'] = 'Manual input'
            save()
            st.success('Manual magnetic values saved to the shared project reference.')
    st.markdown('#### Active magnetic values')
    mcols = st.columns(4)
    mcols[0].metric('Declination', f"{float(refdata['magnetic_declination_deg']):.4f}°" if refdata.get('magnetic_declination_deg') is not None else 'Not set')
    mcols[1].metric('Dip', f"{float(refdata['magnetic_dip_deg']):.4f}°" if refdata.get('magnetic_dip_deg') is not None else 'Not set')
    mcols[2].metric('Total field', f"{float(refdata['magnetic_total_field_nT']):.1f} nT" if refdata.get('magnetic_total_field_nT') is not None else 'Not set')
    mcols[3].metric('Horizontal field', f"{float(refdata['magnetic_horizontal_field_nT']):.1f} nT" if refdata.get('magnetic_horizontal_field_nT') is not None else 'Not set')

    st.markdown('#### Grid convergence')
    convergence_mode = st.radio('Grid convergence source', ['Calculate from selected CRS', 'Enter manually'], horizontal=True, key='grid_convergence_mode')
    if convergence_mode == 'Calculate from selected CRS':
        try:
            conv = grid_convergence_deg(float(project['latitude']), float(project['longitude']), project['crs'])
            refdata['grid_convergence_deg'] = conv
            refdata['grid_convergence_source'] = 'Calculated from project CRS and wellhead location'
            st.metric('Grid convergence', f'{conv:.6f}°')
        except Exception as exc:
            st.error(f'Grid convergence calculation failed: {exc}')
    else:
        current_conv = refdata.get('grid_convergence_deg')
        manual_conv = st.number_input('Grid convergence (°; east-positive convention)', min_value=-180.0, max_value=180.0,
            value=float(current_conv) if current_conv is not None else 0.0, format='%.6f', key='manual_grid_convergence')
        if st.button('Apply manual grid convergence'):
            refdata['grid_convergence_deg'] = float(manual_conv)
            refdata['grid_convergence_source'] = 'User supplied'
            save()
            st.success('Manual grid convergence saved to the shared project reference.')
    try:
        grav = normal_gravity(float(project['latitude']), float(project.get('elevation_m', 0.0)))
        refdata['gravity_mps2'] = grav
        st.metric('Normal gravity', f'{grav:.6f} m/s²')
    except Exception as exc:
        st.warning(f'Normal gravity could not be calculated: {exc}')

    with st.expander('Transformation diagnostics'):
        try:
            st.write(crs_info(project['crs']))
            report = transformation_report('EPSG:4326', project['crs'], lon=project.get('longitude'), lat=project.get('latitude'))
            st.write(report)
            st.markdown('**Available and unavailable non-ballpark operations**')
            st.write(transformation_operations('EPSG:4326', project['crs'], lon=project.get('longitude'), lat=project.get('latitude')))
        except Exception as exc:
            st.warning(f'Geodesy diagnostic unavailable: {exc}')
        st.caption('CRS transformations run in the backend. A CRS may be recognized while its high-accuracy datum transformation is unavailable; verify local control and required grid resources before operational use.')

    if st.button('Save project/reference settings',type='primary'): save(); st.success('Saved.')

# Survey Manager
elif page=='Survey Manager':
    page_header('Survey Manager', 'DIRECTIONAL', 'Load, normalize and calculate survey trajectories while preserving the selected azimuth reference and uncertainty assumptions.')
    sm=project['survey_metadata']; ref=project['reference_data']
    req=reference_requirements(project.get('north_reference','Grid North')); st.info(f"**Primary reference: {req['reference']}** — {req['label']}")
    a,b,c=st.columns(3); sm['azimuth_reference']=a.selectbox('Input azimuth reference',['Magnetic North','True North','Grid North'],index=['Magnetic North','True North','Grid North'].index(sm['azimuth_reference'])); tool_options=['MWD','Gyro','Wireline','Planned','Other']; sm['survey_tool']=b.selectbox('Survey tool',tool_options,index=tool_options.index(sm.get('survey_tool','MWD'))); method_options=['Minimum Curvature','Average Angle','Balanced Tangential']; sm['survey_method']=c.selectbox('Calculation method',method_options,index=method_options.index(sm.get('survey_method','Minimum Curvature')))
    if sm.get('survey_method','Minimum Curvature')!='Minimum Curvature': st.warning(f"{sm['survey_method']} is not implemented: all positions are calculated with Minimum Curvature.")
    st.caption('TVDSS is stored as an elevation: TVDSS = KB elevation − TVD (negative below mean sea level).')
    st.caption('Survey position uncertainty is now represented by a covariance-based development model. Configure the survey error parameters on the Anti-Collision page; a legacy scalar sigma remains in the project schema only for backward compatibility.')
    df=pd.DataFrame(project.get('surveys',[])); display_df=(df.copy() if not df.empty else pd.DataFrame([{'MD':0.,'Inc':0.,'Azi':0.}]))
    if 'MD' in display_df.columns: display_df['MD']=display_df['MD']*M_TO_FT
    # Keep the editable survey input at source precision; result tables are rounded for display.
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
        for col in [c for c in sv.columns if c.startswith('Unc_') and c.endswith('_m')]:
            sv[col]=sv[col]*M_TO_FT
        if 'DLS' in sv.columns:
            stored_interval=float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0))
            sv['DLS']=sv['DLS'].map(lambda x: dls_for_interval_to_100ft(x, stored_interval))
        cov_cols=[c for c in sv.columns if c.startswith('Cov_')]
        uncertainty_cols=[c for c in sv.columns if c.startswith('Unc_')]
        display_cols=[c for c in sv.columns if c not in cov_cols+uncertainty_cols]
        sv_display=sv[display_cols].copy()
        for _angle_col in ('Inc','Azi'):
            if _angle_col in sv_display.columns: sv_display[_angle_col]=sv_display[_angle_col].round(2)
        st.dataframe(sv_display,use_container_width=True,hide_index=True)
        # Export display precision for angles without changing the full-precision stored trajectory.
        export_df=sv[display_cols].copy()
        for _angle_col in ('Inc','Azi'):
            if _angle_col in export_df.columns: export_df[_angle_col]=export_df[_angle_col].round(2)
        csv_bytes=export_df.to_csv(index=False).encode('utf-8-sig')
        project_name=''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in str(project.get('well_name') or project.get('project_name') or 'well_survey'))
        st.download_button('Export survey as CSV', data=csv_bytes,
                           file_name=f'{project_name}_survey.csv', mime='text/csv',
                           help='Downloads the displayed survey data in field units. Covariance matrices are excluded; uncertainty summary columns are retained when available.')
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
        _qc_imp=survey_quality_report(imp,'ft')
        for _q in _qc_imp: (st.error if _q['severity']=='ERROR' else st.warning if _q['severity']=='WARN' else st.info)(f"{_q['check']}: {_q['detail']}")
        if st.button('Replace survey with CSV',disabled=any(_q['severity']=='ERROR' for _q in _qc_imp)):
            if {'MD','Inc','Azi'}.issubset(imp.columns): imp['MD']=imp['MD']*FT_TO_M; project['surveys']=imp[['MD','Inc','Azi']].to_dict('records'); save(); st.success('Imported. Calculate & store trajectory to generate positions, TVDSS and DLS.')
            else: st.error('CSV must contain MD, Inc and Azi.')

# Trajectory Planner
elif page=='Trajectory Planner':
    page_header('Trajectory Planner', 'DIRECTIONAL', 'Generate a planning candidate from target geometry and review the resulting trajectory before using it downstream.')
    st.caption('Practice-grade target-driven build/hold planner. The planner works in a well-relative local frame derived from the target and wellhead coordinates.')
    targets=project.get('targets',[])
    valid_targets=[t for t in targets if t.get('name')]
    if not valid_targets: st.warning('Define a valid target first on the Targets page.'); st.stop()
    names=[t.get('name','Target') for t in valid_targets]
    multi_target=st.checkbox('Plan through multiple targets', value=False, help='Select required targets in interception order. The final selected target determines the default planned TD.')
    if multi_target:
        selected_indices=st.multiselect('Required targets — select in interception order', list(range(len(names))), default=[0], format_func=lambda i:names[i], key='planner_target_sequence')
        if not selected_indices:
            st.warning('Select at least one required target.'); st.stop()
        if len(set(selected_indices)) != len(selected_indices):
            st.error('Each target can appear only once in the required sequence.'); st.stop()
        idx=selected_indices[-1]
    else:
        idx=st.selectbox('Target',range(len(names)),format_func=lambda i:names[i])
        selected_indices=[idx]
    t=valid_targets[idx]
    surface_n=float(project.get('surface_northing_m',0)); surface_e=float(project.get('surface_easting_m',0))
    target_sequence=[]
    for target_idx in selected_indices:
        item=valid_targets[target_idx]
        target_sequence.append({**dict(item), 'name':item.get('name','Target'), 'tvd_m':float(project.get('kb_m',0))-float(item.get('tvdss_m',0)), 'north_m':float(item.get('north_m',0))-surface_n, 'east_m':float(item.get('east_m',0))-surface_e, 'geometry':{**dict(item), 'north_m':float(item.get('north_m',0))-surface_n, 'east_m':float(item.get('east_m',0))-surface_e}, 'tolerance_m':float(item.get('tolerance_m',30.48) or 30.48)})
    target_n=float(t.get('north_m',0)); target_e=float(t.get('east_m',0)); rel_n=target_n-surface_n; rel_e=target_e-surface_e
    target_tvdss=float(t.get('tvdss_m',0)); target_tvd=float(project.get('kb_m',0))-target_tvdss
    default_az=(math.degrees(math.atan2(rel_e,rel_n))%360.0) if abs(rel_n)+abs(rel_e)>1e-9 else 0.0
    max_inc=float(project.get('design_constraints',{}).get('max_inclination_deg',57.0) or 57.0)
    default_hold=min(57.0,max_inc)
    # Unified trajectory optimizer: one search engine, one constraint configuration.
    # This action is intentionally independent of the saved profile preset. Profile-based
    # design workflows remain available elsewhere; this engine searches a free-form path.
    profile='Independent (no predefined profile)'
    planning_mode='Independent trajectory optimizer'
    st.markdown('### Independent trajectory optimizer')
    st.caption('This optimizer does not inherit J-, S-, horizontal or ERD profile geometry. It searches a free-form trajectory from the ordered targets and hard constraints; the shared validator independently checks the resulting survey.')
    st.markdown('### Trajectory constraints')
    dc=project.get('design_constraints',{})
    c1,c2,c3=st.columns(3)
    max_inc=float(c1.number_input('Maximum inclination (°)', min_value=1.0, max_value=90.0, value=float(dc.get('max_inclination_deg',70.0) or 70.0), key='unified_max_inc'))
    max_dls_ft=float(c2.number_input('Maximum DLS (°/100 ft)', min_value=0.1, max_value=15.0, value=float(dls_30m_to_100ft(dc.get('max_dls_deg_30m',3.0) or 3.0)), key='unified_max_dls'))
    effort=c3.selectbox('Optimization effort',['Fast','Balanced','Thorough'],index=1,key='unified_effort',help='Presets control the global wall-clock budget and solver iteration limit. Detailed counts are shown in diagnostics.')
    effort_config={'Fast':{'budget':30,'iterations':40,'section_share':0.20},'Balanced':{'budget':90,'iterations':80,'section_share':0.20},'Thorough':{'budget':180,'iterations':140,'section_share':0.20}}
    search_budget_s=float(effort_config[effort]['budget']); max_iter_general=int(effort_config[effort]['iterations'])
    st.caption(f'{effort} effort: up to {search_budget_s:.0f} seconds total search budget, including section reconstruction. All directional changes (build, drop, turn and combined movement) are governed by the single maximum DLS constraint.')

    st.markdown('### Kickoff point (KOP)')
    kop_mode_ui=st.radio('KOP constraint',['Automatic','Fixed MD','Within tolerance'],horizontal=True,key='unified_kop_mode',help='Automatic lets the optimizer choose KOP. Fixed MD constrains it to one measured depth. Within tolerance searches only inside the specified ± window.')
    kop_ref_ft=float(project.get('well_architecture',{}).get('kop_md_m') or 1450.0*FT_TO_M)*M_TO_FT
    kop_md_ft=None; kop_tolerance_ft=0.0; min_kop_m=None; max_kop_m=None
    if kop_mode_ui!='Automatic':
        ka,kb=st.columns(2)
        kop_md_ft=float(ka.number_input('Reference KOP MD (ft)',min_value=0.0,max_value=100000.0,value=float(kop_ref_ft),step=25.0,key='unified_kop_md_ft'))
        if kop_mode_ui=='Within tolerance':
            kop_tolerance_ft=float(kb.number_input('KOP tolerance ± (ft)',min_value=0.0,max_value=10000.0,value=100.0,step=25.0,key='unified_kop_tolerance_ft'))
        else:
            kb.number_input('KOP tolerance ± (ft)',min_value=0.0,max_value=0.0,value=0.0,disabled=True,key='unified_kop_tolerance_fixed')
        min_kop_m=max(0.0,(kop_md_ft-kop_tolerance_ft)*FT_TO_M); max_kop_m=(kop_md_ft+kop_tolerance_ft)*FT_TO_M

    st.markdown('### Search and clearance')
    gc1,gc2=st.columns(2)
    min_clearance_ft=float(gc1.number_input('Minimum centreline clearance (ft)',min_value=0.0,max_value=5000.0,value=float(st.session_state.get('general_min_clearance_ft',100.0)),key='general_min_clearance_ft',help='Additional geometric clearance used during route search; not a substitute for uncertainty-based anti-collision criteria.'))
    min_sf=float(gc2.number_input('Required separation factor',min_value=0.1,max_value=10.0,value=float(st.session_state.get('general_min_sf',2.0)),key='general_min_sf',help='Use company-approved criteria for operational work.'))
    configured_td=project.get('well_architecture',{}).get('planned_td_md_m')
    internal_search_ceiling=max(target_tvd + 4000.0, target_tvd * 3.0, 3000.0)
    use_max_md_limit=st.checkbox('Apply an explicit maximum MD constraint',value=False,help='Off by default. The final TD is determined by target interception.')
    if use_max_md_limit:
        default_limit_ft=float(configured_td)*M_TO_FT if configured_td and float(configured_td)>0 else internal_search_ceiling*M_TO_FT
        max_md_limit_ft=float(st.number_input('Maximum permitted MD (ft)',min_value=100.0,max_value=100000.0,value=float(min(100000.0,max(100.0,default_limit_ft))),step=100.0,key='unified_max_md_ft'))
        provisional_md_limit=max_md_limit_ft*FT_TO_M
    else:
        provisional_md_limit=internal_search_ceiling
        st.caption(f'No explicit maximum MD constraint. Internal search ceiling: {provisional_md_limit*M_TO_FT:,.0f} ft MD.')
    if target_tvd<=0: st.error('Target TVD must be positive after applying the KB/TVDSS reference conversion.'); st.stop()
    st.warning('Planning outputs are engineering-development candidates. Review trajectory constraints, target interception, survey uncertainty and anti-collision results before operational use.')

    if st.button('Optimize trajectory',type='primary',use_container_width=True):
        try:
            sigma_params=dict(project.get('survey_metadata',{}).get('survey_error_parameters',{}))
            out,meta=optimize_general_trajectory(
                targets=target_sequence,
                max_md_m=provisional_md_limit,
                max_inclination_deg=max_inc,
                max_dls_deg_30m=dls_100ft_to_30m(max_dls_ft),
                station_interval_m=30.0, maxiter=max_iter_general,
                surface_easting_m=surface_e, surface_northing_m=surface_n,
                offsets=project.get('offsets',[]),
                min_centerline_separation_m=min_clearance_ft*FT_TO_M,
                required_separation_factor=min_sf,
                uncertainty_parameters=sigma_params,
                target_tolerance_m=30.48, control_points=6,
                kb_m=float(project.get('kb_m',0) or 0), time_budget_s=search_budget_s,
                min_kop_md_m=min_kop_m, max_kop_md_m=max_kop_m,
                section_reoptimize=True, section_time_budget_s=search_budget_s*effort_config[effort]['section_share'],
            )
            # Quantize the accepted survey stations before independent validation and persistence.
            # Solver iterations deliberately retain full precision for numerical convergence; the
            # trajectory delivered to the rest of the application is defined by 0.01-degree Inc/Azi.
            out=out.copy()
            out['Inc']=pd.to_numeric(out['Inc'],errors='raise').round(2)
            out['Azi']=(pd.to_numeric(out['Azi'],errors='raise').round(2) % 360.0).round(2)
            # Recompute positions and DLS from the quantized station angles so stored geometry,
            # target checks, and downstream engineering modules all use the same trajectory.
            out=minimum_curvature(out[['MD','Inc','Azi']])
            meta=dict(meta); meta['planning_mode']=planning_mode; meta['profile']='Independent (no predefined profile)'
            meta['trajectory_angle_precision_deg']=2
            meta['trajectory_angle_precision_note']='Accepted/stored survey angles are rounded to 0.01°. Positions, DLS and acceptance checks are recomputed from these rounded stations; solver iterations retain full precision for numerical convergence.'
            meta['effort_preset']=effort; meta['configured_constraints']={'max_inclination_deg':max_inc,'max_dls_deg_30m':dls_100ft_to_30m(max_dls_ft)}
            meta['kop_mode_ui']=kop_mode_ui; meta['kop_reference_md_ft']=kop_md_ft; meta['kop_tolerance_ft']=kop_tolerance_ft
    # ---- Independent acceptance for EVERY planning mode --------------------------------------
            # A generator's or optimizer's own verdict never decides validity. The candidate is rebuilt
            # from MD/Inc/Azi and re-checked (constraints between stations, ordered target interception,
            # termination at the final target, offset clearance) before it can be PASS.
            _req_sf=float(min_sf)
            _val=validate_trajectory(out[['MD','Inc','Azi']], targets=target_sequence,
                constraints={'max_inclination_deg':max_inc,'max_dls_deg_30m':dls_100ft_to_30m(max_dls_ft),
                             'max_md_m':provisional_md_limit,
                             'min_kop_md_m':min_kop_m,'max_kop_md_m':max_kop_m},
                offsets=project.get('offsets',[]), surface_easting_m=surface_e, surface_northing_m=surface_n,
                kb_m=float(project.get('kb_m',0) or 0), survey_error_model=dict(project.get('survey_metadata',{}).get('survey_error_parameters',{})),
                required_separation_factor=_req_sf, default_target_tolerance_m=30.48)
            meta=dict(meta)
            meta['validation_status']=_val['status']; meta['validation_checks']=to_jsonable(_val['checks']); meta['survey_hash']=_val['survey_hash']
            meta['validator_version']=_val['validator_version']
            # Replace optimizer metrics with metrics measured from the quantized, independently
            # rebuilt trajectory; do not leave the UI showing pre-rounding geometry.
            _qm=_val.get('metrics',{})
            for _src,_dst in (('max_inclination_deg','max_inclination_deg'),('max_dls_deg_30m','max_dls_deg_30m')):
                if _src in _qm: meta[_dst]=float(_qm[_src])
            if len(out):
                meta['final_md_m']=float(out['MD'].iloc[-1]); meta['final_inclination_deg']=float(out['Inc'].iloc[-1]); meta['final_azimuth_deg']=float(out['Azi'].iloc[-1])
                meta['endpoint_north_m']=float(out['Northing'].iloc[-1]); meta['endpoint_east_m']=float(out['Easting'].iloc[-1]); meta['endpoint_tvd_m']=float(out['TVD'].iloc[-1])
            if _val.get('target_results'):
                meta['target_sequence_feasible']=all(bool(r.get('within_tolerance')) and bool(r.get('in_order')) for r in _val['target_results'])
                meta['target_sequence_results']=to_jsonable(_val['target_results'])
            if _val['status']!='PASS':
                meta['status']='REVIEW'; meta['final_md_is_target_intercept']=False
                if meta.get('optimization_status')=='FEASIBLE': meta['optimization_status']='REVIEW'
                meta['constraint_violations']=sorted(set(meta.get('constraint_violations',[]))|set(_val['violations']))
                # Keep full failed multi-target candidates visible for diagnosis.
                # Clipping at the first missed target can misleadingly look like the
                # optimizer stopped there instead of showing the attempted route to later targets.
                if len(target_sequence) <= 1 and meta.get('display_clip_md_m') is None:
                    _bad=next((r for r in _val['target_results'] if not (r.get('within_tolerance') and r.get('in_order'))), (_val['target_results'][-1] if _val['target_results'] else None))
                    if _bad and _bad.get('intercept_md_m') is not None and math.isfinite(float(_bad['intercept_md_m'])): meta['display_clip_md_m']=float(_bad['intercept_md_m'])+30.48
            meta['result_class']='PASS' if meta['status']=='PASS' else meta.get('result_class') or ('REVIEW' if meta.get('optimization_status') not in ('NO_FEASIBLE_CANDIDATE_FOUND',) else 'NO FEASIBLE CANDIDATE FOUND')
            # Preserve a dedicated planned candidate as well as the legacy active survey.
            # Survey Manager may later replace project['surveys'] with imported/measured data;
            # returning here must still restore the saved planner candidate.
            records=out.to_dict('records')
            project['planned_surveys']=records
            _prev_traj_meta=project.get('trajectory_metadata'); _prev_surveys=project.get('surveys'); _prev_src=(_prev_traj_meta or {}).get('survey_source')
            if meta.get('status')=='PASS':
                # Only a validated plan becomes the active survey. Measured/imported survey data is backed up, never silently lost.
                if _prev_surveys and len(_prev_surveys)>1 and _prev_src!='planned':
                    project['survey_backup']={'surveys':_prev_surveys,'trajectory_metadata':_prev_traj_meta,'saved_utc':datetime.utcnow().isoformat()+'Z','reason':'Replaced by a validated planner trajectory.'}
                project['surveys']=records
            # Do not overwrite the user's saved profile preset with the independent optimizer label.
            project['trajectory_metadata']={'planner':meta.get('planner', 'General control-point trajectory optimizer'),'planner_result':meta,'profile':profile,'planning_mode':planning_mode,'dls_interval_m':30.0,'dls_interval_ft':30.0*M_TO_FT,'calculated_utc':datetime.utcnow().isoformat()+'Z','survey_source':'planned'}
            project['planned_trajectory_metadata']=dict(project['trajectory_metadata'])
            attach_snapshot(project, project['planned_trajectory_metadata'], [x['name'] for x in target_sequence])
            if meta.get('status')=='PASS': project['trajectory_metadata']=dict(project['planned_trajectory_metadata'])
            elif _prev_traj_meta is None: project.pop('trajectory_metadata',None)
            else: project['trajectory_metadata']=_prev_traj_meta
            save()
            if meta.get('status')=='PASS': st.success('Validated trajectory saved and made the active survey. You can leave this page and return without recalculating it.')
            else: st.warning('Candidate saved as REVIEW for inspection only. It was NOT written to the active survey, so Survey Manager data and downstream modules are unchanged.')
        except Exception as ex:
            st.error(str(ex))

    # Render the saved candidate on every visit, not only during the button-click rerun.
    # This keeps results visible after navigation and makes display controls independent of calculation.
    saved_meta_bundle=project.get('planned_trajectory_metadata') or (project.get('trajectory_metadata') if project.get('trajectory_metadata',{}).get('survey_source')=='planned' else None)
    saved_records=project.get('planned_surveys') or (project.get('surveys',[]) if saved_meta_bundle else [])
    if saved_meta_bundle and saved_records:
        meta=saved_meta_bundle.get('planner_result',{})
        saved_profile=saved_meta_bundle.get('profile',meta.get('profile',profile))
        saved_mode=saved_meta_bundle.get('planning_mode',meta.get('planning_mode','Unknown'))
        st.markdown('### Saved trajectory candidate')
        st.caption(f"Saved profile: **{saved_profile}** • Mode: **{saved_mode}** • Calculated: {saved_meta_bundle.get('calculated_utc','time not recorded')} • This is the saved result; changing controls above does not recalculate it.")
        result_line=f"Profile: {saved_profile} • status {meta.get('status','REVIEW')} • lateral error {float(meta.get('lateral_error_m',meta.get('target_lateral_error_m',float('nan'))))*M_TO_FT:.1f} ft • TVD error {float(meta.get('tvd_error_m',meta.get('target_vertical_error_m',float('nan'))))*M_TO_FT:.1f} ft • final inclination {float(meta.get('final_inclination_deg',0.0)):.2f}°"
        if meta.get('status')=='PASS': st.success(result_line)
        else: st.warning(result_line + ' • Target/profile feasibility needs review.')
        for _sr in saved_meta_bundle.get('stale_reasons',[]): st.warning(f'Dependency changed after planning: {_sr}')
        _proof=meta.get('proof_of_infeasibility')
        if _proof: st.error('Proven infeasible (analytic bound, not a search failure): ' + ' '.join(_proof.get('reasons',[])))
        elif meta.get('optimization_status')=='NO_FEASIBLE_CANDIDATE_FOUND': st.info('NO FEASIBLE CANDIDATE FOUND means this search did not find a valid trajectory — it does not prove that none exists.')
        if meta.get('validation_checks'):
            with st.expander(f"Validation details · {meta.get('validation_status','—')}", expanded=False):
                st.dataframe(pd.DataFrame(meta['validation_checks']).astype(str),use_container_width=True,hide_index=True)
                st.caption('Every candidate — optimized or manual — is rebuilt from MD/Inc/Azi and re-checked before it can be PASS. PASS means the checks implemented here passed; it is not operational certification.')
        if meta.get('target_intercept_md_m') is not None:
            st.caption(f"Best target approach: {float(meta['target_intercept_md_m'])*M_TO_FT:,.1f} ft MD • target miss beyond tolerance: {float(meta.get('target_miss_distance_m',max(0.0,float(meta.get('lateral_error_m',0))-30.48)))*M_TO_FT:,.1f} ft")
        if meta.get('target_sequence_results'):
            st.markdown('#### Required target sequence')
            seq_display=pd.DataFrame(meta['target_sequence_results']).copy()
            if 'intercept_md_m' in seq_display: seq_display['intercept_md_ft']=seq_display['intercept_md_m']*M_TO_FT
            for col in ['lateral_error_m','vertical_error_m','miss_distance_m']:
                if col in seq_display: seq_display[col.replace('_m','_ft')]=seq_display[col]*M_TO_FT
            st.dataframe(seq_display.drop(columns=[c for c in ['intercept_md_m','lateral_error_m','vertical_error_m','miss_distance_m'] if c in seq_display]),use_container_width=True,hide_index=True)
            st.caption('All required targets must be intercepted in order. The final required target defines the target-terminated TD when the complete trajectory is feasible.')
        if meta.get('section_schedule') is not None and saved_mode in ('General trajectory optimizer (experimental)', 'Trajectory Optimizer', 'Independent trajectory optimizer'):
            st.markdown('#### Section schedule')
            _sstat=meta.get('section_reconstruction_status','—')
            _s2summary=meta.get('stage2_summary') or meta.get('section_reconstruction_note','Sectionization status unavailable.')
            (st.success if _sstat=='REOPTIMIZED' else st.info if _sstat in ('CLASSIFIED_ONLY','NOT_ATTEMPTED_INFEASIBLE_BASE') else st.warning)(f"**Stage 2 · {_sstat}** — {_s2summary}")
            _sched=pd.DataFrame(meta['section_schedule'])
            if not _sched.empty:
                _v=pd.DataFrame({'Section':_sched.get('section',pd.Series(range(1,len(_sched)+1))),'Type':_sched['type'],
                    'Start MD (ft)':_sched['start_md_m']*M_TO_FT,'End MD (ft)':_sched['end_md_m']*M_TO_FT,'Length (ft)':(_sched['end_md_m']-_sched['start_md_m'])*M_TO_FT,
                    'Start inc (°)':_sched['start_inc_deg'],'End inc (°)':_sched['end_inc_deg'],'Start azi (°)':_sched['start_azi_deg'],'End azi (°)':_sched['end_azi_deg'],
                    'Build/drop (°/100 ft)':_sched['build_drop_rate_deg_30m'].map(dls_30m_to_100ft),'Turn (°/100 ft)':_sched['turn_rate_deg_30m'].map(dls_30m_to_100ft),
                    'Max DLS (°/100 ft)':_sched['max_dls_deg_30m'].map(dls_30m_to_100ft)})
                for _angle_col in ('Start inc (°)','End inc (°)','Start azi (°)','End azi (°)'):
                    if _angle_col in _v.columns: _v[_angle_col]=_v[_angle_col].round(2)
                st.dataframe(_v,use_container_width=True,hide_index=True)
            _chk=meta.get('section_schedule_constraint_check',{})
            if _chk.get('violations'): st.error('Section-schedule constraint violations: '+'; '.join(_chk['violations']))
            _attempts=(meta.get('section_reoptimization') or {}).get('attempts',[])
            if _attempts and _sstat!='REOPTIMIZED':
                with st.expander(f"Sectionization diagnostics · {len(_attempts)} attempts", expanded=False):
                    _diag=pd.DataFrame([{'Sections':a.get('sections'),'Mode':a.get('mode'),'Solver':('converged' if a.get('solver_success') else 'not converged'),'Validation':a.get('validation_status','not validated'),'Issues':', '.join(map(str,a.get('violations') or [])) or '—','Message':str(a.get('message',''))[:140]} for a in _attempts])
                    st.dataframe(_diag,use_container_width=True,hide_index=True)
            _s1,_fm=meta.get('stage1_metrics'),meta.get('final_metrics')
            if _s1 and _fm:
                st.markdown('#### Trajectory comparison: Stage 1 feasible path vs final')
                _rows=[('Final MD (ft)','final_md_m',M_TO_FT),('Final TVD (ft)','final_tvd_m',M_TO_FT),('KOP MD (ft)','kop_md_m',M_TO_FT),('Max inclination (°)','max_inclination_deg',1.0),
                       ('Max DLS (°/100 ft)','max_dls_deg_30m',dls_30m_to_100ft(1.0))]
                _comparison=pd.DataFrame([{'Metric':lbl,'Stage 1':float(_s1[k])*f,'Final':float(_fm[k])*f,'Change':(float(_fm[k])-float(_s1[k]))*f} for lbl,k,f in _rows])
                _angle_metrics=_comparison['Metric'].str.contains('inclination|azimuth',case=False,regex=True)
                for _col in ('Stage 1','Final','Change'):
                    _comparison.loc[_angle_metrics,_col]=_comparison.loc[_angle_metrics,_col].round(2)
                st.dataframe(_comparison,use_container_width=True,hide_index=True)
        if meta.get('validation_checks'):
            _mrows=constraint_margin_rows(meta['validation_checks'])
            if _mrows:
                with st.expander('Constraint margins', expanded=False):
                    _m=pd.DataFrame(_mrows); st.dataframe(_m.astype({c:'object' for c in _m.columns}),use_container_width=True,hide_index=True)
                    st.caption('Positive margin means inside the limit. Target rows show miss distance.')
        if saved_mode in ('Optimize selected profile to target', 'Optimize (free KOP)', 'Optimize (fixed KOP)', 'Optimize (KOP window)', 'General trajectory optimizer (experimental)', 'Trajectory Optimizer'):
            st.metric('Optimization outcome',meta.get('optimization_status','REVIEW'))
            st.caption(f"Objective score: {float(meta.get('objective_m',float('nan'))):.2f} m • Evaluations: {meta.get('optimizer_evaluations','—')} • Max DLS: {float(meta.get('max_dls_deg_30m',float('nan'))):.2f}°/30 m")
            if meta.get('optimization_status')!='FEASIBLE': st.warning('**Stage 1 · No validated path found.** ' + str(meta.get('stage1_summary','The best candidate is for review only; constraints were not relaxed.')))
            if saved_mode in ('General trajectory optimizer (experimental)', 'Trajectory Optimizer', 'Independent trajectory optimizer'):
                st.caption('**Stage 1 · ' + str(meta.get('stage1_summary','See diagnostics for details.')) + '**')
                with st.expander('Optimizer diagnostics', expanded=False):
                    st.caption(f"Solver: {meta.get('optimizer','—')} • Iterations: {meta.get('optimizer_iterations','—')} • Solves: {meta.get('search_solves',meta.get('optimizer_solves','—'))} • Elapsed: {meta.get('search_seconds','—')} s / {meta.get('search_budget_s','—')} s")
                    st.caption(f"Effort: {meta.get('effort_preset','—')} • Budget exhausted: {meta.get('search_budget_exhausted',False)} • KOP mode: {meta.get('kop_mode_ui','Automatic')} • Solver message: {meta.get('optimizer_message','—')}")
                    if meta.get('constraint_violations'): st.write('Validation issues:', ', '.join(map(str, meta.get('constraint_violations',[])[:8])))
                if meta.get('constraint_violations') and meta.get('optimization_status')=='FEASIBLE':
                    st.warning('Some checks need review: ' + ', '.join(map(str, meta.get('constraint_violations', [])[:3])) + (' …' if len(meta.get('constraint_violations', []))>3 else ''))
                if meta.get('collision_validation'):
                    st.markdown('#### Offset-well clearance validation')
                    collision_view=pd.DataFrame(meta['collision_validation'])
                    for cc in ['main_md_m','offset_md_m','separation_m','horizontal_separation_m','vertical_separation_m','directional_uncertainty_m','minimum_sf_separation_m','minimum_sf_directional_uncertainty_m','minimum_sf_main_md_m','minimum_sf_offset_md_m']:
                        if cc in collision_view: collision_view[cc.replace('_m','_ft')]=collision_view[cc]*M_TO_FT
                    st.dataframe(collision_view,use_container_width=True,hide_index=True)
                    st.caption('Clearance is independently screened with the configured covariance-based development model. Any WARNING, ALERT, REVIEW or NOT CHECKED result prevents an overall PASS.')
        m1,m2,m3,m4=st.columns(4)
        m1.metric('Build end / EOB',f"{float(meta.get('build_end_md_m',0))*M_TO_FT:,.0f} ft")
        m2.metric('Build length',f"{float(meta.get('build_length_m',0))*M_TO_FT:,.0f} ft")
        m3.metric('Final MD',f"{float(meta.get('final_md_m',float(pd.DataFrame(saved_records).iloc[-1].get('MD',0))))*M_TO_FT:,.0f} ft")
        m4.metric('Final inclination',f"{float(meta.get('final_inclination_deg',pd.DataFrame(saved_records).iloc[-1].get('Inc',0))):.1f}°")
        detail=st.radio('Survey table detail',['Section endpoints (compact)','Full survey stations'],horizontal=True,index=0,key='planner_survey_detail',help='This only changes the displayed rows. The saved candidate is retained when navigating between pages.')
        display_source=pd.DataFrame(saved_records).copy().reset_index(drop=True)
        if detail=='Section endpoints (compact)' and not display_source.empty:
            section_ends=meta.get('section_end_md_m',{})
            selected_indices={0,len(display_source)-1}; marker_names={}
            for section_name, section_md in section_ends.items():
                if section_md is not None:
                    marker_idx=int((display_source['MD']-float(section_md)).abs().idxmin())
                    selected_indices.add(marker_idx); marker_names.setdefault(marker_idx,[]).append(section_name)
            target_md=meta.get('target_intercept_md_m')
            if target_md is not None:
                marker_idx=int((display_source['MD']-float(target_md)).abs().idxmin())
                selected_indices.add(marker_idx); marker_names.setdefault(marker_idx,[]).append('Best target approach (nearest station)')
            selected_sorted=sorted(selected_indices); display_source=display_source.iloc[selected_sorted].copy()
            labels=[]
            for original_idx in selected_sorted:
                names_here=marker_names.get(original_idx,[])
                if original_idx==0: names_here=['Start']+names_here
                labels.append(' / '.join(dict.fromkeys(names_here)) if names_here else 'Station')
            display_source.insert(0,'Section / marker',labels)
        out_display=display_source.copy()
        for cc in ['MD','TVD','Northing','Easting','VS']:
            if cc in out_display.columns: out_display[cc]=out_display[cc]*M_TO_FT
        if 'TVD' in display_source.columns: out_display['TVDSS']=(float(project.get('kb_m',0))-display_source['TVD'])*M_TO_FT
        if 'DLS' in out_display.columns: out_display['DLS']=out_display['DLS'].map(lambda x:dls_for_interval_to_100ft(x,30.0))
        for _angle_col in ('Inc','Azi'):
            if _angle_col in out_display.columns: out_display[_angle_col]=out_display[_angle_col].round(2)
        st.dataframe(out_display,use_container_width=True,hide_index=True)
    elif project.get('surveys'):
        st.info('No saved trajectory-planner candidate is available yet. The Survey Manager may contain an imported or measured survey; generate a candidate here to create a persistent planned result.')

# Targets
elif page=='Targets':
    page_header('Target Management', 'SETUP', 'Create and manage targets in the project CRS. Absolute grid Easting/Northing are entered and stored in metres; target depth, tolerances and dimensions remain in field units on the interface and are converted internally.')
    st.caption('Target coordinates are absolute project coordinates; the trajectory planner converts them to offsets from the wellhead automatically.')
    types=['Point','Circular','Elliptical','Rectangular','Corridor','Polygon']; typ=st.selectbox('New target type',types); a,b,c=st.columns(3); name=a.text_input('Target name','Target-01'); n=a.number_input('Center grid Northing (m)',-10000000.,10000000.,float(project.get('surface_northing_m',0)),format='%.3f'); e=b.number_input('Center grid Easting (m)',-10000000.,10000000.,float(project.get('surface_easting_m',0)),format='%.3f');
    if project.get('depth_reference','MD / TVDSS')=='MD / TVDSS':
        tvdss=c.number_input('Target TVDSS (ft)',-50000.,50000.,-12000.)
    else:
        tvd=c.number_input('Target TVD (ft)',0.,50000.,12000.); tvdss=(float(project.get('kb_m',0))-tvd*FT_TO_M)*M_TO_FT
    t={'name':name,'type':typ,'north_m':n,'east_m':e,'tvdss_m':tvdss*FT_TO_M,'crs':project.get('crs'),'grid_units':'m'}
    with st.expander('Target tolerance and thickness', expanded=False):
        ta,tb,tc=st.columns(3)
        t['tolerance_m']=ta.number_input('Lateral tolerance (ft)',0.0,5000.0,100.0,key='target_tol_ft',help='Point targets use a fixed 2 ft 3-D acceptance radius around the centre; optimization still aims for zero miss. For non-point targets, this is the lateral tolerance and default vertical band.')*FT_TO_M
        t['vertical_tolerance_m']=tb.number_input('Vertical tolerance (ft)',0.0,5000.0,100.0,key='target_vtol_ft')*FT_TO_M
        t['thickness_m']=tc.number_input('Target thickness (ft, 0 = not used)',0.0,5000.0,0.0,key='target_thick_ft',help='True vertical thickness of the target layer; the vertical acceptance band is at least half of it.')*FT_TO_M
    with st.expander('Advanced target orientation and approach constraints', expanded=False):
        t['inclined_plane_enabled']=st.checkbox('Define an inclined geological target plane', key='target_plane_enabled')
        if t['inclined_plane_enabled']:
            oa,ob=st.columns(2)
            t['dip_deg']=oa.number_input('Target dip (°)',0.0,89.0,25.0,key='target_dip_deg')
            t['dip_direction_deg']=ob.number_input('Dip direction (° from project north)',0.0,360.0,135.0,key='target_dip_direction')
        else:
            t['dip_deg']=0.0; t['dip_direction_deg']=0.0
        t['approach_azimuth_enabled']=st.checkbox('Constrain wellbore azimuth at target',key='target_approach_az_enabled')
        if t['approach_azimuth_enabled']:
            oa,ob=st.columns(2)
            t['approach_azimuth_deg']=oa.number_input('Required approach azimuth (° Grid)',0.0,360.0,0.0,key='target_approach_az')
            t['approach_azimuth_tolerance_deg']=ob.number_input('Azimuth tolerance (°)',0.1,90.0,10.0,key='target_approach_az_tol')
        t['approach_inclination_enabled']=st.checkbox('Constrain wellbore inclination at target',key='target_approach_inc_enabled')
        if t['approach_inclination_enabled']:
            oa,ob=st.columns(2)
            t['approach_inclination_deg']=oa.number_input('Required approach inclination (°)',0.0,180.0,85.0,key='target_approach_inc')
            t['approach_inclination_tolerance_deg']=ob.number_input('Inclination tolerance (°)',0.1,90.0,5.0,key='target_approach_inc_tol')
        t['intersection_angle_enabled']=st.checkbox('Constrain angle between wellbore and target plane',key='target_intersection_angle_enabled')
        if t['intersection_angle_enabled']:
            oa,ob=st.columns(2)
            t['min_intersection_angle_deg']=oa.number_input('Minimum plane-intersection angle (°)',0.0,90.0,45.0,key='target_min_intersection_angle')
            t['max_intersection_angle_deg']=ob.number_input('Maximum plane-intersection angle (°)',0.0,90.0,90.0,key='target_max_intersection_angle')
            if t['min_intersection_angle_deg'] > t['max_intersection_angle_deg']:
                st.error('Minimum plane-intersection angle must not exceed maximum angle.')
    if typ=='Circular': t['radius_m']=st.number_input('Radius (ft)',.1,10000.,50.)*FT_TO_M
    elif typ=='Elliptical':
        a,b,c=st.columns(3); t['semi_major_m']=a.number_input('Semi-major axis (ft)',.1,10000.,131.); t['semi_major_m']*=FT_TO_M; t['semi_minor_m']=b.number_input('Semi-minor axis (ft)',.1,10000.,66.)*FT_TO_M; t['orientation_deg']=c.number_input('Orientation from North (°)',-360.,360.,45.)
    elif typ=='Rectangular':
        a,b,c=st.columns(3); t['length_m']=a.number_input('Length along orientation (ft)',.1,10000.,200.)*FT_TO_M; t['width_m']=b.number_input('Width across orientation (ft)',.1,10000.,100.)*FT_TO_M; t['orientation_deg']=c.number_input('Length-axis azimuth from North (°)',-360.,360.,0.,key='rect_orientation')
    elif typ=='Corridor':
        a,b,c=st.columns(3); t['half_length_m']=a.number_input('Half-length (ft)',.1,20000.,1000.)*FT_TO_M; t['half_width_m']=b.number_input('Half-width (ft)',.1,5000.,50.)*FT_TO_M; t['azimuth_deg']=c.number_input('Corridor azimuth (°)',0.,360.,0.)
    elif typ=='Polygon':
        txt=st.text_area('Polygon vertices as North,East OFFSETS from the target centre, in metres (one per line)','-50,-50\n-50,50\n50,50\n50,-50'); pts=[]
        for line in txt.splitlines():
            try: nn,ee=[float(x.strip()) for x in line.split(',')[:2]]; pts.append([nn,ee])
            except Exception: pass
        t['points']=pts
    if st.button('Add target',type='primary'):
        if not name.strip(): st.error('Target name is required.')
        elif t.get('intersection_angle_enabled') and float(t.get('min_intersection_angle_deg',0)) > float(t.get('max_intersection_angle_deg',90)): st.error('Minimum plane-intersection angle must not exceed maximum angle.')
        elif not __import__('pyproj').CRS.from_user_input(project.get('crs','EPSG:4326')).is_projected: st.error('Select a projected project CRS before creating an absolute-coordinate target.')
        else: project['targets'].append(t); save(); st.success('Target added.')
    if project['targets']:
        td=pd.DataFrame(project['targets']).copy()
        for col in ['tvdss_m','radius_m','semi_major_m','semi_minor_m','length_m','width_m','half_length_m','half_width_m']:
            if col in td.columns: td[col.replace('_m','_ft')]=td[col]*M_TO_FT; td.drop(columns=[col],inplace=True)
        td=td.rename(columns={'north_m':'Grid Northing (m)','east_m':'Grid Easting (m)','tvdss_ft':'TVDSS (ft)','tolerance_ft':'Tolerance (ft)'})
        st.dataframe(td,use_container_width=True,hide_index=True)
        st.markdown('#### Delete a target')
        delete_idx=st.selectbox('Select target to delete',range(len(project['targets'])),format_func=lambda i: project['targets'][i].get('name',f'Target {i+1}'),key='delete_target_index')
        confirm_delete=st.checkbox('I understand that deleting this target may invalidate a saved trajectory.',key='confirm_delete_target')
        if st.button('Delete selected target',disabled=not confirm_delete):
            deleted_name=str(project['targets'][delete_idx].get('name',f'Target {delete_idx+1}'))
            del project['targets'][delete_idx]
            for bundle_key in ('planned_trajectory_metadata','trajectory_metadata'):
                bundle=project.get(bundle_key) or {}
                result=bundle.get('planner_result',{})
                seq=result.get('target_sequence_results',[])
                if any(str(x.get('name'))==deleted_name for x in seq):
                    result['status']='REVIEW'; result['optimization_status']='REVIEW'
                    result.setdefault('constraint_violations',[]).append('target_deleted_after_planning')
                    bundle['stale_reason']=f'Target {deleted_name} was deleted after this trajectory was generated; regenerate and revalidate the plan.'
                    project[bundle_key]=bundle
            save(); st.warning(f'Target {deleted_name} deleted. Any saved trajectory that depended on it is marked REVIEW; regenerate it before relying on the result.'); st.rerun()

    if project['targets']:
        st.markdown('#### Edit a target')
        st.caption('Editing a target that a saved trajectory depends on automatically marks that trajectory REVIEW until it is regenerated and revalidated.')
        edit_idx=st.selectbox('Select target to edit',range(len(project['targets'])),format_func=lambda i: project['targets'][i].get('name',f'Target {i+1}'),key='edit_target_index')
        et=dict(project['targets'][edit_idx]); typ_e=str(et.get('type','Point')); k=f'{edit_idx}'
        st.caption(f'Geometry type: **{typ_e}** — to change the geometry type, create a new target.')
        ea,eb,ec=st.columns(3)
        et['name']=ea.text_input('Name',str(et.get('name','')),key=f'edit_name_{k}')
        en=eb.number_input('Center grid Northing (m)',-10000000.,10000000.,float(et.get('north_m',0)),format='%.3f',key=f'edit_n_{k}')
        ee=ec.number_input('Center grid Easting (m)',-10000000.,10000000.,float(et.get('east_m',0)),format='%.3f',key=f'edit_e_{k}')
        eta,etb,etc=st.columns(3)
        etv=eta.number_input('Target TVDSS (ft)',-50000.,50000.,float(et.get('tvdss_m',0))*M_TO_FT,key=f'edit_tvdss_{k}')
        etol=etb.number_input('Lateral tolerance (ft)',0.0,5000.0,float(et.get('tolerance_m',30.48))*M_TO_FT,key=f'edit_tol_{k}')
        evt=etc.number_input('Vertical tolerance (ft)',0.0,5000.0,float(et.get('vertical_tolerance_m',et.get('tolerance_m',30.48)))*M_TO_FT,key=f'edit_vtol_{k}')
        eda,edb,edc=st.columns(3)
        eth=eda.number_input('Thickness (ft, 0 = none)',0.0,5000.0,float(et.get('thickness_m',0.0))*M_TO_FT,key=f'edit_thick_{k}')
        edip=edb.number_input('Dip (°)',0.0,89.0,float(et.get('dip_deg',0.0) or 0.0),key=f'edit_dip_{k}')
        eddir=edc.number_input('Dip direction (° from project north)',0.0,360.0,float(et.get('dip_direction_deg',0.0) or 0.0),key=f'edit_dipdir_{k}')
        if typ_e=='Circular': et['radius_m']=st.number_input('Radius (ft)',.1,10000.,max(.1,float(et.get('radius_m',15))*M_TO_FT),key=f'edit_r_{k}')*FT_TO_M
        elif typ_e=='Elliptical':
            xa,xb,xc=st.columns(3); et['semi_major_m']=xa.number_input('Semi-major (ft)',.1,10000.,max(.1,float(et.get('semi_major_m',40))*M_TO_FT),key=f'edit_a_{k}')*FT_TO_M; et['semi_minor_m']=xb.number_input('Semi-minor (ft)',.1,10000.,max(.1,float(et.get('semi_minor_m',20))*M_TO_FT),key=f'edit_b_{k}')*FT_TO_M; et['orientation_deg']=xc.number_input('Orientation from North (°)',-360.,360.,float(et.get('orientation_deg',0)),key=f'edit_o_{k}')
        elif typ_e=='Rectangular':
            xa,xb,xc=st.columns(3); et['length_m']=xa.number_input('Length (ft)',.1,10000.,max(.1,float(et.get('length_m',60))*M_TO_FT),key=f'edit_l_{k}')*FT_TO_M; et['width_m']=xb.number_input('Width (ft)',.1,10000.,max(.1,float(et.get('width_m',30))*M_TO_FT),key=f'edit_w_{k}')*FT_TO_M; et['orientation_deg']=xc.number_input('Length-axis azimuth (°)',-360.,360.,float(et.get('orientation_deg',0) or 0),key=f'edit_ro_{k}')
        elif typ_e=='Corridor':
            xa,xb,xc=st.columns(3); et['half_length_m']=xa.number_input('Half-length (ft)',.1,20000.,max(.1,float(et.get('half_length_m',300))*M_TO_FT),key=f'edit_hl_{k}')*FT_TO_M; et['half_width_m']=xb.number_input('Half-width (ft)',.1,5000.,max(.1,float(et.get('half_width_m',15))*M_TO_FT),key=f'edit_hw_{k}')*FT_TO_M; et['azimuth_deg']=xc.number_input('Corridor azimuth (°)',0.,360.,float(et.get('azimuth_deg',0)),key=f'edit_ca_{k}')
        elif typ_e=='Polygon':
            txt_e=st.text_area('Polygon vertices as North,East offsets from the centre (metres, one per line)','\n'.join(f'{p[0]},{p[1]}' for p in et.get('points',[])),key=f'edit_poly_{k}'); pts_e=[]
            for line in txt_e.splitlines():
                try: nn,ee2=[float(x.strip()) for x in line.split(',')[:2]]; pts_e.append([nn,ee2])
                except Exception: pass
            et['points']=pts_e
        if st.button('Save changes to target',type='primary',key=f'edit_save_{k}'):
            other_names=[str(x.get('name')) for j,x in enumerate(project['targets']) if j!=edit_idx]
            if not str(et['name']).strip(): st.error('Target name is required.')
            elif str(et['name']) in other_names: st.error('Another target already uses this name.')
            elif typ_e=='Polygon' and len(et.get('points',[]))<3: st.error('A polygon needs at least three valid vertices.')
            else:
                et.update({'north_m':en,'east_m':ee,'crs':project.get('crs'),'grid_units':'m','tvdss_m':etv*FT_TO_M,'tolerance_m':etol*FT_TO_M,'vertical_tolerance_m':evt*FT_TO_M,'thickness_m':eth*FT_TO_M,'dip_deg':edip,'dip_direction_deg':eddir,'inclined_plane_enabled':bool(edip>0)})
                project['targets'][edit_idx]=et; save(); st.success('Target updated. Any saved trajectory that depends on it is now marked REVIEW until regenerated.'); st.rerun()

# Offsets
elif page=='Offsets':
    page_header('Offset Wells', 'SETUP', 'Create independent reference wells. Surface latitude/longitude are transformed automatically into the project CRS; relative project-grid offsets are then derived.')
    a,b,c=st.columns(3); name=a.text_input('Offset name','OW-01'); lat=b.number_input('Offset latitude',-90.,90.,float(project['latitude']),format='%.6f'); lon=c.number_input('Offset longitude',-180.,180.,float(project['longitude']),format='%.6f')
    try:
        _off_e_native,_off_n_native=transform_coordinates(lon,lat,'EPSG:4326',project.get('crs','EPSG:4326'),strict=True,lon=lon,lat=lat)
        off_e,off_n=projected_coordinates_to_metres(_off_e_native,_off_n_native,project.get('crs','EPSG:4326'))
        main_n=float(project.get('surface_northing_m',0.0)); main_e=float(project.get('surface_easting_m',0.0))
        st.info(f'Automatically transformed to project CRS {project.get("crs")}: Easting {off_e*M_TO_FT:,.2f} ft • Northing {off_n*M_TO_FT:,.2f} ft • Relative ΔN {(off_n-main_n)*M_TO_FT:,.2f} ft • ΔE {(off_e-main_e)*M_TO_FT:,.2f} ft')
    except Exception as ex:
        off_e=off_n=None; st.error(f'Offset coordinate transformation failed: {ex}')
    if st.button('Create offset well'):
        if off_e is None: st.error('Cannot create offset without a valid project-coordinate transformation.')
        else:
            project['offsets'].append({'name':name,'latitude':lat,'longitude':lon,'surface_northing_m':off_n,'surface_easting_m':off_e,'crs':project.get('crs'),'source_crs':'EPSG:4326','north_reference':project.get('north_reference','Grid North'),'azimuth_reference':project.get('north_reference','Grid North'),'surveys':[{'MD':0.,'Inc':0.,'Azi':0.}]}); save(); st.success('Offset created in the project CRS.')
    for i,off in enumerate(project['offsets']):
        with st.expander(f"{i+1}. {off.get('name','Offset')}"):
            main_n=float(project.get('surface_northing_m',0.0)); main_e=float(project.get('surface_easting_m',0.0)); off_n=float(off.get('surface_northing_m',main_n)); off_e=float(off.get('surface_easting_m',main_e))
            st.write(f"**Surface location:** {float(off.get('latitude',float('nan'))):.6f}°, {float(off.get('longitude',float('nan'))):.6f}°")
            st.write(f"**Project CRS:** {off.get('crs',project.get('crs'))}  •  **Relative to WN-01:** Northing {((off_n-main_n)*M_TO_FT):.2f} ft, Easting {((off_e-main_e)*M_TO_FT):.2f} ft")
            _kb_default=float(off.get('kb_m',project.get('kb_m',0)) or 0)*M_TO_FT
            _kb_in=st.number_input('Offset KB elevation (ft above MSL)',-1000.,5000.,_kb_default,key=f'off_kb_{i}',help='TVD is measured from each well’s own KB. Anti-collision shifts offset TVD to the main-well datum when both KB elevations are known; if blank/unchanged the two wells are assumed to share a datum.')
            if abs(_kb_in-_kb_default)>1e-9: off['kb_m']=_kb_in*FT_TO_M; save()
            st.caption(f"Trajectory status: {'Subsurface survey available' if len(off.get('surveys', [])) > 1 else 'Surface location only — add/import survey stations to display the well path'}")
            template_csv=pd.DataFrame([{'MD':0.0,'Inc':0.0,'Azi':0.0},{'MD':1000.0,'Inc':10.0,'Azi':float(off.get('surveys',[{'Azi':0}])[-1].get('Azi',0))}]).to_csv(index=False).encode('utf-8')
            st.download_button('Download offset survey CSV template',template_csv,file_name=f"{off.get('name','offset').replace(' ','_')}_survey_template.csv",mime='text/csv',key=f'offset_template_{i}')
            off_upload=st.file_uploader('Import offset survey CSV (MD ft, Inc deg, Azi deg)', type='csv', key=f'offset_csv_{i}')
            if off_upload is not None:
                try:
                    imp_off=pd.read_csv(off_upload)
                    qc_off=survey_quality_report(imp_off,'ft')
                    for _q in qc_off:
                        (st.error if _q['severity']=='ERROR' else st.warning if _q['severity']=='WARN' else st.info)(f"{_q['check']}: {_q['detail']}")
                    if not {'MD','Inc','Azi'}.issubset(imp_off.columns):
                        st.error('Offset CSV must contain MD, Inc and Azi columns. MD must be in ft; inclination and azimuth in degrees.')
                    elif any(_q['severity']=='ERROR' for _q in qc_off): st.error('Fix the survey errors above before importing.')
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
            st.success(f'Wellhead normalized to project CRS: **{project.get("crs")}** • Easting {ex:.3f} m • Northing {ny:.3f} m')
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
    st.markdown('### Separation criteria')
    _crit=project.setdefault('anti_collision_criteria',{'required_sf':2.0,'min_separation_m':None,'radius_m':0.0})
    ca,cb,cc=st.columns(3)
    req_sf=ca.number_input('Required separation factor',0.1,10.0,float(_crit.get('required_sf',2.0)),step=0.1,key='ac_required_sf',help='Configurable screening threshold, not an industry or company rule. SF here = centre-to-centre distance / 1σ relative uncertainty along the line joining the wells.')
    min_ctc_ft=cb.number_input('Hard minimum centre-to-centre distance (ft, 0 = none)',0.0,5000.0,float(_crit.get('min_separation_m') or 0.0)*M_TO_FT,key='ac_min_ctc_ft')
    radius_in=cc.number_input('Hole/casing radius per well (in, 0 = ignore)',0.0,40.0,float(_crit.get('radius_m') or 0.0)/0.0254,key='ac_radius_in')
    _crit.update({'required_sf':req_sf,'min_separation_m':(min_ctc_ft*FT_TO_M if min_ctc_ft>0 else None),'radius_m':radius_in*0.0254})
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
                    main_surface_northing_m=float(project.get('surface_northing_m',0.0) or 0.0),
                    required_separation_factor=req_sf, main_kb_m=float(project.get('kb_m',0) or 0),
                    criteria={'min_separation_m':_crit.get('min_separation_m'),'main_radius_m':_crit.get('radius_m') or 0.0,'offset_radius_m':_crit.get('radius_m') or 0.0})
                project['anticollision_last']=to_jsonable(rep[['offset','main_md_m','offset_md_m','separation_m','separation_factor','status']]) if not rep.empty else []
                if rep.empty: st.warning('No valid offset comparisons were produced. Check offset survey structure and project coordinates.')
                else:
                    disp=rep.copy()
                    _risk_rows=[{'Offset':r['offset'],'Main MD from (ft)':iv['main_md_start_m']*M_TO_FT,'Main MD to (ft)':iv['main_md_end_m']*M_TO_FT,'Minimum SF':iv['min_sf'],'Main MD at min (ft)':iv['main_md_at_min_m']*M_TO_FT,'Offset MD at min (ft)':iv['offset_md_at_min_m']*M_TO_FT} for _,r in rep.iterrows() for iv in (r.get('risk_intervals') or [])]
                    disp=disp.drop(columns=[c for c in ('risk_intervals','required_separation_factor') if c in disp.columns])
                    for col in ['main_md_m','offset_md_m','separation_m','horizontal_separation_m','vertical_separation_m','directional_uncertainty_m','minimum_sf_separation_m','minimum_sf_directional_uncertainty_m','minimum_sf_main_md_m','minimum_sf_offset_md_m']:
                        if col in disp: disp[col.replace('_m','_ft')]=disp[col]*M_TO_FT; disp.drop(columns=[col],inplace=True)
                    disp=disp.rename(columns={'main_md_ft':'Closest-approach main MD (ft)','offset_md_ft':'Closest-approach offset MD (ft)','separation_ft':'Closest centreline separation (ft)','horizontal_separation_ft':'Horizontal separation (ft)','vertical_separation_ft':'Vertical separation (ft)','directional_uncertainty_ft':'1σ at closest approach (ft)','minimum_sf_separation_ft':'Separation at minimum SF (ft)','minimum_sf_directional_uncertainty_ft':'1σ at minimum SF (ft)','minimum_sf_main_md_ft':'Main MD at minimum SF (ft)','minimum_sf_offset_md_ft':'Offset MD at minimum SF (ft)','separation_factor':'Minimum sampled SF','separation_factor_at_closest_approach':'SF at closest approach','status':'Status','offset':'Offset well'})
                    st.dataframe(disp,use_container_width=True,hide_index=True)
                    if _risk_rows:
                        st.markdown('#### Collision-risk intervals (SF below the required value)'); st.dataframe(pd.DataFrame(_risk_rows),use_container_width=True,hide_index=True)
                    else: st.caption('No main-well MD interval has a sampled SF below the required value.')
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
    _active_surv=pd.DataFrame(project.get('surveys',[])); _planned_surv=pd.DataFrame(project.get('planned_surveys',[]))
    _pbundle=project.get('planned_trajectory_metadata') or {}; _presult=_pbundle.get('planner_result',{})
    main=_active_surv
    if len(_planned_surv)>1 and {'Easting','Northing','TVD','MD'}.issubset(_planned_surv.columns):
        _src=st.radio('Trajectory to display',['Planned candidate','Active survey'],horizontal=True,key='viz_traj_source',help='A candidate that is not PASS is never written to the active survey; choose Planned candidate to inspect it.')
        if _src=='Planned candidate':
            main=display_path(_planned_surv,_presult).reset_index(drop=True)
            if _presult.get('status')!='PASS':
                st.warning(f"Showing a **{_presult.get('status','REVIEW')}** candidate, drawn only ~100 ft beyond its best target approach (display clipping; the stored trajectory is unchanged).")
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

    def _event_points():
        # Target interceptions (planner) and closest-approach locations (last anti-collision scan), main-well frame.
        pts=[]
        try:
            mds=[r.get('intercept_md_m') for r in _presult.get('target_sequence_results',[])]
            for r,mdv in zip(_presult.get('target_sequence_results',[]),mds):
                if mdv is None or not math.isfinite(float(mdv)) or float(mdv)>float(main['MD'].max())+1e-6: continue
                q=interpolate_path(main,[float(mdv)]).iloc[0]; pts.append(('Intercept: '+str(r.get('name','Target')),float(q.Northing),float(q.Easting),float(q.TVD),'star'))
            for r in project.get('anticollision_last',[]):
                mdv=r.get('main_md_m')
                if mdv is None or not math.isfinite(float(mdv)) or float(mdv)>float(main['MD'].max())+1e-6: continue
                q=interpolate_path(main,[float(mdv)]).iloc[0]; pts.append(('Closest approach: '+str(r.get('offset','Offset')),float(q.Northing),float(q.Easting),float(q.TVD),'x'))
        except Exception: pass
        return pts

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
            for _lbl,_pn,_pe,_pz,_sym in _event_points(): fig.add_trace(go.Scatter(x=[_pe*M_TO_FT],y=[_pn*M_TO_FT],mode='markers+text',text=[_lbl],textposition='top right',name=_lbl,marker=dict(size=12,symbol=_sym)))
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
            for _lbl,_pn,_pe,_pz,_sym in _event_points(): fig.add_trace(go.Scatter3d(x=[_pe*M_TO_FT],y=[_pn*M_TO_FT],z=[-_pz*M_TO_FT],mode='markers+text',text=[_lbl],name=_lbl,marker=dict(size=6,symbol='diamond' if _sym=='star' else 'x')))
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
    _qa_bundle=project.get('planned_trajectory_metadata') or project.get('trajectory_metadata',{})
    meta=_qa_bundle.get('planner_result',{})
    if meta.get('validation_status') is not None or meta.get('status') is not None:
        extra.append({'check':'Trajectory independent validation','status':'PASS' if meta.get('validation_status',meta.get('status'))=='PASS' and not _stale_reasons else 'REVIEW','message':f"Result class {meta.get('result_class',meta.get('status'))}; violations: {', '.join(meta.get('constraint_violations',[])) or 'none'}."})
    for _sr in _stale_reasons: extra.append({'check':'Plan dependency','status':'REVIEW','message':_sr})
    if meta:
        laterr=float(meta.get('lateral_error_m',0))*M_TO_FT; tvderr=abs(float(meta.get('tvd_error_m',0)))*M_TO_FT; extra += [{'check':'Trajectory target lateral error','status':'PASS' if laterr<=100 else 'WARN','message':f'{laterr:.1f} ft.'},{'check':'Trajectory target TVD error','status':'PASS' if tvderr<=100 else 'WARN','message':f'{tvderr:.1f} ft.'}]
    results.extend(extra); st.dataframe(pd.DataFrame(results),use_container_width=True,hide_index=True)
    if project.get('casing_program'): st.markdown('### Casing geometry'); st.dataframe(pd.DataFrame(casing_geometry_checks(project['casing_program'])),use_container_width=True,hide_index=True)
    if not s.empty: st.markdown('### Survey statistics'); st.write({'MD min (ft)':float(s.MD.min())*M_TO_FT,'MD max (ft)':float(s.MD.max())*M_TO_FT,'max inclination (°)':float(s.Inc.max()),'max DLS (°/100 ft)':dls_for_interval_to_100ft(float(s.get('DLS',pd.Series([0])).max()),float(project.get('trajectory_metadata',{}).get('dls_interval_m',30.0)))})

# Reports
elif page=='Reports':
    page_header('Engineering Practice Report', 'OUTPUTS', 'Export the shared project state and QA/QC results as a reproducible practice record.')
    _pb=project.get('planned_trajectory_metadata') or project.get('trajectory_metadata') or {}
    report={'platform':'Well Planning Platform','generated_utc':datetime.utcnow().isoformat()+'Z','project':project_to_json(project),'qa_qc':validate_project(project),
            'trajectory_plan':to_jsonable({'result_class':_pb.get('planner_result',{}).get('result_class',_pb.get('planner_result',{}).get('status')),'validation_status':_pb.get('planner_result',{}).get('validation_status'),'violations':_pb.get('planner_result',{}).get('constraint_violations',[]),'stale_reasons':_stale_reasons,'target_sequence_results':_pb.get('planner_result',{}).get('target_sequence_results',[]),'anti_collision':_pb.get('planner_result',{}).get('collision_validation',[]),'anti_collision_last_scan':project.get('anticollision_last',[])}),
            'disclaimer':'Engineering-development software. PASS means the implemented checks passed; it is not operational certification.'}
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
