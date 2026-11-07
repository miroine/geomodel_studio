"""Session helpers shared by the views."""
from __future__ import annotations

import uuid
from typing import Dict, List
import numpy as np
import pandas as pd
import streamlit as st
from core import units as un

from core.project import Project
from core.surface import Geometry, Surface, fill_nan_nearest
from core.faults import Fault


def proj() -> Project:
    if "proj" not in st.session_state:
        st.session_state["proj"] = Project()
        st.session_state["rev"] = 0
    p = st.session_state["proj"]
    un.set_active(p.crs)
    return p


def rev() -> int:
    return st.session_state.get("rev", 0)


def k(name: str, opts=None) -> str:
    """Widget key that changes when a whole project is replaced (avoids stale keyed widgets).

    Pass ``opts`` for select-type widgets whose option list can change: the key then also changes with the
    options, so a stale selection can never point at an option that no longer exists."""
    if opts is not None:
        import hashlib
        name += "_" + hashlib.md5("|".join(map(str, opts)).encode()).hexdigest()[:6]
    return f"{name}_{rev()}"


def replace_project(p: Project):
    st.session_state["proj"] = p
    st.session_state["rev"] = rev() + 1
    st.session_state["focus"] = None
    for key in list(st.session_state.keys()):
        if key.startswith(("nonce_", "sel_", "tmp_")):
            del st.session_state[key]


def need_lattice(p: Project) -> bool:
    if not p.has_lattice():
        st.warning("Define the model area first (Project page), or load the demo project.")
        return False
    return True


def ensure_step_ids(p: Project):
    """Keep step IDs unique and stable, repairing older projects with duplicated steps."""
    reserved = {s["_id"] for s in p.steps if s.get("_id")}
    seen = set()
    for i, s in enumerate(p.steps):
        uid = s.get("_id")
        if not uid or uid in seen:
            # A repeated dict must be detached before changing its ID.
            s = dict(s)
            p.steps[i] = s
            uid = new_id()
            while uid in reserved:
                uid = new_id()
            s["_id"] = uid
            reserved.add(uid)
        seen.add(uid)


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def lattice_surface(p: Project, name: str, fill: bool = True) -> np.ndarray:
    """Library surface resampled onto the model lattice. fill=True nearest-fills undefined nodes (modelling);
    fill=False keeps clipped / filtered nodes undefined (display)."""
    if not fill:
        return p.surfaces[name].resample_to(p.lattice, extrapolate=False).z
    return fill_nan_nearest(p.surfaces[name].resample_to(p.lattice, extrapolate=True).z)


# ---- navigation (object tree) --------------------------------------------------------------
def go(page: str, kind: str = None, name: str = None):
    """on_click callback of the object-tree buttons."""
    st.session_state["nav"] = page
    st.session_state["focus"] = (kind, name) if kind else None


def focus(kind: str):
    """Name of the object selected in the tree when it is of ``kind`` (else None)."""
    f = st.session_state.get("focus")
    return f[1] if f and f[0] == kind else None


def pick(label: str, names: list, key: str, kind: str, **kw):
    """selectbox that opens on the object clicked in the tree.  The key carries the focus so the default applies."""
    f = focus(kind)
    idx = names.index(f) if f in names else 0
    return st.selectbox(label, names, index=idx, key=k(key, names) + f"_{f}", **kw)


def hcolors(p: Project) -> dict:
    from ui.theme import PALETTE
    hs = list(dict.fromkeys(p.tops["horizon"].tolist())) if len(p.tops) else []
    cols = ["#F46036", "#6A4C93", "#1B998B", "#C5A100", "#D7263D", "#00A9F4"]
    return {h: cols[i % len(cols)] for i, h in enumerate(hs)}


def grid_view_layers(grid, prefix: str) -> np.ndarray:
    """Display-only layer selection shared by the 3D window and grid cut-away."""
    signature = [grid.nk, *grid.layer_zone.tolist(), *(z.name for z in grid.zones)]
    mode = st.selectbox("Filter grid view by", ["All cells", "Zones", "Layers", "Zones and layers"],
                        key=k(prefix + "_filter", signature))
    visible = np.ones(grid.nk, dtype=bool)
    if mode in ("Zones", "Zones and layers"):
        zones = list(range(len(grid.zones)))
        selected = st.multiselect("Visible zones", zones, default=zones, format_func=lambda zi: grid.zones[zi].name,
                                  key=k(prefix + "_zones", signature))
        visible &= np.isin(grid.layer_zone, selected)
    if mode in ("Layers", "Zones and layers"):
        if grid.nk > 1:
            first, last = st.slider("Visible layer range (k, inclusive)", 1, grid.nk, (1, grid.nk),
                                    key=k(prefix + "_layers", signature))
        else:
            first = last = 1
            st.caption("The grid has one layer (k = 1).")
        layers = np.arange(1, grid.nk + 1)
        visible &= (layers >= first) & (layers <= last)
    if not visible.any():
        st.warning("No grid layers match the current view filters.")
    elif not (grid.actnum[visible] > 0).any():
        st.warning("The selected layers contain no active grid cells.")
    st.caption("Display only: zone and layer filters do not change the model or exports. Layer numbers are global, starting at 1.")
    return visible


def build_scene(p: Project, surfaces=None, faults=True, polygons=True, wells=True, tops=True, grid=None, prop="Zone",
                i0=0, j0=0, clip_to_boundary=False, well_scale=1.0, hidden=(), surface_opacity=1.0, max_nodes=140_000,
                horizons=None, props=None, layer_mask=None):
    """Assemble the WebGL scene for the 3D window and the inline previews.

    ``surfaces``: library surfaces; ``horizons``: names of structural-model horizons (faulted / calibrated result)."""
    from ui.scene import Scene
    from core import polygons as pg
    lat = p.lattice
    sc = Scene((lat.xori, lat.yori))
    names = list(p.surfaces) if surfaces is None else [n for n in surfaces if n in p.surfaces]
    mask = None
    bpoly = p.boundary_poly()
    if clip_to_boundary and bpoly is not None:
        X, Y = lat.coords()
        mask = pg.inside(X, Y, bpoly.pts)
    hz = []
    if horizons and p.structure is not None:
        Zall = p.structure.lattice_depths()
        hz = [(h, Zall[p.structure.names.index(h)]) for h in horizons if h in p.structure.names]
    # one depth colour range for everything that is coloured by depth, so colours are comparable across objects
    vals = [p.surfaces[n].z for n in names] + [z for _, z in hz]
    fin = [float(np.nanmin(z)) for z in vals if np.isfinite(z).any()], [float(np.nanmax(z)) for z in vals if np.isfinite(z).any()]
    vr = (min(fin[0]), max(fin[1])) if fin[0] else None
    shown = []
    for n in names:
        s = p.surfaces[n]
        if mask is not None and not s.geom.same_lattice(lat):
            s = s.resample_to(lat)
        sc.surface(s, visible=(n not in hidden), mask=mask if s.geom.same_lattice(lat) else None, opacity=surface_opacity,
                   max_nodes=max_nodes, vrange=vr)
        shown.append(n)
    for h, z in hz:
        sc.surface(Surface(h, lat, z), group="Structural model", mask=mask, opacity=surface_opacity, max_nodes=max_nodes, vrange=vr)
    zlo, zhi = vr if vr else (1000.0, 3000.0)
    if grid is not None:
        sc.grid(grid, prop, i0, j0, props=props if props is not None else p.properties, layer_mask=layer_mask)
        zlo = min(zlo, float(grid.zc.min()))
        zhi = max(zhi, float(grid.zc.max()))
    ref = p.surfaces[shown[0]] if shown else (Surface(hz[0][0], lat, hz[0][1]) if hz else None)
    _context(sc, p, zlo, zhi, ref, faults and p.faults, polygons, wells, tops, well_scale)
    return sc


def _context(sc, p, zlo, zhi, ref, faults, polygons, wells, tops, well_scale=1.0):
    """Faults, polygons, wells / tops around the main objects of a scene."""
    lat = p.lattice
    if faults:
        sc.faults(faults if isinstance(faults, dict) else {f.name: f for f in faults}, zlo, zhi)
    if polygons:
        for n, poly in p.polygons.items():
            sc.polygon(poly, ref=ref, zlevel=zlo, color="#00A9F4" if n == p.boundary else "#051C2C")
    if wells and p.wells:
        x0, x1, y0, y1 = lat.bounds()
        radius = 0.0035 * max(x1 - x0, y1 - y0) * well_scale
        hc = hcolors(p)
        for w in p.wells.values():
            sc.well(w, p.tops if tops else None, radius=radius, hcolors=hc, z_start=zlo - 0.15 * (zhi - zlo) - 50)
    elif tops and len(p.tops):
        sc.tops_points(p.tops)


def scene_from_arrays(p: Project, items, faults=None, polygons=False, wells=True, tops=True, clip=True, depth_color=None, well_scale=1.0):
    """Scene from ``[(name, Z on the model lattice)]`` (structural-model horizons, faulted previews ...)."""
    from ui.scene import Scene
    from ui.theme import PALETTE
    from core import polygons as pg
    lat = p.lattice
    sc = Scene((lat.xori, lat.yori))
    bp = p.boundary_poly() if clip else None
    mask = None
    if bp is not None:
        X, Y = lat.coords()
        mask = pg.inside(X, Y, bp.pts)
    single = (len(items) == 1) if depth_color is None else depth_color
    zs = []
    for i, (n, Z) in enumerate(items):
        Z = np.asarray(Z, float)
        if np.isfinite(Z).any():
            zs += [float(np.nanmin(Z)), float(np.nanmax(Z))]
        sc.surface(Surface(n, lat, Z), color=PALETTE[i % len(PALETTE)], color_by_depth=single, mask=mask)
    zlo, zhi = (min(zs), max(zs)) if zs else (1000.0, 3000.0)
    _context(sc, p, zlo, zhi, Surface(items[0][0], lat, np.asarray(items[0][1], float)) if items else None, faults, polygons, wells, tops, well_scale)
    return sc


def wells_for_plot(tops: pd.DataFrame, horizon: str = None, label_horizon=True) -> List[dict]:
    if tops is None or tops.empty:
        return []
    t = tops if horizon is None else tops[tops["horizon"] == horizon]
    return [dict(x=float(r.x), y=float(r.y), z=float(r.z), label=(f"{r.well} {r.horizon}" if label_horizon and horizon is None else r.well))
            for r in t.itertuples()]


def sync_fault_step(p: Project):
    """Keep the workflow's 'faults' step consistent with the fault list (new faults are switched on)."""
    names = list(p.faults.keys())
    step = next((s for s in p.steps if s["type"] == "faults"), None)
    if step is None:
        if names:
            p.steps.insert(0, dict(type="faults", faults=names, _id=new_id()))
        return
    keep = [n for n in step.get("faults", []) if n in p.faults]
    step["faults"] = keep + [n for n in names if n not in keep and n not in step.get("_off", [])]


def surface_table(p: Project) -> pd.DataFrame:
    rows = []
    for n, s in p.surfaces.items():
        st_ = s.stats()
        g = s.geom
        nops = sum(1 for o in p.filters.get(n, {}).get("ops", []) if o.get("enabled", True))
        rows.append({"Surface": n, "Source": s.source, "Grid": f"{g.ncol} x {g.nrow}", "dx x dy": f"{g.xinc:g} x {g.yinc:g}",
                     "Rotation": g.rotation, "Min z": round(st_["min"], 1), "Max z": round(st_["max"], 1),
                     "Mean z": round(st_["mean"], 1), "Defined": f"{st_['defined'] * 100:.0f} %", "Filters": nops or ""})
    return pd.DataFrame(rows)
