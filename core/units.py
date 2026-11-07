"""Project units and coordinate reference system (CRS).

Convention (same idea as Petrel / RMS project settings)
-------------------------------------------------------
* The project stores **everything in its own XY unit and Z unit** (e.g. XY in m, depth in ft).
* Data are converted **once, on the way in** (import dialogs have a "file units" selector) and
  **on the way out** (exports choose the target unit system).
* ``convert_project`` re-expresses a whole project in other units; ``reproject_project`` moves it to
  another CRS (needs pyproj, or a built-in exact UTM <-> UTM path for WGS84 / ETRS89 zones).
* Depth is positive downward (TVDSS); ``z_positive`` is stored for documentation / export only.
"""
from __future__ import annotations

import copy
import math
from typing import Dict, Optional, Tuple
import numpy as np

try:                                    # optional
    import pyproj                       # type: ignore
    HAS_PYPROJ = True
except Exception:                       # pragma: no cover
    pyproj = None
    HAS_PYPROJ = False

# metres per unit
LENGTH: Dict[str, float] = {"m": 1.0, "ft": 0.3048, "ftUS": 1200.0 / 3937.0, "km": 1000.0}
UNIT_LABEL = {"m": "m", "ft": "ft", "ftUS": "ft(US)", "km": "km"}
UNITS = list(LENGTH)

DEFAULT_CRS = dict(name="Local (undefined)", epsg=None, xy_unit="m", z_unit="m", z_positive="down", vdatum="MSL")

# the unit labels the UI currently shows (set from the active project on every rerun)
ACTIVE = dict(xy="m", z="m")


def set_active(crs: Optional[dict]):
    crs = crs or DEFAULT_CRS
    ACTIVE["xy"] = crs.get("xy_unit", "m")
    ACTIVE["z"] = crs.get("z_unit", "m")


def xy() -> str:
    return UNIT_LABEL.get(ACTIVE["xy"], ACTIVE["xy"])


def z() -> str:
    return UNIT_LABEL.get(ACTIVE["z"], ACTIVE["z"])


def factor(src: str, dst: str) -> float:
    """Multiply a value in ``src`` by this to get ``dst``."""
    return LENGTH[src] / LENGTH[dst]


def convert(values, src: str, dst: str):
    return np.asarray(values, float) * factor(src, dst) if not np.isscalar(values) else values * factor(src, dst)


def unit_system(xy_unit: str, z_unit: str) -> str:
    """Reservoir-simulator unit family: METRIC (m) / FIELD (ft) / mixed -> None."""
    if xy_unit == "m" and z_unit == "m":
        return "METRIC"
    if xy_unit in ("ft", "ftUS") and z_unit in ("ft", "ftUS"):
        return "FIELD"
    return "MIXED"


# ---------------------------------------------------------------------------
# CRS catalogue
# ---------------------------------------------------------------------------
def utm_zone_of(epsg: int) -> Optional[Tuple[int, bool, str]]:
    """(zone, north, datum) for WGS84 / ETRS89 / ED50 UTM EPSG codes, else None."""
    if epsg is None:
        return None
    e = int(epsg)
    if 32601 <= e <= 32660:
        return e - 32600, True, "WGS84"
    if 32701 <= e <= 32760:
        return e - 32700, False, "WGS84"
    if 25828 <= e <= 25838:
        return e - 25800, True, "ETRS89"
    if 23028 <= e <= 23038:
        return e - 23000, True, "ED50"
    return None


def describe_epsg(epsg) -> str:
    if epsg in (None, "", 0):
        return "undefined"
    e = int(epsg)
    if e == 4326:
        return "WGS 84 geographic (lon/lat, degrees)"
    u = utm_zone_of(e)
    if u:
        return f"{u[2]} / UTM zone {u[0]}{'N' if u[1] else 'S'}"
    if HAS_PYPROJ:
        try:
            return pyproj.CRS.from_epsg(e).name
        except Exception:
            pass
    return f"EPSG:{e}"


COMMON = {
    "Local / undefined": None,
    "WGS 84 / UTM 31N (32631)": 32631, "WGS 84 / UTM 32N (32632)": 32632, "WGS 84 / UTM 33N (32633)": 32633,
    "WGS 84 / UTM 30N (32630)": 32630, "WGS 84 / UTM 39N (32639)": 32639, "WGS 84 / UTM 40N (32640)": 32640,
    "ETRS89 / UTM 31N (25831)": 25831, "ETRS89 / UTM 32N (25832)": 25832, "ETRS89 / UTM 33N (25833)": 25833,
    "ED50 / UTM 31N (23031)": 23031, "ED50 / UTM 32N (23032)": 23032,
    "Other EPSG code": -1,
}


# ---------------------------------------------------------------------------
# Built-in transverse-Mercator (Kruger series, mm-level accuracy) for UTM <-> WGS84 / ETRS89
# ---------------------------------------------------------------------------
_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996


def _tm_consts():
    n = _F / (2 - _F)
    A = _A / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    a = [n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16, 13 * n ** 2 / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240]
    b = [n / 2 - 2 * n ** 2 / 3 + 37 * n ** 3 / 96, n ** 2 / 48 + n ** 3 / 15, 17 * n ** 3 / 480]
    return n, A, a, b


def lonlat_to_utm(lon, lat, zone: int, north: bool = True):
    n, A, a, _ = _tm_consts()
    lon0 = math.radians(6 * zone - 183)
    phi = np.radians(np.asarray(lat, float))
    lam = np.radians(np.asarray(lon, float)) - lon0
    e = math.sqrt(_F * (2 - _F))
    t = np.sinh(np.arctanh(np.sin(phi)) - e * np.arctanh(e * np.sin(phi)))
    xi = np.arctan2(t, np.cos(lam))
    eta = np.arctanh(np.sin(lam) / np.sqrt(1 + t * t))
    xs = xi.copy()
    es = eta.copy()
    for j, aj in enumerate(a, 1):
        xs = xs + aj * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        es = es + aj * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    E = 500000.0 + _K0 * A * es
    N = _K0 * A * xs + (0.0 if north else 10000000.0)
    return E, N


def utm_to_lonlat(E, N, zone: int, north: bool = True):
    n, A, _, b = _tm_consts()
    E = np.asarray(E, float)
    N = np.asarray(N, float)
    xi = (N - (0.0 if north else 10000000.0)) / (_K0 * A)
    eta = (E - 500000.0) / (_K0 * A)
    xs = xi.copy()
    es = eta.copy()
    for j, bj in enumerate(b, 1):
        xs = xs - bj * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        es = es - bj * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    chi = np.arcsin(np.sin(xs) / np.cosh(es))
    e = math.sqrt(_F * (2 - _F))
    phi = chi.copy()
    for _ in range(6):                                  # isometric latitude inversion
        phi = np.arcsin(np.tanh(np.arctanh(np.sin(chi)) + e * np.arctanh(e * np.sin(phi))))
    lam = np.arctan2(np.sinh(es), np.cos(xs))
    return np.degrees(lam) + 6 * zone - 183, np.degrees(phi)


class ReprojectionError(Exception):
    pass


def transform_xy(x, y, src_epsg: int, dst_epsg: int, src_unit="m", dst_unit="m"):
    """Transform map coordinates between CRSs (inputs/outputs in the given linear units)."""
    x = np.asarray(x, float) * factor(src_unit, "m")
    y = np.asarray(y, float) * factor(src_unit, "m")
    if int(src_epsg) == int(dst_epsg):
        return x * factor("m", dst_unit), y * factor("m", dst_unit)
    if HAS_PYPROJ:
        t = pyproj.Transformer.from_crs(int(src_epsg), int(dst_epsg), always_xy=True)
        xo, yo = t.transform(x, y)
    else:
        us, ud = utm_zone_of(src_epsg), utm_zone_of(dst_epsg)
        ok = lambda u: u is not None and u[2] in ("WGS84", "ETRS89")      # ETRS89 ~ WGS84 (<~1 m)
        if int(src_epsg) == 4326:
            lon, lat = x / factor("m", "m"), y
        elif ok(us):
            lon, lat = utm_to_lonlat(x, y, us[0], us[1])
        else:
            raise ReprojectionError(f"EPSG:{src_epsg} -> EPSG:{dst_epsg} needs pyproj (not installed); "
                                    "only WGS84 / ETRS89 UTM zones can be converted without it.")
        if int(dst_epsg) == 4326:
            xo, yo = lon, lat
        elif ok(ud):
            xo, yo = lonlat_to_utm(lon, lat, ud[0], ud[1])
        else:
            raise ReprojectionError(f"EPSG:{src_epsg} -> EPSG:{dst_epsg} needs pyproj (not installed); "
                                    "only WGS84 / ETRS89 UTM zones can be converted without it.")
    return np.asarray(xo) * factor("m", dst_unit), np.asarray(yo) * factor("m", dst_unit)


def can_reproject(src_epsg, dst_epsg) -> Tuple[bool, str]:
    if not src_epsg or not dst_epsg:
        return False, "Both the current and the target EPSG code must be known."
    if HAS_PYPROJ:
        return True, "pyproj"
    ok = lambda e: int(e) == 4326 or (utm_zone_of(e) and utm_zone_of(e)[2] in ("WGS84", "ETRS89"))
    if ok(src_epsg) and ok(dst_epsg):
        return True, "built-in UTM (WGS84/ETRS89, datum differences < 1 m ignored)"
    return False, "pyproj is not installed - only WGS84 / ETRS89 UTM zones can be reprojected."


# ---------------------------------------------------------------------------
# scaling helpers for imports / exports
# ---------------------------------------------------------------------------
def scale_geometry(g, fxy: float):
    from .surface import Geometry
    return Geometry(g.xori * fxy, g.yori * fxy, g.xinc * fxy, g.yinc * fxy, g.ncol, g.nrow, g.rotation)


def scale_surface(s, fxy: float, fz: float):
    from .surface import Surface
    return Surface(s.name, scale_geometry(s.geom, fxy), s.z * fz, s.source)


def scale_points(p, fxy: float, fz: float):
    q = np.array(p, float, copy=True)
    q[:, 0] *= fxy
    q[:, 1] *= fxy
    if q.shape[1] > 2:
        q[:, 2] *= fz
    return q


def import_factors(crs: dict, file_xy: Optional[str], file_z: Optional[str]) -> Tuple[float, float]:
    """(fxy, fz) taking file units -> project units. ``None`` = same as the project."""
    fx = factor(file_xy or crs["xy_unit"], crs["xy_unit"])
    fz = factor(file_z or crs["z_unit"], crs["z_unit"])
    return fx, fz


# ---------------------------------------------------------------------------
# whole-project conversion
# ---------------------------------------------------------------------------
_STEP_Z = ("shift", "thickness", "zmin", "zmax", "fill_value", "tmin", "tmax")
_STEP_XY = ("radius", "fill_length", "vrange")


def _scale_contacts(c, fx, fz):
    for contact in [c] + list(c.get("blocks", {}).values()) + list((c.get("regions") or {}).get("values", {}).values()):
        for key in ("owc", "goc"):
            contact[key] = None if contact.get(key) is None else contact[key] * fz
    tilt = c.get("tilt")
    if tilt:
        tilt["gx"], tilt["gy"] = tilt.get("gx", 0.0) * fz / fx, tilt.get("gy", 0.0) * fz / fx
        tilt["xref"], tilt["yref"] = tilt.get("xref", 0.0) * fx, tilt.get("yref", 0.0) * fx
    c["fwl_below"] = c.get("fwl_below", 0.0) * fz


def _scale_facies(cfg, fx, fz):
    for zone in cfg.get("zones", []):
        for key in ("major", "minor", "major2", "minor2"):
            if key in zone:
                zone[key] *= fx
        for key in ("vert", "vert2"):
            if key in zone:
                zone[key] *= fz
    for obj in cfg.get("objects", []):
        for key in ("length", "width", "amplitude", "wavelength"):
            if key in obj:
                obj[key] *= fx
        obj["thickness"] *= fz
        obj["centerline"] = [[x * fx, y * fx] for x, y in obj.get("centerline", [])]


def convert_project(p, new_xy: str, new_z: str):
    """Re-express every stored length in ``new_xy`` / ``new_z`` (in place). Returns a short log."""
    crs = p.crs
    fx, fz = factor(crs["xy_unit"], new_xy), factor(crs["z_unit"], new_z)
    if abs(fx - 1) < 1e-15 and abs(fz - 1) < 1e-15:
        crs["xy_unit"], crs["z_unit"] = new_xy, new_z
        return ["Units unchanged."]
    if p.lattice is not None:
        p.lattice = scale_geometry(p.lattice, fx)
    for n, s in list(p.surfaces.items()):
        s.geom = scale_geometry(s.geom, fx)
        s.z = s.z * fz
        if n in p.raw:
            p.raw[n] = p.raw[n] * fz
    for f in p.faults.values():
        f.trace = [[a * fx, b * fx] for a, b in f.trace]
        f.throw *= fz
        f.drag *= fx
        f.slip *= fx
        f.zref *= fz
    for pol in list(p.polygons.values()) + list(p.fences.values()):
        pol.pts = [[a * fx, b * fx] for a, b in pol.pts]
    for w in p.wells.values():
        w.x *= fx
        w.y *= fx
        w.kb *= fz
        w.td = None if w.td is None else w.td * fz
        w.survey = [[r[0] * fz] + list(r[1:]) for r in w.survey]
        w.path = [[r[0] * fx, r[1] * fx, r[2] * fz] for r in w.path]
    for lg in getattr(p, "logs", {}).values():
        lg["md"] = np.asarray(lg["md"], float) * fz
    if len(p.tops):
        p.tops = p.tops.copy()
        p.tops[["x", "y"]] = p.tops[["x", "y"]] * fx
        p.tops["z"] = p.tops["z"] * fz
    vc = getattr(p, "volumetrics", None)
    if vc:                                            # contact depths and the saturation-height entry height are depths / heights
        c = vc["contacts"]
        _scale_contacts(c, fx, fz)
        if vc.get("unc", {}).get("struct"):
            vc["unc"]["struct"][0] *= fz
        vc["sw"]["entry"] = vc["sw"]["entry"] * fz
        vc["unc"]["owc"] = [a * fz for a in vc["unc"]["owc"]]
    for model in p.property_models.values():
        if model.get("method") == "satheight":
            for row in model.get("rows", []):
                row["entry"] = float(row["entry"]) * fz
                if "gas_entry" in row:
                    row["gas_entry"] *= fz
    if p.facies:
        _scale_facies(p.facies, fx, fz)
    for job in p.property_jobs:
        cfg = job["config"]
        kind = job["type"]
        if kind == "facies":
            _scale_facies(cfg, fx, fz)
        elif kind == "stochastic":
            for prop in cfg["props"].values():
                for row in prop["rows"] + prop.get("facies_rows", []):
                    row["major"] *= fx
                    row["minor"] *= fx
                    row["vert"] *= fz
        elif kind == "saturation":
            if cfg["method"] == "satheight":
                for row in cfg["rows"]:
                    row["entry"] *= fz
                    if "gas_entry" in row:
                        row["gas_entry"] *= fz
            _scale_contacts(cfg["contacts"]["contacts"], fx, fz)
    dg = p.digitized
    for c in dg.get("contours", []):
        c["z"] = c["z"] * fz
        c["pts"] = [[a * fx, b * fx] for a, b in c["pts"]]
    dg["points"] = [[r[0] * fx, r[1] * fx, r[2] * fz] for r in dg.get("points", [])]
    for t in dg.get("faults", []):
        t["pts"] = [[a * fx, b * fx] for a, b in t["pts"]]
    for s in p.steps:
        for k in _STEP_Z:
            if s.get(k) not in (None, ""):
                s[k] = float(s[k]) * fz
        for k in _STEP_XY:
            if s.get(k) not in (None, ""):
                s[k] = float(s[k]) * fx
        for k in ("gx", "gy"):                            # z-units per 1000 xy-units
            if s.get(k):
                s[k] = float(s[k]) * fz / fx
    for z in p.zones:
        z.dz *= fz
    gp = p.grid_params
    gp["dx"] *= fx
    gp["dy"] *= fx
    gp["min_thickness"] *= fz
    if gp.get("min_volume"):
        gp["min_volume"] *= fx * fx * fz
    for k in ("origin", "extent"):
        if gp.get(k):
            gp[k] = [v * fx for v in gp[k]]
    for w in gp.get("refine", []) or []:
        for k in ("x0", "x1", "y0", "y1", "dx", "dy"):
            if w.get(k):
                w[k] = float(w[k]) * fx
    crs["xy_unit"], crs["z_unit"] = new_xy, new_z
    for st_ in p.filters.values():                        # value filters hold depth limits / buffers
        lists = [st_.get("ops", [])] + list(st_.get("undo", [])) + list(st_.get("redo", []))
        for ops in lists:
            for op in ops:
                if op.get("type") == "polygon" and op.get("buffer"):
                    op["buffer"] = float(op["buffer"]) * fx
                elif op.get("type") == "range" and op.get("mode") != "percentile":
                    for k in ("min", "max"):
                        if op.get(k) is not None:
                            op[k] = float(op[k]) * fz
                elif op.get("type") == "slope" and op.get("max_slope"):
                    op["max_slope"] = float(op["max_slope"]) * fz / fx
    for pr in p.filter_presets.values():
        for op in pr:
            if op.get("type") == "range" and op.get("mode") != "percentile":
                for k in ("min", "max"):
                    if op.get(k) is not None:
                        op[k] = float(op[k]) * fz
            elif op.get("type") == "polygon" and op.get("buffer"):
                op["buffer"] = float(op["buffer"]) * fx
    p.invalidate()
    set_active(crs)
    return [f"XY x{fx:.6g}, Z x{fz:.6g}: lattice, {len(p.surfaces)} surface(s), {len(p.faults)} fault(s), "
            f"{len(p.wells)} well(s), {len(p.tops)} top(s), {len(p.polygons)} polygon(s), workflow steps and zones converted."]


def reproject_project(p, dst_epsg: int):
    """Move the project to another CRS (same linear units). Surfaces are resampled on a new, unrotated lattice."""
    crs = p.crs
    src = crs.get("epsg")
    ok, how = can_reproject(src, dst_epsg)
    if not ok:
        raise ReprojectionError(how)
    unit = crs["xy_unit"]

    def T(x, y):
        return transform_xy(x, y, src, dst_epsg, unit, unit)

    def Tinv(x, y):
        return transform_xy(x, y, dst_epsg, src, unit, unit)

    from .surface import Geometry, Surface
    old = p.lattice
    if old is not None:
        X, Y = old.coords()
        Xn, Yn = T(X, Y)
        new = Geometry.from_bounds(float(Xn.min()), float(Xn.max()), float(Yn.min()), float(Yn.max()), old.xinc, old.yinc)
        if new.ncol * new.nrow > 400_000:
            raise ReprojectionError("Reprojected lattice would exceed 400 000 nodes - increase the cell size first.")
    else:
        new = None
    for n, s in list(p.surfaces.items()):
        Xn, Yn = (new or s.geom).coords()
        xo, yo = Tinv(Xn, Yn)
        zr = Surface(n, s.geom, p.raw.get(n, s.z)).sample(xo, yo, order=1, extrapolate=False)
        zs = s.sample(xo, yo, order=1, extrapolate=False)
        g2 = new or s.geom
        p.surfaces[n] = Surface(n, g2, zs, s.source)
        p.raw[n] = zr
    if new is not None:
        p.lattice = new
    for f in p.faults.values():
        a, b = T(np.array([q[0] for q in f.trace]), np.array([q[1] for q in f.trace]))
        f.trace = [[float(u), float(v)] for u, v in zip(a, b)]
    for pol in list(p.polygons.values()) + list(p.fences.values()):
        a, b = T(np.array([q[0] for q in pol.pts]), np.array([q[1] for q in pol.pts]))
        pol.pts = [[float(u), float(v)] for u, v in zip(a, b)]
    for w in p.wells.values():
        w.x, w.y = [float(v) for v in T(w.x, w.y)]
        if w.path:
            a, b = T(np.array([r[0] for r in w.path]), np.array([r[1] for r in w.path]))
            w.path = [[float(u), float(v), r[2]] for u, v, r in zip(a, b, w.path)]
    if len(p.tops):
        p.tops = p.tops.copy()
        p.tops["x"], p.tops["y"] = T(p.tops["x"].values, p.tops["y"].values)
    dg = p.digitized
    for c in dg.get("contours", []):
        a, b = T(np.array([q[0] for q in c["pts"]]), np.array([q[1] for q in c["pts"]]))
        c["pts"] = [[float(u), float(v)] for u, v in zip(a, b)]
    for t in dg.get("faults", []):
        a, b = T(np.array([q[0] for q in t["pts"]]), np.array([q[1] for q in t["pts"]]))
        t["pts"] = [[float(u), float(v)] for u, v in zip(a, b)]
    if dg.get("points"):
        a, b = T(np.array([r[0] for r in dg["points"]]), np.array([r[1] for r in dg["points"]]))
        dg["points"] = [[float(u), float(v), r[2]] for u, v, r in zip(a, b, dg["points"])]
    crs["epsg"] = int(dst_epsg)
    crs["name"] = describe_epsg(dst_epsg)
    p.invalidate()
    p.recompute_all()
    return [f"Reprojected EPSG:{src} -> EPSG:{dst_epsg} via {how}; surfaces resampled bilinearly on a new unrotated lattice "
            "(faults, wells, polygons, tops, digitized data transformed point by point). The workflow must be re-run."]
