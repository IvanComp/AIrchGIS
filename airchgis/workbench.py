"""The map workbench: after upload, every tool runs from panels inside the map.

The map (``airchgis/map/component``) sends events (run a tool, find the best view, build a
fused view, export, download, load another file); :func:`handle_event` runs the same Python
functions as before and updates the state; the map then receives the new layers, the
one-sentence explanation and any file to download.
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

import numpy as np

from airchgis import data_input as di

OUT_DIR = di.WORKSPACE_DIR / "outputs" / "workbench"
STEP_LABELS = {"destripe": "Remove banding", "despike": "Remove spikes and pits", "fill_voids": "Fill small voids",
               "denoise": "Reduce noise (edge-preserving)"}
METRIC_LABELS = {"noise_sigma": "Noise (elevation units)", "stripe_energy": "Banding (share of fine detail)",
                 "spike_fraction": "Spikes and pits (share of pixels)", "void_fraction": "Voids (share of pixels)"}
MAX_DOWNLOAD_MB = 200


class Workbench:
    """State of one loaded terrain: layers, arrays, messages, details and the provenance log."""

    def __init__(self, dem, transform, crs, profile, name="terrain"):
        from airchgis.enhance.metrics import zero_nodata
        from airchgis.gis.provenance import ProvenanceLog

        dem, transform, crs, profile = to_metric(np.asarray(dem, dtype=np.float32), transform, crs, dict(profile))
        self.dem, self.n_zero = zero_nodata(dem)
        self.dem = self.dem.astype(np.float32)
        self.transform, self.crs, self.profile = transform, crs, dict(profile)
        self.res = float(abs(transform.a))
        self.name = name
        self.layers = []          # list of dicts sent to the map (without the arrays)
        self.arrays = {}          # layer id -> float array (for downloads and 3D figures)
        self.message = ""
        self.details = {}
        self.download = None
        self.view3d = None
        self.done_nonce = None
        self.counter = 0
        self.log = ProvenanceLog(f"AIrchGIS · {name}")
        self.src_path = None
        self.clean_path = None
        self.sites = None
        self.paths = {}           # layer id -> GeoTIFF written by the tool that made it

    # ------------------------------------------------------------ helpers
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
                  hide_others=True):
        from airchgis.map.view import georeference

        layer = georeference(self.mask_outside(array), self.transform, self.crs, layer_id, name, description,
                             cmap=cmap, visible=visible, opacity=opacity)
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
        self.download = {"id": f"dl{self.counter}", "filename": filename or p.name, "mime": mime,
                         "b64": base64.b64encode(p.read_bytes()).decode("ascii")}

    def map_args(self, tools):
        return {"layers": self.layers, "message": self.message, "details": self.details, "download": self.download,
                "view3d": self.view3d, "done_nonce": self.done_nonce, "tools": tools, "name": self.name,
                "elevation": self.elevation(), "sites": bool(self.sites)}

    def elevation(self):
        if not hasattr(self, "_elev"):
            from airchgis.map.view import elevation_grid

            try:
                self._elev = elevation_grid(self.dem, self.transform, self.crs)
            except Exception:
                self._elev = None
        return self._elev


def to_metric(dem, transform, crs, profile):
    """Reproject a terrain model in geographic coordinates (degrees) to its UTM zone, so pixel sizes are metres."""
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


# ------------------------------------------------------------ event handlers
def run_relief(wb, core, method, value, compute=None):
    """Add one relief visualization as a map layer (recorded in the session log as the ``relief_view`` tool)."""
    from airchgis.gis.tools import run_tool
    from airchgis.rvt_web import RADIUS_TOOLS, TOOL_HELP

    params = {}
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
        wb.add_layer(lid, label, TOOL_HELP.get(method, ""), a, raw=a)
    else:
        rgb = np.moveaxis(arr[:3], 0, -1)
        lo, hi = np.nanpercentile(rgb, [1, 99]) if np.isfinite(rgb).any() else (0, 1)
        rgb = np.clip((rgb - lo) / max(hi - lo, 1e-9), 0, 1)
        wb.add_layer(lid, label, TOOL_HELP.get(method, ""), rgb, raw=rgb)
    wb.paths[lid] = out["output"]
    wb.message = f"{label} added to the map. {TOOL_HELP.get(method, '')}"


def run_best_view(wb, width):
    from airchgis.gis.tools import ToolError, run_tool

    c = run_tool("clean_terrain", log=wb.log, input=wb.input_path(), output=str(OUT_DIR / f"{wb.name}_clean.tif"),
                 steps=list(STEP_LABELS))["outputs"]
    wb.clean_path = c["output"]
    r = run_tool("best_view", log=wb.log, input=wb.clean_path, output_dir=str(OUT_DIR / f"{wb.name}_bestview"),
                 target_feature_width_m=float(width), sites=wb.sites, quick=wb.dem.size > 4_000_000)
    if r["status"] == "refused":
        wb.message = r["message"]
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
    """Blend the single-band relief views the user added to the map."""
    from airchgis.gis.tools import run_tool

    width = float(width or max(2 * wb.res, 4.0))
    ids = [l["id"] for l in wb.layers if l["id"] in wb.paths and np.ndim(wb.arrays.get(l["id"])) == 2]
    if len(ids) < 2:
        wb.message = "Add at least two relief views to the map first; the fused view blends them."
        return
    names = {l["id"]: l["name"] for l in wb.layers}
    r = run_tool("fuse_layers", log=wb.log, input=wb.input_path(), layers=[wb.paths[i] for i in ids],
                 output=str(OUT_DIR / f"{wb.name}_fused.tif"), target_feature_width_m=width)
    if r["status"] == "refused":
        wb.message = r["message"]
        return
    out = r["outputs"]
    best = out["best_single"]["name"]
    best_name = next((names[i] for i in ids if Path(wb.paths[i]).stem == best), best)
    if out["gain_over_best_single"] < 1.005:  # less than 0.5% clearer: not worth a new layer
        wb.message = (f"The blend of your {len(ids)} views does not show features {width:g} m wide more clearly than "
                      f"{best_name} alone, so nothing was added.")
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


def run_research_export(wb):
    from airchgis.terrain.export3d import export_terrain_3d, zip_package

    stem = f"{wb.name}__3D__{datetime.now():%Y%m%d_%H%M%S}"
    out_dir = OUT_DIR / "3d_research" / stem
    meta = export_terrain_3d(wb.dem, wb.transform, wb.crs, out_dir, stem=stem, nodata=None, vertical_exaggeration=1.0,
                             visualization="DTM (no relief visualization)", source=wb.name)
    z = zip_package(meta, out_dir.with_suffix(".zip"))
    wb.offer(z, mime="application/zip")
    wb.message = "Open 3D data (LAZ/LAS, PLY, glTF and a metadata file) packed in one archive."


def offer_layer(wb, layer_id):
    arr = wb.arrays.get(layer_id)
    if arr is None:
        raise ValueError("This layer cannot be downloaded.")
    name = next((l["name"] for l in wb.layers if l["id"] == layer_id), layer_id)
    safe = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    if np.ndim(arr) == 3:
        raise ValueError("Colour layers are saved as PNG from the map; GeoTIFF is for single-band layers.")
    path = write_raster(arr, wb.profile, wb.crs, OUT_DIR / f"{wb.name}__{safe}.tif")
    wb.offer(path, mime="image/tiff")
    wb.message = f"{name} saved as GeoTIFF."


def run_contrast(wb, layer_id):
    from airchgis.enhance import contrast

    arr = wb.arrays.get(layer_id)
    if arr is None or np.ndim(arr) != 2:
        raise ValueError("Stronger contrast works on single-band layers.")
    name = next((l["name"] for l in wb.layers if l["id"] == layer_id), layer_id)
    out, rep = contrast.enhance(arr, "clahe")
    wb.add_layer(f"{layer_id}_clahe", f"{name} · stronger contrast", "Adaptive histogram equalization: display only, "
                 "values are no longer elevations.", out)
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
    """Run one event coming from the map; returns 'reload' when the user wants another file."""
    action = event.get("action")
    wb.download = None
    wb.view3d = None
    try:
        if action == "view3d":
            if view3d is None:
                raise ValueError("The 3D view is not available here.")
            wb.view3d = {"id": event.get("nonce"), "html": view3d()}
            wb.message = "3D view of your terrain: drag to rotate, scroll to zoom. Close it with ×."
        elif action == "relief":
            run_relief(wb, core, event["method"], event.get("value"), compute)
        elif action == "best_view":
            run_best_view(wb, float(event.get("width") or 4.0))
        elif action == "fused":
            run_fused(wb, event.get("width"))
        elif action == "figure":
            run_figure(wb, **{k: event[k] for k in ("fmt", "dpi", "width_mm", "azimuth", "elevation", "ve", "drape",
                                                   "scale_bar", "north_arrow") if k in event})
        elif action == "research":
            run_research_export(wb)
        elif action == "download":
            offer_layer(wb, event["layer"])
        elif action == "contrast":
            run_contrast(wb, event["layer"])
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
    except Exception as exc:  # shown in the map panel, never a crash
        wb.message = f"Not completed: {exc}"
    wb.done_nonce = event.get("nonce")
    return None
