"""Polygon objects (model boundary, clip outlines): masks, import / export."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Dict, List
import numpy as np

from .surface import Geometry


@dataclass
class Polygon:
    name: str
    pts: List[List[float]]

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Polygon(d["name"], [[float(x), float(y)] for x, y in d["pts"]])

    @property
    def array(self) -> np.ndarray:
        return np.asarray(self.pts, float)

    def bounds(self):
        a = self.array
        return float(a[:, 0].min()), float(a[:, 0].max()), float(a[:, 1].min()), float(a[:, 1].max())

    def area(self) -> float:
        a = self.array
        x, y = a[:, 0], a[:, 1]
        return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def inside(X, Y, pts) -> np.ndarray:
    """Even-odd point-in-polygon for arrays X, Y."""
    P = np.asarray(pts, float)
    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    res = np.zeros(X.shape, bool)
    n = len(P)
    j = n - 1
    for i in range(n):
        xi, yi = P[i]
        xj, yj = P[j]
        if yi != yj:
            cond = ((yi > Y) != (yj > Y)) & (X < (xj - xi) * (Y - yi) / (yj - yi) + xi)
            res ^= cond
        j = i
    return res


def distance_to_boundary(X, Y, pts) -> np.ndarray:
    P = np.asarray(pts, float)
    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    best = np.full(X.shape, np.inf)
    n = len(P)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        ab = b - a
        l2 = float(ab @ ab)
        u = np.zeros(X.shape) if l2 == 0 else np.clip(((X - a[0]) * ab[0] + (Y - a[1]) * ab[1]) / l2, 0, 1)
        d = np.hypot(X - (a[0] + u * ab[0]), Y - (a[1] + u * ab[1]))
        best = np.minimum(best, d)
    return best


def mask(geom: Geometry, poly: Polygon, buffer: float = 0.0) -> np.ndarray:
    """True for lattice nodes inside the polygon. buffer > 0 grows, < 0 shrinks the polygon (metres)."""
    X, Y = geom.coords()
    m = inside(X, Y, poly.pts)
    if buffer:
        d = distance_to_boundary(X, Y, poly.pts)
        m = (m | (d <= buffer)) if buffer > 0 else (m & (d > -buffer))
    return m


def mask_points(X, Y, poly: Polygon, buffer: float = 0.0) -> np.ndarray:
    m = inside(X, Y, poly.pts)
    if buffer:
        d = distance_to_boundary(X, Y, poly.pts)
        m = (m | (d <= buffer)) if buffer > 0 else (m & (d > -buffer))
    return m


# ---------------------------------------------------------------------------
def _clean(pts, closed=True):
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if closed and len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def parse_rms_pol(data: bytes, default_name="Polygon", *, closed=True) -> Dict[str, Polygon]:
    """Read RMS ASCII X Y Z parts; closed=False accepts open two-point traces."""
    text = data.decode("utf-8-sig")
    out: Dict[str, Polygon] = {}
    pts = []

    def finish():
        if not pts:
            return
        cleaned = _clean(pts, closed=closed)
        minimum = 3 if closed else 2
        if len(cleaned) < minimum or len({tuple(p) for p in cleaned}) < minimum:
            raise ValueError(f"RMS polygon / trace {len(out) + 1} has fewer than {minimum} distinct vertices.")
        name = f"{default_name}_{len(out) + 1}"
        out[name] = Polygon(name, cleaned)
        pts.clear()

    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"RMS polygon line {line_no} must contain exactly X Y Z.")
        try:
            x, y, z = (float(part) for part in parts)
        except ValueError as exc:
            raise ValueError(f"RMS polygon line {line_no} contains a non-numeric coordinate.") from exc
        if not np.isfinite([x, y, z]).all():
            raise ValueError(f"RMS polygon line {line_no} contains a non-finite coordinate.")
        if x == 999.0 and y == 999.0 and z == 999.0:
            finish()
        else:
            pts.append([x, y])
    finish()
    if not out:
        raise ValueError("No valid polygon / trace found in the RMS file.")
    return out


def parse(data: bytes, default_name="Polygon", *, closed=True) -> Dict[str, Polygon]:
    """Read XY text / GeoJSON polygons; closed=False also accepts two-point text traces."""
    text = data.decode("utf-8", errors="ignore").strip()
    out: Dict[str, Polygon] = {}

    def add(name, pts):
        pts = _clean([[float(a), float(b)] for a, b in pts], closed=closed)
        minimum = 3 if closed else 2
        if not np.isfinite(pts).all():
            raise ValueError("Polygon / trace coordinates must be finite.")
        if not closed and len({tuple(p) for p in pts}) < minimum:
            raise ValueError("A fault trace needs at least 2 distinct X Y vertices.")
        if len(pts) >= minimum and len({tuple(p) for p in pts}) >= minimum:
            nm, k = name, 2
            while nm in out:
                nm = f"{name}_{k}"
                k += 1
            out[nm] = Polygon(nm, pts)

    if text.startswith("{"):
        gj = json.loads(text)
        feats = gj.get("features", [gj]) if gj.get("type") != "Polygon" else [{"geometry": gj, "properties": {}}]
        for i, f in enumerate(feats):
            g = f.get("geometry", f)
            nm = (f.get("properties") or {}).get("name") or f"{default_name}_{i + 1}"
            if g["type"] == "Polygon":
                add(nm, [c[:2] for c in g["coordinates"][0]])
            elif g["type"] == "MultiPolygon":
                for j, poly in enumerate(g["coordinates"]):
                    add(f"{nm}_{j + 1}", [c[:2] for c in poly[0]])
        if not out:
            raise ValueError("No Polygon geometries found in the GeoJSON.")
        return out
    cur, name, count = [], default_name, 1
    for ln in text.splitlines() + [""]:
        s = ln.strip()
        parts = [t for t in re.split(r"[,\s;]+", s) if t]
        nums = None
        if parts and len(parts) >= 2:
            try:
                nums = (float(parts[0]), float(parts[1]))
            except ValueError:
                nums = None
        if nums is not None and not (np.isnan(nums[0]) or np.isnan(nums[1])):
            cur.append(nums)
            continue
        if cur:
            add(name if name != default_name else f"{default_name}_{count}", cur)
            count += 1
            cur = []
        if s and not s.startswith(("#", ">")) and nums is None and parts and not re.match(r"^[xX]\b", parts[0]):
            name = s[:40]
        elif s.startswith(">") and len(s) > 1:
            name = s[1:].strip() or default_name
    if not out:
        raise ValueError(f"No polygon / trace with at least {3 if closed else 2} distinct X Y vertices found.")
    return out


def to_text(polys: Dict[str, Polygon]) -> str:
    lines = []
    for p in polys.values():
        lines.append(f"> {p.name}")
        lines += [f"{x:.2f} {y:.2f}" for x, y in p.pts + [p.pts[0]]]
    return "\n".join(lines) + "\n"
