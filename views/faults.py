"""Faults: JavaScript fault designer on a depth map + parameter table + faulted-surface preview."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core.faults import Fault, next_color, FAULT_TYPE_INFO, FAULT_TYPES, PROFILES
from core import polygons as pg
from ui import state as S
from ui import specs
from ui.components import map_editor, plotly_view, viewer3d
from ui.theme import banner, kpis, note


def _import(p):
    with st.expander("Import fault traces from polygon files"):
        st.caption("RMS .POL / .rmspolygons: X Y Z with 999 999 999 separators. "
                   "XY text: X Y per line, separated by blank lines or > names. "
                   "Each part becomes a fault trace; file Z is ignored. Traces are not automatically closed. "
                   "Set their reference depth below. Existing faults and surfaces are preserved.")
        xy_unit = st.selectbox("Fault XY unit in file", un.UNITS, index=un.UNITS.index(p.crs["xy_unit"]),
                               key=S.k("fault_import_xy"))
        fxy, _ = un.import_factors(p.crs, xy_unit, p.crs["z_unit"])
        a, b, c = st.columns(3)
        ftype = a.selectbox("Imported fault type", FAULT_TYPES, key=S.k("fault_import_type"))
        throw = b.number_input(f"Imported throw ({un.z()})", min_value=0.0, value=50.0, key=S.k("fault_import_throw"))
        dip = c.number_input("Imported dip (degrees)", min_value=5.0, max_value=90.0, value=65.0, key=S.k("fault_import_dip"))
        a, b, c = st.columns(3)
        side = a.selectbox("Imported hanging-wall side", ["left", "right"], key=S.k("fault_import_hw"))
        profile = b.selectbox("Imported throw profile", PROFILES, key=S.k("fault_import_profile"))
        zref = c.number_input(f"Imported reference depth ({un.z()}, positive down)", value=2000.0, key=S.k("fault_import_zref"))
        drag = st.number_input(f"Imported drag-zone width ({un.xy()})", min_value=0.0, value=250.0, key=S.k("fault_import_drag"))
        files = st.file_uploader("Fault polygon / polyline files", accept_multiple_files=True, key=S.k("fault_import_files"))
        for upload in files or []:
            with st.container(border=True):
                st.markdown(f"**{upload.name}**")
                try:
                    ext = upload.name.rsplit(".", 1)[-1].lower()
                    parser = pg.parse_rms_pol if ext in ("pol", "rmspolygons") else pg.parse
                    found = parser(upload.getvalue(), default_name=upload.name.rsplit(".", 1)[0], closed=False)
                except (ValueError, UnicodeError, KeyError, TypeError) as exc:
                    st.error(f"Could not read fault traces: {exc}")
                    continue
                st.caption(", ".join(f"{n} ({len(q.pts)} vertices)" for n, q in found.items()))
                if st.button("Import as faults", type="primary", key=S.k(f"fault_import_add_{upload.name}")):
                    for name, line in found.items():
                        nm, index = name, 2
                        while nm in p.faults:
                            nm = f"{name}_{index}"
                            index += 1
                        p.faults[nm] = Fault(nm, [[x * fxy, y * fxy] for x, y in line.pts],
                                             ftype=ftype, throw=float(throw), dip=float(dip), hw_side=side,
                                             profile=profile, drag=float(drag), zref=float(zref),
                                             color=next_color(len(p.faults)))
                    S.sync_fault_step(p)
                    p.invalidate()
                    st.session_state["nonce_flt"] = st.session_state.get("nonce_flt", 0) + 1
                    st.success(f"Imported {len(found)} fault trace(s). Review direction and hanging-wall side in the designer.")


def faulted_surface(p, name, faults):
    Zb = S.lattice_surface(p, name)
    X, Y = p.lattice.coords()
    zm = float(np.nanmean(Zb))
    Z = Zb.copy()
    from core.surface import Surface
    smp = lambda xx, yy: Surface("b", p.lattice, Zb).sample(xx, yy, order=1, extrapolate=True)
    for f in faults:
        Z = Z + f.delta(smp, X, Y, Zb, zm)
    return Zb, Z


def render():
    p = S.proj()
    nf = len(p.faults)
    banner("2 - Faults", f"{nf} fault{'s' if nf != 1 else ''} designed on the map - set hanging-wall side, throw and dip, then preview the faulted surface"
           if nf else "Draw fault traces on a depth map and give them throw, dip and a hanging-wall side")
    _import(p)
    if not S.need_lattice(p):
        return
    if not p.surfaces:
        note("Create or import at least one surface first - it is the backdrop for fault picking.", warn=True)
        return

    names = list(p.surfaces)
    c1, c2 = st.columns([2, 3])
    bg = c1.selectbox("Backdrop surface", names, key=S.k("flt_bg", names))
    c2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    Zb = S.lattice_surface(p, bg, fill=False)       # show clipped / filtered nodes as holes
    if not np.isfinite(Zb).any():
        Zb = S.lattice_surface(p, bg)
    g = p.lattice
    grid = dict(x0=g.xori, y0=g.yori, dx=g.xinc, dy=g.yinc, ncol=g.ncol, nrow=g.nrow, z=Zb, zmin=float(np.nanmin(Zb)), zmax=float(np.nanmax(Zb)))
    xmin, xmax, ymin, ymax = g.bounds()
    zdef = float(np.nanmean(Zb))
    wells = [dict(name=w, x=float(r.x), y=float(r.y)) for w, r in p.tops.groupby("well").first().iterrows()] if not p.tops.empty else []
    val = map_editor("faults", key=S.k("fault_ed"), height=680, grid=grid, extent=[xmin, xmax, ymin, ymax],
                     faults=[f.to_dict() for f in p.faults.values()], wells=wells,
                     defaults=dict(throw=50, dip=65, zref=round(zdef, 0), profile="elliptical", drag=250),
                     nonce_tag=st.session_state.get("nonce_flt", 0))
    if val and val.get("kind") == "faults" and val.get("nonce") != st.session_state.get("nonce_flt_seen"):
        st.session_state["nonce_flt_seen"] = val["nonce"]
        new = {}
        for d in val["faults"]:
            f = Fault.from_dict(d)
            f.color = f.color or next_color(len(new))
            new[f.name] = f
        p.faults = new
        S.sync_fault_step(p)
        p.invalidate()
        st.session_state["nonce_flt"] = st.session_state.get("nonce_flt", 0) + 1
        st.rerun()
    st.caption("Tip: draw each trace in the direction you like; ticks mark the hanging wall (for normal faults, the downthrown side). "
               "Press **Apply to model** in the editor to send your edits here.")

    if not p.faults:
        return
    with st.expander("Fault models available (select the type in the editor panel)"):
        for k, v in FAULT_TYPE_INFO.items():
            st.markdown(f"- **{k}** - {v}")
        st.markdown("- **Heave** (0-1, any dip-slip type): moves horizons sideways by heave x throw / tan(dip), so cut-offs separate (normal) "
                    "or overlap (reverse) like a real fault. 0 keeps vertical separation only.")
    st.markdown("##### Fault table")
    rows = [dict(Fault=f.name, Type=f.ftype, Throw_m=f.throw, Dip_deg=f.dip, HW=f.hw_side, Profile=f.profile,
                 Length_km=round(f.length() / 1000, 2), Drag_m=f.drag, zref_m=f.zref, Growth=f.growth,
                 Heave=f.heave, Slip_m=f.slip if f.ftype in ("strike_slip", "transverse") else None,
                 Pivot=f.pivot if f.ftype == "transverse" else None) for f in p.faults.values()]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    a, b = st.columns([2, 3])
    with a:
        fsel = st.selectbox("Fault", list(p.faults), key=S.k("flt_sel", list(p.faults)))
        if st.button("Set zref to the backdrop depth along the trace"):
            f = p.faults[fsel]
            P = f.points
            from core.surface import Surface
            z = Surface("b", g, Zb).sample(P[:, 0], P[:, 1], extrapolate=True)
            f.zref = float(round(np.nanmean(z), 1))
            p.invalidate()
            st.success(f"{fsel}: zref = {f.zref:.0f} {un.z()}")
            st.rerun()

    _transmissibility(p)
    st.markdown("##### Preview: faulted backdrop surface")
    c1, c2, c3 = st.columns([1, 1, 2])
    ve = c1.slider("Vertical exaggeration", 1.0, 20.0, 5.0, 0.5, key=S.k("flt_ve"))
    show = c2.radio("Show", ["Faulted", "Unfaulted"], horizontal=True, key=S.k("flt_show"))
    Zb, Zf = faulted_surface(p, bg, list(p.faults.values()))
    sc = S.scene_from_arrays(p, [(bg + (" (faulted)" if show == "Faulted" else ""), Zf if show == "Faulted" else Zb)],
                             faults=list(p.faults.values()), wells=True, tops=True, clip=False,
                             fault_cuts=list(p.faults.values()) if show == "Faulted" else (),
                             fault_references={bg + " (faulted)": Zb})
    st.caption("Faulted preview: the horizon mesh is split across active faults, revealing the depth offset. "
               "The visible gap is mesh-resolution dependent, not an added geological displacement. "
               "Run the structural workflow and rebuild the grid after changing fault parameters.")
    viewer3d(sc, key=S.k("flt3d"), height=580, ve=ve)
    note("The preview offsets the backdrop by each fault's displacement field: half of the throw up on the footwall and half down "
         "on the hanging wall, decaying with the drag-zone width. The final horizons are produced in the <b>Structural model</b> step.")


def _transmissibility(p):
    from core import faultfaces as ff
    st.markdown("##### Fault transmissibility and juxtaposition")
    st.caption("Multiplier 1 = open, 0 = sealing. Written to the GRDECL as FAULTS (the cell faces of each fault) and MULTFLT. The 3D grid is needed to find the faces.")
    df0 = st.session_state.setdefault(S.k("flt_m0", list(p.faults)), pd.DataFrame([dict(Fault=n, Multiplier=float(p.fault_mult.get(n, 1.0))) for n in p.faults]))
    ed = st.data_editor(df0, hide_index=True, disabled=["Fault"], key=S.k("flt_m", list(p.faults)))
    p.fault_mult = {str(r.Fault): float(np.clip(r.Multiplier, 0.0, 1.0)) for r in ed.itertuples() if abs(float(r.Multiplier) - 1.0) > 1e-9}
    g = p.grid
    if g is None:
        st.info("Build the 3D grid (page 6) to list the fault faces and the juxtaposition.")
        return
    faces = ff.assign_faults(g, list(p.faults.values()))
    st.dataframe(pd.DataFrame([dict(Fault=n, Faces=len(v), Eclipse_name=ff.eclipse_names(list(p.faults))[n]) for n, v in faces.items()]), hide_index=True)
    jx = ff.juxtaposition(g, list(p.faults.values()))
    fsel = st.selectbox("Juxtaposition for", [n for n, v in jx.items() if v] or ["-"], key=S.k("flt_jx", list(jx)))
    if fsel in jx and jx[fsel]:
        d = pd.DataFrame(jx[fsel]).rename(columns={"left": "Low I/J side", "right": "High I/J side", "area": "Contact area", "share": "Share"})
        d["Share"] = (100 * d["Share"]).round(1)
        st.dataframe(d.round(0), hide_index=True)
        st.caption("Contact area (project units squared) between zones across the fault, from the overlap of cell-face depths. Same-zone contact = juxtaposition of like against like (the 'sand on sand' risk).")
