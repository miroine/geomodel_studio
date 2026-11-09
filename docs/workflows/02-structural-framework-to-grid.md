# Structural framework to grid

**Goal:** produce a calibrated faulted framework, zones and a checked 3D grid.

**Prerequisites:** project area/units established; source surfaces, boundary and interpretation inputs imported as applicable.

## Stages
1. Define project and source area in [Project setup](../01-project-setup.md).
2. Import horizon maps through [Surfaces](../02-surfaces.md); create/select the model boundary using [Polygons](../03-polygons.md).
3. Define traces in [Faults](../04-faults.md). Load well paths and tops through [Wells](../05-wells.md) and [Well tops](../06-well-tops.md) when calibration data are available.
4. In [Structural model](../07-structural-model.md), create ordered tasks and ensure every referenced horizon is produced first. Configure extension, resampling, smoothing, calibration and fault selection.
5. Review structural run log and horizon/top QC. **Decision:** if residuals or map coverage are unacceptable, correct picks/inputs or interpolation before proceeding.
6. Create zone definitions from zone tasks and define zone layering. In [Zones and 3D grid](../08-zones-and-3d-grid.md), set frame, resolution, refinement and active-cell rules.
7. Build the grid. Inspect 3D cut-away, sections and checks; rebuild after framework, boundary, zone or grid-setting changes.

## Decision points
- Skip optional wells/tops when calibration data are unavailable; do not imply uncalibrated horizons are calibrated.
- Select fault activation and geometry based on interpretation; dependent tasks still need inputs from active producers.
- Start with a manageable resolution and refine after checking cell geometry.

## QC gates
- **Framework:** dependencies valid, required tasks active, fault selection intentional.
- **Calibration:** pick residuals and model coverage acceptable; extrapolation outside picks reviewed.
- **Grid:** zone order, cell dimensions, fault blocks, active volume and boundary plausible.

**Expected result:** current structural horizons, zone table and faulted corner-point grid under Models. Downstream properties must be rebuilt if geometry changes.

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../../LICENSE).*
