import tempfile
import unittest
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

from airchgis import preprocess
from airchgis.gis import tools
from airchgis.gis.provenance import ProvenanceLog


def write_las(path, n=20000, ground_class=True, outliers=30, seed=0):
    import laspy

    rng = np.random.default_rng(seed)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    ground = 100 + 0.02 * x + 0.5 * np.exp(-((x - 50) ** 2) / 20)  # a 0.5 m bank along y
    is_ground = rng.random(n) < 0.6
    z = np.where(is_ground, ground, ground + rng.uniform(2, 15, n))  # vegetation above ground
    ox, oy = rng.uniform(0, 100, outliers), rng.uniform(0, 100, outliers)
    oz = 100 + rng.uniform(80, 120, outliers)
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = [0.01, 0.01, 0.01]
    header.offsets = [0, 0, 0]
    las = laspy.LasData(header)
    las.x, las.y, las.z = np.r_[x, ox], np.r_[y, oy], np.r_[z, oz]
    if ground_class:
        las.classification = np.r_[np.where(is_ground, 2, 5), np.full(outliers, 7)].astype(np.uint8)
    las.write(str(path))
    return path


class PointCloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.las = write_las(Path(self.tmp.name) / "cloud.las")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ground_class_density_and_suggested_cell(self):
        out, steps = preprocess.grid_point_cloud(self.las, Path(self.tmp.name) / "dtm.tif")
        by = {s["step"]: s for s in steps}
        self.assertAlmostEqual(by["ground"]["measures"]["ground_share"], 0.6, delta=0.03)
        self.assertAlmostEqual(by["density"]["measures"]["density_pts_m2"], 1.2, delta=0.2)
        self.assertEqual(by["density"]["measures"]["suggested_cell_m"], 1.0)
        for s in steps:
            self.assertTrue(s["note"])

    def test_every_method_recovers_the_bank(self):
        import rasterio

        for method in preprocess.METHODS:
            out, _ = preprocess.grid_point_cloud(self.las, Path(self.tmp.name) / f"{method}.tif", method=method, cell=2.0)
            with rasterio.open(out) as src:
                a = src.read(1).astype(float)
                a[a == -9999] = np.nan
            profile = np.nanmedian(a, axis=0)
            self.assertGreater(profile[25] - profile[5], 0.3, method)  # bank at x = 50 m (column 25)
            self.assertLess(np.nanmax(a), 103, method)  # vegetation and outliers did not leak into the DTM

    def test_without_ground_class_it_says_so(self):
        las = write_las(Path(self.tmp.name) / "noclass.las", ground_class=False)
        _, steps = preprocess.grid_point_cloud(las, Path(self.tmp.name) / "n.tif", method="min")
        self.assertIn("No ground class", steps[0]["note"])

    def test_tool_is_recorded(self):
        log = ProvenanceLog("t")
        r = tools.run_tool("grid_point_cloud", log=log, input=str(self.las), output=str(Path(self.tmp.name) / "t.tif"), method="idw")
        self.assertEqual(r["status"], "ok")
        self.assertIn("run_tool('grid_point_cloud'", log.to_python())


class DTMTests(unittest.TestCase):
    def test_voids_resample_and_checks(self):
        t = from_origin(0, 100, 0.5, 0.5)
        y, x = np.mgrid[0:200, 0:200].astype(float)
        dem = 50 + 0.01 * x
        dem[90:95, 90:95] = np.nan
        out, tr, steps = preprocess.prepare_dtm(dem, t, fill_voids=True, cell=1.0)
        by = {s["step"]: s for s in steps}
        self.assertEqual(out.shape, (100, 100))
        self.assertAlmostEqual(abs(tr.a), 1.0)
        self.assertEqual(by["voids"]["measures"]["void_share_after"], 0.0)
        self.assertIn("artifacts", by)
        self.assertIn("50.0", by["vertical"]["note"])

    def test_vertical_units_warning(self):
        self.assertIn("vertical units", preprocess.check_vertical(np.full((5, 5), 12000.0))["note"])
        self.assertEqual(preprocess.suggest_cell(4.0), 0.5)
        self.assertEqual(preprocess.suggest_cell(0.05), 5.0)


if __name__ == "__main__":
    unittest.main()


class WorkbenchPreprocessTests(unittest.TestCase):
    def test_events_prepare_regrid_resolution_and_script(self):
        import base64
        from unittest import mock

        import rasterio

        from airchgis import workbench

        with tempfile.TemporaryDirectory() as d, mock.patch.object(workbench, "OUT_DIR", Path(d)):
            las = write_las(Path(d) / "c.las")
            dtm, steps = preprocess.grid_point_cloud(las, Path(d) / "g.tif", cell=2.0)
            with rasterio.open(dtm) as src:
                a = src.read(1).astype(np.float32)
                a[a == -9999] = np.nan
                wb = workbench.Workbench(a, src.transform, "EPSG:32633", src.profile.copy(), name="c",
                                         source={"kind": "points", "path": str(las)}, notes=["1 tile"])
            workbench.handle_event(wb, {"action": "prepare", "fill_voids": True, "nonce": "p"})
            view = wb.prep_view()
            names = [s["step"] for s in view["steps"]]
            for n in ("input", "crs", "nodata", "vertical", "voids", "artifacts"):
                self.assertIn(n, names)
            self.assertEqual(wb.layers[0]["name"], "Hillshade (315)")
            workbench.handle_event(wb, {"action": "regrid", "method": "idw", "cell_m": 4.0, "nonce": "r"})
            self.assertFalse(wb.message.startswith("Not completed"), wb.message)
            self.assertAlmostEqual(wb.res, 4.0, places=3)
            self.assertIn("interpolation", [s["step"] for s in wb.prep_view()["steps"]])
            workbench.handle_event(wb, {"action": "resolution", "width": 1.0, "nonce": "s"})
            self.assertIn(wb.resolution["verdict"], ("warn", "refuse"))
            self.assertTrue(wb.resolution["message"])
            workbench.handle_event(wb, {"action": "script", "nonce": "t"})
            script = base64.b64decode(wb.download["b64"])
            for tool in (b"grid_point_cloud", b"prepare_dtm", b"relief_view"):
                self.assertIn(tool, script)
