"""Scene builders for the WebGL viewer: Python objects -> compact JSON (base64 typed arrays).

All positions are sent as float32 relative to a scene origin (x - ox, y - oy, depth); the viewer applies
vertical exaggeration and the depth sign, so changing VE never needs a round trip to Python.
"""
from __future__ import annotations
from core import units as un

import base64
from typing import Dict, List, Optional
import numpy as np

from core.surface import Surface
from core.faults import Fault
from core.wells import Well, trajectory, xy_at_depth
from core.polygons import Polygon
from . import theme

DEPTH_STOPS = ["#D7191C", "#FDAE61", "#FFFFBF", "#ABD9E9", "#2C7BB6"]       # red = shallow, blue = deep
THICK_STOPS = ["#F7FBFF", "#9ECAE1", "#4292C6", "#08519C", "#051C2C"]
SEQ_STOPS = ["#440154", "#3B528B", "#21908C", "#5DC863", "#FDE725"]


def b64(a, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode("ascii")


def _hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def colorize(vals, vmin, vmax, stops) -> np.ndarray:
    """vals -> uint8 (n, 3) along a multi-stop ramp (NaN -> grey)."""
    vals = np.asarray(vals, float)
    t = np.clip((vals - vmin) / max(vmax - vmin, 1e-12), 0, 1)
    S = np.array([_hex2rgb(s) for s in stops])
    x = t * (len(S) - 1)
    i0 = np.clip(np.floor(x).astype(int), 0, len(S) - 2)
    f = (x - i0)[:, None]
    rgb = S[i0] * (1 - f) + S[i0 + 1] * f
    rgb[~np.isfinite(vals)] = (190, 190, 190)
    return rgb.round().astype(np.uint8)


def legend_ramp(title, vmin, vmax, stops, fmt="{:.0f}"):
    return dict(title=title, vmin=fmt.format(vmin), vmax=fmt.format(vmax), colors=list(stops))


class Scene:
    def __init__(self, origin):
        self.origin = (float(origin[0]), float(origin[1]))
        self.objects: List[dict] = []
        self._bb = None

    # -- bookkeeping ------------------------------------------------------
    def _extend(self, pos):
        pos = np.asarray(pos, float).reshape(-1, 3)
        if len(pos) == 0:
            return
        lo, hi = pos.min(0), pos.max(0)
        self._bb = np.array([lo, hi]) if self._bb is None else np.array([np.minimum(self._bb[0], lo), np.maximum(self._bb[1], hi)])

    def off(self, x, y):
        return np.asarray(x, float) - self.origin[0], np.asarray(y, float) - self.origin[1]

    def add(self, obj: dict, pos=None):
        if pos is not None:
            self._extend(pos)
        obj.setdefault("id", f"{obj.get('group', 'o')}/{obj['name']}")
        self.objects.append(obj)
        return obj

    def to_dict(self, ve=3.0) -> dict:
        bb = self._bb if self._bb is not None else np.array([[0, 0, 0], [1, 1, 1]], float)
        return dict(origin=list(self.origin), bounds=[float(bb[0, 0]), float(bb[1, 0]), float(bb[0, 1]), float(bb[1, 1]),
                                                       float(bb[0, 2]), float(bb[1, 2])],
                    objects=self.objects)

    @property
    def cam_key(self) -> str:
        bb = self._bb
        return "none" if bb is None else ",".join(f"{v:.0f}" for v in bb.ravel())

    # -- builders ---------------------------------------------------------
    def surface(self, s: Surface, group="Surfaces", color=None, color_by_depth=True, vrange=None, max_nodes=140_000,
                visible=True, opacity=1.0, mask: Optional[np.ndarray] = None):
        z = s.z.copy()
        if mask is not None:
            z[~mask] = np.nan
        step = max(1, int(np.ceil(np.sqrt(z.size / max_nodes))))
        zz = z[::step, ::step]
        nr, nc = zz.shape
        if not np.isfinite(zz).any():
            return None
        X, Y = s.geom.coords()
        X, Y = X[::step, ::step], Y[::step, ::step]
        valid = np.isfinite(zz)
        vid = -np.ones(zz.shape, int)
        vid[valid] = np.arange(int(valid.sum()))
        a, b, c, d = vid[:-1, :-1], vid[:-1, 1:], vid[1:, 1:], vid[1:, :-1]
        ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
        a, b, c, d = a[ok], b[ok], c[ok], d[ok]
        tri = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, d])]).astype(np.uint32)
        # also keep triangles where only 3 of 4 corners exist, so clipped edges are not jagged
        full = (vid[:-1, :-1] >= 0) & (vid[:-1, 1:] >= 0) & (vid[1:, 1:] >= 0) & (vid[1:, :-1] >= 0)
        for (p, q, r) in ((vid[:-1, :-1], vid[:-1, 1:], vid[1:, 1:]), (vid[:-1, :-1], vid[1:, 1:], vid[1:, :-1]),
                          (vid[:-1, :-1], vid[:-1, 1:], vid[1:, :-1]), (vid[:-1, 1:], vid[1:, 1:], vid[1:, :-1])):
            m = (p >= 0) & (q >= 0) & (r >= 0) & ~full
            if m.any():
                tri = np.concatenate([tri, np.column_stack([p[m], q[m], r[m]]).astype(np.uint32)])
        ox, oy = self.off(X[valid], Y[valid])
        pos = np.column_stack([ox, oy, zz[valid]]).astype(np.float32)
        obj = dict(name=s.name, group=group, type="mesh", pos=b64(pos, np.float32), idx=b64(tri, np.uint32),
                   color=color or theme.BLUE, visible=visible, opacity=opacity)
        if color_by_depth:
            lo, hi = vrange or (float(np.nanmin(zz)), float(np.nanmax(zz)))
            obj["col"] = b64(colorize(zz[valid], lo, hi, DEPTH_STOPS), np.uint8)
            obj["legend"] = legend_ramp(f"Depth ({un.z()})", lo, hi, DEPTH_STOPS)
            obj["color"] = "#5E9BE0"
        return self.add(obj, pos)

    def curtain(self, x, y, Z, names, group="Fence", name="Fence section", colors=None, opacity=0.85, outline=True):
        """Vertical curtain along a fence: Z is (nh, n) horizon depths at the n fence samples (x, y).
        Each interval is coloured separately (one mesh, per-vertex colours); horizons are drawn as lines."""
        from .theme import PALETTE
        Z = np.asarray(Z, float)
        nh, n = Z.shape
        ox, oy = self.off(np.asarray(x, float), np.asarray(y, float))
        pos, col, tri = [], [], []
        base = 0
        for k in range(nh - 1):
            c = _hex2rgb((colors or PALETTE)[k % len(colors or PALETTE)])
            top, bot = Z[k], Z[k + 1]
            ok = np.isfinite(top) & np.isfinite(bot)
            if ok.sum() < 2:
                continue
            pos.append(np.column_stack([ox, oy, top]))
            pos.append(np.column_stack([ox, oy, bot]))
            col += [np.tile(c, (2 * n, 1))]
            i = np.arange(n - 1)
            good = ok[:-1] & ok[1:]
            a, b, c2, d = base + i[good], base + i[good] + 1, base + n + i[good] + 1, base + n + i[good]
            tri += [np.column_stack([a, b, c2]), np.column_stack([a, c2, d])]
            base += 2 * n
        if not pos:
            return None
        pos = np.vstack(pos).astype(np.float32)
        tri = np.vstack(tri).astype(np.uint32)
        col = np.vstack(col).round().astype(np.uint8)
        # NaNs would break the float32 buffer: park them on a neighbouring finite value (their triangles are dropped)
        pos[~np.isfinite(pos)] = 0.0
        self.add(dict(name=name, group=group, type="mesh", pos=b64(pos, np.float32), idx=b64(tri, np.uint32),
                      color="#5E9BE0", col=b64(col, np.uint8), opacity=opacity), pos)
        if outline:
            lp, pairs, off_ = [], [], 0
            for k in range(nh):
                z = Z[k]
                if not np.isfinite(z).any():
                    continue
                zz = np.where(np.isfinite(z), z, np.nanmean(z))
                lp.append(np.column_stack([ox, oy, zz]))
                pairs.append(np.column_stack([np.arange(n - 1), np.arange(1, n)]) + off_)
                off_ += n
            lp = np.vstack(lp).astype(np.float32)
            self.add(dict(name=f"{name} horizons", group=group, type="lines", pos=b64(lp, np.float32),
                          idx=b64(np.vstack(pairs).astype(np.uint32), np.uint32), color="#051C2C"), lp)
        return True

    def faults(self, faults: Dict[str, Fault], zlo, zhi, group="Faults", opacity=0.30):
        for f in faults.values():
            pm = f.plane_mesh(zlo - 20, zhi + 20, 2)
            if pm is None:
                continue
            xs, ys, zs = pm
            n = xs.shape[1]
            ox, oy = self.off(xs.ravel(), ys.ravel())
            pos = np.column_stack([ox, oy, zs.ravel()]).astype(np.float32)
            tri = []
            for k in range(n - 1):
                tri += [[k, k + 1, n + k + 1], [k, n + k + 1, n + k]]
            self.add(dict(name=f.name, group=group, type="mesh", pos=b64(pos, np.float32), idx=b64(tri, np.uint32),
                          color=f.color or theme.RED, opacity=opacity), pos)
            tx, ty = self.off(xs[0], ys[0])
            tp = np.column_stack([tx, ty, np.full(n, zlo - 20)]).astype(np.float32)
            pairs = np.column_stack([np.arange(n - 1), np.arange(1, n)])
            self.add(dict(name=f"{f.name} trace", group=group, type="lines", pos=b64(tp, np.float32), idx=b64(pairs, np.uint32),
                          color=f.color or theme.RED), tp)

    def polygon(self, poly: Polygon, ref: Optional[Surface] = None, zlevel: float = 0.0, group="Polygons",
                color=None, step=None):
        P = poly.array
        P = np.vstack([P, P[0]])
        step = step or (0.5 * min(ref.geom.xinc, ref.geom.yinc) if ref is not None else 1e9)
        xs, ys = [], []
        for a, b in zip(P[:-1], P[1:]):
            n = max(int(np.hypot(*(b - a)) / step), 1)
            t = np.linspace(0, 1, n, endpoint=False)
            xs += list(a[0] + t * (b[0] - a[0]))
            ys += list(a[1] + t * (b[1] - a[1]))
        xs.append(P[-1, 0])
        ys.append(P[-1, 1])
        xs, ys = np.array(xs), np.array(ys)
        if ref is not None:
            z = ref.sample(xs, ys, extrapolate=True)
            fill = np.nanmin(ref.z) if np.isfinite(ref.z).any() else zlevel
            z = np.where(np.isfinite(z), z, fill)
        else:
            z = np.full(xs.shape, zlevel)
        ox, oy = self.off(xs, ys)
        pos = np.column_stack([ox, oy, z]).astype(np.float32)
        pairs = np.column_stack([np.arange(len(pos) - 1), np.arange(1, len(pos))])
        return self.add(dict(name=poly.name, group=group, type="lines", pos=b64(pos, np.float32), idx=b64(pairs, np.uint32),
                             color=color or theme.NAVY), pos)

    def well(self, w: Well, tops=None, radius=25.0, snap=True, group="Wells", td_default=2500.0, hcolors=None, z_start=None):
        """z_start: crop the path above this depth (project Z unit) so a long well does not dwarf a thin model."""
        tr = trajectory(w, td_default)
        if z_start is not None and tr[0, 2] < z_start < tr[-1, 2]:
            zi = np.maximum.accumulate(tr[:, 2])
            x0, y0 = np.interp(z_start, zi, tr[:, 0]), np.interp(z_start, zi, tr[:, 1])
            keep = tr[:, 2] > z_start
            tr = np.vstack([[x0, y0, z_start], tr[keep]])
        ox, oy = self.off(tr[:, 0], tr[:, 1])
        pos = np.column_stack([ox, oy, tr[:, 2]]).astype(np.float32)
        marks = []
        if tops is not None and len(tops):
            for _, r in tops[tops["well"] == w.name].iterrows():
                x, y = (xy_at_depth(tr, float(r["z"])) if snap else (float(r["x"]), float(r["y"])))
                mx, my = self.off(x, y)
                marks.append(dict(name=str(r["horizon"]), x=float(mx), y=float(my), z=float(r["z"]),
                                  color=(hcolors or {}).get(str(r["horizon"]), theme.CYAN)))
        return self.add(dict(name=w.name, group=group, type="well", path=b64(pos, np.float32), radius=float(radius),
                             color=w.color or theme.BLUE, tops=marks), pos)

    def tops_points(self, tops, group="Well tops", name="Well tops", color=theme.NAVY):
        if tops is None or not len(tops):
            return None
        ox, oy = self.off(tops["x"].values, tops["y"].values)
        pos = np.column_stack([ox, oy, tops["z"].values]).astype(np.float32)
        return self.add(dict(name=name, group=group, type="points", pos=b64(pos, np.float32), color=color, size=6), pos)

    def grid(self, grid, prop="Zone", i0=0, j0=0, group="3D grid", name="3D grid", opacity=1.0, max_faces=120_000, props=None,
             layer_mask=None):
        sc, legend = grid_property(grid, prop, props)
        V, T, S = grid.exterior_faces(i0, j0, sc["values"], max_faces=max_faces, layer_mask=layer_mask)
        if len(V) == 0:
            return None
        vs = np.empty(len(V))
        for c in range(3):
            vs[T[:, c]] = S
        if sc["kind"] == "discrete":
            pal = np.array([_hex2rgb(h) for h in sc["colors"]])
            rgb = pal[np.clip(vs.astype(int) - sc["first"], 0, len(pal) - 1)].round().astype(np.uint8)
        else:
            rgb = colorize(vs, sc["vmin"], sc["vmax"], sc["stops"])
        ox, oy = self.off(V[:, 0], V[:, 1])
        pos = np.column_stack([ox, oy, V[:, 2]]).astype(np.float32)
        nf = len(V) // 4
        q = np.arange(nf)[:, None] * 4
        wire = np.hstack([q, q + 1, q + 1, q + 2, q + 2, q + 3, q + 3, q]).reshape(-1)
        return self.add(dict(name=name, group=group, type="mesh", pos=b64(pos, np.float32), idx=b64(T, np.uint32),
                             col=b64(rgb, np.uint8), wire=b64(wire, np.uint32), color=theme.BLUE, opacity=opacity,
                             legend=legend), pos)


def grid_property(grid, prop: str, props=None):
    """-> (dict(values, kind, ...), legend) for a cell property of a CPGrid (``props``: user Property objects)."""
    act = grid.actnum > 0
    if props and prop in props:
        pr_ = props[prop]
        v = np.nan_to_num(pr_.values.astype(float), nan=0.0)
        if pr_.kind == "discrete":
            codes = np.unique(v[act]).astype(int) if act.any() else np.array([0])
            if len(codes) <= 24:
                lo = int(codes.min())
                cols = [theme.PALETTE[(c - lo) % len(theme.PALETTE)] if c in codes else "#CCCCCC" for c in range(lo, int(codes.max()) + 1)]
                return (dict(values=v, kind="discrete", colors=cols, first=lo),
                        dict(title=prop, items=[dict(color=cols[c - lo], label=str(c)) for c in codes]))
        sel = v[act & np.isfinite(pr_.values)]
        lo, hi = (float(np.percentile(sel, 1)), float(np.percentile(sel, 99))) if sel.size else (0.0, 1.0)
        if hi - lo < 1e-12:
            hi = lo + 1e-9
        return dict(values=v, kind="cont", vmin=lo, vmax=hi, stops=SEQ_STOPS), legend_ramp(prop + (f" ({pr_.unit})" if pr_.unit else ""), lo, hi, SEQ_STOPS, "{:.3g}")
    if prop == "Zone":
        n = len(grid.zones)
        cols = [theme.ZONE_COLORS[k % len(theme.ZONE_COLORS)] for k in range(n)]
        return (dict(values=grid.zone_layer_array().astype(float), kind="discrete", colors=cols, first=1),
                dict(title="Zone", items=[dict(color=c, label=z.name) for c, z in zip(cols, grid.zones)]))
    if prop == "Fault block":
        v = grid.block_array().astype(float)
        nb = int(v.max())
        cols = [theme.PALETTE[k % len(theme.PALETTE)] for k in range(nb)]
        return (dict(values=v, kind="discrete", colors=cols, first=1),
                dict(title="Fault block", items=[dict(color=c, label=f"Block {k + 1}") for k, c in enumerate(cols)]))
    if prop == "Layer (k)":
        v = np.broadcast_to(np.arange(1, grid.nk + 1)[:, None, None], (grid.nk, grid.nj, grid.ni)).astype(float)
        return dict(values=v, kind="cont", vmin=1, vmax=grid.nk, stops=DEPTH_STOPS), legend_ramp("Layer k", 1, grid.nk, DEPTH_STOPS)
    if prop == "Depth":
        v = grid.center_depth()
        lo, hi = (float(v[act].min()), float(v[act].max())) if act.any() else (0.0, 1.0)
        return dict(values=v, kind="cont", vmin=lo, vmax=hi, stops=DEPTH_STOPS), legend_ramp(f"Depth ({un.z()})", lo, hi, DEPTH_STOPS)
    if prop == "Thickness":
        v = grid.thickness()
        hi = float(np.percentile(v[act], 99)) if act.any() else 1.0
        return dict(values=v, kind="cont", vmin=0.0, vmax=hi, stops=THICK_STOPS), legend_ramp(f"dz ({un.z()})", 0.0, hi, THICK_STOPS, "{:.1f}")
    v = grid.property_array(prop)
    title = prop
    if prop.startswith("PERM"):
        v = np.log10(np.maximum(v, 1e-3))
        title = f"log10 {prop}"
    lo, hi = (float(v[act].min()), float(v[act].max())) if act.any() else (0.0, 1.0)
    if hi - lo < 1e-9:
        hi = lo + 1e-9
    return dict(values=v, kind="cont", vmin=lo, vmax=hi, stops=SEQ_STOPS), legend_ramp(title, lo, hi, SEQ_STOPS, "{:.2f}")
