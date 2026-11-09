"""Named property jobs, contact sources, exact fence crossings and average-map regressions."""
import base64
import copy
import os
import sys
import unittest
import io
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import analysis as an, gridsection as gs, petrophysics as petro, volumetrics as vol, props as pp, project as pj, property_workflow as jobs, units as un
from core.polygons import Polygon
from core.surface import Geometry
from test_property_models import grid_fixture
from test_stochastic_facies import fixture
from ui.scene import Scene, grid_property
from ui.components import viewer3d


def project():
    g, props, _ = fixture()
    props["PORO"] = pp.make_property(g, "PORO", 0.2, unit="frac")
    p = pj.Project(grid=g, properties=props)
    p.fences["Diagonal"] = Polygon("Diagonal", [[5., 5.], [115., 75.]])
    return p


def saturation_config(g):
    return dict(method="satheight", domain="zone", rows=[
        dict(zone=i + 1, swirr=0.2, entry=2., lam=0.5, gas_swirr=0.1, gas_entry=1., gas_lam=1.)
        for i, _ in enumerate(g.zones)], gas_curve=True)


class PropertyResultTests(unittest.TestCase):
    def tearDown(self):
        un.set_active(un.DEFAULT_CRS)

    def test_named_editors_for_each_job_type_are_isolated_and_synchronized(self):
        for kind, selector, prefix, field, value in [
            ("petrophysics", "Petrophysics modelling job", "pm", "name", "Alternative petrophysics"),
            ("stochastic", "Stochastic modelling job", "sx", "seed", 123),
            ("saturation", "Water-saturation modelling job", "swm", "output", "SW_ALT"),
            ("calculator", "Calculator job", "calc", "code", "TEST = PORO * 2"),
        ]:
            with self.subTest(kind=kind):
                app = AppTest.from_string(f"""
import streamlit as st
from test_property_results import project
from core import property_workflow as jobs
from views import property_workflow as view
if "p" not in st.session_state:
    p = project()
    p.property_jobs = [jobs.new_job("{kind}", p)]
    p.property_jobs.append(jobs.new_job("{kind}", p))
    st.session_state["p"] = p
view.render(st.session_state["p"])
view.named_job(st.session_state["p"], "{kind}")
""").run(timeout=30)
                self.assertFalse(app.exception)
                p = app.session_state["p"]
                second = p.property_jobs[1]
                first = copy.deepcopy(p.property_jobs[0])
                next(s for s in app.selectbox if s.label == selector).select(second["id"]).run(timeout=30)
                target = next(w for w in list(app.text_input) + list(app.text_area) + list(app.number_input)
                              if w.key.startswith(f"{prefix}_job_{second['id']}_{field}_"))
                target.set_value(value).run(timeout=30)
                next(b for b in app.button if b.key.startswith(f"{prefix}_job_{second['id']}_save")).click().run(timeout=30)
                self.assertFalse(app.exception)
                saved = app.session_state["p"].property_jobs[1]
                self.assertEqual(saved["name"] if field == "name" else saved["config"][field if field != "output" else "output"], value)
                self.assertEqual(app.session_state["p"].property_jobs[0], first)
                mirror = next(w for w in list(app.text_input) + list(app.text_area) + list(app.number_input)
                              if w.key.startswith(f"pj_{second['id']}_{field}_"))
                self.assertEqual(mirror.value, value)

    def test_contact_properties_override_tilt_and_convert_length_units(self):
        g = grid_fixture()
        cfg = vol.default_config(g)
        cfg["contacts"].update(owc_prop="WOC", goc_prop="GOC")
        cfg["contacts"]["tilt"]["gx"] = 10.
        props = {"WOC": pp.make_property(g, "WOC", 1050 / 0.3048, unit="ft"),
                 "GOC": pp.make_property(g, "GOC", 1010, unit="m")}
        o, gas, fwl = vol.contact_cubes(g, cfg, props)
        np.testing.assert_allclose(o, 1050., atol=1e-4)
        np.testing.assert_allclose(gas, 1010.)
        np.testing.assert_allclose(fwl, o)
        flat = vol.contact_cubes(g, cfg, props, dict(owc_all=1060.))[0]
        np.testing.assert_allclose(flat, 1060.)

    def test_gas_curve_only_applies_above_goc_and_uses_water_fwl(self):
        g = grid_fixture()
        contacts = vol.default_config(g)
        contacts["contacts"].update(owc=1050., goc=1010.)
        cfg = saturation_config(g)
        values = petro.model_saturation(g, {}, cfg, contacts)
        expected = np.array([0.1 + 0.9 / 45., 0.2 + 0.8 * np.sqrt(2 / 35.)])
        np.testing.assert_allclose(values[:, 0, 0], expected)
        cfg["gas_curve"] = False
        baseline = petro.model_saturation(g, {}, cfg, contacts)
        self.assertNotEqual(float(values[0, 0, 0]), float(baseline[0, 0, 0]))
        self.assertEqual(float(values[1, 0, 0]), float(baseline[1, 0, 0]))
        contacts["contacts"]["fwl_below"] = -1
        with self.assertRaisesRegex(petro.PetroError, "non-negative"):
            petro.model_saturation(g, {}, cfg, contacts)
        contacts["contacts"].update(fwl_below=0., goc=None)
        cfg["gas_curve"] = True
        with self.assertRaisesRegex(petro.PetroError, "Define GOC"):
            petro.model_saturation(g, {}, cfg, contacts)

    def test_contact_inputs_validation_and_job_rollback(self):
        p = project()
        calc = jobs.new_job("calculator", p)
        calc["config"].update(code="WOC = PORO * 0 + 1050\nGOC = PORO * 0 + 1010",
                              result_kind="continuous", unit="m")
        saturation = jobs.new_job("saturation", p)
        saturation["config"]["contacts"]["contacts"].update(owc_prop="WOC", goc_prop="GOC")
        p.property_jobs = [calc, saturation]
        jobs.run(p)
        self.assertIn("SW", p.properties)
        for mode in ("missing", "stale", "undefined", "wrong_unit", "inverted"):
            with self.subTest(mode=mode):
                other = copy.deepcopy(p)
                if mode == "missing":
                    del other.properties["WOC"]
                elif mode == "stale":
                    other.properties["WOC"].stale = True
                elif mode == "undefined":
                    other.properties["WOC"].values[1, 0, 0] = np.nan
                elif mode == "wrong_unit":
                    other.properties["WOC"].unit = "mD"
                else:
                    other.properties["GOC"].values[:] = 1100
                previous = other.properties["SW"].values.copy()
                with self.assertRaises(jobs.PropertyWorkflowError):
                    jobs.run(other, job_id=saturation["id"])
                np.testing.assert_equal(other.properties["SW"].values, previous)

    def test_gas_parameters_and_contacts_persist_and_convert_with_units(self):
        p = project()
        job = jobs.new_job("saturation", p)
        job["config"].update(saturation_config(p.grid))
        job["config"]["contacts"]["contacts"].update(owc=1050., goc=1010., owc_prop="WOC")
        p.property_jobs = [job]
        p.property_models["saturation_satheight|zone|"] = copy.deepcopy(job["config"])
        saved = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(saved.property_jobs, p.property_jobs)
        un.convert_project(p, "m", "ft")
        self.assertAlmostEqual(job["config"]["rows"][0]["gas_entry"], 1 / 0.3048)
        self.assertAlmostEqual(job["config"]["contacts"]["contacts"]["goc"], 1010 / 0.3048)
        self.assertEqual(job["config"]["contacts"]["contacts"]["owc_prop"], "WOC")

    def test_exact_fence_crossings_clipped_lengths_and_global_cell_values(self):
        p = project()
        points = [[-5., 25.], [125., 25.]]
        columns = gs.fence_columns(p.grid, points)["segs"]
        np.testing.assert_allclose(columns[:, 0], 5 + 10 * np.arange(12))
        np.testing.assert_allclose(columns[:, 1] - columns[:, 0], 10.)
        values = np.arange(p.grid.ncells).reshape(p.grid.actnum.shape).astype(float)
        sec = gs.fence_property_section(p.grid, values, points)
        np.testing.assert_equal(sec["v"], values.ravel()[sec["cell_ids"]])
        np.testing.assert_equal(sec["j"], 2)
        np.testing.assert_allclose(sec["world_y"], 25.)
        for points in ([[1., 2.], [1., 2.]], [[np.nan, 0.], [1., 2.]], [[-10., -5.], [-10., -15.]]):
            with self.assertRaises(gs.SectionError):
                gs.fence_columns(p.grid, points)

    def test_rotated_refined_fence_and_layer_contact_cubes(self):
        p = project()
        g = p.grid
        g.xs = np.array([0, 5, 15, 20, 40, 50, 60, 70, 80, 90, 100, 110, 120.])
        g.angle, g.origin = 28., (1000., 2000.)
        x, y = g.to_world(np.array([0., 120.]), np.array([25., 25.]))
        line = np.column_stack((x, y))
        segs = gs.fence_columns(g, line)["segs"]
        np.testing.assert_allclose(segs[:, 1] - segs[:, 0], np.diff(g.xs), atol=1e-9)
        contact = g.center_depth()
        sec = gs.fence_property_section(g, p.properties["PORO"].values, line, owc=contact)
        self.assertEqual(len(sec["contacts"]["OWC"]["z"]), len(sec["v"]))
        np.testing.assert_allclose(sec["contacts"]["OWC"]["z"], sec["z"].mean(axis=1))

    def test_fence_payload_colors_ids_and_validated_picking(self):
        p = project()
        pr = pp.make_property(p.grid, "PERMX", np.arange(p.grid.ncells).reshape(p.grid.actnum.shape) + 1., unit="mD")
        p.properties["PERMX"] = pr
        sc = Scene((0., 0.))
        obj = sc.property_fence(p.grid, "PERMX", p.fences["Diagonal"].pts, p.properties,
                                layer_mask=[False, True, False, True])
        ids = np.frombuffer(base64.b64decode(obj["cell_ids"]), np.uint32)
        values = np.frombuffer(base64.b64decode(obj["cell_values"]), np.float64)
        np.testing.assert_equal(values, pr.values.ravel()[ids])
        kk, jj, ii = np.unravel_index(ids, p.grid.actnum.shape)
        self.assertTrue(np.isin(kk, [1, 3]).all())
        self.assertTrue((p.grid.actnum[kk, jj, ii] > 0).all())
        with patch("ui.components._viewer3d", side_effect=lambda **args: dict(
                rev=args["rev"], object_id=obj["id"], cell_id=int(ids[-1]))):
            pick = viewer3d(sc, "fence-test")
        self.assertEqual(pick["value"], float(pr.values.ravel()[ids[-1]]))
        self.assertEqual((pick["i"], pick["j"], pick["k"]), (ii[-1] + 1, jj[-1] + 1, kk[-1] + 1))
        self.assertEqual(obj["legend"], grid_property(p.grid, "PERMX", p.properties)[1])

    def test_average_maps_exact_weights_and_empty_columns(self):
        g = grid_fixture()
        g.zc[1, 1] += 10
        props = {"X": pp.make_property(g, "X", [[[1., 2.]], [[3., 4.]]])}
        np.testing.assert_allclose(an.map_2d(g, props, "X", g.actnum > 0, "average", ()), [[2., 3.]])
        np.testing.assert_allclose(an.map_2d(g, props, "X", g.actnum > 0, "thickness-weighted", ()), [[7 / 3, 10 / 3]])
        volume = np.array([[[100., 100.]], [[300., 300.]]])
        with patch.object(g, "bulk_volume", return_value=volume):
            np.testing.assert_allclose(an.map_2d(g, props, "X", g.actnum > 0, "bulk-volume-weighted", ()), [[2.5, 3.5]])
        self.assertFalse(an.selection(g, props, zones=[]).any())
        mask = g.actnum > 0
        mask[:, :, 1] = False
        self.assertTrue(np.isnan(an.map_2d(g, props, "X", mask, "average", ())[0, 1]))
        props["X"].stale = True
        with self.assertRaisesRegex(an.AnalysisError, "stale"):
            an.map_2d(g, props, "X", mask)

    def test_results_ui_and_exported_average_coordinates(self):
        with patch("views.property_results.st.download_button", wraps=st.download_button) as download:
            app = AppTest.from_string("""
import streamlit as st
from test_property_results import project
from views import property_results
if "p" not in st.session_state:
    st.session_state["p"] = project()
p = st.session_state["p"]
property_results.intersections(p)
property_results.average_maps(p)
""").run(timeout=30)
        exported = next(call.args[1] for call in download.call_args_list if call.args[0] == "Download PORO average map (CSV)")
        frame = pd.read_csv(io.BytesIO(exported))
        x, y = app.session_state["p"].grid.center_xy()
        np.testing.assert_allclose(frame["X"], x.ravel())
        np.testing.assert_allclose(frame["Y"], y.ravel())
        np.testing.assert_allclose(frame["Value"], 0.2)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(next(s for s in app.selectbox if s.label == "Property fence").value, "Diagonal")
        self.assertTrue(any(b.label == "Download PORO average map (CSV)" for b in app.get("download_button")))
        next(s for s in app.selectbox if s.label == "Average-map method").select("bulk-volume-weighted").run(timeout=30)
        self.assertFalse(app.exception)
        next(s for s in app.multiselect if s.label == "Zones included" and s.key.startswith("am")).set_value([]).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("at least one zone/layer" in info.value for info in app.info))

    def test_fence_editor_background_shows_clipped_model_top(self):
        from core.cpgrid import ZoneSpec, build_grid
        from core.surface import Surface
        from core.workflow import run_workflow
        from views.property_results import _model_map
        lat = Geometry(0, 0, 10, 10, 11, 11)
        p = pj.Project(lattice=lat)
        p.surfaces = {"Top map": Surface("Top map", lat, np.full(lat.shape, 1000.0))}
        p.steps = [dict(type="surface", horizon="Top", surface="Top map"),
                   dict(type="isochore", horizon="Base", ref="Top", thickness=50)]
        p.structure = run_workflow(p.steps, p.surfaces, {}, None, lat)
        p.zones = [ZoneSpec("Reservoir", "Top", "Base", nlayers=2)]
        p.grid = build_grid(p.structure, p.zones, 10, 10, 0.1)
        self.assertIsNone(_model_map(pj.Project(grid=p.grid)))
        p.polygons["Box"] = Polygon("Box", [[0., 0.], [50., 0.], [50., 50.], [0., 50.]])
        p.boundary = "Box"
        m = _model_map(p)
        self.assertEqual((m["ncol"], m["nrow"], m["x0"], m["dx"]), (11, 11, 0, 10))
        z = np.asarray(m["z"]).reshape(11, 11)
        self.assertEqual((m["zmin"], m["zmax"]), (1000.0, 1000.0))
        self.assertTrue(np.isfinite(z[2, 2]))
        self.assertTrue(np.isnan(z[9, 9]))

    def test_main_properties_page_exposes_all_named_modelling_selectors(self):
        app = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")).run(timeout=30)
        p = project()
        p.lattice = Geometry(0., 0., 10., 10., p.grid.ni + 1, p.grid.nj + 1)
        for kind in jobs.JOB_TYPES:
            p.property_jobs.append(jobs.new_job(kind, p))
        app.session_state["proj"] = p
        app.session_state["nav"] = "Properties"
        app.run(timeout=30)
        self.assertFalse(app.exception)
        labels = [s.label for s in app.selectbox]
        for label in ("Facies modelling job", "Petrophysics modelling job", "Stochastic modelling job",
                      "Water-saturation modelling job", "Calculator job"):
            self.assertIn(label, labels)
        for label, kind in (("Petrophysics modelling job", "petrophysics"), ("Stochastic modelling job", "stochastic"),
                            ("Water-saturation modelling job", "saturation"), ("Calculator job", "calculator")):
            job = next(j for j in p.property_jobs if j["type"] == kind)
            next(s for s in app.selectbox if s.label == label).select(job["id"]).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)


if __name__ == "__main__":
    unittest.main()
