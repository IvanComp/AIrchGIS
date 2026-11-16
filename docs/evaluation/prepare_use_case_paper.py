import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import rasterio
import rvt.vis

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from airchgis.enhance.metrics import finite_fill
from airchgis.use_cases import CASES
from airchgis.workbench import to_metric


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(case):
    source = case["path"]
    output = source.parent / "paper"
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source) as src:
        terrain = src.read(1, masked=True).astype("float32").filled(np.nan)
        native = {
            "crs": str(src.crs), "shape_rows_columns": list(terrain.shape),
            "cell_size_crs_units": list(src.res), "bounds": list(src.bounds),
            "nodata": str(src.nodata), "valid_cells": int(np.isfinite(terrain).sum()),
            "elevation_min_max": [float(np.nanmin(terrain)), float(np.nanmax(terrain))],
        }
        dem, transform, crs, _ = to_metric(terrain, src.transform, src.crs, src.profile)
    dem = np.asarray(dem, dtype=np.float32)
    filled, missing = finite_fill(dem)
    res_x, res_y = abs(transform.a), abs(transform.e)
    shades = []
    for azimuth in (315, 45):
        shade = rvt.vis.hillshade(filled, res_x, res_y, sun_azimuth=azimuth,
                                  sun_elevation=35, ve_factor=1)
        shades.append(np.where(missing, np.nan, shade))
    extent = [0, dem.shape[1] * res_x, 0, dem.shape[0] * res_y]
    plt.rcParams.update({"font.size": 9, "font.family": "DejaVu Sans"})
    fig, axes = plt.subplots(1, 3, figsize=(13.8, 4.8), layout="constrained")
    elevation = axes[0].imshow(dem, cmap="terrain", extent=extent, interpolation="nearest")
    fig.colorbar(elevation, ax=axes[0], shrink=.7, label="DTM elevation (source units)")
    axes[0].set_title("Elevation")
    for ax, shade, azimuth in zip(axes[1:], shades, (315, 45)):
        ax.imshow(shade, cmap="gray", vmin=0, vmax=1, extent=extent, interpolation="nearest")
        ax.set_title(f"Hillshade · azimuth {azimuth}°\nSolar altitude 35° · RVT")
    for ax in axes:
        ax.set_xlabel("Easting offset (m)")
        ax.set_ylabel("Northing offset (m)")
        ax.set_aspect("equal")
    fig.suptitle(case["label"], fontsize=12)
    fig.savefig(figures / "terrain_comparison.png", dpi=300)
    fig.savefig(figures / "terrain_comparison.pdf")
    plt.close(fig)
    metadata = {
        "case": case["label"], "app_case_id": case["id"],
        "input": str(source.relative_to(ROOT)), "input_sha256": digest(source),
        "native_grid": native,
        "figure_grid": {"crs": str(crs), "shape_rows_columns": list(dem.shape),
                        "cell_size_m": [res_x, res_y], "affine": list(transform)[:6],
                        "valid_cells": int(np.isfinite(dem).sum())},
        "processing": {
            "geographic_inputs": "App to_metric: bilinear reprojection to local UTM; projected inputs retained.",
            "void_handling": "Nearest finite fill for derivatives only; original metric NoData mask restored before plotting.",
            "hillshade": {"azimuth_degrees": [315, 45], "sun_altitude_degrees": 35, "vertical_factor": 1},
            "display": "Hillshade fixed range 0–1; native metric grid displayed without smoothing; PNG 300 dpi and PDF.",
            "scope": "Illustrative terrain figures only; no AI analysis, water exclusion or archaeological classification.",
        },
        "software": {name: importlib.metadata.version(name) for name in ("numpy", "rasterio", "matplotlib", "rvt-py")},
        "code": {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                 "dirty_checkout": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
                 "script_sha256": digest(Path(__file__)),
                 "metric_preparation_sha256": digest(ROOT / "airchgis/workbench.py"),
                 "fill_implementation_sha256": digest(ROOT / "airchgis/enhance/metrics.py")},
    }
    (output / "terrain_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (figures / "CAPTION.md").write_text(
        f"Terrain visualization of {case['label']}. Left: elevation; centre and right: RVT hillshade "
        "with illumination azimuths 315° and 45°, respectively, both at a solar altitude of 35° "
        "and vertical factor 1. White areas indicate missing survey data. Coordinates are offsets "
        "from the south-west corner of the metric raster. Geographic inputs were reprojected "
        "using bilinear interpolation; the supplied source DTM was not modified. These panels "
        "illustrate the effect of illumination direction and do not establish archaeological interpretations. "
        "See [processing metadata](../terrain_metadata.json) and "
        "[source provenance](../../provenance.json) for settings and attribution.\n"
    )
    checksums = [f"{digest(path)}  {path.relative_to(output)}" for path in sorted(output.rglob("*"))
                 if path.is_file() and path.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    print(f"Prepared {output.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=[case["path"].parent.name for case in CASES])
    args = parser.parse_args()
    for case in CASES:
        if not args.case or case["path"].parent.name == args.case:
            build(case)
