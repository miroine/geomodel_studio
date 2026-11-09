"""Full-width layering/grid workflow, top build action and navigation compatibility."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest
from views import zones

APP = """
import numpy as np
import streamlit as st
from unittest.mock import patch
from core.project import Project
from core.surface import Geometry, Surface
from core.workflow import run_workflow
from core.cpgrid import ZoneSpec
from ui import state as S
from views.grid_workflow import render
if 'project' not in st.session_state:
    g = Geometry(0,0,10,10,5,5)
    p = Project(lattice=g, grid_params=dict(dx=10,dy=10,min_thickness=0.1))
    p.surfaces = {'Top map':Surface('Top map',g,np.full(g.shape,1000.0))}
    p.steps = [dict(type='surface',horizon='Top',surface='Top map'),
               dict(type='isochore',horizon='Base',ref='Top',thickness=50)]
    p.structure = run_workflow(p.steps,p.surfaces,{},None,g)
    p.zones = [ZoneSpec('Reservoir','Top','Base',nlayers=2)]
    st.session_state.project = p
editor = st.data_editor
def edited(data, **kw):
    result = editor(data, **kw)
    if str(kw.get('key','')).startswith('zone_ed') and 'edited_zones' in st.session_state:
        return st.session_state.edited_zones
    return result
with patch.object(st,'data_editor',side_effect=edited), patch.object(S,'proj',return_value=st.session_state.project):
    render()
"""


class GridWorkflowTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(APP).run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def build(self, app):
        next(b for b in app.button if b.label == "Build / update 3D grid").click().run(timeout=30)
        self.assertFalse(app.exception)

    def test_zone_edits_and_explicit_rebuild_update_results(self):
        app = self.app()
        self.assertIsNone(app.session_state.project.grid)
        self.build(app)
        self.assertEqual(app.session_state.project.grid.nk, 2)
        self.assertEqual([t.label for t in app.tabs], ["3D cut-away", "Sections", "Checks"])
        table = zones._to_df(app.session_state.project)
        table.loc[0, "Layers"] = 4
        app.session_state.edited_zones = table
        app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state.project.grid)
        self.build(app)
        self.assertEqual(app.session_state.project.grid.nk, 4)
        dx = next(w for w in app.number_input if w.label.startswith("Cell size dx"))
        dx.set_value(20).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.project.grid.ni, 4)
        self.build(app)
        self.assertEqual(app.session_state.project.grid.ni, 2)

    def test_invalid_zone_edits_block_build(self):
        app = self.app()
        table = zones._to_df(app.session_state.project)
        table.loc[0, "Base"] = "Top"
        app.session_state.edited_zones = table
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertTrue(next(b for b in app.button if b.label == "Build / update 3D grid").disabled)
        self.assertIsNone(app.session_state.project.grid)

    def test_top_build_action_and_full_width_results(self):
        app = self.app()
        self.assertEqual(app.button[0].label, "Build / update 3D grid")
        self.assertEqual([e.label for e in app.expander][:2], ["1  Zones & layering", "Layering styles"])
        self.build(app)
        nodes = list(app.main.children.values())
        results_heading = next(i for i, node in enumerate(nodes)
                               if node.type == "subheader" and node.value == "3  Grid results")
        tabs = next(i for i, node in enumerate(nodes) if node.type == "tab_container")
        self.assertGreater(tabs, results_heading)
        self.assertFalse(next(e for e in app.expander if e.label == "1  Zones & layering").proto.expanded)
        self.assertFalse(next(e for e in app.expander if e.label == "2  Grid settings").proto.expanded)

    def test_legacy_navigation_opens_combined_page(self):
        for target in ("Zones & layering", "3D grid"):
            app = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"))
            app.session_state.nav = target
            app.run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.nav, "Zones & 3D grid")
            self.assertTrue(any(b.label == "Zones & 3D grid" for b in app.button))
            self.assertFalse(any(b.label in ("Zones & layering", "3D grid") for b in app.button))


if __name__ == "__main__":
    unittest.main()
