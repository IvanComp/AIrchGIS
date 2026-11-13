import json
import re
import unittest

import numpy as np
from rasterio.transform import from_origin

from airchgis.map import view


class MapViewTests(unittest.TestCase):
    def setUp(self):
        self.t = from_origin(350000, 4800000, 1.0, 1.0)
        y, x = np.mgrid[0:60, 0:80].astype(np.float32)
        self.dem = 100 + 0.1 * x + 0.05 * y

    def test_layer_is_georeferenced_in_lonlat(self):
        layer = view.georeference(self.dem, self.t, "EPSG:32633", "relief", "Hillshade", "desc")
        w, s, e, n = layer.bounds
        self.assertTrue(13.1 < w < e < 13.2 and 43.3 < s < n < 43.4)
        self.assertAlmostEqual((e - w) * 111320 * np.cos(np.radians(43.3)), 80, delta=3)
        self.assertGreater(len(layer.png_b64), 100)

    def test_rgb_layer_and_elevation_grid(self):
        rgb = np.dstack([self.dem / self.dem.max()] * 3)
        layer = view.georeference(rgb, self.t, "EPSG:32633", "rgb", "RGB", "")
        self.assertTrue(layer.visible)
        grid = view.elevation_grid(self.dem, self.t, "EPSG:32633")
        vals = [v for v in grid["values"] if v is not None]
        self.assertEqual(len(grid["values"]), grid["width"] * grid["height"])
        self.assertAlmostEqual(min(vals), 100, delta=1)

    def test_html_contains_config_and_no_historical_layers(self):
        layer = view.georeference(self.dem, self.t, "EPSG:32633", "relief", "Hillshade", "desc")
        html = view.map_html([layer], height=500)
        cfg = json.loads(re.search(r"window.AIRCHGIS_MAP=(\{.*?\});</script>", html, re.S).group(1))
        self.assertEqual(cfg["layers"][0]["id"], "relief")
        self.assertIn("maplibre-gl", html)
        self.assertIn("height:500px", html)
        for word in ("roman", "Itiner", "historical-italy", "APM"):
            self.assertNotIn(word, html.split("window.AIRCHGIS_MAP")[1])


if __name__ == "__main__":
    unittest.main()
