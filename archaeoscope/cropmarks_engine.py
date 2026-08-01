import math
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

# Independent, broadly comparable signals used only to rank acquisition dates.
# The divisors represent a useful spatial-contrast scale for each band and keep
# ratio-like indices from dominating linear reflectance transforms.
RANK_FEATURES = (
    ("NDVI", 0.15, 1.0),
    ("GNDVI", 0.15, 0.8),
    ("SAVI", 0.15, 1.0),
    ("NDMI", 0.12, 0.8),
    ("Crop_band", 0.10, 0.8),
    ("Soil_band", 0.10, 0.8),
    ("TCT_greenness", 0.12, 0.8),
)
RANK_BANDS = [item[0] for item in RANK_FEATURES]
TIMESERIES_BANDS = ["NDVI", "GNDVI", "SAVI", "NDMI", "TCT_greenness"]
DEFAULT_PIXEL_CLOUD = 40
DEFAULT_PERSISTENCE_THRESHOLD = 1.35
DEFAULT_LOCAL_RADIUS = 60


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


def geometry_bounds(g):
    pts = []
    flat_coords(g.get("coordinates", []), pts)
    if not pts:
        return None
    lons = [float(point[0]) for point in pts]
    lats = [float(point[1]) for point in pts]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def square_aoi(lat, lon, radius_m=750):
    lat = float(lat)
    lon = float(lon)
    radius_m = max(50.0, float(radius_m))
    lat_delta = radius_m / 111_320.0
    lon_scale = max(0.1, abs(math.cos(math.radians(lat))))
    lon_delta = radius_m / (111_320.0 * lon_scale)
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - lon_delta, lat - lat_delta],
                [lon + lon_delta, lat - lat_delta],
                [lon + lon_delta, lat + lat_delta],
                [lon - lon_delta, lat + lat_delta],
                [lon - lon_delta, lat - lat_delta],
            ]
        ],
    }


def geom(g):
    if g["type"] == "Polygon":
        return ee.Geometry.Polygon(g["coordinates"])
    if g["type"] == "MultiPolygon":
        return ee.Geometry.MultiPolygon(g["coordinates"])
    raise ValueError("Disegna un poligono o un rettangolo.")


def mask_s2(img, max_pixel_cloud=DEFAULT_PIXEL_CLOUD):
    scl = img.select("SCL")
    cloud_probability = ee.Image(img.get("cloud_probability_image")).select("probability")
    edge_mask = img.select("B8A").mask().updateMask(img.select("B9").mask())
    mask = (
        scl.neq(0)
        .And(scl.neq(1))
        .And(scl.neq(3))
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
        .And(cloud_probability.lt(float(max_pixel_cloud)))
        .And(edge_mask)
    )
    scaled = img.select(BANDS).divide(10000)
    return img.addBands(scaled, None, True).addBands(cloud_probability.rename("cloud_probability")).updateMask(mask).copyProperties(
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
        img.expression("(B3-B8)/(B3+B8+0.0001)", v).rename("NDWI"),
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
    reducer = ee.Reducer.mean().combine(
        reducer2=ee.Reducer.stdDev(), sharedInputs=True
    ).combine(
        reducer2=ee.Reducer.count(), sharedInputs=True
    )
    stats = ee.Dictionary(
        img.select(RANK_BANDS + ["cloud_probability"]).reduceRegion(
            reducer=reducer,
            geometry=aoi,
            scale=20,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    score = ee.Number(0)
    total_weight = sum(item[2] for item in RANK_FEATURES)
    for band, useful_scale, weight in RANK_FEATURES:
        normalized = safe_num(stats, band + "_stdDev").divide(useful_scale).min(3)
        score = score.add(normalized.multiply(weight))
    score = score.divide(total_weight)
    ranked = (
        img.set("score", score)
        .set("valid_pixels", safe_num(stats, "NDVI_count"))
        .set("pixel_cloud_mean", safe_num(stats, "cloud_probability_mean"))
        .set("date", ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"))
    )
    for band in TIMESERIES_BANDS:
        ranked = ranked.set("mean_" + band, safe_num(stats, band + "_mean"))
    return ranked


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


def local_signed_z(img, band, radius=DEFAULT_LOCAL_RADIUS):
    kernel = ee.Kernel.circle(radius=radius, units="meters")
    band_img = img.select(band)
    local_mean = band_img.reduceNeighborhood(ee.Reducer.mean(), kernel)
    local_std = band_img.reduceNeighborhood(ee.Reducer.stdDev(), kernel).max(ee.Image.constant(0.0001))
    return band_img.subtract(local_mean).divide(local_std).rename("local_z")


def local_deficit_z(img, band, radius=DEFAULT_LOCAL_RADIUS):
    return local_signed_z(img, band, radius).multiply(-1).max(ee.Image.constant(0)).rename("deficit")


def local_excess_z(img, band, radius=DEFAULT_LOCAL_RADIUS):
    return local_signed_z(img, band, radius).max(ee.Image.constant(0)).rename("excess")


def vegetation_deficit(img):
    deficits = [
        local_deficit_z(img, "NDVI"),
        local_deficit_z(img, "GNDVI"),
        local_deficit_z(img, "SAVI"),
        local_deficit_z(img, "TCT_greenness"),
    ]
    return ee.ImageCollection(deficits).mean().rename("Vegetation_deficit")


def vegetation_excess(img):
    excesses = [
        local_excess_z(img, "NDVI"),
        local_excess_z(img, "GNDVI"),
        local_excess_z(img, "SAVI"),
        local_excess_z(img, "TCT_greenness"),
    ]
    return ee.ImageCollection(excesses).mean().rename("Vegetation_excess")


def temporal_persistence(images, threshold=DEFAULT_PERSISTENCE_THRESHOLD):
    threshold = float(threshold)

    def classify(image):
        image = ee.Image(image)
        deficit = vegetation_deficit(image)
        excess = vegetation_excess(image)
        return (
            deficit.gte(threshold).rename("Persistent_deficit")
            .addBands(excess.gte(threshold).rename("Persistent_excess"))
            .addBands(deficit.max(excess).gte(threshold).rename("Persistent_any"))
            .float()
        )

    return ee.ImageCollection(images.map(classify)).mean().float()


def anomalies(img, aoi):
    zs = [z(img, band, aoi) for band in ["NDVI", "GNDVI", "Crop_band", "Soil_band", "NDMI", "TCT_greenness"]]
    anomaly = ee.ImageCollection(zs).sum().rename("Anomaly_score")
    local = anomaly.subtract(anomaly.focal_mean(radius=60, units="meters")).rename("Local_contrast")
    edges = ee.Algorithms.CannyEdgeDetector(local, 0.7, 1).rename("Edges")
    return (
        anomaly.addBands(local)
        .addBands(edges)
        .addBands(vegetation_deficit(img))
        .addBands(vegetation_excess(img))
        .float()
    )


def tile(img, vis):
    return ee.Image(img).getMapId(vis)["tile_fetcher"].url_format


def add_tile(layer_dict, name, img, vis):
    layer_dict[name] = tile(img, vis)


def add_layer_spec(layer_dict, name, img, vis, group):
    layer_dict[name] = {"image": ee.Image(img), "vis": vis, "group": group}


def layer_url(result, name):
    spec = result["layer_specs"][name]
    return tile(spec["image"], spec["vis"])


def prepare_download(result):
    return ee.Image(result["download_image"]).getDownloadURL(
        {
            "name": "s2_cropmarks",
            "region": result["download_region"],
            "scale": 10,
            "filePerBand": False,
            "format": "GEO_TIFF",
        }
    )


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


def run_analysis(
    project,
    start,
    end,
    cloud,
    topn,
    mode,
    export,
    folder,
    geojson_geometry,
    pixel_cloud=DEFAULT_PIXEL_CLOUD,
    persistence_threshold=DEFAULT_PERSISTENCE_THRESHOLD,
):
    init_ee(project)
    aoi = geom(geojson_geometry)
    criteria = ee.Filter.And(
        ee.Filter.bounds(aoi),
        ee.Filter.date(str(start), str(end)),
    )
    source = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filter(criteria)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud))
    )
    cloud_probability = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY").filter(criteria)
    joined = ee.Join.saveFirst("cloud_probability_image").apply(
        primary=source,
        secondary=cloud_probability,
        condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
    )
    granules = (
        ee.ImageCollection(joined)
        .map(lambda image: mask_s2(image, pixel_cloud))
        .map(add_indices)
    )
    total = granules.size().getInfo()
    if total == 0:
        raise ValueError("Nessuna immagine trovata con questi parametri.")

    ranked = (
        granules.map(lambda image: score_img(image, aoi))
        .filter(ee.Filter.gt("valid_pixels", 10))
        .sort("score", False)
        .distinct("date")
        .sort("score", False)
    )
    valid_count = ranked.size().getInfo()
    if valid_count == 0:
        raise ValueError("Nessuna immagine con pixel validi dopo la maschera. Aumenta l'area o la soglia nuvole.")

    table_count = min(50, valid_count)
    ranked_limited = ranked.limit(table_count)
    selectors = [
        "date",
        "CLOUDY_PIXEL_PERCENTAGE",
        "pixel_cloud_mean",
        "valid_pixels",
        "score",
        "system:index",
    ] + ["mean_" + band for band in TIMESERIES_BANDS]
    rows = ranked_limited.reduceColumns(
        reducer=ee.Reducer.toList(len(selectors)),
        selectors=selectors,
    ).get("list").getInfo()
    df = pd.DataFrame(
        rows,
        columns=[
            "date",
            "cloud",
            "pixel_cloud_mean",
            "valid_pixels",
            "score",
            "id",
        ] + [band.lower() + "_mean" for band in TIMESERIES_BANDS],
    )
    df["selected_for_composite"] = False
    df.loc[df.index[: min(int(topn), len(df))], "selected_for_composite"] = True

    best = ee.Image(ranked.first()).clip(aoi)
    top = ee.ImageCollection(ranked.limit(int(topn)))
    base = top.median().clip(aoi) if mode == "Mediana migliori date" else best
    pcs = pca(base, PCA_BANDS, aoi, 20).select(["PC1", "PC2", "PC3", "PC4", "PC5", "PC6"])
    an = anomalies(base, aoi)
    persistence = temporal_persistence(top, persistence_threshold).clip(aoi)
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
        .addBands(persistence)
        .clip(aoi)
        .float()
    )

    layer_specs = {}
    add_layer_spec(layer_specs, "RGB 4-3-2", base, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35}, "Immagini")
    add_layer_spec(layer_specs, "False color 8-4-3", base, {"bands": ["B8", "B4", "B3"], "min": 0.02, "max": 0.45}, "Immagini")
    add_layer_spec(layer_specs, "Healthy vegetation 8-11-2", base, {"bands": ["B8", "B11", "B2"], "min": 0.02, "max": 0.45}, "Immagini")
    add_layer_spec(layer_specs, "NDVI", base.select("NDVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "GNDVI", base.select("GNDVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "DVI", base.select("DVI"), {"min": -0.2, "max": 0.6, "palette": ["313695", "ffffbf", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "GDVI", base.select("GDVI"), {"min": -0.2, "max": 0.6, "palette": ["313695", "ffffbf", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "GRVI", base.select("GRVI"), {"min": 0, "max": 8, "palette": ["542788", "f7f7f7", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "Simple ratio", base.select("SR"), {"min": 0, "max": 8, "palette": ["542788", "f7f7f7", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "EVI", base.select("EVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "MCARI", base.select("MCARI"), {"min": -0.2, "max": 0.4, "palette": ["2166ac", "f7f7f7", "b2182b"]}, "Vegetazione")
    add_layer_spec(layer_specs, "SAVI", base.select("SAVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]}, "Vegetazione")
    add_layer_spec(layer_specs, "NDMI", base.select("NDMI"), {"min": -0.6, "max": 0.6, "palette": ["8c510a", "f6e8c3", "01665e"]}, "Umidita e suolo")
    add_layer_spec(layer_specs, "NDWI", base.select("NDWI"), {"min": -0.6, "max": 0.6, "palette": ["8c510a", "f6e8c3", "01665e"]}, "Umidita e suolo")
    add_layer_spec(layer_specs, "MSI", base.select("MSI"), {"min": 0.4, "max": 2.5, "palette": ["01665e", "f6e8c3", "8c510a"]}, "Umidita e suolo")
    add_layer_spec(layer_specs, "Crop band", base.select("Crop_band"), {"min": -0.9, "max": 0.1, "palette": ["542788", "f7f7f7", "b35806"]}, "Umidita e suolo")
    add_layer_spec(layer_specs, "Soil band", base.select("Soil_band"), {"min": -1.0, "max": 0.2, "palette": ["2166ac", "f7f7f7", "b2182b"]}, "Umidita e suolo")
    add_layer_spec(layer_specs, "TCT brightness", base.select("TCT_brightness"), {"min": -0.2, "max": 0.8, "palette": ["000004", "f89540", "fcfdbf"]}, "Tasseled Cap")
    add_layer_spec(layer_specs, "TCT greenness", base.select("TCT_greenness"), {"min": -0.3, "max": 0.5, "palette": ["542788", "f7f7f7", "1a9850"]}, "Tasseled Cap")
    add_layer_spec(layer_specs, "TCT wetness", base.select("TCT_wetness"), {"min": -0.4, "max": 0.4, "palette": ["8c510a", "f6e8c3", "01665e"]}, "Tasseled Cap")
    add_layer_spec(
        layer_specs,
        "TCT RGB",
        base,
        {"bands": ["TCT_brightness", "TCT_greenness", "TCT_wetness"], "min": [-0.2, -0.3, -0.4], "max": [0.8, 0.5, 0.4]},
        "Tasseled Cap",
    )
    add_layer_spec(layer_specs, "PCA PC1-PC2-PC3", pcs, {"bands": ["PC1", "PC2", "PC3"], "min": -2, "max": 2}, "PCA")
    add_layer_spec(layer_specs, "PCA PC2-PC3-PC4", pcs, {"bands": ["PC2", "PC3", "PC4"], "min": -2, "max": 2}, "PCA")
    add_layer_spec(layer_specs, "Anomaly score", an.select("Anomaly_score"), {"min": 0, "max": 10, "palette": ["000000", "ffff00", "ff0000"]}, "Anomalie")
    add_layer_spec(layer_specs, "Local contrast", an.select("Local_contrast"), {"min": -2, "max": 2, "palette": ["0000ff", "ffffff", "ff0000"]}, "Anomalie")
    add_layer_spec(
        layer_specs,
        "Vegetazione in deficit - possibili muri",
        an.select("Vegetation_deficit"),
        {"min": 0, "max": 2.5, "palette": ["ffffff", "ffd166", "ef476f", "6a040f"]},
        "Anomalie",
    )
    add_layer_spec(
        layer_specs,
        "Vegetazione in eccesso - possibili fossati",
        an.select("Vegetation_excess"),
        {"min": 0, "max": 2.5, "palette": ["ffffff", "bde0fe", "219ebc", "023047"]},
        "Anomalie",
    )
    add_layer_spec(layer_specs, "Persistenza complessiva", persistence.select("Persistent_any"), {"min": 0, "max": 1, "palette": ["000000", "fee08b", "d73027"]}, "Persistenza temporale")
    add_layer_spec(layer_specs, "Persistenza deficit", persistence.select("Persistent_deficit"), {"min": 0, "max": 1, "palette": ["000000", "ffd166", "9d0208"]}, "Persistenza temporale")
    add_layer_spec(layer_specs, "Persistenza eccesso", persistence.select("Persistent_excess"), {"min": 0, "max": 1, "palette": ["000000", "90e0ef", "0077b6"]}, "Persistenza temporale")
    add_layer_spec(layer_specs, "Edges", an.select("Edges"), {"min": 0, "max": 1, "palette": ["000000", "00ffff"]}, "Anomalie")

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
        "layer_specs": layer_specs,
        "layer_urls": {},
        "download": None,
        "download_image": out,
        "download_region": aoi,
        "task_id": task_id,
        "center": center(geojson_geometry),
        "geometry": geojson_geometry,
        "params": {
            "start": str(start),
            "end": str(end),
            "cloud": cloud,
            "pixel_cloud": pixel_cloud,
            "topn": topn,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
        },
        "scene_count": total,
        "valid_scene_count": valid_count,
    }
