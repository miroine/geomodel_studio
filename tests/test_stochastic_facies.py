"""Facies-domain stochastic modelling and UI regressions."""
import copy
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import geostat as gs, props as pp, project as pj
from core.cpgrid import CPGrid, ZoneSpec
from streamlit.testing.v1 import AppTest


def fixture():
    nk, nj, ni = 4, 8, 12
    depths = 1000 + 10 * (np.arange(nk)[:, None] + np.arange(2))
    zc = np.broadcast_to(depths[..., None, None, None, None], (nk, 2, nj, 2, ni, 2)).copy()
    grid = CPGrid(ni, nj, nk, np.arange(ni + 1) * 10, np.arange(nj + 1) * 10, zc,
                  np.ones((nk, nj, ni), int), np.array([0, 0, 1, 1]),
                  [ZoneSpec("Upper", "Top", "Mid"), ZoneSpec("Lower", "Mid", "Base")],
                  np.ones((nj, ni), int), [])
    grid.actnum[0, 0, 0] = 0
    codes = np.broadcast_to(np.where(np.arange(ni) < ni // 2, 1, 2), grid.actnum.shape).copy()
    props = {"FACIES": pp.make_property(grid, "FACIES", codes, "discrete", legend={"1": "Shale", "2": "Sand"})}
    cfg = gs.default_config(grid)
    cfg.update(domain="zone_facies", facies="FACIES")
    gs.facies_rows(grid, cfg, props, "FACIES")
    for name in gs.PROPS:
        for row in cfg["props"][name]["facies_rows"]:
            row["p1"] = {1: 0.08, 2: 0.3}[row["code"]] if name == "PORO" else {1: 1.0, 2: 100.0}[row["code"]] if name == "PERM" else {1: 0.1, 2: 0.9}[row["code"]]
            row["p2"] = 0.01 if name != "PERM" else 0.1
    return grid, props, cfg


class StochasticFaciesTests(unittest.TestCase):
    def test_sidebar_has_four_connected_model_boxes_and_working_links(self):
        app = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")).run(timeout=30)
        self.assertFalse(app.exception)
        stages = [m.value for m in app.markdown if 'class="sidebar-flow-title"' in m.value]
        self.assertEqual(len(stages), 4)
        self.assertIn("Horizon & fault framework", stages[0])
        self.assertIn("Populate the reservoir", stages[-1])
        arrows = [m for m in app.markdown if 'class="sidebar-flow-arrow"' in m.value]
        self.assertEqual(len(arrows), 4)
        next(b for b in app.button if b.label == "Structural model").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["nav"], "Structural model")
        next(b for b in app.button if b.label == "Properties").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["nav"], "Properties")

    def test_distinct_histograms_in_each_zone_facies_and_inactive_nan(self):
        grid, props, cfg = fixture()
        result = gs.simulate(grid, cfg, properties=props)
        codes = props["FACIES"].values
        active = grid.actnum > 0
        for zi in (0, 1):
            for code, mean in ((1, 0.08), (2, 0.3)):
                mask = active & (grid.layer_zone == zi)[:, None, None] & (codes == code)
                self.assertAlmostEqual(float(result["PORO"]["values"][mask].mean()), mean, places=6)
                self.assertGreater(result["PORO"]["values"][mask].std(), 0.008)
                self.assertAlmostEqual(float(np.median(result["PERMX"]["values"][mask])), 1 if code == 1 else 100, delta=0.1)
        for r in result.values():
            self.assertTrue(np.isnan(r["values"][~active]).all())
        np.testing.assert_allclose(result["PERMY"]["values"], result["PERMX"]["values"])
        np.testing.assert_allclose(result["PERMZ"]["values"], result["PERMX"]["values"] * 0.1)

    def test_seed_is_repeatable_and_realisations_differ(self):
        grid, props, cfg = fixture()
        cfg["nreal"] = 2
        one = gs.simulate(grid, cfg, properties=props)
        two = gs.simulate(grid, cfg, properties=props)
        np.testing.assert_equal(one["PORO_R1"]["values"], two["PORO_R1"]["values"])
        self.assertFalse(np.allclose(one["PORO_R1"]["values"], one["PORO_R2"]["values"], equal_nan=True))

    def test_variogram_parameters_are_taken_from_each_facies_row(self):
        grid, props, cfg = fixture()
        for index, row in enumerate(cfg["props"]["PORO"]["facies_rows"]):
            row["major"] = 100 + index * 50
        cfg["props"]["PERM"]["enabled"] = False
        cfg["props"]["NTG"]["enabled"] = False
        with patch.object(gs, "gaussian_field", wraps=gs.gaussian_field) as generate:
            gs.simulate(grid, cfg, properties=props)
        self.assertEqual([call.args[2]["major"] for call in generate.call_args_list], [100, 150, 200, 250])

    def test_conditioning_does_not_leak_across_facies(self):
        grid, props, cfg = fixture()
        plain = gs.simulate(grid, cfg, properties=props)
        data = np.full(grid.actnum.shape, np.nan)
        data[0, 2, 2] = 0.15
        conditioned = gs.simulate(grid, cfg, cond={"PORO": data}, properties=props)
        self.assertEqual(conditioned["PORO"]["values"][0, 2, 2], 0.15)
        sand = props["FACIES"].values == 2
        np.testing.assert_equal(plain["PORO"]["values"][sand], conditioned["PORO"]["values"][sand])

    def test_transform_and_cutoffs_obey_domain_masks(self):
        grid, props, cfg = fixture()
        cfg["perm_mode"] = "transform"
        cfg["transform"].update(a=10, b=-1, sigma=0)
        cfg["cut"].update(phi=0.2, binary=True)
        out = gs.simulate(grid, cfg, properties=props)
        mask = grid.actnum > 0
        np.testing.assert_allclose(out["PERMX"]["values"][mask], 10 ** (10 * out["PORO"]["values"][mask] - 1))
        np.testing.assert_equal(out["NET"]["values"][mask], props["FACIES"].values[mask] == 2)

    def test_invalid_or_stale_facies_and_missing_rows_are_rejected(self):
        grid, props, cfg = fixture()
        with self.assertRaises(gs.GeostatError):
            gs.simulate(grid, cfg)
        props["FACIES"].stale = True
        with self.assertRaisesRegex(gs.GeostatError, "stale"):
            gs.simulate(grid, cfg, properties=props)
        props["FACIES"].stale = False
        props["FACIES"].values[0, 1, 1] = np.nan
        with self.assertRaisesRegex(gs.GeostatError, "undefined"):
            gs.simulate(grid, cfg, properties=props)
        props["FACIES"].values[0, 1, 1] = 1.5
        with self.assertRaisesRegex(gs.GeostatError, "discrete"):
            gs.simulate(grid, cfg, properties=props)
        props["FACIES"].values[0, 1, 1] = 1
        cfg["props"]["PORO"]["facies_rows"].pop()
        with self.assertRaisesRegex(gs.GeostatError, "exactly once"):
            gs.simulate(grid, cfg, properties=props)

    def test_zone_only_mode_remains_unchanged(self):
        grid, props, _ = fixture()
        cfg = gs.default_config(grid)
        legacy = gs.simulate(grid, cfg)
        cfg["domain"] = "zone"
        current = gs.simulate(grid, cfg, properties=props)
        for name in legacy:
            np.testing.assert_equal(legacy[name]["values"], current[name]["values"])

    def test_parameter_edits_and_domain_config_survive_project_roundtrip(self):
        grid, props, cfg = fixture()
        original = copy.deepcopy(cfg["props"]["PORO"]["rows"])
        cfg["props"]["PORO"]["facies_rows"][0]["p1"] = 0.12
        gs.facies_rows(grid, cfg, props, "FACIES")
        self.assertEqual(cfg["props"]["PORO"]["facies_rows"][0]["p1"], 0.12)
        self.assertEqual(cfg["props"]["PORO"]["rows"], original)
        p = pj.Project(stochastic=cfg)
        saved = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(saved.stochastic, cfg)

    def test_facies_defaults_use_correct_distribution_units(self):
        grid, props, cfg = fixture()
        for name in gs.PROPS:
            cfg["props"][name].pop("facies_rows")
        defaults = [dict(code=1, poro=0.1, poro_sd=0.02, logk=2, logk_sd=0.3, ntg=0.5)]
        gs.facies_rows(grid, cfg, props, "FACIES", defaults)
        row = cfg["props"]["PERM"]["facies_rows"][0]
        self.assertEqual(row["p1"], 100)
        self.assertAlmostEqual(row["p2"], 0.3 * np.log(10))
        self.assertEqual(cfg["props"]["PORO"]["facies_rows"][0]["p1"], 0.1)

    def test_real_streamlit_can_select_facies_edit_tables_and_run(self):
        app = AppTest.from_string("""
import sys
sys.path.insert(0, "tests")
import streamlit as st
from test_stochastic_facies import fixture
from core.project import Project
from views.properties import _stochastic
if "p" not in st.session_state:
    grid, props, cfg = fixture()
    cfg["domain"] = "zone"
    st.session_state["p"] = Project(grid=grid, properties=props, stochastic=cfg)
p = st.session_state["p"]
_stochastic(p, p.grid)
""").run(timeout=30)
        self.assertFalse(app.exception)
        next(r for r in app.radio if r.label == "Stochastic parameter domains").set_value("zone_facies").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any(s.label == "Stochastic facies property" for s in app.selectbox))
        next(b for b in app.button if b.label == "Run stochastic workflow").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        p = app.session_state["p"]
        self.assertEqual(p.properties["PORO"].source, "stochastic")
        self.assertTrue(any(s.label == "QC facies code" for s in app.selectbox))
        self.assertIn("zone_facies", p.properties["PORO"].expr)


if __name__ == "__main__":
    unittest.main()
