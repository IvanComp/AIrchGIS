"""Bring your own data: loaders for rasters, point clouds, multispectral scenes and site lists.

Every screen starts from the user's own files (any country, any sensor, any
CRS). Public archives are an optional second route (see :mod:`airch.sources`).
Nothing here depends on Streamlit; the UI helpers live in
:func:`render_file_input`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from airch.paths import PROJECT_ROOT

WORKSPACE_DIR = PROJECT_ROOT / "workspace"
UPLOAD_DIR = WORKSPACE_DIR / "uploads"

RASTER_EXTS = {".tif", ".tiff", ".vrt", ".img", ".asc", ".jp2"}
POINT_CLOUD_EXTS = {".las", ".laz"}
SITE_EXTS = {".csv", ".txt", ".geojson", ".json", ".gpkg", ".shp", ".kml", ".zip"}


# ---------------------------------------------------------------- generic file handling
def save_upload(name: str, raw: bytes, subdir: str = "misc") -> Path:
    """Store an uploaded file under workspace/uploads, named by content hash (no duplicates)."""
    digest = hashlib.sha1(raw).hexdigest()[:12]
    dest = UPLOAD_DIR / subdir
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{digest}_{Path(name).name}"
    if not path.exists() or path.stat().st_size != len(raw):
        path.write_bytes(raw)
    return path


def resolve_local_paths(text: str, exts=None) -> list[Path]:
    """Paths typed by the user (one per line, files or folders). Avoids copying large files."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip().strip('"').strip("'")
        if not line:
            continue
        p = Path(line).expanduser()
        if p.is_dir():
            out.extend(sorted(q for q in p.rglob("*") if q.is_file() and (exts is None or q.suffix.lower() in exts)))
        elif p.is_file():
            out.append(p)
    return out


# ---------------------------------------------------------------- rasters
def describe_raster(path) -> dict:
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(path) as src:
        crs = src.crs
        info = {
            "path": str(path),
            "crs": crs.to_string() if crs else None,
            "crs_name": crs.to_wkt().split('"')[1] if crs else None,
            "width": src.width,
            "height": src.height,
            "bands": src.count,
            "band_descriptions": [d or "" for d in src.descriptions],
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
            "pixel_size": [abs(src.transform.a), abs(src.transform.e)],
            "bounds": list(src.bounds),
            "units": (crs.linear_units if crs and crs.is_projected else ("degree" if crs else None)),
            "tags": src.tags(),
        }
        if crs is not None:
            try:
                info["bounds_lonlat"] = list(transform_bounds(crs, "EPSG:4326", *src.bounds))
            except Exception:
                info["bounds_lonlat"] = None
    info["pixel_size_m"] = pixel_size_m(info)
    w = info["width"] * (info["pixel_size_m"] or 0)
    h = info["height"] * (info["pixel_size_m"] or 0)
    info["extent_m"] = [w, h]
    return info


def pixel_size_m(info) -> float | None:
    px = info["pixel_size"][0]
    if info.get("units") in ("metre", "meter", "m", "metres", "meters"):
        return float(px)
    if info.get("units") == "degree" and info.get("bounds_lonlat"):
        lat = (info["bounds_lonlat"][1] + info["bounds_lonlat"][3]) / 2.0
        return float(px * 111_320 * max(0.1, np.cos(np.radians(lat))))
    return float(px) if info.get("crs") else None


def plain_description(info) -> str:
    """One sentence a non-specialist can read."""
    px = info.get("pixel_size_m")
    w, h = info.get("extent_m") or (0, 0)
    size = f"{w / 1000:.1f} × {h / 1000:.1f} km" if w > 2000 else f"{w:.0f} × {h:.0f} m"
    crs = info.get("crs_name") or info.get("crs") or "no coordinate system (cannot be placed on the map)"
    bands = f"{info['bands']} band{'s' if info['bands'] > 1 else ''}"
    pix = f"one pixel every {px:.2f} m" if px else "unknown pixel size"
    return f"{bands}, {pix}, covering about {size}, in {crs}."


# ---------------------------------------------------------------- point clouds
def describe_point_cloud(path) -> dict:
    import laspy

    with laspy.open(str(path)) as f:
        h = f.header
        crs = None
        try:
            c = h.parse_crs()
            crs = c.to_string() if c else None
        except Exception:
            pass
        return {
            "path": str(path),
            "points": int(h.point_count),
            "crs": crs,
            "bounds": [float(h.mins[0]), float(h.mins[1]), float(h.maxs[0]), float(h.maxs[1])],
            "z_range": [float(h.mins[2]), float(h.maxs[2])],
            "version": str(h.version),
        }


def rasterize_point_cloud(path, output, resolution=1.0, ground_only=True, crs=None, fill_distance=20) -> Path:
    """Grid a LAS/LAZ point cloud into a DTM (lowest ground point per cell, small gaps filled)."""
    import laspy
    import rasterio
    from rasterio.fill import fillnodata
    from rasterio.transform import from_origin

    las = laspy.read(str(path))
    x, y, z = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)
    if ground_only:
        try:
            cls = np.asarray(las.classification)
            if (cls == 2).any():
                x, y, z = x[cls == 2], y[cls == 2], z[cls == 2]
        except Exception:
            pass
    if x.size == 0:
        raise ValueError("The point cloud has no points to grid.")
    res = float(resolution)
    left, top = np.floor(x.min() / res) * res, np.ceil(y.max() / res) * res
    cols = int(np.ceil((x.max() - left) / res)) + 1
    rows = int(np.ceil((top - y.min()) / res)) + 1
    ci = ((x - left) / res).astype(np.int64).clip(0, cols - 1)
    ri = ((top - y) / res).astype(np.int64).clip(0, rows - 1)
    grid = np.full(rows * cols, np.inf)
    np.minimum.at(grid, ri * cols + ci, z)
    grid = grid.reshape(rows, cols)
    valid = np.isfinite(grid)
    grid[~valid] = -9999.0
    if fill_distance and (~valid).any():
        grid = fillnodata(grid.astype(np.float32), mask=valid.astype(np.uint8), max_search_distance=fill_distance)
    if crs is None:
        try:
            crs = las.header.parse_crs()
        except Exception:
            crs = None
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", height=rows, width=cols, count=1, dtype="float32", nodata=-9999.0,
                   transform=from_origin(left - res / 2, top + res / 2, res, res), compress="deflate")
    if crs is not None:
        profile["crs"] = crs
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(np.asarray(grid, dtype=np.float32), 1)
    return output


# ---------------------------------------------------------------- known sites
_LON = ("lon", "lng", "long", "longitude", "x", "easting", "east")
_LAT = ("lat", "latitude", "y", "northing", "north")
_NAME = ("name", "site", "id", "label", "nome", "title")


@dataclass
class Site:
    name: str
    lon: float
    lat: float
    properties: dict = field(default_factory=dict)


def _pick(header, options):
    low = {h.lower().strip(): h for h in header}
    for o in options:
        if o in low:
            return low[o]
    return None


def read_sites(path, crs=None) -> list[Site]:
    """Read a site list: CSV with lon/lat (or x/y + ``crs``), GeoJSON, GeoPackage, Shapefile or KML."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".zip":
        return _read_ogr_sites(Path("/vsizip/" + str(path)))
    if ext in (".csv", ".txt"):
        sites = _read_csv_sites(path)
        return _reproject_sites(sites, crs) if crs else sites
    if ext in (".geojson", ".json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        src_crs = crs or (data.get("crs") or {}).get("properties", {}).get("name")
        feats = data.get("features", [data])
        sites = []
        for i, f in enumerate(feats):
            g = f.get("geometry") or {}
            pt = _representative_point(g)
            if pt is None:
                continue
            props = f.get("properties") or {}
            name = next((str(props[k]) for k in props if k.lower() in _NAME), f"site {i + 1}")
            sites.append(Site(name, pt[0], pt[1], props))
        return _reproject_sites(sites, src_crs) if src_crs and "4326" not in str(src_crs) and "CRS84" not in str(src_crs) else sites
    return _read_ogr_sites(path)


def _read_csv_sites(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        return []
    lon_k, lat_k, name_k = _pick(rows[0], _LON), _pick(rows[0], _LAT), _pick(rows[0], _NAME)
    if not lon_k or not lat_k:
        raise ValueError("The CSV needs longitude/latitude (or x/y) columns.")
    sites = []
    for i, r in enumerate(rows):
        try:
            lon = float(str(r[lon_k]).replace(",", "."))
            lat = float(str(r[lat_k]).replace(",", "."))
        except (TypeError, ValueError):
            continue
        sites.append(Site(str(r.get(name_k) or f"site {i + 1}") if name_k else f"site {i + 1}", lon, lat, dict(r)))
    return sites


def _representative_point(g):
    t, c = g.get("type"), g.get("coordinates")
    if t == "Point":
        return float(c[0]), float(c[1])
    pts = []

    def walk(x):
        if isinstance(x, (list, tuple)) and x and isinstance(x[0], (int, float)):
            pts.append(x[:2])
        elif isinstance(x, (list, tuple)):
            for y in x:
                walk(y)

    walk(c)
    if not pts:
        return None
    a = np.asarray(pts, dtype=float)
    return float(a[:, 0].mean()), float(a[:, 1].mean())


def _reproject_sites(sites, src_crs):
    if not sites or not src_crs:
        return sites
    from pyproj import Transformer

    tr = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    out = []
    for s in sites:
        lon, lat = tr.transform(s.lon, s.lat)
        out.append(Site(s.name, float(lon), float(lat), s.properties))
    return out


def _read_ogr_sites(path):
    from osgeo import ogr, osr

    ds = ogr.Open(str(path))
    if ds is None and str(path).startswith("/vsizip/"):
        inner = [n for n in __import__("zipfile").ZipFile(str(path)[8:]).namelist() if n.lower().endswith((".shp", ".gpkg", ".geojson", ".kml"))]
        ds = ogr.Open(f"{path}/{inner[0]}") if inner else None
    if ds is None:
        raise ValueError(f"Cannot read {Path(path).name}.")
    layer = ds.GetLayer(0)
    target = osr.SpatialReference()
    target.ImportFromEPSG(4326)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    src = layer.GetSpatialRef()
    tr = None
    if src is not None:
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        tr = osr.CoordinateTransformation(src, target)
    sites = []
    defn = layer.GetLayerDefn()
    fields = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    name_k = _pick(fields, _NAME)
    for i, feat in enumerate(layer):
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        pt = geom.Centroid()
        if tr is not None:
            pt.Transform(tr)
        props = {f: feat.GetField(f) for f in fields}
        sites.append(Site(str(props.get(name_k)) if name_k else f"site {i + 1}", pt.GetX(), pt.GetY(), props))
    return sites


# ---------------------------------------------------------------- multispectral scenes
# Band roles used by the local engine. Positions are 1-based band numbers in a stacked file;
# tokens are the band names used in file names of single-band downloads.
BAND_PRESETS = {
    "Sentinel-2 (B2, B3, B4, B8 stack)": {"positions": {"blue": 1, "green": 2, "red": 3, "nir": 4}, "gsd_m": 10.0},
    "Sentinel-2 (all 12 L2A bands)": {"positions": {"blue": 2, "green": 3, "red": 4, "rededge": 5, "nir": 8, "swir1": 11}, "gsd_m": 10.0,
                                      "tokens": {"blue": "B02", "green": "B03", "red": "B04", "rededge": "B05", "nir": "B08", "swir1": "B11"}},
    "Landsat 8/9 (OLI)": {"positions": {"blue": 2, "green": 3, "red": 4, "nir": 5, "swir1": 6}, "gsd_m": 30.0,
                          "tokens": {"blue": "B2", "green": "B3", "red": "B4", "nir": "B5", "swir1": "B6"}},
    "Landsat 4-7 (TM/ETM+)": {"positions": {"blue": 1, "green": 2, "red": 3, "nir": 4, "swir1": 5}, "gsd_m": 30.0,
                              "tokens": {"blue": "B1", "green": "B2", "red": "B3", "nir": "B4", "swir1": "B5"}},
    "PlanetScope 4-band (B, G, R, NIR)": {"positions": {"blue": 1, "green": 2, "red": 3, "nir": 4}, "gsd_m": 3.0},
    "PlanetScope 8-band": {"positions": {"blue": 2, "green": 4, "red": 6, "rededge": 7, "nir": 8}, "gsd_m": 3.0},
    "Drone / aerial R, G, B, NIR": {"positions": {"red": 1, "green": 2, "blue": 3, "nir": 4}, "gsd_m": None},
    "Drone multispectral (B, G, R, RE, NIR)": {"positions": {"blue": 1, "green": 2, "red": 3, "rededge": 4, "nir": 5}, "gsd_m": None},
    "RGB only (orthophoto)": {"positions": {"red": 1, "green": 2, "blue": 3}, "gsd_m": None},
}
ROLES = ("blue", "green", "red", "rededge", "nir", "swir1")

_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)")
_DESC_ROLES = {
    "blue": ("blue", "b02", "b2 "), "green": ("green", "b03"), "red": ("red", "b04"),
    "rededge": ("red edge", "rededge", "re", "b05"), "nir": ("nir", "near infrared", "b08"),
    "swir1": ("swir1", "swir 1", "b11", "swir"),
}


def parse_date(text) -> date | None:
    m = _DATE_RE.search(str(text))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def roles_from_descriptions(descriptions) -> dict:
    """Guess band roles from band descriptions written in the file, if any."""
    roles = {}
    for i, d in enumerate(descriptions, 1):
        low = (d or "").lower().strip()
        if not low:
            continue
        for role, keys in _DESC_ROLES.items():
            if role not in roles and any(low == k.strip() or low.startswith(k) for k in keys):
                roles[role] = i
                break
    return roles


@dataclass
class Scene:
    name: str
    date: date | None
    bands: dict  # role -> float32 array (reflectance-like, NaN for no data)
    transform: object
    crs: object
    gsd_m: float
    files: list


def load_scene(path, positions: dict, scale=1.0, offset=0.0, scene_date=None) -> Scene:
    """Read one multiband file and return its bands by role."""
    import rasterio

    with rasterio.open(path) as src:
        bands = {}
        for role, idx in positions.items():
            if idx and 1 <= int(idx) <= src.count:
                a = src.read(int(idx)).astype(np.float32)
                if src.nodata is not None:
                    a[a == src.nodata] = np.nan
                bands[role] = a * float(scale) + float(offset)
        info = describe_raster(path)
        return Scene(Path(path).stem, scene_date or parse_date(Path(path).name) or parse_date(src.tags().get("TIFFTAG_DATETIME", "")),
                     bands, src.transform, src.crs, info["pixel_size_m"] or abs(src.transform.a), [str(path)])


_BAND_TOKEN = re.compile(r"(?:^|[_\-.])(B\d{1,2}A?)(?=[_\-.]|$)", re.IGNORECASE)


def group_single_band_files(paths, tokens: dict) -> list[dict]:
    """Group single-band downloads (e.g. ..._B04.tif, ..._SR_B4.TIF) by date into scenes."""
    groups = {}
    want = {v.upper(): k for k, v in tokens.items()}
    for p in paths:
        m = _BAND_TOKEN.search(Path(p).stem)
        if not m:
            continue
        tok = m.group(1).upper()
        tok_norm = re.sub(r"^B0(\d)$", r"B\1", tok)
        role = want.get(tok) or want.get(tok_norm) or want.get(re.sub(r"^B(\d)$", r"B0\1", tok))
        if not role:
            continue
        d = parse_date(Path(p).name)
        groups.setdefault(d, {})[role] = str(p)
    return [{"date": d, "files": files} for d, files in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0]))]


def load_single_band_scene(files: dict, scale=1.0, offset=0.0, scene_date=None) -> Scene:
    """Stack single-band files on the grid of the finest band (others resampled bilinearly)."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    ref_path = min(files.values(), key=lambda p: describe_raster(p)["pixel_size"][0])
    with rasterio.open(ref_path) as ref:
        shape, transform, crs = (ref.height, ref.width), ref.transform, ref.crs
    bands = {}
    for role, p in files.items():
        with rasterio.open(p) as src:
            if (src.height, src.width) == shape and src.transform == transform:
                a = src.read(1).astype(np.float32)
                if src.nodata is not None:
                    a[a == src.nodata] = np.nan
            else:
                a = np.full(shape, np.nan, dtype=np.float32)
                reproject(rasterio.band(src, 1), a, dst_transform=transform, dst_crs=crs,
                          src_nodata=src.nodata, dst_nodata=np.nan, resampling=Resampling.bilinear)
        bands[role] = a * float(scale) + float(offset)
    info = describe_raster(ref_path)
    return Scene(Path(ref_path).stem, scene_date or parse_date(Path(ref_path).name), bands, transform, crs,
                 info["pixel_size_m"] or abs(transform.a), list(files.values()))
