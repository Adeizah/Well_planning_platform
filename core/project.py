
from datetime import date
import copy

SCHEMA_VERSION = "1.0"

def new_project():
    return {
        "schema_version": SCHEMA_VERSION,
        "project_name": "New Well Planning Project",
        "well_name": "NEW-01",
        "status": "Planning",
        "latitude": 4.8,
        "longitude": 6.9,
        "elevation_m": 25.0,
        "kb_m": 25.0,
        "crs": "EPSG:4326",
        "planned_date": str(date.today()),
        "north_reference": "True North",
        "depth_reference": "MD / TVDSS",
        "notes": "",
        "surveys": [
            {"MD": 0.0, "Inc": 0.0, "Azi": 0.0},
            {"MD": 500.0, "Inc": 0.0, "Azi": 0.0},
        ],
        "targets": [],
        "offsets": [],
        "model_metadata": {},
        "trajectory_metadata": {},
    }

def project_to_json(project):
    return copy.deepcopy(project)

def project_from_json(data):
    p = new_project()
    p.update(data)
    p["schema_version"] = SCHEMA_VERSION
    return p

def validate_project(p):
    checks = []
    checks.append({
        "check":"Project identity",
        "status":"PASS" if p.get("project_name") and p.get("well_name") else "FAIL",
        "message":"Project and well names are defined." if p.get("project_name") and p.get("well_name")
                  else "Project and well names are required."
    })
    lat_ok = -90 <= float(p.get("latitude", 999)) <= 90
    lon_ok = -180 <= float(p.get("longitude", 999)) <= 180
    checks.append({"check":"Coordinates","status":"PASS" if lat_ok and lon_ok else "FAIL",
                   "message":"Latitude and longitude are within valid ranges."
                   if lat_ok and lon_ok else "Invalid latitude or longitude."})
    surveys = p.get("surveys", [])
    required = {"MD","Inc","Azi"}
    has_survey = bool(surveys) and required.issubset(surveys[0])
    checks.append({"check":"Survey structure","status":"PASS" if has_survey else "FAIL",
                   "message":"Survey contains MD, Inc and Azi."
                   if has_survey else "Survey requires MD, Inc and Azi."})
    if surveys:
        mds = [float(x["MD"]) for x in surveys]
        ordered = all(b > a for a,b in zip(mds, mds[1:]))
        checks.append({"check":"Survey MD ordering","status":"PASS" if ordered else "FAIL",
                       "message":"MD increases monotonically." if ordered else "MD must increase monotonically."})
    else:
        checks.append({"check":"Survey data","status":"WARN","message":"No survey stations loaded."})
    checks.append({
        "check":"Model provenance",
        "status":"PASS" if p.get("model_metadata") else "WARN",
        "message":"At least one model result is recorded." if p.get("model_metadata")
                  else "No model-derived results recorded yet."
    })
    return checks
