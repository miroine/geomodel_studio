"""Non-destructive surface filter stack.

Each surface keeps its *raw* depth map; the visible surface is ``apply_stack(raw, ops)``.  Ops are plain
dicts so they can be edited, re-ordered, switched off, saved as presets and stored in the project:

  polygon : keep inside / outside a polygon (optional buffer)      {polygon, keep, buffer}
  range   : keep values within [min, max] (absolute or percentile)  {mode, min, max}
  spikes  : remove nodes that deviate from the local median         {window, k}
  slope   : remove nodes steeper than a slope (m/m)                 {max_slope}
  fill    : fill small holes by interpolation                       {max_cells}
  extend  : fill / extrapolate undefined nodes (see core.extrap)    {mode, length, value, tension, max_dist}
"""
from __future__ import annotations

from typing import Dict, List, Tuple
import numpy as np
from scipy import ndimage
from scipy.interpolate import griddata

from . import units as un
from .surface import Geometry, fill_nan_nearest
from . import polygons as pg

OP_TYPES = ["polygon", "range", "spikes", "slope", "fill", "extend"]
OP_LABEL = {"polygon": "Clip by polygon", "range": "Value range", "spikes": "Remove spikes",
            "slope": "Remove steep slopes", "fill": "Fill small holes", "extend": "Extend / extrapolate"}


def default_op(kind: str, **kw) -> dict:
    base = {"polygon": dict(type="polygon", polygon="", keep="inside", buffer=0.0),
            "range": dict(type="range", mode="absolute", min=None, max=None),
            "spikes": dict(type="spikes", window=3, k=4.0),
            "slope": dict(type="slope", max_slope=0.5),
            "fill": dict(type="fill", max_cells=3),
            "extend": dict(type="extend", mode="gradient", length=0.0, value=0.0, tension=0.0, max_dist=0.0)}[kind]
    base.update(kw)
    base["enabled"] = True
    return base


def describe(op: dict) -> str:
    t = op["type"]
    if t == "polygon":
        b = f", buffer {op['buffer']:+.0f} {un.xy()}" if op.get("buffer") else ""
        return f"{'Keep inside' if op.get('keep', 'inside') == 'inside' else 'Remove inside'} polygon **{op.get('polygon') or '?'}**{b}"
    if t == "range":
        lo, hi = op.get("min"), op.get("max")
        unit = " percentile" if op.get("mode") == "percentile" else " " + un.z()
        return f"Keep values {'' if lo is None else f'>= {lo:g}'}{' and ' if lo is not None and hi is not None else ''}{'' if hi is None else f'<= {hi:g}'}{unit}"
    if t == "spikes":
        return f"Remove spikes (> {op['k']:g} robust sigma from the {op['window']}x{op['window']} median)"
    if t == "slope":
        return f"Remove slopes steeper than {op['max_slope']:g} dz/dx"
    if t == "extend":
        lim = f" within {op['max_dist']:g} {un.xy()}" if op.get("max_dist") else ""
        return f"Extend undefined area by **{op.get('mode', 'nearest')}**{lim}"
    if t == "fill":
        return f"Fill holes up to {op['max_cells']} cells from valid data"
    return str(op)


def apply_op(z: np.ndarray, geom: Geometry, op: dict, polys: Dict[str, pg.Polygon]) -> np.ndarray:
    z = z.copy()
    t = op["type"]
    if t == "polygon":
        poly = polys.get(op.get("polygon"))
        if poly is None:
            raise ValueError(f"Polygon '{op.get('polygon')}' not found")
        m = pg.mask(geom, poly, float(op.get("buffer", 0.0)))
        keep = m if op.get("keep", "inside") == "inside" else ~m
        z[~keep] = np.nan
    elif t == "range":
        lo, hi = op.get("min"), op.get("max")
        if op.get("mode") == "percentile":
            v = z[np.isfinite(z)]
            if v.size:
                lo = None if lo is None else float(np.percentile(v, lo))
                hi = None if hi is None else float(np.percentile(v, hi))
        with np.errstate(invalid="ignore"):
            if lo is not None:
                z[z < lo] = np.nan
            if hi is not None:
                z[z > hi] = np.nan
    elif t in ("spikes", "slope"):
        valid = np.isfinite(z)
        if valid.sum() < 9:
            return z
        filled = fill_nan_nearest(z)
        if t == "spikes":
            w = int(op.get("window", 3))
            med = ndimage.median_filter(filled, size=w, mode="nearest")
            r = filled - med
            ar = np.abs(r - np.median(r))
            # MAD collapses to ~0 on near-planar maps; the 90th percentile (half-normal: 1.645 sigma) is a stable floor
            s = max(1.4826 * np.median(ar), float(np.percentile(ar, 90)) / 1.645, 1e-6 * (np.ptp(filled) + 1.0))
            bad = np.abs(r) > float(op.get("k", 4.0)) * s
        else:
            gy, gx = np.gradient(filled, geom.yinc, geom.xinc)
            bad = np.hypot(gx, gy) > float(op.get("max_slope", 0.5))
        z[bad & valid] = np.nan
    elif t == "fill":
        valid = np.isfinite(z)
        if valid.all() or not valid.any():
            return z
        dist = ndimage.distance_transform_edt(~valid)
        target = (~valid) & (dist <= float(op.get("max_cells", 3)))
        if target.any():
            X, Y = geom.coords()
            lin = griddata((X[valid], Y[valid]), z[valid], (X[target], Y[target]), method="linear")
            nn = griddata((X[valid], Y[valid]), z[valid], (X[target], Y[target]), method="nearest")
            z[target] = np.where(np.isfinite(lin), lin, nn)
    elif t == "extend":
        from .extrap import fill_undefined
        valid = np.isfinite(z)
        if valid.all() or not valid.any():
            return z
        out = fill_undefined(z, geom, op.get("mode", "nearest"), length=float(op.get("length", 0.0)), value=float(op.get("value", 0.0)),
                             tension=float(op.get("tension", 0.0)))
        md = float(op.get("max_dist", 0.0) or 0.0)
        if md > 0:
            dist = ndimage.distance_transform_edt(~valid, sampling=(geom.yinc, geom.xinc))
            out = np.where(dist <= md, out, np.nan)
        z = out
    else:
        raise ValueError(f"Unknown filter {t}")
    return z


def apply_stack(raw: np.ndarray, geom: Geometry, ops: List[dict], polys: Dict[str, pg.Polygon]) -> Tuple[np.ndarray, List[dict]]:
    z = raw.copy()
    report = []
    for op in ops:
        if not op.get("enabled", True):
            report.append(dict(label=describe(op), removed=0, enabled=False, defined=float(np.isfinite(z).mean())))
            continue
        before = np.isfinite(z)
        try:
            z = apply_op(z, geom, op, polys)
            err = None
        except Exception as e:      # keep the stack usable: a broken op is skipped and reported
            err = str(e)
        after = np.isfinite(z)
        report.append(dict(label=describe(op), removed=int((before & ~after).sum()), added=int((~before & after).sum()),
                           enabled=True, error=err, defined=float(after.mean())))
    return z, report


def suggest(raw: np.ndarray, geom: Geometry) -> dict:
    """Numbers the UI shows to help choosing thresholds."""
    v = raw[np.isfinite(raw)]
    if v.size == 0:
        return {}
    out = dict(p01=float(np.percentile(v, 1)), p99=float(np.percentile(v, 99)), zmin=float(v.min()), zmax=float(v.max()))
    for k in (3.0, 4.0, 6.0):
        z = apply_op(raw, geom, dict(type="spikes", window=3, k=k), {})
        out[f"spikes_k{int(k)}"] = int((np.isfinite(raw) & ~np.isfinite(z)).sum())
    return out
