"""Fault faces of the corner-point grid: which cell faces lie on which fault (Eclipse FAULTS / MULTFLT), and the juxtaposition of zones across them."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np


def _seg_hit(p, q, a, b):
    """Intersection test of segments p-q with the trace segments a-b (broadcasting); returns bool array and the distance of the hit from p (0-1 fraction)."""
    r = q - p
    s = b - a
    den = r[..., 0] * s[..., 1] - r[..., 1] * s[..., 0]
    ap = a - p
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (ap[..., 0] * s[..., 1] - ap[..., 1] * s[..., 0]) / den
        u = (ap[..., 0] * r[..., 1] - ap[..., 1] * r[..., 0]) / den
    return (np.abs(den) > 1e-12) & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1), t


def assign_faults(grid, faults) -> Dict[str, List[Tuple[str, int, int]]]:
    """Faces between neighbouring columns that belong to different fault blocks, assigned to the fault whose trace crosses the line between the two
    column centres (nearest to the middle if several).  -> {fault name: [(dir, i, j), ...]}  dir 'X' = face between (i, j) and (i+1, j), 'Y' = between (i, j) and (i, j+1); 0-based."""
    cx, cy = grid.center_xy()
    blk = grid.block
    out: Dict[str, List[Tuple[str, int, int]]] = {f.name: [] for f in faults}
    traces = [(f.name, np.asarray(f.trace, float)) for f in faults]
    for d in ("X", "Y"):
        if d == "X":
            diff = blk[:, :-1] != blk[:, 1:]
            jj, ii = np.nonzero(diff)
            p = np.column_stack([cx[jj, ii], cy[jj, ii]])
            q = np.column_stack([cx[jj, ii + 1], cy[jj, ii + 1]])
        else:
            diff = blk[:-1, :] != blk[1:, :]
            jj, ii = np.nonzero(diff)
            p = np.column_stack([cx[jj, ii], cy[jj, ii]])
            q = np.column_stack([cx[jj + 1, ii], cy[jj + 1, ii]])
        if len(jj) == 0:
            continue
        best = np.full(len(jj), -1)
        bestd = np.full(len(jj), np.inf)
        for fi, (nm, T) in enumerate(traces):
            if len(T) < 2:
                continue
            hit_any = np.zeros(len(jj), bool)
            dist = np.full(len(jj), np.inf)
            for a, b in zip(T[:-1], T[1:]):
                h, t = _seg_hit(p, q, a[None, :], b[None, :])
                hit_any |= h
                dist = np.where(h, np.minimum(dist, np.abs(t - 0.5)), dist)
            better = hit_any & (dist < bestd)
            best[better], bestd[better] = fi, dist[better]
        miss = best < 0
        if miss.any():                                   # faces whose centre line misses every trace: use the nearest trace to the midpoint
            mid = 0.5 * (p + q)
            for k in np.nonzero(miss)[0]:
                dmin, fmin = np.inf, -1
                for fi, (nm, T) in enumerate(traces):
                    for a, b in zip(T[:-1], T[1:]):
                        ab = b - a
                        t = np.clip(np.dot(mid[k] - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
                        dd = np.hypot(*(mid[k] - (a + t * ab)))
                        if dd < dmin:
                            dmin, fmin = dd, fi
                best[k] = fmin
        for k in range(len(jj)):
            if best[k] >= 0:
                out[traces[best[k]][0]].append((d, int(ii[k]), int(jj[k])))
    return out


def _runs(idx: List[int]) -> List[Tuple[int, int]]:
    idx = sorted(set(idx))
    runs, start, prev = [], None, None
    for v in idx:
        if start is None:
            start = prev = v
        elif v == prev + 1:
            prev = v
        else:
            runs.append((start, prev))
            start = prev = v
    if start is not None:
        runs.append((start, prev))
    return runs


def eclipse_names(names: List[str]) -> Dict[str, str]:
    """Unique fault names of at most 8 characters, no blanks."""
    used, out = set(), {}
    for n in names:
        base = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in n)[:8] or "FAULT"
        cand, i = base, 1
        while cand.upper() in used:
            suf = str(i)
            cand = base[:8 - len(suf)] + suf
            i += 1
        used.add(cand.upper())
        out[n] = cand
    return out


def faults_keywords(grid, faults, mult: Optional[Dict[str, float]] = None) -> str:
    """Eclipse FAULTS (cell-face lists) and MULTFLT (transmissibility multipliers, only where different from 1) keywords."""
    if not faults:
        return ""
    faces = assign_faults(grid, faults)
    nm = eclipse_names([f.name for f in faults])
    lines = ["FAULTS"]
    for f in faults:
        fx = [(i, j) for d, i, j in faces[f.name] if d == "X"]
        fy = [(i, j) for d, i, j in faces[f.name] if d == "Y"]
        for i in sorted({i for i, _ in fx}):
            for a, b in _runs([j for ii, j in fx if ii == i]):
                lines.append(f" '{nm[f.name]}' {i + 1} {i + 1} {a + 1} {b + 1} 1 {grid.nk} X /")
        for j in sorted({j for _, j in fy}):
            for a, b in _runs([i for i, jj in fy if jj == j]):
                lines.append(f" '{nm[f.name]}' {a + 1} {b + 1} {j + 1} {j + 1} 1 {grid.nk} Y /")
    lines.append("/\n")
    m = {k: float(v) for k, v in (mult or {}).items() if abs(float(v) - 1.0) > 1e-9}
    if m:
        lines.append("MULTFLT")
        for f in faults:
            if f.name in m:
                lines.append(f" '{nm[f.name]}' {m[f.name]:.6g} /")
        lines.append("/\n")
    return "\n".join(lines) + "\n"


def juxtaposition(grid, faults, props=None) -> Dict[str, List[dict]]:
    """Zone-against-zone contact area across each fault (Allan-type juxtaposition from the cell face depth overlaps).
    -> {fault: [{left, right, area, share}]} where left = lower I / J side."""
    faces = assign_faults(grid, faults)
    zc = grid.zc
    act = grid.actnum > 0
    nz = len(grid.zones)
    lz = grid.layer_zone
    out = {}
    dx, dy = np.diff(grid.xs), np.diff(grid.ys)
    for f in faults:
        M = np.zeros((nz, nz))
        for d, i, j in faces[f.name]:
            if d == "X":
                ti, bi = zc[:, 0, j, :, i, 1].mean(axis=1), zc[:, 1, j, :, i, 1].mean(axis=1)
                tj, bj = zc[:, 0, j, :, i + 1, 0].mean(axis=1), zc[:, 1, j, :, i + 1, 0].mean(axis=1)
                al, ar = act[:, j, i], act[:, j, i + 1]
                width = dy[j]
            else:
                ti, bi = zc[:, 0, j, 1, i, :].mean(axis=1), zc[:, 1, j, 1, i, :].mean(axis=1)
                tj, bj = zc[:, 0, j + 1, 0, i, :].mean(axis=1), zc[:, 1, j + 1, 0, i, :].mean(axis=1)
                al, ar = act[:, j, i], act[:, j + 1, i]
                width = dx[i]
            ov = np.clip(np.minimum(bi[:, None], bj[None, :]) - np.maximum(ti[:, None], tj[None, :]), 0, None) * width
            ov = ov * al[:, None] * ar[None, :]
            np.add.at(M, (lz[:, None].repeat(grid.nk, 1), lz[None, :].repeat(grid.nk, 0)), ov)
        tot = M.sum()
        rows = [dict(left=grid.zones[a].name, right=grid.zones[b].name, area=float(M[a, b]), share=float(M[a, b] / tot) if tot > 0 else 0.0)
                for a in range(nz) for b in range(nz) if M[a, b] > 0]
        out[f.name] = sorted(rows, key=lambda r: -r["area"])
    return out
