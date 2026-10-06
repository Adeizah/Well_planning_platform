# Well Planning Platform

A browser-based, open and extensible toolkit for **drilling engineering, well planning, directional drilling, survey management, and well construction engineering**.

The platform brings commonly separated well-planning calculations into one accessible environment while keeping the underlying calculations transparent, reproducible, and extensible.

> **Important:** This project is intended for engineering analysis, training, planning support, research, and educational purposes. It is **not a replacement for company-approved engineering software, procedures, standards, or competent engineering review**. Results must be independently verified before being used for operational decisions.

---

## Overview

Commercial well-planning systems provide highly integrated capabilities for trajectory design, survey management, anti-collision, hydraulics, torque and drag, casing design, well control, and other engineering workflows.

Many of these systems are expensive, licensed, and inaccessible to students, early-career engineers, independent learners, and researchers.

The **Well Planning Platform** aims to provide an accessible and transparent alternative for learning, engineering screening, and software development.

The platform is designed to support:

- Directional well planning
- Survey calculations
- Trajectory visualization
- Target management
- Offset-well management
- Anti-collision screening
- Geomagnetic reference models
- Coordinate transformations
- Casing design screening
- Hydraulics and ECD calculations
- Well-control calculations
- Cement-volume calculations
- Torque and drag screening
- Engineering QA/QC
- Project data management
- Engineering reporting

The project is intentionally designed to be **general-purpose** rather than tied to a particular field, operator, or example well.

---

# Key Features

## 1. Project & Well Management

Create and manage individual well-planning projects containing information such as:

- Well name
- Field
- Operator
- Well type
- Surface location
- Elevation
- Coordinate reference system
- Planned TD
- Targets
- Offset wells
- Engineering assumptions

Projects can be exported and imported as JSON files, allowing planning cases to be saved, shared, and reproduced.

---

## 2. Survey Management & Trajectory Calculations

The platform supports directional survey calculations using the **Minimum Curvature Method**.

Typical survey inputs include:

| Parameter | Description |
|---|---|
| MD | Measured Depth |
| Inclination | Hole inclination |
| Azimuth | Wellbore azimuth |

The platform calculates:

- TVD
- TVDSS
- Northing
- Easting
- Vertical Section
- Closure distance
- Closure azimuth
- Dogleg severity
- Trajectory coordinates

Survey data can also be imported from CSV files.

---

## 3. Trajectory Visualization

Interactive trajectory plots allow users to visualize planned and surveyed wellbores.

Available visualization concepts include:

- 2D trajectory
- 3D trajectory
- Vertical section
- North/East plan view
- Target location
- Offset wells

These visualizations help engineers understand well geometry and identify potential trajectory issues.

---

## 4. Target Management

Define one or more drilling targets using:

- Target coordinates
- Target TVD/TVDSS
- Target radius
- Target description

Targets can be used to evaluate whether a planned trajectory is approaching the intended geological objective.

---

# 5. Geomagnetic Models

Directional drilling depends heavily on accurate magnetic reference information.

The platform is designed to use publicly available geomagnetic reference models rather than relying entirely on manually entered magnetic values.

Current model integration includes:

### WMM2025

The **World Magnetic Model 2025** provides magnetic-field information including:

- Magnetic declination
- Magnetic inclination/dip
- Total field intensity
- Magnetic field components

Model information can be retained so that calculations can be traced to the model and epoch used.

Additional geomagnetic models can be incorporated as development continues.

---

# 6. Geodesy & Coordinate Systems

Well planning is fundamentally a spatial problem.

The platform uses open geospatial libraries to support coordinate-system operations and transformations.

Capabilities include:

- CRS identification
- Coordinate transformations
- Geographic coordinates
- Projected coordinates
- Datum/CRS handling
- Geodetic calculations

The platform uses **PROJ** and EPSG-defined coordinate reference systems where applicable.

---

# 7. Offset Wells

Offset wells can be added to a project for:

- Trajectory comparison
- Anti-collision screening
- Historical well analysis
- Field development planning
- Reference trajectories

An offset well can contain its own survey trajectory rather than being limited to a single coordinate.

This allows multiple wells to be viewed and analyzed within the same planning environment.

---

# 8. Anti-Collision

The anti-collision module provides a framework for evaluating proximity between well trajectories.

The development roadmap includes increasingly rigorous analysis involving:

- Separation distance
- Closest approach
- Relative position
- Survey uncertainty
- Error ellipses
- Collision-risk screening
- ISCWSA-style uncertainty concepts

> Anti-collision results from this platform should be treated as engineering screening unless the implementation has been formally validated against an approved company workflow.

---

# 9. Casing Design

The casing module provides preliminary casing-string screening.

Users can define:

- Hole size
- Casing size
- String type
- Casing grade
- Weight
- Setting depth
- Depth reference
- Design assumptions

The objective is to help engineers understand the relationship between:

**Pressure regime → well architecture → hole sizes → casing strings → setting depths**

The platform is not intended to replace detailed casing design involving burst, collapse, tension, connection performance, triaxial analysis, wear, temperature, and other considerations.

---

# 10. Hydraulics & ECD

The hydraulics module provides screening calculations related to:

- Flow rate
- Mud density
- Rheology
- Annular velocity
- Pressure loss
- ECD
- Hydrostatic pressure

The module is designed to evolve toward more detailed drilling-hydraulics workflows.

Hydraulics results should always be checked against the actual drilling-fluid program, BHA geometry, rheological model, temperature effects, and operating conditions.

---

# 11. Well Control

The well-control module provides basic engineering calculations and screening tools related to:

- Hydrostatic pressure
- Formation pressure
- Kill mud weight
- SIDPP
- SICP
- MAASP
- Pressure relationships

The objective is to provide a transparent calculation environment for learning and preliminary engineering checks.

Operational well-control decisions must follow the applicable company well-control procedures and recognized industry standards.

---

# 12. Cementing

The cement module provides preliminary cement-volume calculations including:

- Hole volume
- Casing volume
- Annular volume
- Excess
- Cement volume
- Basic displacement calculations

The module can be expanded to support more detailed cementing design.

---

# 13. Torque & Drag

The torque-and-drag module provides preliminary screening of drillstring mechanical behavior.

Potential applications include:

- Axial forces
- Torque
- Drag
- Friction effects
- Wellbore geometry
- Drillstring loading

Future development will expand this into more rigorous soft-string and drillstring mechanics workflows.

---

# Engineering Philosophy

The platform follows three main principles.

### 1. Transparent calculations

Where possible, calculations should be visible and understandable rather than hidden behind proprietary software.

### 2. Reproducibility

A project should retain the inputs, assumptions, models, and calculation settings used to generate its results.

### 3. Modular development

Each engineering discipline should remain modular so that new calculations and models can be added without rebuilding the entire application.

---

# Technology Stack

The application is built primarily with open-source technologies.

| Component | Technology |
|---|---|
| User interface | Streamlit |
| Programming language | Python |
| Data processing | Pandas |
| Numerical calculations | NumPy |
| Visualization | Plotly |
| Geomagnetics | WMM / pywmm |
| Geodesy | PROJ / pyproj |
| HTTP/API access | Requests |
| Spreadsheet support | OpenPyXL |
| Testing | Pytest |
| Version control | Git / GitHub |

---

# Project Structure

```text
well-planning-platform/
│
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── MODEL_REGISTRY.md
│
├── core/
│   ├── __init__.py
│   ├── project.py
│   ├── trajectory.py
│   └── units.py
│
├── models/
│   ├── __init__.py
│   ├── geomagnetic.py
│   └── geodesy.py
│
├── engineering/
│   ├── __init__.py
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
