# Analysis and sections
> Location: **Analysis & QC › Analysis & sections** · Previous: [3D window
>   and
>   display](11-3d-window-and-display.md) · Next:
>   [Upscaling](13-upscaling.md)

## Purpose
Summarize, compare and visualize grid properties through statistics,
histograms, crossplots,
vertical profiles, maps and cross-sections.

## Before you start (inputs / prerequisites)
- Build a current grid and create/import properties to analyze.
- Store FLUID first if analysis needs fluid split; confirm property units
  and discrete
  legends.
- Draw a fence on a map when a fence-aligned section is required.

## Step-by-step
1. Open **Analysis & QC › Analysis & sections** and choose the property
   or property pair.
2. Configure **Filters - zones, layers, value ranges**. These filters
   apply to all tabs;
   optionally select net cells only and a split by zone, fault block,
   layer, fluid or
   discrete region.
3. In **Statistics**, review min, volume-weighted mean, standard
   deviation, percentiles and
   maximum for the selected split.
4. Use **Histogram / CDF** for distributions and **Crossplot** for two
   properties,
   including optional log axes, split colouring, correlation and fitted
   line.
5. Use **Vertical profile** for layer means and percentile bands by
   depth. In **Maps**,
   select average, thickness-weighted average, sum, min or max aggregation.
6. Use **Cross-sections** to view a row, column or digitized fence; up to
   three properties
   can be stacked. Overlay contacts and fault crossings where useful.
7. Use **Generate average maps for multiple parameters** for selected
   continuous properties
   and layers, then export/download derived map tables if needed.
8. Save display changes from **Edit property colours** with **Save
   colours**; selected
   custom ranges are display limits only.

## Outputs
- Statistics/tables, distribution plots, crossplots, profiles, map views
  and cross-section
  views.
- Optional derived average-map tables and CSV data; these maps are not new
  3D property
  snapshots.

## Quality control checklist
- [ ] Filters and split dimensions match the intended population.
- [ ] Stale, undefined and inactive-cell values are excluded or understood.
- [ ] Volume-weighted statistics are distinguished from cell-count
      statistics.
- [ ] Crossplot sample and log-axis choices are appropriate.
- [ ] Section orientation, fence path and contact overlays are checked.

## Tips and common pitfalls
- Crossplots sample up to 5,000 cells; correlation and fit describe the
  sampled population.
- Fence sections use grid-column ribbons with averaged layer top/base, not
  a fully
  interpolated surface.
- Maps are indexed in I/J space; CSV exports may include world XY
  coordinates.
- Region/fluid splits depend on valid discrete properties and saved legends.

## Related workflows
- [Facies, petrophysics and
  saturation](workflows/03-facies-petrophysics-saturation.md) ·
  [Upscaling](13-upscaling.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
