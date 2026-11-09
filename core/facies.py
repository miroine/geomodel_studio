"""Facies modelling (Petrel / RMS style): truncated Gaussian simulation, object modelling and facies-driven petrophysics.

* **Truncated Gaussian (TGS)**: a Gaussian random field per zone (variogram per zone) is converted to uniform scores and cut at the cumulative
  facies proportions.  Facies are *ordered* as in the table (neighbouring facies in the table are neighbours in space).  Proportions may change
  linearly from the top to the base of each zone (vertical proportion trend).  Well data (a blocked discrete facies log) condition the field by
  kriging, with the data score placed in the middle of the facies' probability interval, and are then honoured exactly.
* **Objects**: ellipsoids or fluvial channels (parametric meanders or digitized open centerlines) are placed in a background facies
  toward each zone's target volume fraction. Not conditioned to wells.
* **Petrophysics from facies**: PORO, PERMX/Y/Z and NTG drawn per facies (mean / sd, log10 permeability, correlation), with spatial continuity
  from the zone variograms.
"""
from __future__ import annotations

from typing import Dict, List, Optional
import uuid

import numpy as np
from scipy.special import ndtri
from scipy.optimize import least_squares

from . import geostat as gs
from . import facies_trends

METHODS = ["truncated_gaussian", "plurigaussian", "indicator", "objects"]
COLORS = ["#8C8C8C", "#C5A100", "#00A9F4", "#1B998B", "#F46036", "#6A4C93", "#D7263D", "#2251FF"]
VCOLS = ["major", "minor", "vert", "azimuth", "vtype", "nugget"]


class FaciesError(Exception):
    pass


def default_config(grid, nf: int = 3) -> dict:
    names = ["Shale", "Heterolithic", "Sand", "Channel", "Carbonate", "Facies 6", "Facies 7", "Facies 8"]
    fac = [dict(code=i + 1, name=names[i], color=COLORS[i % len(COLORS)], net=i >= 1) for i in range(nf)]
    base = np.array([0.4, 0.2, 0.4] if nf == 3 else np.ones(nf) / nf)
    zones = []
    for z in grid.zones:
        zones.append(dict(zone=z.name, top=[float(x) for x in base], base=[float(x) for x in base], major=1500.0, minor=800.0, vert=8.0,
                          azimuth=45.0, vtype="spherical", nugget=0.0, major2=800.0, minor2=500.0, vert2=3.0, azimuth2=135.0))
    objs = [dict(code=fac[-1]["code"], length=1200.0, width=300.0, thickness=6.0, azimuth=45.0)]
    petro = [dict(code=f["code"], poro=[0.05, 0.12, 0.25, 0.28, 0.15, 0.1, 0.1, 0.1][i], poro_sd=0.02 + 0.005 * i, logk=[-1.0, 0.8, 2.3, 2.8, 1.0, 0.5, 0.5, 0.5][i],
                  logk_sd=0.3, rho=0.7, ntg=1.0 if f["net"] else 0.0) for i, f in enumerate(fac)]
    codes = [f["code"] for f in fac]
    rule = [[codes[0]] * (nf - 1), codes[1:]]                  # nested rule: G1 low -> first facies, G1 high -> G2 splits the others
    return dict(method="truncated_gaussian", seed=42, trend=False, vol_weight=True, rule=rule, nmax=16,
                 background=fac[0]["code"], azimuth_sd=10.0, facies=fac, zones=zones,
                objects=objs, petro=petro, cond="", kykx=1.0)


def normalise(cfg: dict, grid) -> dict:
    """Fill keys that older saved configurations lack."""
    d = default_config(grid, len(cfg["facies"]))
    for k in ("vol_weight", "rule", "nmax"):
        cfg.setdefault(k, d[k])
    for obj in cfg.get("objects", []):
        obj.setdefault("id", uuid.uuid4().hex[:12])
        obj.setdefault("shape", "ellipsoid")
        obj.setdefault("amplitude", 200.0)
        obj.setdefault("wavelength", 800.0)
        obj.setdefault("centerline", [])
    for z in cfg["zones"]:
        for k in ("major2", "minor2", "vert2", "azimuth2"):
            z.setdefault(k, d["zones"][0][k])
    return cfg


def check_config(cfg: dict, grid) -> List[str]:
    errs = []
    fac = cfg["facies"]
    if len(fac) < 2:
        errs.append("Define at least two facies.")
    if len({f["code"] for f in fac}) != len(fac):
        errs.append("Facies codes must be unique.")
    names = {z.name for z in grid.zones}
    for z in cfg["zones"]:
        if z["zone"] not in names:
            errs.append(f"Zone '{z['zone']}' is not in the grid.")
            continue
        for key in ("top", "base"):
            p = np.asarray(z[key], float)
            if len(p) != len(fac) or (p < 0).any() or p.sum() <= 0:
                errs.append(f"Zone {z['zone']}: {key} proportions must be {len(fac)} non-negative numbers with a positive sum.")
        if z["major"] <= 0 or z["minor"] <= 0 or z["vert"] <= 0:
            errs.append(f"Zone {z['zone']}: variogram ranges must be > 0.")
    if cfg["method"] == "plurigaussian":
        codes = {f["code"] for f in fac}
        R = cfg.get("rule") or []
        if not R or any(len(r) != len(R[0]) for r in R) or {int(c) for r in R for c in r} - codes:
            errs.append("Truncation rule: a rectangular table of facies codes from the facies table is required.")
        else:
            used = {int(c) for r in R for c in r}
            for z in cfg["zones"]:
                p = np.asarray(z["top"], float)
                if len(p) == len(fac) and p.sum() > 0:
                    _, _, ach = band_probabilities(R, p / p.sum(), [f["code"] for f in fac])
                    if np.abs(ach - p / p.sum()).max() > 0.05:
                        errs.append(f"Zone {z['zone']}: the truncation rule cannot reproduce the proportions (max error {np.abs(ach - p / p.sum()).max():.2f}) - "
                                    "give every facies a share of the rule table that can match its proportion.")
                        break
                miss = [f["name"] for f, q in zip(fac, p) if q > 0 and f["code"] not in used]
                if miss:
                    errs.append(f"Zone {z['zone']}: facies {', '.join(miss)} have a proportion but do not appear in the truncation rule.")
                    break
    if cfg["method"] == "objects":
        codes = {f["code"] for f in fac}
        if cfg["background"] not in codes:
            errs.append("Background facies is not in the facies table.")
        for o in cfg["objects"]:
            if o["code"] not in codes or o["code"] == cfg["background"]:
                errs.append("Object facies must be in the table and different from the background.")
            if min(o["length"], o["width"], o["thickness"]) <= 0:
                errs.append("Object dimensions must be > 0.")
            shape = o.get("shape", "ellipsoid")
            if shape not in ("ellipsoid", "channel", "digitized_channel"):
                errs.append("Unknown object shape.")
            for key in ("length", "width", "thickness", "azimuth"):
                if not np.isfinite(o[key]):
                    errs.append(f"Object {key} must be finite.")
            if shape == "channel":
                if not np.isfinite(o.get("amplitude", 200.0)) or o.get("amplitude", 200.0) < 0:
                    errs.append("Channel amplitude must be finite and non-negative.")
                if not np.isfinite(o.get("wavelength", 800.0)) or o.get("wavelength", 800.0) <= 0:
                    errs.append("Channel wavelength must be finite and > 0.")
            if shape == "digitized_channel":
                pts = np.asarray(o.get("centerline", []), float)
                if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 2 or not np.isfinite(pts).all():
                    errs.append("Digitized channels require at least two finite XY centerline vertices.")
                elif not (np.linalg.norm(np.diff(pts, axis=0), axis=1) > 0).any():
                    errs.append("Channel centerline must contain distinct vertices.")
    return errs


def channel_distance(u, v, points):
    """Shortest plan-view distance to an open polyline, including its end caps."""
    distance2 = np.full(np.broadcast_shapes(np.shape(u), np.shape(v)), np.inf)
    for start, end in zip(points[:-1], points[1:]):
        du, dv = end - start
        norm = du * du + dv * dv
        if norm == 0:
            continue
        t = np.clip(((u - start[0]) * du + (v - start[1]) * dv) / norm, 0, 1)
        distance2 = np.minimum(distance2, (u - start[0] - t * du) ** 2 + (v - start[1] - t * dv) ** 2)
    return np.sqrt(distance2)


def _props(z: dict, f: np.ndarray, trend: bool) -> np.ndarray:
    """Proportions at relative position f (0 top .. 1 base) of the zone; shape (n, len(f))."""
    a, b = np.asarray(z["top"], float), np.asarray(z["base"] if trend else z["top"], float)
    a, b = a / a.sum(), b / b.sum()
    return a[:, None] * (1 - f)[None] + b[:, None] * f[None]


def _zone_layers(grid, zi):
    ks = np.where(grid.layer_zone == zi)[0]
    return ks, (np.arange(ks.size) + 0.5) / max(ks.size, 1)


def _spacing(grid, ks):
    th = grid.thickness()
    am = (grid.actnum > 0)[ks]
    dz = max(float(th[ks][am].mean()) if am.any() else 1.0, 1e-3)
    return float(np.mean(np.diff(grid.xs))), float(np.mean(np.diff(grid.ys))), dz


def wrank_uniform(f: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Uniform scores of ``f`` such that the *weighted* (bulk-volume) distribution is uniform."""
    flat, wf = f.ravel(), np.maximum(w.ravel(), 0.0)
    if wf.sum() <= 0:
        return gs.rank_uniform(f)
    o = np.argsort(flat, kind="stable")
    cw = np.cumsum(wf[o])
    u = np.empty(flat.size)
    u[o] = (cw - 0.5 * wf[o]) / cw[-1]
    return u.reshape(f.shape)


def _scores(f, w, cfg):
    return wrank_uniform(f, w) if cfg.get("vol_weight", True) else gs.rank_uniform(f)


def simulate_tgs(grid, cfg: dict, cond: Optional[np.ndarray] = None, progress=None, offsets=None) -> np.ndarray:
    """Truncated Gaussian facies realisation (nk, nj, ni) of facies codes (0 = not simulated)."""
    codes = np.array([f["code"] for f in cfg["facies"]])
    nf = len(codes)
    out = np.zeros((grid.nk, grid.nj, grid.ni), np.float32)
    uc = 0.5 * (grid.xs[:-1] + grid.xs[1:])
    vc = 0.5 * (grid.ys[:-1] + grid.ys[1:])
    zi_of = {z.name: i for i, z in enumerate(grid.zones)}
    vol = grid.bulk_volume() * (grid.actnum > 0)
    for n, z in enumerate(cfg["zones"]):
        zi = zi_of[z["zone"]]
        ks, fr = _zone_layers(grid, zi)
        if ks.size == 0:
            continue
        dx, dy, dz = _spacing(grid, ks)
        rng = np.random.default_rng(np.random.SeedSequence([int(cfg["seed"]), zi]))
        vp = dict(vtype=z["vtype"], major=z["major"], minor=z["minor"], vert=z["vert"], nugget=z.get("nugget", 0.0))
        rel = gs.rel_angle(z["azimuth"], grid.angle)
        f = gs.gaussian_field((ks.size, grid.nj, grid.ni), (dx, dy, dz), vp, rng, rel)
        base = _props(z, fr, bool(cfg["trend"]))[:, :, None, None]
        probs = facies_trends.probabilities(base, offsets[:, ks]) if offsets is not None else base
        cum = np.cumsum(probs, axis=0)
        cum = np.clip(cum / cum[-1:], 0.0, 1.0)
        lo = np.concatenate([np.zeros_like(cum[:1]), cum[:-1]], axis=0)
        kk = jj = ii = fc = None
        if cond is not None:
            sub = cond[ks]
            kk, jj, ii = np.where(~np.isnan(sub))
            if kk.size:
                idx = np.array([int(np.argmin(np.abs(codes - c))) if c in codes else -1 for c in np.rint(sub[kk, jj, ii])])
                good = idx >= 0
                kk, jj, ii, idx = kk[good], jj[good], ii[good], idx[good]
                if offsets is not None:
                    mid = np.clip(0.5 * (lo[idx, kk, jj, ii] + cum[idx, kk, jj, ii]), 1e-4, 1 - 1e-4)
                else:
                    mid = np.clip(0.5 * (lo[idx, kk, 0, 0] + cum[idx, kk, 0, 0]), 1e-4, 1 - 1e-4)
                if kk.size:
                    f = gs.condition_field(f, kk, jj, ii, ndtri(mid), uc, vc, dz, vp, rel)
                fc = idx
        u = _scores(f, vol[ks], cfg)
        fi = (u[None] >= cum[:-1]).sum(axis=0)
        if fc is not None and kk is not None and kk.size:
            fi[kk, jj, ii] = fc
        out[ks] = codes[fi]
        if progress:
            progress((n + 1) / len(cfg["zones"]))
    return out


def simulate_objects(grid, cfg: dict, progress=None) -> np.ndarray:
    """Object model: ellipsoids of the object facies in the background facies."""
    out = np.zeros((grid.nk, grid.nj, grid.ni), np.float32)
    uc = 0.5 * (grid.xs[:-1] + grid.xs[1:])
    vc = 0.5 * (grid.ys[:-1] + grid.ys[1:])
    U, V = np.meshgrid(uc, vc)
    zc = grid.center_depth()
    vol = grid.bulk_volume() * (grid.actnum > 0)
    codes = [f["code"] for f in cfg["facies"]]
    zi_of = {z.name: i for i, z in enumerate(grid.zones)}
    for n, z in enumerate(cfg["zones"]):
        zi = zi_of[z["zone"]]
        ks, fr = _zone_layers(grid, zi)
        if ks.size == 0:
            continue
        rng = np.random.default_rng(np.random.SeedSequence([int(cfg["seed"]), zi, 7]))
        out[ks] = cfg["background"]
        p = np.asarray(z["top"], float)
        p = p / p.sum()
        vz = vol[ks]
        tot = float(vz.sum())
        if tot <= 0:
            continue
        act = np.argwhere(vz > 0)
        for o in cfg["objects"]:
            target = float(p[codes.index(o["code"])]) * tot
            filled = float(vz[out[ks] == o["code"]].sum())
            tries = 0
            limit = 20000 if o.get("shape", "ellipsoid") == "ellipsoid" else 2000
            while filled < target and tries < limit:
                tries += 1
                k0, j0, i0 = act[rng.integers(len(act))]
                L, W, T = (o[a] * np.exp(rng.normal(0, 0.2)) for a in ("length", "width", "thickness"))
                az = np.deg2rad(gs.rel_angle(o["azimuth"] + rng.normal(0, cfg.get("azimuth_sd", 10.0)), grid.angle))
                cu, cv, cz = uc[i0], vc[j0], zc[ks[k0], j0, i0]
                shape = o.get("shape", "ellipsoid")
                points = None
                if shape == "channel":
                    wavelength = o.get("wavelength", 800.0)
                    spacing = max(min(np.min(np.diff(grid.xs)), np.min(np.diff(grid.ys)), W / 4, wavelength / 32), 1e-6)
                    count = int(np.ceil(L / spacing)) + 1
                    if count > 10000:
                        raise FaciesError("Channel length/wavelength requires too many centerline samples; increase wavelength or reduce length.")
                    a = np.linspace(-L / 2, L / 2, max(count, 2))
                    b = o.get("amplitude", 200.0) * np.sin(2 * np.pi * a / wavelength + rng.uniform(0, 2 * np.pi))
                    points = np.column_stack((cu + a * np.cos(az) - b * np.sin(az),
                                              cv + a * np.sin(az) + b * np.cos(az)))
                elif shape == "digitized_channel":
                    points = np.asarray(o["centerline"], float)
                    if grid.rotated:
                        points = points - np.asarray(grid.origin)
                        ca, sa = np.cos(np.deg2rad(grid.angle)), np.sin(np.deg2rad(grid.angle))
                        points = points @ np.array([[ca, -sa], [sa, ca]])
                if points is None:
                    r = 0.5 * max(L, W)
                    jm = (np.abs(vc - cv) <= r + 2 * (vc[1] - vc[0] if len(vc) > 1 else 0))
                    im = (np.abs(uc - cu) <= r + 2 * (uc[1] - uc[0] if len(uc) > 1 else 0))
                else:
                    jm = (vc >= points[:, 1].min() - W / 2) & (vc <= points[:, 1].max() + W / 2)
                    im = (uc >= points[:, 0].min() - W / 2) & (uc <= points[:, 0].max() + W / 2)
                js, is_ = np.where(jm)[0], np.where(im)[0]
                if js.size == 0 or is_.size == 0:
                    continue
                du = U[np.ix_(js, is_)] - cu
                dv = V[np.ix_(js, is_)] - cv
                a_ = du * np.cos(az) + dv * np.sin(az)
                b_ = -du * np.sin(az) + dv * np.cos(az)
                q = ((a_ / (0.5 * L)) ** 2 + (b_ / (0.5 * W)) ** 2 if points is None else
                     (channel_distance(U[np.ix_(js, is_)], V[np.ix_(js, is_)], points) / (W / 2)) ** 2)
                dzz = (zc[ks][:, js][:, :, is_] - cz) / (0.5 * T)
                inside = (q[None] + dzz ** 2 <= 1.0) & (vz[:, js][:, :, is_] > 0)
                sub = out[ks][:, js][:, :, is_]
                new = inside & (sub != o["code"])
                if not new.any():
                    continue
                filled += float(vz[:, js][:, :, is_][new].sum())
                sub[inside] = o["code"]
                tmp = out[ks]
                tmp[np.ix_(np.arange(ks.size), js, is_)] = sub
                out[ks] = tmp
            if o.get("shape", "ellipsoid") != "ellipsoid" and filled < target:
                raise FaciesError(f"Zone {z['zone']}: channel placement reached {filled / tot:.1%}, below target {target / tot:.1%}. "
                                  "Reduce the target or increase channel width/thickness/coverage.")
        if progress:
            progress((n + 1) / len(cfg["zones"]))
    return out



def band_probabilities(rule: np.ndarray, p: np.ndarray, codes) -> tuple:
    """Band probabilities (a for G1 rows, b for G2 columns) of a rectangular truncation rule so that, for independent fields, the facies
    probabilities match ``p`` as well as possible.  Returns (a, b, achieved facies probabilities)."""
    R = np.asarray(rule, int)
    n1, n2 = R.shape
    codes = list(codes)
    M = np.zeros((len(codes), n1, n2))
    for q, c in enumerate(codes):
        M[q] = (R == c)

    def split(x):
        e1, e2 = np.exp(x[:n1] - x[:n1].max()), np.exp(x[n1:] - x[n1:].max())
        return e1 / e1.sum(), e2 / e2.sum()

    def res(x):
        a, b = split(x)
        return np.einsum("qij,i,j->q", M, a, b) - p

    best = None
    rng = np.random.default_rng(0)
    for t in range(6):
        x0 = rng.normal(0, 0.5, n1 + n2)
        r = least_squares(res, x0)
        if best is None or r.cost < best.cost:
            best = r
        if r.cost < 1e-14:
            break
    a, b = split(best.x)
    return a, b, np.einsum("qij,i,j->q", M, a, b)


def simulate_plurigaussian(grid, cfg: dict, progress=None) -> np.ndarray:
    """Plurigaussian simulation: two independent Gaussian fields and a rectangular truncation rule (table of facies codes)."""
    codes = [f["code"] for f in cfg["facies"]]
    R = np.asarray(cfg["rule"], int)
    out = np.zeros((grid.nk, grid.nj, grid.ni), np.float32)
    zi_of = {z.name: i for i, z in enumerate(grid.zones)}
    vol = grid.bulk_volume() * (grid.actnum > 0)
    for n, z in enumerate(cfg["zones"]):
        zi = zi_of[z["zone"]]
        ks, _ = _zone_layers(grid, zi)
        if ks.size == 0:
            continue
        dx, dy, dz = _spacing(grid, ks)
        p = np.asarray(z["top"], float)
        p = p / p.sum()
        a, b, _ = band_probabilities(R, p, codes)
        ss = np.random.SeedSequence([int(cfg["seed"]), zi, 3])
        r1, r2 = (np.random.default_rng(s_) for s_ in ss.spawn(2))
        shape = (ks.size, grid.nj, grid.ni)
        f1 = gs.gaussian_field(shape, (dx, dy, dz), dict(vtype=z["vtype"], major=z["major"], minor=z["minor"], vert=z["vert"], nugget=z.get("nugget", 0.0)),
                               r1, gs.rel_angle(z["azimuth"], grid.angle))
        f2 = gs.gaussian_field(shape, (dx, dy, dz), dict(vtype=z["vtype"], major=z.get("major2", z["major"]), minor=z.get("minor2", z["minor"]),
                                                          vert=z.get("vert2", z["vert"]), nugget=z.get("nugget", 0.0)),
                               r2, gs.rel_angle(z.get("azimuth2", z["azimuth"]), grid.angle))
        u1, u2 = _scores(f1, vol[ks], cfg), _scores(f2, vol[ks], cfg)
        i1 = np.minimum((u1[None] >= np.cumsum(a)[:-1, None, None, None]).sum(axis=0), R.shape[0] - 1)
        i2 = np.minimum((u2[None] >= np.cumsum(b)[:-1, None, None, None]).sum(axis=0), R.shape[1] - 1)
        out[ks] = R[i1, i2]
        if progress:
            progress((n + 1) / len(cfg["zones"]))
    return out


def _sk_weights(dpos: np.ndarray, tpos: np.ndarray, vp: dict, nmax: int):
    """Simple-kriging weights of the ``nmax`` nearest data within one range for every target: (idx, w, valid), each (n, m)."""
    from scipy.spatial import cKDTree
    nug = float(np.clip(vp.get("nugget", 0.0), 0.0, 0.99))
    nd, nt = len(dpos), len(tpos)
    m = min(nmax, nd)
    dist, idx = cKDTree(dpos).query(tpos, k=m, distance_upper_bound=1.0)
    dist, idx = dist.reshape(nt, m), idx.reshape(nt, m)
    valid = np.isfinite(dist)
    iic = np.where(valid, idx, 0)
    P = dpos[iic]
    H = np.sqrt(((P[:, :, None, :] - P[:, None, :, :]) ** 2).sum(-1))
    eye = np.eye(m)[None]
    C = (1 - nug) * gs.corr_value(H, vp["vtype"]) + nug * eye
    C = np.where(valid[:, :, None] & valid[:, None, :], C, eye) + 1e-9 * eye
    c0 = np.where(valid, (1 - nug) * gs.corr_value(np.where(valid, dist, 2.0), vp["vtype"]), 0.0)
    w = np.linalg.solve(C, c0[:, :, None])[:, :, 0]
    return iic, np.where(valid, w, 0.0), valid


def simulate_sis(grid, cfg: dict, cond: Optional[np.ndarray] = None, progress=None, offsets=None) -> np.ndarray:
    """Sequential indicator simulation of the facies (active cells), one variogram per zone shared by all indicators.

    Random path; each visited cell gets the local probabilities p_c = p0_c + sum w_i (I_c(x_i) - p0_c(x_i)) from simple indicator kriging of
    the data and previously simulated cells within one range (order relations corrected by clipping and renormalising).  For speed, cells are
    visited in batches that grow along the path; cells of one batch do not see each other."""
    codes = np.array([f["code"] for f in cfg["facies"]])
    nf = len(codes)
    out = np.zeros((grid.nk, grid.nj, grid.ni), np.float32)
    uc = 0.5 * (grid.xs[:-1] + grid.xs[1:])
    vc = 0.5 * (grid.ys[:-1] + grid.ys[1:])
    act = grid.actnum > 0
    zi_of = {z.name: i for i, z in enumerate(grid.zones)}
    nmax = int(cfg.get("nmax", 16))
    for n, z in enumerate(cfg["zones"]):
        zi = zi_of[z["zone"]]
        ks, fr = _zone_layers(grid, zi)
        if ks.size == 0:
            continue
        dx, dy, dz = _spacing(grid, ks)
        rng = np.random.default_rng(np.random.SeedSequence([int(cfg["seed"]), zi, 5]))
        vp = dict(vtype=z["vtype"], major=z["major"], minor=z["minor"], vert=z["vert"], nugget=z.get("nugget", 0.0))
        rel = gs.rel_angle(z["azimuth"], grid.angle)
        kk, jj, ii = np.where(act[ks])
        N = kk.size
        if N == 0:
            continue
        pos = gs._scaled(uc[ii], vc[jj], kk * dz, vp, rel)
        p0 = _props(z, fr, bool(cfg["trend"]))[:, kk]                                  # (nf, N) prior proportions per cell
        p0 = facies_trends.probabilities(p0, offsets[:, ks][:, kk, jj, ii]) if offsets is not None else p0 / p0.sum(axis=0, keepdims=True)
        state = -np.ones(N, int)
        if cond is not None:
            d = cond[ks][kk, jj, ii]
            has = ~np.isnan(d)
            for q, c in enumerate(codes):
                state[has & (np.rint(np.where(has, d, -1)) == c)] = q
        hard = state >= 0
        order = rng.permutation(np.where(~hard)[0])
        cap = max(200, N // 40)
        pos_i, chunk = 0, 32
        while pos_i < len(order):
            sel = order[pos_i:pos_i + chunk]
            known = np.where(state >= 0)[0]
            if known.size:
                iic, w, valid = _sk_weights(pos[known], pos[sel], vp, nmax)
                kn = known[iic]                                                         # global cell index of each neighbour
                ind = (state[kn][:, :, None] == np.arange(nf)[None, None, :]).astype(float)       # (n, m, nf)
                resid = ind - p0[:, kn].transpose(1, 2, 0)
                prob = p0[:, sel].T + np.einsum("nm,nmf->nf", np.where(valid, w, 0.0), resid)
            else:
                prob = p0[:, sel].T.copy()
            prob = np.clip(prob, 0.0, None)
            sm = prob.sum(axis=1, keepdims=True)
            prob = np.where(sm > 1e-12, prob / np.where(sm > 1e-12, sm, 1.0), p0[:, sel].T)
            u = rng.random(len(sel))
            state[sel] = np.minimum((u[:, None] >= np.cumsum(prob, axis=1)).sum(axis=1), nf - 1)
            pos_i += chunk
            chunk = min(int(chunk * 1.5) + 1, cap)
        tmp = out[ks]
        tmp[kk, jj, ii] = codes[state]
        out[ks] = tmp
        if progress:
            progress((n + 1) / len(cfg["zones"]))
    return out


def simulate(grid, cfg: dict, cond: Optional[np.ndarray] = None, progress=None, surfaces=None) -> np.ndarray:
    errs = check_config(cfg, grid)
    if errs:
        raise FaciesError(" ".join(errs))
    trends = cfg.get("probability_trends", {})
    enabled = any(t.get(k) for t in trends.values() for k in ("depth_enabled", "map_enabled", "distance_enabled"))
    if enabled and cfg["method"] not in ("truncated_gaussian", "indicator"):
        raise FaciesError("Facies probability trends are supported only by truncated Gaussian and indicator simulation.")
    try:
        offsets = facies_trends.offsets(grid, cfg, surfaces) if enabled else None
    except (ValueError, TypeError, KeyError) as exc:
        raise FaciesError(str(exc)) from exc
    if cfg["method"] == "objects":
        return simulate_objects(grid, cfg, progress)
    if cfg["method"] == "plurigaussian":
        return simulate_plurigaussian(grid, cfg, progress)
    if cfg["method"] == "indicator":
        try:
            return simulate_sis(grid, cfg, cond, progress, offsets)
        except ValueError as exc:
            raise FaciesError(str(exc)) from exc
    try:
        return simulate_tgs(grid, cfg, cond, progress, offsets)
    except ValueError as exc:
        raise FaciesError(str(exc)) from exc


def legend(cfg: dict) -> dict:
    return {str(f["code"]): f["name"] for f in cfg["facies"]}


def proportions(grid, facies: np.ndarray, cfg: dict) -> List[dict]:
    """Volume proportions per zone (rows) and facies, active cells only."""
    vol = grid.bulk_volume() * (grid.actnum > 0)
    rows = []
    for zi, z in enumerate(grid.zones):
        m = grid.layer_zone == zi
        w = vol[m]
        tot = float(w.sum())
        r = {"Zone": z.name}
        for f in cfg["facies"]:
            r[f["name"]] = float(w[facies[m] == f["code"]].sum() / tot) if tot > 0 else float("nan")
        rows.append(r)
    return rows


def vertical_proportions(grid, facies: np.ndarray, cfg: dict) -> Dict[str, np.ndarray]:
    """Fraction of each facies per layer (active cells)."""
    act = grid.actnum > 0
    out = {}
    for f in cfg["facies"]:
        out[f["name"]] = np.array([float(((facies[k] == f["code"]) & act[k]).sum()) / max(int(act[k].sum()), 1) for k in range(grid.nk)])
    return out


def well_proportions(grid, blocked: np.ndarray, cfg: dict) -> Dict[str, List[float]]:
    """Facies proportions of the blocked well data per zone (to compare with the model / set the proportion table)."""
    out = {}
    codes = [f["code"] for f in cfg["facies"]]
    for zi, z in enumerate(grid.zones):
        d = blocked[grid.layer_zone == zi]
        d = np.rint(d[~np.isnan(d)])
        out[z.name] = [float((d == c).mean()) if d.size else float("nan") for c in codes]
    return out


# ------------------------------------------------------------------ petrophysics from facies
def petrophysics(grid, facies: np.ndarray, cfg: dict, use_kvkh: bool = True) -> Dict[str, dict]:
    """PORO / PERMX / PERMY / PERMZ / NTG drawn per facies with the zone variograms for spatial continuity."""
    shape = (grid.nk, grid.nj, grid.ni)
    poro, perm, ntg = np.zeros(shape), np.ones(shape), np.zeros(shape)
    pt = {r["code"]: r for r in cfg["petro"]}
    zi_of = {z.name: i for i, z in enumerate(grid.zones)}
    for z in cfg["zones"]:
        zi = zi_of[z["zone"]]
        ks, _ = _zone_layers(grid, zi)
        if ks.size == 0:
            continue
        dx, dy, dz = _spacing(grid, ks)
        rng = np.random.default_rng(np.random.SeedSequence([int(cfg["seed"]), zi, 99]))
        vp = dict(vtype=z["vtype"], major=z["major"], minor=z["minor"], vert=z["vert"], nugget=z.get("nugget", 0.0))
        rel = gs.rel_angle(z["azimuth"], grid.angle)
        f1 = gs.gaussian_field((ks.size, grid.nj, grid.ni), (dx, dy, dz), vp, rng, rel)
        f2 = gs.gaussian_field((ks.size, grid.nj, grid.ni), (dx, dy, dz), vp, rng, rel)
        fz = facies[ks]
        P, K, N = np.zeros(fz.shape), np.ones(fz.shape), np.zeros(fz.shape)
        for code, r in pt.items():
            m = fz == code
            if not m.any():
                continue
            rho = float(np.clip(r["rho"], -0.99, 0.99))
            g2 = rho * f1 + np.sqrt(1 - rho * rho) * f2
            P[m] = np.clip(r["poro"] + r["poro_sd"] * f1[m], 0.001, 0.6)
            K[m] = 10.0 ** (r["logk"] + r["logk_sd"] * g2[m])
            N[m] = r["ntg"]
        poro[ks], perm[ks], ntg[ks] = P, K, N
    kv = np.ones(shape)
    if use_kvkh:
        for zi, z in enumerate(grid.zones):
            kv[grid.layer_zone == zi] = z.kvkh
    return dict(PORO=dict(values=poro, kind="continuous", unit="frac"), PERMX=dict(values=perm, kind="continuous", unit="mD"),
                PERMY=dict(values=perm * float(cfg.get("kykx", 1.0)), kind="continuous", unit="mD"),
                PERMZ=dict(values=perm * kv, kind="continuous", unit="mD"), NTG=dict(values=np.clip(ntg, 0, 1), kind="continuous", unit="frac"))
