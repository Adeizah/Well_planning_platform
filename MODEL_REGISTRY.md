# Model Registry

| Model / library | Purpose | Status | Provenance |
|---|---|---|---|
| WMM2025 via pywmm | Magnetic declination, dip, total field, X/Y/Z | Integrated | NOAA/NCEI WMM2025 |
| PROJ / pyproj | CRS and coordinate transformation | Integrated | OSGeo PROJ / EPSG |
| NOAA geoid service | Geoid height query | Optional live | NOAA NGS |
| WGS84 normal gravity | Reference gravity | Integrated | WGS84 normal-gravity formulation |
| ISCWSA concepts | Survey uncertainty / anti-collision methodology | Screening concepts only | ISCWSA public methodology |

## Provenance rule

Model name, epoch/date, coordinates and relevant settings should be stored whenever a model-derived value is written into a project.
