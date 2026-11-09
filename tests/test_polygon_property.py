"""Polygon property assignment in the library and ordered workflows."""
import os
import sys
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import polygon_property, project, property_workflow, props
from core.polygons import Polygon
from test_stochastic_facies import fixture


def setup():
    grid, properties, _ = fixture()
    poly = Polygon("West", [[5, 5], [55, 5], [55, 75], [5, 75]])
    return project.Project(grid=grid, properties=properties, polygons={poly.name: poly}), poly


class PolygonPropertyTests(unittest.TestCase):
    def test_sides_edges_layers_inactive_and_metadata(self):
        p, poly = setup()
        original = p.properties["FACIES"]
        cfg = dict(output="FACIES", mode="inside", inside=9)
        changed = polygon_property.assign(p.grid, p.properties, poly, cfg)
        x, y = p.grid.center_xy()
        # Boundary points, including corners, are inside.
        inside = (x >= 5) & (x <= 55) & (y >= 5) & (y <= 75)
        active = p.grid.actnum > 0
        mask = active & inside[None]
        np.testing.assert_equal(changed.values[mask], 9)
        np.testing.assert_equal(changed.values[~mask], original.values[~mask])
        self.assertEqual(changed.legend, original.legend)
        self.assertEqual(changed.kind, "discrete")
        self.assertEqual(original.values[1, 0, 0], 1)
        cfg.update(mode="outside", outside=4)
        changed = polygon_property.assign(p.grid, p.properties, poly, cfg)
        outside = active & ~inside[None]
        np.testing.assert_equal(changed.values[outside], 4)
        np.testing.assert_equal(changed.values[~outside], original.values[~outside])

    def test_create_both_and_validation(self):
        p, poly = setup()
        cfg = dict(output="PORO", mode="both", inside=0.25, outside=0.05, kind="continuous", unit="frac")
        result = polygon_property.assign(p.grid, p.properties, poly, cfg)
        self.assertTrue(np.isnan(result.values[0, 0, 0]))
        self.assertAlmostEqual(result.values[1, 0, 0], 0.25)
        self.assertAlmostEqual(result.values[1, 0, -1], 0.05)
        self.assertEqual(result.unit, "frac")
        with self.assertRaisesRegex(ValueError, "requires an existing"):
            polygon_property.assign(p.grid, p.properties, poly, dict(cfg, mode="inside"))
        with self.assertRaisesRegex(ValueError, "integer"):
            polygon_property.assign(p.grid, p.properties, poly, dict(cfg, kind="discrete"))
        with self.assertRaisesRegex(ValueError, "represented exactly"):
            polygon_property.assign(p.grid, p.properties, poly, dict(cfg, kind="discrete", inside=16777217, outside=1))
        with self.assertRaisesRegex(ValueError, "finite"):
            polygon_property.assign(p.grid, p.properties, poly, dict(cfg, inside=np.nan))
        with self.assertRaisesRegex(ValueError, "missing"):
            polygon_property.assign(p.grid, p.properties, None, cfg)
        with self.assertRaisesRegex(ValueError, "non-zero"):
            polygon_property.assign(p.grid, p.properties, Polygon("bad", [[0, 0], [1, 1], [2, 2]]), cfg)
        p.properties["FACIES"].stale = True
        with self.assertRaisesRegex(ValueError, "stale"):
            polygon_property.assign(p.grid, p.properties, poly, dict(cfg, output="FACIES"))
        result.stale = True
        props.recompute_stale({"PORO": result}, p.grid)
        self.assertTrue(result.stale)

    def test_workflow_order_rollback_and_persistence(self):
        p, poly = setup()
        first = property_workflow.new_job("calculator", p)
        first["config"].update(code="PORO = 0.1", result_kind="continuous")
        job = property_workflow.new_job("polygon", p)
        job["config"].update(output="PORO", polygon=poly.name, mode="inside", inside=0.3)
        p.property_jobs = [first, job]
        saved = project.from_bytes(project.to_bytes(p))
        self.assertEqual(saved.property_jobs, p.property_jobs)
        property_workflow.run(p)
        self.assertAlmostEqual(p.properties["PORO"].values[1, 0, 0], 0.3)
        self.assertAlmostEqual(p.properties["PORO"].values[1, 0, -1], 0.1)
        original = p.properties["PORO"]
        del p.polygons[poly.name]
        with self.assertRaisesRegex(property_workflow.PropertyWorkflowError, "No workflow outputs were committed"):
            property_workflow.run(p)
        self.assertIs(p.properties["PORO"], original)

    def test_library_tool_and_workflow_ui(self):
        app = AppTest.from_string("""
import streamlit as st
from core.project import Project
from core.polygons import Polygon
from core.surface import Geometry
from test_stochastic_facies import fixture
from views.properties import render
if "proj" not in st.session_state:
    g, props, _ = fixture()
    st.session_state["proj"] = Project(grid=g, lattice=Geometry(0, 0, 10, 10, 13, 9), properties=props, polygons={
        "West": Polygon("West", [[5, 5], [55, 5], [55, 75], [5, 75]])})
render()
""").run(timeout=30)
        self.assertFalse(app.exception)
        next(w for w in app.text_input if w.label == "Property name").set_value("NEWPROP").run(timeout=30)
        next(b for b in app.button if b.label == "Apply polygon assignment").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertIn("NEWPROP", app.session_state["proj"].properties)
        next(s for s in app.selectbox if s.label == "Assign values" and s.key.startswith("pr_poly_")).select("outside").run(timeout=30)
        next(w for w in app.number_input if w.label == "Value outside polygon" and w.key.startswith("pr_poly_")).set_value(0.7).run(timeout=30)
        next(c for c in app.checkbox if c.label == "Replace the existing property with this assignment").check().run(timeout=30)
        next(b for b in app.button if b.label == "Apply polygon assignment").click().run(timeout=30)
        values = app.session_state["proj"].properties["NEWPROP"].values
        self.assertAlmostEqual(values[1, 0, 0], 0.2)
        self.assertAlmostEqual(values[1, 0, -1], 0.7)
        next(s for s in app.selectbox if s.label == "New property job").select("polygon").run(timeout=30)
        next(b for b in app.button if b.label == "Insert job").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["proj"].property_jobs[0]["type"], "polygon")
        self.assertEqual(len(app.session_state["proj"].property_jobs), 3)
        self.assertEqual(len([s for s in app.selectbox if s.label == "Assignment polygon"]), 4)
        job_name = [w for w in app.text_input if w.label == "Property name" and w.key.startswith("pj_")][-1]
        job_name.set_value("WORKPROP").run(timeout=30)
        [b for b in app.button if b.label == "Save job configuration"][-1].click().run(timeout=30)
        self.assertEqual(app.session_state["proj"].property_jobs[-1]["config"]["output"], "WORKPROP")
        next(c for c in app.checkbox if c.label == "Allow workflow jobs to replace existing output properties").check().run(timeout=30)
        next(b for b in app.button if b.label == "Run property workflow").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertIn("WORKPROP", app.session_state["proj"].properties)


if __name__ == "__main__":
    unittest.main()
