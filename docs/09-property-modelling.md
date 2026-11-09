# Property modelling
> Location: **Property modelling › Properties** · Previous: [Zones and 3D
>   grid](08-zones-and-3d-grid.md) · Next: [Volumetrics](10-volumetrics.md)

## Purpose
Create/manage grid properties through the property library, calculator,
facies, petrophysics,
saturation tools and an executable rerunnable job workflow.

## Before you start (inputs / prerequisites)
- Build a current grid and verify its zone table and active cells.
- Import needed facies/log/surface inputs and choose property units; PORO
  and NTG are
  fractions, permeability is mD.

## Step-by-step
1. Open **Property modelling › Properties**. Use **Property library** to
   inspect values or
   create constants/calculated properties. The **Python calculator** is a
   restricted
   array-expression tool, not arbitrary Python.
2. For polygon assignment, open **Assign property using a polygon**,
   select **Assignment
   polygon**, choose **Assign values** (inside/outside modes), set
   values/type, confirm
   replacement if shown, then click **Apply polygon assignment**. It
   assigns by
   column-centre inclusion to active cells.
3. Use **Facies** for supported truncated Gaussian, plurigaussian,
   indicator or object
   modelling. Configure proportions, method, variograms, conditioning,
   trends and
   reproducible seed; store the discrete facies result and inspect QC.
4. In **Petrophysics**, **Domain assignments** defines constant PORO,
   PERM and NTG by
   zone/facies domain. **Stochastic by zone / facies** generates
   spatially varying
   distributions, histograms, variograms, correlations, cut-offs and
   optional well
   conditioning.
5. In **Water saturation**, select saturation-height or Archie, choose a
   **Fluid system**
   (gas only, undersaturated oil, or oil with gas cap), configure
   contacts and domain
   parameters, and store the requested output. Gas-only treats the water
   contact as GWC;
   oil-with-gas-cap requires GOC.
6. Configure depth/map trends for stochastic and domain-parameter
   workflows. Facies
   probability trends support depth, map and surface-distance curves for
   supported methods;
   maps must cover active columns.
7. Use **QC & tools** for LAS blocking, variograms, **Simple kriging**,
   regions/segments,
   geometric tools and property diagnostics. The workflow engine also
   supports saved
   kriging jobs where configured.
8. In **Workflow**, create/configure named jobs; use **Insert job**,
   **Move up / Move
   down**, and **Active** to control execution order. Save settings with
   **Save job
   configuration**.
9. Run one job with **Run this job** or active jobs with **Run property
   workflow**. Resolve
   missing/stale dependencies and approve output replacement; outputs
   commit only if the
   workflow succeeds.
10. Successful standalone operations are recorded in run history. Use
    **Add previous
    successful runs to workflow** to restore supported history into
    executable jobs;
    restoration checks CRS and units.
11. Inspect results in **3D & layer maps**, **Fence intersections** or
    **Average maps**.
    Open **Edit property colours**, set **Custom min / max range** if
    desired, and click
    **Save colours**.

## Outputs
- Continuous/discrete arrays under **Models**, including FACIES, PORO,
  PERMX/Y/Z, NTG and SW
  where created.
- Saved job configurations, execution history, QC plots/tables and derived
  average maps.

## Quality control checklist
- [ ] Grid and active input properties are current, correctly typed
      and unit-labelled.
- [ ] Domain tables cover active zones/facies; active-cell inputs
      contain defined values.
- [ ] Trends/maps cover active columns; conditioning inputs map to the
      correct well and curve.
- [ ] Output names and replacements are intentional; jobs execute in
      dependency order.
- [ ] Review histograms, variograms, correlations, cut-offs and
      representative 3D/layer views.
- [ ] Recompute snapshots after grid, input, contact or parameter changes.

## Tips and common pitfalls
- Calculator scripts use a restricted array language; numeric constants
  need manual review
  after changing project units.
- Polygon assignment is by XY column centre, not fractional cell coverage.
  One-sided
  assignment requires a current input property.
- Named property jobs keep configuration separate from standalone tools;
  tool edits do not
  silently update a saved job.
- Depth/map trends intentionally change local distributions and may alter
  achieved
  histograms/correlations; map values are used directly.
- Property run history is audit data, not automatically a replay list;
  restore successful
  records explicitly when needed.

## Related workflows
- [Facies, petrophysics and
  saturation](workflows/03-facies-petrophysics-saturation.md) ·
  [Rerunnable property
  workflow](workflows/04-rerunnable-property-workflow.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
