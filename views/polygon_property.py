"""Controls shared by the polygon property tool and workflow job."""
import streamlit as st

from core import props


MODES = {"inside": "Inside only", "outside": "Outside only", "both": "Inside and outside"}


def controls(config, project, key):
    names = list(project.polygons)
    selected = config.get("polygon", "")
    if selected and selected not in names:
        names.insert(0, selected)
    if not names:
        st.warning("Import or draw a closed polygon on the Polygons page first.")
        config["polygon"] = ""
    else:
        config["polygon"] = st.selectbox("Assignment polygon", names,
                                         index=names.index(selected) if selected in names else 0,
                                         key=key("polygon", names))
        if config["polygon"] not in project.polygons:
            st.warning("The saved polygon is missing. Choose another polygon.")
    config["output"] = st.text_input("Property name", config.get("output", "PORO"), key=key("output"))
    if project.properties:
        st.caption("Available properties: " + ", ".join(project.properties))
    modes = list(MODES)
    current = config.get("mode", "both")
    config["mode"] = st.selectbox("Assign values", modes, index=modes.index(current) if current in modes else 2,
                                  format_func=MODES.get, key=key("mode"))
    if config["mode"] in ("inside", "both"):
        config["inside"] = float(st.number_input("Value inside polygon", value=float(config.get("inside", 0.2)),
                                                 format="%g", key=key("inside")))
    if config["mode"] in ("outside", "both"):
        config["outside"] = float(st.number_input("Value outside polygon", value=float(config.get("outside", 0.1)),
                                                  format="%g", key=key("outside")))
    config["kind"] = st.selectbox("Type for a new property", props.KINDS,
                                  index=props.KINDS.index(config.get("kind", "continuous"))
                                  if config.get("kind", "continuous") in props.KINDS else 0, key=key("kind"))
    config["unit"] = st.text_input("Unit for a new property", config.get("unit", ""), key=key("unit"))
    st.caption("Cell-column centres on the polygon edge count as inside. The selection applies to every layer's active cells. "
               "One-sided assignment requires an existing property; its other values, type, unit and legend are preserved. "
               "New properties require values on both sides.")
