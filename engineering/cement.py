
import math

def cement_screen(hole_diameter_in, casing_od_in, length_m, excess_pct):
    if hole_diameter_in <= casing_od_in:
        raise ValueError("Hole diameter must exceed casing OD.")
    ann_area_in2 = math.pi/4*(hole_diameter_in**2-casing_od_in**2)
    bbl_per_m = ann_area_in2*0.000000971222  # in²·m to bbl
    base_bbl = bbl_per_m*float(length_m)
    return {
        "annular_volume_bbl":base_bbl,
        "excess_pct":float(excess_pct),
        "cement_volume_with_excess_bbl":base_bbl*(1+float(excess_pct)/100),
        "annular_capacity_bbl_per_m":bbl_per_m
    }
