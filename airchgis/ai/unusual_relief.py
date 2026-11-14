"""Unusual relief: an unsupervised, one-class model of the terrain of one area, read through several RVT views.

The method only re-analyses the measured terrain. It learns what the relief of this area usually looks like across
a few RVT views at the scale of the features sought, and gives each pixel a score: how far its combination of views
is from that usual relief. The most unusual places become "priorities to check". They are not sites: modern
features (drains, banks, buildings, ploughing) and data artefacts (tile seams, interpolation facets) can be unusual too.

Steps (all deterministic for a given input and seed):
1. RVT views at a radius matched to the target width W, plus two band-pass filters of the terrain.
2. Robust normalization of each layer, then standardization against its neighbourhood (window 8 s).
3. A Gaussian model (mean, covariance) of the usual relief, fitted on a random sample of the area with iterative
   trimming of the 10% most unusual pixels, so that features do not shape the model of "usual".
4. Score = Mahalanobis distance to that model, lightly smoothed; borders masked.
5. Priority areas = the most unusual share of the area (sensitivity), only where the score is also clearly high.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
from scipy import ndimage

from airchgis.enhance import metrics

# Sensitivity: the largest share of the area to check, and the minimum mean score of a priority area. A pixel can be
# part of an area only if it is among that share and its score is at least PIXEL_FLOOR. The floors were set on
# synthetic natural terrain (smooth hills) so that, at the default, natural terrain gives no priority area.
SENSITIVITY = {"low": (0.005, 8.0), "medium": (0.01, 7.5), "high": (0.02, 7.0)}
PIXEL_FLOOR = 5.5
DEFAULT_SEED = 0
MAX_SAMPLES = 200_000
TRIM = 0.9
TRIM_PASSES = 5
LOCAL_WINDOW = 8.0  # x s, neighbourhood used to standardize each view
SMOOTH = 0.5  # x s, smoothing of the score
MAX_AREAS = 50
LARGE_FACTOR = 3.0  # "also look for larger structures": second pass at 3 x the feature width
LARGE_OFFSET = 3.0  # the coarse pass has a heavier tail on natural relief (fewer, larger cells): it is lowered by this
# level surfaces such as lakes: tilt at a 15 m scale below WATER_TILT_DEG, elevation spread within WATER_BAND_M,
# connected over at least WATER_MIN_AREA_M2; a buffer of WATER_BUFFER_M is excluded around them
WATER_TILT_DEG = 0.4
WATER_BAND_M = 1.0
WATER_MIN_AREA_M2 = 5000.0
WATER_BUFFER_M = 5.0
EDGE_SHARE = 0.25  # a priority area is dropped as a likely data-edge artefact if more than this share is in the edge band
# geometry term: priority = unusualness x (1 + GEOMETRY_WEIGHT x g)
GEOMETRY_WEIGHT = 1.0
GEOMETRY = {"ring": 1.5, "line": 0.3, "compact": 0.0, "straight line": -0.2}
STRAIGHT_MIN_M = 80.0
STRAIGHT_TOL = 0.03
RING_RADII_M = (12.0, 200.0)
RING_HOLLOW = 0.7  # at least this share of the directions must be usual relief halfway to the centre
RING_TANGENT = 0.9  # |cos| between the line's normal and the direction to the centre (about 25 degrees of tolerance)
RING_BAND = 0.08  # radial tolerance as a share of the radius (ellipses up to about 0.85 axis ratio)
RING_PEAKS = 8  # vote-map peaks checked per radius
RING_Z = 6.0  # minimum strength of a ring centre, in robust standard deviations of the vote map
RING_COVERAGE = 0.3  # minimum share of the circle followed continuously by a line of unusual relief
RING_NULL = 100  # random circles per radius used for the site-adaptive threshold
RING_MARGIN = 0.10  # a ring must beat the most continuous random circle by this share of the circle
RING_ANGLES = 36
UNUSUAL_PIXEL = 3.5  # minimum score of a pixel that counts as unusual for the ring detector
RING_QUANTILE = 0.85  # ... and it must be in the top 15% of the fine-scale score
RING_MIN_UNUSUAL = 4.0  # mean score along a ring; rings are faint lines, their evidence is mostly the geometry
RING_MIN_EXCESS = 0.3  # share of the gap between the best random circle and a complete circle that a ring must close
RING_EDGE_SHARE = 0.1  # share of a ring allowed in the edge band
RING_SMALL_M = 20.0  # single rings smaller than this radius need stronger evidence:
RING_SMALL_EXCESS = 0.5
RING_SMALL_UNUSUAL = 5.0

FEATURES = (
    ("svf", "Sky-view factor"),
    ("pos_openness", "Positive openness"),
    ("neg_openness", "Negative openness"),
    ("slrm", "Local relief model"),
    ("slope", "Slope"),
    ("dog_small", "Small-scale relief"),
    ("dog_medium", "Medium-scale relief"),
)
# plain words for a view that is higher or lower than usual in a priority area
PHRASES = {
    "svf": ("more open to the sky", "more enclosed (less sky visible)"),
    "pos_openness": ("more convex", "less convex"),
    "neg_openness": ("more concave", "less concave"),
    "slrm": ("above the local trend", "below the local trend"),
    "slope": ("steeper", "flatter"),
    "dog_small": ("raised at small scale", "sunken at small scale"),
    "dog_medium": ("raised at medium scale", "sunken at medium scale"),
}
SETTINGS = Path(__file__).resolve().parent.parent / "data" / "rvt" / "settings"


def scales(res, width_m):
    """Gaussian scale s (cells) and RVT radius r (cells) for features of width W."""
    s = metrics.target_scale_px(width_m, res)
    r = int(np.clip(round(2.0 * width_m / res), 3, 40))
    return s, r


def _norm_conv(a, w, sigma):
    num = ndimage.gaussian_filter(a * w, sigma, mode="nearest")
    den = ndimage.gaussian_filter(w, sigma, mode="nearest")
    return num / np.maximum(den, 1e-6)


def rvt_feature_views(dem, res, width_m):
    """The RVT views used by the model, at radius r: sky-view factor, positive and negative openness, simple local
    relief model and slope. Returns (views dict, filled DTM, mask of missing cells)."""
    import rvt.vis

    filled, missing = metrics.finite_fill(dem)
    f = filled.astype(np.float32)
    _, r = scales(res, width_m)
    sv = rvt.vis.sky_view_factor(f, res, compute_svf=True, compute_opns=True, svf_r_max=r, svf_n_dir=16)
    neg = rvt.vis.sky_view_factor(-f, res, compute_svf=False, compute_opns=True, svf_r_max=r, svf_n_dir=16)
    views = {
        "svf": np.asarray(sv["svf"], dtype=np.float64),
        "pos_openness": np.asarray(sv["opns"], dtype=np.float64),
        "neg_openness": np.asarray(neg["opns"], dtype=np.float64),
        "slrm": np.asarray(rvt.vis.slrm(f, radius_cell=max(10, 2 * r)), dtype=np.float64),
        "slope": np.asarray(rvt.vis.slope_aspect(f, res, res, output_units="degree")["slope"], dtype=np.float64),
    }
    return views, filled, missing


def feature_stack(dem, res, width_m):
    """Per-pixel features (h, w, p), the valid mask (borders and missing cells excluded) and the raw SLRM."""
    s, r = scales(res, width_m)
    views, filled, missing = rvt_feature_views(dem, res, width_m)
    views["dog_small"] = ndimage.gaussian_filter(filled, s) - ndimage.gaussian_filter(filled, 3 * s)
    views["dog_medium"] = ndimage.gaussian_filter(filled, 2 * s) - ndimage.gaussian_filter(filled, 6 * s)
    margin = int(max(r, np.ceil(3 * s)))
    valid = ~missing
    if margin > 0:
        valid = ndimage.binary_erosion(valid, iterations=margin, border_value=0)
    if valid.sum() < 100:
        raise ValueError("The terrain is too small for this feature width: enlarge the area or reduce the width.")
    layers = []
    for key, _ in FEATURES:
        a = np.asarray(views[key], dtype=np.float64)
        a = np.where(valid & np.isfinite(a), a, np.nan)
        layers.append(np.nan_to_num(metrics.robust_normalize(a, clip=4.0)))
    return np.stack(layers, axis=-1), valid, views["slrm"]


def local_standardize(X, valid, res, width_m):
    """Each feature relative to its neighbourhood: removes slow changes of the natural landscape."""
    s, _ = scales(res, width_m)
    sigma = LOCAL_WINDOW * s
    w = valid.astype(np.float64)
    out = np.zeros_like(X)
    for i in range(X.shape[-1]):
        m = _norm_conv(X[..., i], w, sigma)
        d = X[..., i] - m
        v = _norm_conv(d * d, w, sigma)
        out[..., i] = np.where(valid, d / np.sqrt(v + 1e-6), 0.0)
    return out


def fit_usual(X, valid, seed=DEFAULT_SEED):
    """Mean and covariance of the usual relief, from a seeded random sample with iterative trimming."""
    p = X.shape[-1]
    pool = X[valid]
    rng = np.random.default_rng(seed)
    if pool.shape[0] > MAX_SAMPLES:
        pool = pool[rng.choice(pool.shape[0], MAX_SAMPLES, replace=False)]
    keep = np.ones(pool.shape[0], dtype=bool)
    for _ in range(TRIM_PASSES):
        mu = pool[keep].mean(axis=0)
        cov = np.cov(pool[keep].T) + 1e-6 * np.eye(p)
        ci = np.linalg.inv(cov)
        d = pool - mu
        q = np.einsum("ij,jk,ik->i", d, ci, d)
        keep = q <= np.quantile(q, TRIM)
    mu = pool[keep].mean(axis=0)
    cov = np.cov(pool[keep].T) + 1e-6 * np.eye(p)
    return mu, cov


def mahalanobis(X, mu, cov):
    """Distance d and per-feature contributions c_i = z_i (C^-1 z)_i, which sum to d^2."""
    ci = np.linalg.inv(cov)
    z = X - mu
    v = z @ ci.T
    contrib = z * v
    d = np.sqrt(np.maximum(contrib.sum(axis=-1), 0.0))
    return d, contrib, z


def _area_shape(rows, cols, res):
    if rows.size < 3:
        return res * max(1, rows.size), res, 0.0
    c = np.cov(np.vstack([cols, -rows]).astype(np.float64)) + 1e-9 * np.eye(2)
    vals, vecs = np.linalg.eigh(c)
    length = 4.0 * np.sqrt(vals[1]) * res
    width = 4.0 * np.sqrt(max(vals[0], 0.0)) * res
    vx, vy = vecs[:, 1]
    bearing = float(np.degrees(np.arctan2(vx, vy)) % 180.0)
    return float(max(length, res)), float(max(width, res)), bearing


def _describe(area, res):
    kind = area.get("kind") or ("line" if area["length_m"] >= 3 * area["width_m"] else "compact")
    form = "raised" if area["relief_m"] > 0 else "sunken"
    linear = kind in ("line", "straight line")
    size = (f"about {area['length_m']:.0f} m long and {area['width_m']:.0f} m wide" if linear
            else f"about {area['length_m']:.0f} × {area['width_m']:.0f} m")
    drivers = " and ".join(d["phrase"] for d in area["drivers"][:2])
    shape = {"line": "curved line", "straight line": "straight line"}.get(kind, "compact form")
    text = f"A {form} {shape}, {size}" + (f": {drivers} than the surrounding terrain." if drivers else ".")
    if kind == "straight line":
        text += " Long and straight: often a modern road, track, drain or field boundary, ranked lower."
    return text


def _classify_shape(rr, cc, res, length, width, width_m):
    """Kind of a priority area from its geometry: a curved line, a straight line or a compact form. Straight lines
    are measured by the largest offset of the area's centre line from a straight axis."""
    if length < 3 * width or length < 4 * width_m:
        return "compact", 0.0, 0.0
    pts = np.vstack([cc, -rr]).astype(np.float64)
    pts -= pts.mean(axis=1, keepdims=True)
    _, vecs = np.linalg.eigh(np.cov(pts) + 1e-9 * np.eye(2))
    along, across = vecs[:, 1] @ pts, vecs[:, 0] @ pts
    bins = np.linspace(along.min(), along.max() + 1e-9, 7)
    idx = np.digitize(along, bins) - 1
    offs = [across[idx == b].mean() for b in range(6) if np.any(idx == b)]
    dev = float((max(offs) - min(offs)) * res) if offs else 0.0
    if length >= STRAIGHT_MIN_M and dev <= max(3.0, STRAIGHT_TOL * length):
        return "straight line", GEOMETRY["straight line"], dev
    return "line", GEOMETRY["line"], dev


def priority_areas(score, valid, contrib, z, slrm, res, width_m, transform=None, sensitivity="medium", edge_band=None):
    """Label the priority areas and describe each one in plain words."""
    share, area_floor = SENSITIVITY[sensitivity]
    floor = PIXEL_FLOOR
    vals = score[valid & np.isfinite(score)]
    cut = max(float(np.quantile(vals, 1.0 - share)), floor) if vals.size else np.inf
    cand = valid & np.isfinite(score) & (score >= cut)
    labels, n = ndimage.label(cand, structure=np.ones((3, 3), dtype=bool))
    min_px = max(4, int(round(0.5 * (width_m / res) ** 2)))
    areas = []
    n_edge = 0
    if n:
        idx = np.arange(1, n + 1)
        sizes = ndimage.sum(cand, labels, idx)
        means = ndimage.mean(score, labels, idx)
        peaks = ndimage.maximum(score, labels, idx)
        on_edge = (ndimage.mean(edge_band.astype(np.float64), labels, idx) if edge_band is not None
                   else np.zeros(n))
        big = [i for i in range(n) if sizes[i] >= min_px and means[i] >= area_floor]
        n_edge = sum(1 for i in big if on_edge[i] > EDGE_SHARE)
        order = [i for i in np.argsort(-means) if sizes[i] >= min_px and means[i] >= area_floor
                 and on_edge[i] <= EDGE_SHARE]
        keep = np.zeros(n + 1, dtype=bool)
        names = dict(FEATURES)
        for rank, i in enumerate(order, 1):
            lab = int(idx[i])
            keep[lab] = True
            if rank > MAX_AREAS:
                continue
            rr, cc = np.nonzero(labels == lab)
            length, width, bearing = _area_shape(rr, cc, res)
            c_mean = contrib[rr, cc].mean(axis=0)
            # direction of each view: inside the area against a ring of width W around it
            pad = max(2, int(round(width_m / res)))
            r0, c0 = max(0, rr.min() - pad - 1), max(0, cc.min() - pad - 1)
            r1, c1 = min(labels.shape[0], rr.max() + pad + 2), min(labels.shape[1], cc.max() + pad + 2)
            inside = labels[r0:r1, c0:c1] == lab
            ring = (ndimage.binary_dilation(inside, iterations=pad) & ~ndimage.binary_dilation(inside, iterations=1)
                    & valid[r0:r1, c0:c1])
            win = z[r0:r1, c0:c1]
            z_mean = (win[inside].mean(axis=0) - (win[ring].mean(axis=0) if ring.any() else 0.0))
            total = float(np.clip(c_mean, 0, None).sum()) or 1.0
            drivers = []
            for k in np.argsort(-c_mean)[:3]:
                if c_mean[k] <= 0:
                    continue
                key = FEATURES[k][0]
                drivers.append({"view": names[key], "share": round(float(c_mean[k]) / total, 2),
                                "phrase": PHRASES[key][0 if z_mean[k] > 0 else 1]})
            row, col = float(rr.mean()), float(cc.mean())
            kind, geom, dev = _classify_shape(rr, cc, res, length, width, width_m)
            area = {"id": rank, "row": row, "col": col, "pixels": int(rr.size), "area_m2": float(rr.size * res * res),
                    "mean_score": float(means[i]), "peak_score": float(peaks[i]), "length_m": length, "width_m": width,
                    "bearing_deg": bearing, "relief_m": float(np.nanmean(slrm[rr, cc])), "drivers": drivers,
                    "bbox": [int(rr.min()), int(cc.min()), int(rr.max()), int(cc.max())], "kind": kind,
                    "geometry": geom, "axis_offset_m": dev, "label": lab}
            if transform is not None:
                x, y = transform * (col + 0.5, row + 0.5)
                area["x"], area["y"] = float(x), float(y)
            area["note"] = _describe(area, res)
            areas.append(area)
        labels = np.where(keep[labels], labels, 0)
        # renumber so that area ids follow the ranking
        remap = np.zeros(n + 1, dtype=np.int32)
        for rank, i in enumerate(order, 1):
            remap[int(idx[i])] = rank
        labels = remap[labels]
    flagged = float((labels > 0)[valid].mean()) if valid.any() else 0.0
    return labels.astype(np.int32), areas, {"share": share, "pixel_floor": floor, "area_floor": area_floor,
                                            "cut": float(cut), "flagged_share": flagged, "min_area_px": min_px,
                                            "edge_areas_dropped": int(n_edge)}


def _unusual_relief_single(dem, res, width_m, sensitivity="medium", seed=DEFAULT_SEED, transform=None):
    """First version, one scale and no masks; kept for comparison in the evaluation."""
    """Run the whole method on a terrain array. Returns the score, the priority labels, the areas and a report."""
    if sensitivity not in SENSITIVITY:
        raise ValueError(f"Sensitivity must be one of {', '.join(SENSITIVITY)}.")
    dem = np.asarray(dem, dtype=np.float64)
    X, valid, slrm = feature_stack(dem, res, width_m)
    XL = local_standardize(X, valid, res, width_m)
    mu, cov = fit_usual(XL, valid, seed=seed)
    d, contrib, z = mahalanobis(XL, mu, cov)
    s, _ = scales(res, width_m)
    score = _norm_conv(np.where(valid, d, 0.0), valid.astype(np.float64), SMOOTH * s)
    score = np.where(valid, score, np.nan).astype(np.float32)
    # area descriptions compare the robustly normalized views (same direction as the raw RVT values) with their ring
    labels, areas, stats = priority_areas(score, valid, contrib, X, slrm, res, width_m, transform, sensitivity)
    report = {
        "method": "Unusual relief (one-class Gaussian model of the local terrain over RVT views)",
        "target_width_m": float(width_m), "cell_m": float(res), "sensitivity": sensitivity, "seed": int(seed),
        "views": [n for _, n in FEATURES], "scale_cells": float(s), "rvt_radius_cells": scales(res, width_m)[1],
        "valid_share": float(valid.mean()), **stats, "n_areas": int(labels.max()),
        "model": {"mean": [float(v) for v in mu], "covariance": np.round(cov, 6).tolist()},
    }
    report["note"] = summary_sentence(report)
    return score, labels, areas, report


def water_mask(dem, res, tilt_deg=WATER_TILT_DEG, band_m=WATER_BAND_M, min_area_m2=WATER_MIN_AREA_M2):
    """Level surfaces such as lakes or the sea: large connected areas whose tilt at a 15 m scale is almost zero and
    whose elevation stays within a narrow band. Gently sloping fields are kept because they tilt."""
    filled, missing = metrics.finite_fill(dem)
    g = ndimage.gaussian_filter(filled, max(1.0, 15.0 / res))
    gy, gx = np.gradient(g, res)
    cand = (np.degrees(np.arctan(np.hypot(gx, gy))) < tilt_deg) & ~missing
    lab, n = ndimage.label(cand)
    water = np.zeros(np.shape(dem), dtype=bool)
    if not n:
        return water
    min_px = min_area_m2 / (res * res)
    sizes = ndimage.sum(cand, lab, np.arange(1, n + 1))
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None or sizes[i - 1] < min_px:
            continue
        m = lab[sl] == i
        v = filled[sl][m]
        if np.percentile(v, 98) - np.percentile(v, 2) <= band_m:
            water[sl] |= m
            # grow the water body up to its shore: neighbouring cells at the same level, within 40 m
            level = float(np.median(v))
            reach = int(round(40.0 / res))
            r0, r1 = max(0, sl[0].start - reach), min(water.shape[0], sl[0].stop + reach)
            c0, c1 = max(0, sl[1].start - reach), min(water.shape[1], sl[1].stop + reach)
            seed_ = np.zeros((r1 - r0, c1 - c0), dtype=bool)
            seed_[sl[0].start - r0: sl[0].stop - r0, sl[1].start - c0: sl[1].stop - c0] = m
            same = (np.abs(filled[r0:r1, c0:c1] - level) <= band_m / 2) & ~missing[r0:r1, c0:c1]
            near = ndimage.binary_dilation(seed_, iterations=reach)
            water[r0:r1, c0:c1] |= ndimage.binary_propagation(seed_, mask=(same & near) | seed_)
    return ndimage.binary_fill_holes(water) & ~missing


def _block_mean(a, f):
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    blk = a[:h, :w].reshape(h // f, f, w // f, f)
    with np.errstate(invalid="ignore"):
        cnt = np.isfinite(blk).sum(axis=(1, 3))
        out = np.nansum(blk, axis=(1, 3)) / np.maximum(cnt, 1)
    out[cnt < f * f / 2] = np.nan
    return out


def _upsample(a, f, shape):
    big = np.repeat(np.repeat(a, f, axis=0), f, axis=1)
    out = np.full(shape, np.nan, dtype=big.dtype)
    h, w = min(shape[0], big.shape[0]), min(shape[1], big.shape[1])
    out[:h, :w] = big[:h, :w]
    return out


def _score_at(dem, res, width_m, seed):
    X, valid, slrm = feature_stack(dem, res, width_m)
    XL = local_standardize(X, valid, res, width_m)
    mu, cov = fit_usual(XL, valid, seed=seed)
    d, contrib, _ = mahalanobis(XL, mu, cov)
    s, _ = scales(res, width_m)
    score = _norm_conv(np.where(valid, d, 0.0), valid.astype(np.float64), SMOOTH * s)
    return np.where(valid, score, np.nan), valid, contrib, X, slrm, (mu, cov)


def _drivers(mask, around, contrib, X):
    names = dict(FEATURES)
    c_mean = contrib[mask].mean(axis=0)
    z_mean = X[mask].mean(axis=0) - (X[around].mean(axis=0) if around.any() else 0.0)
    total = float(np.clip(c_mean, 0, None).sum()) or 1.0
    out = []
    for k in np.argsort(-c_mean)[:3]:
        if c_mean[k] <= 0:
            continue
        key = FEATURES[k][0]
        out.append({"view": names[key], "share": round(float(c_mean[k]) / total, 2),
                    "phrase": PHRASES[key][0 if z_mean[k] > 0 else 1]})
    return out


def _n_angles(radius, band):
    return int(np.clip(2 * np.pi * radius / max(1.0, 1.5 * band), RING_ANGLES, 240))


def _circle_samples(r0, c0, radius, band, shape, n=RING_ANGLES):
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    offs = np.arange(-band, band + 1)
    rr = np.rint(r0 + (radius + offs[None, :]) * np.cos(ang)[:, None]).astype(int)
    cc = np.rint(c0 + (radius + offs[None, :]) * np.sin(ang)[:, None]).astype(int)
    inb = (rr >= 0) & (rr < shape[0]) & (cc >= 0) & (cc < shape[1])
    return np.clip(rr, 0, shape[0] - 1), np.clip(cc, 0, shape[1] - 1), inb


def _ring_coverage(S, valid, edge, r0, c0, radius, band, u, normal=None):
    """Share of the 36 directions with data, share of those crossed by unusual relief running along the circle,
    their mean score, and the share of the circle in the edge band."""
    n = _n_angles(radius, band)
    rr, cc, inb = _circle_samples(r0, c0, radius, band, S.shape, n)
    ok = inb & valid[rr, cc]
    has = ok.sum(axis=1) >= max(1, ok.shape[1] // 2)
    sv = np.where(ok, S[rr, cc], -np.inf)
    if normal is not None:
        # the line of unusual relief must run along the circle: its normal points to the centre
        ang = np.linspace(0, 2 * np.pi, n, endpoint=False)[:, None]
        along = np.abs(np.cos(normal[rr, cc] - ang)) >= RING_TANGENT
        sv = np.where(along, sv, -np.inf)
    vals = sv.max(axis=1)
    off = sv.argmax(axis=1)
    hit = has & (vals >= u)
    inside = float(has.mean())
    # continuity: neighbouring directions both crossed by the same line (similar distance from the centre)
    nxt = np.roll(np.arange(n), -1)
    cont = hit & hit[nxt] & (np.abs(off - off[nxt]) <= max(1, band))
    cover = float(cont.sum() / max(1, has.sum()))
    mean = float(vals[hit].mean()) if hit.any() else 0.0
    on_edge = float((edge[rr, cc] & inb).any(axis=1)[has].mean()) if has.any() else 1.0
    # a ring is hollow: halfway to the centre the relief must be mostly usual
    ri, ci, inb_i = _circle_samples(r0, c0, 0.5 * radius, 0, S.shape, RING_ANGLES)
    ok_i = inb_i[:, 0] & valid[ri[:, 0], ci[:, 0]]
    hollow = 1.0 - float((S[ri[:, 0], ci[:, 0]][ok_i] >= u).mean()) if ok_i.any() else 0.0
    if hollow < RING_HOLLOW:
        cover = 0.0
    return inside, cover, mean, on_edge


def detect_rings(score, valid, edge, res, width_m, seed=DEFAULT_SEED):
    """Rings, arcs and concentric bands of unusual relief. Every unusual pixel lying on a line of unusual relief votes
    for the points at distance R on both sides, across the line; a ring makes the votes meet at its centre. Centres
    are then checked by walking around the circle: the relief must be unusual along at least half of it."""
    h, w = score.shape
    s, _ = scales(res, width_m)
    S = np.where(valid, score, 0.0).astype(np.float64)
    vals = score[valid]
    if vals.size < 100:
        return []
    u = max(float(np.quantile(vals, RING_QUANTILE)), UNUSUAL_PIXEL)
    sig = max(1.0, s)
    hrr = ndimage.gaussian_filter(S, sig, order=(2, 0))
    hcc = ndimage.gaussian_filter(S, sig, order=(0, 2))
    hrc = ndimage.gaussian_filter(S, sig, order=(1, 1))
    lam_min = (hrr + hcc) / 2 - np.sqrt(((hrr - hcc) / 2) ** 2 + hrc ** 2)
    theta = 0.5 * np.arctan2(2 * hrc, hrr - hcc) + np.pi / 2
    vr, vc = np.nonzero(valid & (S >= u) & (lam_min < 0))
    if vr.size < 20:
        return []
    if vr.size > 300_000:
        pick = np.random.default_rng(seed).choice(vr.size, 300_000, replace=False)
        vr, vc = vr[pick], vc[pick]
    wv = S[vr, vc] - u + 1.0
    dr, dc = np.cos(theta[vr, vc]), np.sin(theta[vr, vc])
    rmin = RING_RADII_M[0] / res
    rmax = min(RING_RADII_M[1] / res, 0.45 * min(h, w))
    if rmax <= rmin:
        return []
    radii = np.geomspace(rmin, rmax, 24)
    # candidate centres: the strongest vote peaks of each radius separately, so that small rings are not hidden by
    # the votes of long lines at large radii
    candidates = []
    for k, radius in enumerate(radii):
        acc = np.zeros((h, w))
        for sign in (1.0, -1.0):
            rr = np.rint(vr + sign * radius * dr).astype(int)
            cc = np.rint(vc + sign * radius * dc).astype(int)
            ok = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
            np.add.at(acc, (rr[ok], cc[ok]), wv[ok])
        acc = ndimage.gaussian_filter(acc, max(1.0, 0.08 * radius))
        ref = acc[valid]
        med = float(np.median(ref))
        mad = 1.4826 * float(np.median(np.abs(ref - med))) or 1e-9
        z = (acc - med) / mad
        pk = (acc == ndimage.maximum_filter(acc, size=int(max(3, radius)) | 1)) & (z >= RING_Z) & valid
        pr, pc = np.nonzero(pk)
        for i in np.argsort(-z[pr, pc])[:RING_PEAKS]:
            candidates.append((float(z[pr[i], pc[i]]), int(pr[i]), int(pc[i]), k))
    candidates.sort(reverse=True)
    band = int(max(2, round(0.6 * width_m / res)))
    # site-adaptive threshold: a ring must be more continuous than every one of RING_NULL random circles of the
    # same size drawn on this terrain
    def best_fit(r0, c0, radius, b):
        # the same small search around the centre for candidates and for random circles, so the test is fair
        step = max(1, int(round(0.06 * radius)))
        best_c = None
        for dr in (-step, 0, step):
            for dc in (-step, 0, step):
                res_ = _ring_coverage(S, valid, edge, r0 + dr, c0 + dc, radius, b, u, theta)
                if best_c is None or res_[1] > best_c[0][1]:
                    best_c = (res_, r0 + dr, c0 + dc)
        return best_c

    rng = np.random.default_rng(seed)
    vr_all, vc_all = np.nonzero(valid)
    threshold, nullmax = {}, {}
    for radius in radii:
        b = int(max(band, round(RING_BAND * radius)))
        if radius < 2.5 * b:
            continue
        null = []
        for j in rng.choice(vr_all.size, min(vr_all.size, RING_NULL * 3), replace=False):
            (ins, cov, _, _), _, _ = best_fit(int(vr_all[j]), int(vc_all[j]), radius, b)
            if ins >= 0.7:
                null.append(cov)
            if len(null) >= RING_NULL:
                break
        nullmax[radius] = max(null) if null else 0.0
        threshold[radius] = max(RING_COVERAGE, nullmax[radius] + RING_MARGIN)
    rings = []

    def passes(r0, c0, radius):
        if radius not in threshold:
            return None
        b = int(max(band, round(RING_BAND * radius)))
        (inside, cover, mean, on_edge), rc, cc_ = best_fit(r0, c0, radius, b)
        if inside >= 0.7 and cover >= threshold[radius] and on_edge <= RING_EDGE_SHARE:
            return (radius, cover, mean, b, rc, cc_)
        return None

    for zval, r0, c0, k in candidates:
        if any(np.hypot(r0 - q["row"], c0 - q["col"]) < 0.3 * max(radii[k], q["radius_px"])
               and max(radii[k], q["radius_px"]) / min(radii[k], q["radius_px"]) < 1.5 for q in rings):
            continue
        first = [p for p in (passes(r0, c0, radii[j]) for j in (k - 1, k, k + 1) if 0 <= j < len(radii)) if p]
        if not first:
            continue
        r0, c0 = max(first, key=lambda t: t[1])[4:6]
        found = [p for p in (passes(r0, c0, radius) for radius in radii) if p]
        if not found:
            continue
        r0, c0 = max(found, key=lambda t: t[1])[4:6]
        found = [f_[:4] for f_ in found]
        top = max(found, key=lambda t: (t[1], t[2]))
        found = [f_ for f_ in found if top[0] / 3.0 <= f_[0] <= top[0] * 3.0]
        # merge neighbouring radii into bands: keep the best-covered radius of each run
        bands, run = [], [found[0]]
        for f_ in found[1:]:
            if f_[0] - run[-1][0] <= max(run[-1][3], 2) * 1.5 + 1:
                run.append(f_)
            else:
                bands.append(max(run, key=lambda t: (t[1], t[2])))
                run = [f_]
        bands.append(max(run, key=lambda t: (t[1], t[2])))
        main = max(bands, key=lambda t: (t[1], t[2]))
        outer = max(t[0] for t in bands)
        if any(np.hypot(r0 - q["row"], c0 - q["col"]) < 0.3 * max(main[0], q["radius_px"])
               and max(main[0], q["radius_px"]) / min(main[0], q["radius_px"]) < 1.5 for q in rings):
            continue
        # how far the ring beats the most continuous random circle of the same size (0 = equal, 1 = complete circle)
        excess = max(0.0, (main[1] - nullmax[main[0]]) / max(1e-6, 1.0 - nullmax[main[0]]))
        rings.append({"row": float(r0), "col": float(c0), "radius_px": float(main[0]), "outer_px": float(outer),
                      "coverage": float(main[1]), "excess": float(excess), "random_best": float(nullmax[main[0]]),
                      "unusual": float(np.mean([t[2] for t in bands])),
                      "bands": [(float(t[0]), int(t[3])) for t in bands], "z": float(zval), "u": u})
    # one structure, one ring: drop rings that overlap a stronger one
    kept = []
    for q in sorted(rings, key=lambda t: -(t["excess"] + 0.25 * len(t["bands"]))):
        if any(np.hypot(q["row"] - p["row"], q["col"] - p["col"]) < max(q["outer_px"], p["outer_px"])
               and max(q["radius_px"], p["radius_px"]) / min(q["radius_px"], p["radius_px"]) < 3.0 for p in kept):
            continue
        kept.append(q)
    return kept


def _ring_masks(ring, shape, S, u):
    yy, xx = np.ogrid[:shape[0], :shape[1]]
    dist = np.hypot(yy - ring["row"], xx - ring["col"])
    line = np.zeros(shape, dtype=bool)
    hit = np.zeros(shape, dtype=bool)
    around = np.zeros(shape, dtype=bool)
    for radius, b in ring["bands"]:
        line |= np.abs(dist - radius) <= 1.0
        near = np.abs(dist - radius) <= b
        hit |= near & (S >= u)
        around |= (np.abs(dist - radius) <= 3 * b) & ~near
    return line, hit, around


def _describe_ring(area):
    diam = sorted(round(2 * r) for r in area["radii_m"])
    text = f"A ring-shaped form about {diam[-1]:.0f} m across"
    if len(diam) > 1:
        text += f", with {len(diam)} concentric bands ({', '.join(f'{d:.0f}' for d in diam)} m)"
    drivers = " and ".join(d["phrase"] for d in area["drivers"][:2])
    return (f"{text}; the relief is unusual along {100 * area['coverage']:.0f}% of the circle"
            + (f", {drivers} than the surrounding terrain." if drivers else "."))


def unusual_relief(dem, res, width_m, sensitivity="medium", seed=DEFAULT_SEED, transform=None, larger=True,
                   mask_water=True, water_tilt_deg=WATER_TILT_DEG, water_min_area_m2=WATER_MIN_AREA_M2):
    """Run the whole method on a terrain array. Returns the score, the priority labels, the areas and a report.

    1. Exclude level water surfaces and a buffer around missing data and the data boundary.
    2. Score the unusualness at the feature width and, if `larger`, at 3x the width on a coarser grid; keep the higher.
    3. Find rings and concentric bands of unusual relief, and the unusual areas, lines and straight lines.
    4. Rank them by unusualness x (1 + geometry weight); drop areas that hug the edge of the data.
    """
    if sensitivity not in SENSITIVITY:
        raise ValueError(f"Sensitivity must be one of {', '.join(SENSITIVITY)}.")
    dem = np.asarray(dem, dtype=np.float64)
    missing = ~np.isfinite(dem)
    water = water_mask(dem, res, water_tilt_deg, WATER_BAND_M, water_min_area_m2) if mask_water else np.zeros_like(missing)
    if water.any():
        water = ndimage.binary_dilation(water, iterations=max(1, int(round(WATER_BUFFER_M / res)))) & ~missing
    work = np.where(water, np.nan, dem)
    if np.isfinite(work).sum() < 400:
        raise ValueError("Almost all of this terrain is missing or level water: there is nothing to analyse.")
    score, valid, contrib, X, slrm, model = _score_at(work, res, width_m, seed)
    fine = score.copy()
    scale_used = np.zeros(dem.shape, dtype=np.uint8)
    if larger:
        f = int(LARGE_FACTOR)
        small = _block_mean(work, f)
        if min(small.shape) >= 60:
            try:
                sc_l, valid_l, _, _, _, _ = _score_at(small, res * f, width_m * LARGE_FACTOR, seed)
                big = _upsample(np.where(valid_l, sc_l, np.nan), f, dem.shape) - LARGE_OFFSET
                better = valid & np.isfinite(big) & (big > score)
                score = np.where(better, big, score)
                scale_used[better] = 1
            except ValueError:
                pass
    s, rho = scales(res, width_m)
    # clipped DTMs often carry a strip of interpolated or stretched data along the boundary: the edge band reaches
    # twice the largest filter radius (at least 20 m) beyond the analysed area
    edge_px = int(2 * max(rho, np.ceil(3 * s), round(10.0 / res)))
    edge = ndimage.binary_dilation(~valid, iterations=edge_px) & valid
    score = np.where(valid, score, np.nan).astype(np.float32)
    blob_labels, blobs, stats = priority_areas(score, valid, contrib, X, slrm, res, width_m, transform, sensitivity,
                                               edge_band=edge)
    share, area_floor = SENSITIVITY[sensitivity]
    # rings are made of narrow ditches and banks: they are traced on the fine-scale score
    S = np.where(valid, fine, 0.0)
    rings_raw = detect_rings(np.where(valid, fine, np.nan), valid, edge, res, width_m, seed)
    items = []
    absorbed = set()
    for ring in rings_raw:
        if ring["unusual"] < RING_MIN_UNUSUAL or ring["excess"] < RING_MIN_EXCESS:
            continue
        if (len(ring["bands"]) == 1 and ring["radius_px"] * res < RING_SMALL_M
                and (ring["excess"] < RING_SMALL_EXCESS or ring["unusual"] < RING_SMALL_UNUSUAL)):
            continue  # small single rings must be clearly better than chance: natural bumps make many of them
        line, hit, around = _ring_masks(ring, dem.shape, S, ring["u"])
        line &= valid
        hit &= valid
        if not hit.any():
            continue
        radii_m = [r * res for r, _ in ring["bands"]]
        g = min(2.0, GEOMETRY["ring"] * (0.3 + 2.0 * ring["excess"]) + 0.25 * (len(radii_m) - 1))
        area = {"row": ring["row"], "col": ring["col"], "pixels": int(line.sum()),
                "area_m2": float(np.pi * (ring["outer_px"] * res) ** 2), "mean_score": ring["unusual"],
                "peak_score": float(S[hit].max()), "length_m": 2 * ring["outer_px"] * res,
                "width_m": 2 * ring["outer_px"] * res, "bearing_deg": 0.0, "relief_m": float(np.nanmean(slrm[hit])),
                "drivers": _drivers(hit, around & valid, contrib, X), "kind": "ring", "geometry": g,
                "coverage": ring["coverage"], "radii_m": radii_m, "mask": line,
                "bbox": [int(ring["row"] - ring["outer_px"]), int(ring["col"] - ring["outer_px"]),
                         int(ring["row"] + ring["outer_px"]), int(ring["col"] + ring["outer_px"])]}
        area["note"] = _describe_ring(area)
        for b in blobs:
            if np.hypot(b["row"] - ring["row"], b["col"] - ring["col"]) <= ring["outer_px"] + 2 * ring["bands"][-1][1]:
                absorbed.add(b["label"])
        items.append(area)
    for b in blobs:
        if b["label"] in absorbed:
            continue
        b = dict(b)
        b["mask"] = blob_labels == b["id"]
        b["note"] = _describe(b, res)
        items.append(b)
    for it in items:
        it["priority"] = float(it["mean_score"] * (1.0 + GEOMETRY_WEIGHT * it["geometry"]))
    items.sort(key=lambda a: -a["priority"])
    labels = np.zeros(dem.shape, dtype=np.int32)
    areas = []
    for rank, it in enumerate(items[:MAX_AREAS], 1):
        m = it.pop("mask") & (labels == 0)
        labels[m] = rank
        it.pop("label", None)
        it["id"] = rank
        if transform is not None:
            x, y = transform * (it["col"] + 0.5, it["row"] + 0.5)
            it["x"], it["y"] = float(x), float(y)
        areas.append(it)
    excluded = np.zeros(dem.shape, dtype=np.uint8)
    excluded[(~valid | edge) & ~missing] = 2
    excluded[water] = 1
    data = ~missing
    report = {
        "method": "Unusual relief (one-class Gaussian model of the local terrain over RVT views, with ring detection)",
        "target_width_m": float(width_m), "cell_m": float(res), "sensitivity": sensitivity, "seed": int(seed),
        "larger_structures": bool(larger), "views": [n for _, n in FEATURES], "scale_cells": float(s),
        "rvt_radius_cells": rho, "valid_share": float(valid.mean()), **stats,
        "flagged_share": float((labels > 0)[valid].mean()) if valid.any() else 0.0,
        "n_areas": len(areas), "n_rings": sum(1 for a in areas if a["kind"] == "ring"),
        "water_share": float(water[data].mean()) if data.any() else 0.0,
        "edge_share": float((excluded == 2)[data].mean()) if data.any() else 0.0,
        "large_scale_share": float(scale_used[valid].mean()) if valid.any() else 0.0,
        "model": {"mean": [float(v) for v in model[0]], "covariance": np.round(model[1], 6).tolist()},
        "excluded_mask": excluded,
    }
    report["note"] = summary_sentence(report)
    return score, labels, areas, report


def summary_sentence(report):
    n = report["n_areas"]
    rings = report.get("n_rings", 0)
    what = (f"{n} priority area{'s' if n != 1 else ''} to check"
            + (f", {rings} of them ring-shaped" if rings else "")
            if n else "no priority area: nothing in this terrain is clearly more unusual than the rest")
    excl = []
    if report.get("water_share", 0) >= 0.001:
        excl.append(f"{100 * report['water_share']:.1f}% level water surface")
    if report.get("edge_share", 0) >= 0.001:
        excl.append(f"{100 * report['edge_share']:.1f}% data edge")
    return (f"Unusual relief for features about {report['target_width_m']:g} m wide"
            + (" and larger structures" if report.get("larger_structures") else "") + f": {what}. "
            "Bright places do not look like the rest of this terrain when several RVT views are read together; "
            "rings and curved lines rank first, long straight lines last. "
            + (f"Not analysed (shown grey): {' and '.join(excl)}. " if excl else "")
            + "These are priorities to check, not sites: modern features and data artefacts can show up too.")


# ---------------------------------------------------------------- comparison with RVT views and known features

def _gray(a):
    a = np.asarray(a, dtype=np.float64)
    if a.ndim == 3:
        if a.shape[0] == 3:
            a = np.moveaxis(a, 0, -1)
        return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return a


def vat(dem, res, terrain="general"):
    """RVT's "Archaeological (VAT)" blend with its default settings, as a greyscale image."""
    import rvt.default
    from rvt.blend import BlenderCombination, TerrainSettings

    combos = json.loads((SETTINGS / "default_blender_combinations.json").read_text())["combinations"]
    terrains = json.loads((SETTINGS / "default_terrains_settings.json").read_text())["terrains_settings"]
    cfg = next(c for c in combos if c["combination"]["name"] == "Archaeological (VAT)")
    comb = BlenderCombination(dem_arr=np.asarray(dem, dtype=np.float32).copy(), dem_resolution=res)
    comb.read_from_json(copy.deepcopy(cfg))
    st = rvt.default.DefaultValues()
    ts = TerrainSettings()
    ts.read_from_json(copy.deepcopy(next(t for t in terrains if t["terrain_settings"]["name"] == terrain)))
    ts.apply_terrain(st, comb)
    return _gray(comb.render_all_images(default=st, no_data=np.nan))


def e3mstp(dem, res):
    """RVT's enhanced multi-scale topographic position (e3MSTP), as a greyscale image."""
    import rvt.blend

    return _gray(rvt.blend.e3mstp(np.asarray(dem, dtype=np.float32), res))


def baseline_views(dem, res, width_m, blends=True):
    """The RVT views the AI layer is compared with: single views at radius r, and RVT's VAT and e3MSTP blends."""
    import rvt.vis

    views, filled, _ = rvt_feature_views(dem, res, width_m)
    f = filled.astype(np.float32)
    out = {"Hillshade": np.asarray(rvt.vis.hillshade(f, res, res), dtype=np.float64), "Slope": views["slope"],
           "Sky-view factor": views["svf"], "Positive openness": views["pos_openness"],
           "Negative openness": views["neg_openness"], "Local relief model": views["slrm"]}
    if blends:
        out["VAT (RVT blend)"] = vat(f, res)
        out["e3MSTP (RVT blend)"] = e3mstp(f, res)
    return out


def _window_max(a, radius):
    return ndimage.maximum_filter(a, size=2 * radius + 1, mode="nearest")


def known_feature_scores(layer, site_px, valid, res, width_m, signed=True, n_controls=2000, seed=DEFAULT_SEED):
    """AUC of one layer against known features (points): value at each site (max within W) against random controls
    farther than 3 W from every site. Signed views are compared by their absolute robust z."""
    a = np.asarray(layer, dtype=np.float64)
    a = np.where(valid, a, np.nan)
    a = np.abs(metrics.robust_normalize(a, clip=8.0)) if signed else a
    a = np.nan_to_num(a, nan=-np.inf)
    radius = max(1, int(round(width_m / res)))
    wmax = _window_max(a, radius)
    h, w = a.shape
    pts = [(int(round(r)), int(round(c))) for r, c in site_px if 0 <= round(r) < h and 0 <= round(c) < w]
    pts = [p for p in pts if valid[p]]
    if not pts:
        return None
    near = np.zeros((h, w), dtype=bool)
    for r, c in pts:
        near[r, c] = True
    near = ndimage.binary_dilation(near, iterations=max(1, int(round(3 * width_m / res))))
    pool = np.argwhere(valid & ~near)
    if pool.shape[0] == 0:
        return None
    rng = np.random.default_rng(seed)
    ctrl = pool[rng.choice(pool.shape[0], min(n_controls, pool.shape[0]), replace=False)]
    return metrics.auc([wmax[p] for p in pts], [wmax[r, c] for r, c in ctrl])


def known_feature_report(labels, site_px, res, width_m):
    """Precision at k (share of priority areas within W of a known feature) and hit rate (share of known features
    within W of a priority area)."""
    h, w = labels.shape
    radius = max(1, int(round(width_m / res)))
    pts = [(int(round(r)), int(round(c))) for r, c in site_px if 0 <= round(r) < h and 0 <= round(c) < w]
    if not pts:
        return {"n_sites": 0}
    grown = ndimage.grey_dilation(labels, size=2 * radius + 1)
    hit_ids = {int(grown[p]) for p in pts if grown[p] > 0}
    n_areas = int(labels.max())
    return {"n_sites": len(pts), "n_areas": n_areas,
            "precision_at_k": (len(hit_ids) / n_areas) if n_areas else None,
            "hit_rate": sum(1 for p in pts if grown[p] > 0) / len(pts)}


def compare_with_rvt(dem, res, width_m, score, labels, site_px, blends=True):
    """Compare the AI layer with each RVT view and with VAT and e3MSTP on the known features."""
    valid = np.isfinite(score)
    rows = [{"layer": "Unusual relief (AI)",
             "auc": known_feature_scores(score, site_px, valid, res, width_m, signed=False)}]
    for name, view in baseline_views(dem, res, width_m, blends=blends).items():
        rows.append({"layer": name, "auc": known_feature_scores(view, site_px, valid, res, width_m)})
    rep = known_feature_report(labels, site_px, res, width_m)
    singles = [r for r in rows[1:] if r["auc"] is not None and "blend" not in r["layer"]]
    best = max(singles, key=lambda r: r["auc"]) if singles else None
    ai = rows[0]["auc"]
    blend_rows = {r["layer"]: r["auc"] for r in rows if "blend" in r["layer"]}
    if ai is None or best is None:
        verdict ="The known features fall outside the analysed area, so the comparison could not be made."
    else:
        beats = best is None or ai > best["auc"]
        beats_blends = all(v is None or ai > v for v in blend_rows.values())
        verdict = (f"On your {rep['n_sites']} known features, the AI layer separates them from the rest with AUC "
                   f"{ai:.2f}, against {best['auc']:.2f} for the best single RVT view ({best['layer']})"
                   + "".join(f", {v:.2f} for {k.split(' (')[0]}" for k, v in blend_rows.items() if v is not None) + ". "
                   + ("It does better than all of them here." if beats and beats_blends else
                      "It does not beat every RVT view here: rely on the RVT views for this area."))
    if rep.get("n_areas"):
        verdict += (f" {round((rep['precision_at_k'] or 0) * rep['n_areas'])} of {rep['n_areas']} priority areas are "
                    f"within {width_m:g} m of a known feature; {100 * rep['hit_rate']:.0f}% of the known features are "
                    "inside or near a priority area.")
    return {"rows": rows, "known": rep, "verdict": verdict}
