"""Guided parameter-table workflows for petrophysics and water saturation."""
import pandas as pd
import streamlit as st

from core import petrophysics as petro
from core import props as pp
from core import volumetrics as vol
from core import units as un
from core import property_history
from ui import state as S
from ui.theme import kpis
from views import property_workflow as job_view
from views import contact_settings
from views import property_trends

LABELS = {"zone": "By zone", "facies": "By facies", "zone_facies": "By zone and facies"}


def _domain(p, g, prefix):
    mode = st.radio("Parameter domains", petro.DOMAINS, format_func=LABELS.get,
                    horizontal=True, key=S.k(prefix + "_domain"))
    facies = ""
    if mode != "zone":
        names = [name for name, prop in p.properties.items()
                 if prop.kind == "discrete" and prop.values.shape == g.actnum.shape]
        if not names:
            st.warning("Create or import a discrete facies property first in the Facies workspace.")
            return None
        facies = st.selectbox("Facies property", names, index=names.index("FACIES") if "FACIES" in names else 0,
                             key=S.k(prefix + "_facies", names))
    try:
        rows = petro.domains(g, mode, p.properties, facies)
    except petro.PetroError as exc:
        st.error(str(exc))
        return None
    if not rows:
        st.warning("The grid has no active cells to model.")
        return None
    return mode, facies, rows


def _table(p, prefix, mode, facies, domains, defaults):
    key = f"{prefix}|{mode}|{facies}"
    cfg = p.property_models.setdefault(key, {})
    keys = ["zone"] if mode == "zone" else ["code"] if mode == "facies" else ["zone", "code"]
    saved = {tuple(row[k] for k in keys): row for row in cfg.get("rows", [])}
    rows = []
    for domain in domains:
        row = dict(domain, **defaults(domain))
        previous = saved.get(tuple(domain[k] for k in keys), {})
        row.update({k: previous[k] for k in row if k not in keys + ["label"] and k in previous})
        rows.append(row)
    signature = [tuple(domain[k] for k in keys) for domain in domains]
    edited = st.data_editor(pd.DataFrame(rows), hide_index=True, disabled=keys + ["label"],
                            key=S.k(key + "_table", signature))
    cfg.update(domain=mode, facies=facies, rows=edited.to_dict("records"))
    return cfg


def render_petrophysics(p, g):
    if job_view.named_job(p, "petrophysics"):
        return
    st.subheader("Petrophysical modelling")
    st.caption("Assign porosity, permeability and net-to-gross by zone, facies, or their intersection. "
               "This table sets domain base values; optional depth and map trends add spatial variation. Use Stochastic by zone / facies or the facies simulation "
               "petrophysics step for spatially varying distributions.")
    selected = _domain(p, g, "pm")
    if selected is None:
        return
    mode, facies, domains = selected

    def defaults(domain):
        zone = g.zones[domain.get("zone", 1) - 1]
        row = dict(poro=zone.poro, permx=zone.permx, ntg=zone.ntg, kykx=1.0, kvkh=zone.kvkh)
        facies_defaults = next((r for r in p.facies.get("petro", []) if r["code"] == domain.get("code")), None)
        if facies_defaults:
            row.update(poro=facies_defaults["poro"], permx=10 ** facies_defaults["logk"], ntg=facies_defaults["ntg"])
        return row

    cfg = _table(p, "petrophysics", mode, facies, domains, defaults)
    property_trends.render(cfg, p, lambda field, opts=None: S.k("pm_trend_" + field, opts))
    st.caption("poro / ntg: fractions [0, 1]; permx: mD; kykx = PERMY/PERMX; kvkh = PERMZ/PERMX. "
               "Parameters in this table do not change the zone-definition table.")
    outputs = st.multiselect("Output properties", pp.ZONE_PROPS, default=pp.ZONE_PROPS, key=S.k("pm_outputs"))
    existing = [name for name in outputs if name in p.properties]
    approved = not existing
    if existing:
        approved = st.checkbox("Replace existing outputs: " + ", ".join(existing), key=S.k("pm_replace", existing))
    if st.button("Model petrophysical properties", type="primary", disabled=not outputs or not approved, key=S.k("pm_run")):
        try:
            result = petro.model_petrophysics(g, p.properties, mode, facies, cfg["rows"], cfg.get("trends"), p.surfaces)
        except petro.PetroError as exc:
            property_history.record(p, "Domain assignments", dict(cfg, outputs=outputs), [], status="Failed", message=str(exc))
            st.error(str(exc))
        else:
            p.properties.update({name: result[name] for name in outputs})
            property_history.record(p, "Domain assignments", dict(cfg, outputs=outputs), outputs)
            st.success("Stored " + ", ".join(outputs) + ". Inspect them in QC & tools.")


def render_saturation(p, g):
    if job_view.named_job(p, "saturation"):
        return
    st.subheader("Water-saturation modelling")
    method = st.radio("Saturation model", ["satheight", "archie"], horizontal=True, key=S.k("swm_method"),
                      format_func=lambda value: {"satheight": "Saturation-height", "archie": "Archie"}[value])
    selected = _domain(p, g, "swm")
    if selected is None:
        return
    mode, facies, domains = selected
    if not p.volumetrics:
        p.volumetrics = vol.default_config(g)
    if method == "satheight":
        st.caption("Sw = Swirr + (1 - Swirr) * (entry / max(height, entry))^lambda. "
                   "Height is measured above the free-water level at the cell centre; below the FWL, Sw = 1.")
        try:
            contact_settings.render(p.volumetrics["contacts"], p, lambda field: S.k("swm_contact_" + field))
        except (KeyError, TypeError, ValueError) as exc:
            st.error(f"Contact configuration: {exc}")
            return
        st.caption("Standalone contacts are shared with Volumetrics. Entry height uses the project depth unit.")
        system = p.volumetrics["contacts"].get("fluid_system", "auto")
        gas_curve = system not in ("gas", "oil") and st.checkbox("Separate gas-zone saturation-height parameters", key=S.k("swm_gas_curve"))
        if system == "gas":
            st.caption("The base saturation-height parameters describe the gas-water system.")
        defaults = dict(swirr=0.2, entry=2.0, lam=0.5)
        if gas_curve:
            defaults.update(gas_swirr=0.1, gas_entry=1., gas_lam=0.5)
    else:
        contact_settings.fluid_system(p.volumetrics["contacts"], lambda field, current: S.k("swm_" + field + "_" + current))
        st.caption("Sw = (a * Rw / (PORO^m * Rt))^(1/n), clipped to [0, 1]. "
                   "Archie assumes a clean formation; it is not a shaly-sand saturation model. "
                   "PORO must be a fraction, Rt and Rw must both be in ohm.m; calibrate exponents and Rw to your data. "
                   "Fluid choice affects volumetrics, not the Archie equation.")
        defaults = dict(a=1.0, m=2.0, n=2.0, rw=0.1)
    cfg = _table(p, "saturation_" + method, mode, facies, domains, lambda _domain: defaults)
    cfg["method"] = method
    cfg["gas_curve"] = method == "satheight" and gas_curve
    if method == "archie":
        names = [name for name, prop in p.properties.items()
                 if prop.kind == "continuous" and prop.values.shape == g.actnum.shape]
        if not names:
            st.warning("Create porosity and formation-resistivity (Rt) properties first.")
            return
        a, b = st.columns(2)
        cfg["poro"] = a.selectbox("Porosity property (fraction)", names, index=names.index("PORO") if "PORO" in names else 0,
                                  key=S.k("swm_poro", names))
        cfg["rt"] = b.selectbox("Formation resistivity Rt (ohm.m)", names, index=names.index("RT") if "RT" in names else 0,
                                key=S.k("swm_rt", names))
        if cfg["poro"] == cfg["rt"]:
            st.warning("Porosity and formation resistivity must be separate properties.")
    name = st.text_input("Saturation output property", value="SW", key=S.k("swm_output")).strip()
    valid_name = name.isidentifier() and name not in pp.GEOMETRIC
    if not valid_name:
        st.error("Use a property identifier that is not a geometry variable.")
    approved = name not in p.properties
    if not approved:
        approved = st.checkbox(f"Replace existing property {name}", key=S.k("swm_replace", [name]))
    same_input = method == "archie" and (cfg["poro"] == cfg["rt"] or name in (cfg["poro"], cfg["rt"]))
    if method == "archie" and name in (cfg["poro"], cfg["rt"]):
        st.error("The saturation output must not overwrite an Archie input.")
    if st.button("Model water saturation", type="primary", key=S.k("swm_run"),
                 disabled=not valid_name or not approved or same_input):
        try:
            values = petro.model_saturation(g, p.properties, cfg, p.volumetrics)
        except petro.PetroError as exc:
            property_history.record(p, "Water saturation", dict(cfg, output=name, contacts=p.volumetrics), [], status="Failed", message=str(exc))
            st.error(str(exc))
        else:
            p.properties[name] = pp.make_property(g, name, values, unit="frac", source="saturation",
                                                  expr=f"{method} by {mode}")
            cfg["output"] = name
            property_history.record(p, "Water saturation", dict(cfg, contacts=p.volumetrics), [name])
            st.success(f"Stored {name}. Use QC & tools to inspect the 3D result, layers, and zone statistics.")
    prop = p.properties.get(name)
    if prop is not None and prop.source == "saturation" and prop.values.shape == g.actnum.shape:
        stats = prop.stats(g.actnum)
        kpis([("Minimum Sw", f"{stats['min']:.3f}"), ("Mean Sw", f"{stats['mean']:.3f}"),
              ("Maximum Sw", f"{stats['max']:.3f}")])
        if prop.stale:
            st.warning("This saturation property is stale. Remodel it before using it in volumetrics.")
        if st.button(f"Use {name} in volumetrics", disabled=prop.stale, key=S.k("swm_use")):
            p.volumetrics["sw"].update(mode="property", prop=name)
            st.success(f"Volumetrics now uses the stored {name} property. Grid exports can include it too.")
    st.caption("Stored models are snapshots: rerun petrophysics/saturation after editing input properties, parameters, "
               "or contacts. Inactive grid cells remain undefined.")
