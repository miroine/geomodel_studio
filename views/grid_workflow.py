"""Unified zone/layer design, grid construction and immediate QC."""
import streamlit as st

from ui import state as S
from ui.theme import banner, note
from views import grid, zones


def render():
    p = S.proj()
    banner("Zones & 3D grid", "Design zones and layers, build the grid, and inspect the results in one workflow")
    if p.structure is None:
        note("Run the structural workflow first to define the horizons used by zones and the grid.", warn=True)
        return
    actions, guidance = st.columns([1, 3], gap="large")
    build_area = actions.container()
    with guidance:
        st.markdown("**1 · Design zones and layers → 2 · Set the grid → 3 · Build and inspect**")
        st.caption("Change settings below, then use Build / update 3D grid at the top. "
                   "The results use the last successful build; changing zone layering clears the old grid.")
    with st.expander("1  Zones & layering", expanded=p.grid is None):
        valid = zones.render_controls(p)
    with st.expander("2  Grid settings", expanded=p.grid is None):
        if valid:
            grid.render_controls(p, build_area=build_area)
        else:
            build_area.button("Build / update 3D grid", type="primary", disabled=True, use_container_width=True,
                              help="Define valid zones and resolve table errors before building.")
            st.warning("Define valid zones and resolve table errors before building the grid.")
    st.divider()
    st.subheader("3  Grid results")
    if p.grid is None:
        st.info("Set zones and grid settings above, then click Build / update 3D grid at the top "
                "to see the full-width 3D view, sections and checks here.")
    else:
        grid.render_results(p)
