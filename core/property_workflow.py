"""Ordered property jobs using the existing modelling engines and restricted calculator."""
from __future__ import annotations

import ast
from copy import deepcopy
import uuid

import numpy as np

from . import facies as fa, geostat as gs, petrophysics as petro, props as pp, volumetrics as vol

JOB_TYPES = {
    "facies": "Facies model",
    "calculator": "Python calculator",
    "petrophysics": "Petrophysics - domain parameters",
    "stochastic": "Petrophysics - stochastic",
    "saturation": "Water saturation",
}


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


def _execute(job, grid, properties, progress):
    kind = job["type"]
    cfg = deepcopy(job["config"])
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
        values = fa.simulate(grid, cfg, cond=data, progress=progress)
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
            active_values = value[grid.actnum > 0]
            if kind_ == "discrete" and not np.equal(active_values, np.rint(active_values)).all():
                raise PropertyWorkflowError(f"Discrete output '{name}' contains non-integer codes.")
            result[name] = pp.make_property(grid, name, value, kind_, cfg.get("unit", ""), "calculator", code,
                                           legend=previous.legend if previous and kind_ == "discrete" else None)
        return result
    if kind == "petrophysics":
        cfg["rows"] = _active_rows(grid, properties, cfg, cfg["rows"])
        result = petro.model_petrophysics(grid, properties, cfg["domain"], cfg.get("facies", ""), cfg["rows"])
        outputs = cfg.get("outputs", pp.ZONE_PROPS)
        if not outputs or set(outputs) - set(result):
            raise PropertyWorkflowError("Select valid petrophysical outputs.")
        return {n: result[n] for n in outputs}
    if kind == "stochastic":
        if cfg.get("domain", "zone") == "zone_facies":
            for pc in cfg["props"].values():
                pc["facies_rows"] = _active_rows(grid, properties, cfg, pc.get("facies_rows", []), stochastic=True)
        data = {n: _blocked(grid, properties, name) for n, name in cfg.get("cond", {}).items()}
        result = gs.simulate(grid, cfg, progress=progress, cond=data or None, properties=properties)
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
    for index, job in enumerate(selected):
        if job_id is None and not job.get("enabled", True):
            reports.append(dict(job=job["name"], status="Skipped", outputs=[]))
            continue
        try:
            def update(fraction, index=index):
                if progress:
                    progress((index + fraction) / len(selected))
            result = _execute(job, grid, properties, update)
            for name, prop in result.items():
                values = prop.values[grid.actnum > 0]
                if not np.isfinite(values).all():
                    raise PropertyWorkflowError(f"Output '{name}' has non-finite values in active cells.")
                if prop.kind == "discrete" and not np.equal(values, np.rint(values)).all():
                    raise PropertyWorkflowError(f"Discrete output '{name}' contains non-integer codes.")
            properties.update(result)
            reports.append(dict(job=job["name"], status="Completed", outputs=list(result)))
            update(1.0)
        except (pp.CalcError, gs.GeostatError, fa.FaciesError, petro.PetroError, PropertyWorkflowError,
                KeyError, TypeError, ValueError, OverflowError) as exc:
            number = project.property_jobs.index(job) + 1
            raise PropertyWorkflowError(f"Job {number} - {job['name']}: {exc}. No workflow outputs were committed.") from exc
    project.properties = properties
    return reports
