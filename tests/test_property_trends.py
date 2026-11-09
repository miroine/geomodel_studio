"""Depth curves, map sampling, residual conditioning and persisted trend jobs."""
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import geostat as gs, petrophysics as petro, project as pj, property_workflow as jobs
from core import property_trends as trends
from core.surface import Geometry, Surface
from test_property_models import grid_fixture


class PropertyTrendTests(unittest.TestCase):
    def setUp(self):
        self.grid = grid_fixture()
        self.surface = Surface("Trend", Geometry(0, 0, 10, 10, 3, 2),
                               np.array([[0, 10, 20], [0, 10, 20]], float))
        self.surfaces = {"Trend": self.surface}
        self.trend = dict(depth_enabled=True, curve=[[1005, 0.01], [1015, 0.03]],
                          map_enabled=True, map="Trend", reference=5, strength=0.002)

    def rows(self):
        return [dict(zone=i + 1, label=z.name, poro=0.2, permx=100, ntg=0.8, kykx=0.5, kvkh=0.1)
                for i, z in enumerate(self.grid.zones)]

    def test_curve_and_map_addition(self):
        expected = np.array([[[0.01, 0.03]], [[0.03, 0.05]]])
        np.testing.assert_allclose(trends.offset(self.grid, self.trend, self.surfaces), expected)
        reverse = dict(self.trend, curve=self.trend["curve"][::-1])
        np.testing.assert_allclose(trends.offset(self.grid, reverse, self.surfaces), expected)
        curve = dict(depth_enabled=True, curve=[[1010, -0.1], [1012, 0.1]])
        np.testing.assert_allclose(trends.offset(self.grid, curve), [[[-0.1, -0.1]], [[0.1, 0.1]]])

    def test_rotated_grid_map_samples_world_coordinates(self):
        self.grid.angle = 90
        self.grid.origin = (10, 0)
        self.surfaces["Trend"] = Surface("Trend", Geometry(0, 0, 10, 10, 3, 3),
                                         np.tile([0, 10, 20], (3, 1)).astype(float))
        result = trends.offset(self.grid, dict(map_enabled=True, map="Trend", strength=1, reference=0), self.surfaces)
        np.testing.assert_allclose(result, 5)

    def test_errors_and_inactive_map_columns(self):
        for cfg in (dict(depth_enabled=True, curve=[[1000, 0], [1000, 1]]),
                    dict(depth_enabled=True, curve=[[1000, 0]]),
                    dict(depth_enabled=True, curve=[[1000, np.nan], [1010, 1]]),
                    dict(map_enabled=True, map="Missing"),
                    dict(map_enabled=True, map="Trend", strength=np.inf)):
            with self.subTest(cfg=cfg), self.assertRaises(trends.TrendError):
                trends.offset(self.grid, cfg, self.surfaces)
        self.surface.z[:, 2] = np.nan
        with self.assertRaisesRegex(trends.TrendError, "does not cover"):
            trends.offset(self.grid, self.trend, self.surfaces)
        self.grid.actnum[:, :, 1] = 0
        self.assertTrue(np.isfinite(trends.offset(self.grid, self.trend, self.surfaces)).all())

    def test_domain_properties_ratios_and_limits(self):
        cfg = {"PORO": self.trend, "PERM": dict(depth_enabled=True, curve=[[1000, 50], [1020, 50]]),
               "NTG": dict(depth_enabled=True, curve=[[1000, 1], [1020, 1]])}
        output = petro.model_petrophysics(self.grid, {}, "zone", "", self.rows(), cfg, self.surfaces)
        np.testing.assert_allclose(output["PORO"].values, [[[0.21, 0.23]], [[0.23, 0.25]]])
        np.testing.assert_allclose(output["PERMX"].values, 150)
        np.testing.assert_allclose(output["PERMY"].values, 75)
        np.testing.assert_allclose(output["PERMZ"].values, 15)
        np.testing.assert_allclose(output["NTG"].values, 1)

    def config(self):
        cfg = gs.default_config(self.grid)
        cfg["props"]["PERM"]["enabled"] = cfg["props"]["NTG"]["enabled"] = False
        for row in cfg["props"]["PORO"]["rows"]:
            row.update(p1=0.2, p2=0.01, vmax=1)
        return cfg

    def test_stochastic_trend_and_disabled_parity(self):
        cfg = self.config()
        base = gs.simulate(self.grid, cfg)["PORO"]["values"]
        cfg["trends"] = {"PORO": dict(self.trend, depth_enabled=False, map_enabled=False)}
        np.testing.assert_array_equal(gs.simulate(self.grid, cfg)["PORO"]["values"], base)
        cfg["trends"]["PORO"] = self.trend
        result = gs.simulate(self.grid, cfg, surfaces=self.surfaces)["PORO"]["values"]
        np.testing.assert_allclose(result, base + trends.offset(self.grid, self.trend, self.surfaces))

    def test_conditioning_uses_residual_and_restores_exact_value(self):
        cfg = self.config()
        cfg["trends"] = {"PORO": self.trend}
        data = np.full(self.grid.actnum.shape, np.nan)
        data[0, 0, 0] = 0.31
        original = gs.prob_scores
        with patch.object(gs, "prob_scores", wraps=original) as scores:
            output = gs.simulate(self.grid, cfg, cond={"PORO": data}, surfaces=self.surfaces)
        np.testing.assert_allclose(scores.call_args.args[-1], [0.30])
        self.assertEqual(output["PORO"]["values"][0, 0, 0], 0.31)

    def test_job_execution_persistence_and_rollback(self):
        p = pj.Project(grid=self.grid, surfaces=self.surfaces)
        job = jobs.new_job("petrophysics", p)
        job["config"]["rows"] = self.rows()
        job["config"]["trends"] = {"PORO": self.trend}
        p.property_jobs = [job]
        restored = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(restored.property_jobs, p.property_jobs)
        restored.grid = self.grid
        jobs.run(restored)
        np.testing.assert_allclose(restored.properties["PORO"].values, [[[0.21, 0.23]], [[0.23, 0.25]]])
        before = dict(restored.properties)
        restored.property_jobs[0]["config"]["trends"]["PORO"]["map"] = "Missing"
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "No workflow outputs were committed"):
            jobs.run(restored)
        self.assertEqual(restored.properties, before)

    def test_saved_stochastic_job_and_transform_trends(self):
        p = pj.Project(grid=self.grid, surfaces=self.surfaces)
        job = jobs.new_job("stochastic", p)
        job["config"] = self.config()
        job["config"]["trends"] = {"PORO": self.trend}
        p.property_jobs = [job]
        jobs.run(p)
        direct = gs.simulate(self.grid, job["config"], surfaces=self.surfaces)
        np.testing.assert_allclose(p.properties["PORO"].values, direct["PORO"]["values"])
        cfg = self.config()
        cfg["props"]["PERM"]["enabled"] = True
        cfg["perm_mode"] = "transform"
        baseline = gs.simulate(self.grid, cfg)
        cfg["trends"] = {"PERM": dict(map_enabled=True, map="Trend", strength=2, reference=0)}
        output = gs.simulate(self.grid, cfg, surfaces=self.surfaces)
        np.testing.assert_allclose(output["PERMX"]["values"], baseline["PERMX"]["values"] + [[[10, 30]], [[10, 30]]])
        np.testing.assert_allclose(output["PERMZ"]["values"], output["PERMX"]["values"] * 0.1)

    def test_real_standalone_ui_trends_apply_and_persist(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string("""
import streamlit as st
import numpy as np
from core import project as pj
from core.surface import Geometry, Surface
from test_property_models import grid_fixture
from views.petrophysics import render_petrophysics
if 'p' not in st.session_state:
    st.session_state.p = pj.Project(grid=grid_fixture(), surfaces={
        'Trend': Surface('Trend', Geometry(0,0,10,10,3,2), np.tile([0,10,20],(2,1)).astype(float))})
render_petrophysics(st.session_state.p, st.session_state.p.grid)
""").run(timeout=30)
        self.assertFalse(app.exception)
        next(w for w in app.checkbox if w.label == "PORO: depth trend").check().run()
        self.assertFalse(app.exception)
        next(w for w in app.checkbox if w.label == "PORO: map trend").check().run()
        self.assertFalse(app.exception)
        next(w for w in app.number_input if w.label == "PORO: map strength (fraction per map unit)").set_value(0.002)
        next(w for w in app.button if w.label == "Model petrophysical properties").click().run()
        self.assertFalse(app.exception)
        p = app.session_state.p
        np.testing.assert_allclose(p.properties["PORO"].values, [[[0.21, 0.23]], [[0.21, 0.23]]])
        cfg = p.property_models["petrophysics|zone|"]["trends"]["PORO"]
        self.assertTrue(cfg["depth_enabled"] and cfg["map_enabled"])
        restored = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(restored.property_models, p.property_models)


if __name__ == "__main__":
    unittest.main()
