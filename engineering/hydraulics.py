
from core.units import annular_velocity_fps, hydrostatic_psi, pressure_gradient_psi_ft, ppg_to_sg

def hydraulic_screen(flow_gpm, hole_id_in, pipe_od_in, mud_ppg, tvd_ft, annular_loss_psi):
    hydro = hydrostatic_psi(mud_ppg, tvd_ft)
    grad = pressure_gradient_psi_ft(mud_ppg)
    ecd = float(mud_ppg) + float(annular_loss_psi)/(0.052*float(tvd_ft))
    return {
        "annular_velocity_fps": annular_velocity_fps(flow_gpm, hole_id_in, pipe_od_in),
        "hydrostatic_psi": hydro,
        "pressure_gradient_psi_ft": grad,
        "ecd_ppg": ecd,
        "mud_sg": ppg_to_sg(mud_ppg),
        "annular_loss_psi": float(annular_loss_psi)
    }
