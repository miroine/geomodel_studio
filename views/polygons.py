"""Polygons: digitize or import outlines (model boundary, licence, clip areas) and use them to clip surfaces."""
import numpy as np
import streamlit as st
from core import units as un

from core import polygons as pg, filters as flt
from core.polygons import Polygon
from ui import state as S
from views.surfaces import _file_units
from ui import specs
from ui.components import map_editor, plotly_view
from ui.theme import banner, kpis, note


def _apply_set(p, polys: dict, boundary):
    """Replace the polygon set; keep filters pointing at renamed / removed polygons consistent."""
    p.polygons = polys
    p.boundary = boundary if boundary in polys else None
    for name, stt in p.filters.items():
        for op in stt["ops"]:
            if op["type"] == "polygon" and op.get("polygon") not in polys:
                op["enabled"] = False
    p.recompute_all()
    p.invalidate()


def _digitize(p):
    if not S.need_lattice(p):
        return
    g = p.lattice
    xmin, xmax, ymin, ymax = g.bounds()
    names = list(p.surfaces)
    grid = None
    if names:
        bg = st.selectbox("Backdrop surface", ["(none)"] + names, index=1, key=S.k("poly_bg", names))
        if bg != "(none)":
            Z = S.lattice_surface(p, bg, fill=False)
            if np.isfinite(Z).any():
                grid = dict(x0=g.xori, y0=g.yori, dx=g.xinc, dy=g.yinc, ncol=g.ncol, nrow=g.nrow, z=Z,
                            zmin=float(np.nanmin(Z)), zmax=float(np.nanmax(Z)))
    wells = [dict(name=w.name, x=w.x, y=w.y) for w in p.wells.values()]
    val = map_editor("polygons", key=S.k("poly_ed"), height=660, grid=grid, extent=[xmin, xmax, ymin, ymax], wells=wells,
                     polygons=[q.to_dict() for q in p.polygons.values()], boundary=p.boundary,
                     nonce_tag=st.session_state.get("nonce_poly", 0))
    if val and val.get("kind") == "polygons" and val.get("nonce") != st.session_state.get("nonce_poly_seen"):
        st.session_state["nonce_poly_seen"] = val["nonce"]
        polys = {}
        for d in val["polygons"]:
            nm, k = d["name"] or "Polygon", 2
            base = nm
            while nm in polys:
                nm = f"{base}_{k}"
                k += 1
            if len(d["pts"]) >= 3:
                polys[nm] = Polygon(nm, [[float(a), float(b)] for a, b in d["pts"]])
        _apply_set(p, polys, val.get("boundary"))
        st.session_state["nonce_poly"] = st.session_state.get("nonce_poly", 0) + 1
        st.rerun()
    st.caption("Draw a closed outline around the area you want to keep, tick *Use as model boundary*, press **Apply to project**, "
               "then clip the surfaces in the Library tab or on the Surfaces page (Filter & clip).")


def _library(p):
    if not p.polygons:
        note("No polygons yet. Digitize one on the map, or import an XY / GeoJSON file in the next tab.")
        return
    nb = p.boundary_poly()
    kpis([("Polygons", len(p.polygons)), ("Model boundary", p.boundary or "none"),
          ("Boundary area (km²)", f"{nb.area() / 1e6:.2f}" if nb else "-")])
    rows = []
    for n, q in p.polygons.items():
        x0, x1, y0, y1 = q.bounds()
        users = [s for s, stt in p.filters.items() for o in stt["ops"] if o["type"] == "polygon" and o.get("polygon") == n and o.get("enabled", True)]
        rows.append({"Polygon": n, "Vertices": len(q.pts), "Area km²": round(q.area() / 1e6, 3), "X range": f"{x0:.0f} .. {x1:.0f}",
                     "Y range": f"{y0:.0f} .. {y1:.0f}", "Boundary": "yes" if n == p.boundary else "", "Clips": ", ".join(sorted(set(users)))})
    import pandas as pd
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    names = list(p.polygons)
    c1, c2 = st.columns([2, 3])
    with c1:
        cur = ["(none)"] + names
        idx = cur.index(p.boundary) if p.boundary in cur else 0
        b = st.selectbox("Model boundary", cur, index=idx, key=S.k("poly_bsel", cur) + f"_{p.boundary}")
        nb_ = None if b == "(none)" else b
        if nb_ != p.boundary:
            p.boundary = nb_
            p.invalidate("grid")
            st.rerun()
        st.caption("The boundary switches off grid cells outside it (ACTNUM = 0) and trims the grid extent.")
        sel = S.pick("Polygon", names, "poly_sel", "polygon")
        st.markdown("**Clip surfaces to this polygon**")
        tg = st.multiselect("Surfaces", list(p.surfaces), default=list(p.surfaces), key=S.k("poly_tg", list(p.surfaces)))
        keep = st.radio("Keep", ["inside", "outside"], horizontal=True, key=S.k("poly_keep"))
        buf = st.number_input(f"Buffer ({un.xy()})", value=0.0, step=100.0, key=S.k("poly_buf"))
        if st.button("Add clip to selected surfaces", type="primary", disabled=not tg, key=S.k("poly_clip")):
            for t in tg:
                ops = [dict(o) for o in p.fstate(t)["ops"]]
                ops.append(flt.default_op("polygon", polygon=sel, keep=keep, buffer=float(buf)))
                p.commit_filter(t, ops)
            st.success(f"Clip added to {len(tg)} surface(s). Undo it per surface in Filter & clip.")
            st.rerun()
        if st.button("Delete polygon", key=S.k("poly_del")):
            polys = {k: v for k, v in p.polygons.items() if k != sel}
            _apply_set(p, polys, p.boundary)
            st.rerun()
    with c2:
        ref = [w for w in p.wells.values()]
        plotly_view(specs.plan_view(p.lattice, p.polygons, p.boundary, list(p.faults.values()), ref, title="Plan view"), key=S.k("poly_plan"), height=430)


def _import(p):
    st.markdown("**XY text** (X Y per line; a blank line, a `>` line or a text line starts the next polygon - Petrel / RMS / generic export) "
                "or **GeoJSON** (Polygon / MultiPolygon), or **RMS .POL / .rmspolygons** (X Y Z, "
                "separated by `999 999 999`). Z values are ignored.")
    st.caption("Import adds separate polygon objects; surfaces are only clipped when you explicitly add a clip.")
    fxp, _ = _file_units("poly", p, z_sign=False)
    up = st.file_uploader("Polygon files", accept_multiple_files=True, key=S.k("poly_up"))
    for f in up or []:
        with st.container(border=True):
            st.markdown(f"**{f.name}**")
            try:
                ext = f.name.rsplit(".", 1)[-1].lower()
                parser = pg.parse_rms_pol if ext in ("pol", "rmspolygons") else pg.parse
                found = parser(f.getvalue(), default_name=f.name.rsplit(".", 1)[0])
            except (ValueError, UnicodeError, KeyError, TypeError) as e:
                st.error(f"Could not read: {e}")
                continue
            st.caption(", ".join(f"{n} ({len(q.pts)} pts)" for n, q in found.items()))
            asb = st.checkbox("Use the first polygon as model boundary", value=not p.boundary, key=S.k(f"poly_asb_{f.name}"))
            if st.button("Add to project", type="primary", key=S.k(f"poly_add_{f.name}")):
                polys = dict(p.polygons)
                first = None
                for n, q in found.items():
                    nm, k = n, 2
                    while nm in polys:
                        nm = f"{n}_{k}"
                        k += 1
                    polys[nm] = Polygon(nm, [[a * fxp, b * fxp] for a, b in q.pts])
                    first = first or nm
                previous_boundary = p.boundary
                p.polygons = polys
                p.boundary = first if asb else previous_boundary
                if p.boundary != previous_boundary:
                    p.invalidate("grid")
                st.session_state["nonce_poly"] = st.session_state.get("nonce_poly", 0) + 1
                st.success(f"Added {len(found)} polygon(s).")
    if p.polygons:
        st.download_button("Export all polygons (XY text)", pg.to_text(p.polygons), file_name="polygons.xy", mime="text/plain", key=S.k("poly_dl"))


def render():
    p = S.proj()
    n = len(p.polygons)
    banner("Polygons", f"{n} polygon{'s' if n != 1 else ''}" + (f" - model boundary: {p.boundary}" if p.boundary else " - no model boundary set")
           if n else "Outline the area of interest: digitize or import a boundary polygon, then clip the surfaces to it")
    t1, t2, t3 = st.tabs(["Library & boundary", "Digitize (JavaScript)", "Import / export"])
    with t1:
        _library(p)
    with t2:
        _digitize(p)
    with t3:
        _import(p)
