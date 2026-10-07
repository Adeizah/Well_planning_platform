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

def _workflow_record_to_project(data):
    """Convert the human-readable field-unit workflow record into the app's internal schema."""
    FT_TO_M = 0.3048
    proj = new_project()
    meta = data.get('project', {})
    loc = data.get('surface_location', {})
    vr = data.get('vertical_reference', {})
    sm = data.get('survey_manager', {})
    ref = data.get('reference_and_geomagnetics', {})
    wa = data.get('well_architecture', {})
    tp = data.get('trajectory_planning', {})

    for k in ['project_name','well_name','well_number','operator','field','site_pad','well_purpose','well_design','status','well_type']:
        if k in meta: proj[k] = meta[k]

    # Normalize workflow-record terminology to the application's controlled vocabularies.
    # The workflow record intentionally uses "Production" as a purpose, while the UI
    # models this as the broader "Development" purpose and keeps well type separate.
    purpose_map = {
        'Production': 'Development',
        'Development Producer': 'Development',
        'Producer': 'Development',
        'Development Well': 'Development',
    }
    design_options = {'Vertical','J-Profile','S-Profile','Build & Hold','Build-Hold-Drop','Horizontal','ERD','Custom'}
    purpose_options = {'Exploration','Appraisal','Development','Injection','Sidetrack','Other'}
    status_options = {'Planning','Draft','Under Review','Approved for Training'}
    if proj.get('well_purpose') in purpose_map:
        proj['well_purpose'] = purpose_map[proj['well_purpose']]
    if proj.get('well_purpose') not in purpose_options:
        proj['well_purpose'] = 'Development'
    if proj.get('well_design') not in design_options:
        proj['well_design'] = 'Build & Hold'
    if proj.get('status') not in status_options:
        proj['status'] = 'Planning'
    proj['latitude'] = float(loc.get('latitude_deg', proj['latitude']))
    proj['longitude'] = float(loc.get('longitude_deg', proj['longitude']))
    proj['crs'] = loc.get('crs', proj['crs'])
    proj['surface_easting_m'] = float(loc.get('surface_easting_ft', 0))*FT_TO_M
    proj['surface_northing_m'] = float(loc.get('surface_northing_ft', 0))*FT_TO_M
    proj['elevation_m'] = float(loc.get('elevation_ft_msl', 0))*FT_TO_M
    proj['kb_m'] = float(loc.get('kb_elevation_ft_msl', 0))*FT_TO_M
    proj['north_reference'] = ref.get('selected_north_reference', 'Grid North')
    proj['depth_reference'] = vr.get('depth_reference', 'MD / TVDSS')

    stations = sm.get('stations', [])
    proj['surveys'] = [{'MD': float(x[0])*FT_TO_M, 'Inc': float(x[1]), 'Azi': float(x[2])} for x in stations]
    if not proj['surveys']:
        proj['surveys'] = [{'MD':0.0,'Inc':0.0,'Azi':0.0}]
    proj['survey_metadata'] = {
        'azimuth_reference': sm.get('azimuth_reference', proj['north_reference']),
        'survey_tool': sm.get('survey_tool','MWD'),
        'survey_method': sm.get('calculation_method','Minimum Curvature'),
        'positional_sigma_m': 0.0,
        'uncertainty_model': 'Screening radial uncertainty'
    }
    interval_ft = float(sm.get('dls_interval_ft',100))
    proj['trajectory_metadata'] = {'dls_interval_m': interval_ft*FT_TO_M, 'dls_interval_ft': interval_ft}

    proj['reference_data'].update({
        k: data.get('reference_and_geomagnetics',{}).get(k)
        for k in ['grid_convergence_deg','magnetic_declination_deg','magnetic_dip_deg','magnetic_total_field_nT','magnetic_horizontal_field_nT','magnetic_x_nT','magnetic_y_nT','magnetic_z_nT']
        if data.get('reference_and_geomagnetics',{}).get(k) is not None
    })
    proj['reference_data']['source_crs'] = loc.get('crs', 'EPSG:4326')
    proj['reference_data']['project_crs'] = loc.get('crs', 'EPSG:4326')

    target = data.get('target_a')
    if target:
        ell = target.get('ellipse', {})
        t = {'name': target.get('name','Target A'), 'type':'Elliptical',
             'north_m': float(target.get('north_ft',0))*FT_TO_M,
             'east_m': float(target.get('east_ft',0))*FT_TO_M,
             'tvdss_m': float(target.get('tvdss_ft',0))*FT_TO_M}
        t['semi_major_m'] = float(ell.get('semi_major_ft',0))*FT_TO_M
        t['semi_minor_m'] = float(ell.get('semi_minor_ft',0))*FT_TO_M
        t['orientation_deg'] = float(ell.get('orientation_deg',0))
        proj['targets'] = [t]

    proj['well_architecture'] = {
        'planned_td_md_m': float(wa.get('planned_td_md_ft'))*FT_TO_M if wa.get('planned_td_md_ft') is not None else None,
        'planned_td_tvd_m': float(wa.get('planned_td_tvd_ft'))*FT_TO_M if wa.get('planned_td_tvd_ft') is not None else None,
        'kop_md_m': float(wa.get('kop_md_ft'))*FT_TO_M if wa.get('kop_md_ft') is not None else None,
        'trajectory_type': wa.get('trajectory_type', tp.get('profile','Build & Hold'))
    }
    casing=[]
    for c in wa.get('casing_program',[]):
        casing.append({
            'string_no': c.get('string_no'), 'type': c.get('type'), 'hole_size_in': c.get('hole_size_in'),
            'casing_od_in': c.get('casing_od_in'), 'grade': c.get('grade'), 'weight_lbft': c.get('weight_lbft'),
            'depth_type': c.get('depth_type','MD'),
            'shoe_md_m': float(c.get('shoe_md_ft',0))*FT_TO_M,
            'shoe_tvd_m': float(c.get('shoe_tvd_ft',0))*FT_TO_M,
            'shoe_tvdss_m': float(c.get('shoe_tvdss_ft',0))*FT_TO_M,
            'top_md_m': float(c.get('top_md_ft',0))*FT_TO_M,
            'liner_top_m': float(c['liner_top_ft'])*FT_TO_M if c.get('liner_top_ft') is not None else None
        })
    proj['casing_program'] = casing

    # Offset wells: preserve geographic wellhead coordinates and derive projected coordinates
    # from the project CRS when lat/long are present. Relative offsets remain available for
    # legacy records that only contain local displacements.
    offsets=[]
    for ow in data.get('offset_wells',[]):
        off={'name':ow.get('name','Offset'), 'azimuth_reference':ow.get('azimuth_reference','Grid North')}
        if ow.get('latitude_deg') is not None or ow.get('longitude_deg') is not None:
            if ow.get('latitude_deg') is None or ow.get('longitude_deg') is None:
                raise ValueError(f"Offset {off['name']} must contain both latitude_deg and longitude_deg.")
            off['latitude']=float(ow['latitude_deg'])
            off['longitude']=float(ow['longitude_deg'])
            try:
                from pyproj import Transformer, CRS
                crs=CRS.from_user_input(proj.get('crs','EPSG:4326'))
                if crs.is_projected:
                    tr=Transformer.from_crs('EPSG:4326', crs, always_xy=True)
                    e,n=tr.transform(off['longitude'], off['latitude'])
                    off['surface_easting_m']=float(e)
                    off['surface_northing_m']=float(n)
            except Exception:
                pass
        if ow.get('surface_easting_ft') is not None:
            off['surface_easting_m']=float(ow['surface_easting_ft'])*FT_TO_M
        if ow.get('surface_northing_ft') is not None:
            off['surface_northing_m']=float(ow['surface_northing_ft'])*FT_TO_M
        if ow.get('surface_easting_relative_ft') is not None:
            off['surface_easting_relative_m']=float(ow['surface_easting_relative_ft'])*FT_TO_M
        if ow.get('surface_northing_relative_ft') is not None:
            off['surface_northing_relative_m']=float(ow['surface_northing_relative_ft'])*FT_TO_M
        off['surveys']=[{'MD':float(x[0])*FT_TO_M,'Inc':float(x[1]),'Azi':float(x[2])} for x in ow.get('surveys',[])]
        offsets.append(off)
    proj['offsets'] = offsets
    proj['model_metadata'] = {'geomagnetic_models': ref.get('geomagnetic_models',[]), 'preferred_magnetic_quantity': ref.get('preferred_magnetic_quantity')}
    return proj

def project_from_json(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid project file: the JSON root must be an object.')
    # Accept both native project exports and the field-unit workflow record we created for this training case.
    if data.get('record_type') == 'well_planning_workflow_record':
        return _workflow_record_to_project(data)
    fmt = data.get('_file_format')
    ver = data.get('_file_version')
    if fmt is not None and fmt != PROJECT_FILE_FORMAT:
        raise ValueError('Invalid project file: this JSON was not exported by the Well Planning Platform.')
    if ver is not None:
        try: ver = int(ver)
        except Exception: raise ValueError('Invalid project file: unsupported file-version value.')
        if ver > PROJECT_FILE_VERSION:
            raise ValueError(f'Project file version {ver} is newer than this platform supports (v{PROJECT_FILE_VERSION}).')
    p=new_project()
    clean={k:v for k,v in data.items() if not k.startswith('_')}
    _deep_merge(p,clean)
    # Normalize imported/native project values before any UI selectboxes render.
    purpose_map = {
        'Production': 'Development',
        'Development Producer': 'Development',
        'Producer': 'Development',
        'Development Well': 'Development',
    }
    purpose_options = {'Exploration','Appraisal','Development','Injection','Sidetrack','Other'}
    if p.get('well_purpose') in purpose_map:
        p['well_purpose'] = purpose_map[p['well_purpose']]
    if p.get('well_purpose') not in purpose_options:
        p['well_purpose'] = 'Development'
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
