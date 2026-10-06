def pressure_window(tvd_ft, mud_ppg, pore_gradient_psi_ft, fracture_gradient_psi_ft, safety_margin_ppg=0.0):
    tvd=float(tvd_ft); mw=float(mud_ppg); pp=float(pore_gradient_psi_ft); fg=float(fracture_gradient_psi_ft); margin=float(safety_margin_ppg)
    hydro=0.052*mw*tvd
    pore=pp*tvd
    frac=fg*tvd
    lower_ppg=pp/0.052 + margin
    upper_ppg=fg/0.052 - margin
    return {'tvd_ft':tvd,'mud_hydrostatic_psi':hydro,'pore_pressure_psi':pore,'fracture_pressure_psi':frac,'pore_equivalent_mw_ppg':pp/0.052,'fracture_equivalent_mw_ppg':fg/0.052,'recommended_window_lower_ppg':lower_ppg,'recommended_window_upper_ppg':upper_ppg,'window_width_ppg':upper_ppg-lower_ppg,'status':'PASS' if upper_ppg>lower_ppg else 'FAIL'}
