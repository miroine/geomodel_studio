"""Scattered data / digitized contours -> regular grid.

Methods
-------
min_curvature : sparse biharmonic (+ tension) least squares, honours data through bilinear
                observation operators (Petrel "convergent interpolation"-like, RMS "minimum curvature").
rbf           : thin-plate spline radial basis functions (optional smoothing).
idw           : inverse distance weighting (k nearest).
linear        : Delaunay linear with nearest fill (robust, no overshoot).
cubic         : Clough-Tocher C1 cubic on a Delaunay mesh (smooth, honours data, nearest fill outside hull).
kriging       : ordinary kriging, local neighbourhood, spherical/exponential/gaussian variogram,
                optional polynomial drift removal; also returns the kriging std-dev (uncertainty).
moving_average: Gaussian-kernel weighted mean (smoothing, does not honour data exactly).
local_poly    : LOESS-style local quadratic/linear regression on the k nearest points.
nearest       : Voronoi / nearest-neighbour (blocky, for categorical-like or quick looks).
trend_residual: global polynomial trend + any of the above on the residuals (regional dip honoured).
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree
from scipy.interpolate import RBFInterpolator, griddata
from scipy import ndimage

from .surface import Geometry, Surface

METHODS = ["min_curvature", "rbf", "idw", "linear", "cubic", "kriging", "moving_average",
           "local_poly", "nearest", "trend_residual"]
METHOD_INFO = {
    "min_curvature": "Smoothest surface through the data (tension 0 = classic, 1 = membrane). Best default for structure.",
    "rbf": "Thin-plate spline; exact, smooth, can overshoot between sparse points.",
    "idw": "Inverse distance; bulls-eyes around points, never exceeds the data range.",
    "linear": "Delaunay triangles; no overshoot, visible facets.",
    "cubic": "Clough-Tocher cubic; smooth like min-curvature but local to the triangulation.",
    "kriging": "Ordinary kriging with a variogram; statistically optimal, gives an uncertainty map.",
    "moving_average": "Gaussian kernel mean; smooths noisy picks, does not honour points exactly.",
    "local_poly": "Local regression (LOESS); follows dip well, smooths noise.",
    "nearest": "Nearest point value; blocky, mainly for quick looks.",
    "trend_residual": "Remove a regional polynomial trend, grid the residual, add trend back (good for dipping data).",
}
VARIOGRAMS = ["spherical", "exponential", "gaussian"]
RESIDUAL_METHODS = ["min_curvature", "rbf", "idw", "linear", "cubic", "kriging", "moving_average", "local_poly"]


def dedupe(points: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Average duplicate (x, y) positions."""
    p = np.asarray(points, float)
    p = p[np.isfinite(p).all(axis=1)]
    if len(p) == 0:
        return p
    key = np.round(p[:, :2] / max(tol, 1e-9)).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).ravel()
    n = inv.max() + 1
    out = np.zeros((n, 3))
    cnt = np.bincount(inv, minlength=n)
    for c in range(3):
        out[:, c] = np.bincount(inv, weights=p[:, c], minlength=n) / cnt
    return out


def densify_polyline(xy: np.ndarray, step: float) -> np.ndarray:
    """Insert vertices so that no segment is longer than ``step``."""
    xy = np.asarray(xy, float)
    if len(xy) < 2 or step <= 0:
        return xy
    out = [xy[0]]
    for a, b in zip(xy[:-1], xy[1:]):
        d = np.hypot(*(b - a))
        n = max(int(np.ceil(d / step)), 1)
        for t in np.linspace(0, 1, n + 1)[1:]:
            out.append(a + (b - a) * t)
    return np.array(out)


def contours_to_points(contours: list, step: float) -> np.ndarray:
    """contours = [{'z': float, 'pts': [[x, y], ...]}, ...]  ->  Nx3 densified points."""
    rows = []
    for c in contours:
        pts = np.asarray(c.get("pts", []), float)
        if len(pts) == 0:
            continue
        pts = densify_polyline(pts, step) if len(pts) > 1 else pts
        rows.append(np.column_stack([pts, np.full(len(pts), float(c["z"]))]))
    return np.vstack(rows) if rows else np.zeros((0, 3))


# ---------------------------------------------------------------------------
def _laplacian_1d(n: int) -> sp.csr_matrix:
    if n < 3:
        return sp.csr_matrix((n, n))
    main = np.full(n, -2.0)
    lo = np.ones(n - 1)
    up = np.ones(n - 1)
    D = sp.diags([lo, main, up], [-1, 0, 1], format="lil")
    D[0, 1] = 2.0           # mirror (Neumann) boundaries
    D[n - 1, n - 2] = 2.0
    return D.tocsr()


def _bilinear_operator(fi, fj, ncol, nrow) -> sp.csr_matrix:
    fi = np.clip(fi, 0, ncol - 1 - 1e-9)
    fj = np.clip(fj, 0, nrow - 1 - 1e-9)
    i0 = np.floor(fi).astype(int)
    j0 = np.floor(fj).astype(int)
    tx = fi - i0
    ty = fj - j0
    rows = np.repeat(np.arange(len(fi)), 4)
    cols = np.column_stack([j0 * ncol + i0, j0 * ncol + i0 + 1,
                            (j0 + 1) * ncol + i0, (j0 + 1) * ncol + i0 + 1]).ravel()
    w = np.column_stack([(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty]).ravel()
    return sp.csr_matrix((w, (rows, cols)), shape=(len(fi), ncol * nrow))


def min_curvature(points: np.ndarray, geom: Geometry, tension: float = 0.0, smoothing: float = 0.0,
                  max_nodes: int = 22000) -> np.ndarray:
    """Minimum-curvature gridding with optional tension (0 = pure min curvature, 1 = membrane).

    Solves  min  (1-T)|L z|^2 + T|grad z|^2 + w |B z - d|^2   (cell-unit stencil)
    ``smoothing`` in [0, 1] relaxes the data fit (0 = honour data almost exactly).
    """
    fac = 1
    while (geom.ncol // fac) * (geom.nrow // fac) > max_nodes:
        fac += 1
    if fac > 1:  # solve on a coarser lattice then interpolate
        cg = Geometry(geom.xori, geom.yori, geom.xinc * fac, geom.yinc * fac,
                      (geom.ncol - 1) // fac + 1, (geom.nrow - 1) // fac + 1, geom.rotation)
        zc = min_curvature(points, cg, tension, smoothing, max_nodes=10 ** 9)
        X, Y = geom.coords()
        fi, fj = cg.to_index(X, Y)
        return ndimage.map_coordinates(zc, [fj, fi], order=3, mode="nearest")

    ncol, nrow = geom.ncol, geom.nrow
    n = ncol * nrow
    fi, fj = geom.to_index(points[:, 0], points[:, 1])
    ok = (fi > -1.5) & (fi < ncol + 0.5) & (fj > -1.5) & (fj < nrow + 0.5)
    pts = points[ok]
    fi, fj = fi[ok], fj[ok]
    if len(pts) == 0:
        raise ValueError("No data points fall inside the grid.")
    d = pts[:, 2]
    zmean = d.mean()
    B = _bilinear_operator(fi, fj, ncol, nrow)
    # the (rotation-free) anisotropy is ignored: stencil in cell units
    Lx = _laplacian_1d(ncol)
    Ly = _laplacian_1d(nrow)
    L = sp.kron(sp.identity(nrow), Lx) + sp.kron(Ly, sp.identity(ncol))
    G = -(L + L.T) * 0.5            # symmetric positive semidefinite gradient-energy operator
    K = (1 - tension) * (L.T @ L) + tension * G
    w = 10.0 ** (4.0 - 4.0 * float(np.clip(smoothing, 0, 1)))
    A = (K + w * (B.T @ B) + 1e-6 * sp.identity(n)).tocsc()
    b = w * (B.T @ (d - zmean)) + 0.0
    z = spsolve(A, b) + zmean
    return np.asarray(z).reshape(nrow, ncol)


def grid_rbf(points, geom, smoothing=0.0, kernel="thin_plate_spline"):
    X, Y = geom.coords()
    c = points[:, :2].mean(axis=0)
    s = max(np.ptp(points[:, 0]), np.ptp(points[:, 1]), 1.0)
    P = (points[:, :2] - c) / s
    nb = 64 if len(points) > 1500 else None
    rbf = RBFInterpolator(P, points[:, 2], kernel=kernel, smoothing=smoothing, neighbors=nb)
    Q = (np.column_stack([X.ravel(), Y.ravel()]) - c) / s
    out = np.empty(len(Q))
    for k in range(0, len(Q), 20000):
        out[k:k + 20000] = rbf(Q[k:k + 20000])
    return out.reshape(geom.shape)


def grid_idw(points, geom, k=12, power=2.0):
    X, Y = geom.coords()
    tree = cKDTree(points[:, :2])
    kk = min(k, len(points))
    dist, idx = tree.query(np.column_stack([X.ravel(), Y.ravel()]), k=kk)
    if kk == 1:
        dist, idx = dist[:, None], idx[:, None]
    w = 1.0 / np.maximum(dist, 1e-9) ** power
    z = (w * points[idx, 2]).sum(axis=1) / w.sum(axis=1)
    return z.reshape(geom.shape)


def grid_linear(points, geom):
    X, Y = geom.coords()
    z = griddata(points[:, :2], points[:, 2], (X, Y), method="linear")
    if np.isnan(z).any():
        zn = griddata(points[:, :2], points[:, 2], (X, Y), method="nearest")
        z = np.where(np.isnan(z), zn, z)
    return z


# ---------------------------------------------------------------------------
# Additional algorithms (v3)
# ---------------------------------------------------------------------------
def _node_xy(geom: Geometry):
    X, Y = geom.coords()
    return np.column_stack([X.ravel(), Y.ravel()])


def grid_cubic(points, geom):
    X, Y = geom.coords()
    z = griddata(points[:, :2], points[:, 2], (X, Y), method="cubic")
    if np.isnan(z).any():
        zn = griddata(points[:, :2], points[:, 2], (X, Y), method="nearest")
        z = np.where(np.isnan(z), zn, z)
    return z


def grid_nearest(points, geom):
    _, i = cKDTree(points[:, :2]).query(_node_xy(geom))
    return points[i, 2].reshape(geom.shape)


def grid_moving_average(points, geom, radius=None, k=48):
    xy = _node_xy(geom)
    tree = cKDTree(points[:, :2])
    kk = min(k, len(points))
    if radius is None or radius <= 0:
        d1, _ = tree.query(points[:, :2], k=min(2, len(points)))
        radius = 2.5 * float(np.median(d1[:, -1])) if len(points) > 1 else 1.0
    d, i = tree.query(xy, k=kk)
    d = d.reshape(len(xy), -1)
    i = i.reshape(len(xy), -1)
    w = np.exp(-0.5 * (d / radius) ** 2) + 1e-12
    z = (w * points[i, 2]).sum(1) / w.sum(1)
    return z.reshape(geom.shape)


def grid_local_poly(points, geom, k=24, order=2):
    """Weighted local polynomial regression (tricube weights), batched."""
    xy = _node_xy(geom)
    tree = cKDTree(points[:, :2])
    nb = 6 if order >= 2 else 3
    kk = int(min(max(k, nb + 2), len(points)))
    out = np.empty(len(xy))
    for a in range(0, len(xy), 4000):
        q = xy[a:a + 4000]
        d, i = tree.query(q, k=kk)
        d = d.reshape(len(q), -1)
        i = i.reshape(len(q), -1)
        h = d[:, -1:] * 1.0001 + 1e-9
        w = (1 - (d / h) ** 3) ** 3 + 1e-9
        dx = (points[i, 0] - q[:, :1]) / h
        dy = (points[i, 1] - q[:, 1:2]) / h
        cols = [np.ones_like(dx), dx, dy]
        if nb == 6:
            cols += [dx * dx, dx * dy, dy * dy]
        A = np.stack(cols, axis=2)                       # (n, k, nb)
        Aw = A * w[:, :, None]
        M = np.einsum("nki,nkj->nij", Aw, A) + 1e-8 * np.eye(nb)
        b = np.einsum("nki,nk->ni", Aw, points[i, 2])
        try:
            c = np.linalg.solve(M, b[:, :, None])[:, :, 0]
            out[a:a + 4000] = c[:, 0]
        except np.linalg.LinAlgError:
            out[a:a + 4000] = (w * points[i, 2]).sum(1) / w.sum(1)
    return out.reshape(geom.shape)


def _vario(h, model, rng, sill, nugget):
    r = np.minimum(h / max(rng, 1e-9), 50.0)
    if model == "spherical":
        g = np.where(h < rng, 1.5 * r - 0.5 * r ** 3, 1.0)
    elif model == "exponential":
        g = 1.0 - np.exp(-3.0 * r)
    elif model == "gaussian":
        g = 1.0 - np.exp(-3.0 * r ** 2)
    else:
        raise ValueError(f"Unknown variogram {model}")
    return np.where(h > 0, nugget + (sill - nugget) * g, 0.0)


def fit_variogram_range(points, model="spherical"):
    """Pick a practical range: ~40 % of the data extent, but never below 3x the typical spacing."""
    ext = max(np.ptp(points[:, 0]), np.ptp(points[:, 1]), 1.0)
    d1, _ = cKDTree(points[:, :2]).query(points[:, :2], k=min(2, len(points)))
    sp_ = float(np.median(d1[:, -1])) if len(points) > 1 else ext / 10
    return max(0.4 * ext, 3 * sp_)


def krige(points, geom, model="spherical", vrange=None, nugget_frac=0.0, k=16, drift=0, return_var=False):
    """Ordinary kriging with a moving neighbourhood. ``drift`` = polynomial order removed first (0/1/2)."""
    P = points[:, :3].astype(float)
    trend = None
    if drift:
        P, trend = _remove_trend(P, drift)
    var = np.var(P[:, 2]) + 1e-12
    rng = vrange or fit_variogram_range(P)
    nug = nugget_frac * var
    tree = cKDTree(P[:, :2])
    xy = _node_xy(geom)
    kk = int(min(k, len(P)))
    z = np.empty(len(xy))
    ev = np.empty(len(xy))
    for a in range(0, len(xy), 3000):
        q = xy[a:a + 3000]
        d, i = tree.query(q, k=kk)
        d = d.reshape(len(q), -1)
        i = i.reshape(len(q), -1)
        n = len(q)
        pxy = P[i, :2]                                   # (n, kk, 2)
        H = np.linalg.norm(pxy[:, :, None, :] - pxy[:, None, :, :], axis=3)
        K = np.zeros((n, kk + 1, kk + 1))
        K[:, :kk, :kk] = var - _vario(H, model, rng, var, nug)
        K[:, :kk, :kk] += np.eye(kk) * 1e-9 * var
        K[:, :kk, kk] = 1.0
        K[:, kk, :kk] = 1.0
        rhs = np.ones((n, kk + 1))
        rhs[:, :kk] = var - _vario(d, model, rng, var, nug)
        try:
            sol = np.linalg.solve(K, rhs[:, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(K[0], rhs[0], rcond=None)[0][None, :].repeat(n, 0)
        z[a:a + n] = (sol[:, :kk] * P[i, 2]).sum(1)
        ev[a:a + n] = np.sqrt(np.maximum(var - (sol * rhs).sum(1) + 0.0, 0.0))
    z = z.reshape(geom.shape)
    if trend is not None:
        X, Y = geom.coords()
        z = z + _eval_trend(trend, X, Y)
    return (z, ev.reshape(geom.shape)) if return_var else z


def _poly_terms(x, y, order):
    cols = [np.ones_like(x), x, y]
    if order >= 2:
        cols += [x * x, x * y, y * y]
    return np.stack(cols, axis=-1)


def _remove_trend(P, order):
    cx, cy = P[:, 0].mean(), P[:, 1].mean()
    sc = max(np.ptp(P[:, 0]), np.ptp(P[:, 1]), 1.0)
    nb = 6 if order >= 2 else 3
    if len(P) < nb + 1:
        order, nb = 1, 3
    A = _poly_terms((P[:, 0] - cx) / sc, (P[:, 1] - cy) / sc, order)
    c, *_ = np.linalg.lstsq(A, P[:, 2], rcond=None)
    R = P.copy()
    R[:, 2] = P[:, 2] - A @ c
    return R, dict(c=c, cx=cx, cy=cy, sc=sc, order=order)


def _eval_trend(t, X, Y):
    return _poly_terms((X - t["cx"]) / t["sc"], (Y - t["cy"]) / t["sc"], t["order"]) @ t["c"]


def grid_trend_residual(points, geom, trend_order=1, residual_method="min_curvature", **kw):
    R, t = _remove_trend(points[:, :3].astype(float), int(trend_order))
    res = grid_points(R, geom, residual_method, name="res", **kw).z
    X, Y = geom.coords()
    return res + _eval_trend(t, X, Y)


def mask_far_from_data(z, points, geom, max_dist):
    X, Y = geom.coords()
    d, _ = cKDTree(points[:, :2]).query(np.column_stack([X.ravel(), Y.ravel()]))
    return np.where(d.reshape(geom.shape) > max_dist, np.nan, z)


def grid_points(points, geom: Geometry, method="min_curvature", name="Gridded", tension=0.0,
                smoothing=0.0, max_distance=None, **kw) -> Surface:
    """Grid Nx3 (x, y, z) points on ``geom`` and return a Surface."""
    pts = dedupe(np.asarray(points, float), tol=max(min(geom.xinc, geom.yinc) * 1e-3, 1e-6))
    if len(pts) < 3 and method != "idw":
        raise ValueError("At least 3 distinct points are required.")
    if method == "min_curvature":
        z = min_curvature(pts, geom, tension=tension, smoothing=smoothing)
    elif method == "rbf":
        z = grid_rbf(pts, geom, smoothing=smoothing * 5.0 * 1e-3)
    elif method == "idw":
        z = grid_idw(pts, geom, k=int(kw.get("k", 12)), power=float(kw.get("power", 2.0)))
    elif method == "linear":
        z = grid_linear(pts, geom)
    elif method == "cubic":
        z = grid_cubic(pts, geom)
    elif method == "nearest":
        z = grid_nearest(pts, geom)
    elif method == "moving_average":
        z = grid_moving_average(pts, geom, radius=kw.get("radius"), k=int(kw.get("k", 48)))
    elif method == "local_poly":
        z = grid_local_poly(pts, geom, k=int(kw.get("k", 24)), order=int(kw.get("order", 2)))
    elif method == "kriging":
        z = krige(pts, geom, model=kw.get("variogram", "spherical"), vrange=kw.get("vrange") or None,
                  nugget_frac=float(kw.get("nugget", 0.0)), k=int(kw.get("k", 16)), drift=int(kw.get("drift", 0)))
    elif method == "trend_residual":
        z = grid_trend_residual(pts, geom, trend_order=int(kw.get("trend_order", 1)),
                                residual_method=kw.get("residual_method", "min_curvature"),
                                tension=tension, smoothing=smoothing)
    else:
        raise ValueError(f"Unknown method {method}")
    if max_distance:
        z = mask_far_from_data(z, pts, geom, max_distance)
    return Surface(name, geom, z, source=f"gridded:{method}:{len(pts)}pts")
