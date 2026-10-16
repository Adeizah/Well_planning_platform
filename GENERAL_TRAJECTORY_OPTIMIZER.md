# General trajectory optimizer — engineering-development notes

## Purpose

The General trajectory optimizer adds a control-point-based path search alongside the existing J/S/Horizontal/ERD profile optimizer. It interpolates a sequence of inclination and azimuth controls over measured depth and calculates the resulting positional path with the same minimum-curvature function used by the survey workflow.

## Coordinates and units

- Internal trajectory distances and positions are metres.
- MD increases from 0 and the first station is vertical.
- Azimuth is clockwise from the project's selected north reference.
- Target `tvd_m` is TVD below the well reference used by the Trajectory Planner; target `north_m` and `east_m` are well-relative coordinates.
- Target `dip_deg` is positive downward; `dip_direction_deg` is azimuth clockwise from project north.
- An inclined plane is represented locally by `TVD_plane = target_TVD + tan(dip) * (delta_N*cos(dip_direction) + delta_E*sin(dip_direction))`.

## Optimization approach

The solver uses bounded L-BFGS-B refinement over final MD and control-point inclination/azimuth values. The objective prioritizes final target-centre alignment and depth/plane residual, ordered target misses, hard-limit violation penalties, route length, path smoothness and offset-well clearance screening. After optimization, independent checks determine whether the candidate can be marked PASS. A solver's `success` flag alone does not make a candidate feasible.

## Constraints and anti-collision

- Maximum inclination, DLS, build rate and turn rate are checked on the generated station sequence.
- Required targets are evaluated in sequence; the final required target defines the planned endpoint.
- Optional approach azimuth, approach inclination and wellbore/target-plane intersection-angle constraints are checked when enabled.
- During route search, offset avoidance uses sampled centreline distances plus a conservative approximate uncertainty envelope. The final candidate is independently passed through `engineering.anti_collision.clearance_report`, using the configured covariance-based development model and required separation factor. The report separately identifies geometric closest approach and minimum sampled separation factor, because those may occur at different MD pairs.
- Any clearance result of WARNING, ALERT, REVIEW or NOT CHECKED prevents an overall PASS.

## Known limitations

This is an engineering-development optimizer, not a certified operational trajectory planner. The optimization-time uncertainty envelope is approximate, and the current covariance-based uncertainty model is not ISCWSA-certified. Offset clearance is sampled and therefore requires additional convergence/spacing validation for operational-grade use. Control-point interpolation is flexible but not an arbitrary optimal-control solution; a feasible path may be missed by the bounded local solver. `NO_FEASIBLE_CANDIDATE_FOUND` means no valid candidate was found in this run, not that infeasibility has been proven. The legacy profile optimizer does not enforce the new inclined-plane/approach constraints; the General trajectory optimizer mode is required for those constraints.

## Test expectations

Test single and ordered multiple targets; horizontal and inclined planes; approach constraints enabled/disabled; near/far and shallow/deep targets; feasible and infeasible constraint combinations; offsets with valid, invalid and missing survey trajectories; configurable separation-factor thresholds; project save/reload; survey table; plan/vertical/3D views; and CSV/project exports. Verify both calculations and application persistence.


## Revision 2026-10-15 — acceptance rules and search strategy

* **Acceptance.** `optimize_general_trajectory` returns `PASS` only when `core.validation.validate_trajectory` passes on the
  arc-resampled path. The optimizer's own convergence flag and objective never decide validity. The Trajectory Planner page runs the
  same validator on manual and legacy profiles too.
* **Result classes.** `PASS`; `REVIEW`; `NO FEASIBLE CANDIDATE FOUND` (search ended without a valid candidate — *not* a proof);
  `INFEASIBLE_PROVEN` (an analytic necessary condition in `core/feasibility.py` fired, reasons in `proof_of_infeasibility`).
* **Search.** seeds -> scaled L-BFGS-B -> control points 4 -> 6 -> 8 -> 10 (warm-started) -> collision-buffer escalation -> continuation polish.
  `time_budget_s` caps the search; `adaptive=False` restores a fixed control-point count.
* **Limits.** Search success is empirical. Anti-collision uses the development covariance model, not ISCWSA.
