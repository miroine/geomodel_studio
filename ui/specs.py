"""Plotly.js figure specifications (maps, sections, histograms) as plain dicts.  3D is drawn by the WebGL viewer (ui/scene.py)."""
from __future__ import annotations
from core import units as un

from typing import Dict, List, Optional
import numpy as np

from core.surface import Geometry
from core.faults import Fault
from .theme import NAVY, BLUE, CYAN, INK, MUTE, LINE, PALETTE, ZONE_COLORS

DEPTH_SCALE = [[0., "#D7191C"], [0.25, "#FDAE61"], [0.5, "#FFFFBF"], [0.75, "#ABD9E9"], [1., "#2C7BB6"]]
THICK_SCALE = [[0.0, "#FFFFFF"], [0.25, "#CFE3F7"], [0.5, "#5E9BE0"], [0.75, "#2251FF"], [1.0, "#051C2C"]]
RES_SCALE = [[0.0, "#D7263D"], [0.5, "#F5F8FC"], [1.0, "#2251FF"]]
FONT = dict(family="Arial, Helvetica, sans-serif", color=INK, size=12)
SERIF = "Georgia, 'Times New Roman', serif"


def _title(t):
    return dict(text=t, font=dict(family=SERIF, size=16, color=NAVY), x=0.01, xanchor="left") if t else None


def _nan(a):
    a = np.asarray(a, float)
    return np.where(np.isfinite(a), a, np.nan)


def base_layout(title=None, **kw):
    lay = dict(font=FONT, paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", margin=dict(l=55, r=15, t=45 if title else 15, b=45),
               legend=dict(orientation="h", y=-0.12, font=dict(size=11)), hoverlabel=dict(font=dict(family="Arial")))
    if title:
        lay["title"] = _title(title)
    lay.update(kw)
    return lay


def map_2d(Z, geom: Geometry, title=None, scale=DEPTH_SCALE, faults: Optional[List[Fault]] = None, wells=None,
           colorbar=None, contour_lines=True, zmid=None, reverse=False, line_color="#333333",
           contour_interval=0., contour_labels=False, well_paths=None, zrange=None):
    colorbar = colorbar or f"Depth ({un.z()})"
    z = _nan(Z)
    if geom.rotation:
        from core.surface import Surface
        x0, x1, y0, y1 = geom.bounds()
        step = max(min(abs(geom.xinc), abs(geom.yinc)), np.sqrt((x1 - x0) * (y1 - y0) / 140_000))
        nx, ny = max(2, int(np.ceil((x1 - x0) / step)) + 1), max(2, int(np.ceil((y1 - y0) / step)) + 1)
        target = Geometry(x0, y0, (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1), nx, ny)
        z = Surface("Map", geom, z).resample_to(target, extrapolate=False).z
        geom = target
    if not np.isfinite(z).any():
        raise ValueError("The surface has no finite depths to display.")
    if not np.isfinite(contour_interval) or contour_interval < 0:
        raise ValueError("Contour interval must be finite and non-negative.")
    lo, hi = float(np.nanmin(z)), float(np.nanmax(z))
    tr = dict(type="contour", x=geom.xs, y=geom.ys, z=z, colorscale=scale, connectgaps=False,
              contours=dict(coloring="heatmap", showlines=contour_lines, showlabels=contour_labels),
              line=dict(width=0.6, color=line_color), colorbar=dict(title=colorbar, len=0.8, thickness=12),
              ncontours=18, hovertemplate="x %{x:.0f}<br>y %{y:.0f}<br>%{z:.1f}<extra></extra>")
    tr["reversescale"] = reverse
    if contour_interval > 0:
        if (hi - lo) / contour_interval > 500:
            raise ValueError("Contour interval would create more than 500 contours; increase it.")
        tr.update(autocontour=False)
        tr["contours"].update(start=np.ceil(lo / contour_interval) * contour_interval, end=hi, size=contour_interval)
    if zmid is not None:
        d = max(abs(lo - zmid), abs(hi - zmid), 1e-9)
        tr.update(zmin=zmid - d, zmax=zmid + d, zmid=zmid)
    elif zrange is not None:
        tr.update(zmin=float(zrange[0]), zmax=float(zrange[1]), zauto=False)
    data = [tr]
    for f in (faults or []):
        P = f.points
        data.append(dict(type="scatter", mode="lines", x=P[:, 0], y=P[:, 1], line=dict(color=f.color or "#D7263D", width=3),
                         name=f.name, hoverinfo="name"))
    if wells:
        data.append(dict(type="scatter", mode="markers+text", x=[w["x"] for w in wells], y=[w["y"] for w in wells],
                         text=[w.get("label", "") for w in wells], textposition="top right",
                         marker=dict(symbol="triangle-up", size=10, color=NAVY, line=dict(color="#fff", width=1)),
                         name="Wells", textfont=dict(size=10)))
    from core.wells import trajectory
    for well in well_paths or []:
        path = trajectory(well)
        if not np.isfinite(path).all():
            raise ValueError(f"Well '{well.name}' has non-finite trajectory coordinates.")
        data.append(dict(type="scatter", mode="lines", x=path[:, 0], y=path[:, 1], customdata=path[:, 2],
                         line=dict(color=well.color or NAVY, width=2.5), name=well.name,
                         hovertemplate=well.name + "<br>x %{x:.1f}<br>y %{y:.1f}<br>depth %{customdata:.1f}<extra></extra>"))
        data.append(dict(type="scatter", mode="markers+text", x=[well.x], y=[well.y], text=[well.name],
                         textposition="top right", marker=dict(size=8, symbol="triangle-up", color=well.color or NAVY),
                         name=f"{well.name} head", showlegend=False))
    lay = base_layout(title, xaxis=dict(title="Easting", scaleanchor="y", scaleratio=1, showgrid=False),
                      yaxis=dict(title="Northing", showgrid=False))
    return dict(data=data, layout=lay)


def section(names: List[str], dist: np.ndarray, Z: np.ndarray, zone_of_interval: Optional[List[int]] = None,
            interval_names: Optional[List[str]] = None, title=None, wells=None,
            crossings=None, vertices=None, well_paths=None):
    """Z: (nh, n) depths along the section; fills each interval between consecutive horizons."""
    data = []
    nh = len(names)
    for k in range(nh):
        c = ZONE_COLORS[(zone_of_interval[k - 1] if (zone_of_interval and k > 0) else k) % len(ZONE_COLORS)]
        tr = dict(type="scatter", mode="lines", x=dist, y=_nan(Z[k]), line=dict(color=NAVY, width=1.1 if nh <= 25 else 0.5),
                  name=names[k], showlegend=False, hovertemplate=names[k] + "<br>%{x:.0f} " + un.xy() + "<br>%{y:.1f} " + un.z() + "<extra></extra>")
        if k > 0:
            tr.update(fill="tonexty", fillcolor=c)
            tr["name"] = interval_names[k - 1] if interval_names else names[k]
            tr["showlegend"] = True
        data.append(tr)
    if wells:
        data.append(dict(type="scatter", mode="markers+text", x=[w["x"] for w in wells], y=[w["z"] for w in wells],
                         text=[w.get("label", "") for w in wells], textposition="middle right",
                         marker=dict(size=7, color="#D7263D", line=dict(color="#fff", width=1)), name="Tops (projected)",
                         textfont=dict(size=9)))
    for wp in well_paths or []:
        data.append(dict(type="scatter", mode="lines+text", x=wp["x"], y=wp["z"], line=dict(color="#111", width=2.4),
                         name=f"{wp['name']} ({wp['offset']:.0f} {un.xy()} off)", text=[wp["name"]] + [""] * (len(wp["x"]) - 1),
                         textposition="top center", textfont=dict(size=10), showlegend=False))
    shapes, ann = [], []
    for v in (vertices or [])[1:-1]:
        shapes.append(dict(type="line", xref="x", yref="paper", x0=v, x1=v, y0=0, y1=1, line=dict(color="#8A94A0", width=1, dash="dot")))
    for c in crossings or []:
        shapes.append(dict(type="line", xref="x", yref="paper", x0=c["dist"], x1=c["dist"], y0=0, y1=1, line=dict(color=c.get("color") or "#B8003C", width=1.4, dash="dash")))
        ann.append(dict(x=c["dist"], y=1, xref="x", yref="paper", text=c["name"], showarrow=False, yanchor="bottom", font=dict(size=10, color=c.get("color") or "#B8003C")))
    lay = base_layout(title, xaxis=dict(title=f"Distance along section ({un.xy()})", showgrid=False),
                      yaxis=dict(title=f"Depth ({un.z()})", autorange="reversed", gridcolor=LINE), shapes=shapes, annotations=ann)
    return dict(data=data, layout=lay)


def residual_bars(df, title="Top residuals (observed - model)"):
    """df columns: well, horizon, residual (and optionally residual_after)."""
    data = []
    for k, (h, g) in enumerate(df.groupby("horizon")):
        data.append(dict(type="bar", x=list(g["well"]), y=list(g["residual"]), name=h, marker=dict(color=PALETTE[k % len(PALETTE)])))
    lay = base_layout(title, barmode="group", xaxis=dict(title="Well"), yaxis=dict(title=f"Residual ({un.z()})", gridcolor=LINE, zerolinecolor=NAVY))
    return dict(data=data, layout=lay)


def grid_section(grid, index: int, axis: str = "j", ve_title=None):
    """Cell-edge section along a row (axis='j': fixed j) or column (axis='i'); layer interfaces coloured by zone."""
    data = []
    nz = len(grid.zones)
    if axis == "j":
        n, coord = grid.ni, grid.xs
    else:
        n, coord = grid.nj, grid.ys
    for zi, zone in enumerate(grid.zones):
        ks = np.where(grid.layer_zone == zi)[0]
        xs, ys = [], []
        for k in ks:
            for c in range(n):
                if axis == "j":
                    if not grid.actnum[k, index, c]:
                        continue
                    xa, xb = grid.xs[c], grid.xs[c + 1]
                    z = lambda t, a: grid.zc[k, t, index, 0, c, a]
                else:
                    if not grid.actnum[k, c, index]:
                        continue
                    xa, xb = grid.ys[c], grid.ys[c + 1]
                    z = lambda t, a: grid.zc[k, t, c, a, index, 0]
                # top edge, bottom edge as two lines plus verticals (closed cell outline)
                xs += [xa, xb, xb, xa, xa, None]
                ys += [z(0, 0), z(0, 1), z(1, 1), z(1, 0), z(0, 0), None]
        data.append(dict(type="scatter", mode="lines", x=xs, y=ys, line=dict(color=ZONE_COLORS[zi % len(ZONE_COLORS)] if False else PALETTE[zi % len(PALETTE)], width=1),
                         name=zone.name, hoverinfo="skip"))
    lay = base_layout(None, xaxis=dict(title=f"Easting ({un.xy()})" if axis == "j" else f"Northing ({un.xy()})", showgrid=False),
                      yaxis=dict(title=f"Depth ({un.z()})", autorange="reversed", gridcolor=LINE))
    return dict(data=data, layout=lay)


# ---------------------------------------------------------------------------------------------
# filter / polygon helpers (2D)
def _poly_traces(polys, boundary=None, width=2):
    out = []
    for n, poly in (polys or {}).items():
        P = np.vstack([poly.array, poly.array[0]])
        isb = (n == boundary)
        out.append(dict(type="scatter", mode="lines", x=P[:, 0], y=P[:, 1], name=n + (" (boundary)" if isb else ""),
                        line=dict(color=CYAN if isb else NAVY, width=width + (1 if isb else 0), dash="solid" if isb else "dash"),
                        hoverinfo="name"))
    return out


def mask_map(raw, z, geom: Geometry, polys=None, boundary=None, title=None):
    """Kept / removed / undefined nodes of a filtered surface."""
    raw, z = np.asarray(raw, float), np.asarray(z, float)
    state = np.full(raw.shape, np.nan)
    state[np.isfinite(raw) & np.isfinite(z)] = 1.0
    state[np.isfinite(raw) & ~np.isfinite(z)] = 2.0
    state[~np.isfinite(raw) & np.isfinite(z)] = 3.0
    cs = [[0.0, "#9CC5EE"], [0.3333, "#9CC5EE"], [0.3334, "#D7263D"], [0.6666, "#D7263D"], [0.6667, "#1B998B"], [1.0, "#1B998B"]]
    hm = dict(type="heatmap", x=geom.xs, y=geom.ys, z=state, zmin=0.5, zmax=3.5, colorscale=cs, showscale=False,
              hovertemplate="x %{x:.0f}<br>y %{y:.0f}<extra></extra>")
    data = [hm] + _poly_traces(polys, boundary)
    n_k, n_r = int((state == 1).sum()), int((state == 2).sum())
    data += [dict(type="scatter", mode="markers", x=[None], y=[None], marker=dict(size=10, color="#9CC5EE", symbol="square"), name=f"kept ({n_k:,})"),
             dict(type="scatter", mode="markers", x=[None], y=[None], marker=dict(size=10, color="#D7263D", symbol="square"), name=f"removed ({n_r:,})")]
    lay = base_layout(title, xaxis=dict(title="Easting", scaleanchor="y", scaleratio=1, showgrid=False),
                      yaxis=dict(title="Northing", showgrid=False))
    return dict(data=data, layout=lay)


def histogram(raw, z=None, lines=None, title="Depth distribution", nbins=60):
    raw = np.asarray(raw, float)
    v = raw[np.isfinite(raw)]
    data = [dict(type="histogram", x=v, nbinsx=nbins, name="raw", marker=dict(color="#C9D6E6"))]
    if z is not None:
        zz = np.asarray(z, float)
        zz = zz[np.isfinite(zz)]
        data.append(dict(type="histogram", x=zz, nbinsx=nbins, name="after filters", marker=dict(color=BLUE), opacity=0.8))
    shapes = [dict(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper", line=dict(color="#D7263D", width=2, dash="dot")) for x in (lines or [])]
    lay = base_layout(title, barmode="overlay", xaxis=dict(title=f"Depth ({un.z()})"), yaxis=dict(title="Nodes"), shapes=shapes)
    return dict(data=data, layout=lay)


def plan_view(geom: Geometry, polys=None, boundary=None, faults=None, wells=None, title=None):
    """Plan map: model lattice outline, polygons, fault traces, well heads."""
    x0, x1, y0, y1 = geom.bounds()
    data = [dict(type="scatter", mode="lines", x=[x0, x1, x1, x0, x0], y=[y0, y0, y1, y1, y0], line=dict(color=LINE, width=2),
                 name="Model lattice", hoverinfo="name")]
    data += _poly_traces(polys, boundary)
    for f in (faults or []):
        P = f.points
        data.append(dict(type="scatter", mode="lines", x=P[:, 0], y=P[:, 1], line=dict(color=f.color or "#D7263D", width=3), name=f.name))
    if wells:
        data.append(dict(type="scatter", mode="markers+text", x=[w.x for w in wells], y=[w.y for w in wells], text=[w.name for w in wells],
                         textposition="top right", marker=dict(symbol="triangle-up", size=10, color=NAVY), name="Wells", textfont=dict(size=10)))
    lay = base_layout(title, xaxis=dict(title="Easting", scaleanchor="y", scaleratio=1, showgrid=False),
                      yaxis=dict(title="Northing", showgrid=False))
    return dict(data=data, layout=lay)


def value_histogram(groups: dict, title=None, xtitle="", bins=40):
    """Overlaid histograms; ``groups`` = {name: 1D array}."""
    allv = np.concatenate([np.asarray(v, float) for v in groups.values() if len(v)]) if groups else np.array([0.0])
    allv = allv[np.isfinite(allv)]
    lo, hi = (float(allv.min()), float(allv.max())) if allv.size else (0.0, 1.0)
    if hi - lo < 1e-12:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, bins + 1)
    mid = 0.5 * (edges[:-1] + edges[1:])
    data = []
    for k, (n, v) in enumerate(groups.items()):
        v = np.asarray(v, float)
        v = v[np.isfinite(v)]
        cnt, _ = np.histogram(v, edges)
        data.append(dict(type="bar", x=mid, y=cnt, name=n, marker=dict(color=PALETTE[k % len(PALETTE)]), opacity=0.8))
    lay = base_layout(title, barmode="overlay", xaxis=dict(title=xtitle), yaxis=dict(title="Cells", gridcolor=LINE))
    return dict(data=data, layout=lay)


def layer_map(values2d, title=None, ztitle="", colorscale=None):
    """Map of one layer in I / J index space (valid for rotated and non-uniform grids alike)."""
    nj, ni = values2d.shape
    tr = dict(type="heatmap", x=np.arange(1, ni + 1), y=np.arange(1, nj + 1), z=values2d, colorscale=colorscale or "Viridis",
              colorbar=dict(title=ztitle), hovertemplate="I %{x}, J %{y}: %{z:.4g}<extra></extra>")
    lay = base_layout(title, xaxis=dict(title="I", showgrid=False), yaxis=dict(title="J", showgrid=False, scaleanchor="x"))
    return dict(data=[tr], layout=lay)


# ---------------------------------------------------------------------------------------------
# property cross-sections (grid cells as colour-bucketed polygons)
def _poly_trace(x, z, colour, name, axis_ids):
    xs, zs = [], []
    for a, b in zip(x, z):
        xs += [*a, a[0], None]
        zs += [*b, b[0], None]
    return dict(type="scatter", mode="lines", x=xs, y=zs, fill="toself", fillcolor=colour, line=dict(width=0.4, color=colour),
                hoverinfo="skip", showlegend=False, name=name, **axis_ids)


def property_section(panels, title=None, ve=None, show_contacts=True, show_faults=True, max_hover=6000):
    """panels: list (max 3) of dict(name, unit, sec=<gridsection dict>, discrete=bool, vmin, vmax, stops)."""
    from core import gridsection as gs
    n = max(1, min(3, len(panels)))
    gap = 0.07
    h = (1.0 - gap * (n - 1)) / n
    data, lay = [], base_layout(title, margin=dict(l=65, r=70, t=45 if title else 20, b=50), showlegend=True)
    for p, pan in enumerate(panels[:n]):
        sec = pan["sec"]
        dom = [1.0 - (p + 1) * h - p * gap, 1.0 - p * (h + gap)]
        sfx = "" if p == 0 else str(p + 1)
        ids = dict(xaxis="x" + sfx, yaxis="y" + sfx)
        stops = pan.get("stops") or gs.STOPS
        if len(sec["v"]) == 0:
            lay["yaxis" + sfx] = dict(domain=dom, autorange="reversed")
            lay["xaxis" + sfx] = dict(anchor="y" + sfx)
            continue
        scale = pan.get("scale")
        if scale and scale["kind"] == "discrete":
            codes = scale.get("codes", np.arange(len(scale["colors"])) + scale["first"])
            idx = np.searchsorted(codes, sec["v"])
            bk = [(code, code, color) for code, color in zip(codes, scale["colors"])]
            vmin, vmax = -0.5, len(codes) - 0.5
            color_values = idx
            cs = [[v, c] for i, c in enumerate(scale["colors"])
                  for v in (i / len(codes), (i + 1) / len(codes))]
        else:
            color_values = scale["values"].ravel()[sec["cell_ids"]] if scale else sec["v"]
            idx, bk, vmin, vmax = gs.colour_buckets(color_values, pan.get("discrete", False),
                vmin=scale["vmin"] if scale else pan.get("vmin"), vmax=scale["vmax"] if scale else pan.get("vmax"), stops=stops)
            cs = [[i / (len(stops) - 1), c] for i, c in enumerate(stops)]
        for b, (lo, hi, col) in enumerate(bk):
            m = idx == b
            if m.any():
                data.append(_poly_trace(sec["x"][m], sec["z"][m], col, pan["name"], ids))
        cx, cz, cv = sec["x"].mean(axis=1), sec["z"].mean(axis=1), sec["v"]
        step = max(1, len(cv) // max_hover)
        data.append(dict(type="scatter", mode="markers", x=cx[::step], y=cz[::step], showlegend=False, **ids,
                         marker=dict(size=5, opacity=0.0, color=color_values[::step], colorscale=cs, cmin=vmin, cmax=vmax, showscale=True,
                                     colorbar=dict(title=dict(text=f"{pan['name']}" + (f" ({pan['unit']})" if pan.get("unit") else ""), font=dict(size=11)),
                                                   len=h * 0.95, y=(dom[0] + dom[1]) / 2, yanchor="middle", thickness=12)),
                         text=[f"{pan['name']} = {v:.4g}" for v in cv[::step]], hovertemplate="%{text}<br>depth %{y:.1f}<extra></extra>"))
        if scale and scale["kind"] == "discrete":
            data[-1]["marker"]["colorbar"].update(tickvals=list(range(len(codes))), ticktext=[str(c) for c in codes])
        if show_contacts:
            for nme, c in sec["contacts"].items():
                xs, zs = [], []
                for a, b, z in zip(c["x0"], c["x1"], c["z"]):
                    if np.isfinite(z):
                        xs += [a, b, None]
                        zs += [z, z, None]
                data.append(dict(type="scatter", mode="lines", x=xs, y=zs, line=dict(color="#D7263D" if nme == "OWC" else "#E8A33D", width=2, dash="dash"),
                                 name=nme, showlegend=p == 0, hoverinfo="skip", **ids))
        if show_faults:
            for fc in sec["faults"]:
                data.append(dict(type="scatter", mode="lines", x=[fc["dist"]] * 2, y=[sec["zmin"], sec["zmax"]], line=dict(color=fc.get("color", "#222"), width=1.5, dash="dot"),
                                 name=fc["name"], showlegend=p == 0, hoverinfo="name", **ids))
        lay["yaxis" + sfx] = dict(domain=dom, autorange="reversed", title=f"Depth ({un.z()})", gridcolor=LINE, anchor="x" + sfx)
        lay["xaxis" + sfx] = dict(anchor="y" + sfx, showgrid=False, title=f"{sec['coord_label']} ({un.xy()})" if p == n - 1 else None,
                                  matches="x" if p else None)
        if ve and n == 1:
            lay["yaxis"]["scaleanchor"] = "x"
            lay["yaxis"]["scaleratio"] = float(ve)
    return _plain(dict(data=data, layout=lay))


def _plain(o):
    """JSON-safe copy: numpy arrays / scalars -> lists / floats, NaN -> None."""
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, np.ndarray):
        return _plain(o.tolist())
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


def variogram_plot(evs: dict, fits: Optional[dict] = None, vtype: str = "spherical", title=None):
    """Experimental semivariograms (points) with the fitted unit-sill model (lines); ``evs`` = {"horizontal"|"vertical": result}."""
    from core.geostat import corr_value
    data = []
    for k, (n, ev) in enumerate(evs.items()):
        if ev is None:
            continue
        col = PALETTE[k % len(PALETTE)]
        data.append(dict(type="scatter", mode="markers", x=ev["lag"], y=ev["gamma"] / max(ev["var"], 1e-12), name=f"{n} (data)",
                         marker=dict(color=col, size=7), text=[f"{c} pairs" for c in ev["npairs"]], hovertemplate="%{x:.1f}: %{y:.3f} (%{text})<extra></extra>"))
        ft = (fits or {}).get(n)
        if ft:
            h = np.linspace(0, max(ev["lag"].max(), ft["range"]) * 1.1, 60)
            m = ft["nugget"] + (1 - ft["nugget"]) * (1 - corr_value(h / ft["range"], vtype))
            data.append(dict(type="scatter", mode="lines", x=h, y=m, name=f"{n} model (range {ft['range']:.0f})", line=dict(color=col, width=2)))
    lay = base_layout(title, xaxis=dict(title=f"Lag ({un.xy()} / {un.z()})"), yaxis=dict(title="Semivariance / variance", gridcolor=LINE))
    return dict(data=data, layout=lay)
