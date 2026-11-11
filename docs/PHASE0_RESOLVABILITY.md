# Phase 0 — Can the street grid of Potentia be recovered from Sentinel-2?

**Outcome: no.** Not because of a flaw in the algorithm, but because of two independent limits, each sufficient on its own. The Sentinel-2 branch must be repositioned on what it can do.

Reproduced from `docs/fase0_potentia.png` and `docs/contact_ndvi.png`.

---

## 1. Georeferencing Fig. 71

The figure ticks were measured on the 400 dpi render and interpolated with an affine transform.

| | |
|---|---|
| CRS | EPSG:3004 (Monte Mario / Italy zone 2) |
| GCPs | 4 eastings (2411900→2412800), 5 northings (4807000→4808200), 300 m step |
| Scale | 0.52174 m/px in X, 0.52092 m/px in Y — square pixels within 0.16% |
| Max GCP residual | **0.31 m** |
| Frame extent | 1099.8 × 1637.8 m |

Parameters saved in `airch/data/potentia_reference.json`.

### Correction to the plan: the figure is not high resolution

The image embedded in the PDF is **396 × 584 px at 72 ppi**, i.e. **2.78 m GSD**. The 400 dpi render is a ×5.3 upsampling of that raster. The 0.31 m GCP residual measures the quality of the affine, not the accuracy of the content: vectorising Fig. 71 will carry a positional uncertainty of the order of **±3–6 m**, not metric.

It is still adequate to validate detections on 10 m pixels, but Phase 1 must be sized on this precision and the overlap tolerance must be stated.

## 2. Measured geometry of the urban area

| | |
|---|---|
| Long side | 532 m |
| Short side | 335 m |
| Walled area | 17.8 ha |
| Long-axis azimuth | 163.1° |
| Insula pitch | ~48 m |
| Street width | ~5 m |

Consistent with the published extent of Potentia (~18 ha). The plan's estimate (400–450 m width) was right in order of magnitude on the long side.

## 3. The resolution limit, measured rather than estimated

Real high-frequency NDVI noise inside homogeneous fields, median over 9 scenes:

**σ = 0.0396**

Forward model of the grid — 5 m streets at a 48 m pitch, **strong** crop-mark contrast (ΔNDVI 0.15 on the street), convolved with a realistic Sentinel-2 PSF (Gaussian σ ≈ 4.5 m) and sampled at 10 m:

| structure | modulation at 10 m | single-date SNR |
|---|---|---|
| urban grid, 5 m streets @ 48 m | 0.063 NDVI | **1.6** |
| ditch / extra-urban road, 20 m | 0.150 NDVI | 3.8 |
| enclosure or 40 m band | 0.150 NDVI | 3.8 |

Bringing the grid to SNR 3 on a single date would need **ΔNDVI 0.28** on the street: an exceptional crop mark is between 0.15 and 0.20, so the threshold cannot be reached.

Panel C of `fase0_potentia.png` shows the true grid, with true geometry and true noise, and it is indistinguishable from noise by eye.

*Honest nuance:* stacking N independent dates raises SNR with √N, so 10 good dates would bring it to ~5. It is therefore not an absolute sampling impossibility, but it requires the crop mark to be present and strong on all those dates, and point 4 explains why at Potentia it cannot be.

## 4. The limit that settles it: nothing is cultivated inside the walls

ESA WorldCover at 10 m inside the wall polygon:

| class | share |
|---|---|
| grassland | 43.3% |
| cropland | 36.5% |
| trees | 13.9% |
| built-up | 4.9% |

NDVI cycle 2024–2025:

| | p5 | p50 | p95 |
|---|---|---|---|
| inside the walls | **0.323** | 0.504 | 0.793 |
| surrounding fields | −0.174 | 0.128 | 0.486 |

NDVI inside the walls **never** falls below 0.32: the ground is never bare. Therefore:

- **soil marks: impossible**, there is no ploughed-soil condition;
- **cereal crop marks: impossible on about 62% of the interior**, which is permanent grassland, wooded or built.

The *vegetation marks* of Fig. 69 are parch marks on grass, captured by low-altitude oblique aerial photography (the volume documents the use of Helikite Aerial Photography): a different observation mode, at centimetre resolution.

## 5. What the tool did on this AOI

Ranking on the full 2016–2026 archive, 371 scenes, 347 valid:

- **13 of the top 14 dates come from 2025 alone**, on an 11-year archive;
- `dryness` = 0.00 on all top 14 dates — the water term had no effect;
- `phase` = «vegetation» on all of them, on an area that is 43% permanent grassland.

These are defects 2, 3, 4 and 5 of the plan, observed in operation: the score follows the heterogeneity of the year, AOI-averaged phenology has no physical meaning, and batch-relative normalisation makes values incomparable.

## 6. Correction to the plan: the Potentia DTM is already there

The plan listed the LiDAR tile as to be downloaded. In fact `RVT/generated_dtm/DTM/regional_selection_20260627_173505_DTM.tif` covers 13.6632–13.6733 E, 43.4116–43.4204 N, about 90% of the walled area.

It is however at **5 m**, not 1–2 m like the Ministry of the Environment product used in Fig. 72, and it shows **systematic banding** clearly visible in the hillshade and local relief, which would generate spurious linear anomalies. Validating the LiDAR branch needs the high-resolution tile.

## 7. Operational consequences

1. The Sentinel-2 branch must be declared, in the README and in the interface, for what it can do: extra-urban roads, centuriation, large enclosures, palaeochannels — structures **20 m and wider** — and above all screening of years.
2. Detailed detection must move to high-resolution orthophotos and LiDAR.
3. Potentia **cannot** be used as a calibration case for the Sentinel-2 branch. A target compatible with 10 m is needed: a stretch of centuriation or a large enclosure, on cropland.
4. Phases A–D of the plan remain valid, but the reference metric must be redefined on a resolvable target, otherwise we would optimise towards an absent signal.
