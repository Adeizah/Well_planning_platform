import math

def cement_screen(hole_diameter_in, casing_od_in, length_m, excess_pct, slurry_yield_bbl_sx=1.18):
    annulus_area_in2=math.pi/4*(float(hole_diameter_in)**2-float(casing_od_in)**2)
    vol_bbl=annulus_area_in2*float(length_m)*0.0009714*(1+float(excess_pct)/100)
    sacks=vol_bbl/max(float(slurry_yield_bbl_sx),0.01)
    return {"annular_volume_bbl":vol_bbl,"estimated_slurry_sacks":sacks,"excess_pct":excess_pct,"note":"Screening volume only; slurry yield, contamination, losses and cement design require field-specific data."}
