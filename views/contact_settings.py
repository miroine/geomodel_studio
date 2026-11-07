"""Shared contact editor for saved saturation jobs and standalone modelling."""
import numpy as np
import pandas as pd
import streamlit as st

from core import units as un


def _optional(value):
    return None if pd.isna(value) else float(value)


def _overrides(saved, id_field, key, identifiers=()):
    rows = [dict(**{id_field: int(code)}, OWC=value.get("owc"), GOC=value.get("goc"))
            for code, value in saved.items()]
    for code in identifiers:
        if code not in [r[id_field] for r in rows]:
            rows.append({id_field: int(code), "OWC": None, "GOC": None})
    edited = st.data_editor(pd.DataFrame(rows, columns=[id_field, "OWC", "GOC"]), hide_index=True,
                            num_rows="dynamic", key=key,
                            column_config={"OWC": st.column_config.NumberColumn("OWC"),
                                           "GOC": st.column_config.NumberColumn("GOC"),
                                           id_field: st.column_config.NumberColumn(id_field, step=1)})
    result = {}
    for row in edited.to_dict("records"):
        owc, goc = _optional(row["OWC"]), _optional(row["GOC"])
        if owc is None and goc is None:
            continue
        code = float(row[id_field])
        if not np.isfinite(code) or code != int(code) or str(int(code)) in result:
            raise ValueError(f"{id_field} identifiers must be finite, unique integers.")
        if any(value is not None and not np.isfinite(value) for value in (owc, goc)):
            raise ValueError("Contact overrides must be finite.")
        result[str(int(code))] = dict(owc=owc, goc=goc)
    return result


def render(contacts, project, key):
    st.markdown("**WOC / OWC and GOC contacts**")
    a, b = st.columns(2)
    contacts["owc"] = float(a.number_input(f"OWC / WOC depth ({un.z()}, positive down)",
                                          value=float(contacts["owc"]), key=key("owc")))
    contacts["fwl_below"] = float(b.number_input(f"FWL below OWC ({un.z()})", min_value=0.,
                                                value=float(contacts.get("fwl_below", 0)), key=key("fwl")))
    enabled = st.checkbox("Gas cap (GOC)", value=contacts.get("goc") is not None, key=key("gas"))
    if enabled:
        contacts["goc"] = float(st.number_input(f"GOC depth ({un.z()}, positive down)",
                                               value=float(contacts.get("goc") if contacts.get("goc") is not None else contacts["owc"] - 30),
                                               key=key("goc")))
    else:
        contacts["goc"] = None
    for field, label in (("owc", "OWC / WOC"), ("goc", "GOC")):
        source = st.selectbox(f"{label} source", ["Configured contacts", "3D property"],
                              index=1 if contacts.get(field + "_prop") else 0, key=key(field + "_source"))
        contacts[field + "_prop"] = (st.text_input(f"{label} contact-depth property",
                                                  contacts.get(field + "_prop") or field.upper(),
                                                  key=key(field + "_prop")).strip() if source == "3D property" else "")
        if source == "3D property" and not contacts[field + "_prop"]:
            raise ValueError(f"Specify the {label} contact-depth property.")
    st.caption("3D contact-depth properties override configured values and tilt. They may be outputs of earlier jobs. "
               "Use positive-down depths; a blank property unit means the project depth unit, otherwise specify a length unit.")
    with st.container(border=True):
        st.markdown("**Fault-block and zone / region overrides**")
        contacts["blocks"] = _overrides(contacts.get("blocks", {}), "Block", key("blocks"),
                                        np.unique(project.grid.block[project.grid.block > 0]))
        region = contacts.setdefault("regions", dict(prop="ZONE", values={}))
        region["prop"] = st.text_input("Region property for contacts", region.get("prop", "ZONE"), key=key("region_prop"))
        region["values"] = _overrides(region.get("values", {}), "Region", key("regions"),
                                      range(1, len(project.grid.zones) + 1) if region["prop"] == "ZONE" else ())
        st.caption("Blank contacts inherit global/block values. ZONE uses 1-based zone numbers; other region sets require a discrete property.")
        tilt = contacts.setdefault("tilt", {})
        for field, label in (("gx", "Tilt gradient along X"), ("gy", "Tilt gradient along Y"),
                             ("xref", "Tilt reference X"), ("yref", "Tilt reference Y")):
            tilt[field] = float(st.number_input(label, value=float(tilt.get(field, 0)), key=key("tilt_" + field)))
        st.caption(f"Tilt gradients are {un.z()} per {un.xy()}; reference XY is in {un.xy()}.")
