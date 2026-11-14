"""From heterogeneous LiDAR inputs to an archaeology-ready terrain model.

Two entry points, both registered as tools (so each run is in the provenance script):

- :func:`grid_point_cloud`: LAS/LAZ point cloud -> DTM. Uses the ground class (ASPRS class 2) when the
  file has it, removes isolated outlier points, measures the ground-point density, suggests a cell size
  from it, and interpolates with one of four methods (lowest point, mean, inverse distance weighting,
  linear interpolation on a triangulation).
- :func:`prepare_dtm`: raster DTM -> DTM. Checks the vertical range, fills small interior voids,
  optionally resamples to a coarser cell size, and measures artifacts (banding, spikes) without changing them.

Each function returns a list of steps; every step has a one-line ``note`` and a few ``measures``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

METHODS = {
    "tin": "Linear interpolation on a triangulation of the ground points (TIN)",
    "idw": "Inverse distance weighting of the 8 nearest ground points",
    "mean": "Mean height of the ground points in each cell",
    "min": "Lowest point in each cell",
}
NICE_CELLS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)


def step(name, note, **measures):
    return {"step": name, "note": note, "measures": {k: v for k, v in measures.items() if v is not None}}


def suggest_cell(density):
    """Smallest 'nice' cell size that holds about one ground point on average (cell = 1 / sqrt(density))."""
    if not density or density <= 0:
        return 1.0
    target = 1.0 / np.sqrt(density)
    return float(next((c for c in NICE_CELLS if c >= target * 0.999), NICE_CELLS[-1]))


def _footprint_area(x, y, cell):
    """Area actually covered by points (occupied cells at a coarse cell), not the bounding box."""
    c = max(cell, 1e-6)
    keys = np.unique(np.stack([np.floor(x / c), np.floor(y / c)], axis=1), axis=0)
    return float(len(keys) * c * c)


def read_points(path):
    import laspy

    las = laspy.read(str(path))
    x, y, z = np.asarray(las.x, dtype=np.float64), np.asarray(las.y, dtype=np.float64), np.asarray(las.z, dtype=np.float64)
    try:
        cls = np.asarray(las.classification)
    except Exception:
        cls = None
    try:
        crs = las.header.parse_crs()
    except Exception:
        crs = None
    return x, y, z, cls, crs


def _grid_points(x, y, z, cell, method, left, top, rows, cols):
    ci = ((x - left) / cell).astype(np.int64).clip(0, cols - 1)
    ri = ((top - y) / cell).astype(np.int64).clip(0, rows - 1)
    idx = ri * cols + ci
    if method == "min":
        grid = np.full(rows * cols, np.inf)
        np.minimum.at(grid, idx, z)
        grid[~np.isfinite(grid)] = np.nan
        return grid.reshape(rows, cols)
    sums = np.bincount(idx, weights=z, minlength=rows * cols)
    counts = np.bincount(idx, minlength=rows * cols)
    mean = np.full(rows * cols, np.nan)
    ok = counts > 0
    mean[ok] = sums[ok] / counts[ok]
    if method == "mean":
        return mean.reshape(rows, cols)
    cy, cx = np.divmod(np.arange(rows * cols), cols)
    gx, gy = left + (cx + 0.5) * cell, top - (cy + 0.5) * cell
    if method == "idw":
        from scipy.spatial import cKDTree

        tree = cKDTree(np.column_stack([x, y]))
        k = int(min(8, len(x)))
        d, j = tree.query(np.column_stack([gx, gy]), k=k, distance_upper_bound=6 * cell)
        if k == 1:
            d, j = d[:, None], j[:, None]
        valid = np.isfinite(d)
        w = np.where(valid, 1.0 / np.maximum(d, cell * 1e-3) ** 2, 0.0)
        zz = np.where(valid, z[np.minimum(j, len(z) - 1)], 0.0)
        wsum = w.sum(axis=1)
        out = np.where(wsum > 0, (w * zz).sum(axis=1) / np.maximum(wsum, 1e-30), np.nan)
        return out.reshape(rows, cols)
    if method == "tin":
        from scipy.interpolate import LinearNDInterpolator

        # triangulate the cell means (one point per occupied cell) to keep big clouds fast
        px, py, pz = gx[ok], gy[ok], mean[ok]
        if len(pz) < 3:
            return mean.reshape(rows, cols)
        interp = LinearNDInterpolator(np.column_stack([px, py]), pz)
        out = interp(gx, gy)
        # do not bridge large gaps: keep only cells near data
        from scipy import ndimage

        near = ndimage.binary_dilation(ok.reshape(rows, cols), iterations=6)
        out = out.reshape(rows, cols)
        out[~near] = np.nan
        return out
    raise ValueError(f"Unknown gridding method: {method}. Choose one of {list(METHODS)}.")


def grid_point_cloud(path, output, method="tin", cell=None, ground_only=True, remove_outliers=True, fill_distance=10,
                     crs=None):
    """Point cloud -> DTM GeoTIFF. Returns (output path, steps)."""
    import rasterio
    from rasterio.fill import fillnodata
    from rasterio.transform import from_origin

    x, y, z, cls, file_crs = read_points(path)
    crs = crs or file_crs
    steps = []
    n_total = len(x)
    if n_total == 0:
        raise ValueError("The point cloud is empty.")
    has_ground = cls is not None and (cls == 2).any()
    if ground_only and has_ground:
        keep = cls == 2
        steps.append(step("ground", f"Ground class found: {int(keep.sum()):,} of {n_total:,} points are ground (class 2) and are used.",
                          points=n_total, ground_points=int(keep.sum()), ground_share=round(float(keep.mean()), 3)))
        x, y, z = x[keep], y[keep], z[keep]
    elif ground_only:
        steps.append(step("ground", "No ground class in the file: all points are used and the lowest values dominate "
                          "where the method allows. A ground filter (e.g. CSF or SMRF) would be needed for vegetated areas.",
                          points=n_total, ground_points=None, ground_share=None))
    else:
        steps.append(step("ground", f"All {n_total:,} points are used (ground class ignored).", points=n_total))
    if remove_outliers and len(x) > 16:
        from airchgis.enhance.points import outlier_mask

        out = outlier_mask(np.column_stack([x, y, z]))
        steps.append(step("outliers", f"{int(out.sum()):,} isolated points removed (statistical outlier removal, 8 neighbours, 2.5 sigma).",
                          removed=int(out.sum()), removed_share=round(float(out.mean()), 4)))
        x, y, z = x[~out], y[~out], z[~out]
    area = _footprint_area(x, y, 5.0)
    density = len(x) / area if area > 0 else 0.0
    suggested = suggest_cell(density)
    cell = float(cell) if cell else suggested
    steps.append(step("density", f"Ground-point density {density:.1f} points/m² over {area / 1e4:.2f} ha: suggested cell "
                      f"size {suggested:g} m{'' if cell == suggested else f', using {cell:g} m as requested'}.",
                      density_pts_m2=round(density, 2), area_ha=round(area / 1e4, 3), suggested_cell_m=suggested, cell_m=cell))
    left, top = np.floor(x.min() / cell) * cell, np.ceil(y.max() / cell) * cell
    cols = int(np.ceil((x.max() - left) / cell)) + 1
    rows = int(np.ceil((top - y.min()) / cell)) + 1
    if rows * cols > 400_000_000:
        raise ValueError(f"A {cell:g} m grid of this cloud would have {rows * cols / 1e6:.0f} million cells; use a larger cell size.")
    grid = _grid_points(x, y, z, cell, method, left, top, rows, cols)
    empty = ~np.isfinite(grid)
    filled = 0
    if fill_distance and empty.any() and (~empty).any():
        before = empty.copy()
        g = fillnodata(np.where(empty, 0, grid).astype(np.float32), mask=(~empty).astype(np.uint8),
                       max_search_distance=float(fill_distance))
        g = g.astype(np.float64)
        from scipy import ndimage

        # fillnodata extrapolates everywhere within the distance; keep only gaps inside the data footprint
        footprint = ndimage.binary_closing(~before, iterations=int(fill_distance))
        grid = np.where(before & footprint, g, grid)
        filled = int((before & footprint & np.isfinite(grid)).sum())
    steps.append(step("interpolation", f"{METHODS[method]} at {cell:g} m: {rows} × {cols} cells, "
                      f"{100 * empty.mean():.1f}% without points, {filled:,} gap cells filled.",
                      method=method, rows=rows, cols=cols, empty_share=round(float(empty.mean()), 4), filled_cells=filled))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", height=rows, width=cols, count=1, dtype="float32", nodata=-9999.0,
                   transform=from_origin(left, top, cell, cell), compress="deflate")
    if crs is not None:
        profile["crs"] = crs
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(np.where(np.isfinite(grid), grid, -9999.0).astype(np.float32), 1)
    if crs is None:
        steps.append(step("crs", "The file has no coordinate system: the terrain cannot be placed on the map until one is set."))
    return output, steps


def check_vertical(dem):
    """Plain-language check of the elevation values (units and plausibility)."""
    v = np.asarray(dem, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return step("vertical", "No valid elevations.", valid_share=0.0)
    lo, hi = float(np.percentile(v, 0.5)), float(np.percentile(v, 99.5))
    note = f"Elevations from {lo:.1f} to {hi:.1f} (assumed metres)."
    if hi > 9000 or lo < -500:
        note += " These values are outside the range of terrain on Earth: check the vertical units (feet or centimetres?)."
    elif hi - lo < 0.5:
        note += " The relief is almost flat: check that this is a terrain model and not an index or a mask."
    return step("vertical", note, min_m=round(lo, 2), max_m=round(hi, 2))


def resample(dem, transform, cell, method="average"):
    """Resample a terrain model to a coarser cell (average of the finer cells by default)."""
    from affine import Affine
    from rasterio.warp import Resampling, reproject

    res = abs(transform.a)
    factor = cell / res
    h, w = dem.shape
    dh, dw = max(1, int(round(h / factor))), max(1, int(round(w / factor)))
    dst_t = transform * Affine.scale(w / dw, h / dh)
    out = np.full((dh, dw), np.nan, dtype=np.float32)
    reproject(np.asarray(dem, dtype=np.float32), out, src_transform=transform, dst_transform=dst_t, src_crs="EPSG:3857",
              dst_crs="EPSG:3857", src_nodata=np.nan, dst_nodata=np.nan, resampling=getattr(Resampling, method))
    return out, dst_t


def prepare_dtm(dem, transform, fill_voids=True, cell=None, max_void_m2=400.0):
    """Raster DTM -> DTM ready for relief visualization. Returns (array, transform, steps)."""
    from airchgis.enhance import clean, metrics

    steps = [check_vertical(dem)]
    a = np.asarray(dem, dtype=np.float64)
    res = abs(transform.a)
    if cell and cell > res * 1.01:
        a, transform = resample(a, transform, float(cell))
        a = a.astype(np.float64)
        steps.append(step("resample", f"Resampled from {res:.2f} m to {cell:g} m cells (average of the finer cells).",
                          from_cell_m=round(res, 3), cell_m=float(cell)))
        res = abs(transform.a)
    if fill_voids:
        # only small gaps (up to about 400 m²): larger ones are usually buildings or water, not missing ground
        a, rep = clean.fill_voids(a, max_void_px=max(4, int(round(max_void_m2 / (res * res)))))
        steps.append(step("voids", rep["note"], void_share_before=round(rep["before"], 4), void_share_after=round(rep["after"], 4),
                          filled_cells=rep.get("pixels_filled", 0)))
    else:
        steps.append(step("voids", f"Voids left as they are ({100 * metrics.void_fraction(a):.1f}% of the cells).",
                          void_share=round(metrics.void_fraction(a), 4)))
    share, _ = clean.stripe_energy(a)
    spikes = metrics.spike_fraction(a)
    note = f"Artifact check (no change made): periodic banding {100 * share:.1f}% of the fine detail, spikes and pits {100 * spikes:.2f}% of the cells."
    if share > 0.05:
        note += " Banding is visible: relief views may show stripes that are not on the ground."
    steps.append(step("artifacts", note, banding_share=round(share, 4), spike_share=round(spikes, 4)))
    return a.astype(np.float32), transform, steps
