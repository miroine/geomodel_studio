"""GeoModel Studio - build a geological model (surfaces, polygons, faults, wells, structural model, 3D grid) in Streamlit.

Object-based like Petrel / RMS: a ribbon of process domains, Input / Models / Processes panels on the left,
a step guide on every page and a status bar.

Built by Merouane Hamdani. Non-commercial use only (PolyForm Noncommercial License 1.0.0, see LICENSE).

Run:  streamlit run app.py
"""
import html
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="GeoModel Studio", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")

from core import objects
from ui import state as S
from ui.theme import inject_css
from views import home, surfaces, polygons, faults, wells, tops, workflow, zones, grid, properties, volumetrics, analysis, upscaling, export, viewer

from views import grid_workflow

PAGES = {
    "Project": home.render,
    "3D window": viewer.render,
    "Surfaces": surfaces.render,
    "Polygons": polygons.render,
    "Faults": faults.render,
    "Wells": wells.render,
    "Well tops": tops.render,
    "Structural model": workflow.render,
    "Zones & layering": grid_workflow.render,
    "3D grid": grid_workflow.render,
    "Zones & 3D grid": grid_workflow.render,
    "Properties": properties.render,
    "Volumetrics": volumetrics.render,
    "Analysis & sections": analysis.render,
    "Upscaling": upscaling.render,
    "Export": export.render,
}
GLYPH = {"ok": "●", "missing": "○", "stale": "◐"}
# Petrel-style ribbon: process domains (tabs) and the tools (pages) inside each domain
DOMAINS = [
    ("Project", "Project setup, CRS and model area", ["Project"]),
    ("Input data", "Surfaces, polygons, faults, wells and tops", ["Surfaces", "Polygons", "Faults", "Wells", "Well tops"]),
    ("Structural framework", "Horizons and faults to a structural model", ["Structural model"]),
    ("Gridding", "Zones, layering and the 3D grid", ["Zones & 3D grid"]),
    ("Property modelling", "Facies, petrophysics and saturation", ["Properties"]),
    ("Volumetrics", "Contacts, fluids and in-place volumes", ["Volumetrics"]),
    ("Analysis & QC", "3D window, sections and upscaling", ["3D window", "Analysis & sections", "Upscaling"]),
    ("Export", "Grids, surfaces and reports", ["Export"]),
]
DOMAIN_OF = {page: domain for domain, _, pages in DOMAINS for page in pages}
GUIDES = {
    "Project": "01-project-setup.md", "Surfaces": "02-surfaces.md", "Polygons": "03-polygons.md",
    "Faults": "04-faults.md", "Wells": "05-wells.md", "Well tops": "06-well-tops.md",
    "Structural model": "07-structural-model.md", "Zones & 3D grid": "08-zones-and-3d-grid.md",
    "Properties": "09-property-modelling.md", "Volumetrics": "10-volumetrics.md",
    "3D window": "11-3d-window-and-display.md", "Analysis & sections": "12-analysis-and-sections.md",
    "Upscaling": "13-upscaling.md", "Export": "14-export.md",
}
DOCS = Path(__file__).resolve().parent / "docs"
INPUT_PAGES = ["Surfaces", "Polygons", "Faults", "Wells", "Well tops"]
MODEL_PAGES = ["Structural model", "Zones & 3D grid", "Properties"]
DISCLAIMER = ("Built by Merouane Hamdani · Non-commercial use only · "
              "PolyForm Noncommercial License 1.0.0 · Provided as is, without warranty")

PAGE_KINDS = {
    page: kind
    for _, kinds in objects.GROUPS
    for kind, _, page in kinds
}
PAGE_KINDS["Zones & 3D grid"] = "grid"


def _stage_status(p):
    props_ok = p.grid is not None and bool(p.properties) and all(
        not v.stale and v.values.shape == p.grid.actnum.shape for v in p.properties.values())
    vol = getattr(p, "volumetrics", None)
    return {
        "Project": p.has_lattice(),
        "Input data": bool(p.surfaces),
        "Structural framework": p.structure is not None,
        "Gridding": p.grid is not None,
        "Property modelling": props_ok,
        "Volumetrics": bool(vol),
        "Analysis & QC": p.grid is not None or bool(p.surfaces),
        "Export": p.grid is not None,
    }


def ribbon(page):
    """Domain tabs and the tools of the active domain, like the Petrel ribbon."""
    active = DOMAIN_OF.get(page, "Project")
    with st.container(key="ribbon"):
        cols = st.columns(len(DOMAINS))
        for col, (domain, detail, pages) in zip(cols, DOMAINS):
            col.button(domain, key=f"ribbon_{domain}", help=detail, on_click=S.go, args=(pages[0],),
                       type="primary" if domain == active else "secondary", use_container_width=True)
    tools = next(pages for domain, _, pages in DOMAINS if domain == active)
    with st.container(key="ribbon_tools"):
        cols = st.columns([1] * len(tools) + [max(1, 8 - len(tools))])
        for col, target in zip(cols, tools):
            col.button(target, key=f"tool_{target}", on_click=S.go, args=(target,),
                       type="primary" if target == page else "secondary", use_container_width=True)
    st.markdown(f'<div class="breadcrumb">{active} <span>›</span> <b>{page}</b></div>', unsafe_allow_html=True)


def guide(page):
    """Collapsible step guide rendered from docs/<step>.md."""
    name = GUIDES.get(page)
    path = DOCS / name if name else None
    if path is None or not path.is_file():
        return
    with st.expander(f"📘 Guide · {page}", expanded=False):
        text = path.read_text(encoding="utf-8")
        st.markdown(text.split("\n---\n*GeoModel Studio")[0])
        st.caption(f"Full guide: docs/{name} · Index: docs/README.md")


def status_bar(p):
    crs = p.crs
    lat = p.lattice
    parts = [f"<b>{html.escape(p.name)}</b>",
             html.escape(crs.get("name") or ("EPSG:" + str(crs["epsg"]) if crs.get("epsg") else "Local CRS")),
             f"XY {crs['xy_unit']} · Z {crs['z_unit']}",
             f"Lattice {lat.ncol}×{lat.nrow}" if p.has_lattice() else "No model area",
             "Framework ✓" if p.structure is not None else "Framework –",
             f"Grid {p.grid.ncells:,} cells" if p.grid is not None else "Grid –"]
    st.markdown('<div class="statusbar"><div class="sb-left">' + '<i>|</i>'.join(f"<span>{x}</span>" for x in parts)
                + f'</div><div class="sb-right">{DISCLAIMER}</div></div>', unsafe_allow_html=True)


def _tree(p, page, foc, targets):
    for target in targets:
        _sidebar_page(p, page, target, foc)


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
    foc = st.session_state.get("focus")
    t_input, t_models, t_proc = st.tabs(["Input", "Models", "Processes"])
    with t_input:
        st.markdown('<div class="nav-label">INPUT DATA</div>', unsafe_allow_html=True)
        _tree(p, page, foc, INPUT_PAGES)
    with t_models:
        st.markdown('<div class="nav-label">MODELS</div>', unsafe_allow_html=True)
        _tree(p, page, foc, MODEL_PAGES)
    with t_proc:
        st.markdown('<div class="nav-label">PROCESS FLOW</div>', unsafe_allow_html=True)
        status = _stage_status(p)
        active = DOMAIN_OF.get(page)
        for i, (domain, detail, pages) in enumerate(DOMAINS, 1):
            if i > 1:
                st.markdown('<div class="sidebar-flow-arrow" aria-label="Next stage">&#8595;</div>', unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown(f'<div class="sidebar-flow-title"><span>{i:02d}</span>{domain}</div>', unsafe_allow_html=True)
                st.caption(detail)
                st.button("Open" if domain != active else "Open (current)", key=f"proc_{domain}", on_click=S.go,
                          args=(pages[0],), type="primary" if domain == active else "secondary")
                st.caption("● Ready" if status[domain] else "○ Not built / needs attention")
    st.divider()
    st.markdown(f'<div class="project-chip"><b>{html.escape(p.name)}</b></div>', unsafe_allow_html=True)
    if p.boundary:
        st.caption(f"Boundary · {p.boundary}")
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)


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
        tree_items = [(kind, item) for item in items]
        if target == "Zones & 3D grid":
            tree_items = [("zone", item) for item in objects.items(p, "zone")] + tree_items
        for index, (kind, item) in enumerate(tree_items):
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
    if st.session_state.get("nav") in ("Zones & layering", "3D grid"):
        st.session_state["nav"] = "Zones & 3D grid"
    if st.session_state.get("nav") not in PAGES:
        st.session_state["nav"] = "Project"
    page = st.session_state["nav"]
    with st.sidebar:
        sidebar(p, page)
    ribbon(page)
    guide(page)
    PAGES[page]()
    status_bar(p)


main()
