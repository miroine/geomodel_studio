"""One-click hand-over package: the 3D grid for Eclipse / RMS / Petrel and the structural data in RMS-readable text formats."""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from typing import Dict, List, Optional
import numpy as np

from . import export as ex
from . import simfmt as sf
from . import units as un
from . import io_surfaces
from . import wells as wl
from . import faultfaces as FF
from .surface import Surface

RMS_SEP = "999.00 999.00 999.00"


def rms_polylines(lines: Dict[str, np.ndarray]) -> str:
    """RMS internal polygon / polyline ASCII: 'x y z' per vertex, each line closed by a '999.00 999.00 999.00' record."""
    out = io.StringIO()
    for _, pts in lines.items():
        for x, y, z in np.asarray(pts, float):
            out.write(f"{x:.3f} {y:.3f} {z:.3f}\n")
        out.write(RMS_SEP + "\n")
    return out.getvalue()


def rms_well_picks(tops, xy_unit="m", z_unit="m") -> str:
    """Whitespace-delimited well-pick table (well, horizon/zone, x, y, TVDSS) - map the columns in the RMS import dialog."""
    cols = [c for c in ("well", "horizon", "zone", "x", "y", "z") if c in tops.columns]
    t = tops[cols]
    head = "# " + " ".join(cols) + f"   (x, y in {xy_unit}; z = TVDSS positive down in {z_unit})\n"
    return head + "\n".join(" ".join(str(v) if not isinstance(v, (float, np.floating)) else f"{v:.3f}" for v in r) for r in t.itertuples(index=False)) + "\n"


def roff_files(grdecl_text: str, names: List[str]) -> Dict[str, bytes]:
    """ROFF grid + one ROFF file per property through xtgeo (only when xtgeo is installed)."""
    if not ex.HAS_XTGEO:
        raise RuntimeError("xtgeo is not installed")
    xt = ex.xtgeo
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "model.grdecl")
        with open(src, "w") as f:
            f.write(grdecl_text)
        grid = xt.grid_from_file(src, fformat="grdecl")
        dst = os.path.join(tmp, "grid.roff")
        grid.to_file(dst, fformat="roff_binary")
        out["MODEL.roff"] = open(dst, "rb").read()
        for n in names:
            try:
                prop = xt.gridproperty_from_file(src, fformat="grdecl", name=n, grid=grid)
                pd_ = os.path.join(tmp, n + ".roff")
                prop.to_file(pd_, fformat="roff", name=n)
                out[f"{n}.roff"] = open(pd_, "rb").read()
            except Exception as e:  # keep going with the other properties
                out[f"{n}.error.txt"] = str(e).encode()
    return out


def build(p, g, system: str, prop_names: List[str], custom: dict, xy_out: str, z_out: str, with_blocks=True, want_roff=True) -> bytes:
    """Zip with grid/ (GRDECL, EGRID, INIT, ROFF), surfaces/, faults/, wells/, tops/ and a README.  ``g`` is already in the output system."""
    notes: List[str] = []
    buf = io.BytesIO()
    fx, fz = un.factor(p.crs["xy_unit"], xy_out), un.factor(p.crs["z_unit"], z_out)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        gtxt = ex.grdecl_text(g, prop_names, p.name, with_blocks, system=system, custom=custom, extra=FF.faults_keywords(g, list(p.faults.values()), p.fault_mult))
        z.writestr("grid/MODEL.GRDECL", gtxt)
        z.writestr("grid/MODEL.EGRID", sf.egrid_bytes(g, system))
        arrs = {}
        for n in prop_names:
            if n in custom:
                arrs[n] = (custom[n].values, custom[n].kind)
            elif n in ("PORO", "NTG", "PERMX", "PERMY", "PERMZ"):
                arrs[n] = (g.property_array(n), "continuous")
            elif n in ("FIPNUM", "SATNUM"):
                arrs[n] = (g.zone_layer_array(), "discrete")
        if with_blocks:
            arrs["FLUXNUM"] = (g.block_array(), "discrete")
        sn = sf.short_names(list(arrs))
        z.writestr("grid/MODEL.INIT", sf.init_bytes(g, {sn[k]: v for k, v in arrs.items()}, system))
        renamed = {k: v for k, v in sn.items() if k != v}
        if renamed:
            notes.append("INIT keyword names shortened to 8 characters: " + ", ".join(f"{k}->{v}" for k, v in renamed.items()))
        if want_roff:
            if ex.HAS_XTGEO:
                try:
                    for fn, data in roff_files(gtxt, [n for n in prop_names if n in custom or n in ("PORO", "NTG", "PERMX", "PERMY", "PERMZ")]).items():
                        z.writestr("grid/roff/" + fn, data)
                except Exception as e:
                    notes.append(f"ROFF export failed: {e}")
            else:
                notes.append("ROFF not written: xtgeo is not installed on this server. Import MODEL.GRDECL in RMS (Eclipse grid import) instead, or install xtgeo.")
        if p.structure is not None:
            surfs = {}
            for h, zz in zip(p.structure.names, p.structure.lattice_depths()):
                surfs[h] = un.scale_surface(Surface(h, p.lattice, zz, "model"), fx, fz)
            for n, s in surfs.items():
                data, ext = io_surfaces.write_surface(s, "irap_binary")
                z.writestr(f"surfaces/{n.replace(' ', '_')}.{ext}", data)
        else:
            notes.append("Horizons not written: run the structural model first.")
        if p.faults:
            lines = {f.name: np.column_stack([np.asarray(f.trace, float) * fx, np.full(len(f.trace), f.zref * fz)]) for f in p.faults.values()}
            z.writestr("faults/fault_traces.rmspolygons", rms_polylines(lines))
        if p.wells:
            for n, w in p.wells.items():
                tr = wl.trajectory(w)
                tr = np.column_stack([tr[:, 0] * fx, tr[:, 1] * fx, tr[:, 2] * fz])
                z.writestr(f"wells/{n.replace(' ', '_')}.xyz", "\n".join(f"{a:.3f} {b:.3f} {c:.3f}" for a, b, c in tr) + "\n")
        if not p.tops.empty:
            z.writestr("tops/well_picks.txt", rms_well_picks(ex.tops_in_units(p.tops, p.crs, xy_out, z_out), xy_out, z_out))
        z.writestr("README.txt", _readme(p, g, system, prop_names, notes, xy_out, z_out))
    return buf.getvalue()


def _readme(p, g, system, prop_names, notes, xy_out, z_out) -> str:
    return "\n".join([
        f"GeoModel Studio export - {p.name}",
        f"Grid {g.ni} x {g.nj} x {g.nk} ({int((g.actnum > 0).sum())} active cells), unit system {system}; surfaces / faults / wells / tops in {xy_out} / {z_out}.",
        "",
        "grid/MODEL.GRDECL   Eclipse ASCII grid + properties (" + ", ".join(prop_names) + "). Reads in Petrel, RMS, OPM Flow, Eclipse, tNavigator, CMG.",
        "grid/MODEL.EGRID    Eclipse binary grid (geometry + ACTNUM).",
        "grid/MODEL.INIT     Eclipse binary static properties on the active cells (PORV, DEPTH, DX, DY, DZ and the properties above).",
        "grid/roff/          RMS ROFF grid and one file per property (only when xtgeo is installed on the server).",
        "surfaces/           Final horizons as IRAP / RMS binary maps.",
        "faults/             Fault traces as RMS polylines (x y z, '999.00 999.00 999.00' between lines).",
        "wells/, tops/       Well paths (x y TVDSS) and picks as tables.",
        "",
        "RESCUE is not written (see the app's export page); use GRDECL or ROFF to move the grid into Petrel / RMS.",
        "",
        *(["Notes:"] + ["- " + n for n in notes] if notes else []),
    ]) + "\n"
