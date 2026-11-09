# Rerunnable property workflow

**Goal:** turn successful property operations into an ordered, saved workflow that can be rerun against current project inputs.

**Prerequisites:** current grid, source properties/surfaces/polygons/well data as needed, and clear output-property naming.

## Stages
1. Review the target workflow in [Properties](../09-property-modelling.md). Decide which outputs need reproducible job settings and which are one-off exploratory analyses.
2. Add jobs in dependency order: facies before petrophysics; petrophysics before saturation; calculator or polygon assignment where its inputs exist. Use **Insert job** and position controls when needed.
3. Configure each named job in its own **Configure job** panel. Save with **Save job configuration**; standalone tool settings do not automatically replace named-job settings.
4. Use **Active** to include/exclude a step without deleting configuration. Check that each downstream job has current inputs from an earlier active job or existing stored properties.
5. Run a step with **Run this job** to test it against current properties, or run the sequence with **Run property workflow**. Approve output replacement intentionally.
6. Review completed/skipped status and outputs. A failed workflow does not commit partial outputs; fix the failing step and rerun.
7. Standalone successful operations are captured in run history. Use **Add previous successful runs to workflow** to turn supported prior runs into steps. Restoration checks CRS and units; restore history in its original coordinate setup if they differ.
8. Save the `.gmsz` project to retain job order, activation, configurations, outputs and history. After grid/input changes, check stale indicators and rerun dependent jobs.

## Decision points
- **One job or full sequence:** use one-job execution for focused diagnosis; use the full workflow to reproduce ordered dependencies.
- **Restore history:** include only successful supported runs; review names and outputs before execution.
- **Existing output:** approve replacement only when the new snapshot is intended.

## QC gates
- Job names, order and output names are unique and understandable.
- Active dependencies exist and are current.
- Workflow completes without stale/undefined-input errors and outputs are reviewed.
- Project archive is saved after configuration/history changes.

**Expected result:** an executable workflow with saved job configuration and auditable run history. Property results are snapshots; rerun after inputs or geometry change.

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../../LICENSE).*
