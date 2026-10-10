# Validation Guide

Before recommending the platform to others, use these checks as a minimum practice suite.

## Survey

1. Vertical well: 1,000 m MD should produce 1,000 m TVD.
2. Constant-inclination well: compare against the analytical sine/cosine relationship.
3. Minimum-curvature result should be independently reproduced in a spreadsheet or reference package.
4. Confirm magnetic → true → grid conversions with a known example.

## Geodesy

1. Verify CRS metadata against EPSG/PROJ.
2. Compare coordinate transformations with an independent GIS/geodesy package.
3. Compare grid convergence with a trusted geodetic calculator.
4. Treat normal gravity as a reference value, not local gravity anomaly.

## Geomagnetics

1. Compare WMM2025 output with an authoritative WMM implementation at several locations and dates.
2. Record model version, epoch, date, location and elevation.
3. Do not use the model as a substitute for local magnetic-interference assessment.

## Trajectory

1. Verify build/hold planning against an independent calculation.
2. Check DLS against station interval and design limits.
3. Confirm target miss distance and TVD error.

## Anti-collision

1. Validate interpolated separation using known trajectories.
2. Confirm units and coordinate reference are identical between wells.
3. Treat screening separation factors as non-operational until the uncertainty model is validated.

## Casing

1. Validate geometry and setting-depth ordering.
2. Compare pressure loads against independent calculations.
3. Do not use screening burst/collapse proxies as certified tubular design.

## Hydraulics / T&D / Cement / Well Control

Use independent spreadsheet calculations and company/OEM/reference models before relying on outputs for engineering decisions.

## Trajectory planner profile regression matrix (revision 2026-10-10)

The trajectory planner advertises six profiles: Vertical, J-profile / Build & Hold, S-profile / Build-Hold-Drop, Horizontal, ERD, and Custom. Each profile should be tested in both manual and optimize-to-target modes against the same target, depth reference, planned TD, and constraints.

Minimum regression checks:

1. The generated MD stations are strictly increasing and do not exceed the configured planning MD limit.
2. Target interception is interpolated at target TVD; target-centre lateral error and footprint miss are reported separately where applicable.
3. A candidate is only marked PASS/FEASIBLE when the target tolerance, vertical tolerance, maximum inclination, maximum DLS, and profile-specific section-order checks pass.
4. Vertical trajectories are expected to fail for laterally displaced targets; this is a legitimate infeasibility result, not an optimizer bug.
5. J / Build & Hold uses build-and-hold geometry. S / Build-Hold-Drop retains the drop section in the complete survey.
6. Horizontal requires a compatible inclination limit. ERD requires an inclination range compatible with the project maximum.
7. Compact section-endpoint tables are a display-only filter; full stations remain in the stored survey.
8. Compare profile plots, target intercept MD, lateral miss, TVD error, KOP, section boundaries, final MD, final inclination, max DLS, and constraint violations.

Automated regression tests cover profile generation and run a low-iteration optimizer smoke test for all six profiles. Passing those tests does not establish that every target/profile combination is feasible or that optimization has converged. Manual visual validation against representative easy, difficult, and unreachable targets remains required.

Known limitation: the current candidate parameterization uses a constant azimuth for each trajectory. A true multi-section azimuth-turn schedule and independent turn-rate enforcement are not implemented yet; do not interpret the configured maximum turn rate as validated for a trajectory that changes azimuth by section. Custom is currently a generic build/hold/drop template, not a free-form section editor.
