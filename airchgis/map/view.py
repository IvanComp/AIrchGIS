

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MAX_SIDE = 4096
DEM_SIDE = 300


@dataclass
class MapLayer:
    id: str
    name: str
    description: str
    png_b64: str
    bounds: tuple
    visible: bool = True
    opacity: float = 1.0
    meta: dict = field(default_factory=dict)


def _to_lonlat(arrays, transform, crs, max_side=MAX_SIDE, resampling="bilinear"):

    from rasterio.warp import Resampling, calculate_default_transform, reproject

    first = np.asarray(arrays[0], dtype=np.float32)
    h, w = first.shape
    west, north = transform.c, transform.f
    east, south = west + w * transform.a + h * transform.b, north + w * transform.d + h * transform.e
    left, right = min(west, east), max(west, east)
    bottom, top = min(south, north), max(south, north)
    if crs is None or str(crs).upper() in ("EPSG:4326", "OGC:CRS84"):
        dst_t, dw, dh = transform, w, h
        out = [np.asarray(a, dtype=np.float32) for a in arrays]
        b = (left, bottom, right, top)
    else:
        dst_t, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h, left, bottom, right, top)
        scale = max(1.0, max(dw, dh) / float(max_side))
        if scale > 1:
            from affine import Affine

            dw, dh = int(dw / scale), int(dh / scale)
            dst_t = dst_t * Affine.scale(scale)
        out = []
        for a in arrays:
            dst = np.full((dh, dw), np.nan, dtype=np.float32)
            reproject(np.asarray(a, dtype=np.float32), dst, src_transform=transform, src_crs=crs, dst_transform=dst_t,
                      dst_crs="EPSG:4326", src_nodata=np.nan, dst_nodata=np.nan, resampling=getattr(Resampling, resampling))
            out.append(dst)
        b = (dst_t.c, dst_t.f + dh * dst_t.e, dst_t.c + dw * dst_t.a, dst_t.f)
    return out, tuple(float(v) for v in b)


def _png_b64(rgba):
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG", compress_level=3)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def georeference(array, transform, crs, layer_id, name, description="", cmap="gray", visible=True, opacity=1.0,
                 p_low=2.0, p_high=98.0, display_range=None):

    import matplotlib

    a = np.asarray(array, dtype=np.float32)
    if a.ndim == 3:
        bands, bounds = _to_lonlat([a[..., i] for i in range(3)], transform, crs)
        rgba = np.empty(bands[0].shape + (4,), dtype=np.uint8)
        valid = np.ones(bands[0].shape, dtype=bool)
        for i, band in enumerate(bands):
            valid &= np.isfinite(band)
            channel = np.clip(band, 0, 1)
            np.nan_to_num(channel, copy=False)
            channel *= 255
            rgba[..., i] = channel
    else:
        (dst,), bounds = _to_lonlat([a], transform, crs)
        valid = np.isfinite(dst)
        if display_range is not None:
            lo, hi = map(float, display_range)
            if not np.isfinite([lo, hi]).all() or hi <= lo:
                raise ValueError("The display range must contain two finite increasing values.")
        else:
            finite = dst[valid]
            lo, hi = np.percentile(finite, [p_low, p_high]) if finite.size else (0.0, 1.0)
            if finite.size:
                med = float(np.median(finite))
                sigma = 1.4826 * float(np.median(np.abs(finite - med)))
                if sigma > 0:
                    lo, hi = max(lo, med - 3.5 * sigma), min(hi, med + 3.5 * sigma)
        norm = np.clip((dst - lo) / max(hi - lo, 1e-12), 0, 1)
        rgba = matplotlib.colormaps[cmap](np.nan_to_num(norm), bytes=True)
    np.multiply(valid, np.uint8(255), out=rgba[..., 3])
    return MapLayer(layer_id, name, description, _png_b64(rgba), bounds, visible, float(opacity))


def elevation_grid(dem, transform, crs, side=DEM_SIDE):

    (dst,), bounds = _to_lonlat([np.asarray(dem, dtype=np.float32)], transform, crs, max_side=side)
    vals = [None if not np.isfinite(v) else round(float(v), 2) for v in dst.ravel()]
    return {"width": int(dst.shape[1]), "height": int(dst.shape[0]), "bounds": bounds, "values": vals}


def map_html(layers, basemap_tiles=None, elevation=None, height=640, labels=True, terrain=True):

    css = (HERE / "component" / "detectorlab_map.css").read_text(encoding="utf-8")
    js = (HERE / "detectorlab_map.js").read_text(encoding="utf-8")
    template = (HERE / "detectorlab_map.html").read_text(encoding="utf-8")
    config = {
        "layers": [{"id": l.id, "name": l.name, "description": l.description, "image": "data:image/png;base64," + l.png_b64,
                    "bounds": list(l.bounds), "visible": l.visible, "opacity": l.opacity} for l in layers],
        "basemap": basemap_tiles or "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "elevation": elevation,
        "labels": bool(labels),
        "terrain": bool(terrain),
    }
    return (template.replace("__AIRCHGIS_CSS__", css).replace("__AIRCHGIS_JS__", js)
            .replace("__CONFIG__", json.dumps(config).replace("</", "<\\/")).replace("__HEIGHT__", str(int(height))))


def render_map(layers, basemap_tiles=None, elevation=None, height=640, key=None):

    import streamlit.components.v1 as components

    components.html(map_html(layers, basemap_tiles, elevation, height), height=height + 4, scrolling=False)
