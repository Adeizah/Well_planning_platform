# 🛢️ Well Planning Platform

A browser-based, project-independent drilling engineering and well-planning workspace.

> **Important:** This is engineering-development/training software. It is not a replacement for licensed well-planning packages, company standards, OEM data, approved well-control procedures, specialist survey software, or competent engineering review.

## What this is

The application is designed so that **WN-01 or any other example is just a project inside the platform**.

Each project can have its own:

- well coordinates
- coordinate reference system
- north reference
- KB / elevation
- survey data
- targets
- offset wells
- geomagnetic calculations
- geodetic corrections
- engineering assumptions
- model provenance

## Current capabilities

### Survey / directional

- Minimum-curvature survey calculation
- TVD
- TVDSS reference offset
- Northing / Easting
- Vertical section / closure
- Dogleg severity
- 2D and 3D trajectory visualization
- CSV survey import

### Geomagnetics

- WMM2025 calculation
- Declination
- Inclination / dip
- Total field
- Horizontal field
- X / Y / Z components
- Date-aware calculation
- Model provenance

### Geodesy

- PROJ/pyproj coordinate transformations
- Live NOAA NGS geoid-height query where the selected service/model covers the location
- Model/service provenance

### Engineering screening modules

- Targets
- Offset inventory
- Anti-collision screening
- Casing screening
- Hydraulics / ECD screening
- Basic well-control calculations
- Cement-volume screening
- Basic torque & drag screening
- QA/QC
- Project JSON import/export

## Model philosophy

The application deliberately separates:

**Model layer**

- WMM2025
- future IGRF
- geoid services
- CRS / EPSG / PROJ
- future gravity services
- survey uncertainty models

from:

**Calculation layer**

- minimum curvature
- DLS
- trajectory geometry
- clearance
- hydraulics
- casing
- well control
- cement
- torque & drag

This makes it possible to upgrade a model without rewriting the entire application.

## Geomagnetic note

WMM2025 is the current World Magnetic Model epoch and is valid through 2029. The model provides magnetic declination, inclination, total field and magnetic field components.

For directional-drilling work, WMM is only a model of the Earth's main magnetic field. It does **not** replace measured downhole magnetic data, magnetic-interference assessment, local crustal-field effects, or a full survey-error model.

## Geodesy note

The NOAA NGS geoid API is a public service, but its geoid products have geographic coverage limitations. A failed/no-data response outside coverage should not be treated as a numerical zero.

## Repository structure

```text
well-planning-platform/
│
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
│
├── .streamlit/
│   └── config.toml
│
├── .github/
│   └── workflows/
│       └── tests.yml
│
├── core/
│   ├── project.py
│   ├── trajectory.py
│   └── units.py
│
├── models/
│   ├── geomagnetic.py
│   └── geodesy.py
│
├── engineering/
│   ├── anti_collision.py
│   ├── casing.py
│   ├── cement.py
│   ├── hydraulics.py
│   ├── torque_drag.py
│   └── well_control.py
│
├── data/
│   └── example_project.json
│
└── tests/
    ├── test_project.py
    └── test_trajectory.py
```

## Run locally

Python 3.10+ is recommended.

```bash
git clone https://github.com/YOUR_USERNAME/well-planning-platform.git
cd well-planning-platform
python -m pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL shown by Streamlit.

## Deploy to GitHub + Streamlit Community Cloud

1. Create a GitHub repository named `well-planning-platform`.
2. Upload the contents of this repository to the repository root.
3. Go to Streamlit Community Cloud.
4. Connect GitHub.
5. Create a new app.
6. Select:
   - Repository: your `well-planning-platform`
   - Branch: `main`
   - Main file: `app.py`
7. Deploy.

After deployment, the application is accessible through a browser at a `streamlit.app` address.

The repository's `requirements.txt` tells Community Cloud what Python packages to install.

## Browser-only workflow

Once deployed, your work computer does **not** need:

- Python
- Anaconda
- VS Code
- Git
- Streamlit

It only needs a browser and network access to the deployed application and any external public services you choose to query.

## Using GitHub Codespaces

If you want to modify the application without installing a development environment on your personal/work computer, GitHub Codespaces can provide a browser-based development environment.

## Data and security

Do not upload confidential company well data, proprietary survey data, client information, or restricted operational documents to a public GitHub repository.

For real projects, consider:

- a private GitHub repository
- appropriate access controls
- a private deployment
- removal/anonymization of proprietary data
- company cybersecurity approval

## Engineering roadmap

The architecture is intentionally ready for more serious modules:

1. Survey correction framework
2. IGRF-14
3. WMM uncertainty / error model integration
4. Grid convergence
5. Magnetic declination correction workflow
6. Gravity / geoid model registry
7. ISCWSA-style survey uncertainty
8. Error ellipsoid propagation
9. Full 3D anti-collision
10. Separation factor
11. Target-window optimization
12. Trajectory design algorithms
13. Drillability / DLS constraints
14. Full casing design
15. Pressure / fracture-gradient model
16. More rigorous hydraulics / ECD
17. Surge / swab
18. Soft-string torque & drag
19. BHA mechanics
20. Drill-bit selection
21. Cement design
22. Well-control worksheets
23. Automated drilling-program generation
24. Engineering report generation

## Sources

- NOAA/NCEI World Magnetic Model
- IAGA International Geomagnetic Reference Field
- PROJ / EPSG geospatial standards
- NOAA National Geodetic Survey web services
- ISCWSA survey-management concepts

## Version

`1.0.0` — general-purpose browser platform foundation.
