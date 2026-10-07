from datetime import date
import copy

SCHEMA_VERSION='4.0'
PROJECT_FILE_FORMAT='well-planning-project'
PROJECT_FILE_VERSION=1

def new_project():
    return {'schema_version':SCHEMA_VERSION,'project_name':'New Well Planning Project','well_name':'NEW-01','operator':'','field':'','site_pad':'','well_number':'NEW-01','well_purpose':'Development','well_design':'Build & Hold','status':'Planning','well_type':'Development Producer','latitude':4.8,'longitude':6.9,'surface_easting_m':0.0,'surface_northing_m':0.0,'elevation_m':25.0,'kb_m':25.0,'crs':'EPSG:4326','planned_date':str(date.today()),'north_reference':'Grid North','depth_reference':'MD / TVDSS','units':'Field','notes':'','design_constraints':{'max_dls_deg_30m':3.0,'max_inclination_deg':70.0,'max_build_rate_deg_30m':3.0,'max_turn_rate_deg_30m':3.0},'surveys':[{'MD':0.0,'Inc':0.0,'Azi':0.0}], 'survey_metadata':{'azimuth_reference':'Grid North','survey_tool':'MWD','survey_method':'Minimum Curvature','positional_sigma_m':0.0,'uncertainty_model':'Screening radial uncertainty'},'targets':[],'offsets':[],'model_metadata':{},'trajectory_metadata':{},'reference_data':{'grid_convergence_deg':None,'magnetic_declination_deg':None,'magnetic_dip_deg':None,'magnetic_total_field_nT':None,'magnetic_horizontal_field_nT':None,'magnetic_x_nT':None,'magnetic_y_nT':None,'magnetic_z_nT':None,'gravity_mps2':None,'geoid_height_m':None,'geoid_model':None,'source_crs':'EPSG:4326','project_crs':'EPSG:4326','datum':None,'ellipsoid':None},'well_architecture':{'planned_td_md_m':None,'planned_td_tvd_m':None,'kop_md_m':None,'trajectory_type':'Build & Hold'},'casing_program':[],'geology':[],'bha':[],'engineering_assumptions':{}}

def project_to_json(project):
    out = copy.deepcopy(project)
    # File metadata is deliberately separate from the engineering schema version.
    # This lets the project file format evolve without breaking the engineering model.
    out['_file_format'] = PROJECT_FILE_FORMAT
    out['_file_version'] = PROJECT_FILE_VERSION
    return out

def _deep_merge(base,incoming):
    for k,v in incoming.items():
        if isinstance(v,dict) and isinstance(base.get(k),dict): _deep_merge(base[k],v)
        else: base[k]=v

def project_from_json(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid project file: the JSON root must be an object.')
    fmt = data.get('_file_format')
    ver = data.get('_file_version')
    # Accept legacy project exports that predate explicit file metadata.
    if fmt is not None and fmt != PROJECT_FILE_FORMAT:
        raise ValueError('Invalid project file: this JSON was not exported by the Well Planning Platform.')
    if ver is not None:
        try:
            ver = int(ver)
        except Exception:
            raise ValueError('Invalid project file: unsupported file-version value.')
        if ver > PROJECT_FILE_VERSION:
            raise ValueError(f'Project file version {ver} is newer than this platform supports (v{PROJECT_FILE_VERSION}).')
    p=new_project()
    clean={k:v for k,v in data.items() if not k.startswith('_')}
    _deep_merge(p,clean)
    p['schema_version']=SCHEMA_VERSION
    return p

def validate_project(p):
    checks=[]
    checks.append({'check':'Project identity','status':'PASS' if p.get('project_name') and p.get('well_name') else 'FAIL','message':'Project and well names are defined.'})
    try: lat_ok=-90<=float(p.get('latitude'))<=90; lon_ok=-180<=float(p.get('longitude'))<=180
    except: lat_ok=lon_ok=False
    checks.append({'check':'Surface coordinates','status':'PASS' if lat_ok and lon_ok else 'FAIL','message':'Latitude and longitude are valid.' if lat_ok and lon_ok else 'Invalid latitude/longitude.'})
    try:
        from pyproj import CRS; c=CRS.from_user_input(p.get('crs','EPSG:4326')); msg=f'{c.name} ({c.to_string()})'; status='PASS'
    except Exception as e: msg=str(e); status='FAIL'
    checks.append({'check':'CRS','status':status,'message':msg})
    s=p.get('surveys',[]); req={'MD','Inc','Azi'}; ok=bool(s) and req.issubset(s[0])
    checks.append({'check':'Survey structure','status':'PASS' if ok else 'FAIL','message':'MD, Inc and Azi present.' if ok else 'Survey requires MD, Inc and Azi.'})
    if s:
        try: ordered=all(float(b['MD'])>float(a['MD']) for a,b in zip(s,s[1:])); checks.append({'check':'Survey MD ordering','status':'PASS' if ordered else 'FAIL','message':'MD increases strictly.'})
        except: checks.append({'check':'Survey numeric values','status':'FAIL','message':'Non-numeric survey value detected.'})
    else: checks.append({'check':'Survey data','status':'WARN','message':'No survey loaded.'})
    ref=p.get('reference_data',{}); checks.append({'check':'North-reference data','status':'PASS' if ref.get('grid_convergence_deg') is not None or ref.get('magnetic_declination_deg') is not None else 'WARN','message':'Reference corrections available.' if ref.get('grid_convergence_deg') is not None or ref.get('magnetic_declination_deg') is not None else 'Calculate reference corrections.'})
    checks.append({'check':'Targets','status':'PASS' if p.get('targets') else 'WARN','message':f"{len(p.get('targets',[]))} target(s) defined."})
    checks.append({'check':'Offsets','status':'PASS' if p.get('offsets') else 'WARN','message':f"{len(p.get('offsets',[]))} offset(s) defined."})
    checks.append({'check':'Casing architecture','status':'PASS' if p.get('casing_program') else 'WARN','message':'Final casing program stored.' if p.get('casing_program') else 'No casing program stored.'})
    checks.append({'check':'Model provenance','status':'PASS' if p.get('model_metadata') else 'WARN','message':'Model provenance recorded.' if p.get('model_metadata') else 'No model provenance recorded.'})
    return checks
