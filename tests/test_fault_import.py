"""Import polygon files as open fault traces without replacing existing objects."""
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from core import polygons, project


RMS = b"100 200 3000\n110 210 3100\n999 999 999\n120 200 3200\n130 210 3300\n140 200 3400\n999 999 999\n"
XY = b"> First\n100 200\n110 210\n\n> Second\n120 200\n130 210\n140 200\n"
APP = """
import numpy as np
import streamlit as st
from unittest.mock import patch
from core.project import Project
from core.faults import Fault
from core.surface import Geometry, Surface
from ui import state as S
from views import faults

class Upload:
    name = "input.POL"
    def getvalue(self):
        return %r

if "proj" not in st.session_state:
    p = Project(lattice=Geometry(100, 200, 10, 10, 6, 6))
    p.put_surface(Surface("map", p.lattice, np.full((6, 6), 2000.0)))
    p.faults["input_1"] = Fault("input_1", [[100, 200], [100, 210]])
    p.structure, p.grid = object(), object()
    st.session_state["proj"] = p
with patch.object(st, "file_uploader", return_value=[Upload()]):
    faults._import(S.proj())
""" % RMS


class FaultImportTests(unittest.TestCase):
    def test_parsers_accept_two_points_and_preserve_explicit_closure(self):
        rms = polygons.parse_rms_pol(RMS, "input", closed=False)
        self.assertEqual(len(rms["input_1"].pts), 2)
        self.assertEqual(len(rms), 2)
        xy = polygons.parse(XY, closed=False)
        self.assertEqual(list(xy), ["First", "Second"])
        self.assertEqual(xy["First"].pts, rms["input_1"].pts)
        loop = b"0 0\n10 0\n10 10\n0 0\n"
        self.assertEqual(polygons.parse(loop, closed=False)["Polygon_1"].pts[-1], [0, 0])
        self.assertEqual(len(polygons.parse(loop)["Polygon_1"].pts), 3)
        with self.assertRaises(ValueError):
            polygons.parse_rms_pol(b"1 1 1\n1 1 1\n", closed=False)

    def test_import_parameters_units_names_workflow_and_persistence(self):
        app = AppTest.from_string(APP).run()
        p = app.session_state["proj"]
        original = p.faults["input_1"]
        before = p.surfaces["map"].z.copy()
        next(w for w in app.selectbox if w.label == "Fault XY unit in file").select("ft").run()
        next(w for w in app.selectbox if w.label == "Imported fault type").select("reverse").run()
        next(w for w in app.selectbox if w.label == "Imported hanging-wall side").select("right").run()
        next(w for w in app.number_input if w.label.startswith("Imported throw (")).set_value(80.0).run()
        next(w for w in app.number_input if w.label.startswith("Imported reference depth")).set_value(3000.0).run()
        next(b for b in app.button if b.label == "Import as faults").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(set(p.faults), {"input_1", "input_1_2", "input_2"})
        self.assertIs(p.faults["input_1"], original)
        fault = p.faults["input_1_2"]
        np.testing.assert_allclose(fault.trace, np.array([[100, 200], [110, 210]]) * 0.3048)
        self.assertEqual((fault.ftype, fault.hw_side, fault.throw, fault.zref), ("reverse", "right", 80, 3000))
        self.assertIsNone(p.structure)
        self.assertIsNone(p.grid)
        np.testing.assert_array_equal(p.surfaces["map"].z, before)
        self.assertEqual(set(p.steps[0]["faults"]), set(p.faults))
        saved = project.from_bytes(project.to_bytes(p))
        self.assertEqual(saved.faults["input_1_2"].to_dict(), fault.to_dict())

    def test_xy_and_invalid_import(self):
        for data, valid in ((XY, True), (b"0 0 0\n1 1 nan\n", False)):
            with self.subTest(valid=valid):
                source = APP.replace(repr(RMS), repr(data))
                if valid:
                    source = source.replace('"input.POL"', '"input.xy"')
                app = AppTest.from_string(source).run()
                self.assertFalse(app.exception)
                if valid:
                    next(b for b in app.button if b.label == "Import as faults").click().run()
                    self.assertIn("First", app.session_state["proj"].faults)
                else:
                    self.assertTrue(app.error)
                    self.assertFalse(any(b.label == "Import as faults" for b in app.button))
                    self.assertEqual(list(app.session_state["proj"].faults), ["input_1"])

    def test_full_page_refreshes_designer_and_import_works_without_backdrop(self):
        source = APP.replace("p.structure, p.grid = object(), object()", "p.structure, p.grid = None, None")
        source = source.replace("faults._import(S.proj())", """
    def editor(mode, **kwargs):
        st.session_state["designer_faults"] = kwargs["faults"]
    with patch.object(faults, "map_editor", side_effect=editor), patch.object(faults, "viewer3d", return_value=None):
        faults.render()
""")
        app = AppTest.from_string(source).run()
        next(b for b in app.button if b.label == "Import as faults").click().run()
        self.assertFalse(app.exception)
        self.assertEqual({f["name"] for f in app.session_state["designer_faults"]},
                         {"input_1", "input_1_2", "input_2"})
        empty = source.replace("p = Project(lattice=Geometry(100, 200, 10, 10, 6, 6))", "p = Project()")
        empty = empty.replace('p.put_surface(Surface("map", p.lattice, np.full((6, 6), 2000.0)))', "")
        app = AppTest.from_string(empty).run()
        next(b for b in app.button if b.label == "Import as faults").click().run()
        self.assertFalse(app.exception)
        self.assertIn("input_1_2", app.session_state["proj"].faults)


if __name__ == "__main__":
    unittest.main()
