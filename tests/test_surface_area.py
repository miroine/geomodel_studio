"""Model-area selection from imported surface geometry."""
import os
import sys
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import io_surfaces, project, units
from core.surface import Geometry, Surface, surface_area_values


APP = """
import streamlit as st
from views.home import render
render()
"""


class SurfaceAreaTests(unittest.TestCase):
    def test_imported_unrotated_and_rotated_bounds(self):
        for rotation in (0, 30, -45):
            with self.subTest(rotation=rotation):
                original = Geometry(100, 200, 10, 20, 6, 4, rotation)
                surface = Surface("Imported", original, np.ones(original.shape))
                imported = io_surfaces.read_irap_ascii_py(io_surfaces.write_irap_ascii(surface))
                imported = units.scale_surface(imported, 0.3048, 1)
                xmin, xmax, ymin, ymax, dx, dy = surface_area_values(imported.geom)
                lattice = Geometry.from_bounds(xmin, xmax, ymin, ymax, dx, dy)
                np.testing.assert_allclose(lattice.bounds(), imported.geom.bounds(), atol=1e-9)
                self.assertLessEqual(dx, imported.geom.xinc + 1e-9)
                self.assertLessEqual(dy, imported.geom.yinc + 1e-9)

    def test_invalid_surface_geometry(self):
        for geom in (Geometry(0, 0, 1, 1, 1, 3), Geometry(0, 0, 0, 1, 3, 3),
                     Geometry(float("nan"), 0, 1, 1, 3, 3)):
            with self.subTest(geom=geom), self.assertRaises(ValueError):
                surface_area_values(geom)

    def test_load_and_apply_area_and_preserve_existing_results_until_applied(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        geom = Geometry(100.125, 200.25, 0.5, 0.75, 4, 3)
        p.put_surface(Surface("Other", Geometry(0, 0, 10, 10, 3, 3), np.ones((3, 3))))
        p.put_surface(Surface("Imported", geom, np.ones(geom.shape)))
        p.lattice = Geometry(0, 0, 10, 10, 3, 3)
        p.structure = object()
        app.run()
        next(w for w in app.selectbox if w.label == "Surface for model area").select("Imported").run()
        next(b for b in app.button if b.label == "Load area from surface").click().run()
        self.assertFalse(app.exception)
        self.assertIsNotNone(p.structure)
        self.assertEqual(p.lattice.xori, 0)
        for label, expected in (("X min", 100.125), ("X max", 101.625),
                                ("Y min", 200.25), ("Y max", 201.75),
                                ("dx (m)", 0.5), ("dy (m)", 0.75)):
            self.assertAlmostEqual(next(w.value for w in app.number_input if w.label == label), expected)
        next(b for b in app.button if b.label == "Set model area").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(p.lattice.same_lattice(geom))
        self.assertIsNone(p.structure)
        self.assertIn("Imported", p.surfaces)
        self.assertTrue(project.from_bytes(project.to_bytes(p)).lattice.same_lattice(geom))

    def test_invalid_surface_reports_error_without_changing_area(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        geom = Geometry(0, 0, 1, 1, 1, 2)
        p.put_surface(Surface("Invalid", geom, np.ones(geom.shape)))
        app.run()
        next(b for b in app.button if b.label == "Load area from surface").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("at least two rows and two columns" in e.value for e in app.error))
        self.assertIsNone(p.lattice)

    def test_large_surface_remains_editable_but_cannot_be_applied(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        geom = Geometry(0, 0, 1, 1, 700, 700)
        p.put_surface(Surface("Large", geom, np.ones(geom.shape)))
        app.run()
        next(b for b in app.button if b.label == "Load area from surface").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(next(b for b in app.button if b.label == "Set model area").disabled)
        self.assertIsNone(p.lattice)
        next(w for w in app.number_input if w.label == "dx (m)").set_value(2.0)
        next(w for w in app.number_input if w.label == "dy (m)").set_value(2.0).run()
        self.assertFalse(next(b for b in app.button if b.label == "Set model area").disabled)


if __name__ == "__main__":
    unittest.main()
