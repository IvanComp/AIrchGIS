# AIrch: struttura unificata (proposta)

## Cosa è già fatto (branch `airch-unify`)

- Il pacchetto `archaeoscope/` è stato rinominato in `airch/` con `git mv`, quindi la storia dei file resta.
- `archaeoscope_app.py` → `airch_app.py`, `start_archaeoscope.command` → `start_airch.command`, venv `.venv_airch`.
- Ogni occorrenza di "ArchaeoScope" in codice, README, docs, script e test ora dice "AIrch". Il logo testuale è `<span>AI</span>rch`, con "AI" evidenziato.
- I tool standalone portano il marchio AIrch: finestra Tk "AIrch · LiDAR Explorer", pagine "AIrch · DTM da mappa", "AIrch · 3D Cloud" e "AIrch · Crop Marks".
- **La visualizzazione 3D non è stata toccata**, a parte il titolo della pagina.
- Test: 57 su 59 passano. I 2 che falliscono richiedono `scipy`, che manca solo nella shell di verifica, non nel tuo venv.

## Struttura a cui tendere

L'idea è che l'archeologo veda **un'app sola, con 5 schermate per compito**, non per tecnologia. Il codice segue la stessa divisione.

```text
Neural-Detecting/                 (repo; nome cartella libero)
  start_airch.command             doppio clic: unico punto d'ingresso (mac)
  start_airch.bat                 [da fare] equivalente Windows
  airch_app.py
  airch/
    app.py                        shell, navigazione, stato
    ui.py                         tema e logo
    paths.py                      tutti i percorsi in un posto solo
    terrain/                      ← oggi RVT/core.py + rvt_web.py + lads_preview.py
      visualizations.py           hillshade, SVF, openness, LRM, VAT (rvt-py)
      dtm_io.py                   triplette DTM/DSM, DTM da mappa regionale
      viewer3d.py                 3D Cloud (codice attuale, invariato)
      screen.py                   schermata Streamlit
    spectral/                     ← oggi cropmarks_engine.py + scene_ranking.py
    sites/                        ← archaeological_database.py, geocoding.py,
                                    database_enrichment.py, site_index.py, source_registry.py
    candidates/                   ← candidate_store.py
    evaluation/                   ← benchmark.py (+ scripts/benchmark_cropmarks.py)
    assistant/                    [nuovo] assistente AI
      prompts.py, tools.py, screen.py
    data/
  legacy/
    rvt_desktop_gui.py            ← vecchia GUI Tk (RVT/core.py), solo per chi la usa
  workspace/                      dati utente, ignorato da git
    lidar/  outputs/  dtm_regionale/
  paper/                          manoscritto
  docs/
  tests/
```

### Le 5 schermate, con nomi per non informatici

| Oggi | Proposta | Cosa fa |
|---|---|---|
| RVT | **Terreno (LiDAR)** | Carica DTM/DSM o ritaglia dalla mappa, visualizzazioni, griglia metodi, 3D |
| Crop Marks | **Tracce nei campi (satellite)** | AOI, date migliori, anomalie, persistenza |
| Database | **Siti noti** | Catalogo CAM-M/PVS, mappa, schede |
| Candidati | **I miei candidati** | Dossier, stato verifica, export |
| — | **Assistente AI** (pannello laterale sempre visibile) | Spiega, consiglia parametri, guida passo-passo |

### L'assistente AI (il pezzo che manca per il paper)

- Pannello laterale in ogni schermata. Riceve il contesto della schermata (AOI, layer attivo, parametri, metriche del benchmark) e risponde in italiano semplice.
- Può proporre azioni, come "prova SVF con raggio 10 m" o "questa AOI è al 60% prato: le soil marks non sono attendibili", e l'utente le applica con un clic.
- Guardrail: non inventa coordinate né siti; cita sempre la fonte (scheda CAM-M, pagina); presenta i punteggi come priorità.
- Backend configurabile: API Claude, oppure un modello locale via Ollama per chi non vuole mandare dati fuori.
- Va loggato in modo anonimo, così l'user study ha dati su cosa chiedono gli archeologi.

## Pulizie consigliate (non fatte, aspetto il tuo ok)

1. **`Crop marks Tool/.venv` è dentro git**: 12.866 file tracciati. Si toglie con `git rm -r --cached "Crop marks Tool/.venv"`, che non cancella niente dal disco.
2. Togliere da git `RVT/scripts/__pycache__/*.pyc`, che è tracciato.
3. `USEFUL PAPERS/` (≈ 90 MB di PDF sotto copyright) va in `.gitignore` e non nel repo pubblico.
4. `tmp/` (OCR e render dei PDF) va in `.gitignore`.
5. Spostamento fisico di `RVT/` e `Crop marks Tool/` dentro `airch/terrain` e `airch/spectral`. È il passo più delicato, perché `RVT/core.py` (4.400 righe) usa percorsi relativi ai dati in `RVT/image`, `RVT/data` e `RVT/generated_dtm`. Va fatto insieme allo spostamento dei dati in `workspace/` e provato a mano sull'app.
