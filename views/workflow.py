"""Structural model: ordered workflow of steps, run, QC (3D, maps, cross-sections)."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core import extrap, interp, fence as fc
from core.polygons import Polygon
from core.workflow import (ROLES, STEP_TYPES, FILL_MODES, ZONE_MODES, WorkflowError, describe, run_workflow, tops_misfit, layer_fractions,
                           zone_qc, zonespecs_from_structure)
from ui import state as S
from ui import specs
from ui.components import map_editor, plotly_view, viewer3d
from ui.theme import banner, kpis, note

TYPE_LABEL = {"zone": "Zone (modelled separately)", "surface": "Horizon from surface", "isochore": "Horizon from isochore", "calibrate": "Calibrate to well tops",
              "smooth": "Smooth horizon", "faults": "Apply faults",
              "proportional": "Horizon between two horizons (proportional)", "layers": "Layers between two horizons", "clip": "Clip horizon to a depth window"}
METHODS = ["shift"] + [m for m in interp.METHODS if m != "nearest"]


def _extension(out, d, kk):
    """How a map is brought onto the model lattice and extended beyond its own coverage."""
    with st.expander("Interpolation onto the model lattice and extension beyond the map", expanded=False):
        c1, c2 = st.columns(2)
        out["resample"] = c1.selectbox("Resample map", ["linear", "cubic"], index=_idx(["linear", "cubic"], d.get("resample", "linear")), key=kk("rs"),
                                       help="Bilinear never overshoots; cubic is smoother when the lattice is finer than the map.")
        out["fill"] = c2.selectbox("Where the map is undefined / outside", FILL_MODES, index=_idx(FILL_MODES, d.get("fill", "nearest")), key=kk("fl"),
                                   format_func=lambda m: m)
        st.caption(extrap.MODE_INFO[out["fill"]])
        a, b, c = st.columns(3)
        out["fill_length"] = a.number_input(f"Decay / damping length ({un.xy()}, 0 = auto)", 0.0, value=float(d.get("fill_length", 0.0)),
                                            step=500.0, key=kk("fln"), disabled=out["fill"] not in ("decay", "gradient"))
        out["fill_value"] = b.number_input(f"Constant depth ({un.z()})", value=float(d.get("fill_value", 0.0)), key=kk("flv"),
                                           disabled=out["fill"] != "constant")
        out["fill_tension"] = c.slider("Tension", 0.0, 1.0, float(d.get("fill_tension", 0.0)), 0.05, key=kk("flt"),
                                       disabled=out["fill"] != "min_curvature")
    return out


def _defined_horizons(p, exclude_id=None):
    out = []
    for s in p.steps:
        if s["type"] in ("surface", "isochore", "proportional", "zone") and s.get("_id") != exclude_id and s["horizon"] not in out:
            out.append(s["horizon"])
        elif s["type"] == "layers" and s.get("_id") != exclude_id:
            for h in _layer_names(p, s):
                if h not in out:
                    out.append(h)
    return out


def _layer_names(p, s):
    """Names of the horizons a 'layers' step creates (fraction styles are known up front; dz styles from the last run)."""
    pre = s.get("prefix") or "Layer"
    if s.get("style", "proportional") in ("proportional", "fractions"):
        return [f"{pre}_{i}" for i in range(1, len(layer_fractions(s)) + 1)]
    return [h for h in (p.structure.names if p.structure else []) if h.startswith(pre + "_")]


def _layer_horizon_set(p):
    out = set()
    for s in p.steps:
        if s["type"] == "layers":
            out.update(_layer_names(p, s))
    return out


def _idx(opts, v, default=0):
    return opts.index(v) if v in opts else default


def step_form(kind, d, uid, p):
    """Render the fields of one step type; returns the dict of values."""
    kk = lambda f, o=None: S.k(f"{uid}_{f}", o)
    out = dict(type=kind)
    if kind == "surface":
        names = list(p.surfaces)
        out["horizon"] = st.text_input("Horizon name", value=d.get("horizon", names[0] if names else ""), key=kk("h"))
        out["surface"] = st.selectbox("Source surface", names, index=_idx(names, d.get("surface")), key=kk("s", names))
        c1, c2 = st.columns(2)
        out["shift"] = c1.number_input(f"Constant shift ({un.z()})", value=float(d.get("shift", 0.0)), key=kk("sh"))
        out["role"] = c2.selectbox("Role", ROLES, index=_idx(ROLES, d.get("role", "conformable")), key=kk("r"),
                                   help="erosional: truncates everything below (unconformity). baselap: truncates everything above.")
        _extension(out, d, kk)
    elif kind == "isochore":
        hs = _defined_horizons(p, d.get("_id"))
        out["horizon"] = st.text_input("New horizon name", value=d.get("horizon", "New_horizon"), key=kk("h"))
        c1, c2 = st.columns(2)
        out["ref"] = c1.selectbox("Reference horizon", hs, index=_idx(hs, d.get("ref"), len(hs) - 1 if hs else 0), key=kk("ref", hs)) if hs else ""
        out["direction"] = c2.selectbox("Placed", ["below", "above"], index=_idx(["below", "above"], d.get("direction", "below")), key=kk("dir"))
        out["mode"] = st.radio("Thickness", ["constant", "map"], horizontal=True, index=_idx(["constant", "map"], d.get("mode", "constant")), key=kk("mode"))
        if out["mode"] == "constant":
            c1, c2, c3 = st.columns(3)
            out["thickness"] = c1.number_input(f"Thickness ({un.z()})", 0.0, value=float(d.get("thickness", 50.0)), key=kk("th"))
            out["gx"] = c2.number_input(f"Trend X ({un.z()} per 1000 {un.xy()})", value=float(d.get("gx", 0.0)), key=kk("gx"))
            out["gy"] = c3.number_input(f"Trend Y ({un.z()} per 1000 {un.xy()})", value=float(d.get("gy", 0.0)), key=kk("gy"))
        else:
            names = list(p.surfaces)
            out["surface"] = st.selectbox("Thickness map (surface in library)", names, index=_idx(names, d.get("surface")), key=kk("map", names))
            _extension(out, d, kk)
        out["role"] = st.selectbox("Role", ROLES, index=_idx(ROLES, d.get("role", "conformable")), key=kk("r"))
    elif kind == "zone":
        hs = _defined_horizons(p, d.get("_id"))
        st.caption("A zone is modelled on its own: its own thickness model, smoothing, thickness limits and tops calibration, "
                   "and its own layering for the grid. Place zones top to bottom.")
        c1, c2, c3 = st.columns(3)
        out["name"] = c1.text_input("Zone name", value=d.get("name", "Zone_1"), key=kk("zn"))
        out["top"] = c2.selectbox("Top horizon", hs, index=_idx(hs, d.get("top"), len(hs) - 1 if hs else 0), key=kk("zt", hs)) if hs else ""
        out["horizon"] = c3.text_input("Base horizon (created)", value=d.get("horizon", "Base_Zone_1"), key=kk("zb"))
        out["mode"] = st.radio("Thickness model", ZONE_MODES, horizontal=True, index=_idx(ZONE_MODES, d.get("mode", "constant")), key=kk("zm"),
                               format_func=lambda m: {"constant": "Constant", "trend": "Constant + trend", "map": "Isochore map",
                                                      "surface": "Base from surface"}[m])
        if out["mode"] in ("constant", "trend"):
            a, b, c = st.columns(3)
            out["thickness"] = a.number_input(f"Thickness ({un.z()})", 0.0, value=float(d.get("thickness", 50.0)), key=kk("zth"))
            out["gx"] = b.number_input(f"Trend X ({un.z()} per 1000 {un.xy()})", value=float(d.get("gx", 0.0)), key=kk("zgx"), disabled=out["mode"] == "constant")
            out["gy"] = c.number_input(f"Trend Y ({un.z()} per 1000 {un.xy()})", value=float(d.get("gy", 0.0)), key=kk("zgy"), disabled=out["mode"] == "constant")
            if out["mode"] == "constant":
                out["gx"] = out["gy"] = 0.0
        else:
            names = list(p.surfaces)
            out["surface"] = st.selectbox("Surface in library", names, index=_idx(names, d.get("surface")), key=kk("zs", names))
            if out["mode"] == "surface":
                out["shift"] = st.number_input(f"Constant shift ({un.z()})", value=float(d.get("shift", 0.0)), key=kk("zsh"))
            _extension(out, d, kk)
        a, b, c = st.columns(3)
        out["smooth"] = a.slider("Smooth base (sigma, 0 = off)", 0.0, 10.0, float(d.get("smooth", 0.0)), 0.5, key=kk("zsm"))
        out["tmin"] = b.number_input(f"Min. thickness ({un.z()})", 0.0, value=float(d.get("tmin") or 0.0), key=kk("ztn"))
        out["tmax"] = c.number_input(f"Max. thickness ({un.z()}, 0 = none)", 0.0, value=float(d.get("tmax") or 0.0), key=kk("ztx"))
        labels = sorted(p.tops["horizon"].unique()) if not p.tops.empty else []
        out["calibrate"] = st.checkbox("Calibrate the zone base to well tops", value=bool(d.get("calibrate", False)), key=kk("zc"), disabled=not labels)
        if out["calibrate"]:
            a, b = st.columns(2)
            out["label"] = a.selectbox("Tops name", labels, index=_idx(labels, d.get("label", out["horizon"])), key=kk("zlab", labels))
            out["method"] = b.selectbox("Residual interpolation", METHODS, index=_idx(METHODS, d.get("method", "min_curvature")), key=kk("zcm"))
            a, b, c = st.columns(3)
            out["radius"] = a.number_input(f"Radius ({un.xy()}, 0 = global)", 0.0, value=float(d.get("radius", 3000.0)), step=250.0, key=kk("zcr"))
            out["tension"] = b.slider("Tension", 0.0, 1.0, float(d.get("tension", 0.3)), 0.05, key=kk("zct"))
            out["smoothing"] = c.slider("Smoothing", 0.0, 1.0, float(d.get("smoothing", 0.0)), 0.05, key=kk("zcs"))
        st.markdown("**Layering for the grid**")
        a, b, c, e = st.columns(4)
        out["role"] = a.selectbox("Role of base", ROLES, index=_idx(ROLES, d.get("role", "conformable")), key=kk("zr"))
        styles = ["proportional", "follow_top", "follow_base"]
        out["style"] = b.selectbox("Layer style", styles, index=_idx(styles, d.get("style", "proportional")), key=kk("zls"))
        out["nlayers"] = int(c.number_input("Layers", 1, 400, int(d.get("nlayers", 5)), key=kk("znl"), disabled=out["style"] != "proportional"))
        out["dz"] = float(e.number_input(f"dz ({un.z()})", 0.1, value=float(d.get("dz", 10.0)), key=kk("zdz"), disabled=out["style"] == "proportional"))
    elif kind == "calibrate":
        hs = _defined_horizons(p)
        labels = sorted(p.tops["horizon"].unique()) if not p.tops.empty else []
        c1, c2 = st.columns(2)
        out["horizon"] = c1.selectbox("Horizon", hs, index=_idx(hs, d.get("horizon")), key=kk("h", hs)) if hs else ""
        out["label"] = c2.selectbox("Tops name", labels or [out["horizon"]], index=_idx(labels, d.get("label", out["horizon"])), key=kk("lab", labels))
        c1, c2 = st.columns(2)
        out["method"] = c1.selectbox("Residual interpolation", METHODS, index=_idx(METHODS, d.get("method", "min_curvature")), key=kk("m"),
                                     help="shift = one bulk shift (mean residual); others interpolate the residual field")
        out["radius"] = c2.number_input(f"Influence radius ({un.xy()}, 0 = global)", 0.0, value=float(d.get("radius", 3000.0)), step=250.0, key=kk("rad"))
        c1, c2 = st.columns(2)
        out["tension"] = c1.slider("Tension", 0.0, 1.0, float(d.get("tension", 0.3)), 0.05, key=kk("t"),
                                   disabled=out["method"] not in ("min_curvature", "trend_residual"))
        out["smoothing"] = c2.slider("Smoothing", 0.0, 1.0, float(d.get("smoothing", 0.0)), 0.05, key=kk("sm"),
                                     disabled=out["method"] not in ("min_curvature", "rbf", "trend_residual"))
        if out["method"] == "kriging":
            a, b, c = st.columns(3)
            out["variogram"] = a.selectbox("Variogram", interp.VARIOGRAMS, index=_idx(interp.VARIOGRAMS, d.get("variogram", "spherical")), key=kk("vg"))
            out["vrange"] = b.number_input(f"Range ({un.xy()}, 0 = auto)", 0.0, value=float(d.get("vrange") or 0.0), step=250.0, key=kk("vr"))
            out["nugget"] = c.slider("Nugget (fraction of sill)", 0.0, 1.0, float(d.get("nugget", 0.0)), 0.05, key=kk("ng"))
            if not out["vrange"]:
                out.pop("vrange")
        elif out["method"] == "trend_residual":
            a, b = st.columns(2)
            out["trend_order"] = int(a.selectbox("Regional trend", [1, 2], index=_idx([1, 2], d.get("trend_order", 1)), key=kk("to"),
                                                 format_func=lambda v: {1: "plane", 2: "quadratic"}[v]))
            out["residual_method"] = b.selectbox("Residual method", interp.RESIDUAL_METHODS,
                                                 index=_idx(interp.RESIDUAL_METHODS, d.get("residual_method", "min_curvature")), key=kk("rm"))
    elif kind == "smooth":
        hs = _defined_horizons(p)
        out["horizon"] = st.selectbox("Horizon", hs, index=_idx(hs, d.get("horizon")), key=kk("h", hs)) if hs else ""
        out["sigma"] = st.slider("Gaussian sigma (cells)", 0.5, 10.0, float(d.get("sigma", 2.0)), 0.5, key=kk("sg"))
    elif kind == "proportional":
        hs = _defined_horizons(p, d.get("_id"))
        out["horizon"] = st.text_input("New horizon name", value=d.get("horizon", "Mid_horizon"), key=kk("h"))
        if len(hs) < 2:
            st.warning("Define at least two horizons first.")
            out["top"], out["base"] = (hs + ["", ""])[:2]
        else:
            c1, c2 = st.columns(2)
            out["top"] = c1.selectbox("Upper horizon", hs, index=_idx(hs, d.get("top"), 0), key=kk("pt", hs))
            out["base"] = c2.selectbox("Lower horizon", hs, index=_idx(hs, d.get("base"), len(hs) - 1), key=kk("pb", hs))
        out["fraction"] = st.slider("Position between them (0 = upper, 1 = lower)", 0.0, 1.0, float(d.get("fraction", 0.5)), 0.05, key=kk("pf"))
        out["role"] = st.selectbox("Role", ROLES, index=_idx(ROLES, d.get("role", "conformable")), key=kk("r"))
    elif kind == "layers":
        hs = _defined_horizons(p, d.get("_id"))
        if len(hs) < 2:
            st.warning("Define at least two horizons first.")
            out["top"], out["base"] = (hs + ["", ""])[:2]
        else:
            c1, c2 = st.columns(2)
            out["top"] = c1.selectbox("Upper horizon", hs, index=_idx(hs, d.get("top"), 0), key=kk("lt", hs))
            out["base"] = c2.selectbox("Lower horizon", hs, index=_idx(hs, d.get("base"), len(hs) - 1), key=kk("lb", hs))
        styles = ["proportional", "fractions", "follow_top", "follow_base"]
        out["style"] = st.radio("Layering", styles, horizontal=True, index=_idx(styles, d.get("style", "proportional")), key=kk("ls"),
                                format_func=lambda x: {"proportional": "N equal layers", "fractions": "Custom fractions",
                                                       "follow_top": "Constant thickness from top", "follow_base": "Constant thickness from base"}[x])
        out["prefix"] = st.text_input("Name prefix (Prefix_1, Prefix_2 ...)", value=d.get("prefix", "Layer"), key=kk("lp"))
        if out["style"] == "proportional":
            out["n"] = int(st.number_input("Number of layers (creates n-1 horizons)", 2, 100, int(d.get("n", 4)), key=kk("ln")))
        elif out["style"] == "fractions":
            txt = st.text_input("Fractions between 0 and 1 (comma separated, top = 0)", value=", ".join(f"{f:g}" for f in d.get("fractions", [0.25, 0.5, 0.75])), key=kk("lf"))
            try:
                out["fractions"] = [float(t) for t in txt.replace(";", ",").split(",") if t.strip()]
            except ValueError:
                st.error("Fractions must be numbers.")
                out["fractions"] = d.get("fractions", [0.5])
        else:
            out["dz"] = float(st.number_input(f"Layer thickness ({un.z()})", 0.1, value=float(d.get("dz", 10.0)), step=1.0, key=kk("ldz"),
                                              help="Layers pinch out against the opposite horizon (zero-thickness intervals)."))
        st.caption("Place this step after any calibration of the two bounding horizons, so the layers follow the calibrated surfaces. "
                   "At most 200 intermediate horizons.")
        out["role"] = "conformable"
    elif kind == "clip":
        hs = _defined_horizons(p)
        out["horizon"] = st.selectbox("Horizon", hs, index=_idx(hs, d.get("horizon")), key=kk("h", hs)) if hs else ""
        c1, c2 = st.columns(2)
        out["zmin"] = c1.number_input(f"Shallowest allowed ({un.z()})", value=float(d.get("zmin", 0.0)), key=kk("zl"))
        out["zmax"] = c2.number_input(f"Deepest allowed ({un.z()})", value=float(d.get("zmax", 5000.0)), key=kk("zh"))
    elif kind == "faults":
        names = list(p.faults)
        out["faults"] = st.multiselect("Active faults", names, default=[n for n in d.get("faults", names) if n in names], key=kk("f", names))
    return out


def _steps_ui(p):
    S.ensure_step_ids(p)
    if not p.steps:
        note("The workflow is empty. Add steps below, or start from all library surfaces.")
        if p.surfaces and st.button("Start with all surfaces as horizons"):
            from core.workflow import default_steps
            p.steps = default_steps(list(p.surfaces))
            S.ensure_step_ids(p)
            S.sync_fault_step(p)
            p.invalidate()
            st.rerun()
    changed = False
    for i, s in enumerate(p.steps):
        uid = s["_id"]
        c0, c1, c2, c3, c4 = st.columns([0.5, 9, 0.6, 0.6, 0.6])
        c0.markdown(f"**{i + 1}**")
        c1.markdown(describe(s))
        if c2.button("▲", key=S.k(f"up{uid}"), disabled=i == 0):
            p.steps[i - 1], p.steps[i] = p.steps[i], p.steps[i - 1]
            changed = True
        if c3.button("▼", key=S.k(f"dn{uid}"), disabled=i == len(p.steps) - 1):
            p.steps[i + 1], p.steps[i] = p.steps[i], p.steps[i + 1]
            changed = True
        if c4.button("✕", key=S.k(f"rm{uid}")):
            p.steps.pop(i)
            changed = True
        if changed:
            break
        with st.expander("edit", expanded=False):
            new = step_form(s["type"], s, uid, p)
            if st.button("Update step", key=S.k(f"upd{uid}")):
                s.update(new)
                changed = True
    if changed:
        p.invalidate()
        st.rerun()

    st.markdown("##### Add a step")
    kind = st.selectbox("Step type", STEP_TYPES, format_func=lambda x: TYPE_LABEL[x], key=S.k("new_kind"))
    if kind in ("surface", "isochore") and not p.surfaces:
        st.warning("Add surfaces to the library first.")
        return
    with st.container(border=True):
        new = step_form(kind, {}, "new_" + kind, p)
        if st.button("Add step", type="primary", key=S.k("add_step")):
            new["_id"] = S.new_id()
            if kind == "faults":
                p.steps = [x for x in p.steps if x["type"] != "faults"]
                p.steps.insert(0, new)
            else:
                p.steps.append(new)
            p.invalidate()
            st.rerun()


def _fence_editor(p):
    g = p.lattice
    xmin, xmax, ymin, ymax = g.bounds()
    st_ = p.structure
    Zb = st_.lattice_depths()[0] if st_ is not None else None
    grid = None
    if Zb is not None and np.isfinite(Zb).any():
        grid = dict(x0=g.xori, y0=g.yori, dx=g.xinc, dy=g.yinc, ncol=g.ncol, nrow=g.nrow, z=Zb,
                    zmin=float(np.nanmin(Zb)), zmax=float(np.nanmax(Zb)))
    wells = [dict(name=w.name, x=w.x, y=w.y) for w in p.wells.values()]
    if not wells and not p.tops.empty:
        wells = [dict(name=w, x=float(r.x), y=float(r.y)) for w, r in p.tops.groupby("well").first().iterrows()]
    val = map_editor("fences", key=S.k("fence_ed"), height=560, grid=grid, extent=[xmin, xmax, ymin, ymax], wells=wells,
                     polygons=[q.to_dict() for q in p.fences.values()], nonce_tag=st.session_state.get("nonce_fence", 0))
    if val and val.get("kind") == "fences" and val.get("nonce") != st.session_state.get("nonce_fence_seen"):
        st.session_state["nonce_fence_seen"] = val["nonce"]
        new = {}
        for d in val["polygons"]:
            nm, k = d["name"] or "Fence", 2
            base = nm
            while nm in new:
                nm = f"{base}_{k}"
                k += 1
            if len(d["pts"]) >= 2:
                new[nm] = Polygon(nm, [[float(a), float(b)] for a, b in d["pts"]])
        p.fences = new
        st.session_state["nonce_fence"] = st.session_state.get("nonce_fence", 0) + 1
        st.rerun()


def _section_points(p, mode):
    """Polyline (list of (x, y)) for the chosen section mode."""
    g = p.lattice
    xmin, xmax, ymin, ymax = g.bounds()
    if mode == "West - East":
        y = st.slider(f"Northing ({un.xy()})", float(ymin), float(ymax), float((ymin + ymax) / 2), float(g.yinc), key=S.k("sec_y"))
        return [(xmin, y), (xmax, y)]
    if mode == "South - North":
        x = st.slider(f"Easting ({un.xy()})", float(xmin), float(xmax), float((xmin + xmax) / 2), float(g.xinc), key=S.k("sec_x"))
        return [(x, ymin), (x, ymax)]
    if mode == "Drawn fence":
        if not p.fences:
            note("No fence yet - open <b>Draw / edit fences</b> above, click along the line you want, double-click to finish, then <b>Apply to project</b>.", warn=True)
            return None
        nm = st.selectbox("Fence", list(p.fences), key=S.k("sec_fence", list(p.fences)))
        return [tuple(q) for q in p.fences[nm].pts]
    if mode == "Through wells":
        locs = {w.name: (w.x, w.y) for w in p.wells.values()}
        if not locs and not p.tops.empty:
            locs = {w: (float(r.x), float(r.y)) for w, r in p.tops.groupby("well").first().iterrows()}
        if len(locs) < 2:
            note("Needs at least two wells (Wells page or well tops).", warn=True)
            return None
        names = list(locs)
        pick = st.multiselect("Wells in order along the fence", names, default=names[:min(3, len(names))], key=S.k("sec_wells", names))
        return [locs[n] for n in pick] if len(pick) >= 2 else None
    c = st.columns(4)
    x1 = c[0].number_input("x1", value=float(xmin), key=S.k("sx1"))
    y1 = c[1].number_input("y1", value=float(ymin), key=S.k("sy1"))
    x2 = c[2].number_input("x2", value=float(xmax), key=S.k("sx2"))
    y2 = c[3].number_input("y2", value=float(ymax), key=S.k("sy2"))
    return [(x1, y1), (x2, y2)]


def _section_tab(p, st_):
    with st.expander("Draw / edit fences (polylines for cross-sections)", expanded=not p.fences):
        _fence_editor(p)
        if p.fences:
            fn = st.selectbox("Save a fence as CSV", list(p.fences), key=S.k("fence_dl", list(p.fences)))
            q = p.fences[fn]
            st.download_button("Download fence XY (CSV)", "x,y\n" + "\n".join(f"{a},{b}" for a, b in q.pts), file_name=f"{fn}.csv", key=S.k("fence_dl_btn"))
    mode = st.radio("Section line", ["Drawn fence", "Through wells", "West - East", "South - North", "Custom"], horizontal=True, key=S.k("sec_mode"))
    pts = _section_points(p, mode)
    if pts is None:
        return
    try:
        fs_ = fc.fence_section(st_, pts)
    except ValueError as e:
        st.error(str(e))
        return
    c1, c2 = st.columns(2)
    off = c1.number_input(f"Project wells within ({un.xy()} of the fence)", 0.0, value=400.0, step=100.0, key=S.k("sec_off"))
    show_wp = c2.checkbox("Well paths", True, key=S.k("sec_wp"))
    dist, Zs = fs_["dist"], fs_["Z"]
    names = fs_["names"]
    zone_of, iv_names = None, None
    if p.zones:
        zone_of, iv_names = [], []
        for k in range(len(names) - 1):
            zi = next((i for i, z in enumerate(p.zones) if z.top in names and z.base in names
                       and names.index(z.top) <= k < names.index(z.base)), None)
            zone_of.append(zi if zi is not None else k)
            iv_names.append(p.zones[zi].name if zi is not None else f"{names[k]} - {names[k + 1]}")
    tops = fc.project_tops(pts, p.tops, off)
    wps = fc.project_wells(pts, p.wells, off) if show_wp else []
    kpis([("Length", f"{dist[-1]:,.0f} {un.xy()}"), ("Vertices", len(pts)), ("Faults crossed", len(fs_["crossings"])),
          ("Tops projected", len(tops)), ("Wells near", len(wps))])
    spec = specs.section(names, dist, Zs, zone_of, iv_names, wells=tops, crossings=fs_["crossings"], vertices=list(fs_["vertex_dist"]),
                         well_paths=wps)
    plotly_view(spec, key=S.k("ressec") + str(np.round(np.asarray(pts), 1).tolist()) + str(len(p.zones)) + str(len(names)) + str(off) + str(show_wp),
                height=540)
    if fs_["crossings"]:
        st.caption("Faults crossed (distance along the fence): " + ", ".join(f"{c['name']} @ {c['dist']:.0f}" for c in fs_["crossings"]))
    st.caption("Tick the fence in the **3D horizons** tab to see this section as a curtain in 3D.")


def _results(p):
    st_ = p.structure
    g = p.lattice
    Z = st_.lattice_depths()
    th = np.diff(Z, axis=0)
    area = g.xinc * g.yinc
    kpis([("Horizons", len(st_.names)), ("Active faults", len(st_.faults)),
          ("Gross thickness (mean, m)", f"{(Z[-1] - Z[0]).mean():.0f}"),
          ("Truncated area", f"{100 * (th < 0.01).any(axis=0).mean():.1f} %"),
          ("Calibrated horizons", len(st_.calib_qc))])
    t1, t2, t3, t4, t5 = st.tabs(["3D horizons", "Maps", "Cross-section", "Log & horizon table", "Zones"])
    with t1:
        lay = _layer_horizon_set(p)
        c1, c2, c3 = st.columns([3, 1, 1])
        shown = [h for h in st_.names if h not in lay]
        sel = c1.multiselect("Horizons", st_.names, default=shown, key=S.k("r3_sel", st_.names),
                             help="Horizons created by 'layers' steps start switched off (there can be many).")
        ve = c2.slider("V.E.", 1.0, 20.0, 4.0, 0.5, key=S.k("r3_ve"))
        showf = c3.checkbox("Fault planes", True, key=S.k("r3_f"))
        fsel = []
        if p.fences:
            fsel = st.multiselect("Fence curtains (drawn in the Cross-section tab)", list(p.fences), default=[], key=S.k("r3_fen", list(p.fences)),
                                  help="Shows the cross-section along the fence as a coloured vertical curtain in the 3D window.")
        if sel or fsel:
            items = [(h, Z[st_.names.index(h)]) for h in sel] or [(st_.names[0], Z[0])]
            sc = S.scene_from_arrays(p, items, faults=st_.faults if showf else None, polygons=True, wells=True, tops=True)
            if not sel:
                for o in list(sc.objects):
                    if o.get("group") == "Surfaces":
                        sc.objects.remove(o)
            for nm in fsel:
                fs_ = fc.fence_section(st_, p.fences[nm].pts)
                sc.curtain(fs_["x"], fs_["y"], fs_["Z"], fs_["names"], name=f"Fence {nm}")
            viewer3d(sc, key=S.k("res3d"), height=640, ve=ve)
    with t2:
        c1, c2, c3 = st.columns([2, 2, 1])
        opts = [f"Depth - {h}" for h in st_.names] + [f"Thickness - {a} to {b}" for a, b in zip(st_.names[:-1], st_.names[1:])]
        choice = c1.selectbox("Map", opts, key=S.k("r2_sel", st_.names))
        wf = c2.radio("Faults in horizons", ["Faulted", "Unfaulted"], horizontal=True, key=S.k("r2_wf"))
        Zm = st_.lattice_depths(with_faults=(wf == "Faulted"))
        if choice.startswith("Depth"):
            h = choice[8:]
            spec = specs.map_2d(Zm[st_.names.index(h)], g, title=h, faults=st_.faults, wells=S.wells_for_plot(p.tops, h, False))
        else:
            k = opts.index(choice) - len(st_.names)
            spec = specs.map_2d(np.diff(Zm, axis=0)[k], g, title=choice, scale=specs.THICK_SCALE, colorbar=f"Thickness ({un.z()})", faults=st_.faults)
        plotly_view(spec, key=S.k("res2d") + choice + wf, height=560)
    with t3:
        _section_tab(p, st_)
    with t4:
        for m in st_.log:
            st.write("- " + m)
        rows = []
        for i, h in enumerate(st_.names):
            rows.append({"Horizon": h, "Role": st_.roles.get(h, "conformable"), "Min z": round(float(np.nanmin(Z[i])), 1),
                         "Mean z": round(float(np.nanmean(Z[i])), 1), "Max z": round(float(np.nanmax(Z[i])), 1)})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    with t5:
        _zones_tab(p, st_)


def _zones_tab(p, st_):
    rows = zone_qc(st_)
    if not st_.zone_defs:
        st.caption("No zone steps in the workflow - zones below are simply consecutive horizons. Add *Zone* steps to model each zone separately.")
    df = pd.DataFrame([{"Zone": r["zone"], "Top": r["top"], "Base": r["base"], f"Mean ({un.z()})": round(r["mean"], 1),
                        "Min": round(r["min"], 1), "Max": round(r["max"], 1), "Pinched %": round(r["pinched_pct"], 1),
                        "Tops RMS before": None if r["rms_before"] is None else round(r["rms_before"], 2),
                        "Tops RMS after": None if r["rms_after"] is None else round(r["rms_after"], 2)} for r in rows])
    st.dataframe(df, hide_index=True)
    if st_.zone_defs:
        if st.button("Create / update grid zones from the zone steps", type="primary", key=S.k("mkzones")):
            p.zones = zonespecs_from_structure(st_, p.zones)
            p.grid = None
            st.success(f"{len(p.zones)} grid zone(s) created - set porosity / permeability on the Zones page, layering is taken from the steps.")


def render():
    p = S.proj()
    banner("4 - Structural model",
           (f"{len(p.structure.names)} horizons and {len(p.structure.faults)} faults assembled into a consistent, non-crossing framework"
            if p.structure else "Assemble the framework: an ordered workflow of horizons, isochores, calibration and faults"))
    if not S.need_lattice(p):
        return
    left, right = st.columns([5, 4], gap="large")
    with left:
        st.subheader("Workflow")
        _steps_ui(p)
    with right:
        st.subheader("Run")
        note("Steps run top to bottom. Calibration residuals are computed against the <b>faulted</b> model and interpolated smoothly "
             "on the unfaulted base, so a correction never smears across a fault. Horizons are ordered by mean depth and can never cross.")
        if st.button("Run workflow", type="primary", disabled=not p.steps):
            try:
                with st.spinner("Building the structural framework..."):
                    p.structure = run_workflow(p.steps, p.surfaces, p.faults, p.tops, p.lattice)
                    p.grid = None
                st.success(f"Framework built: {len(p.structure.names)} horizons.")
            except WorkflowError as e:
                st.error(str(e))
                p.structure = None
        if p.structure is not None:
            for q in p.structure.calib_qc:
                st.markdown(f"**{q['horizon']}** calibrated to {q['n']} tops: RMS {q['rms_before']:.1f} {un.z()} -> {q['rms_after']:.2f} {un.z()}")
    if p.structure is not None:
        st.divider()
        _results(p)
