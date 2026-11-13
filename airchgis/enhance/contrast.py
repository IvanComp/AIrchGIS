

from __future__ import annotations

import numpy as np
from scipy import ndimage

from airchgis.enhance import metrics


def _to01(img, p_low=0.5, p_high=99.5):
    a = np.asarray(img, dtype=np.float64)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return np.zeros_like(a), ~np.isfinite(a)
    lo, hi = np.percentile(finite, [p_low, p_high])
    out = np.clip((a - lo) / max(hi - lo, 1e-12), 0, 1)
    mask = ~np.isfinite(out)
    out[mask] = 0.0
    return out, mask


def clahe(img, tiles=8, clip_limit=0.01, bins=256):

    a, mask = _to01(img)
    h, w = a.shape
    ty = max(1, int(round(tiles * h / max(h, w))))
    tx = max(1, int(round(tiles * w / max(h, w))))
    ys = np.linspace(0, h, ty + 1).astype(int)
    xs = np.linspace(0, w, tx + 1).astype(int)
    q = np.minimum((a * (bins - 1)).astype(int), bins - 1)
    luts = np.zeros((ty, tx, bins))
    for i in range(ty):
        for j in range(tx):
            sl = (slice(ys[i], ys[i + 1]), slice(xs[j], xs[j + 1]))
            vals = q[sl][~mask[sl]]
            if vals.size == 0:
                luts[i, j] = np.linspace(0, 1, bins)
                continue
            hist = np.bincount(vals, minlength=bins).astype(np.float64)
            limit = max(1.0, clip_limit * vals.size)
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / bins
            cdf = np.cumsum(hist)
            luts[i, j] = (cdf - cdf[0]) / max(cdf[-1] - cdf[0], 1e-12)

    cy = (ys[:-1] + ys[1:]) / 2.0
    cx = (xs[:-1] + xs[1:]) / 2.0
    yy = np.interp(np.arange(h), cy, np.arange(ty)) if ty > 1 else np.zeros(h)
    xx = np.interp(np.arange(w), cx, np.arange(tx)) if tx > 1 else np.zeros(w)
    y0 = np.floor(yy).astype(int)
    x0 = np.floor(xx).astype(int)
    y1 = np.minimum(y0 + 1, ty - 1)
    x1 = np.minimum(x0 + 1, tx - 1)
    fy = (yy - y0)[:, None]
    fx = (xx - x0)[None, :]
    Y0, X0 = np.meshgrid(y0, x0, indexing="ij")
    Y1, X1 = np.meshgrid(y1, x1, indexing="ij")
    v00 = luts[Y0, X0, q]
    v01 = luts[Y0, X1, q]
    v10 = luts[Y1, X0, q]
    v11 = luts[Y1, X1, q]
    out = (1 - fy) * ((1 - fx) * v00 + fx * v01) + fy * ((1 - fx) * v10 + fx * v11)
    out[mask] = np.nan
    return out


def multiscale_detail(img, sigmas=(1.0, 2.0, 4.0), gains=(1.6, 1.3, 1.1)):

    a, mask = _to01(img)
    base = a
    out = np.zeros_like(a)
    for s, g in zip(sigmas, gains):
        smooth = ndimage.gaussian_filter(base, s)
        out += g * (base - smooth)
        base = smooth
    out += base
    out, _ = _to01(np.where(mask, np.nan, out), 0.5, 99.5)
    out[mask] = np.nan
    return out


def enhance(img, method="clahe", **kw):

    funcs = {"clahe": clahe, "multiscale": multiscale_detail}
    if method not in funcs:
        raise ValueError(f"Unknown method {method}; choose {list(funcs)}.")
    a, mask = _to01(img)
    out = funcs[method](img, **kw)

    def local_contrast(x):
        x = np.nan_to_num(x)
        return float(np.mean(np.abs(x - ndimage.uniform_filter(x, 9))[~mask])) if (~mask).any() else 0.0

    before, after = local_contrast(a), local_contrast(out)
    return out, {"method": method, "metric": "local_contrast", "before": before, "after": after,
                 "note": f"Display contrast {method}: local contrast x{after / max(before, 1e-12):.2f}. "
                         "Display only: values are no longer physical units."}


def pansharpen(ms, pan, method="brovey"):

    ms = np.asarray(ms, dtype=np.float64)
    pan = np.asarray(pan, dtype=np.float64)
    if ms.ndim == 2:
        ms = ms[None]
    ratio = (pan.shape[0] / ms.shape[1], pan.shape[1] / ms.shape[2])
    if min(ratio) < 1.5:
        raise ValueError("The panchromatic band must have a finer grid (at least 1.5x) than the multispectral bands.")
    up = np.stack([ndimage.zoom(np.nan_to_num(b), ratio, order=1)[: pan.shape[0], : pan.shape[1]] for b in ms])
    if up.shape[1:] != pan.shape:
        pad = [(0, 0), (0, pan.shape[0] - up.shape[1]), (0, pan.shape[1] - up.shape[2])]
        up = np.pad(up, pad, mode="edge")
    pan_f = np.nan_to_num(pan)
    if method == "brovey":
        intensity = up.mean(axis=0)
        out = up * (pan_f / np.maximum(intensity, 1e-9))[None]
    elif method == "hpf":
        s = max(ratio) / 2.0
        detail = pan_f - ndimage.gaussian_filter(pan_f, s)
        scale = up.std(axis=(1, 2)) / max(pan_f.std(), 1e-12)
        out = up + detail[None] * scale[:, None, None]
    else:
        raise ValueError("method must be 'brovey' or 'hpf'")
    corr = [float(np.corrcoef(metrics.finite_fill(o - ndimage.gaussian_filter(o, 2))[0].ravel(),
                              (pan_f - ndimage.gaussian_filter(pan_f, 2)).ravel())[0, 1]) for o in out]
    return out, {"method": method, "upsampling": [round(r, 2) for r in ratio], "detail_correlation_with_pan": corr,
                 "note": f"Pan-sharpened ({method}) from a real panchromatic band, x{max(ratio):.1f}: "
                         "spatial detail comes from the pan band, colours from the multispectral bands."}
