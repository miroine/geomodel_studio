"""RESQML 2.0.1 export (EPC package + HDF5 arrays) of the corner-point grid and its properties.

The XML/HDF5 writing is delegated to resqpy (the open-source reference implementation; it needs h5py), so the schema details are not
re-implemented here.  This module builds the (nk, nj, ni, 2, 2, 2, 3) corner-point array resqpy expects, maps the properties to RESQML property
kinds and zips the .epc + .h5 files."""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from typing import Dict, Tuple
import numpy as np

KINDS = {  # keyword -> (RESQML property kind, unit of measure)
    "PORO": ("porosity", "m3/m3"), "NTG": ("net to gross ratio", "m3/m3"),
    "PERMX": ("permeability rock", "mD"), "PERMY": ("permeability rock", "mD"), "PERMZ": ("permeability rock", "mD"),
}


def available() -> Tuple[bool, str]:
    miss = []
    for mod in ("h5py", "resqpy"):
        try:
            __import__(mod)
        except Exception:
            miss.append(mod)
    if miss:
        return False, "RESQML export needs " + " and ".join(miss) + " (pip install resqpy h5py)."
    return True, ""


def corner_points(g) -> np.ndarray:
    """Cell corner coordinates, shape (nk, nj, ni, 2, 2, 2, 3) indexed [k, j, i, kp, jp, ip, xyz] (kp = top/base, jp, ip = low/high side)."""
    cp = np.empty((g.nk, g.nj, g.ni, 2, 2, 2, 3))
    kk, jj, ii = np.indices((g.nk, g.nj, g.ni))
    for kp in (0, 1):
        for jp in (0, 1):
            for ip in (0, 1):
                cp[:, :, :, kp, jp, ip, 0], cp[:, :, :, kp, jp, ip, 1] = g.corner_xy(kk, kp, jj, jp, ii, ip)
    cp[..., 2] = g.zc.transpose(0, 2, 4, 1, 3, 5)
    return cp


def property_spec(name: str, prop) -> dict:
    kind, uom = KINDS.get(name, (None, None))
    if prop is not None and prop.kind == "discrete":
        return dict(property_kind="discrete", uom=None, discrete=True)
    return dict(property_kind=kind or "continuous", uom=uom or (prop.unit if prop is not None and prop.unit else "Euc"), discrete=False)


def export_epc(g, props: Dict[str, object], system: str = "METRIC", title: str = "GeoModel Studio grid") -> bytes:
    """Zip with model.epc, model.h5 and a legend README.  ``g`` must already be in the output unit system; ``props`` = {name: Property}."""
    ok, msg = available()
    if not ok:
        raise RuntimeError(msg)
    import resqpy.model as rq
    import resqpy.crs as rqc
    import resqpy.grid as grr
    import resqpy.property as rqp
    unit = "m" if system == "METRIC" else "ft"
    with tempfile.TemporaryDirectory() as tmp:
        epc = os.path.join(tmp, "model.epc")
        model = rq.new_model(epc)
        crs = rqc.Crs(model, x_units=unit, y_units=unit, z_units=unit, z_inc_down=True, title="Project CRS")
        crs.create_xml()
        grid = grr.grid_from_cp(model, corner_points(g), crs.uuid, active_mask=(g.actnum > 0), ijk_handedness="right")
        grid.title = title
        grid.write_hdf5()
        grid.create_xml(write_geometry=True)
        legends = []
        for n, pr in props.items():
            spec = property_spec(n, pr)
            arr = np.nan_to_num(np.asarray(pr.values, float), nan=0.0)
            if spec["discrete"]:
                arr = np.rint(arr).astype(int)
                legends.append(f"{n}: " + ", ".join(f"{k}={v}" for k, v in pr.legend.items()))
            rqp.Property.from_array(model, arr, source_info="GeoModel Studio", keyword=n, support_uuid=grid.uuid, property_kind=spec["property_kind"],
                                    indexable_element="cells", uom=spec["uom"], discrete=spec["discrete"])
        model.store_epc()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(tmp)):
                z.write(os.path.join(tmp, fn), fn)
            z.writestr("README.txt", f"RESQML 2.0.1 model written with resqpy. Grid {g.ni} x {g.nj} x {g.nk}, {unit}, depth positive down.\n"
                       "Keep model.epc and model.h5 together.\n" + ("\nDiscrete property legends:\n" + "\n".join(legends) + "\n" if legends else ""))
        return buf.getvalue()
