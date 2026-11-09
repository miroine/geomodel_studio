"""Assign grid property values using a polygon in map view."""
import numpy as np

from . import polygons, props


def assign(grid, properties, polygon, config):
    """Create or edit a property snapshot; polygon edges count as inside."""
    name = config.get("output", "")
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("_") or name.upper() in props.GEOMETRIC:
        raise ValueError(f"Invalid output property name: {name!r}")
    mode = config.get("mode")
    if mode not in ("inside", "outside", "both"):
        raise ValueError("Choose inside, outside, or both sides of the polygon.")
    if polygon is None:
        raise ValueError("The selected polygon is missing. Choose an existing polygon.")
    points = np.asarray(polygon.pts, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError("The polygon must have at least three finite XY vertices.")
    centered = points - points[0]
    area = np.dot(centered[:, 0], np.roll(centered[:, 1], -1)) - np.dot(centered[:, 1], np.roll(centered[:, 0], -1))
    if not np.isfinite(area) or abs(area) == 0:
        raise ValueError("The polygon must enclose a non-zero area.")

    previous = properties.get(name)
    if previous is None and mode != "both":
        raise ValueError("A one-sided assignment requires an existing property to preserve the other side.")
    if previous is not None and (previous.stale or previous.values.shape != grid.actnum.shape):
        raise ValueError(f"Property '{name}' is stale or does not fit the grid.")
    kind = previous.kind if previous is not None else config.get("kind", "continuous")
    unit = previous.unit if previous is not None else config.get("unit", "")
    if kind not in props.KINDS:
        raise ValueError("Property type must be continuous or discrete.")
    values = {}
    for side in ("inside", "outside") if mode == "both" else (mode,):
        value = float(config[side])
        if not np.isfinite(value) or abs(value) > np.finfo(np.float32).max:
            raise ValueError(f"The {side} value must be finite and fit in a property array.")
        if kind == "discrete" and value != np.rint(value):
            raise ValueError(f"The {side} value must be an integer for a discrete property.")
        if kind == "discrete" and float(np.float32(value)) != value:
            raise ValueError(f"The {side} integer cannot be represented exactly in a property array.")
        values[side] = value
    x, y = grid.center_xy()
    extent = max(float(np.ptp(points[:, 0])), float(np.ptp(points[:, 1])), 1.0)
    inside = polygons.mask_points(x, y, polygon) | (polygons.distance_to_boundary(x, y, points) <= extent * 1e-10)
    active = grid.actnum > 0
    result = previous.values.copy() if previous is not None else np.full(active.shape, np.nan, dtype=np.float32)
    for side, value in values.items():
        mask = inside if side == "inside" else ~inside
        result[active & mask[None, :, :]] = value
    if not np.isfinite(result[active]).all():
        raise ValueError("The result contains undefined or non-finite active cells; fill them before assignment.")
    return props.make_property(grid, name, result, kind, unit, "polygon",
                               f"polygon assignment: {polygon.name} ({mode})",
                               legend=previous.legend if previous is not None else None)
