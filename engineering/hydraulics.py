import math


def hydraulic_screen(flow_gpm, hole_id_in, pipe_od_in, mud_ppg, tvd_ft, annular_loss_psi, pv_cp=20.0, yp_lbf100ft2=10.0):
    q=float(flow_gpm); hole=float(hole_id_in); pipe=float(pipe_od_in); rho=float(mud_ppg)
    area=max((hole**2-pipe**2)/24.5,0.001)
    v=q/(24.51*area)
    hydro=0.052*rho*tvd_ft
    ecd=rho+annular_loss_psi/(0.052*max(tvd_ft,1))
    return {"annular_area_in2":area,"annular_velocity_fps":v,"hydrostatic_psi":hydro,"ecd_ppg":ecd,"pressure_gradient_psi_ft":0.052*ecd,"pv_cp":pv_cp,"yield_point_lbf100ft2":yp_lbf100ft2,"note":"Screening hydraulics; pressure-loss model is intentionally simplified."}


def rheology_summary(model, pv, yp, flow):
    model=model.lower()
    if model=="bingham plastic":
        return {"model":model,"apparent_viscosity_cp":pv+yp/max(flow,0.1)}
    if model=="power law":
        return {"model":model,"apparent_viscosity_cp":pv*max(flow,0.1)**(yp/10.0)}
    return {"model":"Herschel-Bulkley (screening)","apparent_viscosity_cp":pv+yp/max(flow,0.1)}
