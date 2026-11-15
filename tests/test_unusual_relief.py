import tempfile
import unittest
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

from airchgis.ai import synthetic as sy
from airchgis.ai import unusual_relief as ur
from airchgis.gis.provenance import ProvenanceLog
from airchgis.gis.tools import run_tool
from airchgis.workbench import Workbench, handle_event, write_raster

WIDTH = 5.0


def auc_rows(kind, seed=0):
    dem, truth, _ = sy.terrain(kind, seed=seed)
    score, labels, areas, report = ur.unusual_relief(dem, 1.0, WIDTH)
    cmp = ur.compare_with_rvt(dem, 1.0, WIDTH, score, labels, sy.feature_points(truth))
    return {r["layer"]: r["auc"] for r in cmp["rows"]}, cmp, report


class EasyTerrainTests(unittest.TestCase):
    """Ditch, mound and road under a regional slope, smooth natural hills and noise."""

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.cmp, cls.report = auc_rows("easy")

    def test_beats_every_single_rvt_view_and_both_blends(self):
        ai = self.rows["Unusual relief (AI)"]
        others = {k: v for k, v in self.rows.items() if k != "Unusual relief (AI)"}
        self.assertIn("VAT (RVT blend)", others)
        self.assertIn("e3MSTP (RVT blend)", others)
        for name, auc in others.items():
            with self.subTest(view=name):
                self.assertGreater(ai, auc + 0.05)
        self.assertGreater(ai, 0.9)
        self.assertIn("better than all of them", self.cmp["verdict"])

    def test_priority_areas_lie_on_the_buried_features(self):
        known = self.cmp["known"]
        self.assertGreater(known["n_areas"], 0)
        self.assertGreaterEqual(known["precision_at_k"], 0.9)
        self.assertGreater(known["hit_rate"], 0.25)

    def test_each_area_says_what_drives_it(self):
        dem, _, _ = sy.terrain("easy")
        _, _, areas, _ = ur.unusual_relief(dem, 1.0, WIDTH)
        self.assertTrue(areas)
        for a in areas:
            self.assertTrue(a["drivers"])
            self.assertIn("than the surrounding terrain", a["note"])
            self.assertIn(a["drivers"][0]["view"], dict(ur.FEATURES).values())


class NaturalTerrainTests(unittest.TestCase):
    def test_no_priority_area_on_natural_terrain_at_the_default(self):
        for kind in ("easy", "hard"):
            for seed in range(4):
                with self.subTest(kind=kind, seed=seed):
                    dem, _, _ = sy.terrain(kind, features=False, seed=seed)
                    _, labels, areas, report = ur.unusual_relief(dem, 1.0, WIDTH)
                    self.assertEqual(report["n_areas"], 0)
                    self.assertEqual(int(labels.max()), 0)
                    self.assertIn("no priority area", report["note"])

    def test_share_of_the_area_never_exceeds_the_sensitivity(self):
        dem, _, _ = sy.terrain("easy")
        for sens, (share, _) in ur.SENSITIVITY.items():
            with self.subTest(sensitivity=sens):
                _, _, _, report = ur.unusual_relief(dem, 1.0, WIDTH, sensitivity=sens)
                self.assertLessEqual(report["flagged_share"], share + 1e-9)


class HardTerrainTests(unittest.TestCase):
    """Fractal relief with terraces and a modern field boundary: the result is reported as it is."""

    def test_verdict_matches_the_numbers(self):
        rows, cmp, _ = auc_rows("hard")
        ai = rows["Unusual relief (AI)"]
        best = max(v for k, v in rows.items() if k != "Unusual relief (AI)" and "blend" not in k)
        blends = [v for k, v in rows.items() if "blend" in k]
        wins = ai > best and all(ai > b for b in blends)
        self.assertEqual("better than all of them" in cmp["verdict"], wins)
        self.assertEqual("does not beat every RVT view" in cmp["verdict"], not wins)


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_same_result(self):
        dem, _, _ = sy.terrain("easy", n=300)
        a = ur.unusual_relief(dem, 1.0, WIDTH, seed=3)
        b = ur.unusual_relief(dem, 1.0, WIDTH, seed=3)
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], b[1])

    def test_tool_is_recorded_and_replayed_with_its_seed(self):
        dem, _, _ = sy.terrain("easy", n=300)
        prof = {"transform": from_origin(500000, 4600000, 1, 1), "crs": "EPSG:32633"}
        with tempfile.TemporaryDirectory() as d:
            src = write_raster(dem, prof, "EPSG:32633", Path(d) / "dem.tif")
            log = ProvenanceLog("test")
            r = run_tool("unusual_relief", log=log, input=str(src), output=str(Path(d) / "ai.tif"),
                         target_feature_width_m=WIDTH, seed=7, output_areas=str(Path(d) / "ai.geojson"))
            self.assertEqual(r["status"], "ok")
            self.assertTrue(Path(r["outputs"]["priorities"]).exists())
            self.assertTrue(Path(d, "ai.geojson").exists())
            script = log.to_python()
            self.assertIn("run_tool('unusual_relief'", script)
            self.assertIn("'seed': 7", script)
            r2 = run_tool("unusual_relief", input=str(src), output=str(Path(d) / "ai2.tif"), target_feature_width_m=WIDTH,
                          seed=7)
            import rasterio

            with rasterio.open(r["outputs"]["output"]) as s1, rasterio.open(r2["outputs"]["output"]) as s2:
                np.testing.assert_array_equal(s1.read(1), s2.read(1))


class WorkbenchTests(unittest.TestCase):
    def test_3d_ai_relief_computes_missing_analysis_and_reuses_it(self):
        from unittest.mock import patch
        from RVT.scripts import lads_preview
        from airchgis.workbench import run_unusual_relief

        dem, _, _ = sy.terrain("easy", n=300)
        t = from_origin(500000, 4600000, 1, 1)
        wb = Workbench(dem, t, "EPSG:32633", {"transform": t, "crs": "EPSG:32633"}, name="ai_3d_test")
        grids = []

        def view3d():
            grids.append(lads_preview.build_browser_terrain_grid(
                wb.dem, wb.profile, wb.crs, target_crs=None, cloud_preprocess_key="ai_relief", ai=wb.ai_result))
            return "<html>AI Relief</html>"

        with patch("airchgis.workbench.run_unusual_relief", wraps=run_unusual_relief) as analyse:
            for nonce in ("first", "again"):
                handle_event(wb, {"action": "view3d", "cloud_key": "ai_relief", "width": WIDTH,
                                  "compare": False, "nonce": nonce}, view3d=view3d)
                self.assertNotEqual(wb.message_level, "error", wb.message)
                self.assertEqual(wb.view3d["id"], nonce)
            self.assertEqual(analyse.call_count, 1)
        self.assertEqual(len(grids), 2)
        self.assertTrue(grids[0]["ai_shown"])
        self.assertTrue(grids[0]["ai_views"])
        self.assertIn("ai_score", [layer["id"] for layer in wb.layers])

    def test_ai_layer_is_added_next_to_the_relief_view(self):
        dem, _, _ = sy.terrain("easy", n=300)
        t = from_origin(500000, 4600000, 1, 1)
        wb = Workbench(dem, t, "EPSG:32633", {"transform": t, "crs": "EPSG:32633"}, name="ai_test")
        handle_event(wb, {"action": "unusual_relief", "width": WIDTH, "sensitivity": "medium", "nonce": "n1"})
        self.assertNotEqual(wb.message_level, "error", wb.message)
        ids = [l["id"] for l in wb.layers]
        self.assertIn("ai_score", ids)
        self.assertIn("ai_areas", ids)
        relief = [l for l in wb.layers if l["id"] not in ("ai_score", "ai_areas")]
        self.assertTrue(relief and relief[0]["visible"])
        self.assertIn("not sites", wb.ai["note"])
        self.assertIn("No known features loaded", wb.ai["known"])
        self.assertEqual(wb.map_args({})["ai"]["width"], WIDTH)


class RingworkSiteTests(unittest.TestCase):
    """A concentric ringwork on a hill, a lake, a clipped edge with an artefact and a modern road."""

    @classmethod
    def setUpClass(cls):
        from scipy import ndimage

        cls.runs = []
        for seed in (0, 1):
            dem, masks = sy.ringwork_site(seed=seed)
            score, labels, areas, report = ur.unusual_relief(dem, 1.0, WIDTH)
            grown = {k: ndimage.binary_dilation(m, iterations=6) for k, m in masks.items()}
            cls.runs.append((areas, labels, report, grown))

    def test_ringwork_ranks_first_as_a_ring(self):
        for areas, labels, report, grown in self.runs:
            top = areas[0]
            self.assertEqual(top["kind"], "ring")
            self.assertTrue((grown["ring"] & (labels == top["id"])).any())
            self.assertGreaterEqual(len(top["radii_m"]), 2)
            self.assertIn("concentric", top["note"])

    def test_no_priority_in_the_lake_or_on_the_edge(self):
        for areas, labels, report, grown in self.runs:
            self.assertGreater(report["water_share"], 0.03)
            for a in areas:
                with self.subTest(area=a["id"]):
                    self.assertFalse((grown["lake"] & (labels == a["id"])).any())
                    self.assertFalse((grown["edge"] & (labels == a["id"])).any())

    def test_modern_road_is_not_first(self):
        for areas, labels, report, grown in self.runs:
            self.assertFalse((grown["road"] & (labels == areas[0]["id"])).any())

    def test_no_ring_on_natural_terrain(self):
        for kind in ("easy", "hard"):
            for seed in range(4):
                dem, _, _ = sy.terrain(kind, features=False, seed=seed)
                self.assertEqual(ur.unusual_relief(dem, 1.0, WIDTH)[3]["n_rings"], 0)


class SteppedHillTests(unittest.TestCase):
    """Irregular stepped bands around a summit, with geological steps and agricultural terraces as negatives."""

    def test_bands_rank_first_and_negatives_give_no_structure(self):
        from scipy import ndimage

        for seed in (0, 1):
            dem, masks = sy.stepped_hill_site(seed=seed)
            _, labels, areas, _ = ur.unusual_relief(dem, 1.0, WIDTH)
            grown = {k: ndimage.binary_dilation(m, iterations=6) for k, m in masks.items()}
            self.assertTrue(areas)
            self.assertIn(areas[0]["kind"], ("ring", "hilltop bands"))
            self.assertTrue((grown["bands"] & (labels == areas[0]["id"])).any())
            for a in areas:
                if a["kind"] in ("ring", "hilltop bands"):
                    self.assertFalse((grown["geology"] & (labels == a["id"])).any())
                    self.assertFalse((grown["agri"] & (labels == a["id"])).any())

    def test_hill_bands_follow_a_real_band_and_not_natural_terrain(self):
        from airchgis.enhance import metrics
        from scipy import ndimage

        # a hill with a sunken band at a constant level all around: persistent at that level
        yy, xx = np.mgrid[0:400, 0:400].astype(float)
        hill = 30 * np.exp(-(((xx - 200) / 80) ** 2 + ((yy - 200) / 60) ** 2))
        gy, gx = np.gradient(hill)
        d = (hill - (hill.max() - 8)) / np.maximum(np.hypot(gx, gy), 1e-3)
        dem = 100 + hill - 0.5 * np.exp(-(d / 2) ** 2) * (np.abs(d) < 10)
        dem += np.random.default_rng(0).normal(0, 0.03, dem.shape)
        f, miss = metrics.finite_fill(dem)
        s = metrics.target_scale_px(WIDTH, 1.0)
        dog = ndimage.gaussian_filter(f, s) - ndimage.gaussian_filter(f, 3 * s)
        levels, M, _ = ur._level_profiles(f, miss, dog, 1.0, 200, 200)
        pers, t = ur._band_persistence(M)
        # the sunken band is found at its level (the band-pass filter also puts raised rims beside it)
        sunken = np.where(t < 0, pers, 0.0)
        k = int(np.argmax(sunken))
        self.assertAlmostEqual(levels[k], 8.0, delta=1.5)
        self.assertGreater(pers[k], 0.6)
        for kind in ("easy", "hard"):
            for seed in range(4):
                dem, _, _ = sy.terrain(kind, features=False, seed=seed)
                self.assertEqual(ur.unusual_relief(dem, 1.0, WIDTH)[3]["n_hills"], 0)

    def test_compact_area_near_the_edge_is_kept_with_a_note(self):
        dem, _, _ = sy.terrain("easy", n=300, features=False, seed=1)
        dem = dem.astype(float)
        yy, xx = np.mgrid[0:300, 0:300]
        dem += 0.8 * np.exp(-((xx - 150) ** 2 + (yy - 37) ** 2) / (2 * 4.0 ** 2))  # a mound 37 m from the border
        _, _, wide, _ = ur.unusual_relief(dem, 1.0, WIDTH, edge_m=60.0)
        _, _, narrow, _ = ur.unusual_relief(dem, 1.0, WIDTH, edge_m=10.0)
        near = lambda areas: [a for a in areas if abs(a["row"] - 37) < 8 and abs(a["col"] - 150) < 8]
        self.assertFalse(near(wide))
        self.assertTrue(near(narrow))


class AutoRunTests(unittest.TestCase):
    def setUp(self):
        dem, _, _ = sy.terrain("easy", n=300)
        t = from_origin(500000, 4600000, 1, 1)
        self.wb = Workbench(dem, t, "EPSG:32633", {"transform": t, "crs": "EPSG:32633"}, name="ai_auto")

    def test_ai_relief_runs_the_analysis_when_needed(self):
        calls = []
        handle_event(self.wb, {"action": "view3d", "cloud_key": "ai_relief", "width": WIDTH, "nonce": "a"},
                     view3d=lambda: calls.append(1) or "<html></html>")
        self.assertNotEqual(self.wb.message_level, "error", self.wb.message)
        self.assertIsNotNone(self.wb.ai_result)
        self.assertEqual(calls, [1])
        self.assertIn("ai_score", [l["id"] for l in self.wb.layers])
        self.assertIn("run_tool('unusual_relief'", self.wb.log.to_python())

    def test_same_settings_reuse_the_cached_result(self):
        from airchgis.workbench import run_unusual_relief

        run_unusual_relief(self.wb, width=WIDTH)
        steps = len(self.wb.log.steps)
        run_unusual_relief(self.wb, width=WIDTH)
        self.assertEqual(len(self.wb.log.steps), steps)
        run_unusual_relief(self.wb, width=WIDTH, sensitivity="high")
        self.assertEqual(len(self.wb.log.steps), steps + 1)

    def test_plain_sentence_when_there_is_no_terrain(self):
        from airchgis.workbench import ensure_unusual_relief

        self.wb.dem = np.full((50, 50), np.nan, dtype=np.float32)
        self.wb.ai_result = None
        self.assertIn("Load a terrain first", ensure_unusual_relief(self.wb))


class ThreeDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from RVT.scripts import lads_preview

        cls.lp = lads_preview
        dem, _, _ = sy.terrain("easy")
        cls.dem = dem
        cls.profile = {"transform": from_origin(500000, 4600000, 1, 1), "nodata": None}
        score, labels, areas, _ = ur.unusual_relief(dem, 1.0, WIDTH, transform=cls.profile["transform"])
        cls.ai = {"score": score, "labels": labels, "areas": areas, "width": WIDTH}

    def grid(self, mode, **kw):
        return self.lp.build_browser_terrain_grid(self.dem, self.profile, "EPSG:32633", target_crs=None, max_side=600,
                                                  cloud_preprocess_key=mode, **kw)

    def test_ai_relief_mode_colours_by_score_and_lists_views(self):
        g = self.grid("ai_relief", ai=self.ai)
        self.assertEqual(g["mode_label"], "AI Relief")
        self.assertTrue(g["ai_shown"])
        self.assertTrue(1 <= len(g["ai_views"]) <= self.lp.AI_MAX_VIEWS)
        outline = np.all(g["colors"] == np.array(self.lp.AI_OUTLINE_RGB, dtype=np.uint8), axis=-1)
        self.assertGreater(int(outline.sum()), 0)
        for v in g["ai_views"]:
            self.assertEqual(len(v["target"]), 3)
            self.assertAlmostEqual(float(np.hypot(*v["side"])), 1.0, places=3)
            self.assertGreater(v["light"][2], 0)

    def test_ai_relief_needs_the_ai_result(self):
        with self.assertRaises(RuntimeError):
            self.grid("ai_relief")

    def test_priorities_toggle_in_the_other_modes(self):
        off = self.grid("cloud3", ai=self.ai, show_ai=False)
        on = self.grid("cloud3", ai=self.ai, show_ai=True)
        self.assertFalse(off["ai_views"])
        self.assertFalse(off["ai_shown"])
        self.assertTrue(on["ai_views"])
        self.assertGreater(int((on["colors"] != off["colors"]).any(axis=-1).sum()), 0)

    def test_adaptive_exaggeration_is_off_by_default(self):
        auto = self.grid("ai_relief", ai=self.ai)
        adaptive = self.grid("ai_relief", ai=self.ai, adaptive_ve=True)
        self.assertTrue(auto["ve_source"].startswith("automatic"))
        self.assertTrue(adaptive["ve_source"].startswith("adaptive"))
        self.assertTrue(1.0 <= adaptive["z_scale"] <= 5.0)

    def test_viewer_and_caption_carry_the_ai_information(self):
        from airchgis.terrain.view_export import view_caption

        g = self.grid("ai_relief", ai=self.ai)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "viewer.html"
            self.lp.write_browser_cloud_viewer(path, g)
            html = path.read_text(encoding="utf-8")
        self.assertIn("const AI_VIEWS = [", html)
        self.assertIn('aria-label="Anomalies"', html)
        self.assertIn('id="ai-hover-info"', html)
        self.assertIn("Possible interpretation", html)
        self.assertNotIn("AI priorities outlined in cyan: places to check, not sites", html)
        for view in g["ai_views"]:
            self.assertTrue(view["interpretation"])
            self.assertIn("relief_m", view)
        self.assertIn('const MODE_LABEL = "AI Relief"', html)
        cap = view_caption({"mode_label": "AI Relief", "render_mode": "mesh", "ai_shown": True, "ai_width_m": 5.0,
                            "ai_view": {"label": "Area 1", "light_azimuth": 90}, "vertical_exaggeration": 2.0,
                            "ve_source": "adaptive (from the height and width of the priority features)"})
        self.assertIn("AI Relief mode", cap)
        self.assertIn("Area 1", cap)
        self.assertIn("not sites", cap)
        self.assertIn("(adaptive)", cap)


if __name__ == "__main__":
    unittest.main()
