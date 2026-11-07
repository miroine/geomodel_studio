"""Surfaces: library, import (ASCII / IRAP via xtgeo / XYZ), JavaScript map digitizer, synthetic surfaces."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core import interp, io_surfaces
from core import project as pj
from core.faults import Fault, next_color
from core.surface import Surface, synthetic_surface
from ui import state as S
from ui import specs
from ui.components import map_editor, plotly_view, viewer3d
from ui.theme import banner, kpis, note
from views import filters as filters_view


def _save_surface(p, surface, prefix):
    st.markdown(f"**Save surface: {surface.name}**")
    formats = {"IRAP binary": "irap_binary", "IRAP ASCII": "irap_ascii", "XYZ points": "xyz"}
    label = st.selectbox("Surface file format", list(formats), key=S.k(prefix + "_format"))
    try:
        data, extension = io_surfaces.write_surface(surface, formats[label])
    except ValueError as exc:
        st.error(f"Could not save surface: {exc}")
        return
    filename = surface.name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    st.download_button("Save surface file", data, file_name=f"{filename}.{extension}",
                       mime="application/octet-stream" if formats[label] == "irap_binary" else "text/plain",
                       key=S.k(prefix + "_download"))
    st.caption(f"Exports the current surface, including applied filters, in project units: "
               f"XY {un.xy()}, depth {un.z()}, positive down. File formats do not store the project CRS.")


def _grid_options(prefix, default_method="min_curvature"):
    """Method picker with the parameters that matter for each algorithm. Returns (method, tension, smoothing, maxd, kw)."""
    c1, c2, c3, c4 = st.columns(4)
    method = c1.selectbox("Interpolation method", interp.METHODS, index=interp.METHODS.index(default_method), key=S.k(prefix + "_meth"),
                          help="Hover the caption below for what each method does")
    st.caption(interp.METHOD_INFO[method])
    tension = c2.slider("Tension", 0.0, 1.0, 0.3, 0.05, key=S.k(prefix + "_t"),
                        disabled=(method not in ("min_curvature", "trend_residual")),
                        help="0 = pure minimum curvature, 1 = membrane (no overshoot between data)")
    smoothing = c3.slider("Smoothing", 0.0, 1.0, 0.0, 0.05, key=S.k(prefix + "_s"),
                          disabled=(method not in ("min_curvature", "rbf", "trend_residual")), help="0 honours data exactly")
    maxd = c4.number_input(f"Mask beyond ({un.xy()}, 0 = none)", 0.0, value=0.0, step=100.0, key=S.k(prefix + "_d"),
                           help="Leave nodes further than this from any data point undefined (a trimmed, honest map edge)")
    kw = {}
    if method == "kriging":
        a, b, c, d, e = st.columns(5)
        kw["variogram"] = a.selectbox("Variogram", interp.VARIOGRAMS, key=S.k(prefix + "_vg"))
        kw["vrange"] = b.number_input(f"Range ({un.xy()}, 0 = auto)", 0.0, value=0.0, step=100.0, key=S.k(prefix + "_vr"))
        kw["nugget"] = c.slider("Nugget (fraction of sill)", 0.0, 1.0, 0.0, 0.05, key=S.k(prefix + "_ng"))
        kw["k"] = int(d.number_input("Neighbours", 4, 64, 16, key=S.k(prefix + "_kn")))
        kw["drift"] = int(e.selectbox("Drift (trend removed)", [0, 1, 2], format_func=lambda v: ["none", "plane", "quadratic"][v], key=S.k(prefix + "_dr")))
    elif method == "idw":
        a, b = st.columns(2)
        kw["k"] = int(a.number_input("Neighbours", 3, 64, 12, key=S.k(prefix + "_ik")))
        kw["power"] = float(b.slider("Power", 0.5, 5.0, 2.0, 0.5, key=S.k(prefix + "_ip")))
    elif method == "moving_average":
        a, b = st.columns(2)
        kw["radius"] = a.number_input(f"Kernel sigma ({un.xy()}, 0 = auto)", 0.0, value=0.0, step=100.0, key=S.k(prefix + "_mr"))
        kw["k"] = int(b.number_input("Max neighbours", 8, 128, 48, key=S.k(prefix + "_mk")))
    elif method == "local_poly":
        a, b = st.columns(2)
        kw["k"] = int(a.number_input("Neighbours", 8, 96, 24, key=S.k(prefix + "_lk")))
        kw["order"] = int(b.selectbox("Local polynomial", [1, 2], index=1, format_func=lambda v: ["", "linear (plane)", "quadratic"][v], key=S.k(prefix + "_lo")))
    elif method == "trend_residual":
        a, b = st.columns(2)
        kw["trend_order"] = int(a.selectbox("Regional trend", [1, 2], format_func=lambda v: ["", "plane", "quadratic"][v], key=S.k(prefix + "_to")))
        kw["residual_method"] = b.selectbox("Residual method", interp.RESIDUAL_METHODS, key=S.k(prefix + "_rm"))
    return method, tension, smoothing, maxd, kw


def _file_units(prefix, p, z_sign=True):
    """File-unit selectors; returns (fxy, fz, flip) taking file values to project units / depth-positive-down."""
    with st.expander("File units and depth convention", expanded=False):
        a, b, c = st.columns(3)
        uxy = a.selectbox("XY unit in file", un.UNITS, index=un.UNITS.index(p.crs["xy_unit"]), key=S.k(prefix + "_uxy"))
        uz = b.selectbox("Z unit in file", un.UNITS, index=un.UNITS.index(p.crs["z_unit"]), key=S.k(prefix + "_uz"))
        flip = False
        if z_sign:
            flip = c.radio("Z in file is", ["depth (down +)", "elevation (up +)"], key=S.k(prefix + "_zs"),
                           help="Elevation (e.g. Surfer/Petrel 'Z positive up') is multiplied by -1 so depth is positive downward.") == "elevation (up +)"
        fx, fz = un.import_factors(p.crs, uxy, uz)
        if abs(fx - 1) > 1e-12 or abs(fz - 1) > 1e-12 or flip:
            st.caption(f"Converted on import: XY x{fx:.6g}, Z x{fz * (-1 if flip else 1):.6g} (project: XY {un.xy()}, Z {un.z()}).")
    return fx, fz * (-1.0 if flip else 1.0)


def _library(p):
    if not p.surfaces:
        note("No surfaces yet. Use the other tabs to import, digitize or generate one - or open the demo from the Project page.")
        return
    st.dataframe(S.surface_table(p), hide_index=True)
    names = list(p.surfaces)
    with st.container(border=True):
        with_surface = S.pick("Surface to save", names, "lib_save_surface", "surface")
        _save_surface(p, p.surfaces[with_surface], "lib_save")
        st.download_button("Save complete project (.gmsz)", pj.to_bytes(p),
                           file_name=f"{p.name.replace(' ', '_')}.gmsz", mime="application/zip",
                           key=S.k("lib_save_project"))
        st.caption("Save the project to preserve all surfaces, raw maps, filter history and digitized contours.")
    c1, c2, c3 = st.columns([3, 1, 1])
    sel = c1.multiselect("Show", names, default=names[:min(3, len(names))], key=S.k("lib_sel", names))
    view = c2.radio("View", ["3D", "Map"], horizontal=True, key=S.k("lib_view"))
    ve = c3.slider("Vertical exaggeration", 1.0, 20.0, 4.0, 0.5, key=S.k("lib_ve")) if view == "3D" else 1.0
    from ui import display
    if sel:
        edit = st.selectbox("Surface display settings", sel, key=S.k("lib_display", sel))
        with st.expander("Edit surface depth colours"):
            display.colors(p, edit, "lib", surface=True)
    if sel and S.need_lattice(p):
        if view == "3D":
            sc = S.build_scene(p, surfaces=sel, faults=True, polygons=True, wells=True, tops=False)
            viewer3d(sc, key=S.k("lib3d"), height=620, ve=ve)
        else:
            mapped = st.selectbox("Map surface", sel, key=S.k("lib_map_surface", sel))
            z0 = p.surfaces[mapped].z
            if np.isfinite(z0).any():
                try:
                    spec = display.surface_map(p, p.surfaces[mapped], "lib", faults=p.faults.values())
                    spec["data"] += specs._poly_traces(p.polygons, p.boundary)
                    plotly_view(spec, key=S.k("lib2d"), height=560)
                except ValueError as exc:
                    st.error(f"Surface display: {exc}")
    with st.expander("Manage surfaces"):
        st.markdown("#### Duplicate with a scalar operation")
        source = st.selectbox("Source surface", names, key=S.k("lib_dup_source", names))
        c1, c2 = st.columns(2)
        new_name = c1.text_input("New surface name", value=f"{source}_copy", key=S.k(f"lib_dup_name_{source}"))
        scalar_op = c2.selectbox(
            "Scalar operation",
            ["Add constant", "Multiply by factor"],
            key=S.k("lib_dup_op"),
            help="Positive depth offsets and factors above 1 make the copied surface deeper.",
        )
        if scalar_op == "Add constant":
            value = st.number_input(f"Depth offset ({un.z()})", value=10.0, step=1.0, key=S.k(f"lib_dup_value_{source}_add"))
            operation = "add"
        else:
            value = st.number_input("Multiplier", value=1.01, step=0.01, format="%.4f", key=S.k(f"lib_dup_value_{source}_multiply"))
            operation = "multiply"
        if st.button("Create duplicate", type="primary", disabled=not new_name.strip() or new_name in p.surfaces):
            try:
                p.duplicate_surface(source, new_name, operation, float(value))
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success(f"Created '{new_name.strip()}' from '{source}'.")
                st.rerun()

        st.divider()
        st.markdown("#### Rename or delete")
        old = st.selectbox("Surface to rename", names, key=S.k("ren_sel", names))
        new = st.text_input("New name", value=old, key=S.k("ren_new"))
        if st.button("Rename") and new and new != old and new not in p.surfaces:
            p.rename_surface(old, new)
            for step in p.steps:
                if step.get("surface") == old:
                    step["surface"] = new
            p.invalidate()
            st.rerun()

        target = st.selectbox("Surface to delete", names, key=S.k("del_sel", names))
        references = [
            step for step in p.steps
            if step.get("surface") == target
        ]
        if references:
            used_by = ", ".join(
                str(step.get("horizon") or step.get("name") or step.get("type", "workflow step"))
                for step in references
            )
            st.warning(f"'{target}' is used by workflow step(s): {used_by}. Update or remove those steps before deleting it.")
        confirmed = st.checkbox("Confirm surface deletion", key=S.k(f"delete_surface_confirm_{target}"))
        if st.button("Delete surface", type="secondary", disabled=bool(references) or not confirmed):
            try:
                p.delete_surface(target)
            except ValueError as exc:
                st.error(str(exc))
            else:
                if S.focus("surface") == target:
                    st.session_state["focus"] = None
                st.rerun()


def _import(p):
    st.markdown("Supported: **ESRI/Surfer ASCII grid**, **IRAP/RMS ASCII and binary** (read with *xtgeo* when installed), "
                "and **XYZ points** (`.xyz .csv .txt .dat`; gridded onto the model lattice).")
    if io_surfaces.HAS_XTGEO:
        st.caption("xtgeo detected - IRAP files are read with xtgeo.")
    else:
        st.caption("xtgeo not installed: IRAP files use the built-in reader. `pip install xtgeo` is recommended.")
    fxy, fzz = _file_units("imp", p)
    files = st.file_uploader("Surface files", accept_multiple_files=True, key=S.k("surf_up"))
    for f in files or []:
        with st.container(border=True):
            st.markdown(f"**{f.name}**")
            try:
                kind, obj = io_surfaces.read_any(f.getvalue(), f.name)
            except Exception as e:
                st.error(f"Could not read: {e}")
                continue
            name = st.text_input("Name in library", value=f.name.rsplit(".", 1)[0], key=S.k(f"nm_{f.name}"))
            if kind == "surface":
                s = un.scale_surface(obj, fxy, fzz)
                g = s.geom
                st.caption(f"{g.ncol} x {g.nrow} nodes, dx {g.xinc:g}, dy {g.yinc:g}, rotation {g.rotation:g} deg, "
                           f"z {np.nanmin(s.z):.1f} .. {np.nanmax(s.z):.1f}")
                if st.button("Add to library", key=S.k(f"add_{f.name}"), type="primary"):
                    s.name = name
                    p.put_surface(s)
                    st.session_state[S.k(f"tmp_import_saved_{f.name}")] = name
                    st.success(f"Added {name}.")
            else:
                pts = un.scale_points(obj, fxy, fzz)
                st.caption(f"{len(pts):,} XYZ points; x {pts[:, 0].min():.0f}..{pts[:, 0].max():.0f}, y {pts[:, 1].min():.0f}..{pts[:, 1].max():.0f}, z {pts[:, 2].min():.1f}..{pts[:, 2].max():.1f}")
                if not S.need_lattice(p):
                    continue
                method, tension, smoothing, maxd, gkw = _grid_options(f"imp_{f.name}")
                if st.button("Grid points into a surface", key=S.k(f"grid_{f.name}"), type="primary"):
                    try:
                        s = interp.grid_points(pts, p.lattice, method, name=name, tension=tension, smoothing=smoothing,
                                               max_distance=maxd or None, **gkw)
                        p.put_surface(s)
                        st.session_state[S.k(f"tmp_import_saved_{f.name}")] = name
                        st.success(f"Gridded {len(pts):,} points -> {name}.")
                    except Exception as e:
                        st.error(str(e))
            saved = p.surfaces.get(st.session_state.get(S.k(f"tmp_import_saved_{f.name}")))
            if saved is not None:
                _save_surface(p, saved, f"import_save_{f.name}")


def _digitize(p):
    if not S.need_lattice(p):
        return
    note("<b>How to digitize.</b> (1) Optional: load a scanned map image and calibrate it with 2+ control points (type their X/Y). "
         "(2) Pick <i>Contour line</i>, type the depth, click along the contour, double-click to finish (auto-step raises the depth for the next line). "
         "(3) Add <i>Spot points</i> for well/pick values and <i>Fault traces</i> if the map shows faults. (4) <b>Send to Python</b>, then grid below.")
    xmin, xmax, ymin, ymax = p.lattice.bounds()
    dg = p.digitized
    val = map_editor("digitize", key=S.k("digitizer"), height=680, extent=[xmin, xmax, ymin, ymax],
                     contours=dg.get("contours"), points=dg.get("points"), traces=dg.get("faults"),
                     polygons=[poly.to_dict() for poly in p.polygons.values()], boundary=p.boundary,
                     z_default=float(dg["contours"][-1]["z"]) if dg.get("contours") else 2000.0, nonce_tag=st.session_state.get("nonce_dig", 0))
    if val and val.get("kind") == "digitize" and val.get("nonce") != st.session_state.get("nonce_dig_seen"):
        st.session_state["nonce_dig_seen"] = val["nonce"]
        p.digitized = dict(contours=val["contours"], points=val["points"], faults=val["faults"], calib=val.get("calib"))
        st.session_state["nonce_dig"] = st.session_state.get("nonce_dig", 0) + 1
        st.rerun()
    dg = p.digitized
    npts = sum(len(c["pts"]) for c in dg["contours"]) + len(dg["points"])
    kpis([("Contours", len(dg["contours"])), ("Contour vertices + spots", npts), ("Fault traces", len(dg["faults"]))])
    depths = [float(c["z"]) for c in dg["contours"] if c["pts"]] + [float(pt[2]) for pt in dg["points"]]
    if depths:
        st.caption(f"Digitized depth range: {min(depths):g} .. {max(depths):g} {un.z()}.")
        if len(set(depths)) == 1:
            st.warning("All digitized values have the same depth; gridding will produce a constant map. "
                       "Select contours in Contents, correct their depths, and Send to Python again, "
                       "or set a nonzero depth step before drawing new contours.")
    if npts < 3:
        st.caption("Send at least 3 points (or one contour) to enable gridding.")
        return
    st.markdown("##### Create a surface from the digitized data")
    c1, c2 = st.columns([1, 2])
    name = c1.text_input("Surface name", value="Digitized_map", key=S.k("dig_name"))
    step = c2.number_input(f"Densify contours every ({un.xy()})", 1.0, value=float(max(p.lattice.xinc, 25.0)), key=S.k("dig_step"))
    method, tension, smoothing, maxd, gkw = _grid_options("dig")
    cA, cB, cC = st.columns(3)
    if cA.button("Grid digitized data", type="primary"):
        pts = interp.contours_to_points(dg["contours"], step)
        if dg["points"]:
            pts = np.vstack([pts, np.asarray(dg["points"], float)]) if len(pts) else np.asarray(dg["points"], float)
        try:
            s = interp.grid_points(pts, p.lattice, method, name=name, tension=tension, smoothing=smoothing, max_distance=maxd or None, **gkw)
            s.source = f"digitized:{len(dg['contours'])}contours+{len(dg['points'])}pts"
            p.put_surface(s)
            st.session_state["tmp_dig_preview"] = name
            st.success(f"Surface '{name}' created from {len(pts):,} points.")
        except Exception as e:
            st.error(str(e))
    preview = p.surfaces.get(st.session_state.get("tmp_dig_preview"))
    if preview is not None:
        _save_surface(p, preview, "digitized_save")
        show_boundary = st.checkbox("Show model boundary on gridded map", value=True, key=S.k("dig_boundary"), disabled=not p.boundary)
        spec = specs.map_2d(preview.z, preview.geom, title=preview.name, faults=[])
        if show_boundary and p.boundary in p.polygons:
            spec["data"] += specs._poly_traces({p.boundary: p.polygons[p.boundary]}, p.boundary)
        plotly_view(spec, key=S.k("digprev"), height=420)
    if dg["faults"] and cB.button("Add fault traces to the model"):
        for t in dg["faults"]:
            nm = t["name"]
            while nm in p.faults:
                nm += "_b"
            p.faults[nm] = Fault(nm, t["pts"], throw=40.0, dip=65.0, hw_side="left", zref=float(np.mean([c["z"] for c in dg["contours"]]) if dg["contours"] else 2000.0),
                                 color=next_color(len(p.faults)))
        S.sync_fault_step(p)
        p.invalidate()
        st.success("Fault traces added - refine throw, dip and hanging-wall side on the Faults page.")
    if cC.button("Clear digitized data"):
        p.digitized = dict(contours=[], points=[], faults=[], calib=None)
        st.session_state["nonce_dig"] = st.session_state.get("nonce_dig", 0) + 1
        st.rerun()


def _synthetic(p):
    if not S.need_lattice(p):
        return
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Name", value="Synthetic_top", key=S.k("syn_name"))
    kind = c2.selectbox("Shape", ["anticline", "syncline", "plunging", "tilted", "flat"], key=S.k("syn_kind"))
    z0 = c3.number_input(f"Base depth z0 ({un.z()})", value=2000.0, key=S.k("syn_z0"))
    c1, c2, c3, c4 = st.columns(4)
    relief = c1.number_input(f"Relief ({un.z()})", value=150.0, key=S.k("syn_rel"))
    xmin, xmax, ymin, ymax = p.lattice.bounds()
    wx = c2.number_input(f"Width X ({un.xy()})", 100.0, value=float((xmax - xmin) / 4), key=S.k("syn_wx"))
    wy = c3.number_input(f"Width Y ({un.xy()})", 100.0, value=float((ymax - ymin) / 4), key=S.k("syn_wy"))
    az = c4.number_input("Azimuth (deg)", value=0.0, key=S.k("syn_az"))
    c1, c2, c3 = st.columns(3)
    dxs = c1.number_input(f"Regional dip X ({un.z()} per 1000 {un.xy()})", value=0.0, key=S.k("syn_dx"))
    dys = c2.number_input(f"Regional dip Y ({un.z()} per 1000 {un.xy()})", value=0.0, key=S.k("syn_dy"))
    noise = c3.number_input(f"Noise ({un.z()})", 0.0, value=0.0, key=S.k("syn_noise"))
    if st.button("Create surface", type="primary"):
        s = synthetic_surface(p.lattice, name, kind, z0=z0, relief=relief, width_x=wx, width_y=wy, azimuth=az,
                              dip_x=dxs, dip_y=dys, noise=noise)
        p.put_surface(s)
        st.session_state["tmp_synthetic_preview"] = name
        st.success(f"Created {name}.")
    preview = p.surfaces.get(st.session_state.get("tmp_synthetic_preview"))
    if preview is not None:
        _save_surface(p, preview, "synthetic_save")
        plotly_view(specs.map_2d(preview.z, preview.geom, title=preview.name, faults=[]), key=S.k("synprev"), height=420)


def render():
    p = S.proj()
    n = len(p.surfaces)
    banner("1 - Surfaces", f"{n} depth map{'s' if n != 1 else ''} in the library - import, digitize or generate the structural inputs"
           if n else "Start the structural framework: import a map, digitize one, or generate a concept surface")
    t1, t5, t2, t3, t4 = st.tabs(["Library & QC", "Filter & clip", "Import files", "Digitize a map (JavaScript)", "Synthetic surface"])
    with t1:
        _library(p)
    with t5:
        filters_view.render_tab(p)
    with t2:
        _import(p)
    with t3:
        _digitize(p)
    with t4:
        _synthetic(p)
