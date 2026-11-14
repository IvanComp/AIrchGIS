import unittest

from affine import Affine
import numpy as np
from pyproj import Transformer

from airchgis.terrain.imagery import HALF_WORLD, drape_imagery


class TerrainImageryTests(unittest.TestCase):
    def test_rotated_metric_grid_and_last_sample_align_with_satellite_pixels(self):
        t = Affine(1, .2, 400000, .1, -1, 4700000)
        valid = np.ones((4, 4), dtype=np.uint8)
        valid[1, 2] = 0
        grid = {"sample_step": 3, "valid": valid}
        calls = []

        def tile(zoom, x, y):
            calls.append((zoom, x, y))
            yy, xx = np.mgrid[:256, :256]
            return np.stack([xx, yy, np.full_like(xx, 127)], axis=-1).astype(np.uint8)

        actual = drape_imagery({"transform": t}, "EPSG:32633", (9, 8), grid, "unused", tile_loader=tile)
        rr, cc = np.meshgrid(np.array([0, 3, 6, 8]) + .5, np.array([0, 3, 6, 7]) + .5, indexing="ij")
        mx, my = Transformer.from_crs(32633, 3857, always_xy=True).transform(t.a * cc + t.b * rr + t.c,
                                                                                       t.d * cc + t.e * rr + t.f)
        pixels = 256 * 2 ** calls[0][0]
        expected = np.stack([((mx + HALF_WORLD) / (2 * HALF_WORLD) * pixels - .5) % 256,
                             ((HALF_WORLD - my) / (2 * HALF_WORLD) * pixels - .5) % 256,
                             np.full_like(mx, 127)], axis=-1)
        np.testing.assert_allclose(actual[valid > 0], expected[valid > 0], atol=1)
        np.testing.assert_array_equal(actual[1, 2], [0, 0, 0])
        self.assertEqual(actual.shape, (4, 4, 3))

    def test_missing_tiles_do_not_become_black_imagery(self):
        with self.assertRaisesRegex(ValueError, "could not be loaded"):
            drape_imagery({"transform": Affine(1, 0, 400000, 0, -1, 4700000)}, "EPSG:32633", (3, 3),
                          {"sample_step": 1, "valid": np.ones((3, 3))}, "unused", tile_loader=lambda *args: None)


if __name__ == "__main__":
    unittest.main()
