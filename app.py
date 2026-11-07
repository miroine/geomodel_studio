"""GeoModel Studio - build a geological model (surfaces, polygons, faults, wells, structural model, 3D grid) in Streamlit.

Object-based like Petrel / RMS: every step produces an object in the tree on the left.

Run:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="GeoModel Studio", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")

from core import objects
from ui import state as S
from ui.theme import inject_css
from views import home, surfaces, polygons, faults, wells, tops, workflow, zones, grid, properties, volumetrics, analysis, upscaling, export, viewer

PAGES = {
    "Project": home.render,
    "3D window": viewer.render,
    "Surfaces": surfaces.render,
    "Polygons": polygons.render,
    "Faults": faults.render,
    "Wells": wells.render,
    "Well tops": tops.render,
    "Structural model": workflow.render,
    "Zones & layering": zones.render,
    "3D grid": grid.render,
    "Properties": properties.render,
    "Volumetrics": volumetrics.render,
    "Analysis & sections": analysis.render,
    "Upscaling": upscaling.render,
    "Export": export.render,
}
GLYPH = {"ok": "●", "missing": "○", "stale": "◐"}


def sidebar(p, page):
    st.markdown('<div class="brand">GeoModel Studio<small>object tree &middot; structure &middot; grid</small></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    for col, (label, pg) in zip((c1, c2, c3), (("Project", "Project"), ("3D", "3D window"), ("Export", "Export"))):
        col.button(label, key=f"top_{pg}", on_click=S.go, args=(pg,), type="primary" if page == pg else "secondary")
    st.divider()
    foc = st.session_state.get("focus")
    for grp in objects.tree(p):
        st.markdown(f'<div class="tree-grp">{grp["group"]}</div>', unsafe_allow_html=True)
        for kind in grp["kinds"]:
            items = kind["items"]
            active = page == kind["page"]
            with st.expander(f"{kind['label']}  ({len(items)})", expanded=active):
                st.button(f"Open {kind['label'].lower()}", key=f"open_{kind['kind']}", on_click=S.go, args=(kind["page"],),
                          type="primary" if active and not foc else "secondary")
                for it in items:
                    sel = active and foc and foc[0] == kind["kind"] and foc[1] == it["name"]
                    st.button(f"{GLYPH.get(it['state'], '')} {it['name']}", key=f"obj_{kind['kind']}_{it['name']}", help=it["info"],
                              on_click=S.go, args=(kind["page"], kind["kind"], it["name"]), type="primary" if sel else "secondary")
    st.divider()
    st.caption(f"**{p.name}**")
    if p.boundary:
        st.caption(f"Boundary: {p.boundary}")
    st.caption("Framework: " + ("built" if p.structure else "not built") + " · Grid: " + (f"{p.grid.ncells:,} cells" if p.grid else "not built"))


def main():
    inject_css()
    p = S.proj()
    if st.session_state.get("nav") not in PAGES:
        st.session_state["nav"] = "Project"
    page = st.session_state["nav"]
    with st.sidebar:
        sidebar(p, page)
    PAGES[page]()


main()
