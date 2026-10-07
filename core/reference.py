import math


def normalize_azimuth(azimuth_deg):
    return float(azimuth_deg) % 360.0


def magnetic_to_true(magnetic_azimuth_deg, declination_deg):
    return normalize_azimuth(float(magnetic_azimuth_deg) + float(declination_deg))


def true_to_magnetic(true_azimuth_deg, declination_deg):
    return normalize_azimuth(float(true_azimuth_deg) - float(declination_deg))


def true_to_grid(true_azimuth_deg, convergence_deg):
    return normalize_azimuth(float(true_azimuth_deg) - float(convergence_deg))


def grid_to_true(grid_azimuth_deg, convergence_deg):
    return normalize_azimuth(float(grid_azimuth_deg) + float(convergence_deg))


def magnetic_to_grid(magnetic_azimuth_deg, declination_deg, convergence_deg):
    return true_to_grid(magnetic_to_true(magnetic_azimuth_deg, declination_deg), convergence_deg)


def grid_to_magnetic(grid_azimuth_deg, declination_deg, convergence_deg):
    return true_to_magnetic(grid_to_true(grid_azimuth_deg, convergence_deg), declination_deg)


def reference_requirements(north_reference):
    """Return the corrections required to express survey azimuths in the project reference."""
    ref = str(north_reference)
    if ref == 'True North':
        return {'reference': ref, 'needs_declination': True, 'needs_convergence': False, 'label': 'True North — magnetic declination required; grid convergence not required.'}
    if ref == 'Grid North':
        return {'reference': ref, 'needs_declination': True, 'needs_convergence': True, 'label': 'Grid North — magnetic declination and grid convergence required.'}
    return {'reference': 'Magnetic North', 'needs_declination': False, 'needs_convergence': False, 'label': 'Magnetic North — no magnetic-to-true/grid correction required.'}


def convert_to_project_reference(azimuth_deg, input_reference, project_reference, declination_deg=0.0, convergence_deg=0.0):
    """Convert an input azimuth into the project's selected primary north reference."""
    src = str(input_reference); dst = str(project_reference)
    az = normalize_azimuth(azimuth_deg)
    if src == dst:
        return az
    if src == 'Magnetic North':
        true_az = magnetic_to_true(az, declination_deg)
    elif src == 'True North':
        true_az = az
    else:
        true_az = grid_to_true(az, convergence_deg)
    if dst == 'True North':
        return true_az
    if dst == 'Grid North':
        return true_to_grid(true_az, convergence_deg)
    return true_to_magnetic(true_az, declination_deg)


def magnetic_field_summary(D, I, H, F, X, Y, Z):
    return {'declination_deg': float(D), 'dip_deg': float(I), 'horizontal_field_nT': float(H), 'total_field_nT': float(F), 'X_nT': float(X), 'Y_nT': float(Y), 'Z_nT': float(Z)}


def uncertainty_radius(distance_m, sigma_m):
    return math.sqrt(float(distance_m) ** 2 + float(sigma_m) ** 2)
