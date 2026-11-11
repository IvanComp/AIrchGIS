# AIrch: piano del paper

## 1. Il contributo, in una frase

AIrch è un workbench open source, assistito da AI e pensato per archeologi con poche competenze informatiche. Mette insieme LiDAR, Sentinel-2/Landsat, visualizzazione 3D e un catalogo dei siti noti con le incertezze esplicite, e **misura sé stesso** contro i siti noti e contro i limiti fisici dei sensori.

Il paper non può (e non deve) vendersi come "un nuovo rilevatore che trova siti meglio degli altri": i benchmark in `docs/FASE_A.md` mostrano AUC tra 0.34 e 0.58, cioè vicino al caso. Il contributo forte è un altro, ed è più difendibile:

| # | Contributo | Evidenza già disponibile | Cosa manca |
|---|---|---|---|
| C1 | Workbench unico, no-code: LiDAR/RVT + 3D + multispettrale + catalogo + dossier candidati | App funzionante (ex ArchaeoScope) | Rinomina AIrch, pulizia UI |
| C2 | AI "evidence-first": ranking date fisicamente motivato, statistiche dentro la parcella, punteggi come priorità e non probabilità, assistente in linguaggio naturale | Ranking, maschere, persistenza, ricorrenza (codice + test) | **Assistente AI** da sviluppare |
| C3 | Protocollo di valutazione integrato e riproducibile (AUC, precision@k vs caso, contaminazione dai bordi) + analisi di risolvibilità | Bordi: 7.5% dell'area, 70% dei candidati (9.3×) e poi 0.50→0.05 dopo la Fase A; Potentia SNR 1.6 | Ampliare le regioni di calibrazione (potenza statistica) |
| C4 | Valutazione d'uso con archeologi (prospettiva SE) | — | **User study** (8–15 archeologi, task + SUS + think-aloud) |

Il risultato "negativo" su Sentinel-2 è un punto di forza: pochi lavori dicono con numeri cosa il sensore *non* può vedere, e un tool per non esperti deve dirlo.

## 2. Venue scelta: **Digital Applications in Archaeology and Cultural Heritage (DAACH)**

| Journal | Adatto al contributo? | Motivo |
|---|---|---|
| **DAACH** (Elsevier) | **Sì, prima scelta** | Lo scope è proprio "applicazioni digitali, software, workflow" per archeologia e beni culturali. È indicizzato sia in archeologia sia in informatica applicata. Pubblica già lavori di questo tipo: Pețan & Hegyi 2023 sul DTM LiDAR gratuito, citato da Corbo. Un paper tool + valutazione + user study è il suo formato tipico. |
| Virtual Archaeology Review (UPV) | Buona alternativa | Diamond open access (niente APC) e forte sulla parte CS. Però è centrata su 3D, ricostruzione virtuale e visualizzazione, mentre nel nostro paper il 3D è una componente e non il cuore. Ottimo piano B, o sede per un secondo paper focalizzato sul viewer 3D e sulla UX. |
| npj Heritage Science (Nature) | Solo se arrivano scoperte | Impatto alto e pubblico ampio, ma si aspetta un risultato scientifico forte, per esempio nuovi siti confermati sul campo. Con AUC vicino al caso, oggi verrebbe giudicato debole. Da tenere per un lavoro successivo con validazione sul terreno. |
| Journal of Cultural Heritage (Elsevier) | Meno adatto | Molto orientato a conservazione, materiali e diagnostica. Un paper su un software per la prospezione è periferico rispetto al suo focus. |

Da verificare prima della submission: APC e opzione open access di DAACH, quartili aggiornati su SCImago, guide for authors (lunghezza, stile di citazione: il template usa author-year `elsarticle-harv`).

## 3. Struttura del paper (≈ 8.000–10.000 parole)

1. **Introduction** ✅ scritta (`main.tex`)
2. **Related work**: LiDAR visualisation; multispectral/multitemporal; AI/ML; tools, usability e riproducibilità. Chiude con una tabella del gap (tool × LiDAR/MS/catalogo/3D/AI/no-code/auto-valutazione).
3. **Requirements & design principles**: R1 no-code e un solo punto d'ingresso; R2 multi-sorgente; R3 incertezza e provenienza esplicite; R4 punteggi come priorità; R5 auto-valutazione; R6 local-first e gestione responsabile delle posizioni dei siti.
4. **Architecture & implementation**: moduli Terrain / Spectral / Sites / Candidates / Assistant, con figura dell'architettura.
5. **AI components**: ranking delle scene, anomalie per data aggregate dopo, z-score interni alla parcella, marks lineari, persistenza/ricorrenza, benchmark, assistente con guardrail (non inventa coordinate, cita le fonti).
6. **Evaluation**
   - 6.1 Area di studio e dati (Macerata, CAM-M, PVS, regioni di calibrazione)
   - 6.2 Benchmark di detection (tabelle da `docs/FASE_A.md`)
   - 6.3 Risolvibilità (Potentia, da `docs/FASE0_RISOLVIBILITA.md`)
   - 6.4 Caso studio LiDAR con viste 3D (es. Castello di Montedoglio dal database RVT)
   - 6.5 User study
7. **Discussion**: limiti, potenza statistica, ruolo dell'AI. **Etica**: le coordinate precise dei siti alimentano lo scavo clandestino e il metal detecting non autorizzato; servono livelli di accesso e un richiamo al D.Lgs. 42/2004. Conviene affrontarlo apertamente, perché un reviewer archeologo lo chiederà.
8. **Conclusions**, più Data & code availability.

## 4. Cosa serve per chiudere il paper (in ordine)

1. Rinomina e unificazione AIrch (vedi `docs/AIRCH_STRUTTURA.md`).
2. Implementare l'assistente AI, il pezzo che giustifica la "AI" del titolo oltre al ranking.
3. Ampliare il benchmark a più regioni e alzare k (lo dice già FASE_A: oggi precision@20 non discrimina).
4. Caso studio LiDAR con figure 2D/3D.
5. User study: protocollo, consenso, 8–15 partecipanti, SUS + tempi + errori.
6. Repository pubblico + DOI Zenodo.

## 5. Bibliografia

`references.bib` contiene 55 voci:
- `related-work`: i 3 paper in `USEFUL PAPERS/`;
- `from-refs`: lavori citati nelle loro bibliografie, con metadati presi da lì;
- `external`: AI/ML, usabilità, dati e riproducibilità. **Questi DOI vanno controllati uno per uno prima della submission.**
