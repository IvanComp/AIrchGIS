"""Fused view: a blend of the best visualizations, weighted to maximize visibility.

Layers are robustly normalized and oriented so that features point the same
way (otherwise a ditch dark in one layer and bright in another would cancel).
Two blends are offered:

- ``optimized``: non-negative weights summing to one, found by maximizing the
  visibility score of the blend (starting from the best single layer, so the
  blend is never worse than it);
- ``pca``: the first principal component of the normalized layers.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage, optimize

from airchgis.enhance import metrics


def _prepare(layers):
    names = list(layers)
    z = [metrics.robust_normalize(layers[n], clip=4.0) for n in names]
    return names, z


def _orient(z, res, target_width_m):
    """Flip layers whose target-scale response is anti-correlated with the first (best) layer."""
    s = metrics.target_scale_px(target_width_m, res)

    def band(a):
        f, _ = metrics.finite_fill(a, 0.0)
        return ndimage.gaussian_filter(f, s) - ndimage.gaussian_filter(f, 3 * s)

    ref = band(z[0]).ravel()
    signs = []
    for a in z:
        c = np.corrcoef(ref, band(a).ravel())[0, 1] if np.std(a[np.isfinite(a)]) > 0 else 1.0
        signs.append(-1.0 if np.isfinite(c) and c < 0 else 1.0)
    return [sg * a for sg, a in zip(signs, z)], signs


def _blend(z, w):
    acc = np.zeros_like(z[0])
    wsum = np.zeros_like(z[0])
    for a, wi in zip(z, w):
        ok = np.isfinite(a)
        acc[ok] += wi * a[ok]
        wsum[ok] += wi
    out = acc / np.maximum(wsum, 1e-12)
    out[wsum == 0] = np.nan
    return out


def _softmax(theta):
    e = np.exp(theta - np.max(theta))
    return e / e.sum()


def fuse(layers, res, target_width_m, method="optimized", flat=None, max_iter=200):
    """Blend layers (ordered best first). Returns (fused array, report)."""
    if not layers:
        raise ValueError("No layers to fuse.")
    names, z = _prepare(layers)
    z, signs = _orient(z, res, target_width_m)
    single = [metrics.visibility(a, res, target_width_m, flat)["score"] for a in z]
    best_i = int(np.argmax(single))

    if method == "pca":
        from airchgis.enhance.bestview import _pc1

        fused = _pc1(np.stack(z))
        # PC1 has an arbitrary sign; align it with the best layer
        if np.nansum(fused * z[best_i]) < 0:
            fused = -fused
        weights = None
    elif method == "optimized":
        def neg(theta):
            return -metrics.visibility(_blend(z, _softmax(theta)), res, target_width_m, flat)["score"]

        theta0 = np.zeros(len(z))
        theta0[best_i] = 3.0
        theta, best_val = theta0, neg(theta0)
        if len(z) > 1:
            # two starts: the best single layer and an even blend
            for start in (theta0, np.zeros(len(z))):
                r = optimize.minimize(neg, start, method="Nelder-Mead",
                                      options={"maxiter": max_iter, "xatol": 1e-2, "fatol": 1e-3})
                if r.fun < best_val:
                    theta, best_val = r.x, r.fun
        weights = _softmax(theta)
        fused = _blend(z, weights)
        if metrics.visibility(fused, res, target_width_m, flat)["score"] < single[best_i]:
            weights = np.eye(len(z))[best_i]
            fused = z[best_i]
    else:
        raise ValueError("method must be 'optimized' or 'pca'")

    score = metrics.visibility(fused, res, target_width_m, flat)
    report = {
        "method": method,
        "layers": names,
        "signs": signs,
        "weights": None if weights is None else [float(w) for w in weights],
        "score": score["score"],
        "best_single": {"name": names[best_i], "score": single[best_i]},
        "gain_over_best_single": score["score"] / max(single[best_i], 1e-12),
    }
    if weights is not None:
        parts = ", ".join(f"{n} {100 * w:.0f}%" for n, w in sorted(zip(names, weights), key=lambda t: -t[1]) if w >= 0.01)
        report["note"] = (f"Fused view ({parts}): visibility {score['score']:.2f} against {single[best_i]:.2f} for the best "
                          f"single layer ({names[best_i]}).")
    else:
        report["note"] = (f"First principal component of {len(names)} layers: visibility {score['score']:.2f} against "
                          f"{single[best_i]:.2f} for the best single layer ({names[best_i]}).")
    return fused.astype(np.float32), report


def apply(layers, report):
    """Blend full-size layers with the signs and weights found by :func:`fuse` (e.g. on a smaller window)."""
    names, z = _prepare({n: layers[n] for n in report["layers"]})
    z = [sg * a for sg, a in zip(report["signs"], z)]
    if report["weights"] is None:
        from airchgis.enhance.bestview import _pc1

        out = _pc1(np.stack(z))
        best = report["layers"].index(report["best_single"]["name"])
        if np.nansum(out * z[best]) < 0:
            out = -out
    else:
        out = _blend(z, report["weights"])
    return out.astype(np.float32)
