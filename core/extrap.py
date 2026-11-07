"""Fill / extrapolate undefined nodes of a depth map.

Modes
-----
none          keep NaN (the area stays undefined)
nearest       value of the nearest defined node (flat extension; the v1/v2 behaviour)
gradient      nearest value + local dip carried outwards, damped with distance (no flat shelves)
plane         global least-squares plane through the defined nodes
trend2        global 2nd-order polynomial (bowl / dome) trend - use with care far from data
decay         edge value blending into the regional plane over ``length`` metres
min_curvature smooth minimum-curvature continuation (tension controls how fast it flattens)
constant      a fixed depth
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .surface import Geometry, fill_nan_nearest

MODES = ["nearest", "gradient", "decay", "plane", "trend2", "min_curvature", "constant", "none"]
MODE_INFO = {
    "nearest": "Flat extension of the edge value. Safe, but creates horizontal shelves.",
    "gradient": "Continues the local dip outwards and damps it with distance. Natural flank extension.",
    "decay": "Edge value blends smoothly into the regional plane. Good when the model area is much larger than the map.",
    "plane": "Global best-fit plane. Predictable, ignores local structure.",
    "trend2": "Global 2nd-order trend. Can run away far from data - check the result.",
    "min_curvature": "Smooth continuation by minimum curvature with tension. Best for small gaps and holes.",
    "constant": "A fixed depth value everywhere undefined.",
    "none": "Leave undefined nodes as NaN.",
}


def _coords(geom):
    X, Y = geom.coords()
    return X, Y


def _fit_poly(X, Y, z, order):
    m = np.isfinite(z)
    cx, cy = X[m].mean(), Y[m].mean()
    sc = max(np.ptp(X[m]), np.ptp(Y[m]), 1.0)

    def terms(x, y):
        x, y = (x - cx) / sc, (y - cy) / sc
        c = [np.ones_like(x), x, y]
        if order >= 2:
            c += [x * x, x * y, y * y]
        return np.stack(c, -1)
    idx = np.flatnonzero(m.ravel())
    if len(idx) > 20000:
        idx = idx[:: len(idx) // 20000 + 1]
    A = terms(X.ravel()[idx], Y.ravel()[idx])
    c, *_ = np.linalg.lstsq(A, z.ravel()[idx], rcond=None)
    return terms(X, Y) @ c


def fill_undefined(z, geom: Geometry, mode="nearest", length=0.0, value=0.0, tension=0.0, damping=None):
    """Return ``z`` with NaN nodes filled according to ``mode``.

    length : decay / damping length in metres (default: 25 % of the model width)
    """
    z = np.asarray(z, float)
    nan = np.isnan(z)
    if mode == "none" or not nan.any():
        return z.copy()
    if nan.all():
        return np.full_like(z, float(value) if mode == "constant" else 0.0)
    if mode == "constant":
        return np.where(nan, float(value), z)
    X, Y = _coords(geom)
    ext = max(np.ptp(X), np.ptp(Y))
    L = float(length) if length and length > 0 else 0.25 * ext
    if mode == "nearest":
        return fill_nan_nearest(z)
    if mode in ("plane", "trend2"):
        return np.where(nan, _fit_poly(X, Y, z, 1 if mode == "plane" else 2), z)
    dist, idx = ndimage.distance_transform_edt(nan, sampling=(geom.yinc, geom.xinc), return_indices=True)
    near = z[tuple(idx)]
    if mode == "decay":
        plane = _fit_poly(X, Y, z, 1)
        # shift the plane to match the edge so the blend is continuous at the boundary
        off = near - plane[tuple(idx)]
        w = np.exp(-dist / L)
        return np.where(nan, plane + off * w, z)
    if mode == "gradient":
        zs = ndimage.gaussian_filter(fill_nan_nearest(z), 2.0)
        gy, gx = np.gradient(zs, geom.yinc, geom.xinc)
        gxn, gyn = gx[tuple(idx)], gy[tuple(idx)]
        dx = X - X[tuple(idx)]
        dy = Y - Y[tuple(idx)]
        damp = L * (1 - np.exp(-dist / L)) / np.maximum(dist, 1e-9)
        return np.where(nan, near + (gxn * dx + gyn * dy) * damp, z)
    if mode == "min_curvature":
        from .interp import grid_points
        m = ~nan
        # use a thin band of defined nodes next to the hole(s) plus a sparse interior sample
        edge = m & ndimage.binary_dilation(nan, iterations=2)
        interior = m & ~edge
        pts_i = np.column_stack([X[edge], Y[edge], z[edge]])
        sel = np.flatnonzero(interior.ravel())
        if len(sel) > 1500:
            sel = sel[:: len(sel) // 1500 + 1]
        pts_s = np.column_stack([X.ravel()[sel], Y.ravel()[sel], z.ravel()[sel]])
        pts = np.vstack([pts_i, pts_s])
        if len(pts) > 6000:
            pts = pts[:: len(pts) // 6000 + 1]
        g = grid_points(pts, geom, "min_curvature", tension=float(tension)).z
        lo, hi = np.nanmin(z), np.nanmax(z)
        g = np.clip(g, lo - 0.5 * (hi - lo), hi + 0.5 * (hi - lo))    # guard against overshoot in big holes
        return np.where(nan, g, z)
    raise ValueError(f"Unknown fill mode '{mode}'")
