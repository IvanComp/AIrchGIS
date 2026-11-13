import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from airchgis import data_input as di
from airchgis import sources
from airchgis.gis import tools
from airchgis.gis.guardrails import check_resolvability
from airchgis.spectral import local_engine as le

ORIGIN = (500000, 6200000)


def write_tif(path, bands, res=3.0, crs="EPSG:32632", descriptions=None, nodata=None):
    if bands.ndim == 2:
        bands = bands[None]
    count, h, w = bands.shape
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=count, dtype="float32", crs=crs,
                       transform=from_origin(ORIGIN[0], ORIGIN[1], res, res), nodata=nodata) as dst:
        dst.write(bands.astype(np.float32))
        for i, d in enumerate(descriptions or [], 1):
            dst.set_band_description(i, d)
    return path


def field_scene(seed, marked=True, size=80):

    rng = np.random.default_rng(seed)
    red = 0.05 + rng.normal(0, 0.004, (size, size))
    nir = 0.40 + rng.normal(0, 0.01, (size, size))
    if marked:
        nir[:, 38:42] -= 0.08
        red[:, 38:42] += 0.02
    return np.stack([np.full_like(red, 0.04), np.full_like(red, 0.07), red, nir])


class RasterTests(unittest.TestCase):
    def test_description_in_plain_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_tif(Path(tmp) / "x.tif", np.zeros((50, 40)), res=0.5)
            info = di.describe_raster(p)
            self.assertEqual(info["pixel_size_m"], 0.5)
            self.assertAlmostEqual(info["extent_m"][0], 20.0)
            text = di.plain_description(info)
            self.assertIn("0.50 m", text)
            self.assertIn("UTM zone 32N", text)

    def test_geographic_pixel_size_is_converted_to_metres(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "g.tif"
            with rasterio.open(p, "w", driver="GTiff", height=10, width=10, count=1, dtype="float32", crs="EPSG:4326",
                               transform=from_origin(12.0, 56.0, 0.0001, 0.0001)) as dst:
                dst.write(np.zeros((1, 10, 10), np.float32))
            self.assertAlmostEqual(di.describe_raster(p)["pixel_size_m"], 6.2, delta=0.3)


class PointCloudTests(unittest.TestCase):
    def test_las_is_gridded_into_a_dtm_keeping_ground_only(self):
        import laspy

        with tempfile.TemporaryDirectory() as tmp:
            h = laspy.LasHeader(point_format=3, version="1.4")
            h.scales, h.offsets = np.array([0.01] * 3), np.array([ORIGIN[0], ORIGIN[1], 0.0])
            import pyproj

            h.add_crs(pyproj.CRS.from_epsg(32632))
            las = laspy.LasData(h)
            xs, ys = np.meshgrid(np.arange(0, 20, 0.5), np.arange(0, 20, 0.5))
            n = xs.size
            las.x = np.concatenate([xs.ravel(), xs.ravel()]) + ORIGIN[0]
            las.y = np.concatenate([ys.ravel(), ys.ravel()]) + ORIGIN[1]
            las.z = np.concatenate([np.full(n, 10.0), np.full(n, 25.0)])
            las.classification = np.concatenate([np.full(n, 2), np.full(n, 5)]).astype(np.uint8)
            src = Path(tmp) / "cloud.las"
            las.write(str(src))
            info = di.describe_point_cloud(src)
            self.assertEqual(info["points"], 2 * n)
            out = di.rasterize_point_cloud(src, Path(tmp) / "dtm.tif", resolution=1.0)
            with rasterio.open(out) as r:
                a = r.read(1)
                self.assertEqual(r.crs.to_epsg(), 32632)
            self.assertAlmostEqual(float(np.median(a[a != -9999])), 10.0, places=2)

            r = tools.run_tool("load_point_cloud", input=str(src), output=str(Path(tmp) / "dtm2.tif"))
            self.assertTrue(Path(r["outputs"]["dtm"]).exists())


class SiteTests(unittest.TestCase):
    def test_csv_with_semicolons_and_decimal_commas(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sites.csv"
            p.write_text("Name;Longitude;Latitude\nVilla A;12,5;41,9\nFort B;-1.25;51.75\n", encoding="utf-8")
            sites = di.read_sites(p)
            self.assertEqual([s.name for s in sites], ["Villa A", "Fort B"])
            self.assertAlmostEqual(sites[0].lon, 12.5)

    def test_csv_in_projected_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "xy.csv"
            p.write_text("id,x,y\n1,500000,6200000\n", encoding="utf-8")
            s = di.read_sites(p, crs="EPSG:32632")[0]
            self.assertAlmostEqual(s.lon, 9.0, places=3)
            self.assertAlmostEqual(s.lat, 55.93, places=1)

    def test_geojson_and_geopackage(self):
        with tempfile.TemporaryDirectory() as tmp:
            gj = {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"name": "Barrow"}, "geometry": {"type": "Point", "coordinates": [-2.0, 51.0]}},
                {"type": "Feature", "properties": {"site": "Enclosure"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}}]}
            p = Path(tmp) / "s.geojson"
            p.write_text(json.dumps(gj))
            sites = di.read_sites(p)
            self.assertEqual(sites[0].name, "Barrow")
            self.assertAlmostEqual(sites[1].lon, 0.8, places=1)
            from osgeo import ogr, osr

            gpkg = Path(tmp) / "s.gpkg"
            ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(gpkg))
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(32632)
            layer = ds.CreateLayer("sites", srs, ogr.wkbPoint)
            layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
            f = ogr.Feature(layer.GetLayerDefn())
            f.SetField("name", "Ringfort")
            f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT ({ORIGIN[0]} {ORIGIN[1]})"))
            layer.CreateFeature(f)
            ds = None
            s = di.read_sites(gpkg)[0]
            self.assertEqual(s.name, "Ringfort")
            self.assertAlmostEqual(s.lon, 9.0, places=3)
            self.assertEqual(tools.run_tool("load_sites", input=str(gpkg))["outputs"]["count"], 1)


class BandMappingTests(unittest.TestCase):
    def test_dates_and_band_tokens_from_file_names(self):
        self.assertEqual(di.parse_date("S2A_MSIL2A_20230615T101031_B04.tif"), date(2023, 6, 15))
        self.assertEqual(di.parse_date("drone_2024-05-02_ortho.tif"), date(2024, 5, 2))
        self.assertIsNone(di.parse_date("dtm.tif"))
        files = ["T32_20230615_B04.tif", "T32_20230615_B08.tif", "T32_20230710_B04.tif", "T32_20230710_B08.tif", "notes.tif"]
        groups = di.group_single_band_files(files, di.BAND_PRESETS["Sentinel-2 (all 12 L2A bands)"]["tokens"])
        self.assertEqual([g["date"] for g in groups], [date(2023, 6, 15), date(2023, 7, 10)])
        self.assertEqual(set(groups[0]["files"]), {"red", "nir"})
        landsat = di.group_single_band_files(["LC09_L2SP_20220801_SR_B4.TIF", "LC09_L2SP_20220801_SR_B5.TIF"],
                                             di.BAND_PRESETS["Landsat 8/9 (OLI)"]["tokens"])
        self.assertEqual(set(landsat[0]["files"]), {"red", "nir"})

    def test_roles_from_band_descriptions(self):
        roles = di.roles_from_descriptions(["Blue", "Green", "Red", "Red Edge", "NIR"])
        self.assertEqual(roles, {"blue": 1, "green": 2, "red": 3, "rededge": 4, "nir": 5})

    def test_single_band_files_on_different_grids_are_stacked(self):
        with tempfile.TemporaryDirectory() as tmp:
            red = write_tif(Path(tmp) / "x_20230615_B04.tif", np.full((20, 20), 0.05), res=10)
            swir = write_tif(Path(tmp) / "x_20230615_B11.tif", np.full((10, 10), 0.2), res=20)
            scene = di.load_single_band_scene({"red": str(red), "swir1": str(swir)})
            self.assertEqual(scene.bands["swir1"].shape, (20, 20))
            self.assertEqual(scene.gsd_m, 10.0)


class LocalEngineTests(unittest.TestCase):
    def _scenes(self, tmp, n=3):
        scenes = []
        for i in range(n):
            p = write_tif(Path(tmp) / f"planet_2023061{i}.tif", field_scene(i), res=3.0)
            scenes.append(di.load_scene(p, di.BAND_PRESETS["PlanetScope 4-band (B, G, R, NIR)"]["positions"]))
        return scenes

    def test_buried_wall_is_found_in_uploaded_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = le.run_local_analysis(self._scenes(tmp), radius_m=30, target="Crop marks")
            deficit = res.layers["Vegetation deficit"]
            on_wall = np.nanmean(deficit[10:70, 38:42])
            off_wall = np.nanmean(deficit[10:70, 10:30])
            self.assertGreater(on_wall, 3 * off_wall)
            self.assertEqual(res.vegetation_index, "NDVI")
            self.assertEqual(res.gsd_m, 3.0)
            self.assertTrue(all(r["phase"] == "vegetation" for r in res.table))
            self.assertIn("Field boundaries", res.layers)
            self.assertLess(np.mean(res.layers["Field boundaries"][10:70, 38:42]), 0.2)

    def test_a_different_crop_is_masked_as_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenes = []
            for i, growth in enumerate((0.0, 0.3, 0.6)):
                bands = field_scene(i, marked=False)
                bands[3, :, :40] += growth
                bands[2, :, :40] -= growth / 15
                p = write_tif(Path(tmp) / f"s_2023060{i}.tif", bands, res=3.0)
                scenes.append(di.load_scene(p, di.BAND_PRESETS["PlanetScope 4-band (B, G, R, NIR)"]["positions"]))
            res = le.run_local_analysis(scenes, radius_m=30)
            self.assertGreater(np.mean(res.layers["Field boundaries"][:, 38:42].max(axis=1)), 0.9)

    def test_known_sites_on_the_wall_score_above_chance(self):
        from pyproj import Transformer

        with tempfile.TemporaryDirectory() as tmp:
            res = le.run_local_analysis(self._scenes(tmp), radius_m=30)
            tr = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
            sites = []
            for row in range(15, 65, 10):
                lon, lat = tr.transform(ORIGIN[0] + 40 * 3.0, ORIGIN[1] - row * 3.0 - 1.5)
                sites.append(di.Site(f"s{row}", lon, lat))
            r = le.sample_sites_auc(res.layers["Vegetation deficit"], res.transform, res.crs, sites)
            self.assertEqual(r["sites_inside"], 5)
            self.assertGreater(r["auc"], 0.9)

    def test_rgb_only_orthophoto_uses_visible_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            rgb = field_scene(1)[[2, 1, 0]]
            p = write_tif(Path(tmp) / "ortho.tif", rgb, res=0.2)
            scene = di.load_scene(p, di.BAND_PRESETS["RGB only (orthophoto)"]["positions"])
            res = le.run_local_analysis([scene], radius_m=5)
            self.assertEqual(res.vegetation_index, "VARI")
            self.assertTrue(any("fewer than three dates" in n for n in res.notes))

    def test_layers_written_as_multiband_geotiff(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = le.run_local_analysis(self._scenes(tmp, 2), radius_m=30)
            out = le.write_layers(res, Path(tmp) / "layers.tif")
            with rasterio.open(out) as r:
                self.assertEqual(r.count, len(res.layers))
                self.assertEqual(r.descriptions[0], "Vegetation deficit")


class GuardrailWithRealPixelSize(unittest.TestCase):
    def test_pixel_size_comes_from_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_tif(Path(tmp) / "planet.tif", field_scene(0), res=3.0)
            r = tools.run_tool("check_raster_resolvability", input=str(p), feature_width_m=5)
            self.assertEqual(r["outputs"]["pixel_size_from_file_m"], 3.0)
            self.assertNotEqual(r["outputs"]["verdict"], "refuse")
        self.assertEqual(check_resolvability(5, gsd_m=10).verdict, "refuse")
        self.assertEqual(check_resolvability(5, gsd_m=0.5).verdict, "ok")


class SourceTests(unittest.TestCase):
    def test_registry_lists_upload_alternatives_worldwide(self):
        keys = {p.key for p in sources.PROVIDERS}
        self.assertTrue({"ee_s2", "cop_dem", "opentopo", "nl_ahn", "fr_ign", "us_3dep", "uk_defra"} <= keys)
        for p in sources.PROVIDERS:
            self.assertTrue(p.url.startswith("http"))
            self.assertIn(p.access, {"automatic", "api key", "earth engine", "manual"})

    def test_copernicus_tiles_cover_the_box(self):
        names = sources.cop_dem_tile_names(-0.5, 51.2, 0.3, 51.6)
        self.assertEqual(names, ["Copernicus_DSM_COG_10_N51_00_W001_00_DEM", "Copernicus_DSM_COG_10_N51_00_E000_00_DEM"])

    def test_api_key_is_stored_privately(self):
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sources, "CONFIG_PATH", Path(tmp) / "c.json"):
            sources.save_config_value("opentopography_api_key", "secret")
            self.assertTrue(sources.has_secret("opentopography_api_key"))
            self.assertEqual(os.stat(Path(tmp) / "c.json").st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
