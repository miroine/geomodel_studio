"""Fluvial geometry and named, independently executable property jobs."""
import copy
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import facies as fa, project as pj, property_workflow as jobs, props as pp, units as un
from test_stochastic_facies import fixture


def channel_project(shape="channel"):
    grid, _, _ = fixture()
    p = pj.Project(grid=grid)
    job = jobs.new_job("facies", p)
    job["name"] = "Fluvial sand"
    cfg = job["config"]
    cfg.update(method="objects", azimuth_sd=0)
    cfg["objects"] = [dict(code=3, shape=shape, length=100., width=12., thickness=14.,
                           azimuth=90., amplitude=18., wavelength=70.,
                           centerline=[[5., 35.], [55., 55.], [115., 35.]])]
    for z in cfg["zones"]:
        z["top"] = z["base"] = [0.8, 0., 0.2]
    p.property_jobs = [job]
    return p


class ChannelJobTests(unittest.TestCase):
    def test_polyline_distance_follows_bends_and_open_endcaps(self):
        pts = np.array([[0., 0.], [10., 10.], [20., 0.]])
        distance = fa.channel_distance(np.array([10., 10., -3.]), np.array([10., 0., 0.]), pts)
        np.testing.assert_allclose(distance, [0., np.sqrt(50), 3.])

    def test_channels_reproduce_seed_and_honor_active_zone_targets(self):
        for shape in ("channel", "digitized_channel"):
            with self.subTest(shape=shape):
                p = channel_project(shape)
                jobs.run(p)
                values = p.properties["FACIES"].values
                p2 = channel_project(shape)
                jobs.run(p2)
                np.testing.assert_equal(values, p2.properties["FACIES"].values)
                self.assertTrue(np.isnan(values[p.grid.actnum == 0]).all())
                for zi in (0, 1):
                    mask = (p.grid.actnum > 0) & (p.grid.layer_zone == zi)[:, None, None]
                    self.assertGreaterEqual(float(np.mean(values[mask] == 3)), 0.2)
                    self.assertTrue(np.isin(values[mask], [1, 3]).all())

    def test_digitized_channels_use_world_coordinates_on_rotated_grids(self):
        p = channel_project("digitized_channel")
        other = copy.deepcopy(p)
        other.grid.angle = 32.
        other.grid.origin = (1000., 2000.)
        line = np.asarray(other.property_jobs[0]["config"]["objects"][0]["centerline"])
        x, y = other.grid.to_world(line[:, 0], line[:, 1])
        other.property_jobs[0]["config"]["objects"][0]["centerline"] = np.column_stack((x, y)).tolist()
        jobs.run(p)
        jobs.run(other)
        np.testing.assert_equal(p.properties["FACIES"].values, other.properties["FACIES"].values)

    def test_invalid_channel_parameters_roll_back(self):
        cases = [("channel", "wavelength", 0.), ("channel", "amplitude", np.inf),
                 ("digitized_channel", "centerline", [[1., 2.]]),
                 ("digitized_channel", "centerline", [[1., 2.], [1., 2.]])]
        for shape, key, value in cases:
            with self.subTest(key=key):
                p = channel_project(shape)
                p.property_jobs[0]["config"]["objects"][0][key] = value
                with self.assertRaises(jobs.PropertyWorkflowError):
                    jobs.run(p)
                self.assertFalse(p.properties)

    def test_unreachable_channel_target_reports_error_instead_of_committing(self):
        p = channel_project()
        with patch("core.facies.channel_distance", side_effect=lambda u, v, pts: np.full(u.shape, np.inf)):
            with self.assertRaisesRegex(jobs.PropertyWorkflowError, "below target"):
                jobs.run(p)
        self.assertFalse(p.properties)

    def test_legacy_ellipsoids_unchanged_and_channel_units_roundtrip(self):
        p = channel_project()
        legacy = copy.deepcopy(p.property_jobs[0]["config"])
        for obj in legacy["objects"]:
            for key in ("shape", "amplitude", "wavelength", "centerline"):
                obj.pop(key)
        expected = fa.simulate(p.grid, legacy)
        np.testing.assert_equal(expected, fa.simulate(p.grid, fa.normalise(copy.deepcopy(legacy), p.grid)))
        p.facies = copy.deepcopy(p.property_jobs[0]["config"])
        loaded = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(loaded.property_jobs, p.property_jobs)
        un.convert_project(p, "ft", "ft")
        for cfg in (p.facies, p.property_jobs[0]["config"]):
            obj = cfg["objects"][0]
            self.assertAlmostEqual(obj["amplitude"], 18 / 0.3048)
            self.assertAlmostEqual(obj["wavelength"], 70 / 0.3048)
            np.testing.assert_allclose(obj["centerline"], np.array([[5, 35], [55, 55], [115, 35]]) / 0.3048)

    def test_standalone_runs_disabled_job_only_and_missing_inputs_rollback(self):
        p = channel_project()
        first = p.property_jobs[0]
        first["enabled"] = False
        calc = jobs.new_job("calculator", p)
        calc["config"]["code"] = "COPY = FACIES"
        p.property_jobs.append(calc)
        jobs.run(p, job_id=first["id"])
        self.assertEqual(set(p.properties), {"FACIES"})
        self.assertFalse(first["enabled"])
        jobs.run(p, job_id=calc["id"])
        np.testing.assert_equal(p.properties["COPY"].values, p.properties["FACIES"].values)
        p.properties.clear()
        with self.assertRaises(jobs.PropertyWorkflowError):
            jobs.run(p, job_id=calc["id"])
        self.assertFalse(p.properties)
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "does not exist"):
            jobs.run(p, job_id="deleted")

    def test_new_facies_jobs_get_unique_names_and_output_properties(self):
        p = channel_project()
        second = jobs.new_job("facies", p)
        self.assertNotEqual(second["config"]["output"], p.property_jobs[0]["config"]["output"])
        p.property_jobs.append(second)
        third = jobs.new_job("facies", p)
        self.assertNotEqual(second["name"], third["name"])
        self.assertNotEqual(second["config"]["output"], third["config"]["output"])

    def test_named_facies_editors_are_isolated_and_single_run_commits_only_selected_job(self):
        app = AppTest.from_string("""
import streamlit as st
from test_channels_jobs import channel_project
from core import property_workflow as jobs
from views import property_workflow as view
if "p" not in st.session_state:
    p = channel_project()
    second = jobs.new_job("facies", p)
    second["name"] = "Alternative facies"
    p.property_jobs.append(second)
    st.session_state["p"] = p
view.render(st.session_state["p"])
view.named_facies(st.session_state["p"])
""").run(timeout=30)
        self.assertFalse(app.exception)
        p = app.session_state["p"]
        first, second = p.property_jobs
        selector = next(s for s in app.selectbox if s.label == "Facies modelling job")
        selector.select(second["id"]).run(timeout=30)
        self.assertFalse(app.exception)
        output = next(t for t in app.text_input if t.key.startswith(f"fa_job_{second['id']}_output"))
        output.set_value("FACIES_ALT").run(timeout=30)
        next(b for b in app.button if b.key.startswith(f"fa_job_{second['id']}_save")).click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["p"].property_jobs[1]["config"]["output"], "FACIES_ALT")
        self.assertEqual(app.session_state["p"].property_jobs[0]["config"]["output"], "FACIES")
        self.assertEqual(next(t for t in app.text_input if t.key.startswith(f"pj_{second['id']}_output")).value, "FACIES_ALT")
        next(b for b in app.button if b.key.startswith(f"fa_job_{second['id']}_run")).click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(set(app.session_state["p"].properties), {"FACIES_ALT"})

    def test_digitizer_result_is_saved_in_the_selected_job(self):
        app = AppTest.from_string("""
import streamlit as st
from test_channels_jobs import channel_project
from views.property_workflow import named_facies
if "p" not in st.session_state:
    st.session_state["p"] = channel_project("digitized_channel")
named_facies(st.session_state["p"])
""").run(timeout=30)
        job = app.session_state["p"].property_jobs[0]
        with patch("views.facies_objects.map_editor", return_value=dict(kind="fences", polygons=[
                dict(name="Channel", pts=[[10., 20.], [110., 60.]])])):
            next(s for s in app.selectbox if s.label == "Facies modelling job").select(job["id"]).run(timeout=30)
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == "Save job configuration").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["p"].property_jobs[0]["config"]["objects"][0]["centerline"],
                         [[10., 20.], [110., 60.]])


if __name__ == "__main__":
    unittest.main()
