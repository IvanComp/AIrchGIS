# ArchaeoScope

Tool unico per analisi territoriale e archeologica preliminare. ArchaeoScope integra gli strumenti principali del progetto in un'unica app web:

- screening multispettrale Sentinel-2 per crop marks e soil marks;
- esplorazione LiDAR/DTM con RVT, filtri, export, report e viewer 3D;
- database dei siti archeologici noti CAM-M/PVS con mappa, filtri, schede di dettaglio e provenienza documentaria verificabile;
- dossier di candidati che collegano fonte documentale, AOI, ranking temporale e stato di verifica.

## Avvio consigliato

```bash
cd "/Users/ivan/Desktop/ArchaeoScope"
./start_archaeoscope.command
```

In alternativa:

```bash
cd "/Users/ivan/Desktop/ArchaeoScope"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run archaeoscope_app.py
```

## Cosa trovi nell'app unica

- `RVT`: schermata web per Database, upload raster, DTM da mappa, metodi RVT, preset, basemap, export TIFF/PNG, griglia metodi, 3D Cloud, report PDF/KML.
- `Sentinel-2 Crop Marks`: AOI su mappa, ranking date, indici, Tasseled Cap, PCA, anomaly score, download GeoTIFF ed export Drive.
- `Database`: catalogo CAM-M/PVS deduplicato, con ricerca per metadati, filtri cronologici, fonti primarie collegate, coda dei join incerti, tavole comunali ufficiali e mappa interattiva con coordinate UTM/WGS84 quando disponibili. I riferimenti bibliografici espliciti uniscono le schede PVS alle corrispondenti CAM-M; i casi composti non vengono georiferiti automaticamente.
- `Candidati`: archivio locale dei dossier di verifica, mappa delle AOI, aggiornamento dello stato ed export JSON/GeoJSON.

Le schede georeferenziate del Database possono aprire direttamente un'area di analisi in Crop Marks. Il motore usa maschere nuvolose per pixel, ranking normalizzato, serie temporali e persistenza di anomalie positive/negative. I punteggi sono priorità di indagine, non probabilità archeologiche.

## Fonti documentarie locali

Le copie locali autorizzate dei documenti e, facoltativamente, le 53 tavole/varianti comunali CAM-M possono essere sincronizzate nella cache ignorata da Git:

```bash
python scripts/sync_archaeological_sources.py --maps
```

Il manifest `archaeoscope/data/source_manifest.json` conserva URL istituzionali, licenze, copertura, dimensioni e checksum. L'app non trasforma abbinamenti ambigui in coordinate: li espone nella coda di revisione.

MASE e Google Earth sono disponibili come risorse esterne nella barra superiore, non come sezioni operative dell'app.

## Struttura

```text
ArchaeoScope/
  archaeoscope_app.py
  start_archaeoscope.command
  archaeoscope/
    app.py
    archaeological_database.py
    database_enrichment.py
    source_registry.py
    cropmarks_engine.py
    data/cam_m_sites.json
    data/potenza_valley_sites.json
    data/pvs_2017_enrichment.json
    data/source_manifest.json
    paths.py
    assets/logo.svg
  RVT/
    core.py
    scripts/lads_preview.py
    README_RVT_Lidar_Explorer.md
  Crop marks Tool/
    s2_cropmarks_gui.py
    requirements.txt
    start_mac.command
    README.md
```

## Crop Marks standalone

```bash
cd "/Users/ivan/Desktop/ArchaeoScope/Crop marks Tool"
./start_mac.command
```

Dettagli: `Crop marks Tool/README.md`.

## Note

La cartella `.venv`, gli output RVT, i dati raster locali, i DTM generati e le credenziali/progetti Earth Engine sono locali e non dovrebbero essere versionati.
