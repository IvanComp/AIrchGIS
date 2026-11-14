import unittest

import numpy as np
import rvt.vis
from rasterio.transform import from_origin

from RVT.scripts import lads_preview as lp


class ElevationColorTests(unittest.TestCase):
    def setUp(self):
        y, x = np.mgrid[:80, :96]
        self.dem = (100 + .15 * x + 3 * np.exp(-((x - 45) ** 2 + (y - 38) ** 2) / 120)).astype(np.float32)

    def test_grayscale_matches_rvt_hillshade_and_tint_contains_height_only(self):
        valid = np.ones(self.dem.shape, dtype=bool)
        gray, tint = lp._elevation_relief_colors(self.dem, self.dem, valid, 1, 1)
        expected = np.round(rvt.vis.hillshade(self.dem, 1., 1., sun_azimuth=315, sun_elevation=45) * 255).astype(np.uint8)
        np.testing.assert_array_equal(gray[..., 0], expected)
        np.testing.assert_array_equal(gray[..., 0], gray[..., 1])
        np.testing.assert_array_equal(gray[..., 1], gray[..., 2])
        self.assertTrue(np.all(tint[..., 3] == 255))
        altered = self.dem + np.sin(np.arange(96))[None, :].astype(np.float32)
        other_gray, same_tint = lp._elevation_relief_colors(altered, self.dem, valid, 1, 1)
        np.testing.assert_array_equal(tint, same_tint)
        self.assertFalse(np.array_equal(gray, other_gray))

    def test_missing_cells_remain_excluded_and_elevations_do_not_change(self):
        valid = np.ones(self.dem.shape, dtype=bool)
        valid[:4] = False
        before = self.dem.copy()
        gray, tint = lp._elevation_relief_colors(self.dem, self.dem, valid, 1, 1)
        self.assertTrue(np.all(gray[~valid] == 0))
        self.assertTrue(np.all(tint[~valid] == 0))
        np.testing.assert_array_equal(self.dem, before)
        profile = {"transform": from_origin(400000, 4700000, 1, 1), "nodata": None}
        grid = lp.build_browser_terrain_grid(self.dem, profile, "EPSG:32633", target_crs=None,
                                             cloud_preprocess_key="original")
        np.testing.assert_array_equal(grid["z"], self.dem)
        self.assertEqual(grid["elevation_tint"].shape, self.dem.shape + (4,))


if __name__ == "__main__":
    unittest.main()
