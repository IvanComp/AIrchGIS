# RVT Lidar Explorer (GUI) — README

Questo progetto fornisce uno script Python con interfaccia grafica (`core.py`) per esplorare ed esportare trasformazioni RVT su dati LiDAR scaricati come tripletta:
- DTM
- DSM first return
- DSM last return

Lo script mostra un’anteprima aggiornata in tempo reale e permette di esportare il risultato corrente come GeoTIFF georiferito.
Include anche un generatore DTM da mappa basato sul GeoTIFF regionale locale `data/regional_dtm/HRDTM5m_Umbria_Marche_Abruzzo.tif`: selezioni un rettangolo su una mappa web zoomabile e il tool crea un DTM ritagliato per Marche, Abruzzo e Umbria, poi lo carica nella sessione rapida.

## 1) Requisiti

- macOS
- Python 3.10+ (consigliato 3.11 o 3.12)
- Cartelle con i raster (GeoTIFF/ASC) per DTM, DSMfirst, DSMlast
- Pacchetto RVT su pip: `rvt-py`

Nota: `relief-visualization-toolbox` non è un pacchetto pip. Il pacchetto corretto è `rvt-py`.

## 2) Struttura delle cartelle

Nel progetto deve esistere questa struttura:

```
project/
  core.py
  data/
    regional_dtm/
      HRDTM5m_Umbria_Marche_Abruzzo.tif
  image/
    DTM/
    DSMfirst/
    DSMlast/
```

Dentro ciascuna cartella puoi:
- mettere direttamente i `.tif/.tiff/.asc`, oppure
- scompattare gli zip e lasciare anche eventuali sottocartelle (lo script cerca ricorsivamente).

Lo script userà solo i raster; shapefile e altri file possono restare nelle cartelle.

## 3) Convenzioni dei nomi file (matching delle triplette)

Lo script costruisce una “tripletta” per tile usando il nome base comune.

Esempi supportati:
- `xxx_DTM.tif`
- `xxx_DSMFirst.tif`
- `xxx_DSMLast.tif`

Varianti accettate anche:
- `_DSM_First`, `_DSM_Last`, `_dsm-first`, `_dsm-last`

Il “nome base” è la parte prima del suffisso (es.: `xxx`).

Se i tuoi file non seguono nessuna di queste convenzioni, rinominali così:
- DTM → `BASE_DTM.tif`
- DSM first → `BASE_DSMFirst.tif`
- DSM last → `BASE_DSMLast.tif`

## 4) Creazione di un virtual environment (consigliato)

Questa è la procedura consigliata per evitare conflitti (es.: upgrade di `numpy` a 2.x).

Esegui questi comandi nel Terminale:

```bash
mkdir -p ~/venvs
python3 -m venv ~/venvs/rvt
source ~/venvs/rvt/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy<2" "scipy<1.14" rasterio matplotlib rvt-py

python -c "import rvt.vis, rasterio, numpy, matplotlib; print('OK', numpy.__version__)"
```

Uscire dall’environment:
```bash
deactivate
```

## 5) Come usare lo script (workflow)

1) Scegli un’area nel sito e scarica i 3 zip (DTM, DSM First, DSM Last).
2) Scompatta gli zip.
3) Copia i raster in:
   - `image/DTM/`
   - `image/DSMfirst/`
   - `image/DSMlast/`
4) Attiva l’environment:
   ```bash
   source ~/venvs/rvt/bin/activate
   ```
5) Vai nella cartella del progetto:
   ```bash
   cd /percorso/del/progetto
   ```
6) Avvia la GUI:
   ```bash
   python core.py
   ```

## 5.1) Generare un DTM dalla mappa regionale

Il pulsante `DTM da mappa` nella sezione `Sessione rapida` apre nel browser una mappa Leaflet zoomabile dell'estensione coperta dal raster regionale di Marche, Abruzzo e Umbria. La mappa usa un layer satellitare come base e permette di disegnare/modificare un rettangolo.

Workflow:
1) premi `DTM da mappa`;
2) usa lo strumento rettangolo sulla mappa e zooma fino all'area desiderata;
3) premi `Genera DTM e carica`;
4) il GeoTIFF viene creato in `generated_dtm/DTM/` a risoluzione nativa 5 m x 5 m e caricato come DTM nella sessione rapida.

Il raster sorgente resta invariato. La selezione usa solo i dati locali delle tre regioni forniti nel progetto.

## 6) Funzioni della GUI

Pannello sinistro:
- Selezione del tile (tripletta)
- Scelta dataset:
  - `DTM`, `DSMfirst`, `DSMlast`
  - `nDSM` (DSMfirst − DTM)
  - `First-Last` (DSMfirst − DSMLast)
- Metodo RVT (in base a cosa è disponibile in `rvt.vis`):
  - Raw
  - Hillshade
  - Slope
  - Sky-View Factor
  - Local Relief Model
  - Positive/Negative Openness
- Parametri (azimuth/altitude/z-factor/radius/directions) e stretch percentili
- Export GeoTIFF del risultato corrente
- Batch pipeline base

Pannello destro:
- Anteprima (grayscale) aggiornata quando cambi metodo/parametri/dataset.

## 7) Output

- Export manuale (pulsante “Export corrente GeoTIFF”):
  - `output_rvt_gui/<TILE_KEY>/... .tif`

- Batch pipeline base (pulsante “Batch pipeline base”):
  - `output_rvt_batch/<TILE_KEY>/`
    - `1_DTM_Hillshade.tif` (se disponibile)
    - `2_DTM_SkyViewFactor.tif` (se disponibile)
    - `3_nDSM.tif`
    - `4_FirstMinusLast.tif`

Gli output sono GeoTIFF float32, georiferiti con lo stesso profilo del raster di input.

## 8) Troubleshooting (macOS)

### Tkinter / GUI non parte
Python “framework” su macOS in genere include Tkinter. Se vedi errori tipo “_tkinter not found”, usa un Python che includa Tk (es.: python.org installer) o usa una distribuzione con Tk abilitato.

### Errori RVT su alcuni metodi
`rvt-py` espone funzioni in `rvt.vis`. Lo script mostra solo metodi disponibili. Se un metodo non compare, non è presente nella versione installata.

### Raster enormi / lentezza
Riduci la dimensione del tile (area più piccola) o lavora su downsample esterno (es.: GDAL/QGIS) per iterazioni veloci.

## 9) Esecuzione rapida (riassunto)

```bash
source ~/venvs/rvt/bin/activate
cd /percorso/del/progetto
python core.py
```
