"""Display-only helpers (no plotting library needed)."""
from __future__ import annotations

import numpy as np

from core.trajectory import truncate_trajectory_at_md

FT_100_M = 30.48


def clip_failed_candidate_for_display(path, relevant_approach_md_m, extra_m=FT_100_M):
    """Return a COPY of ``path`` ending ~100 ft beyond the relevant target approach.

    Used only when drawing a candidate that did not pass validation, so the plot is not dominated
    by an overshoot to the search ceiling. The stored trajectory is never modified; the cut station is
    placed on the minimum-curvature arc, so the drawn line is geometrically identical to the original.
    """
    if path is None or len(path) < 2 or relevant_approach_md_m is None:
        return path
    md_end = float(relevant_approach_md_m) + float(extra_m)
    if not np.isfinite(md_end) or md_end >= float(path["MD"].iloc[-1]):
        return path
    return truncate_trajectory_at_md(path, max(md_end, float(path["MD"].iloc[0])))


def display_path(path, planner_result):
    """Clip only non-PASS candidates; PASS plans (which already end at the final target) are untouched."""
    res = planner_result or {}
    if res.get("status") == "PASS":
        return path
    md = res.get("display_clip_md_m")
    if md is None and res.get("target_intercept_md_m") is not None:
        md = float(res["target_intercept_md_m"]) + FT_100_M
    return clip_failed_candidate_for_display(path, None if md is None else float(md) - FT_100_M, FT_100_M)
