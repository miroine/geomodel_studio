# GeoModel Studio

A Streamlit app that walks the Petrel / RMS structural-modelling path in a browser. Like those tools it is **object based**: every step produces an
object in the tree on the left (surfaces, polygons, faults, wells, well tops, structural model, zones, 3D grid) and the **3D window** shows them together.

**surfaces (+ filters) -> polygons -> faults -> wells & tops -> structural workflow -> zones & layering -> 3D corner-point grid -> simulator export**

All plotting and editing is JavaScript, no npm build step:
* `components/viewer3d` - custom **WebGL** 3D window (orbit / pan / zoom, vertical exaggeration, mesh, wells as tubes with top markers, object tree, legends, PNG)
* `components/map_editor` - map **digitizer**, **fault designer** and **polygon editor**
* `components/plotly_view` - Plotly.js for maps, sections and histograms

## Run
```bash
pip install -r requirements.txt      # streamlit, plotly, numpy, scipy, pandas, xtgeo
streamlit run app.py
```
Open **Project -> Open demo project** (synthetic anticline, 2 faults, unconformity, a noisy overburden map, a boundary polygon, 6 wells incl. one deviated).
`plotly` supplies the offline Plotly.js bundle (CDN fallback if missing).
Workflow steps have unique, stable widget IDs; duplicate or missing IDs in older saved projects are repaired automatically when the workflow is opened.

In **Digitize a map**, enter each contour's depth or set a nonzero **Depth step** to increment it after finishing each line (negative steps are supported).
Select a contour in **Contents** to correct its depth, then **Send to Python** again. Equal depths produce a constant map and trigger a warning.
**Show model boundary** overlays the project's boundary polygon on the digitizer (calibrate scanned images first); the gridded map has a separate boundary toggle.

## The object tree (sidebar)
Input data: **Surfaces, Polygons, Faults, Wells, Well tops** - Models: **Structural model, Zones, 3D grid**. Click an object to open its page with that object selected;
the dot shows whether a model object is built. Top buttons: Project, 3D window, Export.

## What each page does
| Page | Capabilities |
|---|---|
| Project | model lattice, demo, save / open `.gmsz` (keeps raw maps, filter stacks with undo history, presets, polygons, wells) |
| Surfaces | import ESRI/Surfer ASCII, **IRAP/RMS ASCII + binary (xtgeo)**, XYZ points; gridding (min-curvature, RBF, IDW, linear); **digitize a scanned map**; synthetic surfaces; **Filter & clip** (below) |
| Polygons | **digitize** (JS editor, drag / insert / delete vertices) or **import** (XY text, GeoJSON); export XY; pick the **model boundary**; clip surfaces to a polygon |
| Faults | draw traces, normal / reverse, throw, dip, hanging-wall side, along-strike profile, drag zone, growth; faulted preview |
| Wells | head table, **deviation surveys (minimum curvature)**, XYZ paths, import with templates, build / hold generator, create from tops, 3D preview |
| Well tops | CSV import, editable table, map, misfit QC |
| Structural model | ordered workflow: surface, isochore, **calibrate to tops**, smooth, faults; roles conformable / erosional / base-lap |
| Zones & layering | proportional, follow top, follow base, fractions; zone properties |
| 3D grid | vertical-pillar corner-point grid, stair-stepped faults, **cells outside the boundary polygon inactive**, WebGL cut-away + sections + checks |
| 3D window | surfaces, structural-model horizons, fault planes, polygons, wells, tops, grid coloured by Zone / Layer / Block / Depth / Thickness / PORO / PERMX / NTG |
| Export | **GRDECL**, **VTK**, **ROFF / EGRID / bGRDECL via xtgeo**, surfaces, fault traces, tops, project |

### Filter & clip (per surface, non-destructive)
The raw map is never overwritten. Each surface has an ordered stack of operations you can **add, edit, switch on/off, reorder and delete**:
*clip by polygon* (inside / outside, buffer), *value range* (absolute or percentile), *remove spikes* (local median, robust sigma), *remove steep slopes*, *fill small holes*.
Every change is **undoable / redoable** (50 steps), stacks can be **saved as presets** and applied (replace / append) to several surfaces, and a **Smart suggestions** box
proposes thresholds from the data (P1-P99, number of spikes at k = 3 / 4 / 6). Previews: kept / removed map, filtered map, histogram with the thresholds.

### 3D window
Left-drag orbit, right- or Shift-drag pan, wheel zoom, double-click fit. Toolbar: vertical exaggeration (live, no rerun), **Mesh** (triangle / cell edges), well **Names** and **Tops** labels,
dark background, Top / 3D / Section N / Section E views, PNG. The object tree toggles visibility and opacity per object; camera and visibility survive reruns.
In **Scene content**, use **Filter grid view by** to show selected **Zones**, an inclusive **Layers** range, or **Zones and layers** together.
The same controls are available in **3D grid > 3D cut-away**. Layers use global 1-based k numbers; combined filters show their intersection.
Filtering exposes the selected cells' outer faces and works with I/J cuts without changing active cells, properties, exports, or other scene objects.

### Drawing faults
Open **Faults**, select a backdrop surface, then choose **Draw fault** (selected automatically when no faults exist).
Click vertices along the trace and double-click the final vertex or press **Enter** to finish. Set throw, dip and hanging-wall side in the panel,
then press **Apply to model**. Run the structural workflow again to update faulted horizons, and rebuild the grid to use the new faults.

## Interpolation and extension algorithms (v3)
**Gridding** (scattered points / digitized contours -> surface): `min_curvature` (default for structure), `rbf` (thin plate), `kriging` (ordinary, spherical / exponential /
gaussian variogram, optional plane / quadratic drift, local neighbourhood; also gives a kriging std-dev), `cubic` (Clough-Tocher), `local_poly` (LOESS), `moving_average`,
`idw`, `linear`, `nearest`, and `trend_residual` (remove a plane / quadratic trend, grid the residual with any method, add it back - best for strongly dipping data).
Each method shows its own parameters; *Mask beyond* leaves nodes far from data undefined.

**Extension of undefined areas** (`core/extrap.py`), used by the *Extend / extrapolate* surface filter (undo / redo, distance limit) and by the structural workflow:
`nearest` (flat shelf, the v1/v2 behaviour and still the default), `gradient` (continues the local dip, damped), `decay` (edge value relaxes to the regional plane),
`plane`, `trend2`, `min_curvature` (smooth continuation, safeguarded against overshoot), `constant`, `none` (surface filter only - a model horizon must be defined everywhere).

**Structural workflow:** every *surface* or *isochore-map* step has *Resample map* (linear / cubic) and *Where the map is undefined* (all extension modes). Calibration residuals
can be interpolated with any gridding method (kriging, trend + residual, local polynomial ...). New steps: **proportional** (a horizon at x % between two horizons) and **clip**
(depth window).

## Layers between horizons, fences and 3D sections (v3.1)
* **Layers step** (Structural model -> Add a step -> *Layers between two horizons*): inserts intermediate horizons between two horizons - *N equal layers*, *custom fractions*,
  *constant thickness from the top* or *from the base* (layers pinch out against the opposite horizon). Names are `Prefix_1 ... Prefix_n`; they behave like any horizon (maps,
  3D, sections, zones, later steps). Put the step after the calibration of its two bounding horizons. Layer horizons start switched off in the 3D tab (there can be up to 200).
* **Fences** - open polylines drawn on the map (*Cross-section* tab -> *Draw / edit fences*; click vertices, double-click to finish, drag / insert / delete vertices, *Apply to project*).
  A section can also run *Through wells* (pick wells in order), West-East, South-North or between typed coordinates.
* **Fence cross-section**: faulted horizons along the bent line, interval colours from the zones table, dashed lines where the fence crosses fault traces, dotted ticks at fence
  vertices, well tops and well paths projected from within a chosen offset.
* **3D**: the structural-model 3D tab already shows all horizons, faults, wells and tops; tick a fence under *Fence curtains* to add its cross-section as a coloured vertical
  curtain (with horizon lines) inside the 3D window.

## Zones, fault models, grid control and properties (v3.2)

**Zone steps** (Structural model > add step > *Zone*). A zone is a self-contained interval: a base horizon below a top horizon with its own thickness
model (constant, constant + trend, isochore map or a base surface), optional Gaussian smoothing, min / max thickness limits, tops calibration (any residual
method) and its own layering. The step is expanded into the primitive steps (isochore / surface -> smooth -> thickness limit -> calibrate), so each zone can be
tuned independently; the **Zones** tab of the results gives per-zone thickness statistics, pinch-out share and tops RMS before / after, and
*Create / update grid zones* turns the zone steps into the zone table (layers and style included, porosity etc. kept for zones with the same name).

**Fault models** (map-editor panel; `core/faults.py`):

| type | behaviour |
|---|---|
| normal / reverse | hanging wall down / up the plane, vertical separation = throw |
| strike_slip | lateral slip along strike (dextral / sinistral); only dipping horizons show an offset; `throw` adds an oblique component |
| transverse | transfer / cross fault: throw changes sign along strike (scissor / hinge) about `pivot`; optional `slip` |

`heave` (0-1) additionally translates horizons horizontally by heave x throw / tan(dip) for the dip-slip types, so cut-offs separate / overlap.
Grid columns are cut into fault blocks wherever the offset (throw, slip or heave) exceeds a small threshold.

**Grid control** (3D grid page): cell size or number of cells; **rotation** (the grid is built in a local frame and the GRDECL carries `MAPAXES`);
frame fitted to the model or entered by hand; **local refinement windows** (grid-line refinement - the entire row / column strip through a window gets the finer
spacing, as in a corner-point grid without LGR; one click adds windows around the fault traces); ACTNUM rules: minimum thickness, minimum bulk volume, inactive zones
(over / underburden), cells outside the model extent / boundary. The page shows an estimate of columns, layers, cells, memory, cell size range and aspect ratio before building, and
active-cell geometry statistics afterwards. Vertical pillars remain: faults are stair-stepped, not sloping pillars.

**Properties** (Properties page; `core/props.py`): dense (K, J, I) arrays linked to the grid; created from the zone table, as constants, or with the **Python calculator**.
The calculator parses the script with `ast`, accepts assignments, arithmetic, comparisons, masks and a fixed list of functions (`where exp log sqrt clip smooth by_zone by_block
zone_mean layer_mean noise gauss table mean percentile ...`), and runs it with empty builtins - no imports, attribute access, loops, comprehensions or strings.
Geometry variables: `I J K X Y DEPTH DX DY DZ VOLUME ZONE BLOCK ACTNUM`. Example: `PERMX = 10 ** (14 * PORO - 1.8)`, `PORO[ZONE == 3] = 0.05`.
When the grid is rebuilt, properties with other dimensions are removed and properties on changed geometry are flagged *stale* (recompute button). Properties
are saved in the project (`props.npz`), shown in 3D / layer maps / histograms, and written to the GRDECL (a user property named like a zone property replaces it).

**Stochastic property modelling** (Properties page > *Stochastic modelling*; `core/geostat.py`): porosity, permeability and net-to-gross as Gaussian random fields
per zone. (1) Variogram per zone: spherical / exponential / gaussian, major / minor / vertical range, azimuth (deg from north), nugget; fields are generated by FFT spectral simulation
in cell-index space scaled by the mean cell size, so millions of cells take seconds. (2) Target histogram per property and zone: normal, log-normal, uniform, triangular, user histogram bins
or pasted values (core plugs), min / max truncation, applied with a rank (normal-score) transform so the histogram is reproduced. (3) Correlation: PORO-PERM, PORO-NTG, PERM-NTG imposed with the
Cholesky factor (correlation of the Gaussian fields, positive-definiteness checked); alternatively permeability from porosity, log10 k = a PORO + b + scatter field. (4) Cut-offs on porosity,
permeability and NTG define a NET flag; NTG can be zeroed in non-net cells or made binary. PERMY = PERMX x ratio, PERMZ = PERMX x KV/KH of the zone. Several realisations (`_R1`, `_R2` ...), fixed seed
for reproducibility. QC: simulated histogram, PORO-PERM cross-plot with log permeability, experimental vs model variograms along I / J / K, achieved Pearson / Spearman correlation, net fraction.
Limits: mean cell size is used for the spectral generation, zones are independent (no continuity across zone boundaries), no conditioning to well logs, truncation lowers the achieved correlation slightly.

## Volumetrics, analysis and property sections (v3.2)

**Volumetrics (page 8).** GRV, NRV, PV, HCPV, STOIIP and GIIP above the contacts of the 3D grid.
- Contacts: a global OWC and optional GOC, with optional overrides per fault block. A cell cut by a contact contributes the fraction of its height above it (cell top / base = mean of the four corner depths), so results change smoothly with the contact.
- Porosity and NTG come from the zone table or from any stored property (e.g. the stochastic `PORO_R1`). Water saturation is a constant per zone, a property, or a saturation-height function `Sw = Swirr + (1 - Swirr) (entry / height above OWC)^exponent`.
- Net cut-offs on porosity, NTG and Sw. `STOIIP = HCPV_oil / Bo`, `GIIP = HCPV_gas / Bg + STOIIP x Rs`. Volumes are computed in m3 (project units converted) and shown in MSm3 / GSm3 or MMstb / Bscf.
- Tables by zone and by fault block, CSV download, **contact scan** (STOIIP versus OWC), **tornado** and **Monte-Carlo** (triangular distributions on OWC shift, Sw multiplier, Bo, porosity and NTG multipliers; P90 / P50 / P10 with P90 the low case), and **P90 / P50 / P10 over stochastic realisations** (`PORO_R#`, `NTG_R#`, `SW_R#`).
- "Store as properties" writes FLUID (1 gas, 2 oil, 3 water), SW, VOL_GRV, VOL_HCPV, VOL_STOIIP, VOL_GIIP and VOL_NET as cell properties.
- Settings are saved in the project file and scaled when the project units change.

**Analysis & sections (page 9).** Filters (zones, layer range, two value ranges, net cells) apply to every tab:
- Statistics (min, volume-weighted mean, std, P10 / P50 / P90, max) split by zone, fault block, layer or fluid.
- Histogram and CDF overlay by split; crossplot of two properties (<= 5000 sampled cells, log axes, correlation, linear fit, coloured by split).
- Vertical profile (layer mean with P10 - P90 band against depth); maps in I / J space (average, thickness-weighted with NTG, sum, min, max).
- **Property cross-sections**: row (J), column (I) or along a digitised fence; up to three properties stacked on a shared axis. Row and column sections draw the exact cell quads; a fence draws one ribbon per grid column crossed (layer top / base averaged over the column). OWC / GOC and fault crossings can be overlaid.

Limits: volumetrics ignore the part of a cell below the OWC by linear interpolation of the top / base (no sub-cell geometry); contacts are horizontal planes per block; fence sections are ribbons, not interpolated surfaces; the fluid split needs FLUID stored first.

## Planes, regions, fluid split and simulator formats (v3.2)

**Planes & regions** (Properties page, last tab).
- *Horizontal planes to properties*: give planes a name and a depth (or use the volumetrics contacts). Per plane you get `HAP_<name>` (height above the plane, positive above), `FRAC_<name>` (fraction of the cell above the plane) and one discrete `PLANE_REGION` numbering the slabs between the planes. The contact button writes `OWC_DEPTH`, `GOC_DEPTH`, `HAOWC`, `HAGOC` and `FLUID`.
- *Fault-block region and segments*: `FAULT_BLOCK` and `REGION` (the fault-block number) and `SEGMENT` (numbered combinations that contain active cells: fault block, zone x block, or zone x block x fluid). Discrete properties carry a legend (value -> name) that is saved with the project and used in tables and plots.

**Fluid split.** FLUID is 1 gas (above the GOC), 2 oil (down to the OWC), 3 water (below), evaluated at the cell centre with the per-block contacts. The Analysis page now computes it from the Volumetrics contacts when it has not been stored, and splits by fluid, region, segment or any other discrete property with the legend names.

**Exports** (page 10).
- GRDECL with any property; REGION / SEGMENT can also be written as FIPNUM, EQLNUM, SATNUM or FLUXNUM.
- **EGRID** and **INIT** are written natively (Eclipse binary big-endian records; INIT holds PORV, DEPTH, DX, DY, DZ and the selected properties on the active cells, names shortened to 8 characters).
- **Hand-over package** (zip): GRDECL, EGRID, INIT, ROFF grid + properties when xtgeo is installed, horizons as IRAP binary, fault traces as RMS polylines, well paths, picks and a README.
- **RESQML 2.0.1** (EPC + HDF5) through resqpy + h5py (listed in requirements.txt; the button explains what is missing when they are not installed).
- RESCUE is not written (retired binary format without an openly verifiable byte layout); Petrel and RMS read GRDECL / EGRID / ROFF directly.

## Well logs, contacts by region, fault transmissibility, inclined pillars, structural uncertainty, upscaling (v3.3)

**Well logs and conditioning** (Properties > *Well logs & kriging*).
- Load LAS 2.0 files (one per well, `WRAP = NO`, MD in the project depth unit from KB). MD is converted to XYZ with the cumulative length of the well path (minimum curvature for survey wells).
- *Block* a curve into the grid: arithmetic, harmonic or geometric mean per cell (continuous) or the most frequent value (discrete); cells without data are NaN and the result is stored as a property with source "blocked wells". Rotated and tilted grids are handled.
- Experimental horizontal (same layer) and vertical (same column) variograms of the blocked data with a brute-force fit of range and nugget; one button copies the fitted ranges into the stochastic setup.
- *Simple kriging* in the normal-score domain per zone (nearest-neighbour search, batched solves). Stochastic workflow step 4 *Condition to wells*: the Gaussian field is conditioned by kriging and the data are honoured exactly in their cells. Permeability derived from porosity is not conditioned directly.

**Facies modelling** (Properties > *Facies modelling*).
- *Truncated Gaussian*: ordered facies (table order = spatial neighbourhood), proportions per zone with an optional vertical trend from top to base, variogram per zone, conditioning to a blocked discrete facies log (kriging of the Gaussian field, data honoured exactly), "use well proportions" shortcut.
- *Volume-weighted proportions* (truncated Gaussian and plurigaussian, on by default): the Gaussian scores are ranked by cell bulk volume, so the proportions hold by volume rather than by cell count.
- *Plurigaussian*: two independent Gaussian fields (own variogram each) and an editable rectangular truncation rule (rows = bands of G1, columns = bands of G2, cells = facies codes); band widths are solved from the proportions, and a rule that cannot reproduce them is reported. Not conditioned to wells, no vertical trend.
- *Indicator (SIS)*: sequential indicator simulation on the active cells with a random path, simple indicator kriging from data and previously simulated cells (one variogram per zone for all facies, order relations corrected), vertical proportion trend and well conditioning; cells are visited in growing batches for speed (cells of a batch do not see each other).
- *Objects*: ellipsoidal bodies (length, width, thickness, azimuth with scatter) of the object facies in a background facies until the zone's target volume fraction is reached; not conditioned to wells.
- QC: proportions by zone, vertical proportion curves, layer map. `FACIES` is stored as a discrete property with a legend (usable in Analysis splits and volumetrics regions).
- *Petrophysics per facies*: PORO (mean/sd), log10 PERM (mean/sd), PORO-PERM correlation and NTG per facies, with spatial continuity from the zone variograms; creates PORO, PERMX/Y/Z and NTG (source "facies").

**Volumetrics by region.** Contacts can be set per fault block, per zone, per segment or per any discrete property, plus a tilted contact plane and a second contact set (FWL below the OWC for the saturation-height model); a volume table by any region set is added; structural uncertainty (smooth random field on the contacts, sigma and range) feeds the Monte Carlo.

**Fault transmissibility.** Faults page: fault cell faces are found from the block pattern and assigned to the fault trace they cross; MULTFLT multipliers per fault, a juxtaposition table (zone against zone contact area) and `FAULTS` + `MULTFLT` written in the GRDECL (export option).

**Inclined pillars** (3D grid page > *Fault geometry*). Pillars near each fault are sheared by cot(dip) towards the hanging wall, faded to vertical at a radius (cells), and every horizon is evaluated where its own tilted pillar crosses it. The shear is reduced automatically where cells would otherwise invert. This is a partial implementation of key-pillar gridding: the fault surface is approximated by cell faces, not honoured exactly. COORD in GRDECL / EGRID, VTK, RESQML, blocking and the 3D view follow the tilted pillars; sections and 2D map views are drawn at the reference depth.

**Upscaling** (page *Upscaling*). Coarse corner-point grid (merged I / J columns with forced cuts at fault-block changes, merged layers per zone), PORO / NTG volume averages, pore-volume weighted saturations, majority for discrete properties, permeability by arithmetic, harmonic, geometric, power-law or flow-based averaging (single-phase steady state with closed lateral boundaries; geometric fallback where clipped cells give no connected path). QC table fine vs coarse, and coarse GRDECL / EGRID / INIT export (no FAULTS keywords).

## Units and coordinate system (v3)
The Project page holds the CRS (EPSG; name), the **XY unit** and the **depth unit** (m, ft, US ft, km) and the vertical datum. The whole project is stored in those units.
* **Import** (surfaces, XYZ, well tops, wells, polygons) has a *File units and depth convention* selector: XY unit, Z unit, and depth vs elevation (z up is flipped).
* **Changing units** either *converts* every stored length (lattice, surfaces, raw maps, faults, wells, tops, polygons, digitized data, workflow parameters, zone dz, grid cell sizes,
  filter limits) or just *relabels* when the numbers were already in the new units.
* **Reprojection** moves the project to another EPSG (surfaces are resampled on a new unrotated lattice; the workflow has to be re-run). With **pyproj** installed any EPSG
  works; without it a built-in exact transverse-Mercator handles WGS84 / ETRS89 UTM zones (datum differences below about 1 m are ignored) and ED50 etc. are refused.
* **Export** converts: the simulator grid to METRIC (m) or FIELD (ft) with a matching `GRIDUNIT` and deck keyword; surfaces, fault traces and tops to any unit. IRAP / ESRI
  files do not carry a CRS - record it in the file name or hand-over note.

## Modelling conventions
* Depth positive downward (project depth unit; metres by default); regular-grid surfaces; the model lattice is unrotated (rotated IRAP maps are resampled).
* By default the structural workflow fills undefined nodes by nearest neighbour (selectable per step, see above), so clipping or filtering a surface does **not** leave holes in the model; use the
  **model boundary** polygon to cut the model: it trims the grid extent and sets ACTNUM = 0 outside it.
* Wells: TVDSS positive down, head depth = -KB; tops are placed on the path where it reaches the pick depth (for deviated wells that is not the (X, Y) in the tops table).
* Fault displacement = `sgn * 0.5 * T(strike) * exp(-|s|/drag)`; vertical separation only, **no heave gap**. Calibration residuals are computed against the faulted model and
  interpolated on the unfaulted base.
* Corner-point faults are **stair-stepped** on vertical pillars: a concept-modelling grid, not a pillar-gridding product (no inclined / listric pillars, no Y-faults).
* RESQML / RESCUE are **not** written. GRDECL imports directly into Petrel and RMS; ROFF/EGRID via xtgeo.

## Tests
```bash
python tests/test_core.py        # engine incl. gridding / extension algorithms, units + CRS, polygons, filters, wells, boundary -> grid (449 checks)
python tests/test_ui.py          # every page through a stub Streamlit, filters, wells, tree navigation (258 checks)
python tests/browser_test.py     # map editor (digitizer, faults, polygons) in headless Chrome (40 checks)
python tests/browser_viewer.py   # WebGL viewer in headless Chrome with software GL (26 checks)
```
Not verifiable in the build sandbox: real Streamlit rendering, real Plotly.js rendering, xtgeo I/O, and WebGL on a GPU (the viewer was exercised with SwiftShader software GL).
