"""Library QC refreshes on import without serializing an unrequested project download."""
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from core import project


APP = """
import numpy as np
import streamlit as st
from unittest.mock import patch
from core import project, io_surfaces
from core.surface import Geometry, Surface
from ui import state as S
from views import surfaces

class Upload:
    name = "fast.gri"
    def getvalue(self):
        geom = Geometry(100, 200, 100, 100, 25, 20)
        return io_surfaces.write_irap_binary_py(Surface("fast", geom, np.full(geom.shape, 2000.0)))

serialize = project.to_bytes

def save_project(p):
    data = serialize(p)
    st.session_state["archives"].append(data)
    return data

def show_scene(scene, **kwargs):
    st.session_state["qc_scene"] = scene.to_dict()

if "archives" not in st.session_state:
    st.session_state["archives"] = []

with patch.object(st, "file_uploader", side_effect=lambda label, **kw: [Upload()] if label == "Surface files" else None), \
     patch.object(surfaces.pj, "to_bytes", side_effect=save_project), \
     patch.object(surfaces, "viewer3d", side_effect=show_scene), \
     patch.object(surfaces, "map_editor", return_value=None):
    surfaces.render()
"""
class SurfaceLibraryRefreshTests(unittest.TestCase):
    def test_import_appears_in_library_and_scene_in_same_run(self):
        app = AppTest.from_string(APP).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["archives"], [])
        next(b for b in app.button if b.label == "Add to library").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Surface" in df.value and "fast" in df.value["Surface"].values for df in app.dataframe))
        scene = app.session_state["qc_scene"]
        self.assertEqual([o["name"] for o in scene["objects"] if o["group"] == "Surfaces"], ["fast"])
        self.assertEqual(app.session_state["archives"], [])
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["archives"], [])

    def test_project_download_is_prepared_only_on_request_with_current_data(self):
        app = AppTest.from_string(APP).run()
        next(b for b in app.button if b.label == "Add to library").click().run()
        next(b for b in app.button if b.label == "Prepare complete project download").click().run()
        self.assertFalse(app.exception)
        archives = app.session_state["archives"]
        self.assertEqual(len(archives), 1)
        restored = project.from_bytes(archives[0])
        np.testing.assert_array_equal(restored.surfaces["fast"].z, np.full((20, 25), 2000))
        p = app.session_state["proj"]
        p.surfaces["fast"].z[:] = 2100
        app.run()
        self.assertEqual(len(archives), 1)
        next(b for b in app.button if b.label == "Prepare complete project download").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(archives), 2)
        restored = project.from_bytes(archives[-1])
        np.testing.assert_array_equal(restored.surfaces["fast"].z, p.surfaces["fast"].z)


if __name__ == "__main__":
    unittest.main()
