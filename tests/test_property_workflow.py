"""Executable property workflows: ordering, skips, rollback, persistence and real UI."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import project as pj, props as pp, property_workflow as jobs, geostat as gs, units as un
from core.surface import Geometry
from test_stochastic_facies import fixture
from streamlit.testing.v1 import AppTest


def pipeline():
    grid, _, _ = fixture()
    p = pj.Project(grid=grid)
    facies = jobs.new_job("facies", p)
    facies["config"]["output"] = "FACIES"
    calc = jobs.new_job("calculator", p)
    calc["config"]["code"] = "FACIES = where(FACIES == 2, 3, FACIES)"
    petro = jobs.new_job("petrophysics", p)
    petro["config"].update(domain="zone_facies", facies="FACIES", rows=[
        dict(zone=i + 1, code=c, label=f"{z.name}/{c}", poro=0.05 if c == 1 else 0.25, permx=1 if c == 1 else 100,
             ntg=0 if c == 1 else 1, kykx=1, kvkh=0.1) for i, z in enumerate(grid.zones) for c in (1, 3)])
    sw = jobs.new_job("saturation", p)
    p.property_jobs = [facies, calc, petro, sw]
    return p


class PropertyWorkflowTests(unittest.TestCase):
    def test_facies_calculator_petrophysics_saturation_chain(self):
        p = pipeline()
        reports = jobs.run(p)
        self.assertEqual([r["status"] for r in reports], ["Completed"] * 4)
        self.assertEqual(set(p.properties), {"FACIES", "PORO", "PERMX", "PERMY", "PERMZ", "NTG", "SW"})
        facies = p.properties["FACIES"].values
        self.assertNotIn(2, facies[p.grid.actnum > 0])
        self.assertTrue(np.isin(facies[p.grid.actnum > 0], [1, 3]).all())
        np.testing.assert_allclose(p.properties["PORO"].values[facies == 1], 0.05)
        np.testing.assert_allclose(p.properties["PORO"].values[facies == 3], 0.25)
        self.assertTrue(((p.properties["SW"].values[p.grid.actnum > 0] >= 0) &
                         (p.properties["SW"].values[p.grid.actnum > 0] <= 1)).all())

    def test_disabled_job_is_skipped_even_with_invalid_configuration(self):
        p = pipeline()
        disabled = jobs.new_job("calculator", p)
        disabled.update(enabled=False, config=dict(code="import os"))
        p.property_jobs.insert(2, disabled)
        report = jobs.run(p)
        self.assertEqual(report[2]["status"], "Skipped")
        self.assertIn("SW", p.properties)

    def test_missing_upstream_job_reports_failure_and_rolls_back(self):
        p = pipeline()
        p.properties["EXISTING"] = pp.make_property(p.grid, "EXISTING", 17)
        p.property_jobs[0]["enabled"] = False
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "Job 2.*No workflow outputs were committed"):
            jobs.run(p)
        self.assertEqual(list(p.properties), ["EXISTING"])
        np.testing.assert_equal(p.properties["EXISTING"].values, 17)

    def test_late_failure_does_not_commit_any_earlier_outputs(self):
        p = pipeline()
        p.property_jobs[-1]["config"]["rows"][0]["entry"] = -1
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "Job 4"):
            jobs.run(p)
        self.assertFalse(p.properties)

    def test_calculator_retains_restrictions_and_discrete_validation(self):
        p = pipeline()
        p.property_jobs[1]["config"]["code"] = "import os"
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "not allowed"):
            jobs.run(p)
        p.property_jobs[1]["config"]["code"] = "FACIES = FACIES + 0.5"
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "non-integer"):
            jobs.run(p)
        p.property_jobs[1]["config"]["code"] = "FACIES = FACIES / 0"
        with self.assertRaisesRegex(jobs.PropertyWorkflowError, "non-finite"):
            jobs.run(p)

    def test_facies_definitions_reject_noninteger_codes_without_rounding(self):
        for code in (1.5, np.nan, np.inf):
            with self.subTest(code=code):
                p = pipeline()
                p.property_jobs[0]["config"]["facies"][0]["code"] = code
                with self.assertRaisesRegex(jobs.PropertyWorkflowError, "Facies codes must be finite integers"):
                    jobs.run(p)
                self.assertFalse(p.properties)

    def test_jobs_snapshot_configurations_and_survive_roundtrip(self):
        p = pipeline()
        p.stochastic = gs.default_config(p.grid)
        job = jobs.new_job("stochastic", p)
        job["config"]["seed"] = 12
        self.assertEqual(p.stochastic["seed"], 42)
        p.property_jobs.append(job)
        p.property_jobs[1]["enabled"] = False
        saved = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(saved.property_jobs, p.property_jobs)
        old = pj.from_bytes(pj.to_bytes(pj.Project()))
        self.assertEqual(old.property_jobs, [])

    def test_job_dimensions_and_contact_snapshots_convert_with_units(self):
        p = pipeline()
        p.property_jobs.append(jobs.new_job("stochastic", p))
        before = p.property_jobs[0]["config"]["zones"][0]["major"]
        entry = p.property_jobs[3]["config"]["rows"][0]["entry"]
        owc = p.property_jobs[3]["config"]["contacts"]["contacts"]["owc"]
        un.convert_project(p, "ft", "ft")
        factor = 1 / 0.3048
        self.assertAlmostEqual(p.property_jobs[0]["config"]["zones"][0]["major"], before * factor)
        self.assertAlmostEqual(p.property_jobs[3]["config"]["rows"][0]["entry"], entry * factor)
        self.assertAlmostEqual(p.property_jobs[3]["config"]["contacts"]["contacts"]["owc"], owc * factor)
        self.assertAlmostEqual(p.property_jobs[4]["config"]["props"]["PORO"]["rows"][0]["major"], 80 * factor)

    def test_stochastic_uses_calculator_facies_instead_of_original_model(self):
        p = pipeline()
        stoch = jobs.new_job("stochastic", p)
        stoch["config"].update(domain="zone_facies", facies="FACIES")
        for name, pc in stoch["config"]["props"].items():
            pc["facies_source"] = "FACIES"
            pc["facies_rows"] = [dict(row, code=c, facies=str(c),
                p1=(0.05 if c == 1 else 0.25) if name == "PORO" else (1 if c == 1 else 100) if name == "PERM" else (0 if c == 1 else 1))
                for row in pc["rows"] for c in (1, 3)]
        p.property_jobs[2] = stoch
        jobs.run(p)
        facies = p.properties["FACIES"].values
        for code, target in ((1, 0.05), (3, 0.25)):
            self.assertAlmostEqual(float(p.properties["PORO"].values[facies == code].mean()), target, delta=0.01)

    def test_real_ui_inserts_skips_reorders_and_runs_calculator_jobs(self):
        app = AppTest.from_string("""
import streamlit as st
from core.project import Project
from core import property_workflow as jobs
from test_stochastic_facies import fixture
from views.property_workflow import render
if "p" not in st.session_state:
    grid, props, _ = fixture()
    p = Project(grid=grid, properties=props)
    p.property_jobs = [jobs.new_job("calculator", p)]
    st.session_state["p"] = p
render(st.session_state["p"])
""").run(timeout=30)
        self.assertFalse(app.exception)
        next(b for b in app.checkbox if b.label == "Allow workflow jobs to replace existing output properties").check().run(timeout=30)
        next(b for b in app.button if b.label == "Run property workflow").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertIn("FACIES_COPY", app.session_state["p"].properties)
        next(b for b in app.button if b.label == "Insert job").click().run(timeout=30)
        self.assertFalse(app.exception)
        p = app.session_state["p"]
        self.assertEqual(len(p.property_jobs), 2)
        next(c for c in app.checkbox if c.label == "Active").uncheck().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.session_state["p"].property_jobs[0]["enabled"])
        second_id = p.property_jobs[1]["id"]
        [b for b in app.button if b.label == "Move up"][1].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["p"].property_jobs[0]["id"], second_id)

    def test_real_ui_configures_all_job_types_and_runs_the_saved_pipeline(self):
        app = AppTest.from_string("""
import streamlit as st
from test_property_workflow import pipeline
from core import property_workflow as jobs
from views.property_workflow import render
if "p" not in st.session_state:
    p = pipeline()
    stochastic = jobs.new_job("stochastic", p)
    stochastic["enabled"] = False
    p.property_jobs.append(stochastic)
    st.session_state["p"] = p
render(st.session_state["p"])
""").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(len([b for b in app.button if b.label == "Save job configuration"]), 5)
        [b for b in app.button if b.label == "Save job configuration"][1].click().run(timeout=30)
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label == "Run property workflow").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertIn("SW", app.session_state["p"].properties)

    def test_property_dropdown_replaces_long_object_lists(self):
        app = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")).run(timeout=30)
        grid, props, _ = fixture()
        p = app.session_state["proj"]
        p.grid = grid
        p.lattice = Geometry(float(grid.xs[0]), float(grid.ys[0]), 10, 10, grid.ni + 1, grid.nj + 1)
        p.properties = props
        p.properties["PORO"] = pp.make_property(grid, "PORO", 0.25)
        app.run(timeout=30)
        dropdown = next(s for s in app.selectbox if s.label == "3D properties")
        dropdown.select("PORO").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["focus"], ("prop", "PORO"))
        self.assertEqual(app.session_state["nav"], "Properties")
        self.assertFalse(any(b.label in ("● FACIES", "● PORO") for b in app.button))
        mesh = next(c for c in app.checkbox if c.label == "Black mesh edges")
        self.assertFalse(mesh.value)
        mesh.check().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(next(c for c in app.checkbox if c.label == "Black mesh edges").value)


if __name__ == "__main__":
    unittest.main()
