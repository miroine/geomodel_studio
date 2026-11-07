"""Surface filtering: polygon clip, value range, spikes, slopes, hole filling.

The raw map is never overwritten.  Each surface owns an ordered, editable stack of operations with
undo / redo, presets, a kept-vs-removed map and a histogram - the same idea as Petrel's / RMS's
"operations on surfaces", but non-destructive.
"""
import numpy as np
import streamlit as st
from core import units as un

from core import filters as flt
from ui import state as S
from ui import specs
from ui.components import plotly_view
from ui.theme import kpis, note


def _edit_form(p, name, idx, ver):
    """Edit form for op ``idx`` (or a new op appended to the end); returns the new op or None."""
    st_ = p.fstate(name)
    ops = st_["ops"]
    op = dict(ops[idx]) if idx < len(ops) else None
    kind = op["type"] if op else st.session_state["tmp_newkind"]
    new = dict(op) if op else flt.default_op(kind)
    key = lambda s: S.k(f"fe_{name}_{idx}_{ver}_{s}")
    sg = flt.suggest(p.raw[name], p.surfaces[name].geom) if p.raw[name].size else {}
    st.markdown(f"**{'Edit' if op else 'New'}: {flt.OP_LABEL[kind]}**")
    if kind == "polygon":
        names = list(p.polygons)
        if not names:
            note("No polygons yet - digitize or import one on the <b>Polygons</b> page first.", warn=True)
            return None
        cur = new.get("polygon") or (p.boundary if p.boundary in names else names[0])
        new["polygon"] = st.selectbox("Polygon", names, index=names.index(cur) if cur in names else 0, key=key("poly"))
        new["keep"] = st.radio("Keep", ["inside", "outside"], index=0 if new.get("keep", "inside") == "inside" else 1, horizontal=True, key=key("keep"),
                               help="'inside' removes everything outside the polygon (boundary clip); 'outside' cuts a hole")
        new["buffer"] = st.number_input(f"Buffer ({un.xy()}, + grows / - shrinks the polygon)", value=float(new.get("buffer", 0.0)), step=50.0, key=key("buf"))
    elif kind == "range":
        new["mode"] = st.radio("Thresholds are", ["absolute", "percentile"], index=0 if new.get("mode", "absolute") == "absolute" else 1,
                               horizontal=True, key=key("mode"))
        pct = new["mode"] == "percentile"
        c1, c2 = st.columns(2)
        use_lo = c1.checkbox("Minimum", value=new.get("min") is not None, key=key("ulo"))
        use_hi = c2.checkbox("Maximum", value=new.get("max") is not None, key=key("uhi"))
        d_lo = new.get("min") if new.get("min") is not None else (1.0 if pct else sg.get("p01", 0.0))
        d_hi = new.get("max") if new.get("max") is not None else (99.0 if pct else sg.get("p99", 0.0))
        lo = c1.number_input("Min (percentile)" if pct else f"Min depth ({un.z()})", value=float(d_lo), step=1.0 if pct else 10.0, key=key("lo"), disabled=not use_lo)
        hi = c2.number_input("Max (percentile)" if pct else f"Max depth ({un.z()})", value=float(d_hi), step=1.0 if pct else 10.0, key=key("hi"), disabled=not use_hi)
        new["min"] = float(lo) if use_lo else None
        new["max"] = float(hi) if use_hi else None
        if sg:
            st.caption(f"Data range {sg['zmin']:.1f} .. {sg['zmax']:.1f} {un.z()}; 1st / 99th percentile {sg['p01']:.1f} / {sg['p99']:.1f} {un.z()}.")
    elif kind == "spikes":
        c1, c2 = st.columns(2)
        new["window"] = int(c1.selectbox("Median window", [3, 5, 7], index=[3, 5, 7].index(int(new.get("window", 3))), key=key("win")))
        new["k"] = float(c2.slider("Threshold (robust sigma)", 2.0, 10.0, float(new.get("k", 4.0)), 0.5, key=key("k"),
                                   help="Lower = more aggressive. A node is a spike when it deviates from the local median by more than k robust sigma."))
        if sg:
            st.caption("Nodes flagged at k = 3 / 4 / 6 on the raw map: " + " / ".join(f"{sg[f'spikes_k{k}']:,}" for k in (3, 4, 6)))
    elif kind == "slope":
        new["max_slope"] = float(st.number_input("Maximum slope (dz/dx, unitless)", 0.01, 10.0, float(new.get("max_slope", 0.5)), 0.05, key=key("sl")))
        st.caption(f"= {np.degrees(np.arctan(new['max_slope'])):.1f} degrees")
    elif kind == "fill":
        new["max_cells"] = int(st.number_input("Fill holes up to this distance from valid data (cells)", 1, 50, int(new.get("max_cells", 3)), 1, key=key("mc")))
    elif kind == "extend":
        from core import extrap
        modes = [m for m in extrap.MODES]
        new["mode"] = st.selectbox("Extension method", modes, index=modes.index(new.get("mode", "gradient")), key=key("xm"))
        st.caption(extrap.MODE_INFO[new["mode"]])
        a, b, c, d = st.columns(4)
        new["max_dist"] = float(a.number_input(f"Only within ({un.xy()}, 0 = everywhere)", 0.0, value=float(new.get("max_dist", 0.0)), step=100.0, key=key("xd")))
        new["length"] = float(b.number_input(f"Decay length ({un.xy()}, 0 = auto)", 0.0, value=float(new.get("length", 0.0)), step=500.0, key=key("xl"),
                                              disabled=new["mode"] not in ("decay", "gradient")))
        new["value"] = float(c.number_input(f"Constant ({un.z()})", value=float(new.get("value", 0.0)), key=key("xv"), disabled=new["mode"] != "constant"))
        new["tension"] = float(d.slider("Tension", 0.0, 1.0, float(new.get("tension", 0.0)), 0.05, key=key("xt"), disabled=new["mode"] != "min_curvature"))
    c1, c2 = st.columns(2)
    if c1.button("Apply", type="primary", key=key("apply")):
        return new
    if c2.button("Cancel", key=key("cancel")):
        st.session_state.pop("tmp_fedit", None)
        st.rerun()
    return None


def render_tab(p):
    if not p.surfaces:
        note("No surfaces yet - import or generate one first.")
        return
    names = list(p.surfaces)
    name = S.pick("Surface", names, "flt_sel", "surface")
    stt = p.fstate(name)
    ops = stt["ops"]
    raw, cur = p.raw[name], p.surfaces[name].z
    geom = p.surfaces[name].geom

    # --- KPIs / history -----------------------------------------------------------------
    n_raw, n_cur = int(np.isfinite(raw).sum()), int(np.isfinite(cur).sum())
    kpis([("Raw nodes", f"{n_raw:,}"), ("After filters", f"{n_cur:,}"), ("Removed", f"{max(n_raw - n_cur, 0):,}"),
          ("Filters", f"{sum(1 for o in ops if o.get('enabled', True))}/{len(ops)} on")])
    b1, b2, b3, b4 = st.columns([1, 1, 1, 3])
    if b1.button(f"Undo ({len(stt['undo'])})", disabled=not stt["undo"], key=S.k(f"undo_{name}")):
        p.undo_filter(name)
        st.session_state.pop("tmp_fedit", None)
        st.rerun()
    if b2.button(f"Redo ({len(stt['redo'])})", disabled=not stt["redo"], key=S.k(f"redo_{name}")):
        p.redo_filter(name)
        st.rerun()
    if b3.button("Reset", disabled=not ops, key=S.k(f"reset_{name}"), help="Remove all filters (undoable)"):
        p.reset_filter(name)
        st.session_state.pop("tmp_fedit", None)
        st.rerun()

    left, right = st.columns([5, 6])
    editing = st.session_state.get("tmp_fedit")
    if editing and editing.get("surf") != name:
        editing = None
        st.session_state.pop("tmp_fedit", None)

    with left:
        st.markdown("##### Filter stack (top to bottom)")
        report = flt.apply_stack(raw, geom, ops, p.polygons)[1] if ops else []     # read-only: do not invalidate the model on every render
        if not ops:
            note("The stack is empty - the raw map is shown. Add a filter below.")
        for i, op in enumerate(ops):
            r = report[i] if i < len(report) else {}
            with st.container(border=True):
                c0, c1, c2, c3, c4 = st.columns([0.9, 5, 0.9, 0.9, 0.9])
                en = c0.checkbox("on", value=op.get("enabled", True), key=S.k(f"en_{name}_{i}_{len(stt['undo'])}"), label_visibility="collapsed")
                c1.markdown(f"**{i + 1}.** {flt.describe(op)}")
                if r.get("error"):
                    c1.error(r["error"])
                elif r.get("enabled", True):
                    c1.caption(f"removed {r.get('removed', 0):,} nodes" + (f", added {r['added']:,}" if r.get("added") else "") + f" - {r.get('defined', 0) * 100:.0f} % defined")
                if en != op.get("enabled", True):
                    new_ops = [dict(o) for o in ops]
                    new_ops[i]["enabled"] = en
                    p.commit_filter(name, new_ops)
                    st.rerun()
                if c2.button("Edit", key=S.k(f"edit_{name}_{i}")):
                    st.session_state["tmp_fedit"] = dict(surf=name, idx=i, ver=st.session_state.get("tmp_fver", 0) + 1)
                    st.session_state["tmp_fver"] = st.session_state["tmp_fedit"]["ver"]
                    st.rerun()
                mv = None
                if c3.button("Up", disabled=i == 0, key=S.k(f"up_{name}_{i}")):
                    mv = (i, i - 1)
                if c4.button("Del", key=S.k(f"del_{name}_{i}")):
                    mv = (i, None)
                if mv:
                    new_ops = [dict(o) for o in ops]
                    if mv[1] is None:
                        new_ops.pop(mv[0])
                    else:
                        new_ops[mv[0]], new_ops[mv[1]] = new_ops[mv[1]], new_ops[mv[0]]
                    p.commit_filter(name, new_ops)
                    st.session_state.pop("tmp_fedit", None)
                    st.rerun()

        # --- add / edit --------------------------------------------------------------------
        if editing:
            with st.container(border=True):
                res = _edit_form(p, name, editing["idx"], editing["ver"])
            if res is not None:
                new_ops = [dict(o) for o in ops]
                if editing["idx"] < len(new_ops):
                    new_ops[editing["idx"]] = res
                else:
                    new_ops.append(res)
                p.commit_filter(name, new_ops)
                st.session_state.pop("tmp_fedit", None)
                st.rerun()
        else:
            a1, a2 = st.columns([3, 1])
            kind = a1.selectbox("Add a filter", flt.OP_TYPES, format_func=lambda k: flt.OP_LABEL[k], key=S.k("flt_newkind"))
            a2.markdown("&nbsp;", unsafe_allow_html=True)
            if a2.button("Add", type="primary", key=S.k("flt_add")):
                st.session_state["tmp_newkind"] = kind
                ver = st.session_state.get("tmp_fver", 0) + 1
                st.session_state["tmp_fver"] = ver
                st.session_state["tmp_fedit"] = dict(surf=name, idx=len(ops), ver=ver)
                st.rerun()

        # --- smart suggestions ---------------------------------------------------------------
        with st.expander("Smart suggestions", expanded=False):
            sg = flt.suggest(raw, geom)
            if sg:
                st.caption("Computed on the raw map. One click adds the filter to the stack (undoable).")
                s1, s2 = st.columns(2)
                if s1.button(f"Trim to P1-P99 ({sg['p01']:.0f}-{sg['p99']:.0f} {un.z()})", key=S.k(f"sg_rng_{name}")):
                    p.commit_filter(name, [dict(o) for o in ops] + [flt.default_op("range", mode="absolute", min=round(sg["p01"], 1), max=round(sg["p99"], 1))])
                    st.rerun()
                if s2.button(f"Remove spikes + fill ({sg['spikes_k4']:,} nodes at k=4)", key=S.k(f"sg_spk_{name}")):
                    p.commit_filter(name, [dict(o) for o in ops] + [flt.default_op("spikes", window=3, k=4.0), flt.default_op("fill", max_cells=2)])
                    st.rerun()
                if p.boundary and s1.button(f"Clip to boundary '{p.boundary}'", key=S.k(f"sg_bnd_{name}")):
                    p.commit_filter(name, [dict(o) for o in ops] + [flt.default_op("polygon", polygon=p.boundary)])
                    st.rerun()

        # --- presets / copy ------------------------------------------------------------------
        with st.expander("Presets and apply to other surfaces", expanded=False):
            c1, c2 = st.columns([3, 1])
            pn = c1.text_input("Save current stack as preset", value="", key=S.k("flt_pname"), placeholder="e.g. Clean seismic spikes")
            c2.markdown("&nbsp;", unsafe_allow_html=True)
            if c2.button("Save", disabled=not (pn and ops), key=S.k("flt_psave")):
                p.filter_presets[pn] = [dict(o) for o in ops]
                st.rerun()
            if p.filter_presets:
                d1, d2, d3 = st.columns([3, 1, 1])
                pk = d1.selectbox("Preset", list(p.filter_presets), key=S.k("flt_pick", list(p.filter_presets)))
                mode = d1.radio("Apply as", ["Replace stack", "Append to stack"], horizontal=True, key=S.k("flt_pmode"))
                targets = d1.multiselect("Apply to", names, default=[name], key=S.k("flt_ptargets", names) + f"_{name}")
                d2.markdown("&nbsp;", unsafe_allow_html=True)
                if d2.button("Apply", key=S.k("flt_papply")):
                    for t in targets:
                        base = [dict(o) for o in p.fstate(t)["ops"]] if mode.startswith("Append") else []
                        p.commit_filter(t, base + [dict(o) for o in p.filter_presets[pk]])
                    st.rerun()
                d3.markdown("&nbsp;", unsafe_allow_html=True)
                if d3.button("Delete", key=S.k("flt_pdel")):
                    p.filter_presets.pop(pk, None)
                    st.rerun()
            else:
                st.caption("No presets saved yet.")

    with right:
        view = st.radio("Preview", ["Kept / removed", "Filtered map", "Histogram"], horizontal=True, key=S.k("flt_view"))
        if view == "Kept / removed":
            plotly_view(specs.mask_map(raw, cur, geom, p.polygons, p.boundary), key=S.k("flt_mask"), height=520)
        elif view == "Filtered map":
            if np.isfinite(cur).any():
                plotly_view(specs.map_2d(cur, geom, title=name, faults=[]), key=S.k("flt_map"), height=520)
            else:
                st.warning("Every node has been removed - check the filter stack.")
        else:
            lines = [x for o in ops if o["type"] == "range" and o.get("enabled", True) and o.get("mode", "absolute") == "absolute" for x in (o.get("min"), o.get("max")) if x is not None]
            plotly_view(specs.histogram(raw, cur, lines), key=S.k("flt_hist"), height=420)
    st.caption("Filters change what the rest of the workflow sees (structural model, gridding, 3D); the raw map is kept and every change is undoable. "
               "Note: the structural workflow fills undefined nodes by nearest neighbour, so use the model boundary (Polygons page) to cut the final grid.")
