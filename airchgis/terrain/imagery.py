from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
import requests
from scipy.ndimage import map_coordinates

from airchgis.data_input import WORKSPACE_DIR


ATTRIBUTION = "© Esri, Maxar, Earthstar Geographics"
HALF_WORLD = 20037508.342789244


def _tile(template, zoom, x, y, cache_dir):
    url = template.format(z=zoom, x=x, y=y)
    path = Path(cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + ".png")
    if path.exists():
        try:
            with Image.open(path) as image:
                return np.asarray(image.convert("RGB").resize((256, 256))).copy()
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
    response = requests.get(url, timeout=10, headers={"User-Agent": "AIrchGIS/1.0"})
    response.raise_for_status()
    with Image.open(io.BytesIO(response.content)) as image:
        image = image.convert("RGB").resize((256, 256))
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")
        return np.asarray(image).copy()


def drape_imagery(profile, crs, shape, grid, template, cache_dir=None, tile_loader=None):
    step = int(grid["sample_step"])
    rows = np.unique(np.append(np.arange(0, shape[0], step), shape[0] - 1))
    cols = np.unique(np.append(np.arange(0, shape[1], step), shape[1] - 1))
    rr, cc = np.meshgrid(rows + .5, cols + .5, indexing="ij")
    t = profile["transform"]
    x, y = t.a * cc + t.b * rr + t.c, t.d * cc + t.e * rr + t.f
    mx, my = Transformer.from_crs(crs, "EPSG:3857", always_xy=True).transform(x, y)
    if not np.isfinite(mx).all() or not np.isfinite(my).all() or np.abs(my).max() > HALF_WORLD:
        raise ValueError("Satellite imagery is unavailable for this terrain location.")
    spacing = max(float(np.median(np.hypot(np.diff(mx, axis=1), np.diff(my, axis=1)))),
                  float(np.median(np.hypot(np.diff(mx, axis=0), np.diff(my, axis=0)))), .01)
    zoom = min(19, max(0, math.ceil(math.log2(2 * HALF_WORLD / (256 * spacing)))))
    while True:
        count = 2 ** zoom
        gx = np.clip((mx + HALF_WORLD) / (2 * HALF_WORLD) * count * 256, 0, count * 256 - 1)
        gy = np.clip((HALF_WORLD - my) / (2 * HALF_WORLD) * count * 256, 0, count * 256 - 1)
        x0, x1 = int(gx.min() // 256), int(gx.max() // 256)
        y0, y1 = int(gy.min() // 256), int(gy.max() // 256)
        if (x1 - x0 + 1) * (y1 - y0 + 1) <= 64 or zoom == 0:
            break
        zoom -= 1
    cache_dir = cache_dir or WORKSPACE_DIR / "cache" / "3d_imagery"
    loader = tile_loader or (lambda z, tx, ty: _tile(template, z, tx, ty, cache_dir))
    coords = [(tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]
    with ThreadPoolExecutor(max_workers=min(8, len(coords))) as pool:
        tiles = list(pool.map(lambda xy: loader(zoom, *xy), coords))
    mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256, 3), dtype=np.uint8)
    for (tx, ty), tile in zip(coords, tiles):
        if tile is None or np.shape(tile) != (256, 256, 3):
            raise ValueError("Some satellite imagery tiles could not be loaded.")
        mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = tile
    sample = np.stack([gy - y0 * 256 - .5, gx - x0 * 256 - .5])
    rgb = np.stack([map_coordinates(mosaic[..., band], sample, order=1, mode="nearest") for band in range(3)], axis=-1)
    valid = np.asarray(grid["valid"], dtype=bool)
    if rgb.shape[:2] != valid.shape:
        raise ValueError("Satellite imagery does not match the 3D terrain grid.")
    rgb[~valid] = 0
    return rgb.astype(np.uint8)
