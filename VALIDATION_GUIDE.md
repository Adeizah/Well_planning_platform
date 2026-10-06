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
