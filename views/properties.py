"""Properties: cell properties linked to the 3D grid + a restricted Python calculator."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core import props as pp
from core import geostat as gs
from core import regions as rg
from core import logs as lg
from core import facies as fa
from core import volumetrics as vol
from ui import state as S
from ui import specs
from ui.components import plotly_view, viewer3d
from ui.theme import banner, kpis, note

EXAMPLES = {
    "Porosity-depth trend": "PORO = clip(0.34 * exp(-DEPTH / 7000), 0.02, 0.35)",
    "Perm from porosity (poroperm)": "PERMX = 10 ** (14 * PORO - 1.8)\nPERMY = PERMX\nPERMZ = PERMX * 0.1",
    "Zone values": "NTG = by_zone(0.1, 0.3, 0.9, 0.8, 0.2)",
    "Zone with noise": "PORO = by_zone(0.1, 0.12, 0.24, 0.19, 0.08) + 0.02 * gauss(11)",
    "Conditional edit": "PORO[ZONE == 3] = PORO * 1.1\nPORO = clip(PORO, 0, 0.4)",
    "Facies by depth (discrete)": "FACIES = where(DEPTH < 2100, 1, where(DEPTH < 2200, 2, 3))",
    "Smooth a property": "PORO_S = smooth(PORO, 1.5)",
    "Hydrocarbon column (OWC)": "OILFLAG = where(DEPTH < 2150, 1, 0)\nPORV = PORO * NTG * VOLUME * ACTNUM",
}


def _table(p, g):
    rows = []
    for n, pr in p.properties.items():
        s = pr.stats(g.actnum) if pr.values.shape == (g.nk, g.nj, g.ni) else {}
        rows.append({"Property": n, "Type": pr.kind, "Unit": pr.unit, "Source": pr.source, "Stale": "yes" if pr.stale else "",
                     "Min": s.get("min"), "Mean": s.get("mean"), "Max": s.get("max"), "Std": s.get("std")})
    return pd.DataFrame(rows)


def render():
    p = S.proj()
    g = p.grid
    banner("7 - Properties", (f"{len(p.properties)} cell propert{'ies' if len(p.properties) != 1 else 'y'} on the {g.ni} x {g.nj} x {g.nk} grid"
                              if g else "Populate the grid with petrophysical and other cell properties"))
    if g is None:
        note("Build the 3D grid first (page 6). Properties are arrays that live on the grid cells.", warn=True)
        return
    stale = [n for n, v in p.properties.items() if v.stale]
    kpis([("Grid", f"{g.ni} x {g.nj} x {g.nk}"), ("Active cells", f"{int(g.actnum.sum()):,}"), ("Properties", len(p.properties)),
          ("Stale", len(stale))])
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["Properties", "Calculator", "View", "Statistics by zone", "Stochastic modelling", "Planes & regions", "Well logs & kriging", "Facies modelling"])
    with t6:
        _planes_regions(p, g)
    with t7:
        _well_logs(p, g)
    with t8:
        _facies(p, g)

    with t1:
        c1, c2, c3 = st.columns(3)
        if c1.button("Populate PORO, PERMX/Y/Z, NTG from the zone table", type="primary", key=S.k("pr_zone")):
            p.properties.update(pp.zone_defaults(g))
            st.rerun()
        if c2.button("Recompute stale properties", disabled=not stale, key=S.k("pr_recomp")):
            for m in pp.recompute_stale(p.properties, g):
                st.info(m)
            for v in p.properties.values():                  # anything still stale that could not be recomputed keeps its flag
                if v.stale and v.source in ("manual", "import"):
                    v.stale = False
            st.rerun()
        with st.expander("Generate geometric properties (depth, zone number, I / J / K, ...)", expanded=not p.properties):
            gsel = st.multiselect("Properties", list(pp.GEO_PROPS), default=["DEPTH", "DZ", "ZONE", "K", "ZFRAC", "VOLUME"],
                                  format_func=lambda n: f"{n} - {pp.GEO_PROPS[n][2]}", key=S.k("pr_geo"))
            if st.button("Generate", disabled=not gsel, key=S.k("pr_geogen")):
                p.properties.update(pp.geometry_properties(g, gsel))
                st.rerun()
            st.caption("Snapshots stored as ordinary properties (colour them, export them, use them in the calculator). "
                       "The calculator also offers these as live read-only variables.")
        if stale:
            st.warning("The grid geometry changed after these were made: " + ", ".join(stale) + ". Recompute them (zone and calculator "
                       "properties can be regenerated).")
        if p.properties:
            st.dataframe(_table(p, g).round(4), hide_index=True)
        else:
            note("No properties yet. Populate from the zone table, or use the calculator to create your own.")
        with st.expander("Create a constant property"):
            a, b, c, d = st.columns(4)
            nm = a.text_input("Name", "PORO_CST", key=S.k("pr_nm"))
            val = b.number_input("Value", value=0.2, format="%g", key=S.k("pr_val"))
            kind = c.selectbox("Type", pp.KINDS, key=S.k("pr_kind"))
            unit = d.text_input("Unit", "", key=S.k("pr_unit"))
            if st.button("Create", key=S.k("pr_mk")):
                if not nm.isidentifier() or nm.upper() in pp.GEOMETRIC:
                    st.error("Use a simple name that is not a geometry variable.")
                else:
                    p.properties[nm] = pp.make_property(g, nm, val, kind, unit, "manual")
                    st.rerun()
        if p.properties:
            with st.expander("Rename / delete"):
                a, b, c = st.columns([2, 2, 1])
                sel = a.selectbox("Property", list(p.properties), key=S.k("pr_sel", list(p.properties)))
                new = b.text_input("New name", sel, key=S.k("pr_ren", sel))
                if c.button("Rename", key=S.k("pr_rn")) and new != sel and new.isidentifier() and new not in p.properties:
                    p.properties = {(new if k == sel else k): v for k, v in p.properties.items()}
                    p.properties[new].name = new
                    st.rerun()
                if c.button("Delete", key=S.k("pr_del")):
                    p.properties.pop(sel, None)
                    st.rerun()
        long_ = [n for n in p.properties if len(n) > 8]
        if long_:
            st.caption("Names longer than 8 characters (" + ", ".join(long_) + ") cannot be written as Eclipse keywords.")

    with t2:
        st.caption("A restricted Python calculator working on whole grid arrays. Existing properties and the geometry variables are available "
                   "by name; assignments create or overwrite properties.")
        a, b = st.columns([3, 2])
        ex = b.selectbox("Examples", list(EXAMPLES), key=S.k("pr_ex"))
        b.button("Load example", key=S.k("pr_exld"), on_click=lambda: st.session_state.__setitem__(S.k("pr_code"), EXAMPLES[st.session_state[S.k("pr_ex")]]))
        code = a.text_area("Script", value=EXAMPLES["Porosity-depth trend"], height=180, key=S.k("pr_code"))
        c1, c2, c3 = st.columns(3)
        out_name = c1.text_input("Output name (single-expression scripts)", "RESULT", key=S.k("pr_out"))
        kind = c2.selectbox("Result type", pp.KINDS, key=S.k("pr_rkind"))
        unit = c3.text_input("Unit", "", key=S.k("pr_runit"))
        if st.button("Run and store", type="primary", key=S.k("pr_run")):
            try:
                res = pp.run_calculator(code, g, p.properties, out_name)
                for n, v in res.items():
                    old = p.properties.get(n)
                    p.properties[n] = pp.make_property(g, n, v, kind if not old or n == out_name or kind != "continuous" else old.kind,
                                                       unit or (old.unit if old else ""), "calculator", code)
                st.session_state["pr_last"] = list(res)
                st.rerun()
            except pp.CalcError as e:
                st.error(str(e))
        if st.session_state.get("pr_last"):
            last = [n for n in st.session_state.pop("pr_last") if n in p.properties]
            st.success("Stored: " + ", ".join(last))
            st.dataframe(_table(p, g).query("Property in @last").round(4), hide_index=True)
        with st.expander("Variables and functions"):
            st.markdown("**Geometry (read-only):** " + ", ".join(f"`{n}`" for n in pp.GEOMETRIC) +
                        f"  \n**Properties:** {', '.join(f'`{n}`' for n in p.properties) or 'none yet'}  \n**Constants:** `pi`, `nan`, `inf`")
            st.markdown("\n".join(f"- `{k}` - {v}" for k, v in pp.FUNCTION_HELP.items()))
            st.markdown("Operators: `+ - * / // % **`, comparisons, `&` `|` `~` for masks, `a if c else b`. "
                        "Mask assignment: `PORO[ZONE == 3] = 0.1`. No imports, attributes, loops or text.")

    with t3:
        if not p.properties:
            note("Create a property first.")
        else:
            a, b, c, d = st.columns(4)
            names = list(p.properties)
            prop = a.selectbox("Property", names, key=S.k("pv_prop", names))
            i0 = b.slider("Cut: start column i", 0, g.ni - 1, 0, key=S.k("pv_i"))
            j0 = c.slider("Cut: start row j", 0, g.nj - 1, 0, key=S.k("pv_j"))
            ve = d.slider("V.E.", 1.0, 20.0, 4.0, 0.5, key=S.k("pv_ve"))
            try:
                sc = S.build_scene(p, surfaces=[], faults=False, polygons=False, wells=False, tops=False, grid=g, prop=prop, i0=i0, j0=j0)
                viewer3d(sc, key=S.k("prop3d"), height=600, ve=ve)
            except ValueError as e:
                st.warning(str(e))
            pr = p.properties[prop]
            k = st.slider("Layer k (map)", 1, g.nk, max(g.nk // 2, 1), key=S.k("pv_k"))
            m1, m2 = st.columns(2)
            v2 = np.where(g.actnum[k - 1] > 0, pr.values[k - 1], np.nan)
            with m1:
                plotly_view(specs.layer_map(v2, f"{prop}, layer {k}", prop), key=S.k("pv_map") + f"{prop}{k}{id(pr)}", height=380)
            with m2:
                act = g.actnum > 0
                groups = {z.name: pr.values[np.broadcast_to((g.layer_zone == zi)[:, None, None], act.shape) & act] for zi, z in enumerate(g.zones)}
                plotly_view(specs.value_histogram(groups, f"{prop} by zone", prop), key=S.k("pv_hist") + f"{prop}{id(pr)}", height=380)

    with t4:
        if not p.properties:
            note("Create a property first.")
        else:
            act = g.actnum > 0
            rows = []
            for n, pr in p.properties.items():
                if pr.values.shape != act.shape:
                    continue
                for zi, z in enumerate(g.zones):
                    m = np.broadcast_to((g.layer_zone == zi)[:, None, None], act.shape) & act
                    v = pr.values[m]
                    v = v[np.isfinite(v)]
                    rows.append({"Property": n, "Zone": z.name, "Cells": int(m.sum()),
                                 "Min": float(v.min()) if v.size else None, "Mean": float(v.mean()) if v.size else None,
                                 "Max": float(v.max()) if v.size else None})
            st.dataframe(pd.DataFrame(rows).round(4), hide_index=True)
            if "PORO" in p.properties:
                ntg = p.properties["NTG"].values if "NTG" in p.properties else 1.0
                pv = float((g.bulk_volume() * np.nan_to_num(p.properties["PORO"].values) * np.nan_to_num(ntg) * act).sum())
                st.caption(f"Pore volume (bulk x NTG x PORO, active cells): {pv / 1e6:.2f} M{un.xy()}2{un.z()}  (units follow the project).")

    with t5:
        _stochastic(p, g)


# ---------------------------------------------------------------------------------------------
ROW_COLS = ["zone", "simulate", "p1", "p2", "p3", "vmin", "vmax", "vtype", "major", "minor", "vert", "azimuth", "nugget"]
PROP_LABEL = {"PORO": "Porosity", "PERM": "Permeability (PERMX, mD)", "NTG": "Net-to-gross"}


def _cfg(p, g):
    cfg = p.stochastic
    zn = [z.name for z in g.zones]
    ok_ = bool(cfg) and all([r["zone"] for r in cfg["props"][k]["rows"]] == zn for k in gs.PROPS)
    if not ok_:
        cfg = gs.default_config(g)
        p.stochastic = cfg
    return cfg


def _plain_row(r):
    return dict(zone=str(r["zone"]), simulate=bool(r["simulate"]), p1=float(r["p1"]), p2=float(r["p2"]), p3=float(r["p3"]),
                vmin=float(r["vmin"]), vmax=float(r["vmax"]), vtype=str(r["vtype"]) if str(r["vtype"]) in gs.VARIOGRAMS else "spherical",
                major=float(r["major"]), minor=float(r["minor"]), vert=float(r["vert"]), azimuth=float(r["azimuth"]), nugget=float(r["nugget"]))


def _stochastic(p, g):
    cfg = _cfg(p, g)
    st.caption("Generate porosity, permeability and net-to-gross as Gaussian random fields with a variogram per zone, forced onto a target histogram, "
               "with cross-correlation and net/gross cut-offs. Zones are simulated independently; no well conditioning.")
    with st.expander("1  Setup", expanded=True):
        a, b, c, d = st.columns(4)
        cfg["seed"] = int(a.number_input("Random seed", 0, 10_000_000, int(cfg["seed"]), key=S.k("sx_seed")))
        cfg["nreal"] = int(b.number_input("Realisations", 1, 10, int(cfg["nreal"]), key=S.k("sx_nreal"),
                                          help="With more than one, properties are named PORO_R1, PORO_R2 ..."))
        cfg["perm_mode"] = c.radio("Permeability", ["field", "transform"], index=0 if cfg["perm_mode"] == "field" else 1, key=S.k("sx_pm"),
                                   format_func=lambda m: {"field": "Own random field (correlated)", "transform": "From porosity + scatter"}[m])
        cfg["kykx"] = float(d.number_input("PERMY / PERMX", 0.01, 100.0, float(cfg["kykx"]), key=S.k("sx_kykx")))
        if cfg["perm_mode"] == "transform":
            a, b, c = st.columns(3)
            t = cfg["transform"]
            t["a"] = float(a.number_input("a  (log10 k = a*PORO + b + scatter)", value=float(t["a"]), key=S.k("sx_ta")))
            t["b"] = float(b.number_input("b", value=float(t["b"]), key=S.k("sx_tb")))
            t["sigma"] = float(c.number_input("Scatter sigma (log10 units)", 0.0, 3.0, float(t["sigma"]), 0.05, key=S.k("sx_ts")))
        cfg["use_kvkh"] = st.checkbox("PERMZ = PERMX x KV/KH of the zone table", bool(cfg["use_kvkh"]), key=S.k("sx_kv"))

    for pr in gs.PROPS:
        pc = cfg["props"][pr]
        with st.expander(f"2  {PROP_LABEL[pr]}: histogram and variogram", expanded=(pr == "PORO")):
            a, b = st.columns([1, 2])
            pc["enabled"] = a.checkbox("Simulate", bool(pc["enabled"]), key=S.k("sx_en_" + pr))
            pc["dist"] = b.selectbox("Distribution", gs.DISTS, index=gs.DISTS.index(pc["dist"]), key=S.k("sx_dist_" + pr),
                                     help="Columns p1 / p2 / p3 mean: " + "; ".join(f"{k}: {', '.join(x for x in v if x) or 'n/a'}" for k, v in gs.DIST_PARAMS.items()))
            lab = gs.DIST_PARAMS[pc["dist"]]
            st.caption("p1 / p2 / p3 = " + (", ".join(f"{n}" for n in lab if n) or "see below") + "   |   vtype: spherical, exponential or gaussian   |   "
                       f"ranges in {un.xy()} (major, minor) and {un.z()} (vert); azimuth deg from north; nugget 0-1")
            if pc["dist"] == "histogram":
                if "bins0_" + pr not in st.session_state:
                    lo, hi = pc["rows"][0]["vmin"], min(pc["rows"][0]["vmax"], pc["rows"][0]["p1"] * 2 + 1e-9)
                    edges = np.linspace(lo, hi, 7)
                    st.session_state["bins0_" + pr] = pd.DataFrame([[edges[i], edges[i + 1], w] for i, w in enumerate([1, 3, 5, 5, 3, 1])],
                                                                    columns=["lower", "upper", "weight"])
                eb = st.data_editor(st.session_state["bins0_" + pr], num_rows="dynamic", key=S.k("sx_bins_" + pr))
                pc["bins"] = [[float(r.lower), float(r.upper), float(r.weight)] for r in eb.itertuples(index=False)
                              if pd.notna(r.lower) and pd.notna(r.upper) and pd.notna(r.weight)]
            elif pc["dist"] == "values":
                txt = st.text_area("Values (e.g. core-plug data; comma, space or line separated)", value=", ".join(f"{v:g}" for v in pc["values"]),
                                   key=S.k("sx_vals_" + pr))
                try:
                    pc["values"] = gs.parse_values(txt)
                except gs.GeostatError as e:
                    st.error(str(e))
            sig = "|".join(r["zone"] for r in pc["rows"]) + pc["dist"]
            kdf = f"rows0_{pr}_{sig}"
            if kdf not in st.session_state:
                st.session_state[kdf] = pd.DataFrame(pc["rows"])[ROW_COLS]
            ed = st.data_editor(st.session_state[kdf], key=S.k("sx_rows_" + pr + sig))
            try:
                pc["rows"] = [_plain_row(r) for r in ed.to_dict("records")]
            except Exception as e:
                st.error(f"Table error: {e}")
            try:
                zi = st.selectbox("Preview zone", [r["zone"] for r in pc["rows"]], key=S.k("sx_pz_" + pr, [r["zone"] for r in pc["rows"]]))
                row = next(r for r in pc["rows"] if r["zone"] == zi)
                uu = (np.arange(4000) + 0.5) / 4000
                q = np.clip(gs.quantile(pc["dist"], uu, row, dict(bins=pc["bins"], values=pc["values"])), row["vmin"], row["vmax"])
                plotly_view(specs.value_histogram({"target": q}, f"Target histogram - {zi}", pr), key=S.k("sx_prev_" + pr) + f"{zi}{pc['dist']}{q.mean():.4g}", height=240)
            except gs.GeostatError as e:
                st.warning(str(e))

    with st.expander("3  Correlation and cut-offs", expanded=True):
        a, b, c = st.columns(3)
        cc = cfg["corr"]
        cc["PORO_PERM"] = float(a.slider("PORO - PERM", -0.95, 0.95, float(cc["PORO_PERM"]), 0.05, key=S.k("sx_c1"),
                                         disabled=cfg["perm_mode"] == "transform"))
        cc["PORO_NTG"] = float(b.slider("PORO - NTG", -0.95, 0.95, float(cc["PORO_NTG"]), 0.05, key=S.k("sx_c2")))
        cc["PERM_NTG"] = float(c.slider("PERM - NTG", -0.95, 0.95, float(cc["PERM_NTG"]), 0.05, key=S.k("sx_c3"),
                                        disabled=cfg["perm_mode"] == "transform"))
        st.caption("Correlation of the underlying Gaussian fields (normal scores); the achieved Pearson / Spearman values are reported after the run. "
                   "Truncation at min / max lowers the achieved value slightly.")
        a, b, c = st.columns(3)
        cu = cfg["cut"]
        cu["phi"] = float(a.number_input("Porosity cut-off (net if >=, 0 = off)", 0.0, 1.0, float(cu["phi"]), 0.01, key=S.k("sx_cphi")))
        cu["k"] = float(b.number_input("Permeability cut-off mD (net if >=, 0 = off)", 0.0, value=float(cu["k"]), step=1.0, key=S.k("sx_ck")))
        cu["ntg"] = float(c.number_input("NTG cut-off (net if >=, 0 = off)", 0.0, 1.0, float(cu["ntg"]), 0.05, key=S.k("sx_cntg")))
        a, b = st.columns(2)
        cu["apply"] = a.checkbox("Apply the cut-offs to NTG (NTG = 0 where not net)", bool(cu["apply"]), key=S.k("sx_capp"))
        cu["binary"] = b.checkbox("Binary NTG (1 where net, 0 elsewhere)", bool(cu["binary"]), key=S.k("sx_cbin"))
        st.caption("The NET flag (1 = net) is always stored as a discrete property when at least one cut-off is active.")
    with st.expander("4  Condition to wells (blocked logs)", expanded=False):
        blk = [n for n, v in p.properties.items() if v.source == "blocked wells" and v.values.shape == (g.nk, g.nj, g.ni)]
        cond = cfg.setdefault("cond", {})
        if not blk:
            st.caption("No blocked-well properties yet. Load LAS logs and block them in the 'Well logs & kriging' tab, then condition PORO / PERM / NTG here.")
        else:
            st.caption("The Gaussian field is conditioned by kriging to the blocked data (honoured exactly in their cells, "
                       "correlated neighbourhood within the variogram range). Cross-correlation between properties is not carried into the conditioning.")
            cols = st.columns(3)
            for c_, pr_ in zip(cols, gs.PROPS):
                opts = ["(none)"] + blk
                cur = cond.get(pr_) if cond.get(pr_) in blk else "(none)"
                sel = c_.selectbox(PROP_LABEL[pr_], opts, index=opts.index(cur), key=S.k("sx_cond_" + pr_, opts))
                if sel == "(none)":
                    cond.pop(pr_, None)
                else:
                    cond[pr_] = sel
            if cfg["perm_mode"] == "transform" and "PERM" in cond:
                st.warning("Permeability derived from porosity is not conditioned directly - condition PORO instead.")
    errs = gs.check_config(cfg)
    for e in errs:
        st.error(e)
    est_mb = g.ncells * 8 * 6 / 1e6 * cfg["nreal"]
    if st.button("Run stochastic workflow", type="primary", disabled=bool(errs), key=S.k("sx_run")):
        try:
            bar = st.progress(0.0)
            cnd = {k: p.properties[v].values for k, v in cfg.get("cond", {}).items() if v in p.properties and p.properties[v].values.shape == (g.nk, g.nj, g.ni)}
            res = gs.simulate(g, cfg, progress=lambda f: bar.progress(min(float(f), 1.0)), cond=cnd or None)
            for n, r in res.items():
                p.properties[n] = pp.make_property(g, n, r["values"], r["kind"], r["unit"], "stochastic", "stochastic workflow")
            st.session_state["sx_last"] = list(res)
            st.rerun()
        except gs.GeostatError as e:
            st.error(str(e))
    st.caption(f"About {est_mb:.0f} MB of arrays are created during the run.")
    last = [n for n in st.session_state.get("sx_last", []) if n in p.properties]
    if last:
        st.success("Stored: " + ", ".join(last))
        _stoch_qc(p, g, cfg, last)


def _stoch_qc(p, g, cfg, last):
    base = [n for n in last if not n.endswith(tuple(f"_R{i}" for i in range(2, 11))) and n != "NET"]
    real = st.selectbox("Realisation to check", sorted({n.split("_R")[1] if "_R" in n else "1" for n in last}), key=S.k("sx_qr", last))
    sfx = "" if "1" == real and not any("_R" in n for n in last) else f"_R{real}"
    zn = [z.name for z in g.zones]
    zi = zn.index(st.selectbox("Zone", zn, index=min(2, len(zn) - 1), key=S.k("sx_qz", zn)))
    vals = {n.replace(sfx, ""): p.properties[n].values for n in last if n.endswith(sfx) or sfx == ""}
    act = g.actnum > 0
    ks = np.where(g.layer_zone == zi)[0]
    m = act[ks]
    if not m.any():
        st.info("This zone has no active cells.")
        return
    t1, t2, t3, t4 = st.columns(4)
    with t1:
        grp = {n: vals[n][ks][m] for n in ("PORO", "PERMX", "NTG") if n in vals}
        if grp:
            plotly_view(specs.value_histogram({k: v for k, v in grp.items() if k == next(iter(grp))}, f"Simulated {next(iter(grp))}", next(iter(grp))),
                        key=S.k("sx_h1") + f"{zi}{sfx}{len(last)}", height=300)
    if "PORO" in vals and "PERMX" in vals:
        idx = np.random.default_rng(1).choice(int(m.sum()), min(int(m.sum()), 3000), replace=False)
        x, y = vals["PORO"][ks][m][idx], vals["PERMX"][ks][m][idx]
        with t2:
            plotly_view(dict(data=[dict(type="scatter", mode="markers", x=x, y=y, marker=dict(size=4, color="#1B998B", opacity=0.5))],
                             layout=specs.base_layout("PORO vs PERMX", xaxis=dict(title="PORO"), yaxis=dict(title="PERMX (mD)", type="log"))),
                        key=S.k("sx_xp") + f"{zi}{sfx}{len(last)}", height=300)
    if "PORO" in vals:
        row = next(r for r in cfg["props"]["PORO"]["rows"] if r["zone"] == zn[zi])
        dz = float(g.thickness()[ks][m].mean())
        sp = (float(np.diff(g.xs).mean()), float(np.diff(g.ys).mean()), dz)
        traces = []
        for ax, nm, colr in ((2, "I", "#051C2C"), (1, "J", "#2251FF"), (0, "K", "#D7263D")):
            lg, gm = gs.exp_variogram(vals["PORO"][ks], m, ax, 15)
            hh = lg * sp[{2: 0, 1: 1, 0: 2}[ax]]
            mod = gs.model_variogram(lg, ax, sp, row, g.angle)
            traces.append(dict(type="scatter", mode="markers", x=hh, y=gm, name=f"exp {nm}", marker=dict(color=colr, size=6)))
            traces.append(dict(type="scatter", mode="lines", x=hh, y=mod, name=f"model {nm}", line=dict(color=colr, dash="dot")))
        with t3:
            plotly_view(dict(data=traces, layout=specs.base_layout("PORO variogram (normalised)", xaxis=dict(title="Lag"), yaxis=dict(title="gamma"))),
                        key=S.k("sx_vg") + f"{zi}{sfx}{len(last)}", height=300)
    with t4:
        ac = gs.achieved_correlation(g, {k: v for k, v in vals.items() if k in ("PORO", "PERMX", "NTG")}, zi)
        if ac:
            st.markdown("**Achieved correlation**")
            st.dataframe(pd.DataFrame([dict(pair=k, pearson=round(v["pearson"], 3), spearman=round(v["spearman"], 3)) for k, v in ac.items()]), hide_index=True)
        if "NET" in vals:
            st.metric("Net fraction (active cells)", f"{float(vals['NET'][ks][m].mean()):.1%}")


def _planes_regions(p, g):
    zu = un.z()
    st.markdown("**Horizontal planes to properties**")
    st.caption("A horizontal plane (a contact or any depth) becomes a height-above-plane property, a fraction-of-cell-above-plane property and a region "
               "property that numbers the slabs between the planes.")
    df0 = st.session_state.setdefault(S.k("pl_df0"), pd.DataFrame([dict(Name="PLANE1", Depth=float(np.round(np.percentile(g.center_depth()[g.actnum > 0], 50), 1)))]))
    ed = st.data_editor(df0, num_rows="dynamic", hide_index=True, key=S.k("pl_ed"))
    planes = [(str(r.Name), float(r.Depth)) for r in ed.itertuples() if str(r.Name).strip() and np.isfinite(r.Depth)]
    c1, c2 = st.columns(2)
    if c1.button("Create plane properties", type="primary", key=S.k("pl_make"), disabled=not planes):
        try:
            new = rg.plane_properties(g, planes, zu)
            p.properties.update(new)
            st.success("Stored: " + ", ".join(new))
        except rg.RegionError as e:
            st.error(str(e))
    ok_c = bool(p.volumetrics) and not vol.check_config(g, p.volumetrics)
    if c2.button("Create contact properties (OWC / GOC depth, height above, FLUID)", key=S.k("pl_cont"), disabled=not ok_c):
        try:
            new = rg.contact_properties(g, p.volumetrics, zu, p.properties)
            p.properties.update(new)
            st.success("Stored: " + ", ".join(new))
        except rg.RegionError as e:
            st.error(str(e))
    if not ok_c:
        st.caption("Contact properties need the contacts: set them on the Volumetrics page first.")
    st.divider()
    st.markdown("**Fault-block region and segments**")
    st.caption("FAULT_BLOCK and REGION number the fault blocks cut by the fault traces. SEGMENT numbers the combinations that contain active cells "
               "(zone x block, optionally x fluid) - the usual basis for FIPNUM / EQLNUM regions and volumetrics by segment.")
    mode = st.selectbox("Segment definition", rg.SEGMENT_MODES, index=1, key=S.k("rg_mode"))
    fluid = None
    if mode.endswith("fluid"):
        if "FLUID" in p.properties:
            fluid = p.properties["FLUID"].values
        elif p.volumetrics and not vol.check_config(g, p.volumetrics):
            fluid = vol.fluid_array(g, p.volumetrics, None, p.properties)
    if st.button("Create FAULT_BLOCK, REGION and SEGMENT", type="primary", key=S.k("rg_make")):
        try:
            new = rg.region_segment(g, mode, fluid)
            p.properties.update(new)
            st.success(f"Stored FAULT_BLOCK, REGION ({int(g.block.max())} blocks) and SEGMENT ({len(new['SEGMENT'].legend)} segments).")
        except rg.RegionError as e:
            st.error(str(e))
    for nm in ("REGION", "SEGMENT", "FLUID", "PLANE_REGION"):
        if nm in p.properties and p.properties[nm].values.shape == (g.nk, g.nj, g.ni):
            with st.expander(f"{nm} legend", expanded=nm == "SEGMENT"):
                tb = pd.DataFrame(rg.region_table(g, p.properties[nm]))
                if len(tb):
                    tb["volume"] = tb["volume"] / 1e6
                    st.dataframe(tb.rename(columns={"value": "Value", "name": "Name", "cells": "Active cells", "volume": "Bulk vol. (10^6 m3 in project units)"}).round(2), hide_index=True)


# ---------------------------------------------------------------------------------------------
def _well_logs(p, g):
    st.caption("Load LAS logs per well, block them into the grid cells, fit variograms to the blocked data and krige. "
               "Blocked properties condition the stochastic workflow (tab 'Stochastic modelling', step 4).")
    with st.expander("1  Logs", expanded=not p.logs):
        ups = st.file_uploader("LAS 2.0 files (one per well; WRAP = NO; depths in the project depth unit, measured from KB)", accept_multiple_files=True, key=S.k("las_up"))
        done = st.session_state.setdefault("done_las", set())
        for up in ups or []:
            if (up.name, up.size) in done:
                continue
            done.add((up.name, up.size))
            try:
                name, log = lg.parse_las(up.getvalue())
            except lg.LogError as e:
                st.error(f"{up.name}: {e}")
                continue
            if name not in p.wells:
                stem = up.name.rsplit(".", 1)[0]
                name = stem if stem in p.wells else name
            if name not in p.wells:
                st.warning(f"{up.name}: well '{name}' is not in the project (wells page) - the logs were kept but cannot be blocked until it exists.")
            p.logs[name] = log
            st.success(f"{name}: {len(log['md'])} samples, curves {', '.join(log['curves'])}")
        if p.logs:
            rows = []
            for n, l in p.logs.items():
                rows.append({"Well": n, "MD from": float(np.min(l["md"])), "MD to": float(np.max(l["md"])), "Samples": len(l["md"]),
                             "Curves": ", ".join(l["curves"]), "In project": "yes" if n in p.wells else "NO"})
            st.dataframe(pd.DataFrame(rows).round(1), hide_index=True)
            a, b = st.columns(2)
            dn = a.selectbox("Remove logs of", ["(none)"] + list(p.logs), key=S.k("las_del", ["(none)"] + list(p.logs)))
            if b.button("Remove", disabled=dn == "(none)", key=S.k("las_delb")):
                p.logs.pop(dn, None)
                st.rerun()
    curves = sorted({c for l in p.logs.values() for c in l["curves"]})
    if not curves:
        note("No logs loaded yet.")
        return
    with st.expander("2  Block logs into the grid", expanded=True):
        a, b, c = st.columns(3)
        cv = a.selectbox("Curve", curves, key=S.k("blk_curve", curves))
        disc = b.checkbox("Discrete (facies / flag): most frequent value", False, key=S.k("blk_disc"))
        avg = c.selectbox("Average", ["arithmetic", "harmonic", "geometric"], disabled=disc, key=S.k("blk_avg"),
                          help="Arithmetic for porosity / NTG, geometric or harmonic for permeability")
        name = st.text_input("Output property", cv + "_BLK", key=S.k("blk_name", [cv]))
        if st.button("Block wells", type="primary", key=S.k("blk_run")):
            arr, info = lg.block_wells(g, p.wells, p.logs, cv, disc, avg)
            if info["cells"] == 0:
                st.error("No log sample falls in an active cell - check that the wells lie inside the grid and the MD range overlaps the reservoir.")
            else:
                pr = pp.make_property(g, name, arr, "discrete" if disc else "continuous", p.logs[info["wells"][0]]["units"].get(cv, ""), "blocked wells",
                                      f"{cv} blocked ({avg})")
                p.properties[name] = pr
                st.session_state["blk_last"] = dict(name=name, **info)
                st.rerun()
        last = st.session_state.get("blk_last")
        if last and last["name"] in p.properties:
            q = lg.blocking_qc(g, p.properties[last["name"]].values)
            st.success(f"{last['name']}: {last['samples']:,} samples from {', '.join(last['wells'])} -> {q['cells']} cells. Per zone: "
                       + ", ".join(f"{k} {v}" for k, v in q["per_zone"].items()))
    blk = [n for n, v in p.properties.items() if v.source == "blocked wells" and v.kind == "continuous" and v.values.shape == (g.nk, g.nj, g.ni)]
    if not blk:
        return
    with st.expander("3  Variogram from blocked data", expanded=False):
        a, b, c = st.columns(3)
        bn = a.selectbox("Blocked property", blk, key=S.k("vg_prop", blk))
        zopts = ["(all zones)"] + [z.name for z in g.zones]
        zn = b.selectbox("Zone", zopts, key=S.k("vg_zone", zopts))
        vt = c.selectbox("Model", gs.VARIOGRAMS, key=S.k("vg_type"))
        zi = None if zn == "(all zones)" else [z.name for z in g.zones].index(zn)
        arr = p.properties[bn].values
        evs = dict(horizontal=lg.experimental_variogram(g, arr, zi, "horizontal"), vertical=lg.experimental_variogram(g, arr, zi, "vertical"))
        fits = dict(horizontal=lg.fit_range(evs["horizontal"], vt), vertical=lg.fit_range(evs["vertical"], vt))
        if not any(evs.values()):
            st.warning("Too few blocked cells for an experimental variogram (need several wells / layers in the selected zone).")
        else:
            plotly_view(specs.variogram_plot(evs, fits, vt, f"{bn} - {zn}"), key=S.k("vg_plot") + f"{bn}{zn}{vt}", height=300)
            st.caption("Horizontal pairs are taken within the same layer, vertical pairs within the same well column. With few wells the horizontal "
                       "variogram is poorly constrained: treat the fitted range as a guide, not a result.")
            if st.button("Apply fitted ranges to this property's stochastic setup" if zi is not None else "Apply fitted ranges to every zone's stochastic setup",
                         disabled=not (fits["horizontal"] or fits["vertical"]), key=S.k("vg_apply")):
                cfg = _cfg(p, g)
                pk = next((k for k in ("PORO", "PERM", "NTG") if k in bn.upper()), "PORO")
                n_ = 0
                for r in cfg["props"][pk]["rows"]:
                    if zn != "(all zones)" and r["zone"] != zn:
                        continue
                    if fits["horizontal"]:
                        r["major"] = r["minor"] = float(fits["horizontal"]["range"])
                    if fits["vertical"]:
                        r["vert"] = float(fits["vertical"]["range"])
                    r["vtype"] = vt
                    n_ += 1
                st.session_state.pop("rows0_" + pk, None)
                for k_ in [k_ for k_ in st.session_state if str(k_).startswith(f"rows0_{pk}_")]:
                    st.session_state.pop(k_)
                st.success(f"Updated {n_} zone row(s) of {pk}.")
    with st.expander("4  Kriging", expanded=False):
        a, b = st.columns(2)
        kn = a.selectbox("Blocked property to krige", blk, key=S.k("kr_prop", blk))
        out = b.text_input("Output property", kn.replace("_BLK", "") + "_KRG", key=S.k("kr_out", [kn]))
        c, d, e, f = st.columns(4)
        vtk = c.selectbox("Model", gs.VARIOGRAMS, key=S.k("kr_vt"))
        maj = float(c.number_input(f"Major range ({un.xy()})", 1.0, value=1500.0, key=S.k("kr_maj")))
        mnr = float(d.number_input(f"Minor range ({un.xy()})", 1.0, value=1500.0, key=S.k("kr_min")))
        vrt = float(d.number_input(f"Vertical range ({un.z()})", 0.1, value=30.0, key=S.k("kr_vrt")))
        az = float(e.number_input("Azimuth (deg from north)", 0.0, 360.0, 0.0, key=S.k("kr_az")))
        nug = float(e.number_input("Nugget (0-1)", 0.0, 0.95, 0.0, 0.05, key=S.k("kr_nug")))
        nmax = int(f.number_input("Max neighbours", 2, 40, 12, key=S.k("kr_nmax")))
        nsc = f.checkbox("Normal-score transform", True, key=S.k("kr_ns"))
        if st.button("Krige", type="primary", key=S.k("kr_run")):
            bar = st.progress(0.0)
            vp = dict(vtype=vtk, major=maj, minor=mnr, vert=vrt, nugget=nug)
            est = gs.krige_property(g, p.properties[kn].values, vp, gs.rel_angle(az, g.angle), True, nmax, nsc, progress=lambda x: bar.progress(min(float(x), 1.0)))
            p.properties[out] = pp.make_property(g, out, est, "continuous", p.properties[kn].unit, "kriging", f"simple kriging of {kn}")
            st.success(f"Stored {out}. Simple kriging in the {'normal-score' if nsc else 'raw'} domain, per zone; cells farther than the range from any datum take the data mean "
                       "(kriging is smooth by nature - use the stochastic workflow for realistic variability).")


# ---------------------------------------------------------------------------------------------
def _facies_cfg(p, g, nf):
    cfg = p.facies
    zn = [z.name for z in g.zones]
    if not cfg or [z["zone"] for z in cfg["zones"]] != zn or len(cfg["facies"]) != nf:
        cfg = fa.default_config(g, nf)
        p.facies = cfg
    return cfg


def _facies(p, g):
    st.caption("Model facies as in Petrel / RMS: truncated Gaussian (ordered facies), plurigaussian (two fields + truncation rule), sequential indicator "
               "simulation or object modelling (ellipsoidal bodies in a background), then create PORO / PERM / NTG per facies.")
    nf0 = len(p.facies["facies"]) if p.facies else 3
    with st.expander("1  Facies and method", expanded=True):
        a, b, c, d = st.columns(4)
        nf = int(a.number_input("Number of facies", 2, 8, nf0, key=S.k("fa_nf")))
        cfg = _facies_cfg(p, g, nf)
        cfg = fa.normalise(cfg, g)
        cfg["method"] = b.radio("Method", fa.METHODS, index=fa.METHODS.index(cfg["method"]), key=S.k("fa_meth"),
                                format_func=lambda m: {"truncated_gaussian": "Truncated Gaussian", "plurigaussian": "Plurigaussian", "indicator": "Indicator (SIS)",
                                                       "objects": "Objects"}[m])
        cfg["seed"] = int(c.number_input("Random seed", 0, 10_000_000, int(cfg["seed"]), key=S.k("fa_seed")))
        cfg["trend"] = d.checkbox("Vertical proportion trend (top -> base of zone)", bool(cfg["trend"]), key=S.k("fa_trend"),
                                  disabled=cfg["method"] in ("objects", "plurigaussian"))
        if cfg["method"] in ("truncated_gaussian", "plurigaussian"):
            cfg["vol_weight"] = st.checkbox("Volume-weighted proportions (match the proportions by cell bulk volume instead of cell count)",
                                            bool(cfg["vol_weight"]), key=S.k("fa_vw"))
        if cfg["method"] == "indicator":
            cfg["nmax"] = int(st.number_input("Neighbours per cell (data + simulated, within one range)", 4, 40, int(cfg["nmax"]), key=S.k("fa_nmax")))
        key = f"fa_tab|{nf}"
        if key not in st.session_state:
            st.session_state[key] = pd.DataFrame(cfg["facies"])[["code", "name", "color", "net"]]
        ed = st.data_editor(st.session_state[key], key=S.k("fa_facies" + key), hide_index=True)
        try:
            cfg["facies"] = [dict(code=int(r["code"]), name=str(r["name"]), color=str(r["color"]), net=bool(r["net"])) for r in ed.to_dict("records")]
        except Exception as e:
            st.error(f"Facies table: {e}")
        st.caption("Order matters for the truncated Gaussian method: neighbouring rows are neighbours in space (e.g. shale -> heterolithic -> sand). "
                   "'net' sets NTG = 1 for that facies in the petrophysics step.")
    names = [f["name"] for f in cfg["facies"]]
    with st.expander("2  Proportions and continuity per zone", expanded=True):
        zkey = "fa_prop|" + "|".join(names) + "|" + "|".join(z["zone"] for z in cfg["zones"])
        if zkey not in st.session_state:
            st.session_state[zkey] = pd.DataFrame([dict(Zone=z["zone"], **{n: float(v) for n, v in zip(names, z["top"])}) for z in cfg["zones"]])
        edp = st.data_editor(st.session_state[zkey], key=S.k("fa_p" + zkey), hide_index=True, disabled=["Zone"])
        rows_t = edp.to_dict("records")
        for z, r in zip(cfg["zones"], rows_t):
            z["top"] = [float(r[n]) for n in names]
        if cfg["trend"] and cfg["method"] in ("truncated_gaussian", "indicator"):
            bkey = "fa_propb|" + zkey
            if bkey not in st.session_state:
                st.session_state[bkey] = pd.DataFrame([dict(Zone=z["zone"], **{n: float(v) for n, v in zip(names, z["base"])}) for z in cfg["zones"]])
            st.caption("Proportions at the base of each zone (the table above = top):")
            edb = st.data_editor(st.session_state[bkey], key=S.k("fa_pb" + bkey), hide_index=True, disabled=["Zone"])
            for z, r in zip(cfg["zones"], edb.to_dict("records")):
                z["base"] = [float(r[n]) for n in names]
        else:
            for z in cfg["zones"]:
                z["base"] = list(z["top"])
        st.caption("Proportions are normalised to 1 per zone. For objects, the object facies get their proportion as target volume fraction and the background fills the rest.")
        vkey = "fa_var|" + "|".join(z["zone"] for z in cfg["zones"])
        if vkey not in st.session_state:
            st.session_state[vkey] = pd.DataFrame(cfg["zones"])[["zone", "major", "minor", "vert", "azimuth", "vtype", "nugget"]]
        edv = st.data_editor(st.session_state[vkey], key=S.k("fa_v" + vkey), hide_index=True, disabled=["zone"])
        for z, r in zip(cfg["zones"], edv.to_dict("records")):
            z.update(major=float(r["major"]), minor=float(r["minor"]), vert=float(r["vert"]), azimuth=float(r["azimuth"]),
                     vtype=str(r["vtype"]) if str(r["vtype"]) in gs.VARIOGRAMS else "spherical", nugget=float(r["nugget"]))
        st.caption(f"Ranges in {un.xy()} (major, minor) and {un.z()} (vert); azimuth deg from north; vtype spherical / exponential / gaussian.")
        if cfg["method"] == "plurigaussian":
            v2 = "fa_var2|" + "|".join(z["zone"] for z in cfg["zones"])
            if v2 not in st.session_state:
                st.session_state[v2] = pd.DataFrame(cfg["zones"])[["zone", "major2", "minor2", "vert2", "azimuth2"]]
            st.caption("Second Gaussian field (G2); the table above describes the first (G1). The fields are independent.")
            ed2 = st.data_editor(st.session_state[v2], key=S.k("fa_v2" + v2), hide_index=True, disabled=["zone"])
            for z, r in zip(cfg["zones"], ed2.to_dict("records")):
                z.update(major2=float(r["major2"]), minor2=float(r["minor2"]), vert2=float(r["vert2"]), azimuth2=float(r["azimuth2"]))
    if cfg["method"] == "plurigaussian":
        with st.expander("3  Truncation rule", expanded=True):
            codes = [f["code"] for f in cfg["facies"]]
            a, b = st.columns(2)
            n1 = int(a.number_input("Bands of G1 (rows)", 1, 6, len(cfg["rule"]), key=S.k("fa_n1")))
            n2 = int(b.number_input("Bands of G2 (columns)", 1, 6, len(cfg["rule"][0]), key=S.k("fa_n2")))
            rk = f"fa_rule|{n1}|{n2}|" + "|".join(map(str, codes))
            if rk not in st.session_state:
                old_r = cfg["rule"]
                st.session_state[rk] = pd.DataFrame([[int(old_r[i][j]) if i < len(old_r) and j < len(old_r[0]) else codes[0] for j in range(n2)] for i in range(n1)],
                                                    columns=[f"G2 band {j + 1}" for j in range(n2)], index=[f"G1 band {i + 1}" for i in range(n1)])
            edr = st.data_editor(st.session_state[rk], key=S.k("fa_r" + rk))
            try:
                cfg["rule"] = [[int(x) for x in row] for row in edr.values.tolist()]
            except Exception as e:
                st.error(f"Rule table: {e}")
            st.caption("Each cell holds the facies code found when G1 falls in the row's band and G2 in the column's band (bands ordered by increasing value). "
                       "Band widths follow from the proportions; the default is nested (G1 low = first facies, G1 high = G2 splits the others). "
                       "Proportions at the top of each zone are used (no vertical trend); not conditioned to wells.")
    if cfg["method"] == "objects":
        with st.expander("3  Objects", expanded=True):
            cfg["background"] = int(st.selectbox("Background facies (code)", [f["code"] for f in cfg["facies"]],
                                                 index=0, key=S.k("fa_bg", [f["code"] for f in cfg["facies"]])))
            okey = "fa_obj|" + "|".join(names)
            if okey not in st.session_state:
                st.session_state[okey] = pd.DataFrame(cfg["objects"])[["code", "length", "width", "thickness", "azimuth"]]
            edo = st.data_editor(st.session_state[okey], key=S.k("fa_o" + okey), num_rows="dynamic", hide_index=True)
            try:
                cfg["objects"] = [dict(code=int(r.code), length=float(r.length), width=float(r.width), thickness=float(r.thickness), azimuth=float(r.azimuth))
                                  for r in edo.itertuples(index=False) if pd.notna(r.code) and pd.notna(r.length) and pd.notna(r.width) and pd.notna(r.thickness)]
            except Exception as e:
                st.error(f"Object table: {e}")
            cfg["azimuth_sd"] = float(st.number_input("Azimuth scatter (deg, standard deviation)", 0.0, 90.0, float(cfg["azimuth_sd"]), key=S.k("fa_asd")))
            st.caption("Dimensions vary +/- 20 % per body; bodies overwrite earlier ones; object models are not conditioned to wells.")
    blk = [n for n, v in p.properties.items() if v.kind == "discrete" and v.source == "blocked wells" and v.values.shape == (g.nk, g.nj, g.ni)]
    if cfg["method"] in ("truncated_gaussian", "indicator"):
        with st.expander("4  Well conditioning", expanded=bool(blk)):
            if not blk:
                st.caption("Block a discrete facies log first (Well logs & kriging tab, 'Discrete' option) to condition the model and to compare well proportions.")
                cfg["cond"] = ""
            else:
                opts = ["(none)"] + blk
                cur = cfg.get("cond") if cfg.get("cond") in blk else "(none)"
                sel = st.selectbox("Blocked facies log", opts, index=opts.index(cur), key=S.k("fa_cond", opts))
                cfg["cond"] = "" if sel == "(none)" else sel
                if cfg["cond"]:
                    wp = fa.well_proportions(g, p.properties[cfg["cond"]].values, cfg)
                    st.dataframe(pd.DataFrame([dict(Zone=k, **{n: v for n, v in zip(names, vs)}) for k, vs in wp.items()]).round(3), hide_index=True)
                    st.caption("Well proportions of the blocked data (NaN = no data in that zone). Wells are usually biased to the reservoir - use them as a guide.")
                    if st.button("Use well proportions where available", key=S.k("fa_usew")):
                        for z in cfg["zones"]:
                            v = wp[z["zone"]]
                            if not np.isnan(v).any() and sum(v) > 0:
                                z["top"], z["base"] = [float(x) for x in v], [float(x) for x in v]
                        for k_ in [k_ for k_ in st.session_state if str(k_).startswith("fa_prop")]:
                            st.session_state.pop(k_)
                        st.rerun()
    errs = fa.check_config(cfg, g)
    for e in errs:
        st.error(e)
    a, b = st.columns([1, 2])
    fname = b.text_input("Output property", "FACIES", key=S.k("fa_out"))
    if a.button("Run facies model", type="primary", disabled=bool(errs), key=S.k("fa_run")):
        try:
            bar = st.progress(0.0)
            cnd = p.properties[cfg["cond"]].values if cfg.get("cond") in p.properties else None
            arr = fa.simulate(g, cfg, cnd, progress=lambda f: bar.progress(min(float(f), 1.0)))
            p.properties[fname] = pp.make_property(g, fname, arr, "discrete", "", "facies", f"facies model ({cfg['method']})", fa.legend(cfg))
            st.session_state["fa_last"] = fname
            st.rerun()
        except fa.FaciesError as e:
            st.error(str(e))
    last = st.session_state.get("fa_last")
    if last in p.properties and p.properties[last].values.shape == (g.nk, g.nj, g.ni):
        arr = p.properties[last].values
        st.success(f"Stored {last}.")
        st.markdown("**Model proportions by zone** (volume weighted; target = proportions at the top of the zone)")
        st.dataframe(pd.DataFrame(fa.proportions(g, arr, cfg)).round(3), hide_index=True)
        vp_ = fa.vertical_proportions(g, arr, cfg)
        data = [dict(type="scatter", mode="lines", x=v, y=np.arange(1, g.nk + 1), name=n, line=dict(color=f["color"], width=2))
                for (n, v), f in zip(vp_.items(), cfg["facies"])]
        plotly_view(dict(data=data, layout=specs.base_layout("Vertical proportion curves", xaxis=dict(title="Fraction of active cells", range=[0, 1]),
                                                             yaxis=dict(title="Layer (k)", autorange="reversed", gridcolor=specs.LINE))),
                    key=S.k("fa_vpc") + f"{last}{arr.sum():.6g}", height=330)
        k_ = int(st.slider("Layer", 1, g.nk, min(g.nk, 3), key=S.k("fa_lay", [g.nk]))) - 1
        plotly_view(specs.layer_map(np.where(g.actnum[k_] > 0, arr[k_], np.nan), f"{last}, layer {k_ + 1}", "Facies code"), key=S.k("fa_map") + f"{last}{k_}{arr.sum():.6g}", height=320)
    with st.expander("5  Petrophysics per facies", expanded=False):
        for f_, r_ in zip(cfg["facies"], cfg["petro"]):
            r_["code"] = f_["code"]
        pkey = "fa_pet|" + "|".join(names) + "|" + "|".join(str(f_["code"]) for f_ in cfg["facies"])
        if pkey not in st.session_state:
            df = pd.DataFrame(cfg["petro"])
            df.insert(1, "facies", names)
            st.session_state[pkey] = df
        edq = st.data_editor(st.session_state[pkey], key=S.k("fa_pt" + pkey), hide_index=True, disabled=["code", "facies"])
        cfg["petro"] = [dict(code=int(r["code"]), poro=float(r["poro"]), poro_sd=float(r["poro_sd"]), logk=float(r["logk"]), logk_sd=float(r["logk_sd"]),
                             rho=float(r["rho"]), ntg=float(r["ntg"])) for r in edq.to_dict("records")]
        st.caption("poro / poro_sd = porosity mean and standard deviation; logk / logk_sd = log10 permeability (mD); rho = PORO-PERM correlation; ntg = net-to-gross of the facies. "
                   "Spatial continuity comes from the zone variograms above. PERMY = PERMX x KY/KX below, PERMZ = PERMX x KV/KH of the zone table.")
        cfg["kykx"] = float(st.number_input("PERMY / PERMX", 0.01, 100.0, float(cfg.get("kykx", 1.0)), key=S.k("fa_kykx")))
        srcs = [n for n, v in p.properties.items() if v.kind == "discrete" and v.values.shape == (g.nk, g.nj, g.ni)]
        if srcs:
            sel = st.selectbox("Facies property to use", srcs, index=srcs.index(last) if last in srcs else 0, key=S.k("fa_src", srcs))
            if st.button("Create PORO, PERMX/Y/Z, NTG from facies", key=S.k("fa_petro")):
                res = fa.petrophysics(g, p.properties[sel].values, cfg)
                for n, r in res.items():
                    p.properties[n] = pp.make_property(g, n, r["values"], r["kind"], r["unit"], "facies", f"from facies {sel}")
                st.success("Stored PORO, PERMX, PERMY, PERMZ, NTG (existing properties of the same names were replaced).")
        else:
            st.caption("Run the facies model first.")
