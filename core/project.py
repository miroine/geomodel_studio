"""Project container + save/load (zip with JSON + NPZ + CSV)."""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from .surface import Geometry, Surface
from .faults import Fault
from .cpgrid import ZoneSpec, CPGrid
from .workflow import Structure
from . import filters as flt
from .polygons import Polygon
from . import units as un
from .wells import Well
from . import props as pr

FORMAT_VERSION = 4


@dataclass
class Project:
    name: str = "Untitled model"
    lattice: Optional[Geometry] = None
    surfaces: Dict[str, Surface] = field(default_factory=dict)
    faults: Dict[str, Fault] = field(default_factory=dict)
    tops: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["well", "x", "y", "horizon", "z"]))
    steps: List[dict] = field(default_factory=list)
    zones: List[ZoneSpec] = field(default_factory=list)
    grid_params: dict = field(default_factory=lambda: dict(dx=100.0, dy=100.0, min_thickness=0.1))
    properties: Dict[str, "pr.Property"] = field(default_factory=dict)      # cell properties linked to the 3D grid
    fault_mult: dict = field(default_factory=dict)                          # fault name -> transmissibility multiplier (MULTFLT)
    volumetrics: dict = field(default_factory=dict)                         # settings of the volumetrics workflow
    facies: dict = field(default_factory=dict)                              # settings of the facies modelling workflow
    upscale: dict = field(default_factory=dict)                             # settings of the upscaling page
    stochastic: dict = field(default_factory=dict)                          # settings of the stochastic property workflow
    digitized: dict = field(default_factory=lambda: dict(contours=[], points=[], faults=[], calib=None))
    polygons: Dict[str, Polygon] = field(default_factory=dict)
    wells: Dict[str, Well] = field(default_factory=dict)
    logs: Dict[str, dict] = field(default_factory=dict)            # well -> dict(md, curves{name: array}, units{name: str})
    fences: Dict[str, Polygon] = field(default_factory=dict)      # open polylines for cross-sections
    crs: dict = field(default_factory=lambda: dict(un.DEFAULT_CRS))    # name, epsg, xy_unit, z_unit, z_positive, vdatum
    boundary: Optional[str] = None                      # name of the model boundary polygon
    raw: Dict[str, np.ndarray] = field(default_factory=dict)       # unfiltered depth maps
    filters: Dict[str, dict] = field(default_factory=dict)         # name -> {ops, undo, redo}
    filter_presets: Dict[str, List[dict]] = field(default_factory=dict)
    # runtime (not saved)
    structure: Optional[Structure] = None
    grid: Optional[CPGrid] = None

    def invalidate(self, level="structure"):
        """Drop derived results after an upstream change."""
        if level == "structure":
            self.structure = None
        self.grid = None

    def set_grid(self, g) -> List[str]:
        """Install a freshly built grid and reconcile the stored properties with it."""
        self.grid = g
        return pr.attach_grid(self.properties, g)

    def has_lattice(self):
        return self.lattice is not None

    # ---- surfaces with a non-destructive filter stack ----------------------
    def put_surface(self, s: Surface):
        """Add / replace a surface; its values become the raw map and any filter stack is reset."""
        self.surfaces[s.name] = s
        self.raw[s.name] = s.z.copy()
        self.filters[s.name] = dict(ops=[], undo=[], redo=[])
        self.invalidate()

    def fstate(self, name: str) -> dict:
        if name not in self.raw:
            self.raw[name] = self.surfaces[name].z.copy()
        return self.filters.setdefault(name, dict(ops=[], undo=[], redo=[]))

    def recompute(self, name: str):
        st = self.fstate(name)
        s = self.surfaces[name]
        z, rep = flt.apply_stack(self.raw[name], s.geom, st["ops"], self.polygons)
        s.z = z
        self.invalidate()
        return rep

    def recompute_all(self):
        for n, st in self.filters.items():
            if n in self.surfaces and st["ops"]:
                self.recompute(n)

    def commit_filter(self, name: str, ops: List[dict]):
        """Replace the op list, remembering the previous one for undo."""
        st = self.fstate(name)
        st["undo"].append(json.loads(json.dumps(st["ops"])))
        st["undo"] = st["undo"][-50:]
        st["redo"] = []
        st["ops"] = json.loads(json.dumps(ops))
        return self.recompute(name)

    def undo_filter(self, name: str):
        st = self.fstate(name)
        if not st["undo"]:
            return None
        st["redo"].append(json.loads(json.dumps(st["ops"])))
        st["ops"] = st["undo"].pop()
        return self.recompute(name)

    def redo_filter(self, name: str):
        st = self.fstate(name)
        if not st["redo"]:
            return None
        st["undo"].append(json.loads(json.dumps(st["ops"])))
        st["ops"] = st["redo"].pop()
        return self.recompute(name)

    def reset_filter(self, name: str):
        return self.commit_filter(name, [])

    def rename_surface(self, old: str, new: str):
        self.surfaces = {(new if k == old else k): v for k, v in self.surfaces.items()}
        self.surfaces[new].name = new
        for d in (self.raw, self.filters):
            if old in d:
                d[new] = d.pop(old)

    def delete_surface(self, name: str):
        for d in (self.surfaces, self.raw, self.filters):
            d.pop(name, None)
        self.invalidate()

    def boundary_poly(self) -> Optional[Polygon]:
        return self.polygons.get(self.boundary) if self.boundary else None

    def grid_bounds(self):
        """Grid extent: lattice bounds, tightened to the boundary polygon when one is set."""
        xmin, xmax, ymin, ymax = self.lattice.bounds()
        b = self.boundary_poly()
        if b is not None:
            bx0, bx1, by0, by1 = b.bounds()
            xmin, xmax, ymin, ymax = max(xmin, bx0), min(xmax, bx1), max(ymin, by0), min(ymax, by1)
        return xmin, xmax, ymin, ymax


# ---------------------------------------------------------------------------
def to_bytes(p: Project) -> bytes:
    meta = dict(
        version=FORMAT_VERSION, name=p.name,
        lattice=p.lattice.to_dict() if p.lattice else None,
        faults=[f.to_dict() for f in p.faults.values()],
        steps=p.steps, zones=[z.to_dict() for z in p.zones],
        grid_params=p.grid_params, digitized=p.digitized,
        surfaces={n: dict(geom=s.geom.to_dict(), source=s.source) for n, s in p.surfaces.items()},
        polygons=[v.to_dict() for v in p.polygons.values()], fences=[v.to_dict() for v in p.fences.values()], wells=[w.to_dict() for w in p.wells.values()],
        boundary=p.boundary, filters={n: p.filters.get(n, dict(ops=[], undo=[], redo=[])) for n in p.surfaces},
        filter_presets=p.filter_presets, crs=p.crs, properties=[v.meta() for v in p.properties.values()], stochastic=p.stochastic, volumetrics=p.volumetrics, fault_mult=p.fault_mult, upscale=p.upscale, facies=p.facies,
        logs={w: dict(curves=list(l["curves"]), units=l.get("units", {})) for w, l in p.logs.items()},
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(meta, indent=1))
        arrs = io.BytesIO()
        np.savez_compressed(arrs, **{f"s{i}": s.z for i, s in enumerate(p.surfaces.values())})
        z.writestr("surfaces.npz", arrs.getvalue())
        raws = io.BytesIO()
        np.savez_compressed(raws, **{f"s{i}": p.raw.get(n, s.z) for i, (n, s) in enumerate(p.surfaces.items())})
        z.writestr("raw.npz", raws.getvalue())
        z.writestr("tops.csv", p.tops.to_csv(index=False))
        if p.properties:
            z.writestr("props.npz", pr.props_to_npz(p.properties))
        if p.logs:
            lb = io.BytesIO()
            arrs_ = {}
            for wi, (w, l) in enumerate(p.logs.items()):
                arrs_[f"w{wi}_md"] = np.asarray(l["md"], float)
                for ci, c in enumerate(l["curves"]):
                    arrs_[f"w{wi}_c{ci}"] = np.asarray(l["curves"][c], np.float32)
            np.savez_compressed(lb, **arrs_)
            z.writestr("logs.npz", lb.getvalue())
    return buf.getvalue()


def from_bytes(data: bytes) -> Project:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        meta = json.loads(z.read("project.json"))
        npz = np.load(io.BytesIO(z.read("surfaces.npz")))
        tops = pd.read_csv(io.BytesIO(z.read("tops.csv")))
        raw = np.load(io.BytesIO(z.read("raw.npz"))) if "raw.npz" in z.namelist() else None
        pdata = z.read("props.npz") if "props.npz" in z.namelist() else None
        ldata = z.read("logs.npz") if "logs.npz" in z.namelist() else None
    p = Project(name=meta["name"])
    p.lattice = Geometry.from_dict(meta["lattice"]) if meta.get("lattice") else None
    for i, (n, d) in enumerate(meta["surfaces"].items()):
        p.surfaces[n] = Surface(n, Geometry.from_dict(d["geom"]), npz[f"s{i}"], d.get("source", ""))
    for i, n in enumerate(p.surfaces):
        p.raw[n] = raw[f"s{i}"] if raw is not None else p.surfaces[n].z.copy()
        p.filters[n] = meta.get("filters", {}).get(n) or dict(ops=[], undo=[], redo=[])
    p.polygons = {d["name"]: Polygon.from_dict(d) for d in meta.get("polygons", [])}
    p.fences = {d["name"]: Polygon.from_dict(d) for d in meta.get("fences", [])}
    p.wells = {d["name"]: Well.from_dict(d) for d in meta.get("wells", [])}
    p.crs = {**un.DEFAULT_CRS, **(meta.get("crs") or {})}
    p.boundary = meta.get("boundary")
    p.filter_presets = meta.get("filter_presets", {})
    p.faults = {f["name"]: Fault.from_dict(f) for f in meta["faults"]}
    p.steps = meta["steps"]
    p.zones = [ZoneSpec.from_dict(z) for z in meta["zones"]]
    p.grid_params = meta.get("grid_params", p.grid_params)
    p.digitized = meta.get("digitized", p.digitized)
    p.tops = tops if len(tops) else p.tops
    p.stochastic = meta.get("stochastic", {}) or {}
    p.volumetrics = meta.get("volumetrics", {}) or {}
    p.fault_mult = meta.get("fault_mult", {}) or {}
    p.upscale = meta.get("upscale", {}) or {}
    p.facies = meta.get("facies", {}) or {}
    if ldata is not None and meta.get("logs"):
        ln = np.load(io.BytesIO(ldata))
        for wi, (w, d) in enumerate(meta["logs"].items()):
            p.logs[w] = dict(md=ln[f"w{wi}_md"], curves={c: ln[f"w{wi}_c{ci}"].astype(float) for ci, c in enumerate(d["curves"])}, units=d.get("units", {}))
    if pdata is not None and meta.get("properties"):
        p.properties = pr.props_from_npz(meta["properties"], pdata)
    return p
