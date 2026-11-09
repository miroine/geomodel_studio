"""IRAP interoperability: X varies fastest, independent of record boundaries."""
import struct
import unittest
from unittest.mock import patch

import numpy as np

from core import io_surfaces
from core.surface import Geometry, Surface


ASCII = (b"-996 2 10 20\n100 120 200 220\n3 0 100 200\n0 0 0 0 0 0 0\n"
         b"11 12 13 21 9999900 23\n")


def record(fmt, *values):
    payload = struct.pack(fmt, *values)
    return struct.pack(">i", len(payload)) + payload + struct.pack(">i", len(payload))


def binary():
    return (record(">iiffffff", -996, 2, 100, 120, 200, 220, 10, 20)
            + record(">ifff", 3, 0, 100, 200) + record(">7i", *([0] * 7))
            + record(">2f", 11, 12) + record(">4f", 13, 21, 9999900, 23))


class IrapOrderingTests(unittest.TestCase):
    def test_external_format_reader(self):
        expected = np.array([[11, 12, 13], [21, np.nan, 23]])
        for data, reader in ((ASCII, io_surfaces.read_irap_ascii_py), (binary(), io_surfaces.read_irap_binary_py)):
            with self.subTest(reader=reader.__name__):
                surface = reader(data)
                np.testing.assert_equal(surface.z, expected)
                np.testing.assert_equal(surface.sample(np.array([110, 120]), np.array([200, 220]), order=0), [12, 23])
                with patch.object(io_surfaces, "HAS_XTGEO", False):
                    kind, imported = io_surfaces.read_any(data, "example.gri")
                self.assertEqual(kind, "surface")
                np.testing.assert_equal(imported.z, expected)

    def test_external_format_writer(self):
        surface = Surface("test", Geometry(100, 200, 10, 20, 3, 2),
                          np.array([[11, 12, 13], [21, np.nan, 23]]))
        ascii_values = np.array(io_surfaces.write_irap_ascii(surface).decode().split()[19:], dtype=float)
        np.testing.assert_equal(ascii_values, [11, 12, 13, 21, 9999900, 23])
        payload = io_surfaces.write_irap_binary_py(surface)
        size = struct.unpack_from(">i", payload, 100)[0]
        binary_values = struct.unpack_from(f">{size // 4}f", payload, 104)
        np.testing.assert_equal(binary_values, [11, 12, 13, 21, 9999900, 23])

    @unittest.skipUnless(io_surfaces.HAS_XTGEO, "xtgeo not installed")
    def test_interoperability_with_xtgeo(self):
        for data, fmt in ((ASCII, "irap_ascii"), (binary(), "irap_binary")):
            with self.subTest(format=fmt):
                fallback = io_surfaces.read_irap_ascii_py(data) if fmt == "irap_ascii" else io_surfaces.read_irap_binary_py(data)
                external = io_surfaces.read_irap_xtgeo(data, fmt, "test")
                np.testing.assert_equal(fallback.z, external.z)
                written = io_surfaces.write_irap_ascii(fallback) if fmt == "irap_ascii" else io_surfaces.write_irap_binary_py(fallback)
                np.testing.assert_equal(io_surfaces.read_irap_xtgeo(written, fmt, "test").z, fallback.z)


if __name__ == "__main__":
    unittest.main()
