"""Upscaling: coarse corner-point grid + averaged / flow-based properties, with volume QC and export of the coarse model."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un
from core import export as ex
from core import props as pp
from core import simfmt as sf
from core import upscale as U
from ui import state as S
from ui import specs
from ui.components import plotly_view
from ui.theme import banner, kpis, note
from views.export import _prepared


def render():
    p = S.proj()
    g = p.grid
    banner("9 - Upscaling", "Coarse grid and upscaled properties for simulation")
    if g is None:
        note("Build the 3D grid first (page 6).", warn=True)
        return
    if not p.properties:
        note("No properties yet - populate them on the Properties page first. The coarse grid can still be built without properties.", warn=False)
    cfg = p.upscale
    cfg.setdefault("ci", 2)
    cfg.setdefault("cj", 2)
    cfg.setdefault("nk", {})
    cfg.setdefault("method", "arithmetic")
    cfg.setdefault("omega", 0.5)
    st.caption("Groups I x J columns and merges layers inside each zone. Group boundaries are also placed wherever the fault-block id changes, so the coarse "
               "grid keeps the fault pattern the fine grid resolves. The coarse corner depths are the fine corner depths on the group boundaries.")
    with st.expander("1  Coarse grid", expanded=True):
        a, b = st.columns(2)
        cfg["ci"] = int(a.number_input("Columns merged along I", 1, max(g.ni, 1), int(min(cfg["ci"], g.ni)), key=S.k("up_ci")))
        cfg["cj"] = int(b.number_input("Columns merged along J", 1, max(g.nj, 1), int(min(cfg["cj"], g.nj)), key=S.k("up_cj")))
        rows = []
        for zi, z in enumerate(g.zones):
            n = int((g.layer_zone == zi).sum())
            rows.append({"Zone": z.name, "Fine layers": n, "Coarse layers": int(min(max(int(cfg["nk"].get(z.name, max(1, n // 2))), 1), max(n, 1)))})
        key = "up_nk_df|" + "|".join(f"{r['Zone']}{r['Fine layers']}" for r in rows)
        if key not in st.session_state:
            st.session_state[key] = pd.DataFrame(rows)
        ed = st.data_editor(st.session_state[key], disabled=["Zone", "Fine layers"], hide_index=True, key=S.k("up_nk" + key))
        nkc = []
        for r in ed.to_dict("records"):
            v = int(max(1, min(int(r["Coarse layers"]), int(r["Fine layers"]) if r["Fine layers"] else 1)))
            cfg["nk"][r["Zone"]] = v
            nkc.append(v)
    with st.expander("2  Property averaging", expanded=True):
        a, b = st.columns(2)
        cfg["method"] = a.selectbox("Permeability", U.PERM_METHODS, index=U.PERM_METHODS.index(cfg["method"]) if cfg["method"] in U.PERM_METHODS else 0, key=S.k("up_meth"),
                                    help="Arithmetic / harmonic / geometric / power-law average of the fine cells, or a flow-based solve per coarse cell and direction "
                                         "(single phase, closed lateral boundaries, needs PERMX, PERMY and PERMZ).")
        cfg["omega"] = float(b.number_input("Power-law exponent", -1.0, 1.0, float(cfg["omega"]), 0.05, disabled=cfg["method"] != "power", key=S.k("up_om")))
        st.caption("PORO and NTG: volume-weighted (PORO by net volume). Saturations: pore-volume weighted. Discrete properties: majority by volume. "
                   "Permeability averaging uses net volume as weight. Flow-based upscaling captures layering and barriers but ignores flow across the "
                   "coarse-cell boundary (local boundary conditions).")
    coarse = c = None
    if st.button("Build coarse grid and upscale", type="primary", key=S.k("up_run")):
        try:
            bar = st.progress(0.0)
            c = U.build_coarse(g, cfg["ci"], cfg["cj"], nkc)
            res = U.upscale_properties(c, g, p.properties, cfg["method"], cfg["omega"], progress=lambda f: bar.progress(min(float(f), 1.0)))
            st.session_state["up_result"] = dict(c=c, res=res, sig=(id(g), cfg["ci"], cfg["cj"], tuple(nkc), cfg["method"]), qc=U.qc(c, g, p.properties, res))
            st.rerun()
        except U.UpscaleError as e:
            st.error(str(e))
    r = st.session_state.get("up_result")
    if not r or r["sig"][0] != id(g):
        return
    c, res, q = r["c"], r["res"], r["qc"]
    cg = c.grid
    kpis([("Coarse grid", f"{cg.ni} x {cg.nj} x {cg.nk}"), ("Active cells", f"{q['cells_coarse']:,} / {q['cells_fine']:,}"),
          ("Reduction", f"x{g.ncells / max(cg.ncells, 1):.1f}"), ("Bulk volume error", f"{(q['bulk_coarse'] / q['bulk_fine'] - 1) * 100:+.3f} %")])
    rows = [{"Quantity": "Bulk volume", "Fine": q["bulk_fine"], "Coarse": q["bulk_coarse"]}]
    if "pv_fine" in q:
        rows.append({"Quantity": "Net pore volume", "Fine": q["pv_fine"], "Coarse": q["pv_coarse"]})
    for n in ("PERMX", "PERMZ"):
        if n + "_fine_geo" in q:
            rows.append({"Quantity": f"{n} geometric mean (volume-weighted)", "Fine": q[n + "_fine_geo"], "Coarse": q[n + "_coarse_geo"]})
    df = pd.DataFrame(rows)
    df["Difference %"] = (df["Coarse"] / df["Fine"] - 1) * 100
    st.dataframe(df.round(3), hide_index=True)
    st.caption("Bulk and pore volume differ slightly because each coarse cell replaces the horizons inside it by its corner interpolation (the error grows with relief inside a cell, typically below 1-2 %); use fewer merged columns where relief is steep. Permeability differs by design: it depends on the averaging method.")
    meth = pd.DataFrame([{"Property": n, "Method": v["method"], "Mean": float(np.nanmean(v["values"])), "Min": float(np.nanmin(v["values"])),
                          "Max": float(np.nanmax(v["values"]))} for n, v in res.items() if np.isfinite(v["values"]).any()])
    if len(meth):
        st.dataframe(meth.round(4), hide_index=True)
    if res:
        a, b = st.columns(2)
        pn = a.selectbox("Compare property", list(res), key=S.k("up_cmp", list(res)))
        k_ = int(b.slider("Fine layer", 1, g.nk, min(g.nk, 3), key=S.k("up_lay", [g.nk]))) - 1
        zi = int(g.layer_zone[k_])
        kc = int(np.argmax((c.ke[:-1] <= k_) & (k_ < c.ke[1:])))
        c1, c2 = st.columns(2)
        with c1:
            plotly_view(specs.layer_map(np.where(g.actnum[k_] > 0, p.properties[pn].values[k_], np.nan), f"Fine - {pn}, layer {k_ + 1}"), key=S.k("up_mf") + f"{pn}{k_}", height=300)
        with c2:
            plotly_view(specs.layer_map(np.where(cg.actnum[kc] > 0, res[pn]["values"][kc], np.nan), f"Coarse - {pn}, layer {kc + 1}"), key=S.k("up_mc") + f"{pn}{kc}", height=300)
    st.subheader("Export the coarse model")
    st.caption("FAULTS / MULTFLT keywords are not written for the coarse grid (the fault faces are defined on the fine grid).")
    system = st.radio("Unit system", ["METRIC", "FIELD"], horizontal=True, key=S.k("up_sys"),
                      index=1 if un.unit_system(p.crs["xy_unit"], p.crs["z_unit"]) == "FIELD" else 0)
    gx = ex.grid_for_system(cg, p.crs, system)
    custom = {n: pp.Property(name=n, values=np.nan_to_num(v["values"], nan=0.0).astype(np.float32), kind=v["kind"], unit=v["unit"]) for n, v in res.items()}
    sig = (id(c), system, cfg["method"], tuple(sorted(custom)))
    _prepared("up_grdecl", sig, lambda: ex.grdecl_text(gx, [n for n in custom if len(n) <= 8], p.name + " (upscaled)", system=system, custom=custom), "coarse GRDECL", "COARSE.GRDECL", "text/plain")
    _prepared("up_egrid", sig, lambda: sf.egrid_bytes(gx, system), "coarse EGRID", "COARSE.EGRID")
    short = sf.short_names([n for n in custom])

    def init_():
        return sf.init_bytes(gx, {short[n]: (np.where(cg.actnum > 0, custom[n].values, 0.0), custom[n].kind) for n in custom}, system)
    _prepared("up_init", sig, init_, "coarse INIT", "COARSE.INIT")
