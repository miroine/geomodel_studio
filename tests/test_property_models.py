"""Focused numerical and UI regressions for the property modelling workspaces."""
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import petrophysics as petro, props as pp, project as pj, volumetrics as vol, export, units
from core.cpgrid import CPGrid, ZoneSpec


def grid_fixture():
    zc = np.broadcast_to(
        (1000 + 10 * (np.arange(2)[:, None] + np.arange(2)))[..., None, None, None, None],
        (2, 2, 1, 2, 2, 2)).copy()
    return CPGrid(2, 1, 2, np.array([0, 10, 20]), np.array([0, 10]), zc,
                  np.ones((2, 1, 2), int), np.array([0, 1]),
                  [ZoneSpec("Upper", "Top", "Middle"), ZoneSpec("Lower", "Middle", "Base")],
                  np.zeros((1, 2), int), [])


class PropertyModelTests(unittest.TestCase):
    def setUp(self):
        self.grid = grid_fixture()
        self.props = {
            "FACIES": pp.make_property(self.grid, "FACIES", [[[1, 2]], [[1, 2]]], "discrete",
                                       legend={"1": "Shale", "2": "Sand"}),
            "PORO": pp.make_property(self.grid, "PORO", 0.2, unit="frac"),
            "RT": pp.make_property(self.grid, "RT", 10, unit="ohm.m"),
        }
        self.contacts = vol.default_config(self.grid)
        self.contacts["contacts"]["owc"] = 1020

    def rows(self, mode, defaults):
        return [dict(domain, **defaults) for domain in petro.domains(self.grid, mode, self.props, "FACIES")]

    def test_petrophysics_all_domains_and_anisotropy(self):
        for mode in petro.DOMAINS:
            with self.subTest(mode=mode):
                rows = self.rows(mode, dict(poro=0.2, permx=100, ntg=0.8, kykx=0.5, kvkh=0.1))
                for i, row in enumerate(rows):
                    row["poro"] = 0.1 + 0.05 * i
                result = petro.model_petrophysics(self.grid, self.props, mode, "FACIES", rows)
                np.testing.assert_allclose(result["PERMY"].values, 50)
                np.testing.assert_allclose(result["PERMZ"].values, 10)
                expected = {"zone": [[[0.1, 0.1]], [[0.15, 0.15]]],
                            "facies": [[[0.1, 0.15]], [[0.1, 0.15]]],
                            "zone_facies": [[[0.1, 0.15]], [[0.2, 0.25]]]}[mode]
                np.testing.assert_allclose(result["PORO"].values, expected)
        np.testing.assert_allclose(self.props["PORO"].values, 0.2)

    def test_saturation_height_and_shared_contacts(self):
        rows = self.rows("zone", dict(swirr=0.2, entry=2.0, lam=0.5))
        cfg = dict(method="satheight", domain="zone", rows=rows)
        sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        expected = 0.2 + 0.8 * np.sqrt(2 / np.array([15, 5]))
        np.testing.assert_allclose(sw[:, 0, 0], expected)
        self.contacts["contacts"]["regions"] = dict(prop="FACIES", values={"2": dict(owc=1000)})
        sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        np.testing.assert_allclose(sw[:, 0, 1], 1)
        self.contacts["contacts"]["fwl_below"] = 5
        sw_deeper = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        self.assertTrue((sw_deeper <= sw).all())

    def test_saturation_parameters_by_facies_and_units(self):
        for mode in ("facies", "zone_facies"):
            cfg = dict(method="satheight", domain=mode, facies="FACIES",
                       rows=self.rows(mode, dict(swirr=0.2, entry=2.0, lam=0.5)))
            cfg["rows"][1]["swirr"] = 0.8
            sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
            self.assertGreater(sw[0, 0, 1], sw[0, 0, 0])
        p = pj.Project(property_models={"height": cfg}, volumetrics=self.contacts)
        units.convert_project(p, "m", "ft")
        self.assertAlmostEqual(cfg["rows"][0]["entry"], 2 / 0.3048)
        self.assertAlmostEqual(p.volumetrics["contacts"]["owc"], 1020 / 0.3048)
        units.set_active(units.DEFAULT_CRS)

    def test_archie_exact_and_grouped_parameters(self):
        for mode in petro.DOMAINS:
            cfg = dict(method="archie", domain=mode, facies="FACIES", poro="PORO", rt="RT",
                       rows=self.rows(mode, dict(a=1, m=2, n=2, rw=0.1)))
            sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
            np.testing.assert_allclose(sw, 0.5)
        cfg["rows"][1]["rw"] = 1
        sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        self.assertEqual(sw[0, 0, 1], 1.0)
        self.assertAlmostEqual(sw[0, 0, 0], 0.5)

    def test_validation_and_inactive_cells(self):
        rows = self.rows("zone", dict(poro=0.2, permx=100, ntg=0.8, kykx=1, kvkh=0.1))
        with self.assertRaisesRegex(petro.PetroError, "exactly once"):
            petro.model_petrophysics(self.grid, self.props, "zone", "", rows[:1])
        with self.assertRaisesRegex(petro.PetroError, "exactly once"):
            petro.model_petrophysics(self.grid, self.props, "zone", "", rows + rows[:1])
        rows[0]["poro"] = 2
        with self.assertRaisesRegex(petro.PetroError, "between 0 and 1"):
            petro.model_petrophysics(self.grid, self.props, "zone", "", rows)
        cfg = dict(method="archie", domain="zone", poro="PORO", rt="RT",
                   rows=self.rows("zone", dict(a=1, m=2, n=2, rw=0.1)))
        self.props["RT"].stale = True
        with self.assertRaisesRegex(petro.PetroError, "stale"):
            petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        self.props["RT"].stale = False
        self.props["RT"].values[0, 0, 0] = 0
        with self.assertRaisesRegex(petro.PetroError, "positive formation resistivity"):
            petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        self.grid.actnum[0, 0, 0] = 0
        sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        self.assertTrue(np.isnan(sw[0, 0, 0]))
        np.testing.assert_allclose(sw[self.grid.actnum > 0], 0.5)
        self.props["FACIES"].values[0, 0, 1] = np.nan
        with self.assertRaisesRegex(petro.PetroError, "undefined"):
            petro.domains(self.grid, "facies", self.props, "FACIES")

    def test_saved_settings_sw_volumetrics_and_export(self):
        cfg = dict(method="archie", domain="zone", poro="PORO", rt="RT",
                   rows=self.rows("zone", dict(a=1, m=2, n=2, rw=0.1)))
        sw = petro.model_saturation(self.grid, self.props, cfg, self.contacts)
        self.props["SW"] = pp.make_property(self.grid, "SW", sw, unit="frac", source="saturation")
        p = pj.Project(properties=self.props, property_models={"saturation_archie|zone|": cfg})
        restored = pj.from_bytes(pj.to_bytes(p))
        self.assertEqual(restored.property_models, p.property_models)
        np.testing.assert_allclose(restored.properties["SW"].values, 0.5)
        self.contacts["sw"].update(mode="property", prop="SW")
        result = vol.compute(self.grid, self.contacts, self.props)
        self.assertGreater(result["total"]["STOIIP"], 0)
        text = export.grdecl_text(self.grid, ["SW"], custom=self.props)
        parsed = export.parse_grdecl(text)
        np.testing.assert_allclose(parsed["SW"], 0.5)


class PropertyStreamlitTests(unittest.TestCase):
    def test_property_workspaces_and_archie_execution(self):
        from streamlit.testing.v1 import AppTest
        code = """
import numpy as np
import streamlit as st
from core.cpgrid import CPGrid, ZoneSpec
from core.project import Project
from core.surface import Geometry
from core import props as pp
from views import properties
if "proj" not in st.session_state:
    zc = np.broadcast_to((1000 + 10 * (np.arange(2)[:, None] + np.arange(2)))[..., None, None, None, None],
                         (2, 2, 2, 2, 2, 2)).copy()
    g = CPGrid(2, 2, 2, np.array([0, 10, 20]), np.array([0, 10, 20]), zc,
               np.ones((2, 2, 2), int), np.array([0, 1]),
               [ZoneSpec("Upper", "Top", "Middle"), ZoneSpec("Lower", "Middle", "Base")],
               np.zeros((2, 2), int), [])
    p = Project(lattice=Geometry(0, 0, 10, 10, 3, 3), grid=g)
    p.properties.update(pp.zone_defaults(g))
    p.properties["RT"] = pp.make_property(g, "RT", 10, unit="ohm.m")
    st.session_state["proj"] = p
properties.render()
"""
        app = AppTest.from_string(code, default_timeout=60).run()
        self.assertFalse(app.exception)
        for label in ("Property library", "Facies", "Petrophysics", "Water saturation", "QC & tools"):
            self.assertIn(label, [tab.label for tab in app.tabs])
        next(radio for radio in app.radio if radio.label == "Saturation model").set_value("archie").run()
        self.assertFalse(app.exception)
        next(button for button in app.button if button.label == "Model water saturation").click().run()
        self.assertFalse(app.exception)
        np.testing.assert_allclose(app.session_state["proj"].properties["SW"].values, 0.5)
        next(button for button in app.button if button.label == "Use SW in volumetrics").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["proj"].volumetrics["sw"]["mode"], "property")


class PropertyWorkflowUITests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.dirname(__file__))
        import fake_streamlit as fs
        fake = fs.install()
        fs.session_state.clear()
        fs.OVERRIDES.clear()
        fs.PRESS.clear()
        fs.MESSAGES.clear()
        self.fs = fs
        from views import petrophysics as view
        from ui import state, theme
        for module in (view, state, theme):
            binding = patch.object(module, "st", fake)
            binding.start()
            self.addCleanup(binding.stop)
        self.view = view
        self.grid = grid_fixture()
        self.p = pj.Project(grid=self.grid, properties={
            "PORO": pp.make_property(self.grid, "PORO", 0.2),
            "RT": pp.make_property(self.grid, "RT", 10),
            "FACIES": pp.make_property(self.grid, "FACIES", [[[1, 2]], [[1, 2]]], "discrete"),
        })

    def test_petrophysics_confirmation_and_facies_domains(self):
        self.fs.OVERRIDES["pm_domain"] = "zone_facies"
        self.fs.PRESS.add("pm_run")
        self.view.render_petrophysics(self.p, self.grid)
        self.assertNotIn("PERMX", self.p.properties)
        self.fs.OVERRIDES["pm_replace"] = True
        self.view.render_petrophysics(self.p, self.grid)
        self.assertIn("PERMX", self.p.properties)
        self.assertEqual(len(self.p.property_models["petrophysics|zone_facies|FACIES"]["rows"]), 4)

    def test_saturation_both_models_and_volumetric_selection(self):
        self.fs.PRESS.add("swm_run")
        self.view.render_saturation(self.p, self.grid)
        self.assertIn("SW", self.p.properties)
        self.fs.OVERRIDES.update(swm_method="archie", swm_replace=True)
        self.fs.PRESS.add("swm_run")
        self.view.render_saturation(self.p, self.grid)
        np.testing.assert_allclose(self.p.properties["SW"].values, 0.5)
        self.fs.PRESS.add("swm_use")
        self.view.render_saturation(self.p, self.grid)
        self.assertEqual(self.p.volumetrics["sw"]["prop"], "SW")
        self.assertEqual(self.p.volumetrics["sw"]["mode"], "property")


if __name__ == "__main__":
    unittest.main()
