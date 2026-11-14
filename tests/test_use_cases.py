import hashlib
import json
import unittest

import numpy as np
import rasterio
from streamlit.testing.v1 import AppTest

from airchgis.use_cases import CASES, FOLDER
from tests.test_help_page import APP


class UseCaseTests(unittest.TestCase):
    def test_downloaded_grids_and_source_provenance(self):
        metadata = json.loads((FOLDER / "provenance.json").read_text())
        self.assertEqual(metadata["license"], "CC0-1.0")
        self.assertEqual(metadata["source_grid_m"], .5)
        arrays = []
        bounds = []
        for case, resolution, size in zip(CASES, (.5, 1., 5.), (2000, 1000, 200)):
            with self.subTest(case=case["id"]):
                with rasterio.open(case["path"]) as src:
                    self.assertEqual(src.res, (resolution, resolution))
                    self.assertEqual(src.shape, (size, size))
                    self.assertEqual(src.crs.to_epsg(), 28992)
                    arrays.append(src.read(1, masked=True).filled(np.nan))
                    bounds.append(tuple(src.bounds))
                expected = next(f for f in metadata["files"] if f["name"] == case["path"].name)
                self.assertEqual(hashlib.sha256(case["path"].read_bytes()).hexdigest(), expected["sha256"])
        self.assertEqual(bounds[0], bounds[1])
        self.assertEqual(bounds[0], bounds[2])
        for derived, factor in zip(arrays[1:], (2, 10)):
            block = arrays[0][:200, :200].reshape(200 // factor, factor, 200 // factor, factor)
            count = np.isfinite(block).sum(axis=(1, 3))
            expected = np.full(count.shape, np.nan)
            np.divide(np.nansum(block, axis=(1, 3), dtype=np.float64), count, out=expected, where=count > 0)
            np.testing.assert_allclose(derived[:200 // factor, :200 // factor], expected, rtol=1e-6, equal_nan=True)

    def test_use_case_button_opens_real_terrain(self):
        app = AppTest.from_file(APP, default_timeout=120).run()
        for case in CASES:
            self.assertFalse(app.button(key="as_case_" + case["id"]).disabled)
        app.button(key="as_case_vaassen_5").click().run()
        self.assertFalse(app.exception)
        wb = app.session_state["as_wb"]
        self.assertEqual(wb.dem.shape, (200, 200))
        self.assertEqual(wb.res, 5.)
        self.assertTrue(wb.layers)
        self.assertEqual(str(wb.crs), "EPSG:28992")


if __name__ == "__main__":
    unittest.main()
