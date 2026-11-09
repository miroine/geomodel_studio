# Quick start: from empty project to volumes

**Goal:** take the shortest reliable route from a blank project to an initial volumetric result.

**Prerequisites:** install dependencies, launch the app, and have a horizon map or use the included demo. Set project CRS and units before importing data.

## Stages
1. Start at [Project setup](../01-project-setup.md). Set the project name, CRS/units and lattice; for exploration, **Open demo project (synthetic anticline, 2 faults, 5 wells)** supplies an example model.
2. If using your own data, follow [Surfaces](../02-surfaces.md) to import a top map, then use [Polygons](../03-polygons.md) for a boundary. Add [Faults](../04-faults.md), [Wells](../05-wells.md) and [Well tops](../06-well-tops.md) when available/needed.
3. Build horizons and zones using [Structural model](../07-structural-model.md), then create the grid using [Zones and 3D grid](../08-zones-and-3d-grid.md).
4. Create minimum required petrophysics and saturation using [Properties](../09-property-modelling.md). Alternatively use demo properties if present.
5. Configure and run [Volumetrics](../10-volumetrics.md). Check contact, fluid system and property sources before reading totals.
6. Review [3D window](../11-3d-window-and-display.md), [Analysis and sections](../12-analysis-and-sections.md), and optionally [Upscaling](../13-upscaling.md); use [Export](../14-export.md) for hand-off.

## Decision points
- **Blank vs demo:** use the demo to learn UI; start a new project for independent work.
- **No tops or faults:** these inputs are optional; skip them if no interpretation is available.
- **Grid resolution:** begin coarse, inspect geometry and volumetrics, then refine if needed.
- **Fluid system:** select gas-only, undersaturated oil or oil with gas cap; gas-cap mode needs a GOC.

## QC gates
- **Gate 1 — project:** CRS, units, depth sign, area and boundary are correct.
- **Gate 2 — structure/grid:** horizons and zones are plausible; grid checks pass and boundary masking is intended.
- **Gate 3 — properties:** active cells have valid inputs; stored results are current.
- **Gate 4 — volumes:** contact interpretation and fluid system are correct; outputs are plausible and saved.

**Expected result:** a saved project with a built grid and initial volumetric report. For validated commercial decisions, verify independently in fit-for-purpose software.

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../../LICENSE).*
