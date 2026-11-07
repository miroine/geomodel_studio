"""Editable, ordered property jobs with the same card-based navigation as structural tasks."""
from copy import deepcopy
from html import escape
import json
import hashlib

import numpy as np
import pandas as pd
import streamlit as st

from core import facies as fa, geostat as gs, props as pp, property_workflow as jobs, units as un
from ui import state as S
from views import facies_objects
from views import contact_settings

STYLES = {"facies": "layering", "calculator": "refinement", "petrophysics": "construction",
          "stochastic": "conditioning", "saturation": "faults"}
DOMAIN_LABELS = {"zone": "By zone", "facies": "By facies", "zone_facies": "By zone and facies"}


def _select(label, options, current, key):
    return st.selectbox(label, options, index=options.index(current) if current in options else 0, key=key)


def _records(rows, key, disabled=(), dynamic=False):
    return st.data_editor(pd.DataFrame(rows), key=key, hide_index=True, disabled=list(disabled),
                          num_rows="dynamic" if dynamic else "fixed").to_dict("records")


def _codes(project, source, before):
    codes = {}
    prop = project.properties.get(source)
    if prop is not None and not prop.stale and prop.values.shape == project.grid.actnum.shape:
        for code in np.unique(prop.values[(project.grid.actnum > 0) & np.isfinite(prop.values)]):
            if code == int(code):
                codes[int(code)] = prop.legend.get(str(int(code)), str(int(code)))
    for job in project.property_jobs[:before]:
        if job.get("enabled", True) and job["type"] == "facies" and job["config"].get("output", "FACIES") == source:
            codes = {int(f["code"]): f["name"] for f in job["config"]["facies"]}
    return codes


def _domain(cfg, project, before, key, stochastic=False):
    modes = ["zone", "zone_facies"] if stochastic else list(DOMAIN_LABELS)
    cfg["domain"] = st.radio("Parameter domains", modes, index=modes.index(cfg.get("domain", "zone")),
                            format_func=DOMAIN_LABELS.get, horizontal=True, key=key("domain"))
    if cfg["domain"] != "zone":
        cfg["facies"] = st.text_input("Input facies property", cfg.get("facies") or "FACIES", key=key("facies"))
        st.caption("This may be an output of an earlier facies or calculator job. Add rows for new calculator codes before running.")
    codes = _codes(project, cfg.get("facies", ""), before)
    specs = []
    if cfg["domain"] == "facies":
        specs = [dict(code=c, label=n) for c, n in codes.items()]
    else:
        for index, zone in enumerate(project.grid.zones):
            if cfg["domain"] == "zone":
                specs.append(dict(zone=index + 1, label=zone.name))
            else:
                specs.extend(dict(zone=index + 1, code=c, label=f"{zone.name} / {n}") for c, n in codes.items())
    return specs


def _parameter_table(cfg, specs, defaults, key):
    keys = ["zone"] if cfg["domain"] == "zone" else ["code"] if cfg["domain"] == "facies" else ["zone", "code"]
    saved = {tuple(r.get(k) for k in keys): r for r in cfg.get("rows", [])}
    rows = [dict(spec, **defaults(spec)) | saved.get(tuple(spec[k] for k in keys), {}) for spec in specs]
    expected = {tuple(r[k] for k in keys) for r in specs}
    rows += [r for k, r in saved.items() if k not in expected and None not in k]
    if not rows:
        st.warning("No input facies codes are known yet. Configure the earlier facies job or supply parameter rows.")
        rows = [dict(zone=1, code=1, label="Facies 1", **defaults(dict(zone=1, code=1)))]
    cfg["rows"] = _records(rows, key, dynamic=True)


def _facies(cfg, project, key):
    grid = project.grid
    cfg["output"] = st.text_input("Facies output", cfg.get("output", "FACIES"), key=key("output"))
    cfg["method"] = _select("Facies method", ["truncated_gaussian", "plurigaussian", "indicator", "objects"],
                            cfg["method"], key("method"))
    cfg["seed"] = int(st.number_input("Random seed", 0, 10_000_000, int(cfg["seed"]), key=key("seed")))
    nf = int(st.number_input("Number of facies", 2, 8, len(cfg["facies"]), key=key("nf")))
    if nf != len(cfg["facies"]):
        output, method, seed = cfg["output"], cfg["method"], cfg["seed"]
        cfg.update(fa.default_config(grid, nf), output=output, method=method, seed=seed)
    st.markdown("**Facies definitions**")
    cfg["facies"] = _records(cfg["facies"], key("definitions", [nf]))
    raw_codes = np.asarray([f["code"] for f in cfg["facies"]], float)
    if not np.isfinite(raw_codes).all() or not np.equal(raw_codes, np.rint(raw_codes)).all():
        raise ValueError("Facies codes must be finite integers.")
    codes = [int(f["code"]) for f in cfg["facies"]]
    cfg["trend"] = st.checkbox("Vertical proportion trend", bool(cfg["trend"]), key=key("trend"),
                               disabled=cfg["method"] in ("objects", "plurigaussian"))
    cfg["vol_weight"] = st.checkbox("Volume-weighted proportions", bool(cfg.get("vol_weight", True)), key=key("weights"))
    st.markdown("**Zone proportions and variograms**")
    default_zones = fa.default_config(grid, nf)["zones"]
    old = {z["zone"]: z for z in cfg["zones"]}
    rows = []
    for zone in default_zones:
        row = deepcopy(old.get(zone["zone"], zone))
        top, base = row.pop("top"), row.pop("base")
        row.update({f"top_{c}": top[i] for i, c in enumerate(codes)})
        row.update({f"base_{c}": base[i] for i, c in enumerate(codes)})
        rows.append(row)
    edited = _records(rows, key("zones", codes), disabled=["zone"])
    cfg["zones"] = []
    for row in edited:
        top = [float(row.pop(f"top_{c}")) for c in codes]
        base = [float(row.pop(f"base_{c}")) for c in codes]
        cfg["zones"].append(dict(row, top=top, base=base if cfg["trend"] else top.copy()))
    st.caption(f"top_CODE/base_CODE are facies proportions. Ranges: major/minor in {un.xy()}, vert in {un.z()}.")
    if cfg["method"] == "plurigaussian":
        n1 = int(st.number_input("G1 bands", 1, 6, len(cfg["rule"]), key=key("bands1")))
        n2 = int(st.number_input("G2 bands", 1, 6, len(cfg["rule"][0]), key=key("bands2")))
        rule = [[cfg["rule"][i][j] if i < len(cfg["rule"]) and j < len(cfg["rule"][i]) else codes[0]
                 for j in range(n2)] for i in range(n1)]
        cfg["rule"] = [[int(x) for x in row] for row in st.data_editor(pd.DataFrame(rule), key=key("rule", [n1, n2, codes])).values.tolist()]
    if cfg["method"] == "objects":
        cfg["background"] = _select("Background code", codes, cfg["background"], key("background", codes))
        facies_objects.render(cfg, project, key)
        cfg["azimuth_sd"] = float(st.number_input("Object azimuth scatter", 0.0, 90.0, float(cfg["azimuth_sd"]), key=key("scatter")))
    if cfg["method"] in ("indicator", "truncated_gaussian"):
        cfg["cond"] = st.text_input("Blocked facies log (optional)", cfg.get("cond", ""), key=key("cond"))
    else:
        cfg["cond"] = ""


def _stochastic(cfg, project, before, key):
    specs = _domain(cfg, project, before, key, stochastic=True)
    cfg["seed"] = int(st.number_input("Random seed", 0, 10_000_000, int(cfg["seed"]), key=key("seed")))
    cfg["nreal"] = int(st.number_input("Realisations", 1, 10, int(cfg["nreal"]), key=key("nreal")))
    cfg["perm_mode"] = _select("Permeability mode", ["field", "transform"], cfg["perm_mode"], key("perm_mode"))
    cfg["kykx"] = float(st.number_input("PERMY / PERMX", 0.01, 100.0, float(cfg["kykx"]), key=key("kykx")))
    cfg["use_kvkh"] = st.checkbox("Use zone KV/KH for PERMZ", bool(cfg["use_kvkh"]), key=key("kvkh"))
    if cfg["perm_mode"] == "transform":
        cfg["transform"] = _records([cfg["transform"]], key("transform"))[0]
    row_key = "facies_rows" if cfg["domain"] == "zone_facies" else "rows"
    default = gs.default_config(project.grid)
    for name in gs.PROPS:
        pc = cfg["props"][name]
        st.markdown(f"**{name}: histogram and variogram**")
        pc["enabled"] = st.checkbox(f"Simulate {name}", bool(pc["enabled"]), key=key(name + "_enabled"))
        pc["dist"] = _select(f"{name} distribution", gs.DISTS, pc["dist"], key(name + "_dist"))
        st.caption("p1/p2/p3: " + ", ".join(v for v in gs.DIST_PARAMS[pc["dist"]] if v))
        if row_key == "facies_rows":
            source_changed = pc.get("facies_source") != cfg["facies"]
            saved = {(r["zone"], r["code"]): r for r in pc.get("facies_rows", [])} if not source_changed else {}
            rows = []
            for spec in specs:
                zone = project.grid.zones[spec["zone"] - 1].name
                base = next((r for r in pc["rows"] if r["zone"] == zone),
                            default["props"][name]["rows"][spec["zone"] - 1])
                rows.append(dict(base, code=spec["code"], facies=spec["label"]) | saved.get((zone, spec["code"]), {}))
            present = {(r["zone"], r["code"]) for r in rows}
            rows += [r for k, r in saved.items() if k not in present]
            if not rows:
                rows = [dict(default["props"][name]["rows"][0], code=1, facies="Facies 1")]
            pc["facies_source"] = cfg["facies"]
        else:
            old = {r["zone"]: r for r in pc["rows"]}
            rows = [old.get(z["zone"], z) for z in default["props"][name]["rows"]]
        pc[row_key] = _records(rows, key(name + "_rows", [cfg["domain"], cfg.get("facies"), pc["dist"]]), dynamic=row_key == "facies_rows")
        if pc["dist"] == "histogram":
            bins = pc.get("bins") or [[0.0, 1.0, 1.0]]
            pc["bins"] = st.data_editor(pd.DataFrame(bins, columns=["lower", "upper", "weight"]),
                                        key=key(name + "_bins"), num_rows="dynamic").values.tolist()
        elif pc["dist"] == "values":
            pc["values"] = gs.parse_values(st.text_area(f"{name} target values", ", ".join(map(str, pc["values"])), key=key(name + "_values")))
    st.markdown("**Normal-score correlations and net cut-offs**")
    cfg["corr"] = _records([cfg["corr"]], key("correlations"))[0]
    cfg["cut"] = _records([cfg["cut"]], key("cutoffs"))[0]
    for name in gs.PROPS:
        value = st.text_input(f"{name} blocked-well input (optional)", cfg.get("cond", {}).get(name, ""), key=key(name + "_cond"))
        if value:
            cfg.setdefault("cond", {})[name] = value
        else:
            cfg.setdefault("cond", {}).pop(name, None)


def _configure(job, project, before, namespace="pj"):
    if job["type"] == "facies":
        fa.normalise(job["config"], project.grid)
    cfg = deepcopy(job["config"])
    revision = hashlib.md5(json.dumps([job["name"], cfg], sort_keys=True).encode()).hexdigest()[:8]
    key = lambda field, opts=None: S.k(f"{namespace}_{job['id']}_{field}_{revision}", opts)
    name = st.text_input("Job name", job["name"], key=key("name"))
    kind = job["type"]
    if kind == "calculator":
        st.caption("Restricted Python, identical to the existing calculator. Assignments create/overwrite arrays; imports and arbitrary Python execution are not allowed.")
        cfg["code"] = st.text_area("Python script", cfg["code"], height=180, key=key("code"))
        cfg["output"] = st.text_input("Output name (single expressions)", cfg.get("output", "RESULT"), key=key("output"))
        cfg["result_kind"] = _select("Result type", pp.KINDS, cfg.get("result_kind", "continuous"), key("kind"))
        cfg["unit"] = st.text_input("Unit", cfg.get("unit", ""), key=key("unit"))
        st.caption("Examples: FACIES = where(FACIES == 2, 3, FACIES)  |  PORO = where(FACIES == 3, 0.25, 0.08)")
    elif kind == "facies":
        _facies(cfg, project, key)
    elif kind == "stochastic":
        _stochastic(cfg, project, before, key)
    else:
        if kind == "saturation":
            cfg["method"] = _select("Saturation model", ["satheight", "archie"], cfg["method"], key("method"))
            cfg["output"] = st.text_input("Saturation output", cfg.get("output", "SW"), key=key("output"))
            if cfg["method"] == "archie":
                cfg["poro"] = st.text_input("Porosity input (fraction)", cfg.get("poro", "PORO"), key=key("poro"))
                cfg["rt"] = st.text_input("Resistivity input (ohm.m)", cfg.get("rt", "RT"), key=key("rt"))
            else:
                contact_settings.render(cfg["contacts"]["contacts"], project, key)
                cfg["gas_curve"] = st.checkbox("Separate gas-zone saturation-height parameters",
                                               value=bool(cfg.get("gas_curve", False)), key=key("gas_curve"))
                st.caption("Gas-zone parameters apply above GOC, using the same height above the water FWL. This job stores its own contacts.")
        specs = _domain(cfg, project, before, key)
        def defaults(spec):
            zone = project.grid.zones[spec.get("zone", 1) - 1]
            if kind == "petrophysics":
                return dict(poro=zone.poro, permx=zone.permx, ntg=zone.ntg, kykx=1.0, kvkh=zone.kvkh)
            if cfg["method"] == "satheight":
                return dict(swirr=0.2, entry=2.0, lam=0.5) | (
                    dict(gas_swirr=0.1, gas_entry=1.0, gas_lam=0.5) if cfg.get("gas_curve") else {})
            return dict(a=1.0, m=2.0, n=2.0, rw=0.1)
        _parameter_table(cfg, specs, defaults, key("parameters", [cfg["domain"], cfg.get("facies"), cfg.get("method"), cfg.get("gas_curve")]))
        if kind == "petrophysics":
            cfg["outputs"] = st.multiselect("Output properties", pp.ZONE_PROPS, default=cfg.get("outputs", pp.ZONE_PROPS), key=key("outputs"))
    if st.button("Save job configuration", key=key("save")):
        if not name.strip() or any(j["id"] != job["id"] and j["name"] == name.strip() for j in project.property_jobs):
            st.error("Give the job a unique, non-empty name.")
        else:
            job.update(name=name.strip(), config=cfg)
            st.session_state.pop(S.k("property_job_last"), None)
            st.rerun()


def _run_single(job, project, namespace):
    key = lambda field: S.k(f"{namespace}_{job['id']}_{field}")
    signature = (job["id"], json.dumps([job["name"], job["config"]], sort_keys=True), pp.grid_hash(project.grid))
    st.caption("Run this saved job only, using current stored properties as inputs. No preceding jobs run. "
               "Active controls workflow inclusion, not an explicit standalone run.")
    approved = not project.properties or st.checkbox("Allow this job to replace existing output properties", key=key("replace"))
    if st.button("Run this job", disabled=not approved, key=key("run")):
        st.session_state.pop(S.k("property_job_last"), None)
        st.session_state.pop(S.k("property_single_last"), None)
        try:
            bar = st.progress(0.0)
            report = jobs.run(project, progress=lambda f: bar.progress(min(float(f), 1.0)), job_id=job["id"])
            st.session_state[S.k("property_single_last")] = (signature, report[0]["outputs"])
            st.rerun()
        except jobs.PropertyWorkflowError as exc:
            st.error(str(exc))
    last = st.session_state.get(S.k("property_single_last"))
    if last and last[0] == signature:
        st.success(f"{job['name']} completed: {', '.join(last[1])}")


def named_facies(project):
    return named_job(project, "facies")


def named_job(project, kind):
    """Edit the actual saved job from its modelling workspace; standalone settings stay separate."""
    labels_by_type = {
        "facies": ("Facies modelling job", "Standalone facies settings", "fa"),
        "petrophysics": ("Petrophysics modelling job", "Standalone petrophysics settings", "pm"),
        "stochastic": ("Stochastic modelling job", "Standalone stochastic settings", "sx"),
        "saturation": ("Water-saturation modelling job", "Standalone saturation settings", "swm"),
        "calculator": ("Calculator job", "Standalone calculator settings", "calc"),
    }
    label, standalone, prefix = labels_by_type[kind]
    candidates = [j for j in project.property_jobs if j["type"] == kind]
    if not candidates:
        return False
    ids = ["standalone"] + [j["id"] for j in candidates]
    labels = {"standalone": standalone} | {
        j["id"]: f"{j['name']} (job {project.property_jobs.index(j) + 1})" for j in candidates}
    selected = st.selectbox(label, ids, format_func=labels.get, key=S.k(prefix + "_named_job", ids))
    if selected == "standalone":
        return False
    job = next(j for j in candidates if j["id"] == selected)
    st.subheader(job["name"])
    try:
        _configure(job, project, project.property_jobs.index(job), namespace=prefix + "_job")
    except (KeyError, TypeError, ValueError, OverflowError, gs.GeostatError) as exc:
        st.error(f"Job configuration: {exc}. Correct invalid values before saving.")
    _run_single(job, project, prefix + "_job")
    return True


def render(project):
    st.subheader("Property workflow")
    st.caption("Jobs run from top to bottom using outputs of earlier jobs. Untick Active to skip a job. "
               "Insert calculator jobs anywhere, including between facies and petrophysics.")
    for index, job in enumerate(project.property_jobs):
        if index:
            st.markdown('<div class="workflow-connector">&#8595;</div>', unsafe_allow_html=True)
        with st.container(border=True):
            style = STYLES[job["type"]]
            st.markdown(f'<div class="workflow-node workflow-{style}"><div class="workflow-number">{index + 1:02d}</div>'
                        f'<div class="workflow-content"><div class="workflow-category">{escape(jobs.JOB_TYPES[job["type"]])}</div>'
                        f'<div class="workflow-title">{escape(job["name"])}</div>'
                        f'<div class="workflow-io">{"Active job" if job.get("enabled", True) else "Skipped / inactive job"}</div></div></div>',
                        unsafe_allow_html=True)
            active = st.checkbox("Active", bool(job.get("enabled", True)), key=S.k(f"pj_{job['id']}_enabled"))
            if active != job.get("enabled", True):
                job["enabled"] = active
                st.session_state.pop(S.k("property_job_last"), None)
                st.rerun()
            up, down, delete = st.columns(3)
            if up.button("Move up", disabled=index == 0, key=S.k(f"pj_up_{job['id']}")):
                project.property_jobs[index - 1], project.property_jobs[index] = project.property_jobs[index], project.property_jobs[index - 1]
                st.session_state.pop(S.k("property_job_last"), None)
                st.rerun()
            if down.button("Move down", disabled=index == len(project.property_jobs) - 1, key=S.k(f"pj_down_{job['id']}")):
                project.property_jobs[index + 1], project.property_jobs[index] = project.property_jobs[index], project.property_jobs[index + 1]
                st.session_state.pop(S.k("property_job_last"), None)
                st.rerun()
            if delete.button("Delete job", key=S.k(f"pj_delete_{job['id']}")):
                project.property_jobs.pop(index)
                st.session_state.pop(S.k("property_job_last"), None)
                st.rerun()
            with st.expander(f"Configure job {index + 1:02d} - {job['name']}"):
                try:
                    _configure(job, project, index)
                except (KeyError, TypeError, ValueError, OverflowError, gs.GeostatError) as exc:
                    st.error(f"Job configuration: {exc}. Correct invalid values before saving.")
            _run_single(job, project, "pj")
    if not project.property_jobs:
        st.info("Add a facies job, optionally a calculator, then petrophysics and saturation. Existing properties can also be used as inputs.")
    with st.container(border=True):
        kind = st.selectbox("New property job", list(jobs.JOB_TYPES), format_func=jobs.JOB_TYPES.get, key=S.k("pj_new_kind"))
        positions = list(range(len(project.property_jobs) + 1))
        position = st.selectbox("Insert position", positions, index=len(positions) - 1,
                                format_func=lambda i: "At the start" if i == 0 else f"After job {i}: {project.property_jobs[i - 1]['name']}",
                                key=S.k("pj_position", [j["id"] for j in project.property_jobs]))
        if st.button("Insert job", key=S.k("pj_insert")):
            project.property_jobs.insert(position, jobs.new_job(kind, project))
            st.session_state.pop(S.k("property_job_last"), None)
            st.rerun()
    signature = json.dumps(project.property_jobs, sort_keys=True)
    approved = not project.properties or st.checkbox("Allow workflow jobs to replace existing output properties", key=S.k("pj_replace"))
    if st.button("Run property workflow", type="primary", disabled=not approved or not any(j.get("enabled", True) for j in project.property_jobs),
                 key=S.k("pj_run")):
        st.session_state.pop(S.k("property_job_last"), None)
        try:
            bar = st.progress(0.0)
            report = jobs.run(project, progress=lambda f: bar.progress(min(float(f), 1.0)))
            st.session_state[S.k("property_job_last")] = (signature, pp.grid_hash(project.grid), report)
            st.rerun()
        except jobs.PropertyWorkflowError as exc:
            st.error(str(exc))
    last = st.session_state.get(S.k("property_job_last"))
    if last and last[:2] == (signature, pp.grid_hash(project.grid)):
        st.success("Property workflow completed. Skipped jobs did not run.")
        st.dataframe(pd.DataFrame(last[2]), hide_index=True)
    st.caption("Save job configuration before running. Each modelling workspace can edit its named jobs; standalone tool settings remain separate. "
               "All active jobs must succeed before any outputs are committed; failures leave existing properties unchanged. "
               "Changing jobs does not delete stored outputs: rerun to update those snapshots.")
