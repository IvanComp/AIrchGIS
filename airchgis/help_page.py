

from __future__ import annotations

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
    ("Simple Local Relief Model", "Removes the large landscape, keeps small bumps and hollows.", "Low earthworks on slopes or hills."),
    ("Multi-Scale Relief Model", "Local relief at several sizes in one image.", "Features of mixed sizes in the same area."),
    ("Multi-Scale Topographic Position", "Colour image of relief position at three scales.", "Overviews of the landscape and its forms."),
    ("Sky Illumination", "Shading under a diffuse, cloudy sky.", "Soft, realistic relief for figures."),
    ("Local Dominance", "How much each point rises above its surroundings.", "Low mounds and barrows on flat ground."),
    ("e3MSTP (RGB)", "Colour blend of several views.", "A rich all-in-one view for archaeology."),
]


SECTIONS = [
    ("overview", "What is AIrchGIS?", """
        <p>AIrchGIS is a research tool for examining digital terrain models and LiDAR point clouds.
        It generates relief visualizations and displays the results on an interactive map.</p>
        <p>Upload terrain data, set the visualization parameters and compare the resulting layers.
        Outputs include GeoTIFF rasters, publication figures and open 3D data.</p>
        <p class="ag-note">Terrain anomalies require interpretation. A visible feature is not, by itself, evidence of an archaeological site.</p>"""),
    ("input", "Upload a digital terrain model", """
        <p>Load a <strong>GeoTIFF or ASCII grid</strong>, a ZIP archive of raster tiles, or a <strong>LAS/LAZ point cloud</strong>.
        The upload accepts multiple files, up to 4 GB per file.</p>
        <ul><li>Raster files need a coordinate system and georeferencing to appear on the map.</li>
        <li>Point clouds are gridded using classified ground points when available; otherwise all points are used. Set the cell size before loading.</li>
        <li>Terrain in geographic coordinates is reprojected to a metric UTM coordinate system for analysis.</li></ul>
        <p>Once the data are loaded, the map opens automatically with a Hillshade layer at 315°. Use <strong>Home</strong> in the top bar to return to upload.</p>"""),
    ("workflow", "Preprocessing and visualization", """
        <ol><li><strong>Load and prepare the terrain.</strong> Point clouds are converted to a terrain raster; geographic data are reprojected as needed.</li>
        <li><strong>Create relief views.</strong> Select a method in the Tools panel, adjust its main parameter and choose <strong>Add to the map</strong>.</li>
        <li><strong>Compare the results.</strong> Toggle layers or change their opacity.</li></ol>
        <p>For hillshade and anisotropic sky-view factor, the light direction is set with a slider.
        Other methods expose a search radius where applicable. Try more than one method: different visualizations emphasize different terrain forms.</p>"""),
    ("relief", "Relief views", """
        <p>Choose a method according to the terrain forms and feature sizes you want to examine.
        Directional lighting can hide features aligned with the light; compare it with methods that do not depend on a single light direction.</p>
        {views_table}"""),
    ("resolution", "Data quality and resolution", """
        <p>The resolution and quality of the source terrain determine which features can be examined.
        A finer grid created from sparse points does not recover missing terrain detail.</p>
        <p>Compare several relief methods and light directions. Features may be obscured by directional shading, vegetation or artefacts in the source data.</p>
        <p><strong>Stronger contrast</strong> changes the display of a layer. It does not increase spatial resolution.</p>"""),
    ("map", "The map", """
        <div class="ag-tool-grid">
        <div><h3>Tools and layers</h3><p>Layers appear first in the right panel, followed by Relief Visualization Toolbox with relief views and visualization controls. The arrow on its edge hides or restores the panel.</p></div>
        <div><h3>Layer comparison</h3><p>Open or close Layers to access Place, Base map and all added relief views. Each level has visibility and opacity controls; relief results also provide contrast, GeoTIFF download and removal.</p></div>
        <div><h3>Distance and coordinates</h3><p>The left controls provide zoom, full screen and two-point distance measurement. Select a point to read UTM coordinates and terrain elevation, then open it in Google Earth.</p></div>
        <div><h3>Terrain relief</h3><p>The 3D toggle tilts the basemap over global terrain. Use 3D Analysis at the top right to inspect the uploaded terrain.</p></div></div>"""),
    ("export", "Export, compare and discover", """
        <p><strong>3D Analysis</strong> includes Original, Cloud 1 (points), Cloud 2 (surface, wireframe and points), and Cloud 3 (enhanced local relief). Select the mode under Terrain rendering. Cloud 3 modifies displayed elevations; exports use the source terrain.</p>
        <ul><li><strong>GeoTIFF:</strong> download individual result layers from their layer options.</li>
        <li><strong>PDF or PNG figure:</strong> open 3D Analysis and choose Download high-quality image in its Export panel. Image options control resolution, width, camera, vertical exaggeration, scale bar and north arrow.</li>
        <li><strong>Open 3D data:</strong> in 3D Analysis, download a package with a point cloud, terrain mesh and georeferencing metadata for use in other research software.</li></ul>
        <p>3D exports include LAZ/LAS, PLY and glTF. LAZ requires compression support; otherwise the point cloud is written as LAS.</p>
        <p>For a figure, check which visible layer is on top: it is used as the terrain drape.</p>"""),
    ("questions", "Practical questions and limits", """
        <div class="ag-faq">
        <details><summary>Which visualization should I start with?</summary><p>The initial Hillshade uses 315°. There is no universally best light direction: features parallel to illumination may be hidden. Compare several directions, Multi-Hillshade, sky-view factor or a local relief model. Change the light direction to check features that may be hidden by directional shading.</p></details>
        <details><summary>Does AIrchGIS identify archaeological sites?</summary><p>No. Relief views help you inspect terrain forms. Interpret anomalies alongside other evidence and, where appropriate, field observations.</p></details>
        <details><summary>Do uploaded data leave my computer?</summary><p>Terrain processing runs locally. Internet access is needed for basemap imagery, geographic labels and global terrain tiles. Opening Google Earth passes the selected coordinates to that service.</p></details>
        <details><summary>Why does a file fail to open?</summary><p>Check its coordinate system, georeferencing and file contents. For large terrain models, try fewer tiles or a smaller area. Available memory can limit the size of an analysis.</p></details>
        <details><summary>Are the use cases available?</summary><p>The three use-case buttons are placeholders and remain disabled. The terrain workbench is available through file upload.</p></details>
        </div>"""),
]


def guide_markup():
    rows = "".join(f"<tr><th scope='row'>{escape(n)}</th><td>{escape(w)}</td><td>{escape(u)}</td></tr>" for n, w, u in VIEWS)
    table = ("<div class='ag-table-wrap'><table><thead><tr><th>View</th><th>What it shows</th><th>Use it for</th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div>")
    links = "".join(f'<a href="#ag-{key}"><span>{i:02}</span>{escape(title)}</a>'
                    for i, (key, title, _) in enumerate(SECTIONS, 1))
    cards = "".join(f'<section id="ag-{key}" class="ag-info-card{ " ag-intro" if i == 1 else ""}">'
                    f'<span class="ag-section-number">{i:02}</span><h2>{escape(title)}</h2>'
                    f'{body.replace("{views_table}", table)}</section>'
                    for i, (key, title, body) in enumerate(SECTIONS, 1))
    return ('<div class="ag-guide"><section class="ag-guide-hero">'
            '<div class="ag-orbits" aria-hidden="true"><i></i><i></i><i></i></div>'
            '<h1>How AIrchGIS works</h1><p>A guide to terrain input, relief visualization, map comparison and research exports.</p></section>'
            '<div class="ag-guide-layout"><aside class="ag-toc" aria-label="Guide contents">'
            f'<p>In this guide</p><nav>{links}</nav></aside><article class="ag-guide-content">{cards}</article></div></div>')


def render_help():
    if st.button("← Back to the tool", key="as_help_back"):
        st.session_state.as_active_tool = st.session_state.get("as_help_from", "RVT")
        st.rerun()
    styles = Path(__file__).with_name("help_page.css").read_text(encoding="utf-8")
    st.html(f"<style>{styles}</style>{guide_markup()}")
