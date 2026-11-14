# AI layer for AIrchGIS: understanding, plan and feasibility

Status: approved and implemented on 14 November 2026 (method A, "Unusual relief (AI)").
Date of the plan: 14 November 2026.

## Decisions taken at approval (defaults; change them here if needed)

1. Method A, name "Unusual relief (AI)": yes.
2. Sensitivity = largest share of the area to check: low 0.5%, medium 1% (default), high 2%. A pixel also needs a score
   of at least 5.5, and an area a mean score of at least 8.0 / 7.5 / 7.0, so that natural terrain gives no priority area.
3. NumPy/SciPy only; no scikit-learn. Isolation Forest stays as optional future work.
4. 3D: "AI relief" mode after Cloud 3, "Show AI priorities" toggle in the other modes, adaptive vertical exaggeration
   available but off by default, up to 5 "views worth looking at", PNG/PDF captions record them.
5. Known features: upload (CSV/GeoJSON) under Advanced with the AUC / precision at k report; paper numbers are \todo.
6. Data on disk (0.5/1/5 m set, the UK sample): internal checks only, never named in the paper.
7. best_view / fused: kept in the library, hidden, available as baselines only.

## Outcome (controlled test, synthetic terrain, mean of three random terrains, W = 5 m)

| Layer | AUC smooth relief | AUC rough relief (fractal, terraces, field boundary) |
|---|---|---|
| Best single RVT view (positive openness) | 0.80 | 0.75 |
| VAT (RVT blend) | 0.77 | 0.75 |
| e3MSTP (RVT blend) | 0.55 | 0.52 |
| Unusual relief (AI) | **0.98** | 0.72 |

- Natural terrain without features: 0 priority areas in 12 of 12 smooth and 12 of 12 rough terrains (default).
- Smooth relief with features: all priority areas on the features (precision at k 1.00), 39% of feature points hit.
- Rough relief with features: no priority area at the default; the layer does not beat positive openness or VAT.
- Internal stability check (0.5 / 1 / 5 m dataset on disk): score rank correlation 0.77 between 0.5 and 1 m (top 1%
  overlap 0.40); 0.49 between 5 and 1 m (overlap 0.13), as expected when 5 m cells cannot resolve 5 m features.
- Runtime: about 5 s for 1000 × 1000 at 1 m, about 35 s for 2000 × 2000 at 0.5 m (W = 5 m).

## Riassunto (italiano, per Ivan)

1. Propongo un livello AI **non supervisionato** chiamato "Unusual relief (AI)", in italiano "rilievo insolito".
2. Funziona così: prende 5 viste RVT (sky-view factor, openness positiva e negativa, SLRM, pendenza) e due filtri di scala del DTM, calcolati alla larghezza del bersaglio. Le standardizza localmente. Poi misura per ogni pixel quanto la combinazione è insolita rispetto al terreno naturale della stessa area (distanza di Mahalanobis robusta, un modello "one-class" stimato sull'area stessa).
3. Non inventa terreno e non dà una probabilità di sito. Dà solo **priorità da controllare**: le zone che, guardando tutte le viste insieme, si comportano diversamente dal resto.
4. Test di fattibilità (preliminare) su un terreno sintetico con fossato, tumulo e strada sotto pendenza e rumore. L'AI ottiene AUC 0.99 contro 0.80 della migliore vista RVT singola, 0.76 di VAT e 0.59 di e3MSTP. I falsi positivi, a parità di feature trovate (80%), scendono dal 44–67% allo 0.7% dell'area.
5. Su un DTM reale a 1 m l'indice di visibilità sale a 7.0 contro 5.1 (SLRM), 2.2 (VAT) e 2.4 (e3MSTP). Ma ho scoperto che quell'indice si può "ingannare": una fusione che lo ottimizza arriva a 18 e non trova le feature. Quindi nel paper l'indice di visibilità da solo non basta: servono AUC sui siti noti e il giudizio degli esperti.
6. L'AI mette in evidenza anche cose moderne (edifici, scoli, bordi dei campi, aratura) e i bordi o le giunture delle tile. Per questo è sempre mostrata accanto alla vista RVT, mai al suo posto.
7. Per il 3D propongo: un nuovo modo "AI relief" accanto a Original e Cloud 1–3 (la mappa drappeggiata sul rilievo), luce automatica scelta per ogni area prioritaria, e una lista di 3–5 "viste da guardare" catturabili in PNG/PDF.
8. Dipendenze: solo NumPy e SciPy, già installati. Niente GPU e niente download. Tempo su 2000×2000 px: circa 10 s per l'AI, più circa 18 s per le viste RVT, picco di memoria circa 1.9 GB.
9. Lavoro stimato: 2–3 sessioni (modulo, tool con provenance, interfaccia, 3D, test, help, README, paper).
10. Prima di procedere mi servono le risposte alle domande della sezione 9.

## 1. What exists today (plain summary)

- **Pre-processing** (`airchgis/preprocess.py`, `airchgis/workbench.py`). Point clouds (LAS/LAZ) are turned into a terrain model. The steps are: keep the ground points, suggest a cell size from the point density, then interpolate with one of four methods (TIN, IDW, mean, lowest point). Raster DTMs are harmonized: one coordinate system in metres, nodata handled, small voids filled (up to 400 m²) and optional resampling. Each step reports a few measures and is recorded.
- **Relief visualizations** come from RVT_py. They are reached through the map's relief tool (hillshade, slope, sky-view factor, openness, local relief model, MSRM, MSTP, sky illumination, local dominance, e3MSTP and others) and through the **RVT workspace** (`airchgis/rvt_api.py`). The workspace exposes about 148 RVT operations and RVT's blend presets, including "Archaeological (VAT)" and its combined general/flat version.
- **Map panel** (`airchgis/map/component/workbench.js`). It is a MapLibre map with layers, opacity and comparison. It contains the Pre-processing card, the relief tool, contrast, GeoTIFF download, the resolution check and the script download. The code also has `best_view` and `fused` actions (`airchgis/enhance/bestview.py`, `fuse.py`), but these are not exposed in the current map panel.
- **Tool registry and provenance** (`airchgis/gis/tools.py`, `provenance.py`). Every tool runs through `run_tool`. Its parameters, inputs and versions go to a log, and the log becomes a Python script that repeats the session.
- **Measures** (`airchgis/enhance/metrics.py`). These are the visibility index (band-pass signal over noise and background at a target width), contrast-to-noise, and AUC against known sites.
- **3D Analysis window** (`RVT/scripts/lads_preview.py` with `airchgis/terrain/viewer_capture.js`). It is a WebGL view of the prepared DTM in the DTM's own metric coordinate system, or in its UTM zone. The current view can be saved as PNG/PDF with a caption (`view_export.py`). Open 3D data can be exported as LAZ, PLY and glTF (`export3d.py`).
- **Tests:** 171 pass.

### The three new visualization types (3D Analysis modes)

The three new modes sit next to **Original**, which is the plain shaded mesh of the prepared terrain.

- **Cloud 1, points.** Only the grid points are drawn, with no surface and no cleaning. It shows the real grain of the data: cell spacing, holes left by removed buildings and vegetation, stripes or tile seams. Use it to judge whether the data can support an interpretation at all.
- **Cloud 2, surface with wireframe and points.** Large flat fill values are masked first. The surface is then drawn with flat facets and a thin wireframe, plus sparse points. It shows breaks of slope, terraces, banks, and the long facets of interpolated areas (for example TIN across a void).
- **Cloud 3, enhanced local relief.** The same cleaning as Cloud 2 is applied first. The local relief is then amplified: z' = T + 4 (z − T), where T is a smooth trend from a Gaussian filter at an 18 m scale (converted to cells from the real 3D grid cell size). Hollows, mounds, banks and ditches narrower than about 18 m stand out. The displayed heights are no longer true.

### Where AI can add information that RVT alone does not give

Each RVT view answers one question: lit from one side, how much sky is visible, convex or concave, above or below the local trend. An archaeologist flips between views and combines them by eye. RVT's blends (VAT, e3MSTP) combine views with **fixed** weights that were chosen for typical terrain.

Two things are missing:

1. **The combination is not adapted to the area.** In a valley with ridge and furrow, the "normal" combination of slope, openness and relief is different from that on a hill slope.
2. **Nothing says where to look first.** On a 4 km² tile, a feature that shows weakly in three views is easy to miss, even if it is clear when the views are read together.

An unsupervised model can learn what the natural terrain of *this* area looks like across all views at the target scale. It can then point to places that do not fit. It does not need labelled sites, so it works anywhere. It only re-analyses the measured terrain.

## 2. Candidate methods

All candidates use the same input. This is a stack of per-pixel features computed at the target feature width W (default 5 m):
- RVT sky-view factor, positive openness and negative openness, with radius about 2W;
- RVT simple local relief model;
- slope;
- two difference-of-Gaussians of the DTM at W and 2W.

Each feature is robustly normalized.

### A. Unsupervised "unusual relief" (recommended)

- **Input.** The feature stack above.
- **Output.** A per-pixel score: how far the pixel's combination of features is from the area's natural terrain. A ranked list of "priorities to check" (connected areas) comes with it.
- **How it works.**
  1. Each feature is standardized locally, relative to its neighbourhood (window about 8W). This removes slow changes of the natural landscape.
  2. A one-class Gaussian model (mean and covariance) is fitted on a random sample of the area. It uses a fixed seed and iterative trimming of the most unusual 10%, so that features do not bias the model of "normal".
  3. The score is the Mahalanobis distance d(x) = √((x − μ)ᵀ Σ⁻¹ (x − μ)), lightly smoothed at the target scale.
  4. Borders (about 2 radii wide) are masked, because RVT views are unreliable there.
- **Why it can show more than RVT alone.** It reads all views at once and it adapts to the local terrain. A ditch that is only weak in openness, weak in SLRM and weak in slope becomes strong when the three agree, because they agree in an unusual way.
- **Dependencies.** NumPy and SciPy only (already installed).
- **Runtime on 2000×2000.** About 9.5 s for the AI step, on top of about 18 s for the RVT views it needs. Peak memory about 1.9 GB for the whole test script, including all baselines.
- **Risks.**
  - It flags *every* unusual relief, including modern features: buildings, drains, field boundaries, ploughing patterns, quarry edges.
  - It flags data artefacts: tile seams, interpolation facets, borders.
  - The score depends on the target width. A very heterogeneous area can make "normal" too broad.
- **How it is explained to the user.** "Bright areas are places where the relief, read through several RVT views at once, does not look like the rest of this area. It is a list of places to check, not a probability of a site. Modern features and data artefacts can be bright too."

### B. Data-driven fusion of RVT layers

The variants are: PCA, a maximum-noise-fraction style eigenvector that maximizes target-scale variance over fine noise, and the existing optimized blend in `fuse.py`.

- **Output.** One greyscale composite, compared with VAT.
- **Why it might help.** It keeps more of the variance of several views in one image.
- **Dependencies.** NumPy/SciPy.
- **Runtime.** PCA and MNF take about 1 s. The existing optimizer takes about 107 s on 2000×2000 (Nelder–Mead over many full visibility evaluations).
- **Risks, found in the feasibility test.** These methods optimize a contrast measure. The MNF fusion collapsed onto a single smoothed band-pass. It raised the visibility index to 9.6–18 while the agreement with real features dropped to chance (AUC 0.52). The existing optimizer simply returned SLRM. PCA was slightly better than the best single view only in one metric. **Not recommended as the AI contribution.** PCA can stay as a baseline.

### C. Self-supervised clustering into terrain classes

The classes would be natural slope, linear features, mounds, pits and modern disturbance, each with a confidence value.

- **Method.** k-means or a Gaussian mixture on the same stack. It can be done in NumPy, or with scikit-learn.
- **Why it might help.** It would give a legend-like map.
- **Risks.** The clusters are not archaeological classes. Naming them ("mound", "pit") needs rules or labels that we do not have, and the confidence values would look more certain than they are. It is hard to evaluate without labelled data.
- **Not recommended now.** It could later describe each priority area, for example "linear, concave, about 4 m wide", from simple shape measures rather than clusters.

### Comparison

| | A. Unusual relief | B. Fusion | C. Clustering |
|---|---|---|---|
| Adapts to the area | yes | partly | yes |
| Needs labels | no | no | no (but naming needs them) |
| Feasibility result (synthetic AUC) | **0.99** | 0.52–0.74 | not tested |
| Can be gamed by the visibility index | partly (see section 4) | **yes** | n/a |
| Explainable | yes, one sentence | yes | weak |
| Extra dependencies | none | none | none (or scikit-learn) |

Optional addition to A, only if you agree to install scikit-learn: an Isolation Forest variant as an ablation. It is a non-linear one-class model. The wheel is about 11 MB and the installed size about 40–45 MB, including joblib and threadpoolctl. It is not needed for the recommendation.

## 3. Feasibility test (preliminary, throwaway code, not committed)

I wrote the code in the scratch folder. It is not in the package.

**Setup.**
- Target width 5 m for both datasets.
- Single views: hillshade, slope, SVF, positive openness, negative openness, SLRM.
- RVT blends: VAT (the "Archaeological (VAT)" preset with general terrain settings, as greyscale) and e3MSTP (as greyscale luminance).
- A 30-pixel border is excluded from all scores.
- Measures:
  - **visibility index** and **CNR**, from `metrics.visibility`;
  - with ground truth: **AUC** (feature pixels against pixels more than 6 m away), **p@2%** (the share of the top 2% of pixels that lie on a feature) and **FPR@80** (the share of non-feature area flagged when 80% of feature pixels are found; lower is better).

### Synthetic DTM

The terrain is 500×500 at 1 m. It has a regional slope, natural hills at 20–120 m scales and fine noise. Three features are buried in it:
- a curved ditch, 4 m wide and 0.35 m deep;
- a mound, 9 m in radius and 0.5 m high;
- a straight road, 6 m wide and raised 0.15 m.

| Layer | Visibility | CNR | AUC | p@2% | FPR@80 |
|---|---|---|---|---|---|
| Hillshade | 0.58 | 0.46 | 0.690 | 0.24 | 0.62 |
| Slope | 0.72 | 0.54 | 0.663 | 0.08 | 0.61 |
| Sky-view factor | 0.74 | 0.41 | 0.703 | 0.42 | 0.63 |
| Positive openness (best single, by AUC) | 0.87 | 0.31 | 0.796 | 0.67 | 0.44 |
| Negative openness | 0.78 | 0.27 | 0.764 | 0.67 | 0.55 |
| SLRM (best single, by visibility) | 1.21 | 1.95 | 0.680 | 0.15 | 0.54 |
| **VAT (RVT blend)** | 0.81 | 0.38 | 0.764 | 0.64 | 0.52 |
| **e3MSTP (RVT blend)** | 1.09 | 1.39 | 0.585 | 0.06 | 0.67 |
| **A. Unusual relief, global** | 4.31 | 12.44 | 0.994 | 0.65 | 0.007 |
| **A. Unusual relief, locally standardized (recommended)** | 4.45 | 10.90 | **0.988** | **0.81** | **0.007** |
| B1. MNF fusion | 9.57 | 164.5 | 0.524 | 0.03 | 0.75 |
| B2. PCA (first component) | 0.77 | 0.68 | 0.743 | 0.26 | 0.46 |
| B3. Existing optimized fuse | 1.21 | 1.95 | 0.684 | 0.15 | 0.51 |

**False patterns on natural terrain only** (the same terrain without features, locally standardized version):

| Threshold | Natural area flagged | Feature pixels found (terrain with features) |
|---|---|---|
| 4 | 1.7% | 79% |
| 5 | 0.07% | 55% |
| 6 | 0.00% | 41% |

### Real 1 m DTM

A 1000×1000 m crop of a lowland agricultural area (internal check only; the dataset is not named in the paper). There is no ground truth, so only label-free measures are available.

| Layer | Visibility | CNR |
|---|---|---|
| Hillshade | 2.60 | 2.78 |
| Slope | 2.49 | 2.74 |
| Sky-view factor | 2.32 | 2.37 |
| SLRM (best single) | 5.13 | 11.6 |
| **VAT** | 2.21 | 1.93 |
| **e3MSTP** | 2.37 | 3.25 |
| A. Unusual relief, global | 7.96 | 36.1 |
| A. Unusual relief, locally standardized | 7.02 | 22.1 |
| B1. MNF fusion | 18.05 | 248 |
| B3. Existing optimized fuse | 5.13 (= SLRM) | 11.6 |

**Visual check of the real map.** Field boundaries, ridge and furrow, a small ring-shaped feature and modern structures (a rectangular building or pond complex) are all bright. A straight tile seam is also visible. The map is clearly richer than VAT on this flat terrain, where VAT looks almost white with the default stretch. It does not separate archaeological features from modern ones.

**Runtime on 2000×2000 at 1 m.** About 18 s for the RVT views, 9.5 s for the AI layer and 107 s for the existing optimized fuse. Peak memory 1.9 GB.

### What the numbers mean, honestly

- On the synthetic test, the AI layer finds the buried features much better than any single RVT view, VAT or e3MSTP. It flags far less unrelated area, and with a high threshold it does not invent features on purely natural terrain.
- The synthetic natural terrain is made of smooth random hills. That suits the Gaussian model, so the real-world advantage will be smaller. **It must be measured on real known features before any claim.**
- The **visibility index can be gamed**. A layer optimized for band-pass contrast (MNF) scores 18 and finds nothing, and smoothing alone raises the index. The AI layer is also smoothed. For the AI comparison, the paper should therefore rely on **AUC and precision at k against known features, stability, and expert judgment**. The visibility index stays a secondary, label-free measure, used with that caveat.
- The AI highlights modern features and data artefacts. This is expected for an anomaly detector, and it must be said in the app and in the paper.

## 4. Recommended method in detail (A)

Inputs: the prepared DTM, the target feature width W (default from the resolution check, or typed by the user) and a sensitivity setting.

1. Compute the RVT views at radius r = clip(round(2W/res), 3, 40) px: SVF, positive openness, negative openness (openness of −DTM), SLRM with radius max(10, 2r), and slope.
2. Compute two difference-of-Gaussians of the DTM at s and 2s, with s = max(0.7, W/(2·res)) px.
3. Normalize each layer robustly: (v − median)/(1.4826·MAD), clipped to ±4.
4. Standardize locally with a Gaussian window of 8s: x' = (x − G(x))/√G((x − G(x))²).
5. Fit the model on up to 200,000 randomly sampled inner pixels (seed 0). The mean and covariance are estimated over 5 trimming passes that keep the 90% most typical pixels.
6. Score d(x), smoothed with a Gaussian of 0.5s. Mask the border of 2r px.
7. **Priorities to check.** The sensitivity setting is the **share of the area to review**: Low 0.5%, Medium 1% or High 2%. Taking the top share is honest and easy to explain. Connected areas of at least (W/res)² px are ranked by their mean score, and each gets one plain sentence with its size, orientation and whether it is raised or sunken (from SLRM).
8. **Explanation per priority.** Show which features made it unusual, as the largest contributions to d². For example: "mostly negative openness and small-scale relief: a narrow hollow". This is computed, not invented.

Everything is deterministic for a given input and seed, and is recorded by the tool registry.

## 5. 3D plan

The AI output joins the existing modes; it never replaces them.

- **New mode "AI relief"**, after Cloud 3. It uses the Original geometry (true heights). The colour is the AI score: a dark-to-bright colormap multiplied by the existing hillshade, with the priority areas outlined. A second option drapes the AI score on Cloud 3 for small features. The caption says: "colour = unusual relief (AI), priorities to check, not site probability".
- **Drape in the other modes.** A toggle "Show AI priorities" adds the outlined priority areas to Original and Cloud 1–3.
- **Adaptive vertical exaggeration** (optional, default off; the current automatic exaggeration stays). It is chosen so that the typical height of the priority features (their SLRM amplitude) is visible against their width, clipped to 1–5. It is always printed in the caption.
- **Automatic lighting per priority.** Hillshade contrast inside each priority area is computed for 16 sun azimuths. The azimuth with the highest contrast is used when the user jumps to that area. This uses the same RVT hillshade, so it is reproducible.
- **"Views worth looking at".** A list of 3–5 camera positions, one per top priority area. Each camera looks at the area's centre from 35° elevation, from the side perpendicular to the feature's long axis, at a distance that frames the area plus 3 W. Clicking one moves the camera; the PNG/PDF capture works as today.
- **Capture and export.** The capture's view metadata and caption get the AI mode, the target width, the sensitivity, the share of the area flagged and the priority id in view. The PLY/LAZ/glTF exports stay the measured terrain only. An optional GeoTIFF of the AI score and a GeoJSON of the priority areas can be added to the research package.

## 6. Evaluation plan (for the paper)

- **Baselines.** Each single RVT view (hillshade, slope, SVF, positive and negative openness, SLRM, MSRM), RVT's **VAT** (general and combined), RVT's **e3MSTP**, and PCA of the same stack.
- **Metrics.**
  - Primary, with known features uploaded by the user: AUC and precision at k (k = the reviewed share of the area), plus the share of known features hit by at least one priority area.
  - Secondary, label-free: the visibility index and CNR, with the caveat above.
  - Null test: the area flagged on terrain known to be natural, or on the synthetic natural terrain.
- **Stability.**
  - Across resolutions: a dataset at 0.5, 1 and 5 m (internal check, not named in the paper unless you decide otherwise). Measures: rank correlation of the AI score after resampling to a common grid, and overlap of the top 1% areas.
  - Across pre-processing choices: TIN, IDW and lowest point, with and without void filling.
- **Ablation.**
  - without local standardization;
  - without the difference-of-Gaussian bands;
  - with each RVT view removed in turn;
  - without border masking;
  - without smoothing;
  - global versus local model;
  - optionally Isolation Forest instead of the Gaussian model.
- **Expert judgment** in the user study, shown side by side with the RVT view (never alone):
  - "Which view lets you see more of the features you know?"
  - "Which flagged areas would you check?"
  - "Do you trust it?" (5-point scale)
  - "Did it flag modern features?"
- **Honesty rule.** If the AI layer does not beat the best baseline on a dataset, the app says so in its result sentence (it already compares with the best single view) and the paper reports it.

## 7. Documentation plan

- **In the app.**
  - One entry in the map panel, "Find hidden features (AI)", with two visible parameters: target feature width and sensitivity (share of the area to review). Everything else goes under Advanced: which views, local window and seed.
  - The result is added as a map layer next to the RVT view, with opacity and before/after comparison, never instead of it.
  - One sentence per result: what it shows, how it was made, and how much to trust it (with the comparison against the best single view and VAT on this area).
  - A short "How the AI works" section in the help page, with one diagram: views, then stack, then model of normal terrain, then score, then priorities.
- **In the README.** One paragraph and the same diagram.
- **In the paper** (not changed in this step), the plan is:
  - title and contributions: add one item, "an unsupervised, explainable 'unusual relief' layer computed from a multi-scale RVT stack, shown in 2D and 3D as priorities to check";
  - a new methods subsection with the formulas of section 4;
  - the 3D Analysis subsection: the new AI relief mode and views worth looking at;
  - an evaluation design with the baselines, metrics, stability and ablation above;
  - figure placeholders: before/after, AI map next to VAT and e3MSTP, the 3D AI relief view;
  - `\todo` for all numbers that need real data;
  - the discussion: modern features and artefacts, and the visibility-index caveat.

## 8. Implementation outline and estimated work (after approval)

1. `airchgis/ai/unusual_relief.py`: the feature stack, the local standardization, the robust model, the score, priorities and explanations. `airchgis/ai/views3d.py`: lighting, cameras and the adaptive exaggeration. About 400 lines.
2. Tools `unusual_relief` and `ai_priorities` in `gis/tools.py`, with provenance and fixed seeds, so the downloaded script reproduces them.
3. Map panel entry, layer, before/after, result sentence and details table (`workbench.js`, `workbench.py`).
4. 3D: the AI relief mode and drape in `lads_preview.py`, the priority list and camera jumps in the viewer, and caption fields in `viewer_capture.js` and `view_export.py`.
5. Tests on synthetic terrain:
   - the ditch, mound and road are recovered better than the best single RVT view and VAT (AUC and FPR@80);
   - no priority areas beyond the requested share on natural terrain, and none at all above a high threshold;
   - deterministic output for a fixed seed;
   - tool and script replay;
   - 3D grid and caption fields.
6. Help page, README and paper.
7. Restart the app and check the whole flow in the browser.

Estimate: 2–3 working sessions. No new dependencies.

## 9. Questions for Ivan before implementation

1. Is method A, "Unusual relief (AI)", unsupervised anomaly detection on the RVT stack, approved as the AI contribution? Is the name fine?
2. Is sensitivity as "share of the area to review" (0.5 / 1 / 2%) acceptable, instead of an abstract threshold?
3. May I install scikit-learn (about 40–45 MB) for an Isolation Forest ablation, or should I stay NumPy/SciPy only?
4. 3D: is the new mode "AI relief" plus the "Show AI priorities" toggle in the other modes fine? Should adaptive exaggeration be on or off by default?
5. Do you have known features (CSV/GeoJSON of points or polygons) for at least one area, so that AUC and precision at k can be measured? Without them the paper can only report synthetic and label-free results.
6. Stability across resolutions: may I use the 0.5/1/5 m dataset still on disk as an internal check, or do you prefer to provide your own dataset for the paper?
7. Should the existing hidden `best_view` and `fused` code stay hidden, become baselines only, or be removed?
