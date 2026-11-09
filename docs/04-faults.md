# Faults
> Location: **Input data › Faults** · Previous: [Polygons](03-polygons.md)
>   · Next:
>   [Wells](05-wells.md)

## Purpose
Define fault surfaces/traces and their displacement parameters for
structural modelling and
grid fault blocks.

## Before you start (inputs / prerequisites)
- Define project CRS and units; fault XY, throw, dip, drag, and depth
  reference use project
  units after conversion.
- Have horizons or a backdrop surface to interpret traces against. Faults
  affect results
  only after rerunning the structural workflow and rebuilding the grid.

## Step-by-step
1. Open **Input data › Faults** and select a backdrop surface if useful.
   Use **Draw
   fault**, place trace vertices in the map editor, and finish with a
   double-click or
   Enter.
2. For imported traces, expand **Import fault traces from polygon
   files**. Choose **Fault
   polygon / polyline files**, set **Fault XY unit in file**, configure
   geometric settings,
   and click **Import as faults**.
3. RMS `.POL`/`.rmspolygons` and XY text files are treated as separate
   open traces; each
   needs at least two distinct vertices. File Z values are ignored.
4. For each fault set the name/type (normal, reverse, strike-slip or
   transverse where
   offered), throw/slip, dip and hanging-wall side. Configure
   along-strike profile,
   drag-zone width and growth settings where relevant.
5. Inspect the reference depth with **Set zref to the backdrop depth
   along the trace** when
   available. Review trace direction because vertex order defines
   left/right and
   hanging-wall side.
6. Apply definitions with **Apply to model**. Use the faulted preview to
   check displacement
   and horizon splitting. In the structural workflow select faults, run
   the workflow, and
   rebuild the grid.
7. Review fault blocks and juxtaposition/contact information. If
   transmissibility
   multipliers are needed, configure them on Faults and include fault
   keywords in export
   settings.

## Outputs
- Named fault definitions and trace geometry in the **Input** tree.
- Faulted structural horizons, fault blocks and fault-face data after
  dependent processes run.

## Quality control checklist
- [ ] Trace direction and hanging-wall side agree with the intended
      interpretation.
- [ ] Throw/slip, dip, z-reference and drag width are in project units.
- [ ] Imported trace coordinates use the correct file XY unit.
- [ ] Preview shows plausible horizon offsets without unintended ramps.
- [ ] Structural model and grid were rerun after editing faults.

## Tips and common pitfalls
- Imported trace Z is ignored; set a reference depth and geometric
  parameters in the UI.
- Import adds uniquely named faults rather than replacing existing objects.
- The structural workflow may show stair-stepped faults on vertical
  pillars; a visible
  display gap is not a physical heave gap.
- Fault edits invalidate dependent structure/grid results; check stale
  status before
  volumetrics or export.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) · [Quick
  start](workflows/01-quick-start.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
