"""Zones & layering."""
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core.cpgrid import STYLES, STYLE_HELP, ZoneSpec, default_zones, validate_zones
from ui import state as S
from ui.theme import banner, kpis, note

COLS = ["Zone", "Top", "Base", "Style", "Layers", "dz", "Fractions", "PORO", "PERMX (mD)", "KV/KH", "NTG"]


def _to_df(p):
    return pd.DataFrame([[z.name, z.top, z.base, z.style, z.nlayers, z.dz, ", ".join(f"{f:g}" for f in z.fractions),
                          z.poro, z.permx, z.kvkh, z.ntg] for z in p.zones], columns=COLS)


def _parse(df):
    zs = []
    for r in df.itertuples(index=False):
        if not r[1] or not r[2]:
            continue
        fr = [float(x) for x in str(r[6]).replace(";", ",").split(",") if x.strip()] if r[6] else []
        zs.append(ZoneSpec(name=str(r[0]), top=str(r[1]), base=str(r[2]), nlayers=int(r[4] or 1), style=str(r[3]),
                           dz=float(r[5] or 5.0), fractions=fr, poro=float(r[7]), permx=float(r[8]),
                           ntg=float(r[10]), kvkh=float(r[9])))
    return zs


def render():
    p = S.proj()
    banner("5 - Zones & layering", f"{len(p.zones)} zones, {sum(z.nlayers for z in p.zones)} layers (before follow-top / follow-base derived counts)"
           if p.zones else "Group horizons into zones and choose a layering style for each")
    render_controls(p)


def render_controls(p):
    """Edit shared zone settings; return whether they are valid for grid construction."""
    if p.structure is None:
        note("Run the structural model first (page 4) - zones are defined between its horizons.", warn=True)
        return
    st_ = p.structure
    names = st_.names
    c1, c2 = st.columns([1, 3])
    if c1.button("One zone per horizon interval", type="primary"):
        st.session_state["zones_ver"] = st.session_state.get("zones_ver", 0) + 1
        p.zones = default_zones(names)
        # suggest styles from roles
        for z in p.zones:
            if st_.roles.get(z.top) == "erosional":
                z.style, z.dz = "follow_base", 10.0
            elif st_.roles.get(z.base) == "baselap":
                z.style, z.dz = "follow_top", 10.0
        p.grid = None
        st.rerun()
    c2.caption("Horizons (top to base): " + " > ".join(names))
    if not p.zones:
        return
    with st.expander("Layering styles"):
        for s, h in STYLE_HELP.items():
            st.markdown(f"**{s}** - {h}")
        st.markdown("Rule of thumb (Petrel/RMS): beds below an *erosional* horizon follow the **base**; beds above a *base-lap* surface follow the **top**; conformable zones are **proportional**.")
    sig = (S.rev(), st.session_state.get("zones_ver", 0), tuple(names))
    if st.session_state.get("tmp_zones_sig") != sig:               # editor input must stay constant between edits
        st.session_state["tmp_zones_base"] = _to_df(p)
        st.session_state["tmp_zones_sig"] = sig
    edited = st.data_editor(
        st.session_state["tmp_zones_base"], num_rows="dynamic", key=S.k(f"zone_ed{sig[1]}", names), hide_index=True,
        column_config={
            "Top": st.column_config.SelectboxColumn(options=names, required=True),
            "Base": st.column_config.SelectboxColumn(options=names, required=True),
            "Style": st.column_config.SelectboxColumn(options=STYLES, required=True),
            "Layers": st.column_config.NumberColumn(min_value=1, max_value=400, step=1, format="%d"),
            "dz": st.column_config.NumberColumn(min_value=0.1, format="%.1f", help="used by follow_top / follow_base (layer count derived from thickest column)"),
            "Fractions": st.column_config.TextColumn(help="comma separated thickness fractions, same count as Layers (style = fractions)"),
            "PORO": st.column_config.NumberColumn(min_value=0.0, max_value=0.6, format="%.3f"),
            "PERMX (mD)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
            "KV/KH": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, format="%.2f"),
            "NTG": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, format="%.2f"),
        })
    try:
        zones = _parse(edited.fillna({"Fractions": "", "Layers": 1, "dz": 5.0, "PORO": 0.2, "PERMX (mD)": 100.0, "KV/KH": 0.1, "NTG": 1.0}))
    except Exception as e:
        st.error(f"Table error: {e}")
        return
    errs = validate_zones(zones, names)
    for e in errs:
        st.error(e)
    if not errs and [z.to_dict() for z in zones] != [z.to_dict() for z in p.zones]:
        p.zones = zones
        p.grid = None
    # layering preview from the framework
    Z = st_.lattice_depths()
    rows = []
    for z in p.zones:
        if z.top in names and z.base in names and names.index(z.base) > names.index(z.top):
            th = Z[names.index(z.base)] - Z[names.index(z.top)]
            n = z.nlayers if z.style in ("proportional", "fractions") else int(np.ceil(th.max() / max(z.dz, 0.1)))
            rows.append({"Zone": z.name, f"Mean thickness ({un.z()})": round(float(th.mean()), 1), f"Max ({un.z()})": round(float(th.max()), 1),
                         "Pinched out": f"{100 * (th < 0.1).mean():.0f} %", "Layers": n,
                         f"Mean layer dz ({un.z()})": round(float(th.mean() / max(n, 1)), 2)})
    if rows:
        st.markdown("##### Layering preview")
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        tot = sum(r["Layers"] for r in rows)
        st.caption(f"Total layers: {tot}.  Cells in the grid = layers x columns; keep total below ~3 million for interactive use.")
    return not errs
