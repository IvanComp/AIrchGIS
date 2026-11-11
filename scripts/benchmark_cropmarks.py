#!/usr/bin/env python3
"""Run the crop-mark engine over a calibration region and measure it.

    python scripts/benchmark_cropmarks.py --label baseline
    python scripts/benchmark_cropmarks.py --label fase-a --mode "Migliore singola data"

Writes one JSON per run under ``docs/benchmarks/`` so that phases can be
compared on identical numbers. The metrics themselves live in
``airch/benchmark.py`` and carry their own tests.
"""

import argparse
import datetime
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ee  # noqa: E402

from airch import benchmark, cropmarks_engine as c, site_index  # noqa: E402
from airch.scene_ranking import roc_auc  # noqa: E402


REGION_PATH = Path(__file__).resolve().parents[1] / "airch" / "data" / "calibration_region.json"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "benchmarks"
CACHE = Path(__file__).resolve().parents[1] / ".benchmark_cache"

# A Roman farm or villa platform is tens of metres across; two candidates closer
# than 100 m are the same anomaly reported twice.
ANALYSIS_SCALE_M = 20
MIN_PEAK_DISTANCE_M = 100
# Surface scatters are displaced from the buried structure by ploughing, so a
# candidate within 100 m of a catalogue point counts as a hit.
HIT_TOLERANCE_M = 100
TOP_K = 20


def download(image, region, scale, path, crs="EPSG:32633", attempts=4):
    """Fetch a raster, retrying: Earth Engine returns 400 under memory pressure."""
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(attempts):
        try:
            url = ee.Image(image).getDownloadURL(
                {"region": region, "scale": scale, "crs": crs, "filePerBand": False, "format": "GEO_TIFF"}
            )
            urllib.request.urlretrieve(url, path)
            return path
        except Exception as exc:  # noqa: BLE001 - the message is what matters
            last = exc
            detail = exc.read().decode("utf-8", "replace")[:200] if hasattr(exc, "read") else str(exc)[:200]
            print(f"    [{path.name}] tentativo {attempt + 1}/{attempts}: {detail}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download non riuscito dopo {attempts} tentativi: {last}")


def ndvi_stack(aoi, start, end, region_key, dates=10):
    """A seasonal NDVI stack, used only to find field boundaries."""
    path = CACHE / f"{region_key}_stack{ANALYSIS_SCALE_M}.tif"
    if path.exists():
        with rasterio.open(path) as src:
            return src.read().astype(float)
    coll = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(str(start), str(end))
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 15))
        .map(lambda i: i.normalizedDifference(["B8", "B4"]).rename("NDVI").copyProperties(i, ["system:time_start"]))
    )
    # One median per month: fields separate by their rotation, and a fixed
    # number of bands keeps the request small.
    image = ee.Image.cat(
        [
            coll.filter(ee.Filter.calendarRange(month, month, "month")).median().rename(f"m{month:02d}")
            for month in range(1, 13)
        ]
    ).clip(aoi).float()
    download(image, aoi, ANALYSIS_SCALE_M, path)
    with rasterio.open(path) as src:
        return src.read().astype(float)


def to_rowcol(transform, lon, lat):
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)
    x, y = t.transform(lon, lat)
    col, row = ~transform * (x, y)
    return row, col


def legacy_detection(result, aoi, mode):
    """Rebuild the pre-Fase-A detection path on the current scene selection.

    Anomalies computed on the composite, neighbourhood z-scores with no parcel
    constraint. Reconstructing it here rather than comparing against an old run
    keeps both arms on the same scenes, the same grid and the same metrics, so
    only the construction differs.
    """
    top = result["selected_collection"]
    base = top.median().clip(aoi) if str(mode).startswith("Mediana") else result["best_image"]
    deficit = c.vegetation_deficit(base)
    excess = c.vegetation_excess(base)
    strength = deficit.max(excess).rename("Mark_strength")
    linear = strength.multiply(c.structure_coherence(strength)).rename("Linear_marks")
    persistence = c.temporal_persistence(top, result["params"]["persistence_threshold"])
    return (
        deficit.addBands(excess).addBands(strength).addBands(linear).addBands(persistence).clip(aoi).float()
    )


def evaluate(result, band, region_key, label, aoi, sites, k=TOP_K, image=None):
    # Deliberately not result["download_image"]: that image carries the PCA
    # bands, whose eigen decomposition fails on large areas and invalidates the
    # whole export graph. validation_image holds persistence plus the anomaly
    # maps and nothing else.
    path = CACHE / f"{region_key}_{label}_{band}_{ANALYSIS_SCALE_M}.tif"
    source = result["validation_image"] if image is None else image
    download(source.select(band), aoi, ANALYSIS_SCALE_M, path)
    with rasterio.open(path) as src:
        layer = src.read(1).astype(float)
        transform = src.transform
        shape = layer.shape

    mask_path = CACHE / f"{region_key}_mask{ANALYSIS_SCALE_M}.tif"
    if not mask_path.exists():
        download(c.analysis_mask(result["params"].get("open_land_only", True)).clip(aoi), aoi, ANALYSIS_SCALE_M, mask_path)
    with rasterio.open(mask_path) as src:
        analysis_mask = src.read(1).astype(float) > 0.5
    analysis_mask = analysis_mask[: shape[0], : shape[1]]
    # The random baseline, the controls and the edge share must all be computed
    # over the pixels the detector actually looked at. Fase A masks out the band
    # near field boundaries, so its searchable area is smaller and comparing it
    # against a baseline drawn over the whole region would be unfair in both
    # directions.
    searchable = analysis_mask & np.isfinite(layer)

    stack = ndvi_stack(aoi, "2023-01-01", "2026-01-01", region_key)
    stack = stack[:, : shape[0], : shape[1]]
    edges = benchmark.boundary_mask(stack)

    targets = [to_rowcol(transform, s["lon"], s["lat"]) for s in sites]
    targets = [(r, c) for r, c in targets if 0 <= r < shape[0] and 0 <= c < shape[1]]
    reachable = [(r, c) for r, c in targets if searchable[int(round(r)), int(round(c))]]

    peaks = benchmark.local_maxima(layer, MIN_PEAK_DISTANCE_M / ANALYSIS_SCALE_M, mask=searchable, limit=200)
    site_values = benchmark.sample_at(layer, targets)
    rng = np.random.default_rng(11)
    valid = np.argwhere(searchable)
    picks = valid[rng.choice(len(valid), size=min(300, len(valid)), replace=False)]
    control_values = benchmark.sample_at(layer, picks)

    return {
        "label": label,
        "band": band,
        "k": k,
        "peak_values": [p[2] for p in peaks],
        "peak_hits": [bool(benchmark._nearest_distance(p, reachable) <= HIT_TOLERANCE_M / ANALYSIS_SCALE_M) for p in peaks],
        "peak_on_edge": [bool(edges[p[0], p[1]]) for p in peaks],
        "site_values": site_values,
        "control_values": control_values,
        "searchable_px": int(searchable.sum()),
        "peaks": len(peaks),
        "targets": len(targets),
        "auc": roc_auc(site_values, control_values),
        "precision": benchmark.precision_at_k(peaks, targets, HIT_TOLERANCE_M / ANALYSIS_SCALE_M, k),
        "precision_random": benchmark.random_precision_baseline(
            shape, reachable, HIT_TOLERANCE_M / ANALYSIS_SCALE_M, mask=searchable
        ),
        "edge_contamination": benchmark.edge_contamination(peaks, edges, k),
        "edge_share_of_area": float(edges[searchable].mean()) if searchable.any() else None,
        "searchable_share": float(searchable[analysis_mask].mean()) if analysis_mask.any() else None,
        "targets_reachable": len(reachable),
        "params": result["params"],
    }


def pool(reports, k_values=(20, 50)):
    """Combine per-region measurements into one set of numbers.

    Candidates are ranked across all regions together, so a strong anomaly in
    one region competes with a strong anomaly in another, but a hit is always
    judged against the targets of the region the candidate came from.
    """
    ranked = sorted(
        (
            (value, hit, edge)
            for report in reports
            for value, hit, edge in zip(report["peak_values"], report["peak_hits"], report["peak_on_edge"])
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    total_px = sum(report["searchable_px"] for report in reports) or 1
    random_precision = sum(
        (report["precision_random"] or 0.0) * report["searchable_px"] for report in reports
    ) / total_px
    out = {
        "regions": [report["region"] for report in reports],
        "band": reports[0]["band"],
        "label": reports[0]["label"],
        "auc": roc_auc(
            [v for report in reports for v in report["site_values"]],
            [v for report in reports for v in report["control_values"]],
        ),
        "targets": sum(report["targets"] for report in reports),
        "targets_reachable": sum(report["targets_reachable"] for report in reports),
        "peaks": len(ranked),
        "precision_random": random_precision,
        "searchable_share": sum(
            (report["searchable_share"] or 0.0) * report["searchable_px"] for report in reports
        ) / total_px,
        "edge_share_of_area": sum(
            (report["edge_share_of_area"] or 0.0) * report["searchable_px"] for report in reports
        ) / total_px,
    }
    for k in k_values:
        top = ranked[:k]
        out[f"precision@{k}"] = (sum(1 for _, hit, _ in top if hit) / len(top)) if top else None
        out[f"edge@{k}"] = (sum(1 for _, _, edge in top if edge) / len(top)) if top else None
    out["k"] = k_values[0]
    out["precision"] = out[f"precision@{k_values[0]}"]
    out["edge_contamination"] = out[f"edge@{k_values[0]}"]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--band", default="Persistent_any")
    parser.add_argument("--mode", default="Migliore singola data")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default=str(datetime.date.today()))
    parser.add_argument("--topn", type=int, default=12)
    parser.add_argument("--target", default="Automatico")
    parser.add_argument("--legacy", action="store_true", help="misura il percorso pre-Fase A sulle stesse scene")
    args = parser.parse_args()

    setup = json.loads(REGION_PATH.read_text(encoding="utf-8"))
    regions = setup.get("regions") or [setup]
    ee.Initialize()
    known = {s["number"]: s for s in site_index.georeferenced_sites(methods=("pubblicata",))}

    reports = []
    for region in regions:
        bbox = region["bbox"]
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]
            ],
        }
        aoi = c.geom(geometry)
        sites = [known[n] for n in region["sites"] if n in known]
        result = c.run_analysis(
            "",
            datetime.date.fromisoformat(args.start),
            datetime.date.fromisoformat(args.end),
            40,
            args.topn,
            args.mode,
            False,
            "x",
            geometry,
            target=args.target,
        )
        image = legacy_detection(result, aoi, args.mode) if args.legacy else None
        item = evaluate(result, args.band, region["key"], args.label, aoi, sites, image=image)
        item["region"] = region["key"]
        item["scene_count"] = result["scene_count"]
        item["valid_scene_count"] = result["valid_scene_count"]
        item["years"] = result["years"]
        reports.append(item)
        print(f"  {region['key']:>3} {region['name']:<16} {benchmark.summarise(item)}")

    report = pool(reports)
    report["legacy"] = bool(args.legacy)
    report["per_region"] = [
        {key: value for key, value in item.items() if not isinstance(value, list)} for item in reports
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.label}_{args.band}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[{args.label}/{args.band}] AUC {report['auc']:.2f} | "
        f"precision@20 {report['precision@20']:.3f} @50 {report['precision@50']:.3f} "
        f"(caso {report['precision_random']:.3f}) | "
        f"bordi@20 {report['edge@20']:.2f} | bersagli {report['targets_reachable']}/{report['targets']} "
        f"| area cercabile {report['searchable_share']:.0%}"
    )


if __name__ == "__main__":
    main()
