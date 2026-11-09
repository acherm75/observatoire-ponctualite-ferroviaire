import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
# `app/` n'est pas un paquet : l'app importe ses modules par leur nom, on fait de même.
for chemin in (RACINE, RACINE / "app"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))
