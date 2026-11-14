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
        for case, resolution, size in zip([{"id": name, "path": FOLDER / ("Vaassen_AHN4_DTM_" + name + ".tif")} for name in ("0p5m", "1m", "5m")], (.5, 1., 5.), (2000, 1000, 200)):
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

    def test_english_reference_is_native_one_metre(self):
        case = next(c for c in CASES if c["id"] == "england_1")
        metadata = json.loads((case["path"].parent / "provenance.json").read_text())
        self.assertTrue(metadata["native"])
        self.assertEqual(hashlib.sha256(case["path"].read_bytes()).hexdigest(), metadata["sha256"])
        with rasterio.open(case["path"]) as src:
            self.assertEqual(src.res, (1., 1.))
            self.assertEqual(src.crs.to_epsg(), 27700)
            self.assertEqual(src.shape, (1000, 1000))
            self.assertEqual(src.read(1, masked=True).count(), 1000000)

    def test_use_case_button_opens_real_terrain(self):
        app = AppTest.from_file(APP, default_timeout=120).run()
        for case in CASES:
            self.assertEqual(app.button(key="as_case_" + case["id"]).disabled, case.get("disabled", False))
        app.button(key="as_case_england_1").click().run()
        self.assertFalse(app.exception)
        wb = app.session_state["as_wb"]
        self.assertEqual(wb.dem.shape, (1000, 1000))
        self.assertEqual(wb.res, 1.)
        self.assertTrue(wb.layers)
        self.assertEqual(str(wb.crs), "EPSG:27700")

    def test_italian_cases_open_georeferenced_terrain_with_references(self):
        for case in CASES[:2]:
            with self.subTest(case=case["id"]):
                metadata = json.loads((case["path"].parent / "provenance.json").read_text())
                self.assertEqual(hashlib.sha256(case["path"].read_bytes()).hexdigest(), metadata["sha256"])
                with rasterio.open(case["path"]) as src:
                    self.assertEqual(src.crs.to_epsg(), 4326)
                    self.assertEqual(list(src.shape), metadata["shape"])
                    self.assertEqual(src.nodata, -9999)
                app = AppTest.from_file(APP, default_timeout=120).run()
                app.button(key="as_case_" + case["id"]).click().run()
                self.assertFalse(app.exception)
                wb = app.session_state["as_wb"]
                self.assertTrue(wb.crs.is_projected)
                self.assertTrue(wb.layers)
                self.assertEqual(wb.use_case["label"], case["label"])
                self.assertTrue(wb.use_case["references"][0]["url"].startswith("https://"))
                self.assertEqual(wb.use_case["summary"], case["summary"])


if __name__ == "__main__":
    unittest.main()
