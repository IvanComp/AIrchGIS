# ArchaeoScope

Tool unico per analisi territoriale e archeologica preliminare. ArchaeoScope integra le due applicazioni del progetto in un'unica app web:

- screening multispettrale Sentinel-2 per crop marks e soil marks;
- esplorazione LiDAR/DTM con RVT, filtri, export, report e viewer 3D.

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

## Struttura

```text
ArchaeoScope/
  archaeoscope_app.py
  start_archaeoscope.command
  archaeoscope/
    app.py
    cropmarks_engine.py
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
