"""Properties derived from horizontal planes (contacts, user depths) and from the fault-block structure:
height above a plane, fraction of a cell above a plane, region between planes, contact maps, fault-block REGION and SEGMENT."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np

from . import props as pp
from . import volumetrics as V


class RegionError(Exception):
    pass


def _tb(grid):
    top = grid.zc[:, 0].mean(axis=(2, 4))
    bot = grid.zc[:, 1].mean(axis=(2, 4))
    return top, bot, 0.5 * (top + bot)


def _safe(name: str) -> str:
    n = "".join(ch if ch.isalnum() else "_" for ch in name.strip().upper())
    return n[:20] or "PLANE"


def plane_properties(grid, planes: List[Tuple[str, float]], z_unit: str = "") -> Dict[str, "pp.Property"]:
    """planes = [(name, depth)].  Per plane: HAP_<n> height above the plane (plane depth - cell-centre depth, positive above) and
    FRAC_<n> fraction of the cell height above the plane; plus PLANE_REGION (discrete: 1 above the shallowest plane ... n+1 below the deepest)."""
    if not planes:
        raise RegionError("Define at least one plane.")
    names = [_safe(n) for n, _ in planes]
    if len(set(names)) != len(names):
        raise RegionError("Plane names must be unique.")
    top, bot, centre = _tb(grid)
    h = np.maximum(bot - top, 1e-9)
    out = {}
    for nm, (_, d) in zip(names, planes):
        out["HAP_" + nm] = pp.make_property(grid, "HAP_" + nm, float(d) - centre, "continuous", z_unit, "planes", f"plane {nm} at {d:g}")
        out["FRAC_" + nm] = pp.make_property(grid, "FRAC_" + nm, np.clip((float(d) - top) / h, 0, 1), "continuous", "frac", "planes", f"plane {nm} at {d:g}")
    order = np.argsort([d for _, d in planes])
    depths = np.array([planes[i][1] for i in order], float)
    reg = np.searchsorted(depths, centre, side="right") + 1          # 1 = above the shallowest plane
    labels = {}
    sn = [names[i] for i in order]
    for r in range(len(depths) + 1):
        labels[str(r + 1)] = (f"above {sn[0]}" if r == 0 else f"below {sn[-1]}" if r == len(depths) else f"{sn[r - 1]} - {sn[r]}")
    out["PLANE_REGION"] = pp.make_property(grid, "PLANE_REGION", reg, "discrete", "", "planes", "regions between planes " + ", ".join(sn), labels)
    return out


def contact_properties(grid, cfg, z_unit: str = "", props=None) -> Dict[str, "pp.Property"]:
    """OWC / GOC depth maps expanded to 3D, height above each contact, and FLUID (1 gas, 2 oil, 3 water) from the volumetrics contacts."""
    if V.check_config(grid, cfg):
        raise RegionError(" ".join(V.check_config(grid, cfg)))
    owc3, goc3, _ = V.contact_cubes(grid, cfg, props)
    _, _, centre = _tb(grid)
    shape = centre.shape
    out = {"OWC_DEPTH": pp.make_property(grid, "OWC_DEPTH", owc3, "continuous", z_unit, "planes", "OWC from the volumetrics set-up"),
           "HAOWC": pp.make_property(grid, "HAOWC", owc3 - centre, "continuous", z_unit, "planes", "height above OWC")}
    if np.isfinite(goc3).any():
        out["GOC_DEPTH"] = pp.make_property(grid, "GOC_DEPTH", goc3, "continuous", z_unit, "planes", "GOC from the volumetrics set-up")
        out["HAGOC"] = pp.make_property(grid, "HAGOC", goc3 - centre, "continuous", z_unit, "planes", "height above GOC")
    out["FLUID"] = pp.make_property(grid, "FLUID", V.fluid_array(grid, cfg, None, props), "discrete", "", "volumetrics", "fluid from contacts", V.FLUID_LEGEND)
    return out


SEGMENT_MODES = ["fault block", "zone x fault block", "zone x fault block x fluid"]


def region_segment(grid, mode: str = "zone x fault block", fluid: Optional[np.ndarray] = None) -> Dict[str, "pp.Property"]:
    """FAULT_BLOCK and REGION (= fault-block number, 1..n) and SEGMENT (numbered combinations that actually contain active cells).
    The legend of each discrete property gives the names (REGION: 'Block 2'; SEGMENT: 'Reservoir / Block 2 / oil')."""
    shape = (grid.nk, grid.nj, grid.ni)
    blk = grid.block_array().astype(int)
    zone = np.broadcast_to(grid.layer_zone[:, None, None], shape).astype(int)
    nb = int(grid.block.max())
    out = {}
    rl = {str(b): f"Block {b}" for b in range(1, nb + 1)}
    out["FAULT_BLOCK"] = pp.make_property(grid, "FAULT_BLOCK", blk, "discrete", "", "regions", "fault block from the fault traces", rl)
    out["REGION"] = pp.make_property(grid, "REGION", blk, "discrete", "", "regions", "region = fault block", rl)
    act = grid.actnum > 0
    if mode == "fault block":
        key = blk
        namer = lambda c: f"Block {c[0]}"
        cols = [blk]
    elif mode == "zone x fault block":
        cols = [zone, blk]
        namer = lambda c: f"{grid.zones[c[0]].name} / Block {c[1]}"
    elif mode == "zone x fault block x fluid":
        if fluid is None:
            raise RegionError("Segments with fluid need the contacts (Volumetrics set-up) or a stored FLUID property.")
        cols = [zone, blk, np.rint(fluid).astype(int)]
        namer = lambda c: f"{grid.zones[c[0]].name} / Block {c[1]} / {V.FLUID_LEGEND.get(str(c[2]), c[2])}"
    else:
        raise RegionError(f"Unknown segment mode '{mode}'")
    stack = np.stack([c[act] for c in cols], axis=1)
    uniq, inv = np.unique(stack, axis=0, return_inverse=True)
    seg = np.zeros(shape, float)
    seg[act] = inv.ravel() + 1
    legend = {str(i + 1): namer(tuple(int(x) for x in u)) for i, u in enumerate(uniq)}
    out["SEGMENT"] = pp.make_property(grid, "SEGMENT", seg, "discrete", "", "regions", f"segments: {mode}", legend)
    return out


def region_table(grid, prop) -> List[dict]:
    """Cells, bulk volume and label of each value of a discrete property."""
    v = np.rint(prop.values).astype(int)
    act = grid.actnum > 0
    w = grid.bulk_volume()
    rows = []
    for u in np.unique(v[act]):
        m = act & (v == u)
        rows.append(dict(value=int(u), name=prop.legend.get(str(int(u)), ""), cells=int(m.sum()), volume=float(w[m].sum())))
    return rows
