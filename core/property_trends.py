"""Additive property trends sampled at grid cell centres."""
from __future__ import annotations

import numpy as np


class TrendError(ValueError):
    pass


def offset(grid, cfg, surfaces=None):
    result = np.zeros(grid.actnum.shape, dtype=float)
    active = grid.actnum > 0
    if cfg.get("depth_enabled"):
        try:
            curve = np.asarray(cfg.get("curve", []), dtype=float)
        except (TypeError, ValueError) as exc:
            raise TrendError("Depth trend pairs must be numeric.") from exc
        if curve.ndim != 2 or curve.shape[1] != 2 or len(curve) < 2 or not np.isfinite(curve).all():
            raise TrendError("Depth trend needs at least two finite depth/offset pairs.")
        curve = curve[np.argsort(curve[:, 0])]
        if (np.diff(curve[:, 0]) <= 0).any():
            raise TrendError("Depth trend depths must be unique.")
        depth = grid.center_depth()
        if not np.isfinite(depth[active]).all():
            raise TrendError("Grid cell depths are undefined in active cells.")
        result += np.interp(depth, curve[:, 0], curve[:, 1])
    if cfg.get("map_enabled"):
        name = cfg.get("map", "")
        surface = (surfaces or {}).get(name)
        if surface is None:
            raise TrendError(f"Trend map '{name}' is missing from the surface library.")
        try:
            strength, reference = float(cfg.get("strength", 1)), float(cfg.get("reference", 0))
        except (TypeError, ValueError) as exc:
            raise TrendError("Map trend strength and reference must be numeric.") from exc
        if not np.isfinite([strength, reference]).all():
            raise TrendError("Map trend strength and reference must be finite.")
        x, y = grid.center_xy()
        values = surface.sample(x, y, extrapolate=False)
        covered = active.any(axis=0)
        if not np.isfinite(values[covered]).all():
            raise TrendError(f"Trend map '{name}' does not cover every active grid column. Extend the map before modelling.")
        result += np.where(np.isfinite(values), strength * (values - reference), 0)[None]
    if not np.isfinite(result[active]).all():
        raise TrendError("Property trend produces non-finite offsets.")
    return result
