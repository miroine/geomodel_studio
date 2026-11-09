"""Shared property trend controls for standalone tools and saved jobs."""
import pandas as pd
import streamlit as st

from core import units as un


def render(cfg, project, key):
    trends = cfg.setdefault("trends", {})
    with st.expander("Depth and map trends", expanded=False):
        st.caption("Additive offsets per property, applied before bounds and cut-offs. "
                   "Depth is positive down in project units. Curve offsets interpolate linearly "
                   "and stay constant beyond the end depths. Maps use their raw library values, not converted depth values.")
        depths = project.grid.center_depth()[project.grid.actnum > 0]
        lo, hi = (float(depths.min()), float(depths.max())) if depths.size else (0.0, 1.0)
        hi = max(hi, lo + 1.0)
        for name in ("PORO", "PERM", "NTG"):
            unit = "mD" if name == "PERM" else "fraction"
            st.markdown(f"**{name} offsets ({unit})**")
            trend = trends.setdefault(name, {})
            trend["depth_enabled"] = st.checkbox(f"{name}: depth trend", bool(trend.get("depth_enabled")), key=key(name + "_depth"))
            if trend["depth_enabled"]:
                curve = trend.get("curve", [[lo, 0.0], [hi, 0.0]])
                frame = st.data_editor(pd.DataFrame(curve, columns=[f"Depth ({un.z()})", f"Offset ({unit})"]),
                                       num_rows="dynamic", hide_index=True, key=key(name + "_curve"))
                trend["curve"] = frame.to_numpy(dtype=float).tolist()
            trend["map_enabled"] = st.checkbox(f"{name}: map trend", bool(trend.get("map_enabled")), key=key(name + "_map_enabled"))
            if trend["map_enabled"]:
                names = list(project.surfaces)
                if not names:
                    st.error("Import or create a library surface to use as a trend map.")
                    trend["map"] = ""
                    continue
                current = trend.get("map")
                trend["map"] = st.selectbox(f"{name}: trend map", names, index=names.index(current) if current in names else 0,
                                            key=key(name + "_map", names))
                trend["reference"] = float(st.number_input(f"{name}: map reference value", value=float(trend.get("reference", 0)),
                                                          key=key(name + "_reference")))
                trend["strength"] = float(st.number_input(f"{name}: map strength ({unit} per map unit)", value=float(trend.get("strength", 1)),
                                                         key=key(name + "_strength")))
                st.caption("Map offset = strength × (map value − reference). Map must cover active grid columns.")
        st.caption("PERM trends modify PERMX in mD; PERMY/PERMZ retain the configured ratios. "
                   "PORO and NTG stay in [0, 1], permeability stays non-negative. "
                   "Stochastic histogram bounds also apply; trends intentionally change the target histogram.")
