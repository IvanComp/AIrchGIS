"""Registry of GIS tools that an assistant can call.

Each tool has a plain-language description and a JSON-schema for its
parameters, so the registry can be handed to an LLM as tool definitions
(:func:`tool_specs` returns the Claude API format; ``fmt="openai"`` returns
the function format used by Ollama and OpenAI-compatible servers).

Tools that exist in QGIS Processing run there when QGIS is installed; all
tools also have a native rvt-py/rasterio implementation. Every run goes
through :func:`run_tool`, which validates the parameters, applies the
resolvability guardrail and records the step in a :class:`ProvenanceLog`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from airch.gis import backend
from airch.gis.guardrails import SENSORS, check_resolvability
from airch.gis.provenance import ProvenanceLog, Step


class ToolError(RuntimeError):
    pass


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    native: Callable
    qgis: Callable | None = None  # params -> (algorithm id, qgis params, outputs)
    input_keys: tuple = ()
    output_keys: tuple = ("output",)
    tags: tuple = field(default_factory=tuple)

    def spec(self, fmt="claude"):
        if fmt == "claude":
            return {"name": self.name, "description": self.description, "input_schema": self.parameters}
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    REGISTRY[tool.name] = tool
    return tool


def tool_specs(fmt="claude", names=None):
    return [t.spec(fmt) for n, t in REGISTRY.items() if names is None or n in names]


# ---------------------------------------------------------------- validation
_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": (list, tuple), "object": dict}


def validate(schema: dict, params: dict) -> dict:
    props = schema.get("properties", {})
    out = {}
    for key in schema.get("required", []):
        if params.get(key) is None:
            raise ToolError(f"Missing required parameter: {key}")
    for key, value in params.items():
        if key not in props:
            raise ToolError(f"Unknown parameter: {key}")
        if value is None:
            continue
        spec = props[key]
        expected = _TYPES.get(spec.get("type"))
        if spec.get("type") == "number" and isinstance(value, bool) or (expected and not isinstance(value, expected)):
            raise ToolError(f"Parameter {key} must be of type {spec.get('type')}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"Parameter {key} must be one of {spec['enum']}")
        if "minimum" in spec and value < spec["minimum"]:
            raise ToolError(f"Parameter {key} must be >= {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise ToolError(f"Parameter {key} must be <= {spec['maximum']}")
        out[key] = value
    for key, spec in props.items():
        if key not in out and "default" in spec:
            out[key] = spec["default"]
    return out


def _schema(required, **props):
    return {"type": "object", "properties": props, "required": list(required)}


_IN = {"type": "string", "description": "Path of the input raster (GeoTIFF)."}
_OUT = {"type": "string", "description": "Path of the output GeoTIFF."}
_TARGET = {
    "type": "number",
    "minimum": 0.01,
    "description": "Optional width in metres of the feature you are looking for; the tool checks first that the data can resolve it.",
}


# ---------------------------------------------------------------- raster io
def _read(path):
    import rasterio

    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        profile = src.profile.copy()
        nodata = src.nodata
    if nodata is not None:
        arr[arr == nodata] = np.nan
    return arr, profile


def _write(path, arr, profile):
    import rasterio

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prof = profile.copy()
    prof.update(driver="GTiff", dtype="float32", count=1, nodata=-9999.0, compress="deflate")
    out = np.where(np.isfinite(arr), arr, -9999.0).astype(np.float32)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(out, 1)
    return str(path)


def _res(profile):
    return float(abs(profile["transform"].a))


def _rvt_input(arr):
    filled = arr.copy()
    mask = ~np.isfinite(filled)
    if mask.any():
        filled[mask] = np.nanmedian(filled)
    return filled, mask


def _finish(out, mask, key=None):
    if isinstance(out, dict):
        out = out[key] if key else next(iter(out.values()))
    out = np.asarray(out, dtype=np.float32)
    out[mask] = np.nan
    return out


# ---------------------------------------------------------------- native implementations
def _native_raster_info(input):
    import rasterio

    with rasterio.open(input) as src:
        arr = src.read(1, masked=True)
        return {
            "crs": src.crs.to_string() if src.crs else None,
            "width": src.width,
            "height": src.height,
            "resolution_m": [abs(src.transform.a), abs(src.transform.e)],
            "bounds": list(src.bounds),
            "nodata": src.nodata,
            "min": float(arr.min()) if arr.count() else None,
            "max": float(arr.max()) if arr.count() else None,
        }


def _native_hillshade(input, output, azimuth, altitude, z_factor, target_feature_width_m=None):
    import rvt.vis

    arr, prof = _read(input)
    dem, mask = _rvt_input(arr)
    out = rvt.vis.hillshade(dem, _res(prof), _res(prof), sun_azimuth=azimuth, sun_elevation=altitude, ve_factor=z_factor)
    return {"output": _write(output, _finish(out, mask), prof)}


def _native_slope(input, output, z_factor, target_feature_width_m=None):
    import rvt.vis

    arr, prof = _read(input)
    dem, mask = _rvt_input(arr)
    out = rvt.vis.slope_aspect(dem, _res(prof), _res(prof), output_units="degree", ve_factor=z_factor)
    return {"output": _write(output, _finish(out, mask, "slope"), prof)}


def _native_svf(input, output, radius_m, directions, target_feature_width_m=None):
    import rvt.vis

    arr, prof = _read(input)
    dem, mask = _rvt_input(arr)
    r = max(1, int(round(radius_m / _res(prof))))
    out = rvt.vis.sky_view_factor(dem, _res(prof), compute_svf=True, compute_asvf=False, compute_opns=False,
                                  svf_n_dir=int(directions), svf_r_max=r)
    return {"output": _write(output, _finish(out, mask, "svf"), prof)}


def _native_openness(input, output, radius_m, directions, negative=False, target_feature_width_m=None):
    import rvt.vis

    arr, prof = _read(input)
    dem, mask = _rvt_input(arr)
    if negative:
        dem = -dem
    r = max(1, int(round(radius_m / _res(prof))))
    out = rvt.vis.sky_view_factor(dem, _res(prof), compute_svf=False, compute_asvf=False, compute_opns=True,
                                  svf_n_dir=int(directions), svf_r_max=r)
    return {"output": _write(output, _finish(out, mask, "opns"), prof)}


def _native_lrm(input, output, radius_m, target_feature_width_m=None):
    import rvt.vis

    arr, prof = _read(input)
    dem, mask = _rvt_input(arr)
    cells = int(max(10, min(50, round(radius_m / _res(prof)))))
    out = rvt.vis.slrm(dem, radius_cell=cells)
    return {"output": _write(output, _finish(out, mask), prof)}


def _load_geometries(aoi):
    data = json.loads(Path(aoi).read_text(encoding="utf-8"))
    feats = data.get("features") if data.get("type") == "FeatureCollection" else [data if data.get("type") == "Feature" else {"type": "Feature", "geometry": data, "properties": {}}]
    crs = (data.get("crs") or {}).get("properties", {}).get("name")
    return feats, crs


def _to_raster_crs(geoms, src_crs, dst_crs):
    if not src_crs or not dst_crs:
        return geoms
    from rasterio.warp import transform_geom

    return [transform_geom(src_crs, dst_crs, g) for g in geoms]


def _geojson_crs(aoi):
    _, crs = _load_geometries(aoi)
    return crs or "EPSG:4326"


def _native_clip(input, aoi, output):
    import rasterio
    import rasterio.mask

    feats, _ = _load_geometries(aoi)
    with rasterio.open(input) as src:
        geoms = _to_raster_crs([f["geometry"] for f in feats], _geojson_crs(aoi), src.crs)
        out, transform = rasterio.mask.mask(src, geoms, crop=True, filled=True, nodata=src.nodata if src.nodata is not None else -9999.0)
        prof = src.profile.copy()
        nod = src.nodata if src.nodata is not None else -9999.0
    arr = out[0].astype(np.float32)
    arr[arr == nod] = np.nan
    prof.update(height=arr.shape[0], width=arr.shape[1], transform=transform)
    return {"output": _write(output, arr, prof)}


def _native_reproject(input, output, target_crs, resolution_m=None):
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    with rasterio.open(input) as src:
        kw = {"resolution": resolution_m} if resolution_m else {}
        transform, width, height = calculate_default_transform(src.crs, target_crs, src.width, src.height, *src.bounds, **kw)
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(rasterio.band(src, 1), dst, dst_transform=transform, dst_crs=target_crs, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
        prof = src.profile.copy()
    prof.update(crs=target_crs, transform=transform, width=width, height=height)
    return {"output": _write(output, dst, prof)}


def _native_zonal(raster, polygons, output, statistics):
    import rasterio
    import rasterio.mask

    feats, _ = _load_geometries(polygons)
    result = []
    with rasterio.open(raster) as src:
        geoms = _to_raster_crs([f["geometry"] for f in feats], _geojson_crs(polygons), src.crs)
        for feat, geom in zip(feats, geoms):
            try:
                data, _ = rasterio.mask.mask(src, [geom], crop=True, filled=False)
                vals = data[0].compressed().astype(np.float64)
                if src.nodata is not None:
                    vals = vals[vals != src.nodata]
                vals = vals[np.isfinite(vals)]
            except ValueError:
                vals = np.array([])
            stats = {}
            for s in statistics:
                if s == "count":
                    stats[s] = int(vals.size)
                elif vals.size == 0:
                    stats[s] = None
                else:
                    stats[s] = float({"mean": np.mean, "std": np.std, "min": np.min, "max": np.max,
                                      "median": np.median, "sum": np.sum}[s](vals))
            props = dict(feat.get("properties") or {})
            props.update({f"_{k}": v for k, v in stats.items()})
            result.append({"type": "Feature", "geometry": feat["geometry"], "properties": props})
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps({"type": "FeatureCollection", "features": result}), encoding="utf-8")
    return {"output": str(output), "features": len(result)}


def _native_resolvability(feature_width_m, sensor, gsd_m=None, n_dates=1):
    return check_resolvability(feature_width_m, sensor=sensor, gsd_m=gsd_m, n_dates=n_dates).to_dict()


def _native_export_3d(input, output_dir, vertical_exaggeration, formats, visualization=None, source=None, acquisition_date=None):
    import rasterio

    from airch.terrain.export3d import export_terrain_3d

    with rasterio.open(input) as src:
        dtm = src.read(1).astype(np.float64)
        meta = export_terrain_3d(dtm, src.transform, src.crs, output_dir, stem=Path(input).stem, nodata=src.nodata,
                                 formats=formats, vertical_exaggeration=vertical_exaggeration,
                                 visualization=visualization, source=source or str(input),
                                 acquisition_date=acquisition_date)
    return {"output_dir": str(output_dir), **meta["paths"]}


def _native_qgis_list(search=None):
    if not backend.qgis_available():
        raise ToolError("QGIS is not installed on this computer.")
    algs = backend.list_algorithms()
    if search:
        s = search.lower()
        algs = {k: v for k, v in algs.items() if s in k.lower() or s in v.lower()}
    return {"algorithms": algs, "count": len(algs)}


def _native_qgis_run(algorithm_id, parameters):
    if not backend.qgis_available():
        raise ToolError("QGIS is not installed on this computer.")
    return backend.run_algorithm(algorithm_id, parameters)


# ---------------------------------------------------------------- QGIS mappings
def _q_hillshade(p):
    return "native:hillshade", {"INPUT": p["input"], "Z_FACTOR": p["z_factor"], "AZIMUTH": p["azimuth"],
                                "V_ANGLE": p["altitude"], "OUTPUT": p["output"]}


def _q_slope(p):
    return "native:slope", {"INPUT": p["input"], "Z_FACTOR": p["z_factor"], "OUTPUT": p["output"]}


def _q_clip(p):
    return "gdal:cliprasterbymasklayer", {"INPUT": p["input"], "MASK": p["aoi"], "CROP_TO_CUTLINE": True,
                                          "KEEP_RESOLUTION": True, "OUTPUT": p["output"]}


def _q_reproject(p):
    params = {"INPUT": p["input"], "TARGET_CRS": p["target_crs"], "RESAMPLING": 1, "OUTPUT": p["output"]}
    if p.get("resolution_m"):
        params["TARGET_RESOLUTION"] = p["resolution_m"]
    return "gdal:warpreproject", params


_QGIS_STATS = {"count": 0, "sum": 1, "mean": 2, "median": 3, "std": 4, "min": 5, "max": 6}


def _q_zonal(p):
    return "native:zonalstatisticsfb", {"INPUT": p["polygons"], "INPUT_RASTER": p["raster"], "RASTER_BAND": 1,
                                        "COLUMN_PREFIX": "_", "STATISTICS": [_QGIS_STATS[s] for s in p["statistics"]],
                                        "OUTPUT": p["output"]}


# ---------------------------------------------------------------- registry
register(Tool("raster_info", "Describe a raster: CRS, size, pixel size in metres, extent and elevation range. Use it first to know what the data can show.",
              _schema(["input"], input=_IN), _native_raster_info, input_keys=("input",), output_keys=()))
register(Tool("hillshade", "Shaded relief of a terrain model, as if lit by a low sun. Good first look at earthworks; one light direction can hide features parallel to it.",
              _schema(["input", "output"], input=_IN, output=_OUT,
                      azimuth={"type": "number", "minimum": 0, "maximum": 360, "default": 315, "description": "Sun direction in degrees from north."},
                      altitude={"type": "number", "minimum": 0, "maximum": 90, "default": 35, "description": "Sun height in degrees."},
                      z_factor={"type": "number", "minimum": 0.1, "default": 1.0, "description": "Vertical exaggeration."},
                      target_feature_width_m=_TARGET),
              _native_hillshade, _q_hillshade, ("input",), tags=("lidar",)))
register(Tool("slope", "Slope in degrees. Shows banks, terraces and the edges of mounds and ditches.",
              _schema(["input", "output"], input=_IN, output=_OUT, z_factor={"type": "number", "minimum": 0.1, "default": 1.0, "description": "Vertical exaggeration."},
                      target_feature_width_m=_TARGET),
              _native_slope, _q_slope, ("input",), tags=("lidar",)))
register(Tool("sky_view_factor", "Sky-view factor: how much sky is visible from each point. Hollows and ditches look dark, ridges bright, with no light direction to choose.",
              _schema(["input", "output"], input=_IN, output=_OUT,
                      radius_m={"type": "number", "minimum": 1, "default": 10, "description": "Search radius in metres; about the size of the features sought."},
                      directions={"type": "integer", "minimum": 4, "maximum": 64, "default": 16, "description": "Number of search directions."},
                      target_feature_width_m=_TARGET),
              _native_svf, None, ("input",), tags=("lidar",)))
register(Tool("openness", "Positive (or negative) openness: highlights convex (or concave) micro-relief such as banks or ditches, independent of light direction.",
              _schema(["input", "output"], input=_IN, output=_OUT,
                      radius_m={"type": "number", "minimum": 1, "default": 10, "description": "Search radius in metres."},
                      directions={"type": "integer", "minimum": 4, "maximum": 64, "default": 16, "description": "Number of search directions."},
                      negative={"type": "boolean", "default": False, "description": "Negative openness (concave features)."},
                      target_feature_width_m=_TARGET),
              _native_openness, None, ("input",), tags=("lidar",)))
register(Tool("local_relief_model", "Local relief model: removes the large-scale landscape and keeps small bumps and hollows, in metres above or below the local trend.",
              _schema(["input", "output"], input=_IN, output=_OUT,
                      radius_m={"type": "number", "minimum": 1, "default": 20, "description": "Trend radius in metres; larger than the features sought."},
                      target_feature_width_m=_TARGET),
              _native_lrm, None, ("input",), tags=("lidar",)))
register(Tool("clip_raster_to_aoi", "Cut a raster to an area of interest drawn or saved as GeoJSON.",
              _schema(["input", "aoi", "output"], input=_IN, aoi={"type": "string", "description": "GeoJSON polygon of the area of interest."}, output=_OUT),
              _native_clip, _q_clip, ("input", "aoi")))
register(Tool("reproject", "Reproject a raster to another coordinate system, optionally changing the pixel size.",
              _schema(["input", "output", "target_crs"], input=_IN, output=_OUT,
                      target_crs={"type": "string", "description": "Target CRS, e.g. EPSG:32633."},
                      resolution_m={"type": "number", "minimum": 0.01, "description": "Optional output pixel size."}),
              _native_reproject, _q_reproject, ("input",)))
register(Tool("zonal_stats", "Statistics of a raster inside each polygon (e.g. field parcels): mean, spread, extremes. Useful to compare a parcel with its neighbours.",
              _schema(["raster", "polygons", "output"], raster={"type": "string", "description": "Input raster."},
                      polygons={"type": "string", "description": "GeoJSON polygons."}, output={"type": "string", "description": "Output GeoJSON (or GPKG with QGIS)."},
                      statistics={"type": "array", "items": {"type": "string", "enum": list(_QGIS_STATS)}, "default": ["count", "mean", "std", "min", "max"],
                                  "description": "Statistics to compute."}),
              _native_zonal, _q_zonal, ("raster", "polygons")))
register(Tool("check_resolvability", "Check whether a feature of a given width can be detected with a sensor at all, before any analysis. Explains why not, and what to use instead.",
              _schema(["feature_width_m"], feature_width_m={"type": "number", "minimum": 0.01, "description": "Width of the feature in metres (e.g. 5 for a Roman street)."},
                      sensor={"type": "string", "enum": list(SENSORS), "default": "sentinel-2", "description": "Sensor."},
                      gsd_m={"type": "number", "minimum": 0.01, "description": "Pixel size, if different from the sensor default."},
                      n_dates={"type": "integer", "minimum": 1, "default": 1, "description": "Independent dates that show the mark."}),
              _native_resolvability, output_keys=()))
register(Tool("export_3d", "Export a terrain model as open, georeferenced 3D data (point cloud LAZ/LAS and PLY, mesh glTF, metadata JSON) for QGIS 3D, CloudCompare or Blender.",
              _schema(["input", "output_dir"], input=_IN, output_dir={"type": "string", "description": "Folder for the exported files."},
                      vertical_exaggeration={"type": "number", "minimum": 0.1, "default": 1.0, "description": "Vertical exaggeration of the mesh."},
                      formats={"type": "array", "items": {"type": "string", "enum": ["laz", "las", "ply", "glb"]}, "default": ["laz", "ply", "glb"], "description": "Formats."},
                      visualization={"type": "string", "description": "Relief visualization applied, recorded in the metadata."},
                      source={"type": "string", "description": "Data source and licence, recorded in the metadata."},
                      acquisition_date={"type": "string", "description": "Acquisition date of the data."}),
              _native_export_3d, None, ("input",), output_keys=("output_dir",), tags=("lidar", "3d")))
register(Tool("qgis_list_algorithms", "List the QGIS Processing algorithms installed on this computer (QGIS, GDAL, GRASS, SAGA...), optionally filtered by a word.",
              _schema([], search={"type": "string", "description": "Word to search in algorithm ids and names."}),
              _native_qgis_list, output_keys=(), tags=("qgis",)))
register(Tool("qgis_run_algorithm", "Run any QGIS Processing algorithm by id with its parameters (as in the QGIS Processing toolbox). Use qgis_list_algorithms first.",
              _schema(["algorithm_id", "parameters"], algorithm_id={"type": "string", "description": "Algorithm id, e.g. native:hillshade."},
                      parameters={"type": "object", "description": "Algorithm parameters, e.g. {\"INPUT\": \"dtm.tif\", \"OUTPUT\": \"out.tif\"}."}),
              _native_qgis_run, output_keys=(), tags=("qgis",)))


# ---------------------------------------------------------------- loaders (bring your own data)
def _native_load_raster(input):
    from airch.data_input import describe_raster, plain_description

    info = describe_raster(input)
    info.pop("tags", None)
    info["summary"] = plain_description(info)
    return info


def _native_load_point_cloud(input, output=None, resolution_m=1.0, ground_only=True):
    from airch.data_input import describe_point_cloud, rasterize_point_cloud

    info = describe_point_cloud(input)
    if output:
        info["dtm"] = str(rasterize_point_cloud(input, output, resolution=resolution_m, ground_only=ground_only))
    return info


def _native_load_sites(input, crs=None):
    from airch.data_input import read_sites

    sites = read_sites(input, crs=crs)
    return {"count": len(sites), "sites": [{"name": s.name, "lon": s.lon, "lat": s.lat} for s in sites[:500]]}


def _native_check_raster(input, feature_width_m, n_dates=1):
    from airch.data_input import describe_raster

    info = describe_raster(input)
    kind = "lidar" if info["bands"] == 1 else "sentinel-2"
    r = check_resolvability(feature_width_m, sensor=kind, gsd_m=info["pixel_size_m"], n_dates=n_dates).to_dict()
    r["pixel_size_from_file_m"] = info["pixel_size_m"]
    return r


register(Tool("load_raster", "Open the user's own raster (any country, sensor or CRS) and describe it in plain language: bands, pixel size, extent, CRS.",
              _schema(["input"], input={"type": "string", "description": "Path of a GeoTIFF or other GDAL raster."}),
              _native_load_raster, input_keys=("input",), output_keys=(), tags=("input",)))
register(Tool("load_point_cloud", "Open the user's LAS/LAZ point cloud; optionally grid its ground points into a DTM GeoTIFF.",
              _schema(["input"], input={"type": "string", "description": "Path of the .las or .laz file."},
                      output={"type": "string", "description": "Optional output DTM GeoTIFF."},
                      resolution_m={"type": "number", "minimum": 0.05, "default": 1.0, "description": "DTM cell size in metres."},
                      ground_only={"type": "boolean", "default": True, "description": "Use only points classified as ground (class 2) when present."}),
              _native_load_point_cloud, input_keys=("input",), output_keys=("dtm",), tags=("input", "lidar")))
register(Tool("load_sites", "Read the user's list of known sites (CSV with longitude/latitude or x/y, GeoJSON, GeoPackage, Shapefile, KML) to use as ground truth.",
              _schema(["input"], input={"type": "string", "description": "Path of the site list."},
                      crs={"type": "string", "description": "CRS of x/y columns if not longitude/latitude, e.g. EPSG:32633."}),
              _native_load_sites, input_keys=("input",), output_keys=(), tags=("input",)))
register(Tool("check_raster_resolvability", "Check a feature width against the real pixel size of a loaded raster (not a default sensor value).",
              _schema(["input", "feature_width_m"], input={"type": "string", "description": "Path of the raster."},
                      feature_width_m={"type": "number", "minimum": 0.01, "description": "Width of the feature in metres."},
                      n_dates={"type": "integer", "minimum": 1, "default": 1, "description": "Independent dates that show the mark."}),
              _native_check_raster, input_keys=("input",), output_keys=()))


# ---------------------------------------------------------------- execution
def _guard(tool, params):
    width = params.get("target_feature_width_m")
    if not width or "input" not in params:
        return None
    try:
        from airch.data_input import describe_raster

        gsd = describe_raster(params["input"])["pixel_size_m"]
    except Exception:
        return None
    return check_resolvability(width, sensor="lidar", gsd_m=gsd)


def run_tool(name: str, log: ProvenanceLog | None = None, prefer: str = "auto", **params) -> dict:
    """Run a registered tool and record it. ``prefer`` is "auto", "qgis" or "native"."""
    if name not in REGISTRY:
        raise ToolError(f"Unknown tool: {name}. Available: {', '.join(REGISTRY)}")
    tool = REGISTRY[name]
    params = validate(tool.parameters, params)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    inputs = ProvenanceLog.describe_inputs([params.get(k) for k in tool.input_keys])

    check = _guard(tool, params)
    if check is not None and check.verdict == "refuse":
        step = Step(name, params, "guardrail", "refused", inputs, {}, None, check.message, started, 0.0)
        if log is not None:
            log.record(step)
        return {"status": "refused", "backend": "guardrail", "message": check.message, "resolvability": check.to_dict()}

    use_qgis = tool.qgis is not None and prefer != "native" and backend.qgis_available()
    command = None
    try:
        if use_qgis:
            alg_id, qparams = tool.qgis(params)
            command = backend.build_command(alg_id, qparams)
            outputs = backend.run_algorithm(alg_id, qparams)
            used = "qgis"
        else:
            run_params = {k: v for k, v in params.items()}
            outputs = tool.native(**run_params)
            used = "qgis" if name.startswith("qgis_") else "native"
            if name == "qgis_run_algorithm":
                command = backend.build_command(params["algorithm_id"], params["parameters"])
    except Exception as exc:
        step = Step(name, params, "qgis" if use_qgis else "native", "error", inputs, {}, command, str(exc), started,
                    round(time.perf_counter() - t0, 3))
        if log is not None:
            log.record(step)
        raise ToolError(f"{name} failed: {exc}") from exc

    status, message = "ok", ""
    if check is not None and check.verdict == "warn":
        status, message = "warn", check.message
    if name == "check_resolvability":
        status, message = ("ok", outputs["message"])
    step = Step(name, params, used, status, inputs, outputs if isinstance(outputs, dict) else {"result": outputs},
                command, message, started, round(time.perf_counter() - t0, 3))
    if log is not None:
        log.record(step)
    result = {"status": status, "backend": used, "outputs": outputs}
    if message:
        result["message"] = message
    return result
