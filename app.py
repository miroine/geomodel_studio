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
PAGE_GROUPS = [
    ("Workspace", ["Project"]),
    ("Build", ["Surfaces", "Polygons", "Faults", "Wells", "Well tops"]),
    ("Model", ["Structural model", "Zones & layering", "3D grid", "Properties"]),
    ("Review & deliver", ["3D window", "Volumetrics", "Analysis & sections", "Upscaling", "Export"]),
]
MODEL_STAGES = {
    "Structural model": ("01", "Horizon & fault framework", "Surfaces, faults and well tops -> structural horizons"),
    "Zones & layering": ("02", "Zones & layering", "Top/base horizons -> zones and layer design"),
    "3D grid": ("03", "Build the 3D grid", "Framework + layering -> active grid cells"),
    "Properties": ("04", "Populate the reservoir", "Facies -> petrophysics -> water saturation -> QC"),
}

PAGE_KINDS = {
    page: kind
    for _, kinds in objects.GROUPS
    for kind, _, page in kinds
}


def sidebar(p, page):
    st.markdown(
        '<div class="brand">GeoModel Studio<small>Geological model workspace</small></div>',
        unsafe_allow_html=True,
    )
    quick = st.columns(3)
    for column, (label, target) in zip(quick, (("Project", "Project"), ("3D", "3D window"), ("Export", "Export"))):
        column.button(
            label,
            key=f"top_{target}",
            on_click=S.go,
            args=(target,),
            type="primary" if page == target else "secondary",
        )
    st.markdown('<div class="nav-label">WORKFLOW</div>', unsafe_allow_html=True)
    st.divider()
    foc = st.session_state.get("focus")
    for group, pages in PAGE_GROUPS:
        with st.expander(group, expanded=page in pages):
            for target in pages:
                if group == "Model":
                    if target != pages[0]:
                        st.markdown('<div class="sidebar-flow-arrow" aria-label="Next model stage">&#8595;</div>', unsafe_allow_html=True)
                    with st.container(border=True):
                        number, title, detail = MODEL_STAGES[target]
                        st.markdown(f'<div class="sidebar-flow-title"><span>{number}</span>{title}</div>', unsafe_allow_html=True)
                        st.caption(detail)
                        _sidebar_page(p, page, target, foc)
                        ready = {"Structural model": p.structure is not None, "Zones & layering": bool(p.zones),
                                 "3D grid": p.grid is not None,
                                 "Properties": p.grid is not None and bool(p.properties) and all(
                                     not v.stale and v.values.shape == p.grid.actnum.shape for v in p.properties.values())}[target]
                        st.caption("Configured" if target == "Zones & layering" and ready else "Ready" if ready else "Not built / needs attention")
                else:
                    _sidebar_page(p, page, target, foc)
            if group == "Model":
                st.markdown('<div class="sidebar-flow-arrow">&#8595;</div>', unsafe_allow_html=True)
                st.caption("Review & deliver: 3D QC -> volumetrics -> export. Facies and saturation are optional where not required.")
    st.divider()
    st.markdown(f'<div class="project-chip"><b>{p.name}</b></div>', unsafe_allow_html=True)
    if p.boundary:
        st.caption(f"Boundary · {p.boundary}")
    st.caption(
        "Framework · " + ("Ready" if p.structure else "Not built")
        + "  |  Grid · " + (f"{p.grid.ncells:,} cells" if p.grid else "Not built")
    )


def _sidebar_page(p, page, target, foc):
    active = page == target
    kind = PAGE_KINDS.get(target)
    st.button(
        target,
        key=f"open_{kind}" if kind else f"nav_{target}",
        on_click=S.go,
        args=(target,),
        type="primary" if active and not foc else "secondary",
    )
    if kind:
        items = objects.items(p, kind)
        if kind == "prop":
            names = [item["name"] for item in items]
            if names:
                selected_name = foc[1] if foc and foc[0] == "prop" and foc[1] in names else None
                key = S.k("sidebar_property", names)

                def open_property():
                    name = st.session_state.get(key)
                    if name in p.properties:
                        S.go("Properties", "prop", name)

                with st.container(key="tree_kind_prop"):
                    st.selectbox("3D properties", names, index=names.index(selected_name) if selected_name else None,
                                 placeholder=f"Select from {len(names)} properties", key=key,
                                 format_func=lambda name: ("🟠 " if p.properties[name].stale else "🟢 ") + name,
                                 on_change=open_property)
                    st.caption("Green: created/current. Orange: stale; rebuild after grid changes.")
            return
        for index, item in enumerate(items):
            selected = active and foc and foc[0] == kind and foc[1] == item["name"]
            with st.container(key=f"tree_kind_{kind}_{index}"):
                with st.container(key=f"tree_{item['state']}_{kind}_{index}"):
                    st.button(
                        f"{GLYPH.get(item['state'], '')} {item['name']}",
                        key=f"obj_{kind}_{item['name']}",
                        help=item["info"],
                        on_click=S.go,
                        args=(target, kind, item["name"]),
                        type="primary" if selected else "secondary",
                    )


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
