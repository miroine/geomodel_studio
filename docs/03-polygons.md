# Polygons
> Location: **Input data › Polygons** · Previous:
>   [Surfaces](02-surfaces.md) · Next:
>   [Faults](04-faults.md)

## Purpose
Create and manage XY polygons for model boundaries, surface clipping, and
property assignment.

## Before you start (inputs / prerequisites)
- Confirm project CRS and XY units. Polygon coordinates are converted from
  declared file
  units.
- Have a closed outline for a boundary or assignment; fault traces are
  imported separately
  on Faults.

## Step-by-step
1. Open **Input data › Polygons**. In **Digitize (JavaScript)** choose a
   backdrop surface
   if useful, draw the outline, and refine it with vertex
   drag/insert/delete controls.
   Apply the drawing to the project.
2. To import, open **Import / export**, select **Polygon files**, set
   source XY units as
   prompted, and add supported XY text, GeoJSON, RMS `.POL`, or
   `.rmspolygons` files.
3. RMS polygon parts are separated by `999 999 999`; Z is ignored. Use
   **Use the first
   polygon as model boundary** when that polygon defines the boundary.
4. Select the intended polygon under **Model boundary** in **Library &
   boundary**. Boundary
   selection does not itself rebuild or mask an existing grid.
5. To clip surfaces, select the polygon and target surfaces, configure
   the buffer and
   inside/outside choice, then click **Add clip to selected surfaces**.
   The surface filter
   stack retains the operation non-destructively.
6. Export polygon coordinates through the import/export controls when
   needed. Delete only
   polygons no longer referenced by the boundary or workflow.
7. For property assignment, build a current grid, then use **Assign
   property using a
   polygon** in **Property modelling › Properties**; see the [Properties
   guide](09-property-modelling.md).

## Outputs
- Named polygon objects in the **Input** tree; optional model-boundary
  reference.
- Polygon clip operations attached to surfaces; exported XY data when
  requested.

## Quality control checklist
- [ ] Imported coordinates use the correct XY unit and project CRS.
- [ ] Boundary/assignment outline is closed and has no unintended
      self-crossings.
- [ ] Selected model boundary is the intended polygon.
- [ ] Surface clipping is previewed before downstream use.
- [ ] Grid is rebuilt after changing boundary settings.

## Tips and common pitfalls
- The surface importer rejects `.POL` and `.rmspolygons` and directs users
  here; polygon
  data are not surfaces.
- RMS separator records are structural delimiters, not polygon vertices.
- Boundary masking affects grid extent and active cells only when **Apply
  model boundary**
  is selected during grid building.
- Polygon assignment tests column centres, not fractional cell coverage;
  points on the edge
  count as inside.

## Related workflows
- [Quick start](workflows/01-quick-start.md) · [Rerunnable property
  workflow](workflows/04-rerunnable-property-workflow.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
