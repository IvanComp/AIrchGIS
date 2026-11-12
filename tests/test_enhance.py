import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from airchgis.enhance import bestview, clean, contrast, fuse, metrics, multispectral, points
from airchgis.gis import tools
from airchgis.gis.provenance import ProvenanceLog

POTENTIA_DTM = Path(os.environ.get(
    "AIRCHGIS_POTENTIA_DTM",
    Path.home() / "Documents/ChatGPT/DetectorLab/ArchaeoScope/RVT/generated_dtm/DTM/regional_selection_20260627_173505_DTM.tif"))


def clean_terrain(size=160):
    """Gently undulating terrain with a 4 m bank, a 3 m ditch and a round mound (1 m pixels)."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float64)
    z = 50 + 0.03 * x + 0.02 * y + 0.8 * np.sin(x / 37.0) * np.cos(y / 41.0)
    z[:, 60:64] += 0.5                                   # bank
    z[100:103, :] -= 0.4                                 # ditch
    z += 0.6 * np.exp(-((x - 120) ** 2 + (y - 40) ** 2) / (2 * 4.0 ** 2))  # mound
    return z


def dirty(z, seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:z.shape[0], 0:z.shape[1]]
    a = z + 0.15 * np.sin(2 * np.pi * (x * np.cos(0.5) + y * np.sin(0.5)) / 5.0)   # oblique banding, 5 px
    a = a + rng.normal(0, 0.05, z.shape)
    spikes = rng.choice(z.size, 60, replace=False)
    sy, sx = np.unravel_index(spikes, z.shape)
    a[sy, sx] += rng.choice([-3.0, 3.0], 60)
    a[30:34, 30:34] = np.nan                            # an interior void
    return a, (sy, sx)


def write_tif(path, arr, res=1.0, crs="EPSG:32633", count=None):
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr[None]
    profile = dict(driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0], dtype="float32", crs=crs,
                   transform=from_origin(350000, 4800000 + arr.shape[1] * res, res, res), nodata=-9999.0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.where(np.isfinite(arr), arr, -9999.0))
    return Path(path)


def bank_height(a):
    return float(np.nanmedian(a[20:90, 60:64]) - np.nanmedian(np.concatenate([a[20:90, 54:58], a[20:90, 66:70]], axis=1)))


class CleaningTests(unittest.TestCase):
    def setUp(self):
        self.truth = clean_terrain()
        self.noisy, self.spikes = dirty(self.truth)

    def test_destripe_removes_banding_and_keeps_the_bank(self):
        a = np.where(np.isfinite(self.noisy), self.noisy, self.truth)
        before, _ = clean.stripe_energy(a)
        out, rep = clean.destripe(a)
        self.assertTrue(rep["applied"])
        self.assertLess(rep["after"], 0.5 * before)
        self.assertAlmostEqual(bank_height(out), 0.5, delta=0.1)

    def test_no_banding_means_no_change(self):
        out, rep = clean.destripe(self.truth)
        self.assertFalse(rep["applied"])
        np.testing.assert_allclose(out, self.truth)

    def test_despike_replaces_injected_spikes(self):
        out, rep = clean.remove_spikes(self.noisy)
        sy, sx = self.spikes
        ok = np.isfinite(self.noisy[sy, sx]) & np.isfinite(out[sy, sx])
        err = np.abs(out[sy, sx] - self.truth[sy, sx])[ok]
        self.assertGreaterEqual((err < 1.0).mean(), 0.9)
        self.assertLess(rep["pixels_replaced"], 0.02 * self.noisy.size)

    def test_fill_voids_interpolates_interior_holes_only(self):
        a = self.truth.copy()
        a[30:34, 30:34] = np.nan
        a[:, :3] = np.nan  # outside the survey: must stay empty
        out, rep = clean.fill_voids(a)
        self.assertTrue(np.isfinite(out[30:34, 30:34]).all())
        self.assertLess(np.abs(out[30:34, 30:34] - self.truth[30:34, 30:34]).max(), 0.1)
        self.assertTrue(np.isnan(out[:, :3]).all())

    def test_denoise_reduces_noise_and_keeps_features(self):
        a = self.truth + np.random.default_rng(1).normal(0, 0.05, self.truth.shape)
        out, rep = clean.denoise(a)
        self.assertLess(rep["after"], 0.8 * rep["before"])
        self.assertAlmostEqual(bank_height(out), bank_height(a), delta=0.08)

    def test_pipeline_reports_and_improves_visibility(self):
        out, reports, summary = clean.clean_dtm(self.noisy, 1.0)
        self.assertEqual([r["step"] for r in reports], list(clean.STEPS))
        self.assertLess(summary["after"]["stripe_energy"], summary["before"]["stripe_energy"])
        self.assertLess(summary["after"]["spike_fraction"], summary["before"]["spike_fraction"])
        self.assertLess(summary["after"]["void_fraction"], summary["before"]["void_fraction"])
        self.assertLess(summary["after"]["noise_sigma"], summary["before"]["noise_sigma"])
        import rvt.vis

        def lrm_cnr(d):
            f, _ = metrics.finite_fill(d)
            return metrics.visibility(rvt.vis.slrm(f.astype(np.float32), radius_cell=12), 1.0, 4.0)["cnr"]

        self.assertGreater(lrm_cnr(out), lrm_cnr(np.where(np.isfinite(self.noisy), self.noisy, np.nanmedian(self.noisy))))

    def test_zero_fill_outside_the_survey_is_masked(self):
        a = self.truth + 800
        a[:, :40] = 0.0
        out, n = metrics.zero_nodata(a)
        self.assertEqual(n, 160 * 40)
        self.assertTrue(np.isnan(out[:, :40]).all())
        low, n2 = metrics.zero_nodata(self.truth - 50)  # real zeros near sea level stay
        self.assertEqual(n2, 0)

    def test_unknown_step_is_rejected(self):
        with self.assertRaises(ValueError):
            clean.clean_dtm(self.truth, 1.0, steps=["sharpen"])


class BestViewTests(unittest.TestCase):
    def setUp(self):
        self.dem = clean_terrain() + np.random.default_rng(2).normal(0, 0.02, (160, 160))

    def test_ranking_is_sorted_and_explained(self):
        r = bestview.rank(self.dem, 1.0, 4.0)
        cnr = [x["score"] for x in r["ranking"]]
        self.assertGreaterEqual(len(cnr), 10)
        self.assertEqual(cnr, sorted(cnr, reverse=True))
        self.assertIn(r["ranking"][0]["name"], r["explanation"])
        self.assertIn("not the probability", r["explanation"])

    def test_auc_at_known_features_is_reported(self):
        sites = [(40, 120), (50, 62), (70, 61), (101, 30), (101, 140)]
        r = bestview.rank(self.dem, 1.0, 4.0, site_pixels=sites)
        top = r["ranking"][0]
        self.assertIsNotNone(top["auc"])
        self.assertGreater(max(x["auc"] for x in r["ranking"]), 0.75)

    def test_fused_view_is_never_worse_than_the_best_layer(self):
        r = bestview.rank(self.dem, 1.0, 4.0)
        names = [x["name"] for x in r["ranking"][:4]]
        flat = metrics.flat_mask(self.dem, 1.0)
        fused, rep = fuse.fuse({n: r["arrays"][n] for n in names}, 1.0, 4.0, flat=flat)
        self.assertGreaterEqual(rep["score"], rep["best_single"]["score"] - 1e-9)
        self.assertAlmostEqual(sum(rep["weights"]), 1.0, places=6)
        pca, rep2 = fuse.fuse({n: r["arrays"][n] for n in names}, 1.0, 4.0, method="pca")
        self.assertEqual(pca.shape, self.dem.shape)

    def test_rank_layers_for_any_image(self):
        z = clean_terrain()
        r = bestview.rank_layers({"signal": z - np.mean(z), "noise": np.random.default_rng(0).normal(size=z.shape)}, 1.0, 4.0)
        self.assertEqual(r["ranking"][0]["name"], "signal")


class ContrastTests(unittest.TestCase):
    def test_clahe_and_multiscale(self):
        img = clean_terrain()
        img[0, 0] = np.nan
        out, rep = contrast.enhance(img, "clahe")
        self.assertTrue(np.nanmin(out) >= 0 and np.nanmax(out) <= 1)
        self.assertTrue(np.isnan(out[0, 0]))
        self.assertGreater(rep["after"], rep["before"])
        out2, rep2 = contrast.enhance(img, "multiscale")
        self.assertGreater(rep2["after"], rep2["before"])

    def test_pansharpen_uses_the_real_pan_band(self):
        rng = np.random.default_rng(0)
        pan = rng.random((80, 80)) + clean_terrain(80) / 100
        ms = np.stack([pan.reshape(20, 4, 20, 4).mean(axis=(1, 3)) * f for f in (0.8, 1.0, 1.2)])
        for method in ("brovey", "hpf"):
            out, rep = contrast.pansharpen(ms, pan, method)
            self.assertEqual(out.shape, (3, 80, 80))
            self.assertGreater(min(rep["detail_correlation_with_pan"]), 0.5)
        with self.assertRaises(ValueError):
            contrast.pansharpen(ms, ms[0])


class MultispectralTests(unittest.TestCase):
    def scene(self):
        h = w = 60
        bands = {"blue": np.full((h, w), 0.04), "green": np.full((h, w), 0.07), "red": np.full((h, w), 0.05),
                 "nir": np.full((h, w), 0.35)}
        bands = {k: v + np.random.default_rng(i).normal(0, 0.005, (h, w)) for i, (k, v) in enumerate(bands.items())}
        for k in ("blue", "green", "red", "nir"):
            bands[k][5:20, 5:20] = 0.45  # bright white cloud
        for k in ("blue", "green", "red"):
            bands[k][30:45, 30:45] = 0.02
        bands["nir"][30:45, 30:45] = 0.05  # shadow
        return {k: v.astype(np.float32) for k, v in bands.items()}

    def test_cloud_and_shadow_are_found(self):
        b = self.scene()
        m = multispectral.masks_from_bands(b)
        self.assertGreater(m["cloud"][5:20, 5:20].mean(), 0.9)
        self.assertGreater(m["shadow"][30:45, 30:45].mean(), 0.9)
        clear = np.ones((60, 60), bool)
        clear[5:20, 5:20] = clear[30:45, 30:45] = False
        self.assertLess((m["cloud"] | m["shadow"])[clear].mean(), 0.02)
        q = multispectral.date_quality(b)
        self.assertAlmostEqual(q["clear_share"], 1 - 2 * 225 / 3600, delta=0.03)

    def test_scaled_values_and_scl(self):
        b = {k: v * 10000 for k, v in self.scene().items()}
        self.assertGreater(multispectral.masks_from_bands(b)["cloud"][5:20, 5:20].mean(), 0.9)
        scl = np.full((60, 60), 4)
        scl[:10] = 9
        q = multispectral.date_quality(self.scene(), scl=scl)
        self.assertEqual(q["source"], "SCL")
        self.assertAlmostEqual(q["cloud_share"], 10 / 60, places=3)

    def test_band_artifacts(self):
        b = self.scene()
        b["swir1"] = np.full((60, 60), 0.2, np.float32)
        ring = b["red"].copy()
        ring[:3] = 0
        ring[-3:] = 0
        ring[:, :3] = 0
        ring[:, -3:] = 0
        b["red"] = ring
        rows = {r["band"]: r["problems"] for r in multispectral.band_artifacts(b)}
        self.assertIn("constant band", rows["swir1"])
        self.assertIn("no-data ring at the edges", rows["red"])
        self.assertNotIn("constant band", rows["nir"])
        self.assertNotIn("no-data ring at the edges", rows["nir"])
        self.assertNotIn("saturated pixels", rows["nir"])


class PointCloudTests(unittest.TestCase):
    def test_statistical_outliers_are_removed(self):
        import laspy

        rng = np.random.default_rng(0)
        n = 4000
        xyz = np.column_stack([rng.uniform(0, 50, n), rng.uniform(0, 50, n), 100 + rng.normal(0, 0.05, n)])
        out = np.column_stack([rng.uniform(0, 50, 20), rng.uniform(0, 50, 20), rng.uniform(130, 160, 20)])
        allp = np.vstack([xyz, out])
        with tempfile.TemporaryDirectory() as tmp:
            header = laspy.LasHeader(point_format=3, version="1.2")
            header.scales = [0.01, 0.01, 0.01]
            header.offsets = [0, 0, 0]
            las = laspy.LasData(header)
            las.x, las.y, las.z = allp[:, 0], allp[:, 1], allp[:, 2]
            src = Path(tmp) / "cloud.las"
            las.write(str(src))
            rep = points.remove_outliers(src, Path(tmp) / "clean.las")
            self.assertGreaterEqual(rep["points_removed"], 18)
            self.assertGreaterEqual(rep["points_after"], int(0.99 * n))
            self.assertLess(rep["z_range_after"][1], 120)


class ToolTests(unittest.TestCase):
    def test_enhance_tools_run_and_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            noisy, _ = dirty(clean_terrain())
            dtm = write_tif(Path(tmp) / "dtm.tif", noisy)
            log = ProvenanceLog("enhance test")
            r = tools.run_tool("clean_terrain", log=log, input=str(dtm), output=str(Path(tmp) / "clean.tif"))
            self.assertEqual(r["status"], "ok")
            self.assertTrue(Path(r["outputs"]["output"]).exists())
            self.assertEqual(len(r["outputs"]["summary"]), 4)
            r = tools.run_tool("best_view", log=log, input=r["outputs"]["output"], output_dir=str(Path(tmp) / "bv"),
                               target_feature_width_m=4.0, quick=True)
            self.assertEqual(r["status"], "ok")
            self.assertTrue(Path(r["outputs"]["output"]).exists())
            ranking = json.loads(Path(r["outputs"]["ranking_json"]).read_text())
            self.assertEqual(ranking["ranking"][0]["name"], r["outputs"]["best"])
            r = tools.run_tool("fused_view", log=log, input=str(Path(tmp) / "clean.tif"), output=str(Path(tmp) / "fused.tif"),
                               target_feature_width_m=4.0, n_layers=3)
            self.assertGreaterEqual(r["outputs"]["gain_over_best_single"], 1.0 - 1e-9)
            r = tools.run_tool("enhance_contrast", log=log, input=str(Path(tmp) / "fused.tif"), output=str(Path(tmp) / "c.tif"))
            self.assertTrue(Path(r["outputs"]["output"]).exists())
            self.assertEqual([s.tool for s in log.steps], ["clean_terrain", "best_view", "fused_view", "enhance_contrast"])
            json.dumps(log.to_dict(), default=str)
            script = log.to_python()
            self.assertIn("run_tool('best_view'", script)

    def test_best_view_refuses_features_below_the_pixel_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            dtm = write_tif(Path(tmp) / "dtm.tif", clean_terrain(60))
            r = tools.run_tool("best_view", input=str(dtm), output_dir=str(Path(tmp) / "bv"), target_feature_width_m=0.5)
            self.assertEqual(r["status"], "refused")

    def test_image_quality_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = MultispectralTests().scene()
            img = write_tif(Path(tmp) / "img.tif", np.stack([b["blue"], b["green"], b["red"], b["nir"]]), res=10.0)
            r = tools.run_tool("image_quality", input=str(img), output_mask=str(Path(tmp) / "mask.tif"))
            self.assertLess(r["outputs"]["clear_share"], 0.9)
            self.assertTrue(Path(r["outputs"]["output_mask"]).exists())


@unittest.skipUnless(POTENTIA_DTM.exists(), "Potentia 5 m DTM not available on this computer")
class PotentiaSmokeTest(unittest.TestCase):
    def test_real_dtm_with_banding(self):
        with rasterio.open(POTENTIA_DTM) as src:
            a = src.read(1).astype(np.float64)
            if src.nodata is not None:
                a[a == src.nodata] = np.nan
            res = abs(src.transform.a)
        out, reports, summary = clean.clean_dtm(a, res)
        self.assertTrue(reports[0]["applied"], "banding should be detected")
        self.assertLess(summary["after"]["stripe_energy"], 0.5 * summary["before"]["stripe_energy"])
        self.assertLess(summary["after"]["noise_sigma"], summary["before"]["noise_sigma"])
        r = bestview.rank(out, res, 10.0)
        self.assertGreater(len(r["ranking"]), 10)


if __name__ == "__main__":
    unittest.main()
