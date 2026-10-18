# Release test report — 2026-10-17

Environment: sandbox without network. `numpy`, `pandas`, `scipy` present; **real `pyproj`, `streamlit`, `plotly` and `pytest` were NOT installed**.
Tests were run with a minimal pytest-compatible runner (per-test 150 s time limit) and the project's own `tests/app_harness.py`.
For the app-workflow tests only, a minimal `pyproj` stand-in (WGS84/UTM only) was placed on the path so that `models.geodesy` could be imported.

## Result of the final full run (final code)
**127 passed, 9 failed, 0 timed out.** Slowest test 14.1 s.

| Test file | Result |
|---|---|
| test_app_workflows | 5 passed (incl. new Stage 2 UI test) |
| test_audit_fixes | 15 passed (assertions updated for exact point targets) |
| test_exact_targets_and_stage2 (new) | 17 passed |
| test_general_optimizer | 5 passed (previously one test alone took ~93 s) |
| test_geomagnetic, test_pressure, test_project, test_survey_uncertainty, test_trajectory | all passed |
| test_multi_target_planning, test_optimizer, test_section_reconstruction | all passed |
| test_trajectory_planner_revision, test_v4_features, test_v5_ui_and_smoke | all passed |
| test_validation | 24 passed (incl. KOP / max-MD, offset avoidance, independent re-check) |
| test_visualization_regressions | 6 passed |
| **test_geodesy_registry** | **3 passed, 9 FAILED — environmental** |

### The 9 failures
`test_common_registry_includes_wgs84_and_minna`, `test_crs_info_reports_minna_datum`, `test_minna_projected_crs_is_recognized_even_if_transform_accuracy_is_unknown`,
`test_projected_grid_coordinates_are_normalized_to_metres_for_foot_crs`, `test_projected_grid_reprojection_preserves_physical_location_between_utm_zones`,
`test_search_epsg_registry_by_code_and_name`, `test_strict_wgs84_to_utm_transform_is_finite_and_roundtrips`, `test_transform_report_has_non_ballpark_wgs84_utm_operation`,
`test_transformation_report_does_not_crash_for_minna_projected_crs`.
They need the real PROJ/EPSG database (Minna datums, foot CRSs, transformation operations) that a stand-in cannot provide. They are **unverified, not known-good**:
run `pytest tests/test_geodesy_registry.py` with `pyproj` installed before release.

### Not run in this environment
`tests/test_app_startup.py` (needs `streamlit.testing.v1.AppTest`). Run the full suite with `pip install -r requirements.txt && pytest` in CI.

## Deployment-style smoke checks performed
- `python -m compileall app.py core models engineering tests`: OK.
- Every page executes for a new and the example project (`test_every_page_executes_for_new_and_example_projects`): passed.
- General-optimizer click path through the Trajectory Planner page, Stage 2 enabled and disabled: passed.

## Speed measurements (sandbox, same results)
| Case | Before | After |
|---|---|---|
| General optimizer, one point target | ~93 s (whole budget) | ~1-3 s |
| Two ordered point targets | ~73 s | ~3-5 s |
| Min-KOP constrained case | failed after 67 s | PASS in ~9 s |
| `minimum_curvature`, 67 stations | 2.1 ms | 0.29 ms |
| Point-to-arc closest approach | 3.8 ms | 0.33 ms |
Equivalence checks: numpy kernel bit-identical to the validated path; fast `minimum_curvature` vs original: 0/200 mismatches, worst 9e-12;
vectorised `core/optimizer._target_residual` vs original: 0/300 mismatches.
