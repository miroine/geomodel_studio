"""3D window: every object of the project in one interactive WebGL scene (object tree, VE, mesh, wells, grid)."""
import numpy as np
import streamlit as st

from ui import state as S
from ui.components import viewer3d
from ui.theme import banner, kpis, note


def render():
    p = S.proj()
    banner("3D window", "Surfaces, faults, polygons, wells, tops and the 3D grid in one interactive scene")
    if not S.need_lattice(p):
        return
    names = list(p.surfaces)
    hnames = list(p.structure.names) if p.structure is not None else []
    with st.expander("Scene content", expanded=not names):
        c1, c2 = st.columns([3, 2])
        sel = c1.multiselect("Surfaces (input maps, after filters)", names, default=[] if hnames else names, key=S.k("v3_surf", names) + f"_{bool(hnames)}")
        hsel = c1.multiselect("Structural-model horizons (faulted, calibrated)", hnames, default=hnames, key=S.k("v3_hz", hnames),
                              disabled=not hnames, help="Run the structural model (step 4) to get these")
        with c2:
            faults = st.checkbox("Fault planes", value=bool(p.faults), key=S.k("v3_f"))
            polys = st.checkbox("Polygons", value=bool(p.polygons), key=S.k("v3_p"))
            wells = st.checkbox("Wells", value=bool(p.wells), key=S.k("v3_w"))
            tops = st.checkbox("Well tops", value=True, key=S.k("v3_t"))
        c1, c2, c3 = st.columns(3)
        clip = c1.checkbox("Clip display to model boundary", value=False, disabled=p.boundary_poly() is None, key=S.k("v3_clip"),
                           help="Hide surface nodes outside the boundary polygon (display only)")
        wscale = c2.slider("Well radius", 0.3, 4.0, 1.0, 0.1, key=S.k("v3_ws"))
        sop = c3.slider("Surface opacity", 0.1, 1.0, 1.0, 0.1, key=S.k("v3_so"))
        grid = None
        layer_mask = None
        prop, i0, j0 = "Zone", 0, 0
        grid_opacity = 1.0
        if p.grid is not None:
            g = p.grid
            show_grid = st.checkbox(f"3D grid ({g.ni} x {g.nj} x {g.nk})", value=True, key=S.k("v3_g"))
            if show_grid:
                grid = g
                props = list(dict.fromkeys(["Zone", "Layer (k)", "Fault block", "Depth", "Thickness",
                                            "PORO", "PERMX", "NTG", *p.properties]))
                a, b, c = st.columns(3)
                prop = a.selectbox("Colour grid by", props, key=S.k("v3_prop"))
                i0 = b.slider("Cut-away: first I", 0, max(g.ni - 1, 1), 0, key=S.k("v3_i0"))
                j0 = c.slider("Cut-away: first J", 0, max(g.nj - 1, 1), 0, key=S.k("v3_j0"))
                layer_mask = S.grid_view_layers(g, "v3")
                grid_opacity = st.slider("Grid opacity", 0.05, 1.0, 1.0, 0.05, key=S.k("v3_opacity"))
                from ui import display
                display.colors(p, prop, "v3")
        else:
            st.caption("Build the 3D grid (step 6) to add it to this scene.")
    if not (sel or hsel or grid is not None or p.wells or p.polygons or p.faults):
        note("Nothing to show yet - add surfaces, wells or polygons.")
        return
    try:
        sc = S.build_scene(p, surfaces=sel, faults=faults, polygons=polys, wells=wells, tops=tops, grid=grid, prop=prop, i0=i0, j0=j0,
                           clip_to_boundary=clip, well_scale=wscale, surface_opacity=sop, horizons=hsel, layer_mask=layer_mask,
                           grid_opacity=grid_opacity)
    except ValueError as e:                      # exterior-face limit of the grid cut-away
        st.warning(str(e))
        return
    ve = st.slider("Initial vertical exaggeration", 1.0, 20.0, 3.0, 0.5, key=S.k("v3_ve"),
                   help="You can also change it live inside the viewer without a rerun")
    mesh = st.checkbox("Black mesh edges", value=False, key=S.k("v3_mesh"))
    selection = viewer3d(sc, key=S.k("v3d"), height=720, ve=ve, mesh=mesh)
    S.grid_view_inspector(selection, p, "v3")
    st.caption("Mouse: **left-drag** orbit · **right-drag / Shift-drag** pan · **wheel** zoom · **double-click** fit. "
               "The object tree toggles visibility and opacity; *Black mesh* shows cell / triangle edges. "
               "Click a grid face to inspect its cell. Property ramps use public Webviz colour tables.")
