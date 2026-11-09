"""Grid properties (cell arrays linked to the 3D grid) and a restricted Python calculator.

A :class:`Property` is a dense (nk, nj, ni) array that belongs to the current grid - exactly like a Petrel
property or an RMS grid parameter.  Properties are created from zone defaults, by the calculator, or by hand,
are checked against the grid dimensions when the grid is rebuilt, and are exported with the grid (GRDECL).

Calculator
----------
A small Python subset is evaluated on whole arrays::

    PORO = 0.32 * exp(-DEPTH / 6000) + noise(7) * 0.01
    PORO[ZONE == 3] = 0.05                      # conditional assignment with a mask
    PERMX = 10 ** (12 * PORO - 1.5)
    NTG = clip(by_zone(0.1, 0.3, 0.9, 0.8, 0.2), 0, 1)

* names: every stored property plus the geometric variables  I J K X Y DEPTH DX DY DZ VOLUME ZONE BLOCK ACTNUM  (read-only)
* functions: see :data:`FUNCTIONS` (``where exp log sqrt clip smooth by_zone noise mean ...``)
* statements: assignments to a name, ``NAME[mask] = ...`` and augmented assignment (``PORO *= 0.9``)
* no attribute access, imports, loops, comprehensions, lambdas, strings or dunder names - the script is parsed with
  :mod:`ast`, checked against a whitelist and executed with empty builtins.
"""
from __future__ import annotations

import ast
import hashlib
import io
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from . import units as un

KINDS = ["continuous", "discrete"]
GEOMETRIC = ["I", "J", "K", "X", "Y", "DEPTH", "DX", "DY", "DZ", "VOLUME", "ZONE", "BLOCK", "ACTNUM"]
ZONE_PROPS = ["PORO", "PERMX", "PERMY", "PERMZ", "NTG"]


class CalcError(Exception):
    pass


@dataclass
class Property:
    name: str
    values: np.ndarray                      # (nk, nj, ni) float32
    kind: str = "continuous"                # continuous | discrete
    unit: str = ""
    source: str = "manual"                  # zones | calculator | manual | import
    expr: str = ""                          # calculator script that produced it
    sig: Tuple[int, int, int] = (0, 0, 0)   # grid dimensions it belongs to
    geom_hash: str = ""                     # fingerprint of the grid geometry when it was made
    stale: bool = False
    legend: dict = field(default_factory=dict)  # discrete value -> label (e.g. {"1": "gas"})

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("values")
        d["sig"] = list(self.sig)
        return d

    @staticmethod
    def from_meta(d: dict, values: np.ndarray) -> "Property":
        d = dict(d)
        d["sig"] = tuple(d.get("sig", values.shape[::-1]))
        keys = Property.__dataclass_fields__.keys()
        return Property(values=np.asarray(values, np.float32), **{k: v for k, v in d.items() if k in keys and k != "values"})

    def stats(self, actnum: Optional[np.ndarray] = None) -> dict:
        v = self.values if actnum is None else self.values[actnum > 0]
        v = v[np.isfinite(v)]
        if v.size == 0:
            return dict(n=0, min=np.nan, mean=np.nan, max=np.nan, std=np.nan, p10=np.nan, p50=np.nan, p90=np.nan)
        return dict(n=int(v.size), min=float(v.min()), mean=float(v.mean()), max=float(v.max()), std=float(v.std()),
                    p10=float(np.percentile(v, 10)), p50=float(np.percentile(v, 50)), p90=float(np.percentile(v, 90)))


def grid_hash(g) -> str:
    h = hashlib.md5()
    h.update(np.asarray([g.ni, g.nj, g.nk], np.int64).tobytes())
    h.update(np.round(g.zc.ravel()[::max(g.zc.size // 4096, 1)], 1).astype(np.float64).tobytes())
    h.update(np.asarray(g.actnum.ravel()[::max(g.actnum.size // 4096, 1)], np.int8).tobytes())
    return h.hexdigest()[:12]


def grid_sig(g) -> Tuple[int, int, int]:
    return (g.ni, g.nj, g.nk)


def make_property(g, name: str, values, kind="continuous", unit="", source="manual", expr="", legend=None) -> Property:
    shape = (g.nk, g.nj, g.ni)
    v = np.broadcast_to(np.asarray(values, float), shape).astype(np.float32).copy()
    if kind == "discrete":
        v = np.rint(v).astype(np.float32)
    return Property(name=name, values=v, kind=kind, unit=unit, source=source, expr=expr, sig=grid_sig(g), geom_hash=grid_hash(g), legend=dict(legend or {}))


# ---------------------------------------------------------------------------
def geometric_vars(g) -> Dict[str, np.ndarray]:
    """Read-only cell variables available to the calculator."""
    shape = (g.nk, g.nj, g.ni)
    K, J, I = np.meshgrid(np.arange(1, g.nk + 1), np.arange(1, g.nj + 1), np.arange(1, g.ni + 1), indexing="ij")
    cx, cy = g.center_xy()
    dxs, dys = np.diff(g.xs), np.diff(g.ys)
    return dict(
        I=I.astype(float), J=J.astype(float), K=K.astype(float),
        X=np.broadcast_to(cx[None], shape).copy(), Y=np.broadcast_to(cy[None], shape).copy(),
        DEPTH=g.center_depth(), DZ=g.thickness(),
        DX=np.broadcast_to(dxs[None, None, :], shape).copy(), DY=np.broadcast_to(dys[None, :, None], shape).copy(),
        VOLUME=g.bulk_volume(), ZONE=g.zone_layer_array().astype(float), BLOCK=g.block_array().astype(float),
        ACTNUM=g.actnum.astype(float))


GEO_PROPS = {   # name -> (kind, unit, description)
    "DEPTH": ("continuous", "z-unit", "cell-centre depth"), "DZ": ("continuous", "z-unit", "cell thickness"),
    "DX": ("continuous", "xy-unit", "cell size along I"), "DY": ("continuous", "xy-unit", "cell size along J"),
    "VOLUME": ("continuous", "", "bulk volume"), "X": ("continuous", "xy-unit", "cell-centre easting"),
    "Y": ("continuous", "xy-unit", "cell-centre northing"), "ZFRAC": ("continuous", "frac", "relative position in the zone (0 top - 1 base)"),
    "I": ("discrete", "", "column index (1-based)"), "J": ("discrete", "", "row index"), "K": ("discrete", "", "layer index"),
    "ZONE": ("discrete", "", "zone number"), "BLOCK": ("discrete", "", "fault block number"), "ACTNUM": ("discrete", "", "1 = active cell"),
    "LAYER_IN_ZONE": ("discrete", "", "layer number inside its zone"),
}


def geometry_properties(g, names=None) -> Dict[str, Property]:
    """Stored snapshots of simple geometric cell properties (depth, zone number, I / J / K ...)."""
    geo = geometric_vars(g)
    shape = (g.nk, g.nj, g.ni)
    lz = g.layer_zone
    first = np.array([np.where(lz == z)[0][0] if (lz == z).any() else 0 for z in range(len(g.zones))])
    cnt = np.array([(lz == z).sum() for z in range(len(g.zones))])
    lin = (np.arange(g.nk) - first[lz]) + 1
    geo["LAYER_IN_ZONE"] = np.broadcast_to(lin[:, None, None], shape).astype(float)
    geo["ZFRAC"] = np.broadcast_to(((lin - 0.5) / np.maximum(cnt[lz], 1))[:, None, None], shape).astype(float)
    out = {}
    for n in (names or list(GEO_PROPS)):
        kind, unit, _ = GEO_PROPS[n]
        unit = {"z-unit": un.z(), "xy-unit": un.xy()}.get(unit, unit)
        out[n] = make_property(g, n, geo[n], kind, unit, "geometry")
    return out


def zone_defaults(g) -> Dict[str, Property]:
    """PORO / PERMX / PERMY / PERMZ / NTG filled from the zone table."""
    units = {"PORO": "frac", "NTG": "frac", "PERMX": "mD", "PERMY": "mD", "PERMZ": "mD"}
    return {n: make_property(g, n, g.property_array(n), "continuous", units[n], "zones") for n in ZONE_PROPS}


# ---------------------------------------------------------------------------
class _Funcs:
    """Calculator functions bound to one grid."""

    def __init__(self, g):
        self.g = g
        self.act = g.actnum > 0
        self.zone = g.zone_layer_array()
        self.shape = (g.nk, g.nj, g.ni)

    def _a(self, x):
        return np.broadcast_to(np.asarray(x, float), self.shape)

    # active-cell statistics (scalars)
    def mean(self, a): return float(np.nanmean(self._a(a)[self.act]))
    def sum(self, a): return float(np.nansum(self._a(a)[self.act]))
    def min(self, a): return float(np.nanmin(self._a(a)[self.act]))
    def max(self, a): return float(np.nanmax(self._a(a)[self.act]))
    def std(self, a): return float(np.nanstd(self._a(a)[self.act]))
    def percentile(self, a, q): return float(np.nanpercentile(self._a(a)[self.act], q))

    def by_zone(self, *vals):
        """Value per zone (1st value = zone 1 ...); the last value is repeated if fewer are given."""
        nz = len(self.g.zones)
        vals = list(vals) or [0.0]
        out = np.zeros(self.shape)
        for zi in range(nz):
            out[self.zone == zi + 1] = vals[min(zi, len(vals) - 1)]
        return out

    def by_block(self, *vals):
        vals = list(vals) or [0.0]
        out = np.zeros(self.shape)
        blk = self.g.block_array()
        for b in range(1, int(blk.max()) + 1):
            out[blk == b] = vals[min(b - 1, len(vals) - 1)]
        return out

    def zone_mean(self, a):
        """Replace each cell by the mean of its zone (active cells)."""
        a = self._a(a)
        out = np.full(self.shape, np.nan)
        for zi in range(len(self.g.zones)):
            m = self.zone == zi + 1
            mm = m & self.act
            out[m] = float(np.nanmean(a[mm])) if mm.any() else np.nan
        return out

    def layer_mean(self, a):
        a = self._a(a)
        out = np.full(self.shape, np.nan)
        for k in range(self.g.nk):
            m = self.act[k]
            out[k] = float(np.nanmean(a[k][m])) if m.any() else np.nan
        return out

    def noise(self, seed=0):
        """Uniform random numbers in [0, 1) (reproducible for a given seed)."""
        return np.random.default_rng(int(seed)).random(self.shape)

    def gauss(self, seed=0, mean=0.0, std=1.0):
        return np.random.default_rng(int(seed)).normal(float(mean), float(std), self.shape)

    def smooth(self, a, n=1):
        """Gaussian smoothing in I, J, K (sigma = n cells)."""
        from scipy.ndimage import gaussian_filter
        a = self._a(a).copy()
        a[~np.isfinite(a)] = 0.0
        return gaussian_filter(a, float(n), mode="nearest")

    def smooth2d(self, a, n=1):
        """Gaussian smoothing in I, J only (within each layer)."""
        from scipy.ndimage import gaussian_filter
        a = self._a(a).copy()
        a[~np.isfinite(a)] = 0.0
        return gaussian_filter(a, (0.0, float(n), float(n)), mode="nearest")

    def table(self, a, *pairs):
        """Piece-wise linear lookup: table(DEPTH, d1, v1, d2, v2, ...)."""
        if len(pairs) < 4 or len(pairs) % 2:
            raise CalcError("table(a, x1, y1, x2, y2, ...) needs at least two (x, y) pairs")
        xs, ys = np.asarray(pairs[0::2], float), np.asarray(pairs[1::2], float)
        o = np.argsort(xs)
        return np.interp(self._a(a), xs[o], ys[o])


_NP_FUNCS: Dict[str, Callable] = dict(
    where=np.where, exp=np.exp, log=np.log, log10=np.log10, sqrt=np.sqrt, abs=np.abs, clip=np.clip, minimum=np.minimum,
    maximum=np.maximum, sin=np.sin, cos=np.cos, tan=np.tan, arctan=np.arctan, floor=np.floor, ceil=np.ceil, round=np.round,
    isnan=np.isnan, nan_to_num=np.nan_to_num, power=np.power, tanh=np.tanh)
_GRID_FUNCS = ["mean", "sum", "min", "max", "std", "percentile", "by_zone", "by_block", "zone_mean", "layer_mean", "noise", "gauss",
               "smooth", "smooth2d", "table"]
FUNCTIONS = sorted(list(_NP_FUNCS) + _GRID_FUNCS)
CONSTANTS = dict(pi=float(np.pi), nan=float("nan"), inf=float("inf"))

FUNCTION_HELP = {
    "where(c, a, b)": "a where the condition c is true, else b", "exp, log, log10, sqrt, abs, tanh, sin, cos": "element-wise maths",
    "clip(a, lo, hi)": "limit a to [lo, hi]", "minimum / maximum(a, b)": "element-wise min / max",
    "by_zone(v1, v2, ...)": "one value per zone (zone 1 first)", "by_block(v1, v2, ...)": "one value per fault block",
    "mean / min / max / sum / std(a)": "statistic over the active cells (a number)", "percentile(a, q)": "q-th percentile of the active cells",
    "zone_mean(a), layer_mean(a)": "replace each cell by the mean of its zone / layer", "smooth(a, n), smooth2d(a, n)": "Gaussian smoothing (n cells)",
    "noise(seed)": "uniform random 0..1", "gauss(seed, mean, std)": "normally distributed random field",
    "table(a, x1, y1, x2, y2, ...)": "piece-wise linear lookup of a",
}

_OK_NODES = (ast.Module, ast.Assign, ast.AugAssign, ast.Expr, ast.Name, ast.Load, ast.Store, ast.Constant, ast.BinOp, ast.UnaryOp,
             ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.keyword, ast.Subscript,
             ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not, ast.Invert,
             ast.And, ast.Or, ast.BitAnd, ast.BitOr, ast.BitXor, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _check(tree: ast.AST, readonly: set, known: set) -> List[str]:
    """Validate the AST; returns the names the script assigns to."""
    targets: List[str] = []
    allowed_callable = set(FUNCTIONS)
    for node in ast.walk(tree):
        if not isinstance(node, _OK_NODES):
            raise CalcError(f"'{type(node).__name__}' is not allowed in the calculator "
                            "(use assignments, arithmetic, comparisons, where(...) and the listed functions).")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise CalcError(f"Name '{node.id}' is not allowed.")
        if isinstance(node, ast.Constant) and not (isinstance(node.value, (int, float, bool)) or node.value is None):
            raise CalcError("Only numbers are allowed as constants (no text).")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_callable:
                raise CalcError("Only the listed functions can be called: " + ", ".join(FUNCTIONS))
            if any(isinstance(a, ast.Starred) for a in node.args):
                raise CalcError("Star-arguments are not allowed.")
    for stmt in tree.body:                                                   # type: ignore[attr-defined]
        if isinstance(stmt, (ast.Assign, ast.AugAssign)):
            tl = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for t in tl:
                if isinstance(t, ast.Name):
                    nm = t.id
                elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                    nm = t.value.id
                else:
                    raise CalcError("Assign to a name, or to NAME[mask].")
                if nm in readonly or nm in allowed_callable or nm in CONSTANTS:
                    raise CalcError(f"'{nm}' is read-only / reserved - choose another property name.")
                if isinstance(t, ast.Subscript) and nm not in known and nm not in targets:
                    raise CalcError(f"'{nm}' must exist before NAME[mask] = ... is used.")
                if nm not in targets:
                    targets.append(nm)
        elif not isinstance(stmt, ast.Expr):
            raise CalcError("Unsupported statement.")
    return targets


def run_calculator(code: str, g, props: Dict[str, Property], out_name: str = "RESULT") -> Dict[str, np.ndarray]:
    """Run a calculator script on grid ``g``.  Returns {name: array(nk, nj, ni)} for every assigned property.

    A script that is a single bare expression is stored under ``out_name``.
    """
    code = (code or "").strip()
    if not code:
        raise CalcError("The script is empty.")
    if len(code) > 6000 or code.count("\n") > 80:
        raise CalcError("Script too long (max 80 lines).")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise CalcError(f"Syntax error (line {e.lineno}): {e.msg}") from None
    # single expression -> assign to out_name
    if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
        if not out_name.isidentifier() or out_name.startswith("_"):
            raise CalcError("Invalid output name.")
        tree = ast.parse(f"{out_name} = " + code, mode="exec")
    # numbers become floats so that huge integer powers cannot hang the server
    class _F(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, int) and not isinstance(node.value, bool):
                return ast.copy_location(ast.Constant(float(node.value)), node)
            return node
    tree = ast.fix_missing_locations(_F().visit(tree))

    geo = geometric_vars(g)
    shape = (g.nk, g.nj, g.ni)
    env: Dict[str, object] = {}
    for n, pr in props.items():
        if pr.values.shape == shape:
            env[n] = pr.values.astype(float).copy()
    env.update({k: v.copy() for k, v in geo.items()})
    fn = _Funcs(g)
    env.update(_NP_FUNCS)
    env.update({n: getattr(fn, n) for n in _GRID_FUNCS})
    env.update(CONSTANTS)
    known_props = set(props)
    targets = _check(tree, set(GEOMETRIC), known_props | set(env))
    # every referenced name must exist (or be assigned earlier)
    defined = set(env)
    for stmt in tree.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in defined:
                raise CalcError(f"Unknown name '{node.id}'. Available properties: {', '.join(sorted(known_props)) or 'none yet'}; "
                                f"geometry: {', '.join(GEOMETRIC)}.")
        if isinstance(stmt, (ast.Assign, ast.AugAssign)):
            for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]):
                defined.add(t.id if isinstance(t, ast.Name) else t.value.id)
    before = {n: (env[n].copy() if isinstance(env.get(n), np.ndarray) else None) for n in targets}
    try:
        with np.errstate(all="ignore"):
            exec(compile(tree, "<calculator>", "exec"), {"__builtins__": {}}, env)
    except CalcError:
        raise
    except Exception as e:
        raise CalcError(f"{type(e).__name__}: {e}") from None
    out = {}
    for n in targets:
        v = env.get(n)
        try:
            arr = np.broadcast_to(np.asarray(v, float), shape).copy()
        except Exception:
            raise CalcError(f"'{n}' has the wrong shape - results must be scalars or (K, J, I) arrays.") from None
        out[n] = arr
    return out


# ---------------------------------------------------------------------------
def attach_grid(props: Dict[str, Property], g) -> List[str]:
    """Check properties against a (re)built grid: drop wrong-sized ones, flag changed geometry as stale."""
    msgs = []
    sig, h = grid_sig(g), grid_hash(g)
    for n in list(props):
        pr = props[n]
        if tuple(pr.values.shape) != (g.nk, g.nj, g.ni):
            msgs.append(f"{n}: removed (grid size changed from {pr.values.shape[::-1]} to {sig}).")
            del props[n]
        elif pr.geom_hash != h:
            pr.stale = True
            msgs.append(f"{n}: grid geometry changed - values kept but flagged stale.")
    return msgs


def recompute_stale(props: Dict[str, Property], g) -> List[str]:
    """Re-run calculator / zone properties that were flagged stale."""
    msgs = []
    h = grid_hash(g)
    done = set()
    for n in list(props):
        pr = props.get(n)
        if pr is None or not pr.stale:
            continue
        if pr.source == "geometry":
            props[n] = geometry_properties(g, [n])[n]
            msgs.append(f"{n} regenerated")
        elif pr.source == "zones":
            for nn, np_ in zone_defaults(g).items():
                if nn in props and props[nn].source == "zones":
                    props[nn] = np_
            msgs.append("zone properties refreshed")
        elif pr.source == "calculator" and pr.expr and pr.expr not in done:
            done.add(pr.expr)
            try:
                res = run_calculator(pr.expr, g, props, out_name=n)
                for k, v in res.items():
                    old = props.get(k)
                    props[k] = make_property(g, k, v, old.kind if old else "continuous", old.unit if old else "", "calculator", pr.expr)
                msgs.append(f"{', '.join(res)} recomputed")
            except CalcError as e:
                msgs.append(f"{n}: {e}")
        elif pr.source == "polygon":
            msgs.append(f"{n}: rerun the polygon assignment on the current grid")
        else:
            pr.geom_hash = h
            pr.stale = False
    return msgs


# ---- persistence (npz) --------------------------------------------------------
def props_to_npz(props: Dict[str, Property]) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **{f"p{i}": p.values.astype(np.float32) for i, p in enumerate(props.values())})
    return buf.getvalue()


def props_from_npz(meta: List[dict], data: bytes) -> Dict[str, Property]:
    npz = np.load(io.BytesIO(data))
    return {m["name"]: Property.from_meta(m, npz[f"p{i}"]) for i, m in enumerate(meta)}
