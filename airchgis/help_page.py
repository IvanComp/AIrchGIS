"""The "?" page: what AIrchGIS is, how it works and what each feature does."""

from __future__ import annotations

import streamlit as st


def _go(label, tool, key):
    if st.button(label, key=key):
        st.session_state.as_active_tool = tool
        st.rerun()


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


def render_help():
    if st.button("← Back to the tool", key="as_help_back"):
        st.session_state.as_active_tool = st.session_state.get("as_help_from", "RVT")
        st.rerun()
    st.markdown("## What is AIrchGIS?")
    st.markdown(
        "AIrchGIS helps archaeologists look for traces of the past in **LiDAR terrain models** and in "
        "**satellite, drone or aerial images**, without writing code. It runs on your computer, in the web browser, "
        "and works with your own files from any country, sensor and coordinate system. Your data stay on your computer."
    )
    st.markdown(
        "Its AI support makes your data **easier to read**: it cleans them, picks the view that shows features of the size "
        "you are looking for most clearly, and tells you what each step changed. It does not find sites by itself, and its "
        "scores are priorities to check, not probabilities."
    )

    st.markdown("## How it works")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**1 · Load data**\n\nUpload your file. Example data and public sources are under *Other sources*.")
    c2.markdown("**2 · Choose a tool**\n\nPick a tool from the list. Each has a one-line description and at most one setting; "
                "the rest is under *Advanced*.")
    c3.markdown("**3 · See and download**\n\nOne image, one sentence that explains it, one download. Measures and "
                "scripts are under *Details*.")

    st.markdown("## The two screens")
    t, f = st.columns(2)
    with t:
        st.markdown("### Terrain (LiDAR)")
        st.markdown(
            "For earthworks, mounds, ditches and terraces, also under trees.\n\n"
            "- **Input:** terrain model (GeoTIFF, ASCII grid, zip) or point cloud (LAS/LAZ); optional surface models.\n"
            "- **Improve and find the best view** *(recommended)*: cleans the terrain, compares up to 19 relief views "
            "with sizes matched to your features, and shows the clearest one with a before/after switch.\n"
            "- **Relief views:** hillshade, multi-direction hillshade, slope, sky-view factor, openness, local relief "
            "model, multi-scale relief model, local dominance and others.\n"
            "- **3D view:** look at the terrain in 3D, save a **high-quality image (PDF or PNG)** for a paper, or export "
            "the terrain and point cloud as open 3D data (LAZ, PLY, glTF) for QGIS, CloudCompare or Blender."
        )
        _go("Open Terrain", "RVT", "as_help_go_t")
    with f:
        st.markdown("### Field marks (images)")
        st.markdown(
            "For crop marks and soil marks of buried walls, ditches and roads.\n\n"
            "- **Input:** images of the same area on one or more dates (satellite, drone, aerial); several dates work "
            "better than one.\n"
            "- **Image quality per date:** clouds, shadows, haze and band problems; cloudy pixels can be masked.\n"
            "- **Find the marks:** ranks the dates, computes anomaly maps for each date and combines them "
            "(persistence, linear marks, vegetation deficit or excess, soil marks), then opens the clearest layer.\n"
            "- **Public archives:** Sentinel-2 and Landsat through Google Earth Engine (optional)."
        )
        _go("Open Field marks", "Crop Marks", "as_help_go_f")

    st.markdown("## Features in detail")
    with st.expander("Relief views: what they show and when to use them"):
        st.table([{"View": n, "What it shows": w, "Use it for": u} for n, w, u in VIEWS])
    with st.expander("Images and sensors (Field marks)"):
        st.markdown(
            "- **Sensors with presets:** Sentinel-2, Landsat 4-9, PlanetScope (4 and 8 bands), drone multispectral and RGB "
            "orthophotos; other sensors can be set band by band under *Advanced*.\n"
            "- **Files:** one multiband file per date, or one file per band (e.g. `..._B04.jp2`). Dates are read from file "
            "names and can be corrected under *Advanced*.\n"
            "- **Marks:** *crop marks* (plants weaker or stronger above buried features; need a growing crop), "
            "*soil marks* (colour of bare, ploughed soil), or *automatic* (chosen date by date).\n"
            "- **Layers:** vegetation deficit (walls, road beds), vegetation excess (ditches, wetter fills), linear marks "
            "(oriented anomalies), persistence (how many dates show the anomaly), soil marks and field boundaries."
        )
    with st.expander("Cleaning the terrain"):
        st.markdown(
            "- **Remove banding:** removes regular stripes from flight lines, while keeping roads and other long features.\n"
            "- **Remove spikes and pits:** replaces isolated wrong points with their neighbours.\n"
            "- **Fill small voids:** fills holes inside the survey smoothly; areas outside the survey stay empty.\n"
            "- **Reduce noise:** smooths noise while keeping the edges of banks and ditches.\n"
            "- **Point clouds:** removes isolated points (birds, wrong returns) from LAS/LAZ files.\n\n"
            "Each step shows a measure before and after. Your original file is never changed."
        )
    with st.expander("Best view and fused view"):
        st.markdown(
            "You type the width of the features you are looking for (e.g. 3 m for a ditch, 10 m for a road). AIrchGIS "
            "computes many relief views and gives each a **visibility score**: how much features of that width stand out "
            "from the noise and from the broad landscape. The best one is shown with a one-line explanation.\n\n"
            "The **fused view** (under *Advanced*) blends the four best views. If the blend is not clearer than the best "
            "single view, AIrchGIS says so and keeps the best view.\n\n"
            "*Stronger contrast* makes faint features easier to see; it is for display only. There is no "
            "\"super-resolution\": AIrchGIS never invents detail."
        )
    with st.expander("Resolution check"):
        st.markdown(
            "Before an analysis, AIrchGIS checks whether features of the width you typed can be seen at the pixel size "
            "of your data. If not, it tells you, and blocks the analysis when it is impossible: for example, 5 m streets "
            "cannot be seen in 10 m Sentinel-2 images."
        )
    with st.expander("Known sites"):
        st.markdown(
            "You can upload a list of known sites (CSV with longitude/latitude, GeoJSON, GeoPackage, zipped Shapefile, "
            "KML). AIrchGIS shows them on the map and reports, for each view or layer, how well it separates the sites "
            "from random places (AUC; 0.5 = chance). Known sites are a small, non-random sample: use this as a check, "
            "not as proof."
        )
    with st.expander("Repeatable work"):
        st.markdown(
            "Every step is recorded with its settings, the files used and the software versions. Under *Details* you can "
            "download it as a Python script that repeats the same analysis on the same files."
        )
    with st.expander("Privacy and site protection"):
        st.markdown(
            "AIrchGIS runs on your computer and keeps your data there. Nothing is published or sent anywhere, unless you "
            "choose a public archive. Precise coordinates of new finds can help looters: share them only with the "
            "competent heritage authorities."
        )

    st.markdown("## Tips")
    st.markdown(
        "- Start with **Improve and find the best view** and the width of the features you expect.\n"
        "- For images, load several dates of the same area: marks appear only in some seasons and years.\n"
        "- Compare the result with the *Before* view and with the measures under *Details*.\n"
        "- For a paper figure, use *3D view and 3D export → Download high-quality image* (PDF, 300 dpi)."
    )
    st.markdown("## Limits")
    st.markdown(
        "- AIrchGIS does not confirm sites: every anomaly needs checking with other sources or in the field.\n"
        "- A resolution warning means *more or better data are needed*, not that nothing is there.\n"
        "- Cleaning can also soften real features: look at the before/after switch.\n"
        "- The result depends on the quality and resolution of your files."
    )
