# Changelog

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
