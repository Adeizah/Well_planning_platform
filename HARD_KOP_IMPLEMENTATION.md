# Hard KOP vertical constraint

When the independent optimizer receives `min_kop_md_m` and/or `max_kop_md_m`, it enters hard-KOP mode. The selected KOP is the lower bound when both are supplied, otherwise the supplied bound. The path is held at exactly 0 degrees inclination through that MD, and the KOP is inserted as an exact station. Inclination controls are mapped over the post-KOP interval. DLS is still calculated on the complete minimum-curvature segment, including the first build segment.

The independent validator checks the dense reconstructed path before `planned_kop_md_m` for both inclination and lateral departure. A survey that starts building before KOP is REVIEW even if its threshold-based KOP estimate falls inside the requested window.

This is a deliberate first implementation: the optimizer does not yet search the full KOP window. If both bounds are supplied, it deterministically chooses the minimum permitted KOP. Future work can promote KOP to an optimization variable while preserving the hard vertical segment.

This is engineering-development software, not a certified operational well-planning system.
