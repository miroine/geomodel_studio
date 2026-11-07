"""Export: GRDECL / ROFF / EGRID / VTK grids, surfaces, faults, tops, project."""
import io

import numpy as np
import pandas as pd
import streamlit as st

from core import export as ex
from core import simfmt as sf
from core import package as pk
from core import faultfaces as ff
from core import resqml as rz
from core import units as un
from core import project as pj
from core.surface import Surface
from ui import state as S
from ui.theme import banner, kpis, note

GRID_PROPS = ["PORO", "PERMX", "PERMY", "PERMZ", "NTG", "FIPNUM", "SATNUM"]


def _prepared(key, sig, builder, label, filename, mime="application/octet-stream"):
    """Two-step download: build on demand (large files), then offer the download button."""
    c1, c2 = st.columns([1, 2])
    store = st.session_state.setdefault("tmp_exports", {})
    if c1.button(f"Prepare {label}", key=S.k("prep_" + key)):
        try:
            with st.spinner(f"Writing {label}..."):
                data = builder()
            store[key] = (sig, data)
        except Exception as e:
            st.error(f"{label}: {e}")
    if key in store and store[key][0] == sig:
        data = store[key][1]
        raw = data if isinstance(data, (bytes, bytearray)) else data.encode()
        c2.download_button(f"Download {filename} ({len(raw) / 1e6:.1f} MB)", raw, file_name=filename, mime=mime, key=S.k("dl_" + key))


def render():
    p = S.proj()
    g = p.grid
    banner("10 - Export", "Export the corner-point grid to a reservoir simulator, and the horizons, faults and tops to other tools"
           if g else "Export surfaces and project now; build the 3D grid to unlock simulator formats")
    t1, t2, t3 = st.tabs(["Grid for simulators", "Surfaces, faults, tops", "Project"])
    with t1:
        if g is None:
            note("Build the 3D grid first (page 6).", warn=True)
        else:
            sm = g.summary()
            kpis([("Grid", f"{g.ni} x {g.nj} x {g.nk}"), ("Active cells", f"{sm['active']:,}"), ("Fault blocks", sm["fault_blocks"])])
            custom = {n: v for n, v in p.properties.items() if v.values.shape == (g.nk, g.nj, g.ni)}
            ca, cb = st.columns(2)
            ra = ca.selectbox("Write REGION (fault blocks) also as", ["-", "FIPNUM", "EQLNUM", "SATNUM", "FLUXNUM"], key=S.k("ex_ra"), disabled="REGION" not in custom)
            sa = cb.selectbox("Write SEGMENT also as", ["-", "FIPNUM", "EQLNUM", "SATNUM", "FLUXNUM"], key=S.k("ex_sa"), disabled="SEGMENT" not in custom)
            aliased = []
            for src_, al in (("REGION", ra), ("SEGMENT", sa)):
                if al != "-" and src_ in custom:
                    custom[al] = custom[src_]
                    aliased.append(al)
            if not custom.keys() & {"REGION", "SEGMENT"}:
                st.caption("Create REGION / SEGMENT on the Properties page (Planes & regions) to write them as FIPNUM / EQLNUM.")
            opts = GRID_PROPS + [n for n in custom if n not in GRID_PROPS]
            props = st.multiselect("Cell properties to write (zone constants, or the property of that name from the Properties page)", opts,
                                   default=[d for d in ["PORO", "PERMX", "PERMY", "PERMZ", "NTG", "FIPNUM"] + aliased if d in opts], key=S.k("ex_props", opts + aliased))
            long_ = [n for n in props if len(n) > 8]
            if long_:
                st.warning("Eclipse keywords are limited to 8 characters: " + ", ".join(long_))
            blocks = st.checkbox("Also write fault blocks as FLUXNUM", False, key=S.k("ex_blocks"))
            wfaults = st.checkbox("Write FAULTS + MULTFLT (fault cell faces and transmissibility multipliers from the Faults page)", bool(p.faults), key=S.k("ex_faults"), disabled=not p.faults)
            est = g.ncells * 8 * 9 / 1e6
            st.caption(f"Estimated GRDECL size about {est + g.ncells * len(props) * 0.007:.0f} MB (ZCORN dominates).")
            sysdef = un.unit_system(p.crs["xy_unit"], p.crs["z_unit"])
            system = st.radio("Simulator unit system", ["METRIC", "FIELD"], index=1 if sysdef == "FIELD" else 0, horizontal=True,
                              key=S.k("ex_sys"), help="METRIC = metres, FIELD = feet. Coordinates and depths are converted from the project "
                              f"units ({un.xy()} / {un.z()}) when they differ.")
            if sysdef == "MIXED":
                st.caption(f"Project units are mixed (XY {un.xy()}, Z {un.z()}) - both are converted to the chosen system.")
            g0 = g
            g = ex.grid_for_system(g0, p.crs, system)
            fm_ = tuple(sorted(p.fault_mult.items()))

            def fault_txt():
                return ff.faults_keywords(g, list(p.faults.values()), p.fault_mult) if wfaults else ""
            sig = (id(g0), fm_, wfaults, tuple(props), blocks, system, tuple((n, c.values.sum()) for n, c in custom.items() if n in props))
            st.markdown("**Eclipse GRDECL** - Eclipse, OPM Flow, INTERSECT, tNavigator, CMG Builder, Petrel, RMS")
            _prepared("grdecl", sig, lambda: ex.grdecl_text(g, props, p.name, blocks, system=system, custom=custom, extra=fault_txt()), "GRDECL", "MODEL.GRDECL", "text/plain")
            st.markdown("**Eclipse binary: EGRID + INIT** (written natively, no extra libraries)")
            esig = (id(g0), tuple(props), blocks, system, tuple(aliased), tuple((n, c.values.sum()) for n, c in custom.items() if n in props))

            def _init():
                arrs = {}
                for n in props:
                    if n in custom:
                        arrs[n] = (custom[n].values, custom[n].kind)
                    elif n in ("PORO", "NTG", "PERMX", "PERMY", "PERMZ"):
                        arrs[n] = (g.property_array(n), "continuous")
                    elif n in ("FIPNUM", "SATNUM"):
                        arrs[n] = (g.zone_layer_array(), "discrete")
                if blocks:
                    arrs["FLUXNUM"] = (g.block_array(), "discrete")
                sn = sf.short_names(list(arrs))
                return sf.init_bytes(g, {sn[k]: v for k, v in arrs.items()}, system)
            _prepared("egrid", (id(g0), system), lambda: sf.egrid_bytes(g, system), "EGRID", "MODEL.EGRID")
            _prepared("init", esig, _init, "INIT", "MODEL.INIT")
            st.markdown("**Hand-over package for RMS / Petrel / Eclipse** - GRDECL + EGRID + INIT (+ ROFF with xtgeo), horizons (IRAP), fault polylines, wells, tops, README")
            c1_, c2_ = st.columns(2)
            pxy = c1_.selectbox("Package XY unit", un.UNITS, index=un.UNITS.index("ft" if system == "FIELD" else "m"), key=S.k("pk_xy"))
            pz_ = c2_.selectbox("Package depth unit", un.UNITS, index=un.UNITS.index("ft" if system == "FIELD" else "m"), key=S.k("pk_z"))
            _prepared("pkg", esig + (pxy, pz_, id(p.structure)), lambda: pk.build(p, g, system, list(props), custom, pxy, pz_, blocks), "package", "geomodel_export.zip", "application/zip")
            st.markdown("**RESQML 2.0.1** (EPC + HDF5; Petrel, RMS, ResInsight, other RESQML readers)")
            rok, rmsg = rz.available()
            if rok:
                rprops = {n: custom[n] for n in props if n in custom}
                for n_ in props:                              # zone-table properties and zone-number properties
                    if n_ not in rprops and n_ in ("PORO", "NTG", "PERMX", "PERMY", "PERMZ"):
                        from core import props as _pp
                        rprops[n_] = _pp.make_property(g0, n_, g0.property_array(n_), "continuous", "", "zones")
                _prepared("resqml", esig + ("resqml",), lambda: rz.export_epc(g, rprops, system, p.name), "RESQML", "model_resqml.zip", "application/zip")
            else:
                st.caption(rmsg + " Add them to the server's environment (they are listed in requirements.txt).")
            st.markdown("**ParaView VTK** (active cells, elevation = -depth)")
            vsc = {"PORO": g.property_array("PORO"), "ZONE": g.zone_layer_array(), "FAULT_BLOCK": g.block_array()}
            vsc.update({n: c.values for n, c in list(custom.items())[:12]})
            _prepared("vtk", (id(g0), system, tuple(custom)), lambda: ex.vtk_text(g, vsc), "VTK", "model.vtk", "text/plain")
            st.markdown("**RMS ROFF / Eclipse EGRID / binary GRDECL** (geometry + ACTNUM through xtgeo)")
            if ex.HAS_XTGEO:
                lab = st.selectbox("Format", list(ex.XTGEO_FORMATS), key=S.k("ex_xt"))
                fmt, ext = ex.XTGEO_FORMATS[lab]
                _prepared("xt" + fmt, (id(g0), fmt, system), lambda: ex.xtgeo_convert(ex.grdecl_text(g, [], p.name, gridunit=False), fmt), lab.split(" (")[0], f"MODEL.{ext}")
            else:
                st.caption("Install xtgeo (`pip install xtgeo`) to enable ROFF / EGRID export.")
            with st.expander("Test deck for OPM Flow / Eclipse"):
                st.code(ex.deck_snippet(g, system=system), language="text")
            note("<b>RESCUE</b> (the retired POSC binary exchange format) is not written: its byte layout is not openly specified. RESQML is its successor and is "
                 "written above (needs resqpy + h5py). GRDECL / EGRID / ROFF are read by Petrel and RMS directly (Petrel: <i>Import (on selection)</i> &rarr; Eclipse grid; RMS: <i>Import &rarr; Grid &rarr; Eclipse GRDECL</i>).")
    with t2:
        o1, o2 = st.columns(2)
        xy_out = o1.selectbox("Output XY unit", un.UNITS, index=un.UNITS.index(p.crs["xy_unit"]), key=S.k("ex_xy"))
        z_out = o2.selectbox("Output depth unit", un.UNITS, index=un.UNITS.index(p.crs["z_unit"]), key=S.k("ex_z"))
        fxo, fzo = un.factor(p.crs["xy_unit"], xy_out), un.factor(p.crs["z_unit"], z_out)
        epsg = p.crs.get("epsg")
        st.caption(f"CRS: {p.crs.get('name')} {f'(EPSG:{epsg})' if epsg else ''}; values are converted from the project units on export. "
                   "IRAP / ESRI files carry no CRS - note it in the file name or hand-over.")
        c1, c2 = st.columns(2)
        fmt = c1.selectbox("Surface format", ["irap_binary", "irap_ascii", "esri_ascii", "xyz"], key=S.k("ex_sfmt"),
                           format_func=lambda x: {"irap_binary": "IRAP / RMS binary (.gri)", "irap_ascii": "IRAP / RMS ASCII", "esri_ascii": "ESRI ASCII grid (.asc)", "xyz": "XYZ CSV"}[x])
        src = c2.radio("Which surfaces", ["Final horizons (faulted)", "Library surfaces"], key=S.k("ex_src"))
        surfs = {}
        if src.startswith("Final"):
            if p.structure is None:
                st.info("Run the structural model to export final horizons.")
            else:
                Z = p.structure.lattice_depths()
                for h, z in zip(p.structure.names, Z):
                    surfs[h] = Surface(h, p.lattice, z, "model")
                    
        else:
            surfs = dict(p.surfaces)
        surfs = {n: un.scale_surface(s, fxo, fzo) for n, s in surfs.items()}
        if surfs:
            _prepared("surf", (fmt, src, tuple(surfs), id(p.structure), xy_out, z_out), lambda: ex.surfaces_zip(surfs, fmt), "surfaces ZIP", "surfaces.zip", "application/zip")
        if p.faults:
            rows = []
            for f in p.faults.values():
                for i, (x, y) in enumerate(f.trace):
                    rows.append(dict(fault=f.name, order=i, x=x * fxo, y=y * fxo, type=f.ftype, throw=f.throw * fzo, dip=f.dip, hw_side=f.hw_side, zref=f.zref * fzo))
            st.download_button("Fault traces (CSV)", pd.DataFrame(rows).to_csv(index=False), file_name="fault_traces.csv")
        if not p.tops.empty:
            st.download_button("Well tops (CSV)", ex.tops_in_units(p.tops, p.crs, xy_out, z_out).to_csv(index=False), file_name="well_tops.csv")
    with t3:
        if p.has_lattice():
            st.download_button("Save project (.gmsz)", pj.to_bytes(p), file_name=f"{p.name.replace(' ', '_')}.gmsz", mime="application/zip")
            st.caption("Contains surfaces, faults, tops, workflow, zones and grid settings. The grid is rebuilt on demand.")
