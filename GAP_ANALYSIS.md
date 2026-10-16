# Gap analysis — Well Planning Platform vs. the Master Requirements Checklist

Audit of `well-planning-platform-general-trajectory-optimizer.zip` and the changes made in this revision.
Rule applied throughout: **no new feature may break existing behaviour, and no trajectory is valid just because
an optimizer found it.**

> **Honesty notes.** (1) The audit sandbox had no network, no Streamlit, no pyproj/plotly. Engine code was run and
> tested for real; `app.py` was executed page-by-page through an offline harness (`tests/app_harness.py`) that fakes
> Streamlit. That catches logic/NameError/KeyError regressions but **not** layout or real-browser behaviour — the
> checklist item *"verify in a live running environment"* is still open (`streamlit run app.py`, then click through
> the new flows listed at the end). (2) Two original tests need real pyproj and could not run here
> (`test_grid_convergence_is_not_hardcoded`, `test_v5_engineering_smoke_chain`); they failed identically on the untouched project.
> (3) Optimizer benchmarks below are 10 scenarios on one machine — evidence, not a guarantee.

## 1. Defects found (all reproduced with a script before fixing)

| # | Severity | Defect | Evidence | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | **Safety-relevant** | Anti-collision separation factor swapped **North and East**: the centre-to-centre unit vector was (E,N,TVD) but was multiplied by a (N,E,TVD) covariance. | Vertical wells 10 m apart: N-S spacing reported SF 4.64 **PASS**; correct SF is 1.29 **WARNING**. | Consistent (N,E,TVD) ordering in `engineering/anti_collision.py`. | `test_separation_factor_uses_correct_north_east_axes` |
| 2 | High | Closest approach taken from a fixed 250/300-point grid on **chords** between stations. | Crossing wells: reported 3.3 m, true 0 m. | Exact minimum-curvature arc sampling (≤10 m spacing) + continuous refinement of closest-approach and min-SF pairs. | `test_closest_approach_is_continuous_not_sample_limited` |
| 3 | High | Surveys whose first MD > 0 (typical for imported offset wells) got TVD starting at 0 → everything too shallow by the first MD. | MD 100/200/300 vertical → TVD 0/100/200. | Vertical tie-in assumed (flagged), or explicit `tie_in=`; QC warns. | `test_survey_not_starting_at_md_zero_gets_vertical_tie_in` |
| 4 | High | Polygon targets: outline and miss distance ignored the target centre. | Point 10 m outside a polygon at (1000,1000): miss 1386 m. | Boundary translated by centre. | `test_polygon_boundary_and_miss_use_the_target_centre` |
| 5 | High | Every planner run — including failed candidates — **overwrote the active/measured survey**. | `project['surveys']=records` unconditional. | Only validated (PASS) plans become active; previous survey is backed up (`survey_backup`); candidates always kept in `planned_surveys`. | `test_failed_manual_candidate_never_overwrites_the_measured_survey` |
| 6 | High | "Mark trajectory REVIEW when a target/dependency changes" existed only for target **deletion**, and the reason was never shown. | `stale_reason` set once, never rendered. | Dependency snapshot (targets, surface/KB/CRS, constraints, uncertainty model, offsets, survey hash) checked on every run; banner + QA/QC + Reports. | `test_dependency_changes_downgrade_the_plan_to_review` |
| 7 | Medium | Optimizer verdicts were trusted; tests accepted either `FEASIBLE` or `NO_FEASIBLE` (tautology). | `assert status in {...}`. | Independent validator (below) for **every** mode; easy case now asserts PASS. | `test_optimizer_pass_is_confirmed_by_independent_validation` |
| 8 | Medium | Uncertainty model O(n²) with pandas row access: 300 stations ≈ 46 s, so offsets with real survey density froze the app. | measured | Vectorised, numerically identical (≤4e-12 vs original loop): 300 stations 0.01 s. | `test_vectorised_covariance_matches_the_original_loop_implementation` |
| 9 | Medium | Minimum curvature used pandas `.loc` loops (the optimizer calls it thousands of times). | measured | Vectorised, identical to 1e-11: ~150× faster. | `test_vectorised_minimum_curvature_matches_textbook_formula` |
| 10 | Medium | Truncating a path interpolated on the **chord** (32 m error at 500 m stations; ~1–2 m at the optimizer's 85 m stations). | measured | Exact circular-arc interpolation (`interpolate_path`). | `test_truncation_places_the_final_station_on_the_arc` |
| 11 | Medium | Failed-candidate display limit (~100 ft beyond target approach) not implemented. | grep | `core/visual.py`, used by Visualization (display only; stored path untouched). | `test_failed_candidates_are_clipped_for_display_only` |
| 12 | Medium | Optimizer-outcome panel keyed on a mode name that no longer exists → never shown for the three Optimize modes. | string compare | Mode tuple corrected. | workflow tests |
| 13 | Medium | Targets could be created/deleted but not **edited**; tolerance hard-coded 100 ft; no thickness; polygon units unlabeled. | UI code | Edit form, per-target lateral/vertical tolerance and thickness, rectangle orientation, polygon label (metres, offsets from centre). | `test_target_can_be_added_and_edited…` |
| 14 | Low | Survey Manager offered Average Angle / Balanced Tangential but always used minimum curvature. | code | Explicit warning; (not implemented). | — |
| 15 | Low | Table column `VS` is horizontal closure, not a vertical section. | code | Documented; `vertical_section()` added. | `test_vertical_section_is_a_projection_not_closure` |
| 16 | Low | UI tests only grep `app.py` text; offset TVD datum (KB) ignored; offset CSV import unvalidated. | tests / code | Offline execution harness; `kb_m` per offset + datum shift; `core/survey_qc.py` on all imports. | `test_every_page_executes…`, `test_offset_kb_datum_shift_is_applied` |

## 2. New capabilities

* **`core/validation.py` — independent validator.** Rebuilds the well from MD/Inc/Azi (stored coordinates are only *compared*), cross-checks minimum curvature by numerical integration, checks inclination / DLS / build / turn / KOP / max MD / station spacing, finds ordered target interceptions on the arcs *between* stations (footprint, inclined plane, thickness, approach azimuth/inclination/intersection angle), requires the plan to **end** at the final interception, and runs anti-collision plus a brute-force closest-distance cross-check. Used by the optimizer, by manual/legacy profiles in the app, and exposed for imports.
* **`core/feasibility.py` — proof vs. failed search.** Analytic necessary conditions (reach bound from build-rate/inclination limits, TVD monotonicity for inclination < 90°, MD ≥ TVD, pairwise horizontal-vs-vertical bound). If one fires the plan is reported `INFEASIBLE_PROVEN` with reasons; otherwise a failed run is `NO FEASIBLE CANDIDATE FOUND` ("not found", never "impossible").
* **Optimizer** (`core/general_optimizer.py`): multi-seed (J / ramps / per-target bearings / left-right detours around offsets) → scaled L-BFGS-B → adaptive control-point count 4→10 (simplest shape wins, a one-step challenger may replace it if it validates and is better after a complexity charge) → optional adaptive segment lengths → collision-buffer escalation on clearance failure → continuation polish toward the target centre. Time budget configurable.
* **Anti-collision**: configurable required SF, hard minimum centre-to-centre distance, hole/casing radii, collision-risk MD intervals, per-MD clearance profile, KB datum alignment; UI controls on the Anti-Collision page.
* **Result classes** `PASS` / `REVIEW` / `NO FEASIBLE CANDIDATE FOUND` (+ `INFEASIBLE_PROVEN` detail) stored as `result_class`.

Measured on the 10-scenario matrix (original → now): feasible cases solved **6/8 → 8/8** (two-target and offset-avoidance were failing); the 2 infeasible cases went from "REVIEW after search" to **proven infeasible in ~2 s**. Every PASS is re-confirmed by the independent validator.

## 3. Checklist status

Legend: ✅ done & tested here · 🟡 partly / needs live check · ⛔ open

| § | Requirement | Status | Notes |
|---|---|---|---|
| 1 | Wellhead, KB, ground elevation; CRS; True/Grid/Mag north; units; save/import/export | 🟡 | Existing and unchanged; new keys are additive (old projects load). Geodesy/geomagnetic tests need real pyproj/pywmm — not runnable offline. |
| 2 | Create / **edit** / delete targets; all shapes; tolerances; dip & direction; **thickness**; approach constraints | ✅ / 🟡 | Edit, tolerances, thickness, rectangle rotation, polygon fix done. Thickness is used in validation but not drawn as a volume. |
| 2 | Targets correct in plan / VS / 3D | 🟡 | Polygon location fixed; intercept markers in plan & 3D; VS-view markers not added. |
| 3 | Profiles; Manual/Free/Fixed/KOP-window | 🟡 | Legacy modes unchanged. General optimizer accepts `min/max_kop_md_m` but the UI does not expose them yet. |
| 3 | Shape-flexible optimizer, variable inc/azi, add/remove sections, adaptive controls & lengths, local nudges, centre preference, ordered multi-target, stop at final target, max MD | ✅ | See §2. "Remove sections" = smallest feasible control-point count wins; no automatic removal of segments in a manual plan. |
| 4 | DLS / build / turn / inc / azi / KOP / max MD; continuity; between-station validation; same validation for manual and optimized | ✅ | Azimuth limits (absolute bounds) are not a separate constraint. Turn rate ignored where inclination < 0.5° (azimuth undefined) — documented. |
| 5 | Offset management, import, validation, joint visualization, per-well uncertainty | 🟡 | Import QC + KB datum added. Uncertainty parameters are still **global**, not stored per well; offset uncertainty regions are not drawn. |
| 6 | 3D separation, closest approach with MDs, uncertainty, SF, configurable criteria, between stations, risk intervals, in optimization, alternative paths, "cannot establish safety" | 🟡 | Implemented and corrected. **The uncertainty model is a development model, not ISCWSA** (no hole/casing geometry beyond optional radii, random errors of adjacent segments treated as independent, no pedal-curve/ellipse-of-uncertainty method). Cannot be called "validated". |
| 7 | Optimization engine; failed search vs proof | ✅ | Proof covers necessary conditions only; absence of a proof ≠ feasibility. |
| 8 | MD/TVD/TVDSS/N/E/Inc/Azi, minimum curvature, consistent references, uncertainty reporting | ✅ / 🟡 | TVDSS is an elevation (KB − TVD) by design — documented in UI. Average-angle/balanced-tangential not implemented. |
| 9 | Plan / VS / 3D plots; targets, offsets, uncertainty; control points & section boundaries; intercept & closest approach; ~100 ft failed-candidate limit; reports | 🟡 | Intercept/closest-approach markers, clipping, reports done. Control-point / section-boundary markers **not** drawn; offset uncertainty regions not drawn. |
| 10 | Preserve pages; sync storage / planner / Survey Manager; mark review on change; reliable import/export; don't break projects | ✅ / 🟡 | All 21 pages execute on new and example projects (offline harness). Real-browser run still required. |
| 11 | Regression tests incl. nearby/far/deep, multi-target, reversed, inclined, DLS violations, offsets, infeasible, reload, exports; independent validation; live run | 🟡 | +42 tests (60 → 102). Project export/import round-trip is covered by the existing tests; **live verification still open**. |
| 12 | PASS / REVIEW / NO FEASIBLE CANDIDATE FOUND; document assumptions; validate against industry/company rules; keep "learning" status | ✅ / ⛔ | Classes implemented. **Validation against industry/company anti-collision rules is not done and cannot be done by software alone.** |

## 4. Still open (priority order)

1. Run the app live (`streamlit run app.py`) and exercise: add/edit target → generate (general + manual) → edit target (banner appears) → Visualization source switch → Anti-Collision criteria → offset CSV import with a bad row.
2. Replace the development uncertainty model with an ISCWSA-conformant one (HLA frames, 2.79σ ellipses, correlated systematic terms) and validate against published ISCWSA reference wells and your company rules.
3. Per-well uncertainty parameters; draw offset uncertainty regions; control-point markers.
4. Expose KOP window / fixed KOP for the general optimizer; optional hard azimuth limits.
5. Large-scale optimizer benchmark (hundreds of random scenarios) before relying on its search success rate.
6. Optional: pre-existing `datetime.utcnow()` deprecation warnings in `app.py`.
