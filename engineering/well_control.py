
def well_control_screen(sidpp_psi, tvd_ft, current_mw_ppg, allowable_surface_psi):
    if tvd_ft <= 0:
        raise ValueError("TVD must be positive.")
    kill_mw = float(current_mw_ppg) + float(sidpp_psi)/(0.052*float(tvd_ft))
    maasp = float(allowable_surface_psi)
    return {
        "current_mw_ppg":float(current_mw_ppg),
        "SIDPP_psi":float(sidpp_psi),
        "TVD_ft":float(tvd_ft),
        "kill_mud_weight_ppg":kill_mw,
        "allowable_surface_pressure_psi":maasp,
        "note":"This is a basic SIDPP/KMW screen. Use the approved well-control method and kick model for operations."
    }
