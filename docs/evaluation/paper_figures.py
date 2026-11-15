"""Figures for the paper, made with the same functions and default settings as the app (feature width 5 m, medium
sensitivity, seed 0). Writes into paper/img/ and a JSON with the numbers quoted in the text.

Run from the repository root:  .venv_airchgis/bin/python docs/evaluation/paper_figures.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import colormaps  # noqa: E402
from scipy import ndimage  # noqa: E402

from airchgis.ai import synthetic as sy  # noqa: E402
from airchgis.ai import unusual_relief as ur  # noqa: E402
from airchgis.enhance.metrics import zero_nodata  # noqa: E402
from airchgis.terrain.figure3d import render_3d_figure  # noqa: E402
from airchgis.workbench import AI_KIND_COLOURS, hillshade, to_metric  # noqa: E402

IMG = ROOT / "paper" / "img"
UC = ROOT / "airchgis" / "data" / "use_cases"
CASES = {
    "UC1": ("Colle San Mauro", UC / "colle_san_mauro" / "colle_san_mauro_DTM.tif"),
    "UC2": ("Castello di Montedoglio", UC / "castello_montedoglio" / "castello_montedoglio_DTM.tif"),
    "UC3": ("Housesteads", UC / "housesteads" / "Housesteads_EA_DTM_1m.tif"),
}
WIDTH = 5.0
plt.rcParams.update({"font.size": 8, "axes.titlesize": 9})


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


def outlines(ax, labels, areas, top=8):
    for a in areas:
        m = labels == a["id"]
        edge = m & ~ndimage.binary_erosion(m)
        rr, cc = np.nonzero(edge)
        ax.scatter(cc, rr, s=0.15, c=AI_KIND_COLOURS.get(a.get("kind"), "#d62728"), marker="s", linewidths=0)
    for a in areas[:top]:
        ax.text(a["col"], a["row"], str(a["id"]), color="white", fontsize=7, weight="bold", ha="center", va="center",
                bbox=dict(boxstyle="circle,pad=0.15", fc=AI_KIND_COLOURS.get(a.get("kind"), "#d62728"), ec="none"))


def use_case_figure(key, name, path, stats):
    dem, tr, crs = load(path)
    res = abs(tr.a)
    t0 = time.perf_counter()
    score, labels, areas, rep = ur.unusual_relief(dem, res, WIDTH, transform=tr)
    runtime = time.perf_counter() - t0
    hs = hillshade(dem, res)
    out = IMG / key
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        p3 = Path(d) / "ai3d.png"
        render_3d_figure(dem, res, p3, drape=np.clip(np.nan_to_num(score, nan=2.0), 2, 9), dpi=200, width_mm=90,
                         scale_bar=True, north_arrow=True, caption=None, max_side=400, cmap="magma")
        img3 = plt.imread(p3)
    h, w = dem.shape
    fig, ax = plt.subplots(1, 3, figsize=(7.2, 2.7 if w <= h * 1.2 else 2.2), gridspec_kw={"width_ratios": [1, 1, 1.15]})
    ax[0].imshow(hs, cmap="gray", vmin=0, vmax=1)
    ax[0].set_title("(a) Hillshade (RVT, 315°)")
    ax[1].imshow(hs, cmap="gray", vmin=0, vmax=1)
    ax[1].imshow(np.ma.masked_invalid(score), cmap="magma", vmin=2, vmax=9, alpha=0.75)
    outlines(ax[1], labels, areas)
    ax[1].set_title("(b) Unusual relief and priorities")
    ax[2].imshow(img3)
    ax[2].set_title("(c) AI relief (3D)")
    for a_ in ax:
        a_.set_xticks([])
        a_.set_yticks([])
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "ai_relief.png", dpi=220)
    plt.close(fig)
    kinds = {}
    for a in areas:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    stats[key] = {"name": name, "shape": list(dem.shape), "cell_m": round(res, 3), "crs": str(crs),
                  "runtime_s": round(runtime, 1), "n_areas": len(areas), "kinds": kinds,
                  "water_share": round(rep["water_share"], 3), "edge_share": round(rep["edge_share"], 3),
                  "top": [{"id": a["id"], "kind": a["kind"], "priority": round(a["priority"], 2), "note": a["note"]}
                          for a in areas[:5]]}
    return dem, tr, crs


def render_modes_figure(dem, tr, crs):
    """The four 3D modes on the same area, from the viewer's own 3D grid (geometry and colours of each mode),
    drawn with Matplotlib instead of the WebGL viewer."""
    from RVT.scripts import lads_preview as lp

    h, w = dem.shape
    sub = dem[h // 2 - 200: h // 2 + 200, w // 2 - 200: w // 2 + 200]
    from affine import Affine

    t = tr * Affine.translation(w // 2 - 200, h // 2 - 200)
    fig = plt.figure(figsize=(7.2, 2.2))
    for i, mode in enumerate(("original", "cloud1", "cloud2", "cloud3")):
        g = lp.build_browser_terrain_grid(sub.astype("float32"), {"transform": t, "nodata": None}, crs,
                                          target_crs=None, max_side=160, cloud_preprocess_key=mode)
        ax = fig.add_subplot(1, 4, i + 1, projection="3d")
        x, y, z, col, v = g["x"], g["y"], g["z"] * g["z_scale"], g["colors"] / 255.0, g["valid"].astype(bool)
        if g["render_mode"] == "points":
            ax.scatter(x[v][::2], y[v][::2], z[v][::2], c=col[v][::2], s=0.3, linewidths=0)
        else:
            ax.plot_surface(x, y, np.where(v, z, np.nan), facecolors=col, rstride=1, cstride=1, linewidth=0,
                            antialiased=False, shade=False)
            if g["wireframe_overlay"]:
                ax.plot_wireframe(x, y, np.where(v, z, np.nan), rstride=6, cstride=6, color="k", linewidth=0.15)
        ax.view_init(elev=35, azim=-60)
        ax.set_axis_off()
        ax.set_title(lp.CLOUD_PREPROCESS_PROFILES[mode]["label"], pad=-2)
    fig.subplots_adjust(left=0, right=1, top=0.92, bottom=0, wspace=0)
    (IMG / "method").mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / "method" / "render_modes.png", dpi=220)
    plt.close(fig)


def method_diagram():
    steps = [("Prepared DTM", "harmonized, metric,\nvoids filled"),
             ("Leave out", "level water,\ndata edge"),
             ("RVT views", "SVF, openness ±,\nSLRM, slope, DoG"),
             ("Usual relief", "local standardization,\nrobust Gaussian"),
             ("Score", "Mahalanobis\ndistance"),
             ("Structures", "rings, hilltop bands,\nlines, compact"),
             ("Priorities", "u·(1+g),\none sentence each")]
    fig, ax = plt.subplots(figsize=(7.2, 1.25))
    ax.set_xlim(0, len(steps))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, (t, s) in enumerate(steps):
        ax.add_patch(matplotlib.patches.FancyBboxPatch((i + 0.05, 0.12), 0.86, 0.76, boxstyle="round,pad=0.02",
                                                       fc="#f6efe2", ec="#8a6d3b", lw=0.8))
        ax.text(i + 0.48, 0.66, t, ha="center", va="center", weight="bold", fontsize=7.5)
        ax.text(i + 0.48, 0.36, s, ha="center", va="center", fontsize=6.3)
        if i < len(steps) - 1:
            ax.annotate("", xy=(i + 1.05, 0.5), xytext=(i + 0.93, 0.5), arrowprops=dict(arrowstyle="->", lw=0.8))
    fig.savefig(IMG / "method" / "ai_relief_method.pdf", bbox_inches="tight")
    plt.close(fig)


def synthetic_figure(stats):
    cases = [("Smooth relief, ditch, mound, road", sy.terrain("easy", seed=0)[0]),
             ("Ringwork, lake, clipped edge, road", sy.ringwork_site(seed=0)[0]),
             ("Stepped hill, geology, terraces", sy.stepped_hill_site(seed=0)[0])]
    fig, ax = plt.subplots(2, 3, figsize=(7.2, 4.6))
    for j, (title, dem) in enumerate(cases):
        dem = dem.astype(float)
        score, labels, areas, rep = ur.unusual_relief(dem, 1.0, WIDTH)
        hs = hillshade(dem, 1.0)
        ax[0, j].imshow(hs, cmap="gray", vmin=0, vmax=1)
        ax[0, j].set_title(title)
        ax[1, j].imshow(hs, cmap="gray", vmin=0, vmax=1)
        ax[1, j].imshow(np.ma.masked_invalid(score), cmap="magma", vmin=2, vmax=9, alpha=0.75)
        outlines(ax[1, j], labels, areas, top=5)
        stats.setdefault("synthetic", {})[title] = [(a["kind"], round(a["priority"], 2)) for a in areas[:3]]
        for a_ in ax[:, j]:
            a_.set_xticks([])
            a_.set_yticks([])
    fig.tight_layout(pad=0.3)
    fig.savefig(IMG / "method" / "synthetic.png", dpi=200)
    plt.close(fig)


def main():
    stats = {}
    first = None
    for key, (name, path) in CASES.items():
        r = use_case_figure(key, name, path, stats)
        if key == "UC3":
            first = r
        print(key, json.dumps(stats[key])[:300])
    render_modes_figure(*first)
    method_diagram()
    synthetic_figure(stats)
    (ROOT / "docs" / "evaluation" / "paper_figures_stats.json").write_text(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
