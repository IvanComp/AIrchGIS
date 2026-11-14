from __future__ import annotations

import base64
import copy
import enum
import importlib
import importlib.metadata
import inspect
import json
import re
import time
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .paths import PROJECT_ROOT
from .rvt_runtime import APPLIED_FIXES, ensure_runtime, ensure_scaling, ensure_tiled_mstp


ensure_runtime()
ensure_scaling()
ensure_tiled_mstp()


MODULES = ("vis", "blend", "blend_func", "default", "tile")
UPSTREAM_COMMIT = "bab109c409fedf77ccec7de5fd84c48b791df3d2"
SETTINGS = Path(__file__).with_name("data") / "rvt" / "settings"
ARRAY_PARAMS = {
    "dem", "dem_arr", "dem_fine", "height_arr", "data", "image", "gray_scale", "active", "background",
    "img", "r", "g", "b", "c", "float_arr", "out_raster_arr", "dem_i_nr_pixels", "dem_i1", "dem_i2",
    "idx_min_lt_zero", "idx_max_c_gt_one", "lum_c", "min_c", "max_c", "slope", "aspect", "array", "numeric_value",
}
CHOICES = {
    "sky_model": ["overcast", "uniform"], "output_units": ["degree", "radian", "percent"],
    "normalization": ["value", "percent"], "blend_mode": ["normal", "multiply", "screen", "overlay", "soft_light", "luminosity"],
    "data_type": ["float64", "float32", "int64", "int32"],
    "method": ["idw", "idw_5_2", "linear_row", "kd_tree", "nearest_neighbour"],
}
LABELS = {
    "slope_aspect": "Slope and aspect", "slrm": "Simple local relief model", "msrm": "Multi-scale relief model",
    "mstp": "Multi-scale topographic position", "e3mstp": "Enhanced MSTP (e3MSTP)", "e4mstp": "Enhanced MSTP (e4MSTP)",
    "color_relief_image_map": "Colour relief image map (CRIM)", "fill_where_nan": "Fill missing elevations",
    "sky_view_factor": "Sky-view factor and openness", "shadow_horizon": "Shadow and horizon",
    "multi_hillshade": "Hillshade from multiple directions", "byte_scale": "Convert to 8-bit",
}

LIVE_OPERATIONS = {
    "vis.byte_scale", "vis.slope_aspect", "vis.hillshade", "vis.multi_hillshade", "vis.mean_filter", "vis.slrm",
    "vis.sky_view_factor", "vis.local_dominance", "vis.sky_illumination", "vis.shadow_horizon", "vis.msrm", "vis.mstp",
    "blend.color_relief_image_map", "blend.e3mstp", "blend.e4mstp", "blend.BlenderCombination.render_all_images",
} | {"default.DefaultValues." + name for name in (
    "get_slope", "get_shadow", "get_hillshade", "get_multi_hillshade", "get_slrm", "get_sky_view_factor",
    "get_neg_opns", "get_sky_illumination", "get_local_dominance", "get_msrm", "get_mstp", "calculate_visualization")}


def plain(value):
    if value is inspect.Parameter.empty:
        return None
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if inspect.isclass(value):
        return value.__name__
    return None


def title(name):
    return LABELS.get(name, name.replace("_", " ").capitalize())


def help_text(obj):
    doc = inspect.getdoc(obj) or ""
    return re.split(r"\n\s*\n|\nParameters|\nAttributes", doc)[0].replace("\n", " ").strip()[:700]


def parameter_help(obj, name):
    doc = inspect.getdoc(obj) or ""
    match = re.search(r"(?:^|\n)" + re.escape(name) + r"\s*:[^\n]*\n((?:[ \t]+[^\n]*\n?)*)", doc)
    return " ".join(match.group(1).split())[:500] if match else ""


def parameters(obj, operation):
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
        return [{"name": "value", "label": "Visualization", "required": True, "kind": "enum", "choices": [v.value for v in obj], "default": list(obj)[0].value, "help": "RVT visualization identifier."}]
    result = []
    for p in inspect.signature(obj).parameters.values():
        if p.name in {"self", "cls"}:
            continue
        default = p.default
        annotation = str(p.annotation)
        kind = "text"
        options = CHOICES.get(p.name, [])
        if p.kind in {p.VAR_KEYWORD, p.VAR_POSITIONAL}:
            kind = "mapping" if p.kind == p.VAR_KEYWORD else "sequence"
        elif p.name in ARRAY_PARAMS:
            kind = "array"
        elif p.name in {"rvt_visualization", "visualization", "vis"} and ("RVTVisualization" in annotation or operation.startswith(("default.", "tile."))):
            kind = "enum"
            options = [v.value for v in importlib.import_module("rvt.default").RVTVisualization]
        elif p.name in {"default", "rvt_default", "combination", "combination1", "combination2", "input_combination", "layer"} or "rvt." in annotation:
            kind = "object"
        elif p.name == "visualization_function":
            kind = "function"
        elif p.name in {"json_data", "function_parameters"} or isinstance(default, dict):
            kind = "mapping"
        elif isinstance(default, (tuple, list)):
            kind = "sequence"
        elif isinstance(default, bool) or p.annotation is bool:
            kind = "boolean"
        elif isinstance(default, (int, float)) or p.name in {"resolution", "resolution_x", "resolution_y", "x_res", "y_res", "dem_resolution", "feature_min", "feature_max", "scaling_factor", "overlap", "tile_size_x", "tile_size_y", "kernel_radius", "minimum", "maximum", "min_norm", "max_norm", "numeric_value", "pyramid_scale", "conv_from", "conv_to", "max_radius", "num_directions", "shift", "axis"}:
            kind = "number"
        elif "path" in p.name or p.name in {"file_path", "custom_dir", "output_dir"}:
            kind = "file"
        elif p.name in {"colormap", "cmap"}:
            kind = "colormap"
        elif options:
            kind = "choice"
        result.append({"name": p.name, "label": p.name.replace("_", " ").capitalize(), "kind": kind,
                       "default": plain(default), "required": default is p.empty, "choices": options,
                       "integer": isinstance(default, int) and not isinstance(default, bool),
                       "help": parameter_help(obj, p.name), "annotation": annotation if p.annotation is not p.empty else ""})
    return result


@lru_cache(maxsize=1)
def registry():
    entries = {}
    for module_name in MODULES:
        module = importlib.import_module("rvt." + module_name)
        for name, obj in vars(module).items():
            if name.startswith("_") or getattr(obj, "__module__", None) != module.__name__:
                continue
            key = module_name + "." + name
            if inspect.isfunction(obj):
                entries[key] = {"callable": obj, "kind": "function", "module": module_name, "label": title(name)}
            elif inspect.isclass(obj):
                entries[key] = {"callable": obj, "kind": "constructor", "module": module_name, "label": "Create " + name, "class": key}
                for method_name, descriptor in vars(obj).items():
                    method = descriptor.__func__ if isinstance(descriptor, (staticmethod, classmethod)) else descriptor
                    if not method_name.startswith("_") and inspect.isfunction(method):
                        entries[key + "." + method_name] = {"callable": method, "kind": "method", "module": module_name,
                            "class": key, "label": name + " · " + title(method_name)}
    for key, value in entries.items():
        value["id"] = key
        value["parameters"] = parameters(value["callable"], key)
        value["help"] = help_text(value["callable"])
        value["preview"] = key in LIVE_OPERATIONS
    return entries


@lru_cache(maxsize=1)
def catalog():
    operations = [{k: v for k, v in entry.items() if k != "callable"} for entry in registry().values()]
    return {"version": importlib.metadata.version("rvt-py"), "upstream_commit": UPSTREAM_COMMIT,
            "operations": operations, "count": len(operations), "compatibility_fixes": list(APPLIED_FIXES),
            "visualizations": [v.name for v in importlib.import_module("rvt.default").RVTVisualization],
            "presets": [d["combination"]["name"] for d in json.loads((SETTINGS / "default_blender_combinations.json").read_text())["combinations"]],
            "terrains": [d["terrain_settings"]["name"] for d in json.loads((SETTINGS / "default_terrains_settings.json").read_text())["terrains_settings"]]}


class RVTWorkspace:
    def __init__(self, wb, folder=None):
        self.wb = wb
        self.folder = Path(folder or PROJECT_ROOT / "workspace" / "outputs" / "rvt" / uuid.uuid4().hex[:12])
        self.folder.mkdir(parents=True, exist_ok=True)
        self.active_dem = wb.dem
        self.active_profile = dict(wb.profile)
        self.active_res = wb.res
        self.items = {}
        self.latest = []
        self.history = []
        self.counter = 0
        self.input_file = self.folder / "terrain.tif"
        self._write_raster(self.input_file, wb.dem)
        self.defaults = importlib.import_module("rvt.default").DefaultValues()
        self.add("Default settings", self.defaults, "settings")
        self.add("Terrain", wb.dem.copy(), "terrain")
        self.add("Terrain GeoTIFF", self.input_file, "terrain_file")
        for preset in sorted(SETTINGS.glob("*.json")):
            self.add("RVT configuration · " + preset.stem, preset, "config_" + preset.stem)
        self.current_run = self.folder
        self.last_operation = None

    def add(self, label, value, key=None):
        if key is None:
            self.counter += 1
            key = f"result{self.counter}"
        self.items[key] = {"label": str(label), "value": value, "summary": self._brief(value)}
        if isinstance(value, np.ndarray) and value.ndim in {2, 3}:
            self.items[key]["profile"] = dict(self.active_profile)
        return key

    def _write_raster(self, path, value, profile=None):
        import rasterio
        array = np.asarray(value)
        source_profile = profile or self.wb.profile
        shape = (source_profile.get("height", self.active_dem.shape[0]), source_profile.get("width", self.active_dem.shape[1]))
        if array.ndim == 2 and array.shape == shape:
            bands = array[np.newaxis]
        elif array.ndim == 3 and array.shape[-2:] == shape:
            bands = array
        elif array.ndim == 3 and array.shape[:2] == shape:
            bands = np.moveaxis(array, -1, 0)
        else:
            raise ValueError("The array does not match the terrain grid.")
        if bands.dtype == bool:
            bands = bands.astype(np.uint8)
        profile = source_profile.copy()
        profile.update(driver="GTiff", count=bands.shape[0], width=bands.shape[2], height=bands.shape[1], dtype=str(bands.dtype),
                       nodata=np.nan if np.issubdtype(bands.dtype, np.floating) else None, compress="deflate")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(bands)
        return Path(path)

    def _mapable(self, value):
        return isinstance(value, np.ndarray) and (value.shape == self.wb.dem.shape or
            (value.ndim == 3 and (value.shape[-2:] == self.wb.dem.shape or value.shape[:2] == self.wb.dem.shape)))

    def is_rgb(self, value):
        if not self._mapable(value) or value.ndim != 3:
            return False
        channels = value.shape[0] if value.shape[-2:] == self.wb.dem.shape else value.shape[-1]
        return channels in {3, 4}

    def _brief(self, value, depth=0):
        if isinstance(value, np.ndarray):
            finite = value[np.isfinite(value)] if np.issubdtype(value.dtype, np.number) else value.ravel()
            return {"type": "array", "shape": list(value.shape), "dtype": str(value.dtype),
                    "minimum": plain(float(np.min(finite))) if finite.size else None,
                    "maximum": plain(float(np.max(finite))) if finite.size else None}
        if isinstance(value, Path):
            return {"type": "file", "name": value.name, "location": str(value), "exists": value.exists()}
        if isinstance(value, enum.Enum):
            return {"type": type(value).__name__, "value": value.value}
        if depth > 2:
            return {"type": type(value).__name__}
        if isinstance(value, dict):
            return {"type": "mapping", "values": {str(k): self._brief(v, depth + 1) for k, v in list(value.items())[:50]}}
        if isinstance(value, (list, tuple)):
            return {"type": "sequence", "length": len(value), "values": [self._brief(v, depth + 1) for v in value[:30]]}
        if hasattr(value, "__dict__"):
            return {"type": type(value).__module__ + "." + type(value).__name__}
        return plain(value)

    def snapshot(self):
        artifacts = []
        for key, item in self.items.items():
            value = item["value"]
            fields = []
            if hasattr(value, "__dict__") and type(value).__module__.startswith("rvt."):
                for name, field in vars(value).items():
                    if not name.startswith("_"):
                        fields.append({"name": name, "value": plain(field), "summary": self._brief(field)})
            profile = item.get("profile", self.wb.profile)
            same_grid = profile.get("transform") == self.wb.profile.get("transform") and str(profile.get("crs")) == str(self.wb.profile.get("crs"))
            artifacts.append({"id": key, "label": item["label"], "summary": item["summary"], "mapable": same_grid and self._mapable(value),
                              "class": type(value).__module__.removeprefix("rvt.") + "." + type(value).__name__, "fields": fields})
        return {"catalog": catalog(), "artifacts": artifacts, "latest": self.latest, "history": self.history[-30:],
                "last_operation": self.last_operation, "preview_status": getattr(self, "preview_status", None), "default_object": "settings"}

    def _nested(self, value):
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                return self.items[value["$ref"]]["value"]
            return {k: self._nested(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._nested(v) for v in value]
        return value

    def _is_output(self, operation, name):
        return name in {"out_raster_path", "output_dir_path", "custom_dir", "save_render_path", "render_path"} or (
            name == "file_path" and any(s in operation.rsplit(".", 1)[-1] for s in ("save", "create")))

    def _auto(self, operation, p):
        name = p.name
        if name in {"default", "rvt_default"}:
            return self.defaults
        if name in {"resolution_y", "y_res"}:
            return abs(self.active_profile["transform"].e)
        if name in {"resolution", "resolution_x", "x_res", "dem_resolution"}:
            return abs(self.active_profile["transform"].a)
        if name in {"dem_path", "raster_path", "src_raster_path"}:
            return self.input_file
        if self._is_output(operation, name):
            if name in {"custom_dir", "output_dir_path"}:
                return self.current_run
            ext = ".json" if name == "file_path" else ".tif"
            return self.current_run / (name + ext)
        if name == "visualization_function":
            return registry()["vis.hillshade"]["callable"]
        if name == "function_parameters":
            return {"resolution_x": None, "resolution_y": None, "no_data": None}
        if name == "dem_arr" and p.default is None and self.input_file != self.folder / "terrain.tif":
            return inspect.Parameter.empty
        if name in ARRAY_PARAMS and (p.default is p.empty or name in {"dem", "dem_arr", "dem_fine", "height_arr"}):
            return self.active_dem.copy()
        if name == "rvt_visualization" or (name == "visualization" and operation.startswith(("default.", "tile."))):
            return importlib.import_module("rvt.default").RVTVisualization.HILLSHADE
        if p.default is not p.empty:
            return inspect.Parameter.empty
        raise ValueError(f"Choose a value or an input result for {name}.")

    def _coerce(self, operation, p, value):
        if value is inspect.Parameter.empty:
            return value
        name = p.name
        if (name == "rvt_visualization" or (name == "visualization" and operation.startswith(("default.", "tile.")))) and isinstance(value, str):
            enum_class = importlib.import_module("rvt.default").RVTVisualization
            value = enum_class[value] if value in enum_class.__members__ else enum_class(value)
        if name == "data_type" and isinstance(value, str):
            value = np.dtype(value).type
        if name == "cmap" and isinstance(value, str):
            from matplotlib import colormaps
            value = colormaps[value]
        if name == "visualization_function" and isinstance(value, str):
            value = registry()[value]["callable"]
        if isinstance(p.default, tuple) and isinstance(value, list):
            value = tuple(value)
        if isinstance(p.default, int) and not isinstance(p.default, bool) and isinstance(value, (int, float)):
            value = int(value)
        if isinstance(value, str) and (p.annotation is Path or "pathlib.Path" in str(p.annotation) or str(p.annotation) == "Path"):
            value = Path(value)
        if isinstance(value, Path) and p.annotation is not Path and "pathlib.Path" not in str(p.annotation) and str(p.annotation) != "Path":
            value = str(value)
        if name in ARRAY_PARAMS and isinstance(value, list):
            value = np.asarray(value)
        return value.copy() if isinstance(value, np.ndarray) else value

    def arguments(self, operation, supplied, function):
        result = {}
        for p in inspect.signature(function).parameters.values():
            if p.name in {"self", "cls"}:
                continue
            descriptor = supplied.get(p.name, {"binding": "auto"})
            binding = descriptor.get("binding", "value") if isinstance(descriptor, dict) else "value"
            if binding == "default":
                value = inspect.Parameter.empty
            elif binding == "artifact":
                value = self.items[descriptor["id"]]["value"]
                if "member" in descriptor and descriptor["member"] not in (None, ""):
                    member = descriptor["member"]
                    value = value[member] if isinstance(value, dict) else value[int(member)]
            elif binding == "auto":
                if p.name == "function_parameters" and "visualization_function" in result:
                    value = {name: None for name in inspect.signature(result["visualization_function"]).parameters
                             if name in {"resolution", "resolution_x", "resolution_y", "no_data"}}
                else:
                    value = self._auto(operation, p)
            elif binding == "none":
                value = None
            else:
                value = self._nested(descriptor.get("value") if isinstance(descriptor, dict) else descriptor)
            if value is inspect.Parameter.empty:
                if p.default is p.empty and p.kind not in {p.VAR_KEYWORD, p.VAR_POSITIONAL}:
                    raise ValueError(f"{p.name} requires an input.")
                continue
            result[p.name] = self._coerce(operation, p, value)
        return result

    def _capture(self, label, result):
        keys = []
        if result is None:
            return keys
        root = self.add(label, result)
        keys.append(root)
        if isinstance(result, dict):
            for name, value in result.items():
                if isinstance(value, (np.ndarray, dict, list, tuple)) or hasattr(value, "__dict__"):
                    keys.extend(self._capture(label + " · " + str(name), value))
        elif isinstance(result, (tuple, list)) and len(result) <= 32:
            for i, value in enumerate(result):
                if isinstance(value, np.ndarray) or type(value).__module__.startswith("rvt."):
                    keys.extend(self._capture(label + f" · {i + 1}", value))
        return keys

    def execute(self, operation, supplied=None, instance=None, preview=False):
        original = self.active_dem, self.active_profile, self.active_res, self.input_file
        try:
            for name in ("dem_path", "raster_path", "src_raster_path"):
                descriptor = (supplied or {}).get(name, {})
                if not isinstance(descriptor, dict):
                    continue
                if descriptor.get("binding") == "artifact":
                    source = self.items[descriptor["id"]]["value"]
                elif descriptor.get("binding") == "value":
                    source = descriptor.get("value")
                else:
                    continue
                if isinstance(source, (str, Path)) and Path(source).is_file():
                    import rasterio
                    with rasterio.open(source) as src:
                        self.active_profile = src.profile.copy()
                        self.active_res = abs(src.transform.a)
                    self.input_file = Path(source)
                    break
            for name in ("dem", "dem_arr", "height_arr", "dem_fine", "image", "gray_scale", "active", "float_arr"):
                descriptor = (supplied or {}).get(name, {})
                if isinstance(descriptor, dict) and descriptor.get("binding") == "artifact":
                    item = self.items[descriptor["id"]]
                    if "profile" in item:
                        self.active_profile = item["profile"].copy()
                        self.active_res = abs(self.active_profile["transform"].a)
                        break
            return self._execute(operation, supplied, instance, preview)
        finally:
            self.active_dem, self.active_profile, self.active_res, self.input_file = original

    def _execute(self, operation, supplied=None, instance=None, preview=False):
        entry = registry().get(operation)
        if entry is None:
            raise ValueError("Unknown RVT operation.")
        if preview and operation not in LIVE_OPERATIONS:
            raise ValueError("This operation requires an explicit run.")
        self.current_run = self.folder / ("live" if preview else f"run_{len(self.history) + 1:04d}_{uuid.uuid4().hex[:6]}")
        self.current_run.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        if entry["kind"] == "method":
            if instance is None:
                matches = [key for key, item in self.items.items() if isinstance(item["value"], registry()[entry["class"]]["callable"])]
                if not matches:
                    raise ValueError("Create or select an instance of " + entry["class"] + ".")
                instance = matches[0]
            obj = self.items[instance]["value"]
            cls = registry()[entry["class"]]["callable"]
            if not isinstance(obj, cls):
                raise ValueError("The selected object has the wrong type.")
            function = getattr(obj, operation.rsplit(".", 1)[-1])
        else:
            function = entry["callable"]
        supplied = supplied or {}
        args = {}
        if inspect.isclass(function) and issubclass(function, enum.Enum):
            descriptor = supplied.get("value", {"binding": "auto"})
            binding = descriptor.get("binding", "value")
            if binding in {"auto", "default"}:
                value = list(function)[0].value
            elif binding == "artifact":
                value = self.items[descriptor["id"]]["value"]
            elif binding == "none":
                value = None
            else:
                value = self._nested(descriptor.get("value"))
            result = function(value)
        else:
            args = self.arguments(operation, supplied, function)
            if preview and operation == "blend.BlenderCombination.render_all_images":
                args.update(save_render_path=None, save_visualizations=False)
            result = function(**args)
        visualization = getattr(args.get("visualization", args.get("rvt_visualization")), "value", None)
        natural_shade = operation in {"vis.hillshade", "vis.multi_hillshade", "default.DefaultValues.get_hillshade", "default.DefaultValues.get_multi_hillshade"} or (
            operation in {"default.DefaultValues.calculate_visualization", "default.DefaultValues.float_to_8bit", "tile.save_rvt_visualization_tile_by_tile"} and visualization in {"hs", "mhs"})
        if preview:
            def first_spatial(value):
                if self._mapable(value):
                    return value
                children = value.values() if isinstance(value, dict) else value if isinstance(value, (tuple, list)) else []
                for child in children:
                    found = first_spatial(child)
                    if found is not None:
                        return found
                return None

            array = first_spatial(result)
            if array is None:
                raise ValueError("No spatial result is available for this preview.")
            if self.active_profile.get("transform") != self.wb.profile.get("transform") or str(self.active_profile.get("crs")) != str(self.wb.profile.get("crs")):
                raise ValueError("This input uses a different raster grid; run it explicitly to retain and download the result.")
            key = self.add(entry["label"] + " · live preview", array, "live_preview")
            self.items[key]["natural_hillshade"] = natural_shade
            self.show(key, rgb=self.is_rgb(array))
            self.latest = [key]
            self.preview_status = {"operation": operation, "duration": round(time.perf_counter() - started, 2)}
            return [key]
        self.latest = self._capture(entry["label"], result)
        for key in self.latest:
            self.items[key]["natural_hillshade"] = natural_shade
        if instance and instance not in self.latest:
            self.latest.append(instance)
        for path in sorted(self.current_run.rglob("*")):
            if path.is_file():
                self.latest.append(self.add(path.name, path))
        self.last_operation = {"id": operation, "label": entry["label"], "duration": round(time.perf_counter() - started, 3)}
        self.history.append({**self.last_operation, "inputs": supplied, "instance": instance, "outputs": list(self.latest)})
        self.save_manifest()
        return self.latest

    def save_manifest(self):
        data = {"rvt_version": catalog()["version"], "upstream_commit": UPSTREAM_COMMIT, "compatibility_fixes": list(APPLIED_FIXES), "history": self.history,
                "artifacts": [{"id": key, "label": item["label"], "summary": item["summary"]} for key, item in self.items.items()]}
        (self.folder / "session.json").write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")

    def update_object(self, key, fields):
        obj = self.items[key]["value"]
        if not type(obj).__module__.startswith("rvt."):
            raise ValueError("Select an RVT settings or composition object.")
        for name, descriptor in fields.items():
            if name.startswith("_") or name not in vars(obj):
                raise ValueError("Unknown settings field: " + name)
            value = self._nested(descriptor)
            if isinstance(getattr(obj, name), tuple) and isinstance(value, list):
                value = tuple(value)
            setattr(obj, name, value)
        self.latest = [key]
        self.history.append({"id": "update_object", "instance": key, "fields": fields})
        self.save_manifest()

    def upload(self, filename, encoded):
        name = Path(filename).name
        folder = self.folder / "uploads"
        folder.mkdir(exist_ok=True)
        path = folder / (uuid.uuid4().hex[:8] + "_" + name)
        path.write_bytes(base64.b64decode(encoded, validate=True))
        key = self.add(name, path)
        self.latest = [key]
        if path.suffix.lower() in {".tif", ".tiff", ".asc"}:
            import rasterio
            with rasterio.open(path) as src:
                value = src.read(masked=True).astype(np.float32).filled(np.nan)
                if value.shape[0] == 1:
                    value = value[0]
                array_key = self.add(name + " · array", value)
                self.items[array_key]["profile"] = src.profile.copy()
                self.items[key]["profile"] = src.profile.copy()
                self.latest.append(array_key)
        elif path.suffix.lower() == ".json":
            self.latest.extend(self._capture(name + " · configuration", json.loads(path.read_text())))
        elif path.suffix.lower() in {".npy", ".npz"}:
            value = np.load(path, allow_pickle=False)
            if isinstance(value, np.lib.npyio.NpzFile):
                for member in value.files:
                    self.latest.append(self.add(name + " · " + member, value[member]))
                value.close()
            else:
                self.latest.append(self.add(name + " · array", value))
        self.save_manifest()
        return key

    def preset(self, name, terrain="general", opacity=50, preview=False):
        started = time.perf_counter()
        from rvt.blend import BlenderCombination, TerrainSettings
        combinations = json.loads((SETTINGS / "default_blender_combinations.json").read_text())["combinations"]
        terrains = json.loads((SETTINGS / "default_terrains_settings.json").read_text())["terrains_settings"]

        def render(preset_name, terrain_name):
            config = next(c for c in combinations if c["combination"]["name"] == preset_name)
            combination = BlenderCombination(dem_arr=self.wb.dem.copy(), dem_resolution=self.wb.res)
            combination.read_from_json(copy.deepcopy(config))
            settings = copy.deepcopy(self.defaults)
            terrain_config = next(t for t in terrains if t["terrain_settings"]["name"] == terrain_name)
            terrain_settings = TerrainSettings()
            terrain_settings.read_from_json(copy.deepcopy(terrain_config))
            terrain_settings.apply_terrain(settings, combination)
            return combination.render_all_images(default=settings, no_data=np.nan)

        if "combined" in name.lower():
            general = render("Archaeological (VAT)", "general")
            flat = render("Archaeological (VAT)", "flat")
            combination = BlenderCombination()
            combination.create_layer(vis_method="VAT general", image=general, normalization="value", minimum=0, maximum=1, blend_mode="normal", opacity=float(opacity))
            combination.create_layer(vis_method="VAT flat", image=flat, normalization="value", minimum=0, maximum=1, blend_mode="normal", opacity=100)
            result = combination.render_all_images(no_data=np.nan)
        else:
            result = render(name, terrain)
        if preview:
            key = self.add(name + " · " + terrain + " · live preview", result, "live_preview")
            self.show(key, rgb=self.is_rgb(result))
            self.latest = [key]
            self.preview_status = {"operation": "preset", "duration": round(time.perf_counter() - started, 2)}
            return [key]
        self.latest = self._capture(name + " · " + terrain, result)
        self.last_operation = {"id": "preset", "label": name, "duration": round(time.perf_counter() - started, 3)}
        self.history.append({**self.last_operation, "inputs": {"name": name, "terrain": terrain, "opacity": opacity}, "outputs": list(self.latest)})
        self.save_manifest()
        return self.latest

    def show(self, key, band=None, rgb=False):
        from .workbench import retain_layer
        value = self.items[key]["value"]
        source_profile = self.items[key].get("profile", self.wb.profile)
        if isinstance(value, Path):
            import rasterio
            with rasterio.open(value) as src:
                value = src.read(masked=True).astype(np.float32).filled(np.nan)
                source_profile = src.profile.copy()
            if value.shape[0] == 1:
                value = value[0]
        array = np.asarray(value)
        if not self._mapable(array) or source_profile.get("transform") != self.wb.profile.get("transform") or str(source_profile.get("crs")) != str(self.wb.profile.get("crs")):
            raise ValueError("This result does not match the loaded terrain grid. It is available for download or as an input to another operation.")
        if array.ndim == 3:
            bands = array if array.shape[-2:] == self.wb.dem.shape else np.moveaxis(array, -1, 0)
            if rgb:
                if bands.shape[0] < 3:
                    raise ValueError("RGB display needs at least three bands.")
                display = np.moveaxis(bands[:3], 0, -1).astype(np.float32)
                if np.issubdtype(array.dtype, np.integer):
                    display /= np.iinfo(array.dtype).max
                elif self.items[key].get("natural_hillshade"):
                    display = np.clip(display, 0, 1)
                elif np.nanmax(display) > 1 or np.nanmin(display) < 0:
                    lo, hi = np.nanpercentile(display, [1, 99])
                    display = np.clip((display - lo) / max(hi - lo, 1e-9), 0, 1)
            else:
                index = int(band or 0)
                if index < 0 or index >= bands.shape[0]:
                    raise ValueError("Band index is outside the result.")
                display = bands[index]
        else:
            display = array
        lid = "rvt_current"
        display_range = (0, 255 if np.issubdtype(array.dtype, np.integer) else 1) if self.items[key].get("natural_hillshade") else None
        self.wb.add_layer(lid, self.items[key]["label"], self.items[key]["label"], display, raw=display, display_range=display_range)
        retain_layer(self.wb, lid)
        path = self.folder / "current_relief.tif"
        self._write_raster(path, array)
        self.wb.paths[lid] = str(path)
        self.wb.rvt_current = key

    def download(self, key, format="native"):
        value = self.items[key]["value"]
        if isinstance(value, Path):
            return value
        if isinstance(value, np.ndarray):
            if format == "geotiff":
                return self._write_raster(self.folder / (key + ".tif"), value, self.items[key].get("profile"))
            if format == "csv":
                path = self.folder / (key + ".csv")
                np.savetxt(path, value.reshape(value.shape[0], -1), delimiter=",")
                return path
            path = self.folder / (key + ".npy")
            np.save(path, value, allow_pickle=False)
            return path
        if hasattr(value, "__dict__"):
            value = {k: plain(v) for k, v in vars(value).items() if not k.startswith("_")}
        path = self.folder / (key + ".json")
        path.write_text(json.dumps(plain(value), indent=2), encoding="utf-8")
        return path

    def batch(self, operation, files, supplied=None, instance=None):
        import rasterio

        original = self.active_dem, self.active_profile, self.active_res, self.input_file
        outputs = []
        try:
            for key in files:
                path = self.items[key]["value"]
                if not isinstance(path, Path):
                    raise ValueError("Batch inputs must be raster files.")
                with rasterio.open(path) as src:
                    self.active_dem = src.read(1, masked=True).astype(np.float32).filled(np.nan)
                    self.active_profile = src.profile.copy()
                    self.active_res = abs(src.transform.a)
                self.input_file = path
                produced = list(self.execute(operation, supplied, instance))
                for item_key in list(produced):
                    value = self.items[item_key]["value"]
                    self.items[item_key]["label"] = path.stem + " · " + self.items[item_key]["label"]
                    if isinstance(value, np.ndarray) and value.ndim in {2, 3}:
                        try:
                            out = self._write_raster(self.current_run / (item_key + ".tif"), value, self.active_profile)
                            produced.append(self.add(out.name, out))
                        except ValueError:
                            pass
                outputs.extend(produced)
        finally:
            self.active_dem, self.active_profile, self.active_res, self.input_file = original
        self.latest = outputs
        self.save_manifest()
        return outputs

    def package(self):
        export_dir = self.folder / "artifacts"
        export_dir.mkdir(exist_ok=True)
        index = {}

        def encode(value, stem):
            if isinstance(value, np.ndarray):
                path = export_dir / (stem + ".npy")
                np.save(path, value, allow_pickle=False)
                return {"array_file": str(path.relative_to(self.folder))}
            if isinstance(value, Path):
                return {"file": str(value.relative_to(self.folder)) if value.is_relative_to(self.folder) else str(value)}
            if isinstance(value, dict):
                return {str(k): encode(v, stem + "_" + str(i)) for i, (k, v) in enumerate(value.items())}
            if isinstance(value, (list, tuple)):
                return [encode(v, stem + "_" + str(i)) for i, v in enumerate(value)]
            if hasattr(value, "__dict__") and type(value).__module__.startswith("rvt."):
                return {"class": type(value).__module__ + "." + type(value).__name__, "fields": encode(vars(value), stem)}
            return plain(value)

        for key, item in self.items.items():
            index[key] = {"label": item["label"], "value": encode(item["value"], key)}
            if "profile" in item:
                profile = item["profile"]
                index[key]["grid"] = {"transform": list(profile["transform"]), "crs": str(profile.get("crs")), "width": profile.get("width"), "height": profile.get("height")}
        (export_dir / "index.json").write_text(json.dumps(index, indent=2, allow_nan=False))
        self.save_manifest()
        path = self.folder.with_suffix(".zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for file in self.folder.rglob("*"):
                if file.is_file():
                    z.write(file, file.relative_to(self.folder))
        return path
