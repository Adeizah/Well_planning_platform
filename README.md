# Well Planning Platform

A browser-first, project-independent drilling engineering and well-planning practice platform.

## Purpose

Well Planning Platform combines geodesy, geomagnetics, survey management, trajectory planning, target geometry, offsets, anti-collision screening, casing architecture, hydraulics/ECD, torque & drag, cementing, well control, BHA documentation, visualization and QA/QC in one project model.

It is designed for students, trainees, drilling engineers, directional drillers, MWD/LWD engineers, petroleum engineers, researchers and educators who want a practical environment for building complete synthetic well plans.

> **Engineering disclaimer:** This is practice and engineering-development software. It is not certified operational software and must not be the sole basis for drilling decisions. Validate calculations against applicable standards, company procedures, OEM data, specialist software and competent engineering review.

## Highlights

- Desktop-first engineering workspace UI layered over the stable v4.0 project schema
- CRS / datum / ellipsoid awareness through PROJ/pyproj
- WMM2025 geomagnetic calculations with provenance
- Magnetic, true and grid azimuth conversion
- Grid convergence and normal gravity
- Public geoid query support where the NOAA service is available
- Survey import, minimum curvature, DLS, TVD, TVDSS, N/E and vertical section
- Screening positional uncertainty
- Target geometries: point, circular, elliptical, rectangular, corridor and polygon
- Target-driven build/hold trajectory planning
- PP/FG and mud-window screening
- Offset wells with independent trajectories
- Screening anti-collision and separation-factor workflow
- Final casing architecture stored as master project data
- Casing burst/collapse/tension screening
- Hydraulics/ECD screening with basic rheology options
- Torque & drag screening
- Cement-volume screening
- Well-control screening
- BHA/drilling configuration records
- Integrated plan, vertical-section and 3D visualization with target, offset and well annotations
- QA/QC, JSON project export and report export
- Example project, regression tests and cross-module engineering smoke tests

## UI / UX philosophy

The current workspace focuses on a desktop/workstation workflow rather than mobile/tablet optimization. The navigation is organized around the actual well-planning sequence, while the engineering engines and shared project schema remain backward-compatible with v4.0 project files.

## Run locally

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

Deploy the repository with:

- Main file: `app.py`
- Dependencies: `requirements.txt`
- Python source: `core/`, `models/`, `engineering/`

## Repository structure

```text
well-planning-platform/
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── MODEL_REGISTRY.md
├── core/
│   ├── geometry.py
│   ├── project.py
│   ├── reference.py
│   ├── trajectory.py
│   └── units.py
├── models/
│   ├── geodesy.py
│   └── geomagnetic.py
├── engineering/
│   ├── anti_collision.py
│   ├── casing.py
│   ├── cement.py
│   ├── hydraulics.py
│   ├── torque_drag.py
│   ├── pressure.py
│   └── well_control.py
├── data/
│   └── example_project.json
└── tests/
    ├── test_project.py
    └── test_trajectory.py
```

## Engineering methodology policy

Every engineering module should document its equations, assumptions, units and validation status. A simplified screening model must never be presented as a certified design calculation.

## Contributing

Contributions are welcome. New engineering calculations should include:

1. Method/equation reference
2. Units and assumptions
3. Example calculation
4. Automated test or reference case where practical
5. Clear statement of limitations

## License

MIT. See `LICENSE`.
