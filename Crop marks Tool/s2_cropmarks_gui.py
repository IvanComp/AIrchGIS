import ee
import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

st.set_page_config(page_title="Sentinel-2 Crop Marks", layout="wide")

BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
INDEX_BANDS = ["NDVI", "GNDVI", "SAVI", "SR", "Crop_band", "Soil_band", "NDMI", "MSI", "TCT_brightness", "TCT_greenness", "TCT_wetness"]
PCA_BANDS = ["B2", "B3", "B4", "B8", "B11", "B12", "NDVI", "GNDVI", "SAVI", "SR", "Crop_band", "Soil_band", "NDMI", "MSI", "TCT_brightness", "TCT_greenness", "TCT_wetness"]

for k, v in {"analysis_result": None, "analysis_geometry": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def init_ee(project):
    if project.strip():
        ee.Initialize(project=project.strip())
    else:
        ee.Initialize()


def flat_coords(x, out):
    if isinstance(x[0], (int, float)):
        out.append(x)
    else:
        for y in x:
            flat_coords(y, out)


def center(g):
    pts = []
    flat_coords(g["coordinates"], pts)
    return [sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)]


def geom(g):
    if g["type"] == "Polygon":
        return ee.Geometry.Polygon(g["coordinates"])
    if g["type"] == "MultiPolygon":
        return ee.Geometry.MultiPolygon(g["coordinates"])
    raise ValueError("Disegna un poligono o un rettangolo.")


def mask_s2(img):
    scl = img.select("SCL")
    m = scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
    scaled = img.select(BANDS).divide(10000)
    return img.addBands(scaled, None, True).updateMask(m).copyProperties(img, ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE", "system:index"])


def add_indices(img):
    v = {b: img.select(b) for b in BANDS}
    out = [
        img.normalizedDifference(["B8", "B4"]).rename("NDVI"),
        img.normalizedDifference(["B8", "B3"]).rename("GNDVI"),
        img.expression("B8-B4", v).rename("DVI"),
        img.expression("B8-B3", v).rename("GDVI"),
        img.expression("B8/B3", v).rename("GRVI"),
        img.expression("B8/B4", v).rename("SR"),
        img.expression("2.5*((B8-B4)/(B8+6*B4-7.5*B2+1))", v).rename("EVI"),
        img.expression("((B5-B4)-0.2*(B5-B3))*(B5/B4)", v).rename("MCARI"),
        img.expression("1.5*(B8-B4)/(B8+B4+0.5)", v).rename("SAVI"),
        img.expression("(B8-B11)/(B8+B11)", v).rename("NDMI"),
        img.expression("(B8-B11)/(B8+B11)", v).rename("NDWI"),
        img.expression("B11/B8", v).rename("MSI"),
        img.expression("-0.38*B3-0.71*B2+0.2*B4-0.56*B8", v).rename("Crop_band"),
        img.expression("0.09*B2+0.27*B3-0.71*B4-0.65*B8", v).rename("Soil_band"),
        img.expression("0.3037*B2+0.2793*B3+0.4743*B4+0.5585*B8+0.5082*B11+0.1863*B12", v).rename("TCT_brightness"),
        img.expression("-0.2848*B2-0.2435*B3-0.5436*B4+0.7243*B8+0.0840*B11-0.1800*B12", v).rename("TCT_greenness"),
        img.expression("0.1509*B2+0.1973*B3+0.3279*B4+0.3406*B8-0.7112*B11-0.4572*B12", v).rename("TCT_wetness")
    ]
    return img.addBands(out).float()


def safe_num(d, k):
    v = ee.Dictionary(d).get(k)
    return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(v, None), 0, v))


def score_img(img, aoi):
    d = ee.Dictionary(img.select(INDEX_BANDS).reduceRegion(reducer=ee.Reducer.stdDev(), geometry=aoi, scale=20, maxPixels=1e8, bestEffort=True, tileScale=4))
    c = ee.Dictionary(img.select("B8").reduceRegion(reducer=ee.Reducer.count(), geometry=aoi, scale=20, maxPixels=1e8, bestEffort=True, tileScale=4))
    s = ee.Number(0)
    for b in INDEX_BANDS:
        s = s.add(safe_num(d, b).abs())
    return img.set("score", s).set("valid_pixels", safe_num(c, "B8")).set("date", ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"))


def pca(img, b, aoi, scale):
    im = img.select(b)
    m = ee.Dictionary(im.reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, scale=scale, maxPixels=1e8, bestEffort=True, tileScale=4))
    c = im.subtract(ee.Image.constant([safe_num(m, x) for x in b]).rename(b))
    arr = c.toArray()
    cov = arr.reduceRegion(reducer=ee.Reducer.centeredCovariance(), geometry=aoi, scale=scale, maxPixels=1e8, bestEffort=True, tileScale=4)
    eig = ee.Array(cov.get("array")).eigen()
    vals = eig.slice(1, 0, 1)
    vecs = eig.slice(1, 1)
    pcs = ee.Image(vecs).matrixMultiply(arr.toArray(1))
    names = ["PC" + str(i + 1) for i in range(len(b))]
    sd = ee.Image(vals.sqrt()).arrayProject([0]).arrayFlatten([["SD" + str(i + 1) for i in range(len(b))]])
    return pcs.arrayProject([0]).arrayFlatten([names]).divide(sd).float()


def z(img, b, aoi):
    r = ee.Dictionary(img.select(b).reduceRegion(reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True), geometry=aoi, scale=20, maxPixels=1e8, bestEffort=True, tileScale=4))
    m = safe_num(r, b + "_mean")
    s = safe_num(r, b + "_stdDev").max(0.0001)
    return img.select(b).subtract(m).divide(s).abs().rename("Z_" + b)


def anomalies(img, aoi):
    zs = [z(img, b, aoi) for b in ["NDVI", "GNDVI", "Crop_band", "Soil_band", "NDMI", "TCT_greenness"]]
    a = ee.ImageCollection(zs).sum().rename("Anomaly_score")
    l = a.subtract(a.focal_mean(radius=60, units="meters")).rename("Local_contrast")
    e = ee.Algorithms.CannyEdgeDetector(l, 0.7, 1).rename("Edges")
    return a.addBands(l).addBands(e).float()


def tile(img, vis):
    return ee.Image(img).getMapId(vis)["tile_fetcher"].url_format


def add_tile(layer_dict, name, img, vis):
    layer_dict[name] = tile(img, vis)


def add_layer(m, url, name, show=False, opacity=1.0):
    folium.raster_layers.TileLayer(tiles=url, attr="Google Earth Engine", name=name, overlay=True, control=True, show=show, opacity=opacity).add_to(m)


def run_analysis(project, start, end, cloud, topn, mode, export, folder, g):
    init_ee(project)
    aoi = geom(g)
    col = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(aoi).filterDate(str(start), str(end)).filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud)).map(mask_s2).map(add_indices)
    n = col.size().getInfo()
    if n == 0:
        raise ValueError("Nessuna immagine trovata con questi parametri.")
    ranked = col.map(lambda x: score_img(x, aoi)).filter(ee.Filter.gt("valid_pixels", 10)).sort("score", False)
    nv = ranked.size().getInfo()
    if nv == 0:
        raise ValueError("Nessuna immagine con pixel validi dopo la maschera. Aumenta l'area o la soglia nuvole.")
    k = min(50, nv)
    df = pd.DataFrame({
        "date": ranked.limit(k).aggregate_array("date").getInfo(),
        "cloud": ranked.limit(k).aggregate_array("CLOUDY_PIXEL_PERCENTAGE").getInfo(),
        "valid_pixels": ranked.limit(k).aggregate_array("valid_pixels").getInfo(),
        "score": ranked.limit(k).aggregate_array("score").getInfo(),
        "id": ranked.limit(k).aggregate_array("system:index").getInfo()
    })
    best = ee.Image(ranked.first()).clip(aoi)
    top = ee.ImageCollection(ranked.limit(topn))
    base = top.median().clip(aoi) if mode == "Mediana migliori date" else best
    pcs = pca(base, PCA_BANDS, aoi, 20).select(["PC1", "PC2", "PC3", "PC4", "PC5", "PC6"])
    an = anomalies(base, aoi)
    out = base.select(["B2", "B3", "B4", "B8", "B11", "B12", "NDVI", "GNDVI", "SAVI", "SR", "Crop_band", "Soil_band", "NDMI", "MSI", "TCT_brightness", "TCT_greenness", "TCT_wetness"]).addBands(pcs).addBands(an).clip(aoi).float()
    layers = {}
    add_tile(layers, "RGB 4-3-2", base, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35})
    add_tile(layers, "False color 8-4-3", base, {"bands": ["B8", "B4", "B3"], "min": 0.02, "max": 0.45})
    add_tile(layers, "Healthy vegetation 8-11-2", base, {"bands": ["B8", "B11", "B2"], "min": 0.02, "max": 0.45})
    add_tile(layers, "NDVI", base.select("NDVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "GNDVI", base.select("GNDVI"), {"min": -0.2, "max": 0.8, "palette": ["313695", "ffffbf", "1a9850"]})
    add_tile(layers, "Crop band", base.select("Crop_band"), {"min": -0.9, "max": 0.1, "palette": ["542788", "f7f7f7", "b35806"]})
    add_tile(layers, "Soil band", base.select("Soil_band"), {"min": -1.0, "max": 0.2, "palette": ["2166ac", "f7f7f7", "b2182b"]})
    add_tile(layers, "NDMI", base.select("NDMI"), {"min": -0.6, "max": 0.6, "palette": ["8c510a", "f6e8c3", "01665e"]})
    add_tile(layers, "TCT RGB", base, {"bands": ["TCT_brightness", "TCT_greenness", "TCT_wetness"], "min": [-0.2, -0.3, -0.4], "max": [0.8, 0.5, 0.4]})
    add_tile(layers, "PCA PC1-PC2-PC3", pcs, {"bands": ["PC1", "PC2", "PC3"], "min": -2, "max": 2})
    add_tile(layers, "PCA PC2-PC3-PC4", pcs, {"bands": ["PC2", "PC3", "PC4"], "min": -2, "max": 2})
    add_tile(layers, "Anomaly score", an.select("Anomaly_score"), {"min": 0, "max": 10, "palette": ["000000", "ffff00", "ff0000"]})
    add_tile(layers, "Local contrast", an.select("Local_contrast"), {"min": -2, "max": 2, "palette": ["0000ff", "ffffff", "ff0000"]})
    add_tile(layers, "Edges", an.select("Edges"), {"min": 0, "max": 1, "palette": ["000000", "00ffff"]})
    try:
        download = out.getDownloadURL({"name": "s2_cropmarks", "region": aoi, "scale": 10, "filePerBand": False, "format": "GEO_TIFF"})
    except Exception:
        download = None
    task_id = None
    if export:
        task = ee.batch.Export.image.toDrive(image=out, description="s2_cropmarks_export", folder=folder, region=aoi, scale=10, maxPixels=1e13, fileFormat="GeoTIFF")
        task.start()
        task_id = task.id
    return {"df": df, "layers": layers, "download": download, "task_id": task_id, "center": center(g), "geometry": g, "params": {"start": str(start), "end": str(end), "cloud": cloud, "topn": topn, "mode": mode}}


st.title("Sentinel-2 crop marks enhancement")
st.write("Disegna un poligono o un rettangolo sulla mappa, imposta periodo e nuvole, poi avvia l'analisi.")

with st.sidebar:
    project = st.text_input("Google Earth Engine project", "")
    start = st.date_input("Da", pd.to_datetime("2016-01-01"))
    end = st.date_input("A", pd.to_datetime("2019-12-31"))
    cloud = st.slider("Cloud cover massimo metadata (%)", 0, 100, 10)
    topn = st.slider("Date migliori da combinare", 1, 20, 5)
    mode = st.selectbox("Immagine base", ["Migliore singola data", "Mediana migliori date"])
    export = st.checkbox("Esporta GeoTIFF su Google Drive", False)
    folder = st.text_input("Cartella Drive", "S2_cropmarks")
    run = st.button("Avvia analisi", type="primary")
    reset = st.button("Reset analisi")

if reset:
    st.session_state.analysis_result = None
    st.session_state.analysis_geometry = None

m = folium.Map(location=[41.5, 15.5], zoom_start=9, tiles="OpenStreetMap")
Draw(export=False, draw_options={"polyline": False, "polygon": True, "rectangle": True, "circle": False, "marker": False, "circlemarker": False}, edit_options={"edit": True}).add_to(m)
draw = st_folium(m, width=1200, height=520, key="draw_map", returned_objects=["all_drawings"])

if run:
    drawings = draw.get("all_drawings") or []
    if drawings:
        st.session_state.analysis_geometry = drawings[-1]["geometry"]
    if not st.session_state.analysis_geometry:
        st.error("Disegna prima un poligono o un rettangolo sulla mappa.")
        st.stop()
    with st.spinner("Analisi in corso. Non interagire con la pagina finche non appare il risultato."):
        try:
            st.session_state.analysis_result = run_analysis(project, start, end, cloud, topn, mode, export, folder, st.session_state.analysis_geometry)
        except Exception as e:
            st.session_state.analysis_result = None
            st.error(str(e))
            st.exception(e)

r = st.session_state.analysis_result
if r:
    st.subheader("Date migliori")
    st.dataframe(r["df"], width="stretch")
    st.info("La tabella ordina le date con maggiore contrasto spettrale. Lo score non e una probabilita archeologica.")
    st.subheader("Mappa dei layer generati")
    rm = folium.Map(location=r["center"], zoom_start=14, tiles="OpenStreetMap")
    folium.TileLayer("CartoDB positron", name="CartoDB Positron", control=True, show=False).add_to(rm)
    folium.TileLayer("Esri.WorldImagery", name="Esri World Imagery", attr="Esri", control=True, show=False).add_to(rm)
    folium.GeoJson(r["geometry"], name="AOI", style_function=lambda x: {"color": "yellow", "weight": 2, "fillOpacity": 0}).add_to(rm)
    for i, (name, url) in enumerate(r["layers"].items()):
        add_layer(rm, url, name, show=(name == "False color 8-4-3"))
    folium.LayerControl(collapsed=False).add_to(rm)
    st_folium(rm, width=1200, height=760, key="result_map", returned_objects=[])
    st.caption("Zoom, pan e layer control non rilanciano l'analisi. Se Streamlit ricarica la pagina, i risultati restano in sessione.")
    cols = st.columns(3)
    with cols[0]:
        if r["download"]:
            st.link_button("Scarica GeoTIFF", r["download"])
        else:
            st.warning("Download diretto non creato: area troppo grande. Usa export su Drive.")
    with cols[1]:
        if r["task_id"]:
            st.success("Export Drive avviato. Task ID: " + r["task_id"])
    with cols[2]:
        st.write("Layer utili: False color, Crop band, Soil band, TCT RGB, PCA, Local contrast.")
