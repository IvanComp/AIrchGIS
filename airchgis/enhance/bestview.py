

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from airchgis.enhance import metrics

MAX_SCORE_SIDE = 768


@dataclass
class Candidate:
    name: str
    family: str
    params: dict
    func: object = field(repr=False)


def _fit(out, shape):
    out = np.asarray(out, dtype=np.float32)
    if out.shape == shape:
        return out
    full = np.full(shape, np.nan, dtype=np.float32)
    dy, dx = (shape[0] - out.shape[0]) // 2, (shape[1] - out.shape[1]) // 2
    full[dy: dy + out.shape[0], dx: dx + out.shape[1]] = out[: shape[0], : shape[1]]
    return full


def _pc1(stack):
    s = np.asarray(stack, dtype=np.float64)
    n = s.shape[0]
    flat = s.reshape(n, -1)
    ok = np.all(np.isfinite(flat), axis=0)
    x = flat[:, ok]
    x = (x - x.mean(axis=1, keepdims=True)) / (x.std(axis=1, keepdims=True) + 1e-12)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    out = np.full(flat.shape[1], np.nan)
    out[ok] = vt[0]
    return out.reshape(s.shape[1:])


def candidates(res, target_width_m, quick=False):

    import rvt.vis

    t = max(1.0, float(target_width_m) / float(res))
    radii = sorted({int(np.clip(round(f * t), 3, 40)) for f in ((1, 2, 4) if not quick else (2,))})
    lrm = sorted({int(np.clip(round(f * t), 10, 50)) for f in ((2, 4, 8) if not quick else (4,))})
    out = []
    for az in (315, 45, 135, 225) if not quick else (315,):
        out.append(Candidate(f"Hillshade {az} deg", "hillshade", {"azimuth": az, "altitude": 35},
                             lambda d, az=az: rvt.vis.hillshade(d, res, res, sun_azimuth=az, sun_elevation=35)))
    out.append(Candidate("Multi-direction hillshade (16 dirs, PC1)", "hillshade", {"directions": 16},
                         lambda d: _pc1(rvt.vis.multi_hillshade(d, res, res, nr_directions=16))))
    out.append(Candidate("Slope", "slope", {}, lambda d: rvt.vis.slope_aspect(d, res, res, output_units="degree")["slope"]))
    for r in radii:
        out.append(Candidate(f"Sky-view factor r={r * res:.3g} m", "svf", {"radius_px": r},
                             lambda d, r=r: rvt.vis.sky_view_factor(d, res, compute_svf=True, compute_opns=False,
                                                                     svf_n_dir=16, svf_r_max=r)["svf"]))
        out.append(Candidate(f"Positive openness r={r * res:.3g} m", "openness", {"radius_px": r},
                             lambda d, r=r: rvt.vis.sky_view_factor(d, res, compute_svf=False, compute_opns=True,
                                                                     svf_n_dir=16, svf_r_max=r)["opns"]))
        out.append(Candidate(f"Negative openness r={r * res:.3g} m", "openness", {"radius_px": r, "negative": True},
                             lambda d, r=r: rvt.vis.sky_view_factor(-d, res, compute_svf=False, compute_opns=True,
                                                                     svf_n_dir=16, svf_r_max=r)["opns"]))
    for r in lrm:
        out.append(Candidate(f"Local relief model r={r * res:.3g} m", "lrm", {"radius_px": r},
                             lambda d, r=r: rvt.vis.slrm(d, radius_cell=r)))
    fmin, fmax = max(res, target_width_m / 2.0), max(4 * res, target_width_m * 8.0)
    out.append(Candidate(f"Multi-scale relief model {fmin:.3g}-{fmax:.3g} m", "msrm", {"feature_min_m": fmin, "feature_max_m": fmax},
                         lambda d: rvt.vis.msrm(d, res, fmin, fmax, 2)))
    return out


def _window(dem, side=MAX_SCORE_SIDE):
    h, w = dem.shape
    if max(h, w) <= side:
        return (slice(0, h), slice(0, w))
    y0 = max(0, (h - side) // 2)
    x0 = max(0, (w - side) // 2)
    return (slice(y0, y0 + min(side, h)), slice(x0, x0 + min(side, w)))


def compute(cand, dem):
    filled, mask = metrics.finite_fill(dem)
    out = _fit(cand.func(filled.astype(np.float32)), filled.shape)
    out[mask] = np.nan
    return out


def rank(dem, res, target_width_m, site_pixels=None, quick=False, keep_arrays=True):

    dem = np.asarray(dem, dtype=np.float64)
    win = _window(dem)
    sub = dem[win]
    flat = metrics.flat_mask(sub, res)
    sites = None
    if site_pixels:
        sites = [(r - win[0].start, c - win[1].start) for r, c in site_pixels]
    rows, arrays = [], {}
    for cand in candidates(res, target_width_m, quick=quick):
        try:
            vis = compute(cand, sub)
        except Exception as exc:
            rows.append({"name": cand.name, "family": cand.family, "params": cand.params, "score": None, "error": str(exc)})
            continue
        v = metrics.visibility(vis, res, target_width_m, flat)
        row = {"name": cand.name, "family": cand.family, "params": cand.params, **v}
        if sites:
            row["auc"] = metrics.site_auc(vis, sites)
        rows.append(row)
        if keep_arrays:
            arrays[cand.name] = vis
    ok = sorted([r for r in rows if r.get("score") is not None], key=lambda r: -r["score"])
    failed = [r for r in rows if r.get("score") is None]
    return {"ranking": ok, "failed": failed, "arrays": arrays, "window": win,
            "scored_on": "whole raster" if sub.shape == dem.shape else f"central {sub.shape[0]}x{sub.shape[1]} px window",
            "target_width_m": float(target_width_m), "explanation": explain(ok, target_width_m, res)}


def compute_named(dem, res, target_width_m, name):

    for cand in candidates(res, target_width_m):
        if cand.name == name:
            return compute(cand, np.asarray(dem, dtype=np.float64))
    raise KeyError(name)


def rank_layers(layers, res, target_width_m, site_pixels=None, flat=None):

    rows = []
    for name, a in layers.items():
        a = np.asarray(a, dtype=np.float64)
        if not np.isfinite(a).any() or np.nanstd(a) == 0:
            continue
        v = metrics.visibility(a, res, target_width_m, flat)
        row = {"name": name, "family": "layer", "params": {}, **v}
        if site_pixels:
            row["auc"] = metrics.site_auc(a, site_pixels)
        rows.append(row)
    rows.sort(key=lambda r: -r["score"])
    return {"ranking": rows, "explanation": explain(rows, target_width_m, res)}


def explain(ranking, target_width_m, res):
    if not ranking:
        return "No visualization could be computed on this raster."
    top = ranking[0]
    parts = [f"{top['name']} shows features about {target_width_m:g} m wide most clearly (visibility {top['score']:.2f}): "
             f"at that scale it lifts them {top['cnr']:.1f} times above the noise of flat areas while keeping the broad "
             f"landscape relief in check"]
    if len(ranking) > 1:
        second = ranking[1]
        parts.append(f"; the runner-up is {second['name']} ({second['score']:.2f})")
    parts.append(".")
    radius = top["params"].get("radius_px")
    if radius:
        parts.append(f" Its radius is {radius * res:.3g} m, {radius * res / target_width_m:.2g} times the width sought.")
    if top["family"] == "hillshade" and "azimuth" in top["params"]:
        parts.append(" A single light direction hides features parallel to it: check the multi-direction view too.")
    worst = ranking[-1]
    if len(ranking) > 2:
        parts.append(f" The weakest was {worst['name']} ({worst['score']:.2f}).")
    aucs = [r for r in ranking if r.get("auc") is not None]
    if aucs:
        best_auc = max(aucs, key=lambda r: r["auc"])
        parts.append(f" At your known sites, {top['name']} has AUC {top.get('auc', float('nan')):.2f}"
                     + (f"; the highest AUC is {best_auc['auc']:.2f} ({best_auc['name']})." if best_auc is not top else "."))
        parts.append(" AUC on a few, non-random sites is a sanity check, not a validation.")
    parts.append(" The score measures visibility, not the probability that a site exists.")
    return "".join(parts)
