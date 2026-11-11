# Fase A — mediana fuori dalla detection, kernel dentro la parcella, mascherature

Difetti 1, 6, 7 del piano, più un ottavo emerso durante la misura.

Tutte le cifre vengono da `scripts/benchmark_cropmarks.py`, che gira sulla stessa
regione, con gli stessi parametri, e scrive in `docs/benchmarks/`.

## Regione di calibrazione

Potentia non è utilizzabile per il ramo Sentinel-2 (vedi `FASE0_RISOLVIBILITA.md`).
Il bersaglio è stato scelto per misura, non per fama: fra i 148 siti con coordinate
pubblicate, quelli con almeno il 70% di seminativo, meno del 5% di edificato, meno
del 10% di alberi entro 400 m, e NDVI invernale sotto 0.15 — cioè campi davvero arati.

Ne restano 20. Il gruppo più denso è **Pollenza / Treia, C.da San Marco Vecchio**:
8 ville e fattorie romane in 3 km, 29 siti pubblicati in totale, 3.8 × 4.7 km.
Definizione in `airch/data/calibration_region.json`.

Sono bersagli compatibili con i 10 m: piattaforme e cortili di decine di metri.

## Metriche

- **AUC**: il layer dà ai siti noti valori più alti che a punti casuali? 0.5 = caso.
- **precision@20**: quanti dei 20 candidati più forti cadono entro 100 m da un sito noto,
  contro la quota di area che sta entro 100 m da un sito (0.045 qui).
- **contaminazione da bordi**: quanti dei 20 candidati stanno su un confine di parcella,
  ricavato indipendentemente dalla dissimilarità stagionale dell'NDVI.

Candidati = massimi locali distanti almeno 100 m fra loro, dentro la maschera di analisi.

## Due confronti, entrambi interni

Le misure a 10 m e a 20 m non sono confrontabili fra loro, quindi ci sono due
confronti separati, ciascuno con i suoi due rami sulla stessa griglia:

- **diagnostica della mediana**, a 10 m: `baseline_*.json` contro `mediana_*.json`;
- **legacy contro Fase A**, a 20 m, che è la scala a cui l'analisi gira davvero:
  `legacy_*.json` contro `fase-a_*.json`. Il ramo legacy non è una vecchia esecuzione
  ricordata: `--legacy` ricostruisce il percorso pre-Fase A **sulle stesse scene, sulla
  stessa griglia, con le stesse metriche**, così l'unica differenza è la costruzione.

Il caso di riferimento è calcolato sull'area **effettivamente analizzata**: la Fase A
esclude la fascia vicino ai confini, quindi cerca in un'area più piccola e confrontarla
con un caso calcolato su tutta la regione sarebbe sbagliato in entrambe le direzioni.

## Baseline e diagnostica della mediana (10 m)

| layer | AUC | precision@20 | su bordi |
|---|---|---|---|
| Persistent_any | 0.54 | 0.050 | **0.70** |
| Vegetation_deficit | 0.41 | 0.000 | 0.45 |
| Linear_marks | 0.36 | 0.000 | 0.15 |

I bordi di parcella occupavano il **7.5%** dell'area analizzabile e raccoglievano il
**70%** dei candidati: **arricchimento 9.3×**. Difetto 6 confermato come dominante.

Le AUC sotto 0.5 di deficit e marks lineari non sono rumore: i siti noti stavano
*sistematicamente più in basso* del fondo. Quei layer misuravano la geometria agraria, e
le ville romane stanno in mezzo ai campi, dove quel contrasto è minimo.

`Persistent_any` è identico nelle due modalità, perché la persistenza era già calcolata
data per data. La mediana toccava solo i layer derivati da `base`:

| layer | modalità | AUC | su bordi |
|---|---|---|---|
| Vegetation_deficit | migliore data | 0.41 | 0.45 |
| Vegetation_deficit | mediana | 0.41 | **0.60** |
| Linear_marks | migliore data | 0.36 | 0.15 |
| Linear_marks | mediana | 0.36 | **0.25** |

La mediana non migliora nulla e aumenta la contaminazione da bordi del 33% e del 67%:
compositando si cancella il segnale transitorio e sopravvive la geometria permanente dei
campi. Difetto 1 confermato nella direzione prevista.

## Cosa è cambiato

**Difetto 1.** Le anomalie non si calcolano più su un'immagine composita. `date_marks`
misura deficit, eccesso e soil marks su **ogni data selezionata**, e `detection_layers`
aggrega dopo: media per le mappe di intensità, soglia e media per la persistenza, e
conteggio degli anni distinti per la ricorrenza. La modalità mediana resta, ma si chiama
«Mediana migliori date (solo contesto)» e alimenta solo i layer da guardare.

**Difetto 6.** I confini di parcella si ricavano dalla **dissimilarità stagionale**: una
mediana NDVI per mese, poi la distanza fra il profilo annuale di un pixel e quello dei
quattro vicini, soglia al 92° percentile dell'area. Il z-score locale viene poi calcolato
solo dove un intorno di 60 m sta **tutto dentro un campo** — lì il kernel circolare non
può attraversare un margine, quindi *è* la statistica di parcella, senza il costo di una
riduzione per componenti connesse.

Una prima versione usava SNIC più `reduceConnectedComponents`. È stata scartata due volte:
sovra-segmentava (dopo il buffer sopravviveva lo **0.5%** dell'area) ed era troppo costosa
per Earth Engine su 18 km² per 12 date.

**Difetto 7.** SCL 2 (ombra topografica) e 6 (acqua) ora mascherate. La copertura è un
**filtro rigido** al 90%, non uno sconto: una scena che vede un lembo dell'area descrive
un altro posto e viene esclusa, per quanto contrastata sia.

**Difetto 8, non nel piano.** `pca()` chiamava `toArray()` su un'immagine con pixel
parzialmente mascherati: array di lunghezza diversa, covarianza centrata NaN, `eigen()`
in errore. Siccome le bande PCA erano dentro l'immagine esportata, **l'intero export
GeoTIFF falliva con un 400 opaco** su ogni AOI grande — «Prepara download GeoTIFF» e
l'export su Drive erano rotti. Ora la PCA maschera ai pixel con tutte le bande valide, si
calcola in modo pigro ed è fuori dall'immagine esportata. L'export funziona.

## Risultato — legacy contro Fase A, a 20 m, sulle stesse scene

| layer | metrica | legacy | Fase A |
|---|---|---|---|
| Persistent_any | AUC | 0.51 | **0.58** |
| | precision@20 | 0.100 (caso 0.043) | 0.000 (caso 0.025) |
| | su bordi | 0.50 | **0.05** |
| Vegetation_deficit | AUC | 0.45 | 0.34 |
| | precision@20 | 0.100 (caso 0.041) | 0.000 (caso 0.025) |
| | su bordi | 0.35 | **0.15** |
| Linear_marks | AUC | 0.51 | 0.51 |
| | precision@20 | 0.050 (caso 0.042) | 0.050 (caso 0.025) |
| | su bordi | 0.00 | 0.00 |

Area cercabile: **95.8% → 40.6%** della regione. Siti raggiungibili: **29 → 12**.
La fascia esclusa contiene il 59% dell'area e il 59% dei siti, cioè la stessa quota:
i siti noti **non** stanno preferenzialmente sui confini di campo, vengono rimossi al
tasso di base.

### Cosa è stato risolto

La contaminazione da bordi crolla di 10× sulla persistenza (0.50 → 0.05) e più che si
dimezza sul deficit (0.35 → 0.15). L'arricchimento 9.3× sui confini non esiste più. È il
difetto che il piano indicava come dominante, ed era dominante.

L'export GeoTIFF, che falliva sempre su AOI grandi, funziona.

### Cosa non è stato risolto, e un peggioramento

L'AUC resta fra 0.34 e 0.58: **il rilevatore non trova i siti noti meglio del caso.**
La Fase A ha tolto falsi positivi, non ha aggiunto veri positivi.

Su due layer la precision@20 **peggiora**, da 0.100 a 0.000: due candidati centrati su
29 bersagli diventano zero su 12. Contro un caso di 0.043 e 0.025, ci si aspettano
rispettivamente 0.86 e 0.50 successi casuali su 20 candidati: sia «due» sia «zero» sono
dentro il rumore di Poisson, e la differenza non è significativa. Ma la direzione è
sfavorevole e va detta.

Il `Vegetation_deficit` peggiora anche in AUC, da 0.45 a 0.34: restringere il calcolo
all'interno delle parcelle lo rende *più* anti-correlato con i siti noti. È coerente con
la lettura della baseline — quel layer misura variabilità agronomica interna al campo —
e suggerisce che il deficit medio, così com'è, non sia un indicatore utile.

### Potenza statistica

Con 12–29 bersagli, 18 km² e 100 m di tolleranza, differenze di uno o due candidati su
venti non sono distinguibili dal caso. **A questa densità di bersagli precision@20 non
discrimina.** L'AUC è il numero più affidabile, e va letto insieme alla contaminazione da
bordi. Prima delle Fasi B e C conviene ampliare la regione di calibrazione o alzare k,
altrimenti si rischia di tarare su rumore.
