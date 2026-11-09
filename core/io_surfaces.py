"""Surface import / export.

Reading
-------
* ESRI/Surfer-style ASCII grid (``ncols nrows xllcorner yllcorner cellsize NODATA_value``)
* IRAP/RMS classic ASCII and IRAP/RMS binary  (xtgeo when installed; pure-Python fallback otherwise)
* XYZ scattered points (``.xyz .csv .txt .dat``) -> returned as points, to be gridded by the user

Writing
-------
* ESRI ASCII, IRAP ASCII, IRAP binary (xtgeo when installed), XYZ CSV
"""
from __future__ import annotations

import io
import os
import re
import struct
import tempfile
from typing import Tuple, Union

import numpy as np

from .surface import Geometry, Surface

try:  # optional, preferred for IRAP
    import xtgeo  # type: ignore
    HAS_XTGEO = True
except Exception:  # pragma: no cover - depends on environment
    xtgeo = None
    HAS_XTGEO = False

IRAP_UNDEF = 9999900.0


# ---------------------------------------------------------------------------
# format sniffing
# ---------------------------------------------------------------------------
def sniff_format(data: bytes, filename: str = "") -> str:
    """Return 'esri_ascii' | 'irap_binary' | 'irap_ascii' | 'xyz'."""
    if len(data) >= 12:
        rec, mag = struct.unpack(">ii", data[:8])
        if rec == 32 and mag == -996:
            return "irap_binary"
    head = data[:2000].decode("latin-1", errors="ignore").lower()
    if re.match(r"\s*ncols\b", head):
        return "esri_ascii"
    toks = head.split()
    if toks and toks[0] in ("-996",):
        return "irap_ascii"
    return "xyz"


# ---------------------------------------------------------------------------
# ESRI ASCII
# ---------------------------------------------------------------------------
def read_esri_ascii(data: bytes, name="Surface") -> Surface:
    text = data.decode("latin-1")
    lines = text.splitlines()
    hdr, k = {}, 0
    while k < len(lines):
        parts = lines[k].split()
        if len(parts) == 2 and re.match(r"[A-Za-z_]+$", parts[0]):
            hdr[parts[0].lower()] = float(parts[1])
            k += 1
        else:
            break
    ncol, nrow = int(hdr["ncols"]), int(hdr["nrows"])
    cs = hdr.get("cellsize")
    dx = hdr.get("dx", cs)
    dy = hdr.get("dy", cs)
    if dx is None or dy is None:
        raise ValueError("ESRI ASCII header lacks cellsize")
    if "xllcorner" in hdr:
        xori = hdr["xllcorner"] + dx / 2.0
        yori = hdr["yllcorner"] + dy / 2.0
    else:
        xori, yori = hdr["xllcenter"], hdr["yllcenter"]
    nodata = hdr.get("nodata_value", -9999.0)
    vals = np.fromstring(" ".join(lines[k:]), sep=" ")
    if vals.size != ncol * nrow:
        raise ValueError(f"ESRI ASCII: expected {ncol * nrow} values, found {vals.size}")
    z = vals.reshape(nrow, ncol)[::-1]                       # file is north -> south
    z = np.where(np.isclose(z, nodata), np.nan, z)
    return Surface(name, Geometry(xori, yori, dx, dy, ncol, nrow, 0.0), z, "esri_ascii")


def write_esri_ascii(s: Surface, nodata=-9999.0) -> bytes:
    g = s.geom
    if abs(g.rotation) > 1e-9:
        raise ValueError("ESRI ASCII cannot store rotated grids; resample to an unrotated lattice first")
    if abs(g.xinc - g.yinc) > 1e-9:
        head = (f"ncols {g.ncol}\nnrows {g.nrow}\nxllcorner {g.xori - g.xinc / 2}\n"
                f"yllcorner {g.yori - g.yinc / 2}\ndx {g.xinc}\ndy {g.yinc}\nNODATA_value {nodata}\n")
    else:
        head = (f"ncols {g.ncol}\nnrows {g.nrow}\nxllcorner {g.xori - g.xinc / 2}\n"
                f"yllcorner {g.yori - g.yinc / 2}\ncellsize {g.xinc}\nNODATA_value {nodata}\n")
    z = np.where(np.isnan(s.z), nodata, s.z)[::-1]
    body = "\n".join(" ".join(f"{v:.4f}" for v in row) for row in z)
    return (head + body + "\n").encode()


# ---------------------------------------------------------------------------
# IRAP ASCII (classic)
# ---------------------------------------------------------------------------
# Standard IRAP ASCII header:  -996 NY XINC YINC / XORI XMAX YORI YMAX / NX ROT X0ORI Y0ORI / 7 ints,
# then node values with the X index running fastest (row by row). The pure-Python readers are a
# fallback for machines without xtgeo; xtgeo is always used first when it is installed.
def write_irap_ascii(s: Surface) -> bytes:
    g = s.geom
    xmax = g.xori + (g.ncol - 1) * g.xinc
    ymax = g.yori + (g.nrow - 1) * g.yinc
    out = io.StringIO()
    out.write(f"-996 {g.nrow} {g.xinc:.6f} {g.yinc:.6f}\n")
    out.write(f"{g.xori:.6f} {xmax:.6f} {g.yori:.6f} {ymax:.6f}\n")
    out.write(f"{g.ncol} {g.rotation:.6f} {g.xori:.6f} {g.yori:.6f}\n")
    out.write("0 0 0 0 0 0 0\n")
    v = np.where(np.isnan(s.z), 9999900.0, s.z).ravel()
    for k in range(0, v.size, 5):
        out.write(" ".join(f"{x:.4f}" for x in v[k:k + 5]) + "\n")
    return out.getvalue().encode()


def read_irap_ascii_py(data: bytes, name="Surface") -> Surface:
    toks = data.decode("latin-1").split()
    ny = int(toks[1])
    xinc, yinc = float(toks[2]), float(toks[3])
    xori, xmax, yori, ymax = (float(t) for t in toks[4:8])
    nx = int(toks[8])
    rot = float(toks[9])
    vals = np.array(toks[19:], dtype=float)
    if vals.size != nx * ny:
        raise ValueError(f"IRAP ASCII: expected {nx * ny} values, found {vals.size}")
    z = vals.reshape(ny, nx)
    z = np.where(z >= IRAP_UNDEF * 0.999, np.nan, z)
    return Surface(name, Geometry(xori, yori, xinc, yinc, nx, ny, rot), z, "irap_ascii")


# ---------------------------------------------------------------------------
# IRAP binary (pure python fallback)
# ---------------------------------------------------------------------------
def read_irap_binary_py(data: bytes, name="Surface") -> Surface:
    pos = 0

    def rec():
        nonlocal pos
        (n,) = struct.unpack(">i", data[pos:pos + 4])
        payload = data[pos + 4:pos + 4 + n]
        pos += 8 + n
        return payload

    h1 = struct.unpack(">iiffffff", rec())      # -996, ny, xori, xmax, yori, ymax, xinc, yinc
    ny = h1[1]
    xori, xmax, yori, ymax, xinc, yinc = h1[2:8]
    h2 = struct.unpack(">ifff", rec())          # nx, rot, x0ori, y0ori
    nx, rot = h2[0], h2[1]
    rec()                                       # 7 ints
    vals = []
    while pos < len(data) and len(vals) < nx * ny:
        p = rec()
        vals.extend(struct.unpack(f">{len(p) // 4}f", p))
    v = np.array(vals[:nx * ny], dtype=float)
    z = v.reshape(ny, nx)
    z = np.where(z >= IRAP_UNDEF * 0.999, np.nan, z)
    return Surface(name, Geometry(xori, yori, xinc, yinc, nx, ny, rot), z, "irap_binary")


def write_irap_binary_py(s: Surface) -> bytes:
    g = s.geom
    xmax = g.xori + (g.ncol - 1) * g.xinc
    ymax = g.yori + (g.nrow - 1) * g.yinc
    out = bytearray()

    def rec(payload: bytes):
        out.extend(struct.pack(">i", len(payload)) + payload + struct.pack(">i", len(payload)))

    rec(struct.pack(">iiffffff", -996, g.nrow, g.xori, xmax, g.yori, ymax, g.xinc, g.yinc))
    rec(struct.pack(">ifff", g.ncol, g.rotation, g.xori, g.yori))
    rec(struct.pack(">7i", 0, 0, 0, 0, 0, 0, 0))
    v = np.where(np.isnan(s.z), IRAP_UNDEF, s.z).astype(">f4").ravel()
    for k in range(0, v.size, 9):
        rec(v[k:k + 9].tobytes())
    return bytes(out)


# ---------------------------------------------------------------------------
# xtgeo bridge
# ---------------------------------------------------------------------------
def _from_xtgeo(rs, name, source) -> Surface:
    if getattr(rs, "yflip", 1) == -1:
        raise ValueError("Surfaces with yflip = -1 are not supported; re-export the map with yflip = 1.")
    vals = np.ma.filled(rs.values.astype(float), np.nan)          # (ncol, nrow)
    geom = Geometry(rs.xori, rs.yori, rs.xinc, rs.yinc, rs.ncol, rs.nrow, rs.rotation)
    return Surface(name, geom, vals.T.copy(), source)


def _to_xtgeo(s: Surface):
    vals = np.ma.masked_invalid(s.z.T)
    return xtgeo.RegularSurface(ncol=s.geom.ncol, nrow=s.geom.nrow, xinc=s.geom.xinc, yinc=s.geom.yinc,
                                xori=s.geom.xori, yori=s.geom.yori, rotation=s.geom.rotation, values=vals)


def read_irap_xtgeo(data: bytes, fmt: str, name: str) -> Surface:
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "in.gri")
        with open(p, "wb") as f:
            f.write(data)
        rs = xtgeo.surface_from_file(p, fformat=fmt)
        return _from_xtgeo(rs, name, f"{fmt}(xtgeo)")


def write_irap_xtgeo(s: Surface, fmt: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "out.gri")
        _to_xtgeo(s).to_file(p, fformat=fmt)
        with open(p, "rb") as f:
            return f.read()


# ---------------------------------------------------------------------------
# XYZ points
# ---------------------------------------------------------------------------
def read_xyz(data: bytes) -> np.ndarray:
    text = data.decode("latin-1")
    rows = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", "//", "--")):
            continue
        parts = re.split(r"[,\s;]+", ln)
        try:
            vals = [float(p) for p in parts[:3]]
        except ValueError:
            continue                     # header line
        if len(vals) == 3:
            rows.append(vals)
    if not rows:
        raise ValueError("No numeric X Y Z rows found.")
    return np.array(rows)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def read_any(data: bytes, filename: str = "surface", name: str = None) -> Tuple[str, Union[Surface, np.ndarray]]:
    """Return ('surface', Surface) or ('points', Nx3 array)."""
    if os.path.splitext(filename)[1].lower() in (".pol", ".rmspolygons"):
        raise ValueError("This is an RMS polygon file. Import it on the Polygons page, not as surface points.")
    name = name or os.path.splitext(os.path.basename(filename))[0]
    fmt = sniff_format(data, filename)
    if fmt == "esri_ascii":
        return "surface", read_esri_ascii(data, name)
    if fmt == "irap_binary":
        if HAS_XTGEO:
            try:
                return "surface", read_irap_xtgeo(data, "irap_binary", name)
            except Exception:
                pass
        return "surface", read_irap_binary_py(data, name)
    if fmt == "irap_ascii":
        if HAS_XTGEO:
            try:
                return "surface", read_irap_xtgeo(data, "irap_ascii", name)
            except Exception:
                pass
        return "surface", read_irap_ascii_py(data, name)
    return "points", read_xyz(data)


def write_surface(s: Surface, fmt: str) -> Tuple[bytes, str]:
    """fmt: esri_ascii | irap_ascii | irap_binary | xyz.  Returns (bytes, extension)."""
    if fmt == "esri_ascii":
        return write_esri_ascii(s), "asc"
    if fmt == "irap_ascii":
        if HAS_XTGEO:
            return write_irap_xtgeo(s, "irap_ascii"), "irap"
        return write_irap_ascii(s), "irap"
    if fmt == "irap_binary":
        if HAS_XTGEO:
            return write_irap_xtgeo(s, "irap_binary"), "gri"
        return write_irap_binary_py(s), "gri"
    if fmt == "xyz":
        X, Y = s.geom.coords()
        m = np.isfinite(s.z)
        buf = io.StringIO()
        buf.write("X,Y,Z\n")
        for x, y, z in zip(X[m], Y[m], s.z[m]):
            buf.write(f"{x:.3f},{y:.3f},{z:.3f}\n")
        return buf.getvalue().encode(), "csv"
    raise ValueError(fmt)
