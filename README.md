# GeoModel Studio

GeoModel Studio is a browser-based Streamlit concept-modelling workspace for geological interpretation, structural framework building, 3D gridding, property modelling, volumetrics and simulator-oriented data export. Its object-based workflow brings surfaces, polygons, faults, wells, tops and grid properties into one project.

> **Disclaimer**  
> Built by Merouane Hamdani. Licensed under the PolyForm Noncommercial License 1.0.0 — free for personal, research, educational and other non-commercial use; commercial use is not permitted. Provided as-is without warranty; a concept-modelling tool, not a substitute for validated commercial software.

## Features

- Import, digitize, filter and QC surfaces; manage polygons and boundary masks.
- Build faulted structural frameworks, calibrated horizons, zones and corner-point grids.
- Model facies, petrophysics and water saturation with conditioning, trends and rerunnable jobs.
- Explore 3D scenes, analysis sections, volumetrics, uncertainty and upscaled grids.
- Export simulator grids and project/object data in supported formats.

## Quick start

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Open the local Streamlit URL in a browser. Use **Open demo project (synthetic anticline, 2 faults, 5 wells)** on **Project › Project** to explore the included example. Project downloads are explicit; save a `.gmsz` archive when work must persist.

## App layout

- **Ribbon domains:** Project, Input data, Structural framework, Gridding, Property modelling, Volumetrics, Analysis & QC, and Export. Each page follows the `Domain › Page` vocabulary used in the documentation.
- **Left panel:** **Input**, **Models**, and **Processes** tabs. Input/Models contain object trees; Processes shows the numbered process flow and readiness/state indicators.
- **Guide panels:** each page has a collapsible **Guide** at the top with the matching page documentation.
- **Status bar:** summarizes project/readiness information and stale or missing dependencies.

## Documentation

Start with the [documentation index](docs/README.md) for the process diagram, conventions and guide map.

| Guide | Purpose |
|---|---|
| [Project setup](docs/01-project-setup.md) | Project, CRS, units, lattice, boundary and save/load |
| [Surfaces](docs/02-surfaces.md) | Import, digitize, synthetic maps, QC and filters |
| [Polygons](docs/03-polygons.md) | Draw/import polygons, boundary and clipping |
| [Faults](docs/04-faults.md) | Fault traces, geometry and workflow inputs |
| [Wells](docs/05-wells.md) | Import, edit and inspect well paths |
| [Well tops](docs/06-well-tops.md) | Import picks and calibration QC |
| [Structural model](docs/07-structural-model.md) | Ordered structural workflow and calibration |
| [Zones and 3D grid](docs/08-zones-and-3d-grid.md) | Layering, grid build and checks |
| [Properties](docs/09-property-modelling.md) | Library, calculator, facies, petrophysics and saturation |
| [Volumetrics](docs/10-volumetrics.md) | Contacts, fluid systems and results |
| [3D window and display](docs/11-3d-window-and-display.md) | Scene navigation, colours and cell inspection |
| [Analysis and sections](docs/12-analysis-and-sections.md) | Statistics, plots, maps and cross-sections |
| [Upscaling](docs/13-upscaling.md) | Coarse-grid construction and QC |
| [Export](docs/14-export.md) | Grid, object and project exports |
| [Quick start workflow](docs/workflows/01-quick-start.md) | Empty project to first volumetric results |
| [Structural framework to grid](docs/workflows/02-structural-framework-to-grid.md) | Structure, zones and grid sequence |
| [Facies, petrophysics and saturation](docs/workflows/03-facies-petrophysics-saturation.md) | Property modelling sequence |
| [Rerunnable property workflow](docs/workflows/04-rerunnable-property-workflow.md) | Configure, execute and restore property jobs |
| [Detailed feature reference](docs/reference.md) | Preserved detailed modelling and algorithm notes |

## Testing

Run the project checks from the repository root:

```powershell
python tests\test_ui.py
python tests\test_core.py
python -m unittest discover -s tests
```

## Project structure

```text
app.py          Streamlit entry point
core/           Modelling, data, grid and export logic
ui/             Shared presentation and plotting helpers
views/          Domain/page implementations
components/     Browser-based map editor and 3D viewer
tests/         Automated checks
docs/           User guides and workflows
```

## License

GeoModel Studio is intended for non-commercial use under the PolyForm Noncommercial License 1.0.0. Commercial use is not permitted. See [LICENSE](LICENSE) for the license text. The software is provided as-is without warranty and is intended for concept modelling.

