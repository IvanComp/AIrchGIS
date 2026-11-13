"""The "?" page: what AIrchGIS is, how it works and what each feature does."""

from __future__ import annotations

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


def render_help():
    if st.button("← Back to the tool", key="as_help_back"):
        st.session_state.as_active_tool = st.session_state.get("as_help_from", "RVT")
        st.rerun()
    st.markdown("## What is AIrchGIS?")
    st.markdown(
        "AIrchGIS helps archaeologists look for traces of the past in **LiDAR terrain models** (DTM, DSM and point "
        "clouds), without writing code. It runs on your computer, in the web browser, and works with your own files "
        "from any country, sensor and coordinate system. Your data stay on your computer."
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
    c3.markdown("**3 · See and download**\n\nThe result on a map, one sentence that explains it, one download. "
                "Measures and scripts are under *Details*.")
    st.markdown("## The map")
    st.markdown(
        "- **Layers panel (right):** switch each layer on or off and set its opacity: the relief view, the best view "
        "(*After*), the original hillshade (*Before*), place names and the satellite base map.\n"
        "- **Tools (left):** full screen, zoom, **measure** a distance between two points, and **coordinates**: click a "
        "point to read its UTM coordinates, latitude/longitude and the elevation of your terrain model (copied to the "
        "clipboard), then open it in Google Earth.\n"
        "- **3D button (bottom left):** tilts the map over a global terrain model; press it again for a flat view.\n"
        "- The map needs an internet connection for the satellite images; your own layers never leave your computer."
    )

    st.markdown("## What you can do")
    st.markdown(
        "- **Input:** terrain model (GeoTIFF, ASCII grid, zip) or point cloud (LAS/LAZ); optional surface models "
        "(first and last return). Example data and public sources are under *Other sources*.\n"
        "- **Improve and find the best view** *(recommended)*: cleans the terrain, compares up to 19 relief views "
        "with sizes matched to your features, and shows the clearest one with a before/after switch.\n"
        "- **Relief views:** hillshade, multi-direction hillshade, slope, sky-view factor, openness, local relief "
        "model, multi-scale relief model, local dominance and others (see the table below).\n"
        "- **3D view:** look at the terrain in 3D, save a **high-quality image (PDF or PNG)** for a paper, or export "
        "the terrain and point cloud as open 3D data (LAZ, PLY, glTF) for QGIS, CloudCompare or Blender."
    )

    st.markdown("## Features in detail")
    with st.expander("Relief views: what they show and when to use them"):
        st.table([{"View": n, "What it shows": w, "Use it for": u} for n, w, u in VIEWS])
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
            "of your data. If not, it tells you, and blocks the analysis when it is impossible: for example, a 0.5 m "
            "feature cannot be seen in a 1 m terrain model."
        )
    with st.expander("Known sites"):
        st.markdown(
            "In *Improve and find the best view* you can upload a list of known sites (CSV with longitude/latitude, "
            "GeoJSON, GeoPackage, zipped Shapefile, KML). AIrchGIS reports, for each view, how well it separates the sites "
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
            "choose a public download. Precise coordinates of new finds can help looters: share them only with the "
            "competent heritage authorities."
        )

    st.markdown("## Tips")
    st.markdown(
        "- Start with **Improve and find the best view** and the width of the features you expect.\n"
        "- If features may run in any direction, prefer views without a light direction (sky-view factor, openness, local relief model).\n"
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
