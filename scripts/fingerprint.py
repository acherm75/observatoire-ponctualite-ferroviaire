"""Empreinte des entrées du pipeline, pour ne republier les données que si elles changent.

L'empreinte combine :
- le contenu des tables SNCF brutes (hors horodatage de chargement) ;
- le code qui produit les marts (ingestion, dbt, ML, export).

La météo n'en fait pas partie : le fichier Météo-France du mois en cours change chaque
jour, mais les faits de ponctualité ne bougent qu'à la publication mensuelle SNCF. La
météo est rafraîchie en même temps que celle-ci.

Pourquoi ne pas comparer simplement les fichiers exportés ? XGBoost ne donne pas
exactement les mêmes décimales d'une machine à l'autre (Mac ARM ou runner Linux), donc
les Parquet changeraient à chaque exécution sans que rien n'ait réellement changé.
"""
import hashlib
import json

import duckdb

from ingestion.config import DATA_DIR, DUCKDB_PATH, ROOT, SNCF_DATASETS

FINGERPRINT_PATH = DATA_DIR / "marts" / "_fingerprint.json"
CODE_GLOBS = [
    "ingestion/*.py", "ml/*.py", "scripts/export_marts.py",
    "transform/dbt_project.yml", "transform/models/**/*", "transform/seeds/*",
    "transform/macros/**/*", "transform/tests/*",
]


def _data_hash() -> dict[str, str]:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    out = {}
    for table in sorted(SNCF_DATASETS.values()):
        # Hash de chaque ligne, triés : insensible à l'ordre des lignes renvoyé par l'API.
        out[table] = con.execute(f"""
            select md5(string_agg(h, '' order by h))
            from (select md5(t::varchar) as h from (select * exclude (_loaded_at) from raw.{table}) t)
        """).fetchone()[0]
    con.close()
    return out


def _code_hash() -> str:
    h = hashlib.sha256()
    files = sorted({p for g in CODE_GLOBS for p in ROOT.glob(g) if p.is_file()})
    for p in files:
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def compute() -> dict:
    return {"donnees_sncf": _data_hash(), "code": _code_hash()}


def stored() -> dict | None:
    try:
        return json.loads(FINGERPRINT_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save(fp: dict) -> None:
    FINGERPRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_PATH.write_text(json.dumps(fp, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    fp = compute()
    print(json.dumps(fp, indent=2), "\ninchangée" if fp == stored() else "\nmodifiée")
