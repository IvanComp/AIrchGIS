import inspect
import zipfile
import shutil
import math
import io
import json
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

import numpy as np
import rasterio
import rasterio.warp
import rasterio.features
import rasterio.transform
from rasterio.fill import fillnodata
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib as mpl

mpl.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from PIL import Image
import requests

import rvt.vis
import rvt.blend

try:
    from scipy.ndimage import gaussian_filter
except Exception:
    gaussian_filter = None

EXTS = {".tif", ".tiff", ".asc"}
SAT_ZOOMS_TRY = (19, 18, 17, 16, 15, 14, 13, 12)
MASE_URL = "https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new."
GE_URL = "https://earth.google.com/web/@42.06329556,13.44458279,859.60342866a,1982377.06794083d,35y,0h,0t,0r/data=CgRCAggBOgMKATBCAggASg0I____________ARAA"
FIRST_DIR_CANDIDATES = ("DSM_First", "DSM_Fisrt", "DSMfirst")
LAST_DIR_CANDIDATES = ("DSM_Last", "DSMlast")
PREPRO_PROFILES = {
    "prep1": {"label": "PrePro 1", "suffix": "_prep1", "fill_dist": 60, "fill_smooth_iter": 1, "sigma": 0.45},
    "prep2": {"label": "PrePro 2", "suffix": "_prep2", "fill_dist": 100, "fill_smooth_iter": 1, "sigma": 0.8},
    "prep3": {"label": "PrePro 3", "suffix": "_prep3", "fill_dist": 140, "fill_smooth_iter": 2, "sigma": 1.2},
}

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


def utm_epsg_from_lonlat(lon, lat):
    zone = int((lon + 180) // 6) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


def prep_output_path(src_path: Path, suffix="_prep"):
    if src_path.stem.endswith(suffix):
        return src_path
    return src_path.with_name(f"{src_path.stem}{suffix}{src_path.suffix}")


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
        raise RuntimeError("GeoJSON senza poligoni validi.")

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
        raise RuntimeError("L'area GeoJSON non interseca il raster corrente.")

    rows, cols = np.where(inside)
    r0, r1 = int(rows.min()), int(rows.max())
    c0, c1 = int(cols.min()), int(cols.max())
    win_h = r1 - r0 + 1
    win_w = c1 - c0 + 1
    inside_win = inside[r0 : r1 + 1, c0 : c1 + 1]

    def _clip_arr(a):
        b = np.asarray(a, dtype=np.float32)[r0 : r1 + 1, c0 : c1 + 1].copy()
        b[~inside_win] = np.nan
        return b

    dtm = _clip_arr(tile["DTM"])
    dsmf = _clip_arr(tile["DSM_First"])
    dsml = _clip_arr(tile["DSM_Last"])
    ndsm = dsmf - dtm
    diff = dsmf - dsml

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
    if prefer_preprocessed is False:
        pref = [p for p in rasters if not p.stem.endswith("_prep")]
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
            raise RuntimeError(f"Shape export non supportata: {out.shape}")
    else:
        raise RuntimeError(f"Dimensioni export non supportate: {out.ndim}")
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
    raise RuntimeError(f"Output RVT con shape non supportata: {arr.shape}")


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
        raise RuntimeError(f"Output RGB non valido: {rgb.shape}")
    if rgb.shape[0] in (3, 4):
        rgb = np.moveaxis(rgb[:3, :, :], 0, 2)
    elif rgb.shape[2] in (3, 4):
        rgb = rgb[:, :, :3]
    else:
        raise RuntimeError(f"Output RGB non valido: {rgb.shape}")
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

    raise RuntimeError(f"Metodo non disponibile o non supportato: {method}")


def latlon_to_global_px(lat, lon, zoom):
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * 256.0 * n
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * 256.0 * n
    return x, y


def clamp_int(v, lo, hi):
    return int(max(lo, min(hi, v)))


class BasemapCache:
    def __init__(self, max_items=6):
        self.max_items = max_items
        self._cache = OrderedDict()

    def get(self, key, loader):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        v = loader()
        self._cache[key] = v
        if len(self._cache) > self.max_items:
            self._cache.popitem(last=False)
        return v


def fetch_tile(z, x, y, session):
    url = f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def build_satellite_rgb(bounds_lonlat, zoom):
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

    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = fetch_tile(zoom, tx, ty, session)
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
        self.src_dtm_path = None
        self.src_dsmf_path = None
        self.src_dsml_path = None
        self.src_original_dtm_path = None
        self.src_original_dsmf_path = None
        self.src_original_dsml_path = None

    def load(self, place_name=None, use_preprocessed=False):
        if place_name:
            db_root = get_database_root(self.root)
            if db_root is None:
                self.loaded = False
                self.error = "Cartella Database non trovata (attese: ./Database oppure ./image/Database)."
                return
            base = db_root / place_name
            prepare_inputs_place(base)
            p_dtm_orig = pick_latest_raster(base / "DTM", prefer_preprocessed=False)
            p_f_orig = pick_latest_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=False)
            p_l_orig = pick_latest_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=False)
            if use_preprocessed:
                p_dtm = pick_latest_raster(base / "DTM", prefer_preprocessed=True) or p_dtm_orig
                p_f = pick_latest_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=True) or p_f_orig
                p_l = pick_latest_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=True) or p_l_orig
            else:
                p_dtm, p_f, p_l = p_dtm_orig, p_f_orig, p_l_orig
            area_geojson_path = find_place_geojson(base)
        else:
            prepare_inputs(self.root)
            base = self.root / "image"
            p_dtm_orig = pick_latest_raster(base / "DTM", prefer_preprocessed=False)
            p_f_orig = pick_latest_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=False)
            p_l_orig = pick_latest_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=False)
            if use_preprocessed:
                p_dtm = pick_latest_raster(base / "DTM", prefer_preprocessed=True) or p_dtm_orig
                p_f = pick_latest_from_candidates(base, FIRST_DIR_CANDIDATES, prefer_preprocessed=True) or p_f_orig
                p_l = pick_latest_from_candidates(base, LAST_DIR_CANDIDATES, prefer_preprocessed=True) or p_l_orig
            else:
                p_dtm, p_f, p_l = p_dtm_orig, p_f_orig, p_l_orig
            area_geojson_path = None

        if p_dtm is None or p_f is None or p_l is None:
            self.loaded = False
            if place_name:
                self.error = f"Input mancanti in Database/{place_name}: richieste cartelle DTM, DSM_First (o DSM_Fisrt), DSM_Last."
            else:
                self.error = "Input mancanti: metti zip o raster in image/DTM, image/DSM_First (o DSM_Fisrt), image/DSM_Last."
            return

        dtm, res, prof, _, bounds, crs = load_raster(p_dtm)
        dsmf, _, _, _, _, _ = load_raster(p_f)
        dsml, _, _, _, _, _ = load_raster(p_l)
        tile = {
            "DTM": dtm,
            "DSM_First": dsmf,
            "DSM_Last": dsml,
            "nDSM": dsmf - dtm,
            "First-Last": dsmf - dsml,
            "res": res,
            "profile": prof,
            "bounds": bounds,
            "crs": crs,
        }
        if area_geojson_path:
            tile = clip_tile_to_geojson(tile, Path(area_geojson_path).expanduser().resolve())

        self.dtm = tile["DTM"]
        self.dsmf = tile["DSM_First"]
        self.dsml = tile["DSM_Last"]
        self.ndsm = tile["nDSM"]
        self.diff = tile["First-Last"]
        self.res = tile["res"]
        self.profile = tile["profile"]
        self.bounds = tile["bounds"]
        self.crs = tile["crs"]
        self.area_geojson_path = str(area_geojson_path) if area_geojson_path else None
        self.src_dtm_path = str(p_dtm)
        self.src_dsmf_path = str(p_f)
        self.src_dsml_path = str(p_l)
        self.src_original_dtm_path = str(p_dtm_orig) if p_dtm_orig else None
        self.src_original_dsmf_path = str(p_f_orig) if p_f_orig else None
        self.src_original_dsml_path = str(p_l_orig) if p_l_orig else None

        self.loaded = True
        self.error = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RVT LiDAR Explorer")
        self.geometry("1200x720")
        self.minsize(1150, 750)

        self.root_path = Path(__file__).resolve().parent
        self.data = InputData(self.root_path)
        self.basemap_cache = BasemapCache(max_items=6)
        self.place_name = tk.StringVar(value="")

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
        self.use_preprocessed = tk.BooleanVar(value=False)

        self.param_widgets = {}

        self._update_job = None
        self._pan_state = None
        self._brush_state = None
        self._home_limits = None
        self._last_shape = None
        self.annotation_alpha = None
        self.im_anno = None

        self.brush_on = tk.BooleanVar(value=False)
        self.brush_size = tk.IntVar(value=5)

        self._build_ui()
        self.refresh_places()
        self.reload_inputs()

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

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self, padding=0)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(main, padding=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)

        right_top = ttk.Frame(right, padding=(8, 8, 8, 0))
        right_top.grid(row=0, column=0, sticky="ew")
        right_top.columnconfigure(0, weight=1)
        ttk.Checkbutton(right_top, text="Pennello giallo", variable=self.brush_on, command=self._on_brush_toggle).grid(row=0, column=1, sticky="e")
        ttk.Label(right_top, text="Dim").grid(row=0, column=2, sticky="e", padx=(8, 2))
        self.brush_size_scale = ttk.Scale(right_top, from_=1, to=20, command=lambda v: self.brush_size.set(int(round(float(v)))))
        self.brush_size_scale.grid(row=0, column=3, sticky="e", padx=(0, 8))
        self.brush_size_scale.set(self.brush_size.get())
        ttk.Button(right_top, text="Pulisci segni", command=self.clear_annotations).grid(row=0, column=4, sticky="e", padx=(0, 8))
        ttk.Button(right_top, text="Griglia metodi", command=self.show_methods_grid).grid(row=0, column=5, sticky="e")

        top = ttk.Frame(left)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)
        place_box = ttk.Frame(top)
        place_box.grid(row=0, column=0, sticky="ew")
        place_box.columnconfigure(1, weight=1)
        ttk.Label(place_box, text="Posto").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.place_combo = ttk.Combobox(place_box, textvariable=self.place_name, values=[], state="readonly")
        self.place_combo.grid(row=0, column=1, sticky="ew")
        self.place_combo.bind("<<ComboboxSelected>>", lambda _e: self.reload_inputs())
        ttk.Button(top, text="MASE", command=self.open_mase).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(top, text="GE", command=self.open_ge).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(top, text="Preset Arch", command=self.apply_archaeology_preset).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(top, text="Preset Rett/Fossati", command=self.apply_rectangles_preset).grid(row=0, column=4, padx=(8, 0))

        ds_box = ttk.LabelFrame(left, text="Dataset", padding=8)
        ds_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for i, name in enumerate(["DTM", "DSM_First", "DSM_Last", "nDSM", "First-Last", "Original"]):
            ttk.Radiobutton(ds_box, text=name, value=name, variable=self.dataset, command=lambda: (self.update_param_states(), self.schedule_update())).grid(row=i, column=0, sticky="w")

        basemap_box = ttk.LabelFrame(left, text="Basemap (Satellite)", padding=8)
        basemap_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        basemap_box.columnconfigure(1, weight=1)

        self.basemap_cb = ttk.Checkbutton(basemap_box, text="Basemap", variable=self.basemap_on, command=lambda: (self.update_param_states(), self.schedule_update()))
        self.basemap_cb.grid(row=0, column=0, sticky="w")

        self.basemap_scale = ttk.Scale(basemap_box, from_=0.0, to=1.0, command=lambda v: self._set_float(self.basemap_mix, v))
        self.basemap_scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.basemap_mix_lbl = ttk.Label(basemap_box, text="")
        self.basemap_mix_lbl.grid(row=0, column=2, sticky="e")

        def sync_mix(*_):
            self.basemap_mix_lbl.config(text=f"{float(self.basemap_mix.get()):.2f}")

        self.basemap_mix.trace_add("write", sync_mix)
        sync_mix()
        self.basemap_scale.set(float(self.basemap_mix.get()))

        meth_box = ttk.LabelFrame(left, text="Metodo RVT", padding=8)
        meth_box.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        meth_box.columnconfigure(0, weight=1)
        self.method_combo = ttk.Combobox(meth_box, textvariable=self.method, values=self.available_methods(), state="readonly")
        self.method_combo.grid(row=0, column=0, sticky="ew")
        self.method_combo.bind("<<ComboboxSelected>>", lambda e: (self.update_param_states(), self.schedule_update()))

        par_box = ttk.LabelFrame(left, text="Parametri", padding=8)
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
        ttk.Button(btn_box, text="Export .TIFF", command=self.export_current).grid(row=0, column=0, sticky="ew", pady=(0, 6), padx=(0, 4))
        ttk.Button(btn_box, text="Export PNG", command=self.export_current_view_hq).grid(row=0, column=1, sticky="ew", pady=(0, 6), padx=(4, 0))
        ttk.Checkbutton(
            btn_box,
            text="Base image preprocess",
            variable=self.use_preprocessed,
            command=self.on_toggle_preprocessed,
        ).grid(row=0, column=2, sticky="e", pady=(0, 6), padx=(4, 0))
        self.status = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.status, wraplength=360).grid(row=6, column=0, sticky="ew", pady=(10, 0))

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
        self.status.set("Preset archeologia applicato (DTM + contrasto alto).")

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
        self.status.set("Preset rettangoli/fossati applicato (DTM + microrelief boost).")

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

    def reload_inputs(self):
        self.refresh_places()
        selected = self.place_name.get()
        if not selected:
            self.status.set("Nessun posto trovato in Database.")
            self._show_blank()
            return
        place = selected
        self.data.load(place_name=place, use_preprocessed=bool(self.use_preprocessed.get()))
        if not self.data.loaded:
            self.status.set(self.data.error or "Errore input.")
            self.update_param_states()
            self._show_blank()
            return
        place_txt = f"Database/{place}"
        src_mode = "preprocessato" if self.use_preprocessed.get() else "originale"
        if self.data.area_geojson_path:
            self.status.set(f"OK | sorgente: {place_txt} ({src_mode}) | area: {Path(self.data.area_geojson_path).name}")
        else:
            self.status.set(f"OK | sorgente: {place_txt} ({src_mode})")
        self.update_param_states()
        self.schedule_update()

    def update_param_states(self):
        ds = self.dataset.get()
        is_original = ds == "Original"
        m = self.method.get()

        if is_original:
            self.method_combo.state(["disabled"])
            self.invert_cb.state(["disabled"])
            self.basemap_cb.state(["disabled"])
            self.basemap_scale.state(["disabled"])
        else:
            self.method_combo.state(["!disabled"])
            self.invert_cb.state(["!disabled"])
            self.basemap_cb.state(["!disabled"])
            self.basemap_scale.state(["!disabled"] if self.basemap_on.get() else ["disabled"])

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

    def _satellite(self, w, h):
        bounds_ll = self._bounds_lonlat()
        if bounds_ll is None:
            return None

        for zbm in SAT_ZOOMS_TRY:
            cache_key = ("sat", zbm, w, h, bounds_ll)

            def loader():
                img = build_satellite_rgb(bounds_ll, zbm)
                if img is None:
                    return None
                img = img.resize((w, h), resample=Image.BILINEAR)
                return np.asarray(img, dtype=np.float32) / 255.0

            sat = self.basemap_cache.get(cache_key, loader)
            if sat is not None:
                return sat
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
            messagebox.showerror("Griglia metodi", "Input non caricati.")
            return

        ds = self.dataset.get()
        if ds == "Original":
            messagebox.showerror("Griglia metodi", "Seleziona un dataset diverso da Original.")
            return

        dem = self._get_dataset_array(ds)
        if dem is None:
            messagebox.showerror("Griglia metodi", "Dataset non disponibile.")
            return

        methods = self.available_methods()
        if not methods:
            messagebox.showerror("Griglia metodi", "Nessun metodo RVT disponibile.")
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
            msg = "Impossibile calcolare i metodi."
            if errors:
                msg = f"{msg}\n{errors[0]}"
            messagebox.showerror("Griglia metodi", msg)
            return

        n = len(images)
        cols = int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / cols))

        win = tk.Toplevel(self)
        win.title(f"Griglia metodi | {ds}")
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
            self.status.set(f"Griglia metodi: {len(images)} OK, {len(errors)} errori")

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
                    raise RuntimeError("DTM mancante.")
                h, w = ref.shape
                sat = self._satellite(w, h)
                if sat is None:
                    raise RuntimeError("Satellite non disponibile (rete o area troppo grande).")
                self._draw(sat, None, alpha_over=0.0, reset=False)
                self.status.set("Original: Satellite")
                return

            dem = self._get_dataset_array(ds)
            if dem is None:
                raise RuntimeError("Dataset non disponibile.")

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
                if self.basemap_on.get():
                    base = self._satellite(disp_over.shape[1], disp_over.shape[0])
                    mix = float(self.basemap_mix.get())
                    mix = max(0.0, min(1.0, mix))
                    alpha_over = 1.0 - mix

                self._draw(base, (disp_over, cmap_obj), alpha_over=alpha_over, reset=False)

            mn = float(np.nanmin(out)) if np.isfinite(out).any() else np.nan
            mx = float(np.nanmax(out)) if np.isfinite(out).any() else np.nan
            self.status.set(f"{ds} | {method} | min {mn:.4f} | max {mx:.4f}")

        except Exception as e:
            self.status.set(f"Errore: {e}")
            self._show_blank()

    def _show_blank(self):
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")
        self.ax.figure.patch.set_facecolor("black")
        self.im_base = None
        self.im_over = None
        self.im_anno = None
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
            raise RuntimeError("Input non caricati.")

        ds = self.dataset.get()
        if ds == "Original":
            ref = self.data.dtm
            if ref is None:
                raise RuntimeError("DTM mancante.")
            h, w = ref.shape
            sat = self._satellite(w, h)
            if sat is None:
                raise RuntimeError("Satellite non disponibile (rete o area troppo grande).")
            return self._apply_annotations_rgb(np.asarray(sat, dtype=np.float32))

        dem = self._get_dataset_array(ds)
        if dem is None:
            raise RuntimeError("Dataset non disponibile.")

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

        base = self._satellite(over_rgb.shape[1], over_rgb.shape[0])
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

    def _annotation_rgba(self):
        if self.annotation_alpha is None:
            return None
        if not np.any(self.annotation_alpha > 0):
            return None
        h, w = self.annotation_alpha.shape
        rgba = np.zeros((h, w, 4), dtype=np.float32)
        rgba[:, :, 0] = 1.0
        rgba[:, :, 1] = 1.0
        rgba[:, :, 2] = 0.0
        rgba[:, :, 3] = np.clip(self.annotation_alpha, 0.0, 1.0)
        return rgba

    def _draw_annotation_artist(self):
        rgba = self._annotation_rgba()
        if rgba is None:
            self.im_anno = None
            return
        self.im_anno = self.ax.imshow(rgba, interpolation="nearest", alpha=1.0)

    def _update_annotation_artist_live(self):
        rgba = self._annotation_rgba()
        if rgba is None:
            if self.im_anno is not None:
                try:
                    self.im_anno.remove()
                except Exception:
                    pass
                self.im_anno = None
            self.canvas.draw_idle()
            return
        if self.im_anno is None:
            self.im_anno = self.ax.imshow(rgba, interpolation="nearest", alpha=1.0)
        else:
            self.im_anno.set_data(rgba)
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
        yellow = np.array([1.0, 1.0, 0.0], dtype=np.float32)
        rgb[:, :, :3] = rgb[:, :, :3] * (1.0 - a[:, :, None]) + yellow[None, None, :] * a[:, :, None]
        return np.clip(rgb, 0.0, 1.0)

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
        patch[m] = np.maximum(patch[m], 0.35)

    def _paint_segment(self, x0, y0, x1, y1):
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(steps + 1):
            t = i / steps
            self._paint_at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    def _on_brush_toggle(self):
        try:
            if self.brush_on.get():
                self.canvas.get_tk_widget().configure(cursor="crosshair")
            else:
                self.canvas.get_tk_widget().configure(cursor="")
        except Exception:
            pass

    def clear_annotations(self):
        if self.annotation_alpha is not None:
            self.annotation_alpha.fill(0.0)
        self._update_annotation_artist_live()
        self.status.set("Segni cancellati.")

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

            place = self.place_name.get().replace(" ", "_")
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
            messagebox.showerror("Export", "Export disabilitato su Original (satellite).")
            return
        arr = self._get_dataset_array(ds)
        if arr is None:
            messagebox.showerror("Export", "Dataset non disponibile.")
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

    def preprocess_current_example(self):
        if not self.data.loaded:
            messagebox.showerror("Preprocess", "Input non caricati.")
            return
        srcs = [
            self.data.src_original_dtm_path or self.data.src_dtm_path,
            self.data.src_original_dsmf_path or self.data.src_dsmf_path,
            self.data.src_original_dsml_path or self.data.src_dsml_path,
        ]
        srcs = [Path(p) for p in srcs if p]
        if len(srcs) != 3:
            messagebox.showerror("Preprocess", "File sorgenti non disponibili per l'esempio corrente.")
            return
        try:
            outs = []
            for src in srcs:
                dst = prep_output_path(src)
                if not dst.exists():
                    preprocess_raster_file(src, dst)
                    outs.append(dst)
            return outs
        except Exception as e:
            messagebox.showerror("Preprocess", str(e))
            return None

    def on_toggle_preprocessed(self):
        if self.use_preprocessed.get():
            outs = self.preprocess_current_example()
            if outs is None:
                self.use_preprocessed.set(False)
                return
            if outs:
                self.status.set(f"Preprocess completato: {', '.join([p.name for p in outs])}")
            self.reload_inputs()
            return
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
                raise RuntimeError("Input incompleti per batch.")

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
