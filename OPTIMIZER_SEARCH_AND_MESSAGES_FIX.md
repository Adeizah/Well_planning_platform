# Optimizer search and concise result messages

## Stage 1 search changes
- Removed the early stop after two preliminary-feasible starts.
- Evaluates the available shortlist (up to six starts per control-point stage), respecting the global deadline during candidate scoring and before each solve.
- Independently validates preliminary-feasible candidates in objective order. A candidate that fails final validation no longer prevents a later candidate from being tested.
- Keeps the best-effort candidate for review if no candidate passes; failure to find one is not represented as proof of infeasibility unless the analytic reachability screen proves it.
- Adds short `stage1_summary` and `stage2_summary` metadata fields.
- Checks the global deadline while scoring candidates for the higher-control-point challenger.

## Stage 2 sectionization changes
- Applies separate build and drop limits in section-rate bounds (`-max_drop` to `+max_build`) instead of assuming symmetric limits.
- Checks the section solver's allotted budget during objective/constraint evaluations so a long SLSQP run can stop when its budget expires.
- Preserves the Stage 1 trajectory unless a reconstructed trajectory independently validates and is accepted.

## UI messaging
- Stage 1 and Stage 2 each show one short summary by default.
- Detailed solver, validation, sectionization-attempt, and constraint-margin information is collapsed into expanders.
- Sectionization attempt details are shown as a compact table rather than a stream of separate messages.

## Validation performed
- Python compilation passed.
- `tests/test_section_reconstruction.py`, `tests/test_unified_optimizer.py`, `tests/test_v5_ui_and_smoke.py`, and `tests/test_general_optimizer.py`: 21 passed.
- `tests/test_app_workflows.py`: 5 passed (deprecation warnings only).
- `tests/test_exact_targets_and_stage2.py` exceeded the available 60-second test run; full-suite success is not claimed.
