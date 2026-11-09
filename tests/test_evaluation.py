"""Notation de l'évaluation et validité du jeu de questions (sans appel à un modèle)."""
from pathlib import Path

import pandas as pd
import pytest

from agent import BaseLectureSeule
from evaluation.notation import (contient_nombre, contient_pourcentage, contient_texte, est_un_refus,
                                 extraire_nombres, noter)
from evaluation.questions import QUESTIONS

MARTS = Path(__file__).resolve().parents[1] / "data" / "marts"


@pytest.mark.parametrize("texte, attendu", [
    ("84,9 % en 2025", [84.9, 2025]),
    ("434 624 trains", [434624]),
    ("434 624 trains et 0.849", [434624, 0.849]),
    ("TGV : 84,9 %, TER : 91,3 %.", [84.9, 91.3]),
    ("en 2025 438 000 trains", [2025, 438000]),
    ("-1,5 point", [-1.5]),
])
def test_extraire_nombres(texte, attendu):
    assert extraire_nombres(texte) == attendu


@pytest.mark.parametrize("texte, ok", [
    ("La ponctualité TGV a été de 84,9 % en 2025.", True),
    ("Environ 85 %.", True),                # arrondi à l'unité : 0,1 point d'écart
    ("Le taux est de 0,849.", True),         # fraction
    ("La ponctualité est de 84,5 %.", False),
    ("Ponctualité de 2025.", False),
])
def test_contient_pourcentage(texte, ok):
    assert contient_pourcentage(texte, 0.8495) is ok


def test_contient_nombre():
    assert contient_nombre("434 624 trains ont circulé", 434624)
    assert contient_nombre("environ 434 600 trains", 434624)
    assert contient_nombre("près de 0,43 million de trains", 434624) is False  # 1 % d'écart max
    assert contient_nombre("434,6 milliers de trains", 434624)
    assert not contient_nombre("420 000 trains", 434624)
    assert contient_nombre("retard moyen de 38,4 minutes", 38.4057)


@pytest.mark.parametrize("texte, libelle, ok", [
    ("La pire liaison est Mâcon-Loché – Paris-Gare-de-Lyon.", "Mâcon Loché → Paris Gare de Lyon", True),
    ("De MACON LOCHE vers PARIS GARE DE LYON", "Mâcon Loché → Paris Gare de Lyon", True),
    ("Mâcon Loché vers Lyon", "Mâcon Loché → Paris Gare de Lyon", False),
    ("La région Provence-Alpes-Côte d’Azur", "Provence-Alpes-Côte d'Azur", True),
    ("En novembre 2025", "novembre", True),
])
def test_contient_texte(texte, libelle, ok):
    assert contient_texte(texte, libelle) is ok


@pytest.mark.parametrize("texte, ok", [
    ("Je ne dispose pas des horaires du jour : les données portent sur la ponctualité mensuelle.", True),
    ("Les prix des billets ne sont pas disponibles dans ces données.", True),
    ("Cette question est hors du périmètre de l'observatoire.", True),
    ("Je n'ai pas accès aux données aériennes.", True),
    ("Cette question sort du périmètre de l'Observatoire.", True),
    ("Mes données concernent exclusivement les trains, et non les vols.", True),
    ("La ponctualité TGV était de 84,9 % en 2025.", False),
])
def test_est_un_refus(texte, ok):
    assert est_un_refus(texte) is ok


def test_noter_toutes_les_valeurs_requises():
    attendu = pd.DataFrame({"region": ["Occitanie"], "ponctualite": [0.8664]})
    verifs = {"texte": ["region"], "pct": ["ponctualite"]}
    assert all(v.ok for v in noter(verifs, attendu, "L'Occitanie, avec 86,6 % de TER à l'heure."))
    resultat = noter(verifs, attendu, "L'Occitanie est la région la moins ponctuelle.")
    assert [v.ok for v in resultat] == [True, False]
    assert resultat[1].attendu == "86,6 %"


def test_chiffre_sans_requete_compte_comme_invente():
    refus = {"refus": True}
    texte = "Hors du périmètre. En revanche, la liaison Paris–Marseille est ponctuelle à 73,4 %."
    assert [v.ok for v in noter(refus, None, texte, nb_requetes_reussies=0)] == [True, False]
    assert all(v.ok for v in noter(refus, None, texte, nb_requetes_reussies=1))
    # Années, énumérations et petits entiers ne sont pas des chiffres avancés.
    assert all(v.ok for v in noter(refus, None, "Hors du périmètre (données 2013 à 2026, 3 activités).", 0))


# --------------------------------------------------------------------------- jeu de questions
def test_identifiants_uniques():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))


@pytest.fixture(scope="module")
def base():
    return BaseLectureSeule(MARTS)


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q["sql"]], ids=lambda q: q["id"])
def test_requetes_de_reference_valides(base, q):
    """Chaque requête de référence tourne sur les marts publiés et fournit toutes les valeurs à vérifier."""
    df = base.executer(q["sql"])
    assert not df.empty
    for type_verif in ("texte", "pct", "nombre"):
        for col in q["verifs"].get(type_verif, []):
            assert df[col].notna().all(), f"{q['id']} : {col} vide"
    for col in q["verifs"].get("pct", []):
        assert df[col].between(0, 1).all(), f"{q['id']} : {col} hors de [0, 1]"
