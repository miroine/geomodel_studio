"""Facies trends, property-run provenance and library calculator."""
import copy
import os
import sys
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import facies, facies_trends, project, property_workflow, units
from core.surface import Geometry, Surface
from test_stochastic_facies import fixture


class FaciesHistoryTests(unittest.TestCase):
    def setUp(self):
        self.grid, self.props, _ = fixture()
        self.cfg = facies.default_config(self.grid, 2)
        self.surface = Surface("Map", Geometry(0, 0, 10, 10, 13, 9), np.full((9, 13), 1010.0))

    def test_baseline_and_absolute_depth_for_both_algorithms(self):
        cfg = self.cfg
        cfg["vol_weight"] = False
        for method in ("truncated_gaussian", "indicator"):
            cfg["method"] = method
            old = facies.simulate(self.grid, cfg)
            zero = copy.deepcopy(cfg)
            zero["probability_trends"] = {"1": dict(depth_enabled=True, curve=[[1000, 0], [1040, 0]])}
            np.testing.assert_array_equal(old, facies.simulate(self.grid, zero))
            changed = copy.deepcopy(cfg)
            changed["probability_trends"] = {"1": dict(depth_enabled=True, curve=[[1000, 1], [1040, -1]]),
                                             "2": dict(depth_enabled=True, curve=[[1000, -1], [1040, 1]])}
            arr = facies.simulate(self.grid, changed)
            self.assertTrue(np.all(arr[0][self.grid.actnum[0] > 0] == 1))
            self.assertTrue(np.all(arr[-1][self.grid.actnum[-1] > 0] == 2))

    def test_surface_map_and_distance_and_conditioning(self):
        cfg = self.cfg
        cfg["probability_trends"] = {
            "1": dict(map_enabled=True, map="Map", reference=1010, strength=1,
                      distance_enabled=True, distance_surface="Map", distance_curve=[[-20, 1], [40, -1]]),
            "2": dict(map_enabled=True, map="Map", reference=1010, strength=1,
                      distance_enabled=True, distance_surface="Map", distance_curve=[[-20, -1], [40, 1]])}
        offsets = facies_trends.offsets(self.grid, cfg, {"Map": self.surface})
        self.assertAlmostEqual(offsets[0, 0, 1, 1], 0.5)
        self.assertAlmostEqual(offsets[0, 3, 1, 1], -0.5)
        cond = np.full(self.grid.actnum.shape, np.nan)
        cond[0, 1, 1] = 2
        for method in ("truncated_gaussian", "indicator"):
            cfg["method"] = method
            self.assertEqual(facies.simulate(self.grid, cfg, cond=cond, surfaces={"Map": self.surface})[0, 1, 1], 2)
        with self.assertRaisesRegex(facies.FaciesError, "missing"):
            facies.simulate(self.grid, cfg, surfaces={})
        bad = copy.deepcopy(cfg)
        bad["probability_trends"]["1"]["distance_curve"] = [[0, 0], [0, 1]]
        with self.assertRaisesRegex(facies.FaciesError, "unique"):
            facies.simulate(self.grid, bad, surfaces={"Map": self.surface})
        bad = copy.deepcopy(cfg)
        bad["probability_trends"] = {
            "1": dict(depth_enabled=True, curve=[[0, -2], [1, -2]]),
            "2": dict(depth_enabled=True, curve=[[0, -2], [1, -2]])}
        with self.assertRaisesRegex(facies.FaciesError, "zero probability"):
            facies.simulate(self.grid, bad)
        cfg["method"] = "objects"
        with self.assertRaisesRegex(facies.FaciesError, "only"):
            facies.simulate(self.grid, cfg, surfaces={"Map": self.surface})

    def test_history_commit_failure_rollback_persistence_and_units(self):
        p = project.Project(grid=self.grid, properties=self.props, surfaces={"Map": self.surface})
        first = property_workflow.new_job("calculator", p)
        first["config"]["code"] = "TEST = 4"
        second = property_workflow.new_job("calculator", p)
        second["config"]["code"] = "import os"
        p.property_jobs = [first, second]
        with self.assertRaises(property_workflow.PropertyWorkflowError):
            property_workflow.run(p)
        self.assertEqual([r["status"] for r in p.property_history], ["Rolled back", "Failed"])
        self.assertNotIn("TEST", p.properties)
        second["config"]["code"] = "NEXT = TEST + 1"
        property_workflow.run(p)
        self.assertEqual(p.property_history[-2]["outputs"], ["TEST"])
        first["config"]["code"] = "TEST = 7"
        self.assertEqual(p.property_history[-2]["settings"]["code"], "TEST = 4")
        restored = project.from_bytes(project.to_bytes(p))
        self.assertEqual(restored.property_history, p.property_history)
        p.facies = copy.deepcopy(self.cfg)
        p.facies["probability_trends"] = {"1": dict(depth_enabled=True, curve=[[1000, 0], [1020, 1]],
            distance_enabled=True, distance_curve=[[-10, 0], [10, 1]], map_enabled=True, reference=1000, strength=0.1)}
        units.convert_project(p, "ft", "ft")
        t = p.facies["probability_trends"]["1"]
        self.assertAlmostEqual(t["curve"][0][0], 1000 / 0.3048)
        self.assertAlmostEqual(t["distance_curve"][0][0], -10 / 0.3048)
        self.assertAlmostEqual(t["reference"], 1000 / 0.3048)
        self.assertAlmostEqual(t["strength"], 0.1 * 0.3048)

    def test_library_calculator_is_recorded_and_persisted(self):
        app = AppTest.from_string("""
import streamlit as st
from core.project import Project
from core.surface import Geometry
from test_stochastic_facies import fixture
from views.properties import render
if "proj" not in st.session_state:
    g, props, _ = fixture()
    st.session_state["proj"] = Project(grid=g, lattice=Geometry(0, 0, 10, 10, 13, 9), properties=props)
render()
""").run(timeout=30)
        self.assertFalse(app.exception)
        scripts = [w for w in app.text_area if w.label == "Script"]
        self.assertEqual(len(scripts), 2)
        scripts[0].set_value("CALC_TEST = 0.25").run(timeout=30)
        [b for b in app.button if b.label == "Run and store"][0].click().run(timeout=30)
        self.assertFalse(app.exception)
        p = app.session_state["proj"]
        self.assertIn("CALC_TEST", p.properties)
        self.assertEqual(p.property_history[-1]["outputs"], ["CALC_TEST"])
        self.assertEqual(project.from_bytes(project.to_bytes(p)).property_history, p.property_history)
        self.assertIn("Domain assignments", [tab.label for tab in app.tabs])

    def test_saved_facies_job_uses_surface_trends(self):
        p = project.Project(grid=self.grid, surfaces={"Map": self.surface})
        job = property_workflow.new_job("facies", p)
        job["config"] = copy.deepcopy(self.cfg)
        job["config"]["output"] = "FACIES_T"
        job["config"]["probability_trends"] = {
            "1": dict(map_enabled=True, map="Map", reference=1010, strength=1,
                      distance_enabled=True, distance_surface="Map", distance_curve=[[-20, 1], [40, -1]]),
            "2": dict(depth_enabled=True, curve=[[1000, -1], [1040, 1]])}
        p.property_jobs = [job]
        property_workflow.run(p)
        self.assertIn("FACIES_T", p.properties)
        self.assertEqual(p.property_history[-1]["job_id"], job["id"])
        self.assertEqual(p.property_history[-1]["settings"]["probability_trends"], job["config"]["probability_trends"])

    def test_standalone_facies_trend_controls_and_run(self):
        app = AppTest.from_string("""
import streamlit as st
import numpy as np
from core.project import Project
from core.surface import Geometry, Surface
from test_stochastic_facies import fixture
from views.properties import _facies
if "p" not in st.session_state:
    g, props, _ = fixture()
    geom = Geometry(0, 0, 10, 10, 13, 9)
    st.session_state["p"] = Project(grid=g, lattice=geom, properties=props,
        surfaces={"Map": Surface("Map", geom, np.full(geom.shape, 1010.0))})
_facies(st.session_state["p"], st.session_state["p"].grid)
""").run(timeout=30)
        self.assertFalse(app.exception)
        next(c for c in app.checkbox if c.label == "Shale: absolute depth trend").check().run(timeout=30)
        next(c for c in app.checkbox if c.label == "Shale: probability map trend").check().run(timeout=30)
        next(c for c in app.checkbox if c.label == "Shale: distance from surface trend").check().run(timeout=30)
        next(b for b in app.button if b.label == "Run facies model").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        p = app.session_state["p"]
        trend = p.property_history[-1]["settings"]["probability_trends"]["1"]
        self.assertTrue(trend["depth_enabled"])
        self.assertEqual(trend["map"], "Map")
        self.assertEqual(trend["distance_surface"], "Map")
        self.assertIn("FACIES", p.property_history[-1]["outputs"])
        self.assertEqual(project.from_bytes(project.to_bytes(p)).property_history, p.property_history)


if __name__ == "__main__":
    unittest.main()
