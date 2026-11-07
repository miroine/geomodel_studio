"""Well tops: parsing, QC and surface calibration (residual correction)."""
from __future__ import annotations

import io
import re
from typing import Optional
import numpy as np
import pandas as pd

from .surface import Geometry
from .interp import grid_points
from scipy.spatial import cKDTree

COLS = ["well", "x", "y", "horizon", "z"]
PATTERNS = {
    "well": r"^(well|wellname|well_name|uwi|wname|borehole)$",
    "x": r"^(x|easting|east|utmx|x_coord|xcoord|x_utm)$",
    "y": r"^(y|northing|north|utmy|y_coord|ycoord|y_utm)$",
    "horizon": r"^(horizon|surface|top|pick|marker|formation|zone|surf|strat|horizon_name|surface_name|top_name)$",
    "z": r"^(z|tvdss|tvd|depth|md|z_tvdss|zvalue|z_value|depth_tvdss)$",
}


def parse_tops(data: bytes) -> pd.DataFrame:
    """Read a tops table (CSV/whitespace) and map columns by name patterns."""
    text = data.decode("latin-1")
    sep = ";" if text.count(";") > text.count(",") else ("," if "," in text.splitlines()[0] else r"\s+")
    df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", comment="#")
    df.columns = [str(c).strip() for c in df.columns]
    mapping = {}
    for key, pat in PATTERNS.items():
        for c in df.columns:
            if re.match(pat, c.strip().lower().replace(" ", "_")) and c not in mapping.values():
                mapping[key] = c
                break
    missing = [k for k in COLS if k not in mapping]
    if missing:
        if len(df.columns) >= 5:        # fall back to positional columns
            mapping = dict(zip(COLS, df.columns[:5]))
        else:
            raise ValueError(f"Could not identify columns for: {', '.join(missing)}. Expected {COLS}.")
    out = df[[mapping[k] for k in COLS]].copy()
    out.columns = COLS
    for c in ("x", "y", "z"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["well"] = out["well"].astype(str).str.strip()
    out["horizon"] = out["horizon"].astype(str).str.strip()
    return out.dropna(subset=["x", "y", "z"]).reset_index(drop=True)


def residual_table(tops: pd.DataFrame, horizon_label: str, model_z: np.ndarray) -> pd.DataFrame:
    t = tops[tops["horizon"] == horizon_label].copy()
    t["model_z"] = model_z
    t["residual"] = t["z"] - t["model_z"]          # observed - model (+ve = model too shallow)
    return t


def calibrate_base(base_z: np.ndarray, geom: Geometry, wx, wy, resid, method="min_curvature",
                   radius: float = 0.0, tension: float = 0.3, smoothing: float = 0.0, **kw) -> np.ndarray:
    """Return a corrected base surface honouring the residuals at the wells.

    method: shift | min_curvature | rbf | idw | linear.   ``radius`` > 0 tapers the correction
    (Gaussian) with distance to the nearest well so the update stays local.
    """
    wx, wy, resid = np.asarray(wx, float), np.asarray(wy, float), np.asarray(resid, float)
    ok = np.isfinite(resid)
    wx, wy, resid = wx[ok], wy[ok], resid[ok]
    if len(resid) == 0:
        return base_z
    if method == "shift":
        return base_z + float(np.mean(resid))
    pts = np.column_stack([wx, wy, resid])
    uniq = np.unique(np.round(pts[:, :2], 3), axis=0)
    m = method
    if len(uniq) < 3 and m != "idw":
        m = "idw"
    if len(uniq) == 1 or m == "idw" and len(uniq) < 3:
        field = grid_points(pts, geom, "idw", k=len(pts), power=2.0).z
    else:
        field = grid_points(pts, geom, m, tension=tension, smoothing=smoothing, **kw).z
    if radius and radius > 0:
        X, Y = geom.coords()
        d, _ = cKDTree(np.column_stack([wx, wy])).query(np.column_stack([X.ravel(), Y.ravel()]))
        field = field * np.exp(-(d.reshape(geom.shape) / radius) ** 2)
    return base_z + field
