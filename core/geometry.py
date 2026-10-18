import math
import numpy as np


def target_contains(target, north, east, tvdss=None):
    t=target or {}; typ=str(t.get('type','Point')).lower(); n=float(north)-float(t.get('north_m',0)); e=float(east)-float(t.get('east_m',0))
    if typ=='point': return abs(n)<1e-9 and abs(e)<1e-9
    if typ=='circular': return n*n+e*e <= float(t.get('radius_m',50))**2
    if typ=='elliptical':
        a=max(float(t.get('semi_major_m',100)),1e-9); b=max(float(t.get('semi_minor_m',50)),1e-9); ang=math.radians(float(t.get('orientation_deg',0)))
        x=e*math.cos(ang)+n*math.sin(ang); y=-e*math.sin(ang)+n*math.cos(ang)
        return (x/a)**2+(y/b)**2<=1
    if typ=='rectangular':
        # Optional rotation (degrees clockwise from North) of the length axis; 0 keeps the legacy N-S orientation.
        ang=math.radians(float(t.get('orientation_deg',0) or 0)); along=n*math.cos(ang)+e*math.sin(ang); cross=e*math.cos(ang)-n*math.sin(ang)
        return abs(cross)<=float(t.get('width_m',100))/2 and abs(along)<=float(t.get('length_m',100))/2
    if typ=='corridor':
        half=float(t.get('half_width_m',50)); az=math.radians(float(t.get('azimuth_deg',0))); along=e*math.sin(az)+n*math.cos(az); cross=e*math.cos(az)-n*math.sin(az)
        return abs(cross)<=half and abs(along)<=float(t.get('half_length_m',500))
    if typ=='polygon':
        pts=t.get('points',[]); inside=False
        j=len(pts)-1
        for i in range(len(pts)):
            xi,yi=float(pts[i][1]),float(pts[i][0]); xj,yj=float(pts[j][1]),float(pts[j][0])
            if ((yi>n)!=(yj>n)) and (e < (xj-xi)*(n-yi)/(yj-yi+1e-12)+xi): inside=not inside
            j=i
        return inside
    return False


def target_boundary(target, n=72):
    t=target or {}; typ=str(t.get('type','Point')).lower(); cN=float(t.get('north_m',0)); cE=float(t.get('east_m',0))
    if typ=='point': return [cN],[cE]
    if typ=='circular':
        r=float(t.get('radius_m',50)); a=np.linspace(0,2*np.pi,n); return cN+r*np.cos(a), cE+r*np.sin(a)
    if typ=='elliptical':
        a=float(t.get('semi_major_m',100)); b=float(t.get('semi_minor_m',50)); ang=math.radians(float(t.get('orientation_deg',0))); q=np.linspace(0,2*np.pi,n); x=a*np.cos(q); y=b*np.sin(q); E=x*np.cos(ang)-y*np.sin(ang); N=x*np.sin(ang)+y*np.cos(ang); return cN+N,cE+E
    if typ=='rectangular':
        L=float(t.get('length_m',100))/2; W=float(t.get('width_m',100))/2; pts=[(-L,-W),(-L,W),(L,W),(L,-W),(-L,-W)]
        ang=math.radians(float(t.get('orientation_deg',0) or 0))
        return [cN+p[0]*math.cos(ang)-p[1]*math.sin(ang) for p in pts],[cE+p[0]*math.sin(ang)+p[1]*math.cos(ang) for p in pts]
    if typ=='corridor':
        az=math.radians(float(t.get('azimuth_deg',0))); hl=float(t.get('half_length_m',500)); hw=float(t.get('half_width_m',50)); along=[(-hl,-hw),(-hl,hw),(hl,hw),(hl,-hw),(-hl,-hw)]; outN=[];outE=[]
        for al,cross in along: outN.append(cN+al*math.cos(az)-cross*math.sin(az)); outE.append(cE+al*math.sin(az)+cross*math.cos(az))
        return outN,outE
    if typ=='polygon':
        # Polygon vertices are stored as (North, East) OFFSETS from the target centre (metres), the
        # same frame target_contains() uses. The boundary must therefore be translated by the centre;
        # previously it was returned untranslated, so the plotted outline and the miss distance were
        # wrong for any polygon whose centre was not at the wellhead.
        pts=t.get('points',[]); N=[cN+float(p[0]) for p in pts]; E=[cE+float(p[1]) for p in pts]
        if pts: N.append(N[0]); E.append(E[0])
        return N,E
    return [cN],[cE]


DEFAULT_TOLERANCE_M = 30.48  # 100 ft, the historical hard-coded target tolerance


def target_tolerances(target, default_m=DEFAULT_TOLERANCE_M):
    """Return (lateral_tolerance_m, vertical_tolerance_m) for a target definition.

    * ``tolerance_m``  - lateral tolerance for point targets and default vertical band.
    * ``vertical_tolerance_m`` - optional separate vertical tolerance.
    * ``thickness_m`` - optional true-vertical thickness of the target layer; the vertical
      acceptance band is at least half of it (divided by cos(dip) for an inclined layer so
      the band is measured vertically).
    """
    t = target or {}
    # Point targets are geometric points, not target areas. The returned zero
    # tolerances are used for engineering acceptance; callers may use a separate
    # numerical solver threshold solely to terminate iterative calculations.
    if str(t.get('type', 'Point')).lower() == 'point':
        lateral = 0.0
        vertical = 0.0
    else:
        lateral = float(t.get('tolerance_m', default_m) or default_m)
        vertical = float(t.get('vertical_tolerance_m', lateral) or lateral)
    thick = float(t.get('thickness_m', 0.0) or 0.0)
    if thick > 0:
        dip = math.radians(min(float(t.get('dip_deg', 0.0) or 0.0), 89.0))
        vertical = max(vertical, 0.5 * thick / max(math.cos(dip), 1e-6))
    return lateral, vertical
