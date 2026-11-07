"""Well tops: import, edit, QC against the structural model."""
import io

import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core import tops as tp
from views.surfaces import _file_units
from core.workflow import tops_misfit
from ui import state as S
from ui import specs
from ui.components import plotly_view
from ui.theme import banner, kpis, note

TEMPLATE = "Well,X,Y,Horizon,Z_TVDSS\nW-1,452000,6703000,Top_Reservoir,2010.5\nW-1,452000,6703000,Base_Reservoir,2140.0\nW-2,453500,6704200,Top_Reservoir,1985.0\n"


def render():
    p = S.proj()
    n = p.tops["well"].nunique() if not p.tops.empty else 0
    banner("3 - Well tops", f"{len(p.tops)} tops in {n} wells are available to calibrate the horizons" if n
           else "Import well tops (well, X, Y, horizon, depth) to calibrate the surfaces")
    t1, t2 = st.tabs(["Import & edit", "QC vs structural model"])
    with t1:
        c1, c2 = st.columns([2, 1])
        fxt, fzt = _file_units("tops", p)
        up = c1.file_uploader("Tops file (CSV / whitespace; columns Well, X, Y, Horizon, Z)", key=S.k("tops_up"))
        c2.download_button("Download template", TEMPLATE, file_name="tops_template.csv")
        if up is not None and st.session_state.get("done_tops") != (up.name, up.size):
            try:
                df = tp.parse_tops(up.getvalue())
                df[["x", "y"]] = df[["x", "y"]] * fxt
                df["z"] = df["z"] * fzt
                p.tops = df
                st.session_state["tops_ver"] = st.session_state.get("tops_ver", 0) + 1
                st.session_state["done_tops"] = (up.name, up.size)
                p.invalidate()
                st.success(f"Read {len(df)} tops from {up.name}.")
            except Exception as e:
                st.error(str(e))
        if not p.tops.empty:
            sig = (S.rev(), st.session_state.get("tops_ver", 0))
            if st.session_state.get("tmp_tops_sig") != sig:        # editor input must stay constant between edits
                st.session_state["tmp_tops_base"] = p.tops.copy()
                st.session_state["tmp_tops_sig"] = sig
            edited = st.data_editor(st.session_state["tmp_tops_base"], num_rows="dynamic", key=S.k(f"tops_ed{sig[1]}"),
                                    column_config={"x": st.column_config.NumberColumn("X", format="%.1f"),
                                                   "y": st.column_config.NumberColumn("Y", format="%.1f"),
                                                   "z": st.column_config.NumberColumn(f"Depth z ({un.z()})", format="%.1f")})
            clean_ = edited.dropna(subset=["x", "y", "z"]).reset_index(drop=True)
            if not clean_.equals(p.tops):
                p.tops = clean_
                p.invalidate()
            hz = sorted(p.tops["horizon"].unique())
            st.caption("Horizons in the tops: " + ", ".join(hz) + ".  A calibrate step in the workflow matches a horizon to a tops name.")
            if p.has_lattice():
                sel = st.selectbox("Map tops for", ["All"] + hz, key=S.k("tops_map", hz))
                g = p.lattice
                Z = np.full(g.shape, np.nan)
                spec = specs.map_2d(S.lattice_surface(p, next(iter(p.surfaces))) if p.surfaces else np.zeros(g.shape), g,
                                    faults=list(p.faults.values()),
                                    wells=S.wells_for_plot(p.tops, None if sel == "All" else sel, label_horizon=False))
                plotly_view(spec, key=S.k("topsmap") + sel, height=480)
        else:
            note("No tops loaded. Without tops the workflow's calibrate step is skipped.")
    with t2:
        if p.structure is None or p.tops.empty:
            note("Run the structural model (page 4) with tops loaded to see the residuals.")
            return
        mis = tops_misfit(p.structure, p.tops)
        if mis.empty:
            note("No tops match horizon names in the structural model.", warn=True)
            return
        kpis([("Tops matched", len(mis)), (f"Mean residual ({un.z()})", f"{mis['residual'].mean():+.2f}"),
              (f"RMS ({un.z()})", f"{np.sqrt((mis['residual'] ** 2).mean()):.2f}"), (f"Max |res| ({un.z()})", f"{mis['residual'].abs().max():.1f}")])
        plotly_view(specs.residual_bars(mis), key=S.k("resbar"), height=380)
        st.dataframe(mis.round(2), hide_index=True)
        if p.structure.calib_qc:
            st.markdown("##### Calibration steps")
            st.dataframe(pd.DataFrame(p.structure.calib_qc).round(2), hide_index=True)
        st.caption("Residual = observed - modelled depth. Residuals after calibration are small but non-zero because the correction "
                   "is interpolated on the lattice (and tops on eroded or truncated horizons cannot be honoured).")
