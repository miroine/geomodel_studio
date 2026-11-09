# Structural model
> Location: **Structural framework › Structural model** · Previous: [Well
>   tops](06-well-tops.md) · Next: [Zones and 3D
>   grid](08-zones-and-3d-grid.md)

## Purpose
Build an ordered, reproducible horizon and fault framework from library
surfaces, thickness
maps, well-top calibration and structural operations.

## Before you start (inputs / prerequisites)
- Import horizon maps on **Input data › Surfaces** and define faults,
  wells and tops as
  needed.
- Set project CRS/units and model area. Check maps cover the intended area
  or configure an
  appropriate extension method.

## Step-by-step
1. Open **Structural framework › Structural model** and inspect the
   numbered workflow
   cards. Arrows show execution order; define horizons before tasks that
   reference them.
2. Add/configure tasks for surface horizons, isochore maps, proportional
   horizons,
   clipping, smoothing, extension, calibration and layers as needed. Use
   **Add a task** to
   append and **Configure task** to edit a step.
3. Set each task's **Active** checkbox. Inactive tasks retain settings
   but skip execution;
   downstream active steps still require their input horizons.
4. For calibration, select well tops and residual interpolation method.
   Review pick
   coverage and settings before running.
5. Configure selected faults with **Apply faults** so fault selection is
   used by the
   framework and calibration; configure throw/profile and geometry on
   Faults.
6. Use **Move up**, **Move down**, or **Delete task** to revise order.
   Click **Update
   step** to apply configuration changes. Structural changes invalidate
   derived
   structure/grid.
7. Click **Run workflow** in **Build & validate**. Review run log,
   horizon maps,
   cross-sections, 3D results and zone/top misfit QC.
8. Create or update grid zones from zone tasks, then continue to
   **Gridding › Zones & 3D
   grid**.

## Outputs
- Structural-model horizon surfaces and fault framework appear under
  **Models**.
- Zone definitions and intermediate layer horizons are available for grid
  construction;
  source surfaces and picks remain in **Input**.

## Quality control checklist
- [ ] Task order respects every horizon dependency; inactive producers
      have no active
      dependants.
- [ ] Surface coverage and extension settings are appropriate.
- [ ] Fault selection is intentional and calibration uses the correct
      framework.
- [ ] Top residuals and horizon maps are plausible after **Run workflow**.
- [ ] Results are current before zone/grid construction.

## Tips and common pitfalls
- Task-card colors indicate task family, not completion status; use
  readiness indicators and
  run log.
- Changing task order, parameters or activation invalidates results; rerun
  before building
  the grid.
- Nearest-neighbour extension is a default in many operations. Choose
  another method or clip
  intentionally when inappropriate.
- Layers between bounding horizons should be inserted after both bounding
  horizons have been
  built/calibrated.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) · [Quick
  start](workflows/01-quick-start.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
