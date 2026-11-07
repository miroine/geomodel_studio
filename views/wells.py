"""Wells: head table, deviation surveys (minimum curvature), import, creation from tops, 3D preview."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core import wells as wl
from core.wells import Well
from ui import state as S
from views.surfaces import _file_units
from ui.components import viewer3d
from ui.scene import Scene
from ui.theme import banner, kpis, note

TEMPLATE_HEAD = "Well,X,Y,KB,TD\nA-1,452000,6702000,25,2600\n"
TEMPLATE_SURVEY = "Well,MD,INCL,AZIM\nA-1,0,0,0\nA-1,900,0,0\nA-1,1500,35,80\nA-1,2600,42,85\n"
TEMPLATE_XYZ = "Well,X,Y,Z\nA-1,452000,6702000,0\nA-1,452150,6702010,1200\nA-1,452600,6702050,2400\n"


def _preview(p, names=None, height=520):
    if not p.wells:
        return
    if not p.has_lattice():
        st.caption("Define the model area to see the 3D preview.")
        return
    sc = S.build_scene(p, surfaces=list(p.surfaces)[:1], faults=False, polygons=False, wells=True, tops=True)
    viewer3d(sc, key=S.k("wells3d"), height=height, ve=3.0)


def _library(p):
    if not p.wells:
        note("No wells yet. Import a head / survey file, create one in the next tab, or use <b>From tops</b> to create wells from your top picks.")
        return
    df = wl.heads_table(p.wells)
    n_dev = sum(1 for w in p.wells.values() if w.kind != "vertical")
    kpis([("Wells", len(p.wells)), ("Deviated / explicit", n_dev), ("With tops", int(p.tops["well"].nunique()) if len(p.tops) else 0)])
    st.dataframe(df, hide_index=True)
    names = list(p.wells)
    w = p.wells[S.pick("Well", names, "well_sel", "well")]
    tr = wl.trajectory(w)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Head X / Y", f"{w.x:.0f} / {w.y:.0f}")
    c2.metric(f"KB ({un.z()})", f"{w.kb:g}")
    c3.metric(f"TVDSS at TD ({un.z()})", f"{tr[-1, 2]:.0f}")
    c4.metric(f"Horizontal departure ({un.xy()})", f"{np.hypot(tr[-1, 0] - tr[0, 0], tr[-1, 1] - tr[0, 1]):.0f}")
    if st.button("Delete this well", key=S.k(f"well_del_{w.name}")):
        p.wells.pop(w.name, None)
        st.rerun()
    _preview(p)


def _import(p):
    st.markdown("Accepted tables (CSV, semicolon or whitespace separated - column names are recognised automatically):")
    c1, c2, c3 = st.columns(3)
    c1.download_button("Head template", TEMPLATE_HEAD, "wells_head_template.csv", key=S.k("wl_t1"))
    c2.download_button("Survey template", TEMPLATE_SURVEY, "wells_survey_template.csv", key=S.k("wl_t2"))
    c3.download_button("XYZ path template", TEMPLATE_XYZ, "wells_xyz_template.csv", key=S.k("wl_t3"))
    st.caption("**Head:** Well, X, Y, KB, TD  ·  **Survey:** Well, MD, INCL, AZIM (+ X, Y, KB of the head)  ·  **Path:** Well, X, Y, Z (TVDSS, positive down). "
               "Surveys are converted with the minimum-curvature method.")
    fxw, fzw = _file_units("wells", p, z_sign=False)
    files = st.file_uploader("Well files", accept_multiple_files=True, key=S.k("wl_up"))
    for f in files or []:
        with st.container(border=True):
            st.markdown(f"**{f.name}**")
            try:
                out, msg = wl.parse(f.getvalue(), p.wells)
                out = {n: (w if w == p.wells.get(n) else wl.scale_well(w, fxw, fzw)) for n, w in out.items()}
            except Exception as e:
                st.error(f"Could not read: {e}")
                continue
            st.caption(msg)
            if st.button("Merge into project", type="primary", key=S.k(f"wl_merge_{f.name}")):
                p.wells = out
                st.success(msg)


def _edit(p):
    names = ["(new well)"] + list(p.wells)
    sel = st.selectbox("Well", names, key=S.k("wl_edit_sel", names))
    w = p.wells.get(sel)
    lat = p.lattice
    cx, cy = ((lat.xori + lat.xori + lat.xinc * (lat.ncol - 1)) / 2, (lat.yori + lat.yori + lat.yinc * (lat.nrow - 1)) / 2) if lat else (0.0, 0.0)
    c1, c2, c3, c4, c5 = st.columns(5)
    name = c1.text_input("Name", value=w.name if w else f"W-{len(p.wells) + 1}", key=S.k(f"wl_name_{sel}"))
    x = c2.number_input("X", value=float(w.x if w else cx), step=50.0, key=S.k(f"wl_x_{sel}"))
    y = c3.number_input("Y", value=float(w.y if w else cy), step=50.0, key=S.k(f"wl_y_{sel}"))
    kb = c4.number_input(f"KB ({un.z()})", value=float(w.kb if w else 25.0), step=1.0, key=S.k(f"wl_kb_{sel}"))
    td = c5.number_input("TD (MD, m)", 10.0, value=float(w.td if (w and w.td) else 2500.0), step=50.0, key=S.k(f"wl_td_{sel}"))
    kinds = ["Vertical", "Deviated - survey table", "Deviated - build / hold (generator)"]
    cur = 0 if (w is None or w.kind == "vertical") else (1 if w.kind.startswith("deviated") else 0)
    if w is not None and w.kind == "explicit path":
        st.info("This well has an explicit XYZ path from an import. Saving here keeps the path and updates head data only.")
    kind = st.radio("Trajectory", kinds, index=cur, horizontal=True, key=S.k(f"wl_kind_{sel}"))
    survey = []
    if kind == kinds[1]:
        base_key = f"tmp_wl_base_{sel}"
        if base_key not in st.session_state:
            st.session_state[base_key] = pd.DataFrame(w.survey if (w and w.survey) else [[0, 0, 0], [1000, 0, 0], [td, 30, 90]], columns=["MD", "INCL", "AZIM"])
        ed = st.data_editor(st.session_state[base_key], num_rows="dynamic", key=S.k(f"wl_tbl_{sel}_{st.session_state.get('tmp_wl_ver', 0)}"),
                            column_config={"MD": st.column_config.NumberColumn(f"MD ({un.z()})"), "INCL": st.column_config.NumberColumn("Inclination (deg)"),
                                           "AZIM": st.column_config.NumberColumn("Azimuth (deg from N)")})
        survey = ed.dropna().astype(float).values.tolist()
    elif kind == kinds[2]:
        a, b, c, d = st.columns(4)
        kop = a.number_input(f"Kick-off MD ({un.z()})", 0.0, value=900.0, step=50.0, key=S.k(f"wl_kop_{sel}"))
        bur = b.number_input(f"Build rate (deg / 30 {un.z()})", 0.1, value=3.0, step=0.5, key=S.k(f"wl_bur_{sel}"))
        inc = c.number_input("Hold inclination (deg)", 1.0, 120.0, value=40.0, step=1.0, key=S.k(f"wl_inc_{sel}"))
        azi = d.number_input("Azimuth (deg from N)", 0.0, 360.0, value=90.0, step=5.0, key=S.k(f"wl_azi_{sel}"))
        end_build = kop + inc / bur * 30.0
        survey = [[0, 0, 0], [kop, 0, azi], [end_build, inc, azi], [max(td, end_build + 50.0), inc, azi]]
        st.caption(f"Build section ends at MD {end_build:.0f} {un.z()}; then holds {inc:.0f} deg to TD.")
    cand = Well(name, x, y, kb, td, survey=survey if kind != kinds[0] else [], path=(w.path if (w and w.path) else []),
                color=(w.color if w else wl.WELL_COLORS[len(p.wells) % len(wl.WELL_COLORS)]))
    tr = wl.trajectory(cand)
    st.caption(f"Preview: TVDSS at TD {tr[-1, 2]:.0f} {un.z()}, horizontal departure {np.hypot(tr[-1, 0] - tr[0, 0], tr[-1, 1] - tr[0, 1]):.0f} {un.xy()}, "
               f"azimuth of departure {np.degrees(np.arctan2(tr[-1, 0] - tr[0, 0], tr[-1, 1] - tr[0, 1])) % 360:.0f} deg.")
    if st.button("Save well", type="primary", key=S.k(f"wl_save_{sel}")):
        if not name:
            st.error("Name required.")
        elif name != sel and name in p.wells:
            st.error(f"A well called {name} already exists.")
        else:
            if sel in p.wells and sel != name:
                p.wells = {(name if k == sel else k): v for k, v in p.wells.items()}
                if len(p.tops):
                    p.tops.loc[p.tops["well"] == sel, "well"] = name
            p.wells[name] = cand
            st.success(f"Saved {name}.")
            st.session_state.pop(f"tmp_wl_base_{sel}", None)
            st.session_state["tmp_wl_ver"] = st.session_state.get("tmp_wl_ver", 0) + 1       # fresh editor state for the next edit


def _from_tops(p):
    if p.tops.empty:
        note("No well tops loaded - import them on the Well tops page first.")
        return
    missing = [w for w in p.tops["well"].unique() if w not in p.wells]
    st.markdown(f"{p.tops['well'].nunique()} wells in the tops table, **{len(missing)}** without a well object" + (f": {', '.join(map(str, missing[:8]))}" if missing else "."))
    pad = st.number_input(f"TD below deepest top ({un.z()})", 0.0, value=300.0, step=50.0, key=S.k("wl_pad"))
    if st.button("Create vertical wells from tops", type="primary", disabled=not missing, key=S.k("wl_fromtops")):
        p.wells = wl.wells_from_tops(p.tops, p.wells, pad=pad)
        st.success(f"Created {len(missing)} well(s). Edit them in 'Create / edit' to add a deviation survey.")
        st.rerun()
    st.caption("In the 3D window a top marker sits on the well path where the path reaches the pick depth. "
               "For deviated wells that is the deviated position, which is not the (X, Y) in the tops table.")


def render():
    p = S.proj()
    n = len(p.wells)
    banner("Wells", f"{n} well{'s' if n != 1 else ''} - trajectories, deviation surveys and top markers shown inside the 3D model"
           if n else "Define wells: import heads and surveys, create deviated wells, or generate them from your tops")
    t1, t2, t3, t4 = st.tabs(["Library & 3D", "Import", "Create / edit", "From tops"])
    with t1:
        _library(p)
    with t2:
        _import(p)
    with t3:
        _edit(p)
    with t4:
        _from_tops(p)
