"""Saved colour preferences shared by grid, fence and map displays."""
import numpy as np
import streamlit as st

from ui import state as S, specs
from ui.scene import COLOR_PRESETS, DEPTH_STOPS, display_stops, grid_property, property_stops


def colors(p, name, prefix, surface=False):
    group = "surfaces" if surface else "properties"
    settings = p.display_settings.get(group, {}).get(name, {})
    default = DEPTH_STOPS if surface else property_stops(name)
    scale = None
    if not surface and p.grid is not None:
        scale, _ = grid_property(p.grid, name, p.properties, p.display_settings.get(group))
        if scale["kind"] == "discrete":
            default = COLOR_PRESETS["Webviz Colors set 3"]
    with st.container(border=True):
        st.markdown(f"**{'Surface depth' if surface else name} colours**")
        options = ["Automatic", *COLOR_PRESETS, "Custom"]
        current = "Custom" if settings.get("stops") else settings.get("preset", "Automatic")
        palette = st.selectbox("Colour preset", options, index=options.index(current),
                               key=S.k(prefix + "_preset", [name, str(settings)]))
        stops = display_stops(settings, default) if palette == "Custom" else list(COLOR_PRESETS.get(palette, default))
        with st.form(S.k(prefix + "_colors", [name, palette, str(settings)])):
            edited = []
            cols = st.columns(min(len(stops), 5))
            for i, color in enumerate(stops):
                edited.append(cols[i % len(cols)].color_picker(f"Colour {i + 1} (low to high)", color,
                                                              key=S.k(prefix + f"_stop_{name}_{palette}_{i}")))
            overrides = {}
            if scale is not None and scale["kind"] == "discrete":
                st.caption("Individual facies/category colours override the selected palette.")
                codes = scale.get("codes", np.arange(len(scale["colors"])) + scale["first"])
                for i, code in enumerate(codes):
                    overrides[str(code)] = st.color_picker(f"Code {code}", settings.get("categories", {}).get(
                        str(code), stops[i % len(stops)]), key=S.k(prefix + f"_code_{name}_{palette}_{code}"))
            if st.form_submit_button("Save colours"):
                value = {}
                if palette != "Automatic":
                    value["preset"] = palette
                if edited != stops or palette == "Custom":
                    value["stops"] = edited
                if scale is not None and scale["kind"] == "discrete":
                    value["categories"] = overrides
                p.display_settings.setdefault(group, {})[name] = value
                st.rerun()
        if st.button("Reset to automatic colours", key=S.k(prefix + "_reset", [name])):
            p.display_settings.get(group, {}).pop(name, None)
            st.rerun()
        st.caption("Saved with the project. Colours only affect display, not property values or modelling jobs.")


def property_map(p, g, name, values, title, unit=""):
    scale, _ = grid_property(g, name, p.properties, p.display_settings.get("properties"))
    mapped = np.asarray(values, float)
    if scale["kind"] == "discrete":
        codes = scale.get("codes", np.arange(len(scale["colors"])) + scale["first"])
        mapped = np.where(np.isfinite(mapped), np.searchsorted(codes, mapped), np.nan)
        colors = scale["colors"]
        cs = [[v, c] for i, c in enumerate(colors) for v in (i / len(colors), (i + 1) / len(colors))]
        spec = specs.layer_map(mapped, title, name, cs)
        spec["data"][0].update(zmin=-0.5, zmax=len(colors) - 0.5, customdata=values,
                               hovertemplate="I %{x}, J %{y}: %{customdata:.4g}<extra></extra>")
        spec["data"][0]["colorbar"].update(tickvals=list(range(len(codes))), ticktext=[str(c) for c in codes])
    else:
        if name.upper().startswith("PERM"):
            mapped = np.where(mapped > 0, np.log10(np.maximum(mapped, 1e-3)), np.nan)
        cs = [[i / (len(scale["stops"]) - 1), c] for i, c in enumerate(scale["stops"])]
        spec = specs.layer_map(mapped, title, name + (f" ({unit})" if unit else ""), cs)
        spec["data"][0].update(zmin=scale["vmin"], zmax=scale["vmax"], customdata=values,
                               hovertemplate="I %{x}, J %{y}: %{customdata:.4g}<extra></extra>")
    return spec


def surface_map(p, surface, prefix, faults=(), wells=None):
    contours = st.checkbox("Show depth contours", value=True, key=S.k(prefix + "_contours"))
    interval = st.number_input("Contour interval (0 = automatic)", min_value=0., value=0., key=S.k(prefix + "_interval"),
                               help="In project depth units.")
    paths = st.checkbox("Show well trajectories", value=bool(p.wells), key=S.k(prefix + "_wells"))
    if paths:
        st.caption("Well paths are projected in plan view, with wellheads and depth hover values; these are not surface-intersection points.")
    labels = st.checkbox("Label contours", value=False, disabled=not contours, key=S.k(prefix + "_labels"))
    stops = display_stops(p.display_settings.get("surfaces", {}).get(surface.name, {}), DEPTH_STOPS)
    return specs.map_2d(surface.z, surface.geom, title=surface.name,
                        scale=[[i / (len(stops) - 1), c] for i, c in enumerate(stops)],
                        faults=list(faults), wells=wells, contour_lines=contours, contour_interval=interval,
                        contour_labels=labels and contours, well_paths=list(p.wells.values()) if paths else [])
