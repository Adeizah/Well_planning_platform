# Unified Trajectory Optimizer — implementation notes

## What changed

- Replaced the multiple trajectory-planning modes on the Trajectory Planner page with one **Optimize trajectory** workflow powered by `core.general_optimizer.optimize_general_trajectory`.
- Consolidated trajectory constraints into one visible group: maximum inclination, maximum DLS, maximum build rate, maximum drop rate, and maximum azimuth turn rate.
- Build and drop rates are now distinct signed inclination-rate limits. Positive inclination change is build; negative inclination change is drop. Both are applied in the general optimizer's objective/feasibility checks and independently validated.
- Added KOP modes: **Automatic**, **Fixed MD**, and **Within tolerance**. MD and tolerance are entered in feet and converted to the internal metre coordinate system. Fixed MD is represented by equal lower and upper KOP bounds.
- Added **Fast**, **Balanced**, and **Thorough** effort presets with global search budgets of 30, 90, and 180 seconds and solver iteration caps of 40, 80, and 140, respectively.
- The optimizer checks the global deadline between search stages and within local solver iterations. Section reconstruction receives only a share of the same overall budget; it does not get an independent full budget.
- The accepted general trajectory remains the primary result if section reconstruction fails. Section reconstruction is reported separately and cannot turn a failed reconstruction into an optimizer failure or replace the validated base path with an invalid sectionized path.
- Added result diagnostics for configured limits, effort preset, elapsed/budget time, solve and iteration counts, KOP mode, and observed maximum drop rate.
- Added focused regression tests for distinct build/drop validation, optimizer API controls, and unified UI wiring.

## Preset settings

| Preset | Global search budget | Per-solve iteration cap |
|---|---:|---:|
| Fast | 30 s | 40 |
| Balanced | 90 s | 80 |
| Thorough | 180 s | 140 |

These are starting presets for this application, not industry standards. Timing can vary with target complexity, offset wells, machine performance and validation costs. A solver iteration cap and a wall-clock budget are separate limits.

## Validation notes

- A candidate is not accepted merely because the optimizer reports success; the independent trajectory validator remains the acceptance gate.
- A search that expires without finding a valid candidate does not prove that the well is infeasible.
- A fixed KOP is implemented as a zero-width permitted KOP interval. Since the optimizer parameterizes inclination control points rather than a dedicated KOP variable, exact fixed-KOP convergence remains sensitive to numerical optimization; inspect the independent KOP validation result.
- Section reconstruction remains a secondary representation. Its failure status must be interpreted separately from the general trajectory's validation status.
- This platform remains an engineering-development tool and is not certified operational well-planning or ISCWSA anti-collision software.
