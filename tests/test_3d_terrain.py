import unittest
import tempfile
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

from RVT.scripts import lads_preview


class TerrainFootprintTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"transform": from_origin(350000, 4800000, 1, 1), "nodata": -9999.0}
        self.dem = np.zeros((40, 40), dtype=np.float32)
        self.dem[8:32, 8:32] = 5 + np.indices((24, 24))[0] * 0.2

    def test_boundary_zero_padding_is_omitted_in_every_rendering_mode(self):
        for mode in ("original", "cloud1", "cloud2", "cloud3"):
            with self.subTest(mode=mode):
                grid = lads_preview.build_browser_terrain_grid(
                    self.dem, self.profile, "EPSG:32633", target_crs="EPSG:32633",
                    max_side=100, cloud_preprocess_key=mode,
                )
                valid = grid["valid"].astype(bool)
                np.testing.assert_array_equal(valid, self.dem != 0)
                self.assertEqual(grid["preview_points"], 24 * 24)
        self.assertEqual(int((self.dem == 0).sum()), 1024)

    def test_initial_framing_ignores_hidden_padding_coordinates(self):
        grid = lads_preview.build_browser_terrain_grid(
            self.dem, self.profile, "EPSG:32633", target_crs="EPSG:32633", max_side=100,
            cloud_preprocess_key="original",
        )
        valid = grid["valid"].astype(bool)
        expected = max(float(np.ptp(grid["x"][valid])), float(np.ptp(grid["y"][valid])),
                       float(np.ptp(grid["z"][valid])) * grid["z_scale"]) * 0.8
        grid["x"][~valid] = 1e6
        grid["y"][~valid] = -1e6
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "viewer.html"
            lads_preview.write_browser_cloud_viewer(path, grid)
            self.assertIn(f"const DEFAULT_RADIUS = {expected:.6f};", path.read_text())

    def test_valid_flat_terrain_is_preserved(self):
        dem = np.full((40, 40), 25, dtype=np.float32)
        np.testing.assert_array_equal(lads_preview._browser_terrain_surface(dem, self.profile), dem)
        dem.fill(0)
        np.testing.assert_array_equal(lads_preview._browser_terrain_surface(dem, self.profile), dem)

    def test_internal_zero_elevations_are_preserved(self):
        dem = np.full((40, 40), 5, dtype=np.float32)
        dem[10:30, 10:30] = 0
        np.testing.assert_array_equal(lads_preview._browser_terrain_surface(dem, self.profile), dem)

    def test_declared_nodata_and_padding_behind_nodata_border(self):
        self.dem[[0, -1], :] = -9999
        self.dem[:, [0, -1]] = -9999
        surface = lads_preview._browser_terrain_surface(self.dem, self.profile)
        np.testing.assert_array_equal(np.isfinite(surface), self.dem > 0)


if __name__ == "__main__":
    unittest.main()
