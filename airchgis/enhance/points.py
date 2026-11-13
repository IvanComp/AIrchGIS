

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


def outlier_mask(xyz, k=8, std_ratio=2.5, chunk=200_000):

    xyz = np.asarray(xyz, dtype=np.float64)
    n = len(xyz)
    if n <= k:
        return np.zeros(n, dtype=bool)
    tree = cKDTree(xyz)
    mean_d = np.empty(n)
    for s in range(0, n, chunk):
        d, _ = tree.query(xyz[s:s + chunk], k=k + 1)
        mean_d[s:s + chunk] = d[:, 1:].mean(axis=1)
    thr = mean_d.mean() + std_ratio * mean_d.std()
    return mean_d > thr


def remove_outliers(input, output, k=8, std_ratio=2.5):

    import laspy

    las = laspy.read(str(input))
    xyz = np.column_stack([las.x, las.y, las.z])
    out_mask = outlier_mask(xyz, k=k, std_ratio=std_ratio)
    keep = ~out_mask
    out = laspy.LasData(las.header)
    out.points = las.points[keep]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.write(str(output))
    except Exception:
        if output.suffix.lower() != ".laz":
            raise
        output = output.with_suffix(".las")
        out.write(str(output))
    removed = int(out_mask.sum())
    z = xyz[:, 2]
    return {
        "output": str(output),
        "points_before": int(len(xyz)),
        "points_after": int(keep.sum()),
        "points_removed": removed,
        "removed_share": removed / max(len(xyz), 1),
        "z_range_before": [float(z.min()), float(z.max())] if len(z) else None,
        "z_range_after": [float(z[keep].min()), float(z[keep].max())] if keep.any() else None,
        "note": f"{removed} isolated points removed ({100 * removed / max(len(xyz), 1):.2f}%).",
    }
