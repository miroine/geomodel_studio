# Detailed feature reference

> Preserved detailed feature and modelling notes from the previous README. For current page names and guided procedures, use the [documentation index](README.md) and numbered guides; current navigation vocabulary is authoritative.

---
# GeoModel Studio

**Volumetrics > Results** includes a full-width **In-place fluids - ternary 3D** view: oil is green, free gas red and water blue.
Cell colours blend by reservoir-condition pore-volume fractions, including saturation and partial contact intersections.
Water includes connate water and water below OWC; solution gas stays in the oil phase. Standard-condition STOIIP/GIIP are not mixed into the colour weights.
Only included reservoir zones are displayed; grey denotes zero net pore volume after rock/saturation cut-offs.
Use I/J cuts, zone/layer filters and optional cell edges to inspect the interior; expand the triangular colour key to read mixtures.
Existing volume reports and totals are unchanged.

**Zones & 3D grid** combines layering and grid construction in one full-width workflow.
Use the **Zones & layering** and **Grid settings** panels, then click **Build / update 3D grid** at the top.
The panels start open for an unbuilt grid and collapse after building to give the results more room.
The full-width results below contain the 3D cut-away, zone/layer view filters, sections and grid checks.
Zone edits invalidate the grid; grid-definition changes take effect on the next build. Invalid zone tables block building.
Existing Zones and 3D grid navigation targets open the combined workflow, with both object-tree nodes retained.

Each structural workflow task has an **Active** checkbox. Deactivate it to skip execution without deleting its settings; reactivate it to include it again.
Inactive zone tasks skip all their internal operations and zone definitions; inactive fault tasks contribute no faults to the framework.
Changing activation invalidates the built structure/grid. Downstream active tasks still need their input horizons: deactivate dependants too if a producer is skipped.
The run log lists skipped tasks using their original step numbers. Existing projects without activation flags keep all tasks active, and activation is saved with the project.

### Property depth and map trends
**Depth and map trends** is available in standalone stochastic and domain-parameter petrophysics modelling and in their saved property jobs.
Configure PORO, PERM and NTG independently. Depth curves contain **depth / additive offset** pairs (depth positive down in project Z units;
PORO/NTG offsets in fractions, PERM offsets in mD). Linear interpolation is used between depths; endpoint offsets apply outside the curve.
Depths must be unique and all entries finite. A zero-offset curve leaves the base model unchanged.

Select a surface from the library for a lateral trend: **offset = strength × (map value − reference)**.
Maps are sampled at cell-column centres in world XY coordinates; their stored values are used directly, without interpreting them as depth.
Import property-valued XYZ/grid maps through the surface library, choosing units and depth sign to preserve the intended values.
The map must cover every active column, with no undefined samples; extend it first if needed.
Depth and map offsets add together. Domain-parameter trends modify the base assignment; stochastic trends modify the random field's property values
before histogram bounds and net cut-offs. They intentionally alter the target histogram and achieved correlations.
PORO/NTG are limited to [0, 1] and trended permeability is non-negative. PERM trends apply to PERMX; PERMY/PERMZ follow the configured ratios.
Blocked-well conditioning subtracts the local offset before conditioning the residual field, then restores the exact well values.
Trend configuration is saved with the project/jobs; disabled trends preserve previous modelling behaviour. Maps remain live references to the library.

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

The first imported regular-grid surface automatically sets the model area using its converted coordinates and spacing.
An existing model area stays unchanged unless **Replace existing model area with this surface on import** is checked.
Alternatively, on **Project** select a library surface under **Surface for model area** and click **Load area from surface**. Review the coordinates and spacing and
click **Set model area**. The full grid-node extent is used, including undefined nodes; rotated surfaces use a north-up
bounding rectangle with spacing adjusted to cover it exactly. The 400,000-node limit still applies, so increase spacing if
needed. XYZ points require an existing model area to be gridded. Surface coordinates are in project XY units after import;
surface files do not establish the project CRS, which must be set separately.

In **Digitize a map**, enter each contour's depth or set a nonzero **Depth step** to increment it after finishing each line (negative steps are supported).
Select a contour in **Contents** to correct its depth, then **Send to Python** again. Equal depths produce a constant map and trigger a warning.
**Show model boundary** overlays the project's boundary polygon on the digitizer (calibrate scanned images first); the gridded map has a separate boundary toggle.

## Navigation
The sidebar is grouped by the modeling workflow: **Workspace**, **Build**, **Model**, and **Review & deliver**. Expand a stage to open its pages.
The sidebar's **Model** pane has connected, numbered boxes: **Horizon & fault framework -> Zones & layering ->
Build the 3D grid -> Populate the reservoir**. Each box explains its input/output and shows readiness.
Existing page links and object selections remain available inside each box. The property stage shows
**Facies -> petrophysics -> water saturation -> QC**, followed by review, volumetrics and export.
When a page has project objects, their names appear beneath it; select one to open that object directly. The symbol beside an object indicates whether it is ready, missing, or stale.

## What each page does
| Page | Capabilities |
|---|---|
| Project | model lattice, demo, save / open `.gmsz` (keeps raw maps, filter stacks with undo history, presets, polygons, wells) |
| Surfaces | import ESRI/Surfer ASCII, **IRAP/RMS ASCII + binary (xtgeo)**, XYZ points; gridding (min-curvature, RBF, IDW, linear); **digitize a scanned map**; synthetic surfaces; duplicate with scalar depth offset or multiplier; rename/delete unused maps (workflow source maps must be detached first); **Filter & clip** (below) |
| Polygons | **digitize** (JS editor, drag / insert / delete vertices) or **import** (XY text, GeoJSON, RMS `.POL` / `.rmspolygons`); export XY; pick the **model boundary**; clip surfaces to a polygon |
| Faults | draw traces or import RMS `.POL` / `.rmspolygons` and XY text; normal / reverse, throw, dip, hanging-wall side, along-strike profile, drag zone, growth; faulted preview |
| Wells | head table, **deviation surveys (minimum curvature)**, XYZ paths, import with templates, build / hold generator, create from tops, 3D preview |
| Well tops | CSV import, editable table, map, misfit QC |
| Structural model | ordered workflow: surface, isochore, **calibrate to tops**, smooth, faults; roles conformable / erosional / base-lap |
| Zones & layering | proportional, follow top, follow base, fractions; zone properties |
| 3D grid | vertical-pillar corner-point grid, stair-stepped faults, **cells outside the boundary polygon inactive**, WebGL cut-away + sections + checks |
| Properties | property library, facies simulation, petrophysics by zone/facies, saturation-height and Archie water saturation, 3D/layer QC, stochastic models, well conditioning and calculator |
| 3D window | surfaces, structural-model horizons, fault planes, polygons, wells, tops, grid coloured by Zone / Layer / Block / Depth / Thickness / PORO / PERMX / NTG |
| Export | **GRDECL**, **VTK**, **ROFF / EGRID / bGRDECL via xtgeo**, surfaces, fault traces, tops, project |

### Structural workflow flowchart
The Structural model configuration uses a connected, top-to-bottom flowchart. Numbered task cards show the
task type, **IN** data, **OUT** result and a named **Configure task** panel. Colors distinguish horizon
construction, fault framework, well conditioning, horizon refinement, and zones/layering; they do not
represent completion status.

Use **Move up**, **Move down**, or **Delete task** on a card. Configure its parameters and press **Update step**
to apply edits. The separate **Add a task** panel appends new tasks; **Apply faults** replaces the fault-selection
task and places it first. Define horizons before tasks that reference them.
**Apply faults** selects faults globally for the framework and calibration, rather than only for the next card.
The arrows show task order, not a branching dependency graph.

Press **Run workflow** in **Build & validate**, then inspect the existing 3D, maps, cross-section and zone QC.
Applying task edits, additions, deletion or reordering invalidates the framework and grid, so rerun and rebuild
before using the updated model. The flowchart preserves existing workflow files and numerical behavior.

### Property modelling workflow
Properties are organized into **Workflow**, **Property library**, **Facies**, **Petrophysics**, **Water saturation**, and **QC & tools**.
The **Workflow** tab is an executable, ordered job flowchart, using the same modelling engines as the individual tools:
**Facies model -> Python calculator -> Petrophysics -> Water saturation**, or any order appropriate to the input dependencies.
Use **Insert job** and its position selector to insert a calculator between two jobs; **Move up / Move down** reorders jobs.
Untick **Active** to skip a job entirely, including its configuration validation. Downstream active jobs must still have
their required inputs, either from an earlier active job or from existing current properties.

Each job has a named **Configure job** panel and its own saved configuration snapshot. **Save job configuration**
applies edits; the individual Facies/Petrophysics tools are retained and do not modify saved jobs automatically.
In **Facies**, use **Facies modelling job** to choose a named workflow job and edit its actual saved configuration,
or select **Standalone facies settings** for the independent tool. Multiple facies jobs keep separate configurations;
new jobs receive unique names and facies output names. Saved edits refresh both the flowchart and named-job editor.
Use descriptive job names and choose the corresponding facies output as the input to downstream petrophysics jobs.
The same named-job selection is available in **Petrophysics -> Domain assignments**, **Stochastic by zone / facies**,
**Water saturation**, and **QC & tools -> Calculator**. Each selector shows only that tool's saved workflow jobs.
Configure and save the selected job there, run it alone with **Run this job**, or execute its saved settings in the ordered
workflow. Selecting standalone settings preserves the independent tools; it does not copy or overwrite a named job.
Calculator jobs use the existing restricted array calculator, not arbitrary Python: for example
`FACIES = where(FACIES == 2, 3, FACIES)` before a zone/facies petrophysics job.
Set the calculator result type to **discrete** for facies, and configure parameter rows for any newly created codes.
Rows for declared but absent facies are skipped at execution; missing rows for actual active codes produce an error.
Geometry variables remain read-only, and stale calculator inputs are rejected.

**Run property workflow** executes all active jobs. Approve replacing existing outputs when needed.
Every card also has **Run this job**: it runs only that saved job using current stored properties, without running
upstream jobs. An explicit standalone run works even when **Active** is unticked; Active only controls workflow inclusion.
Approve standalone output replacement separately. Missing/stale inputs fail explicitly and leave existing outputs unchanged.
Outputs are committed only if every active job succeeds; errors identify the failing job and leave existing properties
unchanged. The run table distinguishes **Completed** and **Skipped** jobs. Editing or disabling jobs does not remove
previously stored properties; rerun to update those snapshots. Jobs, activation, order, parameter tables and scripts
are saved in `.gmsz`; older projects start with an empty job list. Physical job ranges/contact depths convert with
project units; numeric constants inside calculator scripts must be reviewed manually after a unit change.

**Property run history** in the Workflow tab records executed jobs and supported standalone property operations,
with UTC timestamps, status, outputs, configuration, grid fingerprint and project CRS/units at the time.
Failed jobs and workflow outputs rolled back after a later failure are identified. History is saved in `.gmsz`,
is not a replayable job list, and does not retrospectively identify properties created before this feature. Later
runs may overwrite an output; the most recent completed record for that output describes its last recorded run.
The same restricted Python calculator is also available directly in **Property library**.

### Facies probability trends
Standalone and named facies jobs support optional per-facies offsets for **truncated Gaussian** and **indicator**
simulation. An absolute-depth curve interpolates probability offsets by cell-centre depth; a map trend adds
`strength × (surface value − reference)`; and a surface-distance curve interpolates offsets against cell-centre
depth minus the selected depth surface (positive below it). Curve endpoints are held constant beyond the entered range.
Offsets add to the existing zone/top-to-base probabilities, are clipped at zero, and are normalized across facies
at each cell. All-zero probability vectors are rejected. Surfaces must cover every active column, and curves need
at least two finite pairs with unique coordinates. Enabled trends are rejected for plurigaussian and object models.
Conditioning data remain honoured. Trends alter local probabilities and therefore achieved global proportions;
they are not constraints on the final histogram. Depth and distance coordinates convert with project depth units.

The sidebar uses colored object-family borders, green created/current objects and orange stale objects. Cell properties
are in the **3D properties** dropdown instead of a long list of buttons; selecting one opens its property viewer.

### Display colours and cell investigation
Use **Edit property colours** in property QC or the Grid page, **Scene content** in the 3D window,
or **Edit fence property colours** for intersections. Choose Webviz **Physics**, **Physics reverse** or
**Colors set 3**, a shallow-red/deep-blue depth ramp, or Viridis. Edit individual colour stops and,
for categorical properties, individual facies/code colours; press **Save colours**. **Reset to automatic colours**
restores the property-specific defaults. Settings are saved with the project, survive rerunning a same-named
modelling job, and are shared by grid/fence displays, layer maps, analysis sections and average maps.
Permeability colours remain log10-scaled; hover and inspection retain raw values.

**Value range (min / max):** in the same colour editor (and in **Surface depth colours** on the Surfaces
library and structural-model maps), tick **Custom min / max range**, enter the minimum and maximum in data
units (project depth unit for surfaces, Depth and Thickness; mD for permeability), and press **Save colours**.
The automatic range is shown for reference. Values outside the limits use the end colours; the data itself is
not changed. The range applies to 3D views, layer and depth maps, fences and sections, is saved with the
project, and is rescaled when the project depth unit changes. Untick the option or use **Reset to automatic
colours** to return to the automatic range.

**Grid opacity** controls transparency in Grid, Properties QC, the main 3D window, and the surrounding grid
of a fence scene. Lower values reveal well context behind the outer grid skin; transparency does not create
interior cell faces. Use cut-away/layer filters or a fence to expose interior cells. The viewer's object-tree
opacity slider remains available, and explicit Python opacity changes apply to an already-open viewer.

Click a grid face or fence ribbon to open **Other properties at selected cell**. Select which properties to compare
at the same original global I/J/K. The table includes raw values, units, categorical labels, and explicit
undefined/stale status rather than showing incompatible snapshots as current values.

Surface maps now default to depth colours (red shallow, blue deep), matching the 3D depth convention.
In **Surfaces -> Library -> Map**, choose a map surface, toggle **Show depth contours**, set the contour interval
in project depth units (0 = automatic), and optionally label contours. **Show well trajectories** overlays
plan-projected deviated/vertical well paths and labelled wellheads; hover shows trajectory depth, not a calculated
surface crossing. Surface depth palettes are editable and saved under **Edit surface depth colours**.
These map controls are also available for structural-model depth results. Rotated input maps are resampled
for display onto a bounded north-up lattice so contours and world-coordinate well paths align; source data are unchanged.

### Polygon property assignment
Import or draw a closed polygon on **Polygons**, then build the 3D grid. In **Properties -> Property library**,
open **Assign property using a polygon**, select the polygon and enter a property name. Choose **Inside only**,
**Outside only**, or **Inside and outside**, enter the values, and apply. One-sided edits require an existing,
current property and preserve its other values; two-sided assignments can also create a property. Existing property
type, unit and discrete legend are preserved; discrete values must be integers. Confirm replacement when editing.

The test uses each grid column's XY centre; points on the polygon edge are inside, and assignment applies to active
cells in every layer. Inactive existing values remain unchanged; new properties leave inactive cells undefined.
This is not fractional coverage of cells intersecting the boundary. All active output values must be finite.

For repeatable modelling, insert a **Polygon property assignment** job in **Properties -> Workflow**, save its
configuration and run it after any jobs that create its input property. It uses the current project polygon and
the current output of preceding jobs; missing polygons or stale input properties cause an explicit failure and
the workflow commits no outputs. Polygon assignments produce snapshots: rerun after polygon or grid changes.
For a one-sided assignment after a grid change, first rebuild its original input property (or run the upstream
workflow job that produces it); stale properties cannot be used as input.
The job and output persist with the project; property values use the specified property unit, not an automatic
coordinate-unit conversion.

### Fluvial channel objects
Choose the **objects** facies method in a named job or the standalone Facies tool. The object table supports
**ellipsoid**, **channel**, and **digitized_channel** shapes, mixed in the same model.
For parametric **channel** objects, configure centerline length, width, thickness, azimuth, meander amplitude and wavelength.
Azimuth is measured from north; amplitude is lateral displacement, not a sinuosity ratio. Zero amplitude gives a straight channel.
For **digitized_channel**, draw one open XY centerline per object row in the embedded map, finish with Enter and press
**Apply**, then **Save job configuration**. Add another object row for another path. The path stays fixed in world coordinates,
including on rotated grids; length, azimuth, amplitude and wavelength are unused for that shape.

Channels have a rounded cross-section and are placed at random depths within each zone, clipped to active cells.
Width/thickness vary per realization; generated channels also vary in length, position, orientation and meander phase.
Zone proportions are approximate bulk-volume targets for the object facies, not exact channel counts. Later bodies can overwrite
earlier ones. If channel placement cannot reach its target within the attempt limit, an explicit error suggests reducing the
target or increasing coverage. Features smaller than the cell spacing may not be resolved. Channel models are not well-conditioned
and do not include levees, avulsion or erosion simulation. Parameters and digitized paths persist in `.gmsz` and convert with project units.

### Water-saturation contacts
Saturation-height jobs and the standalone Water saturation tool allow **WOC / OWC** (water/oil contact),
optional **GOC** (gas/oil contact), **FWL below OWC** (a finite, non-negative depth offset), fault-block overrides,
zone/discrete-region overrides and tilted contacts.
Depth is positive down: GOC must be shallower than OWC. Blank override values inherit the global or block setting.
Named jobs keep their own contact snapshots; standalone contacts are shared with Volumetrics.

For either contact, select **3D property** as its source and specify an existing continuous contact-depth property,
or an output of an earlier calculator job. Contact properties must fit the grid, be current and finite in active cells;
their values override configured contacts and tilt. A blank unit means the project depth unit; specified length units
are converted when used. Scenario contact shifts remain supported. The same contact inputs are honoured by Volumetrics
and fluid classification; missing or invalid contact properties produce explicit errors.

Enable **Separate gas-zone saturation-height parameters** to set `gas_swirr`, `gas_entry` and `gas_lam` by the selected
zone/facies domains. These parameters apply only above GOC, using height above the same water FWL; the normal curve
applies in the oil leg. Below FWL, water saturation is 1. This is a configurable empirical water-saturation curve,
not a gas/oil capillary-pressure or three-phase saturation solver. Archie remains resistivity-based and does not use contacts.

### Property fence intersections and average maps
Open **Properties -> QC & tools -> 3D & maps -> Fence intersections** to draw/edit shared project fences and select
up to three properties for stacked cross-sections. Filter zones/layers, overlay project contacts or a named saturation
job's contacts, and download the intersected cell values with their original I/J/K and along-fence distances as CSV.
The **Fence intersection in 3D** panel renders a property-colored curtain with optional black edges and surrounding
grid context. Click a ribbon to inspect its raw property value and original I/J/K.
Column crossings are exact in the grid's plan-view frame, including rotated/refined grids; ribbon top/base depths are
column-corner averages, not exact intersections through tilted pillars. Structural fences and saved projects reuse the same paths.

In **Average maps**, select one or several current continuous properties, zones and a layer interval. Choose
**Arithmetic**, **Thickness-weighted**, or **Bulk-volume-weighted** averages of finite active cells in each column.
No implicit NTG multiplier is applied. Empty columns stay undefined; discrete facies codes are not averaged.
Maps display in I/J space and download as CSV with world X/Y coordinates, values and contributing cell counts.
These are derived results, not new 3D property snapshots. The multi-parameter map controls are also available in
**Analysis & sections -> Maps -> Generate average maps for multiple parameters**.

### Property colors and cell inspection
The 3D grid uses color tables from
[Webviz subsurface](https://github.com/equinor/webviz-subsurface/blob/master/webviz_subsurface/plugins/_well_log_viewer/utils/default_color_tables.py):
**Physics** for SW/SWAT, Depth and Layer; **Physics reverse** for other continuous properties; and
**Colors_set_3** for Zone, Fault block and discrete properties. Categorical colors cycle after 10 colors;
user discrete properties with more than 24 codes use a continuous ramp. Undefined values are gray.
User continuous properties use active-cell 1st/99th-percentile display limits. Permeability colors use a
logarithmic scale; inspection still shows the original value.

Enable **Black mesh edges** in the 3D grid/window controls or **Properties -> QC & tools -> 3D & maps ->
3D display filters and well context**. This draws black cell outlines without replacing property colors.
Click a visible grid face without dragging to inspect its global, 1-based **I/J/K**, selected property value
and unit in the viewer overlay and caption below it. Cut-away and layer/zone filters preserve original cell
indices; expose an interior cell with these controls before selecting it. Invalid or stale selections are rejected.

All results are ordinary grid properties: they can be viewed in the 3D window, used by the calculator and volumetrics,
and included in simulator exports. Object-tree selection opens the selected property in the property viewer.

1. Build the grid and optionally create/import a discrete **FACIES** property.
2. In **Petrophysics > Domain assignments**, choose **By zone**, **By facies**, or **By zone and facies**.
   Enter porosity and NTG as fractions, horizontal permeability in mD, and PERMY/PERMX and PERMZ/PERMX ratios.
   The table assigns **constant values within each active domain**; select which outputs to store and confirm replacements.
   Use **Stochastic by zone / facies** or the existing **Facies > Petrophysics per facies** simulation step for spatially varying
   distributions and variogram-based continuity. Parameter-table assignments do not modify the grid zone-definition table.
   In **Stochastic by zone / facies**, choose **By zone and facies** and select a current discrete facies property.
   PORO, PERM and NTG each have separate histogram parameters and variograms for every active zone/facies combination.
   Initial normal PORO/NTG and lognormal PERM parameters use the facies petrophysics table when available; otherwise zone settings
   are copied as editable starting values. Set these rows to the required facies distributions before running.
   Facies membership comes from the selected property, not from zone labels. Histogram ranking, assignment,
   blocked-well conditioning and facies-filtered QC respect that membership; inactive outputs are undefined.
   Domains are simulated independently with reproducible seeds. Distribution type, cross-correlations, poroperm
   transform and cut-offs remain workflow-wide; vertical permeability ratios remain zone-based.
   Facies-domain tables and the selected source are saved in the project; switching back to **By zone** retains
   the original zone tables and legacy numerical behavior. Missing, stale or undefined active facies are rejected.
3. In **Water saturation**, choose a method and the same zone/facies domain options:
   - **Saturation-height:** `Sw = Swirr + (1 - Swirr) * (entry / max(height, entry))^lambda`.
     Height is above the free-water level at the cell centre; `Sw = 1` below the FWL.
     OWC and FWL-below-OWC are shared with Volumetrics, including its fault-block/region contact overrides and tilt.
     Entry height and contact depths use the **project depth unit**; entry-height settings convert with project units.
   - **Archie:** `Sw = (a * Rw / (PORO^m * Rt))^(1/n)`, clipped to `[0, 1]`.
     Select separate porosity (fraction) and formation-resistivity **Rt** (ohm.m) properties; enter `a`, `m`, `n`, and **Rw**
     (ohm.m) per domain. Resistivity can be imported/conditioned through the well-log tools or created with the calculator.
     Archie assumes a clean formation, not a shaly-sand model; calibrate these parameters to well and laboratory data.
4. Store **SW**, inspect **QC & tools > 3D & maps** (zone/layer filters, wells/tops and layer histograms), then select
   **Use SW in volumetrics** or include SW in grid exports.

Parameter tables and generated properties are saved in `.gmsz` projects, including older-project compatibility.
Models reject missing/stale inputs, undefined active-cell values, incomplete domain tables and invalid parameters.
Inactive cells remain undefined. Stored results are **snapshots**: rerun models after changing inputs, contacts or
parameters, and rebuild properties flagged stale after geometry changes. These workflows support concept modelling;
they do not reproduce every Petrel property-modelling process.

### Save surfaces
After **Add to library**, **Grid points into a surface**, **Grid digitized data**, or **Create surface**, use
**Save surface file** in the same tab. Choose **IRAP binary**, **IRAP ASCII**, or **XYZ points**.
The download stays available across reruns, including when you change the file format.
**Library & QC > Surface to save** can download any library surface, including duplicates and filtered maps.
Surface downloads use the current project XY/depth units (depth positive down); these formats do not preserve the project CRS.
XYZ exports only defined nodes; IRAP preserves the regular-grid geometry and undefined nodes.
The built-in IRAP ASCII/binary reader and writer use standard X-fastest node order. If an IRAP surface was imported
using an older built-in reader, reimport the original file and rerun dependent modelling steps; saved projects retain
their previously imported values. IRAP files exported by the older built-in writer may also have scrambled ordering
in other applications; re-export them from the original surface using the corrected version.

Use **Prepare complete project download**, then **Save complete project (.gmsz)** in the library to keep all surfaces, raw maps, filter history, digitized contours,
and project settings together. Surface files save the current map only, not its editable filter history.
Downloads are explicit browser saves, not automatic disk persistence; save a file or project before ending your session.

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

Faulted horizons in the Faults preview, structural results and 3D window are split at fault crossings:
triangles no longer bridge the depth jump into a continuous ramp. Cuts use the unfaulted horizon depth
to locate dipping faults and the applied throw/slip profile (including growth and tapered tips).
Hiding fault planes does not reconnect the horizon. Library surfaces and the **Unfaulted** preview
remain continuous. The visible gap follows the display mesh resolution, including downsampling;
it is not extra throw or a physical heave gap, and does not alter saved surfaces or grid exports.
For physical horizontal separation, use the fault's **heave** parameter. After editing faults, rerun
the structural workflow and rebuild the grid to update the modeled results.
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

**Planes & regions** (Properties > QC & tools > Planes & regions).
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

**Well logs and conditioning** (Properties > QC & tools > *Well logs & kriging*).
- Load LAS 2.0 files (one per well, `WRAP = NO`, MD in the project depth unit from KB). MD is converted to XYZ with the cumulative length of the well path (minimum curvature for survey wells).
- *Block* a curve into the grid: arithmetic, harmonic or geometric mean per cell (continuous) or the most frequent value (discrete); cells without data are NaN and the result is stored as a property with source "blocked wells". Rotated and tilted grids are handled.
- Experimental horizontal (same layer) and vertical (same column) variograms of the blocked data with a brute-force fit of range and nugget; one button copies the fitted ranges into the stochastic setup.
- *Simple kriging* in the normal-score domain per zone (nearest-neighbour search, batched solves). Stochastic workflow step 4 *Condition to wells*: the Gaussian field is conditioned by kriging and the data are honoured exactly in their cells. Permeability derived from porosity is not conditioned directly.

**Facies modelling** (Properties > *Facies*).
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
  Import RMS ASCII `.POL` or `.rmspolygons` on the **Polygons** page: each X Y Z part is separated by
  `999 999 999`; Z is ignored and XY is converted to project units. Import does not clip or replace surfaces.
  Remove and reimport polygons previously loaded with separator records as vertices.
  On **Faults > Import fault traces from polygon files**, the same RMS formats and XY text become separate
  fault traces (at least two distinct vertices). File Z is ignored; set reference depth, throw, dip, hanging-wall
  side, profile and drag width in project units. Vertex order defines left/right. Imports add uniquely named
  faults without replacing existing objects, enable them in the structural workflow, and invalidate derived
  structure/grid results. Rerun the structural workflow and rebuild the grid after import.
* **Changing units** either *converts* every stored length (lattice, surfaces, raw maps, faults, wells, tops, polygons, digitized data, workflow parameters, zone dz, grid cell sizes,
  filter limits) or just *relabels* when the numbers were already in the new units.
* **Reprojection** moves the project to another EPSG (surfaces are resampled on a new unrotated lattice; the workflow has to be re-run). With **pyproj** installed any EPSG
  works; without it a built-in exact transverse-Mercator handles WGS84 / ETRS89 UTM zones (datum differences below about 1 m are ignored) and ED50 etc. are refused.
* **Export** converts: the simulator grid to METRIC (m) or FIELD (ft) with a matching `GRIDUNIT` and deck keyword; surfaces, fault traces and tops to any unit. IRAP / ESRI
  files do not carry a CRS - record it in the file name or hand-over note.

## Modelling conventions
* Successful standalone property runs are automatically appended as **active steps** in **Properties > Workflow**,
  in run order, with saved parameter snapshots. Edit, reorder, disable, rerun one step, or rerun the full workflow
  (confirm output replacement first). Rerunning workflow steps adds audit history without duplicating steps;
  failed/rolled-back runs do not become active steps. Existing history can be added using
  **Add previous successful runs to workflow**; history in different CRS/units must first be restored in its original
  coordinate system. Library tools use an editable JSON configuration. Inputs such as surfaces, polygons,
  wells/logs and upstream properties are resolved from the current project; missing inputs cause an explicit failure.
  Save the `.gmsz` project to preserve both executable steps and audit history.
* **Fluid system** in water-saturation contacts and Volumetrics offers **Gas only**, **Undersaturated oil**,
  and **Oil with gas cap**. Gas-only interprets the water-contact depth (including block/region overrides,
  tilt and contact-depth properties) as GWC and assigns all hydrocarbon volume to gas. Undersaturated oil
  has no free-gas volume, but can retain solution gas through Rs. Both ignore GOC settings. Oil with gas cap
  requires GOC in every active cell. FWL offset is below the water contact; gas-only uses the base gas-water
  saturation-height parameters. Separate gas parameters apply only to gas-cap/legacy models. Archie itself
  is unchanged. Standalone saturation shares contacts with Volumetrics; saved jobs retain their own snapshot.
  Existing projects default to **From contacts (legacy)**. Rerun saturation and volume calculations after changes.
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
