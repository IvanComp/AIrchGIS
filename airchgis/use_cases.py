from pathlib import Path


FOLDER = Path(__file__).with_name("data") / "use_cases" / "vaassen"
CASES = (
    {"id": "colle_san_mauro", "label": "Colle San Mauro, L'Aquila, Italy", "path": None, "disabled": True,
     "flag": "🇮🇹", "help": "Colle San Mauro, L'Aquila, Italy · Use case not configured."},
    {"id": "england_1", "label": "Betterton, Oxfordshire, UK", "path": FOLDER.parent / "england" / "England_EA_DTM_1m.tif",
     "flag": "🇬🇧", "help": "England · Environment Agency native 1 m DTM · Same area as LidarMap UK comparison · OGL v3.0"},
    {"id": "todo_ro", "label": "TODO, TODO, Romania", "path": None, "disabled": True,
     "flag": "🇷🇴", "help": "Use case not configured."},
)
