"""Python wrappers for the two JavaScript components (no npm build; plain HTML/JS directories)."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent
COMP = ROOT / "components"


def ensure_plotly_js() -> bool:
    """Copy the Plotly.js bundle shipped inside the `plotly` Python package next to the viewer
    (works offline).  The viewer falls back to the CDN when the file is missing."""
    dst = COMP / "plotly_view" / "plotly.min.js"
    if dst.exists():
        return True
    try:
        import plotly  # type: ignore
        src = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        if src.exists():
            shutil.copy(src, dst)
            return True
    except Exception:
        pass
    return False


ensure_plotly_js()
_map_editor = components.declare_component("geomodel_map_editor", path=str(COMP / "map_editor"))
_plotly_view = components.declare_component("geomodel_plotly_view", path=str(COMP / "plotly_view"))
_viewer3d = components.declare_component("geomodel_viewer3d", path=str(COMP / "viewer3d"))


def clean(o, nd=2):
    """Make numpy / NaN content JSON-safe (NaN -> None, floats rounded)."""
    if isinstance(o, dict):
        return {str(k): clean(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v, nd) for v in o]
    if isinstance(o, np.ndarray):
        if o.dtype.kind == "f":
            a = np.round(o, nd)
            bad = ~np.isfinite(a)
            if bad.any():
                lst = a.astype(object)
                lst[bad] = None
                return lst.tolist()
            return a.tolist()
        return o.tolist()
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if not np.isfinite(v) else round(v, nd)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def revision(payload) -> str:
    return hashlib.md5(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]


def plotly_view(spec: dict, key: str, height: int = 520):
    spec = clean(spec, 3)
    rev = revision(spec)
    _plotly_view(spec=spec, height=height, rev=rev, key=key, default=None)


def viewer3d(scene, key: str, height: int = 680, ve: float = 3.0):
    """Interactive WebGL 3D window.  ``scene`` is a ui.scene.Scene; camera / visibility survive reruns
    as long as the scene extent (cam_key) is unchanged."""
    d = scene.to_dict()
    rev = revision([[o["id"], len(o.get("pos", o.get("path", ""))), o.get("color"), o.get("opacity"), o.get("visible", True),
                     hashlib.md5((o.get("pos") or o.get("path") or "").encode()).hexdigest(),
                     hashlib.md5((o.get("col") or "").encode()).hexdigest(), o.get("tops")] for o in d["objects"]] + [d["bounds"]])
    _viewer3d(scene=d, rev=rev, cam_key=scene.cam_key, height=height, ve=ve, key=key, default=None)


def map_editor(mode: str, key: str, height: int = 660, grid=None, extent=None, faults=None, wells=None,
               contours=None, points=None, traces=None, defaults=None, z_default=2000.0, nonce_tag="",
               polygons=None, boundary=None):
    """Bidirectional editor.  Returns the last value sent by the user (dict) or None."""
    if grid is not None:
        z = np.asarray(grid["z"], dtype=float)
        shape = (grid["nrow"], grid["ncol"])
        if z.shape not in (shape, (shape[0] * shape[1],)):
            raise ValueError(f"Map editor grid depths must have shape {shape} or be a flat array of {shape[0] * shape[1]} values.")
        grid = dict(grid, z=z.ravel())
    args = dict(mode=mode, height=height, extent=extent, grid=grid, faults=faults or [], wells=wells or [],
                contours=contours or [], points=points or [], traces=traces or [], defaults=defaults or {},
                z_default=z_default, polygons=polygons or [], boundary=boundary or "")
    args = clean(args, 2)
    rev = revision([args, nonce_tag])
    return _map_editor(rev=rev, key=key, default=None, **args)
