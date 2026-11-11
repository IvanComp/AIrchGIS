# AIrch

AIrch (AI + archaeology) is a single web app for preliminary landscape and archaeological prospection. It is built for archaeologists with little IT background and brings the project's tools together in one interface:

- **RVT (LiDAR)**: DTM/DSM exploration with RVT relief visualisations, filters, exports, method grid, reports and the interactive **3D Cloud** viewer;
- **Crop Marks**: multispectral screening for crop marks and soil marks on Sentinel-2 (from 2016) and Landsat (from 1984);
- **Candidates**: a local archive of verification dossiers that link each anomaly to its area, its date ranking and its verification status.

The catalogue of known sites (CAM-M / Potenza Valley Survey) is no longer a separate screen. It stays in `airch/data/` as the ground truth used to draw known sites on the Crop Marks map and to run the built-in check against known sites. Scores are investigation priorities, not archaeological probabilities.

## Quick start

```bash
cd "/Users/ivan/Desktop/Neural-Detecting"
./start_airch.command
```

Or manually:

```bash
python -m venv .venv_airch
source .venv_airch/bin/activate
pip install -r requirements.txt
streamlit run airch_app.py
```

## How the Crop Marks engine picks dates

The ranking does not reward the images with the most variance: field boundaries and different crops produce that, not buried structures. Each acquisition is scored on three independent axes.

1. **Local contrast.** For every index the engine measures the deviation from the neighbourhood mean (60 m), the scale of a wall or a ditch rather than of the landscape.
2. **Crop phase.** Mean NDVI and bare-soil fraction classify the scene as *vegetation*, *bare soil* or *mixed*. Crop marks need a growing crop, soil marks a ploughed field: the «Target mark» option decides which dates enter the composite.
3. **Antecedent dryness.** Rainfall in the 30 days before each scene is compared with the 1991-2020 ERA5-Land mean. A mark that does not show after a wet month can show after a dry one, and the ranking takes this into account.

Statistics are computed only on arable land and open areas (ESA WorldCover): a roof edge produces more contrast than any buried structure, and without the mask the score follows the built-up area.

Besides the vegetation deficit and excess maps, the engine produces:

- **Linear marks**, the anomaly weighted by the directional coherence of the local gradient: natural soil variability is isotropic, a wall or a ditch is not;
- **Soil marks**, the brightness and colour contrast of bare soil;
- **Persistence**, how many of the selected dates show the anomaly, and **Multi-year recurrence**, in how many different years it reappears, which is the strongest clue;
- **Check against known sites**: samples the layer at the catalogued sites inside the AOI and at random control points, and reports the AUC. It is a sanity check on a small, non-random sample, not a statistical validation.

## Georeferencing toponyms

The CAM-M PDF publishes no coordinates: it describes places in words. Only 148 of 1,708 records come with a point from the linked sources.

The local gazetteer closes the gap:

```bash
python scripts/build_gazetteer.py
```

The script downloads the GeoNames dump for Italy, keeps the toponyms of the study area and writes `airch/data/gazetteer.json` (GeoNames, CC BY 4.0). `airch/geocoding.py` then matches the locality of each record against the gazetteer, disambiguates homonyms by distance from the municipality centre and discards matches beyond 9 km. About 390 records get a position within a few hundred metres; about 1,100 stay at municipality level.

An inferred coordinate is never presented as published: it carries its own precision label, uncertainty radius and the name it was matched on. The check against known sites uses published coordinates only, because testing the detector on inferred positions would measure the gazetteer.

## Local documentary sources

Authorised local copies of the documents and, optionally, the 53 CAM-M municipal maps can be synchronised into the git-ignored cache:

```bash
python scripts/sync_archaeological_sources.py --maps
```

The manifest `airch/data/source_manifest.json` stores institutional URLs, licences, coverage, sizes and checksums.

MASE and Google Earth are available as external resources in the top bar.

## Structure

```text
Neural-Detecting/   (AIrch)
  airch_app.py
  start_airch.command
  airch/
    app.py                    shell and navigation
    ui.py                     theme, animations and logo
    rvt_web.py                RVT (LiDAR) screen, including 3D Cloud
    cropmarks_engine.py       collections, masks and anomaly maps
    scene_ranking.py          date ranking, no Earth Engine dependency
    candidate_store.py        verification dossiers
    benchmark.py              metrics against known sites
    site_index.py             known-site catalogue as points
    geocoding.py              toponyms -> coordinates, with explicit uncertainty
    database_enrichment.py    CAM-M / PVS joins
    source_registry.py
    paths.py
    data/                     catalogues, gazetteer, calibration regions
    assets/logo.svg
  RVT/
    core.py                   RVT engine (and the legacy Tk desktop GUI)
    scripts/lads_preview.py   3D Cloud viewer
  Crop marks Tool/            standalone Crop Marks launcher
  paper/                      manuscript (0-MAIN.tex + sections/)
  docs/
  scripts/
  tests/
```

## Standalone Crop Marks

```bash
cd "/Users/ivan/Desktop/Neural-Detecting/Crop marks Tool"
./start_mac.command
```

Details: `Crop marks Tool/README.md`.

## Tests

```bash
python -m unittest tests.test_scene_ranking tests.test_geocoding tests.test_cropmarks_helpers tests.test_candidate_store tests.test_database_enrichment tests.test_benchmark
```

Ranking and georeferencing logic live in pure modules so they can be tested without network access: the tests cover phenological classification, dryness index, date ordering, AUC, homonym disambiguation and georeferencing counts.

## Notes

The `.venv*` folders, RVT outputs, local raster data, generated DTMs and Earth Engine credentials/projects are local and should not be versioned.
