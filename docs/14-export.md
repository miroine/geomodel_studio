# Export
> Location: **Export › Export** · Previous: [Upscaling](13-upscaling.md) ·
>   Next: —

## Purpose
Write the current grid, selected properties, surfaces, faults, tops and
project archive in
supported hand-off formats.

## Before you start (inputs / prerequisites)
- Build a current grid and recompute or review stale properties.
- Decide simulator units (METRIC or FIELD), output properties, regional
  keywords, and
  destination file location.
- Install optional libraries listed by the app when requesting formats
  that depend on them
  (for example xtgeo or RESQML dependencies).

## Step-by-step
1. Open **Export › Export** and choose **Grid for simulators**,
   **Surfaces, faults, tops**,
   or **Project**.
2. For grid output, select format and properties. Supported choices
   include Eclipse GRDECL,
   EGRID/INIT and VTK; xtgeo-dependent formats include ROFF and related
   output where
   available.
3. Choose simulator unit system, configure optional region keywords
   (FIPNUM/EQLNUM/SATNUM/FLUXNUM), and decide whether to write
   FAULTS/MULTFLT data.
4. For GRDECL choose the layout: **One merged file** (grid + all
   properties in `MODEL.GRDECL`) or **Standalone files** (zip with
   `MODEL_GRID.GRDECL`, one `MODEL_<PROP>.GRDECL` per property and a
   `MODEL_INCLUDE.GRDECL` deck that INCLUDEs them all).
5. Review estimated output size and warnings. Download generated files
   through the browser.
5. On **Surfaces, faults, tops**, select the requested object and format.
   Surface downloads
   use current project XY/depth units; IRAP/ESRI outputs do not preserve
   CRS.
6. On **Project**, prepare and save the complete `.gmsz` archive when
   project settings, raw
   maps, workflow history and objects need to travel together.
7. Reopen or inspect exports with the target consumer, and verify CRS,
   units, property
   mnemonics, active-cell ordering and file completeness before
   operational use.

## Outputs
- Grid/deck, binary simulator, VTK/ROFF/RESQML or object-specific exports
  depending on
  dependencies and selected options.
- Surface/fault/top files and complete `.gmsz` project archive.

## Quality control checklist
- [ ] Export uses current grid and property versions.
- [ ] Simulator unit system, GRIDUNIT and deck settings agree.
- [ ] Required properties and regional arrays are selected and named
      appropriately.
- [ ] Optional dependencies are installed and format warnings resolved.
- [ ] Output files are reopened/validated in a compatible tool before use.

## Tips and common pitfalls
- RESCUE is not written; GRDECL/EGRID/ROFF are documented interchange
  paths for Petrel/RMS
  workflows.
- EGRID/INIT property names may be shortened to simulator limits.
- Surface and fault-trace interchange formats may not carry CRS; record it
  externally.
- Downloads are explicit browser saves; this app does not automatically
  persist files to a
  chosen local folder.

## Related workflows
- [Quick start](workflows/01-quick-start.md) · [Structural framework to
  grid](workflows/02-structural-framework-to-grid.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
