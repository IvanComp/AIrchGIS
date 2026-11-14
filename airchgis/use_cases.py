from pathlib import Path


FOLDER = Path(__file__).with_name("data") / "use_cases" / "vaassen"
CASES = (
    {"id": "colle_san_mauro", "label": "Colle San Mauro, L'Aquila, Italy",
     "path": FOLDER.parent / "colle_san_mauro" / "colle_san_mauro_DTM.tif",
     "flag": "🇮🇹", "help": "Open the Colle San Mauro DTM and archaeological references.",
     "summary": "Colle San Mauro overlooks the Amiternum area near San Vittorino, in the upper Aterno valley. The Roman amphitheatre lies at its foot. The cited study examines the town, its surrounding settlements and the landscape through survey, geophysics and excavation.",
     "terrain": "One original DTM tile · 1000 × 1000 cells · EPSG:4326 · 0.00001° grid (approximately 1 m). NoData areas are excluded from the terrain.",
     "references": [{"citation": "Heinzelmann, M., Jordan, D. & Murer, C. (2010). Amiternum and the upper Aterno valley: a Sabine-Roman town and its territory. Journal of Roman Archaeology 23, 55–83.",
                     "url": "https://doi.org/10.1017/S1047759400002300",
                     "pdf": "https://archaeologie.phil-fak.uni-koeln.de/sites/archaeologie/Forschungsprojekte/amiternum/Heinzelmann_Amiternum_JRA_2010.pdf"}]},
    {"id": "castello_montedoglio", "label": "Castello di Montedoglio, Sansepolcro, Italy",
     "path": FOLDER.parent / "castello_montedoglio" / "castello_montedoglio_DTM.tif",
     "flag": "🇮🇹", "help": "Open the Castello di Montedoglio DTM and historical references.",
     "summary": "The ruined castle of Montedoglio occupies a hill overlooking the Tiber near Sansepolcro, beside the present reservoir. Vigotti reconstructs the castle and its estates from inventories of 1432–1434, documenting its rooms, possessions and strategic role in the upper Tiber valley.",
     "terrain": "Two adjacent original DTM tiles · 2000 × 1000 cells · EPSG:4326 · 0.00001° grid (approximately 1 m). Mosaicked without resampling.",
     "references": [{"citation": "Vigotti, L. (2021). Il castello e i possedimenti dei conti di Montedoglio nel 1434. Pagine Altotiberine 70, 181–202. ISSN 2039-4861.",
                     "url": "https://www.researchgate.net/publication/389939665_Il_castello_di_Montedoglio_e_i_possedimenti_dei_Conti_di_Montdoglio_nel_1434"}]},
    {"id": "england_1", "label": "Betterton, Oxfordshire, UK", "path": FOLDER.parent / "england" / "England_EA_DTM_1m.tif",
     "flag": "🇬🇧", "help": "England · Environment Agency native 1 m DTM · Same area as LidarMap UK comparison · OGL v3.0"},
)
