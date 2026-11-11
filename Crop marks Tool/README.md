# Sentinel-2 Crop Marks GUI

> Nota: questo tool ora e integrato nell'app unica `AIrch`.
> Avvio consigliato dalla root del repository:
>
> ```bash
> ./start_airch.command
> ```
>
> Le istruzioni sotto restano valide per l'avvio standalone.

Tool locale in Python/Streamlit per analisi automatizzata di crop marks e soil marks da immagini Sentinel-2, seguendo una pipeline compatibile con il paper su Sentinel-2 multitemporale, indici spettrali, Tasseled Cap e PCA.

Il tool non conferma siti archeologici. Serve per screening preliminare: evidenzia anomalie candidate che devono essere controllate con ortofoto storiche, Google Earth, dati locali, sopralluogo, drone o geofisica.

## Cosa fa

- Mostra una mappa interattiva.
- Permette di disegnare un rettangolo o poligono come area di studio.
- Carica immagini Sentinel-2 L2A da Google Earth Engine.
- Applica maschera nuvole e ombre usando la banda SCL.
- Calcola composizioni RGB e indici spettrali.
- Calcola Tasseled Cap brightness, greenness e wetness.
- Calcola PCA sugli strati principali.
- Ordina le date Sentinel-2 in base a uno score di contrasto spettrale.
- Mostra i layer su mappa.
- Esporta un GeoTIFF multibanda direttamente o su Google Drive.

## Layer generati

Composizioni:

- RGB naturale: B4, B3, B2
- False color infrared: B8, B4, B3
- Healthy vegetation: B8, B11, B2

Indici:

- NDVI
- GNDVI
- DVI
- GDVI
- GRVI
- Simple Ratio
- EVI
- MCARI
- SAVI
- NDMI
- NDWI
- MSI
- Crop_band
- Soil_band

Tasseled Cap:

- TCT_brightness
- TCT_greenness
- TCT_wetness

PCA:

- PC1-PC6

Anomalie candidate:

- Anomaly_score
- Local_contrast
- Possibili strutture - erba bassa
- Edges

## Requisiti

- Python 3.10 o superiore.
- Account Google Earth Engine attivo.
- Progetto Google Cloud/Earth Engine abilitato, se richiesto dal tuo account.

## Installazione

Crea un ambiente Python:

```bash
python -m venv .venv
```

Attiva l'ambiente su Linux/macOS:

```bash
source .venv/bin/activate
```

Attiva l'ambiente su Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Installa i pacchetti:

```bash
pip install -r requirements.txt
```

Autentica Earth Engine:

```bash
earthengine authenticate
```

## Esecuzione

Avvia il tool:

```bash
streamlit run s2_cropmarks_gui.py
```

Apri il link locale mostrato da Streamlit, di solito:

```text
http://localhost:8501
```

## Uso

1. Disegna un rettangolo o poligono sulla mappa.
2. Imposta intervallo temporale.
3. Imposta la copertura nuvolosa massima.
4. Scegli quante date migliori combinare.
5. Scegli se usare la migliore singola data o la mediana delle migliori date.
6. Premi `Avvia analisi`.
7. Esamina i layer generati dalla mappa risultati.
8. Scarica il GeoTIFF o usa export su Google Drive.

## Parametri consigliati

Per iniziare:

- Area piccola, ad esempio pochi km quadrati.
- Cloud cover massimo: 5-15%.
- Periodo: più anni, non una singola stagione.
- Date migliori da combinare: 3-5.
- Immagine base: prova sia migliore singola data sia mediana migliori date.

Per crop marks in aree agricole mediterranee, prova finestre che includano primavera, inizio estate, settembre, novembre e dicembre. La data giusta dipende da coltura, pioggia, umidità e stress vegetazionale.

## Note importanti

Sentinel-2 ha risoluzione limitata. Le bande principali sono a 10 m, mentre Red Edge e SWIR sono a 20 m. Il tool non vede direttamente muri o strutture piccole. Cerca anomalie grandi, ripetute o geometricamente coerenti.

La PCA può produrre risultati diversi in base all'area, al periodo e alle colture. Non interpretare automaticamente ogni bordo o anomalia come archeologica.

Se il download diretto fallisce, l'area selezionata è probabilmente troppo grande. Riduci l'AOI oppure usa export su Google Drive.

## File principali

- `s2_cropmarks_gui.py`: applicazione Streamlit.
- `requirements.txt`: dipendenze Python.
- `README.md`: istruzioni.
