"""Measurement harness for the crop-mark detector.

Every phase of the refactor has to be judged on the same numbers, so the metrics
live here as pure array functions: no Earth Engine, no Streamlit, no network.
The script ``scripts/benchmark_cropmarks.py`` fetches the rasters and calls into
this module.

Three questions are asked of a candidate map:

* does it rank known sites above arbitrary locations (AUC);
* of the strongest candidates it proposes, how many land on a known site
  (precision@k);
* how many land on a field boundary instead, which is the failure mode a
  neighbourhood z-score produces when its kernel straddles two crops.
"""

import numpy as np


def local_maxima(array, min_distance_px, mask=None, limit=None):
    """Peaks of ``array`` separated by at least ``min_distance_px``.

    Greedy non-maximum suppression, strongest first. Returns a list of
    ``(row, col, value)`` ordered by decreasing value.
    """
    values = np.array(array, dtype=float)
    if mask is not None:
        values = np.where(np.asarray(mask, dtype=bool), values, np.nan)
    finite = np.isfinite(values)
    if not finite.any():
        return []
    order = np.argsort(np.where(finite, values, -np.inf), axis=None)[::-1]
    radius = float(min_distance_px)
    taken_r, taken_c = [], []
    peaks = []
    for flat in order:
        r, c = np.unravel_index(flat, values.shape)
        if not finite[r, c]:
            break
        if taken_r:
            dr = np.asarray(taken_r) - r
            dc = np.asarray(taken_c) - c
            if np.min(dr * dr + dc * dc) < radius * radius:
                continue
        taken_r.append(r)
        taken_c.append(c)
        peaks.append((int(r), int(c), float(values[r, c])))
        if limit is not None and len(peaks) >= limit:
            break
    return peaks


def _nearest_distance(peak, targets):
    if not len(targets):
        return np.inf
    t = np.asarray(targets, dtype=float)
    d = np.hypot(t[:, 0] - peak[0], t[:, 1] - peak[1])
    return float(d.min())


def precision_at_k(peaks, targets, tolerance_px, k):
    """Share of the top ``k`` candidates that land within tolerance of a target.

    Note this is bounded above by ``len(targets)/k`` when targets are scarce,
    so compare it against the random-placement baseline, never against 1.
    """
    top = peaks[:k]
    if not top:
        return None
    hits = sum(_nearest_distance(p, targets) <= tolerance_px for p in top)
    return hits / len(top)


def random_precision_baseline(shape, targets, tolerance_px, mask=None):
    """Precision a detector placing candidates at random would reach.

    This is the number precision@k has to beat: the share of the searchable
    area that lies within tolerance of a target.
    """
    rows, cols = shape
    yy, xx = np.mgrid[0:rows, 0:cols]
    covered = np.zeros((rows, cols), dtype=bool)
    for tr, tc in np.asarray(targets, dtype=float):
        covered |= (yy - tr) ** 2 + (xx - tc) ** 2 <= tolerance_px ** 2
    if mask is not None:
        m = np.asarray(mask, dtype=bool)
        if not m.any():
            return None
        return float(covered[m].mean())
    return float(covered.mean())


def edge_contamination(peaks, edge_mask, k, dilate_px=0):
    """Share of the top ``k`` candidates sitting on a field boundary."""
    top = peaks[:k]
    if not top:
        return None
    mask = np.asarray(edge_mask, dtype=bool)
    if dilate_px:
        from scipy import ndimage

        mask = ndimage.binary_dilation(mask, iterations=int(dilate_px))
    return sum(bool(mask[r, c]) for r, c, _ in top) / len(top)


def sample_at(array, positions):
    """Values of ``array`` at integer ``(row, col)`` positions, NaNs dropped."""
    values = []
    a = np.asarray(array, dtype=float)
    rows, cols = a.shape
    for r, c in positions:
        r, c = int(round(r)), int(round(c))
        if 0 <= r < rows and 0 <= c < cols and np.isfinite(a[r, c]):
            values.append(float(a[r, c]))
    return values


def boundary_strength(stack):
    """How differently two neighbouring pixels behave through the season.

    ``stack`` is (dates, rows, cols) of an index such as NDVI. Two pixels in the
    same field follow the same curve; two pixels across a boundary do not. The
    result is the maximum Euclidean distance between a pixel's temporal profile
    and those of its four neighbours, which peaks on parcel limits.
    """
    a = np.asarray(stack, dtype=float)
    if a.ndim != 3:
        raise ValueError("stack deve essere (date, righe, colonne)")
    filled = np.where(np.isfinite(a), a, np.nan)
    out = np.zeros(a.shape[1:], dtype=float)
    for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = np.roll(filled, shift=(dr, dc), axis=(1, 2))
        diff = filled - shifted
        with np.errstate(invalid="ignore"):
            dist = np.sqrt(np.nanmean(diff * diff, axis=0))
        out = np.fmax(out, np.nan_to_num(dist, nan=0.0))
    return out


def boundary_mask(stack, percentile=88):
    """Binary field-boundary mask from the temporal dissimilarity."""
    strength = boundary_strength(stack)
    finite = strength[np.isfinite(strength) & (strength > 0)]
    if finite.size == 0:
        return np.zeros(strength.shape, dtype=bool)
    return strength >= np.percentile(finite, percentile)


def summarise(report):
    """One-line rendering of a metric dictionary, for logs and reports."""
    def fmt(key, digits=3):
        value = report.get(key)
        return "n.d." if value is None else f"{value:.{digits}f}"

    return (
        f"AUC {fmt('auc',2)} | precision@{report.get('k', 20)} {fmt('precision')} "
        f"(caso {fmt('precision_random')}) | su bordi {fmt('edge_contamination')} "
        f"| candidati {report.get('peaks', 0)}"
    )
