"""Fault model: map-view trace + dip + throw profile -> vertical displacement field.

Kinematic model used (documented in the app):

* The trace is the fault position at reference depth ``zref`` (map view polyline).
* The fault plane dips at ``dip`` towards the hanging wall (HW), so at depth z the plane sits
  ``(z - zref)/tan(dip)`` further towards the HW side.
* Throw (vertical separation) varies along strike with a profile (elliptical, triangular, plateau, constant)
  and optionally grows with depth (growth faults).
* Displacement of a point is  sgn * 0.5 * T * exp(-|s|/drag)  with sgn = +1 for the HW of a normal fault
  (HW moves down, z increases), -1 for the FW, signs reversed for reverse faults.
  Across the fault the horizon is therefore offset by exactly T * exp(-|s|/drag) -> T at the trace.
* By default no heave gap is modelled: separation is purely vertical (stair-step corner-point faults).

Fault types (``ftype``)
-----------------------
normal      hanging wall moves down the plane.
reverse     hanging wall moves up the plane (thrust / reverse fault).
strike_slip lateral (dextral / sinistral) slip along strike; ``throw`` is an optional oblique vertical component.
transverse  transfer / cross fault: the throw changes *sign* along strike (scissor / hinge fault) - zero at
            ``pivot`` (0..1 along the trace), +throw at one end and -throw at the other - plus optional ``slip``.

Heave: with ``heave`` > 0 the dip-slip types also translate the horizons horizontally by
``heave * throw / tan(dip)`` (so the footwall/hanging-wall cut-offs separate / overlap as in a real fault);
heave = 0 keeps the classic vertical-separation behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional
import numpy as np

PROFILES = ["elliptical", "triangular", "plateau", "constant"]
FAULT_TYPES = ["normal", "reverse", "strike_slip", "transverse"]
FAULT_TYPE_INFO = {
    "normal": "Hanging wall moves down the fault plane (extension). Vertical separation = throw.",
    "reverse": "Hanging wall moves up the plane (compression / thrust). Vertical separation = throw, sign reversed.",
    "strike_slip": "Lateral slip along strike (dextral / sinistral). Horizons shift sideways by the slip; "
                   "throw (if > 0) adds an oblique vertical component.",
    "transverse": "Transfer / cross fault: throw changes sign along strike (scissor / hinge) about the pivot, "
                  "typically linking or segmenting the main faults. Optional lateral slip.",
}
PALETTE = ["#D7263D", "#F46036", "#2E294E", "#1B998B", "#C5D86D", "#6A4C93", "#1982C4"]


def _profile(kind: str, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    if kind == "elliptical":
        return np.sqrt(np.clip(1 - (2 * t - 1) ** 2, 0, 1))
    if kind == "triangular":
        return 1 - np.abs(2 * t - 1)
    if kind == "plateau":
        u = np.clip(np.minimum(t, 1 - t) / 0.25, 0, 1)
        return u * u * (3 - 2 * u)
    return np.ones_like(t)


@dataclass
class Fault:
    name: str
    trace: List[List[float]]
    ftype: str = "normal"          # normal | reverse | strike_slip | transverse
    throw: float = 50.0            # m, maximum vertical separation at zref
    dip: float = 65.0              # degrees
    hw_side: str = "left"          # side of the trace (walking along vertex order) with the hanging wall
    profile: str = "elliptical"
    drag: float = 250.0            # m, exponential decay length of the drag zone
    growth: float = 0.0            # m of extra throw per 100 m of depth below zref (growth fault)
    zref: float = 2000.0
    color: str = ""
    slip: float = 0.0              # lateral slip (m) for strike_slip / transverse faults
    slip_sense: str = "dextral"    # dextral | sinistral
    pivot: float = 0.5             # transverse faults: fraction along the trace where the throw changes sign
    heave: float = 0.0             # 0 = vertical separation only, 1 = full horizontal heave (throw / tan dip)

    # ------------------------------------------------------------------
    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        keys = Fault.__dataclass_fields__.keys()
        return Fault(**{k: v for k, v in d.items() if k in keys})

    @property
    def points(self) -> np.ndarray:
        return np.asarray(self.trace, float)

    def length(self) -> float:
        p = self.points
        return float(np.hypot(*np.diff(p, axis=0).T).sum()) if len(p) > 1 else 0.0

    @property
    def hw_sign(self) -> int:
        return 1 if self.hw_side == "left" else -1

    def flip_hw(self):
        self.hw_side = "right" if self.hw_side == "left" else "left"

    # ------------------------------------------------------------------
    def locate(self, X, Y):
        """Signed distance to the trace (positive = left of travel direction) and strike fraction t."""
        s, t, _, _ = self.locate_full(X, Y)
        return s, t

    def locate_full(self, X, Y):
        """As :meth:`locate` plus the unit tangent (tx, ty) of the nearest trace segment."""
        P = self.points
        X = np.asarray(X, float)
        Y = np.asarray(Y, float)
        if len(P) < 2:
            return np.full(X.shape, 1e12), np.zeros(X.shape), np.ones(X.shape), np.zeros(X.shape)
        seg = np.diff(P, axis=0)
        L = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.concatenate([[0.0], np.cumsum(L)])
        total = max(cum[-1], 1e-9)
        best = np.full(X.shape, np.inf)
        s_out = np.zeros(X.shape)
        t_out = np.zeros(X.shape)
        tx_out = np.ones(X.shape)
        ty_out = np.zeros(X.shape)
        for k in range(len(seg)):
            if L[k] < 1e-9:
                continue
            ax, ay = P[k]
            abx, aby = seg[k]
            u = np.clip(((X - ax) * abx + (Y - ay) * aby) / (L[k] ** 2), 0.0, 1.0)
            cx, cy = ax + u * abx, ay + u * aby
            d2 = (X - cx) ** 2 + (Y - cy) ** 2
            better = d2 < best
            cross = abx * (Y - ay) - aby * (X - ax)
            sg = np.where(cross >= 0, 1.0, -1.0)
            s_out = np.where(better, sg * np.sqrt(d2), s_out)
            t_out = np.where(better, (cum[k] + u * L[k]) / total, t_out)
            tx_out = np.where(better, abx / L[k], tx_out)
            ty_out = np.where(better, aby / L[k], ty_out)
            best = np.where(better, d2, best)
        return s_out, t_out, tx_out, ty_out

    def throw_at_depth(self, z_mean: float) -> float:
        return max(0.0, self.throw + self.growth * (z_mean - self.zref) / 100.0)

    def _s_eff(self, X, Y, z):
        s, t = self.locate(X, Y)
        delta = (np.asarray(z, float) - self.zref) / np.tan(np.deg2rad(np.clip(self.dip, 5.0, 90.0)))
        return s * self.hw_sign - delta, t

    def side(self, X, Y, z) -> np.ndarray:
        """+1 on the hanging-wall side of the fault plane at depth z, -1 on the footwall side."""
        s_eff, _ = self._s_eff(X, Y, z)
        return np.where(s_eff >= 0, 1.0, -1.0)

    def throw_fraction(self, X, Y):
        """Signed throw factor along strike (-1..1); for transverse faults it changes sign at ``pivot``."""
        _, t = self.locate(X, Y)
        if self.ftype == "transverse":
            piv = float(np.clip(self.pivot, 0.0, 1.0))
            return np.clip((t - piv) / max(piv, 1.0 - piv, 1e-9), -1.0, 1.0)
        return _profile(self.profile, t)

    def slip_fraction(self, X, Y):
        _, t = self.locate(X, Y)
        prof = "plateau" if self.profile == "constant" and self.ftype == "transverse" else self.profile
        return _profile(prof, t)

    def cut_amount(self, X, Y):
        """Size of the offset across the fault at each location (used to decide where grid columns are cut)."""
        a = np.abs(self.throw * self.throw_fraction(X, Y))
        if self.ftype in ("strike_slip", "transverse") and self.slip:
            a = np.maximum(a, abs(self.slip) * self.slip_fraction(X, Y))
        if self.heave > 0:
            a = np.maximum(a, self.heave * a / np.tan(np.deg2rad(np.clip(self.dip, 5.0, 90.0))))
        return a

    @property
    def max_offset(self) -> float:
        m = abs(self.throw)
        if self.ftype in ("strike_slip", "transverse"):
            m = max(m, abs(self.slip))
        return m

    def _components(self, X, Y, z, z_mean, side=None):
        """(dz, ux, uy): vertical displacement and horizontal translation of the points."""
        s, t, tx, ty = self.locate_full(X, Y)
        delta = (np.asarray(z, float) - self.zref) / np.tan(np.deg2rad(np.clip(self.dip, 5.0, 90.0)))
        s_eff = s * self.hw_sign - delta
        sf = np.where(s_eff >= 0, 1.0, -1.0) if side is None else side
        decay = np.exp(-np.abs(s_eff) / max(self.drag, 1.0))
        sgn = -1.0 if self.ftype == "reverse" else 1.0
        T = self.throw_at_depth(z_mean) * self.throw_fraction(X, Y)         # signed
        dz = sgn * sf * 0.5 * T * decay
        ux = np.zeros(np.shape(dz))
        uy = np.zeros(np.shape(dz))
        if self.heave > 0 and self.ftype != "strike_slip":
            hd = sgn * sf * 0.5 * self.heave * T / np.tan(np.deg2rad(np.clip(self.dip, 5.0, 90.0))) * decay
            nlx, nly = -ty, tx                                              # left normal
            ux = ux + hd * self.hw_sign * nlx
            uy = uy + hd * self.hw_sign * nly
        if self.ftype in ("strike_slip", "transverse") and self.slip:
            sl = (1.0 if self.slip_sense == "dextral" else -1.0) * self.slip * self.slip_fraction(X, Y)
            left = sf * self.hw_sign                                        # +1 on the left block of the trace
            ls = left * 0.5 * sl * decay                                    # dextral: left block moves along +t
            ux = ux + ls * tx
            uy = uy + ls * ty
        return dz, ux, uy

    def displacement(self, X, Y, z, z_mean: float, side: Optional[np.ndarray] = None) -> np.ndarray:
        """Vertical displacement (+ve = deeper) of a horizon whose unfaulted depth at (X,Y) is ``z``."""
        return self._components(X, Y, z, z_mean, side)[0]

    def delta(self, sampler, X, Y, z, z_mean: float, side: Optional[np.ndarray] = None) -> np.ndarray:
        """Total depth change including the horizontal translation (heave / strike slip).

        ``sampler(X, Y)`` returns the unfaulted horizon depth at arbitrary locations.
        """
        dz, ux, uy = self._components(X, Y, z, z_mean, side)
        if not (np.any(ux) or np.any(uy)):
            return dz
        zs = sampler(np.asarray(X, float) - ux, np.asarray(Y, float) - uy)
        return (zs - np.asarray(z, float)) + dz

    # ------------------------------------------------------------------
    def plane_mesh(self, z_top: float, z_bot: float, n_z: int = 2):
        """Mesh of the fault plane for 3D display: returns (x, y, z) arrays of shape (n_z, n_vertices)."""
        P = self.points
        if len(P) < 2:
            return None
        seg = np.diff(P, axis=0)
        ang = np.arctan2(seg[:, 1], seg[:, 0])
        # vertex direction = average of adjacent segment directions
        d = np.zeros((len(P), 2))
        for k in range(len(P)):
            if k == 0:
                a = ang[0]
            elif k == len(P) - 1:
                a = ang[-1]
            else:
                a = np.arctan2(np.sin(ang[k - 1]) + np.sin(ang[k]), np.cos(ang[k - 1]) + np.cos(ang[k]))
            d[k] = (np.cos(a), np.sin(a))
        nl = np.column_stack([-d[:, 1], d[:, 0]])                     # left normal
        zs = np.linspace(z_top, z_bot, n_z)
        tan = np.tan(np.deg2rad(np.clip(self.dip, 5.0, 90.0)))
        xs = np.array([P[:, 0] + self.hw_sign * nl[:, 0] * (z - self.zref) / tan for z in zs])
        ys = np.array([P[:, 1] + self.hw_sign * nl[:, 1] * (z - self.zref) / tan for z in zs])
        zz = np.repeat(zs[:, None], len(P), axis=1)
        return xs, ys, zz


def next_color(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


def block_labels(faults: List[Fault], CX, CY, zrep=None, min_throw_frac=0.02, min_throw=0.5):
    """Label fault blocks of grid columns (connected components cut by faults with meaningful throw).

    Returns (labels (nj,ni) int, sides dict name -> (nj,ni) of +/-1).
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    nj, ni = CX.shape
    sides, tf = {}, {}
    for f in faults:
        sides[f.name] = f.side(CX, CY, f.zref if zrep is None else zrep)
        tf[f.name] = f.cut_amount(CX, CY)
    idx = np.arange(nj * ni).reshape(nj, ni)
    rows, cols = [], []

    def connect(a_idx, b_idx, cut):
        keep = ~cut
        rows.append(a_idx[keep])
        cols.append(b_idx[keep])

    cut_x = np.zeros((nj, ni - 1), bool)
    cut_y = np.zeros((nj - 1, ni), bool)
    for f in faults:
        S, T = sides[f.name], tf[f.name]
        thr = max(min_throw, min_throw_frac * f.max_offset)
        cut_x |= (S[:, :-1] != S[:, 1:]) & (np.minimum(T[:, :-1], T[:, 1:]) > thr)
        cut_y |= (S[:-1, :] != S[1:, :]) & (np.minimum(T[:-1, :], T[1:, :]) > thr)
    connect(idx[:, :-1].ravel(), idx[:, 1:].ravel(), cut_x.ravel())
    connect(idx[:-1, :].ravel(), idx[1:, :].ravel(), cut_y.ravel())
    r = np.concatenate(rows) if rows else np.array([], int)
    c = np.concatenate(cols) if cols else np.array([], int)
    g = coo_matrix((np.ones(len(r)), (r, c)), shape=(nj * ni, nj * ni))
    n, lab = connected_components(g, directed=False)
    # order labels by size (largest = block 1)
    counts = np.bincount(lab)
    order = np.argsort(-counts)
    remap = np.empty(n, int)
    remap[order] = np.arange(1, n + 1)
    return remap[lab].reshape(nj, ni), sides
