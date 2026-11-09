# 3D window and display
> Location: **Analysis & QC › 3D window** · Previous:
>   [Volumetrics](10-volumetrics.md) ·
>   Next: [Analysis and sections](12-analysis-and-sections.md)

## Purpose
Inspect surfaces, faults, wells, tops and grid properties together in the
interactive 3D
scene, with consistent colour controls and cell-level inspection.

## Before you start (inputs / prerequisites)
- Create at least one model object; build the grid to inspect cells and
  properties.
- Keep properties current and select a stored property for property
  colouring.

## Step-by-step
1. Open **Analysis & QC › 3D window**. Choose visible surfaces,
   structural horizons, fault
   planes, polygons, wells, tops and grid through **Scene content**.
2. Navigate with left-drag orbit, right- or Shift-drag pan, wheel zoom,
   and double-click
   fit. Use view controls for top, 3D, north/south or east/west section
   views; adjust
   vertical exaggeration live.
3. Select **Mesh** / **Black mesh edges** where available to show
   triangle or cell
   outlines. Adjust per-object visibility and opacity in the scene object
   tree.
4. Colour the grid by zone, layer, block, depth, thickness or a stored
   property. For custom
   palettes/ranges, open **Edit property colours** (or **Scene content**)
   and select
   **Custom min / max range**; click **Save colours**. Use **Reset to
   automatic colours**
   to restore defaults.
5. Adjust **Grid opacity** when the outer grid skin obscures wells. To
   see interior cells,
   use cut-away/layer filters or a fence; opacity alone does not reveal
   interior faces.
6. Click a visible grid face without dragging to inspect global 1-based
   I/J/K, value and
   unit. Use **Other properties at selected cell** to compare more
   properties at the same
   cell.
7. Save a PNG from the scene toolbar when a static view is needed. Camera
   and visibility
   persist across reruns in the project.

## Outputs
- Interactive scene state and project-saved display settings, including
  palettes, custom
  limits, opacity and camera/visibility.
- Optional PNG image and selected-cell property inspection.

## Quality control checklist
- [ ] Correct objects and selected property are shown.
- [ ] Colour range is reported in property data units and does not
      change underlying values.
- [ ] Interior cells are exposed with cuts/filters/fences before inspection.
- [ ] Selected cell is current, active and indexed in the original
      global I/J/K grid.
- [ ] Exported image includes the intended view and legend/context.

## Tips and common pitfalls
- Values outside custom limits use end colours; values are not clipped or
  modified.
- Permeability colour mapping is log-scaled while inspection reports raw
  values.
- Lower opacity reveals context behind the shell but does not create
  internal faces.
- Display gap at fault crossings follows mesh resolution; it is not
  additional throw or heave.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) · [Analysis
  and sections](12-analysis-and-sections.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
