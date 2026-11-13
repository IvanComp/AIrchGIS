import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin

from airchgis.gis import backend, guardrails, tools, workflows
from airchgis.gis.provenance import ProvenanceLog, file_sha256
from airchgis.terrain import export3d


def synthetic_dtm(folder, size=60, res=1.0):
    """A tilted plane with a 4 m wide bank and a ditch, in EPSG:32633."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    z = 100 + 0.05 * x + 0.02 * y
    z[:, 20:24] += 0.6
    z[30:33, :] -= 0.4
    z[0, 0] = -9999.0
    path = Path(folder) / "dtm.tif"
    profile = dict(driver="GTiff", height=size, width=size, count=1, dtype="float32", crs="EPSG:32633",
                   transform=from_origin(350000, 4800000 + size * res, res, res), nodata=-9999.0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(z, 1)
    return path


class RegistryTests(unittest.TestCase):
    def test_every_tool_has_a_valid_schema(self):
        self.assertGreaterEqual(len(tools.REGISTRY), 10)
        for name, tool in tools.REGISTRY.items():
            schema = tool.parameters
            self.assertEqual(schema["type"], "object", name)
            for req in schema["required"]:
                self.assertIn(req, schema["properties"], name)
            for prop in schema["properties"].values():
                self.assertIn("description", prop, name)
            self.assertGreater(len(tool.description), 20, name)

    def test_specs_in_claude_and_function_formats(self):
        claude = tools.tool_specs()
        self.assertTrue(all({"name", "description", "input_schema"} <= set(s) for s in claude))
        oai = tools.tool_specs("openai")
        self.assertTrue(all(s["type"] == "function" and "parameters" in s["function"] for s in oai))
        json.dumps(claude)

    def test_validation_rejects_bad_parameters(self):
        with self.assertRaises(tools.ToolError):
            tools.run_tool("hillshade", input="a.tif")  # missing output
        with self.assertRaises(tools.ToolError):
            tools.run_tool("check_resolvability", feature_width_m=5, sensor="hubble")
        with self.assertRaises(tools.ToolError):
            tools.run_tool("check_resolvability", feature_width_m=5, colour="red")

    def test_qgis_command_line(self):
        cmd = backend.build_command("native:hillshade", {"INPUT": "a b.tif", "Z_FACTOR": 1.0, "X": None, "FLAG": True}, exe="qgis_process")
        self.assertEqual(cmd[:5], ["qgis_process", "run", "native:hillshade", "--json", "--"])
        self.assertIn("INPUT=a b.tif", cmd)
        self.assertIn("FLAG=true", cmd)
        self.assertFalse(any(c.startswith("X=") for c in cmd))


class GuardrailTests(unittest.TestCase):
    def test_roman_streets_are_refused_on_sentinel2(self):
        r = guardrails.check_resolvability(5, sensor="sentinel-2")
        self.assertEqual(r.verdict, "refuse")
        self.assertLess(r.snr_single_date, 2.0)
        self.assertIn("LiDAR", r.message)

    def test_twenty_metre_features_pass(self):
        self.assertEqual(guardrails.check_resolvability(20, sensor="sentinel-2").verdict, "ok")
        self.assertEqual(guardrails.check_resolvability(10, sensor="sentinel-2").verdict, "warn")

    def test_stacking_dates_raises_snr(self):
        one = guardrails.check_resolvability(10, n_dates=1)
        many = guardrails.check_resolvability(10, n_dates=9)
        self.assertAlmostEqual(many.snr_stacked / one.snr_stacked, 3.0, places=1)

    def test_crop_mark_workflow_refuses_and_explains(self):
        r = workflows.crop_mark_screening(5)
        self.assertEqual(r["status"], "refused")
        self.assertEqual(r["log"].steps[0].tool, "check_resolvability")
        ok = workflows.crop_mark_screening(40)
        self.assertEqual(ok["status"], "ok")
        self.assertTrue(ok["settings"]["parcel_interior_statistics"])


class NativeToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dtm = synthetic_dtm(self.dir)
        patcher = mock.patch.object(backend, "find_qgis_process", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_relief_tools_write_georeferenced_rasters(self):
        log = ProvenanceLog("test")
        for name, extra in [("hillshade", {}), ("slope", {}), ("sky_view_factor", {"radius_m": 5}),
                            ("openness", {"radius_m": 5}), ("local_relief_model", {"radius_m": 15})]:
            out = self.dir / f"{name}.tif"
            r = tools.run_tool(name, log=log, input=str(self.dtm), output=str(out), **extra)
            self.assertEqual(r["backend"], "native")
            with rasterio.open(out) as src:
                self.assertEqual(src.crs.to_epsg(), 32633)
                self.assertEqual(src.shape, (60, 60))
                self.assertTrue(np.isfinite(src.read(1, masked=True)).any())
        self.assertEqual(len(log.steps), 5)
        self.assertEqual(log.steps[0].inputs[0]["sha256"], file_sha256(self.dtm))

    def test_bank_stands_out_in_local_relief(self):
        out = self.dir / "lrm.tif"
        tools.run_tool("local_relief_model", input=str(self.dtm), output=str(out), radius_m=15)
        with rasterio.open(out) as src:
            lrm = src.read(1)
        self.assertGreater(np.mean(lrm[5:25, 20:24]), np.mean(lrm[5:25, 40:44]) + 0.2)

    def test_guardrail_refuses_subpixel_targets(self):
        r = tools.run_tool("hillshade", input=str(self.dtm), output=str(self.dir / "h.tif"), target_feature_width_m=0.2)
        self.assertEqual(r["status"], "refused")
        self.assertFalse((self.dir / "h.tif").exists())

    def test_clip_and_zonal_stats(self):
        poly = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:32633"}},
                "features": [{"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Polygon", "coordinates": [[
                    [350010, 4800010], [350030, 4800010], [350030, 4800030], [350010, 4800030], [350010, 4800010]]]}}]}
        aoi = self.dir / "aoi.geojson"
        aoi.write_text(json.dumps(poly))
        r = tools.run_tool("clip_raster_to_aoi", input=str(self.dtm), aoi=str(aoi), output=str(self.dir / "clip.tif"))
        with rasterio.open(r["outputs"]["output"]) as src:
            self.assertEqual(src.shape, (20, 20))
        z = tools.run_tool("zonal_stats", raster=str(self.dtm), polygons=str(aoi), output=str(self.dir / "z.geojson"))
        props = json.loads(Path(z["outputs"]["output"]).read_text())["features"][0]["properties"]
        self.assertEqual(props["_count"], 400)
        self.assertGreater(props["_mean"], 100)

    def test_workflow_saves_replayable_scripts(self):
        r = workflows.lidar_micro_relief(self.dtm, self.dir / "wf", radius_m=5)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(set(r["outputs"]), {"lrm", "svf", "openness_pos", "openness_neg", "hillshade"})
        script = Path(r["scripts"]["python"]).read_text()
        self.assertEqual(script.count("run_tool("), 5)
        compile(script, "replay.py", "exec")
        data = json.loads(Path(r["scripts"]["json"]).read_text())
        self.assertEqual(len(data["steps"]), 5)
        self.assertIn("rvt", data["environment"])

    def test_replay_script_reproduces_outputs(self):
        log = ProvenanceLog("replay")
        out = self.dir / "hs.tif"
        tools.run_tool("hillshade", log=log, input=str(self.dtm), output=str(out))
        first = file_sha256(out)
        out.unlink()
        exec(compile(log.to_python().replace("log.save_json('replay_provenance.json')", ""), "replay", "exec"), {})
        self.assertEqual(file_sha256(out), first)

    def test_shell_script_lists_qgis_commands(self):
        log = ProvenanceLog("qgis")
        with mock.patch.object(backend, "find_qgis_process", return_value=Path("/x/qgis_process")), \
             mock.patch.object(backend, "run_algorithm", return_value={"OUTPUT": "o.tif"}) as run:
            r = tools.run_tool("hillshade", log=log, input=str(self.dtm), output="o.tif")
        self.assertEqual(r["backend"], "qgis")
        self.assertEqual(run.call_args[0][0], "native:hillshade")
        shell = log.to_shell()
        self.assertIn("native:hillshade", shell)
        self.assertIn("INPUT=", shell)


class Export3DTests(unittest.TestCase):
    def test_round_trip_keeps_georeference(self):
        with tempfile.TemporaryDirectory() as tmp:
            dtm_path = synthetic_dtm(tmp, size=30, res=2.0)
            r = tools.run_tool("export_3d", input=str(dtm_path), output_dir=str(Path(tmp) / "out"),
                               vertical_exaggeration=2.0, visualization="Local Relief Model", source="synthetic")
            meta = json.loads(Path(r["outputs"]["sidecar"]).read_text())
            self.assertEqual(meta["crs"], "EPSG:32633")
            self.assertEqual(meta["point_cloud"]["exported_points"], 30 * 30 - 1)
            self.assertEqual(meta["relief_visualization"], "Local Relief Model")

            xs, ys, zs = export3d.read_ply(r["outputs"]["ply"])
            self.assertAlmostEqual(xs.min(), 350001.0)
            self.assertAlmostEqual(ys.max(), 4800059.0)

            import laspy

            las = laspy.read(r["outputs"]["point_cloud"])
            self.assertEqual(len(las.points), 30 * 30 - 1)
            self.assertAlmostEqual(float(las.x.min()), 350001.0, places=2)
            self.assertEqual(las.header.parse_crs().to_epsg(), 32633)

            gltf, pos = export3d.read_glb(r["outputs"]["mesh"])
            ox, oy, oz = meta["mesh"]["origin"]
            self.assertAlmostEqual(float(pos[:, 0].min()) + ox, 350001.0, places=1)
            self.assertAlmostEqual(float(pos[:, 1].max()) / 2.0 + oz, meta["elevation_range_m"][1], places=1)
            self.assertEqual(gltf["nodes"][0]["extras"]["crs"], "EPSG:32633")


if __name__ == "__main__":
    unittest.main()


class Figure3DTests(unittest.TestCase):
    def test_pdf_and_png_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            dtm = synthetic_dtm(tmp)
            log = ProvenanceLog("figure")
            r = tools.run_tool("export_3d_figure", log=log, input=str(dtm), output=str(Path(tmp) / "fig.pdf"))
            self.assertEqual(r["status"], "ok")
            data = Path(r["outputs"]["output"]).read_bytes()
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertGreater(r["outputs"]["vertical_exaggeration"], 0)
            r = tools.run_tool("export_3d_figure", log=log, input=str(dtm), output=str(Path(tmp) / "fig.png"),
                               dpi=150, width_mm=100.0, scale_bar=False, north_arrow=False, caption="")
            from PIL import Image

            w, h = Image.open(r["outputs"]["output"]).size
            self.assertAlmostEqual(w, round(100 / 25.4 * 150), delta=2)
            self.assertEqual([s.tool for s in log.steps], ["export_3d_figure", "export_3d_figure"])
            with self.assertRaises(tools.ToolError):
                tools.run_tool("export_3d_figure", input=str(dtm), output=str(Path(tmp) / "fig.svg"))
