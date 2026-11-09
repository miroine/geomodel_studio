"""Fence intersections and vertically aggregated maps of existing grid properties."""
import numpy as np
import pandas as pd
import streamlit as st

from core import analysis as an, gridsection as gs, volumetrics as vol, units as un
from core.polygons import Polygon
from ui import state as S, specs
from ui.scene import Scene
from ui.components import map_editor, plotly_view, viewer3d


def _layers(p, prefix):
    g = p.grid
    names = [z.name for z in g.zones]
    zones = st.multiselect("Zones included", names, default=names, key=S.k(prefix + "_zones", names))
    lo, hi = st.slider("Layers included", 1, g.nk, (1, g.nk), key=S.k(prefix + "_layers", [g.nk])) if g.nk > 1 else (1, 1)
    layers = np.isin(g.layer_zone, [i for i, z in enumerate(g.zones) if z.name in zones])
    layers &= (np.arange(g.nk) >= lo - 1) & (np.arange(g.nk) <= hi - 1)
    return layers


def _model_map(p):
    """Top-of-model depth map (lattice, clipped to the boundary) used as the fence editor background."""
    lat, st_, g = p.lattice, p.structure, p.grid
    if lat is None or st_ is None or not st_.names:
        return None
    top = g.zones[0].top if g.zones and g.zones[0].top in st_.names else st_.names[0]
    Z = np.array(st_.lattice_depths()[st_.names.index(top)], dtype=float)
    if Z.shape != lat.shape:
        return None
    bp = p.boundary_poly()
    if bp is not None:
        from core import polygons as pg
        X, Y = lat.coords()
        Z[~pg.inside(X, Y, bp.pts)] = np.nan
    if not np.isfinite(Z).any():
        return None
    return dict(x0=lat.xori, y0=lat.yori, dx=lat.xinc, dy=lat.yinc, ncol=lat.ncol, nrow=lat.nrow, z=Z,
                zmin=float(np.nanmin(Z)), zmax=float(np.nanmax(Z)))


def _draw_fences(p, prefix):
    g = p.grid
    x, y = g.pillar_xy()
    extent = [float(x.min()), float(x.max()), float(y.min()), float(y.max())]
    result = map_editor("fences", key=S.k(prefix + "_editor"), height=460, extent=extent, grid=_model_map(p),
                        polygons=[f.to_dict() for f in p.fences.values()],
                        wells=[dict(name=w.name, x=w.x, y=w.y) for w in p.wells.values()],
                        nonce_tag=st.session_state.get(S.k(prefix + "_revision"), 0))
    if result and result.get("kind") == "fences" and result.get("nonce") != st.session_state.get(S.k(prefix + "_seen")):
        updated = {}
        for row in result.get("polygons", []):
            name = str(row.get("name") or "Fence").strip() or "Fence"
            gs.fence_columns(g, row["pts"])
            if name in updated:
                raise gs.SectionError("Fence names must be unique.")
            updated[name] = Polygon(name, row["pts"])
        p.fences = updated
        st.session_state[S.k(prefix + "_seen")] = result["nonce"]
        st.session_state[S.k(prefix + "_revision")] = st.session_state.get(S.k(prefix + "_revision"), 0) + 1
        st.rerun()
    st.caption("Draw an open polyline, finish with Enter, then Apply. Fences are shared with structural sections and saved in the project.")


def intersections(p):
    g = p.grid
    try:
        with st.expander("Draw / edit property fences", expanded=not p.fences):
            _draw_fences(p, "pi")
        if not p.fences:
            st.info("Draw a fence to investigate property intersections.")
            return
        fence = st.selectbox("Property fence", list(p.fences), key=S.k("pi_fence", list(p.fences)))
        names = [n for n, pr in p.properties.items() if pr.values.shape == g.actnum.shape and not pr.stale]
        if not names:
            st.warning("Create current grid properties first.")
            return
        selected = st.multiselect("Fence properties (up to 3)", names, default=names[:1], max_selections=3, key=S.k("pi_props", names))
        layers = _layers(p, "pi")
        if not selected or not layers.any():
            st.info("Select properties and at least one zone/layer.")
            return
        contacts = st.selectbox("Fence contacts", ["None", "Project contacts"] + [
            j["id"] for j in p.property_jobs if j["type"] == "saturation" and j["config"]["method"] == "satheight"],
            format_func=lambda v: next((j["name"] for j in p.property_jobs if j["id"] == v), v),
            key=S.k("pi_contacts", [j["id"] for j in p.property_jobs]))
        owc = goc = None
        contact_cfg = p.volumetrics if contacts == "Project contacts" else next(
            (j["config"]["contacts"] for j in p.property_jobs if j["id"] == contacts), None)
        if contacts != "None":
            if not contact_cfg:
                st.warning("Configure project contacts on Water saturation or Volumetrics first.")
            else:
                o3, g3, _ = vol.contact_cubes(g, contact_cfg, p.properties)
                # Contact depth properties may vary by layer; each ribbon shows its own contact.
                owc, goc = o3, g3
        points = p.fences[fence].pts
        panels = []
        from ui import display
        from ui.scene import grid_property
        with st.expander("Edit fence property colours"):
            edit = st.selectbox("Property colours to edit", selected, key=S.k("pi_color_prop", selected))
            display.colors(p, edit, "pi")
        for name in selected:
            pr = p.properties[name]
            values = np.where(layers[:, None, None], pr.values, np.nan)
            section = gs.fence_property_section(g, values, points, p.faults, owc, goc)
            scale, _ = grid_property(g, name, p.properties, p.display_settings.get("properties"))
            panels.append(dict(name=name, unit=pr.unit, sec=section, discrete=pr.kind == "discrete",
                               scale=scale, stops=scale.get("stops", scale.get("colors"))))
        if not any(len(panel["sec"]["v"]) for panel in panels):
            st.warning("No finite active property values intersect this fence and layer selection.")
            return
        plotly_view(specs.property_section(panels, show_contacts=contacts != "None"), key=S.k("pi_section"), height=300 + 220 * len(panels))
        st.caption("Plan-view column crossings are exact. Ribbon depths average the column's corner depths; this is not a tilted-pillar plane slice. Hover for raw property values.")
        with st.expander("Fence intersection in 3D", expanded=True):
            name = st.selectbox("3D fence property", selected, key=S.k("pi_3d_prop", selected))
            include_grid = st.checkbox("Show surrounding grid", value=False, key=S.k("pi_grid"))
            opacity = st.slider("Grid opacity", 0.05, 1.0, 1.0, 0.05, disabled=not include_grid, key=S.k("pi_opacity"))
            mesh = st.checkbox("Black fence mesh edges", value=True, key=S.k("pi_mesh"))
            ve = st.slider("Fence V.E.", 1., 20., 4., 0.5, key=S.k("pi_ve"))
            x, y = g.pillar_xy()
            sc = Scene((float(x.min()), float(y.min())))
            if include_grid:
                sc.grid(g, prop=name, props=p.properties, layer_mask=layers, opacity=opacity,
                        display=p.display_settings.get("properties"))
            sc.property_fence(g, name, points, p.properties, name=fence, layer_mask=layers,
                              display=p.display_settings.get("properties"))
            S.grid_view_inspector(viewer3d(sc, key=S.k("pi_viewer"), height=560, ve=ve, mesh=mesh), p, "pi")
            st.caption("Hide the surrounding grid to expose interior fence cells; click a ribbon for its original I/J/K and value.")
        for panel in panels:
            sec = panel["sec"]
            df = pd.DataFrame(dict(I=sec["i"] + 1, J=sec["j"] + 1, K=sec["k"] + 1,
                                   Distance_start=sec["x"][:, 0], Distance_end=sec["x"][:, 1], Value=sec["v"]))
            st.download_button(f"Download {panel['name']} fence data (CSV)", df.to_csv(index=False).encode(),
                               f"{fence}_{panel['name']}.csv", "text/csv", key=S.k("pi_dl_" + panel["name"]))
    except (gs.SectionError, vol.VolError, ValueError, KeyError) as exc:
        st.error(f"Property intersection: {exc}")


def average_maps(p, prefix="am"):
    g = p.grid
    names = [n for n, pr in p.properties.items() if pr.kind == "continuous" and pr.values.shape == g.actnum.shape and not pr.stale]
    if not names:
        st.info("Create current continuous properties to generate average maps. Averaging facies codes is not meaningful.")
        return
    selected = st.multiselect("Average-map properties", names, default=names[:1], key=S.k(prefix + "_props", names))
    modes = {"average": "Arithmetic average", "thickness-weighted": "Thickness-weighted average",
             "bulk-volume-weighted": "Bulk-volume-weighted average"}
    mode = st.selectbox("Average-map method", list(modes), format_func=modes.get, key=S.k(prefix + "_mode"))
    layers = _layers(p, prefix)
    if not layers.any() or not selected:
        st.info("Select properties and at least one zone/layer.")
        return
    mask = (g.actnum > 0) & layers[:, None, None]
    for name in selected:
        try:
            values = an.map_2d(g, p.properties, name, mask, mode, ())
            if not np.isfinite(values).any():
                st.warning(f"{name}: no finite active values in the selected interval.")
                continue
            title = f"{name} - {modes[mode]}"
            unit = p.properties[name].unit
            from ui import display
            plotly_view(display.property_map(p, g, name, values, title, unit), key=S.k(prefix + "_map_" + name), height=420)
            x, y = g.center_xy()
            j, i = np.indices(values.shape)
            df = pd.DataFrame(dict(I=i.ravel() + 1, J=j.ravel() + 1, X=x.ravel(), Y=y.ravel(),
                                   Value=values.ravel(), Count=np.sum(mask & np.isfinite(p.properties[name].values), axis=0).ravel()))
            st.download_button(f"Download {name} average map (CSV)", df.to_csv(index=False).encode(),
                               f"{name}_{mode}.csv", "text/csv", key=S.k(prefix + "_dl_" + name))
        except an.AnalysisError as exc:
            st.error(str(exc))
    st.caption(f"Maps aggregate finite active cells vertically, with no NTG multiplier. Display uses I/J indices; CSV uses world XY ({un.xy()}) "
               "and preserves rotated/refined grid centers. Empty columns are undefined. These are derived results, not new 3D properties.")
