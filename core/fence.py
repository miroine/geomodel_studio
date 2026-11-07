"""Fence (polyline) cross-sections through the structural model.

A fence is an open polyline in map view (drawn in the Fence editor or typed). The section samples the
faulted horizons along it, marks where the fence crosses fault traces, and projects well tops / well paths
that lie within an offset of the fence.
"""
from __future__ import annotations

from typing import Dict, List, Optional
import numpy as np

from .wells import trajectory


def polyline_length(pts) -> float:
    P = np.asarray(pts, float)
    return float(np.hypot(*np.diff(P, axis=0).T).sum()) if len(P) > 1 else 0.0


def sample_polyline(pts, spacing: float, n_max: int = 2500):
    """Points every ``spacing`` along the polyline, always including the vertices.
    Returns (x, y, dist, vertex_dist)."""
    P = np.asarray(pts, float)
    if len(P) < 2:
        raise ValueError("A fence needs at least 2 vertices.")
    seg = np.hypot(*np.diff(P, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        raise ValueError("The fence has zero length.")
    spacing = max(float(spacing), total / n_max)
    d = np.unique(np.concatenate([np.arange(0.0, total, spacing), cum, [total]]))
    x = np.interp(d, cum, P[:, 0])
    y = np.interp(d, cum, P[:, 1])
    return x, y, d, cum


def project_to_polyline(pts, x, y):
    """Nearest point on the polyline for each (x, y): returns (along-distance, offset)."""
    P = np.asarray(pts, float)
    x = np.atleast_1d(np.asarray(x, float))
    y = np.atleast_1d(np.asarray(y, float))
    seg = np.diff(P, axis=0)
    L = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(L)])
    best_off = np.full(x.shape, np.inf)
    best_along = np.zeros(x.shape)
    for k in range(len(seg)):
        if L[k] == 0:
            continue
        t = ((x - P[k, 0]) * seg[k, 0] + (y - P[k, 1]) * seg[k, 1]) / L[k] ** 2
        t = np.clip(t, 0, 1)
        qx, qy = P[k, 0] + t * seg[k, 0], P[k, 1] + t * seg[k, 1]
        off = np.hypot(x - qx, y - qy)
        better = off < best_off
        best_off = np.where(better, off, best_off)
        best_along = np.where(better, cum[k] + t * L[k], best_along)
    return best_along, best_off


def fault_crossings(pts, faults) -> List[dict]:
    """Where the fence crosses fault traces: [{dist, name, color}]."""
    P = np.asarray(pts, float)
    seg = np.diff(P, axis=0)
    L = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(L)])
    out = []
    for f in faults:
        T = np.asarray(f.trace, float)
        for i in range(len(P) - 1):
            p, r = P[i], seg[i]
            for j in range(len(T) - 1):
                q, s = T[j], T[j + 1] - T[j]
                den = r[0] * s[1] - r[1] * s[0]
                if abs(den) < 1e-12:
                    continue
                t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
                u = ((q[0] - p[0]) * r[1] - (q[1] - p[1]) * r[0]) / den
                if 0 <= t <= 1 and 0 <= u <= 1:
                    out.append(dict(dist=float(cum[i] + t * L[i]), name=f.name, color=getattr(f, "color", "") or "#B8003C"))
    return sorted(out, key=lambda d: d["dist"])


def fence_section(structure, pts, spacing: Optional[float] = None, with_faults: bool = True) -> dict:
    """Sample the model along a fence. Returns dict(dist, x, y, Z (nh, n), vertex_dist, crossings, names)."""
    g = structure.geom
    sp = spacing or 0.75 * min(g.xinc, g.yinc)
    x, y, d, cum = sample_polyline(pts, sp)
    Z = structure.eval(x, y, with_faults=with_faults)
    return dict(dist=d, x=x, y=y, Z=Z, vertex_dist=cum, names=list(structure.names),
                crossings=fault_crossings(pts, structure.faults))


def project_tops(pts, tops, max_offset: float) -> List[dict]:
    if tops is None or len(tops) == 0:
        return []
    along, off = project_to_polyline(pts, tops["x"].values, tops["y"].values)
    keep = off <= max_offset
    return [dict(x=float(a), z=float(z), label=f"{w} ({h})", offset=float(o))
            for a, z, w, h, o in zip(along[keep], tops["z"].values[keep], tops["well"].values[keep], tops["horizon"].values[keep], off[keep])]


def project_wells(pts, wells: Dict, max_offset: float, step: float = 20.0) -> List[dict]:
    """Well paths projected onto the fence plane: [{name, x (along), z, offset}] for wells within the offset."""
    out = []
    for w in wells.values():
        try:
            tr = trajectory(w, 2500.0, step)
        except Exception:
            continue
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(tr, axis=0), axis=1))])
        if arc[-1] > step:                                         # densify straight segments so the projection is smooth
            u = np.arange(0.0, arc[-1], step)
            u = np.append(u, arc[-1])
            tr = np.column_stack([np.interp(u, arc, tr[:, c]) for c in range(3)])
        along, off = project_to_polyline(pts, tr[:, 0], tr[:, 1])
        if np.nanmin(off) > max_offset:
            continue
        m = off <= max_offset
        out.append(dict(name=w.name, x=along[m].tolist(), z=tr[m, 2].tolist(), offset=float(np.nanmin(off))))
    return out
