"""Consistent KOP onset estimation for trajectory search and independent validation.

KOP is estimated from the start of sustained inclination build, not the MD of the
last station below an arbitrary inclination threshold. This is a geometric estimate;
when an authoritative planned KOP is available, it should be retained as design metadata.
"""
from __future__ import annotations
import numpy as np


def estimate_kop_md(md, inc, *, build_rate_threshold_deg_30m: float = 0.02,
                    sustained_intervals: int = 2) -> float:
    """Return MD at the start of sustained inclination increase (metres).

    A build-rate threshold suppresses tiny floating-point noise. For a single
    interval of build, it is still recognized; for longer surveys, requiring a
    short run of build intervals suppresses isolated noisy stations. The returned
    MD is the start of the run, not the later threshold-crossing station.
    """
    md = np.asarray(md, dtype=float); inc = np.asarray(inc, dtype=float)
    if len(md) < 2 or len(md) != len(inc):
        return float(md[-1]) if len(md) else 0.0
    dmd = np.diff(md)
    valid = dmd > 0
    rate = np.zeros(len(dmd), dtype=float)
    rate[valid] = np.diff(inc)[valid] / dmd[valid] * 30.0
    building = rate > float(build_rate_threshold_deg_30m)
    run = max(1, int(sustained_intervals))
    if run > 1 and len(building) >= run:
        for i in range(len(building) - run + 1):
            if bool(np.all(building[i:i + run])):
                return float(md[i])
    elif building.any():
        return float(md[int(np.flatnonzero(building)[0])])
    if building.any():
        return float(md[int(np.flatnonzero(building)[0])])
    return float(md[-1])
