"""Quality of multispectral images: clouds, shadows, haze, band artefacts.

When the Sentinel-2 scene classification (SCL) is available it is used as is.
Otherwise simple, documented spectral tests are applied on reflectance
(values above 1.5 are assumed to be scaled by 10 000):

- cloud: bright and white in the visible bands (mean > 0.25, spread < 0.7 of
  the mean) and not vegetated (NDVI < 0.4), or very bright in blue (> 0.3);
- haze: haze-optimized transform HOT = blue - 0.5 * red - 0.08 > 0;
- shadow: dark in NIR (< 0.12) and in the visible (< 0.06), excluding water
  when green exceeds NIR (water is reported apart).

These tests are deliberately conservative screening rules, not a cloud model;
the masks are shown to the user and can be switched off.
"""

from __future__ import annotations

import numpy as np

from airchgis.enhance import metrics

SCL_CLASSES = {0: "no data", 1: "saturated", 2: "dark area", 3: "cloud shadow", 4: "vegetation", 5: "bare soil",
               6: "water", 7: "unclassified", 8: "cloud (medium)", 9: "cloud (high)", 10: "thin cirrus", 11: "snow"}
SCL_BAD = {0: "nodata", 1: "saturated", 3: "shadow", 8: "cloud", 9: "cloud", 10: "haze"}


def to_reflectance(a):
    a = np.asarray(a, dtype=np.float32)
    finite = a[np.isfinite(a)]
    if finite.size and np.percentile(finite, 99) > 1.5:
        return a / 10000.0
    return a


def masks_from_scl(scl):
    scl = np.asarray(scl)
    out = {}
    for code, name in SCL_BAD.items():
        out[name] = out.get(name, np.zeros(scl.shape, bool)) | (scl == code)
    return out


def masks_from_bands(bands):
    b = {k: to_reflectance(v) for k, v in bands.items() if v is not None}
    shape = next(iter(b.values())).shape
    zero = np.zeros(shape, bool)
    blue, green, red, nir = b.get("blue"), b.get("green"), b.get("red"), b.get("nir")
    vis = [x for x in (blue, green, red) if x is not None]
    out = {"cloud": zero.copy(), "haze": zero.copy(), "shadow": zero.copy(), "water": zero.copy()}
    with np.errstate(invalid="ignore", divide="ignore"):
        if vis:
            stack = np.stack(vis)
            vmean = np.nanmean(stack, axis=0)
            vspread = np.nanmax(stack, axis=0) - np.nanmin(stack, axis=0)
            ndvi = (nir - red) / (nir + red + 1e-6) if nir is not None and red is not None else np.zeros(shape)
            cloud = (vmean > 0.25) & (vspread < 0.7 * vmean) & (ndvi < 0.4)
            if blue is not None:
                cloud |= blue > 0.3
            out["cloud"] = np.nan_to_num(cloud).astype(bool)
            if blue is not None and red is not None:
                out["haze"] = np.nan_to_num(blue - 0.5 * red - 0.08 > 0).astype(bool) & ~out["cloud"]
            if nir is not None:
                dark = (nir < 0.12) & (vmean < 0.06)
                water = (green > nir) if green is not None else np.zeros(shape, bool)
                out["water"] = np.nan_to_num(dark & water).astype(bool)
                out["shadow"] = np.nan_to_num(dark & ~water).astype(bool)
    nodata = np.zeros(shape, bool)
    for v in b.values():
        nodata |= ~np.isfinite(v)
    out["nodata"] = nodata
    return out


def band_artifacts(bands, border_px=3):
    """Per band: no-data share, saturation, constant band, stripe energy and a ring of zeros or no data at the edges."""
    rows = []
    for name, a in bands.items():
        a = np.asarray(a, dtype=np.float64)
        finite = np.isfinite(a)
        vals = a[finite]
        row = {"band": name, "nodata_share": float(1 - finite.mean()) if a.size else 1.0}
        if vals.size == 0:
            row.update(constant=True, saturated_share=0.0, stripe_energy=0.0, edge_artifact_share=1.0, problems=["no valid data"])
            rows.append(row)
            continue
        vmax = vals.max()
        refl_max = float(np.nanmax(to_reflectance(vals)))
        # saturation: a plateau at the top of the range that is also at or above full reflectance
        row["saturated_share"] = float((vals >= vmax).mean()) if vals.std() > 0 and refl_max >= 1.0 else 0.0
        row["constant"] = bool(vals.std() == 0)
        from airchgis.enhance.clean import stripe_energy

        try:
            row["stripe_energy"] = stripe_energy(a)[0] if min(a.shape) >= 16 else 0.0
        except Exception:
            row["stripe_energy"] = 0.0
        edge = np.zeros(a.shape, bool)
        edge[:border_px], edge[-border_px:], edge[:, :border_px], edge[:, -border_px:] = True, True, True, True
        bad = ~finite | (a == 0)
        row["edge_artifact_share"] = float(bad[edge].mean())
        problems = []
        if row["constant"]:
            problems.append("constant band")
        if row["saturated_share"] > 0.02:
            problems.append("saturated pixels")
        if row["stripe_energy"] > 0.05:
            problems.append("striping")
        if row["edge_artifact_share"] > 0.2 and bad[~edge].mean() < 0.5 * row["edge_artifact_share"]:
            problems.append("no-data ring at the edges")
        if row["nodata_share"] > 0.3:
            problems.append("large no-data share")
        row["problems"] = problems
        rows.append(row)
    return rows


def date_quality(bands, scl=None, aoi_mask=None):
    """Quality of one date: share of clear pixels, of clouds, shadows and haze, band problems, and a 0-1 score."""
    m = masks_from_scl(scl) if scl is not None else masks_from_bands(bands)
    shape = next(iter(bands.values())).shape
    region = np.ones(shape, bool) if aoi_mask is None else np.asarray(aoi_mask, bool)
    n = max(int(region.sum()), 1)
    shares = {k: float((v & region).sum() / n) for k, v in m.items()}
    bad = np.zeros(shape, bool)
    for k in ("nodata", "saturated", "cloud", "shadow"):
        if k in m:
            bad |= m[k]
    clear = float((~bad & region).sum() / n)
    haze = shares.get("haze", 0.0)
    artefacts = band_artifacts(bands)
    problem_bands = [r["band"] for r in artefacts if r["problems"]]
    score = clear * (1.0 - 0.5 * haze) * (0.8 ** len(problem_bands))
    mask = bad | (m.get("haze", np.zeros(shape, bool)) if haze > 0.5 else np.zeros(shape, bool))
    return {
        "score": float(score),
        "clear_share": clear,
        "cloud_share": shares.get("cloud", 0.0),
        "shadow_share": shares.get("shadow", 0.0),
        "haze_share": haze,
        "source": "SCL" if scl is not None else "spectral tests",
        "band_problems": {r["band"]: r["problems"] for r in artefacts if r["problems"]},
        "mask": mask,
    }


def mask_scene(scene, scl=None):
    """Set cloudy, shadowed and no-data pixels of a :class:`~airchgis.data_input.Scene` to NaN; returns the quality."""
    q = date_quality(scene.bands, scl=scl)
    for k, v in scene.bands.items():
        v = np.asarray(v, dtype=np.float32).copy()
        v[q["mask"]] = np.nan
        scene.bands[k] = v
    return q


def quality_table(scenes):
    rows = []
    for sc in scenes:
        q = date_quality(sc.bands)
        rows.append({"image": sc.name, "date": sc.date, "quality": round(q["score"], 2),
                     "clear %": round(100 * q["clear_share"], 1), "cloud %": round(100 * q["cloud_share"], 1),
                     "shadow %": round(100 * q["shadow_share"], 1), "haze %": round(100 * q["haze_share"], 1),
                     "band problems": "; ".join(f"{b}: {', '.join(p)}" for b, p in q["band_problems"].items()) or "none"})
    return rows


__all__ = ["date_quality", "mask_scene", "quality_table", "band_artifacts", "masks_from_bands", "masks_from_scl",
           "metrics"]
