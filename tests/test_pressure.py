from engineering.pressure import pressure_window

def test_positive_pressure_window():
    r=pressure_window(10000,10,.5,.65)
    assert r['status']=='PASS'
    assert r['window_width_ppg']>0
