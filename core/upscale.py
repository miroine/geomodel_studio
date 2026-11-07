"""Upscaling: coarse corner-point grid from the fine grid + property averaging.

Coarse grid
-----------
* I / J: regular groups of ``ci`` / ``cj`` columns.  Extra group boundaries are inserted wherever the fault-block id changes between
  neighbouring columns (anywhere in the model), so coarse cells never straddle a block boundary the fine grid resolves.
* K: layers are grouped inside each zone (zone boundaries are always kept); ``nk_coarse`` gives the number of coarse layers per zone.
* Coarse corner depths are the fine corner depths on the group boundaries (top of the first fine layer, base of the last).
  Pillars are vertical (as in the fine grid), so the coarse cell is exactly the union of its fine cells for the volume.

Property averaging
------------------
PORO / NTG: bulk-volume weighted (PORO weighted by volume x NTG when NTG exists, the net volume).  Saturations: pore-volume weighted.
Discrete: majority by bulk volume.  Permeability: arithmetic, harmonic, geometric, power (exponent w) or flow-based, where a single-phase
steady-state problem with closed lateral boundaries is solved on the fine cells of each coarse cell, per direction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .cpgrid import CPGrid

PERM_METHODS = ["arithmetic", "harmonic", "geometric", "power", "flow"]
SAT_NAMES = ("SW", "SWAT", "SWL", "SWI", "SO", "SG")


class UpscaleError(Exception):
    pass


# ------------------------------------------------------------------ coarse grid
def _edges(n: int, step: int, forced: np.ndarray) -> np.ndarray:
    """Group edges in 0..n: every ``step`` plus the forced cut positions."""
    e = set(range(0, n, max(1, step))) | {n} | {int(f) for f in forced}
    return np.array(sorted(e), int)


def coarse_axes(g: CPGrid, ci: int, cj: int, nk_coarse: Optional[List[int]] = None):
    """Edges (indices into the fine pillars) along I and J, and the fine-layer edges along K."""
    blk = g.block
    fi = np.where((blk[:, :-1] != blk[:, 1:]).any(axis=0))[0] + 1 if g.ni > 1 else np.array([], int)
    fj = np.where((blk[:-1, :] != blk[1:, :]).any(axis=1))[0] + 1 if g.nj > 1 else np.array([], int)
    ie, je = _edges(g.ni, ci, fi), _edges(g.nj, cj, fj)
    ke = [0]
    zones = []
    for zi in range(len(g.zones)):
        ks = np.where(g.layer_zone == zi)[0]
        if ks.size == 0:
            continue
        n = ks.size
        want = int(nk_coarse[zi]) if nk_coarse is not None and zi < len(nk_coarse) else n
        want = int(np.clip(want, 1, n))
        cuts = np.linspace(0, n, want + 1).round().astype(int)
        cuts = np.unique(cuts)
        for c in cuts[1:]:
            ke.append(int(ks[0] + c))
            zones.append(zi)
    return ie, je, np.array(ke, int), np.array(zones, int)


@dataclass
class Coarse:
    grid: CPGrid
    ie: np.ndarray
    je: np.ndarray
    ke: np.ndarray
    k_zone: np.ndarray

    def groups(self):
        """Iterate coarse cells as (K, J, I, k0, k1, j0, j1, i0, i1)."""
        for K in range(len(self.ke) - 1):
            for J in range(len(self.je) - 1):
                for I in range(len(self.ie) - 1):
                    yield K, J, I, self.ke[K], self.ke[K + 1], self.je[J], self.je[J + 1], self.ie[I], self.ie[I + 1]


def build_coarse(g: CPGrid, ci: int, cj: int, nk_coarse: Optional[List[int]] = None) -> Coarse:
    ie, je, ke, kz = coarse_axes(g, ci, cj, nk_coarse)
    ni, nj, nk = len(ie) - 1, len(je) - 1, len(ke) - 1
    zc = np.empty((nk, 2, nj, 2, ni, 2))
    k0, k1 = ke[:-1], ke[1:] - 1
    j0, j1 = je[:-1], je[1:] - 1
    i0, i1 = ie[:-1], ie[1:] - 1
    for a in range(2):
        jj = j0 if a == 0 else j1
        for b in range(2):
            ii = i0 if b == 0 else i1
            zc[:, 0, :, a, :, b] = g.zc[k0[:, None, None], 0, jj[None, :, None], a, ii[None, None, :], b]
            zc[:, 1, :, a, :, b] = g.zc[k1[:, None, None], 1, jj[None, :, None], a, ii[None, None, :], b]
    V = g.bulk_volume() * (g.actnum > 0)
    act = np.zeros((nk, nj, ni), int)
    blk = np.zeros((nj, ni), int)
    for K in range(nk):
        for J in range(nj):
            for I in range(ni):
                act[K, J, I] = int(V[ke[K]:ke[K + 1], je[J]:je[J + 1], ie[I]:ie[I + 1]].sum() > 0)
    for J in range(nj):
        for I in range(ni):
            sub = g.block[je[J]:je[J + 1], ie[I]:ie[I + 1]].ravel()
            u, c = np.unique(sub, return_counts=True)
            blk[J, I] = u[c.argmax()]
    cg = CPGrid(ni, nj, nk, g.xs[ie], g.ys[je], zc, act, kz.copy(), g.zones, blk, list(g.faults),
                notes=list(g.notes) + [f"Upscaled {g.ni}x{g.nj}x{g.nk} -> {ni}x{nj}x{nk}"], origin=g.origin, angle=g.angle,
                slope=None if g.slope is None else g.slope[np.ix_(je, ie)], zref=g.zref)
    return Coarse(cg, ie, je, ke, kz)


# ------------------------------------------------------------------ block sums
def _block_sum(a: np.ndarray, ke, je, ie) -> np.ndarray:
    """Sum of a (nk, nj, ni) array over the coarse groups."""
    t = np.add.reduceat(a, ke[:-1], axis=0)
    t = np.add.reduceat(t, je[:-1], axis=1)
    return np.add.reduceat(t, ie[:-1], axis=2)


def weighted_mean(c: Coarse, g: CPGrid, values: np.ndarray, weight: np.ndarray) -> np.ndarray:
    v = np.nan_to_num(values.astype(float), nan=0.0)
    w = np.where(np.isnan(values), 0.0, weight)
    num = _block_sum(v * w, c.ke, c.je, c.ie)
    den = _block_sum(w, c.ke, c.je, c.ie)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def majority(c: Coarse, g: CPGrid, values: np.ndarray, weight: np.ndarray) -> np.ndarray:
    out = np.full((len(c.ke) - 1, len(c.je) - 1, len(c.ie) - 1), np.nan)
    for K, J, I, k0, k1, j0, j1, i0, i1 in c.groups():
        v = values[k0:k1, j0:j1, i0:i1].ravel()
        w = weight[k0:k1, j0:j1, i0:i1].ravel()
        m = ~np.isnan(v) & (w > 0)
        if not m.any():
            continue
        u = np.unique(v[m])
        tot = [w[m][v[m] == x].sum() for x in u]
        out[K, J, I] = u[int(np.argmax(tot))]
    return out


# ------------------------------------------------------------------ permeability
def perm_average(c: Coarse, g: CPGrid, k: np.ndarray, weight: np.ndarray, method: str, omega: float = 0.5) -> np.ndarray:
    kk = np.where(np.isnan(k) | (k <= 0), np.nan, k.astype(float))
    m = ~np.isnan(kk) & (weight > 0)
    w = np.where(m, weight, 0.0)
    kz = np.where(m, kk, 1.0)
    den = _block_sum(w, c.ke, c.je, c.ie)
    ok = den > 0
    d = np.where(ok, den, 1.0)
    if method == "arithmetic":
        r = _block_sum(w * kz, c.ke, c.je, c.ie) / d
    elif method == "harmonic":
        r = den / np.maximum(_block_sum(w / kz, c.ke, c.je, c.ie), 1e-300)
    elif method == "geometric":
        r = np.exp(_block_sum(w * np.log(kz), c.ke, c.je, c.ie) / d)
    elif method == "power":
        om = float(omega)
        if abs(om) < 1e-9:
            return perm_average(c, g, k, weight, "geometric")
        r = (_block_sum(w * kz ** om, c.ke, c.je, c.ie) / d) ** (1.0 / om)
    else:
        raise UpscaleError(f"Unknown averaging '{method}'")
    return np.where(ok, r, np.nan)


def _flow_block(kx, ky, kz, dx, dy, dz, act, axis: int) -> float:
    """Effective permeability of one block along ``axis`` (0 = K, 1 = J, 2 = I) by a single-phase steady-state solve.

    Two-point flux on an orthogonal grid, closed lateral faces, unit pressure drop between the two end faces."""
    nk, nj, ni = act.shape
    n = nk * nj * ni
    idx = np.arange(n).reshape(nk, nj, ni)
    K = (kz, ky, kx)[axis]
    L = (dz, dy, dx)                                           # (nk,nj,ni) cell sizes along K / J / I
    A = (dx * dy, dx * dz, dy * dz)                           # face areas normal to K / J / I
    Kd = (kz, ky, kx)
    rows, cols, vals = [], [], []
    diag = np.zeros(n)
    rhs = np.zeros(n)

    def link(a, b, T):
        m = T > 0
        a, b, T = a[m], b[m], T[m]
        rows.extend([a, b])
        cols.extend([b, a])
        vals.extend([-T, -T])
        np.add.at(diag, a, T)
        np.add.at(diag, b, T)

    for ax in range(3):
        sl1 = [slice(None)] * 3
        sl2 = [slice(None)] * 3
        sl1[ax], sl2[ax] = slice(0, -1), slice(1, None)
        s1, s2 = tuple(sl1), tuple(sl2)
        if idx[s1].size == 0:
            continue
        g1 = Kd[ax][s1] * A[ax][s1] / (0.5 * L[ax][s1])
        g2 = Kd[ax][s2] * A[ax][s2] / (0.5 * L[ax][s2])
        with np.errstate(divide="ignore", invalid="ignore"):
            T = np.where((g1 > 0) & (g2 > 0) & act[s1] & act[s2], 1.0 / (1.0 / g1 + 1.0 / g2), 0.0)
        link(idx[s1].ravel(), idx[s2].ravel(), T.ravel())
    # boundary conditions on the faces normal to ``axis``: p = 1 at the first face, 0 at the last
    sl_in = [slice(None)] * 3
    sl_out = [slice(None)] * 3
    sl_in[axis], sl_out[axis] = slice(0, 1), slice(-1, None)
    sin, sout = tuple(sl_in), tuple(sl_out)
    gin = np.where(act[sin], K[sin] * A[axis][sin] / (0.5 * L[axis][sin]), 0.0)
    gout = np.where(act[sout], K[sout] * A[axis][sout] / (0.5 * L[axis][sout]), 0.0)
    ii, io = idx[sin].ravel(), idx[sout].ravel()
    np.add.at(diag, ii, gin.ravel())
    np.add.at(rhs, ii, gin.ravel())
    np.add.at(diag, io, gout.ravel())
    M = np.zeros((n, n))
    if rows:
        np.add.at(M, (np.concatenate(rows), np.concatenate(cols)), np.concatenate(vals))
    M[np.arange(n), np.arange(n)] += diag
    dead = ~act.ravel() | (diag <= 0)
    M[dead, :] = 0.0
    M[:, dead] = 0.0
    M[np.arange(n)[dead], np.arange(n)[dead]] = 1.0
    rhs[dead] = 0.0
    M[np.arange(n), np.arange(n)] += 1e-14 * max(float(diag.max()), 1e-30)       # keeps floating islands solvable
    p = np.linalg.solve(M, rhs)
    q = float((gin.ravel() * (1.0 - p[ii])).sum())
    vol = float((dx * dy * dz)[act].sum())
    length = float(np.mean(L[axis].sum(axis=axis)))
    return q * length * length / max(vol, 1e-300)           # k_eff = Q L / (A_eff dP) with A_eff = active volume / L


def flow_upscale(c: Coarse, g: CPGrid, kx, ky, kz, progress=None, max_cells: int = 20000) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flow-based effective PERMX / PERMY / PERMZ of every coarse cell."""
    nk, nj, ni = len(c.ke) - 1, len(c.je) - 1, len(c.ie) - 1
    if nk * nj * ni > max_cells:
        raise UpscaleError(f"Flow-based upscaling of {nk * nj * ni:,} coarse cells is too slow here (limit {max_cells:,}); use an averaging method or a coarser grid.")
    dxs, dys = np.diff(g.xs), np.diff(g.ys)
    DX = np.broadcast_to(dxs[None, None, :], (g.nk, g.nj, g.ni))
    DY = np.broadcast_to(dys[None, :, None], (g.nk, g.nj, g.ni))
    DZ = np.maximum(g.thickness(), 1e-6)
    act = (g.actnum > 0)
    outx, outy, outz = (np.full((nk, nj, ni), np.nan) for _ in range(3))
    nfall = 0
    tot = nk * nj * ni
    done = 0
    for K, J, I, k0, k1, j0, j1, i0, i1 in c.groups():
        sl = (slice(k0, k1), slice(j0, j1), slice(i0, i1))
        a = act[sl] & np.isfinite(kx[sl]) & (kx[sl] > 0)
        if a.any():
            args = (np.where(a, kx[sl], 0.0), np.where(a, ky[sl], 0.0), np.where(a, kz[sl], 0.0), DX[sl], DY[sl], DZ[sl], a)
            res3 = [_flow_block(*args, axis=ax) for ax in (2, 1, 0)]
            w_ = (DX[sl] * DY[sl] * DZ[sl])[a]
            geo = [float(np.exp((w_ * np.log(np.maximum(kk_[sl][a], 1e-12))).sum() / w_.sum())) for kk_ in (kx, ky, kz)]
            bad_ = [not (np.isfinite(r_) and r_ > 1e-6 * gv) for r_, gv in zip(res3, geo)]      # no connected path through the (clipped) block
            if any(bad_):
                res3 = [gv if b_ else r_ for r_, gv, b_ in zip(res3, geo, bad_)]
                nfall += 1
            outx[K, J, I], outy[K, J, I], outz[K, J, I] = res3
        done += 1
        if progress and done % 50 == 0:
            progress(done / tot)
    flow_upscale.last_fallbacks = nfall
    return outx, outy, outz


# ------------------------------------------------------------------ driver
def upscale_properties(c: Coarse, g: CPGrid, props: Dict[str, "object"], perm_method="arithmetic", omega=0.5, progress=None) -> Dict[str, dict]:
    """Upscale every property that matches the fine grid.  Returns {name: dict(values, kind, unit, method)}."""
    shape = (g.nk, g.nj, g.ni)
    V = g.bulk_volume() * (g.actnum > 0)
    P = {n: v for n, v in props.items() if getattr(v, "values", None) is not None and v.values.shape == shape}
    ntg = P["NTG"].values.astype(float) if "NTG" in P else np.ones(shape)
    poro = P["PORO"].values.astype(float) if "PORO" in P else None
    net = V * np.nan_to_num(ntg, nan=1.0)
    pv = net * np.nan_to_num(poro, nan=0.0) if poro is not None else net
    out: Dict[str, dict] = {}
    perm = {n: P[n].values.astype(float) for n in ("PERMX", "PERMY", "PERMZ") if n in P}
    flow = perm_method == "flow" and {"PERMX", "PERMY", "PERMZ"} <= set(perm)
    if flow:
        fx, fy, fz = flow_upscale(c, g, perm["PERMX"], perm["PERMY"], perm["PERMZ"], progress)
        for n, a in (("PERMX", fx), ("PERMY", fy), ("PERMZ", fz)):
            out[n] = dict(values=a, kind="continuous", unit=P[n].unit, method="flow (geometric fallback in %d clipped cells)" % flow_upscale.last_fallbacks if flow_upscale.last_fallbacks else "flow")
    for n, v in P.items():
        if n in out:
            continue
        a = v.values.astype(float)
        if v.kind == "discrete":
            out[n] = dict(values=majority(c, g, a, V), kind="discrete", unit=v.unit, method="majority")
        elif n.startswith("PERM") and n in perm:
            meth = "geometric" if perm_method == "flow" else perm_method          # flow needs all three components
            out[n] = dict(values=perm_average(c, g, a, net, meth, omega), kind="continuous", unit=v.unit, method=meth)
        elif n.split("_")[0] in SAT_NAMES:
            out[n] = dict(values=weighted_mean(c, g, a, pv), kind="continuous", unit=v.unit, method="pore-volume weighted")
        elif n == "PORO":
            out[n] = dict(values=weighted_mean(c, g, a, net), kind="continuous", unit=v.unit, method="net-volume weighted")
        else:
            out[n] = dict(values=weighted_mean(c, g, a, V), kind="continuous", unit=v.unit, method="volume weighted")
    return out


def _wgeo(k, w) -> float:
    m = np.isfinite(k) & (k > 0) & (w > 0)
    return float(np.exp((w[m] * np.log(k[m])).sum() / w[m].sum())) if m.any() else float("nan")


def qc(c: Coarse, g: CPGrid, fine: Dict[str, "object"], coarse: Dict[str, dict]) -> dict:
    """Bulk volume, net volume and pore volume of the fine and the coarse model (they should agree)."""
    Vf = g.bulk_volume() * (g.actnum > 0)
    cg = c.grid
    Vc = cg.bulk_volume() * (cg.actnum > 0)
    r = dict(cells_fine=int((g.actnum > 0).sum()), cells_coarse=int((cg.actnum > 0).sum()), bulk_fine=float(Vf.sum()), bulk_coarse=float(Vc.sum()))
    if "PORO" in fine and "PORO" in coarse:
        nf = fine["NTG"].values if "NTG" in fine else np.ones(Vf.shape)
        nc = coarse["NTG"]["values"] if "NTG" in coarse else np.ones(Vc.shape)
        r["pv_fine"] = float((Vf * np.nan_to_num(nf, nan=1.0) * np.nan_to_num(fine["PORO"].values, nan=0.0)).sum())
        r["pv_coarse"] = float((Vc * np.nan_to_num(nc, nan=1.0) * np.nan_to_num(coarse["PORO"]["values"], nan=0.0)).sum())
    for n in ("PERMX", "PERMZ"):
        if n in fine and n in coarse:
            r[n + "_fine_geo"] = _wgeo(fine[n].values, Vf)
            r[n + "_coarse_geo"] = _wgeo(coarse[n]["values"], Vc)
    return r
