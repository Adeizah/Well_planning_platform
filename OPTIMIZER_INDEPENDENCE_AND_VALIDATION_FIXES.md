# Optimizer independence and validation fixes

This update is a focused implementation pass on the trajectory optimizer.

## Changes

- The trajectory optimization action is explicitly profile-independent. It no longer copies the saved J/S/Horizontal/ERD preset into the optimization result as though the preset constrained the search. Profile workflows remain separate.
- Corrected the optimizer objective so approach constraints for **every** ordered target contribute to the search penalty. Previously, due to indentation, only the last target's approach constraints were penalized, although final validation still checked the target sequence.
- Replaced the arbitrary `Inc > 0.5°` KOP proxy with a shared estimate based on the start of sustained inclination build. Both the optimizer and independent validator use the same function and threshold. This is still a geometric estimate; an authoritative planned KOP should be kept as design metadata where available.
- Added the random seed and explicit optimizer mode to result metadata for repeatability diagnostics.
- Added regression tests for early build and delayed build KOP detection.

## Important limits

- The optimizer uses a bounded numerical search with penalties to guide candidate generation; independent validation remains the acceptance gate.
- A failed search means no validated candidate was found within the configured search budget; it does not prove the project is infeasible unless the separate analytical screen establishes that.
- This is engineering-development software, not a certified operational well-planning system.
