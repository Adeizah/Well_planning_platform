"""Section classification for feasible trajectories.

This first implementation creates an auditable section schedule from a feasible
control-point trajectory. It does not claim to re-optimize section parameters;
that optimization remains a separate, explicitly reported stage.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from core.trajectory import minimum_curvature


def build_section_schedule(path: pd.DataFrame, *, max_dls_deg_30m: float = 3.0,
                           rate_threshold_deg_30m: float = 0.15,
                           min_section_length_m: float = 15.0) -> list[dict]:
    """Classify trajectory intervals as vertical/build/drop/turn/tangent.

    DLS and rates are calculated from the survey itself. Adjacent like intervals
    are merged. This is descriptive reconstruction, not an optimized replacement.
    """
    if path is None or len(path) < 2:
        return []
    p = path.copy()
    if not {'MD','Inc','Azi'}.issubset(p.columns):
        raise ValueError('Section schedule requires MD, Inc and Azi columns.')
    p = minimum_curvature(p[['MD','Inc','Azi']].copy())
    md=p.MD.to_numpy(float); inc=p.Inc.to_numpy(float); azi=np.unwrap(np.radians(p.Azi.to_numpy(float)))
    rows=[]
    for i in range(len(p)-1):
        length=max(md[i+1]-md[i],1e-9)
        build=(inc[i+1]-inc[i])*30.0/length
        turn=np.degrees(azi[i+1]-azi[i])*30.0/length
        dls=float(p.DLS.iloc[i+1])
        if max(inc[i],inc[i+1]) < 0.5 and abs(build)<rate_threshold_deg_30m and abs(turn)<rate_threshold_deg_30m:
            typ='Vertical'
        elif abs(turn)>=rate_threshold_deg_30m and abs(build)>=rate_threshold_deg_30m:
            typ='Build & Turn' if build>0 else 'Drop & Turn'
        elif abs(turn)>=rate_threshold_deg_30m:
            typ='Turn'
        elif build>=rate_threshold_deg_30m:
            typ='Build'
        elif build<=-rate_threshold_deg_30m:
            typ='Drop'
        else:
            typ='Tangent'
        rows.append({'start_i':i,'end_i':i+1,'start_md_m':float(md[i]),'end_md_m':float(md[i+1]),
          'type':typ,'start_inc_deg':float(inc[i]),'end_inc_deg':float(inc[i+1]),
          'start_azi_deg':float(np.degrees(azi[i])%360),'end_azi_deg':float(np.degrees(azi[i+1])%360),
          'build_drop_rate_deg_30m':float(build),'turn_rate_deg_30m':float(turn),'max_dls_deg_30m':dls})
    merged=[]
    for r in rows:
        if merged and merged[-1]['type']==r['type'] and r['start_md_m']-merged[-1]['start_md_m'] < 1e12:
            prev=merged[-1]
            prev['end_md_m']=r['end_md_m']; prev['end_inc_deg']=r['end_inc_deg']; prev['end_azi_deg']=r['end_azi_deg']
            prev['build_drop_rate_deg_30m']=float((prev['end_inc_deg']-prev['start_inc_deg'])*30/max(prev['end_md_m']-prev['start_md_m'],1e-9))
            prev['turn_rate_deg_30m']=float(((prev['end_azi_deg']-prev['start_azi_deg']+180)%360-180)*30/max(prev['end_md_m']-prev['start_md_m'],1e-9))
            prev['max_dls_deg_30m']=max(prev['max_dls_deg_30m'],r['max_dls_deg_30m'])
        else: merged.append(dict(r))
    return [{k:v for k,v in r.items() if k not in ('start_i','end_i')} for r in merged if r['end_md_m']-r['start_md_m']>=min_section_length_m]


def validate_section_schedule(schedule, *, max_dls_deg_30m: float,
                              max_build_rate_deg_30m: float, max_turn_rate_deg_30m: float) -> dict:
    violations=[]
    for i,s in enumerate(schedule):
        if s['max_dls_deg_30m'] > max_dls_deg_30m + 1e-6: violations.append(f'Section {i+1}: DLS limit exceeded')
        if abs(s['build_drop_rate_deg_30m']) > max_build_rate_deg_30m + 1e-6: violations.append(f'Section {i+1}: build/drop rate limit exceeded')
        if abs(s['turn_rate_deg_30m']) > max_turn_rate_deg_30m + 1e-6: violations.append(f'Section {i+1}: turn rate limit exceeded')
    return {'status':'PASS' if not violations else 'REVIEW','violations':violations,
            'note':'Section classification only; not a re-optimized trajectory. Validate the underlying survey independently.'}


def constraint_margin_rows(checks) -> list[dict]:
    """Per-constraint margin table from independent-validation checks (positive margin = inside the limit).

    Numeric limits (inclination, DLS, build, turn, MD) report limit - value. Target interception rows report
    the miss distance (0 = intercepted). Non-numeric limits (KOP window) report their status only.
    """
    rows = []
    for c in checks or []:
        name = str(c.get('check', '')); val, lim = c.get('value'), c.get('limit')
        margin = None
        if isinstance(val, (int, float)) and isinstance(lim, (int, float)) and not name.startswith('target['):
            margin = float(lim) - float(val)
        elif name.startswith('target[') and name.endswith('_intercept') and isinstance(val, (int, float)):
            margin = -float(val)                     # negative = miss distance
        rows.append({'check': name, 'status': c.get('status'), 'value': val if isinstance(val, (int, float)) else None,
                     'limit': lim if isinstance(lim, (int, float)) else None, 'margin': margin})
    return rows
