"""Real Streamlit interaction checks for the structural workflow flowchart."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest
from core.workflow import STEP_TYPES
from views.workflow import TASK_GROUPS, _task_io
import numpy as np
from core.workflow import run_workflow, WorkflowError, zone_defs, expand_steps
from core.surface import Geometry, Surface
from core.faults import Fault
from core import project as pj


APP = """
import numpy as np
import streamlit as st
from core.project import Project
from core.surface import Geometry, Surface
from ui import state as S
from ui.theme import inject_css
from views.workflow import render
if "project" not in st.session_state:
    g = Geometry(0, 0, 10, 10, 5, 5)
    p = Project(lattice=g)
    p.put_surface(Surface("Top map", g, np.full(g.shape, 1000.0)))
    p.steps = [
        dict(type="surface", horizon="Top", surface="Top map", _id="top"),
        dict(type="isochore", horizon="Base", ref="Top", thickness=50.0, _id="base"),
    ]
    st.session_state["project"] = p
S.proj = lambda: st.session_state["project"]
inject_css()
render()
"""


class WorkflowFlowchartTests(unittest.TestCase):
    def test_inactive_tasks_skip_validation_composites_and_faults(self):
        g = Geometry(0, 0, 10, 10, 5, 5)
        surfaces = {"Top map": Surface("Top map", g, np.full(g.shape, 1000.0))}
        steps = [
            dict(type="surface", horizon="Top", surface="Top map"),
            dict(type="surface", horizon="Missing", surface="Missing map", enabled=False),
            dict(type="zone", enabled=False),
            dict(type="faults", faults=["F"], enabled=False),
            dict(type="isochore", horizon="Base", ref="Top", thickness=50),
        ]
        result = run_workflow(steps, surfaces, {"F": Fault("F", [[0, 0], [40, 40]])}, None, g)
        self.assertEqual(result.names, ["Top", "Base"])
        self.assertEqual(result.faults, [])
        self.assertEqual(zone_defs(steps), [])
        self.assertTrue(any("Step 3: skipped" in message for message in result.log))
        self.assertEqual(expand_steps(steps)[-1][0], 5)
        steps[0]["enabled"] = False
        with self.assertRaisesRegex(WorkflowError, "used before it is defined"):
            run_workflow(steps, surfaces, {}, None, g)
        steps[-1]["enabled"] = False
        with self.assertRaisesRegex(WorkflowError, "defines no horizons"):
            run_workflow(steps, surfaces, {}, None, g)

    def test_activation_invalidates_skips_and_survives_save_load(self):
        app = self.app()
        self.button(app, "Run workflow").click().run()
        [w for w in app.checkbox if w.label == "Active"][1].uncheck().run()
        self.assertFalse(app.exception)
        p = app.session_state["project"]
        self.assertFalse(p.steps[1]["enabled"])
        self.assertIsNone(p.structure)
        self.assertEqual(p.steps[1]["thickness"], 50.0)
        self.assertTrue(any("INACTIVE" in m.value for m in app.markdown))
        self.button(app, "Run workflow").click().run()
        self.assertEqual(app.session_state["project"].structure.names, ["Top"])
        restored = pj.from_bytes(pj.to_bytes(app.session_state["project"]))
        self.assertFalse(restored.steps[1]["enabled"])
        [w for w in app.checkbox if w.label == "Active"][1].check().run()
        self.button(app, "Run workflow").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["project"].structure.names, ["Top", "Base"])

    def app(self):
        app = AppTest.from_string(APP).run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def button(self, app, label, index=0):
        return [b for b in app.button if b.label == label][index]

    def test_all_task_types_have_families_and_io(self):
        self.assertEqual(set(TASK_GROUPS), set(STEP_TYPES))
        for kind in STEP_TYPES:
            source, output = _task_io(dict(type=kind))
            self.assertTrue(source)
            self.assertTrue(output)

    def test_cards_connect_and_have_named_configuration(self):
        app = self.app()
        cards = [m.value for m in app.markdown if 'class="workflow-node ' in m.value]
        self.assertEqual(len(cards), 2)
        self.assertIn("Top map", cards[0])
        self.assertIn("workflow-construction", cards[0])
        self.assertIn("Top + thickness", cards[1].replace("Horizon: ", ""))
        self.assertEqual([e.label for e in app.expander if e.label.startswith("Configure task")],
                         ["Configure task 01 - Horizon from surface", "Configure task 02 - Horizon from isochore"])
        self.assertTrue(any('aria-label="Next task"' in m.value for m in app.markdown))
        self.assertTrue(self.button(app, "Move up", 0).disabled)
        self.assertTrue(self.button(app, "Move down", 1).disabled)

    def test_reordering_deleting_and_running_keep_existing_behavior(self):
        app = self.app()
        self.button(app, "Run workflow").click().run(timeout=30)
        p = app.session_state["project"]
        self.assertIsNotNone(p.structure)
        self.assertEqual(p.structure.names, ["Top", "Base"])
        self.button(app, "Move down").click().run(timeout=30)
        self.assertFalse(app.exception)
        p = app.session_state["project"]
        self.assertEqual([s["_id"] for s in p.steps], ["base", "top"])
        self.assertIsNone(p.structure)
        self.button(app, "Run workflow").click().run(timeout=30)
        self.assertTrue(app.error)
        self.assertIsNone(app.session_state["project"].structure)
        self.button(app, "Move up", 1).click().run(timeout=30)
        self.button(app, "Delete task", 1).click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual([s["_id"] for s in app.session_state["project"].steps], ["top"])

    def test_editing_and_adding_tasks_invalidates_framework(self):
        app = self.app()
        self.button(app, "Run workflow").click().run(timeout=30)
        next(t for t in app.text_input if t.label == "Horizon name" and t.value == "Top").set_value("Top edited")
        self.button(app, "Update step").click().run(timeout=30)
        self.assertFalse(app.exception)
        p = app.session_state["project"]
        self.assertEqual(p.steps[0]["horizon"], "Top edited")
        self.assertIsNone(p.structure)
        next(s for s in app.selectbox if s.label == "Step type").select("smooth").run(timeout=30)
        self.button(app, "Add step").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["project"].steps[-1]["type"], "smooth")

    def test_card_names_are_html_escaped(self):
        app = self.app()
        app.session_state["project"].steps[0]["horizon"] = "<img src=x>"
        app.run(timeout=30)
        cards = [m.value for m in app.markdown if 'class="workflow-node ' in m.value]
        self.assertIn("&lt;img src=x&gt;", cards[0])
        self.assertNotIn("<img src=x>", cards[0])


if __name__ == "__main__":
    unittest.main()
