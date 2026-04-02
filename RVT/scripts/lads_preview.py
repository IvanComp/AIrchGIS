import argparse
import math

import numpy as np
import rasterio
import rasterio.transform
import rasterio.warp
from matplotlib.figure import Figure

try:
    import laspy
except Exception:
    laspy = None

try:
    import pyproj
except Exception:
    pyproj = None

LADS_TARGET_CRS = "EPSG:32632"
LADS_MAX_POINTS = 85000


def _as_crs_text(crs):
    if crs is None:
        return "sconosciuto"
    try:
        return crs.to_string()
    except Exception:
        return str(crs)


def build_lads_point_cloud(dtm, profile, src_crs, target_crs=LADS_TARGET_CRS, max_points=LADS_MAX_POINTS):
    arr = np.asarray(dtm, dtype=np.float32)
    if arr.ndim != 2:
        raise RuntimeError("Il DTM LADS deve essere mono-banda.")
    if profile is None or profile.get("transform") is None:
        raise RuntimeError("Transform georiferito non disponibile per LADS.")
    if src_crs is None:
        raise RuntimeError("CRS del raster non disponibile per LADS.")

    valid = np.isfinite(arr)
    total_points = int(valid.sum())
    if total_points <= 0:
        raise RuntimeError("Il DTM non contiene celle valide.")

    rows, cols = np.where(valid)
    step = 1
    if max_points is not None and int(max_points) > 0:
        step = max(1, int(math.ceil(total_points / float(max_points))))
    if step > 1:
        rows = rows[::step]
        cols = cols[::step]

    xs, ys = rasterio.transform.xy(profile["transform"], rows.tolist(), cols.tolist(), offset="center")
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    zs = arr[rows, cols].astype(np.float32)

    dst_crs = target_crs or src_crs
    if _as_crs_text(src_crs) != _as_crs_text(dst_crs):
        tx, ty = rasterio.warp.transform(src_crs, dst_crs, xs.tolist(), ys.tolist())
        xs = np.asarray(tx, dtype=np.float64)
        ys = np.asarray(ty, dtype=np.float64)

    origin_x = float(np.nanmin(xs))
    origin_y = float(np.nanmin(ys))
    x_local = (xs - origin_x).astype(np.float32)
    y_local = (ys - origin_y).astype(np.float32)

    return {
        "x": x_local,
        "y": y_local,
        "z": zs,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "source_crs": _as_crs_text(src_crs),
        "target_crs": _as_crs_text(dst_crs),
        "total_points": total_points,
        "preview_points": int(zs.size),
        "sample_step": step,
    }


def build_lads_figure(cloud, title="LADS 3D"):
    fig = Figure(figsize=(10.5, 8.0), dpi=120)
    fig.patch.set_facecolor("black")
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("black")

    x = np.asarray(cloud["x"], dtype=np.float32)
    y = np.asarray(cloud["y"], dtype=np.float32)
    z = np.asarray(cloud["z"], dtype=np.float32)

    point_size = 0.8 if z.size > 50000 else 1.6
    ax.scatter(x, y, z, c=z, cmap="terrain", s=point_size, marker=".", linewidths=0, alpha=0.95)

    x_span = max(1.0, float(np.nanmax(x) - np.nanmin(x)))
    y_span = max(1.0, float(np.nanmax(y) - np.nanmin(y)))
    z_span = max(1.0, float(np.nanmax(z) - np.nanmin(z)))
    try:
        ax.set_box_aspect((x_span, y_span, z_span))
    except Exception:
        pass

    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    y_min = float(np.nanmin(y))
    y_max = float(np.nanmax(y))
    z_min = float(np.nanmin(z))
    z_max = float(np.nanmax(z))
    x_pad = max(1.0, x_span * 0.03)
    y_pad = max(1.0, y_span * 0.03)
    z_pad = max(1.0, z_span * 0.06)
    ax.set_xlim3d(x_min - x_pad, x_max + x_pad)
    ax.set_ylim3d(y_min - y_pad, y_max + y_pad)
    ax.set_zlim3d(z_min - z_pad, z_max + z_pad)

    ax.view_init(elev=34, azim=-63)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    ax.set_axis_off()
    for axis in (getattr(ax, "xaxis", None), getattr(ax, "yaxis", None), getattr(ax, "zaxis", None)):
        if axis is None:
            continue
        try:
            axis.pane.set_visible(False)
        except Exception:
            pass
        try:
            axis.line.set_color((0.0, 0.0, 0.0, 0.0))
        except Exception:
            pass
    return fig


def export_lads_las(dtm, profile, src_crs, output_path, target_crs=LADS_TARGET_CRS):
    if laspy is None:
        raise RuntimeError("Modulo `laspy` non disponibile per esportare .LAS.")
    if pyproj is None:
        raise RuntimeError("Modulo `pyproj` non disponibile per esportare .LAS.")

    cloud = build_lads_point_cloud(dtm, profile, src_crs, target_crs=target_crs, max_points=None)
    xs = np.asarray(cloud["x"], dtype=np.float64) + float(cloud["origin_x"])
    ys = np.asarray(cloud["y"], dtype=np.float64) + float(cloud["origin_y"])
    zs = np.asarray(cloud["z"], dtype=np.float64)

    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.001, 0.001, 0.001], dtype=np.float64)
    header.offsets = np.array([float(np.nanmin(xs)), float(np.nanmin(ys)), float(np.nanmin(zs))], dtype=np.float64)
    try:
        header.add_crs(pyproj.CRS.from_user_input(target_crs or src_crs))
    except Exception:
        pass

    las = laspy.LasData(header)
    las.x = xs
    las.y = ys
    las.z = zs
    try:
        las.classification = np.full(zs.shape[0], 2, dtype=np.uint8)
    except Exception:
        pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    las.write(str(output_path))
    return cloud


def _load_raster_for_cli(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr, src.profile.copy(), src.crs


def main():
    parser = argparse.ArgumentParser(description="Preview LADS 3D da un DTM raster.")
    parser.add_argument("raster_path", help="Path del raster DTM da convertire in point cloud")
    parser.add_argument("--target-crs", default=LADS_TARGET_CRS, help="CRS metrico di destinazione per la preview 3D")
    parser.add_argument("--max-points", type=int, default=LADS_MAX_POINTS, help="Numero massimo di punti da plottare nella preview")
    parser.add_argument("--output", default="", help="PNG di output facoltativo; se omesso salva nulla")
    args = parser.parse_args()

    arr, profile, crs = _load_raster_for_cli(args.raster_path)
    cloud = build_lads_point_cloud(arr, profile, crs, target_crs=args.target_crs, max_points=max(1000, int(args.max_points)))
    fig = build_lads_figure(cloud, title="LADS 3D CLI")
    if args.output:
        fig.savefig(args.output, dpi=140)
        print(args.output)
        return
    print(
        f"LADS pronto | src={cloud['source_crs']} | dst={cloud['target_crs']} | "
        f"punti={cloud['preview_points']}/{cloud['total_points']} | step={cloud['sample_step']}"
    )


if __name__ == "__main__":
    main()
