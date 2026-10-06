import math


def casing_screen(od_in, weight_lbft, shoe_md_m, mud_weight_ppg, external_gradient_psi_ft, grade_yield_psi=80000.0):
    # Screening-only tubular geometry estimates.
    od=float(od_in); wt=float(weight_lbft); depth_ft=float(shoe_md_m)*3.28084
    t_in = wt/(3.14159265*490.0*max(od,0.01))
    area=3.14159265/4*(od**2-(od-2*t_in)**2)
    buoy=max(0.0,1.0-mud_weight_ppg/65.4)
    burst_allow=2*t_in*grade_yield_psi/max(od,0.01)
    ext=external_gradient_psi_ft*depth_ft
    tension=area*grade_yield_psi*buoy
    return {"wall_thickness_in_est":t_in,"steel_area_in2":area,"burst_pressure_screen_psi":burst_allow,"external_pressure_psi":ext,"tension_capacity_lb_screen":tension,"design_note":"Screening only; verify against API/ISO/OEM tubular data."}


def casing_program_summary(records):
    out=[]
    for r in records:
        if not r.get("type") and not r.get("casing_od_in"): continue
        rr=dict(r)
        for key in ["string_no","hole_size_in","casing_od_in","weight_lbft","shoe_md_m","shoe_tvd_m","shoe_tvdss_m","liner_top_md_m","top_md_m"]:
            try: rr[key]=float(rr[key]) if rr.get(key) not in ("",None) else None
            except Exception: pass
        out.append(rr)
    return out


def casing_geometry_checks(program):
    rows=[]; prev=0.0
    for i,r in enumerate(program,1):
        shoe=float(r.get("shoe_md_m") or 0); hole=float(r.get("hole_size_in") or 0); od=float(r.get("casing_od_in") or 0)
        rows.append({"string":r.get("string_no",i),"shoe_md_m":shoe,"hole_size_in":hole,"casing_od_in":od,"annular_clearance_in":hole-od,"depth_order":"PASS" if shoe>=prev else "FAIL","geometry":"PASS" if hole>od>0 else "FAIL"})
        prev=shoe
    return rows


def casing_design_checks(od_in, weight_lbft, grade_yield_psi, shoe_md_m, mud_weight_ppg, pore_gradient_psi_ft, fracture_gradient_psi_ft, burst_factor=1.1, collapse_factor=1.0):
    depth_ft=shoe_md_m*3.28084
    hydro=0.052*mud_weight_ppg*depth_ft
    pore=pore_gradient_psi_ft*depth_ft
    frac=fracture_gradient_psi_ft*depth_ft
    t=weight_lbft/(490*math.pi*max(od_in,0.01))
    id_est=max(0.1,od_in-2*t)
    area=math.pi/4*(od_in**2-id_est**2)
    burst_capacity=2*t*grade_yield_psi/max(od_in,0.01)
    collapse_proxy=2*grade_yield_psi*(t/max(od_in,0.01))**3
    tension=area*grade_yield_psi
    burst_required=max(0,pore-(0.052*mud_weight_ppg*depth_ft))/burst_factor
    collapse_required=max(0,frac-hydro)/max(collapse_factor,0.01)
    return {"hydrostatic_psi":hydro,"pore_pressure_psi":pore,"fracture_pressure_psi":frac,"estimated_wall_thickness_in":t,"estimated_id_in":id_est,"burst_capacity_psi":burst_capacity,"burst_required_screen_psi":burst_required,"burst_margin":burst_capacity-max(burst_required,1),"collapse_capacity_proxy_psi":collapse_proxy,"collapse_required_screen_psi":collapse_required,"collapse_margin":collapse_proxy-max(collapse_required,1),"tension_capacity_lb":tension,"note":"Screening design equations only; use certified tubular properties and applicable standards for final design."}
