import os
from pathlib import Path

import ee
import folium
import pandas as pd

from .paths import CROP_EE_PROJECT_FILE, ROOT_EE_PROJECT_FILE


BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
INDEX_BANDS = [
    "NDVI",
    "GNDVI",
    "DVI",
    "GDVI",
    "GRVI",
    "SR",
    "EVI",
    "MCARI",
    "SAVI",
    "NDMI",
    "NDWI",
    "MSI",
    "Crop_band",
    "Soil_band",
    "TCT_brightness",
    "TCT_greenness",
    "TCT_wetness",
]
PCA_BANDS = [
    "B2",
    "B3",
    "B4",
    "B8",
    "B11",
    "B12",
    "NDVI",
    "GNDVI",
    "DVI",
    "GDVI",
    "GRVI",
    "SR",
    "EVI",
    "MCARI",
    "SAVI",
    "NDMI",
    "NDWI",
    "MSI",
    "Crop_band",
    "Soil_band",
    "TCT_brightness",
    "TCT_greenness",
    "TCT_wetness",
]


def default_project():
    env = os.environ.get("EE_PROJECT", "").strip()
    if env:
        return env
    for project_file in (CROP_EE_PROJECT_FILE, ROOT_EE_PROJECT_FILE):
        if project_file.exists():
            return project_file.read_text(encoding="utf-8").strip()
    return ""


def save_default_project(project):
    project = (project or "").strip()
    if not project:
        return
    CROP_EE_PROJECT_FILE.write_text(project + "\n", encoding="utf-8")


def add_base_tiles(m, esri_show=True):
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Imagery",
        overlay=False,
        control=True,
        show=esri_show,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False, control=True, show=not esri_show).add_to(m)
    folium.TileLayer("CartoDB positron", name="CartoDB Positron", overlay=False, control=True, show=False).add_to(m)


def init_ee(project):
    project = (project or "").strip()
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()


def flat_coords(x, out):
    if not x:
        return
    if isinstance(x[0], (int, float)):
        out.append(x)
    else:
        for y in x:
            flat_coords(y, out)


def center(g):
    pts = []
    flat_coords(g["coordinates"], pts)
    if not pts:
        return [41.5, 15.5]
    return [sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)]


def geom(g):
    if g["type"] == "Polygon":
        return ee.Geometry.Polygon(g["coordinates"])
    if g["type"] == "MultiPolygon":
        return ee.Geometry.MultiPolygon(g["coordinates"])
    raise ValueError("Disegna un poligono o un rettangolo.")


def mask_s2(img):
    scl = img.select("SCL")
    mask = (
        scl.neq(0)
        .And(scl.neq(1))
        .And(scl.neq(3))
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
    )
    scaled = img.select(BANDS).divide(10000)
    return img.addBands(scaled, None, True).updateMask(mask).copyProperties(
        img,
        ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE", "system:index"],
    )


def add_indices(img):
    v = {band: img.select(band) for band in BANDS}
    out = [
        img.normalizedDifference(["B8", "B4"]).rename("NDVI"),
        img.normalizedDifference(["B8", "B3"]).rename("GNDVI"),
        img.expression("B8-B4", v).rename("DVI"),
        img.expression("B8-B3", v).rename("GDVI"),
        img.expression("B8/(B3+0.0001)", v).rename("GRVI"),
        img.expression("B8/(B4+0.0001)", v).rename("SR"),
        img.expression("2.5*((B8-B4)/(B8+6*B4-7.5*B2+1+0.0001))", v).rename("EVI"),
        img.expression("((B5-B4)-0.2*(B5-B3))*(B5/(B4+0.0001))", v).rename("MCARI"),
        img.expression("1.5*(B8-B4)/(B8+B4+0.5)", v).rename("SAVI"),
        img.expression("(B8-B11)/(B8+B11)", v).rename("NDMI"),
        img.expression("(B8-B11)/(B8+B11)", v).rename("NDWI"),
        img.expression("B11/(B8+0.0001)", v).rename("MSI"),
        img.expression("-0.38*B3-0.71*B2+0.2*B4-0.56*B8", v).rename("Crop_band"),
        img.expression("0.09*B2+0.27*B3-0.71*B4-0.65*B8", v).rename("Soil_band"),
        img.expression("0.3037*B2+0.2793*B3+0.4743*B4+0.5585*B8+0.5082*B11+0.1863*B12", v).rename(
            "TCT_brightness"
        ),
        img.expression("-0.2848*B2-0.2435*B3-0.5436*B4+0.7243*B8+0.0840*B11-0.1800*B12", v).rename(
            "TCT_greenness"
        ),
        img.expression("0.1509*B2+0.1973*B3+0.3279*B4+0.3406*B8-0.7112*B11-0.4572*B12", v).rename(
            "TCT_wetness"
        ),
    ]
    return img.addBands(out).float()


def safe_num(d, k):
    v = ee.Dictionary(d).get(k)
    return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(v, None), 0, v))


def score_img(img, aoi):
    stddev = ee.Dictionary(
        img.select(INDEX_BANDS).reduceRegion(
            reducer=ee.Reducer.stdDev(),
            geometry=aoi,
            scale=20,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    count = ee.Dictionary(
        img.select("B8").reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=aoi,
            scale=20,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    score = ee.Number(0)
    for band in INDEX_BANDS:
        score = score.add(safe_num(stddev, band).abs())
    return (
        img.set("score", score)
        .set("valid_pixels", safe_num(count, "B8"))
        .set("date", ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"))
    )


def pca(img, bands, aoi, scale):
    image = img.select(bands)
    means = ee.Dictionary(
        image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=scale,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    centered = image.subtract(ee.Image.constant([safe_num(means, x) for x in bands]).rename(bands))
    arr = centered.toArray()
    cov = arr.reduceRegion(
        reducer=ee.Reducer.centeredCovariance(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e8,
        bestEffort=True,
        tileScale=4,
    )
    eig = ee.Array(cov.get("array")).eigen()
    vals = eig.slice(1, 0, 1)
    vecs = eig.slice(1, 1)
    pcs = ee.Image(vecs).matrixMultiply(arr.toArray(1))
    names = ["PC" + str(i + 1) for i in range(len(bands))]
    sd = ee.Image(vals.sqrt()).arrayProject([0]).arrayFlatten([["SD" + str(i + 1) for i in range(len(bands))]])
    return pcs.arrayProject([0]).arrayFlatten([names]).divide(sd).float()


def z(img, band, aoi):
    values = ee.Dictionary(
        img.select(band).reduceRegion(
            reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True),
            geometry=aoi,
            scale=20,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    mean = safe_num(values, band + "_mean")
    stddev = safe_num(values, band + "_stdDev").max(0.0001)
    return img.select(band).subtract(mean).divide(stddev).abs().rename("Z_" + band)


def local_deficit_z(img, band, radius=60):
    kernel = ee.Kernel.circle(radius=radius, units="meters")
    band_img = img.select(band)
    local_mean = band_img.reduceNeighborhood(ee.Reducer.mean(), kernel)
    local_std = band_img.reduceNeighborhood(ee.Reducer.stdDev(), kernel).max(ee.Image.constant(0.0001))
    deficit = local_mean.subtract(band_img).divide(local_std).max(ee.Image.constant(0))
    return deficit.rename("deficit")


def vegetation_deficit(img):
    deficits = [
        local_deficit_z(img, "NDVI"),
        local_deficit_z(img, "GNDVI"),
        local_deficit_z(img, "SAVI"),
        local_deficit_z(img, "TCT_greenness"),
    ]
    return ee.ImageCollection(deficits).mean().rename("Vegetation_deficit")


def anomalies(img, aoi):
    zs = [z(img, band, aoi) for band in ["NDVI", "GNDVI", "Crop_band", "Soil_band", "NDMI", "TCT_greenness"]]
    anomaly = ee.ImageCollection(zs).sum().rename("Anomaly_score")
    local = anomaly.subtract(anomaly.focal_mean(radius=60, units="meters")).rename("Local_contrast")
    edges = ee.Algorithms.CannyEdgeDetector(local, 0.7, 1).rename("Edges")
    return anomaly.addBands(local).addBands(edges).addBands(vegetation_deficit(img)).float()


def tile(img, vis):
    return ee.Image(img).getMapId(vis)["tile_fetcher"].url_format


def add_tile(layer_dict, name, img, vis):
    layer_dict[name] = tile(img, vis)


def add_layer(m, url, name, show=False, opacity=1.0):
    folium.raster_layers.TileLayer(
        tiles=url,
        attr="Google Earth Engine",
        name=name,
        overlay=True,
        control=True,
        show=show,
        opacity=opacity,
    ).add_to(m)


def run_analysis(project, start, end, cloud, topn, mode, export, folder, geojson_geometry):
    init_ee(project)
    aoi = geom(geojson_geometry)
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(str(start), str(end))
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud))
        .map(mask_s2)
        .map(add_indices)
    )
    total = col.size().getInfo()
    if total == 0:
        raise ValueError("Nessuna immagine trovata con questi parametri.")

    ranked = col.map(lambda x: score_img(x, aoi)).filter(ee.Filter.gt("valid_pixels", 10)).sort("score", False)
    valid_count = ranked.size().getInfo()
    if valid_count == 0:
        raise ValueError("Nessuna immagine con pixel validi dopo la maschera. Aumenta l'area o la soglia nuvole.")

    table_count = min(50, valid_count)
    ranked_limited = ranked.limit(table_count)
    df = pd.DataFrame(
        {
            "date": ranked_limited.aggregate_array("date").getInfo(),
            "cloud": ranked_limited.aggregate_array("CLOUDY_PIXEL_PERCENTAGE").getInfo(),
            "valid_pixels": ranked_limited.aggregate_array("valid_pixels").getInfo(),
            "score": ranked_limited.aggregate_array("score").getInfo(),
            "id": ranked_limited.aggregate_array("system:index").getInfo(),
        }
    )

    best = ee.Image(ranked.first()).clip(aoi)
    top = ee.ImageCollection(ranked.limit(int(topn)))
    base = top.median().clip(aoi) if mode == "Mediana migliori date" else best
    pcs = pca(base, PCA_BANDS, aoi, 20).select(["PC1", "PC2", "PC3", "PC4", "PC5", "PC6"])
    an = anomalies(base, aoi)
    out = (
        base.select(
            [
                "B2",
                "B3",
                "B4",
                "B8",
                "B11",
                "B12",
                "NDVI",
                "GNDVI",
                "DVI",
                "GDVI",
                "GRVI",
                "SR",
                "EVI",
                "MCARI",
                "SAVI",
                "NDMI",
                "NDWI",
                "MSI",
                "Crop_band",
                "Soil_band",
                "TCT_brightness",
                "TCT_greenness",
                "TCT_wetness",
            ]
        )
        .addBands(pcs)
        .addBands(an)
        .clip(aoi)
        .float()
    )

    layers = {}
    add_tile(layers, "RGB 4-3-2", base, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35})
    add_tile(layers, "False color 8-4-3", base, {"bands": ["B8", "B4", "B3"], "min": 0.02, "max": 0.45})
    add_tile(layers, "Healthy vegetation 8-11-2", base, {"bands": ["B8", "B11", "B2"], "min": 0.02, "max": 0.45})
    add_tile(layers, "NDVI", base.select("NDVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "GNDVI", base.select("GNDVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "DVI", base.select("DVI"), {"min": -0.2, "max": 0.6, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "GDVI", base.select("GDVI"), {"min": -0.2, "max": 0.6, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "GRVI", base.select("GRVI"), {"min": 0, "max": 8, "palette": ["542788", "f7f7f7", "1a9850"]})
    add_tile(layers, "Simple ratio", base.select("SR"), {"min": 0, "max": 8, "palette": ["542788", "f7f7f7", "1a9850"]})
    add_tile(layers, "EVI", base.select("EVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "MCARI", base.select("MCARI"), {"min": -0.2, "max": 0.4, "palette": ["2166ac", "f7f7f7", "b2182b"]})
    add_tile(layers, "SAVI", base.select("SAVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "NDMI", base.select("NDMI"), {"min": -0.6, "max": 0.6, "palette": ["8c510a", "f6e8c3", "01665e"]})
    add_tile(layers, "NDWI", base.select("NDWI"), {"min": -0.6, "max": 0.6, "palette": ["8c510a", "f6e8c3", "01665e"]})
    add_tile(layers, "MSI", base.select("MSI"), {"min": 0.4, "max": 2.5, "palette": ["01665e", "f6e8c3", "8c510a"]})
    add_tile(layers, "Crop band", base.select("Crop_band"), {"min": -0.9, "max": 0.1, "palette": ["542788", "f7f7f7", "b35806"]})
    add_tile(layers, "Soil band", base.select("Soil_band"), {"min": -1.0, "max": 0.2, "palette": ["2166ac", "f7f7f7", "b2182b"]})
    add_tile(layers, "TCT brightness", base.select("TCT_brightness"), {"min": -0.2, "max": 0.8, "palette": ["000004", "f89540", "fcfdbf"]})
    add_tile(layers, "TCT greenness", base.select("TCT_greenness"), {"min": -0.3, "max": 0.5, "palette": ["542788", "f7f7f7", "1a9850"]})
    add_tile(layers, "TCT wetness", base.select("TCT_wetness"), {"min": -0.4, "max": 0.4, "palette": ["8c510a", "f6e8c3", "01665e"]})
    add_tile(
        layers,
        "TCT RGB",
        base,
        {"bands": ["TCT_brightness", "TCT_greenness", "TCT_wetness"], "min": [-0.2, -0.3, -0.4], "max": [0.8, 0.5, 0.4]},
    )
    add_tile(layers, "PCA PC1-PC2-PC3", pcs, {"bands": ["PC1", "PC2", "PC3"], "min": -2, "max": 2})
    add_tile(layers, "PCA PC2-PC3-PC4", pcs, {"bands": ["PC2", "PC3", "PC4"], "min": -2, "max": 2})
    add_tile(layers, "Anomaly score", an.select("Anomaly_score"), {"min": 0, "max": 10, "palette": ["000000", "ffff00", "ff0000"]})
    add_tile(layers, "Local contrast", an.select("Local_contrast"), {"min": -2, "max": 2, "palette": ["0000ff", "ffffff", "ff0000"]})
    add_tile(
        layers,
        "Possibili strutture - erba bassa",
        an.select("Vegetation_deficit"),
        {"min": 0, "max": 2.5, "palette": ["ffffff", "ffd166", "ef476f", "6a040f"]},
    )
    add_tile(layers, "Edges", an.select("Edges"), {"min": 0, "max": 1, "palette": ["000000", "00ffff"]})

    try:
        download = out.getDownloadURL(
            {"name": "s2_cropmarks", "region": aoi, "scale": 10, "filePerBand": False, "format": "GEO_TIFF"}
        )
    except Exception:
        download = None

    task_id = None
    if export:
        task = ee.batch.Export.image.toDrive(
            image=out,
            description="s2_cropmarks_export",
            folder=folder,
            region=aoi,
            scale=10,
            maxPixels=1e13,
            fileFormat="GeoTIFF",
        )
        task.start()
        task_id = task.id

    return {
        "df": df,
        "layers": layers,
        "download": download,
        "task_id": task_id,
        "center": center(geojson_geometry),
        "geometry": geojson_geometry,
        "params": {"start": str(start), "end": str(end), "cloud": cloud, "topn": topn, "mode": mode},
    }
