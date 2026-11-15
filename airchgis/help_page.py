

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

import streamlit as st


VIEWS = [
    ("Hillshade", "Shaded relief lit by a low sun.", "A first look; change the light direction, because features parallel to the light disappear."),
    ("Multi-Hillshade", "Shaded relief from many light directions.", "When you do not know the direction of the features."),
    ("Slope", "Steepness of the ground.", "Banks, terraces, edges of mounds and ditches."),
    ("Sky-View Factor", "How much sky each point sees.", "Ditches, hollows and sunken roads (dark); works without a light direction."),
    ("Anisotropic Sky-View Factor", "Sky-view factor weighted towards one direction.", "A sky-view factor with a sense of relief, like a hillshade."),
    ("Positive Openness", "How open each point is upwards.", "Banks, walls and other raised micro-relief."),
    ("Negative Openness", "Openness computed on the inverted terrain.", "Hollows and enclosed depressions."),
    ("Simple Local Relief Model", "Removes the large landscape, keeps small bumps and hollows.", "Low earthworks on slopes or hills."),
    ("Multi-Scale Relief Model", "Local relief at several sizes in one image.", "Features of mixed sizes in the same area."),
    ("Multi-Scale Topographic Position", "Colour image of relief position at three scales.", "Overviews of the landscape and its forms."),
    ("Sky Illumination", "Shading under a diffuse, cloudy sky.", "Soft, realistic relief for figures."),
    ("Local Dominance", "How much each point rises above its surroundings.", "Low mounds and barrows on flat ground."),
    ("CRIM", "Colour relief image map combining slope and openness.", "Terrain forms with slope and relative position in one image."),
    ("e4MSTP (RGB)", "Enhanced multi-scale topographic position.", "Colour interpretation of terrain at several scales."),
    ("e3MSTP (RGB)", "Colour blend of several views.", "Comparing several relief descriptors in one colour view."),
]


SECTIONS = [
    ("overview", "Start with the terrain", """
        <p>AIrchGIS helps examine digital terrain models and LiDAR point clouds through relief views, map comparison and interactive 3D analysis. Relief calculations use <a href="https://github.com/EarthObservation/RVT_py" target="_blank" rel="noopener noreferrer">RVT_py</a>.</p>
        <div class="ag-workflow-grid">
          <a href="#ag-input"><span>01</span><h3>Load</h3><p>Upload a terrain file or open a bundled use case.</p></a>
          <a href="#ag-workflow"><span>02</span><h3>Inspect</h3><p>Compare relief methods, light directions and the satellite image.</p></a>
          <a href="#ag-export"><span>03</span><h3>Export</h3><p>Save numerical layers, the current 3D view or full terrain data.</p></a>
        </div>
        <p class="ag-note">Start with a bundled use case to follow the examples below. Screenshots use Colle San Mauro; the same controls work with uploaded terrain.</p>"""),
    ("input", "Load a terrain model", """
        <p>Use <strong>Upload</strong> for GeoTIFF, ASCII grid, ZIP archives of raster tiles or LAS/LAZ point clouds. Multiple files are supported, up to 4 GB per file.</p>
        {upload_image}
        <ul><li><strong>Rasters:</strong> coordinates and a coordinate system are needed to place the terrain on the map. Compatible tiles are joined; excluded inputs are reported.</li>
        <li><strong>Point clouds:</strong> ground-class points are used when available, then interpolated into a terrain model. Without a ground class, vegetation and buildings may remain in the result.</li>
        <li><strong>Geographic coordinates:</strong> the app converts degrees to a metric UTM grid for terrain calculations.</li></ul>
        <div class="ag-example"><span class="ag-example-label">Try it</span><h3>Open a use case</h3><p>Choose <strong>Colle San Mauro</strong> on the upload screen. The map opens with a hillshade already applied. Choose <strong>Home</strong> to return and try Montedoglio or Betterton.</p></div>"""),
    ("preprocessing", "Check the prepared terrain", """
        <p>In <strong>Visualization tools → Pre-processing</strong>, read the recorded steps before interpreting the terrain.</p>
        <ul><li>Check the coordinate system, cell size and elevation range.</li>
        <li>For point clouds, check ground classification, point density and the chosen interpolation. TIN is the default; IDW, mean-per-cell and lowest-point gridding are also available.</li>
        <li>Small interior gaps may be filled. Large missing areas and the exterior of the survey remain outside the surface.</li>
        <li>The artifact check measures banding and spikes. These can also produce apparent anomalies.</li></ul>
        <p><strong>Change the pre-processing</strong> reruns preparation with different settings and records the changes in the session script.</p>
        <div class="ag-example"><span class="ag-example-label">Resolution example</span><h3>A 5 m feature on two grids</h3><p>On a <strong>1 m grid</strong>, a feature 5 m wide spans about five cells. On a <strong>5 m grid</strong>, it spans only one cell. Enlarging the image or increasing contrast cannot recover its missing shape. Use <strong>Resolution check</strong> with the width you want to examine.</p></div>"""),
    ("map", "Read the map and its layers", """
        {map_image}
        <div class="ag-tool-grid">
          <div><h3>Layers</h3><p><strong>Place</strong>, <strong>Base map</strong> and <strong>Relief view</strong> have visibility switches and opacity sliders. Turning Base map off also turns Place off.</p></div>
          <div><h3>Visualization tools</h3><p>Prepare terrain, run the resolution check, choose relief methods or open the full RVT workspace. The panel-edge arrow hides or restores these controls.</p></div>
          <div><h3>Measurements</h3><p>The left controls provide zoom, full screen, distance measurement and coordinate/elevation queries.</p></div>
          <div><h3>Two different 3D views</h3><p>The map's <strong>3D</strong> toggle tilts the global basemap terrain. <strong>3D Analysis</strong> opens the terrain loaded into AIrchGIS.</p></div>
        </div>
        <div class="ag-example"><span class="ag-example-label">Try it</span><h3>Compare a landform with the satellite image</h3><ol><li>Keep <strong>Base map</strong> enabled.</li><li>Lower <strong>Relief view</strong> opacity from 100% toward 0%.</li><li>Check whether the shape coincides with a present-day track, field edge or other visible feature.</li></ol></div>"""),
    ("workflow", "Compare relief methods", """
        <p>Open <strong>Visualization tools → Relief types</strong>, select a method, adjust its parameter and choose <strong>Add to the map</strong>. Applying a new type replaces the current Relief view. The initial hillshade uses light direction 315° and sun elevation 45°.</p>
        <div class="ag-example"><span class="ag-example-label">Try it</span><h3>Check a suspected bank or ditch</h3><ol><li>Inspect it with Hillshade at <strong>315°</strong>.</li><li>Change the light direction to <strong>45°</strong> and compare its visibility.</li><li>Try <strong>Multi-Hillshade</strong> or <strong>Sky-View Factor</strong> to compare it with a view that does not rely on a single illumination direction.</li><li>Try a <strong>Simple Local Relief Model</strong> to separate smaller forms from the broad terrain trend.</li></ol><p>A feature becoming less visible under another light direction does not mean it has disappeared from the data.</p></div>
        <p>For more detailed parameter control, use the <a href="#ag-rvt">RVT workspace</a> with live preview. Stronger contrast changes the display, not the terrain elevations or spatial resolution.</p>"""),
    ("relief", "Relief method reference", """
        <p>Use these descriptions to choose a starting method, then compare it with other views. A visualization emphasizes terrain geometry; it does not determine the origin or date of a feature.</p>
        {views_table}"""),
    ("ai", "Read an AI anomaly", """
        <p><strong>Find hidden features (AI)</strong> combines RVT relief descriptors to find forms that differ from their surroundings. It analyzes the loaded terrain; it does not create extra terrain detail.</p>
        <ol class="ag-ai-flow">
          <li><b>Leave out</b><span>Level water (lakes, sea) and a strip along the data edge are not analysed; they appear grey.</span></li>
          <li><b>Describe</b><span>Read relief at the chosen feature width, and at three times it, using several RVT views.</span></li>
          <li><b>Compare</b><span>Model the usual relief of this terrain and score how unusual each place is.</span></li>
          <li><b>Find shapes</b><span>Look for rings and concentric bands that a line of unusual relief follows around a circle, and for stepped bands that follow the shape of a hill around its summit (terraces or ditches of a hillfort or castle mound), each better than chance on the same terrain.</span></li>
          <li><b>Rank</b><span>Rings first, then curved lines and compact forms; long straight lines (often modern roads) last.</span></li>
        </ol>
        <p>Set <strong>feature width</strong> and <strong>sensitivity</strong>. Low, medium and high sensitivity cap the flagged share at 0.5%, 1% and 2%; a terrain can still return no anomalies. Outlines are coloured by kind: orange ring, purple bands around a hilltop, green curved line, red compact form, grey straight line. A compact form close to the edge of the data is kept with the note "near the edge of the data: check for artefacts". Advanced settings include larger structures, the water options, the width of the edge strip, the random seed and known-feature inputs.</p>
        <p>In the map, scores and outlines appear beside the relief view. In <strong>3D Analysis → View → AI Relief</strong>, the analysis runs automatically if needed and existing results are reused. Labels stay near their anomaly markers as the terrain rotates. Hover to read details; click to focus the camera.</p>
        {ai_image}
        <div class="ag-example"><span class="ag-example-label">Example from Colle San Mauro</span><h3>Anomaly 2: a raised form</h3><p>With feature width <strong>5 m</strong> and medium sensitivity, the example shows a form about <strong>17.3 × 6.4 m</strong>, with local relief of <strong>+0.27 m</strong>. Its shape is compatible with a mound or built-up platform; a natural rise or spoil heap can have similar relief.</p><p>The dimensions and relief are measurements from this analysis. The interpretation is a morphological hypothesis, not evidence that the form is archaeological. Anomaly numbers can change with data or settings.</p></div>
        <p>Known features can be loaded as CSV or GeoJSON to compare the result with individual RVT views and VAT/e3MSTP. Without independent reference data, the app cannot establish detection accuracy for the survey. Settings and the random seed are recorded in the downloaded script.</p>"""),
    ("rvt", "Use the full RVT workspace", """
        <p>Choose <strong>Visualization tools → Open RVT workspace</strong>. The tools dock beside the map. The pinned RVT_py version exposes <strong>148 public operations</strong>, including their parameters.</p>
        <div class="ag-tool-grid">
          <div><h3>Operations and preview</h3><p>Search an operation, use the loaded terrain or a previous result, and change its parameters. <strong>Live preview</strong> updates supported calculations; <strong>Keep result</strong> retains an output.</p></div>
          <div><h3>Settings and compositions</h3><p>Edit RVT settings or render compositions such as VAT, Combined VAT, Prismatic openness and City. File and object actions require an explicit run.</p></div>
          <div><h3>Inputs and results</h3><p>Import rasters, configuration files or arrays. Inspect outputs, display a band or RGB result, download files or package a session.</p></div>
          <div><h3>Batch and tiles</h3><p>Apply an operation to selected raster files. Tiled operations calculate large rasters in blocks.</p></div>
        </div>
        <div class="ag-example"><span class="ag-example-label">Try it</span><h3>Adjust the light while keeping the map visible</h3><p>Select the Hillshade operation, enable <strong>Live preview</strong> and change the light direction. Each preview replaces the temporary result. Choose <strong>Keep result</strong> when you want to retain it for further processing.</p></div>
        <p>Calculations use the loaded grid; speed depends on the operation and terrain size. A session package contains managed files, arrays, settings and history, but does not automatically restore an interactive session.</p>"""),
    ("export", "Inspect in 3D and export", """
        <p>Open <strong>3D Analysis</strong>. Drag to rotate and scroll to zoom. The terrain has its own viewport; <strong>View settings</strong> and <strong>EXPORT AS</strong> occupy the separate right column.</p>
        {terrain_image}
        <div class="ag-table-wrap"><table><thead><tr><th>Control</th><th>How to use it</th></tr></thead><tbody>
          <tr><th>View</th><td>Original; Cloud 1 (points); Cloud 2 (surface, wireframe and points); Cloud 3 (enhanced local relief); AI Relief (anomaly scores).</td></tr>
          <tr><th>Relief view</th><td>100% shows the relief; 0% reveals satellite imagery on the same cropped 3D surface. Intermediate values blend them.</td></tr>
          <tr><th>Elevation color</th><td>Starts at <strong>35%</strong>. At 0% the terrain is grayscale. Increasing it adds elevation tint while preserving the grayscale luminance, so small relief variations remain legible. AI Relief keeps its separate anomaly-score palette.</td></tr>
          <tr><th>Contrast / Brightness</th><td>Both range from 0 to 100. Defaults are <strong>65%</strong> contrast and <strong>40%</strong> brightness. They affect display and images, not numerical terrain data.</td></tr>
          <tr><th>Vertical Boost</th><td>Starts at <strong>×1</strong>, preserving true proportions. Move toward <strong>Auto</strong> to emphasize relief. At ×2, a 1 m height difference is displayed as 2 m relative to horizontal distances.</td></tr>
        </tbody></table></div>
        <details class="ag-visual-example"><summary>Try it: reveal the satellite surface</summary><div><ol><li>Keep the same camera position.</li><li>Move <strong>Relief view</strong> from 100% to 0%.</li><li>Compare the relief with the satellite image. Only the valid terrain surface is shown; the exterior remains transparent.</li></ol>{satellite_image}</div></details>
        <p class="ag-note"><strong>Cloud 3</strong> enhances local relief and changes displayed elevations. Use <strong>Original</strong> at <strong>×1</strong> when assessing true terrain proportions. Higher image resolution cannot add elevations absent from the terrain grid.</p>
        <div class="ag-table-wrap"><table><thead><tr><th>Export</th><th>Choose it for</th></tr></thead><tbody>
          <tr><th>GeoTIFF</th><td>Numerical relief layers for GIS analysis, downloaded from the map's layer options.</td></tr>
          <tr><th>PDF / PNG</th><td>The current 3D camera, zoom, rendering, opacity and exaggeration, with a transparent background. Maximum supported image quality is automatic.</td></tr>
          <tr><th>LAZ / PLY / glTF</th><td>The full current terrain grid for other 3D tools, without point subsampling or mesh decimation. glTF downloads as a binary .glb.</td></tr>
        </tbody></table></div>
        <div class="ag-example"><span class="ag-example-label">Export example</span><h3>Save a figure</h3><p>Choose the rendering, position the terrain, set the relief opacity and press <strong>PNG</strong> or <strong>PDF</strong> under <strong>EXPORT AS</strong>. The image matches that view. Images render up to an 8192-pixel longest edge, within graphics-device and 32-million-pixel limits; PDF embeds a raster figure.</p></div>"""),
    ("usecases", "Use cases and references", """
        <p>The upload screen provides three datasets. <strong>Site &amp; references</strong> in the map gives context for the Italian sites.</p>
        <div class="ag-case-list">
          <div><h3>🇮🇹 Colle San Mauro, L'Aquila</h3><p>One original 1000 × 1000 DTM tile. The examples in this guide use this dataset.</p><p>Heinzelmann, M., Jordan, D. &amp; Murer, C. (2010). <em>Amiternum and the upper Aterno valley: a Sabine-Roman town and its territory.</em> Journal of Roman Archaeology 23, 55–83. <a href="https://doi.org/10.1017/S1047759400002300" target="_blank" rel="noopener noreferrer">Read reference</a>.</p></div>
          <div><h3>🇮🇹 Castello di Montedoglio, Sansepolcro</h3><p>Two adjacent tiles mosaicked into 2000 × 1000 cells without resampling, for inspecting the castle's surrounding terrain.</p><p>Vigotti, L. (2021). <em>Il castello e i possedimenti dei conti di Montedoglio nel 1434.</em> Pagine Altotiberine 70, 181–202. <a href="https://www.researchgate.net/publication/389939665_Il_castello_di_Montedoglio_e_i_possedimenti_dei_Conti_di_Montdoglio_nel_1434" target="_blank" rel="noopener noreferrer">Read reference</a>.</p></div>
          <div><h3>🇬🇧 Betterton, Oxfordshire</h3><p>Environment Agency native 1 m DTM. Terrain data are licensed under <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/" target="_blank" rel="noopener noreferrer">OGL v3.0</a>.</p></div>
        </div>
        <p>RVT algorithms are provided by <a href="https://github.com/EarthObservation/RVT_py" target="_blank" rel="noopener noreferrer">RVT_py</a> (ZRC SAZU and University of Ljubljana, Apache License 2.0), pinned to commit bab109c. Cite RVT_py and the relevant method publications when using its visualizations.</p>"""),
    ("questions", "Practical questions", """
        <div class="ag-faq">
          <details><summary>Which light direction is best?</summary><p>There is no universally best direction. Compare 315° with another direction and check a non-directional method. Directional shading can hide forms aligned with the light.</p></details>
          <details><summary>Does contrast improve terrain resolution?</summary><p>No. It changes tonal differences in the display. Source resolution, point density and data quality determine which terrain forms are present.</p></details>
          <details><summary>Does an AI anomaly mean an archaeological site?</summary><p>No. It identifies unusual relief. Its possible interpretation must be checked against imagery, survey context and independent evidence.</p></details>
          <details><summary>Why is part of the terrain missing?</summary><p>NoData and large boundary-connected fill regions are excluded from the 3D surface. Check the input coverage and preparation log before treating an edge as a real landform.</p></details>
          <details><summary>What stays local?</summary><p>Terrain processing runs locally. Basemap imagery, place labels and global terrain tiles require internet access. Opening an external coordinate link passes that location to the external service.</p></details>
          <details><summary>What if a file or operation is too large?</summary><p>Check georeferencing and input contents first. Reduce the study area or tile count, or use a tiled RVT operation. Processing uses local memory. Browser downloads are limited to 200 MB; larger outputs remain at the local location reported by the app.</p></details>
          <details><summary>Can I reproduce the processing?</summary><p>Use the map's <strong>Script</strong> card to download the recorded Python steps. RVT workspace packages retain managed inputs, outputs, settings and operation history.</p></details>
        </div>"""),
]

@st.cache_data(show_spinner=False)
def screenshot_uri(path, modified):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def screenshot_markup(name, section, alt, caption):
    path = Path(__file__).resolve().parents[1] / "docs" / "assets" / name
    uri = screenshot_uri(str(path), path.stat().st_mtime_ns)
    ident = "ag-shot-" + name.removeprefix("screenshot-").removesuffix(".png")
    return (f'<figure class="ag-figure" id="{ident}">'
            f'<a class="ag-figure-close" href="#ag-{section}" aria-label="Close enlarged screenshot">Close image ×</a>'
            f'<a class="ag-figure-open" href="#{ident}" aria-label="Enlarge screenshot: {escape(alt, quote=True)}">'
            f'<img src="{uri}" alt="{escape(alt, quote=True)}" width="1440" height="900" loading="lazy" decoding="async"></a>'
            f'<figcaption>{escape(caption)}<small>Click image to enlarge</small></figcaption></figure>')


def guide_markup():
    rows = "".join(f"<tr><th scope='row'>{escape(n)}</th><td>{escape(w)}</td><td>{escape(u)}</td></tr>" for n, w, u in VIEWS)
    table = ("<div class='ag-table-wrap'><table><thead><tr><th>View</th><th>What it shows</th><th>Use it for</th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div>")
    replacements = {
        "views_table": table,
        "upload_image": screenshot_markup("screenshot-upload.png", "input", "Upload screen and bundled use cases",
                                            "Load a file or choose one of the three bundled terrains."),
        "map_image": screenshot_markup("screenshot-map.png", "map", "Colle San Mauro on the map with layers and preprocessing",
                                         "Colle San Mauro: hillshade over satellite imagery, with the preparation log on the right."),
        "ai_image": screenshot_markup("screenshot-3d-anomaly-info.png", "ai", "Anomaly 2 details in the Colle San Mauro 3D view",
                                        "Hover an anomaly label to read measurements and its possible morphological interpretation."),
        "terrain_image": screenshot_markup("screenshot-3d.png", "export", "3D AI Relief with settings and export controls",
                                             "The 3D terrain has its own viewport, with View settings and EXPORT AS on the right."),
        "satellite_image": screenshot_markup("screenshot-3d-satellite.png", "export", "Satellite imagery draped on the cropped 3D terrain",
                                               "Relief view at 0%: satellite imagery follows the same valid terrain surface."),
    }
    def content(body):
        for key, value in replacements.items():
            body = body.replace("{" + key + "}", value)
        return body
    links = "".join(f'<a href="#ag-{key}"><span>{i:02}</span>{escape(title)}</a>'
                    for i, (key, title, _) in enumerate(SECTIONS, 1))
    cards = "".join(f'<section id="ag-{key}" class="ag-info-card{ " ag-intro" if i == 1 else ""}">'
                    f'<span class="ag-section-number">{i:02}</span><h2>{escape(title)}</h2>'
                    f'{content(body)}</section>'
                    for i, (key, title, body) in enumerate(SECTIONS, 1))
    return ('<div class="ag-guide"><section class="ag-guide-hero">'
            '<div class="ag-orbits" aria-hidden="true"><i></i><i></i><i></i></div>'
            '<h1>How AIrchGIS works</h1><p>Follow a terrain from upload to relief comparison, anomaly inspection and research export. Includes examples from Colle San Mauro.</p></section>'
            '<div class="ag-guide-layout"><aside class="ag-toc" aria-label="Guide contents">'
            f'<p>In this guide</p><nav>{links}</nav></aside><article class="ag-guide-content">{cards}</article></div></div>')


def render_help():
    if st.button("← Back to the tool", key="as_help_back"):
        st.session_state.as_active_tool = st.session_state.get("as_help_from", "RVT")
        st.rerun()
    styles = Path(__file__).with_name("help_page.css").read_text(encoding="utf-8")
    st.html(f"<style>{styles}</style>{guide_markup()}")
