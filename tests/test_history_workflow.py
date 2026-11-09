"""Successful standalone runs become persistent executable workflow steps."""
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from core import property_history as H, property_workflow as W, project, props, units
from test_property_models import grid_fixture


class HistoryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.p = project.Project(grid=grid_fixture())

    def test_order_snapshot_rerun_and_roundtrip(self):
        H.record(self.p, "Constant property", dict(name="INPUT", value=0.25, kind="continuous", unit="frac"), ["INPUT"])
        settings = dict(code="OUTPUT = INPUT * 2", output="OUTPUT", kind="continuous", unit="frac")
        H.record(self.p, "Python calculator", settings, ["OUTPUT"])
        settings["code"] = "OUTPUT = 0"
        self.assertEqual([j["type"] for j in self.p.property_jobs], ["tool", "calculator"])
        self.assertTrue(all(j["enabled"] for j in self.p.property_jobs))
        p = project.from_bytes(project.to_bytes(self.p))
        p.grid = self.p.grid
        W.run(p)
        np.testing.assert_allclose(p.properties["OUTPUT"].values, 0.5)
        self.assertEqual(len(p.property_jobs), 2)
        self.assertEqual(len(p.property_history), 4)
        p.property_jobs[0]["config"]["settings"]["value"] = 0.4
        W.run(p)
        np.testing.assert_allclose(p.properties["OUTPUT"].values, 0.8)
        self.assertEqual(p.property_history[0]["settings"]["value"], 0.25)
        self.assertEqual(len(p.property_jobs), 2)

    def test_failures_and_restore_old_history_are_not_duplicated(self):
        H.record(self.p, "Python calculator", dict(code="BAD = MISSING", kind="continuous"), [], status="Failed")
        self.assertEqual(self.p.property_jobs, [])
        H.record(self.p, "Python calculator", dict(code="VALUE = 2", kind="continuous"), ["VALUE"])
        self.p.property_jobs.clear()
        self.p.property_history[-1]["job_id"] = None
        self.assertEqual(W.restore_history(self.p), 1)
        self.assertEqual(W.restore_history(self.p), 0)
        W.run(self.p)
        self.assertEqual(len(self.p.property_jobs), 1)
        H.record(self.p, "Python calculator", dict(code="NEXT = MISSING", kind="continuous"), ["NEXT"])
        before = self.p.properties["VALUE"].values.copy()
        with self.assertRaises(W.PropertyWorkflowError):
            W.run(self.p)
        np.testing.assert_array_equal(self.p.properties["VALUE"].values, before)
        self.assertEqual(len(self.p.property_jobs), 2)
        self.assertEqual(self.p.property_history[-1]["status"], "Failed")

    def test_zone_geometry_planes_and_contacts_replay(self):
        g = self.p.grid
        H.record(self.p, "Zone table properties", dict(zones=[z.to_dict() for z in g.zones]), props.ZONE_PROPS)
        H.record(self.p, "Generate geometric properties", dict(properties=["DEPTH", "ZONE"]), ["DEPTH", "ZONE"])
        H.record(self.p, "Plane properties", dict(planes=[["Test", 1010]], depth_unit="m"), [])
        from core import volumetrics as V
        cfg = V.default_config(g)
        H.record(self.p, "Contact properties", dict(volumetrics=cfg), [])
        H.record(self.p, "Fault-block region and segments", dict(mode="zone x fault block", volumetrics=cfg), [])
        W.run(self.p)
        self.assertIn("PORO", self.p.properties)
        self.assertIn("FLUID", self.p.properties)
        self.assertIn("SEGMENT", self.p.properties)
        original_depth = self.p.property_jobs[2]["config"]["settings"]["planes"][0][1]
        units.convert_project(self.p, "m", "ft")
        self.assertAlmostEqual(self.p.property_jobs[2]["config"]["settings"]["planes"][0][1], original_depth / 0.3048)
        units.set_active(units.DEFAULT_CRS)

    def test_existing_history_crs_mismatch_rejected_atomically(self):
        H.record(self.p, "Constant property", dict(name="X", value=1, kind="continuous", unit=""), ["X"])
        self.p.property_jobs.clear()
        self.p.property_history[0]["job_id"] = None
        self.p.crs["epsg"] = 32631
        with self.assertRaisesRegex(W.PropertyWorkflowError, "CRS/units"):
            W.restore_history(self.p)
        self.assertEqual(self.p.property_jobs, [])

    def test_sparse_blocking_then_kriging_and_missing_well_rollback(self):
        from core.wells import Well
        self.p.wells["A"] = Well("A", 5, 5, td=1100)
        self.p.logs["A"] = dict(md=np.array([1005, 1015]), curves={"PHI": np.array([0.2, 0.3])},
                                units={"PHI": "frac"})
        H.record(self.p, "Block well logs", dict(curve="PHI", discrete=False, average="arithmetic",
                                                output="PHI_BLK", wells=["A"]), ["PHI_BLK"])
        H.record(self.p, "Simple kriging", dict(input="PHI_BLK", output="PHI_KRG", variogram=dict(
            vtype="spherical", major=100, minor=100, vert=100, nugget=0), azimuth=0,
            neighbours=4, normal_score=False), ["PHI_KRG"])
        W.run(self.p)
        self.assertTrue(np.isnan(self.p.properties["PHI_BLK"].values).any())
        self.assertTrue(np.isfinite(self.p.properties["PHI_KRG"].values).all())
        previous = self.p.properties["PHI_KRG"].values.copy()
        del self.p.wells["A"]
        with self.assertRaisesRegex(W.PropertyWorkflowError, "missing"):
            W.run(self.p)
        np.testing.assert_array_equal(self.p.properties["PHI_KRG"].values, previous)

    def test_library_run_reappears_as_active_step_and_runs_from_workflow(self):
        app = AppTest.from_string("""
import streamlit as st
from core.project import Project
from test_property_models import grid_fixture
from views.properties import _calculator
from views.property_workflow import render
if "p" not in st.session_state:
    st.session_state["p"] = Project(grid=grid_fixture())
p = st.session_state["p"]
_calculator(p, p.grid, named=False)
render(p)
""").run()
        next(w for w in app.text_area if w.label == "Script").set_value("REPLAY = 0.3").run()
        next(b for b in app.button if b.label == "Run and store").click().run()
        self.assertFalse(app.exception)
        p = app.session_state["p"]
        self.assertEqual(len(p.property_jobs), 1)
        self.assertTrue(any(w.label == "Active" and w.value for w in app.checkbox))
        next(w for w in app.checkbox if w.label == "Allow workflow jobs to replace existing output properties").check().run()
        next(b for b in app.button if b.label == "Run property workflow").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(p.property_jobs), 1)
        np.testing.assert_allclose(p.properties["REPLAY"].values, 0.3)


if __name__ == "__main__":
    unittest.main()
