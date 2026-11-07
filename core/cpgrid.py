"""Zones, layering and corner-point grid construction.

The corner-point grid uses vertical pillars on a regular lateral lattice (the usual starting point for
a simulation model).  Faults are represented by *stair-stepping*: every cell column is assigned to a
fault block (side of each fault plane at the fault's reference depth) and each of its corner depths is
evaluated with that side forced - so neighbouring columns on opposite sides of a fault carry different
ZCORN values on the shared pillar (this is exactly how Eclipse GRDECL grids store faults).

Array conventions: cell arrays are (nk, nj, ni); ``zc`` is (nk, 2, nj, 2, ni, 2) with axes
(layer, top/bottom, row, south/north, col, west/east) - flattened C-order this *is* the Eclipse ZCORN order.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
import numpy as np

from .workflow import Structure
from .faults import block_labels

STYLES = ["proportional", "follow_top", "follow_base", "fractions"]
STYLE_HELP = {
    "proportional": "n layers of equal fraction of the zone thickness (conformable zone).",
    "follow_top": "constant layer thickness dz measured from the top; layers truncate at the base (base-lap / onlap).",
    "follow_base": "constant layer thickness dz measured from the base; layers truncate at the top (erosion below an unconformity).",
    "fractions": "user-defined thickness fractions (e.g. thin layers near the top).",
}


@dataclass
class ZoneSpec:
    name: str
    top: str
    base: str
    nlayers: int = 5
    style: str = "proportional"
    dz: float = 5.0
    fractions: List[float] = field(default_factory=list)
    poro: float = 0.20
    permx: float = 100.0
    ntg: float = 1.0
    kvkh: float = 0.1

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        keys = ZoneSpec.__dataclass_fields__.keys()
        return ZoneSpec(**{k: v for k, v in d.items() if k in keys})


def default_zones(horizons: List[str]) -> List[ZoneSpec]:
    return [ZoneSpec(name=f"Z{i + 1}_{a}", top=a, base=b) for i, (a, b) in enumerate(zip(horizons[:-1], horizons[1:]))]


def layer_interfaces(zt: np.ndarray, zb: np.ndarray, spec: ZoneSpec, n: int) -> np.ndarray:
    """Layer interface depths, shape (n + 1, *zt.shape)."""
    H = np.maximum(zb - zt, 0.0)
    if spec.style == "proportional":
        f = np.linspace(0, 1, n + 1)
        return zt[None] + f[:, None, None] * H[None]
    if spec.style == "fractions":
        fr = np.asarray(spec.fractions if len(spec.fractions) == n else np.ones(n), float)
        cum = np.concatenate([[0.0], np.cumsum(fr / fr.sum())])
        return zt[None] + cum[:, None, None] * H[None]
    k = np.arange(n + 1)[:, None, None]
    if spec.style == "follow_top":
        return np.minimum(zt[None] + k * spec.dz, zb[None] + 0 * k)
    if spec.style == "follow_base":
        return np.maximum(zb[None] - (n - k) * spec.dz, zt[None] + 0 * k)
    raise ValueError(spec.style)


@dataclass
class CPGrid:
    ni: int
    nj: int
    nk: int
    xs: np.ndarray                     # pillar x (ni+1)
    ys: np.ndarray                     # pillar y (nj+1)
    zc: np.ndarray                     # (nk, 2, nj, 2, ni, 2)
    actnum: np.ndarray                 # (nk, nj, ni) int
    layer_zone: np.ndarray             # (nk,) zone index per layer
    zones: List[ZoneSpec]
    block: np.ndarray                  # (nj, ni) fault block id
    faults: List[str]
    notes: List[str] = field(default_factory=list)
    origin: tuple = (0.0, 0.0)         # world position of the local (0, 0) - only used by rotated grids
    angle: float = 0.0                 # rotation (deg, counter-clockwise) of the I axis from +X; xs/ys are local when != 0
    slope: Optional[np.ndarray] = None  # (nj+1, ni+1, 2) local dU/dz, dV/dz of each pillar (None = vertical pillars)
    zref: float = 0.0                  # depth at which a tilted pillar is at (xs, ys)

    # ---- derived ---------------------------------------------------
    @property
    def ncells(self):
        return self.ni * self.nj * self.nk

    @property
    def rotated(self) -> bool:
        return abs(self.angle) > 1e-9

    def to_world(self, u, v):
        if not self.rotated:
            return np.asarray(u, float), np.asarray(v, float)
        c, s_ = np.cos(np.deg2rad(self.angle)), np.sin(np.deg2rad(self.angle))
        u, v = np.asarray(u, float), np.asarray(v, float)
        return self.origin[0] + u * c - v * s_, self.origin[1] + u * s_ + v * c

    @property
    def tilted(self) -> bool:
        return self.slope is not None and bool(np.any(self.slope != 0))

    def pillar_xy(self, z=None):
        """World X, Y of every pillar, shape (nj+1, ni+1); at the reference depth, or at depth ``z`` (scalar / array) for tilted pillars."""
        U, V = np.meshgrid(self.xs, self.ys)
        if z is not None and self.tilted:
            U = U + self.slope[..., 0] * (z - self.zref)
            V = V + self.slope[..., 1] * (z - self.zref)
        return self.to_world(U, V)

    def center_xy(self):
        """World X, Y of the cell-column centres (at the reference depth), shape (nj, ni)."""
        U, V = np.meshgrid(0.5 * (self.xs[:-1] + self.xs[1:]), 0.5 * (self.ys[:-1] + self.ys[1:]))
        return self.to_world(U, V)

    def corner_xy(self, k, t, j, b, i, a):
        """World X, Y of cell corners (index arrays; t = 0 top / 1 base, b = J side, a = I side) - follows tilted pillars."""
        k, t, j, b, i, a = np.broadcast_arrays(*(np.asarray(v) for v in (k, t, j, b, i, a)))
        U, V = self.xs[i + a], self.ys[j + b]
        if self.tilted:
            z = self.zc[k, t, j, b, i, a]
            U = U + self.slope[j + b, i + a, 0] * (z - self.zref)
            V = V + self.slope[j + b, i + a, 1] * (z - self.zref)
        return self.to_world(U, V)

    def coord(self) -> np.ndarray:
        zt = float(np.nanmin(self.zc)) - 10.0
        zb = float(np.nanmax(self.zc)) + 10.0
        X, Y = np.meshgrid(self.xs, self.ys)
        out = np.empty((self.nj + 1, self.ni + 1, 6))
        if self.tilted:
            out[..., 0], out[..., 1] = X + self.slope[..., 0] * (zt - self.zref), Y + self.slope[..., 1] * (zt - self.zref)
            out[..., 3], out[..., 4] = X + self.slope[..., 0] * (zb - self.zref), Y + self.slope[..., 1] * (zb - self.zref)
        else:
            out[..., 0], out[..., 1] = X, Y
            out[..., 3], out[..., 4] = X, Y
        out[..., 2], out[..., 5] = zt, zb
        return out

    def thickness(self) -> np.ndarray:
        return (self.zc[:, 1] - self.zc[:, 0]).mean(axis=(2, 4))

    def center_depth(self) -> np.ndarray:
        return self.zc.mean(axis=(1, 3, 5))

    def cell_dx_dy(self):
        return np.diff(self.xs), np.diff(self.ys)

    def bulk_volume(self) -> np.ndarray:
        dx, dy = self.cell_dx_dy()
        if not self.tilted:
            return self.thickness() * dy[None, :, None] * dx[None, None, :]
        zm = self.center_depth()                                   # plan area of the sheared column at the cell's mid depth
        X, Y = np.meshgrid(self.xs, self.ys)
        sx, sy = self.slope[..., 0], self.slope[..., 1]
        P = {}
        for b in (0, 1):
            for a in (0, 1):
                sl = (slice(b, b + self.nj), slice(a, a + self.ni))
                P[b, a] = (X[sl][None] + sx[sl][None] * (zm - self.zref), Y[sl][None] + sy[sl][None] * (zm - self.zref))
        (x00, y00), (x10, y10), (x11, y11), (x01, y01) = P[0, 0], P[0, 1], P[1, 1], P[1, 0]
        area = 0.5 * np.abs((x00 * y10 - x10 * y00) + (x10 * y11 - x11 * y10) + (x11 * y01 - x01 * y11) + (x01 * y00 - x00 * y01))
        return self.thickness() * area

    def zone_layer_array(self) -> np.ndarray:
        """Zone index (1-based) as a (nk, nj, ni) array."""
        return np.broadcast_to((self.layer_zone + 1)[:, None, None], (self.nk, self.nj, self.ni)).copy()

    def property_array(self, name: str) -> np.ndarray:
        arr = np.zeros((self.nk, self.nj, self.ni))
        for zi, z in enumerate(self.zones):
            val = {"PORO": z.poro, "PERMX": z.permx, "PERMY": z.permx, "PERMZ": z.permx * z.kvkh,
                   "NTG": z.ntg}[name]
            arr[self.layer_zone == zi] = val
        return arr

    def block_array(self) -> np.ndarray:
        return np.broadcast_to(self.block[None], (self.nk, self.nj, self.ni)).copy()

    def summary(self) -> Dict[str, float]:
        vol = self.bulk_volume()
        act = self.actnum.astype(bool)
        th = self.thickness()
        return dict(cells=self.ncells, active=int(act.sum()), inactive=int((~act).sum()),
                    bulk_volume_Mm3=float(vol[act].sum() / 1e6),
                    min_thickness=float(th[act].min()) if act.any() else 0.0,
                    mean_thickness=float(th[act].mean()) if act.any() else 0.0,
                    fault_blocks=int(self.block.max()))

    def check(self) -> List[str]:
        msgs = []
        th = self.thickness()
        if (self.zc[:, 1] < self.zc[:, 0] - 1e-6).any():
            msgs.append("Negative cell thickness found (should not happen).")
        if (np.diff(self.zc.reshape(self.nk * 2, -1), axis=0)[1::2] < -1e-6).any():
            msgs.append("Layers overlap between neighbouring cells in a column.")
        pinched = int(((th <= 1e-6) & (self.actnum == 0)).sum())
        msgs.append(f"{pinched:,} zero-thickness (pinched-out) cells are inactive.")
        return msgs

    # ---- exterior faces for 3D display -------------------------------
    def exterior_faces(self, i0=0, j0=0, scalar: Optional[np.ndarray] = None, max_faces=120_000,
                       layer_mask: Optional[np.ndarray] = None):
        """Triangulated outer skin of displayed active cells in the sub-block [i0:, j0:]."""
        act = self.actnum[:, j0:, i0:].astype(bool)
        if layer_mask is not None:
            layer_mask = np.asarray(layer_mask, dtype=bool)
            if layer_mask.shape != (self.nk,):
                raise ValueError(f"Layer visibility mask must have shape ({self.nk},).")
            act &= layer_mask[:, None, None]
        K, J, I = act.shape

        def nb(a, axis, step):
            out = np.zeros_like(a)
            sl_dst = [slice(None)] * 3
            sl_src = [slice(None)] * 3
            if step == 1:      # neighbour at index+1
                sl_dst[axis], sl_src[axis] = slice(0, -1), slice(1, None)
            else:              # neighbour at index-1
                sl_dst[axis], sl_src[axis] = slice(1, None), slice(0, -1)
            out[tuple(sl_dst)] = a[tuple(sl_src)]
            return out

        spec = {
            "top": (act & ~nb(act, 0, -1), [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)]),
            "bottom": (act & ~nb(act, 0, 1), [(1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)]),
            "west": (act & ~nb(act, 2, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
            "east": (act & ~nb(act, 2, 1), [(0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)]),
            "south": (act & ~nb(act, 1, -1), [(0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)]),
            "north": (act & ~nb(act, 1, 1), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
        }
        total = sum(int(m.sum()) for m, _ in spec.values())
        if total > max_faces:
            raise ValueError(f"{total:,} faces to draw (limit {max_faces:,}); cut the model with the I/J sliders "
                             "or build a coarser grid.")
        V, T, S = [], [], []
        base = 0
        for name, (mask, corners) in spec.items():
            idx = np.argwhere(mask)
            if len(idx) == 0:
                continue
            k, j, i = idx[:, 0], idx[:, 1] + j0, idx[:, 2] + i0
            pts = []
            for (t, b, a) in corners:
                cx_, cy_ = self.corner_xy(k, t, j, b, i, a)
                pts.append(np.column_stack([cx_, cy_, self.zc[k, t, j, b, i, a]]))
            n = len(idx)
            verts = np.stack(pts, axis=1).reshape(-1, 3)                 # (n*4, 3)
            q = base + np.arange(n)[:, None] * 4
            tri = np.concatenate([np.hstack([q, q + 1, q + 2]), np.hstack([q, q + 2, q + 3])]).reshape(-1, 3)
            V.append(verts)
            T.append(tri)
            if scalar is not None:
                S.append(np.tile(scalar[k, j, i], 2))
            base += n * 4
        if not V:
            return np.zeros((0, 3)), np.zeros((0, 3), int), np.zeros(0)
        return np.vstack(V), np.vstack(T), (np.concatenate(S) if scalar is not None else np.zeros(0))


# ---------------------------------------------------------------------------
def validate_zones(zones: List[ZoneSpec], names: List[str]) -> List[str]:
    errs = []
    if not zones:
        errs.append("Define at least one zone.")
    last = -1
    for z in zones:
        if z.top not in names or z.base not in names:
            errs.append(f"Zone {z.name}: horizon not found in the structural model.")
            continue
        a, b = names.index(z.top), names.index(z.base)
        if b <= a:
            errs.append(f"Zone {z.name}: base ({z.base}) must lie below top ({z.top}).")
        if a < last:
            errs.append(f"Zone {z.name} overlaps the previous zone.")
        last = max(last, b)
        if z.style in ("follow_top", "follow_base") and z.dz <= 0:
            errs.append(f"Zone {z.name}: dz must be > 0.")
        if z.style != "follow_top" and z.style != "follow_base" and z.nlayers < 1:
            errs.append(f"Zone {z.name}: at least one layer.")
    return errs


DEFAULT_SPEC = dict(angle=0.0, origin=None, extent=None, refine=[], trim_extent=False, min_volume=0.0, inactive_zones=[], tilt=False, tilt_radius=3.0)


def make_axis(a: float, b: float, d: float, windows=(), max_cells=5000) -> np.ndarray:
    """Pillar coordinates from a to b with nominal spacing d, locally refined inside ``windows`` = [(lo, hi, d_local)]."""
    if not windows:
        n = max(int(round((b - a) / d)), 1)
        return np.linspace(a, b, n + 1)
    bnds = sorted({w[0] for w in windows} | {w[1] for w in windows})
    xs = [a]
    pos = a
    while pos < b - 1e-9 and len(xs) < max_cells:
        dd = min([d] + [w[2] for w in windows if w[0] <= pos + 1e-9 < w[1]])
        nxt = pos + dd
        for bd in bnds:
            if pos + 0.5 * dd < bd <= nxt + 0.5 * dd:
                nxt = bd
                break
        if b - nxt < 0.5 * dd:
            nxt = b
        xs.append(min(nxt, b))
        pos = xs[-1]
    xs[-1] = b
    return np.array(xs)


def plan_axes(bounds, dx: float, dy: float, spec: Optional[dict] = None) -> dict:
    """Grid frame and pillar axes from model bounds + grid spec (angle, origin, extent, refinement windows)."""
    sp = {**DEFAULT_SPEC, **(spec or {})}
    xmin, xmax, ymin, ymax = bounds
    ang = float(sp["angle"] or 0.0)
    ca, sa = np.cos(np.deg2rad(ang)), np.sin(np.deg2rad(ang))
    rot = abs(ang) > 1e-9

    def to_local(x, y, o):
        return (x - o[0]) * ca + (y - o[1]) * sa, -(x - o[0]) * sa + (y - o[1]) * ca

    if not rot:
        o = sp["origin"] or (xmin, ymin)
        ext = sp["extent"] or (xmax - o[0], ymax - o[1])
        a_x, a_y = o[0], o[1]
        origin = (0.0, 0.0)
        loc = lambda x, y: (x, y)
    else:
        if sp["origin"] and sp["extent"]:
            origin, ext = tuple(sp["origin"]), tuple(sp["extent"])
        else:
            cx, cy = 0.5 * (xmin + xmax), 0.5 * (ymin + ymax)
            cu, cv = to_local(np.array([xmin, xmax, xmax, xmin]), np.array([ymin, ymin, ymax, ymax]), (cx, cy))
            u0, v0 = cu.min(), cv.min()
            origin = (cx + u0 * ca - v0 * sa, cy + u0 * sa + v0 * ca)
            ext = (cu.max() - u0, cv.max() - v0)
            if sp["origin"]:
                origin = tuple(sp["origin"])
        a_x = a_y = 0.0
        loc = lambda x, y, o=origin: to_local(x, y, o)
    wx, wy = [], []
    for w in sp["refine"] or []:
        cu, cv = loc(np.array([w["x0"], w["x1"], w["x1"], w["x0"]], float), np.array([w["y0"], w["y0"], w["y1"], w["y1"]], float))
        wx.append((float(cu.min()), float(cu.max()), float(w.get("dx") or dx)))
        wy.append((float(cv.min()), float(cv.max()), float(w.get("dy") or dy)))
    xs = make_axis(a_x, a_x + ext[0], dx, wx)
    ys = make_axis(a_y, a_y + ext[1], dy, wy)
    return dict(xs=xs, ys=ys, origin=origin if rot else (0.0, 0.0), angle=ang, extent=ext)


def grid_estimate(zones: List[ZoneSpec], axes: dict, names=None, st: Optional[Structure] = None) -> dict:
    ni, nj = len(axes["xs"]) - 1, len(axes["ys"]) - 1
    nk = 0
    for z in zones:
        if z.style in ("proportional", "fractions"):
            nk += int(z.nlayers)
        else:
            nk += 20
    dxs, dys = np.diff(axes["xs"]), np.diff(axes["ys"])
    return dict(ni=ni, nj=nj, nk=nk, cells=ni * nj * nk, dx_min=float(dxs.min()), dx_max=float(dxs.max()),
                dy_min=float(dys.min()), dy_max=float(dys.max()), mem_mb=ni * nj * nk * (8 * 8 + 4) / 1e6,
                aspect_max=float(max(dxs.max() / dys.min(), dys.max() / dxs.min())))


def _to_world(u, v, origin, angle):
    if abs(angle) < 1e-9:
        return np.asarray(u, float), np.asarray(v, float)
    c, s_ = np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))
    return origin[0] + u * c - v * s_, origin[1] + u * s_ + v * c


def _seg_nearest(px, py, trace):
    """Nearest point on a polyline for each (px, py): returns distance, unit left normal at that point."""
    P = np.asarray(trace, float)
    best = np.full(px.shape, np.inf)
    nx, ny = np.zeros(px.shape), np.zeros(px.shape)
    for a, b in zip(P[:-1], P[1:]):
        d = b - a
        L2 = float(d @ d)
        if L2 < 1e-12:
            continue
        t = np.clip(((px - a[0]) * d[0] + (py - a[1]) * d[1]) / L2, 0.0, 1.0)
        dist = np.hypot(px - (a[0] + t * d[0]), py - (a[1] + t * d[1]))
        m = dist < best
        best = np.where(m, dist, best)
        L = np.sqrt(L2)
        nx = np.where(m, -d[1] / L, nx)
        ny = np.where(m, d[0] / L, ny)
    return best, nx, ny


def tilt_slopes(faults, PX, PY, radius: float, dip_min: float = 25.0):
    """World-frame pillar slopes (dX/dz, dY/dz) that make pillars near a fault follow its dipping plane.

    Slope = cot(dip) towards the hanging wall, faded linearly to zero at ``radius`` (map distance) from the trace.
    Where fault influence overlaps, the fault giving the largest weight wins.  Returns (sx, sy, weight)."""
    sx, sy, wbest = np.zeros(PX.shape), np.zeros(PX.shape), np.zeros(PX.shape)
    for f in faults:
        if f.ftype in ("strike_slip",) or len(f.trace) < 2:
            continue
        d, nx, ny = _seg_nearest(PX, PY, f.trace)
        w = np.clip(1.0 - d / max(radius, 1e-9), 0.0, 1.0)
        w = w * w * (3.0 - 2.0 * w)                                      # smoothstep
        cot = 1.0 / np.tan(np.deg2rad(np.clip(float(f.dip), dip_min, 89.0)))
        sgn = 1.0 if f.hw_side == "left" else -1.0
        upd = w > wbest
        sx = np.where(upd, sgn * nx * cot * w, sx)
        sy = np.where(upd, sgn * ny * cot * w, sy)
        wbest = np.where(upd, w, wbest)
    return sx, sy, wbest


def limit_tilt(slope_local: np.ndarray, xs, ys, zlo: float, zhi: float, zref: float, min_area_frac: float = 0.3):
    """Largest factor lam in [0, 1] such that every quad of pillar positions at depths zlo and zhi keeps an area >= min_area_frac of the vertical one."""
    X, Y = np.meshgrid(xs, ys)
    area0 = (np.diff(xs)[None, :] * np.diff(ys)[:, None])

    def valid(lam):
        for z in (zlo, zhi):
            U = X + lam * slope_local[..., 0] * (z - zref)
            V = Y + lam * slope_local[..., 1] * (z - zref)
            x00, x10, x11, x01 = U[:-1, :-1], U[:-1, 1:], U[1:, 1:], U[1:, :-1]
            y00, y10, y11, y01 = V[:-1, :-1], V[:-1, 1:], V[1:, 1:], V[1:, :-1]
            A = 0.5 * ((x00 * y10 - x10 * y00) + (x10 * y11 - x11 * y10) + (x11 * y01 - x01 * y11) + (x01 * y00 - x00 * y01))
            if (A < min_area_frac * area0).any():
                return False
            # no pillar may cross the line between its neighbours' x or y order
            if (np.diff(U, axis=1) <= 0).any() or (np.diff(V, axis=0) <= 0).any():
                return False
        return True
    if valid(1.0):
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if valid(mid) else (lo, mid)
    return lo


def build_grid(st: Structure, zones: List[ZoneSpec], dx: float, dy: float, min_thickness: float = 0.1,
               bounds=None, max_layers_per_zone: int = 400, boundary=None, spec: Optional[dict] = None) -> CPGrid:
    errs = validate_zones(zones, st.names)
    if errs:
        raise ValueError("; ".join(errs))
    sp = {**DEFAULT_SPEC, **(spec or {})}
    ax = plan_axes(bounds or st.geom.bounds(), dx, dy, sp)
    xs, ys, origin, angle = ax["xs"], ax["ys"], ax["origin"], ax["angle"]
    ni, nj = len(xs) - 1, len(ys) - 1
    if ni > 4000 or nj > 4000:
        raise ValueError("More than 4000 columns along an axis - increase the cell size.")
    proto = CPGrid(ni, nj, 0, xs, ys, np.zeros((0, 2, nj, 2, ni, 2)), np.zeros((0, nj, ni), int), np.zeros(0, int), zones,
                   np.ones((nj, ni), int), [], origin=origin, angle=angle)
    PX, PY = proto.pillar_xy()                       # world pillar positions
    CX, CY = proto.center_xy()

    # layer count per zone (follow_* derive it from the thickest column)
    Zp = st.eval(PX, PY)
    nl = []
    for z in zones:
        a, b = st.names.index(z.top), st.names.index(z.base)
        if z.style in ("follow_top", "follow_base"):
            hmax = float(np.max(Zp[b] - Zp[a]))
            n = int(np.clip(np.ceil(hmax / z.dz - 1e-9), 1, max_layers_per_zone))
        else:
            n = int(z.nlayers)
            if z.style == "fractions" and len(z.fractions) != n:
                n = max(len(z.fractions), 1) if z.fractions else n
        nl.append(n)
    nk = int(sum(nl))
    layer_zone = np.concatenate([np.full(n, zi) for zi, n in enumerate(nl)]).astype(int)

    # fault blocks / sides (evaluated at each fault's reference depth)
    sides = {f.name: f.side(CX, CY, f.zref) for f in st.faults}
    block = block_labels(st.faults, CX, CY)[0] if st.faults else np.ones((nj, ni), int)

    slope, zref_t, tilt_note = None, 0.0, None
    if sp["tilt"] and st.faults:
        rad = float(sp["tilt_radius"]) * float(min(np.diff(xs).mean(), np.diff(ys).mean()))
        sxw, syw, wt = tilt_slopes(st.faults, PX, PY, rad)
        if (wt > 0).any():
            c_, s_ = np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))
            slope = np.stack([sxw * c_ + syw * s_, -sxw * s_ + syw * c_], axis=-1)          # world -> local frame
            zref_t = float(np.mean([f.zref for f in st.faults]))
            lam = limit_tilt(slope, xs, ys, float(Zp.min()) - 20.0, float(Zp.max()) + 20.0, zref_t)
            slope = slope * lam
            mx = float(np.degrees(np.arctan(np.hypot(slope[..., 0], slope[..., 1]).max())))
            tilt_note = (f"Pillars inclined along {len(st.faults)} fault plane(s) within {sp['tilt_radius']:g} cells (max {mx:.0f} deg from vertical"
                         + (f"; tilt reduced to {lam * 100:.0f} % so no cell inverts" if lam < 0.999 else "") + f"); reference depth {zref_t:.0f}.")
        else:
            tilt_note = "Pillar tilt requested but no fault lies within the radius of a pillar - pillars stay vertical."
    nh = len(st.names)
    U0, V0 = np.meshgrid(xs, ys)
    zc = np.zeros((nk, 2, nj, 2, ni, 2))
    for b in (0, 1):
        for a in (0, 1):
            X = PX[b:b + nj, a:a + ni]
            Y = PY[b:b + nj, a:a + ni]
            Z = st.eval(X, Y, sides=sides if st.faults else None)
            if slope is not None:                        # fixed point: each horizon is evaluated where its own tilted pillar crosses it
                Uc, Vc = U0[b:b + nj, a:a + ni], V0[b:b + nj, a:a + ni]
                SU, SV = slope[b:b + nj, a:a + ni, 0], slope[b:b + nj, a:a + ni, 1]
                for _ in range(2):
                    Zn = np.empty_like(Z)
                    for h in range(nh):
                        Xh, Yh = _to_world(Uc + SU * (Z[h] - zref_t), Vc + SV * (Z[h] - zref_t), origin, angle)
                        Zn[h] = st.eval(Xh, Yh, sides=sides if st.faults else None)[h]
                    Z = np.maximum.accumulate(Zn, axis=0)
            k0 = 0
            for zi, (zspec, n) in enumerate(zip(zones, nl)):
                ia, ib = st.names.index(zspec.top), st.names.index(zspec.base)
                L = layer_interfaces(Z[ia], Z[ib], zspec, n)               # (n+1, nj, ni)
                zc[k0:k0 + n, 0, :, b, :, a] = L[:-1]
                zc[k0:k0 + n, 1, :, b, :, a] = L[1:]
                k0 += n
    th = (zc[:, 1] - zc[:, 0]).mean(axis=(2, 4))
    actnum = (th > min_thickness).astype(np.int32)
    notes = [f"{ni} x {nj} x {nk} cells; pillars {'inclined near faults' if slope is not None else 'vertical'}; {len(st.faults)} fault(s) stair-stepped."]
    if tilt_note:
        notes.append(tilt_note)
    if angle:
        notes.append(f"Grid rotated {angle:.1f} deg; origin ({origin[0]:.1f}, {origin[1]:.1f}); MAPAXES is written to GRDECL.")
    if len(set(np.round(np.diff(xs), 6))) > 1 or len(set(np.round(np.diff(ys), 6))) > 1:
        notes.append(f"Non-uniform spacing: dx {np.diff(xs).min():.1f}-{np.diff(xs).max():.1f}, dy {np.diff(ys).min():.1f}-{np.diff(ys).max():.1f}.")
    if min_thickness > 0:
        notes.append(f"Cells thinner than {min_thickness:g} are inactive.")
    if sp["trim_extent"] or angle:
        x0, x1, y0, y1 = st.geom.bounds()
        out = (CX < x0) | (CX > x1) | (CY < y0) | (CY > y1)
        n_out = int((actnum.astype(bool) & out[None]).sum())
        actnum = np.where(out[None], 0, actnum).astype(np.int32)
        notes.append(f"{n_out} cells outside the model extent set inactive.")
    if boundary is not None:
        from .polygons import inside
        outside = ~inside(CX, CY, boundary.pts)
        n_out = int((actnum.astype(bool) & outside[None]).sum())
        actnum = np.where(outside[None], 0, actnum).astype(np.int32)
        notes.append(f"Boundary polygon '{boundary.name}': {n_out} cells set inactive outside it.")
    if sp["inactive_zones"]:
        for zi, z in enumerate(zones):
            if z.name in sp["inactive_zones"]:
                actnum[layer_zone == zi] = 0
        notes.append("Zones set inactive: " + ", ".join(sp["inactive_zones"]) + ".")
    if sp["min_volume"] and sp["min_volume"] > 0:
        vol = th * np.diff(ys)[None, :, None] * np.diff(xs)[None, None, :]
        small = (vol < sp["min_volume"]) & (actnum > 0)
        actnum[small] = 0
        notes.append(f"{int(small.sum())} cells below the minimum bulk volume {sp['min_volume']:g} set inactive.")
    return CPGrid(ni, nj, nk, xs, ys, zc, actnum, layer_zone, zones, block, [f.name for f in st.faults], notes,
                  origin=origin, angle=angle, slope=slope, zref=zref_t)
