# Surfaces
> Location: **Input data â€º Surfaces** Â· Previous: [Project
>   setup](01-project-setup.md) Â·
>   Next: [Polygons](03-polygons.md)

## Purpose
Import, create, inspect, edit and export depth maps used as horizons,
model-area sources, or
property-valued maps.

## Before you start (inputs / prerequisites)
- Set project CRS and units on **Project â€º Project**.
- Have a supported regular grid or point/contour source. XYZ points
  require a defined model
  area for gridding.
- Polygon files belong on **Input data â€º Polygons**; the surface reader
  intentionally
  rejects polygon extensions.

## Step-by-step
1. Open **Input data â€º Surfaces**, then **Import files**. Supported
   surfaces include
   ESRI/Surfer ASCII, IRAP/RMS ASCII and binary grids (xtgeo support),
   and XYZ points. Set
   file XY/Z units and depth/elevation convention when asked.
2. Choose **Add to library** to retain a regular grid, or **Grid points
   into a surface**
   for point data; select a gridding method and parameters. The first
   regular-grid import
   can set the area; replace an existing area only with **Replace
   existing model area with
   this surface on import**.
3. To digitize contours, open **Digitize a map (JavaScript)**, calibrate
   the image, draw
   contours, and enter depth. **Depth step** increments after each line;
   select a line in
   **Contents** to correct its depth and click **Send to Python**.
4. To create a synthetic map, use **Synthetic surface**, configure the
   available parameters
   and click **Create surface**. Save generated maps through **Save
   surface file**.
5. In **Library & QC**, select a surface and inspect map, histogram,
   statistics, contours
   and optional well context. **Show depth contours**, contour interval,
   contour labels,
   and **Show well trajectories** apply to the map view.
6. Use **Filter & clip** for an ordered, non-destructive stack: polygon
   clip, value range,
   spike removal, steep-slope removal, hole filling or extension where
   available.
   Operations can be edited, toggled, reordered, deleted, previewed, and
   undone/redone.
   Presets can be saved and applied to other surfaces.
7. Duplicate a map with a depth offset or multiplier, or rename/delete an
   unused map.
   Detach workflow references before deleting a source surface.
8. Use **Surface display settings** / **Edit surface depth colours** to
   adjust display; use
   **Custom min / max range** and **Save colours** to preserve explicit
   data-unit limits.
9. Use **Save surface file** for IRAP binary, IRAP ASCII or XYZ points.
   For a full project
   archive, click **Prepare complete project download**, then **Save
   complete project
   (.gmsz)**.

## Outputs
- Named library surfaces and filter/preset metadata; maps appear in the
  **Input** tree.
- Digitized contours, gridded surfaces and export files. Surfaces are
  available to
  structural tasks and property trends.

## Quality control checklist
- [ ] File units and depth/elevation sign are correct before import.
- [ ] Map bounds and undefined-value coverage suit downstream horizons
      or trends.
- [ ] Polygon upload is redirected to Polygons if rejected by the
      surface importer.
- [ ] Filter previews show intended kept/removed areas; the raw map
      remains unchanged.
- [ ] Export format and CRS limitations are understood (IRAP/XYZ do
      not carry project CRS).

## Tips and common pitfalls
- IRAP grid node order uses standard X-fastest ordering. Reimport files
  read with older
  versions if ordering appears scrambled.
- XYZ exports only defined nodes; IRAP retains regular-grid geometry and
  undefined nodes.
- Surface files save the current map, not editable filter history; use
  `.gmsz` for full
  provenance.
- **Show model boundary** can overlay the project boundary while
  digitizing; calibrate the
  scanned image first.

## Related workflows
- [Quick start](workflows/01-quick-start.md) Â· [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md)
---

*GeoModel Studio â€” built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*

