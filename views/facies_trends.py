"""Facies probability trend controls shared by standalone and workflow runs."""
import pandas as pd
import streamlit as st

from core import units


def render(cfg, project, key):
    st.markdown("**Facies probability trends**")
    st.caption("Optional additive probability offsets per facies: absolute depth, map value, and/or vertical distance "
               "from a depth surface. Offsets add to zone proportions, are clipped at zero, then normalized. "
               "Available for truncated Gaussian and indicator simulation only; other methods reject enabled trends.")
    trends = cfg.setdefault("probability_trends", {})
    depths = project.grid.center_depth()[project.grid.actnum > 0]
    lo, hi = (float(depths.min()), float(depths.max())) if depths.size else (0.0, 1.0)
    if hi <= lo:
        hi = lo + 1
    names = list(project.surfaces)
    for fac in cfg["facies"]:
        code = str(fac["code"])
        trend = trends.setdefault(code, {})
        prefix = f"facies_trend_{code}_"
        st.markdown(f"**{fac['name']} ({code})**")
        trend["depth_enabled"] = st.checkbox(f"{fac['name']}: absolute depth trend", bool(trend.get("depth_enabled")), key=key(prefix + "depth"))
        if trend["depth_enabled"]:
            trend["curve"] = st.data_editor(pd.DataFrame(trend.get("curve", [[lo, 0.0], [hi, 0.0]]),
                columns=[f"Depth ({units.z()})", "Probability offset"]), num_rows="dynamic", hide_index=True,
                key=key(prefix + "curve")).to_numpy(dtype=float).tolist()
        trend["map_enabled"] = st.checkbox(f"{fac['name']}: probability map trend", bool(trend.get("map_enabled")), key=key(prefix + "map_enabled"))
        if trend["map_enabled"]:
            current = trend.get("map", "")
            options = ([current] if current and current not in names else []) + names
            if not options:
                st.warning("Add a surface to use a probability map.")
                trend["map"] = ""
            else:
                trend["map"] = st.selectbox(f"{fac['name']}: probability map", options,
                    index=options.index(current) if current in options else 0, key=key(prefix + "map", options))
            trend["reference"] = float(st.number_input(f"{fac['name']}: map reference", value=float(trend.get("reference", 0)), key=key(prefix + "reference")))
            trend["strength"] = float(st.number_input(f"{fac['name']}: map strength", value=float(trend.get("strength", 1)), key=key(prefix + "strength")))
        trend["distance_enabled"] = st.checkbox(f"{fac['name']}: distance from surface trend", bool(trend.get("distance_enabled")), key=key(prefix + "distance"))
        if trend["distance_enabled"]:
            current = trend.get("distance_surface", "")
            options = ([current] if current and current not in names else []) + names
            if not options:
                st.warning("Add a depth surface for the distance trend.")
                trend["distance_surface"] = ""
            else:
                trend["distance_surface"] = st.selectbox(f"{fac['name']}: depth surface", options,
                    index=options.index(current) if current in options else 0, key=key(prefix + "surface", options))
            trend["distance_curve"] = st.data_editor(pd.DataFrame(trend.get("distance_curve", [[-100., 0.], [100., 0.]]),
                columns=[f"Depth minus surface ({units.z()})", "Probability offset"]), num_rows="dynamic", hide_index=True,
                key=key(prefix + "distance_curve")).to_numpy(dtype=float).tolist()
