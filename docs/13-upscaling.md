# Upscaling
> Location: **Analysis & QC › Upscaling** · Previous: [Analysis and
>   sections](12-analysis-and-sections.md) · Next: [Export](14-export.md)

## Purpose
Construct a coarser corner-point grid and upscale selected fine-grid
properties for review and
simulator hand-off.

## Before you start (inputs / prerequisites)
- Build and QC the fine grid; create the continuous and discrete
  properties to transfer.
- Review fault blocks and zone boundaries because coarse-grid merging
  preserves forced cuts
  at these boundaries.

## Step-by-step
1. Open **Analysis & QC › Upscaling**. Choose coarse I/J grouping and
   layer merging
   settings and select the property set to upscale.
2. Review averaging methods: PORO/NTG use volume-weighted averages,
   saturation uses
   pore-volume weighting, discrete properties use majority, and
   permeability supports
   arithmetic, harmonic, geometric, power-law or flow-based averaging.
3. For flow-based permeability, confirm assumptions: single-phase steady
   flow and closed
   lateral boundaries; where clipped cells have no connected flow path,
   geometric fallback
   may be used.
4. Click **Build coarse grid and upscale**. Inspect the coarse grid and
   fine-versus-coarse
   QC table.
5. Compare volume, pore volume, facies/zone distribution and permeability
   trends. Adjust
   grouping or averaging method and rebuild if the coarse representation
   is unsuitable.
6. Use **Export the coarse model** to download supported coarse
   GRDECL/EGRID/INIT data.

## Outputs
- Coarse grid and selected upscaled properties, with a fine-versus-coarse
  QC report.
- Coarse simulator export files.

## Quality control checklist
- [ ] Coarse grid honors key fault-block changes and zone boundaries.
- [ ] Property averaging method is appropriate for the property and
      intended use.
- [ ] Fine/coarse totals and distributions are reviewed.
- [ ] Flow-based permeability assumptions and fallback cells are understood.
- [ ] Coarse export format and units are verified.

## Tips and common pitfalls
- Upscaling is not a substitute for simulator-specific grid validation.
- Discrete properties use majority assignment; this can suppress thin
  facies.
- Flow-based averaging may use geometric fallback if connectivity is absent.
- Coarse exports do not include FAULTS keywords in the documented current
  workflow.

## Related workflows
- [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md) ·
  [Export](14-export.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
