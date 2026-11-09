# Facies, petrophysics and saturation

**Goal:** create a facies model, populate petrophysical properties, calculate water saturation and prepare them for volumetrics.

**Prerequisites:** current grid and zones; optional facies logs, well logs, property-valued maps and interpreted properties.

## Stages
1. Verify the grid in [Zones and 3D grid](../08-zones-and-3d-grid.md). Import/create discrete facies input or blocked well logs where required.
2. In [Properties](../09-property-modelling.md), configure facies proportions, method, variograms, conditioning and supported depth/map/distance trends. Run and inspect proportions and QC.
3. **Decision:** use **Domain assignments** for constant domain values or **Stochastic by zone / facies** for spatially variable distributions; ensure all active domains are parameterized.
4. Define PORO, PERMX/Y/Z, NTG and cut-offs. Check units (fractions, mD and ratios), correlations, histogram settings and reproducible seed. Review 3D/layer maps and distributions.
5. Select saturation-height or Archie. Choose gas only, undersaturated oil, or oil with gas cap. Set contact sources and domain values; gas-cap mode requires GOC. Archie also needs suitable PORO and Rt properties and calibrated parameters.
6. Run saturation and store SW. Verify active-cell coverage, contact response and saturation range. Rerun after changing grid, facies, petrophysics, contacts or settings.
7. Open [Volumetrics](../10-volumetrics.md), select intended properties and contacts, calculate results and inspect contact/fluid display.

## Decision points
- Facies simulation method depends on available conditioning data and intended spatial model.
- Domain-based values are constant within active domains; stochastic runs produce spatially varying values.
- Fluid system controls GWC/OWC/GOC interpretation; choose oil-with-gas-cap only with valid GOC.

## QC gates
- **Facies:** proportions and conditioning are understood; unsupported trends/method combinations are disabled.
- **Petrophysics:** every active zone/facies has values; PORO/NTG bounds and permeability distributions are plausible.
- **Saturation:** contact/FWL and fluid system match; SW is finite/current for active cells.
- **Volumetrics:** input properties are current and results plausible by zone/fault block.

**Expected result:** current FACIES/PORO/PERM/NTG/SW grid properties and a reproducible volumetric setup.

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../../LICENSE).*
