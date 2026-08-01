import math
import unittest

from archaeoscope import cropmarks_engine as cropmarks


class CropmarksGeometryTests(unittest.TestCase):
    def test_square_aoi_is_closed_and_centered(self):
        geometry = cropmarks.square_aoi(43.2, 13.3, radius_m=750)
        ring = geometry["coordinates"][0]

        self.assertEqual(geometry["type"], "Polygon")
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 5)
        center = cropmarks.center(geometry)
        self.assertTrue(math.isclose(center[0], 43.2, abs_tol=0.002))
        self.assertTrue(math.isclose(center[1], 13.3, abs_tol=0.002))

    def test_geometry_bounds_uses_leaflet_order(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[[13.0, 43.0], [13.4, 43.0], [13.4, 43.2], [13.0, 43.0]]],
        }
        self.assertEqual(
            cropmarks.geometry_bounds(geometry), [[43.0, 13.0], [43.2, 13.4]]
        )

    def test_rank_features_do_not_repeat_indices(self):
        self.assertEqual(len(cropmarks.RANK_BANDS), len(set(cropmarks.RANK_BANDS)))
        self.assertIn("NDMI", cropmarks.RANK_BANDS)
        self.assertNotIn("NDWI", cropmarks.RANK_BANDS)


if __name__ == "__main__":
    unittest.main()
