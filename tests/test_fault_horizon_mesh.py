"""Faulted horizon meshes must not interpolate triangles across a displacement jump."""
import base64
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.faults import Fault
from core.surface import Geometry, Surface
from core.workflow import Structure
from core.project import Project
from ui.scene import Scene
from ui import state as S


def buffers(obj):
    pos = np.frombuffer(base64.b64decode(obj["pos"]), np.float32).reshape(-1, 3)
    tri = np.frombuffer(base64.b64decode(obj["idx"]), np.uint32).reshape(-1, 3)
    return pos, tri


class FaultHorizonMeshTests(unittest.TestCase):
    def setUp(self):
        self.geom = Geometry(0, 0, 10, 10, 7, 7)
        self.base = np.full(self.geom.shape, 1000.0)
        self.fault = Fault("F", [[25, -10], [25, 70]], throw=60, dip=90, profile="constant", drag=100, zref=1000)
        x, y = self.geom.coords()
        self.depth = self.base + self.fault.displacement(x, y, self.base, 1000)

    def test_unfaulted_mesh_is_preserved(self):
        obj = Scene((0, 0)).surface(Surface("H", self.geom, self.base))
        _, triangles = buffers(obj)
        self.assertEqual(len(triangles), 72)

    def test_original_topology_bridges_the_numerical_jump(self):
        obj = Scene((0, 0)).surface(Surface("H", self.geom, self.depth))
        pos, triangles = buffers(obj)
        sides = self.fault.side(pos[:, 0], pos[:, 1], 1000)
        self.assertTrue((sides[triangles] != sides[triangles[:, :1]]).any())

    def test_fault_jump_is_not_bridged_at_any_display_resolution(self):
        for maximum in (140000, 20):
            obj = Scene((0, 0)).surface(Surface("H", self.geom, self.depth), max_nodes=maximum,
                                       fault_cuts=[self.fault], fault_reference=self.base)
            pos, triangles = buffers(obj)
            sides = self.fault.side(pos[:, 0], pos[:, 1], 1000)
            self.assertGreater(len(triangles), 0)
            self.assertTrue((sides[triangles] == sides[triangles[:, :1]]).all())
            np.testing.assert_allclose(pos[:, 2], Surface("H", self.geom, self.depth).sample(pos[:, 0], pos[:, 1]), atol=1e-4)
            self.assertGreater(float(pos[:, 2].max() - pos[:, 2].min()), 50)

    def test_zero_throw_keeps_surface_continuous(self):
        self.fault.throw = 0
        obj = Scene((0, 0)).surface(Surface("H", self.geom, self.base), fault_cuts=[self.fault], fault_reference=self.base)
        self.assertEqual(len(buffers(obj)[1]), 72)

    def test_dipping_fault_uses_unfaulted_reference(self):
        self.fault.dip = 60
        self.fault.zref = 980
        x, y = self.geom.coords()
        depth = self.base + self.fault.displacement(x, y, self.base, 1000)
        obj = Scene((0, 0)).surface(Surface("H", self.geom, depth), fault_cuts=[self.fault], fault_reference=self.base)
        pos, tri = buffers(obj)
        side = self.fault.side(pos[:, 0], pos[:, 1], 1000)
        self.assertTrue((side[tri] == side[tri[:, :1]]).all())

    def test_structural_view_cuts_even_when_planes_are_hidden(self):
        structure = Structure(self.geom, {"H": self.base}, {"H": "conformable"}, [self.fault], ["H"])
        p = Project(lattice=self.geom, structure=structure)
        scene = S.build_scene(p, surfaces=[], horizons=["H"], faults=False, wells=False, polygons=False, tops=False)
        pos, tri = buffers(scene.objects[0])
        side = self.fault.side(pos[:, 0], pos[:, 1], 1000)
        self.assertTrue((side[tri] == side[tri[:, :1]]).all())
        self.assertEqual(len(scene.objects), 1)

    def test_partial_undefined_cells_do_not_restore_fault_bridges(self):
        depth = self.depth.copy()
        depth[1, 2] = np.nan
        obj = Scene((0, 0)).surface(Surface("H", self.geom, depth), fault_cuts=[self.fault], fault_reference=self.base)
        pos, tri = buffers(obj)
        side = self.fault.side(pos[:, 0], pos[:, 1], 1000)
        self.assertTrue((side[tri] == side[tri[:, :1]]).all())
        self.assertTrue(np.isfinite(pos).all())

    def test_tapered_fault_does_not_cut_beyond_its_tips(self):
        self.fault.trace = [[25, 20], [25, 40]]
        self.fault.profile = "elliptical"
        obj = Scene((0, 0)).surface(Surface("H", self.geom, self.depth), fault_cuts=[self.fault], fault_reference=self.base)
        pos, tri = buffers(obj)
        side = self.fault.side(pos[:, 0], pos[:, 1], 1000)
        crossing = (side[tri] != side[tri[:, :1]]).any(axis=1)
        self.assertTrue(crossing.any())
        self.assertTrue(((pos[tri[crossing], 1] <= 20).all(axis=1) |
                         (pos[tri[crossing], 1] >= 40).all(axis=1)).all())

    def test_multiple_faults_and_growth_only_throw(self):
        self.fault.throw = 0
        self.fault.growth = 60
        self.fault.zref = 900
        self.fault.dip = 90
        second = Fault("F2", [[-10, 35], [70, 35]], throw=20, dip=90, profile="constant", zref=1000, ftype="reverse")
        obj = Scene((0, 0)).surface(Surface("H", self.geom, self.depth), fault_cuts=[self.fault, second],
                                   fault_reference=self.base)
        pos, tri = buffers(obj)
        self.assertGreater(len(tri), 0)
        for fault in (self.fault, second):
            side = fault.side(pos[:, 0], pos[:, 1], 1000)
            self.assertTrue((side[tri] == side[tri[:, :1]]).all())

    def test_array_previews_separate_cuts_from_fault_plane_visibility(self):
        p = Project(lattice=self.geom)
        cut = S.scene_from_arrays(p, [("H", self.depth)], fault_cuts=[self.fault], fault_references={"H": self.base},
                                  wells=False, tops=False)
        uncut = S.scene_from_arrays(p, [("H", self.base)], faults=[self.fault], wells=False, tops=False)
        self.assertLess(len(buffers(cut.objects[0])[1]), 72)
        self.assertEqual(len(buffers(uncut.objects[0])[1]), 72)


if __name__ == "__main__":
    unittest.main()
