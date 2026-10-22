# Point-target tolerance update

- Point targets are accepted when the continuous minimum-curvature path's closest 3-D distance to the target centre is <= 2 ft (0.6096 m).
- This is a spherical 3-D acceptance envelope, not a separate 2 ft allowance on each axis.
- The optimizer objective and exact-target polishing continue to minimize the distance to the centre; the 2 ft value is not a target-seeking objective and does not replace the centre coordinates.
- The much tighter `POINT_NUMERIC_TOL_M` remains reserved for numerical polishing/convergence and is no longer used as the point-target pass/fail threshold.
- General optimizer result evaluation, independent trajectory validation, and the legacy profile optimizer use the same acceptance constant.
- Section reconstruction continues to aim at the target centre through its equality residuals; the reconstructed path is independently checked against the same 2 ft acceptance threshold before it can be accepted.
- Non-point target acceptance rules are unchanged.

The tolerance is applied to continuous 3-D closest approach on the minimum-curvature arcs, with ordered target checks preserved. A trajectory outside the 2 ft envelope is not accepted merely because its optimizer objective is low.
