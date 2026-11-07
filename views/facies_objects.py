"""Shared object and fluvial-channel configuration for standalone and named facies jobs."""
import numpy as np
import pandas as pd
import streamlit as st
import uuid

from core import facies as fa, units as un
from ui.components import map_editor


def render(cfg, project, key):
    fa.normalise(cfg, project.grid)
    for obj in cfg["objects"]:
        obj.setdefault("id", uuid.uuid4().hex[:12])
    fields = ["id", "code", "shape", "length", "width", "thickness", "azimuth", "amplitude", "wavelength"]
    rows = [{k: o[k] for k in fields} for o in cfg["objects"]]
    edited = st.data_editor(pd.DataFrame(rows, columns=fields), key=key("objects"), hide_index=True, num_rows="dynamic",
                           disabled=["id"], column_config={"id": None, "shape": st.column_config.SelectboxColumn(
                               "Shape", options=["ellipsoid", "channel", "digitized_channel"], required=True)})
    old = {o["id"]: o for o in cfg["objects"]}
    cfg["objects"] = [dict(r, id=r["id"] if isinstance(r["id"], str) else uuid.uuid5(uuid.NAMESPACE_URL, f"{key('objects')}:{i}").hex[:12],
                          centerline=old.get(r["id"], {}).get("centerline", []))
                      for i, r in enumerate(edited.to_dict("records"))]
    st.caption(f"channel: meandering centerline; amplitude and wavelength in {un.xy()}. "
               f"Width/length in {un.xy()}, thickness in {un.z()}. Azimuth is degrees from north. "
               "digitized_channel: fixed XY path, random depth placement; length/azimuth/amplitude/wavelength are unused.")
    for index, obj in enumerate(cfg["objects"]):
        if obj["shape"] != "digitized_channel":
            continue
        with st.container(border=True):
            st.markdown(f"**Channel centerline - object {index + 1}, facies {obj['code']}**")
            grid = project.grid
            x, y = grid.pillar_xy()
            extent = [float(np.min(x)), float(np.max(x)), float(np.min(y)), float(np.max(y))]
            val = map_editor("fences", key=key(f"channel_map_{obj['id']}"), height=420, extent=extent,
                             polygons=[dict(name="Channel", pts=obj["centerline"])] if obj["centerline"] else [])
            if val and val.get("kind") == "fences":
                lines = val.get("polygons", [])
                if len(lines) > 1:
                    st.error("Keep one centerline per object row. Add another object row for another channel.")
                    raise ValueError("Multiple centerlines in one channel object.")
                obj["centerline"] = lines[0]["pts"] if lines else []
            st.caption("Draw an open line, finish with Enter, then press Apply. Save the job configuration to retain it.")
