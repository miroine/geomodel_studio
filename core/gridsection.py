"""Property cross-sections through the 3D grid: row / column sections (exact cell quads) and fence sections along a
digitised polyline (one ribbon per grid column crossed).  Returns plain arrays that ``ui.specs.property_section`` draws."""
from __future__ import annotations

from typing import Dict, List, Optional
import numpy as np

from . import fence as fz


class SectionError(Exception):
    pass


def _quads(grid, axis: str, index: int):
    """Cell quads of a row (axis 'j') or column (axis 'i') section: x (n,4), z (n,4), k, c (position along the section)."""
    if axis == "j":
        n, coord = grid.ni, grid.xs
        sl = lambda t: grid.zc[:, t, index].mean(axis=1)            # (nk, ni, 2) -> mean over j side
    else:
        n, coord = grid.nj, grid.ys
        sl = lambda t: grid.zc[:, t, :, :, index].mean(axis=3)      # (nk, nj, 2)
    top, bot = sl(0), sl(1)                                          # (nk, n, 2) : [..., a]
    nk = grid.nk
    K, C = np.meshgrid(np.arange(nk), np.arange(n), indexing="ij")
    xa, xb = coord[:-1][C], coord[1:][C]
    x = np.stack([xa, xb, xb, xa], axis=-1)
    z = np.stack([top[K, C, 0], top[K, C, 1], bot[K, C, 1], bot[K, C, 0]], axis=-1)
    return x.reshape(-1, 4), z.reshape(-1, 4), K.ravel(), C.ravel()


def grid_line_section(grid, values: np.ndarray, axis: str, index: int, owc=None, goc=None) -> dict:
    """Row / column section of one property.  ``owc`` / ``goc`` are optional (nj, ni) contact maps for overlay lines."""
    if axis not in ("i", "j"):
        raise SectionError("axis must be 'i' or 'j'")
    lim = grid.nj if axis == "j" else grid.ni
    if not 0 <= index < lim:
        raise SectionError(f"index out of range 0..{lim - 1}")
    x, z, k, c = _quads(grid, axis, index)
    j_i = (np.full_like(c, index), c) if axis == "j" else (c, np.full_like(c, index))
    act = grid.actnum[k, j_i[0], j_i[1]] > 0
    v = values[k, j_i[0], j_i[1]].astype(float)
    keep = act & np.isfinite(v) & np.all(np.isfinite(z), axis=1)
    coord = grid.xs if axis == "j" else grid.ys
    out = dict(x=x[keep], z=z[keep], v=v[keep], k=k[keep], layer_zone=grid.layer_zone[k[keep]], coord_label="Easting" if axis == "j" else "Northing",
               zmin=float(np.nanmin(z[act])) if act.any() else 0.0, zmax=float(np.nanmax(z[act])) if act.any() else 1.0, faults=[], contacts={})
    out["cell_ids"] = ((k * grid.nj + j_i[0]) * grid.ni + j_i[1])[keep]
    for name, cm in (("OWC", owc), ("GOC", goc)):
        if cm is None:
            continue
        row = cm[index, :] if axis == "j" else cm[:, index]
        if np.isfinite(row).any():
            out["contacts"][name] = dict(x0=coord[:-1], x1=coord[1:], z=np.asarray(row, float))
    return out


def _to_local(grid, X, Y):
    if not grid.rotated:
        return np.asarray(X, float), np.asarray(Y, float)
    c, s = np.cos(np.deg2rad(grid.angle)), np.sin(np.deg2rad(grid.angle))
    dx, dy = np.asarray(X, float) - grid.origin[0], np.asarray(Y, float) - grid.origin[1]
    return dx * c + dy * s, -dx * s + dy * c


def fence_columns(grid, pts, spacing: Optional[float] = None) -> dict:
    """Intersect an open polyline with local grid-column boundaries; spacing is retained for compatibility."""
    pts = np.asarray(pts, float)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 2 or not np.isfinite(pts).all():
        raise SectionError("A fence needs at least two finite XY points.")
    L = fz.polyline_length(pts)
    if L <= 0:
        raise SectionError("The fence has zero length.")
    u, v = _to_local(grid, pts[:, 0], pts[:, 1])
    segs = []
    offset = 0.
    for n, length in enumerate(np.linalg.norm(np.diff(pts, axis=0), axis=1)):
        if length == 0:
            continue
        du, dv = u[n + 1] - u[n], v[n + 1] - v[n]
        cuts = [np.array([0., 1.])]
        if du != 0:
            cuts.append((grid.xs - u[n]) / du)
        if dv != 0:
            cuts.append((grid.ys - v[n]) / dv)
        t = np.unique(np.clip(np.concatenate(cuts), 0., 1.))
        for a, b in zip(t[:-1], t[1:]):
            if b - a < 1e-12:
                continue
            mid = (a + b) / 2
            um, vm = u[n] + mid * du, v[n] + mid * dv
            if not (grid.xs[0] <= um <= grid.xs[-1] and grid.ys[0] <= vm <= grid.ys[-1]):
                continue
            i = min(np.searchsorted(grid.xs, um, side="right") - 1, grid.ni - 1)
            j = min(np.searchsorted(grid.ys, vm, side="right") - 1, grid.nj - 1)
            segs.append([offset + a * length, offset + b * length, int(i), int(j)])
        offset += length
        if len(segs) > 20000:
            raise SectionError("Fence crosses too many grid columns; simplify the path.")
    if not segs:
        raise SectionError("The fence is outside the grid.")
    return dict(segs=np.array(segs, float), length=L)


def fence_property_section(grid, values: np.ndarray, pts, faults=None, owc=None, goc=None, spacing=None) -> dict:
    fc = fence_columns(grid, pts, spacing)
    S = fc["segs"]
    d0, d1, si, sj = S[:, 0], S[:, 1], S[:, 2].astype(int), S[:, 3].astype(int)
    nk = grid.nk
    top = grid.zc[:, 0].mean(axis=(2, 4))      # (nk, nj, ni)
    bot = grid.zc[:, 1].mean(axis=(2, 4))
    K = np.arange(nk)[:, None]
    zt, zb = top[K, sj[None], si[None]], bot[K, sj[None], si[None]]   # (nk, S)
    v = values[K, sj[None], si[None]].astype(float)
    act = grid.actnum[K, sj[None], si[None]] > 0
    keep = (act & np.isfinite(v) & np.isfinite(zt) & np.isfinite(zb)).ravel()
    X0, X1 = np.broadcast_to(d0, zt.shape).ravel(), np.broadcast_to(d1, zt.shape).ravel()
    x = np.stack([X0, X1, X1, X0], axis=-1)[keep]
    z = np.stack([zt.ravel(), zt.ravel(), zb.ravel(), zb.ravel()], axis=-1)[keep]
    kk = np.broadcast_to(K, zt.shape).ravel()[keep]
    out = dict(x=x, z=z, v=v.ravel()[keep], k=kk, layer_zone=grid.layer_zone[kk], coord_label="Distance along fence", length=fc["length"],
               zmin=float(np.nanmin(z)) if len(z) else 0.0, zmax=float(np.nanmax(z)) if len(z) else 1.0, contacts={}, faults=[])
    ii = np.broadcast_to(si[None], zt.shape).ravel()[keep]
    jj = np.broadcast_to(sj[None], zt.shape).ravel()[keep]
    out["cell_ids"] = (kk * grid.nj + jj) * grid.ni + ii
    out["i"], out["j"] = ii, jj
    path = np.asarray(pts, float)
    distance = np.concatenate(([0.], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))))
    out["world_x"] = np.interp(x, distance, path[:, 0])
    out["world_y"] = np.interp(x, distance, path[:, 1])
    if faults:
        out["faults"] = fz.fault_crossings(np.asarray(pts, float), list(faults.values()) if isinstance(faults, dict) else list(faults))
    for name, cm in (("OWC", owc), ("GOC", goc)):
        if cm is None:
            continue
        cm = np.asarray(cm, float)
        if cm.shape == grid.actnum.shape:
            depth = cm[kk, jj, ii]
            show = np.isfinite(depth) & (depth >= z.min(axis=1)) & (depth <= z.max(axis=1))
            out["contacts"][name] = dict(x0=x[show, 0], x1=x[show, 1], z=depth[show])
        elif cm.shape == (grid.nj, grid.ni):
            if np.isfinite(cm[sj, si]).any():
                out["contacts"][name] = dict(x0=d0, x1=d1, z=cm[sj, si])
        else:
            raise SectionError("Contact overlay must match the grid map or cube shape.")
    return out


# ---------------------------------------------------------------------------------------------
STOPS = ["#440154", "#3B528B", "#21908C", "#5DC863", "#FDE725"]


def _hex(t: float, stops=STOPS) -> str:
    t = float(np.clip(t, 0, 1)) * (len(stops) - 1)
    a = int(min(np.floor(t), len(stops) - 2))
    f = t - a
    ca = [int(stops[a][i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(stops[a + 1][i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(int(round(p + (q - p) * f)) for p, q in zip(ca, cb))


def colour_buckets(v: np.ndarray, discrete=False, nb=32, vmin=None, vmax=None, stops=STOPS):
    """-> (bin index per value, list of (label_lo, label_hi, colour), vmin, vmax).  Continuous: percentile 1-99 clipped linear bins."""
    v = np.asarray(v, float)
    if discrete:
        u = np.unique(v[np.isfinite(v)])
        idx = np.searchsorted(u, v)
        cols = [_hex(t, stops) for t in (np.linspace(0, 1, len(u)) if len(u) > 1 else [0.5])]
        return idx, [(x, x, c) for x, c in zip(u, cols)], float(u.min()) if len(u) else 0.0, float(u.max()) if len(u) else 1.0
    if vmin is None or vmax is None:
        lo, hi = (np.nanpercentile(v, [1, 99]) if v.size else (0.0, 1.0))
        vmin = lo if vmin is None else vmin
        vmax = hi if vmax is None else vmax
    if vmax <= vmin:
        vmax = vmin + 1e-9
    edges = np.linspace(vmin, vmax, nb + 1)
    idx = np.clip(np.floor((v - vmin) / (vmax - vmin) * nb).astype(int), 0, nb - 1)
    return idx, [(edges[i], edges[i + 1], _hex((i + 0.5) / nb, stops)) for i in range(nb)], float(vmin), float(vmax)
