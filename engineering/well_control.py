
def well_control_screen(sidpp_psi, tvd_ft, current_mw_ppg, allowable_surface_psi, fracture_gradient_psi_ft=None):
    sid=float(sidpp_psi); tvd=float(tvd_ft); mw=float(current_mw_ppg)
    formation_grad=0.052*mw+sid/max(tvd,1)
    kill_mw=mw+sid/(0.052*max(tvd,1))
    maasp=None
    if fracture_gradient_psi_ft is not None:
        maasp=fracture_gradient_psi_ft*tvd-0.052*mw*tvd
    return {"estimated_formation_gradient_psi_ft":formation_grad,"kill_mud_weight_ppg":kill_mw,"allowable_surface_pressure_psi":allowable_surface_psi,"maasp_screen_psi":maasp,"note":"Use approved well-control procedures and company-specific kill sheets for operations."}
