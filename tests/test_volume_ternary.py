"""Fluid-volume conservation and RGB ternary mesh rendering."""
import base64
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import volumetrics as V, project as pj
from ui.scene import Scene
from test_property_models import grid_fixture


class TernaryVolumeTests(unittest.TestCase):
    def test_primary_mixed_and_empty_colors(self):
        rgb = V.ternary_colors([1, 0, 0, 1, 0], [0, 1, 0, 1, 0], [0, 0, 1, 2, 0])
        np.testing.assert_array_equal(rgb, [[0, 255, 0], [255, 0, 0], [0, 0, 255],
                                           [64, 64, 128], [190, 190, 190]])
        for values in ((-1, 0, 0), (np.nan, 0, 0)):
            with self.assertRaises(V.VolError):
                V.ternary_colors(*values)

    def result(self):
        g = grid_fixture()
        cfg = V.default_config(g)
        cfg["contacts"].update(owc=1015, goc=1005)
        cfg["sw"]["zone"] = {z.name: 0.25 for z in g.zones}
        return g, cfg, V.compute(g, cfg, {}, 1)

    def test_contact_fractions_conserve_pore_volumes_and_totals(self):
        g, cfg, result = self.result()
        cells = result["cells"]
        pore = g.bulk_volume() * g.property_array("NTG") * g.property_array("PORO")
        np.testing.assert_allclose(cells["OIL_PV"] + cells["GAS_PV"] + cells["WATER_PV"], pore)
        np.testing.assert_allclose(cells["GAS_PV"][0], pore[0] * 0.5 * 0.75)
        np.testing.assert_allclose(cells["OIL_PV"][0], pore[0] * 0.5 * 0.75)
        np.testing.assert_allclose(cells["WATER_PV"][1], pore[1] * (0.5 + 0.5 * 0.25))
        self.assertAlmostEqual(cells["OIL_PV"].sum(), result["total"]["STOIIP"] * cfg["fluid"]["Bo"])
        self.assertAlmostEqual(cells["GAS_PV"].sum(), result["total"]["gas"]["GIIP_free"] * cfg["fluid"]["Bg"])
        cfg["contacts"].update(owc=900, goc=None)
        water = V.compute(g, cfg, {}, 1)["cells"]
        np.testing.assert_array_equal(V.ternary_colors(water["OIL_PV"], water["GAS_PV"], water["WATER_PV"]),
                                      np.broadcast_to([0, 0, 255], (*g.actnum.shape, 3)))
        cfg["zones"] = [g.zones[0].name]
        excluded = V.compute(g, cfg, {}, 1)["cells"]
        self.assertTrue((excluded["WATER_PV"][1] == 0).all())

    def test_mesh_colors_match_triangle_cell_ids(self):
        g, _, result = self.result()
        cells = result["cells"]
        colors = V.ternary_colors(cells["OIL_PV"], cells["GAS_PV"], cells["WATER_PV"])
        sc = Scene((0, 0))
        legend = dict(title="Fluids", items=[dict(label="Oil", color="#00FF00")])
        obj = sc.grid(g, i0=1, cell_colors=colors, color_legend=legend)
        ids = np.frombuffer(base64.b64decode(obj["cell_ids"]), dtype=np.uint32)
        triangles = np.frombuffer(base64.b64decode(obj["idx"]), dtype=np.uint32).reshape(-1, 3)
        rgb = np.frombuffer(base64.b64decode(obj["col"]), dtype=np.uint8).reshape(-1, 3)
        for vertex in range(3):
            np.testing.assert_array_equal(rgb[triangles[:, vertex]], colors.reshape(-1, 3)[ids])
        self.assertEqual(obj["legend"], legend)

    def test_inactive_and_cutoff_cells_have_no_fluid_pore_volume(self):
        g, cfg, _ = self.result()
        g.actnum[0, 0, 0] = 0
        cfg["cut"]["phi"] = 0.5
        result = V.compute(g, cfg, {}, 1)
        for name in ("OIL_PV", "GAS_PV", "WATER_PV"):
            self.assertTrue((result["cells"][name] == 0).all())
        cfg["cut"]["phi"] = 0
        result = V.compute(g, cfg, {}, 1)
        for name in ("OIL_PV", "GAS_PV", "WATER_PV"):
            self.assertEqual(result["cells"][name][0, 0, 0], 0)
        self.assertEqual(result["total"], V.compute(g, cfg, {}, 1, cells=False)["total"])
        colors = V.ternary_colors(*(result["cells"][n] for n in ("OIL_PV", "GAS_PV", "WATER_PV")))
        sc = Scene((0, 0))
        obj = sc.grid(g, layer_mask=np.array([False, True]), cell_colors=colors)
        ids = np.frombuffer(base64.b64decode(obj["cell_ids"]), dtype=np.uint32)
        self.assertTrue((ids >= g.ni * g.nj).all())

    def test_real_results_view_contains_ternary_mesh(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string("""
import streamlit as st
from core import volumetrics as V, project as pj
from core.surface import Geometry
from test_property_models import grid_fixture
from views.volumetrics import _fluid_view
p = pj.Project(lattice=Geometry(0,0,10,10,3,2), grid=grid_fixture())
cfg = V.default_config(p.grid)
_fluid_view(p, p.grid, cfg, V.compute(p.grid,cfg,{},1))
""").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any(w.label == "Filter grid view by" for w in app.selectbox))
        self.assertTrue(any("Green = oil" in w.value for w in app.caption))


if __name__ == "__main__":
    unittest.main()
