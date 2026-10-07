"""
core/project.py
Standalone project/state persistence helpers for the well-planning workflow.

Engineering-facing values in this module use field units:
    length: ft
    pressure: psi
    density: ppg
    flow: gpm
    angle: deg
    DLS: deg/100ft

This module intentionally keeps the project record JSON-friendly so it can be
saved/exported and imported without a database.

The importer accepts the current field-unit workflow format, including:
    project
    reference
    well_architecture
    targets
    offsets
    surveys
    trajectory
    geomagnetics
    etc.

Offset records are normalized so latitude/longitude and the surface offset
from the main well are retained.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA_VERSION = "1.5"
PROJECT_NAME = "Well Planning Project"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _copy(value: Any) -> Any:
    return deepcopy(value)


# ---------------------------------------------------------------------------
# Default project
# ---------------------------------------------------------------------------

def default_project() -> Dict[str, Any]:
    """Return a clean, JSON-serializable project record."""
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "name": "",
            "field": "",
            "well_name": "",
            "pad": "",
            "operator": "",
            "country": "",
            "well_purpose": "Development",
            "well_type": "Development",
            "design": "",
            "status": "Planning",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        },
        "reference": {
            "crs": {
                "epsg": None,
                "name": "",
                "latitude_deg": None,
                "longitude_deg": None,
                "coordinate_order": "Easting, Northing",
            },
            "surface": {
                "latitude_deg": None,
                "longitude_deg": None,
                "northing_ft": None,
                "easting_ft": None,
                "ground_elevation_ft_msl": None,
                "wellhead_elevation_ft_msl": None,
                "kb_elevation_ft_msl": None,
                "kb_to_ground_ft": None,
                "tvd_reference": "KB/RKB",
                "tvdss_reference": "MSL",
                "north_reference": "Grid North",
                "declination_deg": None,
                "grid_convergence_deg": None,
            },
        },
        "well_architecture": {
            "planned_md_ft": None,
            "planned_tvd_ft": None,
            "kop_ft": None,
            "casing": [],
        },
        "targets": [],
        "offsets": [],
        "surveys": [],
        "trajectory": {
            "method": "Minimum Curvature",
            "stations": [],
        },
        "geomagnetics": {
            "model": "WMM2025",
            "date": None,
            "latitude_deg": None,
            "longitude_deg": None,
            "ellipsoid_height_ft": None,
            "declination_deg": None,
            "dip_deg": None,
            "total_field_nt": None,
            "horizontal_field_nt": None,
            "north_component_nt": None,
            "east_component_nt": None,
            "vertical_component_nt": None,
        },
        "geodesy": {
            "grid_convergence_deg": None,
            "normal_gravity_m_s2": None,
            "geoid_model": "",
            "geoid_separation_ft": None,
        },
        "anti_collision": {
            "enabled": True,
            "method": "Screening",
            "separation_factor": None,
        },
        "casing_design": [],
        "hydraulics": {},
        "pp_fg": {},
        "torque_drag": {},
        "cementing": {},
        "well_control": {},
        "bha": {},
        "visualization": {},
        "qa_qc": {},
        "reports": {},
        "ui": {
            "active_page": "01 Dashboard",
        },
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_project(project: Mapping[str, Any]) -> Dict[str, Any]:
    p = dict(project)
    purpose = str(p.get("well_purpose", p.get("purpose", "Development")))
    allowed = {
        "Exploration", "Appraisal", "Development", "Injection",
        "Sidetrack", "Other"
    }
    if purpose not in allowed:
        # Compatibility with records that used "Production".
        if purpose.lower() == "production":
            purpose = "Development"
        else:
            purpose = "Other"
    p["well_purpose"] = purpose
    p["updated_at"] = _now_iso()
    return p


def _normalize_surface(reference: Mapping[str, Any]) -> Dict[str, Any]:
    ref = deepcopy(dict(reference or {}))
    surface = deepcopy(ref.get("surface", {}))

    # Accept common aliases used by older workflow records.
    if surface.get("latitude_deg") is None:
        surface["latitude_deg"] = _float(
            surface.get("latitude", ref.get("latitude_deg"))
        )
    if surface.get("longitude_deg") is None:
        surface["longitude_deg"] = _float(
            surface.get("longitude", ref.get("longitude_deg"))
        )

    for key in (
        "northing_ft", "easting_ft",
        "ground_elevation_ft_msl",
        "wellhead_elevation_ft_msl",
        "kb_elevation_ft_msl",
        "kb_to_ground_ft",
        "declination_deg",
        "grid_convergence_deg",
    ):
        surface[key] = _float(surface.get(key))

    ref["surface"] = surface
    return ref


def normalize_offset(offset: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Normalize one offset well.

    The important fields are deliberately kept in field units:
      latitude, longitude
      surface_northing_relative_ft
      surface_easting_relative_ft
      surface_northing_ft
      surface_easting_ft
    """
    src = deepcopy(dict(offset or {}))

    name = (
        src.get("name")
        or src.get("well_name")
        or src.get("offset_name")
        or "Offset"
    )

    lat = _float(src.get("latitude", src.get("latitude_deg")))
    lon = _float(src.get("longitude", src.get("longitude_deg")))

    rn = _float(
        src.get(
            "surface_northing_relative_ft",
            src.get("relative_northing_ft", src.get("northing_relative_ft")),
        ),
        0.0,
    )
    re = _float(
        src.get(
            "surface_easting_relative_ft",
            src.get("relative_easting_ft", src.get("easting_relative_ft")),
        ),
        0.0,
    )

    sn = _float(src.get("surface_northing_ft"))
    se = _float(src.get("surface_easting_ft"))

    surveys = src.get("surveys")
    if not isinstance(surveys, list):
        surveys = []

    result = {
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "surface_northing_relative_ft": rn,
        "surface_easting_relative_ft": re,
        "surface_northing_ft": sn,
        "surface_easting_ft": se,
        "azimuth_reference": src.get(
            "azimuth_reference",
            src.get("north_reference", "Grid North"),
        ),
        "surveys": surveys,
    }

    # Preserve any extra user-defined offset fields.
    for key, value in src.items():
        if key not in result:
            result[key] = value

    return result


def normalize_offsets(data: Any) -> List[Dict[str, Any]]:
    """Normalize the supported offset container formats."""
    if data is None:
        return []

    if isinstance(data, Mapping):
        # Accept {"OW-01": {...}, ...}
        items = []
        for key, value in data.items():
            if isinstance(value, Mapping):
                item = dict(value)
                item.setdefault("name", key)
                items.append(item)
        data = items

    if not isinstance(data, list):
        return []

    return [normalize_offset(x) for x in data if isinstance(x, Mapping)]


def normalize_project_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Convert a workflow JSON record into the canonical field-unit schema.

    This function is intentionally tolerant of the earlier names:
      offset_wells -> offsets
      latitude_deg / longitude_deg -> latitude / longitude on offsets
      purpose / Production -> Development-compatible purpose
    """
    base = default_project()
    src = deepcopy(dict(record))

    # Merge top-level sections without destroying defaults.
    for key, value in src.items():
        if key == "schema_version":
            continue
        if key == "offset_wells":
            continue
        base[key] = value

    base["schema_version"] = SCHEMA_VERSION
    base["project"] = _normalize_project(
        src.get("project", base["project"])
    )
    base["reference"] = _normalize_surface(
        src.get("reference", base["reference"])
    )

    # Offsets are always canonicalized into "offsets".
    raw_offsets = src.get("offsets", src.get("offset_wells", []))
    base["offsets"] = normalize_offsets(raw_offsets)

    # If surveys are stored separately, keep them. Offset surveys remain
    # attached to their respective offset as well.
    if not isinstance(base.get("surveys"), list):
        base["surveys"] = []

    # Keep trajectory stations separate from survey-manager records.
    if not isinstance(base.get("trajectory"), Mapping):
        base["trajectory"] = {"method": "Minimum Curvature", "stations": []}
    else:
        base["trajectory"] = dict(base["trajectory"])

    base["project"]["updated_at"] = _now_iso()
    return base


# ---------------------------------------------------------------------------
# Project object
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """Small in-memory project container suitable for Streamlit session state."""

    data: Dict[str, Any] = field(default_factory=default_project)

    def __post_init__(self) -> None:
        self.data = normalize_project_record(self.data)

    @classmethod
    def new(cls) -> "Project":
        return cls(default_project())

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "Project":
        return cls(normalize_project_record(record))

    def to_dict(self) -> Dict[str, Any]:
        return _copy(self.data)

    def update(self, **sections: Any) -> None:
        for key, value in sections.items():
            self.data[key] = deepcopy(value)
        self.data["project"]["updated_at"] = _now_iso()

    # ---- offsets ---------------------------------------------------------

    @property
    def offsets(self) -> List[Dict[str, Any]]:
        return self.data.setdefault("offsets", [])

    def add_offset(
        self,
        name: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        surface_northing_relative_ft: float = 0.0,
        surface_easting_relative_ft: float = 0.0,
        surface_northing_ft: Optional[float] = None,
        surface_easting_ft: Optional[float] = None,
        azimuth_reference: str = "Grid North",
        surveys: Optional[Iterable[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        offset = normalize_offset({
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
            "surface_northing_relative_ft": surface_northing_relative_ft,
            "surface_easting_relative_ft": surface_easting_relative_ft,
            "surface_northing_ft": surface_northing_ft,
            "surface_easting_ft": surface_easting_ft,
            "azimuth_reference": azimuth_reference,
            "surveys": list(surveys or []),
        })
        self.offsets.append(offset)
        self.data["project"]["updated_at"] = _now_iso()
        return offset

    def remove_offset(self, name: str) -> bool:
        before = len(self.offsets)
        self.data["offsets"] = [
            x for x in self.offsets if x.get("name") != name
        ]
        changed = len(self.offsets) != before
        if changed:
            self.data["project"]["updated_at"] = _now_iso()
        return changed

    # ---- JSON ------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            self.to_dict(),
            indent=indent,
            ensure_ascii=False,
            allow_nan=False,
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json() + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        source = Path(path)
        record = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(record, Mapping):
            raise ValueError("Project JSON root must be an object.")
        return cls.from_dict(record)


# ---------------------------------------------------------------------------
# Functional API
# ---------------------------------------------------------------------------

def create_project() -> Dict[str, Any]:
    return default_project()


def export_project(project: Any, path: str | Path) -> Path:
    """Export either a Project object or a plain project dictionary."""
    if isinstance(project, Project):
        return project.save(path)

    normalized = normalize_project_record(project)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            normalized,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )
    return target


def import_project(path: str | Path) -> Dict[str, Any]:
    """
    Import a project safely.

    Nothing is modified outside the returned object. Callers can validate
    first and only then replace their Streamlit session-state project.
    """
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project JSON: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ValueError("Project JSON root must be an object.")

    return normalize_project_record(raw)


def project_from_json(text: str) -> Dict[str, Any]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project JSON: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ValueError("Project JSON root must be an object.")

    return normalize_project_record(raw)


def project_to_json(project: Mapping[str, Any], indent: int = 2) -> str:
    return json.dumps(
        normalize_project_record(project),
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    )


def validate_project(project: Mapping[str, Any]) -> List[str]:
    """
    Return validation errors. Empty list means the project record is valid
    enough for workflow persistence.
    """
    errors: List[str] = []

    if not isinstance(project, Mapping):
        return ["Project must be a JSON object."]

    p = project.get("project")
    if not isinstance(p, Mapping):
        errors.append("Missing project section.")

    offsets = project.get("offsets", [])
    if not isinstance(offsets, list):
        errors.append("offsets must be a list.")
    else:
        for i, offset in enumerate(offsets):
            if not isinstance(offset, Mapping):
                errors.append(f"offsets[{i}] must be an object.")
                continue
            if not offset.get("name"):
                errors.append(f"offsets[{i}] is missing name.")
            for key in (
                "surface_northing_relative_ft",
                "surface_easting_relative_ft",
            ):
                if offset.get(key) is not None and _float(offset.get(key)) is None:
                    errors.append(f"offsets[{i}].{key} must be numeric.")

    return errors


# Backward-compatible aliases used by simple Streamlit workflows.
ProjectState = Project
load_project = import_project
save_project = export_project
