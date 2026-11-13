

from __future__ import annotations

import numpy as np
from scipy import ndimage

MAD_TO_SIGMA = 1.4826


def finite_fill(a, value=None):

    a = np.asarray(a, dtype=np.float64)
    mask = ~np.isfinite(a)
    out = a.copy()
    if mask.any():
        if value is None and (~mask).any():

            idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
            out = a[idx[0], idx[1]]
        else:
            out[mask] = value or 0.0
    return out, mask


def zero_nodata(a, min_share=0.005, min_level=20.0):

    a = np.asarray(a, dtype=np.float64)
    zeros = a == 0
    if zeros.mean() < min_share:
        return a, 0
    rest = a[np.isfinite(a) & ~zeros]
    if rest.size == 0 or abs(float(np.median(rest))) < min_level:
        return a, 0
    out = a.copy()
    out[zeros] = np.nan
    return out, int(zeros.sum())


def robust_sigma(values):
    v = np.asarray(values, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan")
    return float(MAD_TO_SIGMA * np.median(np.abs(v - np.median(v))))


def noise_sigma(a):

    filled, mask = finite_fill(a)
    if filled.shape[0] < 3 or filled.shape[1] < 3:
        return float("nan")
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    conv = ndimage.convolve(filled, kernel, mode="reflect")
    valid = ~ndimage.binary_dilation(mask, iterations=1)
    valid[[0, -1], :] = False
    valid[:, [0, -1]] = False
    if not valid.any():
        return float("nan")
    return float(np.sqrt(np.pi / 2.0) / 6.0 * np.mean(np.abs(conv[valid])))


def void_fraction(a):
    a = np.asarray(a)
    return float((~np.isfinite(a)).mean()) if a.size else 0.0


def spike_mask(a, size=3, k=6.0, min_abs=None):

    filled, mask = finite_fill(a)
    med = ndimage.median_filter(filled, size=size, mode="reflect")
    res = filled - med
    res[mask] = np.nan
    sigma = robust_sigma(res)
    if not np.isfinite(sigma) or sigma == 0:
        sigma = np.nanstd(res) or 1e-9
    thr = k * sigma
    if min_abs is not None:
        thr = max(thr, float(min_abs))
    out = np.abs(np.nan_to_num(res)) > thr

    extreme = (filled >= ndimage.maximum_filter(filled, size=3)) | (filled <= ndimage.minimum_filter(filled, size=3))
    out &= extreme
    out[ndimage.binary_dilation(mask, iterations=1)] = False
    return out


def spike_fraction(a, **kw):
    return float(spike_mask(a, **kw).mean())


def _highpass(a, sigma_px=3.0):
    filled, mask = finite_fill(a)
    hp = filled - ndimage.gaussian_filter(filled, sigma_px, mode="reflect")
    hp[mask] = 0.0
    return hp


def directional_spectrum(a, n_bins=36, sigma_px=3.0, r_min=3):

    hp = _highpass(a, sigma_px)
    h, w = hp.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    power = np.abs(np.fft.fftshift(np.fft.fft2(hp * win))) ** 2
    yy, xx = np.indices(power.shape)
    cy, cx = h // 2, w // 2
    fy, fx = (yy - cy) / max(h, 1), (xx - cx) / max(w, 1)
    r = np.hypot(yy - cy, xx - cx)
    ang = np.degrees(np.arctan2(fy, fx)) % 180.0
    keep = r >= r_min
    bins = np.minimum((ang[keep] / (180.0 / n_bins)).astype(int), n_bins - 1)
    energy = np.bincount(bins, weights=power[keep], minlength=n_bins)
    total = energy.sum() or 1.0
    return energy / total


def stripe_index(a, n_bins=36, sigma_px=3.0):

    spec = directional_spectrum(a, n_bins, sigma_px)
    med = float(np.median(spec)) or 1e-12
    k = int(np.argmax(spec))
    return float(spec[k] / med), (k + 0.5) * 180.0 / n_bins


def flat_mask(dem, res, percentile=30):

    filled, mask = finite_fill(dem)
    gy, gx = np.gradient(filled, res)
    slope = np.hypot(gx, gy)
    slope[mask] = np.nan
    if not np.isfinite(slope).any():
        return ~mask
    thr = np.nanpercentile(slope, percentile)
    return np.isfinite(slope) & (slope <= thr)


def robust_normalize(a, clip=4.0):

    a = np.asarray(a, dtype=np.float64)
    med = np.nanmedian(a) if np.isfinite(a).any() else 0.0
    s = robust_sigma(a)
    if not np.isfinite(s) or s == 0:
        s = np.nanstd(a) or 1.0
    z = (a - med) / s
    return np.clip(z, -clip, clip)


def target_scale_px(target_width_m, res):
    return max(0.7, float(target_width_m) / float(res) / 2.0)


def visibility(vis, res, target_width_m, flat=None):

    z = robust_normalize(vis)
    filled, mask = finite_fill(z, 0.0)
    s = target_scale_px(target_width_m, res)
    g1 = ndimage.gaussian_filter(filled, s)
    g3 = ndimage.gaussian_filter(filled, 3.0 * s)
    band = g1 - g3
    coarse = g3 - ndimage.gaussian_filter(filled, 9.0 * s)
    fine = filled - ndimage.gaussian_filter(filled, 0.7)
    valid = ~ndimage.binary_dilation(mask, iterations=max(1, int(3 * s)))
    if not valid.any():
        valid = ~mask
    signal = float(np.percentile(np.abs(band[valid]), 95)) if valid.any() else 0.0
    region = valid if flat is None else (valid & flat)
    if region.sum() < 50:
        region = valid
    noise = robust_sigma(fine[region])
    if not np.isfinite(noise) or noise <= 1e-9:
        noise = float(np.std(fine[region])) or 1e-9
    background = float(np.std(coarse[valid])) if valid.any() else 1e-9
    background = max(background, 1e-9)
    return {"signal": signal, "noise": float(noise), "background": background,
            "cnr": signal / noise, "score": signal / float(np.sqrt(noise * background))}


def auc(values_at_sites, controls):

    s = np.asarray([v for v in values_at_sites if np.isfinite(v)], dtype=np.float64)
    c = np.asarray([v for v in controls if np.isfinite(v)], dtype=np.float64)
    if s.size == 0 or c.size == 0:
        return None
    greater = (s[:, None] > c[None, :]).mean()
    ties = (s[:, None] == c[None, :]).mean()
    return float(greater + 0.5 * ties)


def site_auc(vis, site_pixels, n_controls=500, radius_px=1, seed=0):

    z = np.abs(robust_normalize(vis))
    h, w = z.shape
    at = []
    for r, c in site_pixels:
        r, c = int(round(r)), int(round(c))
        if 0 <= r < h and 0 <= c < w:
            win = z[max(0, r - radius_px): r + radius_px + 1, max(0, c - radius_px): c + radius_px + 1]
            if np.isfinite(win).any():
                at.append(float(np.nanmax(win)))
    valid = np.argwhere(np.isfinite(z))
    if not at or len(valid) == 0:
        return None
    rng = np.random.default_rng(seed)
    pick = valid[rng.choice(len(valid), size=min(n_controls, len(valid)), replace=False)]
    controls = []
    for r, c in pick:
        win = z[max(0, r - radius_px): r + radius_px + 1, max(0, c - radius_px): c + radius_px + 1]
        controls.append(float(np.nanmax(win)))
    return auc(at, controls)


def spike_threshold(a, size=3, k=6.0):

    filled, mask = finite_fill(a)
    res = filled - ndimage.median_filter(filled, size=size, mode="reflect")
    res[mask] = np.nan
    sigma = robust_sigma(res)
    if not np.isfinite(sigma) or sigma == 0:
        sigma = float(np.nanstd(res)) or 1e-9
    return k * sigma


def dtm_report(dem, res, spike_abs=None):

    from airchgis.enhance.clean import stripe_energy

    share, ang = stripe_energy(dem)
    thr = spike_threshold(dem) if spike_abs is None else spike_abs
    return {
        "noise_sigma": noise_sigma(dem),
        "stripe_energy": share,
        "stripe_angle_deg": ang,
        "spike_fraction": spike_fraction(dem, k=0.0, min_abs=thr),
        "spike_threshold": thr,
        "void_fraction": void_fraction(dem),
    }
