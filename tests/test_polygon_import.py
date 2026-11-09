"""RMS polygon import and isolation from existing surface data."""
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from core import io_surfaces, package, polygons, project


RMS = b"""\
500000 6700000 1234
500100 6700000 1235
500100 6700100 1236
500000 6700000 1234
999.00 999.00 999.00
500200 6700000 0
500300 6700000 0
500300 6700100 0
999.00 999.00 999.00
"""

APP = """
import numpy as np
import streamlit as st
from unittest.mock import patch
from core import project
from core.surface import Geometry, Surface
from core.polygons import Polygon
from ui import state as S
from views import polygons

class Upload:
    name = "map.POL"
    def getvalue(self):
        return %r

if "proj" not in st.session_state:
    g = Geometry(500000, 6700000, 100, 100, 3, 3)
    p = project.Project(lattice=g)
    p.put_surface(Surface("map", g, np.ones(g.shape)))
    p.filters["map"]["ops"] = [{"type": "range", "min": 0, "max": 10, "enabled": True}]
    p.surfaces["map"].z[:] = 7
    p.polygons["existing"] = Polygon("existing", [[0, 0], [1, 0], [1, 1]])
    p.boundary = "existing"
    p.structure = object()
    p.grid = object()
    st.session_state["proj"] = p
with patch.object(st, "file_uploader", return_value=[Upload()]):
    polygons._import(S.proj())
""" % RMS


class RmsPolygonTests(unittest.TestCase):
    def test_polygon_files_are_rejected_by_surface_import(self):
        for filename in ("map.POL", "map.rmspolygons"):
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "Polygons page"):
                io_surfaces.read_any(RMS, filename)

    def test_surface_import_shows_polygon_error_without_overwriting(self):
        source = APP.replace("from views import polygons", "from views import surfaces")
        source = source.replace("polygons._import(S.proj())", "surfaces._import(S.proj())")
        app = AppTest.from_string(source).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Polygons page" in error.value for error in app.error))
        self.assertFalse(any(button.label == "Grid points into a surface" for button in app.button))
        np.testing.assert_array_equal(app.session_state["proj"].surfaces["map"].z, np.full((3, 3), 7))

    def test_multiple_parts_and_closure(self):
        result = polygons.parse_rms_pol(RMS, "map")
        self.assertEqual(list(result), ["map_1", "map_2"])
        self.assertEqual(result["map_1"].pts, [[500000, 6700000], [500100, 6700000], [500100, 6700100]])
        self.assertEqual(result["map_2"].bounds(), (500200, 500300, 6700000, 6700100))

    def test_package_format_and_valid_999_xy(self):
        data = package.rms_polylines({"part": np.array([[999, 999, 1], [1000, 999, 2], [1000, 1000, 3]])})
        result = polygons.parse_rms_pol(data.encode(), "part")
        self.assertEqual(result["part_1"].pts[0], [999, 999])

    def test_final_part_without_separator_and_invalid_parts(self):
        self.assertEqual(len(polygons.parse_rms_pol(b"0 0 0\n1 0 0\n1 1 0\n")), 1)
        for data in (b"0 0 0\n1 1 0\n999 999 999\n",
                     b"0 0 0\n1 broken 0\n", b"0 0 0\n1 0 inf\n",
                     b"0 0\n1 0\n1 1\n"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                polygons.parse_rms_pol(data)

    def test_import_preserves_surface_and_derived_objects(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        structure, grid, lattice = p.structure, p.grid, p.lattice
        raw = p.raw["map"].copy()
        before = p.surfaces["map"].z.copy()
        next(b for b in app.button if b.label == "Add to project").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(set(p.polygons), {"existing", "map_1", "map_2"})
        self.assertEqual(p.boundary, "existing")
        self.assertIs(p.structure, structure)
        self.assertIs(p.grid, grid)
        self.assertIs(p.lattice, lattice)
        np.testing.assert_array_equal(p.raw["map"], raw)
        np.testing.assert_array_equal(p.surfaces["map"].z, before)
        self.assertEqual(p.filters["map"]["ops"][0]["type"], "range")
        saved = project.from_bytes(project.to_bytes(p))
        np.testing.assert_array_equal(saved.surfaces["map"].z, before)
        self.assertEqual(saved.polygons["map_1"].pts, p.polygons["map_1"].pts)

    def test_explicit_boundary_and_xy_unit_conversion(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        structure = p.structure
        next(w for w in app.selectbox if w.label == "XY unit in file").select("ft").run()
        next(w for w in app.checkbox if w.label == "Use the first polygon as model boundary").check().run()
        next(b for b in app.button if b.label == "Add to project").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(p.boundary, "map_1")
        self.assertIsNone(p.grid)
        self.assertIs(p.structure, structure)
        np.testing.assert_allclose(p.polygons["map_1"].pts[0], np.array([500000, 6700000]) * 0.3048)
        np.testing.assert_array_equal(p.surfaces["map"].z, np.full((3, 3), 7))


if __name__ == "__main__":
    unittest.main()
