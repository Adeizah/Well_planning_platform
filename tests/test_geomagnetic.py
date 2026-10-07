import sys
import types
from datetime import date


def test_wmm_wrapper_uses_documented_getters(monkeypatch):
    class FakeWMM:
        def get_declination(self,*a): return 2.0
        def get_dip_angle(self,*a): return 12.0
        def get_intensity(self,*a): return 42000.0
        def get_horizontal_intensity(self,*a): return 41000.0
        def get_north_intensity(self,*a): return 40000.0
        def get_east_intensity(self,*a): return 9000.0
    mod=types.SimpleNamespace(WMMv2=FakeWMM)
    monkeypatch.setitem(sys.modules,'pywmm',mod)
    from models.geomagnetic import wmm2025
    r=wmm2025(9,9,20,date(2026,10,7))
    assert r['D']==2.0 and r['I']==12.0 and r['F']==42000.0


def test_igrf_wrapper_normalizes_python_datetime(monkeypatch):
    seen={}
    class FakePP:
        @staticmethod
        def igrf(lon,lat,h,dt):
            seen['dt']=dt
            return 3.0,4.0,5.0
    monkeypatch.setitem(sys.modules,'ppigrf',FakePP)
    from models.geomagnetic import igrf14
    r=igrf14(9,9,20,date(2026,10,7))
    assert seen['dt'].__class__.__name__ == 'datetime'
    assert abs(r['X']-4.0)<1e-12 and abs(r['Y']-3.0)<1e-12 and abs(r['Z']+5.0)<1e-12
