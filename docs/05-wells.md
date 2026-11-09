# Wells
> Location: **Input data › Wells** · Previous: [Faults](04-faults.md) ·
>   Next: [Well
>   tops](06-well-tops.md)

## Purpose
Import, create and edit well paths that provide spatial context and can
condition structural
and property models.

## Before you start (inputs / prerequisites)
- Confirm CRS, XY units and depth convention. Well depth is positive down;
  imported formats
  may specify depth from KB.
- Prepare well files or a head/deviation survey. LAS logs are handled in
  property QC tools,
  not as well-path imports.

## Step-by-step
1. Open **Input data › Wells**. Use **Import** and upload files with
   **Well files**. Review
   detected format and file unit/depth convention, then click **Merge
   into project**.
2. In **Create / edit**, select a **Well** and choose its **Trajectory**
   representation.
   Enter/edit the wellhead and path/survey data; save with **Save well**.
3. Deviation surveys are converted using minimum-curvature trajectory
   calculation. XYZ
   paths may also be imported where supported.
4. Use **From tops** to create vertical paths for wells represented by
   picks without an
   existing trajectory. Set **TD below deepest top** and click **Create
   vertical wells from
   tops**. Existing wells are not replaced implicitly.
5. Inspect wells in **Library & 3D**. Check wellheads, deviated path, and
   the 3D overlay
   relative to structural horizons and grid.
6. To use well logs for property conditioning, load LAS 2.0 files from
   Properties well-log
   tools and block a curve into the current grid; this is separate from
   path import.
7. Remove an incorrect well with **Delete this well** only after checking
   whether tops or
   modelling steps depend on it.

## Outputs
- Wellhead and trajectory objects in the **Input** tree and 3D scene.
- Paths available to well-top placement, structural calibration context,
  and log
  blocking/conditioning.

## Quality control checklist
- [ ] Wellhead XY and depth datum are correctly interpreted.
- [ ] Survey measured depth and project depth units agree.
- [ ] Deviated trajectories have plausible geometry and terminal depth.
- [ ] Tops align to the trajectory rather than only the tabulated
      wellhead XY.
- [ ] Any well-log curve used for conditioning is blocked to the
      current grid and reviewed.

## Tips and common pitfalls
- Wells use TVDSS positive down; head depth is represented relative to KB
  by app conventions.
- For deviated wells, a top is placed where the trajectory reaches the
  pick depth, which may
  not be the XY in the tops table.
- Vertical wells from tops are a convenience when no deviation data exist;
  use surveys for
  realistic paths.
- Rebuild or re-block logs after grid geometry changes; stale outputs
  should not be treated
  as current.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) · [Facies,
  petrophysics and
  saturation](workflows/03-facies-petrophysics-saturation.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
