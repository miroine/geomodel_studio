"""Volumetrics on the 3D grid: gross rock volume above the contacts, net rock volume, pore volume,
hydrocarbon pore volume and STOIIP / GIIP, with contacts per fault block, saturation from a constant per zone,
a property or a saturation-height function, contact sensitivity, tornado / Monte-Carlo uncertainty and
statistics over stochastic realisations.

Conventions
-----------
* Depths are positive down, so "above the contact" means depth < contact.
* Cell top / base are the mean of the four corner depths; a cell cut by a contact contributes the fraction of
  its height above the contact (so the result is smooth in the contact depth).
* gas cap = above GOC, oil leg = between GOC and OWC; both are limited to the included zones.
* GRV  = bulk volume x fraction in the fluid leg
  NRV  = GRV x NTG x [net flag from the porosity / NTG / Sw cut-offs]
  PV   = NRV x PHI,  HCPV = PV x (1 - Sw)
  STOIIP = HCPV(oil) / Bo,  GIIP = HCPV(gas) / Bg + STOIIP x Rs   (Bo in rm3/Sm3, Bg in rm3/Sm3, Rs in Sm3/Sm3)
* All volumes are computed in m3 (project lengths are converted) and reported in 10^6 Sm3 / 10^9 Sm3 or MMstb / Bscf.
"""
from __future__ import annotations

from typing import Dict, List, Optional
import numpy as np

SW_MODES = ["constant", "property", "satheight"]
M3_TO_STB = 6.289811
M3_TO_SCF = 35.31467


class VolError(Exception):
    pass


def default_config(grid) -> dict:
    act = grid.actnum > 0
    cd = grid.center_depth()[act]
    owc = float(np.percentile(cd, 60)) if cd.size else 2000.0
    return dict(
        contacts=dict(owc=round(owc, 1), goc=None, blocks={}, regions=dict(prop="SEGMENT", values={}), tilt=dict(gx=0.0, gy=0.0, xref=0.0, yref=0.0), fwl_below=0.0),
        fluid=dict(Bo=1.25, Bg=0.005, Rs=0.0),
        sw=dict(mode="constant", zone={z.name: 0.25 for z in grid.zones}, prop="SW", swirr=0.2, entry=2.0, lam=0.5),
        src=dict(phi="zone", ntg="zone"),
        cut=dict(phi=0.0, ntg=0.0, sw=1.0),
        zones=[z.name for z in grid.zones],
        display="metric",
        unc=dict(owc=[-20.0, 20.0], sw=[0.85, 1.15], Bo=[1.15, 1.35], phi=[0.9, 1.1], ntg=[0.9, 1.1], struct=[0.0, 3.0], n=200, seed=1),
        report_by="ZONE")


def check_config(grid, cfg) -> List[str]:
    errs = []
    c = cfg["contacts"]
    if c["goc"] is not None and c["goc"] > c["owc"]:
        errs.append("GOC must be above (shallower than) the OWC.")
    for b, v in c["blocks"].items():
        if v.get("goc") is not None and v.get("owc") is not None and v["goc"] > v["owc"]:
            errs.append(f"Block {b}: GOC must be above the OWC.")
    if cfg["fluid"]["Bo"] <= 0 or cfg["fluid"]["Bg"] <= 0:
        errs.append("Bo and Bg must be positive.")
    if not cfg["zones"]:
        errs.append("Include at least one zone.")
    return errs


def _src(grid, props, name, kind, ridx=None):
    if name in ("zone", "one"):
        if name == "one":
            return np.ones((grid.nk, grid.nj, grid.ni))
        return grid.property_array("PORO" if kind == "phi" else "NTG")
    key = f"{name}_R{ridx}" if ridx and f"{name}_R{ridx}" in props else name
    if key not in props:
        raise VolError(f"Property '{key}' not found - create it on the Properties page.")
    v = props[key].values
    if v.shape != (grid.nk, grid.nj, grid.ni):
        raise VolError(f"Property '{key}' does not fit the current grid.")
    return np.nan_to_num(v.astype(float))


def contact_maps(grid, cfg, over=None):
    """(nj, ni) OWC and GOC maps (NaN GOC = no gas cap) from the global values, the per-block overrides and the scenario shifts."""
    over = over or {}
    c = cfg["contacts"]
    owc = np.full(grid.block.shape, float(c["owc"]))
    goc = np.full(grid.block.shape, np.nan if c["goc"] is None else float(c["goc"]))
    for b, v in c["blocks"].items():
        m = grid.block == int(b)
        if v.get("owc") is not None:
            owc[m] = float(v["owc"])
        if v.get("goc") is not None:
            goc[m] = float(v["goc"])
    if over.get("owc_all") is not None:
        owc[:] = float(over["owc_all"])
    owc = owc + float(over.get("owc_shift", 0.0))
    goc = goc + float(over.get("owc_shift", 0.0))
    return owc, goc


def _region_values(grid, props, name):
    if name in ("ZONE", "zone"):
        return np.broadcast_to((grid.layer_zone + 1)[:, None, None], (grid.nk, grid.nj, grid.ni))
    if name in ("BLOCK", "FAULT_BLOCK", "block") and (props is None or name not in props):
        return grid.block_array()
    if props is None or name not in props:
        raise VolError(f"Region property '{name}' (used for region contacts) is not available - create it on the Properties page (Planes & regions).")
    return np.rint(props[name].values).astype(int)


def contact_cubes(grid, cfg, props=None, over=None):
    """3D OWC, GOC (NaN = no gas cap) and FWL for every cell: global value -> per fault block -> per region value (zone / segment / any discrete
    property) -> tilt plane -> scenario shifts.  ``over``: owc_all (one flat OWC everywhere), owc_shift, struct_field (nj, ni)."""
    over = over or {}
    shape = (grid.nk, grid.nj, grid.ni)
    o2, g2 = contact_maps(grid, cfg, dict(owc_all=over.get("owc_all")))
    owc = np.broadcast_to(o2[None], shape).copy()
    goc = np.broadcast_to(g2[None], shape).copy()
    c = cfg["contacts"]
    if over.get("owc_all") is None:
        reg = c.get("regions") or {}
        if reg.get("values"):
            rv = _region_values(grid, props, reg.get("prop", "SEGMENT"))
            for key, v in reg["values"].items():
                m = rv == int(key)
                if v.get("owc") is not None:
                    owc[m] = float(v["owc"])
                if v.get("goc") is not None:
                    goc[m] = float(v["goc"])
        t = c.get("tilt") or {}
        if t.get("gx") or t.get("gy"):
            X, Y = grid.center_xy()
            plane = float(t.get("gx", 0.0)) * (X - float(t.get("xref", 0.0))) + float(t.get("gy", 0.0)) * (Y - float(t.get("yref", 0.0)))
            owc = owc + plane[None]
            goc = goc + plane[None]
    sh = float(over.get("owc_shift", 0.0))
    owc = owc + sh
    goc = goc + sh
    if over.get("struct_field") is not None:
        owc = owc + over["struct_field"][None]
        goc = goc + over["struct_field"][None]
    return owc, goc, owc + float(c.get("fwl_below", 0.0))


FLUID_LEGEND = {"1": "gas", "2": "oil", "3": "water"}


def fluid_array(grid, cfg, over=None, props=None) -> np.ndarray:
    """Fluid at the cell centre from the contacts: 1 gas (above GOC), 2 oil (between GOC and OWC), 3 water (below OWC)."""
    top = grid.zc[:, 0].mean(axis=(2, 4))
    bot = grid.zc[:, 1].mean(axis=(2, 4))
    centre = 0.5 * (top + bot)
    owc, goc, _ = contact_cubes(grid, cfg, props, over)
    has_gas = np.isfinite(goc)
    fl = np.full(centre.shape, 3.0)
    fl = np.where(centre < owc, 2.0, fl)
    return np.where(has_gas & (centre < np.where(has_gas, goc, 0.0)), 1.0, fl)


def compute(grid, cfg, props, vol_to_m3=1.0, over: Optional[dict] = None, ridx: Optional[int] = None, cells=True) -> dict:
    """Volumetrics for the current configuration.  ``over`` = dict(owc_shift, sw_mult, Bo, phi_mult, ntg_mult, owc_all)."""
    over = over or {}
    errs = check_config(grid, cfg)
    if errs:
        raise VolError(" ".join(errs))
    shape = (grid.nk, grid.nj, grid.ni)
    top = grid.zc[:, 0].mean(axis=(2, 4))
    bot = grid.zc[:, 1].mean(axis=(2, 4))
    h = np.maximum(bot - top, 1e-9)
    centre = 0.5 * (top + bot)
    owc, goc, fwl = contact_cubes(grid, cfg, props, over)
    f_ow = np.clip((owc - top) / h, 0.0, 1.0)
    has_gas = np.isfinite(goc)
    f_g = np.where(has_gas, np.clip((np.where(has_gas, goc, 0.0) - top) / h, 0.0, 1.0), 0.0)
    f_g = np.minimum(f_g, f_ow)
    f_o = f_ow - f_g
    zin = np.isin(np.arange(len(grid.zones)), [i for i, z in enumerate(grid.zones) if z.name in cfg["zones"]])
    mask = (grid.actnum > 0) & zin[grid.layer_zone][:, None, None]
    vol = grid.bulk_volume() * float(vol_to_m3)
    phi = np.clip(_src(grid, props, cfg["src"]["phi"], "phi", ridx) * float(over.get("phi_mult", 1.0)), 0.0, 1.0)
    ntg = np.clip(_src(grid, props, cfg["src"]["ntg"], "ntg", ridx) * float(over.get("ntg_mult", 1.0)), 0.0, 1.0)
    sc = cfg["sw"]
    if sc["mode"] == "constant":
        swz = np.array([sc["zone"].get(z.name, 0.25) for z in grid.zones], float)
        sw = np.broadcast_to(swz[grid.layer_zone][:, None, None], shape).copy()
    elif sc["mode"] == "property":
        sw = np.clip(_src(grid, props, sc["prop"], "sw", ridx), 0.0, 1.0)
    else:
        hc = np.maximum(fwl - centre, 0.0)
        ent = max(float(sc["entry"]), 1e-9)
        sw = np.clip(sc["swirr"] + (1.0 - sc["swirr"]) * (ent / np.maximum(hc, ent)) ** float(sc["lam"]), 0.0, 1.0)
    sw = np.clip(sw * float(over.get("sw_mult", 1.0)), 0.0, 1.0)
    cut = cfg["cut"]
    net = (phi >= cut["phi"]) & (ntg >= cut["ntg"]) & (sw <= cut["sw"])
    fl = cfg["fluid"]
    Bo = float(over.get("Bo", fl["Bo"]))
    Bg = float(fl["Bg"])
    out = {}
    cellv = {}
    for fluid, frac in (("oil", f_o), ("gas", f_g)):
        grv = vol * frac * mask
        nrv = grv * ntg * net
        pv = nrv * phi
        hcpv = pv * (1.0 - sw)
        cellv[fluid] = dict(GRV=grv, NRV=nrv, PV=pv, HCPV=hcpv)
    stoiip = cellv["oil"]["HCPV"] / Bo
    giip_free = cellv["gas"]["HCPV"] / Bg
    giip_ass = stoiip * float(fl["Rs"])
    giip = giip_free + giip_ass
    cellv["STOIIP"], cellv["GIIP"] = stoiip, giip

    def tot(a):
        return float(a.sum())

    out["total"] = dict(
        oil=dict(GRV=tot(cellv["oil"]["GRV"]), NRV=tot(cellv["oil"]["NRV"]), PV=tot(cellv["oil"]["PV"]), HCPV=tot(cellv["oil"]["HCPV"]), STOIIP=tot(stoiip)),
        gas=dict(GRV=tot(cellv["gas"]["GRV"]), NRV=tot(cellv["gas"]["NRV"]), PV=tot(cellv["gas"]["PV"]), HCPV=tot(cellv["gas"]["HCPV"]), GIIP_free=tot(giip_free)),
        GIIP=tot(giip), STOIIP=tot(stoiip))
    if not cells:
        return out
    rows_z = []
    for zi, z in enumerate(grid.zones):
        m = grid.layer_zone == zi
        rows_z.append(dict(zone=z.name, included=z.name in cfg["zones"], GRV_oil=tot(cellv["oil"]["GRV"][m]), GRV_gas=tot(cellv["gas"]["GRV"][m]),
                           NRV=tot((cellv["oil"]["NRV"] + cellv["gas"]["NRV"])[m]), PV=tot((cellv["oil"]["PV"] + cellv["gas"]["PV"])[m]),
                           HCPV_oil=tot(cellv["oil"]["HCPV"][m]), HCPV_gas=tot(cellv["gas"]["HCPV"][m]), STOIIP=tot(stoiip[m]), GIIP=tot(giip[m])))
    owc2 = owc.mean(axis=0)
    goc2 = np.where(np.isfinite(goc).any(axis=0), np.nanmean(np.where(np.isfinite(goc), goc, np.nan), axis=0), np.nan) if np.isfinite(goc).any() else np.full(owc2.shape, np.nan)
    rows_b = []
    for b in range(1, int(grid.block.max()) + 1):
        m = (grid.block == b)[None] & np.ones(shape, bool)
        mb = grid.block == b
        rows_b.append(dict(block=b, OWC=float(owc2[mb].mean()) if mb.any() else np.nan,
                           GOC=float(goc2[mb].mean()) if mb.any() and np.isfinite(goc2[mb]).any() else np.nan,
                           GRV_oil=tot(cellv["oil"]["GRV"][m]), GRV_gas=tot(cellv["gas"]["GRV"][m]),
                           HCPV_oil=tot(cellv["oil"]["HCPV"][m]), HCPV_gas=tot(cellv["gas"]["HCPV"][m]), STOIIP=tot(stoiip[m]), GIIP=tot(giip[m])))
    fluid = fluid_array(grid, cfg, over, props)
    out.update(by_zone=rows_z, by_block=rows_b, owc=owc2, goc=goc2,
               cells=dict(FLUID=fluid, SW=sw, GRV=cellv["oil"]["GRV"] + cellv["gas"]["GRV"], HCPV=cellv["oil"]["HCPV"] + cellv["gas"]["HCPV"],
                          STOIIP=stoiip, GIIP=giip, NET=net.astype(float), PHI=phi, NTG=ntg))
    return out


def scan_contact(grid, cfg, props, vol_to_m3, owc_values, key="STOIIP") -> np.ndarray:
    """STOIIP (m3) for a series of OWC depths applied to all fault blocks."""
    return np.array([compute(grid, cfg, props, vol_to_m3, over=dict(owc_all=v), cells=False)["total"][key] if key == "STOIIP"
                     else compute(grid, cfg, props, vol_to_m3, over=dict(owc_all=v), cells=False)["total"]["oil"]["GRV"] for v in owc_values])


PARAMS = ["owc", "sw", "Bo", "phi", "ntg"]
PARAM_LABEL = dict(owc="OWC shift", sw="Sw multiplier", Bo="Bo", phi="Porosity multiplier", ntg="NTG multiplier")
_OVER = dict(owc="owc_shift", sw="sw_mult", Bo="Bo", phi="phi_mult", ntg="ntg_mult")


def _base_value(cfg, p):
    return {"owc": 0.0, "sw": 1.0, "Bo": cfg["fluid"]["Bo"], "phi": 1.0, "ntg": 1.0}[p]


def tornado(grid, cfg, props, vol_to_m3, key="STOIIP") -> dict:
    """One-at-a-time low / high sensitivities of STOIIP (or GIIP) to the uncertainty ranges in ``cfg['unc']``."""
    base = compute(grid, cfg, props, vol_to_m3, cells=False)["total"][key]
    rows = []
    for p in PARAMS:
        lo, hi = cfg["unc"][p]
        r = [compute(grid, cfg, props, vol_to_m3, over={_OVER[p]: v}, cells=False)["total"][key] for v in (lo, hi)]
        rows.append(dict(param=p, label=PARAM_LABEL[p], low_in=lo, high_in=hi, low=r[0], high=r[1]))
    rows.sort(key=lambda r: -abs(r["high"] - r["low"]))
    return dict(base=base, rows=rows)


def monte_carlo(grid, cfg, props, vol_to_m3, key="STOIIP") -> np.ndarray:
    """Monte-Carlo of the uncertain scalars (triangular around the base value); returns the sampled volumes (m3)."""
    u = cfg["unc"]
    rng = np.random.default_rng(int(u["seed"]))
    n = int(np.clip(u["n"], 10, 2000))
    samp = {}
    for p in PARAMS:
        lo, hi = u[p]
        b = _base_value(cfg, p)
        lo, hi = min(lo, b, hi), max(lo, b, hi)
        samp[p] = rng.triangular(lo, b, hi, n) if hi > lo else np.full(n, b)
    sg, rg = (list(u.get("struct", [0.0, 3.0])) + [3.0])[:2]
    out = []
    for i in range(n):
        ov = {_OVER[p]: samp[p][i] for p in PARAMS}
        if sg > 0:
            ov["struct_field"] = struct_field(grid, sg, rg, rng)
        out.append(compute(grid, cfg, props, vol_to_m3, over=ov, cells=False)["total"][key])
    return np.array(out)


def realisation_ids(props: dict, names=("PORO",)) -> List[int]:
    ids = set()
    for n in props:
        for b in names:
            if n.startswith(b + "_R") and n[len(b) + 2:].isdigit():
                ids.add(int(n[len(b) + 2:]))
    return sorted(ids)


def over_realisations(grid, cfg, props, vol_to_m3) -> List[dict]:
    """Volumes for every stochastic realisation (PORO_R#, NTG_R#, SW_R# are used where the source is a property)."""
    names = [cfg["src"][k] for k in ("phi", "ntg") if cfg["src"][k] not in ("zone", "one")]
    if cfg["sw"]["mode"] == "property":
        names.append(cfg["sw"]["prop"])
    ids = realisation_ids(props, names or ["PORO"])
    out = []
    for r in ids:
        t = compute(grid, cfg, props, vol_to_m3, ridx=r, cells=False)["total"]
        out.append(dict(realisation=r, STOIIP=t["STOIIP"], GIIP=t["GIIP"], GRV=t["oil"]["GRV"] + t["gas"]["GRV"], HCPV=t["oil"]["HCPV"] + t["gas"]["HCPV"]))
    return out


def percentiles(v) -> dict:
    """Oil-industry convention: P90 = value exceeded with 90 % probability (low case), P10 = high case."""
    v = np.asarray(v, float)
    return dict(P90=float(np.percentile(v, 10)), P50=float(np.percentile(v, 50)), P10=float(np.percentile(v, 90)), mean=float(v.mean()))


def to_display(value_m3: float, kind: str, system: str = "metric") -> tuple:
    """-> (value, unit label).  kind: oil (STOIIP) | gas (GIIP) | vol (rock / pore volume)."""
    if kind == "vol":
        return value_m3 / 1e6, "10^6 m3"
    if kind == "oil":
        return (value_m3 / 1e6, "MSm3") if system == "metric" else (value_m3 * M3_TO_STB / 1e6, "MMstb")
    return (value_m3 / 1e9, "GSm3") if system == "metric" else (value_m3 * M3_TO_SCF / 1e9, "Bscf")


def by_region(res: dict, grid, props, name: str) -> List[dict]:
    """Volumes summed over the values of a discrete property (SEGMENT, REGION, FAULT_BLOCK, ZONE, ...); needs ``compute(cells=True)``."""
    rv = _region_values(grid, props, name)
    cl = res["cells"]
    leg = props[name].legend if props is not None and name in props else {}
    rows = []
    for u in np.unique(rv[grid.actnum > 0]):
        m = (rv == u) & (grid.actnum > 0)
        label = leg.get(str(int(u)), f"Zone {grid.zones[int(u) - 1].name}" if name in ("ZONE", "zone") and 0 < u <= len(grid.zones) else f"Block {int(u)}" if name in ("BLOCK", "FAULT_BLOCK") else f"{name} {int(u)}")
        rows.append(dict(value=int(u), name=label, GRV=float(cl["GRV"][m].sum()), HCPV=float(cl["HCPV"][m].sum()), STOIIP=float(cl["STOIIP"][m].sum()), GIIP=float(cl["GIIP"][m].sum())))
    return rows


def struct_field(grid, sigma: float, range_cells: float, rng) -> np.ndarray:
    """Smooth random depth shift (nj, ni) with standard deviation ``sigma`` (z units) and correlation length ``range_cells`` (structural uncertainty)."""
    from scipy.ndimage import gaussian_filter
    f = gaussian_filter(rng.normal(size=(grid.nj, grid.ni)), max(float(range_cells), 0.3), mode="reflect")
    sd = f.std()
    return f / sd * float(sigma) if sd > 0 else np.zeros_like(f)
