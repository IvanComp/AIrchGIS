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
- `Crop Marks`: AOI su mappa, scelta dell'archivio (Sentinel-2 dal 2016, Landsat dal 1984, o entrambi), ranking delle date, indici, Tasseled Cap, PCA, mappe di anomalia, download GeoTIFF ed export Drive.
- `Database`: catalogo CAM-M/PVS deduplicato, con ricerca per metadati, filtri cronologici, fonti primarie collegate, coda dei join incerti, tavole comunali ufficiali e mappa interattiva. I riferimenti bibliografici espliciti uniscono le schede PVS alle corrispondenti CAM-M; i casi composti non vengono georiferiti automaticamente.
- `Candidati`: archivio locale dei dossier di verifica, mappa delle AOI, aggiornamento dello stato ed export JSON/GeoJSON.

Le schede georeferenziate del Database possono aprire direttamente un'area di analisi in Crop Marks, con il raggio preimpostato sull'incertezza della posizione. I punteggi sono priorità di indagine, non probabilità archeologiche.

## Come sceglie le date il motore Crop Marks

Il ranking non premia le immagini con più varianza: quella la producono i confini di campo e le colture diverse, non le strutture sepolte. Ogni acquisizione viene invece valutata su tre assi indipendenti.

1. **Contrasto locale.** Per ogni indice si misura lo scarto dalla media del vicinato (60 m), cioè la scala di un muro o di un fossato, non quella del paesaggio.
2. **Fase della coltura.** NDVI medio e frazione di suolo nudo classificano la scena come *vegetazione*, *suolo nudo* o *misto*. Le crop marks vogliono una coltura in crescita, le soil marks un campo arato: la voce «Traccia cercata» decide quali date entrano nel composito.
3. **Siccità precedente.** La pioggia dei 30 giorni prima di ogni scena viene confrontata con la media 1991-2020 di ERA5-Land. Una traccia che non compare dopo un mese piovoso compare dopo un mese secco, e il ranking lo tiene in conto.

Le statistiche sono calcolate solo su seminativi e aree aperte (ESA WorldCover): un bordo di tetto produce più contrasto di qualunque struttura sepolta, e senza maschera il punteggio segue l'urbanizzato.

Oltre alle mappe di deficit ed eccesso di vegetazione, il motore produce:

- **Marks lineari**, l'anomalia pesata per la coerenza direzionale del gradiente locale: la variabilità naturale del suolo è isotropa, un muro o un fossato no;
- **Soil marks**, il contrasto di brillantezza e colore del suolo nudo;
- **Persistenza**, quante delle date scelte mostrano l'anomalia, e **Ricorrenza pluriennale**, in quanti anni diversi ricompare - che è l'indizio più solido;
- **Controllo sui siti noti**: campiona il layer sui siti catalogati dentro l'AOI e su punti di controllo casuali, e riporta l'AUC. È un controllo di sanità su un campione piccolo e non casuale, non una validazione statistica.

## Georeferenziazione dei toponimi

Il PDF CAM-M non pubblica coordinate: descrive i luoghi a parole. Solo 148 schede su 1708 arrivano con un punto dalle fonti collegate, e le altre resterebbero fuori sia dalla mappa sia dall'analisi satellitare.

Il gazetteer locale colma il divario:

```bash
python scripts/build_gazetteer.py
```

Lo script scarica il dump GeoNames per l'Italia, tiene i toponimi dell'area di studio e scrive `archaeoscope/data/gazetteer.json` (GeoNames, CC BY 4.0). A quel punto `archaeoscope/geocoding.py` abbina la località di ogni scheda al gazetteer, disambigua gli omonimi sulla distanza dal centro del comune e scarta i risultati oltre i 9 km. Circa 390 schede ottengono una posizione entro qualche centinaio di metri, ~1100 restano posizionate sul solo comune.

Una coordinata dedotta non viene mai presentata come pubblicata: porta la propria etichetta di precisione, il proprio raggio di incertezza e il nome su cui è stata abbinata. Il filtro «Origine delle coordinate» mostra di default solo le posizioni pubblicate e quelle da toponimo; il controllo sui siti noti usa esclusivamente le coordinate pubblicate, perché verificare il rilevatore su posizioni dedotte misurerebbe il gazetteer.

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
    ui.py                     tema, animazioni e logo
    archaeological_database.py
    database_enrichment.py
    geocoding.py              toponimi -> coordinate, con incertezza esplicita
    site_index.py             catalogo come punti, per le mappe satellitari
    source_registry.py
    cropmarks_engine.py       collezioni, maschere e mappe di anomalia
    scene_ranking.py          ranking delle date, senza dipendenze Earth Engine
    data/cam_m_sites.json
    data/potenza_valley_sites.json
    data/pvs_2017_enrichment.json
    data/source_manifest.json
    data/gazetteer.json       generato da scripts/build_gazetteer.py
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

## Test

```bash
python -m unittest tests.test_scene_ranking tests.test_geocoding tests.test_cropmarks_helpers tests.test_candidate_store tests.test_database_enrichment
```

La logica di ranking e di georeferenziazione è scritta in moduli puri proprio per essere verificabile senza rete: i test coprono classificazione fenologica, indice di siccità, ordinamento delle date, AUC, disambiguazione degli omonimi e conteggi della georeferenziazione.

## Note

La cartella `.venv`, gli output RVT, i dati raster locali, i DTM generati e le credenziali/progetti Earth Engine sono locali e non dovrebbero essere versionati.
