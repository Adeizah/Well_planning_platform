
def torque_drag_screen(depth_m, friction_factor, buoyancy_factor, string_weight_lbft):
    if depth_m < 0:
        raise ValueError("Depth cannot be negative.")
    effective_weight = float(string_weight_lbft)*float(buoyancy_factor)
    hookload_lbf = effective_weight*float(depth_m)*3.28084
    return {
        "depth_m":float(depth_m),
        "effective_weight_lbft":effective_weight,
        "approximate_string_weight_lbf":hookload_lbf,
        "friction_factor":float(friction_factor),
        "note":"This is not a full soft-string or stiff-string T&D model."
    }
