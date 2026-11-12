"""Open, georeferenced 3D export of a DTM for research.

Writes, next to each other:

* a point cloud as LAZ (when a LAZ backend is installed) or LAS, and as PLY;
* a terrain mesh as binary glTF (``.glb``);
* a JSON sidecar with source, CRS, bounds, resolution, date, relief
  visualization and vertical exaggeration.

Coordinates stay in the raster CRS. glTF stores float32 and is Y-up, so the
mesh is written relative to an origin (stored in the sidecar and in the glTF
``extras``) with X = east, Y = up, Z = -north. The existing 3D Cloud viewer
is not touched.
"""

from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SIDE_CAR_SCHEMA = "airchgis-3d-export/1"


def _cell_centers(transform, rows, cols):
    jj, ii = np.meshgrid(np.arange(cols), np.arange(rows))
    xs = transform.c + (jj + 0.5) * transform.a + (ii + 0.5) * transform.b
    ys = transform.f + (jj + 0.5) * transform.d + (ii + 0.5) * transform.e
    return xs, ys


def _decimate(dtm, transform, max_side):
    rows, cols = dtm.shape
    step = max(1, int(np.ceil(max(rows, cols) / float(max_side)))) if max_side else 1
    if step == 1:
        return dtm, transform, 1
    from rasterio.transform import Affine

    small = dtm[::step, ::step]
    t = transform * Affine.scale(step, step)
    return small, t, step


def _valid(dtm, nodata):
    z = np.asarray(dtm, dtype=np.float64)
    mask = np.isfinite(z)
    if nodata is not None:
        mask &= z != nodata
    return z, mask


def write_ply(path, xs, ys, zs):
    n = xs.size
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        "comment AIrchGIS 3D export; coordinates in the CRS given in the sidecar JSON\n"
        f"element vertex {n}\nproperty double x\nproperty double y\nproperty double z\nend_header\n"
    )
    data = np.empty(n, dtype=[("x", "<f8"), ("y", "<f8"), ("z", "<f8")])
    data["x"], data["y"], data["z"] = xs, ys, zs
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(data.tobytes())
    return path


def read_ply(path):
    raw = Path(path).read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    data = np.frombuffer(raw[end:], dtype=[("x", "<f8"), ("y", "<f8"), ("z", "<f8")])
    return data["x"], data["y"], data["z"]


def write_las(path, xs, ys, zs, crs=None):
    import laspy

    header = laspy.LasHeader(point_format=3, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([float(xs.min()), float(ys.min()), float(zs.min())])
    if crs is not None:
        try:
            import pyproj

            header.add_crs(pyproj.CRS.from_user_input(crs))
        except Exception:
            pass
    las = laspy.LasData(header)
    las.x, las.y, las.z = xs, ys, zs
    las.classification = np.full(xs.size, 2, dtype=np.uint8)  # ground
    path = Path(path)
    if path.suffix.lower() == ".laz" and not laspy.LazBackend.detect_available():
        path = path.with_suffix(".las")
    las.write(str(path))
    return path


def write_glb(path, dtm, transform, mask, origin, vertical_exaggeration=1.0, extras=None):
    rows, cols = dtm.shape
    xs, ys = _cell_centers(transform, rows, cols)
    z = np.where(mask, dtm, np.nan)
    fill = float(np.nanmin(z)) if np.isfinite(z).any() else 0.0
    z = np.where(mask, z, fill)
    ox, oy, oz = origin
    pos = np.stack(
        [(xs - ox), (z - oz) * float(vertical_exaggeration), -(ys - oy)], axis=-1
    ).reshape(-1, 3).astype("<f4")

    idx = np.arange(rows * cols, dtype=np.uint32).reshape(rows, cols)
    a, b = idx[:-1, :-1], idx[:-1, 1:]
    c, d = idx[1:, :-1], idx[1:, 1:]
    quad_ok = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
    tris = np.concatenate(
        [np.stack([a, c, b], -1)[quad_ok], np.stack([b, c, d], -1)[quad_ok]]
    ).astype("<u4").reshape(-1)

    pos_bytes, idx_bytes = pos.tobytes(), tris.tobytes()
    pad = (4 - len(pos_bytes) % 4) % 4
    binary = pos_bytes + b"\0" * pad + idx_bytes
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    gltf = {
        "asset": {"version": "2.0", "generator": "AIrchGIS export3d"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "terrain", "extras": extras or {}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes) + pad, "byteLength": len(idx_bytes), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": int(pos.shape[0]), "type": "VEC3",
             "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5125, "count": int(tris.size), "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)
    return path, int(tris.size // 3)


def read_glb(path):
    raw = Path(path).read_bytes()
    magic, version, total = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67 and version == 2 and total == len(raw)
    jlen, _ = struct.unpack_from("<II", raw, 12)
    gltf = json.loads(raw[20 : 20 + jlen])
    blen, _ = struct.unpack_from("<II", raw, 20 + jlen)
    binary = raw[28 + jlen : 28 + jlen + blen]
    view = gltf["bufferViews"][0]
    pos = np.frombuffer(binary, dtype="<f4", count=gltf["accessors"][0]["count"] * 3, offset=view["byteOffset"])
    return gltf, pos.reshape(-1, 3)


def export_terrain_3d(
    dtm,
    transform,
    crs,
    output_dir,
    stem="terrain",
    nodata=None,
    formats=("laz", "ply", "glb"),
    vertical_exaggeration=1.0,
    visualization=None,
    source=None,
    acquisition_date=None,
    max_points=2_000_000,
    mesh_max_side=1024,
):
    """Export a DTM as point cloud and mesh with a metadata sidecar. Returns the sidecar dict."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dtm = np.asarray(dtm)
    crs_text = None
    crs_wkt = None
    if crs is not None:
        try:
            import pyproj

            c = pyproj.CRS.from_user_input(crs.to_wkt() if hasattr(crs, "to_wkt") else crs)
            crs_text = c.to_string()
            crs_wkt = c.to_wkt()
        except Exception:
            crs_text = str(crs)

    files = {}
    z, mask = _valid(dtm, nodata)
    xs, ys = _cell_centers(transform, *dtm.shape)
    px, py, pz = xs[mask], ys[mask], z[mask]
    total_points = int(pz.size)
    if total_points == 0:
        raise ValueError("The DTM has no valid cells to export.")
    step = 1
    if max_points and total_points > max_points:
        step = int(np.ceil(total_points / max_points))
        px, py, pz = px[::step], py[::step], pz[::step]
    origin = (float(np.mean(px)), float(np.mean(py)), float(np.min(pz)))

    wanted = {f.lower() for f in formats}
    if wanted & {"laz", "las"}:
        files["point_cloud"] = str(write_las(output_dir / f"{stem}.{'laz' if 'laz' in wanted else 'las'}", px, py, pz, crs_wkt or crs_text))
    if "ply" in wanted:
        files["ply"] = str(write_ply(output_dir / f"{stem}.ply", px, py, pz))
    triangles = 0
    mesh_step = 1
    if wanted & {"glb", "gltf"}:
        small, t_small, mesh_step = _decimate(dtm, transform, mesh_max_side)
        zs, ms = _valid(small, nodata)
        extras = {"crs": crs_text, "origin": origin, "axes": "x=east, y=up, z=-north",
                  "vertical_exaggeration": vertical_exaggeration}
        glb, triangles = write_glb(output_dir / f"{stem}.glb", zs, t_small, ms, origin, vertical_exaggeration, extras)
        files["mesh"] = str(glb)

    res_x, res_y = abs(transform.a), abs(transform.e)
    rows, cols = dtm.shape
    left, top = transform.c, transform.f
    right, bottom = left + cols * transform.a, top + rows * transform.e
    meta = {
        "schema": SIDE_CAR_SCHEMA,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "software": "AIrchGIS",
        "source": source,
        "acquisition_date": acquisition_date,
        "crs": crs_text,
        "crs_wkt": crs_wkt,
        "bounds": {"left": min(left, right), "right": max(left, right), "bottom": min(top, bottom), "top": max(top, bottom)},
        "resolution_m": [res_x, res_y],
        "shape": [rows, cols],
        "elevation_range_m": [float(np.min(z[mask])), float(np.max(z[mask]))],
        "relief_visualization": visualization,
        "vertical_exaggeration": vertical_exaggeration,
        "point_cloud": {"total_valid_cells": total_points, "exported_points": int(pz.size), "sample_step": step},
        "mesh": {"origin": origin, "axes": "x=east, y=up, z=-north (glTF Y-up)", "decimation_step": mesh_step, "triangles": triangles},
        "files": {k: Path(v).name for k, v in files.items()},
        "how_to_open": "LAZ/LAS and PLY: QGIS 3D, CloudCompare. GLB: Blender, QGIS 3D, any glTF viewer; add the origin to return to CRS coordinates.",
    }
    sidecar = output_dir / f"{stem}.json"
    sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    meta["files"]["sidecar"] = sidecar.name
    meta["paths"] = {**files, "sidecar": str(sidecar)}
    return meta


def zip_package(meta, zip_path):
    """Bundle the exported files (for upload to Zenodo or similar)."""
    import zipfile

    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in meta["paths"].values():
            zf.write(p, Path(p).name)
    return zip_path
