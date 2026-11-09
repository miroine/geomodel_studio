"""Ordered property jobs using the existing modelling engines and restricted calculator."""
from __future__ import annotations

import ast
from copy import deepcopy
import uuid

import numpy as np

from . import facies as fa, geostat as gs, petrophysics as petro, props as pp, volumetrics as vol, polygon_property, property_history

JOB_TYPES = {
    "facies": "Facies model",
    "calculator": "Python calculator",
    "polygon": "Polygon property assignment",
    "petrophysics": "Petrophysics - domain assignments",
    "stochastic": "Petrophysics - stochastic",
    "saturation": "Water saturation",
    "tool": "Property tool",
}

HISTORY_TYPES = {
    "Facies model": "facies", "Python calculator": "calculator",
    "Polygon property assignment": "polygon", "Domain assignments": "petrophysics",
    "Stochastic property modelling": "stochastic", "Water saturation": "saturation",
}
TOOL_RUNS = ("Zone table properties", "Generate geometric properties", "Constant property",
             "Plane properties", "Contact properties", "Fault-block region and segments",
             "Block well logs", "Simple kriging", "Petrophysics from facies", "Recompute stale properties")


def job_from_history(name, settings, outputs, existing=()):
    """Convert recorded settings into an independent executable step."""
    kind = HISTORY_TYPES.get(name, "tool" if name in TOOL_RUNS else None)
    if kind is None:
        return None
    cfg = deepcopy(settings)
    if kind == "calculator":
        cfg["result_kind"] = cfg.pop("kind", cfg.get("result_kind", "continuous"))
    if kind == "petrophysics":
        cfg["outputs"] = list(outputs)
    if kind == "tool":
        if name == "Recompute stale properties":
            cfg["outputs"] = list(outputs)
        cfg = dict(operation=name, settings=cfg)
    names = {j["name"] for j in existing}
    label, suffix = name, 2
    while label in names:
        label = f"{name} {suffix}"
        suffix += 1
    return dict(id=uuid.uuid4().hex[:12], type=kind, name=label, enabled=True, config=cfg)


def restore_history(project):
    """Append completed, unlinked historical runs once, in execution order."""
    added = 0
    for entry in project.property_history:
        if entry["status"] != "Completed" or entry.get("job_id"):
            continue
        if entry.get("crs") and any(entry["crs"].get(k) != project.crs.get(k)
                                    for k in ("epsg", "xy_unit", "z_unit")):
            raise PropertyWorkflowError("Historical CRS/units differ from the project. Restore in the original CRS/units first.")
        if job_from_history(entry["name"], entry["settings"], entry["outputs"]) is None:
            raise PropertyWorkflowError(f"History entry '{entry['name']}' has no executable configuration.")
    for entry in project.property_history:
        if entry["status"] == "Completed" and not entry.get("job_id"):
            job = job_from_history(entry["name"], entry["settings"], entry["outputs"], project.property_jobs)
            project.property_jobs.append(job)
            entry["job_id"] = job["id"]
            added += 1
    return added


class PropertyWorkflowError(ValueError):
    pass


def new_job(kind, project):
    if kind not in JOB_TYPES:
        raise PropertyWorkflowError(f"Unknown property job: {kind}")
    grid = project.grid
    if grid is None:
        raise PropertyWorkflowError("Build the grid before configuring property jobs.")
    cfg = {}
    if kind == "facies":
        cfg = deepcopy(project.facies or fa.default_config(grid))
        cfg["output"] = "FACIES"
    elif kind == "calculator":
        cfg = dict(code="FACIES_COPY = FACIES", output="RESULT", result_kind="discrete", unit="")
    elif kind == "polygon":
        cfg = dict(output="PORO", polygon=next(iter(project.polygons), ""), mode="both",
                   inside=0.2, outside=0.1, kind="continuous", unit="")
    elif kind == "stochastic":
        cfg = deepcopy(project.stochastic or gs.default_config(grid))
    elif kind == "petrophysics":
        candidates = [v for k, v in project.property_models.items() if k.startswith("petrophysics|")]
        cfg = deepcopy(candidates[-1]) if candidates else dict(domain="zone", facies="", rows=[
            dict(zone=i + 1, label=z.name, poro=z.poro, permx=z.permx, ntg=z.ntg, kykx=1.0, kvkh=z.kvkh)
            for i, z in enumerate(grid.zones)])
        cfg["outputs"] = list(pp.ZONE_PROPS)
    elif kind == "saturation":
        candidates = [v for v in project.property_models.values() if v.get("method") in ("satheight", "archie")]
        cfg = deepcopy(candidates[-1]) if candidates else dict(method="satheight", domain="zone", facies="", output="SW",
            rows=[dict(zone=i + 1, label=z.name, swirr=0.2, entry=2.0, lam=0.5) for i, z in enumerate(grid.zones)])
        cfg["contacts"] = deepcopy(project.volumetrics or vol.default_config(grid))
    elif kind == "tool":
        cfg = dict(operation="Constant property", settings=dict(name="CONSTANT", value=0.2, kind="continuous", unit=""))
    names = {j["name"] for j in project.property_jobs}
    name, suffix = JOB_TYPES[kind], 2
    while name in names:
        name = f"{JOB_TYPES[kind]} {suffix}"
        suffix += 1
    if kind == "facies":
        outputs = set(project.properties) | {j["config"].get("output", "FACIES") for j in project.property_jobs if j["type"] == "facies"}
        output, suffix = cfg["output"], 2
        while output in outputs:
            output = f"{cfg['output']}_{suffix}"
            suffix += 1
        cfg["output"] = output
    return dict(id=uuid.uuid4().hex[:12], type=kind, name=name, enabled=True, config=cfg)


def _name(value):
    if not isinstance(value, str) or not value.isidentifier() or value.startswith("_") or value.upper() in pp.GEOMETRIC:
        raise PropertyWorkflowError(f"Invalid output property name: {value!r}")
    return value


def _active_rows(grid, properties, cfg, rows, stochastic=False):
    mode = cfg.get("domain", "zone")
    domains = petro.domains(grid, mode, properties, cfg.get("facies", ""))
    keys = ["zone"] if mode == "zone" else ["code"] if mode == "facies" else ["zone", "code"]
    expected = set()
    for domain in domains:
        values = dict(domain)
        if stochastic:
            values["zone"] = grid.zones[domain["zone"] - 1].name
        expected.add(tuple(values[k] for k in keys))
    supplied = [tuple(row.get(k) for k in keys) for row in rows]
    if len(supplied) != len(set(supplied)):
        raise PropertyWorkflowError("Duplicate parameter domains. Define each zone/facies combination once.")
    if not expected.issubset(set(supplied)):
        raise PropertyWorkflowError("Missing parameter rows for active zone/facies domains. Configure rows for any new calculator facies codes.")
    return [row for row, key in zip(rows, supplied) if key in expected]


def _blocked(grid, properties, name):
    prop = properties.get(name)
    if prop is None or prop.stale or prop.values.shape != grid.actnum.shape:
        raise PropertyWorkflowError(f"Conditioning property '{name}' is missing, stale or does not fit the grid.")
    if np.isinf(prop.values).any():
        raise PropertyWorkflowError(f"Conditioning property '{name}' contains infinite values.")
    return prop.values


def _tool(cfg, grid, properties, project, progress):
    from copy import copy
    from . import regions, logs, units
    operation, settings = cfg["operation"], cfg["settings"]
    if operation == "Constant property":
        name = _name(settings["name"])
        return {name: pp.make_property(grid, name, settings["value"], settings["kind"], settings["unit"], "manual")}
    if operation == "Generate geometric properties":
        return pp.geometry_properties(grid, settings["properties"])
    if operation == "Zone table properties":
        from .cpgrid import ZoneSpec
        snapshot = copy(grid)
        snapshot.zones = [ZoneSpec.from_dict(row) for row in settings["zones"]]
        if [z.name for z in snapshot.zones] != [z.name for z in grid.zones]:
            raise PropertyWorkflowError("Saved zone table does not match the current grid zones.")
        return pp.zone_defaults(snapshot)
    if operation == "Plane properties":
        return regions.plane_properties(grid, settings["planes"], settings["depth_unit"])
    if operation == "Contact properties":
        return regions.contact_properties(grid, settings["volumetrics"], units.z(), properties)
    if operation == "Fault-block region and segments":
        fluid = None
        if settings["mode"].endswith("fluid"):
            fluid = petro.property_values(grid, properties, "FLUID") if "FLUID" in properties else vol.fluid_array(
                grid, settings["volumetrics"], props=properties)
        return regions.region_segment(grid, settings["mode"], fluid)
    if operation == "Block well logs":
        if project is None:
            raise PropertyWorkflowError("Well/log inputs are unavailable.")
        names = settings.get("wells")
        if names and any(n not in project.wells or n not in project.logs for n in names):
            raise PropertyWorkflowError("A saved blocking well or its logs are missing.")
        values, info = logs.block_wells(grid, project.wells, project.logs, settings["curve"],
                                       settings["discrete"], settings["average"], names)
        if not info["cells"]:
            raise PropertyWorkflowError("No log sample falls in an active cell.")
        name = _name(settings["output"])
        unit = project.logs[info["wells"][0]]["units"].get(settings["curve"], "")
        return {name: pp.make_property(grid, name, values, "discrete" if settings["discrete"] else "continuous",
                                      unit, "blocked wells", f"{settings['curve']} blocked ({settings['average']})")}
    if operation == "Simple kriging":
        values = _blocked(grid, properties, settings["input"])
        estimates = gs.krige_property(grid, values, settings["variogram"],
                                      gs.rel_angle(settings["azimuth"], grid.angle), True,
                                      settings["neighbours"], settings["normal_score"], progress=progress)
        name = _name(settings["output"])
        return {name: pp.make_property(grid, name, estimates, unit=properties[settings["input"]].unit, source="kriging")}
    if operation == "Petrophysics from facies":
        values = petro.property_values(grid, properties, settings["input_facies"])
        result = fa.petrophysics(grid, values, settings)
        return {n: pp.make_property(grid, n, r["values"], r["kind"], r["unit"], "facies",
                                    f"from facies {settings['input_facies']}") for n, r in result.items()}
    if operation == "Recompute stale properties":
        result = {}
        for name in settings.get("outputs", settings["requested"]):
            if name not in properties:
                raise PropertyWorkflowError(f"Refresh input '{name}' is missing.")
            prop = deepcopy(properties[name])
            if prop.source == "geometry":
                result.update(pp.geometry_properties(grid, [name]))
            elif prop.source == "zones":
                result[name] = pp.zone_defaults(grid)[name]
            elif prop.source == "calculator":
                values = pp.run_calculator(prop.expr, grid, properties | result, name)
                result.update({n: pp.make_property(grid, n, v, prop.kind, prop.unit, "calculator", prop.expr)
                               for n, v in values.items()})
            elif prop.source in ("manual", "import"):
                prop.stale, prop.geom_hash = False, pp.grid_hash(grid)
                result[name] = prop
            else:
                raise PropertyWorkflowError(f"Rerun the original modelling step for '{name}'.")
        return result
    raise PropertyWorkflowError(f"Unknown property tool: {operation}")


def _execute(job, grid, properties, progress, surfaces=None, polygons=None, project=None):
    kind = job["type"]
    cfg = deepcopy(job["config"])
    if kind == "tool":
        return _tool(cfg, grid, properties, project, progress)
    if kind == "polygon":
        result = polygon_property.assign(grid, properties, (polygons or {}).get(cfg.get("polygon")), cfg)
        return {result.name: result}
    if kind == "facies":
        output = _name(cfg.get("output", "FACIES"))
        codes = np.asarray([f["code"] for f in cfg["facies"]], float)
        if not np.isfinite(codes).all() or not np.equal(codes, np.rint(codes)).all():
            raise PropertyWorkflowError("Facies codes must be finite integers.")
        if not all(str(f["name"]).strip() for f in cfg["facies"]):
            raise PropertyWorkflowError("Give every facies a name.")
        if {z["zone"] for z in cfg["zones"]} != {z.name for z in grid.zones}:
            raise PropertyWorkflowError("Facies job zones do not match the current grid. Update the configuration.")
        errs = fa.check_config(cfg, grid)
        if errs:
            raise PropertyWorkflowError(" ".join(errs))
        data = _blocked(grid, properties, cfg["cond"]) if cfg.get("cond") else None
        values = fa.simulate(grid, cfg, cond=data, progress=progress, surfaces=surfaces)
        values = np.where(grid.actnum > 0, values, np.nan)
        return {output: pp.make_property(grid, output, values, "discrete", source="facies",
                                        expr=f"workflow facies ({cfg['method']})", legend=fa.legend(cfg))}
    if kind == "calculator":
        code = cfg.get("code", "")
        try:
            references = {node.id for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        except SyntaxError as exc:
            raise PropertyWorkflowError(f"Calculator syntax error on line {exc.lineno}: {exc.msg}") from exc
        for name in references & properties.keys():
            prop = properties[name]
            if prop.stale or prop.values.shape != grid.actnum.shape:
                raise PropertyWorkflowError(f"Calculator input '{name}' is stale or does not fit the grid.")
        values = pp.run_calculator(code, grid, properties, cfg.get("output", "RESULT"))
        result = {}
        for name, value in values.items():
            _name(name)
            previous = properties.get(name)
            kind_ = cfg.get("result_kind", "continuous")
            metadata = cfg.get("output_metadata", {}).get(name, {})
            kind_ = metadata.get("kind", kind_)
            active_values = value[grid.actnum > 0]
            if kind_ == "discrete" and not np.equal(active_values, np.rint(active_values)).all():
                raise PropertyWorkflowError(f"Discrete output '{name}' contains non-integer codes.")
            result[name] = pp.make_property(grid, name, value, kind_, metadata.get("unit", cfg.get("unit", "")), "calculator", code,
                                           legend=previous.legend if previous and kind_ == "discrete" else None)
        return result
    if kind == "petrophysics":
        cfg["rows"] = _active_rows(grid, properties, cfg, cfg["rows"])
        result = petro.model_petrophysics(grid, properties, cfg["domain"], cfg.get("facies", ""), cfg["rows"],
                                         cfg.get("trends"), surfaces)
        outputs = cfg.get("outputs", pp.ZONE_PROPS)
        if not outputs or set(outputs) - set(result):
            raise PropertyWorkflowError("Select valid petrophysical outputs.")
        return {n: result[n] for n in outputs}
    if kind == "stochastic":
        if cfg.get("domain", "zone") == "zone_facies":
            for pc in cfg["props"].values():
                pc["facies_rows"] = _active_rows(grid, properties, cfg, pc.get("facies_rows", []), stochastic=True)
        data = {n: _blocked(grid, properties, name) for n, name in cfg.get("cond", {}).items()}
        result = gs.simulate(grid, cfg, progress=progress, cond=data or None, properties=properties, surfaces=surfaces)
        return {n: pp.make_property(grid, n, r["values"], r["kind"], r["unit"], "stochastic",
                                   f"workflow stochastic by {cfg.get('domain', 'zone')}") for n, r in result.items()}
    if kind == "saturation":
        output = _name(cfg.get("output", "SW"))
        if cfg["method"] == "archie" and (cfg.get("poro") == cfg.get("rt") or output in (cfg.get("poro"), cfg.get("rt"))):
            raise PropertyWorkflowError("Archie requires distinct porosity, resistivity and output properties.")
        cfg["rows"] = _active_rows(grid, properties, cfg, cfg["rows"])
        values = petro.model_saturation(grid, properties, cfg, cfg["contacts"])
        return {output: pp.make_property(grid, output, values, unit="frac", source="saturation",
                                        expr=f"workflow {cfg['method']} by {cfg['domain']}")}
    raise PropertyWorkflowError(f"Unknown property job: {kind}")


def run(project, progress=None, job_id=None):
    """Run enabled workflow jobs, or one explicitly selected job using stored inputs."""
    grid = project.grid
    if grid is None:
        raise PropertyWorkflowError("Build the grid before running the property workflow.")
    selected = project.property_jobs
    if job_id is not None:
        selected = [job for job in selected if job["id"] == job_id]
        if len(selected) != 1:
            raise PropertyWorkflowError("The selected property job does not exist or has a duplicate ID.")
    active = [job for job in selected if job_id is not None or job.get("enabled", True)]
    if not active:
        raise PropertyWorkflowError("Activate at least one job.")
    properties = dict(project.properties)
    reports = []
    pending = []
    for index, job in enumerate(selected):
        if job_id is None and not job.get("enabled", True):
            reports.append(dict(job=job["name"], status="Skipped", outputs=[]))
            continue
        try:
            def update(fraction, index=index):
                if progress:
                    progress((index + fraction) / len(selected))
            result = _execute(job, grid, properties, update, project.surfaces, project.polygons, project)
            for name, prop in result.items():
                values = prop.values[grid.actnum > 0]
                sparse = prop.source == "blocked wells" or (
                    job["type"] == "tool" and job["config"]["operation"] == "Contact properties")
                if np.isinf(values).any() or (not sparse and not np.isfinite(values).all()):
                    raise PropertyWorkflowError(f"Output '{name}' has non-finite values in active cells.")
                finite = values[np.isfinite(values)]
                if prop.kind == "discrete" and not np.equal(finite, np.rint(finite)).all():
                    raise PropertyWorkflowError(f"Discrete output '{name}' contains non-integer codes.")
            properties.update(result)
            pending.append((job, list(result)))
            reports.append(dict(job=job["name"], status="Completed", outputs=list(result)))
            update(1.0)
        except (pp.CalcError, gs.GeostatError, fa.FaciesError, petro.PetroError, PropertyWorkflowError,
                KeyError, TypeError, ValueError, OverflowError) as exc:
            for attempted, outputs in pending:
                property_history.record(project, attempted["name"], attempted["config"], outputs,
                                        status="Rolled back", message="A later workflow job failed.", job_id=attempted["id"])
            property_history.record(project, job["name"], job["config"], [], status="Failed", message=str(exc), job_id=job["id"])
            number = project.property_jobs.index(job) + 1
            raise PropertyWorkflowError(f"Job {number} - {job['name']}: {exc}. No workflow outputs were committed.") from exc
    project.properties = properties
    for job, outputs in pending:
        property_history.record(project, job["name"], job["config"], outputs, job_id=job["id"])
    return reports
