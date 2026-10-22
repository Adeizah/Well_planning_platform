# Single DLS Constraint Update

The platform now uses `max_dls_deg_30m` as the sole directional-change-rate constraint across the general optimizer, independent trajectory validator, section reconstruction validator, section optimizer bounds, reachability screening, legacy profile optimizer and primary UI. Maximum inclination remains an independent constraint.

Legacy function arguments for build/drop/turn rates are retained where needed for API compatibility, but are ignored as constraint inputs. Build/drop/turn rates may still appear as descriptive metrics in section schedules; they are not independent acceptance limits.

The unified UI now exposes one Maximum DLS field plus Maximum Inclination. Existing project files with older build/drop/turn keys continue to load, but those keys no longer control acceptance.

DLS is checked on the trajectory's minimum-curvature survey intervals. Since DLS is the combined dogleg, build and azimuth turn occurring together can produce a larger DLS than either component alone; the independent validator remains the final acceptance gate.
