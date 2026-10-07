M_TO_FT = 3.280839895013123
FT_TO_M = 1.0 / M_TO_FT

def m_to_ft(value):
    return float(value) * M_TO_FT

def ft_to_m(value):
    return float(value) * FT_TO_M

def dls_m_to_ft(value):
    return float(value) * (30.0 / 30.48)

def dls_ft_to_m(value):
    return float(value) * (30.48 / 30.0)

def length_label(unit='Field'):
    return 'ft' if unit == 'Field' else 'm'

def depth_value_m(value_m, unit='Field'):
    return m_to_ft(value_m) if unit == 'Field' else float(value_m)

def depth_value_ft(value_ft, unit='Field'):
    return ft_to_m(value_ft) if unit == 'Field' else float(value_ft)

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
