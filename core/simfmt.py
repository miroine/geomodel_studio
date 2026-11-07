"""Native Eclipse binary files (big-endian Fortran records): EGRID (geometry + ACTNUM) and INIT (static cell properties on the
active cells), a reader used for round-trip checks, and keyword-name shortening for the 8-character limit.

Record layout:  [int32 nbytes][payload][int32 nbytes];  a keyword is a header record (8-char name, int32 count, 4-char type)
followed by the data in blocks of at most 1000 numbers (105 strings for CHAR)."""
from __future__ import annotations

import datetime as _dt
import struct
from typing import Dict, List, Optional, Tuple
import numpy as np

from .cpgrid import CPGrid

_DT = {"INTE": ">i4", "REAL": ">f4", "DOUB": ">f8", "LOGI": ">i4"}


def _rec(payload: bytes) -> bytes:
    n = struct.pack(">i", len(payload))
    return n + payload + n


def write_kw(name: str, typ: str, data) -> bytes:
    name = name.upper().ljust(8)[:8]
    if typ == "CHAR":
        items = [str(x).ljust(8)[:8] for x in data]
        out = [_rec(name.encode() + struct.pack(">i", len(items)) + b"CHAR")]
        for i in range(0, len(items), 105):
            out.append(_rec("".join(items[i:i + 105]).encode()))
        return b"".join(out)
    arr = np.asarray(data).astype(_DT[typ]).ravel()
    out = [_rec(name.encode() + struct.pack(">i", arr.size) + typ.encode())]
    for i in range(0, arr.size, 1000):
        out.append(_rec(arr[i:i + 1000].tobytes()))
    return b"".join(out)


def read_kw(buf: bytes) -> List[Tuple[str, str, np.ndarray]]:
    """Parse an Eclipse binary file -> [(keyword, type, array)]."""
    pos, out = 0, []
    while pos < len(buf):
        n = struct.unpack(">i", buf[pos:pos + 4])[0]
        head = buf[pos + 4:pos + 4 + n]
        if n != 16 or struct.unpack(">i", buf[pos + 4 + n:pos + 8 + n])[0] != n:
            raise ValueError("bad header record")
        name = head[:8].decode().strip()
        cnt = struct.unpack(">i", head[8:12])[0]
        typ = head[12:16].decode()
        pos += 8 + n
        got, chunks = 0, []
        per = 105 if typ == "CHAR" else 1000
        while got < cnt:
            m = struct.unpack(">i", buf[pos:pos + 4])[0]
            chunks.append(buf[pos + 4:pos + 4 + m])
            if struct.unpack(">i", buf[pos + 4 + m:pos + 8 + m])[0] != m:
                raise ValueError("bad data record")
            pos += 8 + m
            got += min(per, cnt - got)
        raw = b"".join(chunks)
        if typ == "CHAR":
            arr = np.array([raw[i:i + 8].decode().strip() for i in range(0, len(raw), 8)])
        else:
            arr = np.frombuffer(raw, dtype=_DT[typ]) if cnt else np.zeros(0)
        out.append((name, typ, arr))
    return out


def egrid_bytes(g: CPGrid, system: str = "METRIC") -> bytes:
    """Eclipse EGRID of a (unit-converted) grid: FILEHEAD, GRIDUNIT, [MAPAXES], GRIDHEAD, COORD, ZCORN, ACTNUM, ENDGRID."""
    fh = np.zeros(100, int)
    fh[:4] = [3, 2007, 0, 0]
    gh = np.zeros(100, int)
    gh[:4] = [1, g.ni, g.nj, g.nk]
    gh[24] = 1
    out = [write_kw("FILEHEAD", "INTE", fh), write_kw("MAPUNITS", "CHAR", ["METRES" if system == "METRIC" else "FEET"]),
           write_kw("GRIDUNIT", "CHAR", ["METRES" if system == "METRIC" else "FEET", ""])]
    if g.rotated:
        d = 1000.0
        c, s_ = np.cos(np.deg2rad(g.angle)), np.sin(np.deg2rad(g.angle))
        ox, oy = g.origin
        out.insert(2, write_kw("MAPAXES", "REAL", [ox - d * s_, oy + d * c, ox, oy, ox + d * c, oy + d * s_]))
    out += [write_kw("GRIDHEAD", "INTE", gh), write_kw("COORD", "REAL", g.coord()), write_kw("ZCORN", "REAL", g.zc),
            write_kw("ACTNUM", "INTE", (g.actnum > 0).astype(int)), write_kw("ENDGRID", "INTE", [])]
    return b"".join(out)


def short_names(names: List[str]) -> Dict[str, str]:
    """Map property names to unique Eclipse keywords of at most 8 characters (keeps names that already fit)."""
    used, out = set(), {}
    for n in names:
        if len(n) <= 8 and n.upper() not in used:
            out[n] = n.upper()
            used.add(n.upper())
    for n in names:
        if n in out:
            continue
        base = "".join(ch for ch in n.upper() if ch.isalnum() or ch == "_")
        cand = base[:8]
        i = 1
        while cand in used:
            suf = str(i)
            cand = base[:8 - len(suf)] + suf
            i += 1
        out[n] = cand
        used.add(cand)
    return out


def init_bytes(g: CPGrid, props: Dict[str, Tuple[np.ndarray, str]], system: str = "METRIC", title: str = "GeoModel Studio") -> bytes:
    """Eclipse INIT file: INTEHEAD / LOGIHEAD / DOUBHEAD, geometry arrays (PORV, DEPTH, DX, DY, DZ) and every property on the active cells.
    ``props`` = {keyword: (array (nk, nj, ni), 'continuous' | 'discrete')}.  Keywords must already be <= 8 characters."""
    act = g.actnum > 0
    n_act = int(act.sum())
    ih = np.zeros(411, int)
    ih[2] = 1 if system == "METRIC" else 2
    ih[8:12] = [g.ni, g.nj, g.nk, n_act]
    ih[14] = 3
    now = _dt.date.today()
    ih[64:67] = [now.day, now.month, now.year]
    xs, ys = g.pillar_xy()
    dx = np.hypot(np.diff(xs, axis=1), np.diff(ys, axis=1))       # (nj+1, ni)
    dy = np.hypot(np.diff(xs, axis=0), np.diff(ys, axis=0))       # (nj, ni+1)
    cdx = 0.5 * (dx[:-1] + dx[1:])
    cdy = 0.5 * (dy[:, :-1] + dy[:, 1:])
    shape = act.shape
    dxa, dya = np.broadcast_to(cdx[None], shape)[act], np.broadcast_to(cdy[None], shape)[act]
    dza = g.thickness()[act]
    poro, ntg = props.get("PORO", (g.property_array("PORO"), "c"))[0], props.get("NTG", (g.property_array("NTG"), "c"))[0]
    bulk = g.bulk_volume()[act] if g.tilted else dxa * dya * dza
    porv = bulk * poro[act] * ntg[act]
    out = [write_kw("INTEHEAD", "INTE", ih), write_kw("LOGIHEAD", "LOGI", np.zeros(121, int)), write_kw("DOUBHEAD", "DOUB", np.zeros(229)),
           write_kw("PORV", "REAL", porv), write_kw("DEPTH", "REAL", g.center_depth()[act]), write_kw("DX", "REAL", dxa), write_kw("DY", "REAL", dya),
           write_kw("DZ", "REAL", dza)]
    for k, (arr, kind) in props.items():
        a = np.nan_to_num(np.asarray(arr, float)[act], nan=0.0)
        if kind == "discrete":
            out.append(write_kw(k, "INTE", np.rint(a)))
        else:
            out.append(write_kw(k, "REAL", a))
    return b"".join(out)
