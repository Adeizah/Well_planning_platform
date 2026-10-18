# Implementation status — 2026-10-17 (integrated release)

## Implemented in this package

### Phase 1 — General optimizer and target handling
- **Exact point targets.** A point target is a geometric constraint with *no engineering tolerance radius*. Interception is solved
  continuously on the minimum-curvature arcs (`core/exact_targets.py`, Newton iteration along the arc) and accepted only when the 3-D
  distance is <= `POINT_NUMERIC_TOL_M` = 1e-4 m. That value is a floating-point closure criterion (0.1 mm), not a design tolerance.
  The previous 0.5 m dense-sampling threshold has been removed from the validator and the optimizer.
- **Closure step.** After each local solve, point targets that are not yet closed go through a bounded least-squares closure
  (`exact_polish`) on the exact residuals, with limit hinges and a weak pull toward the solved design. Achieved misses are ~1e-9..1e-13 m.
- **Mandatory, ordered targets.** Unchanged semantics, now enforced with exact metrics: every target is mandatory, intercepted in order, the whole
  sequence is evaluated even after an earlier miss, and success is reported only if all pass independent validation.
- **Circular / elliptical geometry** is preserved (footprint, dimensions, orientation, approach constraints) and is never collapsed to a point.
- **Recovery.** New KOP-aware delayed-build / build-hold-build seeds, plus bounded inclination/azimuth/MD nudge restarts when a control-point stage
  ends infeasible.
- **Consistency fixes found while testing:** KOP is now defined identically in the optimizer and the validator (last vertical station), and the
  optimizer's feasibility test now includes `min_kop_md_m` / `max_kop_md_m` (previously a plan could be "station-feasible" while violating KOP).

### Phase 2 — Section-based re-optimization (`core/section_optimizer.py`)
- Stage 1 finds a validated feasible path. Stage 2 segments it into the fewest constant-rate sections (dynamic programming on inclination and
  azimuth swing), re-optimizes azimuth, section lengths (KOP), build/drop rates and turn rates with SLSQP under hard target, DLS, rate, inclination,
  KOP and MD constraints, and regenerates survey stations *from the section parameters* (every section boundary is a station).
- Two passes: "practical" (near-zero rates fixed at zero => true tangents/verticals) then "free".
- The result is adopted only if the independent validator returns PASS and the MD increase is within `section_max_md_increase_pct` (default 10 %).
  Otherwise the Stage-1 trajectory is retained and the reason is reported (`RETAINED_ORIGINAL_*`). An exception in Stage 2 can never break Stage 1.

### Phase 3 — Outputs
- Trajectory Planner now shows the section schedule (field units), the Stage-2 status/source, per-attempt diagnostics, a Stage 1 vs final comparison table,
  and a constraint-margin table. Infeasible plans, missed targets and violated constraints continue to be reported by the validator.

### Phase 4 — Geodesy / geomagnetics (existing backend verified, one speed change)
- CRS selection, geomagnetic model selection (WMM2025 / IGRF-14 retained), automatic convergence/declination/dip/field/gravity, lat/lon or N/E wellhead input,
  Minna datum/zone registry and metre-standardised absolute grid coordinates were already in the package and are unchanged.
- Geomagnetic evaluation and the PROJ transformation report are now cached across Streamlit reruns.

### Speed (identical results; see CHANGELOG for measurements)
- `core/trajectory.mc_core` numpy kernel; `minimum_curvature` fast path (7x); optimizer inner loop is array-based (path build ~15x);
  point-to-arc solve 11x faster; vectorised target residual in `core/optimizer.py` (identical results on 300 randomised cases).

## Known limitations (not claimed as done)
- **Geodesy tests could not be executed in the build environment** (no network, real `pyproj`/PROJ database unavailable). `tests/test_geodesy_registry.py`
  (12 tests) must be run in CI / on a machine with `pyproj` installed. No claim is made about Minna transformation accuracy from this build.
- `test_app_startup.py` / `test_v5_ui_and_smoke.py` need real Streamlit; they were skipped in the build environment. The app workflow tests
  (`tests/test_app_workflows.py`) passed using the project's own harness.
- The profile-based optimizer (`core/optimizer.py`, "Optimize selected profile" modes) still uses its legacy point-tolerance radius; exact point targets apply to the
  General trajectory optimizer path. Approach-angle constraints are validated after Stage 2 but are not explicit Stage-2 constraints (a plan that violates them is rejected, not adopted).
- Stage 2 ignores offsets while optimizing; applicable anti-collision constraints are checked by the validator and a failing plan is rejected.
- Variable-rate builds may be returned as two or three consecutive "Build" sections with decreasing rates rather than a single build + tangent.

## Validation performed (see RELEASE_TEST_REPORT.md)
