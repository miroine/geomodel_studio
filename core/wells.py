"""Well objects: head, deviation survey (minimum curvature) or explicit path, import / export."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

WELL_COLORS = ["#00A9F4", "#2251FF", "#1B998B", "#F46036", "#6A4C93", "#C5A100", "#D7263D", "#7B8FA6"]


@dataclass
class Well:
    name: str
    x: float
    y: float
    kb: float = 0.0                  # kelly bushing above MSL (m); head depth = -kb (TVDSS, positive down)
    td: Optional[float] = None       # total depth, measured depth (m); None = derive
    survey: List[List[float]] = field(default_factory=list)   # [md, incl_deg, azim_deg]
    path: List[List[float]] = field(default_factory=list)     # explicit [x, y, z_tvdss]
    color: str = ""

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        keys = Well.__dataclass_fields__.keys()
        return Well(**{k: v for k, v in d.items() if k in keys})

    @property
    def kind(self) -> str:
        return "explicit path" if len(self.path) >= 2 else ("deviated (survey)" if len(self.survey) >= 2 else "vertical")


def scale_well(w: Well, fx: float, fz: float) -> Well:
    """Return a copy with XY lengths x fx and depth-like lengths (KB, TD, MD, TVDSS) x fz."""
    import copy
    q = copy.deepcopy(w)
    q.x, q.y = w.x * fx, w.y * fx
    q.kb = w.kb * fz
    q.td = None if w.td is None else w.td * fz
    q.survey = [[r[0] * fz] + list(r[1:]) for r in w.survey]
    q.path = [[r[0] * fx, r[1] * fx, r[2] * fz] for r in w.path]
    return q


def _mincurv(survey: np.ndarray, x0, y0, z0) -> np.ndarray:
    """Minimum-curvature stations -> array [md, x, y, z] (z = TVDSS, positive down)."""
    s = survey[np.argsort(survey[:, 0])]
    if s[0, 0] > 0:
        s = np.vstack([[0.0, 0.0, 0.0], s])
    I = np.deg2rad(s[:, 1])
    A = np.deg2rad(s[:, 2])
    out = [[s[0, 0], x0, y0, z0]]
    n_, e_, d_ = 0.0, 0.0, 0.0
    for k in range(1, len(s)):
        dmd = s[k, 0] - s[k - 1, 0]
        I1, I2, A1, A2 = I[k - 1], I[k], A[k - 1], A[k]
        cosb = np.clip(np.cos(I2 - I1) - np.sin(I1) * np.sin(I2) * (1 - np.cos(A2 - A1)), -1, 1)
        beta = np.arccos(cosb)
        rf = 1.0 if beta < 1e-9 else 2.0 / beta * np.tan(beta / 2.0)
        n_ += dmd / 2 * (np.sin(I1) * np.cos(A1) + np.sin(I2) * np.cos(A2)) * rf
        e_ += dmd / 2 * (np.sin(I1) * np.sin(A1) + np.sin(I2) * np.sin(A2)) * rf
        d_ += dmd / 2 * (np.cos(I1) + np.cos(I2)) * rf
        out.append([s[k, 0], x0 + e_, y0 + n_, z0 + d_])
    return np.array(out)


def trajectory(w: Well, td_default: float = 2500.0, step: float = 10.0) -> np.ndarray:
    """Well path as Nx3 (x, y, z) with z = TVDSS positive down."""
    z0 = -float(w.kb)
    if len(w.path) >= 2:
        return np.asarray(w.path, float)
    if len(w.survey) >= 2:
        st = _mincurv(np.asarray(w.survey, float), w.x, w.y, z0)
        md = st[:, 0]
        td = w.td if w.td else md[-1]
        grid = np.unique(np.concatenate([np.arange(0, min(td, md[-1]), step), [min(td, md[-1])]]))
        return np.column_stack([np.interp(grid, md, st[:, c]) for c in (1, 2, 3)])
    td = w.td if w.td else td_default
    return np.array([[w.x, w.y, z0], [w.x, w.y, z0 + td]])


def xy_at_depth(traj: np.ndarray, z: float) -> Tuple[float, float]:
    """Interpolate (x, y) where the path crosses depth z (first crossing)."""
    zz = traj[:, 2]
    order = np.argsort(zz)
    if not (zz.min() <= z <= zz.max()):
        return float(traj[-1, 0]), float(traj[-1, 1])
    zi = np.maximum.accumulate(zz)         # tolerate small up-hole wiggles
    return float(np.interp(z, zi, traj[:, 0])), float(np.interp(z, zi, traj[:, 1]))


def wells_from_tops(tops: pd.DataFrame, existing: Dict[str, Well], pad: float = 100.0) -> Dict[str, Well]:
    out = dict(existing)
    for i, (name, g) in enumerate(tops.groupby("well", sort=False)):
        if name in out:
            continue
        out[name] = Well(name, float(g["x"].iloc[0]), float(g["y"].iloc[0]), 0.0, float(g["z"].max() + pad),
                         color=WELL_COLORS[len(out) % len(WELL_COLORS)])
    return out


# ---------------------------------------------------------------------------
PAT = {
    "well": r"^(well|wellname|well_name|uwi|wname|borehole)$",
    "x": r"^(x|easting|east|utmx|x_coord|xcoord)$",
    "y": r"^(y|northing|north|utmy|y_coord|ycoord)$",
    "kb": r"^(kb|rkb|kelly|kelly_bushing|elev|elevation|rt)$",
    "td": r"^(td|total_depth|md_td|final_md)$",
    "md": r"^(md|mdkb|measured_depth|depth_md)$",
    "incl": r"^(incl|inc|inclination|dev|deviation|angle)$",
    "azim": r"^(azim|azi|azimuth|az)$",
    "z": r"^(z|tvdss|tvd|zss|z_tvdss|depth_tvdss|depth)$",
}


def _cols(df):
    m = {}
    for key, pat in PAT.items():
        for c in df.columns:
            if re.match(pat, str(c).strip().lower().replace(" ", "_")) and c not in m.values():
                m[key] = c
                break
    return m


def parse(data: bytes, existing: Dict[str, Well]) -> Tuple[Dict[str, Well], str]:
    """Read a well head table, a deviation survey (MD INCL AZIM) or an XYZ path table."""
    text = data.decode("latin-1")
    first = text.splitlines()[0] if text.strip() else ""
    sep = ";" if text.count(";") > text.count(",") else ("," if "," in first else r"\s+")
    df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", comment="#")
    df.columns = [str(c).strip() for c in df.columns]
    m = _cols(df)
    out = {k: Well.from_dict(v.to_dict()) for k, v in existing.items()}
    if "well" not in m:
        raise ValueError("A 'Well' column is required.")
    n_new = 0
    if {"md", "incl", "azim"} <= m.keys():
        for name, g in df.groupby(m["well"], sort=False):
            name = str(name)
            w = out.get(name) or Well(name, float(g[m["x"]].iloc[0]) if "x" in m else 0.0, float(g[m["y"]].iloc[0]) if "y" in m else 0.0,
                                      color=WELL_COLORS[len(out) % len(WELL_COLORS)])
            if "x" in m and "y" in m and not existing.get(name):
                w.x, w.y = float(g[m["x"]].iloc[0]), float(g[m["y"]].iloc[0])
            if "kb" in m:
                w.kb = float(g[m["kb"]].iloc[0])
            w.survey = g[[m["md"], m["incl"], m["azim"]]].astype(float).values.tolist()
            w.path = []
            out[name] = w
            n_new += 1
        return out, f"Survey read for {n_new} well(s) (minimum curvature)."
    if {"x", "y", "z"} <= m.keys() and df.groupby(m["well"]).size().max() >= 2:
        for name, g in df.groupby(m["well"], sort=False):
            name = str(name)
            pts = g[[m["x"], m["y"], m["z"]]].astype(float).values.tolist()
            w = out.get(name) or Well(name, pts[0][0], pts[0][1], color=WELL_COLORS[len(out) % len(WELL_COLORS)])
            w.path, w.survey = pts, []
            out[name] = w
            n_new += 1
        return out, f"Explicit XYZ path read for {n_new} well(s)."
    if {"x", "y"} <= m.keys():
        for _, r in df.iterrows():
            name = str(r[m["well"]])
            w = out.get(name) or Well(name, float(r[m["x"]]), float(r[m["y"]]), color=WELL_COLORS[len(out) % len(WELL_COLORS)])
            w.x, w.y = float(r[m["x"]]), float(r[m["y"]])
            if "kb" in m and pd.notna(r[m["kb"]]):
                w.kb = float(r[m["kb"]])
            if "td" in m and pd.notna(r[m["td"]]):
                w.td = float(r[m["td"]])
            out[name] = w
            n_new += 1
        return out, f"{n_new} well head(s) read."
    raise ValueError("Could not recognise the table: expected Well + (X, Y [, KB, TD]) or Well + (MD, INCL, AZIM) or Well + (X, Y, Z).")


def heads_table(wells: Dict[str, Well]) -> pd.DataFrame:
    return pd.DataFrame([dict(Well=w.name, X=w.x, Y=w.y, KB=w.kb, TD=w.td, Type=w.kind) for w in wells.values()])
