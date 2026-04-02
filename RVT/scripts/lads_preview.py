import argparse
import base64
import json
import math
import struct
from collections import deque
from html import escape
from pathlib import Path

import numpy as np
import rasterio
import rasterio.transform
import rasterio.warp
from matplotlib.figure import Figure
from matplotlib import colormaps

try:
    import laspy
except Exception:
    laspy = None

try:
    import pyproj
except Exception:
    pyproj = None

try:
    from scipy.ndimage import gaussian_filter, label as ndi_label
except Exception:
    gaussian_filter = None
    ndi_label = None

LADS_TARGET_CRS = "EPSG:32632"
LADS_MAX_POINTS = 85000
LADS_BROWSER_MAX_SIDE = 1400
LADS_Z_EXAGGERATION = 2.5
CLOUD_PREPROCESS_PROFILES = {
    "original": {
        "label": "Original",
        "description": "Mostra il terreno com'e, senza effetti aggiuntivi. E la vista piu fedele al dato originale.",
        "sanitize": False,
        "sigma": 0.0,
        "blend": 0.0,
        "passes": 0,
        "render_mode": "mesh",
        "flat_shading": False,
        "wireframe_overlay": False,
        "mesh_opacity": 1.0,
        "relief_sigma": 0.0,
        "relief_gain": 1.0,
        "show_points": False,
        "point_stride": 1,
        "point_size": 0.0,
        "point_opacity": 0.0,
    },
    "cloud1": {
        "label": "Cloud 1",
        "description": "Mostra solo i punti del terreno. Ti fa vedere il dato grezzo e la sua grana reale, senza unirlo in una superficie continua.",
        "sanitize": False,
        "sigma": 0.0,
        "blend": 0.0,
        "passes": 0,
        "render_mode": "points",
        "flat_shading": False,
        "wireframe_overlay": False,
        "mesh_opacity": 0.0,
        "relief_sigma": 0.0,
        "relief_gain": 1.0,
        "show_points": True,
        "point_stride": 1,
        "point_size": 1.95,
        "point_opacity": 0.96,
    },
    "cloud2": {
        "label": "Cloud 2",
        "description": "Unisce i punti in una superficie continua e lascia vedere anche la trama della superficie. Di solito rende il terreno piu leggibile e ordinato.",
        "sanitize": True,
        "sigma": 0.0,
        "blend": 0.0,
        "passes": 0,
        "render_mode": "mesh_wire",
        "flat_shading": True,
        "wireframe_overlay": True,
        "mesh_opacity": 0.92,
        "relief_sigma": 0.0,
        "relief_gain": 1.0,
        "show_points": True,
        "point_stride": 2,
        "point_size": 1.35,
        "point_opacity": 0.42,
    },
    "cloud3": {
        "label": "Cloud 3",
        "description": "Spinge in evidenza avvallamenti, gobbe e piccoli segni del terreno. E utile per cercare anomalie, ma puo deformare un po' la forma reale.",
        "sanitize": True,
        "sigma": 0.0,
        "blend": 0.0,
        "passes": 0,
        "render_mode": "relief_mesh",
        "flat_shading": False,
        "wireframe_overlay": False,
        "mesh_opacity": 1.0,
        "relief_sigma": 18.0,
        "relief_gain": 4.0,
        "show_points": True,
        "point_stride": 2,
        "point_size": 1.15,
        "point_opacity": 0.26,
    },
}


def _as_crs_text(crs):
    if crs is None:
        return "sconosciuto"
    try:
        return crs.to_string()
    except Exception:
        return str(crs)


def _sanitize_surface_for_lads(dtm):
    arr = np.asarray(dtm, dtype=np.float32).copy()
    finite = np.isfinite(arr)
    if finite.sum() < 16:
        return arr
    vals = arr[finite]
    lo = float(np.nanmin(vals))
    eps = max(1e-4, abs(lo) * 1e-6)
    q10 = float(np.nanpercentile(vals, 10.0))
    q25 = float(np.nanpercentile(vals, 25.0))
    q50 = float(np.nanpercentile(vals, 50.0))
    if q10 <= lo + eps and q25 <= lo + eps and (q50 - lo) >= 80.0:
        arr[np.abs(arr - lo) <= eps] = np.nan
    return arr


def _box_blur_nan(arr):
    pad = np.pad(arr, 1, mode="edge")
    mask = np.isfinite(pad).astype(np.float32)
    vals = np.where(np.isfinite(pad), pad, 0.0).astype(np.float32)
    total = np.zeros(arr.shape, dtype=np.float32)
    weight = np.zeros(arr.shape, dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            total += vals[dy : dy + arr.shape[0], dx : dx + arr.shape[1]]
            weight += mask[dy : dy + arr.shape[0], dx : dx + arr.shape[1]]
    out = np.full(arr.shape, np.nan, dtype=np.float32)
    ok = weight > 1e-6
    out[ok] = total[ok] / weight[ok]
    return out


def _gaussian_blur_nan(arr, sigma):
    values = np.asarray(arr, dtype=np.float32)
    if sigma is None or float(sigma) <= 0:
        return values.copy()
    valid = np.isfinite(values)
    if not valid.any():
        return values.copy()
    filled = np.where(valid, values, 0.0).astype(np.float32)
    weights = valid.astype(np.float32)
    if gaussian_filter is not None:
        num = gaussian_filter(filled, sigma=float(sigma), mode="nearest")
        den = gaussian_filter(weights, sigma=float(sigma), mode="nearest")
        out = np.full(values.shape, np.nan, dtype=np.float32)
        ok = den > 1e-6
        out[ok] = num[ok] / den[ok]
        return out
    passes = max(1, int(round(float(sigma))))
    out = values.copy()
    for _ in range(passes):
        out = _box_blur_nan(out)
    return out


def _soft_smooth_surface(arr, sigma=0.0, blend=0.0, passes=0):
    out = np.asarray(arr, dtype=np.float32).copy()
    if passes <= 0 or blend <= 0.0:
        return out
    for _ in range(int(passes)):
        valid = np.isfinite(out)
        if not valid.any():
            return out
        filled = np.where(valid, out, 0.0).astype(np.float32)
        weights = valid.astype(np.float32)
        if gaussian_filter is not None and sigma and float(sigma) > 0:
            num = gaussian_filter(filled, sigma=float(sigma), mode="nearest")
            den = gaussian_filter(weights, sigma=float(sigma), mode="nearest")
            smooth = np.full(out.shape, np.nan, dtype=np.float32)
            ok = den > 1e-6
            smooth[ok] = num[ok] / den[ok]
        else:
            smooth = _box_blur_nan(out)
        mix = np.where(valid & np.isfinite(smooth), smooth, out)
        out = np.where(valid, out * (1.0 - float(blend)) + mix * float(blend), np.nan).astype(np.float32)
    return out


def _enhance_local_relief(arr, sigma=12.0, gain=3.0):
    values = np.asarray(arr, dtype=np.float32)
    valid = np.isfinite(values)
    if not valid.any():
        return values.copy(), np.full(values.shape, np.nan, dtype=np.float32)
    trend = _gaussian_blur_nan(values, sigma=float(sigma))
    residual = np.where(valid & np.isfinite(trend), values - trend, np.nan).astype(np.float32)
    enhanced = np.where(valid & np.isfinite(trend), trend + residual * float(gain), np.nan).astype(np.float32)
    return enhanced, residual


def _label_components(mask):
    arr = np.asarray(mask, dtype=bool)
    if not arr.any():
        return np.zeros(arr.shape, dtype=np.int32), 0
    if ndi_label is not None:
        labels, n = ndi_label(arr.astype(np.uint8), structure=np.ones((3, 3), dtype=np.uint8))
        return labels.astype(np.int32, copy=False), int(n)

    h, w = arr.shape
    labels = np.zeros((h, w), dtype=np.int32)
    label_id = 0
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]
    starts = np.argwhere(arr)
    for r0, c0 in starts:
        if labels[r0, c0] != 0:
            continue
        label_id += 1
        queue = deque([(int(r0), int(c0))])
        labels[r0, c0] = label_id
        while queue:
            r, c = queue.popleft()
            for dr, dc in neighbors:
                rr = r + dr
                cc = c + dc
                if rr < 0 or cc < 0 or rr >= h or cc >= w:
                    continue
                if not arr[rr, cc] or labels[rr, cc] != 0:
                    continue
                labels[rr, cc] = label_id
                queue.append((rr, cc))
    return labels, label_id


def _principal_shape_metrics(xs, ys):
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    if x.size == 0:
        return 0.0, 0.0, 1.0, 0.0
    if x.size == 1:
        return 0.0, 0.0, 1.0, 0.0
    pts = np.column_stack([x, y])
    center = np.nanmean(pts, axis=0)
    centered = pts - center
    x_span = float(np.nanmax(x) - np.nanmin(x))
    y_span = float(np.nanmax(y) - np.nanmin(y))
    if centered.shape[0] < 3 or np.allclose(centered, 0.0):
        length = max(x_span, y_span)
        width = max(1e-3, min(x_span, y_span))
        ratio = float(length / max(width, 1e-3))
        angle = 0.0 if x_span >= y_span else 90.0
        return float(length), float(width), ratio, angle

    cov = np.cov(centered, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    basis = eigvecs[:, order]
    proj = centered @ basis
    length = float(np.nanpercentile(proj[:, 0], 95.0) - np.nanpercentile(proj[:, 0], 5.0))
    width = float(np.nanpercentile(proj[:, 1], 95.0) - np.nanpercentile(proj[:, 1], 5.0))
    length = max(length, max(x_span, y_span, 1e-3))
    width = max(width, min(x_span, y_span, 1e-3))
    ratio = float(length / max(width, 1e-3))
    angle = (math.degrees(math.atan2(float(basis[1, 0]), float(basis[0, 0]))) + 180.0) % 180.0
    return float(length), float(width), ratio, float(angle)


def _binary_perimeter(mask):
    arr = np.asarray(mask, dtype=bool)
    if not arr.any():
        return np.zeros(arr.shape, dtype=bool)
    h, w = arr.shape
    padded = np.pad(arr, 1, mode="constant", constant_values=False)
    eroded = np.ones((h, w), dtype=bool)
    for dy in range(3):
        for dx in range(3):
            eroded &= padded[dy : dy + h, dx : dx + w]
    return arr & ~eroded


def _component_shape_scores(mask, x_arr, y_arr, area_m2, length_m, width_m, ratio):
    xs = np.asarray(x_arr[mask], dtype=np.float64)
    ys = np.asarray(y_arr[mask], dtype=np.float64)
    center_x = float(np.nanmean(xs)) if xs.size else 0.0
    center_y = float(np.nanmean(ys)) if ys.size else 0.0
    bbox_area = max(1e-3, float(length_m * width_m))
    occupancy = float(area_m2 / bbox_area)

    perimeter = _binary_perimeter(mask)
    px = np.asarray(x_arr[perimeter], dtype=np.float64)
    py = np.asarray(y_arr[perimeter], dtype=np.float64)
    radius_mean = 0.0
    radial_std_norm = 1.0
    thickness_ratio = 1.0
    if px.size >= 8:
        radial = np.hypot(px - center_x, py - center_y)
        radius_mean = float(np.nanmedian(radial))
        if radius_mean > 1e-3:
            radial_std_norm = float(np.nanstd(radial) / radius_mean)
            thickness_est = float(area_m2 / max(2.0 * math.pi * radius_mean, 1e-3))
            thickness_ratio = float(thickness_est / radius_mean)

    line_ratio = max(0.0, min(1.0, (ratio - 2.6) / 3.4))
    line_length = max(0.0, min(1.0, (length_m - 10.0) / 36.0))
    line_width = 1.0 if width_m <= 18.0 else max(0.0, 1.0 - (width_m - 18.0) / 18.0)
    line_score = line_ratio * max(0.35, line_length) * line_width

    ring_ratio = max(0.0, 1.0 - abs(ratio - 1.0) / 0.75)
    ring_radial = max(0.0, 1.0 - radial_std_norm / 0.42)
    ring_occupancy = 1.0 if 0.08 <= occupancy <= 0.58 else max(0.0, 1.0 - abs(occupancy - 0.33) / 0.35)
    ring_thickness = max(0.0, 1.0 - thickness_ratio / 0.72)
    ring_size = max(0.0, min(1.0, (radius_mean - 5.0) / 22.0))
    ring_score = ring_ratio * ring_radial * ring_occupancy * max(0.35, ring_thickness) * max(0.35, ring_size)

    regular_ratio = max(0.0, 1.0 - abs(ratio - 1.5) / 1.0)
    regular_occupancy = 1.0 if 0.28 <= occupancy <= 0.88 else max(0.0, 1.0 - abs(occupancy - 0.58) / 0.38)
    regular_size = max(0.0, min(1.0, (max(length_m, width_m) - 9.0) / 28.0))
    regular_score = regular_ratio * regular_occupancy * regular_size

    shape_scores = {
        "linear": float(line_score * 1.12),
        "enclosure": float(ring_score * 1.25),
        "regular": float(regular_score * 0.92),
    }
    best_shape = max(shape_scores, key=shape_scores.get)
    best_score = float(shape_scores[best_shape])
    return {
        "center_x": center_x,
        "center_y": center_y,
        "occupancy": float(occupancy),
        "radius_mean": float(radius_mean),
        "radial_std_norm": float(radial_std_norm),
        "shape_scores": shape_scores,
        "shape": str(best_shape),
        "shape_score": best_score,
    }


def _archaeology_label(kind, shape):
    if shape == "linear":
        if kind == "negative":
            return (
                "Possibile fossato o linea artificiale",
                "Dislivello lineare abbastanza continuo. Potrebbe essere un fossato, un bordo, una strada antica o un limite di terreno.",
            )
        return (
            "Possibile argine o linea rialzata",
            "Rialzo lineare abbastanza continuo. Potrebbe essere un argine, un terrapieno o il margine di una struttura.",
        )
    if shape == "enclosure":
        if kind == "negative":
            return (
                "Possibile recinto o fossato chiuso",
                "Forma chiusa o semicircolare con dislivello continuo. Potrebbe ricordare una cinta, un recinto o un fossato ad anello.",
            )
        return (
            "Possibile cinta o terrapieno chiuso",
            "Forma chiusa o quasi chiusa in rilievo. Potrebbe ricordare una cinta, un terrapieno o un perimetro artificiale.",
        )
    return (
        "Possibile struttura regolare",
        "Forma abbastanza ordinata e continua rispetto al contesto. Potrebbe valere un controllo per capire se ha origine artificiale.",
    )


def _score_to_confidence(score):
    if score >= 2.6:
        return "alta"
    if score >= 1.7:
        return "media"
    return "bassa"


def detect_archaeology_candidates(x, y, z_source, z_display, valid, max_items=8):
    valid_mask = np.asarray(valid, dtype=bool)
    if not valid_mask.any():
        return []

    x_arr = np.asarray(x, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.float32)
    z_base = np.asarray(z_source, dtype=np.float32)
    z_vis = np.asarray(z_display, dtype=np.float32)
    col_step, row_step = _grid_spacing(x_arr, y_arr)
    cell_area = max(1e-3, float(col_step * row_step))

    sigma = float(np.clip(min(z_base.shape) / 140.0, 3.0, 8.0))
    trend = _gaussian_blur_nan(z_base, sigma=sigma)
    residual = np.where(valid_mask & np.isfinite(trend), z_base - trend, np.nan).astype(np.float32)
    if not np.isfinite(residual[valid_mask]).any():
        return []

    resid_vals = np.abs(residual[valid_mask])
    threshold = max(
        0.15,
        float(np.nanpercentile(resid_vals, 90.0)),
        float(np.nanstd(residual[valid_mask]) * 0.98),
    )
    if not np.isfinite(threshold) or threshold <= 0:
        return []

    results = []
    min_cells = max(5, int(round(5.0 / cell_area)))
    max_area = 6500.0
    component_specs = [
        ("positive", residual >= threshold),
        ("negative", residual <= -threshold),
    ]
    for kind, comp_mask in component_specs:
        labels, n_labels = _label_components(comp_mask & valid_mask)
        for label_id in range(1, n_labels + 1):
            mask = labels == label_id
            cell_count = int(mask.sum())
            if cell_count < min_cells:
                continue
            area_m2 = float(cell_count * cell_area)
            if area_m2 < 4.0 or area_m2 > max_area:
                continue

            comp_resid = residual[mask]
            mean_relief = float(np.nanmean(comp_resid))
            peak_relief = float(np.nanmax(comp_resid) if kind == "positive" else np.nanmin(comp_resid))
            relief_strength = abs(peak_relief if abs(peak_relief) > abs(mean_relief) else mean_relief)
            if relief_strength < threshold:
                continue

            xs = x_arr[mask]
            ys = y_arr[mask]
            length_m, width_m, ratio, angle_deg = _principal_shape_metrics(xs, ys)
            shape_info = _component_shape_scores(mask, x_arr, y_arr, area_m2, length_m, width_m, ratio)
            shape = shape_info["shape"]
            shape_score = float(shape_info["shape_score"])
            if shape == "linear" and shape_score < 0.18:
                continue
            if shape == "enclosure" and shape_score < 0.16:
                continue
            if shape == "regular" and shape_score < 0.22:
                continue
            title, summary = _archaeology_label(kind, shape)

            rr, cc = np.where(mask)
            if shape == "linear":
                focus_idx = int(np.nanargmax(np.abs(comp_resid)))
                fr = int(rr[focus_idx])
                fc = int(cc[focus_idx])
                focus_x = float(x_arr[fr, fc])
                focus_y = float(y_arr[fr, fc])
                focus_z = float(z_vis[fr, fc])
            else:
                center_dist = (x_arr[mask] - float(shape_info["center_x"])) ** 2 + (y_arr[mask] - float(shape_info["center_y"])) ** 2
                center_idx = int(np.nanargmin(center_dist))
                fr = int(rr[center_idx])
                fc = int(cc[center_idx])
                focus_x = float(shape_info["center_x"])
                focus_y = float(shape_info["center_y"])
                focus_z = float(np.nanmedian(z_vis[mask]))

            score = abs(mean_relief) / max(threshold, 1e-6)
            score *= min(1.8, max(0.75, math.log1p(area_m2) / 2.4))
            score *= (1.0 + shape_score * 1.25)
            if shape == "linear" and ratio >= 4.0:
                score *= 1.10
            if shape == "enclosure":
                score *= 1.18

            results.append(
                {
                    "title": title,
                    "summary": summary,
                    "kind": kind,
                    "confidence": _score_to_confidence(score),
                    "score": float(score),
                    "shape": str(shape),
                    "x": focus_x,
                    "y": focus_y,
                    "z": focus_z,
                    "area_m2": float(area_m2),
                    "length_m": float(length_m),
                    "width_m": float(width_m),
                    "relief_m": float(mean_relief),
                    "orientation_deg": float(angle_deg),
                    "shape_score": float(shape_score),
                }
            )

    if not results:
        return []

    shape_priority = {"enclosure": 3, "linear": 2, "regular": 1}
    results.sort(key=lambda item: (shape_priority.get(item.get("shape", ""), 0), item["score"]), reverse=True)
    selected = []
    for item in results:
        too_close = False
        for keep in selected:
            dist = math.hypot(item["x"] - keep["x"], item["y"] - keep["y"])
            min_dist = max(8.0, 0.35 * max(item["length_m"], keep["length_m"], 1.0))
            if dist < min_dist:
                too_close = True
                break
        if too_close:
            continue
        selected.append(item)
        if len(selected) >= int(max_items):
            break

    for idx, item in enumerate(selected, start=1):
        item["id"] = int(idx)
    return selected


def apply_cloud_preprocessing(dtm, cloud_preprocess_key="cloud1"):
    key = cloud_preprocess_key or "cloud1"
    cfg = CLOUD_PREPROCESS_PROFILES.get(key)
    if cfg is None:
        raise RuntimeError(f"Cloud preprocessing non valido: {key}")
    arr = np.asarray(dtm, dtype=np.float32).copy()
    if cfg.get("sanitize"):
        arr = _sanitize_surface_for_lads(arr)
    arr = _soft_smooth_surface(
        arr,
        sigma=float(cfg.get("sigma", 0.0) or 0.0),
        blend=float(cfg.get("blend", 0.0) or 0.0),
        passes=int(cfg.get("passes", 0) or 0),
    )
    return arr


def build_lads_point_cloud(dtm, profile, src_crs, target_crs=LADS_TARGET_CRS, max_points=LADS_MAX_POINTS, cloud_preprocess_key="original"):
    arr = apply_cloud_preprocessing(dtm, cloud_preprocess_key=cloud_preprocess_key)
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
        ax.set_box_aspect((x_span, y_span, z_span * float(LADS_Z_EXAGGERATION)))
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


def _terrain_colors_u8(z_values):
    z = np.asarray(z_values, dtype=np.float32)
    orig_shape = z.shape
    z = z.reshape(-1)
    finite = np.isfinite(z)
    if not finite.any():
        return np.zeros(orig_shape + (3,), dtype=np.uint8)
    lo = float(np.nanpercentile(z, 2.0))
    hi = float(np.nanpercentile(z, 98.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = float(np.nanmin(z))
        hi = float(np.nanmax(z))
    denom = max(1e-6, hi - lo)
    norm = np.clip((z - lo) / denom, 0.0, 1.0)
    rgb = colormaps["turbo"](norm)[:, :3]
    return np.round(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8).reshape(orig_shape + (3,))


def _mean_abs_step(arr, axis):
    values = np.asarray(arr, dtype=np.float32)
    if values.ndim != 2 or values.shape[axis] <= 1:
        return 1.0
    diffs = np.diff(values, axis=axis)
    diffs = np.abs(diffs[np.isfinite(diffs)])
    if diffs.size == 0:
        return 1.0
    step = float(np.nanmedian(diffs))
    return step if np.isfinite(step) and step > 1e-6 else 1.0


def _grid_spacing(x_arr, y_arr):
    x = np.asarray(x_arr, dtype=np.float32)
    y = np.asarray(y_arr, dtype=np.float32)
    if x.ndim != 2 or y.ndim != 2:
        return 1.0, 1.0

    col_dx = np.diff(x, axis=1)
    col_dy = np.diff(y, axis=1)
    row_dx = np.diff(x, axis=0)
    row_dy = np.diff(y, axis=0)
    col_dist = np.hypot(col_dx, col_dy)
    row_dist = np.hypot(row_dx, row_dy)
    col_vals = col_dist[np.isfinite(col_dist) & (col_dist > 1e-6)]
    row_vals = row_dist[np.isfinite(row_dist) & (row_dist > 1e-6)]
    col_step = float(np.nanmedian(col_vals)) if col_vals.size else 1.0
    row_step = float(np.nanmedian(row_vals)) if row_vals.size else 1.0
    if not np.isfinite(col_step) or col_step <= 1e-6:
        col_step = 1.0
    if not np.isfinite(row_step) or row_step <= 1e-6:
        row_step = 1.0
    return col_step, row_step


def _height_shaded_colors_u8(z_values, valid_mask, dx=1.0, dy=1.0):
    z = np.asarray(z_values, dtype=np.float32)
    valid = np.asarray(valid_mask, dtype=bool)
    if z.ndim != 2:
        return _terrain_colors_u8(z)
    if not valid.any():
        return np.zeros(z.shape + (3,), dtype=np.uint8)

    lo = float(np.nanpercentile(z[valid], 2.0))
    hi = float(np.nanpercentile(z[valid], 98.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = float(np.nanmin(z[valid]))
        hi = float(np.nanmax(z[valid]))
    denom = max(1e-6, hi - lo)
    norm = np.clip((z - lo) / denom, 0.0, 1.0)
    base_rgb = colormaps["RdYlGn_r"](norm)[..., :3]

    fill = np.array(z, copy=True)
    fill[~valid] = np.nan
    fill_value = float(np.nanmedian(fill[valid]))
    fill[~valid] = fill_value

    try:
        gy, gx = np.gradient(fill, max(1e-6, float(dy)), max(1e-6, float(dx)))
    except Exception:
        gy, gx = np.gradient(fill)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azimuth = math.radians(315.0)
    altitude = math.radians(42.0)
    shade = (
        np.sin(altitude) * np.sin(slope)
        + np.cos(altitude) * np.cos(slope) * np.cos(azimuth - aspect)
    )
    shade = np.clip((shade + 1.0) * 0.5, 0.0, 1.0)
    shade = 0.45 + 0.70 * shade

    rgb = np.clip(base_rgb * shade[..., None], 0.0, 1.0)
    rgb[~valid] = 0.0
    return np.round(rgb * 255.0).astype(np.uint8)


def _adaptive_z_scale(x_span, y_span, z_span):
    xy_span = max(1.0, float(max(x_span, y_span)))
    z_span = max(1e-6, float(z_span))
    target_ratio = 0.42
    scale = target_ratio * xy_span / z_span
    return float(np.clip(scale, 0.45, float(LADS_Z_EXAGGERATION)))


def _align_xy_to_principal_axes(x, y, valid_mask):
    x_arr = np.asarray(x, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.float32)
    valid = np.asarray(valid_mask, dtype=bool)
    if not valid.any():
        return x_arr, y_arr

    pts = np.column_stack([x_arr[valid].astype(np.float64), y_arr[valid].astype(np.float64)])
    center = np.nanmean(pts, axis=0)
    centered = pts - center
    if centered.shape[0] < 3:
        xr = x_arr - float(center[0])
        yr = y_arr - float(center[1])
        return xr.astype(np.float32), yr.astype(np.float32)

    cov = np.cov(centered, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    basis = eigvecs[:, order]
    if np.linalg.det(basis) < 0:
        basis[:, 1] *= -1.0

    flat = np.column_stack([x_arr.reshape(-1).astype(np.float64), y_arr.reshape(-1).astype(np.float64)])
    rotated = (flat - center) @ basis
    xr = rotated[:, 0].reshape(x_arr.shape)
    yr = rotated[:, 1].reshape(y_arr.shape)
    return xr.astype(np.float32), yr.astype(np.float32)


def _encode_f32_triplets_base64(a, b, c):
    interleaved = np.column_stack(
        [
            np.asarray(a, dtype=np.float32),
            np.asarray(b, dtype=np.float32),
            np.asarray(c, dtype=np.float32),
        ]
    ).astype(np.float32, copy=False)
    return base64.b64encode(interleaved.tobytes(order="C")).decode("ascii")


def _encode_u8_triplets_base64(rgb):
    arr = np.asarray(rgb, dtype=np.uint8)
    return base64.b64encode(arr.tobytes(order="C")).decode("ascii")


def _encode_u8_base64(arr):
    return base64.b64encode(np.asarray(arr, dtype=np.uint8).tobytes(order="C")).decode("ascii")


def build_browser_terrain_grid(dtm, profile, src_crs, target_crs=LADS_TARGET_CRS, max_side=LADS_BROWSER_MAX_SIDE, cloud_preprocess_key="cloud1"):
    arr = apply_cloud_preprocessing(dtm, cloud_preprocess_key=cloud_preprocess_key)
    cfg = CLOUD_PREPROCESS_PROFILES.get(cloud_preprocess_key, CLOUD_PREPROCESS_PROFILES["cloud1"])
    if arr.ndim != 2:
        raise RuntimeError("Il DTM browser deve essere mono-banda.")
    if profile is None or profile.get("transform") is None:
        raise RuntimeError("Transform georiferito non disponibile per il browser 3D.")
    if src_crs is None:
        raise RuntimeError("CRS del raster non disponibile per il browser 3D.")

    h, w = arr.shape
    if h <= 1 or w <= 1:
        raise RuntimeError("Raster troppo piccolo per il viewer 3D.")
    step = max(1, int(math.ceil(max(h, w) / float(max_side))))
    rows = np.arange(0, h, step, dtype=np.int32)
    cols = np.arange(0, w, step, dtype=np.int32)
    if rows[-1] != h - 1:
        rows = np.append(rows, h - 1)
    if cols[-1] != w - 1:
        cols = np.append(cols, w - 1)

    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    z_source = arr[np.ix_(rows, cols)].astype(np.float32)
    if cfg.get("render_mode") == "relief_mesh":
        z_render, _residual = _enhance_local_relief(
            z_source,
            sigma=float(cfg.get("relief_sigma", 12.0) or 12.0),
            gain=float(cfg.get("relief_gain", 3.0) or 3.0),
        )
    else:
        z_render = z_source.copy()

    valid = np.isfinite(z_render)
    if not valid.any():
        raise RuntimeError("Nessuna cella valida per il viewer 3D.")

    xs, ys = rasterio.transform.xy(profile["transform"], rr.ravel().tolist(), cc.ravel().tolist(), offset="center")
    x = np.asarray(xs, dtype=np.float64).reshape(z_render.shape)
    y = np.asarray(ys, dtype=np.float64).reshape(z_render.shape)

    dst_crs = target_crs or src_crs
    if _as_crs_text(src_crs) != _as_crs_text(dst_crs):
        tx, ty = rasterio.warp.transform(src_crs, dst_crs, x.ravel().tolist(), y.ravel().tolist())
        x = np.asarray(tx, dtype=np.float64).reshape(z_render.shape)
        y = np.asarray(ty, dtype=np.float64).reshape(z_render.shape)

    origin_x = float(np.nanmin(x[valid]))
    origin_y = float(np.nanmin(y[valid]))
    x, y = _align_xy_to_principal_axes(x, y, valid)
    x = (x - float(np.nanmin(x[valid]))).astype(np.float32)
    y = (y - float(np.nanmin(y[valid]))).astype(np.float32)
    z_fill = np.where(valid, z_render, np.nanmin(z_render[valid])).astype(np.float32)
    dx = _mean_abs_step(x, axis=1)
    dy = _mean_abs_step(y, axis=0)
    colors = _height_shaded_colors_u8(z_fill, valid, dx=dx, dy=dy)
    colors[~valid] = 0
    archaeology_candidates = detect_archaeology_candidates(x, y, z_source, z_fill, valid)
    x_span = float(np.nanmax(x[valid]) - np.nanmin(x[valid]))
    y_span = float(np.nanmax(y[valid]) - np.nanmin(y[valid]))
    z_span = float(np.nanmax(z_render[valid]) - np.nanmin(z_render[valid]))
    z_scale = _adaptive_z_scale(x_span, y_span, z_span)

    return {
        "x": x,
        "y": y,
        "z": z_fill,
        "valid": valid.astype(np.uint8),
        "colors": colors.astype(np.uint8),
        "rows": int(z_render.shape[0]),
        "cols": int(z_render.shape[1]),
        "origin_x": origin_x,
        "origin_y": origin_y,
        "source_crs": _as_crs_text(src_crs),
        "target_crs": _as_crs_text(dst_crs),
        "sample_step": int(step),
        "preview_points": int(valid.sum()),
        "total_points": int(np.isfinite(arr).sum()),
        "z_scale": float(z_scale),
        "cloud_preprocess_key": str(cloud_preprocess_key),
        "archaeology_candidates": archaeology_candidates,
        "render_mode": str(cfg.get("render_mode", "mesh")),
        "flat_shading": bool(cfg.get("flat_shading", False)),
        "wireframe_overlay": bool(cfg.get("wireframe_overlay", False)),
        "mesh_opacity": float(cfg["mesh_opacity"]) if cfg.get("mesh_opacity") is not None else 1.0,
        "show_points": bool(cfg.get("show_points", False)),
        "point_stride": int(cfg.get("point_stride", 1) or 1),
        "point_size": float(cfg["point_size"]) if cfg.get("point_size") is not None else 1.0,
        "point_opacity": float(cfg["point_opacity"]) if cfg.get("point_opacity") is not None else 0.7,
    }


def write_browser_cloud_viewer(
    output_html,
    terrain,
    las_href="",
    variant_options=None,
    current_variant_key="",
    cloud_preprocess_options=None,
    current_cloud_preprocess_key="",
):
    output_html = Path(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    x = np.asarray(terrain["x"], dtype=np.float32)
    y = np.asarray(terrain["y"], dtype=np.float32)
    z = np.asarray(terrain["z"], dtype=np.float32)
    valid = np.asarray(terrain["valid"], dtype=np.uint8)
    colors = np.asarray(terrain["colors"], dtype=np.uint8)
    rows = int(terrain["rows"])
    cols = int(terrain["cols"])
    show_points = bool(terrain.get("show_points", False))
    point_stride = max(1, int(terrain.get("point_stride", 1) or 1))
    point_size = float(terrain["point_size"]) if terrain.get("point_size") is not None else 1.0
    point_opacity = float(terrain["point_opacity"]) if terrain.get("point_opacity") is not None else 0.7
    render_mode = str(terrain.get("render_mode", "mesh"))
    flat_shading = bool(terrain.get("flat_shading", False))
    wireframe_overlay = bool(terrain.get("wireframe_overlay", False))
    mesh_opacity = float(terrain["mesh_opacity"]) if terrain.get("mesh_opacity") is not None else 1.0
    archaeology_candidates = terrain.get("archaeology_candidates", []) or []

    x_span = max(1.0, float(np.nanmax(x) - np.nanmin(x)))
    y_span = max(1.0, float(np.nanmax(y) - np.nanmin(y)))
    z_scale = float(terrain.get("z_scale", LADS_Z_EXAGGERATION))
    z_span = max(1.0, float(np.nanmax(z) - np.nanmin(z)))
    radius = max(x_span, y_span, z_span * z_scale) * 0.8

    pos_b64 = _encode_f32_triplets_base64(x.reshape(-1), y.reshape(-1), z.reshape(-1))
    color_b64 = _encode_u8_triplets_base64(colors.reshape(-1, 3))
    valid_b64 = _encode_u8_base64(valid.reshape(-1))
    exag = float(z_scale)
    archaeology_json = json.dumps(archaeology_candidates, ensure_ascii=False)
    las_button = ""
    if las_href:
        las_button = f'<a class="toolbar-btn" href="{las_href}" download>Esporta .LAS</a>'
    analysis_button_html = '<button id="analysis-toggle" class="toolbar-btn toolbar-btn--button" type="button">Stima archeologica</button>'
    variant_html = ""
    if variant_options:
        options_markup = []
        for item in variant_options:
            key = str(item.get("key", ""))
            href = str(item.get("href", ""))
            label = str(item.get("label", key or href))
            selected = " selected" if key == current_variant_key else ""
            options_markup.append(f'<option value="{escape(href, quote=True)}"{selected}>{escape(label)}</option>')
        variant_html = (
            '<label class="toolbar-select-wrap">'
            '<span>Dato</span>'
            f'<select id="variant-select" class="toolbar-select">{"".join(options_markup)}</select>'
            "</label>"
        )
    cloud_preprocess_html = ""
    cloud_preprocess_desc_html = ""
    if cloud_preprocess_options:
        cp_options_markup = []
        current_description = ""
        for item in cloud_preprocess_options:
            key = str(item.get("key", ""))
            href = str(item.get("href", ""))
            label = str(item.get("label", key or href))
            description = str(item.get("description", ""))
            selected = " selected" if key == current_cloud_preprocess_key else ""
            cp_options_markup.append(f'<option value="{escape(href, quote=True)}"{selected}>{escape(label)}</option>')
            if key == current_cloud_preprocess_key:
                current_description = description
        cloud_preprocess_html = (
            '<label class="toolbar-select-wrap">'
            '<span>Cloud preprocessing</span>'
            f'<select id="cloud-preprocess-select" class="toolbar-select">{"".join(cp_options_markup)}</select>'
            "</label>"
        )
        if current_description:
            cloud_preprocess_desc_html = f'<div class="toolbar-help">{escape(current_description)}</div>'

    html = f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D Cloud</title>
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #000;
    }}
    #app {{
      position: fixed;
      inset: 0;
      background: #000;
    }}
    #toolbar {{
      position: fixed;
      top: 14px;
      left: 14px;
      z-index: 20;
      display: flex;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 10px;
      max-width: min(1100px, calc(100vw - 28px));
    }}
    .toolbar-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 14px;
      border-radius: 10px;
      background: rgba(18, 18, 18, 0.92);
      color: #fff;
      text-decoration: none;
      font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      border: 1px solid rgba(255,255,255,0.12);
      backdrop-filter: blur(6px);
    }}
    .toolbar-btn--button {{
      cursor: pointer;
    }}
    .toolbar-select-wrap {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 10px;
      background: rgba(18, 18, 18, 0.92);
      color: #fff;
      font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      border: 1px solid rgba(255,255,255,0.12);
      backdrop-filter: blur(6px);
    }}
    .toolbar-select {{
      min-width: 130px;
      padding: 6px 10px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.14);
      background: #111;
      color: #fff;
      font: 500 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      outline: none;
    }}
    .toolbar-help {{
      max-width: 380px;
      padding: 9px 12px;
      border-radius: 10px;
      background: rgba(18, 18, 18, 0.92);
      color: rgba(255,255,255,0.86);
      font: 500 12px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      border: 1px solid rgba(255,255,255,0.10);
      backdrop-filter: blur(6px);
    }}
    #analysis-panel {{
      position: fixed;
      top: 14px;
      right: 14px;
      z-index: 22;
      width: min(360px, calc(100vw - 28px));
      max-height: calc(100vh - 28px);
      overflow: auto;
      padding: 14px;
      border-radius: 14px;
      background: rgba(12, 12, 12, 0.94);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.10);
      backdrop-filter: blur(8px);
      box-shadow: 0 16px 50px rgba(0,0,0,0.35);
      display: none;
    }}
    #analysis-panel.visible {{
      display: block;
    }}
    #analysis-panel h3 {{
      margin: 0 0 6px;
      font: 700 15px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #analysis-panel .analysis-note {{
      margin: 0 0 12px;
      color: rgba(255,255,255,0.75);
      font: 500 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .analysis-list {{
      display: grid;
      gap: 10px;
    }}
    .analysis-item {{
      padding: 11px 12px;
      border-radius: 12px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      cursor: pointer;
    }}
    .analysis-item:hover {{
      background: rgba(255,255,255,0.08);
    }}
    .analysis-head {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }}
    .analysis-id {{
      min-width: 22px;
      height: 22px;
      border-radius: 999px;
      background: #d44b4b;
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font: 700 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .analysis-title {{
      font: 700 13px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      flex: 1;
    }}
    .analysis-confidence {{
      color: rgba(255,255,255,0.72);
      font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .analysis-summary {{
      margin: 0 0 7px;
      color: rgba(255,255,255,0.82);
      font: 500 12px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .analysis-meta {{
      color: rgba(255,255,255,0.62);
      font: 500 11px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    canvas {{
      display: block;
    }}
  </style>
</head>
<body>
  <div id="toolbar">{las_button}{analysis_button_html}{variant_html}{cloud_preprocess_html}{cloud_preprocess_desc_html}</div>
  <div id="app"></div>
  <aside id="analysis-panel">
    <h3>Stima archeologica</h3>
    <p class="analysis-note">Analisi sperimentale basata sulle irregolarita del terreno. Non identifica siti certi: evidenzia solo zone che meritano un controllo.</p>
    <div id="analysis-list" class="analysis-list"></div>
  </aside>
  <div id="errorbox" style="display:none; position:fixed; right:14px; top:14px; max-width:520px; padding:12px 14px; background:rgba(120,0,0,0.9); color:#fff; font:13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; z-index:30; border-radius:10px; white-space:pre-wrap;"></div>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <script>
    function showError(message) {{
      const box = document.getElementById('errorbox');
      box.style.display = 'block';
      box.textContent = message;
    }}
    try {{
      if (!window.THREE) {{
        throw new Error('Three.js non caricato.');
      }}
    const variantSelect = document.getElementById('variant-select');
    if (variantSelect) {{
      variantSelect.addEventListener('change', function() {{
        if (this.value) {{
          window.location.href = this.value;
        }}
      }});
    }}
    const cloudPreprocessSelect = document.getElementById('cloud-preprocess-select');
    if (cloudPreprocessSelect) {{
      cloudPreprocessSelect.addEventListener('change', function() {{
        if (this.value) {{
          window.location.href = this.value;
        }}
      }});
    }}
    const POS_B64 = "{pos_b64}";
    const COLOR_B64 = "{color_b64}";
    const VALID_B64 = "{valid_b64}";
    const GRID_ROWS = {rows};
    const GRID_COLS = {cols};
    const Z_EXAGGERATION = {exag:.6f};
    const DEFAULT_RADIUS = {radius:.6f};
    const SHOW_POINTS = {"true" if show_points else "false"};
    const POINT_STRIDE = {point_stride};
    const POINT_SIZE = {point_size:.6f};
    const POINT_OPACITY = {point_opacity:.6f};
    const RENDER_MODE = "{escape(render_mode)}";
    const FLAT_SHADING = {"true" if flat_shading else "false"};
    const WIREFRAME_OVERLAY = {"true" if wireframe_overlay else "false"};
    const MESH_OPACITY = {mesh_opacity:.6f};
    const ARCH_CANDIDATES = {archaeology_json};

    function base64ToUint8Array(base64) {{
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {{
        bytes[i] = binary.charCodeAt(i);
      }}
      return bytes;
    }}

    const root = document.getElementById('app');
    const renderer = new THREE.WebGLRenderer({{ antialias: true, powerPreference: 'high-performance' }});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 1);
    renderer.outputEncoding = THREE.sRGBEncoding;
    root.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);
    const hemi = new THREE.HemisphereLight(0xffffff, 0x060708, 1.15);
    scene.add(hemi);
    const dir1 = new THREE.DirectionalLight(0xffffff, 1.0);
    dir1.position.set(1.1, -1.3, 1.45);
    scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0xffddaa, 0.30);
    dir2.position.set(-0.8, 0.7, 0.55);
    scene.add(dir2);

    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, Math.max(50000, DEFAULT_RADIUS * 20));
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 1.05;
    controls.zoomSpeed = 1.15;
    controls.panSpeed = 0.95;
    controls.screenSpacePanning = true;
    controls.minPolarAngle = 0.02;
    controls.maxPolarAngle = Math.PI - 0.02;
    controls.minDistance = Math.max(2, DEFAULT_RADIUS * 0.04);
    controls.maxDistance = Math.max(200000, DEFAULT_RADIUS * 40);
    controls.enableKeys = true;

    const posBytes = base64ToUint8Array(POS_B64);
    const positions = new Float32Array(posBytes.buffer, posBytes.byteOffset, posBytes.byteLength / 4);
    const colorBytes = base64ToUint8Array(COLOR_B64);
    const validBytes = base64ToUint8Array(VALID_B64);
    const analysisPanel = document.getElementById('analysis-panel');
    const analysisList = document.getElementById('analysis-list');
    const analysisToggle = document.getElementById('analysis-toggle');

    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    for (let i = 2; i < positions.length; i += 3) {{
      positions[i] = positions[i] * Z_EXAGGERATION;
    }}
    for (let i = 0; i < validBytes.length; i++) {{
      if (!validBytes[i]) continue;
      const posIdx = i * 3;
      const px = positions[posIdx];
      const py = positions[posIdx + 1];
      const pz = positions[posIdx + 2];
      if (px < minX) minX = px;
      if (py < minY) minY = py;
      if (pz < minZ) minZ = pz;
      if (px > maxX) maxX = px;
      if (py > maxY) maxY = py;
      if (pz > maxZ) maxZ = pz;
    }}
    if (!isFinite(minX) || !isFinite(minY) || !isFinite(minZ)) {{
      throw new Error('Nessun punto valido generato per il viewer 3D.');
    }}
    const centerX = (minX + maxX) * 0.5;
    const centerY = (minY + maxY) * 0.5;
    const centerZ = (minZ + maxZ) * 0.5;
    for (let i = 0; i < validBytes.length; i++) {{
      if (!validBytes[i]) continue;
      const posIdx = i * 3;
      positions[posIdx] -= centerX;
      positions[posIdx + 1] -= centerY;
      positions[posIdx + 2] -= centerZ;
    }}

    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);
    const spanZ = Math.max(1, maxZ - minZ);
    const sceneRadius = Math.max(10, Math.max(spanX, spanY, spanZ) * 0.82);

    function buildPointGeometry() {{
      const pointPositions = [];
      const pointColors = [];
      for (let i = 0; i < validBytes.length; i += POINT_STRIDE) {{
        if (!validBytes[i]) continue;
        const posIdx = i * 3;
        pointPositions.push(positions[posIdx], positions[posIdx + 1], positions[posIdx + 2]);
        pointColors.push(colorBytes[posIdx], colorBytes[posIdx + 1], colorBytes[posIdx + 2]);
      }}
      if (!pointPositions.length) {{
        return null;
      }}
      const pointsGeometry = new THREE.BufferGeometry();
      pointsGeometry.setAttribute('position', new THREE.Float32BufferAttribute(pointPositions, 3));
      pointsGeometry.setAttribute('color', new THREE.Uint8BufferAttribute(new Uint8Array(pointColors), 3, true));
      pointsGeometry.computeBoundingSphere();
      return pointsGeometry;
    }}

    function badgeTexture(label) {{
      const size = 128;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = 'rgba(212,75,75,0.96)';
      ctx.beginPath();
      ctx.arc(size * 0.5, size * 0.5, size * 0.34, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '700 46px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(label), size * 0.5, size * 0.52);
      const texture = new THREE.CanvasTexture(canvas);
      texture.needsUpdate = true;
      return texture;
    }}

    function formatMeters(value) {{
      const sign = value > 0 ? '+' : '';
      return `${{sign}}${{Number(value || 0).toFixed(2)}} m`;
    }}

    function shapeLabel(value) {{
      if (value === 'enclosure') return 'chiusa o circolare';
      if (value === 'linear') return 'lineare';
      if (value === 'regular') return 'regolare';
      return 'anomalia';
    }}

    let radius = Math.max(DEFAULT_RADIUS, sceneRadius);
    if (RENDER_MODE !== 'points') {{
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.Uint8BufferAttribute(colorBytes, 3, true));
      const indices = [];
      for (let r = 0; r < GRID_ROWS - 1; r++) {{
        for (let c = 0; c < GRID_COLS - 1; c++) {{
          const a = r * GRID_COLS + c;
          const b = a + 1;
          const d = (r + 1) * GRID_COLS + c;
          const e = d + 1;
          if (validBytes[a] && validBytes[b] && validBytes[d]) indices.push(a, d, b);
          if (validBytes[b] && validBytes[d] && validBytes[e]) indices.push(b, d, e);
        }}
      }}
      if (!indices.length) {{
        throw new Error('Nessun triangolo valido generato per il terrain viewer.');
      }}
      geometry.setIndex(indices);
      geometry.computeVertexNormals();
      geometry.computeBoundingSphere();

      const material = new THREE.MeshPhongMaterial({{
        vertexColors: true,
        shininess: FLAT_SHADING ? 2 : 6,
        specular: FLAT_SHADING ? 0x080808 : 0x1b1b1b,
        flatShading: FLAT_SHADING,
        side: THREE.DoubleSide,
        transparent: MESH_OPACITY < 0.999,
        opacity: MESH_OPACITY,
      }});
      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      if (WIREFRAME_OVERLAY) {{
        const wireframe = new THREE.LineSegments(
          new THREE.WireframeGeometry(geometry),
          new THREE.LineBasicMaterial({{
            color: 0x080808,
            transparent: true,
            opacity: 0.28,
          }})
        );
        scene.add(wireframe);
      }}
      radius = Math.max(radius, (geometry.boundingSphere && geometry.boundingSphere.radius) || radius);
    }}

    if (SHOW_POINTS) {{
      const pointsGeometry = buildPointGeometry();
      if (pointsGeometry) {{
        const pointsMaterial = new THREE.PointsMaterial({{
          size: POINT_SIZE,
          sizeAttenuation: true,
          vertexColors: true,
          transparent: true,
          opacity: POINT_OPACITY,
          depthWrite: false,
        }});
        const points = new THREE.Points(pointsGeometry, pointsMaterial);
        scene.add(points);
        radius = Math.max(radius, (pointsGeometry.boundingSphere && pointsGeometry.boundingSphere.radius) || radius);
      }}
    }}

    const analysisGroup = new THREE.Group();
    analysisGroup.visible = false;
    scene.add(analysisGroup);
    const analysisMarkers = [];

    function focusCandidate(marker) {{
      if (!marker) return;
      const target = marker.userData.focus.clone();
      controls.target.copy(target);
      camera.position.set(
        target.x + radius * 0.52,
        target.y - radius * 0.58,
        target.z + radius * 0.42
      );
      controls.update();
    }}

    function buildAnalysisUI() {{
      if (!analysisList) return;
      if (!ARCH_CANDIDATES.length) {{
        analysisList.innerHTML = '<div class="analysis-item"><div class="analysis-summary">Nessuna anomalia abbastanza chiara da segnalare in questa vista.</div></div>';
        return;
      }}
      const frag = document.createDocumentFragment();
      ARCH_CANDIDATES.forEach((candidate, index) => {{
        const item = document.createElement('div');
        item.className = 'analysis-item';
        item.innerHTML = `
          <div class="analysis-head">
            <span class="analysis-id">${{candidate.id}}</span>
            <div class="analysis-title">${{candidate.title}}</div>
            <div class="analysis-confidence">${{candidate.confidence}}</div>
          </div>
          <p class="analysis-summary">${{candidate.summary}}</p>
          <div class="analysis-meta">
            Forma: ${{shapeLabel(candidate.shape)}}<br />
            Rilievo: ${{formatMeters(candidate.relief_m)}}<br />
            Estensione: ${{Number(candidate.length_m || 0).toFixed(1)}} x ${{Number(candidate.width_m || 0).toFixed(1)}} m<br />
            Area stimata: ${{Number(candidate.area_m2 || 0).toFixed(1)}} m²
          </div>
        `;
        item.addEventListener('click', () => focusCandidate(analysisMarkers[index]));
        frag.appendChild(item);
      }});
      analysisList.innerHTML = '';
      analysisList.appendChild(frag);
    }}

    ARCH_CANDIDATES.forEach((candidate) => {{
      const px = Number(candidate.x || 0) - centerX;
      const py = Number(candidate.y || 0) - centerY;
      const pz = Number(candidate.z || 0) * Z_EXAGGERATION - centerZ;
      const marker = new THREE.Group();
      const lineHeight = Math.max(6, radius * 0.045);
      const lineGeometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(px, py, pz),
        new THREE.Vector3(px, py, pz + lineHeight),
      ]);
      const line = new THREE.Line(
        lineGeometry,
        new THREE.LineBasicMaterial({{
          color: 0xff6666,
          transparent: true,
          opacity: 0.95,
        }})
      );
      const head = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(1.1, radius * 0.007), 18, 18),
        new THREE.MeshBasicMaterial({{ color: 0xff6666 }})
      );
      head.position.set(px, py, pz + lineHeight);
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({{
          map: badgeTexture(candidate.id),
          transparent: true,
          depthTest: false,
          depthWrite: false,
        }})
      );
      const spriteSize = Math.max(8, radius * 0.05);
      sprite.scale.set(spriteSize, spriteSize, 1);
      sprite.position.set(px, py, pz + lineHeight + spriteSize * 0.42);
      marker.add(line);
      marker.add(head);
      marker.add(sprite);
      marker.userData.focus = new THREE.Vector3(px, py, pz + lineHeight * 0.35);
      analysisGroup.add(marker);
      analysisMarkers.push(marker);
    }});

    buildAnalysisUI();
    if (analysisToggle) {{
      analysisToggle.addEventListener('click', function() {{
        const nextVisible = !analysisGroup.visible;
        analysisGroup.visible = nextVisible;
        if (analysisPanel) {{
          analysisPanel.classList.toggle('visible', nextVisible);
        }}
        this.textContent = nextVisible ? 'Nascondi stima' : 'Stima archeologica';
      }});
    }}

    controls.target.set(0, 0, 0);
    camera.near = 0.1;
    camera.far = Math.max(200000, radius * 80);
    camera.position.set(radius * 1.22, -radius * 1.18, radius * 0.92);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    controls.update();

    function onResize() {{
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    }}
    window.addEventListener('resize', onResize);

    function animate() {{
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }}
    animate();
    }} catch (err) {{
      console.error(err);
      showError(String(err && err.stack ? err.stack : err));
    }}
  </script>
</body>
</html>
"""
    output_html.write_text(html, encoding="utf-8")
    return output_html


def export_lads_las(dtm, profile, src_crs, output_path, target_crs=LADS_TARGET_CRS, cloud_preprocess_key="original"):
    if laspy is None:
        raise RuntimeError("Modulo `laspy` non disponibile per esportare .LAS.")
    if pyproj is None:
        raise RuntimeError("Modulo `pyproj` non disponibile per esportare .LAS.")

    cloud = build_lads_point_cloud(
        dtm,
        profile,
        src_crs,
        target_crs=target_crs,
        max_points=None,
        cloud_preprocess_key=cloud_preprocess_key,
    )
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
