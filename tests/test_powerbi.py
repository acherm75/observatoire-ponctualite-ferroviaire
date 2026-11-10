"""Cohérence du projet Power BI généré (powerbi/), vérifiable sans Power BI Desktop.

Les fichiers JSON du rapport sont validés contre les schémas Microsoft à la génération ; ici on
vérifie ce qu'aucun schéma ne contrôle : chaque champ cité par un visuel ou par une mesure DAX
existe dans le modèle, et les relations reposent sur des clés réellement uniques.
"""
import json
import re
from pathlib import Path

import duckdb
import pytest

POWERBI = Path(__file__).resolve().parents[1] / "powerbi"
MODELE = POWERBI / "Observatoire.SemanticModel" / "definition"
RAPPORT = POWERBI / "Observatoire.Report" / "definition"
MARTS = Path(__file__).resolve().parents[1] / "data" / "marts"


def _nom(brut: str) -> str:
    brut = brut.strip()
    return brut[1:-1].replace("''", "'") if brut.startswith("'") else brut


def _modele():
    tables, expressions = {}, {}
    for f in sorted((MODELE / "tables").glob("*.tmdl")):
        lignes = f.read_text().split("\n")
        table = _nom(lignes[0].removeprefix("table "))
        colonnes, mesures = set(), {}
        courante = None
        for ligne in lignes[1:]:
            if m := re.match(r"\tcolumn (.+)$", ligne):
                colonnes.add(_nom(m.group(1)))
                courante = None
            elif m := re.match(r"\tmeasure ('(?:[^']|'')+'|\S+) =(.*)$", ligne):
                courante = _nom(m.group(1))
                mesures[courante] = m.group(2)
            elif courante and ligne.startswith("\t\t\t"):
                mesures[courante] += "\n" + ligne
            elif not ligne.startswith("\t\t\t"):
                courante = None if not ligne.startswith("\t\t") else courante
                if ligne.startswith("\t\t"):
                    courante = None
        tables[table] = colonnes
        expressions.update({(table, k): v for k, v in mesures.items()})
    return tables, expressions


TABLES, MESURES = _modele()
NOMS_MESURES = {m for _, m in MESURES}


def _champs(objet):
    """Tous les champs {Column|Measure: {Expression: {SourceRef: {Entity}}, Property}} d'un JSON."""
    if isinstance(objet, dict):
        for genre in ("Column", "Measure"):
            c = objet.get(genre)
            if isinstance(c, dict) and "Entity" in c.get("Expression", {}).get("SourceRef", {}):
                yield genre, c["Expression"]["SourceRef"]["Entity"], c["Property"]
        for v in objet.values():
            yield from _champs(v)
    elif isinstance(objet, list):
        for v in objet:
            yield from _champs(v)


VISUELS = sorted(RAPPORT.glob("pages/*/visuals/*/visual.json"))


def test_projet_present():
    assert (POWERBI / "Observatoire.pbip").exists()
    assert len(TABLES) == 12 and len(MESURES) >= 40 and len(VISUELS) >= 40


@pytest.mark.parametrize("fichier", VISUELS, ids=lambda f: f"{f.parts[-4]}/{f.parts[-2]}")
def test_champs_des_visuels_existent(fichier):
    for genre, table, nom in _champs(json.loads(fichier.read_text())):
        assert table in TABLES, f"table inconnue : {table}"
        if genre == "Column":
            assert nom in TABLES[table], f"colonne inconnue : {table}[{nom}]"
        else:
            assert (table, nom) in MESURES, f"mesure inconnue : {table}[{nom}]"


def test_references_dax():
    for (table, nom), expr in MESURES.items():
        for t, c in re.findall(r"\b(\w+)\[([^\]]+)\]", expr):
            assert t in TABLES and c in TABLES[t], f"{nom} : colonne {t}[{c}] inconnue"
        for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", expr):
            assert ref in NOMS_MESURES, f"{nom} : mesure [{ref}] inconnue"


def test_relations_sur_des_cles_uniques():
    relations = re.findall(r"fromColumn: (\w+)\.(\w+)\n\ttoColumn: (\w+)\.(\w+)", (MODELE / "relationships.tmdl").read_text())
    assert len(relations) == 14
    for t_de, c_de, t_vers, c_vers in relations:
        assert c_de in TABLES[t_de] and c_vers in TABLES[t_vers]
        (n, distincts), = duckdb.sql(f"select count(*), count(distinct {c_vers}) from '{MARTS / t_vers}.parquet'").fetchall()
        assert n == distincts, f"{t_vers}.{c_vers} n'est pas une clé unique"


def test_colonnes_conformes_aux_parquet():
    import pyarrow.parquet as pq
    for table, colonnes in TABLES.items():
        assert colonnes == set(pq.read_schema(MARTS / f"{table}.parquet").names), table


def test_interactions_et_tri_visent_des_visuels_existants():
    for page in RAPPORT.glob("pages/*/page.json"):
        noms = {p.name for p in (page.parent / "visuals").iterdir()}
        for i in json.loads(page.read_text()).get("visualInteractions", []):
            assert {i["source"], i["target"]} <= noms, page.parent.name
    ordre = json.loads((RAPPORT / "pages" / "pages.json").read_text())["pageOrder"]
    assert set(ordre) == {p.parent.name for p in RAPPORT.glob("pages/*/page.json")}
