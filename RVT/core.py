import rvt.vis
import rvt.default
import rasterio
import numpy as np
import os
from pathlib import Path

def save_raster(data, output_path, profile):
    """Salva l'array in formato GeoTIFF con metadati geografici."""
    profile.update(dtype=rasterio.float32, count=1, nodata=np.nan, driver='GTiff')
    with rasterio.open(output_path, 'w', **profile) as dst:
        dst.write(data.astype(np.float32), 1)

def load_lidar(path):
    """Carica il raster (TIF o ASC) e restituisce dati, risoluzione e profilo."""
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        # Sostituisce i valori NoData con NaN per evitare artefatti nei calcoli RVT
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
        return data, src.res[0], src.profile

def process_triple(filename):
    # Definisce i percorsi per i tre tipi di file
    base_name = Path(filename).stem
    ext = Path(filename).suffix
    
    p_dtm = Path("image/DTM") / filename
    p_first = Path("image/DSMfirst") / filename
    p_last = Path("image/DSMlast") / filename

    # Verifica che esistano tutti e tre
    if not (p_dtm.exists() and p_first.exists() and p_last.exists()):
        print(f"⚠️ Tripletta incompleta per {filename}. Controlla che il file esista in tutte e 3 le cartelle.")
        return

    print(f"--- Elaborazione in corso: {base_name} ---")
    
    # Caricamento dati
    dtm, res, prof = load_lidar(p_dtm)
    dsm_f, _, _ = load_lidar(p_first)
    dsm_l, _, _ = load_lidar(p_last)

    # Crea cartella di output specifica per questo lotto
    out_dir = Path(f"output_rvt/{base_name}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. PRODOTTI DAL DTM (Morfologia Terreno) ---
    print("   > Generazione Hillshade e Sky-View Factor...")
    save_raster(rvt.vis.hillshade(dtm, res, res), out_dir / "1_DTM_Hillshade.tif", prof)
    svf = rvt.vis.sky_view_factor(dtm, resolution=res, compute_svf=True)[0]
    save_raster(svf, out_dir / "2_DTM_SkyViewFactor.tif", prof)

    # --- 2. nDSM (Mappa delle Altezze Reali) ---
    # Formula: Primo Ritorno - Terreno
    print("   > Calcolo nDSM (Altezza edifici/alberi)...")
    ndsm = dsm_f - dtm
    save_raster(ndsm, out_dir / "3_nDSM_Altezze.tif", prof)

    # --- 3. DENSITÀ VEGETAZIONE (First - Last) ---
    # Indica quanto raggio laser è 'passato attraverso' prima di fermarsi
    print("   > Analisi penetrazione vegetazione...")
    diff_fl = dsm_f - dsm_l
    save_raster(diff_fl, out_dir / "4_Vegetazione_Densita.tif", prof)

    print(f"✅ Completato: {base_name}\n")

if __name__ == "__main__":
    # Cerca tutti i file supportati nella cartella DTM
    dtm_path = Path("image/DTM")
    if not dtm_path.exists():
        print("❌ Errore: La cartella 'image/DTM' non esiste!")
    else:
        # Trova file .tif, .tiff e .asc
        extensions = ['*.tif', '*.tiff', '*.asc']
        files_to_process = []
        for ext in extensions:
            files_to_process.extend(dtm_path.glob(ext))

        if not files_to_process:
            print("❓ Nessun file trovato. Assicurati di aver messo i file in image/DTM")
        else:
            print(f"📂 Trovati {len(files_to_process)} file da elaborare.\n")
            for f in files_to_process:
                process_triple(f.name)
            print("🚀 Processo terminato! Trovi i risultati nella cartella 'output_rvt'.")