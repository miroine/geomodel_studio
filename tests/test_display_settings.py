"""Saved palettes, depth maps, opacity and multi-property cell inspection."""
import sys
import unittest
from pathlib import Path

import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import project as pj, props as pp, gridsection as gs
from core.surface import Surface, Geometry
from core.wells import Well, trajectory
from test_property_models import grid_fixture
from ui import state as S, specs, display
from ui.scene import Scene, grid_property, DEPTH_STOPS, WEBVIZ_PHYSICS


def fixture():
    g = grid_fixture()
    p = pj.Project(grid=g, lattice=Geometry(0., 0., 10., 10., 3, 3))
    p.properties = {
        "PORO": pp.make_property(g, "PORO", .2, unit="frac"),
        "PERMX": pp.make_property(g, "PERMX", 100., unit="mD"),
        "FACIES": pp.make_property(g, "FACIES", np.where(np.indices(g.actnum.shape)[2] == 0, 1., 20.),
                                   kind="discrete", legend={"1": "Sand", "20": "Shale"})}
    p.put_surface(Surface("Top", p.lattice, np.arange(9).reshape(3, 3) * 10. + 100.))
    p.grid = g
    return p


class DisplaySettingsTests(unittest.TestCase):
    def test_saved_palette_changes_grid_fence_and_maps_without_changing_values(self):
        p = fixture()
        g = p.grid
        raw = p.properties["PORO"].values.copy()
        p.display_settings = {"properties": {"PORO": {"stops": ["#123456", "#FEDCBA"]}}}
        scale, legend = grid_property(g, "PORO", p.properties, p.display_settings["properties"])
        self.assertEqual(scale["stops"], ["#123456", "#FEDCBA"])
        self.assertEqual(legend["colors"], scale["stops"])
        scene = S.build_scene(p, surfaces=[], faults=False, polygons=False, wells=False, tops=False,
                              grid=g, prop="PORO", grid_opacity=.35)
        self.assertEqual(scene.objects[0]["opacity"], .35)
        self.assertEqual(scene.objects[0]["legend"]["colors"], scale["stops"])
        f = Scene((0, 0)).property_fence(g, "PORO", [[1., 1.], [19., 1.]], p.properties,
                                       display=p.display_settings["properties"])
        self.assertEqual(f["legend"]["colors"], scale["stops"])
        mp = display.property_map(p, g, "PORO", raw[0], "Map")
        self.assertEqual(mp["data"][0]["colorscale"], [[0., "#123456"], [1., "#FEDCBA"]])
        np.testing.assert_array_equal(p.properties["PORO"].values, raw)
        q = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(q.display_settings, p.display_settings)

    def test_sparse_category_colours_match_map_and_section(self):
        p = fixture()
        p.display_settings = {"properties": {"FACIES": {"preset": "Webviz Colors set 3",
                                                      "categories": {"1": "#010203", "20": "#AABBCC"}}}}
        scale, legend = grid_property(p.grid, "FACIES", p.properties, p.display_settings["properties"])
        self.assertEqual(scale["colors"], ["#010203", "#AABBCC"])
        mp = display.property_map(p, p.grid, "FACIES", p.properties["FACIES"].values[0], "Facies")
        self.assertEqual(mp["data"][0]["colorbar"]["ticktext"], ["1", "20"])
        self.assertEqual(mp["data"][0]["colorscale"][0][1], "#010203")
        sec = gs.grid_line_section(p.grid, p.properties["FACIES"].values, "j", 0)
        plot = specs.property_section([dict(name="FACIES", sec=sec, scale=scale, stops=scale["colors"])])
        colors = {t["fillcolor"] for t in plot["data"] if "fillcolor" in t}
        self.assertEqual(colors, set(scale["colors"]))
        self.assertEqual(legend["items"][1]["color"], "#AABBCC")

    def test_log_colour_maps_keep_raw_hover_values(self):
        p = fixture()
        mp = display.property_map(p, p.grid, "PERMX", p.properties["PERMX"].values[0], "K", "mD")["data"][0]
        np.testing.assert_allclose(mp["z"], 2.)
        np.testing.assert_allclose(mp["customdata"], 100.)

    def test_multi_property_inspection_handles_units_labels_undefined_and_stale(self):
        p = fixture()
        p.properties["PERMX"].values.flat[0] = np.nan
        p.properties["OLD"] = pp.make_property(p.grid, "OLD", 999.)
        p.properties["OLD"].stale = True
        rows = {r["Property"]: r for r in S.cell_property_values(p, {"cell_id": 0})}
        self.assertAlmostEqual(rows["PORO"]["Value"], .2)
        self.assertEqual(rows["PORO"]["Unit"], "frac")
        self.assertEqual(rows["FACIES"]["Label"], "Sand")
        self.assertIsNone(rows["PERMX"]["Value"])
        self.assertEqual(rows["PERMX"]["Status"], "Undefined")
        self.assertIsNone(rows["OLD"]["Value"])
        self.assertEqual(rows["OLD"]["Status"], "Stale / different grid")
        with self.assertRaises(ValueError):
            S.cell_property_values(p, {"cell_id": p.grid.ncells})

    def test_depth_palette_contours_trajectory_and_rotated_map(self):
        p = fixture()
        well = Well("Deviated", 1., 1., path=[[1., 1., 0.], [8., 10., 150.]], color="#111111")
        spec = specs.map_2d(p.surfaces["Top"].z, p.lattice, contour_interval=20.,
                            contour_labels=True, well_paths=[well])
        tr = spec["data"][0]
        self.assertEqual(tr["contours"]["size"], 20.)
        self.assertTrue(tr["contours"]["showlabels"])
        self.assertEqual(tr["colorscale"][0][1], DEPTH_STOPS[0])
        np.testing.assert_array_equal(spec["data"][1]["x"], trajectory(well)[:, 0])
        np.testing.assert_array_equal(spec["data"][1]["customdata"], trajectory(well)[:, 2])
        p.display_settings = {"surfaces": {"Top": {"preset": "Webviz Physics"}}}
        obj = S.build_scene(p, faults=False, polygons=False, wells=False, tops=False).objects[0]
        self.assertEqual(obj["legend"]["colors"], WEBVIZ_PHYSICS)
        rotated = Geometry(100., 200., 10., 10., 6, 6, 35.)
        x, y = rotated.coords()
        out = specs.map_2d(x + y, rotated)["data"][0]
        xx, yy = np.meshgrid(out["x"], out["y"])
        finite = np.isfinite(out["z"])
        np.testing.assert_allclose(np.asarray(out["z"])[finite], (xx + yy)[finite], atol=1e-8)
        with self.assertRaisesRegex(ValueError, "500"):
            specs.map_2d(p.surfaces["Top"].z, p.lattice, contour_interval=.001)

    def test_real_palette_editor_and_cell_inspector(self):
        app = AppTest.from_string("""
import streamlit as st
from test_display_settings import fixture
from ui import display, state as S
if "p" not in st.session_state:
    st.session_state["p"] = fixture()
p = st.session_state["p"]
display.colors(p, "PORO", "test")
S.grid_view_inspector(dict(cell_id=0, i=1, j=1, k=1, property="PORO", value=.2, unit="frac"), p, "test")
""").run()
        self.assertFalse(app.exception)
        app.selectbox[0].select("Webviz Physics").run()
        app.color_picker[0].set_value("#112233")
        next(b for b in app.button if b.label == "Save colours").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["p"].display_settings["properties"]["PORO"]["stops"][0], "#112233")
        self.assertEqual(list(app.dataframe[0].value["Property"]), ["PORO", "PERMX", "FACIES"])
        app.multiselect[0].set_value(["PERMX"]).run()
        self.assertEqual(list(app.dataframe[0].value["Property"]), ["PERMX"])
        next(b for b in app.button if b.label == "Reset to automatic colours").click().run()
        self.assertNotIn("PORO", app.session_state["p"].display_settings["properties"])

    def test_live_project_migration_and_surface_display_rename(self):
        app = AppTest.from_string("""
import streamlit as st
from test_display_settings import fixture
from ui import state as S
if "proj" not in st.session_state:
    p = fixture()
    del p.display_settings
    st.session_state["proj"] = p
st.write(S.proj().display_settings)
""").run()
        self.assertFalse(app.exception)
        p = fixture()
        p.display_settings = {"surfaces": {"Top": {"preset": "Viridis"}}}
        p.rename_surface("Top", "Renamed")
        self.assertIn("Renamed", p.display_settings["surfaces"])
        p.delete_surface("Renamed")
        self.assertFalse(p.display_settings["surfaces"])


if __name__ == "__main__":
    unittest.main()
