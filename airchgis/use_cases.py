from pathlib import Path


FOLDER = Path(__file__).with_name("data") / "use_cases" / "vaassen"
CASES = (
    {"id": "vaassen_05", "label": "Vaassen · 0.5 m", "path": FOLDER / "Vaassen_AHN4_DTM_0p5m.tif",
     "help": "Netherlands · AHN4 native DTM · 0.5 m cells · 1 km² · CC0"},
    {"id": "vaassen_1", "label": "Vaassen · 1 m", "path": FOLDER / "Vaassen_AHN4_DTM_1m.tif",
     "help": "Netherlands · Mean of 2 × 2 native AHN4 cells · 1 km² · CC0"},
    {"id": "vaassen_5", "label": "Vaassen · 5 m", "path": FOLDER / "Vaassen_AHN4_DTM_5m.tif",
     "help": "Netherlands · Mean of 10 × 10 native AHN4 cells · 1 km² · CC0"},
)
