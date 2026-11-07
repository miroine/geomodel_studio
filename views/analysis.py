"""Analysis & sections: statistics, histogram / CDF, crossplot, vertical profile, 2D maps and property cross-sections."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un
from core import analysis as an
from core import gridsection as gsx
from core import volumetrics as V
from core import props as pp
from ui import state as S
from ui import specs
from ui.components import plotly_view
from ui.theme import banner, kpis, note
from views import property_results


def _filters(props, g, names):
    """Zone / layer / value filters shared by the analysis tabs -> boolean mask."""
    with st.expander("Filters - zones, layers, value ranges", expanded=False):
        zn = [z.name for z in g.zones]
        zones = st.multiselect("Zones", zn, default=zn, key=S.k("an_zones", zn))
        k0, k1 = st.slider("Layers", 1, g.nk, (1, g.nk), key=S.k("an_k", [g.nk]))
        flt = []
        for n in (1, 2):
            c1, c2, c3 = st.columns([2, 1, 1])
            pn = c1.selectbox(f"Filter {n}", ["(none)"] + names, key=S.k(f"an_f{n}", names))
            lo = c2.text_input("min", "", key=S.k(f"an_lo{n}"))
            hi = c3.text_input("max", "", key=S.k(f"an_hi{n}"))
            if pn != "(none)" and (lo.strip() or hi.strip()):
                try:
                    flt.append(dict(prop=pn, lo=float(lo) if lo.strip() else None, hi=float(hi) if hi.strip() else None))
                except ValueError:
                    st.warning(f"Filter {n}: min / max must be numbers.")
        if "NET" in names or "VOL_NET" in names:
            nn = "VOL_NET" if "VOL_NET" in names else "NET"
            if st.checkbox(f"Net cells only ({nn} = 1)", key=S.k("an_net")):
                flt.append(dict(prop=nn, lo=0.5, hi=None))
    m = an.selection(g, props, flt, zones, (k0 - 1, k1 - 1))
    return m, flt


def render():
    p = S.proj()
    g = p.grid
    banner("9 - Analysis & sections", "Statistics, crossplots, profiles, maps and property cross-sections")
    if g is None:
        note("Build the 3D grid first (page 6).", warn=True)
        return
    props = dict(p.properties)
    fluid_auto = False
    if "FLUID" not in props and p.volumetrics and not V.check_config(g, p.volumetrics):   # fluid split straight from the contacts
        try:
            props["FLUID"] = pp.make_property(g, "FLUID", V.fluid_array(g, p.volumetrics, None, p.properties), "discrete", "", "volumetrics", legend=V.FLUID_LEGEND)
            fluid_auto = True
        except V.VolError as exc:
            st.warning(f"Fluid classification unavailable: {exc}")
    names = [n for n, v in props.items() if v.values.shape == (g.nk, g.nj, g.ni)]
    if not names:
        note("No properties yet. Generate geometric properties or populate PORO / NTG on the Properties page.", warn=True)
        return
    mask, flt = _filters(props, g, names)
    kpis([("Properties", len(names)), ("Cells selected", f"{int(mask.sum()):,}"), ("Active cells", f"{int((g.actnum > 0).sum()):,}")])
    if not mask.any():
        note("No cells pass the filters.", warn=True)
        return
    splits = an.available_splits(props)
    if fluid_auto:
        st.caption("Fluid split uses the contacts of the Volumetrics set-up (gas above GOC, oil down to the OWC, water below).")
    elif "FLUID" not in props:
        st.caption("Set the contacts on the Volumetrics page to enable the oil / gas / water split.")
    t1, t2, t3, t4, t5, t6 = st.tabs(["Statistics", "Histogram / CDF", "Crossplot", "Vertical profile", "Maps", "Cross-sections"])
    try:
        with t1:
            c1, c2 = st.columns(2)
            pn = c1.selectbox("Property", names, key=S.k("an_sp", names))
            sp = c2.selectbox("Split by", splits, index=1, key=S.k("an_ss", splits))
            rows = an.stats_table(g, props, pn, sp, mask)
            df = pd.DataFrame(rows)
            if len(df):
                df = df.rename(columns={"group": "Group", "count": "Cells", "min": "Min", "mean": "Mean (vol-wtd)", "std": "Std", "p10": "P10", "p50": "P50", "p90": "P90", "max": "Max",
                                        "volume": "Bulk vol."})
                st.dataframe(df.round(4), hide_index=True)
                st.download_button("Download (CSV)", df.to_csv(index=False).encode(), f"stats_{pn}.csv", "text/csv", key=S.k("an_dl1"))
        with t2:
            c1, c2, c3 = st.columns(3)
            pn = c1.selectbox("Property", names, key=S.k("an_hp", names))
            sp = c2.selectbox("Split by", splits, index=1, key=S.k("an_hs", splits))
            nb = int(c3.number_input("Bins", 10, 100, 40, 5, key=S.k("an_hb")))
            grp = an.groups_values(g, props, pn, sp, mask)
            plotly_view(specs.value_histogram(grp, f"{pn} by {sp}", pn, bins=nb), key=S.k("an_h") + f"{pn}{sp}{nb}{int(mask.sum())}", height=300)
            cd = []
            for k_, (n_, v_) in enumerate(grp.items()):
                x_, y_ = an.cdf(v_)
                step = max(1, len(x_) // 400)
                cd.append(dict(type="scatter", mode="lines", x=x_[::step], y=y_[::step], name=n_, line=dict(color=specs.PALETTE[k_ % len(specs.PALETTE)])))
            plotly_view(dict(data=cd, layout=specs.base_layout("Cumulative distribution", xaxis=dict(title=pn), yaxis=dict(title="Fraction <= x", gridcolor=specs.LINE))),
                        key=S.k("an_c") + f"{pn}{sp}{int(mask.sum())}", height=280)
        with t3:
            c1, c2, c3 = st.columns(3)
            xn = c1.selectbox("X", names, index=0, key=S.k("an_x", names))
            yn = c2.selectbox("Y", names, index=min(1, len(names) - 1), key=S.k("an_y", names))
            sp = c3.selectbox("Colour by", splits, index=1, key=S.k("an_cs", splits))
            c1, c2 = st.columns(2)
            lx, ly = c1.checkbox("Log X", key=S.k("an_lx")), c2.checkbox("Log Y", key=S.k("an_ly"))
            xp = an.crossplot(g, props, xn, yn, mask, sp)
            if np.isfinite(xp["r"]):
                kpis([("Correlation r", f"{xp['r']:.3f}"), ("R2", f"{xp['r2']:.3f}"), ("Cells", f"{xp['n_total']:,}"), ("Shown", f"{len(xp['x']):,}")])
            data = []
            for gi, gn in enumerate(xp["names"]):
                m = xp["group"] == gi
                if m.any():
                    data.append(dict(type="scattergl", mode="markers", x=xp["x"][m], y=xp["y"][m], name=gn, marker=dict(size=4, opacity=0.6, color=specs.PALETTE[gi % len(specs.PALETTE)])))
            if "slope" in xp:
                xl = np.array([xp["x"].min(), xp["x"].max()])
                data.append(dict(type="scatter", mode="lines", x=xl, y=xp["slope"] * xl + xp["intercept"], name="linear fit", line=dict(color="#222", dash="dash")))
            lay = specs.base_layout(None, xaxis=dict(title=xn, type="log" if lx else "linear", gridcolor=specs.LINE), yaxis=dict(title=yn, type="log" if ly else "linear", gridcolor=specs.LINE))
            plotly_view(dict(data=data, layout=lay), key=S.k("an_xp") + f"{xn}{yn}{sp}{lx}{ly}{int(mask.sum())}", height=380)
            if "slope" in xp:
                st.caption(f"Fit (all selected cells): {yn} = {xp['slope']:.4g} x {xn} + {xp['intercept']:.4g}")
        with t4:
            c1, c2 = st.columns(2)
            pn = c1.selectbox("Property", names, key=S.k("an_pp", names))
            zsel = c2.selectbox("Zone", ["All"] + [z.name for z in g.zones], key=S.k("an_pz"))
            pr = an.layer_profile(g, props, pn, mask, None if zsel == "All" else [z.name for z in g.zones].index(zsel))
            if len(pr["k"]):
                data = [dict(type="scatter", mode="lines", x=pr["p10"], y=pr["depth"], line=dict(width=0), showlegend=False, hoverinfo="skip"),
                        dict(type="scatter", mode="lines", x=pr["p90"], y=pr["depth"], fill="tonextx", fillcolor="rgba(0,120,200,0.18)", line=dict(width=0), name="P10 - P90"),
                        dict(type="scatter", mode="lines+markers", x=pr["mean"], y=pr["depth"], name="mean", line=dict(color=specs.PALETTE[0]), marker=dict(size=4),
                             text=[f"Layer {k + 1}" for k in pr["k"]])]
                lay = specs.base_layout(f"{pn} by layer", xaxis=dict(title=pn, gridcolor=specs.LINE), yaxis=dict(title=f"Mean depth ({un.z()})", autorange="reversed", gridcolor=specs.LINE))
                plotly_view(dict(data=data, layout=lay), key=S.k("an_pf") + f"{pn}{zsel}{int(mask.sum())}", height=420)
        with t5:
            c1, c2 = st.columns(2)
            pn = c1.selectbox("Property", names, key=S.k("an_mp", names))
            md = c2.selectbox("Map type", an.MAP_MODES, index=1, key=S.k("an_mm"))
            wts = ()
            if md == "thickness-weighted":
                wts = tuple(st.multiselect("Extra weights (cell thickness is always used)", names, default=["NTG"] if "NTG" in names else [], key=S.k("an_mw", names)))
            mp = an.map_2d(g, props, pn, mask, md, wts)
            lbl = {"sum": f"Sum of {pn}"}.get(md, f"{pn} ({md})")
            from ui import display
            plotly_view(display.property_map(p, g, pn, mp, lbl, props[pn].unit),
                        key=S.k("an_map") + f"{pn}{md}{wts}{int(mask.sum())}", height=420)
            st.caption("Maps are drawn in grid index space (I, J), so they are valid for rotated and refined grids. Use 'sum' on HCPV / STOIIP for an HC thickness style map.")
            with st.expander("Generate average maps for multiple parameters"):
                property_results.average_maps(p, prefix="an_average")
        with t6:
            _sections(p, g, names, props)
    except (an.AnalysisError, gsx.SectionError, V.VolError) as e:
        st.error(str(e))


def _sections(p, g, names, props):
    c1, c2 = st.columns([1, 2])
    mode = c1.radio("Section type", ["row (J)", "column (I)", "fence"], key=S.k("sc_mode"), horizontal=False)
    sel = c2.multiselect("Properties (up to 3, stacked)", names, default=names[:1], max_selections=3, key=S.k("sc_props", names))
    c1, c2, c3 = st.columns(3)
    ve = c1.number_input("Vertical exaggeration (single property)", 1.0, 50.0, 5.0, 1.0, key=S.k("sc_ve"))
    ctc = c2.checkbox("Show contacts", value=bool(p.volumetrics), key=S.k("sc_ct"))
    fl = c3.checkbox("Show faults (fence)", value=True, key=S.k("sc_fl"))
    owc = goc = None
    if ctc and p.volumetrics and not V.check_config(g, p.volumetrics):
        o3, g3, _ = V.contact_cubes(g, p.volumetrics, props)
        owc = o3.mean(axis=0)
        goc = np.nanmean(np.where(np.isfinite(g3), g3, np.nan), axis=0) if np.isfinite(g3).any() else None
    pts = None
    if mode == "row (J)":
        idx = st.slider("Row J", 1, g.nj, max(1, g.nj // 2), key=S.k("sc_j", [g.nj])) - 1
    elif mode == "column (I)":
        idx = st.slider("Column I", 1, g.ni, max(1, g.ni // 2), key=S.k("sc_i", [g.ni])) - 1
    else:
        if not p.fences:
            note("Digitise a fence in the Structural model page (cross-section tab) first.", warn=True)
            return
        fn = st.selectbox("Fence", list(p.fences), key=S.k("sc_fence", list(p.fences)))
        pts = np.asarray(p.fences[fn].pts, float)
    if not sel:
        return
    panels = []
    for n in sel:
        pr = props[n]
        vals = pr.values
        if pts is None:
            sec = gsx.grid_line_section(g, vals, "j" if mode == "row (J)" else "i", idx, owc, goc)
        else:
            sec = gsx.fence_property_section(g, vals, pts, list(p.faults.values()) if fl else None, owc, goc)
        from ui.scene import grid_property
        scale, _ = grid_property(g, n, props, p.display_settings.get("properties"))
        panels.append(dict(name=n, unit=pr.unit, sec=sec, discrete=pr.kind == "discrete",
                           scale=scale, stops=scale.get("stops", scale.get("colors"))))
    if not any(len(pn["sec"]["v"]) for pn in panels):
        note("The section contains no active cells.", warn=True)
        return
    plotly_view(specs.property_section(panels, None, ve if len(panels) == 1 else None, ctc, fl),
                key=S.k("sc_plot") + f"{mode}{sel}{idx if pts is None else 'f'}{ve}{ctc}{fl}", height=300 + 220 * len(panels))
    st.caption("Cells are the exact grid cells (row / column) or one ribbon per grid column crossed by the fence (layer top / base averaged over the column). "
               "Dashed red / orange: OWC / GOC from the Volumetrics set-up.")
