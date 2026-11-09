"""Zone/facies parameter assignment and cell-centre water-saturation models."""
from __future__ import annotations

import numpy as np

from . import props as pp
from . import volumetrics as vol
from . import property_trends as trends

DOMAINS = ["zone", "facies", "zone_facies"]


class PetroError(ValueError):
    pass


def property_values(grid, properties, name: str, discrete: bool = False) -> np.ndarray:
    prop = properties.get(name)
    shape = (grid.nk, grid.nj, grid.ni)
    if prop is None or prop.values.shape != shape:
        raise PetroError(f"Property '{name}' is missing or does not fit the current grid.")
    if prop.stale:
        raise PetroError(f"Property '{name}' is stale. Rebuild it before modelling.")
    values = prop.values.astype(float)
    active = grid.actnum > 0
    if not np.isfinite(values[active]).all():
        raise PetroError(f"Property '{name}' has undefined values in active cells.")
    if discrete and (prop.kind != "discrete" or not np.equal(values[active], np.rint(values[active])).all()):
        raise PetroError(f"Property '{name}' must contain discrete facies codes.")
    return values


def domains(grid, mode: str, properties, facies_name: str = "") -> list[dict]:
    """Enumerate only active modelling domains; zone numbers are 1-based."""
    if mode not in DOMAINS:
        raise PetroError(f"Unknown modelling domain: {mode}")
    active = grid.actnum > 0
    facies = property_values(grid, properties, facies_name, discrete=True) if mode != "zone" else None
    legend = properties[facies_name].legend if facies is not None else {}
    rows = []
    for zi, zone in enumerate(grid.zones):
        mask = active & (grid.layer_zone == zi)[:, None, None]
        if mode == "zone":
            if mask.any():
                rows.append(dict(zone=zi + 1, label=zone.name))
            continue
        for code in np.unique(facies[mask]):
            number = int(code)
            if mode == "facies" and any(row["code"] == number for row in rows):
                continue
            label = str(legend.get(str(number), number))
            row = dict(code=number, label=label)
            if mode == "zone_facies":
                row.update(zone=zi + 1, label=f"{zone.name} / {label}")
            rows.append(row)
    return rows


def parameter_arrays(grid, properties, mode: str, facies_name: str, rows: list[dict], fields: list[str]) -> dict:
    expected = domains(grid, mode, properties, facies_name)
    keys = ["zone"] if mode == "zone" else ["code"] if mode == "facies" else ["zone", "code"]
    expected_keys = {tuple(row[key] for key in keys) for row in expected}
    supplied = [tuple(row.get(key) for key in keys) for row in rows]
    if len(set(supplied)) != len(supplied) or set(supplied) != expected_keys:
        raise PetroError("Parameter rows must match every active zone/facies domain exactly once.")
    active = grid.actnum > 0
    facies = property_values(grid, properties, facies_name, discrete=True) if mode != "zone" else None
    arrays = {field: np.full(active.shape, np.nan) for field in fields}
    for row in rows:
        mask = active.copy()
        if "zone" in keys:
            mask &= (grid.layer_zone == row["zone"] - 1)[:, None, None]
        if "code" in keys:
            mask &= facies == row["code"]
        for field in fields:
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise PetroError(f"{row.get('label', supplied)}: '{field}' must be a number.") from exc
            if not np.isfinite(value):
                raise PetroError(f"{row.get('label', '')}: '{field}' must be finite.")
            arrays[field][mask] = value
    return arrays


def model_petrophysics(grid, properties, mode: str, facies_name: str, rows: list[dict], trend_config=None, surfaces=None) -> dict:
    """Assign PORO, permeability and NTG constants per active domain."""
    fields = ["poro", "permx", "ntg", "kykx", "kvkh"]
    values = parameter_arrays(grid, properties, mode, facies_name, rows, fields)
    active = grid.actnum > 0
    for key in ("poro", "ntg"):
        if ((values[key][active] < 0) | (values[key][active] > 1)).any():
            raise PetroError(f"{key} must be between 0 and 1.")
    for key in ("permx", "kykx", "kvkh"):
        if (values[key][active] < 0).any():
            raise PetroError(f"{key} must be non-negative.")
    try:
        for name, field in (("PORO", "poro"), ("PERM", "permx"), ("NTG", "ntg")):
            values[field] += trends.offset(grid, (trend_config or {}).get(name, {}), surfaces)
            values[field] = np.clip(values[field], 0, np.inf if name == "PERM" else 1)
    except trends.TrendError as exc:
        raise PetroError(str(exc)) from exc
    with np.errstate(over="ignore"):
        outputs = dict(PORO=values["poro"], PERMX=values["permx"],
                       PERMY=values["permx"] * values["kykx"], PERMZ=values["permx"] * values["kvkh"],
                       NTG=values["ntg"])
    if any(not np.isfinite(value[active]).all() or (np.abs(value[active]) > np.finfo(np.float32).max).any()
           for value in outputs.values()):
        raise PetroError("Petrophysical parameters produce values outside the supported range.")
    return {name: pp.make_property(grid, name, value, unit="mD" if name.startswith("PERM") else "frac",
                                   source="petrophysics", expr=f"assignment by {mode}" + (" with spatial trends" if trend_config else ""))
            for name, value in outputs.items()}


def model_saturation(grid, properties, cfg: dict, contacts: dict) -> np.ndarray:
    """Return SW in [0, 1] on active cells; inactive cells are undefined."""
    method = cfg["method"]
    fields = ["swirr", "entry", "lam"] if method == "satheight" else ["a", "m", "n", "rw"]
    if method not in ("satheight", "archie"):
        raise PetroError(f"Unknown saturation method: {method}")
    params = parameter_arrays(grid, properties, cfg["domain"], cfg.get("facies", ""), cfg["rows"], fields)
    active = grid.actnum > 0
    if any((params[key][active] <= 0).any() for key in fields if key != "swirr"):
        raise PetroError("Saturation-height entry/lambda and Archie a/m/n/Rw must be positive.")
    if method == "satheight":
        if ((params["swirr"][active] < 0) | (params["swirr"][active] > 1)).any():
            raise PetroError("Irreducible water saturation must be between 0 and 1.")
        try:
            owc, goc, fwl = vol.contact_cubes(grid, contacts, properties)
        except vol.VolError as exc:
            raise PetroError(str(exc)) from exc
        depth = grid.center_depth()
        if not np.isfinite(fwl[active]).all() or not np.isfinite(depth[active]).all():
            raise PetroError("Free-water level and cell-centre depths must be finite.")
        if (np.isinf(goc[active])).any() or (np.isfinite(goc[active]) & (goc[active] > owc[active])).any():
            raise PetroError("GOC must be finite where defined and shallower than OWC.")
        height = np.maximum(fwl - depth, 0.0)
        sw = vol.saturation_height(height, params["swirr"], params["entry"], params["lam"])
        if cfg.get("gas_curve", False) and contacts["contacts"].get("fluid_system", "auto") not in ("gas", "oil"):
            gas_params = parameter_arrays(grid, properties, cfg["domain"], cfg.get("facies", ""), cfg["rows"],
                                          ["gas_swirr", "gas_entry", "gas_lam"])
            if ((gas_params["gas_swirr"][active] < 0) | (gas_params["gas_swirr"][active] > 1)).any():
                raise PetroError("Gas irreducible water saturation must be between 0 and 1.")
            if (gas_params["gas_entry"][active] <= 0).any() or (gas_params["gas_lam"][active] <= 0).any():
                raise PetroError("Gas saturation-height entry/lambda must be positive.")
            if not np.isfinite(goc[active]).any():
                raise PetroError("Define GOC before enabling a separate gas-zone saturation curve.")
            gas_sw = vol.saturation_height(height, gas_params["gas_swirr"], gas_params["gas_entry"], gas_params["gas_lam"])
            sw = np.where(active & np.isfinite(goc) & (depth < goc), gas_sw, sw)
    else:
        phi = property_values(grid, properties, cfg["poro"])
        rt = property_values(grid, properties, cfg["rt"])
        if ((phi[active] <= 0) | (phi[active] > 1)).any() or (rt[active] <= 0).any():
            raise PetroError("Archie requires porosity in (0, 1] and positive formation resistivity Rt (ohm.m).")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            logsw = (np.log(params["a"]) + np.log(params["rw"]) - params["m"] * np.log(phi) - np.log(rt)) / params["n"]
            sw = np.exp(np.minimum(logsw, 0.0))
    if not np.isfinite(sw[active]).all():
        raise PetroError("Saturation model produced non-finite values.")
    return np.where(active, np.clip(sw, 0.0, 1.0), np.nan)
