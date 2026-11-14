import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np
from PIL import Image
from rasterio.transform import from_origin

from airchgis.terrain.view_export import save_current_view
from airchgis.terrain.export3d import export_terrain_3d, read_glb, read_ply


class CurrentViewExportTests(unittest.TestCase):
    def test_satellite_blend_is_recorded_in_the_export_caption(self):
        from airchgis.terrain.view_export import view_caption

        caption = view_caption({"relief_opacity": 35, "imagery_attribution": "© Esri, Maxar, Earthstar Geographics"})
        self.assertIn("relief opacity 35% over satellite imagery", caption)
        self.assertIn("Esri", caption)
        self.assertNotIn("satellite imagery", view_caption({"relief_opacity": 100}))

    def test_png_preserves_exact_captured_pixels_and_camera(self):
        pixels = np.zeros((60, 80, 3), dtype=np.uint8)
        pixels[5:25, 35:70] = [213, 157, 48]
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        encoded = base64.b64encode(stream.getvalue()).decode()
        camera = {"position": [13, -27, 16], "target": [4, 3, 2], "pixels": [80, 60]}
        with tempfile.TemporaryDirectory() as directory:
            path = save_current_view(encoded, Path(directory) / "view.png", camera)
            self.assertEqual(path.read_bytes(), stream.getvalue())
            np.testing.assert_array_equal(np.asarray(Image.open(path)), pixels)
            meta = json.loads(path.with_suffix(".view.json").read_text())
            self.assertEqual(meta["view"], camera)
            self.assertEqual(meta["image_pixels"], [80, 60])
            pdf = save_current_view(encoded, Path(directory) / "view.pdf", camera)
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            self.assertIn(b"/Width 80", pdf.read_bytes())
            self.assertIn(b"/Height 60", pdf.read_bytes())

    def test_transparent_background_survives_png_and_pdf_exports(self):
        pixels = np.zeros((48, 64, 4), dtype=np.uint8)
        pixels[10:35, 20:45] = [180, 130, 60, 255]
        pixels[9, 20:45] = [180, 130, 60, 120]
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        encoded = base64.b64encode(stream.getvalue()).decode()
        with tempfile.TemporaryDirectory() as directory:
            png = save_current_view(encoded, Path(directory) / "transparent.png", {"background": "none"})
            np.testing.assert_array_equal(np.asarray(Image.open(png)), pixels)
            pdf = save_current_view(encoded, Path(directory) / "transparent.pdf", {"background": "none"})
            self.assertIn(b"/SMask", pdf.read_bytes())

    def test_capture_rejects_invalid_image_or_format(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                save_current_view(base64.b64encode(b"invalid").decode(), Path(directory) / "x.png")
            with self.assertRaises(ValueError):
                save_current_view("", Path(directory) / "x.svg")

    def test_full_quality_data_exports_keep_every_valid_sample(self):
        terrain = np.arange(900, dtype=np.float32).reshape(30, 30) / 10 + 100
        terrain[0, 0] = np.nan
        transform = from_origin(350000, 4800000, .5, .5)
        original = terrain.copy()
        with tempfile.TemporaryDirectory() as directory:
            meta = export_terrain_3d(terrain, transform, "EPSG:32633", directory, max_points=None, mesh_max_side=None)
            self.assertEqual(meta["point_cloud"]["sample_step"], 1)
            self.assertEqual(meta["point_cloud"]["exported_points"], 899)
            self.assertEqual(meta["mesh"]["decimation_step"], 1)
            self.assertTrue(meta["paths"]["point_cloud"].endswith(".laz"))
            cloud = laspy.read(meta["paths"]["point_cloud"])
            self.assertEqual(len(cloud.points), 899)
            np.testing.assert_allclose(np.asarray(cloud.z), terrain[np.isfinite(terrain)], atol=.001)
            self.assertEqual(cloud.header.parse_crs().to_epsg(), 32633)
            x, y, z = read_ply(meta["paths"]["ply"])
            self.assertEqual(len(z), 899)
            np.testing.assert_array_equal(z, terrain[np.isfinite(terrain)])
        np.testing.assert_array_equal(terrain, original)


if __name__ == "__main__":
    unittest.main()
