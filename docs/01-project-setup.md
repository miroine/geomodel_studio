# Project setup
> Location: **Project › Project** · Previous: — · Next:
>   [Surfaces](02-surfaces.md)

## Purpose
Create a named project, establish coordinate and unit conventions, and
define the regular
model lattice and optional model boundary before modelling.

## Before you start (inputs / prerequisites)
- Decide the project CRS (EPSG), XY unit, depth unit, and vertical datum.
  Depth is positive
  down.
- If a model-area surface is available, import it first or plan to select
  it from the
  surface library.
- A project-area lattice is limited to 400,000 nodes; choose spacing with
  that limit in mind.

## Step-by-step
1. Open **Project › Project**. Edit **Name** to label the project.
2. In **Coordinate system and units**, set CRS, XY unit, depth unit and
   vertical datum;
   click **Apply CRS and units**. Choose whether existing values should
   be converted or
   relabelled when prompted. Surface files do not establish the project CRS.
3. In **Model area**, enter the lattice extent and spacing (or node
   counts) and review the
   reported lattice size. Keep it within the limit, then click **Set
   model area**.
4. To derive the model area from an imported regular grid, choose
   **Surface for model
   area**, click **Load area from surface**, review calculated bounds and
   spacing, then
   click **Set model area**. The full node extent, including undefined
   nodes, is used;
   rotated grids are enclosed by a north-up rectangle.
5. The first regular-grid surface import can fill the area automatically.
   Existing area is
   preserved unless **Replace existing model area with this surface on
   import** is
   selected. XYZ point files need an existing area before gridding.
6. Optionally select a boundary polygon in **Model boundary** on the
   Polygons page. When
   building the grid, enable **Apply model boundary** to trim the extent
   and deactivate
   cells outside it.
7. Use **Open demo project (synthetic anticline, 2 faults, 5 wells)** to
   load the example,
   or **New empty project** to reset to a blank project.
8. Save with **Save project (.gmsz)**. Reopen through **Open saved
   project (.gmsz)**;
   downloads are explicit and not automatic disk persistence.

## Outputs
- Project name, CRS/unit/datum settings, model-area lattice, and optional
  boundary selection.
- Active project objects appear in the left **Input** and **Models** trees.

## Quality control checklist
- [ ] CRS and datum describe the data rather than being inferred from
      a file.
- [ ] XY and depth units match imported sources; depth is positive down.
- [ ] Lattice covers the intended area and is below 400,000 nodes.
- [ ] Boundary selection is intentional; boundary masking is applied
      later during grid
      construction.
- [ ] Save a `.gmsz` download outside the browser session when work
      must persist.

## Tips and common pitfalls
- Unit conversion changes stored lengths; relabelling changes their
  interpretation. Choose
  carefully when project data already exist.
- Full surface node extent is used for automatic area derivation, not only
  its defined-value
  footprint.
- Rotated source maps are resampled into the model's north-up lattice; the
  model lattice
  itself is unrotated.
- Reprojection resamples surfaces and requires rerunning structural
  modelling.

## Related workflows
- [Quick start](workflows/01-quick-start.md) · [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*

