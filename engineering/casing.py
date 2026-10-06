
def casing_screen(od_in, weight_lbft, shoe_m, mud_ppg, external_gradient_psi_ft):
    # Thin-wall elastic screening only; not a proprietary API tubular rating.
    # Approximate internal diameter from OD and nominal weight is intentionally not inferred.
    hydro = 0.052 * float(mud_ppg) * float(shoe_m) * 3.28084
    ext = float(external_gradient_psi_ft) * float(shoe_m) * 3.28084
    return {
        "casing_od_in": float(od_in),
        "nominal_weight_lbft": float(weight_lbft),
        "shoe_md_m": float(shoe_m),
        "mud_hydrostatic_psi": hydro,
        "external_pressure_psi": ext,
        "screening_external_minus_internal_psi": ext-hydro,
        "note":"Use API/ISO tubular properties and company design criteria for actual burst/collapse qualification."
    }
