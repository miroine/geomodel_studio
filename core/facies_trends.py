"""Spatial offsets to facies probabilities."""
import numpy as np

from . import property_trends


def _curve(values, points, label):
    curve = np.asarray(points, dtype=float)
    if curve.ndim != 2 or curve.shape[1] != 2 or len(curve) < 2 or not np.isfinite(curve).all():
        raise ValueError(f"{label} needs at least two finite coordinate/offset pairs.")
    curve = curve[np.argsort(curve[:, 0])]
    if (np.diff(curve[:, 0]) <= 0).any():
        raise ValueError(f"{label} coordinates must be unique.")
    return np.interp(values, curve[:, 0], curve[:, 1])


def offsets(grid, config, surfaces):
    shape = grid.actnum.shape
    active = grid.actnum > 0
    result = np.zeros((len(config["facies"]), *shape), dtype=float)
    trends = config.get("probability_trends", {})
    depth = grid.center_depth()
    if not np.isfinite(depth[active]).all():
        raise ValueError("Grid depths must be finite in active cells.")
    for i, facies in enumerate(config["facies"]):
        trend = trends.get(str(facies["code"]), {})
        result[i] += property_trends.offset(grid, trend, surfaces)
        if trend.get("distance_enabled"):
            surface_name = trend.get("distance_surface", "")
            surface = (surfaces or {}).get(surface_name)
            if surface is None:
                raise ValueError(f"Depth surface '{surface_name}' is missing.")
            x, y = grid.center_xy()
            z = surface.sample(x, y, extrapolate=False)
            if not np.isfinite(z[active.any(axis=0)]).all():
                raise ValueError(f"Depth surface '{surface_name}' does not cover every active grid column.")
            distance = depth - np.where(np.isfinite(z), z, 0)[None]
            result[i] += _curve(distance, trend.get("distance_curve", []), "Surface-distance trend")
    if not np.isfinite(result[:, active]).all():
        raise ValueError("Facies probability offsets must be finite in active cells.")
    result[:, ~active] = 0
    return result


def probabilities(base, offsets):
    adjusted = np.maximum(base + offsets, 0.0)
    total = adjusted.sum(axis=0, keepdims=True)
    if (total <= 0).any():
        raise ValueError("Facies trend offsets leave zero probability at one or more cells.")
    return adjusted / total
