# Reference setup update

## User-facing workflow
- Project & Reference is the only navigation location for geomagnetic and geodetic reference setup.
- IGRF-14 is the only selectable/calculated geomagnetic model in the setup workflow.
- Magnetic values can be calculated using IGRF-14 or supplied manually. Manual values are tagged as user supplied and are not labelled as calculated IGRF output.
- Grid convergence can be calculated from the selected projected CRS and wellhead location or entered manually. The source is recorded in project reference data.
- Grid convergence, magnetic declination, dip, field components, total field and normal gravity remain stored in shared project reference data for downstream survey/trajectory workflows.

## Minna and CRS transformations
- Coordinate transformations now infer a location-specific area of interest from projected source coordinates where possible.
- Strict transformations use PROJ's non-ballpark TransformerGroup and require stated accuracy. If no suitable operation exists, the application raises an actionable error and does not relabel coordinates.
- Transformation diagnostics list available operations, their stated accuracies, unavailable operations and missing grids.
- Minna CRSs are discoverable from the installed EPSG registry. This does not imply all Minna transformations have survey-grade accuracy: the selected operation's published accuracy and local control must be checked. Some regional Minna/WGS 84 operations have metre-level stated accuracy, which may be unsuitable for high-accuracy well positioning.

## Validation
- `python -m compileall -q app.py models core` passed.
- `pytest -q tests/test_geodesy_registry.py tests/test_geomagnetic.py tests/test_project.py`: 17 passed.
- A broader combined run exceeded the available runtime and is not claimed as passed.
- IGRF coefficient provenance and numerical agreement with DirectionalPlan remain to be independently verified. This change simplifies model selection; it does not claim to resolve the previously observed IGRF numerical discrepancy.
