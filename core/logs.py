"""Well logs: LAS import, MD -> XYZ, blocking into the grid, experimental / fitted variograms.

A log set is stored per well as ``dict(md=[...], curves={name: [...]}, units={name: unit})`` (NaN = null).
MD is the measured depth from the wellhead (KB); positions come from the cumulative length of the well path
(``wells.trajectory``), which is the minimum-curvature MD for survey wells and the polyline length otherwise.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import wells as wl

DEPTH_NAMES = ("DEPT", "DEPTH", "MD", "DEPT.M", "TDEP")


class LogError(Exception):
    pass


# ------------------------------------------------------------------ LAS 2.0
def parse_las(data: bytes) -> Tuple[str, dict]:
    """Parse a LAS 1.2 / 2.0 file.  Returns (well name, dict(md, curves, units)).  Raises :class:`LogError`."""
    txt = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    sect, null, name = None, -999.25, "WELL"
    curves: List[Tuple[str, str]] = []
    rows: List[List[float]] = []
    wrap = False
    for raw in txt.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("~"):
            sect = line[1:2].upper()
            continue
        if sect == "A":
            rows.append([float(t) for t in re.split(r"[\s,]+", line) if t != ""] if _isnum(line) else [])
            continue
        if sect in ("W", "C", "P", "V") and "." in line:
            mn, rest = line.split(".", 1)
            mn = mn.strip().upper()
            parts = rest.split(":", 1)
            head = parts[0]
            unit, _, value = head.partition(" ")
            if sect == "W":
                v = value.strip()
                if mn == "NULL":
                    try:
                        null = float(v)
                    except ValueError:
                        pass
                elif mn == "WELL" and v:
                    name = v
            elif sect == "V" and mn == "WRAP":
                wrap = value.strip().upper().startswith("Y")
            elif sect == "C":
                curves.append((mn, unit.strip()))
    if wrap:
        raise LogError("Wrapped LAS files are not supported - export with WRAP = NO.")
    if not curves:
        raise LogError("No ~C (curve) section found.")
    rows = [r for r in rows if r]
    if not rows:
        raise LogError("No ~A (ASCII data) section found.")
    n = len(curves)
    bad = [r for r in rows if len(r) != n]
    if bad:
        raise LogError(f"{len(bad)} data rows do not have {n} columns.")
    arr = np.array(rows, float)
    arr[np.isclose(arr, null)] = np.nan
    di = next((i for i, (c, _) in enumerate(curves) if c in DEPTH_NAMES), 0)
    md = arr[:, di]
    if np.isnan(md).any():
        raise LogError("The depth curve contains null values.")
    order = np.argsort(md, kind="stable")
    md, arr = md[order], arr[order]
    cv, un = {}, {}
    for i, (c, u) in enumerate(curves):
        if i == di:
            continue
        key = c
        while key in cv:
            key += "_"
        cv[key] = arr[:, i]
        un[key] = u
    return name, dict(md=md, curves=cv, units=un)


def _isnum(line: str) -> bool:
    try:
        [float(t) for t in re.split(r"[\s,]+", line) if t != ""]
        return True
    except ValueError:
        return False


def to_las(well: str, log: dict, null: float = -999.25) -> bytes:
    """Write a LAS 2.0 file (round trip of :func:`parse_las`)."""
    md = np.asarray(log["md"], float)
    names = list(log["curves"])
    out = ["~Version Information", " VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0", " WRAP.   NO  : One line per depth step",
           "~Well Information", f" NULL.   {null} : NULL VALUE", f" WELL.   {well} : WELL", "~Curve Information", " DEPT.m : Measured depth"]
    out += [f" {n}.{log.get('units', {}).get(n, '')} : {n}" for n in names]
    out.append("~ASCII")
    cols = [md] + [np.asarray(log["curves"][n], float) for n in names]
    for r in zip(*cols):
        out.append(" ".join(f"{(null if np.isnan(v) else v):.5g}" if i else f"{v:.3f}" for i, v in enumerate(r)))
    return ("\n".join(out) + "\n").encode()


# ------------------------------------------------------------------ geometry
def path_at_md(well: wl.Well, md: np.ndarray) -> np.ndarray:
    """XYZ (z = TVDSS positive down) at the given measured depths."""
    tr = wl.trajectory(well, step=2.0)
    seg = np.r_[0.0, np.cumsum(np.sqrt((np.diff(tr, axis=0) ** 2).sum(axis=1)))]
    md = np.asarray(md, float)
    return np.column_stack([np.interp(md, seg, tr[:, c]) for c in range(3)])


def to_local(g, x, y):
    """World -> local grid coordinates (inverse of ``CPGrid.to_world``)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if not g.rotated:
        return x, y
    c, s = np.cos(np.deg2rad(g.angle)), np.sin(np.deg2rad(g.angle))
    dx, dy = x - g.origin[0], y - g.origin[1]
    return dx * c + dy * s, -dx * s + dy * c


def locate(g, xyz: np.ndarray) -> np.ndarray:
    """Cell (k, j, i) of each point; -1 where the point is outside the grid or in an inactive / missing cell."""
    u, v = to_local(g, xyz[:, 0], xyz[:, 1])
    i = np.clip(np.searchsorted(g.xs, u, side="right") - 1, 0, g.ni - 1)
    j = np.clip(np.searchsorted(g.ys, v, side="right") - 1, 0, g.nj - 1)
    if g.tilted:                                                   # undo the pillar shear at the sample depth (2 passes)
        sm = 0.25 * (g.slope[:-1, :-1] + g.slope[1:, :-1] + g.slope[:-1, 1:] + g.slope[1:, 1:])
        z = xyz[:, 2]
        u0, v0 = u, v
        for _ in range(2):
            u = u0 - sm[j, i, 0] * (z - g.zref)
            v = v0 - sm[j, i, 1] * (z - g.zref)
            i = np.clip(np.searchsorted(g.xs, u, side="right") - 1, 0, g.ni - 1)
            j = np.clip(np.searchsorted(g.ys, v, side="right") - 1, 0, g.nj - 1)
    else:
        i = np.searchsorted(g.xs, u, side="right") - 1
        j = np.searchsorted(g.ys, v, side="right") - 1
    ok = (i >= 0) & (i < g.ni) & (j >= 0) & (j < g.nj) & (u <= g.xs[-1]) & (v <= g.ys[-1])
    top = g.zc[:, 0].mean(axis=(2, 4))
    base = g.zc[:, 1].mean(axis=(2, 4))
    out = -np.ones((len(xyz), 3), int)
    idx = np.where(ok)[0]
    ii, jj = i[idx], j[idx]
    t, b = top[:, jj, ii], base[:, jj, ii]                         # (nk, n)
    z = xyz[idx, 2][None, :]
    hit = (z >= t) & (z < b) & (g.actnum[:, jj, ii] > 0)
    has = hit.any(axis=0)
    k = hit.argmax(axis=0)
    sel = idx[has]
    out[sel, 0], out[sel, 1], out[sel, 2] = k[has], jj[has], ii[has]
    return out


# ------------------------------------------------------------------ blocking
def block_curve(g, well: wl.Well, log: dict, curve: str, discrete: bool = False, acc: Optional[dict] = None) -> dict:
    """Accumulate one curve of one well into per-cell statistics.  Returns {(k, j, i): list of values}."""
    acc = {} if acc is None else acc
    if curve not in log["curves"]:
        return acc
    md = np.asarray(log["md"], float)
    val = np.asarray(log["curves"][curve], float)
    m = ~np.isnan(val)
    if not m.any():
        return acc
    cells = locate(g, path_at_md(well, md[m]))
    for c, v in zip(cells, val[m]):
        if c[0] < 0:
            continue
        acc.setdefault((int(c[0]), int(c[1]), int(c[2])), []).append(float(v))
    return acc


def blocked_array(g, acc: dict, discrete: bool = False, average: str = "arithmetic") -> np.ndarray:
    """Collapse the per-cell samples: mean (arithmetic / harmonic / geometric) for continuous, mode for discrete."""
    out = np.full((g.nk, g.nj, g.ni), np.nan, np.float32)
    for (k, j, i), v in acc.items():
        a = np.asarray(v)
        if discrete:
            u, c = np.unique(np.round(a), return_counts=True)
            out[k, j, i] = u[c.argmax()]
        elif average == "harmonic" and (a > 0).all():
            out[k, j, i] = len(a) / np.sum(1.0 / a)
        elif average == "geometric" and (a > 0).all():
            out[k, j, i] = np.exp(np.mean(np.log(a)))
        else:
            out[k, j, i] = a.mean()
    return out


def block_wells(g, wells: Dict[str, wl.Well], logs: Dict[str, dict], curve: str, discrete=False, average="arithmetic",
                well_names: Optional[List[str]] = None) -> Tuple[np.ndarray, dict]:
    """Block one curve for all wells that have it.  Returns (array (nk,nj,ni) with NaN = no data, info)."""
    acc: dict = {}
    used, nsamp = [], 0
    for n, lg in logs.items():
        if well_names is not None and n not in well_names:
            continue
        if n not in wells or curve not in lg["curves"]:
            continue
        before = sum(len(v) for v in acc.values())
        block_curve(g, wells[n], lg, curve, discrete, acc)
        after = sum(len(v) for v in acc.values())
        if after > before:
            used.append(n)
            nsamp += after - before
    arr = blocked_array(g, acc, discrete, average)
    return arr, dict(wells=used, cells=len(acc), samples=nsamp)


# ------------------------------------------------------------------ variograms from blocked data
def data_points(g, arr: np.ndarray, zone: Optional[int] = None):
    """Local (u, v), layer index and value of every blocked cell (optionally for one zone)."""
    k, j, i = np.where(~np.isnan(arr))
    if zone is not None:
        keep = g.layer_zone[k] == zone
        k, j, i = k[keep], j[keep], i[keep]
    uc = 0.5 * (g.xs[:-1] + g.xs[1:])
    vc = 0.5 * (g.ys[:-1] + g.ys[1:])
    return uc[i], vc[j], k, arr[k, j, i].astype(float), j, i


def experimental_variogram(g, arr: np.ndarray, zone: Optional[int] = None, direction: str = "horizontal",
                           nlag: int = 12, lag: Optional[float] = None, dz: Optional[float] = None) -> Optional[dict]:
    """Omnidirectional horizontal (same layer) or vertical (same column) semivariogram of blocked values."""
    u, v, k, val, j, i = data_points(g, arr, zone)
    n = len(val)
    if n < 4:
        return None
    if dz is None:
        th = g.thickness()[g.actnum > 0]
        dz = float(th.mean()) if th.size else 1.0
    if direction == "vertical":
        same = (j[:, None] == j[None, :]) & (i[:, None] == i[None, :])
        h = np.abs(k[:, None] - k[None, :]) * dz
    else:
        same = (k[:, None] == k[None, :]) & ~((j[:, None] == j[None, :]) & (i[:, None] == i[None, :]))
        h = np.hypot(u[:, None] - u[None, :], v[:, None] - v[None, :])
    iu = np.triu_indices(n, 1)
    sel = same[iu]
    hh = h[iu][sel]
    gg = 0.5 * (val[:, None] - val[None, :])[iu][sel] ** 2
    if hh.size < 3:
        return None
    if lag is None:
        lag = float(hh.max()) / 2.0 / nlag if direction != "vertical" else dz
    lag = max(lag, 1e-6)
    b = np.minimum((hh / lag).round().astype(int), nlag)
    lags, gam, cnt = [], [], []
    for q in range(1, nlag + 1):
        m = b == q
        if m.sum() >= 3:
            lags.append(float(hh[m].mean()))
            gam.append(float(gg[m].mean()))
            cnt.append(int(m.sum()))
    if len(lags) < 2:
        return None
    return dict(lag=np.array(lags), gamma=np.array(gam), npairs=np.array(cnt), var=float(np.var(val)), direction=direction)


def fit_range(ev: Optional[dict], vtype: str = "spherical", nugget_max: float = 0.3) -> Optional[dict]:
    """Brute-force fit of (range, nugget fraction) of a unit-sill model to an experimental variogram (pair-count weighted)."""
    from .geostat import corr_value
    if ev is None:
        return None
    h, gm, w = ev["lag"], ev["gamma"], ev["npairs"].astype(float)
    sill = max(ev["var"], 1e-12)
    gn = gm / sill
    best = None
    for a in np.linspace(h.min() * 0.5, h.max() * 2.5, 80):
        for nug in np.linspace(0.0, nugget_max, 7):
            model = nug + (1.0 - nug) * (1.0 - corr_value(h / a, vtype))
            err = float((w * (gn - model) ** 2).sum() / w.sum())
            if best is None or err < best[0]:
                best = (err, float(a), float(nug))
    return dict(range=best[1], nugget=best[2], rmse=float(np.sqrt(best[0])))


def suggest_variogram(g, arr: np.ndarray, zone: Optional[int] = None, vtype: str = "spherical") -> dict:
    """Fitted horizontal / vertical ranges from blocked data (falls back to None where the data are insufficient)."""
    hz = fit_range(experimental_variogram(g, arr, zone, "horizontal"), vtype)
    vt = fit_range(experimental_variogram(g, arr, zone, "vertical"), vtype)
    return dict(horizontal=hz, vertical=vt, vtype=vtype)


# ------------------------------------------------------------------ QC
def blocking_qc(g, arr: np.ndarray, log_values: Optional[np.ndarray] = None) -> dict:
    n = int(np.sum(~np.isnan(arr)))
    per_zone = {z.name: int(np.sum(~np.isnan(arr[g.layer_zone == zi]))) for zi, z in enumerate(g.zones)}
    d = dict(cells=n, per_zone=per_zone)
    if n:
        v = arr[~np.isnan(arr)]
        d.update(mean=float(v.mean()), std=float(v.std()), min=float(v.min()), max=float(v.max()))
    if log_values is not None and len(log_values):
        d["log_mean"] = float(np.nanmean(log_values))
    return d


def scale_logs(logs: Dict[str, dict], fz: float) -> Dict[str, dict]:
    """Rescale MD of every log (unit conversion)."""
    out = {}
    for n, lg in logs.items():
        q = dict(lg)
        q["md"] = np.asarray(lg["md"], float) * fz
        out[n] = q
    return out
