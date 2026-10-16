# Changelog

## 2026-10-16 — Geodetic reference and coordinate-unit consistency

- Added a searchable installed EPSG/PROJ CRS registry to Project & Reference, with the datum/reference frame shown as part of each CRS selection.
- Added either/or wellhead input: latitude/longitude or grid Northing/Easting in metres.
- Normalized absolute grid coordinates to metres even when a projected CRS uses non-metre native units; conversion to CRS-native units happens at transformation boundaries.
- Changed target creation, target editing, and target tables to use metres for absolute grid Northing/Easting. Target depths, tolerances, and shape dimensions remain field-unit inputs where applicable and are converted internally.
- Added safe reprojection of stored wellhead, target-center, and offset surface coordinates when changing between projected CRSs. Changes are staged and cancelled if a suitable non-ballpark transformation with stated accuracy is unavailable.
- Added source CRS metadata for offset coordinate inputs and target CRS metadata; documented coordinate-unit conventions.
- Tests: geodesy/registry and project tests pass; app workflow/UI smoke tests pass; trajectory-planner/multi-target tests pass. The full suite did not complete within the available runtime window.

## 2026-10-15 — Audit, correction and independent-validation pass

See `GAP_ANALYSIS.md` for evidence, tests and open items.

- **Fixed (safety-relevant):** anti-collision separation factor swapped North/East in the covariance projection.
- Anti-collision: exact arc sampling, continuous closest-approach refinement, risk intervals, per-MD profile, configurable SF / hard minimum distance / radii, KB datum alignment, UI controls.
- Fixed TVD tie-in for surveys not starting at MD 0; polygon target outline/miss distance; truncation on the arc; vertical-section helper.
- Vectorised minimum curvature (~150x) and survey uncertainty (O(n)); numerically identical to the previous implementation.
- New `core/validation.py` (independent validator used for every planning mode), `core/feasibility.py` (infeasibility proofs), `core/dependencies.py` (stale-plan detection), `core/visual.py` (failed-candidate display window), `core/survey_qc.py` (import QC).
- General optimizer: multi-seed search, adaptive control points/segment lengths, offset detours, collision-buffer escalation, polish, time budget; result classes PASS / REVIEW / NO FEASIBLE CANDIDATE FOUND with proof of infeasibility where provable.
- App: target editing, per-target tolerance/thickness, failed candidates no longer overwrite the active survey (backup kept), stale-plan banners, validation panel, trajectory-source selector, intercept / closest-approach markers.
- Tests: 60 -> 102 (+ offline app harness). Original tests unchanged except one tautological assertion that now requires PASS.

## 2026-10-07 — Integrated engineering correction pass

- Fixed WMM2025 integration to use the documented `pywmm` field getters with a compatible fallback path.
- Fixed IGRF-14 date normalization for `ppigrf`.
- Corrected DLS unit normalization between deg/30 m and deg/100 ft, including stored interval metadata.
- Corrected survey TVDSS calculation to `KB elevation - TVD`.
- Prevented survey/reference conversions from silently using zero declination or convergence when required data are missing.
- Derived projected wellhead Easting/Northing from latitude/longitude for projected CRSs.
- Corrected target handling so absolute project coordinates are converted to well-relative offsets for trajectory planning and visualization.
- Expanded target coordinate ranges and made target vertical reference explicit.
- Derived trajectory-planner azimuth from target displacement when not explicitly overridden.
- Corrected offset surface translation for visualization and anti-collision screening.
- Made coordinate-transformation labels reflect geographic vs projected CRS coordinates.
- Added a clear NOAA GEOID18 coverage guard; GEOID18 is not a global service and is not applicable to the Nigeria training case.
- Added regression tests for geomagnetic wrappers, convergence behavior, DLS normalization and offset translation.


## 5.0.0 — Desktop Engineering Workspace

- Redesigned the application UI around a desktop/workstation well-planning workflow.
- Added persistent project/well context header and status badge.
- Added grouped, numbered module navigation for Setup, Directional, Drilling Engineering and Outputs.
- Added dashboard engineering-pulse cards for current MD, survey count, targets, offsets, casing and reference corrections.
- Added consistent module headers, helper panels, cards and data presentation styling.
- Kept the v4.0 project schema unchanged to preserve JSON compatibility.
- Added v5 UI contract/regression checks and cross-module engineering smoke tests.
- No engineering calculation engine was replaced solely for the UI release.

## 4.0.0 — Integrated Practice Release

- Rebuilt the application around a v4 project schema.
- Added flexible target geometry and target-driven trajectory planning.
- Added integrated offset trajectories and visualization.
- Added casing architecture and design screening.
- Expanded hydraulics, T&D, cement and well-control screens.
- Added BHA/drilling configuration.
- Added integrated visualization for plan, vertical section and 3D views.
- Added stronger project QA/QC and report export.
- Clarified screening versus validated engineering status throughout the product.

## v6.0 — Integrated planning/reference upgrade

- Added target-fit hold-inclination solving to the constant build/hold planner, bounded by the project maximum inclination.
- Added trajectory planning diagnostics for EOB, build length, final MD, hold margin and target-reference azimuth mismatch.
- Normalized anti-collision uncertainty units (field-unit UI, metre internal calculations) and added readiness diagnostics.
- Upgraded anti-collision screening to accept raw survey offsets, calculate positional trajectories automatically, and search pairwise minimum 3D separation with separate main/offset MD values.
- Added automatic offset surface-coordinate transformation from WGS84 lat/lon into the authoritative project CRS.
- Made manual coordinate transformation an advanced utility while keeping required project normalization automatic.
- Clarified the geomagnetic north-reference converter and displayed the correction inputs used.
- Added casing-string selection and cement top-of-cement interval workflow.
- Expanded well-control screening display with SICP comparison.
- Expanded QA/QC with inclination/DLS constraint checks, trajectory target-error checks and offset readiness.

## v6.2 — Covariance-Based Anti-Collision Upgrade

- Replaced the scalar anti-collision sigma workflow with a transparent covariance-based survey uncertainty model.
- Added independent station measurement errors plus correlated systematic inclination/azimuth bias and surface-position uncertainty.
- Propagated 3D North/East/TVD covariance to survey stations and exposed 1-sigma horizontal ellipse summaries.
- Updated Survey Manager to calculate/store the covariance profile with the trajectory.
- Updated Anti-Collision to compare trajectories in a common project frame and assess separation using directional relative uncertainty.
- Updated plan visualization to display stationwise 1-sigma uncertainty ellipses and keep main/offset wells in a common relative plotting frame.
- Explicitly labels the implementation as engineering-development screening, not an ISCWSA-certified error model.


## v6.4 — Anti-collision uncertainty and trajectory profile correction
- Corrected random angular-error covariance propagation so numerical perturbations and variances use the same degree units as the survey calculation. This prevents angular uncertainty from being artificially suppressed.
- Anti-collision treats zero/invalid propagated uncertainty as a review condition and reports incomplete comparisons explicitly instead of showing an all-clear banner when rows remain under review.
- Added trajectory profile generation for Vertical, J-Profile, S-Profile, Build & Hold, Build-Hold-Drop, Horizontal, ERD and Custom. The selected profile now generates a different inclination-versus-MD trajectory when Generate is pressed.
- Added a project maximum-inclination check for generated profiles.
- These remain engineering-development calculations, not ISCWSA-certified anti-collision or a full target-constrained trajectory optimizer.

## Audit follow-up — visualization and reference-state fixes

- Made wall-plot export geometry and axis bounds independent of the selected interactive view; export no longer relies on variables initialized only by the Wall Plot branch.
- Corrected survey azimuth reference validation to require declination and/or grid convergence according to the actual input-reference to project-reference conversion.
- Preserved selected depth reference, survey tool, and survey calculation method across Streamlit reruns.
- Stored the active geomagnetic model and its metadata in `reference_data` for consistent visualization export metadata.
- Distinguished uncertainty availability from whether uncertainty is shown in the export, and added a visible warning when requested uncertainty ellipses cannot be generated.
- Added regression tests for these behaviours.

## Follow-up — Target optimization and offset visualization
- Restored an explicit `Optimize Build & Hold to target` planning mode using KOP, build rate, target TVD and horizontal offsets to search hold inclination within the project maximum-inclination limit.
- Kept other trajectory profiles available in manual-profile mode and stored the active planning mode in trajectory metadata.
- Visualization now derives local minimum-curvature coordinates for offset wells that only contain MD/Inc/Azi survey stations, so their trajectories can appear in plan, vertical-section, 3D and wall-plot views.
- Added regression checks for target optimization UI integration and offset coordinate derivation.

## Profile-aware optimizer, offset survey workflow and theme toggle
- Added multi-parameter optimization for the selected trajectory profile using SciPy differential evolution. Search parameters include KOP, build rate, peak inclination and azimuth; S, Build-Hold-Drop and the current Custom template additionally optimize drop start, drop rate and final inclination.
- Target objective now uses target footprint containment for circular, elliptical, rectangular, corridor and polygon targets; point targets retain an explicit positional tolerance.
- Optimizer reports target miss, constraints, evaluation count and feasibility; it does not silently relax constraints.
- Added offset survey CSV template/download and import workflow with minimum-curvature coordinate generation and uncertainty metadata.
- Visualization now displays offset surface markers even when subsurface surveys are missing and provides per-offset plotting readiness diagnostics.
- Added optional in-app Light/Dark theme selection and matching Plotly templates.
- Added SciPy dependency for the optimizer.
- Limitation: Custom currently represents a configurable build-hold-drop template; arbitrary section-by-section custom control points remain future work. This remains practice/screening software, not an operationally certified trajectory design engine.

## Trajectory planner persistence follow-up (2026-10-12)
- Persisted the latest generated candidate separately as `planned_surveys` and `planned_trajectory_metadata`, while retaining the legacy active `surveys` collection for downstream compatibility.
- Trajectory Planner now restores and displays the saved candidate on page revisit rather than rendering results only during the generation-button rerun.
- Full/compact survey display is a view-only control with a stable Streamlit key; it does not run the optimizer or replace the candidate.
- Survey Manager may replace the active survey collection without destroying the separately saved planned candidate.

## 2026-10-12 — Target interception and Survey Manager export

- Updated optimizer target evaluation to inspect the full trajectory, including horizontal/near-horizontal sections after the first target-TVD crossing. This prevents a valid later intersection along a horizontal hold from being ignored.
- Target-intercept MD metadata now reflects the selected best target approach rather than always reporting the first TVD crossing.
- Added Survey Manager CSV export for the calculated/stored survey in field units; covariance matrices are excluded and uncertainty lengths are displayed/exported in feet.
- Added a regression test for a horizontal section that reaches the target laterally after its first target-TVD crossing.

## Targeted optimizer correction (2026-10-12)
- Reparameterized optimizer azimuth as a signed deviation from the wellhead-to-target bearing, avoiding the 0°/360° search-boundary issue for due-north targets.
- Added a modest target-centre tie-breaker so candidates inside a target footprint are not all treated as equally desirable regardless of centre miss.
- Increased default search effort moderately while keeping the test suite runtime practical.
- Exercised the distant, nearly due-north ERD case against the revised optimizer; it now returns a feasible candidate within the configured circular target in the local validation run.

## 2026-10-12 — KOP-constrained optimization modes
- Added explicit `Optimize (free KOP)`, `Optimize (fixed KOP)`, and `Optimize (KOP window)` modes alongside `Manual profile`.
- Fixed-KOP mode uses an equal-bound KOP variable, so optimization cannot silently move the entered KOP.
- KOP-window mode bounds the optimizer to the user-specified minimum and maximum KOP MD; the interval is converted from ft in the UI to the optimizer's internal metres.
- Optimization metadata now records the KOP mode and applied constraint.
- Added regression tests for fixed KOP, KOP-window enforcement, and invalid-window rejection.
- Validation: 50 tests passed; Python compilation passed. Streamlit interactive browser testing was not performed.

## Diagnostic and azimuth-turn update (2026-10-12)
- Added optional signed continuous azimuth turning beginning at KOP to the trajectory generator; minimum-curvature dogleg severity includes combined inclination and azimuth changes.
- Added azimuth turn-rate as an optimizer variable bounded by the configured maximum turn rate; independent post-search diagnostics report actual turn rate and violations.
- Added a manual-mode azimuth-turn-rate control (zero retains constant azimuth) and shared checks for target fit, maximum inclination, DLS and turn rate.
- Clarified target approach terminology: the reported best-approach station / target-TVD crossing is not by itself proof of a target hit. Target feasibility still requires lateral footprint and vertical tolerance.
- Increased optimization effort for ordinary searches (requested maxiter >= 5) by 50% to improve target-fit reliability while retaining short budgets for quick smoke tests.
- Added regression coverage for continuous azimuth turning and its configured rate limit.
- Scope note: this remains practice-grade piecewise trajectory software; changing azimuth is represented as a continuous constant-rate turn beginning at KOP, not a complete vendor-style 3D steering/BHA dynamics model.

## MD/TD target-intercept correction
- Added exact trajectory trimming at a validated target-intercept MD, including an interpolated final survey station.
- Optimized candidates are trimmed only when the target footprint/depth, required profile section, inclination, DLS, and azimuth-turn checks pass. Failed candidates retain the full search path for diagnosis and remain REVIEW.
- Manual candidates are likewise trimmed only after all current feasibility checks pass.
- Target crossings during build are no longer valid interceptions for profiles whose selected geometry requires completion of the build first; drop profiles require completion of the drop section.
- Added regression tests for final-MD truncation and rejection of a Horizontal target crossing during build.

## 2026-10-12 — Target-driven TD and ordered multiple-target planning
- Target-driven trajectory planning no longer treats the Well Architecture planned TD as an implicit hard ceiling. The default uses an internal search ceiling while calculating final TD from the valid final-target interception; users can explicitly enable a maximum-MD constraint.
- Added an ordered multiple-target selection workflow to Trajectory Planner. The final selected target defines the target-terminated TD, and the optimizer scores every required target against its depth/footprint and enforces increasing interception MD order.
- Added per-target interception results (MD, lateral/vertical error, footprint miss, order and tolerance flags) to optimizer metadata and the saved-result UI.
- Multiple-target planning requires an optimization mode; Manual profile mode explicitly refuses to imply that a single-target manual candidate satisfies a sequence.
- Added regression tests for malformed sequence inputs and vertical-well target sequences.
- Validation performed: Python compilation passed; project/pressure tests passed (2); multi-target tests passed (2). Broader trajectory/optimizer tests exceeded the execution time limit when run together, so full end-to-end validation remains outstanding.

## General trajectory optimizer development build
- Added an experimental control-point trajectory optimizer with variable inclination and azimuth schedules integrated through minimum-curvature survey calculations.
- Added ordered-target support, inclined target-plane residuals (dip/dip direction), optional target approach azimuth/inclination constraints, and optional wellbore/target-plane intersection-angle constraints.
- Added optimization-time offset avoidance screening and independent covariance-based clearance validation; the uncertainty envelope used during search is explicitly documented as approximate and development-grade.
- Added a configurable separation-factor threshold to the independent anti-collision screening report; the report samples the pairwise trajectory grid and separately reports geometric closest approach and minimum sampled SF locations.
- Added target deletion confirmation and marks saved trajectories that depended on a deleted target as REVIEW.
- Added regression tests for general optimization, missing offset survey review, target sequence metadata, inclined plane geometry and intersection-angle calculations.
