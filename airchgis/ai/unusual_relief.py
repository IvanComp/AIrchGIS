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
    shape = "linear" if area["length_m"] >= 3 * area["width_m"] else "compact"
    form = "raised" if area["relief_m"] > 0 else "sunken"
    size = (f"about {area['length_m']:.0f} m long and {area['width_m']:.0f} m wide" if shape == "linear"
            else f"about {area['length_m']:.0f} × {area['width_m']:.0f} m")
    drivers = " and ".join(d["phrase"] for d in area["drivers"][:2])
    return f"A {shape}, {form} form, {size}: {drivers} than the surrounding terrain."


def priority_areas(score, valid, contrib, z, slrm, res, width_m, transform=None, sensitivity="medium"):
    """Label the priority areas and describe each one in plain words."""
    share, area_floor = SENSITIVITY[sensitivity]
    floor = PIXEL_FLOOR
    vals = score[valid & np.isfinite(score)]
    cut = max(float(np.quantile(vals, 1.0 - share)), floor) if vals.size else np.inf
    cand = valid & np.isfinite(score) & (score >= cut)
    labels, n = ndimage.label(cand, structure=np.ones((3, 3), dtype=bool))
    min_px = max(4, int(round(0.5 * (width_m / res) ** 2)))
    areas = []
    if n:
        idx = np.arange(1, n + 1)
        sizes = ndimage.sum(cand, labels, idx)
        means = ndimage.mean(score, labels, idx)
        peaks = ndimage.maximum(score, labels, idx)
        order = [i for i in np.argsort(-means) if sizes[i] >= min_px and means[i] >= area_floor]
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
            area = {"id": rank, "row": row, "col": col, "pixels": int(rr.size), "area_m2": float(rr.size * res * res),
                    "mean_score": float(means[i]), "peak_score": float(peaks[i]), "length_m": length, "width_m": width,
                    "bearing_deg": bearing, "relief_m": float(np.nanmean(slrm[rr, cc])), "drivers": drivers,
                    "bbox": [int(rr.min()), int(cc.min()), int(rr.max()), int(cc.max())]}
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
                                            "cut": float(cut), "flagged_share": flagged, "min_area_px": min_px}


def unusual_relief(dem, res, width_m, sensitivity="medium", seed=DEFAULT_SEED, transform=None):
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


def summary_sentence(report):
    n = report["n_areas"]
    what = (f"{n} priority area{'s' if n != 1 else ''} to check ({100 * report['flagged_share']:.2f}% of the area)"
            if n else "no priority area: nothing in this terrain is clearly more unusual than the rest")
    return (f"Unusual relief for features about {report['target_width_m']:g} m wide: {what}. "
            "Bright places do not look like the rest of this terrain when several RVT views are read together. "
            "They are priorities to check, not sites: modern features and data artefacts can show up too.")


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
