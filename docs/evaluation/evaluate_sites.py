"""Before/after check of the Unusual relief layer on the three design sites.

These three sites and their target outlines were used to DESIGN the improvement (masks, ring detection, ranking),
so the numbers below are a development check, not an independent evaluation.

Run from the repository root:  .venv_airchgis/bin/python docs/evaluation/evaluate_sites.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from airchgis.ai import unusual_relief as ur  # noqa: E402
from airchgis.enhance.metrics import zero_nodata  # noqa: E402
from airchgis.workbench import to_metric  # noqa: E402

UC = ROOT / "airchgis" / "data" / "use_cases"
SITES = {
    "colle_san_mauro": UC / "colle_san_mauro" / "colle_san_mauro_DTM.tif",
    "castello_montedoglio": UC / "castello_montedoglio" / "castello_montedoglio_DTM.tif",
    "betterton_ring": UC / "england" / "England_EA_DTM_1m.tif",
}
WIDTH = 5.0


def load(path):
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        prof = src.profile.copy()
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
        crs = src.crs
    dem, tr, crs, _ = to_metric(a, prof["transform"], crs, prof)
    dem, _ = zero_nodata(dem)
    return np.asarray(dem, dtype=np.float64), tr, crs


def target_masks(name, tr, crs, shape):
    from pyproj import Transformer

    gj = json.loads((Path(__file__).with_name(f"{name}_target.geojson")).read_text())
    tf = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    ring = [tf.transform(lon, lat) for lon, lat in gj["features"][0]["geometry"]["coordinates"][0]]
    poly = {"type": "Polygon", "coordinates": [ring]}
    inside = rasterize([(poly, 1)], out_shape=shape, transform=tr, fill=0).astype(bool)
    outline = inside & ~ndimage.binary_erosion(inside, iterations=2)
    return inside, outline


def measure(dem, tr, labels, areas, score, inside, outline, res):
    w = max(1, int(round(WIDTH / res)))
    near_target = ndimage.binary_dilation(outline, iterations=2 * w) | inside
    rank = next((a["id"] for a in areas if (near_target & (labels == a["id"])).any()), None)
    covered = ndimage.binary_dilation(labels > 0, iterations=2 * w)
    share = float(covered[outline].mean()) if outline.any() else 0.0
    missing = ~np.isfinite(dem)
    water = ur.water_mask(dem, res)
    # edge of the data: within 30 m of missing data or of the raster border
    outside = missing.copy()
    outside[[0, -1], :] = True
    outside[:, [0, -1]] = True
    edge = ndimage.distance_transform_edt(~outside) * res <= 30.0
    in_water = sum(1 for a in areas if (water & (labels == a["id"])).any())
    on_edge = sum(1 for a in areas
                  if (edge & (labels == a["id"])).sum() > 0.25 * max(1, (labels == a["id"]).sum()))
    rr, cc = np.nonzero(outline)
    pts = list(zip(rr[:: max(1, len(rr) // 60)], cc[:: max(1, len(rr) // 60)]))
    valid = np.isfinite(score)
    auc = ur.known_feature_scores(score, pts, valid, res, WIDTH, signed=False)
    return {"areas": len(areas), "target_rank": rank, "target_kind": next((a.get("kind", "compact") for a in areas
            if a["id"] == rank), None), "target_outline_covered": round(share, 2), "in_water": in_water,
            "on_edge": on_edge, "auc_on_target_outline": None if auc is None else round(auc, 3)}


def main():
    rows = {}
    for name, path in SITES.items():
        dem, tr, crs = load(path)
        res = abs(tr.a)
        inside, outline = target_masks(name, tr, crs, dem.shape)
        s1, l1, a1, _ = ur._unusual_relief_single(dem, res, WIDTH, transform=tr)
        s2, l2, a2, r2 = ur.unusual_relief(dem, res, WIDTH, transform=tr)
        rows[name] = {"before": measure(dem, tr, l1, a1, s1, inside, outline, res),
                      "after": measure(dem, tr, l2, a2, s2, inside, outline, res),
                      "water_share_after": round(r2["water_share"], 3), "edge_share_after": round(r2["edge_share"], 3)}
        print(name, json.dumps(rows[name]))
    Path(__file__).with_name("design_sites_results.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
