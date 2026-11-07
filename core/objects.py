"""Petrel/RMS-style object tree: one node per data object and per modelling step."""
from __future__ import annotations

from typing import List
from .project import Project

# (group, kind, page) -- page is the app page that edits the object kind
GROUPS = [
    ("Input data", [("surface", "Surfaces", "Surfaces"), ("polygon", "Polygons", "Polygons"),
                    ("fault", "Faults", "Faults"), ("well", "Wells", "Wells"), ("tops", "Well tops", "Well tops")]),
    ("Models", [("structure", "Structural model", "Structural model"), ("zone", "Zones", "Zones & layering"),
                ("grid", "3D grid", "3D grid"), ("prop", "Properties", "Properties")]),
    ("Analysis", [("vol", "Volumetrics", "Volumetrics"), ("analysis", "Analysis & sections", "Analysis & sections"), ("upscale", "Upscaling", "Upscaling")]),
]


def items(p: Project, kind: str) -> List[dict]:
    """Objects of one kind: dicts with name, info and state (ok / stale / missing)."""
    out = []
    if kind == "surface":
        for n, s in p.surfaces.items():
            nops = sum(1 for o in p.filters.get(n, {}).get("ops", []) if o.get("enabled", True))
            out.append(dict(name=n, info=f"{s.geom.ncol}x{s.geom.nrow}" + (f", {nops} filter(s)" if nops else ""), state="ok"))
    elif kind == "polygon":
        for n, poly in p.polygons.items():
            out.append(dict(name=n, info=f"{len(poly.pts)} pts" + (", model boundary" if n == p.boundary else ""), state="ok"))
    elif kind == "fault":
        for n, f in p.faults.items():
            out.append(dict(name=n, info=f"{f.ftype}, throw {f.throw:g} m", state="ok"))
    elif kind == "well":
        for n, w in p.wells.items():
            out.append(dict(name=n, info=w.kind, state="ok"))
    elif kind == "tops":
        if len(p.tops):
            out.append(dict(name="Well tops", info=f"{len(p.tops)} picks, {p.tops['well'].nunique()} wells", state="ok"))
    elif kind == "structure":
        out.append(dict(name="Structural model", info=f"{len(p.steps)} steps" + (f", {len(p.structure.names)} horizons" if p.structure else ", not run"),
                        state="ok" if p.structure else "missing"))
    elif kind == "zone":
        if p.zones:
            out.append(dict(name="Zones", info=f"{len(p.zones)} zones, {sum(z.nlayers for z in p.zones)} layers", state="ok"))
    elif kind == "grid":
        out.append(dict(name="3D grid", info=(f"{p.grid.ni}x{p.grid.nj}x{p.grid.nk}" if p.grid else "not built"),
                        state="ok" if p.grid else "missing"))
    elif kind == "vol":
        if p.grid is not None:
            c = p.volumetrics.get("contacts") if p.volumetrics else None
            out.append(dict(name="Volumetrics", info=(f"OWC {c['owc']:g}" + (f", GOC {c['goc']:g}" if c.get("goc") is not None else "")) if c else "not set up", state="ok" if c else "missing"))
    elif kind == "analysis":
        if p.grid is not None and p.properties:
            out.append(dict(name="Analysis & sections", info=f"{len(p.properties)} properties", state="ok"))
    elif kind == "upscale":
        if p.grid is not None:
            u = p.upscale or {}
            out.append(dict(name="Upscaling", info=(f"{u['ci']}x{u['cj']} columns" if u.get("ci") else "not set up"), state="ok" if u.get("ci") else "missing"))
    elif kind == "prop":
        for n, pr_ in p.properties.items():
            out.append(dict(name=n, info=f"{pr_.kind}, {pr_.source}" + (" - stale" if pr_.stale else ""), state="stale" if pr_.stale else "ok"))
    return out


def tree(p: Project) -> List[dict]:
    return [dict(group=g, kinds=[dict(kind=k, label=lab, page=pg, items=items(p, k)) for k, lab, pg in kinds]) for g, kinds in GROUPS]
