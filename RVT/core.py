import inspect
import zipfile
import shutil
import math
import io
import json
import subprocess
import webbrowser
import xml.etree.ElementTree as ET
import threading
import hashlib
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote, urlparse
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import rasterio
import rasterio.merge
import rasterio.warp
import rasterio.features
import rasterio.transform
import rasterio.windows
from rasterio.fill import fillnodata
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib as mpl

mpl.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from PIL import Image, ImageDraw, ImageFont
import requests

import rvt.vis
import rvt.blend
from scripts.lads_preview import (
    CLOUD_PREPROCESS_PROFILES,
    LADS_BROWSER_MAX_SIDE,
    LADS_TARGET_CRS,
    build_browser_terrain_grid,
    build_lads_figure,
    build_lads_point_cloud,
    export_lads_las,
    write_browser_cloud_viewer,
)

try:
    from scipy.ndimage import gaussian_filter
except Exception:
    gaussian_filter = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    TKDND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    TKDND_AVAILABLE = False

BaseTk = TkinterDnD.Tk if TKDND_AVAILABLE and TkinterDnD is not None else tk.Tk
EXTS = {".tif", ".tiff", ".asc"}
PREPROCESSED_SUFFIXES = ("_prep", "_prep1", "_prep2", "_prep3")
SAT_ZOOMS_TRY = (19, 18, 17, 16, 15, 14, 13, 12)
REGIONAL_DTM_RELATIVE_PATH = Path("data") / "regional_dtm" / "HRDTM5m_Umbria_Marche_Abruzzo.tif"
GENERATED_DTM_OUTPUT_RELATIVE = Path("generated_dtm") / "DTM"
REGIONAL_DTM_PREVIEW_ZOOMS = (10, 9, 8, 7, 6)
REGIONAL_DTM_MAX_RECOMMENDED_CELLS = 80_000_000
MASE_URL = "https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new/"
GE_URL = "https://earth.google.com/web/@42.06329556,13.44458279,859.60342866a,1982377.06794083d,35y,0h,0t,0r/data=CgRCAggBOgMKATBCAggASg0I____________ARAA"
ARCGIS_CURRENT_TILE_TEMPLATE = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
WAYBACK_CAPABILITIES_URL = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
FIRST_DIR_CANDIDATES = ("DSM_First", "DSM_Fisrt", "DSMfirst")
LAST_DIR_CANDIDATES = ("DSM_Last", "DSMlast")
PREPRO_PROFILES = {
    "prep1": {"label": "PrePro 1", "suffix": "_prep1", "fill_dist": 60, "fill_smooth_iter": 1, "sigma": 0.45},
    "prep2": {"label": "PrePro 2", "suffix": "_prep2", "fill_dist": 100, "fill_smooth_iter": 1, "sigma": 0.8},
    "prep3": {"label": "PrePro 3", "suffix": "_prep3", "fill_dist": 140, "fill_smooth_iter": 2, "sigma": 1.2},
}
BASE_IMAGE_OPTIONS = ["Original", "PrePro 1", "PrePro 2", "PrePro 3"]
BASE_IMAGE_TO_PROFILE = {"PrePro 1": "prep1", "PrePro 2": "prep2", "PrePro 3": "prep3"}
CLOUD_SURFACE_OPTIONS = [
    {"key": "original", "label": "Original"},
    {"key": "prep1", "label": "PrePro 1"},
    {"key": "prep2", "label": "PrePro 2"},
    {"key": "prep3", "label": "PrePro 3"},
]
REPORT_CROP_RADIUS_PX = 140
REPORT_CROP_OUTPUT_SIZE = 720
PDF_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
]
WAYBACK_NS = {"wmts": "https://www.opengis.net/wmts/1.0", "ows": "https://www.opengis.net/ows/1.1"}

def unzip_all(folder: Path):
    if not folder.exists():
        return 0
    n = 0
    for z in folder.rglob("*.zip"):
        if not z.is_file():
            continue
        dest = z.parent / z.stem
        marker = dest / ".unzipped"
        mt = str(z.stat().st_mtime_ns)
        if marker.exists():
            try:
                if marker.read_text(encoding="utf-8").strip() == mt:
                    continue
            except Exception:
                pass
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except Exception:
                pass
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(z, "r") as zz:
                zz.extractall(dest)
            marker.write_text(mt, encoding="utf-8")
            n += 1
        except Exception:
            pass
    return n


def prepare_inputs(root: Path):
    n = 0
    base = root / "image"
    n += unzip_all(base / "DTM")
    for name in FIRST_DIR_CANDIDATES:
        n += unzip_all(base / name)
    for name in LAST_DIR_CANDIDATES:
        n += unzip_all(base / name)
    return n


def find_dir(base: Path, candidates):
    for name in candidates:
        p = base / name
        if p.exists():
            return p
    return None


def pick_latest_from_candidates(base: Path, candidates, prefer_preprocessed=None):
    best = None
    best_mtime = -1
    for name in candidates:
        p = pick_latest_raster(base / name, prefer_preprocessed=prefer_preprocessed)
        if p is None:
            continue
        try:
            mt = p.stat().st_mtime_ns
        except Exception:
            mt = 0
        if mt > best_mtime:
            best = p
            best_mtime = mt
    return best


def select_rasters(folder: Path, prefer_preprocessed=None):
    rasters = list_rasters(folder)
    if not rasters:
        return []
    rasters.sort(key=lambda p: (p.parent.as_posix(), p.name.lower()))
    if prefer_preprocessed is True:
        return [p for p in rasters if p.stem.endswith(("_prep", "_prep1", "_prep2", "_prep3"))]
    if isinstance(prefer_preprocessed, str) and prefer_preprocessed:
        return [p for p in rasters if p.stem.endswith(prefer_preprocessed)]
    if prefer_preprocessed is False:
        return [
            p
            for p in rasters
            if not (
                p.stem.endswith("_prep")
                or p.stem.endswith("_prep1")
                or p.stem.endswith("_prep2")
                or p.stem.endswith("_prep3")
            )
        ]
    return rasters


def select_rasters_from_candidates(base: Path, candidates, prefer_preprocessed=None):
    folder = find_dir(base, candidates)
    if folder is None:
        return []
    return select_rasters(folder, prefer_preprocessed=prefer_preprocessed)


def utm_epsg_from_lonlat(lon, lat):
    zone = int((lon + 180) // 6) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


def prep_output_path(src_path: Path, suffix="_prep"):
    if src_path.stem.endswith(suffix):
        return src_path
    return src_path.with_name(f"{src_path.stem}{suffix}{src_path.suffix}")


def database_place_root_for_source(root: Path, src_path: Path):
    db_root = get_database_root(root)
    if db_root is None:
        return None
    try:
        src_resolved = Path(src_path).expanduser().resolve()
        db_resolved = db_root.expanduser().resolve()
        rel = src_resolved.relative_to(db_resolved)
    except Exception:
        return None
    if not rel.parts:
        return None
    return db_resolved / rel.parts[0]


def persistent_prepro_output_path(root: Path, src_path: Path, suffix="_prep"):
    src = Path(src_path).expanduser().resolve()
    place_root = database_place_root_for_source(root, src)
    if place_root is None:
        return prep_output_path(src, suffix=suffix)
    try:
        rel = src.relative_to(place_root)
    except Exception:
        return prep_output_path(src, suffix=suffix)
    cache_dir = place_root / ".prepro_cache" / suffix.lstrip("_") / rel.parent
    return cache_dir / f"{src.stem}{suffix}{src.suffix}"


def has_fresh_preprocessed(root: Path, src_path: Path, suffix="_prep"):
    src = Path(src_path).expanduser().resolve()
    dst = persistent_prepro_output_path(root, src, suffix=suffix)
    if not dst.exists():
        return False, dst
    try:
        return dst.stat().st_mtime_ns >= src.stat().st_mtime_ns, dst
    except Exception:
        return True, dst


def preprocess_raster_file(src_path: Path, dst_path: Path, fill_dist=100, fill_smooth_iter=1, sigma=0.8):
    with rasterio.open(src_path) as src:
        arr = src.read(1).astype(np.float32)
        nodata = src.nodata
        meta = src.meta.copy()
        src_crs = src.crs
        src_transform = src.transform
        src_bounds = src.bounds

    if nodata is not None:
        arr[arr == nodata] = np.nan

    mask_nan = ~np.isfinite(arr)
    if np.any(mask_nan):
        filled = np.nan_to_num(arr, nan=0.0).astype(np.float32)
        valid = np.isfinite(arr).astype(np.uint8)
        if np.any(valid):
            arr = fillnodata(
                filled,
                mask=valid,
                max_search_distance=int(fill_dist),
                smoothing_iterations=int(fill_smooth_iter),
            ).astype(np.float32)
        else:
            arr = filled

    if gaussian_filter is not None and sigma and float(sigma) > 0:
        arr = gaussian_filter(arr, sigma=float(sigma)).astype(np.float32)

    dst_crs = src_crs
    if src_crs and src_crs.is_geographic:
        lon_c = float((src_bounds.left + src_bounds.right) * 0.5)
        lat_c = float((src_bounds.bottom + src_bounds.top) * 0.5)
        dst_crs = rasterio.crs.CRS.from_string(utm_epsg_from_lonlat(lon_c, lat_c))

    if dst_crs and src_crs and str(dst_crs) != str(src_crs):
        dst_transform, dst_w, dst_h = rasterio.warp.calculate_default_transform(
            src_crs, dst_crs, meta["width"], meta["height"], *src_bounds
        )
        dst_arr = np.full((dst_h, dst_w), np.nan, dtype=np.float32)
        rasterio.warp.reproject(
            source=arr,
            destination=dst_arr,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            src_nodata=np.nan,
            dst_nodata=np.nan,
            resampling=rasterio.warp.Resampling.bilinear,
        )
        arr = dst_arr
        meta.update(transform=dst_transform, width=dst_w, height=dst_h, crs=dst_crs)
    else:
        meta.update(transform=src_transform, crs=src_crs)

    out_nodata = -9999.0
    out = np.asarray(arr, dtype=np.float32)
    out[~np.isfinite(out)] = out_nodata
    meta.update(dtype="float32", count=1, nodata=out_nodata, compress="lzw")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dst_path, "w", **meta) as dst:
        dst.write(out, 1)


def _infer_geojson_crs(geojson_obj):
    crs_obj = geojson_obj.get("crs")
    if not crs_obj:
        return "EPSG:4326"
    props = crs_obj.get("properties", {})
    name = props.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "EPSG:4326"


def _collect_polygon_geometries(geojson_obj):
    geoms = []
    if geojson_obj.get("type") == "FeatureCollection":
        for feat in geojson_obj.get("features", []):
            g = feat.get("geometry")
            if not g:
                continue
            if g.get("type") in {"Polygon", "MultiPolygon"}:
                geoms.append(g)
    elif geojson_obj.get("type") in {"Polygon", "MultiPolygon"}:
        geoms.append(geojson_obj)
    return geoms


def find_place_geojson(place_root: Path):
    if not place_root.exists() or not place_root.is_dir():
        return None
    files = sorted(
        [p for p in place_root.iterdir() if p.is_file() and p.suffix.lower() in {".geojson", ".json"}],
        key=lambda p: p.name.lower(),
    )
    for p in files:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _collect_polygon_geometries(obj):
            return p
    return None


def clip_tile_to_geojson(tile, geojson_path: Path):
    if geojson_path is None or not geojson_path.exists():
        return tile
    profile = tile.get("profile")
    if not profile or "transform" not in profile:
        return tile
    transform = profile["transform"]
    h, w = tile["DTM"].shape
    if h <= 0 or w <= 0:
        return tile

    obj = json.loads(geojson_path.read_text(encoding="utf-8"))
    geoms = _collect_polygon_geometries(obj)
    if not geoms:
        raise RuntimeError("GeoJSON without valid polygons.")

    src_crs = _infer_geojson_crs(obj)
    dst_crs = tile.get("crs")
    geoms_dst = []
    for g in geoms:
        if dst_crs is not None:
            try:
                g2 = rasterio.warp.transform_geom(src_crs, dst_crs, g, precision=6)
            except Exception:
                g2 = g
        else:
            g2 = g
        geoms_dst.append(g2)

    inside = rasterio.features.geometry_mask(geoms_dst, out_shape=(h, w), transform=transform, invert=True)
    if not np.any(inside):
        raise RuntimeError("The GeoJSON area does not intersect the current raster.")

    rows, cols = np.where(inside)
    r0, r1 = int(rows.min()), int(rows.max())
    c0, c1 = int(cols.min()), int(cols.max())
    win_h = r1 - r0 + 1
    win_w = c1 - c0 + 1
    inside_win = inside[r0 : r1 + 1, c0 : c1 + 1]

    def _clip_arr(a):
        if a is None:
            return None
        b = np.asarray(a, dtype=np.float32)[r0 : r1 + 1, c0 : c1 + 1].copy()
        b[~inside_win] = np.nan
        return b

    dtm = _clip_arr(tile["DTM"])
    dsmf = _clip_arr(tile["DSM_First"])
    dsml = _clip_arr(tile["DSM_Last"])
    ndsm = (dsmf - dtm) if dsmf is not None else None
    diff = (dsmf - dsml) if dsmf is not None and dsml is not None else None

    new_transform = transform * rasterio.transform.Affine.translation(c0, r0)
    new_profile = profile.copy()
    new_profile.update(width=win_w, height=win_h, transform=new_transform)
    b = rasterio.transform.array_bounds(win_h, win_w, new_transform)
    new_bounds = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))

    out = tile.copy()
    out["DTM"] = dtm
    out["DSM_First"] = dsmf
    out["DSM_Last"] = dsml
    out["nDSM"] = ndsm
    out["First-Last"] = diff
    out["profile"] = new_profile
    out["bounds"] = new_bounds
    out["area_geojson"] = str(geojson_path)
    return out


def list_database_places(root: Path):
    db = get_database_root(root)
    if db is None:
        return []
    out = []
    for p in sorted([x for x in db.iterdir() if x.is_dir()], key=lambda x: x.name.lower()):
        if p.name.startswith("."):
            continue
        if not (p / "DTM").exists():
            continue
        out.append(p.name)
    return out


def get_database_root(root: Path):
    cands = [root / "Database", root / "image" / "Database"]
    for db in cands:
        if db.exists() and db.is_dir():
            return db
    return None


def prepare_inputs_place(place_root: Path):
    n = 0
    n += unzip_all(place_root / "DTM")
    for name in FIRST_DIR_CANDIDATES:
        n += unzip_all(place_root / name)
    for name in LAST_DIR_CANDIDATES:
        n += unzip_all(place_root / name)
    return n


def list_rasters(folder: Path):
    if not folder.exists():
        return []
    out = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            out.append(p)
    return out


def pick_latest_raster(folder: Path, prefer_preprocessed=None):
    rasters = list_rasters(folder)
    if not rasters:
        return None
    rasters.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    if prefer_preprocessed is True:
        pref = [p for p in rasters if p.stem.endswith("_prep")]
        if pref:
            return pref[0]
    if isinstance(prefer_preprocessed, str) and prefer_preprocessed:
        pref = [p for p in rasters if p.stem.endswith(prefer_preprocessed)]
        if pref:
            return pref[0]
    if prefer_preprocessed is False:
        pref = [
            p
            for p in rasters
            if not (
                p.stem.endswith("_prep")
                or p.stem.endswith("_prep1")
                or p.stem.endswith("_prep2")
                or p.stem.endswith("_prep3")
            )
        ]
        if pref:
            return pref[0]
    return rasters[0]


def load_raster(path: Path):
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
        res = float(src.res[0])
        profile = src.profile.copy()
        bounds = (float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top))
        crs = src.crs
    return data, res, profile, nodata, bounds, crs


def load_raster_source(paths):
    if isinstance(paths, Path):
        return load_raster(paths)
    if not isinstance(paths, (list, tuple)):
        raise RuntimeError("Invalid raster source.")
    items = [Path(p) for p in paths if p]
    if not items:
        raise RuntimeError("No raster available.")
    if len(items) == 1:
        return load_raster(items[0])

    datasets = []
    try:
        for path in items:
            datasets.append(rasterio.open(path))
        first = datasets[0]
        merged, out_transform = rasterio.merge.merge(datasets, indexes=1)
        data = merged[0].astype(np.float32)
        nodata = first.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
        profile = first.profile.copy()
        profile.update(
            width=data.shape[1],
            height=data.shape[0],
            transform=out_transform,
        )
        bounds = rasterio.transform.array_bounds(data.shape[0], data.shape[1], out_transform)
        res = float(abs(out_transform.a))
        crs = first.crs
        return data, res, profile, nodata, (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])), crs
    finally:
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass


def profile_for_float(profile, nodata_val=-9999.0, count=1):
    p = profile.copy()
    p.update(dtype=rasterio.float32, count=count, nodata=nodata_val, driver="GTiff", compress="lzw")
    return p


def save_geotiff(path: Path, data: np.ndarray, profile, nodata_val=-9999.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.asarray(data, dtype=np.float32)
    if out.ndim == 2:
        bands = out[None, :, :]
    elif out.ndim == 3:
        if out.shape[0] <= 16 and out.shape[1] > 16 and out.shape[2] > 16:
            bands = out
        elif out.shape[2] <= 16 and out.shape[0] > 16 and out.shape[1] > 16:
            bands = np.moveaxis(out, 2, 0)
        else:
            raise RuntimeError(f"Unsupported export shape: {out.shape}")
    else:
        raise RuntimeError(f"Unsupported export dimensions: {out.ndim}")
    p = profile_for_float(profile, nodata_val=nodata_val, count=int(bands.shape[0]))
    bands[~np.isfinite(bands)] = np.float32(nodata_val)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(bands)


def sig_filter(func, kwargs):
    try:
        params = inspect.signature(func).parameters
        return {k: v for k, v in kwargs.items() if k in params}
    except Exception:
        return kwargs


def safe_call(func, args, kwargs):
    kw = sig_filter(func, kwargs)
    try:
        return func(*args, **kw)
    except TypeError:
        return func(*args)


def nanpercentile_safe(a, q):
    finite = np.isfinite(a)
    if finite.sum() == 0:
        return np.nan
    return np.nanpercentile(a, q)


def stretch01(a, p_low, p_high):
    lo = nanpercentile_safe(a, p_low)
    hi = nanpercentile_safe(a, p_high)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = np.nanmin(a)
        hi = np.nanmax(a)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        b = np.zeros_like(a, dtype=np.float32)
        b[~np.isfinite(a)] = np.nan
        return b
    b = (a - lo) / (hi - lo)
    b = np.clip(b, 0.0, 1.0).astype(np.float32)
    b[~np.isfinite(a)] = np.nan
    return b


def fill_nan_with_median(a):
    mask = ~np.isfinite(a)
    if mask.all():
        return a, mask
    v = np.nanmedian(a)
    b = a.copy()
    b[mask] = v
    return b, mask


def extract_array(x):
    if isinstance(x, np.ndarray):
        return x
    if isinstance(x, (list, tuple)):
        for v in x:
            if isinstance(v, np.ndarray):
                return v
        for v in x:
            y = extract_array(v)
            if isinstance(y, np.ndarray):
                return y
        raise TypeError("RVT returned list/tuple without ndarray")
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, np.ndarray):
                return v
        for v in x.values():
            y = extract_array(v)
            if isinstance(y, np.ndarray):
                return y
        raise TypeError("RVT returned dict without ndarray")
    raise TypeError(f"RVT returned unsupported type: {type(x).__name__}")


def as_float32(x):
    return np.asarray(x, dtype=np.float32)


def to_single_band(out, dem_shape):
    arr = as_float32(out)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        if arr.shape[0] <= 64 and arr.shape[1:] == dem_shape:
            return as_float32(np.nanmean(arr, axis=0))
        if arr.shape[-1] <= 4 and arr.shape[:2] == dem_shape:
            return as_float32(np.nanmean(arr, axis=2))
        if arr.shape[0] in (3, 4):
            return as_float32(np.nanmean(arr, axis=0))
        return as_float32(np.nanmean(arr, axis=0))
    raise RuntimeError(f"RVT output with unsupported shape: {arr.shape}")


def fit_to_shape(arr, target_shape):
    if arr.shape == target_shape:
        return arr
    th, tw = target_shape
    h, w = arr.shape

    out = np.full((th, tw), np.nan, dtype=np.float32)

    src_y0 = max(0, (h - th) // 2)
    src_x0 = max(0, (w - tw) // 2)
    dst_y0 = max(0, (th - h) // 2)
    dst_x0 = max(0, (tw - w) // 2)

    copy_h = min(h - src_y0, th - dst_y0)
    copy_w = min(w - src_x0, tw - dst_x0)
    if copy_h <= 0 or copy_w <= 0:
        return out

    out[dst_y0 : dst_y0 + copy_h, dst_x0 : dst_x0 + copy_w] = arr[src_y0 : src_y0 + copy_h, src_x0 : src_x0 + copy_w]
    return out


def normalize_rgb01(arr):
    rgb = as_float32(arr)
    if rgb.ndim != 3:
        raise RuntimeError(f"Invalid RGB output: {rgb.shape}")
    if rgb.shape[0] in (3, 4):
        rgb = np.moveaxis(rgb[:3, :, :], 0, 2)
    elif rgb.shape[2] in (3, 4):
        rgb = rgb[:, :, :3]
    else:
        raise RuntimeError(f"Invalid RGB output: {rgb.shape}")
    finite = np.isfinite(rgb)
    if not finite.any():
        return np.zeros_like(rgb, dtype=np.float32)
    lo = np.nanpercentile(rgb, 2.0)
    hi = np.nanpercentile(rgb, 98.0)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = np.nanmin(rgb)
        hi = np.nanmax(rgb)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        out = np.zeros_like(rgb, dtype=np.float32)
        out[~np.isfinite(rgb)] = 0.0
        return out
    out = (rgb - lo) / (hi - lo)
    out = np.clip(out, 0.0, 1.0).astype(np.float32)
    out[~np.isfinite(rgb)] = 0.0
    return out


def is_rgb_method(method_name):
    return method_name in {"e3MSTP (RGB)"}


def compute_method(method, dem, res, az, alt, z, rad, n_dir):
    if method == "Raw":
        return dem

    dem2, mask = fill_nan_with_median(dem)
    svf_r = int(max(1, round(rad)))

    def finalize(raw):
        arr = to_single_band(extract_array(raw), dem2.shape)
        arr = fit_to_shape(arr, dem2.shape)
        if arr.shape == mask.shape:
            arr[mask] = np.nan
        return arr

    if method == "Hillshade" and hasattr(rvt.vis, "hillshade"):
        f = rvt.vis.hillshade
        kw = {
            "sun_az": az,
            "sun_el": alt,
            "sun_azimuth": az,
            "sun_altitude": alt,
            "azimuth": az,
            "altitude": alt,
            "z_factor": z,
            "z": z,
        }
        out = safe_call(f, (dem2, res, res), kw)
        return finalize(out)

    if method == "Slope":
        if hasattr(rvt.vis, "slope"):
            f = rvt.vis.slope
            kw = {"z_factor": z, "z": z}
            out = safe_call(f, (dem2, res, res), kw)
            return finalize(out)
        if hasattr(rvt.vis, "slope_aspect"):
            f = rvt.vis.slope_aspect
            kw = {"ve_factor": z, "z_factor": z, "z": z}
            out = safe_call(f, (dem2, res, res), kw)
            if isinstance(out, dict) and "slope" in out:
                out = out["slope"]
            return finalize(out)

    if method == "Sky-View Factor" and hasattr(rvt.vis, "sky_view_factor"):
        out = rvt.vis.sky_view_factor(
            dem2,
            float(res),
            compute_svf=True,
            compute_asvf=False,
            compute_opns=False,
            svf_n_dir=int(n_dir),
            svf_r_max=svf_r,
            ve_factor=float(z),
        )
        if isinstance(out, dict) and "svf" in out:
            out = out["svf"]
        return finalize(out)

    if method == "Anisotropic Sky-View Factor" and hasattr(rvt.vis, "sky_view_factor"):
        out = rvt.vis.sky_view_factor(
            dem2,
            float(res),
            compute_svf=False,
            compute_asvf=True,
            compute_opns=False,
            svf_n_dir=int(n_dir),
            svf_r_max=svf_r,
            asvf_dir=float(az),
            asvf_level=1,
            ve_factor=float(z),
        )
        if isinstance(out, dict) and "asvf" in out:
            out = out["asvf"]
        return finalize(out)

    if method == "Positive Openness" and hasattr(rvt.vis, "sky_view_factor"):
        out = rvt.vis.sky_view_factor(
            dem2,
            float(res),
            compute_svf=False,
            compute_asvf=False,
            compute_opns=True,
            svf_n_dir=int(n_dir),
            svf_r_max=svf_r,
            ve_factor=float(z),
        )
        if isinstance(out, dict) and "opns" in out:
            out = out["opns"]
        return finalize(out)

    if method in {"Simple Local Relief Model", "Local Relief Model"} and (hasattr(rvt.vis, "slrm") or hasattr(rvt.vis, "local_relief_model")):
        if hasattr(rvt.vis, "slrm"):
            f = rvt.vis.slrm
            radius_cell = int(round(rad))
            radius_cell = max(10, min(50, radius_cell))
            kw = {"radius_cell": radius_cell, "ve_factor": z}
            out = safe_call(f, (dem2,), kw)
        else:
            f = rvt.vis.local_relief_model
            kw = {"radius": rad, "rad": rad, "max_rad": rad, "ve_factor": z, "z_factor": z, "z": z}
            out = safe_call(f, (dem2, res, res), kw)
        return finalize(out)

    if method == "Multi-Hillshade" and hasattr(rvt.vis, "multi_hillshade"):
        f = rvt.vis.multi_hillshade
        kw = {"nr_directions": int(n_dir), "sun_elevation": alt, "ve_factor": z}
        out = safe_call(f, (dem2, res, res), kw)
        return finalize(out)

    if method == "Sky Illumination" and hasattr(rvt.vis, "sky_illumination"):
        f = rvt.vis.sky_illumination
        kw = {
            "resolution": res,
            "num_directions": int(n_dir),
            "max_fine_radius": int(max(1, round(rad))),
            "shadow_az": az,
            "shadow_el": alt,
            "ve_factor": z,
        }
        out = safe_call(f, (dem2,), kw)
        return finalize(out)

    if method == "Local Dominance" and hasattr(rvt.vis, "local_dominance"):
        f = rvt.vis.local_dominance
        min_rad = max(1, int(round(rad)))
        max_rad = max(min_rad + 5, min_rad * 2)
        rad_inc = max(1, int(round(min_rad / 5)))
        angular_res = max(5, int(round(360 / max(4, int(n_dir)))))
        kw = {
            "min_rad": min_rad,
            "max_rad": max_rad,
            "rad_inc": rad_inc,
            "angular_res": angular_res,
            "observer_height": 1.7,
            "ve_factor": z,
        }
        out = safe_call(f, (dem2,), kw)
        return finalize(out)

    if method == "Multi-Scale Relief Model" and hasattr(rvt.vis, "msrm"):
        f = rvt.vis.msrm
        feature_min = max(float(res), float(rad) * float(res) * 0.5)
        feature_max = max(feature_min + float(res), feature_min * 6.0)
        kw = {"resolution": res, "feature_min": feature_min, "feature_max": feature_max, "scaling_factor": 2, "ve_factor": z}
        out = safe_call(f, (dem2,), kw)
        return finalize(out)

    if method == "Multi-Scale Topographic Position" and hasattr(rvt.vis, "mstp"):
        f = rvt.vis.mstp
        kw = {"ve_factor": z}
        out = safe_call(f, (dem2,), kw)
        return finalize(out)

    if method == "e3MSTP (RGB)" and hasattr(rvt.blend, "e3mstp"):
        out = rvt.blend.e3mstp(dem2, float(res))
        rgb = normalize_rgb01(out)
        if rgb.shape[:2] != dem2.shape:
            h, w = dem2.shape
            rh, rw = rgb.shape[:2]
            tmp = np.full((h, w, 3), 0.0, dtype=np.float32)
            src_y0 = max(0, (rh - h) // 2)
            src_x0 = max(0, (rw - w) // 2)
            dst_y0 = max(0, (h - rh) // 2)
            dst_x0 = max(0, (w - rw) // 2)
            copy_h = min(rh - src_y0, h - dst_y0)
            copy_w = min(rw - src_x0, w - dst_x0)
            if copy_h > 0 and copy_w > 0:
                tmp[dst_y0 : dst_y0 + copy_h, dst_x0 : dst_x0 + copy_w, :] = rgb[src_y0 : src_y0 + copy_h, src_x0 : src_x0 + copy_w, :]
            rgb = tmp
        rgb[mask, :] = 0.0
        return rgb

    raise RuntimeError(f"Method not available or not supported: {method}")


def latlon_to_global_px(lat, lon, zoom):
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * 256.0 * n
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * 256.0 * n
    return x, y


def clamp_int(v, lo, hi):
    return int(max(lo, min(hi, v)))


def decimal_to_dms(value, positive_ref, negative_ref):
    value = float(value)
    ref = positive_ref if value >= 0 else negative_ref
    value = abs(value)
    deg = int(value)
    minutes_full = (value - deg) * 60.0
    minutes = int(minutes_full)
    seconds = int(round((minutes_full - minutes) * 60.0))
    if seconds == 60:
        seconds = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        deg += 1
    return f"{deg}°{minutes:02d}'{seconds:02d}\"{ref}"


def google_maps_point_url(lat, lon):
    return f"https://www.google.com/maps/search/?api=1&query={float(lat):.8f},{float(lon):.8f}"


def wrap_text_lines(draw, text, font, max_width):
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def load_pdf_font(size):
    for path in PDF_FONT_CANDIDATES:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def load_wayback_layers():
    try:
        text = requests.get(WAYBACK_CAPABILITIES_URL, timeout=20).text
        root = ET.fromstring(text)
    except Exception:
        return []

    out = []
    for layer in root.findall(".//wmts:Layer", WAYBACK_NS):
        title = layer.findtext("ows:Title", default="", namespaces=WAYBACK_NS).strip()
        if "Wayback " not in title:
            continue
        date_str = title.split("Wayback ", 1)[1].rstrip(")")
        resource = layer.find("wmts:ResourceURL", WAYBACK_NS)
        if resource is None:
            continue
        template = resource.attrib.get("template", "").strip()
        if not template:
            continue
        year = date_str[:4]
        out.append({"year": year, "date": date_str, "template": template})
    return out


class BasemapCache:
    def __init__(self, max_items=6):
        self.max_items = max_items
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, loader):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        v = loader()
        with self._lock:
            self._cache[key] = v
            if len(self._cache) > self.max_items:
                self._cache.popitem(last=False)
        return v

    def peek(self, key):
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key, value):
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self.max_items:
                self._cache.popitem(last=False)


def fetch_tile(z, x, y, session, tile_template=ARCGIS_CURRENT_TILE_TEMPLATE):
    url = tile_template.format(z=z, y=y, x=x, TileMatrix=z, TileRow=y, TileCol=x, TileMatrixSet="GoogleMapsCompatible")
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def build_satellite_rgb(bounds_lonlat, zoom, tile_template=ARCGIS_CURRENT_TILE_TEMPLATE):
    left, bottom, right, top = bounds_lonlat
    if right <= left or top <= bottom:
        return None

    px0, py0 = latlon_to_global_px(top, left, zoom)
    px1, py1 = latlon_to_global_px(bottom, right, zoom)

    min_px = min(px0, px1)
    max_px = max(px0, px1)
    min_py = min(py0, py1)
    max_py = max(py0, py1)

    n = 2 ** zoom
    max_tile = n - 1

    tx0 = clamp_int(math.floor(min_px / 256.0), 0, max_tile)
    tx1 = clamp_int(math.floor((max_px - 1.0) / 256.0), 0, max_tile)
    ty0 = clamp_int(math.floor(min_py / 256.0), 0, max_tile)
    ty1 = clamp_int(math.floor((max_py - 1.0) / 256.0), 0, max_tile)

    tiles_x = tx1 - tx0 + 1
    tiles_y = ty1 - ty0 + 1
    if tiles_x * tiles_y > 64:
        return None

    w = tiles_x * 256
    h = tiles_y * 256
    mosaic = Image.new("RGB", (w, h), (0, 0, 0))

    session = requests.Session()
    session.headers.update({"User-Agent": "RVT-LiDAR-Explorer"})
    coords = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    max_workers = min(8, max(1, len(coords)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(fetch_tile, zoom, tx, ty, session, tile_template): (tx, ty)
            for tx, ty in coords
        }
        for fut in as_completed(futures):
            tx, ty = futures[fut]
            try:
                tile = fut.result()
            except Exception:
                tile = None
            if tile is None:
                continue
            ox = (tx - tx0) * 256
            oy = (ty - ty0) * 256
            mosaic.paste(tile, (ox, oy))

    crop_l = int(round(min_px - tx0 * 256.0))
    crop_t = int(round(min_py - ty0 * 256.0))
    crop_r = int(round(max_px - tx0 * 256.0))
    crop_b = int(round(max_py - ty0 * 256.0))

    crop_l = max(0, min(w, crop_l))
    crop_t = max(0, min(h, crop_t))
    crop_r = max(0, min(w, crop_r))
    crop_b = max(0, min(h, crop_b))

    if crop_r <= crop_l or crop_b <= crop_t:
        return None

    return mosaic.crop((crop_l, crop_t, crop_r, crop_b))


def regional_dtm_source_path(root: Path):
    return Path(root).expanduser().resolve() / REGIONAL_DTM_RELATIVE_PATH


def regional_dtm_output_dir(root: Path):
    return Path(root).expanduser().resolve() / GENERATED_DTM_OUTPUT_RELATIVE


def tile_count_for_lonlat_bounds(bounds_lonlat, zoom):
    left, bottom, right, top = bounds_lonlat
    px0, py0 = latlon_to_global_px(top, left, zoom)
    px1, py1 = latlon_to_global_px(bottom, right, zoom)
    min_px = min(px0, px1)
    max_px = max(px0, px1)
    min_py = min(py0, py1)
    max_py = max(py0, py1)
    n = 2**zoom
    tx0 = clamp_int(math.floor(min_px / 256.0), 0, n - 1)
    tx1 = clamp_int(math.floor((max_px - 1.0) / 256.0), 0, n - 1)
    ty0 = clamp_int(math.floor(min_py / 256.0), 0, n - 1)
    ty1 = clamp_int(math.floor((max_py - 1.0) / 256.0), 0, n - 1)
    return max(0, tx1 - tx0 + 1) * max(0, ty1 - ty0 + 1)


def choose_regional_preview_zoom(bounds_lonlat):
    for zoom in REGIONAL_DTM_PREVIEW_ZOOMS:
        if tile_count_for_lonlat_bounds(bounds_lonlat, zoom) <= 64:
            return zoom
    return REGIONAL_DTM_PREVIEW_ZOOMS[-1]


def raster_bounds_lonlat(path: Path):
    with rasterio.open(path) as src:
        bounds = src.bounds
        crs = src.crs
        if crs is None:
            raise RuntimeError("Regional raster CRS not available.")
        if crs.to_string() == "EPSG:4326":
            return (float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top))
        b = rasterio.warp.transform_bounds(crs, "EPSG:4326", bounds.left, bounds.bottom, bounds.right, bounds.top, densify_pts=21)
        return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))


def normalize_lonlat_bounds(bounds_lonlat):
    left, bottom, right, top = [float(v) for v in bounds_lonlat]
    left, right = sorted((left, right))
    bottom, top = sorted((bottom, top))
    return left, bottom, right, top


def create_regional_dtm_crop(root: Path, bounds_lonlat, max_recommended_cells=REGIONAL_DTM_MAX_RECOMMENDED_CELLS):
    src_path = regional_dtm_source_path(root)
    if not src_path.exists():
        raise RuntimeError(f"Regional raster not found: {src_path}")

    left, bottom, right, top = normalize_lonlat_bounds(bounds_lonlat)
    if right <= left or top <= bottom:
        raise RuntimeError("Invalid selected area.")

    with rasterio.open(src_path) as src:
        if src.crs is None:
            raise RuntimeError("Regional raster CRS not available.")
        src_bounds = src.bounds
        sel_bounds = rasterio.warp.transform_bounds("EPSG:4326", src.crs, left, bottom, right, top, densify_pts=21)
        sel_left = max(float(src_bounds.left), float(sel_bounds[0]))
        sel_bottom = max(float(src_bounds.bottom), float(sel_bounds[1]))
        sel_right = min(float(src_bounds.right), float(sel_bounds[2]))
        sel_top = min(float(src_bounds.top), float(sel_bounds[3]))
        if sel_right <= sel_left or sel_top <= sel_bottom:
            raise RuntimeError("The selected area does not intersect the DTM of the three regions.")

        raw_window = rasterio.windows.from_bounds(sel_left, sel_bottom, sel_right, sel_top, src.transform)
        col_off = max(0, int(math.floor(raw_window.col_off)))
        row_off = max(0, int(math.floor(raw_window.row_off)))
        col_max = min(src.width, int(math.ceil(raw_window.col_off + raw_window.width)))
        row_max = min(src.height, int(math.ceil(raw_window.row_off + raw_window.height)))
        width = col_max - col_off
        height = row_max - row_off
        if width < 2 or height < 2:
            raise RuntimeError("Selected area too small to generate a DTM.")

        cells = int(width) * int(height)
        if max_recommended_cells and cells > int(max_recommended_cells):
            raise RuntimeError(
                f"Area too large: {cells:,} cells. Select a smaller area "
                f"(recommended maximum {int(max_recommended_cells):,} celle)."
            )

        window = rasterio.windows.Window(col_off, row_off, width, height)
        data = src.read(1, window=window, out_dtype="float32")
        nodata_val = src.nodata if src.nodata is not None else -9999.0
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=height,
            width=width,
            transform=rasterio.windows.transform(window, src.transform),
            dtype=rasterio.float32,
            count=1,
            nodata=nodata_val,
            tiled=True,
            blockxsize=256,
            blockysize=256,
            compress="deflate",
            predictor=3,
            BIGTIFF="IF_SAFER",
        )

    out_dir = regional_dtm_output_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"regional_selection_{ts}_DTM.tif"
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data.astype(np.float32, copy=False), 1)

    meta_path = out_path.with_suffix(".json")
    meta = {
        "source": str(src_path),
        "output": str(out_path),
        "bounds_lonlat": [left, bottom, right, top],
        "width": int(width),
        "height": int(height),
        "cells": cells,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out_path, meta


def regional_dtm_map_html(bounds_lonlat, max_cells=REGIONAL_DTM_MAX_RECOMMENDED_CELLS):
    left, bottom, right, top = normalize_lonlat_bounds(bounds_lonlat)
    payload = {
        "bounds": [[bottom, left], [top, right]],
        "flatBounds": [left, bottom, right, top],
        "maxCells": int(max_cells),
    }
    cfg = json.dumps(payload)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AIrchGIS · DTM da mappa</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    #panel {{
      position: absolute;
      z-index: 1000;
      top: 14px;
      left: 58px;
      max-width: 520px;
      background: rgba(255, 255, 255, 0.94);
      color: #1f2933;
      border-radius: 8px;
      box-shadow: 0 8px 30px rgba(0,0,0,.22);
      padding: 12px 14px;
      line-height: 1.35;
    }}
    #panel h1 {{ font-size: 16px; margin: 0 0 6px; }}
    #panel p {{ margin: 0 0 8px; font-size: 13px; }}
    #status {{ font-size: 13px; margin-top: 8px; white-space: pre-line; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
    button {{
      border: 1px solid #b8c0cc;
      background: white;
      color: #111827;
      border-radius: 6px;
      padding: 8px 10px;
      cursor: pointer;
      font-weight: 600;
    }}
    button.primary {{ background: #155eef; color: white; border-color: #155eef; }}
    button:disabled {{ opacity: .55; cursor: default; }}
    .hint {{ color: #4b5563; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="panel">
    <h1>Generate DTM from map</h1>
    <p>Use the tools on the left to draw a rectangle. The DTM is clipped from the local data for Marche, Abruzzo and Umbria.</p>
    <p class="hint">Output: DTM GeoTIFF at the native 5 m x 5 m resolution, then loaded automatically into RVT.</p>
    <div class="actions">
      <button id="generate" class="primary" disabled>Generate DTM and load</button>
      <button id="clear" disabled>Clear rectangle</button>
      <button id="fit">Back to the 3 regions</button>
    </div>
    <div id="status">Draw a rectangle on the map.</div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
  <script>
    const CONFIG = {cfg};
    const dtmBounds = L.latLngBounds(CONFIG.bounds);
    const map = L.map('map', {{
      maxBounds: dtmBounds.pad(0.28),
      maxBoundsViscosity: 0.45,
      zoomControl: true
    }}).fitBounds(dtmBounds);

    const imagery = L.tileLayer(
      'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
      {{ maxZoom: 20, attribution: 'Imagery Esri' }}
    ).addTo(map);
    const osm = L.tileLayer(
      'https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
      {{ maxZoom: 20, attribution: 'OpenStreetMap' }}
    );
    L.control.layers({{ 'Satellite': imagery, 'OpenStreetMap': osm }}).addTo(map);

    L.rectangle(dtmBounds, {{
      color: '#10b981',
      weight: 2,
      fillOpacity: 0.02,
      interactive: false
    }}).addTo(map).bindTooltip('DTM coverage Marche, Abruzzo, Umbria');

    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    const drawControl = new L.Control.Draw({{
      draw: {{
        polyline: false,
        polygon: false,
        circle: false,
        marker: false,
        circlemarker: false,
        rectangle: {{
          shapeOptions: {{
            color: '#ffdf4d',
            weight: 3,
            fillColor: '#ffdf4d',
            fillOpacity: 0.12
          }}
        }}
      }},
      edit: {{
        featureGroup: drawnItems,
        remove: true
      }}
    }});
    map.addControl(drawControl);

    let activeLayer = null;
    const generateBtn = document.getElementById('generate');
    const clearBtn = document.getElementById('clear');
    const fitBtn = document.getElementById('fit');
    const statusEl = document.getElementById('status');

    function setStatus(text) {{
      statusEl.textContent = text;
    }}

    function selectedBounds() {{
      if (!activeLayer) return null;
      const b = activeLayer.getBounds();
      return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    }}

    function updateStatusFromLayer() {{
      const b = selectedBounds();
      if (!b) {{
        generateBtn.disabled = true;
        clearBtn.disabled = true;
        setStatus('Draw a rectangle on the map.');
        return;
      }}
      generateBtn.disabled = false;
      clearBtn.disabled = false;
      setStatus(
        'Selected area:\\n' +
        `lon ${{b[0].toFixed(6)}} - ${{b[2].toFixed(6)}}\\n` +
        `lat ${{b[1].toFixed(6)}} - ${{b[3].toFixed(6)}}`
      );
    }}

    map.on(L.Draw.Event.CREATED, function (event) {{
      drawnItems.clearLayers();
      activeLayer = event.layer;
      drawnItems.addLayer(activeLayer);
      updateStatusFromLayer();
    }});
    map.on(L.Draw.Event.EDITED, function () {{
      const layers = drawnItems.getLayers();
      activeLayer = layers.length ? layers[0] : null;
      updateStatusFromLayer();
    }});
    map.on(L.Draw.Event.DELETED, function () {{
      activeLayer = null;
      updateStatusFromLayer();
    }});

    clearBtn.addEventListener('click', () => {{
      drawnItems.clearLayers();
      activeLayer = null;
      updateStatusFromLayer();
    }});
    fitBtn.addEventListener('click', () => map.fitBounds(dtmBounds));

    generateBtn.addEventListener('click', async () => {{
      const b = selectedBounds();
      if (!b) return;
      generateBtn.disabled = true;
      setStatus('Generating DTM... you can leave this page open.');
      try {{
        const response = await fetch('/generate', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ bounds: b }})
        }});
        const data = await response.json();
        if (!response.ok || !data.ok) {{
          throw new Error(data.error || 'Generation failed.');
        }}
        setStatus(
          `DTM created and loaded into RVT.\\n${{data.file}}\\n` +
          `${{data.width}} x ${{data.height}} px, resolution 5 m.`
        );
      }} catch (err) {{
        setStatus('Error: ' + err.message);
        generateBtn.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""


class InputData:
    def __init__(self, root: Path):
        self.root = root
        self.loaded = False
        self.error = None

        self.dtm = None
        self.dsmf = None
        self.dsml = None
        self.ndsm = None
        self.diff = None

        self.res = None
        self.profile = None
        self.bounds = None
        self.crs = None
        self.area_geojson_path = None
        self.src_dtm_paths = []
        self.src_dsmf_paths = []
        self.src_dsml_paths = []
        self.src_dtm_path = None
        self.src_dsmf_path = None
        self.src_dsml_path = None
        self.src_original_dtm_paths = []
        self.src_original_dsmf_paths = []
        self.src_original_dsml_paths = []
        self.src_original_dtm_path = None
        self.src_original_dsmf_path = None
        self.src_original_dsml_path = None

    def _set_loaded_tile(self, tile, area_geojson_path, p_dtm, p_f, p_l, p_dtm_orig, p_f_orig, p_l_orig):
        self.dtm = tile.get("DTM")
        self.dsmf = tile.get("DSM_First")
        self.dsml = tile.get("DSM_Last")
        self.ndsm = tile.get("nDSM")
        self.diff = tile.get("First-Last")
        self.res = tile["res"]
        self.profile = tile["profile"]
        self.bounds = tile["bounds"]
        self.crs = tile["crs"]
        self.area_geojson_path = str(area_geojson_path) if area_geojson_path else None
        self.src_dtm_paths = [str(p) for p in p_dtm]
        self.src_dsmf_paths = [str(p) for p in p_f]
        self.src_dsml_paths = [str(p) for p in p_l]
        self.src_dtm_path = self.src_dtm_paths[0] if self.src_dtm_paths else None
        self.src_dsmf_path = self.src_dsmf_paths[0] if self.src_dsmf_paths else None
        self.src_dsml_path = self.src_dsml_paths[0] if self.src_dsml_paths else None
        self.src_original_dtm_paths = [str(p) for p in p_dtm_orig]
        self.src_original_dsmf_paths = [str(p) for p in p_f_orig]
        self.src_original_dsml_paths = [str(p) for p in p_l_orig]
        self.src_original_dtm_path = self.src_original_dtm_paths[0] if self.src_original_dtm_paths else None
        self.src_original_dsmf_path = self.src_original_dsmf_paths[0] if self.src_original_dsmf_paths else None
        self.src_original_dsml_path = self.src_original_dsml_paths[0] if self.src_original_dsml_paths else None
        self.loaded = True
        self.error = None

    def _resolve_preprocessed_paths(self, paths, use_preprocessed=False, preprocessed_suffix="_prep1"):
        original = [Path(p) for p in paths if p]
        if not use_preprocessed:
            return original, original
        resolved = []
        for p in original:
            is_fresh, candidate = has_fresh_preprocessed(self.root, p, suffix=preprocessed_suffix)
            resolved.append(candidate if is_fresh else p)
        return resolved, original

    def load(self, place_name=None, use_preprocessed=False, preprocessed_suffix="_prep1"):
        if place_name:
            db_root = get_database_root(self.root)
            if db_root is None:
                self.loaded = False
                self.error = "Database folder not found (expected: ./Database or ./image/Database)."
                return
            base = db_root / place_name
            prepare_inputs_place(base)
            p_dtm_orig = select_rasters(base / "DTM", prefer_preprocessed=False)
            p_f_orig = select_rasters_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=False)
            p_l_orig = select_rasters_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=False)
            p_dtm, _ = self._resolve_preprocessed_paths(p_dtm_orig, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
            p_f, _ = self._resolve_preprocessed_paths(p_f_orig, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
            p_l, _ = self._resolve_preprocessed_paths(p_l_orig, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
            area_geojson_path = find_place_geojson(base)
        else:
            prepare_inputs(self.root)
            base = self.root / "image"
            p_dtm_orig = select_rasters(base / "DTM", prefer_preprocessed=False)
            p_f_orig = select_rasters_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=False)
            p_l_orig = select_rasters_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=False)
            p_dtm, _ = self._resolve_preprocessed_paths(p_dtm_orig, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
            p_f, _ = self._resolve_preprocessed_paths(p_f_orig, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
            p_l, _ = self._resolve_preprocessed_paths(p_l_orig, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
            area_geojson_path = None

        if not p_dtm:
            self.loaded = False
            if place_name:
                self.error = f"Missing inputs in Database/{place_name}: at least one raster is needed in the DTM folder."
            else:
                self.error = "Missing inputs: put at least one raster or zip in image/DTM."
            return

        dtm, res, prof, _, bounds, crs = load_raster_source(p_dtm)
        dsmf = None
        dsml = None
        if p_f:
            dsmf, _, _, _, _, _ = load_raster_source(p_f)
        if p_l:
            dsml, _, _, _, _, _ = load_raster_source(p_l)
        tile = {
            "DTM": dtm,
            "DSM_First": dsmf,
            "DSM_Last": dsml,
            "nDSM": (dsmf - dtm) if dsmf is not None else None,
            "First-Last": (dsmf - dsml) if dsmf is not None and dsml is not None else None,
            "res": res,
            "profile": prof,
            "bounds": bounds,
            "crs": crs,
        }
        if area_geojson_path:
            tile = clip_tile_to_geojson(tile, Path(area_geojson_path).expanduser().resolve())

        self._set_loaded_tile(tile, area_geojson_path, p_dtm, p_f, p_l, p_dtm_orig, p_f_orig, p_l_orig)

    def load_from_paths(self, dtm_paths, dsmf_paths, dsml_paths, use_preprocessed=False, preprocessed_suffix="_prep1"):
        p_dtm, p_dtm_orig = self._resolve_preprocessed_paths(dtm_paths, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
        p_f, p_f_orig = self._resolve_preprocessed_paths(dsmf_paths, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)
        p_l, p_l_orig = self._resolve_preprocessed_paths(dsml_paths, use_preprocessed=use_preprocessed, preprocessed_suffix=preprocessed_suffix)

        if not p_dtm:
            self.loaded = False
            self.error = "Incomplete drag-and-drop inputs: at least one DTM is needed."
            return

        dtm, res, prof, _, bounds, crs = load_raster_source(p_dtm)
        dsmf = None
        dsml = None
        if p_f:
            dsmf, _, _, _, _, _ = load_raster_source(p_f)
        if p_l:
            dsml, _, _, _, _, _ = load_raster_source(p_l)
        tile = {
            "DTM": dtm,
            "DSM_First": dsmf,
            "DSM_Last": dsml,
            "nDSM": (dsmf - dtm) if dsmf is not None else None,
            "First-Last": (dsmf - dsml) if dsmf is not None and dsml is not None else None,
            "res": res,
            "profile": prof,
            "bounds": bounds,
            "crs": crs,
        }
        self._set_loaded_tile(tile, None, p_dtm, p_f, p_l, p_dtm_orig, p_f_orig, p_l_orig)


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("AIrchGIS · LiDAR Explorer")
        self.geometry("1600x920")
        self.minsize(1320, 820)

        self.root_path = Path(__file__).resolve().parent
        self.data = InputData(self.root_path)
        self.basemap_cache = BasemapCache(max_items=6)
        self.place_name = tk.StringVar(value="")
        self.active_source_mode = "database"
        self.drop_sources = {"DTM": [], "DSM_First": [], "DSM_Last": []}
        self.drop_cache_root = self.root_path / ".dragdrop_cache"
        self.drop_status_var = tk.StringVar(value="")

        self.dataset = tk.StringVar(value="DTM")
        self.method = tk.StringVar(value="Hillshade")

        self.azimuth = tk.DoubleVar(value=315.0)
        self.altitude = tk.DoubleVar(value=45.0)
        self.z_factor = tk.DoubleVar(value=1.0)
        self.radius = tk.DoubleVar(value=10.0)
        self.n_dir = tk.IntVar(value=16)

        self.p_low = tk.DoubleVar(value=2.0)
        self.p_high = tk.DoubleVar(value=98.0)
        self.invert = tk.BooleanVar(value=False)

        self.basemap_on = tk.BooleanVar(value=False)
        self.basemap_mix = tk.DoubleVar(value=0.35)
        self.basemap_year = tk.StringVar(value="")
        self.base_image_mode = tk.StringVar(value="PrePro 1")
        self.prepro_profile = tk.StringVar(value="prep1")
        self.wayback_layers = []
        self.basemap_year_values_cache = {}

        self.param_widgets = {}
        self.dataset_widgets = {}

        self._update_job = None
        self._pan_state = None
        self._brush_state = None
        self._home_limits = None
        self._last_shape = None
        self.annotation_alpha = None
        self.annotation_rgb = None
        self.im_anno = None
        self.measure_points = []
        self.measure_armed = False
        self.im_measure = None

        self.brush_on = tk.BooleanVar(value=False)
        self.brush_size = tk.IntVar(value=5)
        self.brush_color = tk.StringVar(value="Giallo")
        self.lads_enabled = tk.BooleanVar(value=False)
        self.lads_button_text = tk.StringVar(value="☁️ 3D Cloud")
        self.pick_coords_armed = False
        self.report_pick_pending = None
        self.report_items = []
        self.lads_window = None
        self.lads_canvas = None
        self.lads_axes = None
        self.lads_home_limits = None
        self.lads_fullscreen = False
        self.lads_windowed_geometry = ""
        self.report_window = None
        self.lads_info_var = tk.StringVar(value="")
        self.report_name_var = tk.StringVar(value="")
        self.report_status_var = tk.StringVar(value="No points in the report.")
        self.report_list_var = tk.StringVar(value=[])
        self.report_notes_text = None
        self.report_listbox = None
        self._satellite_loading_keys = set()
        self._satellite_loading_lock = threading.Lock()
        self.drop_target_label = None
        self.cloud_http_server = None
        self.cloud_http_port = None
        self.cloud_http_root = None
        self.regional_dtm_map_server = None
        self._prepro_cache_thread = None
        self._prepro_cache_started = False

        self._build_ui()
        self._refresh_drop_status()
        self.refresh_basemap_years()
        self.refresh_places()
        try:
            self.reload_inputs()
        except Exception as e:
            self.status.set(f"Initial loading error: {e}")
            self._show_blank()

    def open_mase(self):
        url = MASE_URL
        try:
            subprocess.Popen(["open", "-a", "Google Chrome", url])
            return
        except Exception:
            pass
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def open_ge(self):
        url = GE_URL
        try:
            subprocess.Popen(["open", "-a", "Google Chrome", url])
            return
        except Exception:
            pass
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def open_regional_dtm_selector(self):
        src_path = regional_dtm_source_path(self.root_path)
        if not src_path.exists():
            messagebox.showerror("DTM from map", f"Regional raster not found:\n{src_path}")
            return

        try:
            bounds_ll = raster_bounds_lonlat(src_path)
        except Exception as e:
            messagebox.showerror("DTM from map", str(e))
            return

        app = self
        html = regional_dtm_map_html(bounds_ll)

        class RegionalMapHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send_bytes(self, body, content_type="text/html; charset=utf-8", status=200):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8", status=status)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self._send_bytes(html.encode("utf-8"))
                    return
                self.send_error(404)

            def do_POST(self):
                if self.path != "/generate":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    bounds = payload.get("bounds")
                    if not isinstance(bounds, list) or len(bounds) != 4:
                        raise RuntimeError("Invalid bounds.")
                    out_path, meta = create_regional_dtm_crop(app.root_path, bounds)

                    def load_generated():
                        app.drop_sources = {"DTM": [str(out_path)], "DSM_First": [], "DSM_Last": []}
                        app.active_source_mode = "drop"
                        app.base_image_mode.set("Original")
                        app.load_dropped_inputs()
                        app.status.set(
                            f"DTM generated and loaded: {out_path.name} "
                            f"({meta['width']} x {meta['height']} px, 5 m)"
                        )

                    app.after(0, load_generated)
                    self._send_json(
                        {
                            "ok": True,
                            "file": out_path.name,
                            "path": str(out_path),
                            "width": meta["width"],
                            "height": meta["height"],
                            "cells": meta["cells"],
                        }
                    )
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, status=400)

        if self.regional_dtm_map_server is not None:
            try:
                self.regional_dtm_map_server.shutdown()
                self.regional_dtm_map_server.server_close()
            except Exception:
                pass
            self.regional_dtm_map_server = None

        server = ThreadingHTTPServer(("127.0.0.1", 0), RegionalMapHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.regional_dtm_map_server = server
        url = f"http://127.0.0.1:{int(server.server_address[1])}/"
        self.status.set(f"DTM from map opened in the browser: {url}")
        try:
            subprocess.Popen(["open", "-a", "Google Chrome", url])
        except Exception:
            webbrowser.open(url)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self, padding=0)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=0, minsize=430)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, padding=(8, 8, 6, 8))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(main, padding=(0, 6, 6, 6))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)

        right_top = ttk.Frame(right, padding=(8, 8, 8, 0))
        right_top.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(right_top, text="Brush", variable=self.brush_on, command=self._on_brush_toggle).grid(row=0, column=0, sticky="w")
        ttk.Label(right_top, text="Colour").grid(row=0, column=1, sticky="w", padx=(8, 2))
        self.brush_color_combo = ttk.Combobox(
            right_top,
            textvariable=self.brush_color,
            values=["Giallo", "Rosso", "Verde", "Ciano"],
            state="readonly",
            width=8,
        )
        self.brush_color_combo.grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Label(right_top, text="Dim").grid(row=0, column=3, sticky="w", padx=(0, 2))
        self.brush_size_scale = ttk.Scale(right_top, from_=1, to=20, command=lambda v: self.brush_size.set(int(round(float(v)))))
        self.brush_size_scale.grid(row=0, column=4, sticky="w", padx=(0, 20))
        self.brush_size_scale.set(self.brush_size.get())
        right_top.columnconfigure(5, weight=1)
        ttk.Button(right_top, text="📍", width=2, command=self.arm_coordinate_pick).grid(row=0, column=6, sticky="e", padx=(0, 4))
        ttk.Button(right_top, text="📏", width=2, command=self.arm_measure_tool).grid(row=0, column=7, sticky="e", padx=(0, 4))
        ttk.Button(right_top, text="🗑", width=2, command=self.clear_annotations).grid(row=0, column=8, sticky="e", padx=(0, 8))
        ttk.Button(right_top, text="🧩 Method grid", command=self.show_methods_grid).grid(row=0, column=9, sticky="e")
        ttk.Button(right_top, textvariable=self.lads_button_text, command=self.show_3d_cloud_viewer).grid(row=0, column=10, sticky="e", padx=(8, 0))

        top = ttk.Frame(left)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)
        tools_row = ttk.Frame(top)
        tools_row.grid(row=0, column=0, sticky="ew")
        for i in range(4):
            tools_row.columnconfigure(i, weight=1)
        ttk.Button(tools_row, text="🛰️ MASE", command=self.open_mase).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(tools_row, text="🌍 GE", command=self.open_ge).grid(row=0, column=1, sticky="ew", padx=(4, 4))
        ttk.Button(tools_row, text="🏛️ Preset Arch", command=self.apply_archaeology_preset).grid(row=0, column=2, sticky="ew", padx=(4, 4))
        ttk.Button(tools_row, text="⬛ Preset Rect/Ditches", command=self.apply_rectangles_preset).grid(row=0, column=3, sticky="ew", padx=(4, 0))
        quick_box = ttk.LabelFrame(top, text="Quick session", padding=6)
        quick_box.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        quick_box.columnconfigure(0, weight=1)
        self.drop_target_label = ttk.Label(
            quick_box,
            textvariable=self.drop_status_var,
            anchor="w",
            justify="left",
            wraplength=380,
            relief="solid",
            padding=(10, 10),
        )
        self.drop_target_label.grid(row=0, column=0, sticky="ew")
        quick_actions = ttk.Frame(quick_box)
        quick_actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        quick_actions.columnconfigure(0, weight=1)
        quick_actions.columnconfigure(1, weight=1)
        quick_actions.columnconfigure(2, weight=1)
        ttk.Button(quick_actions, text="Use selected place", command=self.use_database_selection).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(quick_actions, text="DTM from map", command=self.open_regional_dtm_selector).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(quick_actions, text="Clear session", command=self.clear_drop_inputs).grid(row=0, column=2, sticky="ew", padx=(4, 0))
        self._register_drop_widget(quick_box)
        self._register_drop_widget(self.drop_target_label)

        place_box = ttk.Frame(left)
        place_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        place_box.columnconfigure(1, weight=1)
        ttk.Label(place_box, text="Place").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.place_combo = ttk.Combobox(place_box, textvariable=self.place_name, values=[], state="readonly")
        self.place_combo.grid(row=0, column=1, sticky="ew")
        self.place_combo.bind("<<ComboboxSelected>>", self.on_place_selected)

        ds_box = ttk.LabelFrame(left, text="", padding=8)
        ds_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ds_box.columnconfigure(0, weight=1)
        ds_box.columnconfigure(1, weight=1)
        datasets = ["DTM", "DSM_First", "DSM_Last", "nDSM", "First-Last"]
        for i, name in enumerate(datasets):
            r = i // 2
            c = i % 2
            rb = ttk.Radiobutton(
                ds_box,
                text=name,
                value=name,
                variable=self.dataset,
                command=lambda: (self.update_param_states(), self.schedule_update()),
            )
            rb.grid(row=r, column=c, sticky="w", padx=(0, 12), pady=(0, 2))
            self.dataset_widgets[name] = rb
        original_row = 2
        original_frame = ttk.Frame(ds_box)
        original_frame.grid(row=original_row, column=1, sticky="ew")
        original_rb = ttk.Radiobutton(
            original_frame,
            text="Original",
            value="Original",
            variable=self.dataset,
            command=lambda: (self.update_param_states(), self.schedule_update()),
        )
        original_rb.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 2))
        self.dataset_widgets["Original"] = original_rb
        self.basemap_year_combo = ttk.Combobox(
            original_frame,
            textvariable=self.basemap_year,
            values=[],
            state="readonly",
            width=8,
        )
        self.basemap_year_combo.grid(row=0, column=1, sticky="w", pady=(0, 2))
        self.basemap_year_combo.bind("<<ComboboxSelected>>", lambda _e: self.schedule_update())

        basemap_row = ttk.Frame(ds_box)
        basemap_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        basemap_row.columnconfigure(1, weight=1)

        self.basemap_cb = ttk.Checkbutton(basemap_row, text="Basemap", variable=self.basemap_on, command=lambda: (self.update_param_states(), self.schedule_update()))
        self.basemap_cb.grid(row=0, column=0, sticky="w")

        self.basemap_scale = ttk.Scale(basemap_row, from_=0.0, to=1.0, command=lambda v: self._set_float(self.basemap_mix, v))
        self.basemap_scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.basemap_mix_lbl = ttk.Label(basemap_row, text="")
        self.basemap_mix_lbl.grid(row=0, column=2, sticky="e")

        def sync_mix(*_):
            self.basemap_mix_lbl.config(text=f"{float(self.basemap_mix.get()):.2f}")

        self.basemap_mix.trace_add("write", sync_mix)
        sync_mix()
        self.basemap_scale.set(float(self.basemap_mix.get()))

        meth_box = ttk.LabelFrame(left, text="RVT method", padding=8)
        meth_box.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        meth_box.columnconfigure(0, weight=1)
        self.method_combo = ttk.Combobox(meth_box, textvariable=self.method, values=self.available_methods(), state="readonly")
        self.method_combo.grid(row=0, column=0, sticky="ew")
        self.method_combo.bind("<<ComboboxSelected>>", lambda e: (self.update_param_states(), self.schedule_update()))

        par_box = ttk.LabelFrame(left, text="Parameters", padding=8)
        par_box.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        par_box.columnconfigure(0, weight=1)

        self._add_slider(par_box, "Azimuth", "azimuth", self.azimuth, 0.0, 360.0, 0)
        self._add_slider(par_box, "Altitude", "altitude", self.altitude, 0.0, 90.0, 1)
        self._add_slider(par_box, "Z-factor", "z_factor", self.z_factor, 0.1, 10.0, 2)
        self._add_slider(par_box, "Radius", "radius", self.radius, 1.0, 200.0, 3)
        self._add_slider(par_box, "Directions", "n_dir", self.n_dir, 4, 64, 4, is_int=True)
        self._add_slider(par_box, "Stretch low (p)", "p_low", self.p_low, 0.0, 20.0, 5)
        self._add_slider(par_box, "Stretch high (p)", "p_high", self.p_high, 80.0, 100.0, 6)

        self.invert_cb = ttk.Checkbutton(par_box, text="Invert", variable=self.invert, command=self.schedule_update)
        self.invert_cb.grid(row=7, column=0, sticky="w", pady=(6, 0))

        btn_box = ttk.Frame(left)
        btn_box.grid(row=5, column=0, sticky="ew")
        btn_box.columnconfigure(0, weight=1)
        btn_box.columnconfigure(1, weight=1)
        btn_box.columnconfigure(2, weight=1)
        btn_box.columnconfigure(3, weight=1)
        ttk.Button(btn_box, text="Export .TIFF", command=self.export_current).grid(row=0, column=0, sticky="ew", pady=(0, 6), padx=(0, 4))
        ttk.Button(btn_box, text="Export .PNG", command=self.export_current_view_hq).grid(row=0, column=1, sticky="ew", pady=(0, 6), padx=(4, 4))
        ttk.Label(btn_box, text="AI").grid(row=0, column=2, sticky="e", padx=(4, 4))
        self.base_mode_combo = ttk.Combobox(btn_box, textvariable=self.base_image_mode, values=BASE_IMAGE_OPTIONS, state="readonly")
        self.base_mode_combo.grid(row=0, column=3, sticky="ew", pady=(0, 6))
        self.base_mode_combo.bind("<<ComboboxSelected>>", self.on_base_image_mode_change)
        ttk.Button(left, text="Create exploration report", command=self.open_report_window).grid(row=6, column=0, sticky="ew", pady=(0, 6))
        self.status = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.status, wraplength=390).grid(row=7, column=0, sticky="ew", pady=(8, 0))

        fig = Figure(figsize=(6, 5), dpi=150)
        fig.patch.set_facecolor("black")
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        self.ax = fig.add_subplot(111)
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")

        self.im_base = None
        self.im_over = None

        self.canvas = FigureCanvasTkAgg(fig, master=right)
        w = self.canvas.get_tk_widget()
        w.grid(row=1, column=0, sticky="nsew")
        w.configure(borderwidth=0, highlightthickness=0)
        try:
            w.configure(padx=0, pady=0)
        except Exception:
            pass
        self._connect_mouse()

    def available_methods(self):
        methods = ["Raw"]
        if hasattr(rvt.vis, "hillshade"):
            methods.append("Hillshade")
        if hasattr(rvt.vis, "multi_hillshade"):
            methods.append("Multi-Hillshade")
        if hasattr(rvt.vis, "slope") or hasattr(rvt.vis, "slope_aspect"):
            methods.append("Slope")
        if hasattr(rvt.vis, "sky_view_factor"):
            methods.append("Sky-View Factor")
            methods.append("Anisotropic Sky-View Factor")
            methods.append("Positive Openness")
        if hasattr(rvt.vis, "slrm") or hasattr(rvt.vis, "local_relief_model"):
            methods.append("Simple Local Relief Model")
        if hasattr(rvt.vis, "msrm"):
            methods.append("Multi-Scale Relief Model")
        if hasattr(rvt.vis, "mstp"):
            methods.append("Multi-Scale Topographic Position")
        if hasattr(rvt.vis, "sky_illumination"):
            methods.append("Sky Illumination")
        if hasattr(rvt.vis, "local_dominance"):
            methods.append("Local Dominance")
        if hasattr(rvt.blend, "e3mstp"):
            methods.append("e3MSTP (RGB)")
        return methods

    def available_basemap_years(self):
        years = []
        seen = set()
        for item in self.wayback_layers:
            y = item.get("year")
            if y and y not in seen:
                years.append(y)
                seen.add(y)
        return years

    def _preview_signature(self, bounds_ll, tile_template):
        img = build_satellite_rgb(bounds_ll, 12, tile_template=tile_template)
        if img is None:
            return None
        arr = np.asarray(img.resize((96, 96), resample=Image.BILINEAR), dtype=np.float32) / 255.0
        return arr

    def _filtered_basemap_years_for_bounds(self, bounds_ll):
        if bounds_ll is None:
            return self.available_basemap_years()
        key = tuple(round(float(v), 5) for v in bounds_ll)
        cached = self.basemap_year_values_cache.get(key)
        if cached:
            return cached

        values = []
        previous_sig = None
        year_to_template = {}
        for item in self.wayback_layers:
            year = item.get("year")
            if year and year not in year_to_template:
                year_to_template[year] = item.get("template", ARCGIS_CURRENT_TILE_TEMPLATE)

        for year in sorted(year_to_template.keys(), reverse=True):
            sig = self._preview_signature(bounds_ll, year_to_template[year])
            if sig is None:
                continue
            if previous_sig is not None:
                diff = float(np.mean(np.abs(sig - previous_sig)))
                if diff < 0.01:
                    continue
            values.append(year)
            previous_sig = sig

        self.basemap_year_values_cache[key] = values
        return values

    def refresh_basemap_years(self):
        if not self.wayback_layers:
            self.wayback_layers = load_wayback_layers()
        bounds_ll = self._bounds_lonlat() if getattr(self, "data", None) and self.data.loaded else None
        values = self._filtered_basemap_years_for_bounds(bounds_ll)
        self.basemap_year_combo["values"] = values
        if self.basemap_year.get() not in values:
            self.basemap_year.set(values[0] if values else "")

    def _satellite_template_for_year(self):
        year = self.basemap_year.get()
        for item in self.wayback_layers:
            if item.get("year") == year:
                return item.get("template", ARCGIS_CURRENT_TILE_TEMPLATE)
        return ARCGIS_CURRENT_TILE_TEMPLATE

    def _add_slider(self, parent, label, key, var, vmin, vmax, row, is_int=False):
        frm = ttk.Frame(parent)
        frm.grid(row=row, column=0, sticky="ew", pady=2)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text=label).grid(row=0, column=0, sticky="w")

        if is_int:
            scale = ttk.Scale(frm, from_=vmin, to=vmax, command=lambda v: self._set_int(var, v))
        else:
            scale = ttk.Scale(frm, from_=vmin, to=vmax, command=lambda v: self._set_float(var, v))

        scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.param_widgets[key] = scale

        val_lbl = ttk.Label(frm, text="")
        val_lbl.grid(row=0, column=2, sticky="e")

        def sync_label(*_):
            val = var.get()
            val_lbl.config(text=str(int(val)) if is_int else f"{float(val):.2f}")

        var.trace_add("write", sync_label)
        sync_label()
        scale.set(int(var.get()) if is_int else float(var.get()))

    def _set_int(self, var, v):
        try:
            var.set(int(round(float(v))))
        except Exception:
            pass
        self.schedule_update()

    def _set_float(self, var, v):
        try:
            var.set(float(v))
        except Exception:
            pass
        self.schedule_update()

    def apply_archaeology_preset(self):
        methods = self.available_methods()
        preferred = ["Hillshade", "Simple Local Relief Model", "Sky-View Factor", "Multi-Hillshade"]
        chosen = None
        for m in preferred:
            if m in methods:
                chosen = m
                break
        if chosen is None and methods:
            chosen = methods[0]

        self.dataset.set("DTM")
        if chosen is not None:
            self.method.set(chosen)
        self.basemap_on.set(False)
        self.invert.set(False)

        self.azimuth.set(315.0)
        self.altitude.set(24.0)
        self.z_factor.set(1.8)
        self.radius.set(20.0)
        self.n_dir.set(32)
        self.p_low.set(0.8)
        self.p_high.set(99.5)

        self.update_param_states()
        self.schedule_update()
        self.status.set("Archaeology preset applied (DTM + high contrast).")

    def apply_rectangles_preset(self):
        methods = self.available_methods()
        preferred = [
            "Sky-View Factor",
            "Anisotropic Sky-View Factor",
            "Simple Local Relief Model",
            "Hillshade",
            "Multi-Hillshade",
        ]
        chosen = None
        for m in preferred:
            if m in methods:
                chosen = m
                break
        if chosen is None and methods:
            chosen = methods[0]

        self.dataset.set("DTM")
        if chosen is not None:
            self.method.set(chosen)
        self.basemap_on.set(False)
        self.invert.set(False)

        self.azimuth.set(330.0)
        self.altitude.set(18.0)
        self.z_factor.set(2.2)
        self.radius.set(24.0)
        self.n_dir.set(32)
        self.p_low.set(0.2)
        self.p_high.set(99.8)

        self.update_param_states()
        self.schedule_update()
        self.status.set("Rectangles/ditches preset applied (DTM + microrelief boost).")

    def _is_preprocessed_path(self, path):
        return Path(path).stem.lower().endswith(PREPROCESSED_SUFFIXES)

    def _dedupe_paths(self, paths):
        out = []
        seen = set()
        for item in paths:
            p = Path(item).expanduser()
            try:
                p = p.resolve()
            except Exception:
                p = p.absolute()
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _drop_session_ready(self):
        return bool(self.drop_sources.get("DTM"))

    def _drop_session_label(self):
        dtm_paths = self.drop_sources.get("DTM") or []
        if not dtm_paths:
            return "sessione_rapida"
        stem = Path(dtm_paths[0]).stem
        for suffix in ("_DTM", "_dtm", "_prep1", "_prep2", "_prep3", "_prep"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        if len(dtm_paths) > 1:
            stem = f"{stem}_mosaic"
        return stem or "sessione_rapida"

    def _current_place_label(self):
        if self.active_source_mode == "drop" and self._drop_session_ready():
            return self._drop_session_label()
        return self.place_name.get() or "report"

    def _refresh_drop_status(self):
        counts = [
            f"DTM: {len(self.drop_sources['DTM'])}",
            f"DSM First: {len(self.drop_sources['DSM_First'])}",
            f"DSM Last: {len(self.drop_sources['DSM_Last'])}",
        ]
        if not TKDND_AVAILABLE:
            self.drop_status_var.set(
                "Drag and drop not available. Install `tkinterdnd2`. "
                + " | ".join(counts)
            )
            return
        header = "Drop rasters, folders or zip files here."
        if self._drop_session_ready():
            mode_txt = "Quick session ready."
            if self.active_source_mode == "drop" and self.data.loaded:
                mode_txt = "Quick session active."
            self.drop_status_var.set(f"{mode_txt} {header} {' | '.join(counts)}")
            return
        missing = []
        if not self.drop_sources["DTM"]:
            missing.append("DTM")
        if not self.drop_sources["DSM_First"]:
            missing.append("DSM First")
        if not self.drop_sources["DSM_Last"]:
            missing.append("DSM Last")
        missing_txt = ", ".join(missing) if missing else "-"
        self.drop_status_var.set(f"{header} Mancano: {missing_txt}. {' | '.join(counts)}")

    def _register_drop_widget(self, widget):
        if not TKDND_AVAILABLE or DND_FILES is None or widget is None:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop_files)
        except Exception:
            pass

    def _normalize_drop_token(self, token):
        token = (token or "").strip()
        if not token:
            return None
        if token.startswith("{") and token.endswith("}"):
            token = token[1:-1]
        if token.startswith("file://"):
            parsed = urlparse(token)
            token = unquote(parsed.path or "")
            if parsed.netloc and not token.startswith("/"):
                token = f"/{token}"
        token = unquote(token)
        if not token:
            return None
        path = Path(token).expanduser()
        try:
            return path.resolve()
        except Exception:
            return path.absolute()

    def _extract_drop_zip(self, zip_path):
        zip_path = Path(zip_path).expanduser().resolve()
        stat = zip_path.stat()
        stamp = f"{zip_path}::{stat.st_size}::{stat.st_mtime_ns}"
        digest = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16]
        dest = self.drop_cache_root / "extracted" / f"{zip_path.stem}_{digest}"
        marker = dest / ".unzipped"
        if marker.exists():
            try:
                if marker.read_text(encoding="utf-8").strip() == stamp:
                    return dest
            except Exception:
                pass
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zz:
            zz.extractall(dest)
        marker.write_text(stamp, encoding="utf-8")
        return dest

    def _classify_dataset_from_path(self, path):
        p = Path(path)
        full = p.as_posix().lower()
        parts = {part.lower() for part in p.parts}
        compact = "".join(ch for ch in p.stem.lower() if ch.isalnum())

        if parts & {"dsm_first", "dsm_fisrt", "dsmfirst"}:
            return "DSM_First"
        if parts & {"dsm_last", "dsmlast"}:
            return "DSM_Last"
        if "dtm" in parts:
            return "DTM"

        if any(marker in full for marker in ("dsm_first", "dsm-first", "dsm first", "dsm_fisrt", "dsm-fisrt", "dsm fisrt")):
            return "DSM_First"
        if any(marker in full for marker in ("dsm_last", "dsm-last", "dsm last")):
            return "DSM_Last"
        if "/dtm/" in full or full.endswith("_dtm") or "_dtm." in full:
            return "DTM"

        if compact.endswith("dsmfirst") or compact.endswith("dsmfisrt"):
            return "DSM_First"
        if compact.endswith("dsmlast"):
            return "DSM_Last"
        if compact.endswith("dtm"):
            return "DTM"
        return None

    def _group_drop_rasters(self, rasters):
        grouped = {"DTM": [], "DSM_First": [], "DSM_Last": []}
        for raster in rasters:
            ds_name = self._classify_dataset_from_path(raster)
            if ds_name is None:
                continue
            grouped[ds_name].append(Path(raster))
        for name, items in grouped.items():
            if not items:
                continue
            raw = [p for p in items if not self._is_preprocessed_path(p)]
            chosen = raw or items
            grouped[name] = [Path(p).expanduser().resolve() for p in chosen]
        return grouped

    def _scan_drop_entry(self, path):
        path = Path(path).expanduser().resolve()
        if path.is_dir():
            return self._group_drop_rasters(list_rasters(path))
        if path.is_file() and path.suffix.lower() == ".zip":
            extracted = self._extract_drop_zip(path)
            return self._scan_drop_entry(extracted)
        if path.is_file() and path.suffix.lower() in EXTS:
            grouped = {"DTM": [], "DSM_First": [], "DSM_Last": []}
            ds_name = self._classify_dataset_from_path(path)
            if ds_name is not None:
                grouped[ds_name].append(path)
            return grouped
        return {"DTM": [], "DSM_First": [], "DSM_Last": []}

    def on_drop_files(self, event):
        try:
            tokens = list(self.tk.splitlist(event.data))
        except Exception:
            tokens = [event.data]

        incoming = {"DTM": [], "DSM_First": [], "DSM_Last": []}
        for token in tokens:
            path = self._normalize_drop_token(token)
            if path is None or not path.exists():
                continue
            grouped = self._scan_drop_entry(path)
            for name, items in grouped.items():
                incoming[name].extend(items)

        if not any(incoming.values()):
            self.status.set("Drag and drop: no DTM / DSM First / DSM Last recognised.")
            return

        for name, items in incoming.items():
            if not items:
                continue
            self.drop_sources[name] = self._dedupe_paths([str(p) for p in items])

        self._refresh_drop_status()
        if self._drop_session_ready():
            self.active_source_mode = "drop"
            self.reload_inputs()
        else:
            missing = []
            if not self.drop_sources["DTM"]:
                missing.append("DTM")
            if not self.drop_sources["DSM_First"]:
                missing.append("DSM First")
            if not self.drop_sources["DSM_Last"]:
                missing.append("DSM Last")
            self.status.set(f"Quick session updated. Missing: {', '.join(missing)}.")

    def clear_drop_inputs(self):
        self.drop_sources = {"DTM": [], "DSM_First": [], "DSM_Last": []}
        if self.drop_cache_root.exists():
            shutil.rmtree(self.drop_cache_root, ignore_errors=True)
        self._refresh_drop_status()
        if self.active_source_mode == "drop":
            self.active_source_mode = "database"
            self.reload_inputs()
        else:
            self.status.set("Quick session cleared.")

    def use_database_selection(self):
        self.active_source_mode = "database"
        self.reload_inputs()

    def on_place_selected(self, _evt=None):
        self.active_source_mode = "database"
        self.reload_inputs()

    def refresh_places(self):
        places = list_database_places(self.root_path)
        values = places
        current = self.place_name.get()
        self.place_combo["values"] = values
        if values and current in values:
            self.place_name.set(current)
        elif values:
            self.place_name.set(values[0])
        else:
            self.place_name.set("")

    def _warm_database_prepro_cache(self):
        db_root = get_database_root(self.root_path)
        if db_root is None:
            return
        for place in list_database_places(self.root_path):
            try:
                base = db_root / place
                prepare_inputs_place(base)
                src_groups = [
                    select_rasters(base / "DTM", prefer_preprocessed=False),
                    select_rasters_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=False),
                    select_rasters_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=False),
                ]
                if not any(src_groups):
                    continue
                for profile in PREPRO_PROFILES.values():
                    self._ensure_preprocessed_groups(src_groups, profile)
            except Exception:
                continue

    def _start_database_prepro_cache(self):
        if self._prepro_cache_started:
            return
        self._prepro_cache_started = True
        self._prepro_cache_thread = threading.Thread(target=self._warm_database_prepro_cache, daemon=True)
        self._prepro_cache_thread.start()

    def load_database_inputs(self):
        self._refresh_drop_status()
        self.refresh_places()
        selected = self.place_name.get()
        if not selected:
            if self.lads_enabled.get():
                self._close_lads_window()
            self.status.set("No place found in Database.")
            self._show_blank()
            return
        place = selected
        mode = self.base_image_mode.get()
        profile_key = BASE_IMAGE_TO_PROFILE.get(mode)
        use_preprocessed = profile_key is not None
        if profile_key:
            self.prepro_profile.set(profile_key)
        profile = PREPRO_PROFILES.get(self.prepro_profile.get(), PREPRO_PROFILES["prep1"])
        if use_preprocessed:
            try:
                db_root = get_database_root(self.root_path)
                if db_root is not None:
                    base = db_root / place
                    prepare_inputs_place(base)
                    p_dtm_orig = select_rasters(base / "DTM", prefer_preprocessed=False)
                    p_f_orig = select_rasters_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=False)
                    p_l_orig = select_rasters_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=False)
                    src_groups = [p_dtm_orig, p_f_orig, p_l_orig]
                    if p_dtm_orig and p_f_orig and p_l_orig and self._preprocessed_groups_missing(src_groups, profile):
                        self.status.set(f"{profile['label']} being prepared...")
                        self.update_idletasks()
                        self._ensure_preprocessed_groups(src_groups, profile)
            except Exception as e:
                self.status.set(f"Error {profile['label']}: {e}")
                messagebox.showerror("Preprocess", str(e))
                self.update_param_states()
                self.refresh_basemap_years()
                self._show_blank()
                return
        self.data.load(
            place_name=place,
            use_preprocessed=use_preprocessed,
            preprocessed_suffix=profile["suffix"],
        )
        if not self.data.loaded:
            if self.lads_enabled.get():
                self._close_lads_window()
            self.status.set(self.data.error or "Input error.")
            self.update_param_states()
            self.refresh_basemap_years()
            self._show_blank()
            return
        place_txt = f"Database/{place}"
        src_mode = mode
        self.refresh_basemap_years()
        if self.data.area_geojson_path:
            self.status.set(f"OK | source: {place_txt} ({src_mode}) | area: {Path(self.data.area_geojson_path).name}")
        else:
            self.status.set(f"OK | source: {place_txt} ({src_mode})")
        self.update_param_states()
        self.schedule_update()
        self._refresh_lads_if_open()

    def load_dropped_inputs(self):
        self._refresh_drop_status()
        if not self._drop_session_ready():
            if self.lads_enabled.get():
                self._close_lads_window()
            self.status.set("Quick session incomplete: at least one DTM is needed.")
            self.update_param_states()
            self.refresh_basemap_years()
            self._show_blank()
            return
        mode = self.base_image_mode.get()
        profile_key = BASE_IMAGE_TO_PROFILE.get(mode)
        use_preprocessed = profile_key is not None
        if profile_key:
            self.prepro_profile.set(profile_key)
        profile = PREPRO_PROFILES.get(self.prepro_profile.get(), PREPRO_PROFILES["prep1"])
        if use_preprocessed:
            try:
                src_groups = [
                    self.drop_sources["DTM"],
                    self.drop_sources["DSM_First"],
                    self.drop_sources["DSM_Last"],
                ]
                if self._preprocessed_groups_missing(src_groups, profile):
                    self.status.set(f"{profile['label']} being prepared...")
                    self.update_idletasks()
                    self._ensure_preprocessed_groups(src_groups, profile)
            except Exception as e:
                self.status.set(f"Error {profile['label']}: {e}")
                messagebox.showerror("Preprocess", str(e))
                self.update_param_states()
                self.refresh_basemap_years()
                self._show_blank()
                return
        self.data.load_from_paths(
            self.drop_sources["DTM"],
            self.drop_sources["DSM_First"],
            self.drop_sources["DSM_Last"],
            use_preprocessed=use_preprocessed,
            preprocessed_suffix=profile["suffix"],
        )
        if not self.data.loaded:
            if self.lads_enabled.get():
                self._close_lads_window()
            self.status.set(self.data.error or "Drag-and-drop input error.")
            self.update_param_states()
            self.refresh_basemap_years()
            self._show_blank()
            return
        self.refresh_basemap_years()
        src_mode = mode
        counts_txt = f"DTM {len(self.drop_sources['DTM'])} | DSM First {len(self.drop_sources['DSM_First'])} | DSM Last {len(self.drop_sources['DSM_Last'])}"
        self.status.set(f"OK | source: Quick session/{self._drop_session_label()} ({src_mode}) | {counts_txt}")
        self.update_param_states()
        self.schedule_update()
        self._refresh_drop_status()
        self._refresh_lads_if_open()

    def reload_inputs(self):
        if self.active_source_mode == "drop":
            self.load_dropped_inputs()
            return
        self.load_database_inputs()

    def update_param_states(self):
        self._update_dataset_availability()
        ds = self.dataset.get()
        is_original = ds == "Original"
        m = self.method.get()

        if is_original:
            self.method_combo.state(["disabled"])
            self.invert_cb.state(["disabled"])
            self.basemap_cb.state(["disabled"])
            self.basemap_scale.state(["disabled"])
            self.basemap_year_combo.state(["!disabled"])
        else:
            self.method_combo.state(["!disabled"])
            self.invert_cb.state(["!disabled"])
            self.basemap_cb.state(["!disabled"])
            self.basemap_scale.state(["!disabled"] if self.basemap_on.get() else ["disabled"])
            self.basemap_year_combo.state(["disabled"])

        use_params = (not is_original) and (m != "Raw")

        need_az_alt = use_params and (m in {"Hillshade", "Multi-Hillshade", "Sky Illumination"})
        need_rad = use_params and (
            m
            in {
                "Sky-View Factor",
                "Anisotropic Sky-View Factor",
                "Positive Openness",
                "Simple Local Relief Model",
                "Local Relief Model",
                "Multi-Scale Relief Model",
                "Sky Illumination",
                "Local Dominance",
            }
        )
        need_dir = use_params and (m in {"Sky-View Factor", "Anisotropic Sky-View Factor", "Positive Openness", "Multi-Hillshade", "Sky Illumination"})
        need_z = use_params and (m != "e3MSTP (RGB)")

        self.param_widgets["azimuth"].state(["!disabled"] if need_az_alt else ["disabled"])
        self.param_widgets["altitude"].state(["!disabled"] if need_az_alt else ["disabled"])
        self.param_widgets["radius"].state(["!disabled"] if need_rad else ["disabled"])
        self.param_widgets["n_dir"].state(["!disabled"] if need_dir else ["disabled"])
        self.param_widgets["z_factor"].state(["!disabled"] if need_z else ["disabled"])
        self.param_widgets["p_low"].state(["!disabled"] if not is_original else ["disabled"])
        self.param_widgets["p_high"].state(["!disabled"] if not is_original else ["disabled"])

    def schedule_update(self):
        if self._update_job is not None:
            try:
                self.after_cancel(self._update_job)
            except Exception:
                pass
        self._update_job = self.after(120, self.update_view)

    def _stretch_for_display(self, arr):
        p_lo = float(self.p_low.get())
        p_hi = float(self.p_high.get())
        if p_hi <= p_lo:
            p_lo, p_hi = 2.0, 98.0
        return stretch01(as_float32(arr), p_lo, p_hi)

    def _bounds_lonlat(self):
        bounds = self.data.bounds
        crs = self.data.crs
        if bounds is None:
            return None
        if crs is not None and crs.to_string() != "EPSG:4326":
            try:
                b = rasterio.warp.transform_bounds(crs, "EPSG:4326", *bounds, densify_pts=21)
                return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
            except Exception:
                return bounds
        return bounds

    def _satellite_cache_entries(self, w, h):
        bounds_ll = self._bounds_lonlat()
        if bounds_ll is None:
            return None, []
        tile_template = self._satellite_template_for_year()
        year_key = self.basemap_year.get()
        entries = []
        for zbm in SAT_ZOOMS_TRY:
            cache_key = ("sat", year_key, zbm, w, h, bounds_ll)
            entries.append((cache_key, zbm, tile_template, bounds_ll))
        return bounds_ll, entries

    def _satellite_sync(self, w, h):
        _, entries = self._satellite_cache_entries(w, h)
        if not entries:
            return None

        for cache_key, zbm, tile_template, bounds_ll in entries:
            cached = self.basemap_cache.peek(cache_key)
            if cached is not None:
                return cached

            def loader():
                img = build_satellite_rgb(bounds_ll, zbm, tile_template=tile_template)
                if img is None:
                    return None
                img = img.resize((w, h), resample=Image.BILINEAR)
                return np.asarray(img, dtype=np.float32) / 255.0

            sat = self.basemap_cache.get(cache_key, loader)
            if sat is not None:
                return sat
        return None

    def _satellite(self, w, h):
        _, entries = self._satellite_cache_entries(w, h)
        if not entries:
            return None

        for cache_key, _zbm, _tile_template, _bounds_ll in entries:
            cached = self.basemap_cache.peek(cache_key)
            if cached is not None:
                return cached

        load_key = ("load", self.basemap_year.get(), w, h, entries[0][3])
        with self._satellite_loading_lock:
            if load_key in self._satellite_loading_keys:
                return None
            self._satellite_loading_keys.add(load_key)

        def worker():
            try:
                for cache_key, zbm, tile_template, bounds_ll in entries:
                    img = build_satellite_rgb(bounds_ll, zbm, tile_template=tile_template)
                    if img is None:
                        continue
                    img = img.resize((w, h), resample=Image.BILINEAR)
                    arr = np.asarray(img, dtype=np.float32) / 255.0
                    self.basemap_cache.put(cache_key, arr)
                    break
            finally:
                with self._satellite_loading_lock:
                    self._satellite_loading_keys.discard(load_key)
                try:
                    self.after(0, self.schedule_update)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()
        return None

    def _get_dataset_array(self, ds):
        if ds == "DTM":
            return self.data.dtm
        if ds == "DSM_First":
            return self.data.dsmf
        if ds == "DSM_Last":
            return self.data.dsml
        if ds == "nDSM":
            return self.data.ndsm
        if ds == "First-Last":
            return self.data.diff
        return None

    def show_methods_grid(self):
        if not self.data.loaded:
            messagebox.showerror("Method grid", "Inputs not loaded.")
            return

        ds = self.dataset.get()
        if ds == "Original":
            messagebox.showerror("Method grid", "Select a dataset other than Original.")
            return

        dem = self._get_dataset_array(ds)
        if dem is None:
            messagebox.showerror("Method grid", "Dataset not available.")
            return

        methods = self.available_methods()
        if not methods:
            messagebox.showerror("Method grid", "No RVT method available.")
            return

        res = float(self.data.res)
        az = float(self.azimuth.get())
        alt = float(self.altitude.get())
        z = float(self.z_factor.get())
        rad = float(self.radius.get())
        n_dir = int(self.n_dir.get())
        cmap = "gray_r" if self.invert.get() else "gray"
        cmap_obj = mpl.colormaps.get_cmap(cmap).copy()
        cmap_obj.set_bad("black")

        images = []
        errors = []
        for method in methods:
            try:
                out = compute_method(method, dem, res, az, alt, z, rad, n_dir)
                out = as_float32(out)
                if out.ndim == 3:
                    disp = normalize_rgb01(out)
                    images.append((method, disp, True))
                else:
                    disp = self._stretch_for_display(out)
                    images.append((method, disp, False))
            except Exception as e:
                errors.append(f"{method}: {e}")

        if not images:
            msg = "Unable to compute the methods."
            if errors:
                msg = f"{msg}\n{errors[0]}"
            messagebox.showerror("Method grid", msg)
            return

        n = len(images)
        cols = int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / cols))

        win = tk.Toplevel(self)
        win.title(f"Method grid | {ds}")
        win.geometry("1280x860")
        win.minsize(900, 600)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        fig = Figure(figsize=(12, 8), dpi=130)
        fig.patch.set_facecolor("black")
        fig.subplots_adjust(left=0.02, right=0.98, top=0.94, bottom=0.03, wspace=0.02, hspace=0.10)
        axes = fig.subplots(rows, cols)
        axes = np.atleast_1d(axes).ravel()

        for idx, ax in enumerate(axes):
            ax.set_axis_off()
            ax.set_facecolor("black")
            if idx < n:
                method, disp, is_rgb = images[idx]
                if is_rgb:
                    ax.imshow(disp, interpolation="nearest")
                else:
                    ax.imshow(np.ma.masked_invalid(disp), cmap=cmap_obj, interpolation="nearest")
                ax.set_title(method, color="white", fontsize=10, pad=4)

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        canvas.draw_idle()

        if errors:
            self.status.set(f"Method grid: {len(images)} OK, {len(errors)} errori")

    def _build_lads_cloud(self):
        if not self.data.loaded or self.data.dtm is None:
            raise RuntimeError("DTM not loaded.")
        original_dtm, original_profile, original_crs = self._load_original_dtm_surface()
        return build_lads_point_cloud(
            original_dtm,
            original_profile,
            original_crs,
            target_crs=LADS_TARGET_CRS,
        )

    def _ensure_preprocessed_groups(self, src_groups, profile):
        groups = []
        for group in src_groups:
            items = [Path(p).expanduser().resolve() for p in group if p]
            if items:
                groups.append(items)
        if not groups:
            return []

        created = []
        for group in groups:
            for src in group:
                is_fresh, dst = has_fresh_preprocessed(self.root_path, src, suffix=profile["suffix"])
                if is_fresh:
                    continue
                preprocess_raster_file(
                    src,
                    dst,
                    fill_dist=profile["fill_dist"],
                    fill_smooth_iter=profile["fill_smooth_iter"],
                    sigma=profile["sigma"],
                )
                created.append(dst)
        return created

    def _preprocessed_groups_missing(self, src_groups, profile):
        groups = []
        for group in src_groups:
            items = [Path(p).expanduser().resolve() for p in group if p]
            if items:
                groups.append(items)
        if not groups:
            return False
        for group in groups:
            for src in group:
                is_fresh, _dst = has_fresh_preprocessed(self.root_path, src, suffix=profile["suffix"])
                if not is_fresh:
                    return True
        return False

    def _dataset_available(self, name):
        if name == "DTM":
            return self.data.loaded and self.data.dtm is not None
        if name == "DSM_First":
            return self.data.loaded and self.data.dsmf is not None
        if name == "DSM_Last":
            return self.data.loaded and self.data.dsml is not None
        if name == "nDSM":
            return self.data.loaded and self.data.ndsm is not None
        if name == "First-Last":
            return self.data.loaded and self.data.diff is not None
        if name == "Original":
            return self.data.loaded and self.data.dtm is not None
        return False

    def _update_dataset_availability(self):
        available_now = [name for name in ("DTM", "DSM_First", "DSM_Last", "nDSM", "First-Last", "Original") if self._dataset_available(name)]
        for name, widget in self.dataset_widgets.items():
            if self._dataset_available(name):
                widget.state(["!disabled"])
            else:
                widget.state(["disabled"])
        if available_now and self.dataset.get() not in available_now:
            fallback = "DTM" if "DTM" in available_now else available_now[0]
            self.dataset.set(fallback)

    def _current_3d_cloud_variant_key(self):
        return "original"

    def _current_cloud_preprocess_key(self):
        return "original"

    def _load_original_dtm_surface(self):
        return self._load_dtm_surface_variant("original")

    def _load_dtm_surface_variant(self, variant_key="original"):
        src_paths = self.data.src_original_dtm_paths or self.data.src_dtm_paths
        if not src_paths:
            raise RuntimeError("Original DTM source not available.")

        src_paths = [Path(p).expanduser().resolve() for p in src_paths if p]
        load_paths = src_paths
        if variant_key != "original":
            profile_cfg = PREPRO_PROFILES.get(variant_key)
            if profile_cfg is None:
                raise RuntimeError(f"Invalid 3D Cloud profile: {variant_key}")
            self._ensure_preprocessed_groups([src_paths], profile_cfg)
            load_paths = []
            for src in src_paths:
                is_fresh, dst = has_fresh_preprocessed(self.root_path, src, suffix=profile_cfg["suffix"])
                load_paths.append(dst if is_fresh else src)

        dtm, _res, profile, _nodata, bounds, crs = load_raster_source(load_paths)
        if self.data.area_geojson_path:
            dummy = np.zeros_like(dtm, dtype=np.float32)
            tile = {
                "DTM": dtm,
                "DSM_First": dummy,
                "DSM_Last": dummy,
                "nDSM": dummy,
                "First-Last": dummy,
                "profile": profile,
                "bounds": bounds,
                "crs": crs,
            }
            tile = clip_tile_to_geojson(tile, Path(self.data.area_geojson_path).expanduser().resolve())
            dtm = tile["DTM"]
            profile = tile["profile"]
            crs = tile["crs"]
        return dtm, profile, crs

    def _3d_cloud_output_bundle(self):
        out_dir = self.root_path / "output_rvt_gui" / "3d_cloud"
        out_dir.mkdir(parents=True, exist_ok=True)
        place = self._current_place_label().replace(" ", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"{place}__3DCloud__{ts}"
        return out_dir, stem

    def _ensure_3d_cloud_http_server(self, root_dir):
        root_dir = Path(root_dir).resolve()
        if (
            self.cloud_http_server is not None
            and self.cloud_http_port is not None
            and self.cloud_http_root == str(root_dir)
        ):
            return int(self.cloud_http_port)

        if self.cloud_http_server is not None:
            try:
                self.cloud_http_server.shutdown()
                self.cloud_http_server.server_close()
            except Exception:
                pass
            self.cloud_http_server = None
            self.cloud_http_port = None
            self.cloud_http_root = None

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                return

        handler = partial(QuietHandler, directory=str(root_dir))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.cloud_http_server = server
        self.cloud_http_port = int(server.server_address[1])
        self.cloud_http_root = str(root_dir)
        return self.cloud_http_port

    def show_3d_cloud_viewer(self):
        if not self.data.loaded or self.data.dtm is None:
            messagebox.showerror("3D Cloud", "Load a DTM first.")
            return
        try:
            out_dir, stem = self._3d_cloud_output_bundle()
            current_data_key = self._current_3d_cloud_variant_key()
            current_cloud_key = self._current_cloud_preprocess_key()
            data_outputs = []
            data_outputs_by_key = {}
            surface_cache = {}
            for item in CLOUD_SURFACE_OPTIONS:
                data_key = item["key"]
                data_label = item["label"]
                self.status.set(f"3D Cloud being prepared: data {data_label}...")
                self.update_idletasks()
                dtm, profile, crs = self._load_dtm_surface_variant(data_key)
                surface_cache[data_key] = (dtm, profile, crs)
                las_path = out_dir / f"{stem}__{data_key}.las"
                payload = {"key": data_key, "label": data_label, "las_path": las_path}
                data_outputs.append(payload)
                data_outputs_by_key[data_key] = payload

            cloud_options = [
                {
                    "key": key,
                    "label": cfg["label"],
                    "description": cfg.get("description", ""),
                }
                for key, cfg in CLOUD_PREPROCESS_PROFILES.items()
            ]
            combo_index = {}
            combo_order = []
            for data_item in data_outputs:
                for cloud_item in cloud_options:
                    payload = {
                        "data_key": data_item["key"],
                        "data_label": data_item["label"],
                        "cloud_key": cloud_item["key"],
                        "cloud_label": cloud_item["label"],
                        "las_path": data_item["las_path"],
                        "html_path": out_dir / f"{stem}__{data_item['key']}__{cloud_item['key']}.html",
                    }
                    combo_index[(data_item["key"], cloud_item["key"])] = payload
                    combo_order.append(payload)

            chosen = combo_index.get((current_data_key, current_cloud_key))
            if chosen is None:
                chosen = combo_order[0]
                current_data_key = chosen["data_key"]
                current_cloud_key = chosen["cloud_key"]

            def build_variant_items(cloud_key):
                return [
                    {
                        "key": data_item["key"],
                        "label": data_item["label"],
                        "href": quote(combo_index[(data_item["key"], cloud_key)]["html_path"].name),
                    }
                    for data_item in data_outputs
                ]

            def build_cloud_items(data_key):
                return [
                    {
                        "key": cloud_item["key"],
                        "label": cloud_item["label"],
                        "description": cloud_item.get("description", ""),
                        "href": quote(combo_index[(data_key, cloud_item["key"])]["html_path"].name),
                    }
                    for cloud_item in cloud_options
                ]

            chosen_dtm, chosen_profile, chosen_crs = surface_cache[chosen["data_key"]]
            self.status.set(f"3D Cloud being prepared: data {chosen['data_label']} | {chosen['cloud_label']}...")
            self.update_idletasks()
            export_lads_las(
                chosen_dtm,
                chosen_profile,
                chosen_crs,
                chosen["las_path"],
                target_crs=LADS_TARGET_CRS,
                cloud_preprocess_key="original",
            )
            chosen_grid = build_browser_terrain_grid(
                chosen_dtm,
                chosen_profile,
                chosen_crs,
                target_crs=LADS_TARGET_CRS,
                max_side=LADS_BROWSER_MAX_SIDE,
                cloud_preprocess_key=chosen["cloud_key"],
            )
            write_browser_cloud_viewer(
                chosen["html_path"],
                chosen_grid,
                las_href=quote(chosen["las_path"].name),
                variant_options=build_variant_items(chosen["cloud_key"]),
                current_variant_key=chosen["data_key"],
                cloud_preprocess_options=build_cloud_items(chosen["data_key"]),
                current_cloud_preprocess_key=chosen["cloud_key"],
            )

            port = self._ensure_3d_cloud_http_server(out_dir)
            url = f"http://127.0.0.1:{port}/{quote(chosen['html_path'].name)}?v={int(datetime.now().timestamp())}"
            try:
                subprocess.Popen(["open", "-a", "Google Chrome", url])
            except Exception:
                webbrowser.open(url)
            self.status.set(
                f"3D Cloud opened in the browser | data {chosen['data_label']} | cloud {chosen['cloud_label']} | other variants being prepared"
            )

            def background_generate_remaining():
                try:
                    las_ready = {chosen["data_key"]}
                    ordered_keys = []
                    for cloud_item in cloud_options:
                        key = (chosen["data_key"], cloud_item["key"])
                        if key != (chosen["data_key"], chosen["cloud_key"]):
                            ordered_keys.append(key)
                    for data_item in data_outputs:
                        key = (data_item["key"], chosen["cloud_key"])
                        if key != (chosen["data_key"], chosen["cloud_key"]) and key not in ordered_keys:
                            ordered_keys.append(key)
                    for payload in combo_order:
                        key = (payload["data_key"], payload["cloud_key"])
                        if key != (chosen["data_key"], chosen["cloud_key"]) and key not in ordered_keys:
                            ordered_keys.append(key)

                    for data_key, cloud_key in ordered_keys:
                        item = combo_index[(data_key, cloud_key)]
                        dtm, profile, crs = surface_cache[data_key]
                        if data_key not in las_ready:
                            export_lads_las(
                                dtm,
                                profile,
                                crs,
                                item["las_path"],
                                target_crs=LADS_TARGET_CRS,
                                cloud_preprocess_key="original",
                            )
                            las_ready.add(data_key)
                        terrain_grid = build_browser_terrain_grid(
                            dtm,
                            profile,
                            crs,
                            target_crs=LADS_TARGET_CRS,
                            max_side=LADS_BROWSER_MAX_SIDE,
                            cloud_preprocess_key=cloud_key,
                        )
                        write_browser_cloud_viewer(
                            item["html_path"],
                            terrain_grid,
                            las_href=quote(item["las_path"].name),
                            variant_options=build_variant_items(cloud_key),
                            current_variant_key=data_key,
                            cloud_preprocess_options=build_cloud_items(data_key),
                            current_cloud_preprocess_key=cloud_key,
                        )
                    self.after(
                        0,
                        lambda: self.status.set(
                            f"3D Cloud ready | data {chosen['data_label']} | cloud {chosen['cloud_label']}"
                        ),
                    )
                except Exception:
                    pass

            threading.Thread(target=background_generate_remaining, daemon=True).start()
        except Exception as e:
            messagebox.showerror("3D Cloud", str(e))

    def _sync_lads_button_state(self):
        self.lads_button_text.set("❌ Close 3D Cloud" if self.lads_enabled.get() else "☁️ 3D Cloud")

    def _lads_output_path(self):
        out_dir = self.root_path / "output_rvt_gui" / "lads"
        out_dir.mkdir(parents=True, exist_ok=True)
        place = self._current_place_label().replace(" ", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return out_dir / f"{place}__3DCloud__{ts}.las"

    def export_lads_file(self):
        if not self.data.loaded or self.data.dtm is None:
            messagebox.showerror("3D Cloud", "DTM not loaded.")
            return
        try:
            original_dtm, original_profile, original_crs = self._load_original_dtm_surface()
            out_path = self._lads_output_path()
            cloud = export_lads_las(
                original_dtm,
                original_profile,
                original_crs,
                out_path,
                target_crs=LADS_TARGET_CRS,
            )
            self.status.set(f"3D Cloud exported: {out_path} | points {cloud['total_points']:,}")
        except Exception as e:
            messagebox.showerror("3D Cloud", str(e))

    def _toggle_lads_fullscreen(self, _event=None):
        if self.lads_window is None or not self.lads_window.winfo_exists():
            return
        enable = not self.lads_fullscreen
        if enable:
            try:
                self.lads_windowed_geometry = self.lads_window.geometry()
            except Exception:
                self.lads_windowed_geometry = ""
        try:
            self.lads_window.attributes("-fullscreen", enable)
            self.lads_fullscreen = enable
        except Exception:
            self.lads_fullscreen = enable
            if enable:
                w = self.lads_window.winfo_screenwidth()
                h = self.lads_window.winfo_screenheight()
                self.lads_window.geometry(f"{w}x{h}+0+0")
            elif self.lads_windowed_geometry:
                self.lads_window.geometry(self.lads_windowed_geometry)

    def _exit_lads_fullscreen(self, _event=None):
        if not self.lads_fullscreen or self.lads_window is None or not self.lads_window.winfo_exists():
            return
        try:
            self.lads_window.attributes("-fullscreen", False)
        except Exception:
            pass
        self.lads_fullscreen = False
        if self.lads_windowed_geometry:
            try:
                self.lads_window.geometry(self.lads_windowed_geometry)
            except Exception:
                pass

    def _render_lads_window(self):
        cloud = self._build_lads_cloud()
        if self.lads_window is None or not self.lads_window.winfo_exists():
            win = tk.Toplevel(self)
            win.title("3D Cloud")
            screen_w = max(960, int(self.winfo_screenwidth()) - 40)
            screen_h = max(720, int(self.winfo_screenheight()) - 90)
            self.lads_windowed_geometry = f"{screen_w}x{screen_h}+20+20"
            win.geometry(self.lads_windowed_geometry)
            win.minsize(840, 640)
            win.columnconfigure(0, weight=1)
            win.rowconfigure(1, weight=1)
            win.protocol("WM_DELETE_WINDOW", self._close_lads_window)
            win.bind("<F11>", self._toggle_lads_fullscreen)
            win.bind("<Escape>", self._exit_lads_fullscreen)
            try:
                win.configure(bg="black")
            except Exception:
                pass
            self.lads_window = win
        else:
            win = self.lads_window
            for child in win.winfo_children():
                child.destroy()
            win.columnconfigure(0, weight=1)
            win.rowconfigure(1, weight=1)
            try:
                win.configure(bg="black")
            except Exception:
                pass
        toolbar = tk.Frame(win, bg="black")
        toolbar.grid(row=0, column=0, sticky="ew")
        tk.Button(
            toolbar,
            text="Export .LAS",
            command=self.export_lads_file,
            bg="#111111",
            fg="white",
            activebackground="#222222",
            activeforeground="white",
            relief="flat",
            padx=10,
            pady=5,
            highlightthickness=0,
            bd=0,
        ).pack(side="left", padx=8, pady=8)
        fig = build_lads_figure(cloud, title=f"3D Cloud | {self._current_place_label()}")
        self.lads_canvas = FigureCanvasTkAgg(fig, master=win)
        canvas_widget = self.lads_canvas.get_tk_widget()
        canvas_widget.grid(row=1, column=0, sticky="nsew")
        try:
            canvas_widget.configure(borderwidth=0, highlightthickness=0, bg="black")
        except Exception:
            pass
        self.lads_axes = fig.axes[0] if fig.axes else None
        if self.lads_axes is not None:
            self.lads_home_limits = (
                self.lads_axes.get_xlim3d(),
                self.lads_axes.get_ylim3d(),
                self.lads_axes.get_zlim3d(),
            )
        self.lads_canvas.mpl_connect("scroll_event", self._on_lads_scroll)
        self.lads_canvas.mpl_connect("button_press_event", self._on_lads_click)
        self.lads_canvas.draw_idle()
        self.status.set(
            f"3D Cloud open: elevation colouring | scroll to zoom | .LAS export | {cloud['preview_points']:,} points"
        )

    def _close_lads_window(self):
        win = self.lads_window
        self.lads_window = None
        self.lads_canvas = None
        self.lads_axes = None
        self.lads_home_limits = None
        self.lads_fullscreen = False
        self.lads_info_var.set("")
        if self.lads_enabled.get():
            self.lads_enabled.set(False)
        self._sync_lads_button_state()
        if win is not None and win.winfo_exists():
            win.destroy()

    def _on_lads_scroll(self, event):
        if self.lads_axes is None or event.inaxes != self.lads_axes:
            return
        base = 1.2
        btn = getattr(event, "button", None)
        scale = 1 / base if btn in ("up", 1) else base

        xlim = self.lads_axes.get_xlim3d()
        ylim = self.lads_axes.get_ylim3d()
        zlim = self.lads_axes.get_zlim3d()

        xmid = (xlim[0] + xlim[1]) * 0.5
        ymid = (ylim[0] + ylim[1]) * 0.5
        zmid = (zlim[0] + zlim[1]) * 0.5

        xspan = max(1e-6, (xlim[1] - xlim[0]) * scale)
        yspan = max(1e-6, (ylim[1] - ylim[0]) * scale)
        zspan = max(1e-6, (zlim[1] - zlim[0]) * scale)

        self.lads_axes.set_xlim3d(xmid - xspan * 0.5, xmid + xspan * 0.5)
        self.lads_axes.set_ylim3d(ymid - yspan * 0.5, ymid + yspan * 0.5)
        self.lads_axes.set_zlim3d(zmid - zspan * 0.5, zmid + zspan * 0.5)
        if self.lads_canvas is not None:
            self.lads_canvas.draw_idle()

    def _on_lads_click(self, event):
        if self.lads_axes is None or event.inaxes != self.lads_axes:
            return
        if not getattr(event, "dblclick", False) or self.lads_home_limits is None:
            return
        xlim, ylim, zlim = self.lads_home_limits
        self.lads_axes.set_xlim3d(xlim)
        self.lads_axes.set_ylim3d(ylim)
        self.lads_axes.set_zlim3d(zlim)
        if self.lads_canvas is not None:
            self.lads_canvas.draw_idle()

    def _refresh_lads_if_open(self):
        if not self.lads_enabled.get():
            return
        try:
            self._render_lads_window()
        except Exception as e:
            if self.lads_window is not None and self.lads_window.winfo_exists():
                self.lads_window.destroy()
            self.lads_window = None
            self.lads_canvas = None
            self.lads_info_var.set("")
            self.lads_enabled.set(False)
            self._sync_lads_button_state()
            messagebox.showerror("3D Cloud", str(e))

    def on_lads_toggle(self):
        if self.lads_enabled.get():
            self._close_lads_window()
            self.status.set("3D Cloud turned off.")
            return
        self.lads_enabled.set(True)
        self._sync_lads_button_state()
        if not self.data.loaded:
            self.lads_enabled.set(False)
            self._sync_lads_button_state()
            messagebox.showerror("3D Cloud", "Load a DTM first.")
            return
        try:
            self._render_lads_window()
        except Exception as e:
            self.lads_enabled.set(False)
            self._sync_lads_button_state()
            messagebox.showerror("3D Cloud", str(e))

    def update_view(self):
        self._update_job = None
        if not self.data.loaded:
            self._show_blank()
            return

        ds = self.dataset.get()

        try:
            if ds == "Original":
                ref = self.data.dtm
                if ref is None:
                    raise RuntimeError("DTM missing.")
                h, w = ref.shape
                sat = self._satellite(w, h)
                if sat is None:
                    self.status.set(f"Original: loading satellite {self.basemap_year.get()}...")
                    return
                self._draw(sat, None, alpha_over=0.0, reset=False)
                self.status.set(f"Original: Satellite ({self.basemap_year.get()})")
                return

            dem = self._get_dataset_array(ds)
            if dem is None:
                raise RuntimeError("Dataset not available.")

            method = self.method.get()
            res = float(self.data.res)
            az = float(self.azimuth.get())
            alt = float(self.altitude.get())
            z = float(self.z_factor.get())
            rad = float(self.radius.get())
            n_dir = int(self.n_dir.get())

            out = compute_method(method, dem, res, az, alt, z, rad, n_dir)
            out = as_float32(out)

            if out.ndim == 3 or is_rgb_method(method):
                disp_rgb = normalize_rgb01(out)
                self._draw(None, (disp_rgb, None), alpha_over=1.0, reset=False)
                self.status.set(f"{ds} | {method} | RGB")
                return
            else:
                disp_over = self._stretch_for_display(out)
                cmap = "gray_r" if self.invert.get() else "gray"
                cmap_obj = mpl.colormaps.get_cmap(cmap).copy()
                cmap_obj.set_bad("black")

                base = None
                alpha_over = 1.0
                loading_basemap = False
                if self.basemap_on.get():
                    base = self._satellite(disp_over.shape[1], disp_over.shape[0])
                    mix = float(self.basemap_mix.get())
                    mix = max(0.0, min(1.0, mix))
                    alpha_over = 1.0 - mix
                    if base is None:
                        loading_basemap = True

                self._draw(base, (disp_over, cmap_obj), alpha_over=alpha_over, reset=False)

            mn = float(np.nanmin(out)) if np.isfinite(out).any() else np.nan
            mx = float(np.nanmax(out)) if np.isfinite(out).any() else np.nan
            if loading_basemap:
                self.status.set(f"{ds} | {method} | loading basemap {self.basemap_year.get()}... | min {mn:.4f} | max {mx:.4f}")
            else:
                self.status.set(f"{ds} | {method} | min {mn:.4f} | max {mx:.4f}")

        except Exception as e:
            self.status.set(f"Error: {e}")
            self._show_blank()

    def _show_blank(self):
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")
        self.ax.figure.patch.set_facecolor("black")
        self.im_base = None
        self.im_over = None
        self.im_anno = None
        self.im_measure = None
        self.canvas.draw_idle()

    def _draw(self, base_rgb01, over_pack, alpha_over=1.0, reset=False):
        h = None
        w = None
        if over_pack is not None:
            over01, _ = over_pack
            h, w = over01.shape[:2]
        elif base_rgb01 is not None:
            h, w = base_rgb01.shape[:2]

        if h is None or w is None:
            self._show_blank()
            return
        self._ensure_annotation_canvas(h, w)

        keep = (not reset) and (self._last_shape == (h, w)) and (self.im_over is not None or self.im_base is not None)
        prev_xlim = self.ax.get_xlim() if keep else None
        prev_ylim = self.ax.get_ylim() if keep else None

        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")
        self.ax.figure.patch.set_facecolor("black")

        if base_rgb01 is not None:
            base_rgb01 = np.asarray(base_rgb01, dtype=np.float32)
            self.im_base = self.ax.imshow(base_rgb01, interpolation="bilinear", alpha=1.0)
        else:
            self.im_base = None

        if over_pack is not None and alpha_over > 0.0:
            over01, cmap_obj = over_pack
            over01 = np.asarray(over01, dtype=np.float32)
            if over01.ndim == 3:
                self.im_over = self.ax.imshow(over01, interpolation="nearest", alpha=alpha_over)
            else:
                m1 = np.ma.masked_invalid(over01)
                self.im_over = self.ax.imshow(m1, cmap=cmap_obj, interpolation="nearest", alpha=alpha_over)
        else:
            self.im_over = None

        self._draw_annotation_artist()

        if keep and prev_xlim is not None and prev_ylim is not None:
            self.ax.set_xlim(prev_xlim)
            self.ax.set_ylim(prev_ylim)

        if self._home_limits is None or reset:
            self._home_limits = (self.ax.get_xlim(), self.ax.get_ylim())

        self._last_shape = (h, w)
        self.canvas.draw_idle()

    def _compose_current_view_rgb01(self):
        if not self.data.loaded:
            raise RuntimeError("Inputs not loaded.")

        ds = self.dataset.get()
        if ds == "Original":
            ref = self.data.dtm
            if ref is None:
                raise RuntimeError("DTM missing.")
            h, w = ref.shape
            sat = self._satellite_sync(w, h)
            if sat is None:
                raise RuntimeError("Satellite not available (network or area too large).")
            return self._apply_annotations_rgb(np.asarray(sat, dtype=np.float32))

        dem = self._get_dataset_array(ds)
        if dem is None:
            raise RuntimeError("Dataset not available.")

        method = self.method.get()
        res = float(self.data.res)
        az = float(self.azimuth.get())
        alt = float(self.altitude.get())
        z = float(self.z_factor.get())
        rad = float(self.radius.get())
        n_dir = int(self.n_dir.get())

        out = compute_method(method, dem, res, az, alt, z, rad, n_dir)
        out = as_float32(out)

        if out.ndim == 3 or is_rgb_method(method):
            return self._apply_annotations_rgb(normalize_rgb01(out))

        disp_over = self._stretch_for_display(out)
        cmap = "gray_r" if self.invert.get() else "gray"
        cmap_obj = mpl.colormaps.get_cmap(cmap).copy()
        rgba = cmap_obj(np.nan_to_num(disp_over, nan=0.0))
        over_rgb = np.asarray(rgba[:, :, :3], dtype=np.float32)
        over_rgb[~np.isfinite(disp_over)] = 0.0

        if not self.basemap_on.get():
            return self._apply_annotations_rgb(over_rgb)

        base = self._satellite_sync(over_rgb.shape[1], over_rgb.shape[0])
        if base is None:
            return self._apply_annotations_rgb(over_rgb)

        mix = float(self.basemap_mix.get())
        mix = max(0.0, min(1.0, mix))
        alpha_over = 1.0 - mix
        mixed = np.clip(np.asarray(base, dtype=np.float32) * (1.0 - alpha_over) + over_rgb * alpha_over, 0.0, 1.0)
        return self._apply_annotations_rgb(mixed)

    def _ensure_annotation_canvas(self, h, w):
        if self.annotation_alpha is None or self.annotation_alpha.shape != (h, w):
            self.annotation_alpha = np.zeros((h, w), dtype=np.float32)
        if self.annotation_rgb is None or self.annotation_rgb.shape != (h, w, 3):
            self.annotation_rgb = np.zeros((h, w, 3), dtype=np.float32)

    def _brush_rgb(self):
        palette = {
            "Giallo": np.array([1.0, 1.0, 0.0], dtype=np.float32),
            "Rosso": np.array([1.0, 0.15, 0.15], dtype=np.float32),
            "Verde": np.array([0.2, 1.0, 0.2], dtype=np.float32),
            "Ciano": np.array([0.1, 0.95, 1.0], dtype=np.float32),
        }
        return palette.get(self.brush_color.get(), palette["Giallo"])

    def _annotation_rgba(self):
        if self.annotation_alpha is None:
            return None
        if not np.any(self.annotation_alpha > 0):
            return None
        h, w = self.annotation_alpha.shape
        rgba = np.zeros((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = self.annotation_rgb
        rgba[:, :, 3] = np.clip(self.annotation_alpha, 0.0, 1.0)
        return rgba

    def _draw_annotation_artist(self):
        rgba = self._annotation_rgba()
        if rgba is None:
            self.im_anno = None
        else:
            self.im_anno = self.ax.imshow(rgba, interpolation="nearest", alpha=1.0)
        measure_rgba = self._measure_overlay_rgba()
        if measure_rgba is None:
            self.im_measure = None
            return
        self.im_measure = self.ax.imshow(measure_rgba, interpolation="nearest", alpha=1.0)

    def _update_annotation_artist_live(self):
        rgba = self._annotation_rgba()
        if rgba is None:
            if self.im_anno is not None:
                try:
                    self.im_anno.remove()
                except Exception:
                    pass
                self.im_anno = None
        else:
            if self.im_anno is None:
                self.im_anno = self.ax.imshow(rgba, interpolation="nearest", alpha=1.0)
            else:
                self.im_anno.set_data(rgba)
        self._update_measure_artist_live()
        self.canvas.draw_idle()

    def _update_measure_artist_live(self):
        rgba = self._measure_overlay_rgba()
        if rgba is None:
            if self.im_measure is not None:
                try:
                    self.im_measure.remove()
                except Exception:
                    pass
                self.im_measure = None
            return
        if self.im_measure is None:
            self.im_measure = self.ax.imshow(rgba, interpolation="nearest", alpha=1.0)
        else:
            self.im_measure.set_data(rgba)
        self.canvas.draw_idle()

    def _apply_annotations_rgb(self, rgb01):
        rgb = np.asarray(rgb01, dtype=np.float32).copy()
        if rgb.ndim != 3 or rgb.shape[2] < 3:
            return rgb
        h, w = rgb.shape[:2]
        self._ensure_annotation_canvas(h, w)
        if self.annotation_alpha is None:
            return rgb
        a = np.clip(self.annotation_alpha, 0.0, 1.0)
        if not np.any(a > 0):
            return rgb
        anno_rgb = np.asarray(self.annotation_rgb, dtype=np.float32)
        rgb[:, :, :3] = rgb[:, :, :3] * (1.0 - a[:, :, None]) + anno_rgb * a[:, :, None]
        return np.clip(rgb, 0.0, 1.0)

    def arm_coordinate_pick(self):
        if not self.data.loaded:
            messagebox.showerror("Get Coordinates", "Inputs not loaded.")
            return
        self.pick_coords_armed = True
        self.brush_on.set(False)
        self._on_brush_toggle()
        self.status.set("Get Coordinates active: click a point on the map.")

    def _copy_point_coordinates(self, x_data, y_data):
        profile = self.data.profile
        transform = profile.get("transform") if profile else None
        if transform is None:
            raise RuntimeError("Georeferenced transform not available.")

        row = int(round(float(y_data)))
        col = int(round(float(x_data)))
        h, w = self.data.dtm.shape
        if row < 0 or col < 0 or row >= h or col >= w:
            raise RuntimeError("Point outside the raster area.")

        x_map, y_map = rasterio.transform.xy(transform, row, col, offset="center")
        crs = self.data.crs
        if crs is None:
            raise RuntimeError("Raster CRS not available.")
        if crs.to_string() != "EPSG:4326":
            lon, lat = rasterio.warp.transform(crs, "EPSG:4326", [float(x_map)], [float(y_map)])
            lon = float(lon[0])
            lat = float(lat[0])
        else:
            lon = float(x_map)
            lat = float(y_map)

        text = f"{decimal_to_dms(lat, 'N', 'S')}, {decimal_to_dms(lon, 'E', 'W')}"

        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        self.status.set(f"Coordinates copied: {text}")
        return {"row": row, "col": col, "x_map": float(x_map), "y_map": float(y_map), "lon": lon, "lat": lat, "dms": text}

    def arm_measure_tool(self):
        if not self.data.loaded:
            messagebox.showerror("Measure", "Inputs not loaded.")
            return
        self.measure_points = []
        self.measure_armed = True
        self.pick_coords_armed = False
        self.report_pick_pending = None
        self.brush_on.set(False)
        self._update_measure_artist_live()
        self._on_brush_toggle()
        self.status.set("Measure active: click two points on the map.")

    def _measure_distance_m(self, p1, p2):
        crs = self.data.crs
        x1, y1 = p1["x_map"], p1["y_map"]
        x2, y2 = p2["x_map"], p2["y_map"]
        if crs is not None and crs.is_projected:
            return float(math.hypot(x2 - x1, y2 - y1))
        lon = [p1["lon"], p2["lon"]]
        lat = [p1["lat"], p2["lat"]]
        dst_crs = rasterio.crs.CRS.from_string(utm_epsg_from_lonlat((lon[0] + lon[1]) * 0.5, (lat[0] + lat[1]) * 0.5))
        xx, yy = rasterio.warp.transform("EPSG:4326", dst_crs, lon, lat)
        return float(math.hypot(xx[1] - xx[0], yy[1] - yy[0]))

    def _measure_overlay_rgba(self):
        if self.annotation_alpha is None or len(self.measure_points) < 2:
            return None
        h, w = self.annotation_alpha.shape
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        p1, p2 = self.measure_points[-2], self.measure_points[-1]
        x1, y1 = p1["col"], p1["row"]
        x2, y2 = p2["col"], p2["row"]
        draw.line((x1, y1, x2, y2), fill=(255, 80, 80, 255), width=4)
        for x, y in ((x1, y1), (x2, y2)):
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), outline=(255, 80, 80, 255), width=3)
        return np.asarray(img, dtype=np.float32) / 255.0

    def open_report_window(self):
        if self.report_window is not None and self.report_window.winfo_exists():
            self.report_window.lift()
            self.report_window.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Exploration report")
        win.geometry("760x560")
        win.minsize(680, 500)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        self.report_window = win

        header = ttk.Frame(win, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Place name").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(header, textvariable=self.report_name_var).grid(row=0, column=1, sticky="ew")

        notes_box = ttk.LabelFrame(win, text="Note", padding=10)
        notes_box.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        notes_box.columnconfigure(0, weight=1)
        notes = tk.Text(notes_box, height=5, wrap="word")
        notes.grid(row=0, column=0, sticky="ew")
        self.report_notes_text = notes

        body = ttk.Frame(win, padding=(10, 0, 10, 10))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.report_listbox = tk.Listbox(body, listvariable=self.report_list_var, height=12)
        self.report_listbox.grid(row=0, column=0, sticky="nsew")

        actions = ttk.Frame(win, padding=(10, 0, 10, 10))
        actions.grid(row=3, column=0, sticky="ew")
        for idx in range(5):
            actions.columnconfigure(idx, weight=1)
        ttk.Button(actions, text="Add from map", command=self.start_report_point_pick).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text="Remove selected", command=self.remove_selected_report_item).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(actions, text="Clear all", command=self.clear_report_items).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(actions, text="Generate PDF", command=self.generate_exploration_report_pdf).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Button(actions, text="Export KML", command=self.export_report_kml).grid(row=0, column=4, sticky="ew", padx=(4, 0))

        ttk.Label(win, textvariable=self.report_status_var, wraplength=720, padding=(10, 0, 10, 10)).grid(row=4, column=0, sticky="ew")
        win.protocol("WM_DELETE_WINDOW", self._close_report_window)
        self.refresh_report_list()

    def _close_report_window(self):
        try:
            self.report_notes_text = None
        except Exception:
            pass
        self.report_listbox = None
        win = self.report_window
        self.report_window = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def refresh_report_list(self):
        values = []
        for idx, item in enumerate(self.report_items, start=1):
            note_flag = " | note" if item.get("notes") else ""
            values.append(f"{idx}. {item['name']} | {item['coords_dms']}{note_flag}")
        self.report_list_var.set(values)
        n = len(self.report_items)
        self.report_status_var.set(f"Points in the report: {n}" if n else "No points in the report.")

    def start_report_point_pick(self):
        if not self.data.loaded:
            messagebox.showerror("Report", "Inputs not loaded.")
            return
        if self.report_window is None or not self.report_window.winfo_exists():
            self.open_report_window()
        name = self.report_name_var.get().strip()
        notes = ""
        if hasattr(self, "report_notes_text") and self.report_notes_text is not None:
            notes = self.report_notes_text.get("1.0", "end").strip()
        if not name:
            messagebox.showerror("Report", "Enter the place name before clicking on the map.")
            return
        self.report_pick_pending = {"name": name, "notes": notes}
        self.pick_coords_armed = False
        self.brush_on.set(False)
        self._on_brush_toggle()
        self.status.set(f"Report: click the point for '{name}'.")
        try:
            self.canvas.get_tk_widget().configure(cursor="crosshair")
        except Exception:
            pass

    def _capture_report_crop(self, rgb01, col, row):
        arr = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
        h, w = arr.shape[:2]
        radius = REPORT_CROP_RADIUS_PX
        x0 = max(0, col - radius)
        x1 = min(w, col + radius + 1)
        y0 = max(0, row - radius)
        y1 = min(h, row + radius + 1)
        crop = (arr[y0:y1, x0:x1, :3] * 255.0).astype(np.uint8)
        img = Image.fromarray(crop, mode="RGB").resize((REPORT_CROP_OUTPUT_SIZE, REPORT_CROP_OUTPUT_SIZE), resample=Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        cx = (col - x0) / max(1, x1 - x0)
        cy = (row - y0) / max(1, y1 - y0)
        px = int(round(cx * REPORT_CROP_OUTPUT_SIZE))
        py = int(round(cy * REPORT_CROP_OUTPUT_SIZE))
        r = 18
        draw.ellipse((px - r, py - r, px + r, py + r), outline=(255, 40, 40), width=4)
        draw.line((px - 28, py, px - 8, py), fill=(255, 40, 40), width=3)
        draw.line((px + 8, py, px + 28, py), fill=(255, 40, 40), width=3)
        draw.line((px, py - 28, px, py - 8), fill=(255, 40, 40), width=3)
        draw.line((px, py + 8, px, py + 28), fill=(255, 40, 40), width=3)
        return img

    def _compose_original_view_rgb01(self):
        if not self.data.loaded:
            raise RuntimeError("Inputs not loaded.")
        ref = self.data.dtm
        if ref is None:
            raise RuntimeError("DTM missing.")
        h, w = ref.shape
        sat = self._satellite_sync(w, h)
        if sat is None:
            raise RuntimeError("Satellite not available (network or area too large).")
        return np.asarray(sat, dtype=np.float32)

    def _handle_report_point_pick(self, x_data, y_data):
        pending = self.report_pick_pending
        if pending is None:
            return
        coords = self._copy_point_coordinates(x_data, y_data)
        current_rgb01 = self._compose_current_view_rgb01()
        original_rgb01 = self._compose_original_view_rgb01()
        current_crop_img = self._capture_report_crop(current_rgb01, coords["col"], coords["row"])
        original_crop_img = self._capture_report_crop(original_rgb01, coords["col"], coords["row"])
        item = {
            "name": pending["name"],
            "notes": pending.get("notes", ""),
            "coords_dms": coords["dms"],
            "lat": coords["lat"],
            "lon": coords["lon"],
            "current_crop_img": current_crop_img,
            "original_crop_img": original_crop_img,
            "dataset": self.dataset.get(),
            "method": self.method.get(),
            "place": self._current_place_label(),
            "original_year": self.basemap_year.get(),
        }
        self.report_items.append(item)
        self.report_pick_pending = None
        self.report_name_var.set("")
        if hasattr(self, "report_notes_text") and self.report_notes_text is not None:
            self.report_notes_text.delete("1.0", "end")
        self.refresh_report_list()
        self.status.set(f"Point added to the report: {item['name']}")

    def remove_selected_report_item(self):
        if not hasattr(self, "report_listbox") or self.report_listbox is None:
            return
        sel = self.report_listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.report_items):
            del self.report_items[idx]
            self.refresh_report_list()

    def clear_report_items(self):
        self.report_items.clear()
        self.refresh_report_list()

    def _build_report_page(self, item, index, total):
        page = Image.new("RGB", (1654, 2339), "white")
        draw = ImageDraw.Draw(page)
        title_font = load_pdf_font(44)
        section_font = load_pdf_font(34)
        text_font = load_pdf_font(26)

        draw.rectangle((70, 70, 1584, 2269), outline=(30, 30, 30), width=3)
        draw.text((110, 110), f"Exploration report  {index}/{total}", fill=(20, 20, 20), font=title_font)
        draw.text((110, 190), f"Place: {item['name']}", fill=(20, 20, 20), font=section_font)
        draw.text((110, 250), f"Coordinates: {item['coords_dms']}", fill=(20, 20, 20), font=text_font)
        draw.text((110, 295), f"Scenario: {item['place']} | {item['dataset']} | {item['method']} | Original {item.get('original_year', 'Current')}", fill=(20, 20, 20), font=text_font)

        orig_img = item["original_crop_img"].copy()
        curr_img = item["current_crop_img"].copy()
        left_x = 110
        right_x = 824
        img_y = 420
        label_y = 370

        draw.text((left_x, label_y), "Original", fill=(20, 20, 20), font=section_font)
        draw.text((right_x, label_y), "Current filter", fill=(20, 20, 20), font=section_font)

        page.paste(orig_img, (left_x, img_y))
        page.paste(curr_img, (right_x, img_y))
        draw.rectangle((left_x, img_y, left_x + orig_img.width, img_y + orig_img.height), outline=(40, 40, 40), width=2)
        draw.rectangle((right_x, img_y, right_x + curr_img.width, img_y + curr_img.height), outline=(40, 40, 40), width=2)

        note_y = 1180
        draw.text((110, note_y), "Note", fill=(20, 20, 20), font=section_font)
        box = (110, note_y + 40, 1544, 2140)
        draw.rectangle(box, outline=(80, 80, 80), width=2)
        lines = wrap_text_lines(draw, item.get("notes") or "-", text_font, box[2] - box[0] - 30)
        y = box[1] + 18
        for line in lines:
            draw.text((box[0] + 15, y), line, fill=(30, 30, 30), font=text_font)
            y += 38
            if y > box[3] - 35:
                break
        return page

    def generate_exploration_report_pdf(self):
        if not self.report_items:
            messagebox.showerror("Report", "Add at least one point to the report.")
            return
        try:
            pages = [self._build_report_page(item, idx + 1, len(self.report_items)).convert("RGB") for idx, item in enumerate(self.report_items)]
            out_dir = self.root_path / "output_rvt_gui" / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            place = (self._current_place_label() or "report").replace(" ", "_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = out_dir / f"exploration_report__{place}__{ts}.pdf"
            pages[0].save(out_path, save_all=True, append_images=pages[1:], resolution=150.0)
            self.report_status_var.set(f"PDF created: {out_path}")
            self.status.set(f"PDF report created: {out_path}")
        except Exception as e:
            messagebox.showerror("Report", str(e))

    def export_report_kml(self):
        if not self.report_items:
            messagebox.showerror("KML", "Add at least one point to the report before exporting.")
            return
        try:
            out_dir = self.root_path / "output_rvt_gui" / "maps"
            out_dir.mkdir(parents=True, exist_ok=True)
            place = (self._current_place_label() or "report").replace(" ", "_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = out_dir / f"poi_mymaps__{place}__{ts}.kml"
            doc_name = xml_escape(f"Points of interest - {self._current_place_label()}")

            placemarks = []
            for idx, item in enumerate(self.report_items, start=1):
                name = xml_escape(item.get("name") or f"Point {idx}")
                notes = item.get("notes") or "-"
                coords_dms = item.get("coords_dms") or "-"
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
                dataset = item.get("dataset") or "-"
                method = item.get("method") or "-"
                place_label = item.get("place") or self._current_place_label()
                maps_url = google_maps_point_url(lat, lon)
                description_lines = [
                    f"Coordinates: {coords_dms}",
                    f"Lat/Lon: {lat:.8f}, {lon:.8f}",
                    f"Scenario: {place_label} | {dataset} | {method}",
                    f"Google Maps: {maps_url}",
                    "",
                    f"Note: {notes}",
                ]
                description = xml_escape("\n".join(description_lines))
                placemarks.append(
                    f"""
    <Placemark>
      <name>{name}</name>
      <styleUrl>#poi-red</styleUrl>
      <description>{description}</description>
      <Point>
        <coordinates>{lon:.8f},{lat:.8f},0</coordinates>
      </Point>
    </Placemark>""".rstrip()
                )

            kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{doc_name}</name>
    <Style id="poi-red">
      <IconStyle>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>1.0</scale>
      </LabelStyle>
    </Style>
{chr(10).join(placemarks)}
  </Document>
</kml>
"""
            out_path.write_text(kml, encoding="utf-8")
            msg = f"KML created: {out_path} | import it into Google My Maps to share it."
            self.report_status_var.set(msg)
            self.status.set(msg)
        except Exception as e:
            messagebox.showerror("KML", str(e))

    def _paint_at(self, x_data, y_data):
        if self.annotation_alpha is None:
            return
        h, w = self.annotation_alpha.shape
        cx = int(round(float(x_data)))
        cy = int(round(float(y_data)))
        if cx < 0 or cy < 0 or cx >= w or cy >= h:
            return
        r = max(1, int(self.brush_size.get()))
        x0 = max(0, cx - r)
        x1 = min(w - 1, cx + r)
        y0 = max(0, cy - r)
        y1 = min(h - 1, cy + r)
        yy, xx = np.ogrid[y0 : y1 + 1, x0 : x1 + 1]
        m = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        patch = self.annotation_alpha[y0 : y1 + 1, x0 : x1 + 1]
        rgb_patch = self.annotation_rgb[y0 : y1 + 1, x0 : x1 + 1, :]
        brush_rgb = self._brush_rgb()
        patch[m] = np.maximum(patch[m], 0.35)
        rgb_patch[m] = brush_rgb

    def _paint_segment(self, x0, y0, x1, y1):
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(steps + 1):
            t = i / steps
            self._paint_at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    def _on_brush_toggle(self):
        try:
            if self.measure_armed or self.pick_coords_armed or self.report_pick_pending is not None or self.brush_on.get():
                self.canvas.get_tk_widget().configure(cursor="crosshair")
            else:
                self.canvas.get_tk_widget().configure(cursor="")
        except Exception:
            pass

    def clear_annotations(self):
        if self.annotation_alpha is not None:
            self.annotation_alpha.fill(0.0)
        if self.annotation_rgb is not None:
            self.annotation_rgb.fill(0.0)
        self.measure_points = []
        self.measure_armed = False
        self._update_annotation_artist_live()
        self.status.set("Marks cleared.")

    def export_current_view_hq(self):
        try:
            rgb01 = self._compose_current_view_rgb01()
            arr = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
            img = Image.fromarray((arr * 255.0).astype(np.uint8), mode="RGB")

            h, w = arr.shape[:2]
            long_side = max(h, w)
            scale = 1
            if long_side < 1600:
                scale = 2
            if long_side < 900:
                scale = 3
            if scale > 1:
                img = img.resize((w * scale, h * scale), resample=Image.LANCZOS)

            out_dir = self.root_path / "output_rvt_gui" / "export_hq_png"
            out_dir.mkdir(parents=True, exist_ok=True)

            place = self._current_place_label().replace(" ", "_")
            ds = self.dataset.get().replace(" ", "_")
            method = self.method.get().replace(" ", "_").replace("-", "_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = out_dir / f"{place}__{ds}__{method}__HQ__{ts}.png"
            img.save(out_path, format="PNG", optimize=True)
            self.status.set(f"Export PNG HQ: {out_path}")
        except Exception as e:
            messagebox.showerror("Export PNG HQ", str(e))

    def export_current(self):
        if not self.data.loaded:
            return
        ds = self.dataset.get()
        if ds == "Original":
            messagebox.showerror("Export", "Export disabled on Original (satellite).")
            return
        arr = self._get_dataset_array(ds)
        if arr is None:
            messagebox.showerror("Export", "Dataset not available.")
            return
        try:
            method_name = self.method.get()
            res = float(self.data.res)
            az = float(self.azimuth.get())
            alt = float(self.altitude.get())
            z = float(self.z_factor.get())
            rad = float(self.radius.get())
            n_dir = int(self.n_dir.get())

            out = compute_method(method_name, arr, res, az, alt, z, rad, n_dir)
            out = as_float32(out)

            out_dir = self.root_path / "output_rvt_gui"
            fname = f"{ds}__{method_name.replace(' ', '_').replace('-', '_')}.tif"
            save_geotiff(out_dir / fname, out, self.data.profile)
            self.status.set(f"Export: {out_dir / fname}")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def _active_prepro(self):
        key = self.prepro_profile.get()
        return PREPRO_PROFILES.get(key, PREPRO_PROFILES["prep1"])

    def preprocess_current_example(self, profile_key=None):
        if not self.data.loaded:
            messagebox.showerror("Preprocess", "Inputs not loaded.")
            return
        if profile_key:
            self.prepro_profile.set(profile_key)
        profile = self._active_prepro()
        src_groups = [
            self.data.src_original_dtm_paths or self.data.src_dtm_paths,
            self.data.src_original_dsmf_paths or self.data.src_dsmf_paths,
            self.data.src_original_dsml_paths or self.data.src_dsml_paths,
        ]
        src_groups = [[Path(p) for p in group if p] for group in src_groups]
        if not any(group for group in src_groups):
            messagebox.showerror("Preprocess", "Source files not available for the current example.")
            return
        try:
            outs = self._ensure_preprocessed_groups(src_groups, profile)
            return outs
        except Exception as e:
            messagebox.showerror("Preprocess", str(e))
            return None

    def on_base_image_mode_change(self, _evt=None):
        mode = self.base_image_mode.get()
        profile_key = BASE_IMAGE_TO_PROFILE.get(mode)
        if profile_key is None:
            self.reload_inputs()
            return
        outs = self.preprocess_current_example(profile_key=profile_key)
        if outs is None:
            self.base_image_mode.set("PrePro 1")
            self.reload_inputs()
            return
        profile = self._active_prepro()
        if outs:
            self.status.set(f"{profile['label']} creato: {', '.join([p.name for p in outs])}")
        else:
            self.status.set(f"{profile['label']} already available.")
        self.reload_inputs()

    def batch_pipeline(self):
        if not self.data.loaded:
            return
        out_root = self.root_path / "output_rvt_batch"
        out_root.mkdir(parents=True, exist_ok=True)
        log_path = out_root / "batch_log.txt"

        ok = 0
        fail = 0
        logs = []

        try:
            dtm = self.data.dtm
            dsmf = self.data.dsmf
            dsml = self.data.dsml
            res = float(self.data.res)
            prof = self.data.profile

            if dtm is None or dsmf is None or dsml is None:
                raise RuntimeError("Incomplete inputs for batch.")

            if hasattr(rvt.vis, "hillshade"):
                hs = compute_method("Hillshade", dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
                save_geotiff(out_root / "1_DTM_Hillshade.tif", hs, prof)

            if hasattr(rvt.vis, "sky_view_factor"):
                svf = compute_method("Sky-View Factor", dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
                save_geotiff(out_root / "2_DTM_SkyViewFactor.tif", svf, prof)

            save_geotiff(out_root / "3_nDSM.tif", dsmf - dtm, prof)
            save_geotiff(out_root / "4_FirstMinusLast.tif", dsmf - dsml, prof)
            ok = 1
        except Exception as e:
            fail = 1
            logs.append(f"{type(e).__name__}: {e}")

        log_path.write_text("\n".join(logs), encoding="utf-8")
        self.status.set(f"Batch OK: {ok} | Fail: {fail} | Log: {log_path}")

    def _connect_mouse(self):
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

    def _on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        base = 1.2
        btn = getattr(event, "button", None)
        if btn in ("up", 1):
            scale = 1 / base
        else:
            scale = base

        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        x = event.xdata
        y = event.ydata

        w = (xlim[1] - xlim[0]) * scale
        h = (ylim[1] - ylim[0]) * scale

        rx = (x - xlim[0]) / (xlim[1] - xlim[0])
        ry = (y - ylim[0]) / (ylim[1] - ylim[0])

        self.ax.set_xlim(x - w * rx, x + w * (1 - rx))
        self.ax.set_ylim(y - h * ry, y + h * (1 - ry))
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes != self.ax:
            return
        if event.dblclick and event.button == 1 and self._home_limits is not None:
            xlim, ylim = self._home_limits
            self.ax.set_xlim(xlim)
            self.ax.set_ylim(ylim)
            self.canvas.draw_idle()
            return
        if event.button != 1:
            return
        if self.measure_armed:
            if event.xdata is None or event.ydata is None:
                return
            try:
                point = self._copy_point_coordinates(event.xdata, event.ydata)
                self.measure_points.append(point)
                self.measure_points = self.measure_points[-2:]
                self._update_measure_artist_live()
                if len(self.measure_points) == 2:
                    dist_m = self._measure_distance_m(self.measure_points[0], self.measure_points[1])
                    self.status.set(f"Estimated distance: {dist_m:.2f} m")
                    self.measure_armed = False
                    self._on_brush_toggle()
                else:
                    self.status.set("Measure: click the second point.")
            except Exception as e:
                self.status.set(f"Measuring error: {e}")
                self.measure_armed = False
                self._on_brush_toggle()
            return
        if self.report_pick_pending is not None:
            if event.xdata is None or event.ydata is None:
                return
            try:
                self._handle_report_point_pick(event.xdata, event.ydata)
            except Exception as e:
                self.status.set(f"Report error: {e}")
            finally:
                self.report_pick_pending = None
                self._on_brush_toggle()
            return
        if self.pick_coords_armed:
            if event.xdata is None or event.ydata is None:
                return
            try:
                self._copy_point_coordinates(event.xdata, event.ydata)
            except Exception as e:
                self.status.set(f"Coordinates error: {e}")
            finally:
                self.pick_coords_armed = False
                self._on_brush_toggle()
            return
        if self.brush_on.get():
            if event.xdata is None or event.ydata is None:
                return
            self._brush_state = {"x": float(event.xdata), "y": float(event.ydata)}
            self._paint_at(event.xdata, event.ydata)
            self._update_annotation_artist_live()
            return
        if event.x is None or event.y is None:
            return
        self._pan_state = {
            "x_px": float(event.x),
            "y_px": float(event.y),
            "xlim": self.ax.get_xlim(),
            "ylim": self.ax.get_ylim(),
        }
        try:
            self.canvas.get_tk_widget().configure(cursor="fleur")
        except Exception:
            pass

    def _on_motion(self, event):
        if self._brush_state is not None and self.brush_on.get():
            if event.xdata is None or event.ydata is None:
                return
            p = self._brush_state
            self._paint_segment(p["x"], p["y"], float(event.xdata), float(event.ydata))
            p["x"] = float(event.xdata)
            p["y"] = float(event.ydata)
            self._update_annotation_artist_live()
            return
        if self._pan_state is None:
            return
        if event.x is None or event.y is None:
            return
        s = self._pan_state
        dx_px = float(event.x) - s["x_px"]
        dy_px = float(event.y) - s["y_px"]

        inv = self.ax.transData.inverted()
        x0d, y0d = inv.transform((0.0, 0.0))
        x1d, y1d = inv.transform((dx_px, dy_px))
        dx_data = x1d - x0d
        dy_data = y1d - y0d

        xlim0 = s["xlim"]
        ylim0 = s["ylim"]
        self.ax.set_xlim(xlim0[0] - dx_data, xlim0[1] - dx_data)
        self.ax.set_ylim(ylim0[0] - dy_data, ylim0[1] - dy_data)
        self.canvas.draw_idle()

    def _on_release(self, event):
        if event.button == 1:
            if self._brush_state is not None:
                self._brush_state = None
            self._pan_state = None
            try:
                if self.brush_on.get():
                    self.canvas.get_tk_widget().configure(cursor="crosshair")
                else:
                    self.canvas.get_tk_widget().configure(cursor="")
            except Exception:
                pass


if __name__ == "__main__":
    App().mainloop()
