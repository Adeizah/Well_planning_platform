
def sg_to_ppg(sg):
    return float(sg) * 8.345404452

def ppg_to_sg(ppg):
    return float(ppg) / 8.345404452

def hydrostatic_psi(mw_ppg, tvd_ft):
    return 0.052 * float(mw_ppg) * float(tvd_ft)

def pressure_gradient_psi_ft(mw_ppg):
    return 0.052 * float(mw_ppg)

def annular_velocity_fps(flow_gpm, hole_id_in, pipe_od_in):
    area_in2 = 0.7853981633974483 * (float(hole_id_in)**2 - float(pipe_od_in)**2)
    if area_in2 <= 0:
        raise ValueError("Hole ID must be greater than pipe OD.")
    return 24.5107 * float(flow_gpm) / area_in2

def psi_to_mpa(psi):
    return float(psi) * 0.006894757293168

def mpa_to_psi(mpa):
    return float(mpa) / 0.006894757293168
