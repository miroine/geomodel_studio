"""Regular-grid surfaces (depth maps).

Conventions
-----------
* Depth is positive downward (TVDSS, metres). Larger z = deeper.
* ``Surface.z`` has shape ``(nrow, ncol)``: row = Y direction (j), column = X direction (i).
  NaN marks undefined nodes.  (xtgeo uses ``(ncol, nrow)``; conversion happens only in io_surfaces.)
* Geometry may be rotated (counter-clockwise, degrees) so imported RMS/IRAP maps resample correctly.
  The model lattice itself is always unrotated.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np
from scipy import ndimage


@dataclass
class Geometry:
    xori: float
    yori: float
    xinc: float
    yinc: float
    ncol: int
    nrow: int
    rotation: float = 0.0

    # ---- coordinates -------------------------------------------------
    def coords(self):
        """World coordinates of all nodes, each shape (nrow, ncol)."""
        i = np.arange(self.ncol) * self.xinc
        j = np.arange(self.nrow) * self.yinc
        I, J = np.meshgrid(i, j)
        a = np.deg2rad(self.rotation)
        X = self.xori + I * np.cos(a) - J * np.sin(a)
        Y = self.yori + I * np.sin(a) + J * np.cos(a)
        return X, Y

    @property
    def xs(self):
        return self.xori + np.arange(self.ncol) * self.xinc

    @property
    def ys(self):
        return self.yori + np.arange(self.nrow) * self.yinc

    def to_index(self, X, Y):
        """Fractional (col, row) index of world coordinates."""
        dx = np.asarray(X, float) - self.xori
        dy = np.asarray(Y, float) - self.yori
        a = np.deg2rad(self.rotation)
        u = dx * np.cos(a) + dy * np.sin(a)
        v = -dx * np.sin(a) + dy * np.cos(a)
        return u / self.xinc, v / self.yinc

    def bounds(self):
        X, Y = self.coords()
        return float(X.min()), float(X.max()), float(Y.min()), float(Y.max())

    @property
    def shape(self):
        return (self.nrow, self.ncol)

    def same_lattice(self, other: "Geometry", tol=1e-6) -> bool:
        return (self.ncol == other.ncol and self.nrow == other.nrow
                and abs(self.xori - other.xori) < tol and abs(self.yori - other.yori) < tol
                and abs(self.xinc - other.xinc) < tol and abs(self.yinc - other.yinc) < tol
                and abs(self.rotation - other.rotation) < tol)

    def to_dict(self):
        return {k: (int(v) if k in ("ncol", "nrow") else float(v)) for k, v in asdict(self).items()}

    @staticmethod
    def from_dict(d):
        return Geometry(float(d["xori"]), float(d["yori"]), float(d["xinc"]), float(d["yinc"]),
                        int(d["ncol"]), int(d["nrow"]), float(d.get("rotation", 0.0)))

    @staticmethod
    def from_bounds(xmin, xmax, ymin, ymax, dx, dy=None):
        dy = dy or dx
        ncol = int(round((xmax - xmin) / dx)) + 1
        nrow = int(round((ymax - ymin) / dy)) + 1
        return Geometry(xmin, ymin, dx, dy, ncol, nrow, 0.0)


def surface_area_values(geom: Geometry):
    """Return north-up bounds and spacing covering the entire surface lattice."""
    values = (geom.xori, geom.yori, geom.xinc, geom.yinc, geom.rotation)
    if not all(math.isfinite(v) for v in values) or geom.xinc <= 0 or geom.yinc <= 0:
        raise ValueError("Surface coordinates and positive spacing must be finite.")
    if geom.ncol < 2 or geom.nrow < 2:
        raise ValueError("The surface must have at least two rows and two columns.")
    a = math.radians(geom.rotation)
    ux, uy = (geom.ncol - 1) * geom.xinc * math.cos(a), (geom.ncol - 1) * geom.xinc * math.sin(a)
    vx, vy = -(geom.nrow - 1) * geom.yinc * math.sin(a), (geom.nrow - 1) * geom.yinc * math.cos(a)
    xmin = geom.xori + min(0, ux) + min(0, vx)
    xmax = geom.xori + max(0, ux) + max(0, vx)
    ymin = geom.yori + min(0, uy) + min(0, vy)
    ymax = geom.yori + max(0, uy) + max(0, vy)
    width, height = xmax - xmin, ymax - ymin
    if not all(math.isfinite(v) for v in (xmin, xmax, ymin, ymax)) or width <= 0 or height <= 0:
        raise ValueError("The surface must have finite, non-zero X and Y extents.")
    nx = max(1, math.ceil(width / geom.xinc))
    ny = max(1, math.ceil(height / geom.yinc))
    dx, dy = width / nx, height / ny
    if dx < 1e-12 or dy < 1e-12:
        raise ValueError("Surface spacing is too small for the model area controls.")
    return xmin, xmax, ymin, ymax, dx, dy


class Surface:
    def __init__(self, name: str, geom: Geometry, z: np.ndarray, source: str = ""):
        self.name = name
        self.geom = geom
        z = np.asarray(z, dtype=float)
        if z.shape != geom.shape:
            raise ValueError(f"z shape {z.shape} does not match geometry {geom.shape}")
        self.z = z
        self.source = source

    # ---- sampling ------------------------------------------------------
    def sample(self, X, Y, order: int = 1, extrapolate: bool = False) -> np.ndarray:
        """Interpolate at arbitrary world coordinates (bilinear by default)."""
        X = np.asarray(X, float)
        Y = np.asarray(Y, float)
        fi, fj = self.geom.to_index(X, Y)
        z = self.z
        if order > 1 and np.isnan(z).any():
            order = 1
        out = ndimage.map_coordinates(z, [fj.ravel(), fi.ravel()], order=order, mode="nearest",
                                      cval=np.nan, prefilter=(order > 1))
        out = out.reshape(X.shape)
        if not extrapolate:
            eps = 1e-6
            outside = (fi < -eps) | (fi > self.geom.ncol - 1 + eps) | (fj < -eps) | (fj > self.geom.nrow - 1 + eps)
            out = np.where(outside, np.nan, out)
        return out

    def resample_to(self, geom: Geometry, order: int = 1, extrapolate: bool = False, name=None) -> "Surface":
        X, Y = geom.coords()
        return Surface(name or self.name, geom, self.sample(X, Y, order, extrapolate), self.source)

    # ---- stats ---------------------------------------------------------
    def stats(self) -> dict:
        v = self.z[np.isfinite(self.z)]
        if v.size == 0:
            return dict(min=np.nan, max=np.nan, mean=np.nan, std=np.nan, defined=0.0)
        return dict(min=float(v.min()), max=float(v.max()), mean=float(v.mean()), std=float(v.std()),
                    defined=float(v.size / self.z.size))

    def copy(self, name=None):
        return Surface(name or self.name, self.geom, self.z.copy(), self.source)


def fill_nan_nearest(z: np.ndarray) -> np.ndarray:
    """Fill undefined nodes with the value of the nearest defined node."""
    mask = np.isnan(z)
    if not mask.any():
        return z
    if mask.all():
        return np.zeros_like(z)
    idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return z[tuple(idx)]


def smooth(z: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return z
    zf = fill_nan_nearest(z)
    out = ndimage.gaussian_filter(zf, sigma, mode="nearest")
    return np.where(np.isnan(z), np.nan, out)


# ---------------------------------------------------------------------------
# Synthetic surfaces (for demo / concept models)
# ---------------------------------------------------------------------------
def synthetic_surface(geom: Geometry, name="Synthetic", kind="anticline", z0=2000.0, relief=150.0,
                      width_x=None, width_y=None, azimuth=0.0, dip_x=0.0, dip_y=0.0, noise=0.0,
                      seed=1, cx=None, cy=None) -> Surface:
    """Generate a smooth structural surface.

    kind: anticline | syncline | tilted | flat | plunging
    dip_x / dip_y are regional dips in m per km.
    """
    X, Y = geom.coords()
    xmin, xmax, ymin, ymax = geom.bounds()
    cx = (xmin + xmax) / 2 if cx is None else cx
    cy = (ymin + ymax) / 2 if cy is None else cy
    wx = width_x or (xmax - xmin) / 4
    wy = width_y or (ymax - ymin) / 4
    a = np.deg2rad(azimuth)
    u = (X - cx) * np.cos(a) + (Y - cy) * np.sin(a)
    v = -(X - cx) * np.sin(a) + (Y - cy) * np.cos(a)
    z = np.full(geom.shape, float(z0))
    if kind in ("anticline", "syncline"):
        bump = np.exp(-(u ** 2 / (2 * wx ** 2) + v ** 2 / (2 * wy ** 2)))
        z = z - (relief if kind == "anticline" else -relief) * bump
    elif kind == "plunging":
        bump = np.exp(-(v ** 2 / (2 * wy ** 2)))
        z = z - relief * bump + relief * 0.6 * (u - u.min()) / max(np.ptp(u), 1.0)
    z = z + dip_x * (X - cx) / 1000.0 + dip_y * (Y - cy) / 1000.0
    if noise > 0:
        rng = np.random.default_rng(seed)
        n = ndimage.gaussian_filter(rng.standard_normal(geom.shape), 4.0)
        n = n / (n.std() + 1e-12)
        z = z + noise * n
    return Surface(name, geom, z, source=f"synthetic:{kind}")
