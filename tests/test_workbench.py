import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from rasterio.transform import from_origin

from airchgis import workbench
from tests.test_enhance import clean_terrain, dirty


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(workbench, "OUT_DIR", Path(self.tmp.name))
        self.patch.start()
        dem, _ = dirty(clean_terrain())
        t = from_origin(350000, 4800160, 1.0, 1.0)
        self.wb = workbench.Workbench(dem, t, "EPSG:32633", {"transform": t, "crs": "EPSG:32633"}, name="test")

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def ev(self, **kw):
        kw.setdefault("nonce", f"n{len(kw)}{kw.get('action')}")
        return workbench.handle_event(self.wb, kw, compute=lambda m, v: (np.asarray(self.wb.dem) * 0 + 1.0 + np.random.rand(*self.wb.dem.shape), None))

    def test_best_view_adds_after_and_before_layers_and_details(self):
        self.ev(action="best_view", width=4)
        ids = [l["id"] for l in self.wb.layers]
        self.assertEqual(ids[:2], ["best", "before"])
        self.assertTrue(self.wb.layers[0]["visible"])
        self.assertFalse(self.wb.layers[1]["visible"])
        self.assertIn("shows features about 4 m wide", self.wb.message)
        self.assertEqual(len(self.wb.details["cleaning"]), 4)
        self.assertTrue(self.wb.details["ranking"])
        self.assertTrue(self.wb.layers[0]["image"].startswith("data:image/png;base64,"))

    def test_relief_views_fused_and_downloads(self):
        self.ev(action="fused", width=4, nonce="f0")
        self.assertIn("at least two relief views", self.wb.message)
        self.ev(action="relief", method="Slope", value=None, nonce="r1")
        self.assertEqual(self.wb.layers[0]["name"], "Slope")
        self.ev(action="relief", method="Sky-View Factor", value=8, nonce="r2")
        self.ev(action="relief", method="Simple Local Relief Model", value=12, nonce="r3")
        self.assertEqual(len([l for l in self.wb.layers if l["id"].startswith("view")]), 3)
        self.ev(action="fused", width=4, nonce="f1")
        self.assertTrue(self.wb.message)
        top = self.wb.layers[0]["id"]
        self.ev(action="contrast", layer=top, nonce="c1")
        self.assertTrue(self.wb.layers[0]["id"].endswith("_clahe"))
        self.ev(action="download", layer=top, nonce="d1")
        self.assertEqual(self.wb.download["mime"], "image/tiff")
        self.assertTrue(base64.b64decode(self.wb.download["b64"])[:2] in (b"II", b"MM"))
        self.ev(action="script", nonce="s1")
        script = base64.b64decode(self.wb.download["b64"])
        self.assertIn(b"run_tool('relief_view'", script)
        self.ev(action="figure", fmt="pdf", dpi=100, width_mm=90, drape=top, nonce="g1")
        self.assertTrue(base64.b64decode(self.wb.download["b64"]).startswith(b"%PDF"))
        self.ev(action="remove", layer=top, nonce="x1")
        self.assertNotIn(top, [l["id"] for l in self.wb.layers])
        self.assertEqual(self.wb.done_nonce, "x1")

    def test_ui_replaces_previous_relief_and_contrast_layers(self):
        self.ev(action="relief", method="Hillshade", value=315, replace=True, nonce="first")
        old = self.wb.layers[0]["id"]
        self.ev(action="relief", method="Slope", value=None, replace=True, nonce="second")
        self.assertEqual([layer["name"] for layer in self.wb.layers], ["Slope"])
        self.assertNotIn(old, self.wb.arrays)
        self.assertNotIn(old, self.wb.paths)
        current = self.wb.layers[0]["id"]
        self.ev(action="contrast", layer=current, replace=True, nonce="contrast")
        self.assertEqual(len(self.wb.layers), 1)
        self.assertTrue(self.wb.layers[0]["id"].endswith("_clahe"))
        self.ev(action="relief", method="Sky-View Factor", value=8, replace=True, nonce="third")
        self.assertEqual(len(self.wb.layers), 1)
        self.assertEqual(self.wb.layers[0]["name"], "Sky-View Factor (8)")
        self.assertTrue(self.wb.layers[0]["visible"])
        self.assertEqual(len(self.wb.arrays), 1)

    def test_map_messages_only_report_warnings_and_errors(self):
        self.ev(action="relief", method="Hillshade", value=315, nonce="initial")
        self.assertEqual(self.wb.map_args({})["message"], "")
        self.ev(action="fused", width=4, nonce="insufficient")
        self.assertIn("at least two", self.wb.map_args({})["message"])
        self.ev(action="download", layer="missing", nonce="invalid")
        self.assertEqual(self.wb.map_args({})["message_level"], "error")
        self.ev(action="relief", method="Slope", value=None, nonce="success")
        self.assertEqual(self.wb.map_args({})["message"], "")

    def test_errors_are_messages_and_reload(self):
        self.ev(action="download", layer="nope", nonce="x")
        self.assertTrue(self.wb.message.startswith("Not completed"))
        self.assertEqual(workbench.handle_event(self.wb, {"action": "load_another", "nonce": "y"}), "reload")
        args = self.wb.map_args({"views": []})
        for key in ("layers", "message", "details", "download", "done_nonce", "tools", "elevation"):
            self.assertIn(key, args)

    def test_sites_upload(self):
        csv = "name,lon,lat\nA,13.15,43.337\nB,13.1501,43.3372\n"
        self.ev(action="sites", filename="sites.csv", b64=base64.b64encode(csv.encode()).decode(), nonce="k")
        self.assertIn("2 known sites", self.wb.message)
        self.assertTrue(self.wb.sites)


class ComponentFilesTests(unittest.TestCase):
    def test_component_assets_exist_and_have_no_historical_layers(self):
        from airchgis.map.workbench_component import COMPONENT_DIR

        for name in ("index.html", "workbench.js", "workbench.css", "detectorlab_map.css"):
            self.assertTrue((COMPONENT_DIR / name).exists(), name)
        js = (COMPONENT_DIR / "workbench.js").read_text()
        self.assertIn("streamlit:componentReady", js)
        self.assertIn("streamlit:setComponentValue", js)
        for word in ("roman", "Itiner", "historical-italy"):
            self.assertNotIn(word, js.lower() if word == "roman" else js)


if __name__ == "__main__":
    unittest.main()


class MetricTests(unittest.TestCase):
    def test_geographic_terrain_is_reprojected_to_utm(self):
        t = from_origin(13.40, 42.08, 0.0002777778, 0.0002777778)
        dem = np.random.default_rng(0).normal(500, 5, (60, 80)).astype(np.float32)
        out, tr, crs, prof = workbench.to_metric(dem, t, "EPSG:4326", {"transform": t, "crs": "EPSG:4326"})
        self.assertEqual(crs.to_epsg(), 32633)
        self.assertGreater(abs(tr.a), 15)
        self.assertLess(abs(tr.a), 40)
        self.assertTrue(np.isfinite(out).mean() > 0.8)
