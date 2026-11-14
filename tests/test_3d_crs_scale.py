import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import transform as warp

from RVT.scripts import lads_preview
from airchgis.terrain.export3d import export_terrain_3d
from airchgis.terrain.view_export import view_caption


def bumpy(res, size_m=200.0):
    """The same synthetic terrain sampled at a given cell size: a gentle slope with small mounds and a ditch."""
    n = int(round(size_m / res))
    c = (np.arange(n) + 0.5) * res
    xx, yy = np.meshgrid(c, c)
    z = 100 + 0.05 * xx + 0.02 * yy
    for cx, cy in ((50, 60), (120, 140), (150, 50)):
        z += 0.8 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 4.0 ** 2))
    z -= 0.5 * np.exp(-((xx - 100) ** 2) / (2 * 2.0 ** 2))
    return z.astype(np.float32)


class CrsTests(unittest.TestCase):
    def grid(self, dem, transform, crs, mode="original"):
        return lads_preview.build_browser_terrain_grid(dem, {"transform": transform, "nodata": None}, crs,
                                                        target_crs=None, max_side=400, cloud_preprocess_key=mode)

    def test_uk_projected_dtm_keeps_its_crs_and_position(self):
        t = from_origin(530000, 180000, 1, 1)
        dem = bumpy(1.0, 100)
        g = self.grid(dem, t, "EPSG:27700")
        self.assertEqual(g["target_crs"], "EPSG:27700")
        self.assertAlmostEqual(g["origin_x"], 530000.5, places=3)
        self.assertAlmostEqual(g["origin_y"], 180000 - 99.5, places=3)
        self.assertAlmostEqual(g["cell_size_m"], 1.0, places=3)

    def test_geographic_dtm_in_romania_goes_to_its_utm_zone(self):
        t = from_origin(24.00, 45.80, 0.0002777778, 0.0002777778)
        dem = np.random.default_rng(1).normal(400, 2, (60, 80)).astype(np.float32)
        g = self.grid(dem, t, "EPSG:4326")
        self.assertEqual(g["target_crs"], "EPSG:32635")
        lon, lat = warp("EPSG:32635", "EPSG:4326", [g["origin_x"]], [g["origin_y"]])
        self.assertAlmostEqual(lon[0], 24.0, delta=0.002)
        self.assertAlmostEqual(lat[0], 45.80 - 60 * 0.0002777778, delta=0.002)
        self.assertGreater(g["cell_size_m"], 15)
        self.assertLess(g["cell_size_m"], 35)

    def test_southern_hemisphere_uses_south_zone(self):
        self.assertEqual(lads_preview.utm_crs_for_lonlat(-70.6, -33.4), "EPSG:32719")
        self.assertEqual(lads_preview.utm_crs_for_lonlat(12.5, 41.9), "EPSG:32633")

    def test_point_cloud_and_las_use_the_same_crs(self):
        t = from_origin(530000, 180000, 1, 1)
        cloud = lads_preview.build_lads_point_cloud(bumpy(1.0, 50), {"transform": t}, "EPSG:27700", target_crs=None)
        self.assertEqual(cloud["target_crs"], "EPSG:27700")
        self.assertGreaterEqual(cloud["origin_x"], 530000)

    def test_ply_export_and_caption_keep_the_crs(self):
        t = from_origin(530000, 180000, 1, 1)
        with tempfile.TemporaryDirectory() as d:
            meta = export_terrain_3d(bumpy(1.0, 30), t, "EPSG:27700", d, formats=("ply",))
            head = Path(meta["paths"]["ply"]).read_bytes()[:400].decode("latin-1")
            self.assertIn("EPSG:27700", head)
            self.assertEqual(json.loads(Path(meta["paths"]["sidecar"]).read_text())["crs"], "EPSG:27700")
        cap = view_caption({"render_mode": "relief_mesh", "crs": "EPSG:27700", "cell_size_m": 1.0,
                            "relief_scale_m": 18.0, "vertical_exaggeration": 2.5})
        self.assertIn("EPSG:27700", cap)
        self.assertIn("18 m", cap)


class Cloud3ScaleTests(unittest.TestCase):
    def relief(self, res):
        dem = bumpy(res)
        g = lads_preview.build_browser_terrain_grid(dem, {"transform": from_origin(500000, 5000000, res, res)},
                                                     "EPSG:32633", target_crs=None, max_side=1000,
                                                     cloud_preprocess_key="cloud3")
        return g, g["z"] - dem

    def test_sigma_is_in_metres(self):
        for res in (0.5, 1.0, 2.0):
            with self.subTest(res=res):
                g, _ = self.relief(res)
                self.assertEqual(g["relief_sigma_m"], 18.0)
                self.assertAlmostEqual(g["relief_sigma_cells"], 18.0 / res, places=3)

    def test_same_terrain_at_three_cell_sizes_gives_comparable_relief(self):
        out = {}
        for res in (0.5, 1.0, 2.0):
            _, d = self.relief(res)
            k = int(round(2.0 / res))
            out[res] = d.reshape(d.shape[0] // k, k, d.shape[1] // k, k).mean(axis=(1, 3))
        ref = out[1.0]
        for res in (0.5, 2.0):
            with self.subTest(res=res):
                r = np.corrcoef(out[res].ravel(), ref.ravel())[0, 1]
                self.assertGreater(r, 0.95)
                self.assertAlmostEqual(float(np.std(out[res])) / float(np.std(ref)), 1.0, delta=0.2)

    def test_one_metre_dtm_keeps_previous_behaviour(self):
        dem = bumpy(1.0)
        g, _ = self.relief(1.0)
        old, _ = lads_preview._enhance_local_relief(lads_preview._sanitize_surface_for_lads(dem), sigma=18.0, gain=4.0)
        np.testing.assert_allclose(g["z"], old, atol=1e-3)


if __name__ == "__main__":
    unittest.main()
