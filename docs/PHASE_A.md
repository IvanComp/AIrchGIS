# Phase A — median out of detection, kernel inside the parcel, masking

Defects 1, 6 and 7 of the plan, plus an eighth that emerged during measurement.

All figures come from `scripts/benchmark_cropmarks.py`, which runs on the same region with the same parameters and writes to `docs/benchmarks/`.

## Calibration region

Potentia cannot be used for the Sentinel-2 branch (see `PHASE0_RESOLVABILITY.md`). The target was chosen by measurement, not by fame: among the 148 sites with published coordinates, those with at least 70% arable land, less than 5% built-up area, less than 10% trees within 400 m, and winter NDVI below 0.15, that is fields that are really ploughed.

Twenty remain. The densest group is **Pollenza / Treia, C.da San Marco Vecchio**: 8 Roman villas and farms within 3 km, 29 published sites in total, 3.8 × 4.7 km. Definition in `airchgis/data/calibration_region.json`.

These targets are compatible with 10 m pixels: platforms and courtyards tens of metres across.

## Metrics

- **AUC**: does the layer give known sites higher values than random points? 0.5 = chance.
- **precision@20**: how many of the 20 strongest candidates fall within 100 m of a known site, against the share of the area within 100 m of a site (0.045 here).
- **edge contamination**: how many of the 20 candidates sit on a parcel boundary, derived independently from the seasonal NDVI dissimilarity.

Candidates = local maxima at least 100 m apart, inside the analysis mask.

## Two comparisons, both internal

Measurements at 10 m and at 20 m are not comparable, so there are two separate comparisons, each with its two arms on the same grid:

- **median diagnostics**, at 10 m: `baseline_*.json` vs `mediana_*.json`;
- **legacy vs Phase A**, at 20 m, the scale at which the analysis actually runs: `legacy_*.json` vs `fase-a_*.json`. The legacy arm is not a remembered old run: `--legacy` rebuilds the pre-Phase A path **on the same scenes, on the same grid, with the same metrics**, so the only difference is the construction.

The chance baseline is computed on the area **actually analysed**: Phase A excludes the band near boundaries, so it searches a smaller area, and comparing it with a baseline computed over the whole region would be wrong in both directions.

## Baseline and median diagnostics (10 m)

| layer | AUC | precision@20 | on edges |
|---|---|---|---|
| Persistent_any | 0.54 | 0.050 | **0.70** |
| Vegetation_deficit | 0.41 | 0.000 | 0.45 |
| Linear_marks | 0.36 | 0.000 | 0.15 |

Parcel boundaries covered **7.5%** of the analysable area and collected **70%** of the candidates: a **9.3× enrichment**. Defect 6 confirmed as dominant.

The AUCs below 0.5 of deficit and linear marks are not noise: known sites sat *systematically lower* than the background. Those layers were measuring agrarian geometry, and Roman villas lie in the middle of fields, where that contrast is lowest.

`Persistent_any` is identical in both modes, because persistence was already computed date by date. The median only affected the layers derived from `base`:

| layer | mode | AUC | on edges |
|---|---|---|---|
| Vegetation_deficit | best date | 0.41 | 0.45 |
| Vegetation_deficit | median | 0.41 | **0.60** |
| Linear_marks | best date | 0.36 | 0.15 |
| Linear_marks | median | 0.36 | **0.25** |

The median improves nothing and increases edge contamination by 33% and 67%: compositing erases the transient signal and keeps the permanent geometry of the fields. Defect 1 confirmed in the expected direction.

## What changed

**Defect 1.** Anomalies are no longer computed on a composite. `date_marks` measures deficit, excess and soil marks on **each selected date**, and `detection_layers` aggregates afterwards: mean for the intensity maps, threshold and mean for persistence, count of distinct years for recurrence. The median mode remains, renamed «Median of best dates (context only)», and feeds only the layers meant for viewing.

**Defect 6.** Parcel boundaries come from the **seasonal dissimilarity**: one NDVI median per month, then the distance between the annual profile of a pixel and those of its four neighbours, thresholded at the 92nd percentile of the area. The local z-score is then computed only where a 60 m neighbourhood lies **entirely inside a field**: there the circular kernel cannot cross a margin, so it *is* the parcel statistic, without the cost of a connected-component reduction.

A first version used SNIC plus `reduceConnectedComponents`. It was dropped twice: it over-segmented (only **0.5%** of the area survived the buffer) and it was too expensive for Earth Engine over 18 km² and 12 dates.

**Defect 7.** SCL 2 (topographic shadow) and 6 (water) are now masked. Coverage is a **hard filter** at 90%, not a discount: a scene that sees a sliver of the area describes another place and is excluded, however contrasted it is.

**Defect 8, not in the plan.** `pca()` called `toArray()` on an image with partially masked pixels: arrays of different length, NaN centred covariance, `eigen()` failing. Since the PCA bands were inside the exported image, **the whole GeoTIFF export failed with an opaque 400** on every large AOI: «Prepare GeoTIFF download» and the Drive export were broken. PCA now masks to pixels with all bands valid, is computed lazily and is outside the exported image. Export works.

## Result — legacy vs Phase A, at 20 m, on the same scenes

| layer | metric | legacy | Phase A |
|---|---|---|---|
| Persistent_any | AUC | 0.51 | **0.58** |
| | precision@20 | 0.100 (chance 0.043) | 0.000 (chance 0.025) |
| | on edges | 0.50 | **0.05** |
| Vegetation_deficit | AUC | 0.45 | 0.34 |
| | precision@20 | 0.100 (chance 0.041) | 0.000 (chance 0.025) |
| | on edges | 0.35 | **0.15** |
| Linear_marks | AUC | 0.51 | 0.51 |
| | precision@20 | 0.050 (chance 0.042) | 0.050 (chance 0.025) |
| | on edges | 0.00 | 0.00 |

Searchable area: **95.8% → 40.6%** of the region. Reachable sites: **29 → 12**. The excluded band holds 59% of the area and 59% of the sites, the same share: known sites do **not** sit preferentially on field boundaries; they are removed at the base rate.

### What was fixed

Edge contamination drops tenfold on persistence (0.50 → 0.05) and more than halves on deficit (0.35 → 0.15). The 9.3× enrichment on boundaries is gone. This was the defect the plan flagged as dominant, and it was.

The GeoTIFF export, which always failed on large AOIs, works.

### What was not fixed, and one regression

AUC stays between 0.34 and 0.58: **the detector does not find known sites better than chance.** Phase A removed false positives; it did not add true positives.

On two layers precision@20 **gets worse**, from 0.100 to 0.000: two centred candidates on 29 targets become zero on 12. With chance at 0.043 and 0.025, one expects 0.86 and 0.50 random hits out of 20 candidates: both «two» and «zero» are within Poisson noise, and the difference is not significant. But the direction is unfavourable and must be stated.

`Vegetation_deficit` also gets worse in AUC, from 0.45 to 0.34: restricting the computation to parcel interiors makes it *more* anti-correlated with known sites. This is consistent with the baseline reading (the layer measures agronomic variability inside the field) and suggests that the mean deficit, as it stands, is not a useful indicator.

### Statistical power

With 12–29 targets, 18 km² and a 100 m tolerance, differences of one or two candidates out of twenty cannot be told apart from chance. **At this target density precision@20 does not discriminate.** AUC is the most reliable number and must be read together with edge contamination. Before Phases B and C the calibration region should be widened or k raised, otherwise we risk tuning on noise.
