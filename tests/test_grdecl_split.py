"""GRDECL export as one merged file or standalone per-property files."""
import io
import os
import sys
import unittest
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import export
from core import props as pp
from test_property_models import grid_fixture


class GrdeclSplitTests(unittest.TestCase):
    def setUp(self):
        self.g = grid_fixture()
        self.custom = {"FACIES": pp.make_property(self.g, "FACIES", np.ones(self.g.actnum.shape), "discrete")}
        self.props = ["PORO", "PERMX", "FIPNUM", "FACIES"]

    def test_standalone_files_match_merged_file(self):
        merged = export.parse_grdecl(export.grdecl_text(self.g, self.props, custom=self.custom, extra="-- FAULTS\n"))
        files = export.grdecl_files(self.g, self.props, custom=self.custom, extra="-- FAULTS\n")
        self.assertEqual(set(files), {"MODEL_GRID.GRDECL", "MODEL_PORO.GRDECL", "MODEL_PERMX.GRDECL",
                                      "MODEL_FIPNUM.GRDECL", "MODEL_FACIES.GRDECL", "MODEL_INCLUDE.GRDECL"})
        grid = export.parse_grdecl(files["MODEL_GRID.GRDECL"])
        self.assertIn("-- FAULTS", files["MODEL_GRID.GRDECL"])
        self.assertEqual(list(grid["SPECGRID"]), list(merged["SPECGRID"]))
        for key in ("COORD", "ZCORN", "ACTNUM"):
            np.testing.assert_allclose(grid[key], merged[key])
        self.assertFalse(set(grid) & set(self.props))
        for name in self.props:
            single = export.parse_grdecl(files[f"MODEL_{name}.GRDECL"])
            self.assertEqual(list(single), [name])
            np.testing.assert_allclose(single[name], merged[name])
        include = files["MODEL_INCLUDE.GRDECL"]
        for name in files:
            if name != "MODEL_INCLUDE.GRDECL":
                self.assertIn(f"'{name}'", include)

    def test_zip_and_fault_blocks(self):
        files = export.grdecl_files(self.g, ["PORO"], include_fault_blocks=True)
        self.assertIn("MODEL_FLUXNUM.GRDECL", files)
        self.assertIn("FLUXNUM", export.parse_grdecl(export.grdecl_text(self.g, ["PORO"], include_fault_blocks=True)))
        with zipfile.ZipFile(io.BytesIO(export.grdecl_zip(files))) as z:
            self.assertEqual(sorted(z.namelist()), sorted(files))
            self.assertEqual(z.read("MODEL_PORO.GRDECL").decode(), files["MODEL_PORO.GRDECL"])


if __name__ == "__main__":
    unittest.main()
