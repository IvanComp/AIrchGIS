"""Crop- and soil-mark screening on uploaded images, without Earth Engine.

Same logic as the Earth Engine engine, on numpy arrays:

1. indices per date (NDVI, SAVI, NDRE with red edge, NDMI with SWIR; for
   RGB-only images the visible greenness index VARI and brightness);
2. local contrast: each index minus its neighbourhood mean (default 60 m,
   the scale of a wall or ditch), divided by the neighbourhood spread;
3. crop phase per date (vegetation / bare soil / mixed) and a ranking of the
   dates by local contrast inside the area;
4. per-date anomaly maps aggregated afterwards: vegetation deficit and excess,
   soil marks, linear marks (gradient coherence), persistence across dates;
5. field-boundary mask from the temporal dissimilarity of neighbouring pixels
   (needs at least two dates), so edges between parcels are not ranked as marks.

All dates must share one grid (the first scene's); others are resampled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from airch import benchmark

EPS = 1e-6


def indices(bands: dict) -> dict:
    r, g, b = bands.get("red"), bands.get("green"), bands.get("blue")
    nir, re_, sw = bands.get("nir"), bands.get("rededge"), bands.get("swir1")
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        if nir is not None and r is not None:
            out["NDVI"] = (nir - r) / (nir + r + EPS)
            out["SAVI"] = 1.5 * (nir - r) / (nir + r + 0.5)
        if nir is not None and re_ is not None:
            out["NDRE"] = (nir - re_) / (nir + re_ + EPS)
        if nir is not None and sw is not None:
            out["NDMI"] = (nir - sw) / (nir + sw + EPS)
        if r is not None and g is not None and b is not None:
            out["VARI"] = (g - r) / (g + r - b + EPS)
            out["Brightness"] = (r + g + b) / 3.0
        elif r is not None and nir is not None:
            out["Brightness"] = (r + nir) / 2.0
    for k, v in out.items():
        v[~np.isfinite(v)] = np.nan
        if k == "VARI":
            np.clip(v, -1, 1, out=v)
    return out


def vegetation_index(idx: dict):
    for k in ("NDVI", "SAVI", "VARI"):
        if k in idx:
            return k, idx[k]
    raise ValueError("Need at least red and near-infrared, or red, green and blue bands.")


def _nan_uniform(a, size):
    valid = np.isfinite(a)
    filled = np.where(valid, a, 0.0)
    num = ndimage.uniform_filter(filled, size=size, mode="nearest")
    den = ndimage.uniform_filter(valid.astype(float), size=size, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / den, den


def local_z(a, radius_px):
    size = int(2 * max(1, radius_px) + 1)
    mean, den = _nan_uniform(a, size)
    sq, _ = _nan_uniform(a * a, size)
    with np.errstate(invalid="ignore"):
        sd = np.sqrt(np.maximum(sq - mean * mean, 0))
    floor = np.nanmedian(sd[np.isfinite(sd)]) * 0.25 if np.isfinite(sd).any() else 0
    z = (a - mean) / np.maximum(sd, max(floor, EPS))
    z[(den < 0.3) | ~np.isfinite(a)] = np.nan
    return z


def coherence(a, sigma=1.5):
    """Directional coherence of the local gradient: ~1 on linear features, ~0 on isotropic noise."""
    f = np.where(np.isfinite(a), a, np.nanmedian(a) if np.isfinite(a).any() else 0)
    gx, gy = ndimage.sobel(f, axis=1), ndimage.sobel(f, axis=0)
    jxx = ndimage.gaussian_filter(gx * gx, sigma)
    jyy = ndimage.gaussian_filter(gy * gy, sigma)
    jxy = ndimage.gaussian_filter(gx * gy, sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + EPS)
    return np.clip(np.nan_to_num(c), 0, 1)


def boundary_mask_from_shape(stack, percentile=88, min_strength=0.02):
    """Field boundaries where neighbouring seasonal curves differ in shape (stack already de-meaned)."""
    strength = benchmark.boundary_strength(stack)
    finite = strength[np.isfinite(strength) & (strength > 0)]
    if finite.size == 0:
        return np.zeros(strength.shape, dtype=bool)
    return strength >= max(np.percentile(finite, percentile), min_strength)


def crop_phase(veg_name, veg):
    v = veg[np.isfinite(veg)]
    if v.size == 0:
        return "unknown", np.nan, np.nan
    bare_thr, veg_thr = (0.25, 0.4) if veg_name != "VARI" else (0.0, 0.1)
    mean, bare = float(np.mean(v)), float(np.mean(v < bare_thr))
    if bare > 0.5:
        return "bare soil", mean, bare
    if mean >= veg_thr:
        return "vegetation", mean, bare
    return "mixed", mean, bare


@dataclass
class LocalResult:
    layers: dict
    table: list
    transform: object
    crs: object
    gsd_m: float
    params: dict
    vegetation_index: str
    boundary_mask: np.ndarray | None = None
    notes: list = field(default_factory=list)


def _to_grid(scene, ref):
    """Resample a scene's bands onto the reference scene grid when they differ."""
    any_band = next(iter(scene.bands.values()))
    ref_band = next(iter(ref.bands.values()))
    if any_band.shape == ref_band.shape and scene.transform == ref.transform:
        return scene.bands
    from rasterio.warp import Resampling, reproject

    out = {}
    for role, a in scene.bands.items():
        dst = np.full(ref_band.shape, np.nan, dtype=np.float32)
        reproject(a, dst, src_transform=scene.transform, src_crs=scene.crs, dst_transform=ref.transform,
                  dst_crs=ref.crs, src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
        out[role] = dst
    return out


def run_local_analysis(scenes, radius_m=60.0, threshold=1.5, target="Automatic", top_n=8, aoi_mask=None) -> LocalResult:
    if not scenes:
        raise ValueError("Load at least one image.")
    ref = scenes[0]
    gsd = float(ref.gsd_m)
    radius_px = max(1, int(round(radius_m / gsd)))
    notes = []
    if radius_px < 2:
        notes.append(f"The neighbourhood ({radius_m:g} m) is under two pixels at {gsd:g} m: contrast will be noisy.")

    per_date = []
    for s in scenes:
        idx = indices(_to_grid(s, ref))
        if aoi_mask is not None:
            for v in idx.values():
                v[~aoi_mask] = np.nan
        veg_name, veg = vegetation_index(idx)
        phase, veg_mean, bare = crop_phase(veg_name, veg)
        zveg = local_z(veg, radius_px)
        zb = local_z(idx["Brightness"], radius_px) if "Brightness" in idx else None
        contrast = float(np.nanpercentile(np.abs(zveg), 90)) if np.isfinite(zveg).any() else 0.0
        per_date.append({"scene": s, "idx": idx, "veg": veg, "zveg": zveg, "zb": zb, "phase": phase,
                         "veg_mean": veg_mean, "bare": bare, "contrast": contrast, "veg_name": veg_name})

    def eligible(d):
        if target.lower().startswith("crop"):
            return d["phase"] in ("vegetation", "mixed")
        if target.lower().startswith("soil"):
            return d["phase"] in ("bare soil", "mixed")
        return True

    ranked = sorted(per_date, key=lambda d: (eligible(d), d["contrast"]), reverse=True)
    chosen = [d for d in ranked if eligible(d)][: max(1, int(top_n))] or ranked[:1]
    if not any(eligible(d) for d in per_date):
        notes.append(f"No date matches the target '{target}': the best date was used anyway.")

    veg_name = chosen[0]["veg_name"]
    bmask = None
    if len(per_date) >= 3:
        # Compare the *shape* of each pixel's seasonal curve, not its level: a buried feature shifts
        # the curve (constant offset), a different crop changes its shape. Removing each pixel's
        # mean keeps persistent marks out of the boundary mask.
        stack = np.stack([d["veg"] for d in per_date])
        stack = stack - np.nanmean(stack, axis=0, keepdims=True)
        bmask = boundary_mask_from_shape(stack)
    else:
        notes.append("With fewer than three dates, field boundaries cannot be told apart from marks: load more dates if you can.")

    zs = np.stack([d["zveg"] for d in chosen])
    with np.errstate(invalid="ignore"):
        deficit = np.nanmean(np.where(zs < 0, -zs, 0), axis=0)
        excess = np.nanmean(np.where(zs > 0, zs, 0), axis=0)
        persistence = np.nanmean((np.abs(zs) >= threshold).astype(float), axis=0)
        persistence[np.all(~np.isfinite(zs), axis=0)] = np.nan
        strongest = np.nanmax(np.abs(zs), axis=0)
    linear = strongest * coherence(np.nanmean(zs, axis=0))
    layers = {
        "Vegetation deficit": deficit,
        "Vegetation excess": excess,
        "Linear marks": linear,
        "Persistence": persistence,
        f"{veg_name} (best date)": chosen[0]["veg"],
    }
    soil = [d["zb"] for d in chosen if d["zb"] is not None and d["phase"] in ("bare soil", "mixed")]
    if soil:
        with np.errstate(invalid="ignore"):
            layers["Soil marks"] = np.nanmean(np.abs(np.stack(soil)), axis=0)
    if bmask is not None:
        for k in ("Vegetation deficit", "Vegetation excess", "Linear marks", "Persistence", "Soil marks"):
            if k in layers:
                layers[k] = np.where(bmask, np.nan, layers[k])
        layers["Field boundaries"] = bmask.astype(float)

    table = []
    chosen_ids = {id(d) for d in chosen}
    for rank, d in enumerate(ranked, 1):
        s = d["scene"]
        table.append({"rank": rank, "date": s.date.isoformat() if s.date else "", "scene": s.name, "phase": d["phase"],
                      f"{d['veg_name'].lower()}_mean": round(d["veg_mean"], 3) if np.isfinite(d["veg_mean"]) else None,
                      "bare_fraction": round(d["bare"], 3) if np.isfinite(d["bare"]) else None,
                      "local_contrast": round(d["contrast"], 3), "selected": id(d) in chosen_ids})
    return LocalResult(layers, table, ref.transform, ref.crs, gsd,
                       {"radius_m": radius_m, "threshold": threshold, "target": target, "top_n": top_n,
                        "dates": len(scenes), "selected": len(chosen)}, veg_name, bmask, notes)


def sample_sites_auc(layer, transform, crs, sites, n_controls=500, seed=0):
    """AUC of a layer at known sites vs random control pixels (a sanity check, not a validation)."""
    from pyproj import Transformer

    a = np.asarray(layer, dtype=float)
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = ~transform
    positions = []
    for s in sites:
        x, y = tr.transform(s.lon, s.lat)
        c, r = inv * (x, y)
        positions.append((r, c))
    at_sites = benchmark.sample_at(a, positions)
    rng = np.random.default_rng(seed)
    valid = np.argwhere(np.isfinite(a))
    if len(at_sites) == 0 or len(valid) == 0:
        return {"sites_inside": len(at_sites), "auc": None}
    pick = valid[rng.choice(len(valid), size=min(n_controls, len(valid)), replace=False)]
    controls = a[pick[:, 0], pick[:, 1]]
    s = np.asarray(at_sites)
    greater = (s[:, None] > controls[None, :]).mean()
    ties = (s[:, None] == controls[None, :]).mean()
    return {"sites_inside": len(at_sites), "auc": float(greater + 0.5 * ties), "controls": int(len(controls))}


def write_layers(result: LocalResult, path):
    import rasterio

    names = list(result.layers)
    first = result.layers[names[0]]
    profile = dict(driver="GTiff", height=first.shape[0], width=first.shape[1], count=len(names), dtype="float32",
                   transform=result.transform, crs=result.crs, nodata=np.nan, compress="deflate")
    with rasterio.open(path, "w", **profile) as dst:
        for i, n in enumerate(names, 1):
            dst.write(np.asarray(result.layers[n], dtype=np.float32), i)
            dst.set_band_description(i, n)
    return path
