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


def magnetic_field_summary(D, I, H, F, X, Y, Z):
    return {
        "declination_deg": float(D), "dip_deg": float(I), "horizontal_field_nT": float(H),
        "total_field_nT": float(F), "X_nT": float(X), "Y_nT": float(Y), "Z_nT": float(Z)
    }


def uncertainty_radius(distance_m, sigma_m):
    """Simple radial screening uncertainty; not an ISCWSA covariance model."""
    return math.sqrt(float(distance_m) ** 2 + float(sigma_m) ** 2)
