"""Structural modelling workflow.

A workflow is an ordered list of *steps* (plain dicts, JSON friendly).  Running it produces a
``Structure``: unfaulted *base* depth maps for every horizon on the model lattice, plus an analytic
``eval`` that adds the fault displacement field and applies the truncation rules at any (x, y).

Step types
----------
surface   : horizon taken from a library surface (+ optional shift).      {horizon, surface, shift, role}
isochore  : horizon = reference +/- thickness (constant, trend, or map).  {horizon, ref, direction, mode,
                                                                           thickness, gx, gy, surface, role}
smooth    : Gaussian smoothing of a horizon.                              {horizon, sigma}
calibrate : residual correction to well tops.                             {horizon, label, method, radius,
                                                                           tension, smoothing}
proportional: horizon placed at a fraction between two horizons.      {horizon, top, base, fraction, role}
layers    : N-1 intermediate horizons between two horizons.               {top, base, n, style, dz, fractions,
                                                                           prefix, role}
          style: proportional (equal fractions) | fractions (user list) | follow_top (dz below top) | follow_base (dz above base)
clip      : limit a horizon to a depth window.                            {horizon, zmin, zmax}
faults    : faults active in the model (global).                          {faults: [names]}
zone      : one self-contained zone = base horizon below ``top``.         {name, top, horizon, mode(constant|trend|map|surface),
            Own thickness model, smoothing, thickness limits, tops          thickness, gx, gy, surface, shift, smooth, tmin, tmax,
            calibration, role and layering. Expanded into the primitive      calibrate, label, method, radius, tension, smoothing,
            steps above, so every zone can be modelled separately.            role, nlayers, style, dz, fill*, resample}
thickness_limit (internal, produced by zone): {horizon, ref, tmin, tmax}

Surface / isochore-map steps also take the *extension* options (see core.extrap):
  fill (nearest|gradient|decay|plane|trend2|min_curvature|constant), fill_length, fill_value, fill_tension
  resample (linear|cubic) - how the source map is interpolated onto the model lattice.

Horizon roles: conformable | erosional (truncates everything below it) | baselap (truncates everything above it)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from . import units as un
from .surface import Geometry, Surface, fill_nan_nearest, smooth
from .faults import Fault
from .tops import calibrate_base
from .extrap import fill_undefined, MODES as _FILL_ALL

ROLES = ["conformable", "erosional", "baselap"]
STEP_TYPES = ["surface", "isochore", "zone", "proportional", "layers", "calibrate", "smooth", "clip", "faults"]
ZONE_MODES = ["constant", "trend", "map", "surface"]
FILL_MODES = [m for m in _FILL_ALL if m != "none"]            # a model horizon must be defined everywhere
RESAMPLE = {"linear": 1, "cubic": 3}


def _bring_to_lattice(src: Surface, lattice: Geometry, step: dict) -> np.ndarray:
    """Resample a library surface on the model lattice and fill what the map does not cover."""
    order = RESAMPLE.get(step.get("resample", "linear"), 1)
    z = src.resample_to(lattice, order=order, extrapolate=False).z
    if np.isnan(z).all():
        raise WorkflowError(f"Surface '{src.name}' does not overlap the model area.")
    return fill_undefined(z, lattice, step.get("fill", "nearest"), length=float(step.get("fill_length", 0.0)),
                          value=float(step.get("fill_value", 0.0)), tension=float(step.get("fill_tension", 0.0)))


class WorkflowError(Exception):
    pass


@dataclass
class Structure:
    geom: Geometry
    base: Dict[str, np.ndarray]
    roles: Dict[str, str]
    faults: List[Fault]
    names: List[str]                      # top -> bottom
    log: List[str] = field(default_factory=list)
    calib_qc: List[dict] = field(default_factory=list)
    zone_defs: List[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    def zmean(self, h: str) -> float:
        return float(np.nanmean(self.base[h]))

    def _sample_base(self, h, X, Y):
        s = Surface(h, self.geom, self.base[h])
        return s.sample(X, Y, order=1, extrapolate=True)

    def eval(self, X, Y, sides: Optional[Dict[str, np.ndarray]] = None, with_faults: bool = True) -> np.ndarray:
        """Depth of every horizon at (X, Y): shape (nh, *X.shape).

        ``sides`` (optional) forces, per fault name, the side (+1 HW / -1 FW) used for the displacement;
        this is how stair-stepped corner-point cells get a consistent fault block.
        """
        X = np.asarray(X, float)
        Y = np.asarray(Y, float)
        Z = np.empty((len(self.names),) + X.shape)
        for k, h in enumerate(self.names):
            zb = self._sample_base(h, X, Y)
            z = zb.copy()
            if with_faults:
                zm = self.zmean(h)
                smp = lambda xx, yy, h=h: self._sample_base(h, xx, yy)
                for f in self.faults:
                    sf = None if sides is None else sides.get(f.name)
                    z = z + f.delta(smp, X, Y, zb, zm, side=sf)
            Z[k] = z
        for k, h in enumerate(self.names):                      # truncation rules
            role = self.roles.get(h, "conformable")
            if role == "erosional" and k + 1 < len(self.names):
                Z[k + 1:] = np.maximum(Z[k + 1:], Z[k])
            elif role == "baselap" and k > 0:
                Z[:k] = np.minimum(Z[:k], Z[k])
        return np.maximum.accumulate(Z, axis=0)                 # never cross

    def lattice_depths(self, with_faults=True) -> np.ndarray:
        X, Y = self.geom.coords()
        return self.eval(X, Y, with_faults=with_faults)

    def thickness(self, with_faults=True) -> np.ndarray:
        Z = self.lattice_depths(with_faults)
        return np.diff(Z, axis=0)

    def depth_at(self, h: str, x, y, with_faults=True):
        k = self.names.index(h)
        return self.eval(np.atleast_1d(x), np.atleast_1d(y), with_faults=with_faults)[k]


# ---------------------------------------------------------------------------
def default_steps(surface_names: List[str]) -> List[dict]:
    return [dict(type="surface", horizon=n, surface=n, shift=0.0, role="conformable") for n in surface_names]


def layer_fractions(s: dict) -> List[float]:
    """Interior fractions (0..1) for proportional / fractions styles."""
    if s.get("style") == "fractions":
        fr = sorted({float(f) for f in s.get("fractions", []) if 0.0 < float(f) < 1.0})
        return fr
    nn = int(max(s.get("n", 2), 1))
    return [k / nn for k in range(1, nn)]


def layer_horizons(ztop: np.ndarray, zbase: np.ndarray, s: dict) -> Dict[str, np.ndarray]:
    """Intermediate horizons between ``ztop`` and ``zbase`` according to a layers step."""
    prefix = s.get("prefix") or "Layer"
    style = s.get("style", "proportional")
    out: Dict[str, np.ndarray] = {}
    if style in ("proportional", "fractions"):
        for i, f in enumerate(layer_fractions(s), 1):
            out[f"{prefix}_{i}"] = ztop + f * (zbase - ztop)
    elif style in ("follow_top", "follow_base"):
        dz = float(s.get("dz", 10.0))
        if dz <= 0:
            raise WorkflowError("Layer thickness (dz) must be positive.")
        thick = float(np.nanmax(zbase - ztop))
        nmax = int(min(np.ceil(thick / dz) - 1, 199))
        for i in range(1, nmax + 1):
            z = ztop + i * dz if style == "follow_top" else zbase - i * dz
            out[f"{prefix}_{i}"] = np.clip(z, ztop, zbase)         # pinches out against the other bounding horizon
    else:
        raise WorkflowError(f"Unknown layers style '{style}'")
    if len(out) > 200:
        raise WorkflowError("More than 200 intermediate horizons - use fewer / thicker layers.")
    return out


def expand_steps(steps: List[dict]):
    """Expand composite ``zone`` steps into primitive steps.  Returns [(original step number, primitive step)]."""
    out = []
    for n, s in enumerate(steps, 1):
        if not s.get("enabled", True) or s["type"] != "zone":
            out.append((n, s))
            continue
        h, top = s["horizon"], s["top"]
        common = {k: s[k] for k in ("fill", "fill_length", "fill_value", "fill_tension", "resample") if k in s}
        role = s.get("role", "conformable")
        if s.get("mode", "constant") == "surface":
            out.append((n, dict(type="surface", horizon=h, surface=s.get("surface"), shift=float(s.get("shift", 0.0)), role=role, **common)))
        else:
            out.append((n, dict(type="isochore", horizon=h, ref=top, direction="below",
                                mode="map" if s.get("mode") == "map" else "const", thickness=float(s.get("thickness", 50.0)),
                                gx=float(s.get("gx", 0.0)), gy=float(s.get("gy", 0.0)), surface=s.get("surface"), role=role, **common)))
        if float(s.get("smooth", 0.0)) > 0:
            out.append((n, dict(type="smooth", horizon=h, sigma=float(s["smooth"]))))
        if s.get("tmin") not in (None, "", 0, 0.0) or s.get("tmax") not in (None, "", 0, 0.0):
            out.append((n, dict(type="thickness_limit", horizon=h, ref=top, tmin=s.get("tmin"), tmax=s.get("tmax"))))
        if s.get("calibrate"):
            cal = dict(type="calibrate", horizon=h, label=s.get("label") or h, method=s.get("method", "min_curvature"),
                       radius=float(s.get("radius", 0.0)), tension=float(s.get("tension", 0.3)), smoothing=float(s.get("smoothing", 0.0)))
            cal.update({k: s[k] for k in ("variogram", "vrange", "nugget", "k", "drift", "trend_order", "residual_method") if s.get(k) not in (None, "")})
            out.append((n, cal))
    return out


def zone_defs(steps: List[dict]) -> List[dict]:
    """Zone definitions (name, top, base, layering) carried by the zone steps, in step order."""
    return [dict(name=s.get("name") or f"{s['top']}_{s['horizon']}", top=s["top"], base=s["horizon"], nlayers=int(s.get("nlayers", 5)),
                 style=s.get("style", "proportional"), dz=float(s.get("dz", 10.0)))
            for s in steps if s.get("enabled", True) and s["type"] == "zone"]


def describe(step: dict) -> str:
    t = step["type"]
    if t == "zone":
        how = {"constant": f"{step.get('thickness', 0):g} {un.z()}", "trend": f"{step.get('thickness', 0):g} {un.z()} + trend",
               "map": f"map *{step.get('surface')}*", "surface": f"surface *{step.get('surface')}*"}.get(step.get("mode", "constant"), "?")
        extra = []
        if step.get("smooth"):
            extra.append(f"smooth {step['smooth']:g}")
        if step.get("tmin") or step.get("tmax"):
            extra.append(f"limits [{step.get('tmin') or 0:g}, {step.get('tmax') or 'inf'}]")
        if step.get("calibrate"):
            extra.append(f"calibrated ({step.get('method', 'min_curvature')})")
        return (f"Zone **{step.get('name') or step['horizon']}**: **{step['horizon']}** below **{step['top']}**, thickness {how}"
                + (f"; {', '.join(extra)}" if extra else "") + f"; {step.get('nlayers', 5)} layers  [{step.get('role', 'conformable')}]")
    if t == "thickness_limit":
        return f"Limit thickness {step['ref']} -> {step['horizon']} to [{step.get('tmin')}, {step.get('tmax')}]"
    if t == "surface":
        sh = f", shift {step['shift']:+.1f} {un.z()}" if step.get("shift") else ""
        ex = f", extend: {step['fill']}" if step.get("fill", "nearest") != "nearest" else ""
        return f"Horizon **{step['horizon']}** from surface *{step['surface']}*{sh}{ex}  [{step.get('role', 'conformable')}]"
    if t == "isochore":
        d = "below" if step.get("direction", "below") == "below" else "above"
        if step.get("mode") == "map":
            th = f"map *{step.get('surface')}*"
        else:
            th = f"{step.get('thickness', 0):.1f} {un.z()}"
            if step.get("gx") or step.get("gy"):
                th += f" (+{step.get('gx', 0):.1f}/{step.get('gy', 0):.1f} {un.z()}/1000 {un.xy()} trend)"
        return f"Horizon **{step['horizon']}** = **{step['ref']}** {d} + isochore {th}  [{step.get('role', 'conformable')}]"
    if t == "smooth":
        return f"Smooth **{step['horizon']}** (sigma {step['sigma']:.1f} cells)"
    if t == "calibrate":
        return (f"Calibrate **{step['horizon']}** to tops *{step.get('label', step['horizon'])}* "
                f"({step['method']}, radius {step.get('radius', 0):.0f} {un.xy()})")
    if t == "proportional":
        return (f"Horizon **{step['horizon']}** = {step.get('fraction', 0.5):.0%} of the way from **{step['top']}** "
                f"to **{step['base']}**  [{step.get('role', 'conformable')}]")
    if t == "layers":
        st_ = step.get("style", "proportional")
        how = {"proportional": f"{int(step.get('n', 2))} equal layers", "fractions": f"fractions {step.get('fractions', [])}",
               "follow_top": f"every {step.get('dz', 10):g} {un.z()} below the top", "follow_base": f"every {step.get('dz', 10):g} {un.z()} above the base"}[st_]
        return f"Layers **{step.get('prefix', 'Layer')}_#** between **{step['top']}** and **{step['base']}**: {how}"
    if t == "clip":
        return f"Clip **{step['horizon']}** to [{step.get('zmin', '-inf')}, {step.get('zmax', 'inf')}] {un.z()}"
    if t == "faults":
        return "Apply faults: " + (", ".join(step.get("faults", [])) or "none")
    return str(step)


# ---------------------------------------------------------------------------
def run_workflow(steps: List[dict], surfaces: Dict[str, Surface], faults: Dict[str, Fault],
                 tops: Optional[pd.DataFrame], lattice: Geometry) -> Structure:
    base: Dict[str, np.ndarray] = {}
    roles: Dict[str, str] = {}
    log: List[str] = []
    qc: List[dict] = []
    X, Y = lattice.coords()
    xmin, xmax, ymin, ymax = lattice.bounds()

    active_names: List[str] = []
    for s in steps:
        if s.get("enabled", True) and s["type"] == "faults":
            for n in s.get("faults", []):
                if n in faults and n not in active_names:
                    active_names.append(n)
    active = [faults[n] for n in active_names]

    st = Structure(lattice, base, roles, active, [], log, qc)

    def need(h):
        if h not in base:
            raise WorkflowError(f"Horizon '{h}' is used before it is defined - move its step earlier.")

    for n, s in expand_steps(steps):
        if not s.get("enabled", True):
            log.append(f"Step {n}: skipped (inactive)")
            continue
        t = s["type"]
        try:
            if t == "surface":
                src = surfaces.get(s["surface"])
                if src is None:
                    raise WorkflowError(f"Surface '{s['surface']}' not found in the library.")
                z = _bring_to_lattice(src, lattice, s) + float(s.get("shift", 0.0))
                base[s["horizon"]] = z
                roles[s["horizon"]] = s.get("role", "conformable")
            elif t == "isochore":
                ref = s["ref"]
                need(ref)
                if s.get("mode") == "map":
                    m = surfaces.get(s.get("surface"))
                    if m is None:
                        raise WorkflowError(f"Thickness map '{s.get('surface')}' not found.")
                    th = _bring_to_lattice(m, lattice, s)
                else:
                    th = (float(s.get("thickness", 0.0))
                          + float(s.get("gx", 0.0)) * (X - (xmin + xmax) / 2) / 1000.0
                          + float(s.get("gy", 0.0)) * (Y - (ymin + ymax) / 2) / 1000.0)
                th = np.maximum(th, 0.0)
                sign = 1.0 if s.get("direction", "below") == "below" else -1.0
                base[s["horizon"]] = base[ref] + sign * th
                roles[s["horizon"]] = s.get("role", "conformable")
            elif t == "proportional":
                need(s["top"])
                need(s["base"])
                f = float(s.get("fraction", 0.5))
                base[s["horizon"]] = base[s["top"]] + f * (base[s["base"]] - base[s["top"]])
                roles[s["horizon"]] = s.get("role", "conformable")
                log.append(f"Step {n}: {s['horizon']} at {f:.0%} between {s['top']} and {s['base']}")
            elif t == "layers":
                need(s["top"])
                need(s["base"])
                for nm, zz in layer_horizons(base[s["top"]], base[s["base"]], s).items():
                    base[nm] = zz
                    roles[nm] = s.get("role", "conformable")
                log.append(f"Step {n}: {len(layer_horizons(base[s['top']], base[s['base']], s))} layer horizon(s) between "
                           f"{s['top']} and {s['base']} ({s.get('style', 'proportional')})")
            elif t == "clip":
                need(s["horizon"])
                lo = float(s["zmin"]) if s.get("zmin") not in (None, "") else -np.inf
                hi = float(s["zmax"]) if s.get("zmax") not in (None, "") else np.inf
                nclip = int(((base[s["horizon"]] < lo) | (base[s["horizon"]] > hi)).sum())
                base[s["horizon"]] = np.clip(base[s["horizon"]], lo, hi)
                log.append(f"Step {n}: clipped {nclip} node(s) of {s['horizon']} to [{lo:g}, {hi:g}]")
            elif t == "smooth":
                need(s["horizon"])
                base[s["horizon"]] = smooth(base[s["horizon"]], float(s["sigma"]))
            elif t == "calibrate":
                h = s["horizon"]
                need(h)
                label = s.get("label") or h
                if tops is None or tops.empty:
                    raise WorkflowError("No well tops loaded.")
                tt = tops[tops["horizon"] == label]
                if tt.empty:
                    raise WorkflowError(f"No tops named '{label}' (available: {', '.join(sorted(tops['horizon'].unique()))}).")
                k = None
                # residual vs the current faulted model (only this horizon is evaluated)
                tmp = Structure(lattice, {h: base[h]}, {h: "conformable"}, active, [h])
                zmod = tmp.eval(tt["x"].values, tt["y"].values)[0]
                resid = tt["z"].values - zmod
                before = float(np.sqrt(np.mean(resid ** 2)))
                new = calibrate_base(base[h], lattice, tt["x"].values, tt["y"].values, resid,
                                     method=s["method"], radius=float(s.get("radius", 0.0)),
                                     tension=float(s.get("tension", 0.3)), smoothing=float(s.get("smoothing", 0.0)),
                                     **{k: s[k] for k in ("variogram", "vrange", "nugget", "k", "drift", "trend_order",
                                                          "residual_method") if s.get(k) not in (None, "")})
                base[h] = new
                tmp = Structure(lattice, {h: new}, {h: "conformable"}, active, [h])
                zmod2 = tmp.eval(tt["x"].values, tt["y"].values)[0]
                after = float(np.sqrt(np.mean((tt["z"].values - zmod2) ** 2)))
                qc.append(dict(horizon=h, label=label, n=len(tt), rms_before=before, rms_after=after,
                               mean_before=float(resid.mean()), method=s["method"]))
                log.append(f"Step {n}: calibrated {h} to {len(tt)} tops: RMS {before:.2f} -> {after:.2f} {un.z()}")
            elif t == "thickness_limit":
                need(s["horizon"])
                need(s["ref"])
                th = base[s["horizon"]] - base[s["ref"]]
                lo = float(s["tmin"]) if s.get("tmin") not in (None, "") else 0.0
                hi = float(s["tmax"]) if s.get("tmax") not in (None, "", 0, 0.0) else np.inf
                n_ch = int(((th < lo) | (th > hi)).sum())
                base[s["horizon"]] = base[s["ref"]] + np.clip(th, lo, hi)
                log.append(f"Step {n}: thickness of {s['horizon']} limited to [{lo:g}, {hi:g}] ({n_ch} node(s) changed)")
            elif t == "faults":
                log.append(f"Step {n}: {len(active)} fault(s) active")
            else:
                raise WorkflowError(f"Unknown step type '{t}'")
        except WorkflowError:
            raise
        except Exception as e:  # surface a readable error with the step number
            raise WorkflowError(f"Step {n} ({t}): {e}") from e

    if not base:
        raise WorkflowError("The workflow defines no horizons.")
    names = sorted(base, key=lambda h: float(np.nanmean(base[h])))
    st.names = names
    st.zone_defs = zone_defs(steps)
    log.append("Horizon order (top -> base): " + " > ".join(names))
    return st


def tops_misfit(structure: Structure, tops: pd.DataFrame) -> pd.DataFrame:
    """Observed - modelled depth for every top whose horizon exists in the model."""
    rows = []
    for h in structure.names:
        tt = tops[tops["horizon"] == h]
        if tt.empty:
            continue
        zmod = structure.eval(tt["x"].values, tt["y"].values)[structure.names.index(h)]
        for (w, x, y, zo), zm in zip(tt[["well", "x", "y", "z"]].itertuples(index=False), zmod):
            rows.append(dict(well=w, horizon=h, x=x, y=y, observed=zo, model=float(zm), residual=float(zo - zm)))
    return pd.DataFrame(rows)


def zone_qc(structure: Structure) -> List[dict]:
    """Per-zone thickness statistics on the faulted lattice (zones from zone steps, else consecutive horizons)."""
    Z = structure.lattice_depths()
    defs = structure.zone_defs or [dict(name=f"{a}->{b}", top=a, base=b) for a, b in zip(structure.names[:-1], structure.names[1:])]
    rows = []
    for d in defs:
        if d["top"] not in structure.names or d["base"] not in structure.names:
            continue
        th = Z[structure.names.index(d["base"])] - Z[structure.names.index(d["top"])]
        cal = [c for c in structure.calib_qc if c["horizon"] == d["base"]]
        rows.append(dict(zone=d["name"], top=d["top"], base=d["base"], mean=float(np.nanmean(th)), min=float(np.nanmin(th)),
                         max=float(np.nanmax(th)), pinched_pct=float(100.0 * np.mean(th < 0.1)),
                         rms_before=cal[-1]["rms_before"] if cal else None, rms_after=cal[-1]["rms_after"] if cal else None))
    return rows


def zonespecs_from_structure(structure: Structure, old: Optional[list] = None):
    """ZoneSpec list from the zone steps (keeps petrophysical defaults of existing zones with the same name)."""
    from .cpgrid import ZoneSpec
    keep = {z.name: z for z in (old or [])}
    out = []
    for d in structure.zone_defs:
        z = keep.get(d["name"])
        extra = dict(poro=z.poro, permx=z.permx, ntg=z.ntg, kvkh=z.kvkh) if z else {}
        out.append(ZoneSpec(name=d["name"], top=d["top"], base=d["base"], nlayers=d["nlayers"], style=d["style"], dz=d["dz"], **extra))
    return out
