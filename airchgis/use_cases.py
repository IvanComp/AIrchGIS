from pathlib import Path


FOLDER = Path(__file__).with_name("data") / "use_cases" / "vaassen"
CASES = (
    {"id": "england_1", "label": "England · 1 m", "path": FOLDER.parent / "england" / "England_EA_DTM_1m.tif",
     "flag": "🇬🇧", "help": "England · Environment Agency native 1 m DTM · Same area as LidarMap UK comparison · OGL v3.0"},
    {"id": "todo_uk", "label": "TODO, TODO, UK", "path": None, "disabled": True,
     "flag": "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f", "help": "Use case not configured."},
    {"id": "todo_ro", "label": "TODO, TODO, Romania", "path": None, "disabled": True,
     "flag": "🇷🇴", "help": "Use case not configured."},
)
