# AIrchGIS: unified structure

## Done (branch `airchgis-unify`)

- Package `archaeoscope/` renamed to `airchgis/` with `git mv`, so file history is kept.
- `archaeoscope_app.py` → `airchgis_app.py`, `start_archaeoscope.command` → `start_airchgis.command`, venv `.venv_airchgis`.
- Every "ArchaeoScope" in code, READMEs, docs, scripts and tests now reads "AIrchGIS"; the text logo is `<span>AI</span>rchGIS`.
- Standalone tools carry the AIrchGIS brand: Tk window "AIrchGIS · LiDAR Explorer", pages "AIrchGIS · DTM from map", "AIrchGIS · 3D Cloud", "AIrchGIS · Crop Marks".
- **The 3D visualisation is unchanged**, apart from its page title.
- The whole interface, READMEs and docs are in English.
- The **Database screen has been removed**: the tool is tailored to the paper. The CAM-M/PVS catalogue stays in `airchgis/data/` only as the ground truth for known sites on the Crop Marks map and for the built-in benchmark.
- Git clean-up: `Crop marks Tool/.venv`, `*.pyc` and `tmp/` are no longer tracked; `USEFUL PAPERS/`, `tmp/` and `.venv_airchgis/` are ignored.

## Target layout

The archaeologist sees **one app with task-oriented screens**, not technology-oriented ones. The code follows the same split.

```text
Neural-Detecting/
  start_airchgis.command             double-click: single entry point (macOS)
  start_airchgis.bat                 [to do] Windows equivalent
  airchgis_app.py
  airchgis/
    app.py                        shell, navigation, state
    ui.py                         theme and logo
    paths.py                      every path in one place
    terrain/                      ← today RVT/core.py + rvt_web.py + lads_preview.py
      visualizations.py           hillshade, SVF, openness, LRM, VAT (rvt-py)
      dtm_io.py                   DTM/DSM triplets, DTM from regional map
      viewer3d.py                 3D Cloud (current code, unchanged)
      screen.py                   Streamlit screen
    spectral/                     ← today cropmarks_engine.py + scene_ranking.py
    sites/                        ← geocoding.py, database_enrichment.py, site_index.py,
                                    source_registry.py (ground truth only, no screen)
    candidates/                   ← candidate_store.py
    evaluation/                   ← benchmark.py (+ scripts/benchmark_cropmarks.py)
    assistant/                    [new] AI assistant
      prompts.py, tools.py, screen.py
    data/
  legacy/
    rvt_desktop_gui.py            ← old Tk GUI (RVT/core.py), for those who still use it
  workspace/                      user data, git-ignored
    lidar/  outputs/  regional_dtm/
  paper/                          manuscript
  docs/
  tests/
```

### Screens, named for non-specialists

| Today | Proposed | What it does |
|---|---|---|
| RVT | **Terrain (LiDAR)** | Load DTM/DSM or clip from the map, visualisations, method grid, 3D |
| Crop Marks | **Field marks (satellite)** | AOI, best dates, anomalies, persistence, check against known sites |
| Candidates | **My candidates** | Dossiers, verification status, export |
| — | **AI assistant** (side panel, always visible) | Explains, suggests parameters, guides step by step |

### The AI assistant (the piece the paper still needs)

- A side panel on every screen. It receives the screen context (AOI, active layer, parameters, benchmark metrics) and answers in plain language.
- It can propose actions, such as "try SVF with a 10 m radius" or "this AOI is 60% grassland: soil marks are not reliable here", which the user applies with one click.
- Guardrails: it never invents coordinates or sites, always cites its source, and presents scores as priorities.
- Configurable backend: the Claude API, or a local model through Ollama for users who do not want data to leave their machine.
- Anonymous logging, so the user study has data on what archaeologists ask.

**Done: the tool layer under the assistant** (`airchgis/gis/`). The assistant calls tools instead of computing results: a registry with JSON schemas for Claude API / Ollama tool calling, a QGIS Processing backend (`qgis_process`) with rvt-py/rasterio fallback, ready-made workflows (`lidar_micro_relief`, `crop_mark_screening`), a resolvability guardrail based on Phase 0, and a provenance log exported as Python and `qgis_process` replay scripts. Still to do: the chat panel itself and the model loop that hands `tool_specs()` to the LLM.

**Done: 3D export for research** (`airchgis/terrain/export3d.py`, panel "Export 3D for research" in 3D Cloud): LAZ/LAS, PLY, glTF and a JSON sidecar, zipped for Zenodo. The existing 3D viewer is unchanged.

## Remaining step

Physically moving `RVT/` and `Crop marks Tool/` into `airchgis/terrain` and `airchgis/spectral`. This is the most delicate step, because `RVT/core.py` (4,400 lines) uses paths relative to the data in `RVT/image`, `RVT/data` and `RVT/generated_dtm`. It should be done together with moving the data into `workspace/`, and tested by hand on the app.
