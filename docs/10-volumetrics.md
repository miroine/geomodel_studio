# Volumetrics
> Location: **Volumetrics › Volumetrics** · Previous:
>   [Properties](09-property-modelling.md)
>   · Next: [3D window and display](11-3d-window-and-display.md)

## Purpose
Calculate in-place volumes above configured contacts and review scenario
sensitivity, regional
reports and stored cell outputs.

## Before you start (inputs / prerequisites)
- Build a current grid with zones and fault blocks as required.
- Set or generate porosity, NTG and water-saturation inputs; confirm units
  and contact
  interpretation.

## Step-by-step
1. Open **Volumetrics › Volumetrics**, then **Setup**. Select the fluid
   system and
   configure global water contact (OWC/WOC or GWC) and optional gas-oil
   contact (GOC).
2. Select sources for porosity, NTG and Sw. Choose a stored property or
   supported
   zone-based setting; configure net cut-offs and formation-volume
   factors (Bo/Bg) and
   solution gas (Rs) as required.
3. Add optional contacts by fault block/region, contact-depth properties,
   tilt and FWL
   below OWC. For gas-only, the water contact is labelled/interpreted as
   GWC. Gas-only and
   undersaturated oil ignore separate GOC; oil with gas cap requires a
   valid GOC.
4. Set report grouping and compute results. Review GRV, NRV, PV, HCPV,
   STOIIP and GIIP
   totals and tables by zone/block or selected region.
5. Use **Contact scan** and **Run contact scan** to inspect STOIIP
   sensitivity. Configure
   uncertainty and use **Run tornado and Monte-Carlo** for scenario
   distributions; P90 is
   the low case.
6. Use **Realisations & store** to compute P90/P50/P10 across property
   realisations where
   available. Click **Store as properties** to persist supported
   fluid/volume outputs on
   the grid.
7. Review **In-place fluids - ternary 3D** for pore-volume-weighted oil,
   free gas and water
   distribution; use I/J cuts, filters and optional cell edges to inspect
   the interior.
8. Recalculate after changing contacts, saturation, porosity, NTG, fluid
   system or grid.
   Save the project to preserve settings and results.

## Outputs
- Volumetric summaries, regional tables, sensitivity/uncertainty results
  and optional CSV
  downloads.
- Optional cell properties such as FLUID, SW, VOL_GRV, VOL_HCPV,
  VOL_STOIIP, VOL_GIIP and
  VOL_NET.

## Quality control checklist
- [ ] Fluid system matches the geological scenario; gas-cap contacts
      are complete where
      required.
- [ ] Contact sources, units, overrides, tilt and FWL offset are checked.
- [ ] PORO, NTG, Sw and cut-offs are current and appropriate.
- [ ] Results by zone/block reconcile with totals and expected trends.
- [ ] Contact-scan and uncertainty assumptions are reviewed before
      reporting.

## Tips and common pitfalls
- Contact fractions use cell-top/base corner-depth averages; partial
  contact cells are
  apportioned linearly, not by sub-cell geometry.
- Single-fluid systems ignore GOC. Oil-with-gas-cap mode requires GOC in
  each active cell.
- Standalone saturation contacts are shared with Volumetrics; named jobs
  retain their own
  contact snapshot.
- Ternary display shows reservoir-condition pore-volume fractions; it does
  not mix
  standard-condition STOIIP/GIIP into its weights.

## Related workflows
- [Facies, petrophysics and
  saturation](workflows/03-facies-petrophysics-saturation.md) ·
  [Quick start](workflows/01-quick-start.md)
---

*GeoModel Studio — built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial 1.0.0). See [LICENSE](../LICENSE).*
