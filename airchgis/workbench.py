

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from airchgis import data_input as di

OUT_DIR = di.WORKSPACE_DIR / "outputs" / "workbench"
STEP_LABELS = {"destripe": "Remove banding", "despike": "Remove spikes and pits", "fill_voids": "Fill small voids",
               "denoise": "Reduce noise (edge-preserving)"}
METRIC_LABELS = {"noise_sigma": "Noise (elevation units)", "stripe_energy": "Banding (share of fine detail)",
                 "spike_fraction": "Spikes and pits (share of pixels)", "void_fraction": "Voids (share of pixels)"}
MAX_DOWNLOAD_MB = 200


class Workbench:


    def __init__(self, dem, transform, crs, profile, name="terrain", log=None, source=None, notes=None):
        from airchgis.gis.provenance import ProvenanceLog

        self.name = name
        self.log = log or ProvenanceLog(f"AIrchGIS · {name}")
        self.source = source or {"kind": "raster"}
        self.prep = {"steps": [], "params": {"fill_voids": True, "cell_m": 0.0}}
        self.resolution = None
        self.harmonize(dem, transform, crs, profile, notes)
        self.layers = []
        self.arrays = {}
        self.message = ""
        self.message_level = "info"
        self.details = {}
        self.download = None
        self.view3d = None
        self.cloud_key = "original"
        self.rvt_workspace = None
        self.done_nonce = None
        self.counter = 0
        self.src_path = None
        self.clean_path = None
        self.sites = None
        self.paths = {}


    def harmonize(self, dem, transform, crs, profile, notes=None):
        """Bring the loaded terrain to metres and a clear no-data convention, and record what was done."""
        from rasterio.crs import CRS

        from airchgis.enhance.metrics import zero_nodata
        from airchgis.preprocess import step

        steps = [step("input", n) for n in (notes or [])]
        c = CRS.from_user_input(crs) if crs is not None else None
        h0, w0 = np.shape(dem)
        dem, transform, crs, profile = to_metric(np.asarray(dem, dtype=np.float32), transform, crs, dict(profile))
        if c is not None and c.is_geographic:
            steps.append(step("crs", f"Coordinates in degrees ({c.to_string()}) reprojected to {CRS.from_user_input(crs).to_string()} "
                              f"so that sizes are in metres; cell {abs(transform.a):.2f} m.", cell_m=round(abs(transform.a), 3)))
        else:
            steps.append(step("crs", f"Coordinate system {c.to_string() if c else 'unknown'}, cell {abs(transform.a):.2f} m.",
                              cell_m=round(abs(transform.a), 3)))
        dem, n_zero = zero_nodata(dem)
        steps.append(step("nodata", f"{n_zero:,} cells with elevation exactly 0 treated as no data (fill outside the survey)."
                          if n_zero else "No-data cells read from the file; no zero fill found.", zero_cells=int(n_zero)))
        self.base = (np.asarray(dem, dtype=np.float32), transform, crs, dict(profile))
        self.base_steps = steps
        self.base_path = None
        self.set_dem(*self.base)

    def set_dem(self, dem, transform, crs, profile):
        self.dem = np.asarray(dem, dtype=np.float32)
        self.transform, self.crs, self.profile = transform, crs, dict(profile)
        self.profile.update(transform=transform, crs=crs, height=self.dem.shape[0], width=self.dem.shape[1])
        self.res = float(abs(transform.a))
        self.n_zero = 0
        self.src_path = None
        self.layers, self.arrays, self.paths = [], {}, {}
        if hasattr(self, "_elev"):
            del self._elev

    def base_input(self):
        if self.base_path is None or not Path(self.base_path).exists():
            dem, transform, crs, profile = self.base
            prof = dict(profile)
            prof.update(transform=transform, crs=crs)
            self.base_path = str(write_raster(dem, prof, crs, OUT_DIR / f"{self.name}_harmonized.tif"))
        return self.base_path

    def input_path(self):
        if self.src_path is None or not Path(self.src_path).exists():
            self.src_path = str(write_raster(self.dem, self.profile, self.crs, OUT_DIR / f"{self.name}_input.tif"))
        return self.src_path

    def mask_outside(self, arr):
        a = np.array(arr, dtype=np.float32)
        if a.shape[:2] == self.dem.shape:
            a[~np.isfinite(self.dem)] = np.nan
        return a

    def add_layer(self, layer_id, name, description, array, visible=True, opacity=1.0, cmap="gray", raw=None,
                  hide_others=True, display_range=None):
        from airchgis.map.view import georeference

        layer = georeference(self.mask_outside(array), self.transform, self.crs, layer_id, name, description,
                             cmap=cmap, visible=visible, opacity=opacity, display_range=display_range)
        if hide_others and visible:
            for l in self.layers:
                l["visible"] = False
        self.layers = [l for l in self.layers if l["id"] != layer_id]
        self.layers.insert(0, {"id": layer_id, "name": name, "description": description, "bounds": list(layer.bounds),
                               "image": "data:image/png;base64," + layer.png_b64, "visible": visible, "opacity": opacity})
        self.arrays[layer_id] = np.asarray(raw if raw is not None else array, dtype=np.float32)

    def offer(self, path, filename=None, mime="application/octet-stream"):
        p = Path(path)
        size = p.stat().st_size / 1e6
        if size > MAX_DOWNLOAD_MB:
            raise ValueError(f"The file is {size:.0f} MB, too large to send to the browser; it is saved in {p}.")
        self.download = {"id": "dl" + uuid4().hex, "filename": filename or p.name, "mime": mime,
                         "b64": base64.b64encode(p.read_bytes()).decode("ascii")}

    def map_args(self, tools):
        return {"layers": self.layers, "message": self.message if self.message_level in {"warning", "error"} else "", "message_level": self.message_level, "details": self.details, "download": self.download,
                "view3d": self.view3d, "prep": self.prep_view(), "resolution": self.resolution, "cloud_key": self.cloud_key, "done_nonce": self.done_nonce, "tools": tools, "name": self.name,
                "elevation": self.elevation(), "sites": bool(self.sites),
                "rvt_api": self.rvt_workspace.snapshot() if self.rvt_workspace is not None else None}

    def prep_view(self):
        p = dict(self.prep)
        p["steps"] = list(self.prep.get("source_steps", [])) + list(self.base_steps) + list(self.prep.get("steps", []))
        p["kind"] = self.source.get("kind", "raster")
        p["cell_m"] = round(self.res, 3)
        return p

    def elevation(self):
        if not hasattr(self, "_elev"):
            from airchgis.map.view import elevation_grid

            try:
                self._elev = elevation_grid(self.dem, self.transform, self.crs)
            except Exception:
                self._elev = None
        return self._elev


def to_metric(dem, transform, crs, profile):

    from rasterio.crs import CRS

    c = CRS.from_user_input(crs) if crs is not None else None
    if c is None or not c.is_geographic:
        return dem, transform, crs, profile
    from pyproj import CRS as PCRS
    from pyproj.aoi import AreaOfInterest
    from pyproj.database import query_utm_crs_info
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    h, w = dem.shape
    west, north = transform.c, transform.f
    east, south = west + w * transform.a, north + h * transform.e
    info = query_utm_crs_info(datum_name="WGS 84", area_of_interest=AreaOfInterest(min(west, east), min(south, north),
                                                                                    max(west, east), max(south, north)))
    dst_crs = CRS.from_epsg(int(info[0].code)) if info else CRS.from_epsg(3857)
    dst_t, dw, dh = calculate_default_transform(c, dst_crs, w, h, min(west, east), min(south, north), max(west, east),
                                                max(south, north))
    out = np.full((dh, dw), np.nan, dtype=np.float32)
    reproject(dem, out, src_transform=transform, src_crs=c, dst_transform=dst_t, dst_crs=dst_crs, src_nodata=np.nan,
              dst_nodata=np.nan, resampling=Resampling.bilinear)
    prof = dict(profile)
    prof.update(transform=dst_t, crs=dst_crs, width=dw, height=dh)
    return out, dst_t, dst_crs, prof


def write_raster(arr, profile, crs, path):
    import rasterio

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.asarray(arr, dtype=np.float32)
    prof = dict(profile)
    prof.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, crs=crs or prof.get("crs"), compress="deflate",
                height=a.shape[0], width=a.shape[1])
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(np.where(np.isfinite(a), a, -9999.0).astype(np.float32), 1)
    return path


def read_raster(path):
    import rasterio

    with rasterio.open(path) as src:
        a = src.read(1).astype(np.float32)
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
    return a


def one_sentence(ranking, width):
    if not ranking:
        return "No view could be computed."
    top = ranking[0]
    text = f"{top['name']} shows features about {width:g} m wide most clearly (visibility {top['score']:.2f}"
    if len(ranking) > 1:
        text += f"; next: {ranking[1]['name']}, {ranking[1]['score']:.2f}"
    return text + ")."


def hillshade(dem, res):
    import rvt.vis

    from airchgis.enhance.metrics import finite_fill

    f, mask = finite_fill(dem)
    h = np.asarray(rvt.vis.hillshade(f.astype(np.float32), res, res, sun_azimuth=315, sun_elevation=35), dtype=np.float32)
    h[mask] = np.nan
    return h


def run_preparation(wb, fill_voids=True, cell_m=0.0):
    """Prepare the harmonized terrain (voids, optional coarser cell, artifact check) and reload the map."""
    from airchgis.gis.tools import run_tool

    out = run_tool("prepare_dtm", log=wb.log, input=wb.base_input(), output=str(OUT_DIR / f"{wb.name}_prepared.tif"),
                   fill_voids=bool(fill_voids), cell_m=float(cell_m or 0.0))["outputs"]
    import rasterio

    with rasterio.open(out["output"]) as src:
        dem = src.read(1).astype(np.float32)
        dem[dem == -9999.0] = np.nan
        transform, crs, profile = src.transform, src.crs, src.profile.copy()
    wb.set_dem(dem, transform, crs, profile)
    wb.prep["steps"] = out["steps"]
    wb.prep["params"] = {"fill_voids": bool(fill_voids), "cell_m": float(cell_m or 0.0)}
    run_relief(wb, None, "Hillshade", 315, replace=True)
    wb.message = f"Terrain prepared: {wb.dem.shape[1]} × {wb.dem.shape[0]} cells of {wb.res:.2f} m."


def run_regrid(wb, method="tin", cell_m=0.0, ground_only=True, remove_outliers=True, fill_voids=True):
    """Grid the point cloud again with other choices, then prepare the terrain."""
    from airchgis.gis.tools import run_tool

    las = wb.source.get("path")
    if wb.source.get("kind") != "points" or not las:
        raise ValueError("This terrain did not come from a point cloud.")
    out = run_tool("grid_point_cloud", log=wb.log, input=las, output=str(OUT_DIR / f"{wb.name}_{method}.tif"),
                   method=method, cell_m=float(cell_m or 0.0), ground_only=bool(ground_only),
                   remove_outliers=bool(remove_outliers))["outputs"]
    import rasterio

    with rasterio.open(out["output"]) as src:
        dem = src.read(1).astype(np.float32)
        dem[dem == -9999.0] = np.nan
        wb.harmonize(dem, src.transform, src.crs, src.profile.copy())
    wb.prep["source_steps"] = out["steps"]
    wb.prep["grid"] = {"method": method, "cell_m": float(cell_m or 0.0), "ground_only": bool(ground_only),
                       "remove_outliers": bool(remove_outliers)}
    run_preparation(wb, fill_voids=fill_voids)


def run_resolution(wb, width):
    from airchgis.gis.tools import run_tool

    r = run_tool("check_raster_resolvability", log=wb.log, input=wb.input_path(), feature_width_m=float(width))["outputs"]
    wb.resolution = {"width": float(width), "verdict": r.get("verdict"), "message": r.get("message"),
                     "cell_m": round(wb.res, 3)}


def run_relief(wb, core, method, value, compute=None, replace=False):

    from airchgis.gis.tools import run_tool
    from airchgis.rvt_web import RADIUS_TOOLS, TOOL_HELP

    params = {"altitude": 45.0} if method == "Hillshade" else {}
    if value is not None:
        if method in ("Hillshade", "Anisotropic Sky-View Factor"):
            params["azimuth"] = float(value)
        elif method in RADIUS_TOOLS:
            params["radius_px"] = float(value)
    wb.counter += 1
    lid = f"view{wb.counter}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in method).strip("_")
    out = run_tool("relief_view", log=wb.log, input=wb.input_path(), output=str(OUT_DIR / f"{wb.name}_{lid}_{safe}.tif"),
                   method=method, **params)["outputs"]
    import rasterio

    with rasterio.open(out["output"]) as src:
        arr = src.read().astype(np.float32)
    label = method if value is None else f"{method} ({value:g})"
    if out["bands"] == 1:
        a = arr[0]
        a[a == -9999.0] = np.nan
        wb.add_layer(lid, label, TOOL_HELP.get(method, ""), a, raw=a, display_range=(0, 1) if method == "Hillshade" else None)
    else:
        rgb = np.moveaxis(arr[:3], 0, -1)
        if method == "Multi-Hillshade":
            rgb = np.clip(rgb, 0, 1)
        else:
            lo, hi = np.nanpercentile(rgb, [1, 99]) if np.isfinite(rgb).any() else (0, 1)
            rgb = np.clip((rgb - lo) / max(hi - lo, 1e-9), 0, 1)
        wb.add_layer(lid, label, TOOL_HELP.get(method, ""), rgb, raw=rgb)
    wb.paths[lid] = out["output"]
    if replace:
        retain_layer(wb, lid)
    wb.message = f"{label} added to the map. {TOOL_HELP.get(method, '')}"


def retain_layer(wb, layer_id):
    wb.layers = [layer for layer in wb.layers if layer["id"] == layer_id]
    wb.arrays = {key: value for key, value in wb.arrays.items() if key == layer_id}
    wb.paths = {key: value for key, value in wb.paths.items() if key == layer_id}


def run_best_view(wb, width):
    from airchgis.gis.tools import ToolError, run_tool

    c = run_tool("clean_terrain", log=wb.log, input=wb.input_path(), output=str(OUT_DIR / f"{wb.name}_clean.tif"),
                 steps=list(STEP_LABELS))["outputs"]
    wb.clean_path = c["output"]
    r = run_tool("best_view", log=wb.log, input=wb.clean_path, output_dir=str(OUT_DIR / f"{wb.name}_bestview"),
                 target_feature_width_m=float(width), sites=wb.sites, quick=wb.dem.size > 4_000_000)
    if r["status"] == "refused":
        wb.message = r["message"]
        wb.message_level = "warning"
        return
    out = r["outputs"]
    before = hillshade(wb.dem, wb.res)
    wb.add_layer("before", "Before: original (hillshade)", "The terrain as loaded, before cleaning.", before,
                 visible=False, hide_others=False)
    best = read_raster(out["output"])
    wb.add_layer("best", f"After: {out['best']}", "Best view for the width you typed, on the cleaned terrain.", best)
    q = c["quality"]
    wb.details = {
        "cleaning": [{"measure": METRIC_LABELS[k], "before": q["before"][k], "after": q["after"][k]} for k in METRIC_LABELS],
        "notes": c["summary"],
        "ranking": [{"view": x["name"], "visibility": round(x["score"], 2),
                     **({"auc": None if x.get("auc") is None else round(x["auc"], 2)} if wb.sites else {})}
                    for x in out["ranking"]],
        "explanation": out["explanation"],
    }
    wb.message = one_sentence(out["ranking"], float(width)) + (f" {r['message']}" if r.get("message") else "")
    wb.last_width = float(width)


def run_fused(wb, width=None):

    from airchgis.gis.tools import run_tool

    width = float(width or max(2 * wb.res, 4.0))
    ids = [l["id"] for l in wb.layers if l["id"] in wb.paths and np.ndim(wb.arrays.get(l["id"])) == 2]
    if len(ids) < 2:
        wb.message = "Add at least two relief views to the map first; the fused view blends them."
        wb.message_level = "warning"
        return
    names = {l["id"]: l["name"] for l in wb.layers}
    r = run_tool("fuse_layers", log=wb.log, input=wb.input_path(), layers=[wb.paths[i] for i in ids],
                 output=str(OUT_DIR / f"{wb.name}_fused.tif"), target_feature_width_m=width)
    if r["status"] == "refused":
        wb.message = r["message"]
        wb.message_level = "warning"
        return
    out = r["outputs"]
    best = out["best_single"]["name"]
    best_name = next((names[i] for i in ids if Path(wb.paths[i]).stem == best), best)
    if out["gain_over_best_single"] < 1.005:
        wb.message = (f"The blend of your {len(ids)} views does not show features {width:g} m wide more clearly than "
                      f"{best_name} alone, so nothing was added.")
        wb.message_level = "warning"
        return
    weights = ", ".join(f"{names.get(i, i)} {100 * w:.0f}%" for i, w in zip(ids, out["weights"] or []) if w >= 0.01)
    wb.add_layer("fused", "Fused view", f"Blend of your relief views: {weights}.", read_raster(out["output"]))
    wb.paths["fused"] = out["output"]
    wb.message = (f"Fused view of {len(ids)} relief views ({weights}): features {width:g} m wide stand out "
                  f"{out['gain_over_best_single']:.2f} times more than in {best_name} alone.")


def run_figure(wb, fmt="pdf", dpi=300, width_mm=190.0, azimuth=-44.0, elevation=29.0, ve=0.0, drape=None,
               scale_bar=True, north_arrow=True):
    from airchgis.gis.tools import run_tool

    kw = dict(input=wb.input_path(), output=str(OUT_DIR / f"{wb.name}_3D_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"),
              azimuth=float(azimuth), elevation=float(elevation), dpi=int(dpi), width_mm=float(width_mm),
              scale_bar=bool(scale_bar), north_arrow=bool(north_arrow))
    if ve and float(ve) > 0:
        kw["vertical_exaggeration"] = float(ve)
    arr = wb.arrays.get(drape) if drape else None
    if arr is not None and np.ndim(arr) == 2 and arr.shape == wb.dem.shape:
        kw["drape"] = str(write_raster(arr, wb.profile, wb.crs, OUT_DIR / f"{wb.name}_drape.tif"))
    r = run_tool("export_3d_figure", log=wb.log, **kw)["outputs"]
    wb.offer(r["output"], mime="application/pdf" if fmt == "pdf" else "image/png")
    wb.message = r["note"]


def run_research_export(wb, format=None):
    from airchgis.terrain.export3d import export_terrain_3d, zip_package

    stem = f"{wb.name}__3D__{datetime.now():%Y%m%d_%H%M%S}"
    out_dir = OUT_DIR / "3d_research" / stem
    meta = export_terrain_3d(wb.dem, wb.transform, wb.crs, out_dir, stem=stem, nodata=None, vertical_exaggeration=1.0,
                             visualization="DTM (no relief visualization)", source=wb.name,
                             formats=(format,) if format else ("laz", "ply", "glb"), max_points=None, mesh_max_side=None)
    if format:
        key = {"laz": "point_cloud", "las": "point_cloud", "ply": "ply", "glb": "mesh"}.get(format)
        if key is None:
            raise ValueError("Unknown 3D data format.")
        wb.offer(meta["paths"][key], mime="model/gltf-binary" if format == "glb" else "application/octet-stream")
        return
    z = zip_package(meta, out_dir.with_suffix(".zip"))
    wb.offer(z, mime="application/zip")
    wb.message = "Open 3D data (LAZ/LAS, PLY, glTF and a metadata file) packed in one archive."


def offer_layer(wb, layer_id):
    if layer_id == "rvt_current" and wb.rvt_workspace is not None and getattr(wb, "rvt_current", None):
        wb.offer(wb.rvt_workspace.download(wb.rvt_current, "geotiff"), mime="image/tiff")
        return
    arr = wb.arrays.get(layer_id)
    if arr is None:
        raise ValueError("This layer cannot be downloaded.")
    name = next((l["name"] for l in wb.layers if l["id"] == layer_id), layer_id)
    safe = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    path = OUT_DIR / f"{wb.name}__{safe}.tif"
    if np.ndim(arr) == 3:
        from airchgis.rvt_api import RVTWorkspace
        if wb.rvt_workspace is None:
            wb.rvt_workspace = RVTWorkspace(wb)
        wb.rvt_workspace._write_raster(path, arr)
    else:
        path = write_raster(arr, wb.profile, wb.crs, path)
    wb.offer(path, mime="image/tiff")
    wb.message = f"{name} saved as GeoTIFF."


def run_contrast(wb, layer_id, replace=False):
    from airchgis.enhance import contrast

    arr = wb.arrays.get(layer_id)
    if arr is None or np.ndim(arr) != 2:
        raise ValueError("Stronger contrast works on single-band layers.")
    name = next((l["name"] for l in wb.layers if l["id"] == layer_id), layer_id)
    out, rep = contrast.enhance(arr, "clahe")
    wb.add_layer(f"{layer_id}_clahe", f"{name} · stronger contrast", "Adaptive histogram equalization: display only, "
                 "values are no longer elevations.", out)
    if replace:
        retain_layer(wb, f"{layer_id}_clahe")
    wb.message = rep["note"]


def offer_script(wb):
    path = OUT_DIR / f"{wb.name}_steps.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(wb.log.to_python(), encoding="utf-8")
    wb.offer(path, mime="text/x-python")
    wb.message = "The steps of this session as a Python script that repeats them."


def save_sites(wb, filename, b64):
    path = di.save_upload(Path(filename).name, base64.b64decode(b64), "sites")
    sites = di.read_sites(path)
    wb.sites = str(path)
    wb.message = f"{len(sites)} known sites loaded: the best view will report how well each view separates them (AUC)."


def handle_event(wb, event, compute=None, core=None, view3d=None):

    action = event.get("action")
    wb.download = None
    wb.view3d = None
    wb.message_level = "info"
    try:
        if str(action).startswith("rvt_"):
            from airchgis.rvt_api import RVTWorkspace

            if wb.rvt_workspace is None:
                wb.rvt_workspace = RVTWorkspace(wb)
            workspace = wb.rvt_workspace
            if action == "rvt_preview":
                workspace.execute(event["operation"], event.get("parameters"), event.get("instance"), preview=True)
            elif action == "rvt_preset_preview":
                workspace.preset(event["preset"], event.get("terrain", "general"), event.get("opacity", 50), preview=True)
            elif action == "rvt_run":
                keys = workspace.execute(event["operation"], event.get("parameters"), event.get("instance"))
                if event.get("show", True):
                    for key in keys:
                        if workspace._mapable(workspace.items[key]["value"]):
                            workspace.show(key, rgb=workspace.is_rgb(workspace.items[key]["value"]))
                            break
            elif action == "rvt_show":
                workspace.show(event["artifact"], event.get("band"), event.get("rgb", False))
            elif action == "rvt_download":
                wb.offer(workspace.download(event["artifact"], event.get("format", "native")))
            elif action == "rvt_package":
                wb.offer(workspace.package(), mime="application/zip")
            elif action == "rvt_settings":
                workspace.update_object(event["artifact"], event["fields"])
            elif action == "rvt_upload":
                workspace.upload(event["filename"], event["b64"])
            elif action == "rvt_preset":
                keys = workspace.preset(event["preset"], event.get("terrain", "general"), event.get("opacity", 50))
                if keys:
                    workspace.show(keys[0], rgb=True)
            elif action == "rvt_batch":
                workspace.batch(event["operation"], event["files"], event.get("parameters"), event.get("instance"))
            elif action != "rvt_open":
                raise ValueError("Unknown RVT workspace action.")
        elif action == "view3d":
            if view3d is None:
                raise ValueError("The 3D view is not available here.")
            wb.view3d = {"id": event.get("nonce"), "html": view3d()}
            wb.message = "3D view of your terrain: drag to rotate, scroll to zoom. Close it with ×."
        elif action == "prepare":
            run_preparation(wb, event.get("fill_voids", True), event.get("cell_m", 0.0))
        elif action == "regrid":
            run_regrid(wb, **{k: event[k] for k in ("method", "cell_m", "ground_only", "remove_outliers", "fill_voids") if k in event})
        elif action == "resolution":
            run_resolution(wb, float(event.get("width") or 2.0))
        elif action == "relief":
            run_relief(wb, core, event["method"], event.get("value"), compute, replace=event.get("replace", False))
        elif action == "best_view":
            run_best_view(wb, float(event.get("width") or 4.0))
        elif action == "fused":
            run_fused(wb, event.get("width"))
        elif action == "capture3d":
            from airchgis.terrain.view_export import save_current_view

            fmt = event.get("fmt", "png")
            if fmt not in {"pdf", "png"}:
                raise ValueError("Choose PDF or PNG.")
            path = OUT_DIR / "3d_figures" / f"{wb.name}_{uuid4().hex[:12]}.{fmt}"
            save_current_view(event["b64"], path, event.get("view"))
            wb.offer(path, mime="application/pdf" if fmt == "pdf" else "image/png")
        elif action == "figure":
            run_figure(wb, **{k: event[k] for k in ("fmt", "dpi", "width_mm", "azimuth", "elevation", "ve", "drape",
                                                   "scale_bar", "north_arrow") if k in event})
        elif action == "research":
            run_research_export(wb, event.get("format"))
        elif action == "download":
            offer_layer(wb, event["layer"])
        elif action == "contrast":
            run_contrast(wb, event["layer"], replace=event.get("replace", False))
        elif action == "script":
            offer_script(wb)
        elif action == "sites":
            save_sites(wb, event["filename"], event["b64"])
        elif action == "remove":
            wb.layers = [l for l in wb.layers if l["id"] != event["layer"]]
            wb.arrays.pop(event["layer"], None)
            wb.paths.pop(event["layer"], None)
            wb.message = ""
        elif action == "load_another":
            return "reload"
        else:
            wb.message = f"Unknown action: {action}"
            wb.message_level = "error"
    except Exception as exc:
        wb.message = f"Not completed: {exc}"
        wb.message_level = "error"
    wb.done_nonce = event.get("nonce")
    return None
