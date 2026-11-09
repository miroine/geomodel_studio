"""Saved colour preferences shared by grid, fence and map displays."""
import numpy as np
import streamlit as st

from core import units as un
from ui import state as S, specs
from ui.scene import (COLOR_PRESETS, DEPTH_STOPS, display_range, display_stops, grid_property, has_range,
                      property_stops)


def _surface_depths(p, name):
    if name in p.surfaces:
        return p.surfaces[name].z
    if p.structure is not None and name in p.structure.names:
        return p.structure.lattice_depths()[p.structure.names.index(name)]
    return None


def auto_range(p, name, surface=False):
    """Automatic colour range in data units (raw mD for permeability), or None for discrete/unknown data."""
    if surface:
        z = _surface_depths(p, name)
        if z is None or not np.isfinite(z).any():
            return None
        return float(np.nanmin(z)), float(np.nanmax(z))
    if p.grid is None:
        return None
    scale, _ = grid_property(p.grid, name, p.properties, None)
    if scale["kind"] == "discrete":
        return None
    lo, hi = float(scale["vmin"]), float(scale["vmax"])
    if name.upper().startswith("PERM"):
        lo, hi = 10 ** lo, 10 ** hi
    return lo, hi


def _range_inputs(p, name, prefix, settings, surface):
    """Min / max colour-range widgets inside the colour form. Returns (custom, vmin, vmax) or None."""
    auto = auto_range(p, name, surface)
    if auto is None:
        return None
    unit = un.z() if surface else (p.properties[name].unit if name in p.properties else "")
    suffix = f" ({unit})" if unit else ""
    st.markdown("**Value range**")
    custom = st.checkbox("Custom min / max range", value=has_range(settings),
                         key=S.k(prefix + "_range_on", [name, str(settings)]),
                         help="Clip the colour scale to these limits; values outside use the end colours.")
    c1, c2 = st.columns(2)
    lo = c1.number_input("Minimum" + suffix, value=float(settings.get("vmin", auto[0])), format="%.6g",
                         key=S.k(prefix + "_vmin", [name, str(settings)]))
    hi = c2.number_input("Maximum" + suffix, value=float(settings.get("vmax", auto[1])), format="%.6g",
                         key=S.k(prefix + "_vmax", [name, str(settings)]))
    st.caption(f"Automatic range: {auto[0]:.6g} to {auto[1]:.6g}{suffix}.")
    return custom, lo, hi


def colors(p, name, prefix, surface=False):
    group = "surfaces" if surface else "properties"
    settings = p.display_settings.get(group, {}).get(name, {})
    default = DEPTH_STOPS if surface else property_stops(name)
    scale = None
    if not surface and p.grid is not None:
        scale, _ = grid_property(p.grid, name, p.properties, None)
        if scale["kind"] == "discrete":
            default = COLOR_PRESETS["Webviz Colors set 3"]
    with st.container(border=True):
        st.markdown(f"**{'Surface depth' if surface else name} colours and range**")
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
            limits = _range_inputs(p, name, prefix, settings, surface)
            if st.form_submit_button("Save colours"):
                value = {}
                if palette != "Automatic":
                    value["preset"] = palette
                if edited != stops or palette == "Custom":
                    value["stops"] = edited
                if scale is not None and scale["kind"] == "discrete":
                    value["categories"] = overrides
                error = None
                if limits and limits[0]:
                    _, lo, hi = limits
                    if not (np.isfinite(lo) and np.isfinite(hi) and lo < hi):
                        error = "Range minimum must be smaller than maximum."
                    elif name.upper().startswith("PERM") and not surface and lo <= 0:
                        error = "Permeability is shown on a log scale; the minimum must be positive."
                    else:
                        value.update(vmin=float(lo), vmax=float(hi))
                if error:
                    st.error(error)
                else:
                    p.display_settings.setdefault(group, {})[name] = value
                    st.rerun()
        if st.button("Reset to automatic colours", key=S.k(prefix + "_reset", [name])):
            p.display_settings.get(group, {}).pop(name, None)
            st.rerun()
        st.caption("Saved with the project. Colours and ranges only affect display, not property values or modelling jobs.")


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
    settings = p.display_settings.get("surfaces", {}).get(surface.name, {})
    stops = display_stops(settings, DEPTH_STOPS)
    zrange = None
    if has_range(settings):
        z = surface.z[np.isfinite(surface.z)]
        zrange = display_range(settings, float(z.min()) if z.size else 0., float(z.max()) if z.size else 1.)
    return specs.map_2d(surface.z, surface.geom, title=surface.name,
                        scale=[[i / (len(stops) - 1), c] for i, c in enumerate(stops)],
                        faults=list(faults), wells=wells, contour_lines=contours, contour_interval=interval,
                        contour_labels=labels and contours, well_paths=list(p.wells.values()) if paths else [],
                        zrange=zrange)
