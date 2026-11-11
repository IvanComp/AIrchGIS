# Fase 0 — Il reticolo di Potentia è recuperabile da Sentinel-2?

**Esito: no.** Non per un difetto dell'algoritmo, ma per due limiti indipendenti, ciascuno
sufficiente da solo. Il ramo Sentinel-2 va riposizionato su ciò che può fare.

Riprodotto da `docs/fase0_potentia.png` e `docs/contact_ndvi.png`.

---

## 1. Georeferenziazione della Fig. 71

I tick della figura sono stati misurati sul render a 400 dpi e interpolati con una affine.

| | |
|---|---|
| CRS | EPSG:3004 (Monte Mario / Italy zone 2) |
| GCP | 4 easting (2411900→2412800), 5 northing (4807000→4808200), passo 300 m |
| Scala | 0.52174 m/px in X, 0.52092 m/px in Y — pixel quadri entro lo 0.16% |
| Residuo massimo GCP | **0.31 m** |
| Estensione inquadratura | 1099.8 × 1637.8 m |

Parametri salvati in `airch/data/potentia_reference.json`.

### Correzione al piano: la figura non è ad alta risoluzione

L'immagine incorporata nel PDF è di **396 × 584 px a 72 ppi**, cioè **2.78 m di GSD**.
Il rendering a 400 dpi è un upsampling ×5.3 di quel raster. Il residuo GCP di 0.31 m
misura la qualità dell'affine, non l'accuratezza del contenuto: la vettorializzazione
della Fig. 71 avrà un'incertezza di posizione dell'ordine di **±3–6 m**, non metrica.

Resta comunque adeguata a validare rilevazioni su pixel da 10 m, ma la Fase 1 va
dimensionata su questa precisione, e la tolleranza di sovrapposizione va dichiarata.

## 2. Geometria misurata dell'area urbana

| | |
|---|---|
| Lato lungo | 532 m |
| Lato corto | 335 m |
| Area murata | 17.8 ha |
| Azimut asse lungo | 163.1° |
| Passo delle insulae | ~48 m |
| Larghezza strade | ~5 m |

Congruente con l'estensione pubblicata di Potentia (~18 ha). La stima del piano
(400–450 m di larghezza) era corretta come ordine di grandezza sul lato lungo.

## 3. Il limite di risoluzione, misurato e non stimato

Rumore NDVI reale, ad alta frequenza, dentro campi omogenei, mediano su 9 scene:

**σ = 0.0396**

Modello diretto del reticolo — strade di 5 m con passo 48 m, contrasto di crop mark
**forte** (ΔNDVI 0.15 sulla strada), convoluto con una PSF Sentinel-2 realistica
(gaussiana σ ≈ 4.5 m) e campionato a 10 m:

| struttura | modulazione a 10 m | SNR su singola data |
|---|---|---|
| reticolo urbano, strade 5 m @ 48 m | 0.063 NDVI | **1.6** |
| fossato / strada extraurbana, 20 m | 0.150 NDVI | 3.8 |
| recinto o banda di 40 m | 0.150 NDVI | 3.8 |

Per portare il reticolo a SNR 3 su una singola data servirebbe **ΔNDVI 0.28** sulla
strada: un crop mark eccezionale sta fra 0.15 e 0.20, quindi la soglia non è raggiungibile.

Il pannello C di `fase0_potentia.png` mostra il reticolo vero, con la geometria vera e il
rumore vero, ed è indistinguibile dal rumore a occhio.

*Sfumatura onesta:* impilando N date indipendenti l'SNR cresce con √N, quindi 10 buone
date porterebbero a ~5. Non è quindi un'impossibilità assoluta di campionamento — ma
richiede che il crop mark sia presente e forte su tutte quelle date, e il punto 4 spiega
perché a Potentia non può esserlo.

## 4. Il limite che chiude la questione: dentro le mura non si coltiva

ESA WorldCover a 10 m dentro il poligono delle mura:

| classe | quota |
|---|---|
| prateria | 43.3% |
| seminativo | 36.5% |
| alberi | 13.9% |
| edificato | 4.9% |

Ciclo NDVI 2024–2025:

| | p5 | p50 | p95 |
|---|---|---|---|
| dentro le mura | **0.323** | 0.504 | 0.793 |
| campi circostanti | −0.174 | 0.128 | 0.486 |

L'NDVI dentro le mura non scende **mai** sotto 0.32: il terreno non è mai nudo.
Quindi:

- **soil marks: impossibili**, non esiste la condizione di suolo arato;
- **crop marks in cereali: impossibili su circa il 62% dell'interno**, che è prato
  permanente, alberato o costruito.

I *vegetation marks* della Fig. 69 sono parch marks su prato, ripresi da fotografia
aerea obliqua a bassa quota (il volume documenta l'uso di Helikite Aerial Photography):
un'altra modalità di osservazione, a risoluzione centimetrica.

## 5. Cosa ha fatto il tool su questa AOI

Ranking sull'archivio completo 2016–2026, 371 scene, 347 valide:

- **13 delle prime 14 date vengono dal solo 2025**, su un archivio di 11 anni;
- `siccita` = 0.00 su tutte le prime 14 date — il termine idrico non ha inciso;
- `fase` = «vegetazione» su tutte, su un'area che è per il 43% prato permanente.

Sono i difetti 2, 3, 4 e 5 del piano, osservati in esercizio: il punteggio segue
l'eterogeneità dell'annata, la fenologia mediata sull'AOI non ha significato fisico, e
la normalizzazione relativa al lotto rende i valori non confrontabili.

## 6. Correzione al piano: il DTM di Potentia c'è già

Il piano dava per scaricare il tassello LiDAR. In realtà
`RVT/generated_dtm/DTM/regional_selection_20260627_173505_DTM.tif` copre
13.6632–13.6733 E, 43.4116–43.4204 N, cioè circa il 90% dell'area murata.

È però a **5 m**, non a 1–2 m come il prodotto del Ministero dell'Ambiente usato nella
Fig. 72, e mostra una **bandeggiatura sistematica** ben visibile nell'hillshade e nel
rilievo locale, che genererebbe anomalie lineari spurie. Per la validazione del ramo
LiDAR serve il tassello ad alta risoluzione.

## 7. Conseguenze operative

1. Il ramo Sentinel-2 va dichiarato, nel README e nell'interfaccia, per quello che può
   fare: strade extraurbane, centuriazione, grandi recinti, paleoalvei — strutture da
   **20 m in su** — e soprattutto screening delle annate.
2. La detection di dettaglio va spostata su ortofoto ad alta risoluzione e su LiDAR.
3. Potentia **non** è utilizzabile come caso di calibrazione per il ramo Sentinel-2.
   Serve un bersaglio compatibile con 10 m: un tratto di centuriazione o un grande
   recinto, su seminativo.
4. Le fasi A–D del piano restano valide, ma la metrica di riferimento va ridefinita su
   un bersaglio risolvibile, altrimenti si ottimizzerebbe verso un segnale assente.
