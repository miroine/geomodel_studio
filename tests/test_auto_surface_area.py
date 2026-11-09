"""Automatic model-area setup when a regular grid is imported."""
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from core import project


APP = """
import numpy as np
import streamlit as st
from unittest.mock import patch
from core.surface import Geometry, Surface
from core import project, io_surfaces
from ui import state as S
from views import surfaces, home
class Upload:
    name = "map.gri"
    def getvalue(self):
        geom = Geometry(100, 200, 10, 20, 4, 3, 30)
        surface = Surface("input", geom, np.full(geom.shape, 2000.0))
        return io_surfaces.write_irap_binary_py(surface)
if "proj" not in st.session_state:
    st.session_state["proj"] = project.Project()
    st.session_state["proj"].crs["epsg"] = 32631
with patch.object(st, "file_uploader", side_effect=lambda label, **kw: [Upload()] if label == "Surface files" else None):
    p = S.proj()
    surfaces._import(p)
    home.render()
"""


class AutomaticSurfaceAreaTests(unittest.TestCase):
    def test_import_sets_area_and_refreshes_existing_project_widgets(self):
        app = AppTest.from_string(APP).run()
        self.assertFalse(app.exception)
        p = app.session_state["proj"]
        self.assertIsNone(p.lattice)
        self.assertEqual(next(w.value for w in app.number_input if w.label == "X min"), 0)
        next(w for w in app.selectbox if w.label == "XY unit in file").select("ft").run()
        next(b for b in app.button if b.label == "Add to library").click().run()
        self.assertFalse(app.exception)
        self.assertIsNotNone(p.lattice)
        source = p.surfaces["map"]
        np.testing.assert_allclose(p.lattice.bounds(), source.geom.bounds(), atol=1e-8)
        self.assertEqual(p.crs["epsg"], 32631)
        self.assertEqual(next(w.value for w in app.number_input if w.label == "X min"), p.lattice.xori)
        self.assertTrue(project.from_bytes(project.to_bytes(p)).lattice.same_lattice(p.lattice))

    def test_existing_area_untouched_unless_explicitly_replaced(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        next(b for b in app.button if b.label == "Add to library").click().run()
        original = p.lattice
        p.lattice = type(original)(0, 0, 100, 100, 3, 3)
        app.run()
        checkbox = next(c for c in app.checkbox if c.label == "Replace existing model area with this surface on import")
        self.assertFalse(checkbox.value)
        next(b for b in app.button if b.label == "Add to library").click().run()
        self.assertEqual(p.lattice.xori, 0)
        next(c for c in app.checkbox if c.label == "Replace existing model area with this surface on import").check().run()
        next(b for b in app.button if b.label == "Add to library").click().run()
        self.assertFalse(app.exception)
        np.testing.assert_allclose(p.lattice.bounds(), p.surfaces["map"].geom.bounds())
        app.run()
        self.assertFalse(next(c for c in app.checkbox if c.label == "Replace existing model area with this surface on import").value)

    def test_oversized_and_invalid_surfaces_are_imported_without_setting_area(self):
        for geom, shape, warning in (
            ("Geometry(100, 200, 10, 20, 700, 700, 0)", "(700, 700)", "exceeds 400,000"),
            ("Geometry(100, 200, 10, 20, 4, 1, 0)", "(1, 4)", "at least two rows"),
        ):
            with self.subTest(geom=geom):
                source = APP.replace("Geometry(100, 200, 10, 20, 4, 3, 30)", geom).replace(
                    "np.full(geom.shape, 2000.0)", f"np.full({shape}, 2000.0)")
                app = AppTest.from_string(source).run(timeout=30)
                next(b for b in app.button if b.label == "Add to library").click().run(timeout=30)
                p = app.session_state["proj"]
                self.assertIn("map", p.surfaces)
                self.assertIsNone(p.lattice)
                self.assertTrue(any(warning in msg.value for msg in list(app.warning) + list(app.error)))


if __name__ == "__main__":
    unittest.main()
