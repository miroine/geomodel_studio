# Well tops
> Location: **Input data › Well tops** · Previous: [Wells](05-wells.md) ·
>   Next: [Structural
>   model](07-structural-model.md)

## Purpose
Import and QC stratigraphic picks on wells, then use them to calibrate
structural horizons and
zone bases.

## Before you start (inputs / prerequisites)
- Import or create well paths first when picks should be positioned along
  deviated
  trajectories.
- Prepare a CSV table with well identifiers, horizon/pick labels and depth
  values; confirm
  depth unit and positive-down convention.

## Step-by-step
1. Open **Input data › Well tops** and select **Import & edit**. Load the
   tops CSV and map
   its columns to well, horizon and depth fields as prompted.
2. Review the editable table for unmatched wells, horizon names,
   duplicate picks and
   plausible depths. Correct entries before calibration.
3. Confirm project depth units and depth convention on Project. Import
   conversion does not
   infer a project CRS.
4. Use **Map tops for** to inspect all tops or one horizon's picks in
   plan view.
5. Open **QC vs structural model** after a structural workflow run.
   Compare observed picks
   with modeled horizon depths and review misfit statistics.
6. In Structural model, enable **Calibrate to tops** for the relevant
   horizon or
   **Calibrate the zone base to well tops** for a zone task, configure
   residual
   interpolation, and rerun.
7. Recheck top misfits after calibration; retain the raw pick table as
   the observation
   source and inspect extrapolation outside pick coverage.

## Outputs
- Named well-top/pick objects in the **Input** tree.
- Pick-versus-model QC and calibration constraints for structural
  horizons/zone bases.

## Quality control checklist
- [ ] Every pick maps to the intended existing well and horizon.
- [ ] Depth values use project units and positive-down convention.
- [ ] Duplicate or implausible picks are resolved or documented.
- [ ] Deviated well picks are interpreted along the trajectory.
- [ ] Calibration residuals and post-run misfit are reviewed.

## Tips and common pitfalls
- A pick is not necessarily located at its table XY when the well is
  deviated; path
  intersection at pick depth is used.
- Structural calibration modifies derived horizons, not original well-top
  observations.
- Calibrate after constructing the target horizon and before downstream
  tasks that depend on
  the calibrated result.
- Large misfits may indicate unit, datum, horizon-name or trajectory
  problems rather than an
  interpolation issue.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) · [Quick
  start](workflows/01-quick-start.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
