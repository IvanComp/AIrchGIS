import base64
import importlib
import inspect
import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from airchgis.rvt_api import MODULES, SETTINGS, RVTWorkspace, catalog, registry
from airchgis.workbench import Workbench, handle_event, offer_layer


def values(**kwargs):
    return {k: {"binding": "value", "value": v} for k, v in kwargs.items()}


def ref(key):
    return {"$ref": key}


class RVTAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        y, x = np.mgrid[:64, :64]
        self.dem = (100 + np.sin(x / 4) * 2 + np.cos(y / 7) + x * .2 + y * .1).astype("float32")
        t = from_origin(350000, 4800000, 1, 1)
        self.wb = Workbench(self.dem, t, "EPSG:32633", {"transform": t, "crs": "EPSG:32633", "width": 64, "height": 64})
        self.w = RVTWorkspace(self.wb, self.tmp.name)
        self.w.update_object("settings", {"svf_r_max": 5, "svf_n_dir": 8, "ld_min_rad": 1, "ld_max_rad": 3,
            "ld_anglr_res": 90, "mstp_local_scale": [1, 3, 1], "mstp_meso_scale": [3, 5, 1],
            "mstp_broad_scale": [5, 9, 2], "sim_shadow_dist": 5, "sim_nr_dir": 8, "msrm_feature_max": 10,
            "tile_size": [32, 32], "slrm_rad_cell": 10})

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalog_matches_every_public_callable_and_parameter(self):
        expected = set()
        for name in MODULES:
            module = importlib.import_module("rvt." + name)
            for key, obj in vars(module).items():
                if key.startswith("_") or getattr(obj, "__module__", None) != module.__name__:
                    continue
                if inspect.isfunction(obj) or inspect.isclass(obj):
                    expected.add(name + "." + key)
                if inspect.isclass(obj):
                    for method, descriptor in vars(obj).items():
                        fn = descriptor.__func__ if isinstance(descriptor, (staticmethod, classmethod)) else descriptor
                        if not method.startswith("_") and inspect.isfunction(fn):
                            expected.add(name + "." + key + "." + method)
        self.assertEqual(set(registry()), expected)
        self.assertEqual(len(expected), 148)
        for key, entry in registry().items():
            if key == "default.RVTVisualization":
                continue
            params = [p for p in inspect.signature(entry["callable"]).parameters if p not in {"self", "cls"}]
            self.assertEqual([p["name"] for p in entry["parameters"]], params, key)
        json.dumps(catalog(), allow_nan=False)
        key = self.w.execute("default.RVTVisualization")[0]
        self.assertEqual(self.w.items[key]["value"].value, "slp")

    def test_every_public_operation_executes(self):
        w = self.w
        seen = set()
        failures = []

        def run(operation, instance=None, **params):
            seen.add(operation)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    keys = w.execute(operation, values(**params), instance)
                return keys[0] if keys else None
            except Exception as exc:
                failures.append(f"{operation}: {type(exc).__name__}: {exc}")
                return None

        simple = {
            "byte_scale": {}, "slope_aspect": {}, "roll_fill_nans": {"shift": 1, "axis": 0}, "hillshade": {},
            "multi_hillshade": {"nr_directions": 8}, "mean_filter": {"kernel_radius": 3}, "slrm": {"radius_cell": 10},
            "horizon_shift_vector": {"radius_pixels": 5, "num_directions": 8},
            "sky_view_factor_compute": {"radius_max": 5, "num_directions": 8, "compute_opns": True, "compute_asvf": True},
            "sky_view_factor": {"svf_r_max": 5, "svf_n_dir": 8, "compute_opns": True, "compute_asvf": True},
            "local_dominance": {"min_rad": 1, "max_rad": 3, "angular_res": 90},
            "horizon_generate_coarse_dem": {"pyramid_scale": 3, "conv_from": -1, "conv_to": 1, "max_radius": 3},
            "horizon_generate_pyramids": {"max_fine_radius": 5, "max_pyramid_radius": 3},
            "sky_illumination": {"max_fine_radius": 5, "num_directions": 8, "compute_shadow": True}, "shadow_horizon": {},
            "msrm": {"feature_min": 0, "feature_max": 10, "scaling_factor": 2}, "integral_image": {},
            "max_elevation_deviation": {"minimum_radius": 1, "maximum_radius": 5, "step": 1},
            "mstp": {"local_scale": [1, 3, 1], "meso_scale": [3, 5, 1], "broad_scale": [5, 9, 2]}, "fill_where_nan": {},
        }
        for method, params in simple.items():
            run("vis." + method, **params)
        import rvt.vis
        w.add("pixel count", rvt.vis.integral_image(np.ones_like(self.dem)), "counts")
        w.add("sum", rvt.vis.integral_image(self.dem), "sums")
        w.add("squares", rvt.vis.integral_image(self.dem ** 2), "squares")
        run("vis.topographic_dev", dem_i_nr_pixels=ref("counts"), dem_i1=ref("sums"), dem_i2=ref("squares"), kernel_radius=3)
        for method in ("color_relief_image_map", "e3mstp", "e4mstp"):
            run("blend." + method)
        run("blend.create_blender_file_example")
        layer = run("blend.BlenderLayer", vis_method="Hillshade", minimum=0, maximum=1)
        run("blend.BlenderLayer.check_data", layer)
        combo = run("blend.BlenderCombination")
        run("blend.BlenderCombination.add_dem_arr", combo)
        run("blend.BlenderCombination.add_dem_path", combo)
        run("blend.BlenderCombination.create_layer", combo, vis_method="Hillshade", minimum=0, maximum=1)
        run("blend.BlenderCombination.add_layer", combo, layer=ref(layer))
        for method in ("layers_info", "check_data", "to_json", "render_all_images", "save_to_file"):
            run("blend.BlenderCombination." + method, combo)
        combo_file = next((v["value"] for k, v in reversed(list(w.items.items())) if isinstance(v["value"], Path) and v["value"].name == "file_path.json"), None)
        run("blend.BlenderCombination.read_from_file", combo, file_path=str(combo_file))
        conf = json.loads((SETTINGS / "default_blender_combinations.json").read_text())
        run("blend.BlenderCombination.read_from_json", combo, json_data=conf["combinations"][0])
        run("blend.BlenderCombination.create_log_file", combo, combination_name="test")
        run("blend.compare_2_combinations", combination1=ref(combo), combination2=ref(combo))
        combos = run("blend.BlenderCombinations")
        run("blend.BlenderCombinations.add_combination", combos, combination=ref(combo), name="test")
        run("blend.BlenderCombinations.combination_in_combinations", combos, input_combination=ref(combo))
        for method in ("combinations_names", "save_to_file"):
            run("blend.BlenderCombinations." + method, combos)
        run("blend.BlenderCombinations.read_from_file", combos, file_path=str(SETTINGS / "default_blender_combinations.json"))
        run("blend.BlenderCombinations.select_combination_by_name", combos, name="Archaeological (VAT)")
        run("blend.BlenderCombinations.remove_combination_by_name", combos, name="Archaeological (VAT)")
        run("blend.BlenderCombinations.remove_all_combinations", combos)
        terrain = run("blend.TerrainSettings")
        tc = json.loads((SETTINGS / "default_terrains_settings.json").read_text())["terrains_settings"][0]
        run("blend.TerrainSettings.read_from_json", terrain, json_data=tc)
        terrain_file = Path(self.tmp.name) / "single_terrain.json"
        terrain_file.write_text(json.dumps(tc))
        run("blend.TerrainSettings.read_from_file", terrain, file_path=str(terrain_file))
        run("blend.TerrainSettings.apply_terrain", terrain, combination=ref(combo))
        terrains = run("blend.TerrainsSettings")
        run("blend.TerrainsSettings.read_from_file", terrains, file_path=str(SETTINGS / "default_terrains_settings.json"))
        run("blend.TerrainsSettings.select_terrain_settings_by_name", terrains, name="general")
        run("blend.BlenderCombination.remove_all_layers", combo)
        grey = (self.dem - self.dem.min()) / np.ptp(self.dem)
        w.add("gray", grey, "gray")
        w.add("rgb", np.stack([grey, grey * .8, grey * .5]), "rgb")
        w.add("index", grey < .5, "index")
        common = {"image": ref("gray"), "img": ref("rgb"), "gray_scale": ref("gray"), "r": ref("gray"), "g": ref("gray"),
                  "b": ref("gray"), "c": ref("rgb"), "active": ref("rgb"), "background": ref("rgb"), "minimum": 0,
                  "maximum": 1, "normalization": "value", "blend_mode": "normal", "colormap": "viridis", "cmap": "viridis",
                  "idx_min_lt_zero": ref("index"), "idx_max_c_gt_one": ref("index"), "lum_c": ref("gray"),
                  "min_c": ref("gray"), "max_c": ref("gray"), "opacity": 50, "numeric_value": ref("gray"),
                  "visualization": "Hillshade", "min_norm": 0, "max_norm": 1, "mode": "value"}
        for name, entry in registry().items():
            if name.startswith("blend_func."):
                params = {p["name"]: common[p["name"]] for p in entry["parameters"] if p["name"] in common}
                if name.endswith(("normalize_perc", "lin_cutoff_calc_from_perc")):
                    params.update(minimum=2, maximum=2)
                if name.endswith("matrix_eq_min_lt_zero"):
                    params["min_c"] = [[-.2] * 64] * 64
                if name.endswith("matrix_eq_max_gt_one"):
                    params["max_c"] = [[1.2] * 64] * 64
                run(name, **params)
        run("default.RVTVisualization", value="hs")
        defaults = run("default.DefaultValues")
        for name in registry():
            if name.startswith("default.DefaultValues."):
                if name.endswith("read_default_from_file"):
                    params = {"file_path": str(SETTINGS / "default_settings.json")}
                elif name.endswith("get_visualization_file_name"):
                    params = {"path_8bit": False}
                elif name.endswith("get_visualization_path"):
                    params = {"path_8bit": False}
                elif name.endswith("float_to_8bit"):
                    params = {"float_arr": ref("gray")}
                else:
                    params = {}
                run(name, "settings", **params)
        for name in ("default.get_raster_arr", "default.get_raster_size", "default.save_raster"):
            run(name)
        run("tile.save_visualization_tile_by_tile", overlap=2, tile_size_x=32, tile_size_y=32)
        run("tile.save_rvt_visualization_tile_by_tile")
        self.assertEqual(seen, set(registry()))
        self.assertFalse(failures, "\n" + "\n".join(failures))
        np.testing.assert_array_equal(self.wb.dem, self.dem)

    def test_presets_exports_and_session(self):
        for name in catalog()["presets"]:
            with self.subTest(preset=name):
                result = self.w.preset(name)[0]
                self.w.show(result, rgb=True)
                self.assertEqual(len(self.wb.layers), 1)
                path = self.w.download(result, "geotiff")
                with rasterio.open(path) as src:
                    self.assertEqual(src.count, 1 if self.w.items[result]["value"].ndim == 2 else 3)
                    self.assertEqual(src.transform, self.wb.profile["transform"])
                    self.assertEqual(src.crs.to_epsg(), 32633)
        with zipfile.ZipFile(self.w.package()) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("session.json", archive.namelist())

    def test_upload_grid_batch_and_bindings(self):
        path = Path(self.tmp.name) / "different.tif"
        t = from_origin(360000, 4800000, 2, 2)
        profile = dict(self.wb.profile, transform=t)
        self.w._write_raster(path, self.dem, profile)
        key = self.w.upload(path.name, base64.b64encode(path.read_bytes()).decode())
        array_key = self.w.latest[-1]
        self.assertFalse(next(a for a in self.w.snapshot()["artifacts"] if a["id"] == array_key)["mapable"])
        with self.assertRaises(ValueError):
            self.w.show(array_key)
        output = self.w.batch("vis.hillshade", [key])
        files = [self.w.items[k]["value"] for k in output if isinstance(self.w.items[k]["value"], Path)]
        self.assertTrue(files)
        with rasterio.open(files[-1]) as src:
            self.assertEqual(src.transform, t)
        self.assertEqual(self.w.active_profile, self.wb.profile)
        key = self.w.execute("vis.slope_aspect")[0]
        params = {"slope": {"binding": "artifact", "id": key, "member": "slope"},
                  "aspect": {"binding": "artifact", "id": key, "member": "aspect"}}
        output = self.w.execute("vis.hillshade", params)[0]
        self.assertEqual(self.w.items[output]["value"].shape, self.dem.shape)
        self.assertEqual(self.w.items[self.w.execute("vis.multi_hillshade", values(nr_directions=8))[0]]["value"].shape, (8, 64, 64))

    def test_all_visualization_enum_outputs_and_tiled_exports(self):
        from rvt.default import RVTVisualization
        for visualization in RVTVisualization:
            with self.subTest(visualization=visualization.value):
                self.w.execute("default.DefaultValues.calculate_visualization", values(visualization=visualization.value, save_8bit=True), "settings")
                keys = self.w.execute("tile.save_rvt_visualization_tile_by_tile", values(rvt_visualization=visualization.value, save_8bit=True))
                files = [self.w.items[k]["value"] for k in keys if isinstance(self.w.items[k]["value"], Path)]
                self.assertTrue(files)
                for path in files:
                    if path.suffix == ".tif":
                        with rasterio.open(path) as src:
                            self.assertEqual(src.shape, self.dem.shape)
                            self.assertEqual(src.transform, self.wb.transform)

    def test_array_scaling_nondefault_ranges_and_no_input_mutation(self):
        source = np.array([[10., 30., 80.], [100., 170., 250.]])
        key = self.w.add("byte values", source)
        for operation in ("scale_within_0_and_1", "scale_strict_0_to_1", "scale_0_to_1"):
            with self.subTest(operation=operation):
                result = self.w.execute("blend_func." + operation, {"numeric_value": {"binding": "artifact", "id": key}})[0]
                array = self.w.items[result]["value"]
                self.assertEqual(array.shape, source.shape)
                self.assertTrue(np.isfinite(array).all())
                self.assertGreaterEqual(array.min(), 0)
                self.assertLessEqual(array.max(), 1)
                np.testing.assert_array_equal(self.w.items[key]["value"], source)
        result = self.w.execute("blend_func.scale_strict_0_to_1", values(numeric_value=[[5., 5.], [5., 5.]]))[0]
        np.testing.assert_array_equal(self.w.items[result]["value"], np.zeros((2, 2)))

    def test_multiband_exports_archive_and_download_identifiers(self):
        key = self.w.execute("vis.multi_hillshade", values(nr_directions=8))[0]
        path = self.w.download(key, "geotiff")
        with rasterio.open(path) as src:
            self.assertEqual(src.count, 8)
            np.testing.assert_allclose(src.read(), self.w.items[key]["value"], rtol=1e-6)
        self.wb.offer(path)
        first_id = self.wb.download["id"]
        self.wb.offer(path)
        self.assertNotEqual(self.wb.download["id"], first_id)
        with zipfile.ZipFile(self.w.package()) as archive:
            index = json.loads(archive.read("artifacts/index.json"))
            self.assertIn(index[key]["value"]["array_file"], archive.namelist())
            self.assertEqual(index[key]["grid"]["crs"], "EPSG:32633")
        with self.assertRaises(ValueError):
            self.w.execute("vis.nonexistent")
        with self.assertRaises(ValueError):
            self.w.execute("vis.msrm", {"feature_min": {"binding": "default"}})

    def test_live_preview_replaces_transient_result_and_preserves_history(self):
        self.wb.rvt_workspace = self.w
        history = list(self.w.history)
        for direction in (315, 90, 225):
            handle_event(self.wb, {"action": "rvt_preview", "operation": "vis.hillshade", "parameters": values(sun_azimuth=direction), "nonce": str(direction)})
            self.assertNotEqual(self.wb.message_level, "error", self.wb.message)
            self.assertEqual(self.w.latest, ["live_preview"])
            self.assertEqual(self.wb.rvt_current, "live_preview")
            self.assertEqual(len(self.wb.layers), 1)
        self.assertEqual(self.w.history, history)
        self.assertEqual(len([key for key in self.w.items if key.startswith("live_preview")]), 1)
        import rvt.vis
        np.testing.assert_allclose(self.w.items["live_preview"]["value"], rvt.vis.hillshade(self.dem, 1, 1, sun_azimuth=225))
        original = self.w.items["live_preview"]["value"].copy()
        foreign = self.w.add("foreign grid", self.dem.copy())
        self.w.items[foreign]["profile"]["transform"] = from_origin(360000, 4800000, 1, 1)
        with self.assertRaises(ValueError):
            self.w.execute("vis.hillshade", {"dem": {"binding": "artifact", "id": foreign}}, preview=True)
        np.testing.assert_array_equal(self.w.items["live_preview"]["value"], original)
        self.w.preset("Archaeological (VAT)", preview=True)
        self.assertEqual(self.w.history, history)
        with self.assertRaises(ValueError):
            self.w.execute("blend.BlenderCombination", preview=True)
        np.testing.assert_array_equal(self.wb.dem, self.dem)

    def test_map_events_and_relief_download_preserve_all_bands(self):
        self.wb.rvt_workspace = self.w
        handle_event(self.wb, {"action": "rvt_run", "operation": "vis.multi_hillshade", "parameters": values(nr_directions=8), "nonce": "run"})
        self.assertNotEqual(self.wb.message_level, "error", self.wb.message)
        self.assertEqual(self.wb.done_nonce, "run")
        self.assertEqual(len(self.wb.layers), 1)
        self.assertEqual(self.wb.arrays["rvt_current"].shape, self.dem.shape)
        self.assertEqual(self.wb.map_args({})["message"], "")
        offer_layer(self.wb, "rvt_current")
        with rasterio.io.MemoryFile(base64.b64decode(self.wb.download["b64"])) as memory:
            with memory.open() as src:
                self.assertEqual(src.count, 8)
        handle_event(self.wb, {"action": "rvt_run", "operation": "vis.missing", "nonce": "bad"})
        self.assertEqual(self.wb.message_level, "error")
        self.assertEqual(self.wb.done_nonce, "bad")

    def test_referenced_raster_uses_its_own_pixel_sizes(self):
        transform = from_origin(360000, 4800000, 2, 3)
        path = Path(self.tmp.name) / "rectangular.tif"
        self.w._write_raster(path, self.dem, dict(self.wb.profile, transform=transform))
        self.w.upload(path.name, base64.b64encode(path.read_bytes()).decode())
        key = self.w.latest[-1]
        output = self.w.execute("vis.hillshade", {"dem": {"binding": "artifact", "id": key}})[0]
        import rvt.vis
        expected = rvt.vis.hillshade(self.dem, 2, 3)
        np.testing.assert_allclose(self.w.items[output]["value"], expected)
        with rasterio.open(self.w.download(output, "geotiff")) as src:
            self.assertEqual(src.transform, transform)
        self.assertEqual(self.w.active_profile, self.wb.profile)


if __name__ == "__main__":
    unittest.main()
