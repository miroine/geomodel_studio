"""Volumetrics: GRV / NRV / PV / HCPV / STOIIP / GIIP above the contacts, sensitivities and uncertainty."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un
from core import props as pp
from core import volumetrics as V
from ui import state as S
from ui import specs
from ui.components import plotly_view, viewer3d
from ui.scene import Scene
from ui.theme import banner, kpis, note


def _cfg(p, g):
    cfg = p.volumetrics
    zn = [z.name for z in g.zones]
    base = V.default_config(g)
    bad = (not cfg) or set(cfg.get("sw", {}).get("zone", {})) != set(zn)
    if bad:
        if cfg:                                         # keep what still applies
            base["contacts"]["owc"] = cfg.get("contacts", {}).get("owc", base["contacts"]["owc"])
        p.volumetrics = cfg = base
    _fill(cfg, base)
    return cfg


def _fill(cfg, base):
    """Add keys introduced by newer versions (old projects keep their values)."""
    for k, v in base.items():
        if k not in cfg:
            cfg[k] = v
        elif isinstance(v, dict) and isinstance(cfg[k], dict) and k not in ("zone",):
            _fill(cfg[k], v)


def _v2m3(p):
    return un.factor(p.crs["xy_unit"], "m") ** 2 * un.factor(p.crs["z_unit"], "m")


def _fmt(x, d=2):
    return "-" if x is None or not np.isfinite(x) else f"{x:,.{d}f}"


def _opt(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def _contact_extras(p, g, cfg, zu):
    c = cfg["contacts"]
    with st.expander("Contacts by zone / segment / region, tilted contacts, free-water level", expanded=bool(c["regions"]["values"]) or bool(c["tilt"]["gx"] or c["tilt"]["gy"])):
        opts = ["ZONE"] + [n for n, pr in p.properties.items() if pr.kind == "discrete" and pr.values.shape == (g.nk, g.nj, g.ni) and n in ("SEGMENT", "REGION", "FAULT_BLOCK", "PLANE_REGION", "FLUID") or
                           (pr.kind == "discrete" and pr.values.shape == (g.nk, g.nj, g.ni) and pr.legend)]
        opts = list(dict.fromkeys(opts))
        cur = c["regions"]["prop"] if c["regions"]["prop"] in opts else opts[0]
        c["regions"]["prop"] = st.selectbox("Region set for contacts", opts, index=opts.index(cur), key=S.k("vo_rprop", opts),
                                            help="Contacts given below replace the global / block contacts in the cells of that region (SEGMENT is made on the Properties page).")
        if c["regions"]["prop"] == "ZONE":
            vals = {str(i + 1): z.name for i, z in enumerate(g.zones)}
        else:
            pr = p.properties[c["regions"]["prop"]]
            vals = {str(int(u)): pr.legend.get(str(int(u)), f"{c['regions']['prop']} {int(u)}") for u in np.unique(np.rint(pr.values[g.actnum > 0]))}
        rows = [dict(Value=int(k), Name=n, OWC=c["regions"]["values"].get(k, {}).get("owc"), GOC=c["regions"]["values"].get(k, {}).get("goc")) for k, n in vals.items()]
        df0 = st.session_state.setdefault(S.k("vo_reg0", [c["regions"]["prop"], len(rows)]), pd.DataFrame(rows))
        ed = st.data_editor(df0, hide_index=True, disabled=["Value", "Name"], key=S.k("vo_reg", [c["regions"]["prop"], len(rows)]))
        c["regions"]["values"] = {str(int(r.Value)): dict(owc=_opt(r.OWC), goc=_opt(r.GOC)) for r in ed.itertuples() if _opt(r.OWC) is not None or _opt(r.GOC) is not None}
        st.caption("Leave OWC / GOC blank to keep the global (or fault-block) value. A region contact applies to every cell of that region.")
        a, b, d = st.columns(3)
        X, Y = g.center_xy()
        t = c["tilt"]
        t["gx"] = a.number_input(f"Tilt: {zu} per 1000 along X", -500.0, 500.0, float(t["gx"]) * 1000.0, 1.0, key=S.k("vo_tgx")) / 1000.0
        t["gy"] = b.number_input(f"Tilt: {zu} per 1000 along Y", -500.0, 500.0, float(t["gy"]) * 1000.0, 1.0, key=S.k("vo_tgy")) / 1000.0
        c["fwl_below"] = d.number_input(f"FWL below OWC ({zu})", 0.0, 1e4, float(c["fwl_below"]), 1.0, key=S.k("vo_fwl"),
                                        help="Only used by the saturation-height function: height is measured above the free-water level, the OWC limits the hydrocarbon column.")
        a, b = st.columns(2)
        t["xref"] = a.number_input("Tilt reference X", value=float(t["xref"] or np.mean(X)), key=S.k("vo_txr"))
        t["yref"] = b.number_input("Tilt reference Y", value=float(t["yref"] or np.mean(Y)), key=S.k("vo_tyr"))


def _fluid_view(p, g, cfg, res):
    st.markdown("### In-place fluids - ternary 3D")
    st.caption("Green = oil, red = free gas, blue = water. Colours blend by reservoir-condition fluid pore volume, "
               "including mixed contact cells and water below OWC. Grey = no included net pore volume. "
               "Solution gas remains part of the oil phase; STOIIP/GIIP reporting is unchanged.")
    cells = res["cells"]
    try:
        colors = V.ternary_colors(cells["OIL_PV"], cells["GAS_PV"], cells["WATER_PV"])
    except V.VolError as exc:
        st.error(str(exc))
        return
    a, b, c = st.columns(3)
    i0 = a.slider("Fluid view: first I", 0, max(g.ni - 1, 0), 0, key=S.k("vo_3i")) if g.ni > 1 else 0
    j0 = b.slider("Fluid view: first J", 0, max(g.nj - 1, 0), 0, key=S.k("vo_3j")) if g.nj > 1 else 0
    ve = c.slider("Fluid view: vertical exaggeration", 1.0, 20.0, 3.0, 0.5, key=S.k("vo_3ve"))
    mesh = st.checkbox("Fluid view: show cell edges", value=False, key=S.k("vo_3mesh"))
    layers = S.grid_view_layers(g, "vo_3")
    included = np.isin(g.layer_zone, [i for i, z in enumerate(g.zones) if z.name in cfg["zones"]])
    layers &= included
    legend = dict(title="Fluid pore-volume mixture", items=[
        dict(label="Oil", color="#00FF00"), dict(label="Gas", color="#FF0000"),
        dict(label="Water", color="#0000FF"), dict(label="No net pore volume", color="#BEBEBE")])
    sc = Scene((p.lattice.xori, p.lattice.yori))
    try:
        sc.grid(g, name="In-place fluids", prop="Zone", i0=i0, j0=j0, layer_mask=layers,
                cell_colors=colors, color_legend=legend)
        viewer3d(sc, key=S.k("vo_fluid3d"), height=720, ve=ve, mesh=mesh)
    except ValueError as exc:
        st.warning(str(exc))
    if not layers.any():
        st.warning("No included reservoir layers match the fluid view filters.")
    with st.expander("Ternary colour key"):
        fractions = np.array([(oil / 20, gas / 20, (20 - oil - gas) / 20)
                              for oil in range(21) for gas in range(21 - oil)])
        rgb = V.ternary_colors(*fractions.T)
        plotly_view(dict(data=[dict(type="scatterternary", a=fractions[:, 0].tolist(),
                                   b=fractions[:, 1].tolist(), c=fractions[:, 2].tolist(), mode="markers",
                                   marker=dict(size=12, color=[f"rgb({r},{g},{b})" for r, g, b in rgb]),
                                   hovertemplate="Oil: %{a:.0%}<br>Gas: %{b:.0%}<br>Water: %{c:.0%}<extra></extra>")],
                         layout=specs.base_layout("Reservoir fluid pore-volume fractions", showlegend=False,
                                                  ternary=dict(sum=1, aaxis=dict(title="Oil", color="#00B050"),
                                                               baxis=dict(title="Gas", color="#FF0000"),
                                                               caxis=dict(title="Water", color="#0000FF")))),
                    key=S.k("vo_ternary_key"), height=360)


def render():
    p = S.proj()
    g = p.grid
    banner("8 - Volumetrics", "Hydrocarbons in place from the 3D grid, contacts and saturations")
    if g is None:
        note("Build the 3D grid first (page 6).", warn=True)
        return
    cfg = _cfg(p, g)
    v2 = _v2m3(p)
    zu = un.z()
    t1, t2, t3, t4, t5 = st.tabs(["Setup", "Results", "Contact scan", "Uncertainty", "Realisations & store"])

    with t1:
        from views import contact_settings
        system = contact_settings.fluid_system(cfg["contacts"], lambda field, current: S.k("vo_" + field + "_" + current))
        c1, c2, c3 = st.columns(3)
        cfg["contacts"]["owc"] = c1.number_input(f"{'GWC' if system == 'gas' else 'OWC'} depth ({zu})", value=float(cfg["contacts"]["owc"]), step=5.0, key=S.k("vo_owc"))
        use_goc = system == "oil_gas" or (system == "auto" and c2.checkbox("Gas cap (GOC)", value=cfg["contacts"]["goc"] is not None, key=S.k("vo_usegoc")))
        if use_goc:
            dflt = cfg["contacts"]["goc"] if cfg["contacts"]["goc"] is not None else cfg["contacts"]["owc"] - 30.0
            cfg["contacts"]["goc"] = c3.number_input(f"GOC depth ({zu})", value=float(dflt), step=5.0, key=S.k("vo_goc"))
        else:
            cfg["contacts"]["goc"] = None
        nb = int(g.block.max())
        if nb > 1:
            with st.expander(f"Contacts per fault block ({nb} blocks) - leave blank to use the global value", expanded=bool(cfg["contacts"]["blocks"])):
                rows = [dict(Block=b, OWC=cfg["contacts"]["blocks"].get(str(b), {}).get("owc"), GOC=cfg["contacts"]["blocks"].get(str(b), {}).get("goc"))
                        for b in range(1, nb + 1)]
                df0 = st.session_state.setdefault(S.k("vo_blk0", [nb]), pd.DataFrame(rows))
                ed = st.data_editor(df0, hide_index=True, key=S.k("vo_blk", [nb]), disabled=["Block"])
                cfg["contacts"]["blocks"] = {str(int(r.Block)): dict(owc=_opt(r.OWC), goc=_opt(r.GOC)) for r in ed.itertuples()
                                             if _opt(r.OWC) is not None or _opt(r.GOC) is not None}
        _contact_extras(p, g, cfg, zu)
        a, b, c = st.columns(3)
        cfg["fluid"]["Bo"] = a.number_input("Bo (rm3/Sm3)", value=float(cfg["fluid"]["Bo"]), min_value=0.5, step=0.01, format="%.3f", key=S.k("vo_bo"))
        cfg["fluid"]["Bg"] = b.number_input("Bg (rm3/Sm3)", value=float(cfg["fluid"]["Bg"]), min_value=0.0001, step=0.0005, format="%.5f", key=S.k("vo_bg"))
        cfg["fluid"]["Rs"] = c.number_input("Rs (Sm3/Sm3), solution gas in the oil", value=float(cfg["fluid"]["Rs"]), min_value=0.0, step=10.0, key=S.k("vo_rs"))
        cfg["zones"] = st.multiselect("Zones included in the reservoir", [z.name for z in g.zones],
                                      default=[n for n in cfg["zones"] if n in [z.name for z in g.zones]], key=S.k("vo_zones", [z.name for z in g.zones]))
        st.markdown("**Rock and saturation sources**")
        pnames = [n for n, v in p.properties.items() if v.values.shape == (g.nk, g.nj, g.ni)]
        a, b, c = st.columns(3)
        opts = ["zone"] + pnames
        for col, key, lab in ((a, "phi", "Porosity from"), (b, "ntg", "Net-to-gross from")):
            cur = cfg["src"][key] if cfg["src"][key] in opts else "zone"
            cfg["src"][key] = col.selectbox(lab, opts, index=opts.index(cur), key=S.k("vo_s" + key, opts),
                                            format_func=lambda n: "zone table" if n == "zone" else n)
        cfg["sw"]["mode"] = c.selectbox("Water saturation", V.SW_MODES, index=V.SW_MODES.index(cfg["sw"]["mode"]), key=S.k("vo_swm"),
                                        format_func=lambda m: dict(constant="constant per zone", property="from a property", satheight="saturation-height function")[m])
        if cfg["sw"]["mode"] == "constant":
            zdf0 = st.session_state.setdefault(S.k("vo_sw0", tuple(cfg["sw"]["zone"])), pd.DataFrame([dict(Zone=k, Sw=v) for k, v in cfg["sw"]["zone"].items()]))
            ze = st.data_editor(zdf0, hide_index=True, disabled=["Zone"], key=S.k("vo_sw", tuple(cfg["sw"]["zone"])))
            cfg["sw"]["zone"] = {str(r.Zone): float(np.clip(r.Sw, 0, 1)) for r in ze.itertuples()}
        elif cfg["sw"]["mode"] == "property":
            if not pnames:
                st.warning("No properties yet - create SW on the Properties page (calculator or stochastic modelling).")
            else:
                cur = cfg["sw"]["prop"] if cfg["sw"]["prop"] in pnames else pnames[0]
                cfg["sw"]["prop"] = st.selectbox("Sw property", pnames, index=pnames.index(cur), key=S.k("vo_swp", pnames))
        else:
            a, b, c = st.columns(3)
            cfg["sw"]["swirr"] = a.number_input("Swirr", 0.0, 0.9, float(cfg["sw"]["swirr"]), 0.01, key=S.k("vo_swirr"))
            cfg["sw"]["entry"] = b.number_input(f"Entry height ({zu})", 0.01, 1e5, float(cfg["sw"]["entry"]), 0.5, key=S.k("vo_ent"))
            cfg["sw"]["lam"] = c.number_input("Exponent", 0.05, 5.0, float(cfg["sw"]["lam"]), 0.05, key=S.k("vo_lam"))
            st.caption("Sw = Swirr + (1 - Swirr) x (entry / height above OWC)^exponent, evaluated at the cell centre.")
        a, b, c = st.columns(3)
        cfg["cut"]["phi"] = a.number_input("Net cut-off: porosity >=", 0.0, 0.5, float(cfg["cut"]["phi"]), 0.01, key=S.k("vo_cphi"))
        cfg["cut"]["ntg"] = b.number_input("Net cut-off: NTG >=", 0.0, 1.0, float(cfg["cut"]["ntg"]), 0.05, key=S.k("vo_cntg"))
        cfg["cut"]["sw"] = c.number_input("Net cut-off: Sw <=", 0.0, 1.0, float(cfg["cut"]["sw"]), 0.05, key=S.k("vo_csw"))
        cfg["display"] = st.radio("Reporting units", ["metric", "field"], index=["metric", "field"].index(cfg["display"]), horizontal=True, key=S.k("vo_disp"),
                                  format_func=lambda m: "metric (MSm3, GSm3)" if m == "metric" else "field (MMstb, Bscf)")
        for e in V.check_config(g, cfg):
            st.warning(e)

    errs = V.check_config(g, cfg)
    res = None
    if not errs:
        try:
            res = V.compute(g, cfg, p.properties, v2)
        except V.VolError as e:
            with t1:
                st.error(str(e))
    disp = cfg["display"]

    with t2:
        if res is None:
            note("Fix the set-up first.", warn=True)
        else:
            _fluid_view(p, g, cfg, res)
            so, uo = V.to_display(res["total"]["STOIIP"], "oil", disp)
            gg, ug = V.to_display(res["total"]["GIIP"], "gas", disp)
            grv = res["total"]["oil"]["GRV"] + res["total"]["gas"]["GRV"]
            hcpv = res["total"]["oil"]["HCPV"] + res["total"]["gas"]["HCPV"]
            kpis([(f"STOIIP ({uo})", _fmt(so)), (f"GIIP ({ug})", _fmt(gg, 3)), ("GRV (10^6 m3)", _fmt(grv / 1e6, 1)), ("HCPV (10^6 m3)", _fmt(hcpv / 1e6, 2))])
            st.markdown("**By zone**")
            zrows = []
            for r in res["by_zone"]:
                zrows.append({"Zone": r["zone"], "In": "yes" if r["included"] else "", "GRV oil": r["GRV_oil"] / 1e6, "GRV gas": r["GRV_gas"] / 1e6, "NRV": r["NRV"] / 1e6,
                              "PV": r["PV"] / 1e6, "HCPV oil": r["HCPV_oil"] / 1e6, "HCPV gas": r["HCPV_gas"] / 1e6,
                              f"STOIIP ({uo})": V.to_display(r["STOIIP"], "oil", disp)[0], f"GIIP ({ug})": V.to_display(r["GIIP"], "gas", disp)[0]})
            st.dataframe(pd.DataFrame(zrows).round(3), hide_index=True)
            st.caption("Rock, pore and hydrocarbon pore volumes in 10^6 m3 (reservoir conditions).")
            if res["by_block"] and len(res["by_block"]) > 1:
                st.markdown("**By fault block**")
                brows = [{"Block": r["block"], f"OWC ({zu})": r["OWC"], f"GOC ({zu})": r["GOC"], "GRV oil": r["GRV_oil"] / 1e6, "GRV gas": r["GRV_gas"] / 1e6,
                          f"STOIIP ({uo})": V.to_display(r["STOIIP"], "oil", disp)[0], f"GIIP ({ug})": V.to_display(r["GIIP"], "gas", disp)[0]} for r in res["by_block"]]
                st.dataframe(pd.DataFrame(brows).round(3), hide_index=True)
            ropts = ["ZONE", "BLOCK"] + [n for n, pr in p.properties.items() if pr.kind == "discrete" and pr.values.shape == (g.nk, g.nj, g.ni) and pr.legend]
            ropts = list(dict.fromkeys(ropts))
            cfg["report_by"] = st.selectbox("Volumes by region set", ropts, index=ropts.index(cfg["report_by"]) if cfg.get("report_by") in ropts else 0, key=S.k("vo_rby", ropts))
            try:
                rr_ = V.by_region(res, g, p.properties, cfg["report_by"])
                st.dataframe(pd.DataFrame([{"Value": r["value"], "Region": r["name"], "GRV": r["GRV"] / 1e6, "HCPV": r["HCPV"] / 1e6, f"STOIIP ({uo})": V.to_display(r["STOIIP"], "oil", disp)[0],
                                            f"GIIP ({ug})": V.to_display(r["GIIP"], "gas", disp)[0]} for r in rr_]).round(3), hide_index=True)
            except V.VolError as e:
                st.warning(str(e))
            names = [r["zone"] for r in res["by_zone"] if r["included"]]
            vals = [V.to_display(r["STOIIP"], "oil", disp)[0] for r in res["by_zone"] if r["included"]]
            if names:
                lay = specs.base_layout("STOIIP by zone", yaxis=dict(title=uo, gridcolor=specs.LINE), xaxis=dict(title=""))
                plotly_view(dict(data=[dict(type="bar", x=names, y=vals, marker=dict(color="#00B050"))], layout=lay), key=S.k("vo_bar") + str(round(sum(vals), 3)), height=280)
            tbl = pd.DataFrame([{"Quantity": "GRV oil (10^6 m3)", "Value": res["total"]["oil"]["GRV"] / 1e6}, {"Quantity": "NRV oil (10^6 m3)", "Value": res["total"]["oil"]["NRV"] / 1e6},
                                {"Quantity": "PV oil (10^6 m3)", "Value": res["total"]["oil"]["PV"] / 1e6}, {"Quantity": "HCPV oil (10^6 m3)", "Value": res["total"]["oil"]["HCPV"] / 1e6},
                                {"Quantity": f"STOIIP ({uo})", "Value": so}, {"Quantity": f"GIIP free gas ({ug})", "Value": V.to_display(res["total"]["gas"]["GIIP_free"], "gas", disp)[0]},
                                {"Quantity": f"GIIP total incl. solution gas ({ug})", "Value": gg}])
            st.download_button("Download results (CSV)", pd.DataFrame(zrows).to_csv(index=False).encode(), "volumetrics.csv", "text/csv", key=S.k("vo_dl"))

    with t3:
        if res is None:
            note("Fix the set-up first.", warn=True)
        else:
            c1, c2 = st.columns(2)
            rng = c1.number_input(f"Scan OWC +/- ({zu})", 1.0, 5000.0, 100.0, 10.0, key=S.k("vo_rng"))
            npts = int(c2.number_input("Points", 5, 41, 15, 2, key=S.k("vo_np")))
            if st.button("Run contact scan", type="primary", key=S.k("vo_scan")):
                x = np.linspace(cfg["contacts"]["owc"] - rng, cfg["contacts"]["owc"] + rng, npts)
                st.session_state[S.k("vo_scan_res")] = (x, V.scan_contact(g, cfg, p.properties, v2, x))
            sc = st.session_state.get(S.k("vo_scan_res"))
            if sc is not None:
                x, y = sc
                yy = [V.to_display(v, "oil", disp)[0] for v in y]
                lay = specs.base_layout("STOIIP versus OWC depth (same OWC in all blocks)", xaxis=dict(title=f"OWC ({zu})"), yaxis=dict(title=V.to_display(1, "oil", disp)[1], gridcolor=specs.LINE))
                plotly_view(dict(data=[dict(type="scatter", mode="lines+markers", x=x, y=yy, line=dict(color=specs.PALETTE[0]))], layout=lay), key=S.k("vo_scanp") + f"{len(x)}{yy[-1]:.3f}", height=320)
                st.dataframe(pd.DataFrame({f"OWC ({zu})": x, V.to_display(1, "oil", disp)[1]: yy}).round(3), hide_index=True)

    with t4:
        if res is None:
            note("Fix the set-up first.", warn=True)
        else:
            u = cfg["unc"]
            st.caption("One-at-a-time sensitivities (tornado) and a Monte-Carlo with triangular distributions (min - base - max) on the scalar uncertainties.")
            rows = [dict(Parameter=V.PARAM_LABEL[k], Min=u[k][0], Max=u[k][1]) for k in V.PARAMS]
            df0 = st.session_state.setdefault(S.k("vo_u0"), pd.DataFrame(rows))
            ed = st.data_editor(df0, hide_index=True, disabled=["Parameter"], key=S.k("vo_u"))
            for k, r in zip(V.PARAMS, ed.itertuples()):
                u[k] = [float(min(r.Min, r.Max)), float(max(r.Min, r.Max))]
            a_, b_ = st.columns(2)
            sg = a_.number_input(f"Structural uncertainty: depth sigma ({zu})", 0.0, 500.0, float(u["struct"][0]), 1.0, key=S.k("vo_ssg"),
                                 help="Each Monte-Carlo sample shifts the contacts by a smooth random field (structure moving against the contact); 0 = off.")
            rg_ = b_.number_input("Correlation length (cells)", 0.5, 50.0, float(u["struct"][1]), 0.5, key=S.k("vo_srg"))
            u["struct"] = [float(sg), float(rg_)]
            c1, c2, c3 = st.columns(3)
            u["n"] = int(c1.number_input("Monte-Carlo samples", 20, 2000, int(u["n"]), 20, key=S.k("vo_n")))
            u["seed"] = int(c2.number_input("Seed", 0, 99999, int(u["seed"]), 1, key=S.k("vo_seed")))
            key = c3.selectbox("Result", ["STOIIP", "GIIP"], key=S.k("vo_ukey"))
            kind = "oil" if key == "STOIIP" else "gas"
            unit = V.to_display(1, kind, disp)[1]
            if st.button("Run tornado and Monte-Carlo", type="primary", key=S.k("vo_unc")):
                with st.spinner("Running..."):
                    st.session_state[S.k("vo_unc_res")] = (key, V.tornado(g, cfg, p.properties, v2, key), V.monte_carlo(g, cfg, p.properties, v2, key))
            ur = st.session_state.get(S.k("vo_unc_res"))
            if ur is not None:
                k0, tor, mc = ur
                kind = "oil" if k0 == "STOIIP" else "gas"
                cv = lambda x: V.to_display(x, kind, disp)[0]
                base = cv(tor["base"])
                rws = tor["rows"][::-1]
                data = [dict(type="bar", orientation="h", y=[r["label"] for r in rws], x=[cv(r["low"]) - base for r in rws], base=[base] * len(rws), name="low input",
                             marker=dict(color=specs.PALETTE[1])),
                        dict(type="bar", orientation="h", y=[r["label"] for r in rws], x=[cv(r["high"]) - base for r in rws], base=[base] * len(rws), name="high input",
                             marker=dict(color=specs.PALETTE[0]))]
                plotly_view(dict(data=data, layout=specs.base_layout(f"Tornado - {k0} (base {base:,.2f} {unit})", barmode="overlay", xaxis=dict(title=unit, gridcolor=specs.LINE))),
                            key=S.k("vo_torn") + f"{base:.3f}", height=300)
                pc = V.percentiles(mc)
                kpis([("P90", _fmt(cv(pc["P90"]))), ("P50", _fmt(cv(pc["P50"]))), ("P10", _fmt(cv(pc["P10"]))), ("Mean", _fmt(cv(pc["mean"])))])
                plotly_view(specs.value_histogram({k0: np.array([cv(x) for x in mc])}, f"Monte-Carlo {k0} ({len(mc)} samples)", unit, bins=25), key=S.k("vo_mch") + f"{len(mc)}{pc['P50']:.1f}", height=280)

    with t5:
        if res is None:
            note("Fix the set-up first.", warn=True)
        else:
            ids = V.realisation_ids(p.properties, [n for n in (cfg["src"]["phi"], cfg["src"]["ntg"]) if n not in ("zone", "one")] or ["PORO"])
            if not ids:
                st.info("No stochastic realisations (PORO_R2, ...) found. Run the stochastic workflow on the Properties page with several realisations and set the porosity / NTG "
                        "sources to those properties to get P90 / P50 / P10 over realisations.")
            elif st.button(f"Compute volumetrics for {len(ids)} realisations", key=S.k("vo_real")):
                st.session_state[S.k("vo_real_res")] = V.over_realisations(g, cfg, p.properties, v2)
            rr = st.session_state.get(S.k("vo_real_res"))
            if rr:
                df = pd.DataFrame(rr)
                so_ = np.array([V.to_display(x, "oil", disp)[0] for x in df["STOIIP"]])
                pc = V.percentiles(so_)
                kpis([(f"STOIIP P90 ({V.to_display(1, 'oil', disp)[1]})", _fmt(pc["P90"])), ("P50", _fmt(pc["P50"])), ("P10", _fmt(pc["P10"])), ("Realisations", len(df))])
                df["STOIIP"], df["GIIP"] = so_, [V.to_display(x, "gas", disp)[0] for x in df["GIIP"]]
                df["GRV"], df["HCPV"] = df["GRV"] / 1e6, df["HCPV"] / 1e6
                st.dataframe(df.round(3), hide_index=True)
            st.divider()
            st.markdown("**Store the base-case result as cell properties**")
            st.caption("FLUID (1 gas, 2 oil, 3 water), SW, GRV, HCPV, STOIIP, GIIP (per cell, m3), NET (cut-off flag). They can be coloured in the 3D window, "
                       "sectioned, analysed and exported.")
            if st.button("Store as properties", key=S.k("vo_store"), disabled=res is None):
                units_ = dict(FLUID="", SW="frac", GRV="m3", HCPV="m3", STOIIP="m3", GIIP="m3", NET="")
                for n_, arr in res["cells"].items():
                    if n_ in units_:
                        p.properties["VOL_" + n_ if n_ not in ("FLUID", "SW") else n_] = pp.make_property(
                            g, "VOL_" + n_ if n_ not in ("FLUID", "SW") else n_, arr, "discrete" if n_ in ("FLUID", "NET") else "continuous", units_[n_], "volumetrics", legend=V.FLUID_LEGEND if n_ == "FLUID" else None)
                st.success("Stored FLUID, SW, VOL_GRV, VOL_HCPV, VOL_STOIIP, VOL_GIIP and VOL_NET.")
