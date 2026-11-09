"""3D grid: build the corner-point grid and QC it."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core.cpgrid import build_grid, validate_zones, plan_axes, grid_estimate
from ui import state as S
from ui import specs
from ui.components import plotly_view, viewer3d
from ui.theme import banner, kpis, note

PROPS = ["Zone", "Layer (k)", "Fault block", "Depth", "Thickness", "PORO", "PERMX", "NTG"]
MAX_CELLS = 3_000_000
DEFAULT_GP = dict(dx=100.0, dy=100.0, min_thickness=0.1, mode="size", ni=40, nj=40, angle=0.0, auto_frame=True, origin=None, extent=None,
                  refine=[], trim_extent=False, min_volume=0.0, inactive_zones=[], tilt=False, tilt_radius=3.0)


def _controls(p, gp, bounds):
    """Gridding controls (Petrel 'Make simple grid' / Eclipse-style): size, frame, refinement, ACTNUM.  Returns the build spec."""
    xmin, xmax, ymin, ymax = bounds
    out = {}
    with st.expander("Grid definition: cell size, orientation, local refinement", expanded=True):
        mode = st.radio("Define the lateral grid by", ["size", "count"], horizontal=True, index=0 if gp["mode"] == "size" else 1,
                        format_func=lambda m: {"size": "Cell size (dx, dy)", "count": "Number of cells (ni, nj)"}[m], key=S.k("gc_mode"))
        c1, c2, c3, c4 = st.columns(4)
        ang = c3.number_input("Rotation (deg, counter-clockwise)", -90.0, 90.0, float(gp["angle"]), 5.0, key=S.k("gc_ang"),
                              help="Orientation of the I axis. Align it with the main fault trend to get cells parallel to faults. Written as MAPAXES in GRDECL.")
        auto = c4.checkbox("Fit frame to model", bool(gp["auto_frame"]), key=S.k("gc_auto"))
        origin = extent = None
        if not auto:
            a, b, c, d = st.columns(4)
            ox = a.number_input(f"Origin X ({un.xy()})", value=float(gp["origin"][0] if gp["origin"] else xmin), key=S.k("gc_ox"))
            oy = b.number_input(f"Origin Y ({un.xy()})", value=float(gp["origin"][1] if gp["origin"] else ymin), key=S.k("gc_oy"))
            lx = c.number_input(f"Length along I ({un.xy()})", 1.0, value=float(gp["extent"][0] if gp["extent"] else xmax - xmin), key=S.k("gc_lx"))
            ly = d.number_input(f"Length along J ({un.xy()})", 1.0, value=float(gp["extent"][1] if gp["extent"] else ymax - ymin), key=S.k("gc_ly"))
            origin, extent = [ox, oy], [lx, ly]
        frame = plan_axes(bounds, 1.0, 1.0, dict(angle=ang, origin=origin, extent=extent))["extent"]
        if mode == "size":
            dx = c1.number_input(f"Cell size dx ({un.xy()})", 1.0, value=float(gp["dx"]), step=25.0, key=S.k("g_dx"))
            dy = c2.number_input(f"Cell size dy ({un.xy()})", 1.0, value=float(gp["dy"]), step=25.0, key=S.k("g_dy"))
            nci, ncj = gp["ni"], gp["nj"]
        else:
            nci = int(c1.number_input("ni (cells along I)", 1, 4000, int(gp["ni"]), key=S.k("gc_ni")))
            ncj = int(c2.number_input("nj (cells along J)", 1, 4000, int(gp["nj"]), key=S.k("gc_nj")))
            dx, dy = frame[0] / nci, frame[1] / ncj
            st.caption(f"-> dx = {dx:.1f}, dy = {dy:.1f} {un.xy()}")
        st.markdown("**Local refinement** (grid-line refinement: the whole row / column strip through each window gets the finer spacing, "
                    "as in an Eclipse corner-point grid without LGR)")
        if "gc_ref0" not in st.session_state:
            st.session_state["gc_ref0"] = pd.DataFrame(gp["refine"] or [], columns=["x0", "x1", "y0", "y1", "dx", "dy"]).astype(float)
        c5, c6, c7 = st.columns([1, 1, 2])
        buf = c5.number_input(f"Buffer around faults ({un.xy()})", 0.0, value=float(gp.get("fault_buffer", 300.0)), step=50.0, key=S.k("gc_buf"))
        fd = c6.number_input(f"Refined cell size ({un.xy()})", 1.0, value=float(max(dx / 2, 1.0)), step=10.0, key=S.k("gc_fd"))
        if c7.button("Add windows around the fault traces", key=S.k("gc_addf"), disabled=not p.faults):
            rows = []
            for f in p.faults.values():
                P_ = f.points
                for q in range(len(P_) - 1):
                    seg = P_[q:q + 2]
                    rows.append(dict(x0=seg[:, 0].min() - buf, x1=seg[:, 0].max() + buf, y0=seg[:, 1].min() - buf,
                                     y1=seg[:, 1].max() + buf, dx=fd, dy=fd))
            cur = st.session_state["gc_ref0"]
            st.session_state["gc_ref0"] = pd.concat([cur, pd.DataFrame(rows[:12])], ignore_index=True)
            st.session_state["gc_ref_ver"] = st.session_state.get("gc_ref_ver", 0) + 1
            st.rerun()
        ed = st.data_editor(st.session_state["gc_ref0"], num_rows="dynamic", key=S.k("gc_ref") + str(st.session_state.get("gc_ref_ver", 0)))
        refine = [dict(x0=float(r.x0), x1=float(r.x1), y0=float(r.y0), y1=float(r.y1),
                       dx=float(r.dx) if pd.notna(r.dx) and r.dx > 0 else dx, dy=float(r.dy) if pd.notna(r.dy) and r.dy > 0 else dy)
                  for r in ed.itertuples(index=False) if pd.notna(r.x0) and pd.notna(r.x1) and pd.notna(r.y0) and pd.notna(r.y1)]
    with st.expander("Active cells (ACTNUM)", expanded=False):
        a, b, c = st.columns(3)
        mt = a.number_input(f"Min. thickness for active cell ({un.z()})", 0.0, value=float(gp["min_thickness"]), step=0.05, key=S.k("g_mt"))
        mv = b.number_input(f"Min. bulk volume ({un.xy()}\u00b2\u00b7{un.z()}, 0 = off)", 0.0, value=float(gp["min_volume"]), step=1000.0, key=S.k("gc_mv"))
        trim = c.checkbox("Inactivate cells outside the model extent", bool(gp["trim_extent"] or ang), key=S.k("gc_trim"),
                          help="Always on for rotated grids.")
        names = [z.name for z in p.zones]
        izn = st.multiselect("Zones to make inactive (e.g. over- / underburden)", names, default=[n for n in gp["inactive_zones"] if n in names],
                             key=S.k("gc_iz", names))
    with st.expander("Fault geometry - inclined pillars", expanded=False):
        a, b = st.columns(2)
        tilt = a.checkbox("Incline pillars along fault planes", bool(gp.get("tilt", False)), key=S.k("gc_tilt"), disabled=not p.faults,
                          help="Pillars near each fault are sheared by cot(dip) towards the hanging wall (faded to vertical at the radius), and every horizon is "
                               "evaluated where its own tilted pillar crosses it.")
        trad = float(b.number_input("Tilt radius (cells)", 0.5, 20.0, float(gp.get("tilt_radius", 3.0)), 0.5, key=S.k("gc_trad"), disabled=not tilt))
        st.caption("Partial implementation of key-pillar gridding: pillars follow the dipping plane near the fault instead of sitting exactly on it, so the fault "
                   "surface is only approximated by the cell faces. The shear is reduced automatically where cells would otherwise invert. "
                   "Sections and the 2D map views are drawn at the reference depth. Strike-slip faults are not tilted.")
    gp["min_thickness"] = mt
    spec = dict(angle=ang, origin=origin, extent=extent, refine=refine, trim_extent=trim, min_volume=mv, inactive_zones=izn, tilt=tilt, tilt_radius=trad)
    out["dx"], out["dy"] = dx, dy
    out["spec"] = spec
    out["store"] = dict(mode=mode, ni=nci, nj=ncj, dx=dx if mode == "size" else gp["dx"], dy=dy if mode == "size" else gp["dy"], angle=ang,
                        auto_frame=auto, origin=origin, extent=extent, refine=refine, trim_extent=trim, min_volume=mv, inactive_zones=izn,
                        min_thickness=mt, fault_buffer=buf, tilt=tilt, tilt_radius=trad)
    return out



def render():
    p = S.proj()
    g = p.grid
    banner("6 - 3D grid", (f"{g.ni} x {g.nj} x {g.nk} corner-point grid: {int(g.actnum.sum()):,} active cells in {int(g.block.max())} fault block(s)"
                           if g else "Grid the framework: vertical pillars, zone layering, stair-stepped faults"))
    render_controls(p)
    render_results(p)


def render_controls(p, build_area=None):
    if p.structure is None or not p.zones:
        note("Run the structural model (page 4) and define zones (page 5) first.", warn=True)
        return
    names = p.structure.names
    errs = validate_zones(p.zones, names)
    if errs:
        for e in errs:
            st.error(e)
        return
    bpoly = p.boundary_poly()
    use_b = False
    if bpoly is not None:
        use_b = st.checkbox(f"Apply model boundary '{p.boundary}' (trim extent, cells outside become inactive)", value=True, key=S.k("g_useb"))
    bounds = p.grid_bounds() if use_b else p.structure.geom.bounds()
    xmin, xmax, ymin, ymax = bounds
    gp = {**DEFAULT_GP, **p.grid_params}
    spec = _controls(p, gp, bounds)
    ax = plan_axes(bounds, spec["dx"], spec["dy"], spec["spec"])
    est = grid_estimate(p.zones, ax)
    ni, nj, nl = est["ni"], est["nj"], est["nk"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Columns (ni x nj)", f"{ni} x {nj}")
    k2.metric("Layers (est.)", f"{nl}")
    k3.metric("Cells (est.)", f"{est['cells'] / 1e6:.2f} M", f"~{est['mem_mb']:.0f} MB in memory")
    k4.metric(f"Cell size ({un.xy()})", f"{est['dx_min']:.0f}-{est['dx_max']:.0f} x {est['dy_min']:.0f}-{est['dy_max']:.0f}",
              f"max aspect {est['aspect_max']:.1f}")
    if est["aspect_max"] > 6:
        st.warning("Strongly elongated cells (aspect > 6) hurt simulator convergence - refine the coarse direction.")
    button_area = build_area if build_area is not None else st
    label = "Build / update 3D grid" if build_area is not None else "Build 3D grid"
    if button_area.button(label, type="primary", disabled=est["cells"] > MAX_CELLS * 1.5,
                          use_container_width=build_area is not None,
                          help="Build or update the grid using the current zone, layering and grid settings."):
        p.grid_params = {**gp, **spec["store"]}
        built = None
        try:
            with st.spinner("Building corner-point grid..."):
                built = build_grid(p.structure, p.zones, spec["dx"], spec["dy"], gp.get("min_thickness", 0.1),
                                   bounds=bounds if use_b else None, boundary=bpoly if use_b else None, spec=spec["spec"])
        except Exception as e:
            st.error(f"Grid failed: {e}")
        if built is not None:
            if built.ncells > MAX_CELLS:
                st.error(f"{built.ncells:,} cells exceeds the {MAX_CELLS:,} limit - coarsen dx/dy or reduce layers.")
            else:
                st.session_state["grid_msgs"] = p.set_grid(built)
                st.rerun()
    for m in st.session_state.pop("grid_msgs", []):
        st.info(m)


def render_results(p):
    g = p.grid
    if g is None:
        return
    sm = g.summary()
    kpis([("Cells", f"{sm['cells']:,}"), ("Active", f"{sm['active']:,}"), ("Bulk volume (Mm3)", f"{sm['bulk_volume_Mm3']:.1f}"),
          ("Fault blocks", sm["fault_blocks"]), (f"Mean dz ({un.z()})", f"{sm['mean_thickness']:.2f}")])
    t1, t2, t3 = st.tabs(["3D cut-away", "Sections", "Checks"])
    with t1:
        a, b, c, d = st.columns(4)
        popts = PROPS + [n for n in p.properties if n not in PROPS]
        prop = a.selectbox("Colour by", popts, key=S.k("g3_prop", popts))
        i0 = b.slider("Cut: start column i", 0, g.ni - 1, 0, key=S.k("g3_i"))
        j0 = c.slider("Cut: start row j", 0, g.nj - 1, 0, key=S.k("g3_j"))
        ve = d.slider("V.E.", 1.0, 20.0, 4.0, 0.5, key=S.k("g3_ve"))
        layer_mask = S.grid_view_layers(g, "g3")
        mesh = st.checkbox("Black mesh edges", value=False, key=S.k("g3_mesh"))
        opacity = st.slider("Grid opacity", 0.05, 1.0, 1.0, 0.05, key=S.k("g3_opacity"))
        from ui import display
        with st.expander("Edit property colours"):
            display.colors(p, prop, "g3")
        try:
            sc = S.build_scene(p, surfaces=[], faults=False, polygons=True, wells=True, tops=True, grid=g, prop=prop, i0=i0, j0=j0,
                               layer_mask=layer_mask, grid_opacity=opacity)
            selection = viewer3d(sc, key=S.k("grid3d"), height=660, ve=ve, mesh=mesh)
            S.grid_view_inspector(selection, p, "g3")
        except ValueError as e:
            st.warning(str(e))
        st.caption("Drag the cut sliders to open the grid and see layering and fault offsets in the walls of the cut.")
    with t2:
        a, b = st.columns([1, 3])
        axis = a.radio("Section along", ["Row (W-E)", "Column (S-N)"], key=S.k("gs_axis"))
        ax = "j" if axis.startswith("Row") else "i"
        n = g.nj if ax == "j" else g.ni
        idx = b.slider("Index", 0, n - 1, n // 2, key=S.k("gs_idx") + ax)
        plotly_view(specs.grid_section(g, idx, ax), key=S.k("gridsec") + f"{ax}{idx}{id(g)}", height=520)
        st.caption("Each outlined cell is one grid cell; offsets across a fault show the stair-stepped fault throw stored in ZCORN.")
    with t3:
        for m in g.check():
            st.write("- " + m)
        th = g.thickness()
        act = g.actnum > 0
        rows = []
        for zi, z in enumerate(g.zones):
            m = (g.layer_zone == zi)
            a_ = act[m]
            t_ = th[m][a_]
            rows.append({"Zone": z.name, "Layers": int(m.sum()), "Active cells": int(a_.sum()),
                         "Inactive (pinched)": int((~a_).sum()),
                         f"Mean dz ({un.z()})": round(float(t_.mean()), 2) if t_.size else 0.0,
                         f"Min dz ({un.z()})": round(float(t_.min()), 3) if t_.size else 0.0})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        act3 = g.actnum > 0
        if act3.any():
            dxs, dys = np.diff(g.xs), np.diff(g.ys)
            DX = np.broadcast_to(dxs[None, None, :], act3.shape)[act3]
            DY = np.broadcast_to(dys[None, :, None], act3.shape)[act3]
            DZ = th[act3]
            VOL = g.bulk_volume()[act3]
            q = lambda a: [float(np.percentile(a, v)) for v in (0, 5, 50, 95, 100)]
            qc = pd.DataFrame([[round(v, 2) for v in q(DX)], [round(v, 2) for v in q(DY)], [round(v, 2) for v in q(DZ)],
                               [round(v / 1e3, 1) for v in q(VOL)], [round(v, 1) for v in q(np.maximum(DX, DY) / np.maximum(DZ, 1e-3))]],
                              index=[f"dx ({un.xy()})", f"dy ({un.xy()})", f"dz ({un.z()})", f"Bulk volume (k{un.xy()}2{un.z()})", "Aspect max(dx,dy)/dz"],
                              columns=["min", "p5", "median", "p95", "max"])
            st.markdown("**Active-cell geometry**")
            st.dataframe(qc)
        for n_ in g.notes:
            st.caption(n_)
