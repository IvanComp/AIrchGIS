

from __future__ import annotations

import numpy as np
from scipy import ndimage

from airchgis.enhance import metrics

STEPS = ("destripe", "despike", "fill_voids", "denoise")


def _spectrum_geometry(h, w):
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    rho = np.hypot(fy, fx)
    ang = np.degrees(np.arctan2(fy, fx)) % 180.0
    return rho, ang


def periodic_peaks(P, angle_deg=None, width_deg=10.0, k=3.0, n_r=48, n_a=36):

    h, w = P.shape
    rho, ang = _spectrum_geometry(h, w)
    rbin = np.minimum((rho / (rho.max() + 1e-12) * n_r).astype(int), n_r - 1)
    ref = []
    for i in range(n_r):
        values = P[rbin == i]
        ref.append(np.median(values, overwrite_input=True) if values.size else 0.0)
    refmap = np.asarray(ref)[rbin]
    cand = (rho > 3.0 / max(h, w)) & (P > k * refmap)
    if angle_deg is not None:
        d = np.abs(((ang - angle_deg) + 90.0) % 180.0 - 90.0)
        cand &= d <= width_deg
    peaks = np.zeros_like(cand)
    if cand.any():
        Ps = np.fft.fftshift(P)
        cy, cx = h // 2, w // 2
        iy, ix = np.nonzero(np.fft.fftshift(cand))
        uy, ux = iy - cy, ix - cx
        neigh = [ndimage.map_coordinates(Ps, [cy + uy * f, cx + ux * f], order=1, mode="nearest")
                 for f in (0.7, 0.78, 0.85, 1.15, 1.22, 1.3)]
        along = np.median(np.vstack(neigh), axis=0)
        keep = Ps[iy, ix] > k * np.maximum(along, 1e-30)
        m = np.zeros_like(Ps, dtype=bool)
        m[iy[keep], ix[keep]] = True
        m = ndimage.binary_dilation(m, iterations=1)
        peaks = np.fft.ifftshift(m) & (rho > 3.0 / max(h, w))
    return peaks, refmap, ang


def _highpass_spectrum(a, sigma_px, pad):
    filled, mask = metrics.finite_fill(a)
    low = ndimage.gaussian_filter(filled, sigma_px, mode="reflect")
    hp = np.pad(filled - low, pad, mode="reflect")
    return filled, mask, low, np.fft.fft2(hp)


def stripe_energy(dem, sigma_px=3.0, k=6.0, pad=16):

    _, _, _, F = _highpass_spectrum(dem, sigma_px, pad)
    P = np.abs(F) ** 2
    peaks, _, ang = periodic_peaks(P, k=k)
    total = P.sum() or 1.0
    share = float(P[peaks].sum() / total)
    main = float(np.average(ang[peaks], weights=P[peaks])) if peaks.any() else None
    return share, main


def destripe(dem, angle_deg=None, sigma_px=3.0, width_deg=10.0, k=6.0, min_share=0.02, force=False, pad=16, passes=2):

    out, rep = _destripe_once(dem, angle_deg, sigma_px, width_deg, k, min_share, force, pad)
    notes, total_damped = [rep["note"]], rep.get("frequencies_damped", 0)
    for _ in range(int(passes) - 1):
        if not rep.get("applied"):
            break
        nxt, r2 = _destripe_once(out, angle_deg, sigma_px, width_deg, k, min_share, False, pad)
        if not r2.get("applied"):
            break
        out, total_damped = nxt, total_damped + r2["frequencies_damped"]
        notes.append(r2["note"])
        rep.update(after=r2["after"])
    if rep.get("applied"):
        filled, mask = metrics.finite_fill(dem)
        diff = filled - np.nan_to_num(out, nan=0.0)
        diff[mask] = np.nan
        rep.update(frequencies_damped=total_damped, rms_change=float(np.sqrt(np.nanmean(diff ** 2))),
                   note=" ".join(notes))
    return out, rep


def _destripe_once(dem, angle_deg=None, sigma_px=3.0, width_deg=10.0, k=6.0, min_share=0.02, force=False, pad=16):

    a = np.asarray(dem, dtype=np.float64)
    filled, mask, low, F = _highpass_spectrum(a, sigma_px, pad)
    P = np.abs(F) ** 2
    peaks, refmap, ang = periodic_peaks(P, angle_deg, width_deg, k)
    total = P.sum() or 1.0
    before = float(P[peaks].sum() / total)
    main = float(np.average(ang[peaks], weights=P[peaks])) if peaks.any() else None
    report = {"step": "destripe", "metric": "stripe_energy", "before": before, "angle_deg": main}
    if before < min_share and not force:
        report.update(applied=False, after=before,
                      note=f"No banding found (periodic stripes carry {100 * before:.1f}% of the fine-scale energy).")
        return a.copy(), report
    gain = np.ones_like(P)
    gain[peaks] = np.minimum(1.0, np.sqrt(np.maximum(refmap[peaks], 1e-30) / np.maximum(P[peaks], 1e-30)))
    hp_clean = np.real(np.fft.ifft2(F * gain))[pad:-pad, pad:-pad]
    out = low + hp_clean
    out[mask] = np.nan
    after, _ = stripe_energy(out, sigma_px, k, pad)
    removed = filled - out
    removed[mask] = np.nan
    report.update(applied=True, after=after, frequencies_damped=int(peaks.sum()),
                  rms_change=float(np.sqrt(np.nanmean(removed ** 2))),
                  note=f"Periodic banding (frequency orientation about {main:.0f} deg) damped: stripe energy "
                       f"{100 * before:.1f}% -> {100 * after:.1f}% of the fine-scale signal; "
                       f"mean change {np.sqrt(np.nanmean(removed ** 2)):.3g} elevation units.")
    return out, report


def remove_spikes(dem, size=3, k=6.0, min_abs=None):
    a = np.asarray(dem, dtype=np.float64)
    mask = metrics.spike_mask(a, size=size, k=k, min_abs=min_abs)
    before = float(mask.mean())
    out = a.copy()
    if mask.any():
        filled, nan = metrics.finite_fill(a)
        med = ndimage.median_filter(filled, size=size, mode="reflect")
        out[mask] = med[mask]
    after = metrics.spike_fraction(out, size=size, k=k, min_abs=min_abs)
    return out, {"step": "despike", "metric": "spike_fraction", "before": before, "after": after,
                 "applied": bool(mask.any()), "pixels_replaced": int(mask.sum()),
                 "note": f"{int(mask.sum())} spikes or pits replaced by the local median."}


def fill_voids(dem, max_void_px=None, iterations=300):

    a = np.asarray(dem, dtype=np.float64)
    holes = ~np.isfinite(a)
    before = float(holes.mean())
    report = {"step": "fill_voids", "metric": "void_fraction", "before": before}
    if not holes.any() or holes.all():
        report.update(applied=False, after=before, note="No voids to fill." if not holes.any() else "No valid data.")
        return a.copy(), report
    fill = holes.copy()
    if max_void_px:
        lab, n = ndimage.label(holes)
        sizes = ndimage.sum(holes, lab, range(1, n + 1))
        big = np.isin(lab, np.flatnonzero(sizes > max_void_px) + 1)
        fill &= ~big

    lab, n = ndimage.label(fill)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    fill &= ~np.isin(lab, border[border > 0])
    out = a.copy()
    if fill.any():
        idx = ndimage.distance_transform_edt(holes, return_distances=False, return_indices=True)
        out[fill] = a[idx[0][fill], idx[1][fill]]
        kernel = np.array([[0, 0.25, 0], [0.25, 0, 0.25], [0, 0.25, 0]])
        work = np.where(np.isfinite(out), out, 0.0)
        for _ in range(int(iterations)):
            sm = ndimage.convolve(work, kernel, mode="nearest")
            work[fill] = sm[fill]
        out[fill] = work[fill]
    after = metrics.void_fraction(out)
    report.update(applied=bool(fill.any()), after=after, pixels_filled=int(fill.sum()), filled_mask=fill,
                  note=f"{int(fill.sum())} void pixels filled from their borders; "
                       f"{int((holes & ~fill).sum())} left empty (outside the survey or too large).")
    return out, report


def _box(a, r):
    return ndimage.uniform_filter(a, size=2 * r + 1, mode="reflect")


def guided_filter(img, radius=2, eps=1e-3):

    I = np.asarray(img, dtype=np.float64)
    mean = _box(I, radius)
    var = np.maximum(_box(I * I, radius) - mean * mean, 0.0)
    a = var / (var + eps)
    b = mean * (1.0 - a)
    return _box(a, radius) * I + _box(b, radius)


def denoise(dem, radius_px=2, strength=2.0):

    a = np.asarray(dem, dtype=np.float64)
    noise = metrics.noise_sigma(a)
    report = {"step": "denoise", "metric": "noise_sigma", "before": noise}
    if not np.isfinite(noise) or noise <= 0:
        report.update(applied=False, after=noise, note="Noise not measurable.")
        return a.copy(), report
    filled, mask = metrics.finite_fill(a)
    trend = ndimage.gaussian_filter(filled, 4 * radius_px, mode="reflect")
    detail = filled - trend
    out = trend + guided_filter(detail, int(radius_px), (strength * noise) ** 2)
    out[mask] = np.nan
    after = metrics.noise_sigma(out)
    report.update(applied=True, after=after, radius_px=int(radius_px), eps=(strength * noise) ** 2,
                  note=f"Noise {noise:.3g} -> {after:.3g} (same units as the elevation); edges larger than the noise kept.")
    return out, report


def clean_dtm(dem, res, steps=STEPS, options=None):

    options = options or {}
    order = [s for s in STEPS if s in steps]
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise ValueError(f"Unknown cleaning steps: {sorted(unknown)}; choose from {STEPS}.")
    before = metrics.dtm_report(dem, res)
    thr = before["spike_threshold"]
    out = np.asarray(dem, dtype=np.float64)
    reports = []
    funcs = {"destripe": destripe, "despike": remove_spikes, "fill_voids": fill_voids, "denoise": denoise}
    for s in order:
        out, rep = funcs[s](out, **options.get(s, {}))
        reports.append(rep)
    after = metrics.dtm_report(out, res, spike_abs=thr)
    return out, reports, {"before": before, "after": after}


def plain_summary(reports):
    return [r["note"] for r in reports]
