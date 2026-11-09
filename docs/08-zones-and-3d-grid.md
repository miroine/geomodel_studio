# Zones and 3D grid
> Location: **Gridding › Zones & 3D grid** · Previous: [Structural
>   model](07-structural-model.md) · Next:
>   [Properties](09-property-modelling.md)

## Purpose
Turn the structural framework into zone intervals, define within-zone
layering, and
build/check a corner-point grid.

## Before you start (inputs / prerequisites)
- Run a valid structural workflow and create zone definitions from its
  zone tasks.
- Confirm boundary polygon, lattice, faults, grid resolution and output
  size. Invalid zone
  tables block building.

## Step-by-step
1. Open **Gridding › Zones & 3D grid**. Review **Zones & layering** and
   **Grid settings**;
   the panels are combined in this page.
2. Define each zone's top/base horizons, thickness model, optional
   calibration and layer
   scheme. Use proportional fractions, follow-top/follow-base or
   configured layer thickness
   as appropriate.
3. Review zone order, thickness limits, pinch-outs and top/base
   assignments. Structural
   edits invalidate the grid-zone table; update it from zone steps when
   prompted.
4. In **Grid settings**, set cell size or cell counts, orientation, frame
   and any local
   refinement. Review estimates for columns, layers, cells, memory,
   cell-size range and
   aspect ratio.
5. Select the fault framework. Optionally set
   inactive-zone/thickness/volume rules and
   enable **Apply model boundary** to trim extent and mark cells outside
   it inactive.
6. Click **Build / update 3D grid**. Controls collapse after a successful
   build to give
   results room.
7. Inspect **3D cut-away**, **Sections**, and **Checks**. Use I/J cuts,
   zone/layer filters
   and cell edges to find inversions, thin cells, gaps or unexpected
   inactive regions.
8. After changing zone or grid definitions, rebuild. Do not use stale
   properties for
   analysis/export until recomputed or reviewed.

## Outputs
- Zone table, layering scheme and 3D corner-point grid appear under
  **Models**.
- Grid checks and sections provide geometry QC; active cells form the
  basis for properties,
  volumetrics and export.

## Quality control checklist
- [ ] Zone tops/bases are ordered, valid and cover intended intervals.
- [ ] Layering and grid dimensions fit resolution and cell budget.
- [ ] Boundary and inactive-cell rules match the study scope.
- [ ] Fault blocks and grid geometry are plausible in cut-away and sections.
- [ ] Grid checks are reviewed and stale downstream products identified.

## Tips and common pitfalls
- Zone edits invalidate the grid; grid-definition changes take effect only
  after a build.
- The current implementation uses vertical pillars and stair-stepped
  faults; it is a
  concept-model grid, not a fully general pillar-gridding system.
- Local refinement creates finer strips through row/column windows rather
  than isolated LGR
  cells.
- Boundary masking sets cells outside the polygon inactive; it is not
  fractional
  boundary-cell clipping.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) · [Facies,
  petrophysics and
  saturation](workflows/03-facies-petrophysics-saturation.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
