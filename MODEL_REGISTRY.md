# Model Registry

| Model / service | Purpose | Status | Notes |
|---|---|---|---|
| WMM2025 | Main geomagnetic field | Integrated | Date-aware; valid 2025–2030 |
| IGRF-14 | Global geomagnetic reference | Planned | Add as a separate model adapter |
| PROJ | CRS and geodetic transformation | Integrated | Local |
| EPSG | CRS definitions | Via PROJ | Local database |
| NOAA NGS Geoid API | Geoid height | Integrated | Coverage dependent |
| NOAA GRAV-D | Gravity | Planned | Coverage/data-product dependent |
| ISCWSA-style uncertainty | Survey uncertainty | Planned | Must be implemented against the applicable specification |
| WMM error model | Geomagnetic uncertainty | Planned | Separate from main-field value |

## Provenance rule

Every model-derived result should retain:

- model name
- model version/epoch
- calculation date
- coordinates
- altitude reference
- CRS/reference frame
- source
- query timestamp for live services
- relevant uncertainty where available
