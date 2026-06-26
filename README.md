# ArchaeoScope

Tool unico per analisi territoriale e archeologica preliminare. ArchaeoScope mette nella stessa pagina le due applicazioni del progetto:

- screening multispettrale Sentinel-2 per crop marks e soil marks;
- esplorazione LiDAR/DTM con RVT, report e viewer 3D.

I due motori originali restano disponibili e non sono stati smontati: `RVT/core.py` continua a essere la GUI LiDAR completa, mentre `Crop marks Tool/s2_cropmarks_gui.py` resta avviabile come tool Streamlit standalone.

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

- `RVT LiDAR`: launcher della GUI RVT esistente, con accesso a cartella/output e verifica dipendenze.
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

## Avvio legacy RVT

```bash
cd "/Users/ivan/Desktop/ArchaeoScope/RVT"
python core.py
```

Dettagli: `RVT/README_RVT_Lidar_Explorer.md`.

## Avvio legacy Crop Marks

```bash
cd "/Users/ivan/Desktop/ArchaeoScope/Crop marks Tool"
./start_mac.command
```

Dettagli: `Crop marks Tool/README.md`.

## Note

La cartella `.venv`, gli output RVT, i dati raster locali, i DTM generati e le credenziali/progetti Earth Engine sono locali e non dovrebbero essere versionati.
