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
        return abs(e)<=float(t.get('width_m',100))/2 and abs(n)<=float(t.get('length_m',100))/2
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
        L=float(t.get('length_m',100))/2; W=float(t.get('width_m',100))/2; pts=[(-L,-W),(-L,W),(L,W),(L,-W),(-L,-W)]; return [cN+p[0] for p in pts],[cE+p[1] for p in pts]
    if typ=='corridor':
        az=math.radians(float(t.get('azimuth_deg',0))); hl=float(t.get('half_length_m',500)); hw=float(t.get('half_width_m',50)); along=[(-hl,-hw),(-hl,hw),(hl,hw),(hl,-hw),(-hl,-hw)]; outN=[];outE=[]
        for al,cross in along: outN.append(cN+al*math.cos(az)-cross*math.sin(az)); outE.append(cE+al*math.sin(az)+cross*math.cos(az))
        return outN,outE
    if typ=='polygon':
        pts=t.get('points',[]); return [float(p[0]) for p in pts]+([float(pts[0][0])] if pts else []), [float(p[1]) for p in pts]+([float(pts[0][1])] if pts else [])
    return [cN],[cE]
