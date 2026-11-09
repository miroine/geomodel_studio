"""Fluid-system consistency between saturation, classification and volumetrics."""
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from core import volumetrics as V, petrophysics as P, project, property_workflow
from test_property_models import grid_fixture


class FluidSystemTests(unittest.TestCase):
    def test_volumes_classification_and_conservation(self):
        g = grid_fixture()
        cfg = V.default_config(g)
        cfg["contacts"].update(owc=1015, goc=1005)
        for system in ("gas", "oil", "oil_gas"):
            with self.subTest(system=system):
                cfg["contacts"]["fluid_system"] = system
                result = V.compute(g, cfg, {})
                cells = result["cells"]
                expected = g.bulk_volume() * g.property_array("NTG") * g.property_array("PORO")
                np.testing.assert_allclose(sum(cells[n] for n in ("OIL_PV", "GAS_PV", "WATER_PV")), expected)
                fluid = V.fluid_array(g, cfg)
                if system == "gas":
                    self.assertTrue((cells["OIL_PV"] == 0).all())
                    self.assertGreater(cells["GAS_PV"].sum(), 0)
                    self.assertFalse((fluid == 2).any())
                elif system == "oil":
                    self.assertTrue((cells["GAS_PV"] == 0).all())
                    self.assertGreater(cells["OIL_PV"].sum(), 0)
                    self.assertFalse((fluid == 1).any())
                else:
                    self.assertGreater(cells["GAS_PV"].sum(), 0)
                    self.assertGreater(cells["OIL_PV"].sum(), 0)
        cfg["contacts"].pop("fluid_system")
        legacy = V.compute(g, cfg, {})
        cfg["contacts"]["fluid_system"] = "auto"
        self.assertEqual(legacy["total"], V.compute(g, cfg, {})["total"])

    def test_saturation_single_fluid_ignores_stale_gas_curve_and_goc(self):
        g = grid_fixture()
        contacts = V.default_config(g)
        contacts["contacts"].update(owc=1015, goc=9999, goc_prop="missing",
                                   regions=dict(prop="ZONE", values={"1": dict(owc=1020, goc=9999)}))
        cfg = dict(method="satheight", domain="zone", gas_curve=True,
                   rows=[dict(zone=i+1, swirr=0.2, entry=2, lam=0.5) for i in range(2)])
        for system in ("gas", "oil"):
            contacts["contacts"]["fluid_system"] = system
            sw = P.model_saturation(g, {}, cfg, contacts)
            self.assertTrue(np.isfinite(sw).all())
            self.assertTrue((sw[1] == 1).all())
            self.assertTrue((sw[0] < 1).all())
            restored = project.from_bytes(project.to_bytes(project.Project(volumetrics=contacts)))
            self.assertEqual(restored.volumetrics["contacts"]["fluid_system"], system)
        contacts["contacts"].update(fluid_system="oil_gas", goc_prop="", goc=None, regions={})
        with self.assertRaisesRegex(P.PetroError, "requires a GOC"):
            P.model_saturation(g, {}, cfg, contacts)

    def test_shared_contact_editor_choices(self):
        app = AppTest.from_string("""
import streamlit as st
from core import volumetrics as V
from core.project import Project
from test_property_models import grid_fixture
from views import contact_settings
if "p" not in st.session_state:
    g = grid_fixture()
    st.session_state["p"] = Project(grid=g, volumetrics=V.default_config(g))
p = st.session_state["p"]
contact_settings.render(p.volumetrics["contacts"], p, lambda field: "test_" + field)
""").run()
        for system in ("gas", "oil", "oil_gas"):
            next(w for w in app.selectbox if w.label == "Fluid system").select(system).run()
            self.assertFalse(app.exception)
            app.run()
            self.assertEqual(app.session_state["p"].volumetrics["contacts"]["fluid_system"], system)
            if system == "gas":
                self.assertTrue(any(w.label.startswith("GWC depth") for w in app.number_input))

    def test_saved_saturation_job_keeps_fluid_snapshot(self):
        g = grid_fixture()
        p = project.Project(grid=g, volumetrics=V.default_config(g))
        p.volumetrics["contacts"].update(fluid_system="gas", owc=1015)
        job = property_workflow.new_job("saturation", p)
        p.property_jobs.append(job)
        p.volumetrics["contacts"]["fluid_system"] = "oil"
        self.assertEqual(job["config"]["contacts"]["contacts"]["fluid_system"], "gas")
        property_workflow.run(p)
        self.assertIn("SW", p.properties)
        self.assertTrue(np.isfinite(p.properties["SW"].values).all())

    def test_volumetrics_page_persists_choice(self):
        app = AppTest.from_string("""
import streamlit as st
from unittest.mock import patch
from core import project
from core.surface import Geometry
from test_property_models import grid_fixture
from views import volumetrics
if "proj" not in st.session_state:
    st.session_state["proj"] = project.Project(grid=grid_fixture(), lattice=Geometry(0,0,10,10,3,2))
with patch.object(volumetrics, "viewer3d", return_value=None), patch.object(volumetrics, "plotly_view", return_value=None):
    volumetrics.render()
""").run(timeout=30)
        self.assertFalse(app.exception)
        next(w for w in app.selectbox if w.label == "Fluid system").select("gas").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["proj"].volumetrics["contacts"]["fluid_system"], "gas")
        self.assertTrue(any(w.label.startswith("GWC depth") for w in app.number_input))

if __name__ == "__main__":
    unittest.main()
