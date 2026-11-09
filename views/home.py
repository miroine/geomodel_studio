"""Project page: model area, demo, save / load."""
import streamlit as st

from core import project as pj
from core import units as un
from core.demo import build_demo
from core.project import Project
from core.surface import Geometry, surface_area_values
from ui import state as S
from ui.theme import banner, disclaimer, kpis, stepper, note


def _crs_panel(p):
    crs = p.crs
    st.subheader("Coordinate system and units")
    n_obj = len(p.surfaces) + len(p.wells) + len(p.faults) + len(p.polygons) + len(p.tops)
    st.caption(f"All data are stored in the project units below (XY {un.xy()}, depth {un.z()}, depth positive down). "
               "Imports convert from the units of the file; exports convert to the units you choose.")
    names = list(un.COMMON)
    cur = next((n for n, e in un.COMMON.items() if e == crs.get("epsg") and e not in (None, -1)), None)
    if cur is None:
        cur = "Local / undefined" if not crs.get("epsg") else "Other EPSG code"
    a, b, c = st.columns([3, 2, 3])
    pick = a.selectbox("Projected CRS", names, index=names.index(cur), key=S.k("crs_pick"))
    epsg = un.COMMON[pick]
    if epsg == -1:
        epsg = int(b.number_input("EPSG code", 1000, 99999, int(crs.get("epsg") or 32631), key=S.k("crs_epsg")))
    else:
        b.markdown("&nbsp;", unsafe_allow_html=True)
    c.markdown(f"<div style='padding-top:1.9rem;color:#5B6770'>{un.describe_epsg(epsg)}</div>", unsafe_allow_html=True)
    d, e, f_, g_ = st.columns(4)
    uxy = d.selectbox("XY unit", un.UNITS, index=un.UNITS.index(crs["xy_unit"]), key=S.k("crs_uxy"))
    uz = e.selectbox("Depth (Z) unit", un.UNITS, index=un.UNITS.index(crs["z_unit"]), key=S.k("crs_uz"))
    f_.selectbox("Z positive", ["down (depth, TVDSS)"], key=S.k("crs_zp"), disabled=True, help="The app always works with depth positive downward.")
    vd = g_.text_input("Vertical datum", value=crs.get("vdatum", "MSL"), key=S.k("crs_vd"))
    units_changed = (uxy, uz) != (crs["xy_unit"], crs["z_unit"])
    mode = "relabel"
    if units_changed and n_obj:
        mode = st.radio("The project already holds data - what do the numbers mean?",
                        ["convert", "relabel"], horizontal=True, key=S.k("crs_mode"),
                        format_func=lambda m: {"convert": f"Convert all stored values to the new units (e.g. {crs['z_unit']} -> {uz})",
                                               "relabel": "Do not convert - the numbers already are in the new units (fix a wrong label)"}[m])
    if st.button("Apply CRS and units", type="primary", key=S.k("crs_apply")):
        msgs = []
        if units_changed and n_obj and mode == "convert":
            msgs += un.convert_project(p, uxy, uz)
        else:
            crs["xy_unit"], crs["z_unit"] = uxy, uz
        crs["vdatum"] = vd
        crs["epsg"] = int(epsg) if epsg else None
        crs["name"] = un.describe_epsg(epsg) if epsg else "Local (undefined)"
        un.set_active(crs)
        p.invalidate()
        st.success(" ".join(msgs) or "CRS and units set.")
        st.rerun()
    with st.expander("Reproject the whole project to another CRS"):
        src = crs.get("epsg")
        t_names = [n for n in names if un.COMMON[n] not in (None, -1)]
        tgt = st.selectbox("Target CRS", t_names, key=S.k("rp_tgt"))
        ok, how = un.can_reproject(src, un.COMMON[tgt])
        if not src:
            st.info("Set the current CRS first (it is undefined).")
        elif ok:
            st.caption(f"Engine: {how}. Surfaces are resampled on a new unrotated lattice; the workflow has to be re-run.")
        else:
            st.warning(how)
        if st.button("Reproject project", disabled=not ok, key=S.k("rp_go")):
            try:
                msgs = un.reproject_project(p, int(un.COMMON[tgt]))
                st.success(" ".join(msgs))
                st.rerun()
            except un.ReprojectionError as ex_:
                st.error(str(ex_))
        st.caption("Without pyproj only WGS84 / ETRS89 UTM zones are supported (datum differences below about 1 m are ignored). "
                   "Install pyproj for all other systems, including ED50 with its datum shift.")


def render():
    p = S.proj()
    if not p.has_lattice():
        title = "Define the model area - or open the demo - to start building a geological model"
    else:
        g = p.lattice
        st_ = "grid built" if p.grid else ("framework built" if p.structure else "framework not yet built")
        title = f"{len(p.surfaces)} surfaces and {len(p.faults)} faults over {g.ncol * g.xinc / 1000:.1f} x {g.nrow * g.yinc / 1000:.1f} km - {st_}"
    banner("Project", title)
    disclaimer()
    stepper([
        ("1 · Inputs", "Maps, faults, wells and picks", bool(p.surfaces or p.faults or p.wells or not p.tops.empty)),
        ("2 · Structure", "Build and quality-check horizons", p.structure is not None),
        ("3 · Grid", "Define zones and build cells", p.grid is not None),
        ("4 · Review", "Inspect, analyze and export", p.grid is not None),
    ])
    n_act = int(p.grid.actnum.sum()) if p.grid else 0
    kpis([("Surfaces", len(p.surfaces)), ("Polygons", len(p.polygons)), ("Faults", len(p.faults)), ("Wells", len(p.wells)),
          ("Well tops", len(p.tops)), ("Workflow steps", len(p.steps)), ("Zones", len(p.zones)), ("Active cells", f"{n_act:,}" if p.grid else "-")])

    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        st.subheader("Model area")
        if p.surfaces:
            names = list(p.surfaces)
            source = st.selectbox("Surface for model area", names, key=S.k("area_surface", names))
            st.caption("Load a surface's full grid extent in project XY units, then review and set the model area. "
                       "Rotated surfaces use their north-up bounding rectangle; their CRS is not inferred.")
            if st.button("Load area from surface", key=S.k("area_from_surface")):
                try:
                    area = surface_area_values(p.surfaces[source].geom)
                except ValueError as exc:
                    st.error(f"Cannot use surface for model area: {exc}")
                else:
                    for key, value in zip(("lx0", "lx1", "ly0", "ly1", "ldx", "ldy"), area):
                        st.session_state[S.k(key)] = float(value)
                    st.rerun()
        g = p.lattice
        d = (g.xori, g.xori + (g.ncol - 1) * g.xinc, g.yori, g.yori + (g.nrow - 1) * g.yinc, g.xinc, g.yinc) if g else (0.0, 10000.0, 0.0, 8000.0, 100.0, 100.0)
        a, b, c = st.columns(3)
        xmin = a.number_input("X min", value=float(d[0]), key=S.k("lx0"), format="%.12f")
        xmax = b.number_input("X max", value=float(d[1]), key=S.k("lx1"), format="%.12f")
        dx = c.number_input(f"dx ({un.xy()})", value=float(d[4]), min_value=1e-12, key=S.k("ldx"), format="%.12f")
        a, b, c = st.columns(3)
        ymin = a.number_input("Y min", value=float(d[2]), key=S.k("ly0"), format="%.12f")
        ymax = b.number_input("Y max", value=float(d[3]), key=S.k("ly1"), format="%.12f")
        dy = c.number_input(f"dy ({un.xy()})", value=float(d[5]), min_value=1e-12, key=S.k("ldy"), format="%.12f")
        ncol = int(round((xmax - xmin) / dx)) + 1
        nrow = int(round((ymax - ymin) / dy)) + 1
        st.caption(f"Lattice: {ncol} x {nrow} nodes ({ncol * nrow:,}). All horizons are evaluated on this lattice; "
                   "the 3D grid can use a different (coarser or finer) cell size later.")
        if st.button("Set model area", type="primary", disabled=(xmax <= xmin or ymax <= ymin or ncol * nrow > 400_000)):
            p.lattice = Geometry.from_bounds(xmin, xmax, ymin, ymax, dx, dy)
            p.invalidate()
            st.success("Model area set. Existing surfaces are resampled on the fly.")
            st.rerun()
        if ncol * nrow > 400_000:
            st.error("Lattice too large for interactive use (> 400 000 nodes).")
    with c2:
        st.subheader("Project")
        p.name = st.text_input("Name", value=p.name, key=S.k("pname"))
        if st.button("Open demo project (synthetic anticline, 2 faults, 5 wells)"):
            S.replace_project(build_demo())
            st.rerun()
        up = st.file_uploader("Open saved project (.gmsz)", type=["gmsz", "zip"], key=S.k("pup"))
        if up is not None and st.session_state.get("done_up") != (up.name, up.size):
            st.session_state["done_up"] = (up.name, up.size)
            newp = None
            try:
                newp = pj.from_bytes(up.getvalue())
            except Exception as e:
                st.error(f"Could not read project: {e}")
            if newp is not None:
                S.replace_project(newp)
                st.rerun()
        if p.has_lattice():
            st.download_button("Save project (.gmsz)", pj.to_bytes(p), file_name=f"{p.name.replace(' ', '_')}.gmsz",
                               mime="application/zip")
        if st.button("New empty project"):
            S.replace_project(Project())
            st.rerun()

    _crs_panel(p)

    with st.expander("How this app models structure (read once)"):
        st.markdown("""
**Workflow** &nbsp; The ribbon at the top follows the modelling process: *Project* -> *Input data* (surfaces, polygons, faults, wells, tops) -> *Structural framework* -> *Gridding* (zones, layering, 3D grid) -> *Property modelling* -> *Volumetrics* -> *Analysis & QC* -> *Export*. The tools of the selected domain appear under the ribbon. The left panel has **Input** and **Models** object trees (like the Petrel / RMS data tree; click an object to open it) and a numbered **Processes** flow with the status of each stage. Every page has a **Guide** panel with step-by-step instructions (also in the `docs/` folder), and the status bar at the bottom shows the project, CRS, units and build state. The **3D window** shows all objects together.

**Surface filters** are non-destructive: each surface keeps its raw map and an ordered, editable stack of operations (clip by polygon, value range, spikes, slopes, hole filling) with undo / redo and presets. A **model boundary** polygon trims the grid extent and switches off cells outside it.

**Depth maps** are regular grids, depth positive downward (metres). Import ASCII/IRAP maps, grid XYZ points, digitize a scanned map, or generate a concept surface.

**Faults** are map-view traces with dip, hanging-wall side, throw profile along strike (elliptical, triangular, plateau, constant), drag-zone width and optional growth with depth.
Four fault models: *normal*, *reverse*, *strike-slip* (lateral slip, dextral / sinistral) and *transverse* (transfer / scissor fault whose throw changes sign about a pivot). By default throw is a *vertical separation* (horizons offset exactly by the throw at the trace, tapering to zero at the tips); set **heave** > 0 to also translate horizons sideways by throw / tan(dip).

**Structural workflow** &nbsp; each horizon is a *surface*, an *isochore* (constant, trend or map thickness) from another horizon, optionally calibrated to well tops with a smooth residual field (so the update never fights the faults) and smoothed.
Horizons carry a role: *conformable*, *erosional* (truncates everything below, e.g. an unconformity) or *base-lap* (truncates everything above). Horizons can never cross.

**Zones** can be modelled one by one with *Zone* steps (own thickness model, smoothing, thickness limits, tops calibration and layering). **Properties** are cell arrays linked to the grid (populate from zones, or compute with the sandboxed Python calculator) and are exported in the GRDECL.

**Layering** per zone: proportional, follow top, follow base, or user fractions - as in Petrel/RMS. **Gridding** builds a vertical-pillar corner-point grid; faults are stair-stepped (each cell column belongs to a fault block and carries that block's depths), exactly how GRDECL stores faults.
""")
    from ui.theme import footer
    footer()
