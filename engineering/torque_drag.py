import math

def torque_drag_screen(depth_m, friction_factor, buoyancy_factor, string_weight_lbft, inclination_deg=0.0, dogleg_deg_30m=0.0):
    w=float(string_weight_lbft); L=float(depth_m)*3.28084; ff=float(friction_factor); bf=float(buoyancy_factor)
    hookload=max(0,w*L*bf)
    drag=hookload*ff*math.sin(math.radians(max(0,inclination_deg)))
    torque=drag*0.3048*0.1
    return {"buoyant_weight_lb":hookload,"drag_screen_lb":drag,"surface_torque_screen_ftlb":torque,"friction_factor":ff,"inclination_deg":inclination_deg,"dls_deg_30m":dogleg_deg_30m,"note":"Screening soft-string approximation; not a validated stiff-string model."}
