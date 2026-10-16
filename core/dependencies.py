"""Plan dependency tracking: mark a saved trajectory REVIEW when something it relied on changes.

At planning time a *snapshot* of every input the plan depends on is stored with the plan
(required targets, surface/reference data, design constraints, offsets, uncertainty model,
and the survey itself). On every app run :func:`refresh_plan_staleness` re-computes the
fingerprints; any difference downgrades the saved plan to REVIEW with the reasons recorded.
The plan data is never altered - only its status and ``stale_reasons`` fields.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from core.validation import survey_hash

_PLAN_KEYS = ("planned_trajectory_metadata", "trajectory_metadata")


def _h(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def dependency_snapshot(project: dict, target_names=None) -> dict:
    """Fingerprints of everything the plan depends on."""
    names = list(target_names or [])
    targets = [t for t in project.get("targets", []) if (not names or t.get("name") in names)]
    snap = {
        "targets": {str(t.get("name")): _h(t) for t in targets},
        "target_order": names,
        "surface": _h([project.get("surface_easting_m"), project.get("surface_northing_m"), project.get("kb_m"),
                       project.get("elevation_m"), project.get("crs")]),
        "constraints": _h(project.get("design_constraints", {})),
        "uncertainty_model": _h(project.get("survey_metadata", {}).get("survey_error_parameters", {})),
        "offsets": {str(o.get("name")): _h([o.get("surface_easting_m"), o.get("surface_northing_m"), o.get("kb_m"),
                                            survey_hash(o.get("surveys", [])) if len(o.get("surveys", [])) > 1 else "surface-only"])
                    for o in project.get("offsets", [])},
    }
    return snap


def stale_dependencies(project: dict, snapshot: dict) -> list[str]:
    """Human-readable reasons why ``snapshot`` no longer matches the project (empty = up to date)."""
    if not snapshot:
        return []
    now = dependency_snapshot(project, snapshot.get("target_order"))
    reasons = []
    for name, h in snapshot.get("targets", {}).items():
        if name not in now["targets"]:
            reasons.append(f"Required target '{name}' was deleted or renamed.")
        elif now["targets"][name] != h:
            reasons.append(f"Required target '{name}' was edited.")
    for key, label in (("surface", "Surface location / KB / CRS changed."), ("constraints", "Design constraints changed."),
                       ("uncertainty_model", "Survey uncertainty parameters changed.")):
        if now[key] != snapshot.get(key):
            reasons.append(label)
    old_off, new_off = snapshot.get("offsets", {}), now["offsets"]
    for name in sorted(set(old_off) | set(new_off)):
        if name not in new_off:
            reasons.append(f"Offset well '{name}' was removed.")
        elif name not in old_off:
            reasons.append(f"Offset well '{name}' was added after planning (not screened).")
        elif old_off[name] != new_off[name]:
            reasons.append(f"Offset well '{name}' changed (position, datum or survey).")
    return reasons


def attach_snapshot(project: dict, bundle: dict, target_names) -> dict:
    """Store the dependency snapshot and survey fingerprint on a plan bundle."""
    bundle["dependency_snapshot"] = dependency_snapshot(project, target_names)
    records = project.get("planned_surveys") or []
    bundle["survey_hash"] = survey_hash(records) if records else ""
    return bundle


def refresh_plan_staleness(project: dict) -> list[str]:
    """Downgrade the saved plan to REVIEW if a dependency changed. Returns the reasons (possibly empty)."""
    all_reasons: list[str] = []
    for key in _PLAN_KEYS:
        bundle = project.get(key) or {}
        snap = bundle.get("dependency_snapshot")
        result = bundle.get("planner_result") or {}
        reasons = stale_dependencies(project, snap) if snap else []
        # a stored plan whose survey was edited after planning is also stale
        planned = project.get("planned_surveys") or []
        if bundle.get("survey_hash") and planned and survey_hash(planned) != bundle["survey_hash"]:
            reasons.append("The saved planned survey was modified after validation.")
        if reasons:
            result["status"] = "REVIEW"
            if result.get("optimization_status") == "FEASIBLE":
                result["optimization_status"] = "REVIEW"
            viol = result.setdefault("constraint_violations", [])
            if "dependency_changed_after_planning" not in viol:
                viol.append("dependency_changed_after_planning")
            bundle["stale_reasons"] = reasons
            bundle["stale_detected_utc"] = bundle.get("stale_detected_utc") or datetime.utcnow().isoformat() + "Z"
            bundle["planner_result"] = result
            project[key] = bundle
            all_reasons.extend(r for r in reasons if r not in all_reasons)
        elif "stale_reasons" in bundle and snap:
            # dependencies match again (e.g. an edit was reverted); keep REVIEW until re-validated, but explain
            bundle["stale_reasons"] = bundle.get("stale_reasons", [])
    return all_reasons
