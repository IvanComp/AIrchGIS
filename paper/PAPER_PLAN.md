# AIrch: paper plan

## 1. The contribution in one sentence

AIrch is an open-source, AI-assisted workbench for archaeologists with little IT background. It brings LiDAR, Sentinel-2/Landsat and 3D visualisation together in one interface, and it **measures itself** against known sites and against the physical limits of the sensors.

The paper cannot (and should not) be sold as "a new detector that finds sites better than others": the benchmarks in `docs/PHASE_A.md` give AUC between 0.34 and 0.58, close to chance. The strong contribution is a different one, and easier to defend:

| # | Contribution | Evidence already available | Missing |
|---|---|---|---|
| C1 | Single no-code workbench: LiDAR/RVT + 3D + multispectral + candidate dossiers | Working app (ex ArchaeoScope), renamed AIrch | UI polish |
| C2 | Evidence-first AI: physically motivated date ranking, parcel-interior statistics, scores as priorities rather than probabilities, natural-language assistant | Ranking, masks, persistence, recurrence (code + tests) | **AI assistant** to be built |
| C3 | Built-in, reproducible evaluation protocol (AUC, precision@k vs chance, edge contamination) against a catalogue of known sites + resolvability analysis | Boundaries: 7.5% of the area, 70% of candidates (9.3×), then 0.50→0.05 after Phase A; Potentia SNR 1.6 | Widen the calibration regions (statistical power) |
| C4 | Usability evaluation with archaeologists (SE perspective) | — | **User study** (8–15 archaeologists, tasks + SUS + think-aloud) |

The known-site catalogue (CAM-M / PVS) is no longer a screen of the tool: it is the ground truth behind C3. The "negative" Sentinel-2 result is a strength: few papers state with numbers what the sensor *cannot* see, and a tool for non-specialists has to say it.

## 2. Chosen venue: **Digital Applications in Archaeology and Cultural Heritage (DAACH)**

| Journal | Fit | Why |
|---|---|---|
| **DAACH** (Elsevier) | **Yes, first choice** | Its scope is exactly digital applications, software and workflows for archaeology and cultural heritage, and it is indexed in both archaeology and applied computer science. It already publishes this kind of work (Pețan & Hegyi 2023 on free LiDAR DTMs, cited by Corbo). A tool + evaluation + user-study paper is its typical format. |
| Virtual Archaeology Review (UPV) | Good alternative | Diamond open access (no APC) and strong on the CS side, but centred on 3D, virtual reconstruction and visualisation; in our paper 3D is a component, not the core. Good plan B, or the venue for a second paper on the 3D viewer and UX. |
| npj Heritage Science (Nature) | Only with discoveries | High impact and broad audience, but it expects a strong scientific result, e.g. new sites confirmed in the field. With AUC near chance it would look weak today. Keep it for later work with field validation. |
| Journal of Cultural Heritage (Elsevier) | Less suitable | Strongly oriented to conservation, materials and diagnostics; a prospection software paper is peripheral to its focus. |

To check before submission: DAACH APC and open-access option, current SCImago quartiles, guide for authors (length, citation style: the template uses author-year `elsarticle-harv`).

## 3. Paper structure (≈ 8,000–10,000 words)

1. **Introduction** ✅ written (`0-MAIN.tex` + `sections/`)
2. **Related work**: LiDAR visualisation; multispectral/multitemporal; AI/ML; tools, usability and reproducibility. Ends with a gap table (tool × LiDAR/MS/3D/AI/no-code/self-evaluation).
3. **Requirements & design principles**: R1 no-code, single entry point; R2 multi-source; R3 explicit uncertainty and provenance; R4 scores as priorities; R5 self-evaluation; R6 local-first and responsible handling of site locations.
4. **Architecture & implementation**: Terrain (RVT + 3D) / Spectral (Crop Marks) / Candidates / Evaluation / Assistant modules, with an architecture figure.
5. **AI components**: scene ranking, per-date anomalies aggregated afterwards, parcel-interior z-scores, linear marks, persistence/recurrence, benchmark, assistant with guardrails (never invents coordinates, cites sources).
6. **Evaluation**
   - 6.1 Study area and data (Macerata, CAM-M, PVS, calibration regions)
   - 6.2 Detection benchmark (tables from `docs/PHASE_A.md`)
   - 6.3 Resolvability (Potentia, from `docs/PHASE0_RESOLVABILITY.md`)
   - 6.4 LiDAR case study with 3D views (e.g. Castello di Montedoglio from the RVT tile database)
   - 6.5 User study
7. **Discussion**: limits, statistical power, role of AI. **Ethics**: precise site coordinates feed illicit digging and unauthorised metal detecting; access levels and a reference to the Italian Code (D.Lgs. 42/2004) are needed. Better to address it openly: an archaeologist reviewer will ask.
8. **Conclusions**, plus Data & code availability.

## 4. What is needed to finish the paper (in order)

1. Implement the AI assistant, the piece that justifies the "AI" in the title beyond the ranking.
2. Widen the benchmark to more regions and raise k (PHASE_A already says precision@20 does not discriminate today).
3. LiDAR case study with 2D/3D figures.
4. User study: protocol, consent, 8–15 participants, SUS + times + errors.
5. Public repository + Zenodo DOI.

## 5. Bibliography

`references.bib` holds 55 entries:
- `related-work`: the 3 papers in `USEFUL PAPERS/`;
- `from-refs`: works cited in their bibliographies, with metadata taken from there;
- `external`: AI/ML, usability, data and reproducibility. **Check these DOIs one by one before submission.**
