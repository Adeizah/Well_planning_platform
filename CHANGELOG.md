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
