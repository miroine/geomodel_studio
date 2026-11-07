"""Property analysis on the grid: statistics, histograms / CDFs, crossplots, vertical profiles and 2D maps, with
splitting (zone, fault block, layer, fluid) and filtering (value range, net flag)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np

SPLITS = ["none", "zone", "fault block", "layer", "fluid", "region", "segment"]   # fluid / region / segment need FLUID / REGION / SEGMENT
MAP_MODES = ["average", "thickness-weighted", "sum", "min", "max"]
FLUID_NAMES = {1: "gas", 2: "oil", 3: "water"}


class AnalysisError(Exception):
    pass


def get(props, name, grid):
    if name not in props:
        raise AnalysisError(f"Property '{name}' not found.")
    v = props[name].values
    if v.shape != (grid.nk, grid.nj, grid.ni):
        raise AnalysisError(f"Property '{name}' does not fit the grid.")
    return v.astype(float)


def selection(grid, props, filters: Optional[List[dict]] = None, zones: Optional[List[str]] = None, k_range=None) -> np.ndarray:
    """Boolean cell mask: active cells in the chosen zones / layers that pass every filter dict(prop, lo, hi)."""
    m = grid.actnum > 0
    if zones:
        zi = [i for i, z in enumerate(grid.zones) if z.name in zones]
        m = m & np.isin(grid.layer_zone, zi)[:, None, None]
    if k_range:
        k0, k1 = k_range
        kk = np.arange(grid.nk)
        m = m & ((kk >= k0) & (kk <= k1))[:, None, None]
    for f in filters or []:
        v = get(props, f["prop"], grid)
        lo = -np.inf if f.get("lo") is None else float(f["lo"])
        hi = np.inf if f.get("hi") is None else float(f["hi"])
        m = m & (v >= lo) & (v <= hi)
    return m


def labels(grid, props, split: str, mask) -> Tuple[np.ndarray, List[str]]:
    """Integer group per cell (0..n-1) and group names."""
    shape = (grid.nk, grid.nj, grid.ni)
    if split == "none":
        return np.zeros(shape, int), ["All"]
    if split == "zone":
        return np.broadcast_to(grid.layer_zone[:, None, None], shape).copy(), [z.name for z in grid.zones]
    if split == "fault block":
        b = grid.block_array() - 1
        return b, [f"Block {i + 1}" for i in range(int(grid.block.max()))]
    if split == "layer":
        return np.broadcast_to(np.arange(grid.nk)[:, None, None], shape).copy(), [f"L{k + 1}" for k in range(grid.nk)]
    disc = {"fluid": "FLUID", "region": "REGION", "segment": "SEGMENT"}.get(split, split[5:] if split.startswith("prop:") else None)
    if disc:
        if disc not in props:
            raise AnalysisError(f"Create {disc} first ({'Volumetrics: Store as properties, or set up the contacts' if disc == 'FLUID' else 'Properties page: Planes & regions'}).")
        pr = props[disc]
        v = np.rint(get(props, disc, grid)).astype(int)
        legend = dict(pr.legend) or ({str(k): n for k, n in FLUID_NAMES.items()} if disc == "FLUID" else {})
        vals = sorted(int(u) for u in np.unique(v[mask])) if mask is not None and np.any(mask) else []
        if not vals:
            return np.zeros(v.shape, int), ["(none)"]
        idx = np.searchsorted(vals, v)
        idx = np.clip(idx, 0, len(vals) - 1)
        lab = np.where(np.isin(v, vals), idx, 0)
        return lab, [legend.get(str(u), f"{disc} {u}") for u in vals]
    raise AnalysisError(f"Unknown split '{split}'")


def _wstats(v, w):
    if v.size == 0:
        return dict(count=0)
    mean = float(np.average(v, weights=w)) if w.sum() > 0 else float(v.mean())
    p10, p50, p90 = np.percentile(v, [10, 50, 90])
    return dict(count=int(v.size), min=float(v.min()), mean=mean, std=float(np.sqrt(np.average((v - mean) ** 2, weights=w))) if w.sum() > 0 else float(v.std()),
                p10=float(p10), p50=float(p50), p90=float(p90), max=float(v.max()))


def stats_table(grid, props, name, split="zone", mask=None) -> List[dict]:
    v = get(props, name, grid)
    m = selection(grid, props) if mask is None else mask
    m = m & np.isfinite(v)
    lab, names = labels(grid, props, split, m)
    w = grid.bulk_volume()
    rows = []
    for gi, gn in enumerate(names):
        s = m & (lab == gi)
        if not s.any():
            continue
        r = dict(group=gn)
        r.update(_wstats(v[s], w[s]))
        r["volume"] = float(w[s].sum())
        rows.append(r)
    if split != "none":
        s = m
        r = dict(group="All")
        r.update(_wstats(v[s], w[s]))
        r["volume"] = float(w[s].sum())
        rows.append(r)
    return rows


def groups_values(grid, props, name, split, mask, max_groups=12) -> Dict[str, np.ndarray]:
    v = get(props, name, grid)
    m = mask & np.isfinite(v)
    lab, names = labels(grid, props, split, m)
    out = {}
    for gi, gn in enumerate(names):
        s = m & (lab == gi)
        if s.any():
            out[gn] = v[s]
    if len(out) > max_groups:
        keep = sorted(out, key=lambda n: -out[n].size)[:max_groups]
        out = {n: out[n] for n in keep}
    return out


def cdf(v) -> Tuple[np.ndarray, np.ndarray]:
    v = np.sort(np.asarray(v, float))
    v = v[np.isfinite(v)]
    return v, (np.arange(1, v.size + 1) / max(v.size, 1))


def crossplot(grid, props, xname, yname, mask, split="none", n_max=5000, seed=0) -> dict:
    x, y = get(props, xname, grid), get(props, yname, grid)
    m = mask & np.isfinite(x) & np.isfinite(y)
    lab, names = labels(grid, props, split, m)
    idx = np.flatnonzero(m.ravel())
    if idx.size == 0:
        raise AnalysisError("No cells pass the filters.")
    xs, ys = x.ravel()[idx], y.ravel()[idx]
    out = dict(n_total=int(idx.size), names=names)
    if xs.std() > 0 and ys.std() > 0:
        out["r"] = float(np.corrcoef(xs, ys)[0, 1])
        a, b = np.polyfit(xs, ys, 1)
        out["slope"], out["intercept"] = float(a), float(b)
        out["r2"] = out["r"] ** 2
    else:
        out["r"] = out["r2"] = float("nan")
    rng = np.random.default_rng(seed)
    pick = rng.choice(idx.size, min(n_max, idx.size), replace=False)
    out.update(x=xs[pick], y=ys[pick], group=lab.ravel()[idx][pick])
    return out


def layer_profile(grid, props, name, mask, zone_idx: Optional[int] = None) -> dict:
    """Mean, P10, P90 per layer (volume-weighted mean) plus the mean layer depth."""
    v = get(props, name, grid)
    m = mask & np.isfinite(v)
    cd = grid.center_depth()
    w = grid.bulk_volume()
    rows = []
    for k in range(grid.nk):
        s = m[k]
        if zone_idx is not None and grid.layer_zone[k] != zone_idx:
            continue
        if not s.any():
            continue
        vk = v[k][s]
        rows.append((k, float(cd[k][s].mean()), float(np.average(vk, weights=w[k][s])) if w[k][s].sum() > 0 else float(vk.mean()),
                     float(np.percentile(vk, 10)), float(np.percentile(vk, 90)), int(grid.layer_zone[k])))
    a = np.array(rows) if rows else np.zeros((0, 6))
    return dict(k=a[:, 0].astype(int), depth=a[:, 1], mean=a[:, 2], p10=a[:, 3], p90=a[:, 4], zone=a[:, 5].astype(int))


def map_2d(grid, props, name, mask, mode="average", weight_props: Optional[Tuple[str, ...]] = ("NTG",)) -> np.ndarray:
    """(nj, ni) map over the selected cells.  thickness-weighted weights each cell by DZ x the weight properties (default NTG)."""
    v = get(props, name, grid)
    m = mask & np.isfinite(v)
    if mode == "sum":
        out = np.where(m, v, 0.0).sum(axis=0)
    elif mode in ("min", "max"):
        f = np.where(m, v, np.inf if mode == "min" else -np.inf)
        out = f.min(axis=0) if mode == "min" else f.max(axis=0)
        out[~np.isfinite(out)] = np.nan
        return out
    else:
        w = np.ones_like(v)
        if mode == "thickness-weighted":
            w = grid.thickness().astype(float)
            for wn in weight_props or ():
                if wn in props:
                    w = w * get(props, wn, grid)
        w = np.where(m, w, 0.0)
        sw = w.sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(sw > 0, (np.where(m, v, 0.0) * w).sum(axis=0) / sw, np.nan)
        return out
    out = out.astype(float)
    out[~m.any(axis=0)] = np.nan
    return out


def available_splits(props) -> List[str]:
    """Built-in splits plus fluid / region / segment when those properties exist, plus any other discrete property."""
    out = ["none", "zone", "fault block", "layer"]
    for k, n in (("fluid", "FLUID"), ("region", "REGION"), ("segment", "SEGMENT")):
        if n in props:
            out.append(k)
    out += [f"prop:{n}" for n, p in props.items() if p.kind == "discrete" and n not in ("FLUID", "REGION", "SEGMENT")]
    return out
