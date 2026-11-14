import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
import requests
from affine import Affine


ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "workspace" / "test_dtm" / "Vaassen_AHN4"
SERVICE = "https://service.pdok.nl/rws/ahn/wcs/v1_0"
PARAMETERS = [("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"),
              ("coverageId", "dtm_05m"), ("subset", "x(191650,192650)"),
              ("subset", "y(478100,479100)"), ("format", "image/tiff")]


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    source = FOLDER / "source_0p5m.tif"
    url = requests.Request("GET", SERVICE, params=PARAMETERS).prepare().url
    if not source.exists():
        response = requests.get(SERVICE, params=PARAMETERS, timeout=60)
        response.raise_for_status()
        if response.content[:2] not in (b"II", b"MM"):
            raise ValueError("The coverage service did not return a GeoTIFF.")
        source.write_bytes(response.content)
    with rasterio.open(source) as src:
        dem = src.read(1, masked=True).astype(np.float32).filled(np.nan)
        profile = src.profile.copy()
        transform = src.transform
        bounds = tuple(src.bounds)
        crs = str(src.crs)
    if dem.shape != (2000, 2000) or abs(transform.a - .5) > 1e-8 or abs(transform.e + .5) > 1e-8:
        raise ValueError("Unexpected source grid; no test rasters were generated.")
    files = []
    for resolution, factor, suffix in ((.5, 1, "0p5m"), (1, 2, "1m"), (5, 10, "5m")):
        if factor == 1:
            output = dem
        else:
            blocks = dem.reshape(dem.shape[0] // factor, factor, dem.shape[1] // factor, factor)
            counts = np.isfinite(blocks).sum(axis=(1, 3))
            sums = np.nansum(blocks, axis=(1, 3), dtype=np.float64)
            output = np.full(counts.shape, np.nan, dtype=np.float32)
            np.divide(sums, counts, out=output, where=counts > 0, casting="unsafe")
        path = FOLDER / f"Vaassen_AHN4_DTM_{suffix}.tif"
        settings = dict(profile, height=output.shape[0], width=output.shape[1], dtype="float32", nodata=np.nan,
                        transform=transform * Affine.scale(factor), compress="deflate", predictor=3,
                        tiled=True, blockxsize=256, blockysize=256)
        with rasterio.open(path, "w", **settings) as dst:
            dst.write(output, 1)
            dst.update_tags(SOURCE=url, LICENSE="CC0-1.0", VERTICAL_DATUM="NAP (EPSG:5709)",
                            RESOLUTION_METRES=str(resolution),
                            PROCESSING="Native grid; NoData converted to NaN" if factor == 1 else f"Mean of valid {factor}x{factor} native cells; no upsampling")
        with rasterio.open(path) as check:
            if tuple(check.bounds) != bounds or check.res != (resolution, resolution):
                raise ValueError("The output grids do not share the source extent.")
            data = check.read(1, masked=True)
            files.append({"name": path.name, "resolution_m": resolution, "native": factor == 1,
                          "shape": list(check.shape), "bounds": bounds, "valid_fraction": data.count() / data.size,
                          "elevation_min_m": float(data.min()), "elevation_max_m": float(data.max()),
                          "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    metadata = {"area": "Vaassen, Gortelseweg, Netherlands; 1 km x 1 km", "source": "AHN4 DTM via PDOK",
                "source_grid_m": .5, "source_url": url, "crs": crs, "vertical_datum": "NAP (EPSG:5709)",
                "retrieved_utc": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(), "license": "CC0-1.0",
                "dataset_record": "https://data.overheid.nl/dataset/47567-actueel-hoogtebestand-nederland--ahn--dtm",
                "archaeology_record": "https://monumentenregister.cultureelerfgoed.nl/monumenten/45346",
                "method": "The 0.5 m raster retains the native grid and values. The 1 m and 5 m rasters are area means of valid native cells. All-NoData blocks remain NoData. These are not independent surveys.",
                "files": files}
    (FOLDER / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (FOLDER / "LEGGIMI.txt").write_text(
        "DTM DI TEST — VAASSEN, PAESI BASSI\n\n"
        "Tre GeoTIFF sulla stessa area di 1 km x 1 km, pronti per AIrchGIS:\n"
        "- Vaassen_AHN4_DTM_0p5m.tif: 0,5 m, 2000 x 2000 pixel, griglia nativa AHN4.\n"
        "- Vaassen_AHN4_DTM_1m.tif: 1 m, 1000 x 1000 pixel, media di blocchi 2 x 2.\n"
        "- Vaassen_AHN4_DTM_5m.tif: 5 m, 200 x 200 pixel, media di blocchi 10 x 10.\n\n"
        "Fonte: Rijkswaterstaat / AHN4, servizio pubblico PDOK, licenza CC0-1.0.\n"
        "Coordinate: Amersfoort / RD New, EPSG:28992. Quote in metri rispetto a NAP.\n"
        "0,5 m e la massima risoluzione nativa del raster DTM di questa fonte; non e un limite globale dei DTM.\n"
        "Le tre versioni non sono rilievi indipendenti. Le versioni a 1 e 5 m sono derivate per isolare l'effetto della risoluzione.\n"
        "I vuoti del DTM originale sono conservati; nei blocchi aggregati si usano solo celle valide.\n"
        "Il registro nazionale documenta campi antichi e dieci tumuli nella zona di Gortelseweg (monumento 45346).\n\n"
        "CONFRONTO\n"
        "Caricare un file alla volta, mantenendo stessa area, zoom, direzione e altezza del sole.\n"
        "Per filtri con raggio in pixel, adattare il raggio alla risoluzione per confrontare la stessa scala fisica:\n"
        "un raggio di 10 m equivale a 20 pixel a 0,5 m, 10 pixel a 1 m e 2 pixel a 5 m.\n"
        "Aumentare lo zoom non crea nuovi dettagli. La risoluzione della griglia non equivale alla precisione verticale.\n"
        "L'anteprima PNG mostra hillshade senza interpolazione grafica; il GeoTIFF conserva i dati numerici.\n\n"
        + "Fonte dati: " + metadata["dataset_record"] + "\n"
        + "Contesto archeologico: " + metadata["archaeology_record"] + "\n"
        + "Richiesta di download: " + url + "\n"
        + "Dettagli e SHA-256: provenance.json\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rvt.vis import hillshade
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
    for axis, item in zip(axes, files):
        with rasterio.open(FOLDER / item["name"]) as src:
            data = src.read(1, masked=True).filled(np.nan)
            shaded = hillshade(data, item["resolution_m"], item["resolution_m"], sun_azimuth=315, sun_elevation=35, no_data=np.nan)
            axis.imshow(shaded, cmap="gray", vmin=0, vmax=1, extent=(bounds[0], bounds[2], bounds[1], bounds[3]), interpolation="nearest", origin="upper")
            axis.set_xlim(191950, 192250)
            axis.set_ylim(478400, 478700)
            axis.set_title(str(item["resolution_m"]).replace(".", ",") + " m" + (" · nativo" if item["native"] else " · aggregato"))
            axis.set_xticks([])
            axis.set_yticks([])
    fig.suptitle("Vaassen · stessa area 300 × 300 m · hillshade 315° / 35°")
    fig.savefig(FOLDER / "confronto_risoluzioni.png", dpi=170)
    plt.close(fig)
    package = FOLDER / "Vaassen_AHN4_3_DTM.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in [f["name"] for f in files] + ["LEGGIMI.txt", "provenance.json", "confronto_risoluzioni.png"]:
            archive.write(FOLDER / filename, filename)
    print(json.dumps(metadata, indent=2))
    print(package)


if __name__ == "__main__":
    main()
