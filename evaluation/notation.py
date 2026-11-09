"""Notation automatique et déterministe d'une réponse de l'assistant (pas de LLM juge).

Une réponse est juste si elle contient toutes les valeurs attendues : chaque taux à 0,15 point
près, chaque libellé (liaison, région, mois…), chaque valeur brute à 0,5 % près. Une question
hors périmètre est juste si l'assistant dit qu'il ne peut pas y répondre.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

TOLERANCE_PCT = 0.15     # en points de pourcentage (l'assistant arrondit à une décimale)
TOLERANCE_NOMBRE = 0.005  # relative

_NOMBRE = re.compile(r"(?<![\d,.])-?(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:[,.]\d+)?")
_REFUS = re.compile(
    r"ne (dispose|contien|couvr|permet|port|concern|fourni|propos|peu)\w*"
    r"|pas (de donnee|d'information|acces|disponible|dans (les|mes|le perimetre))"
    r"|hors (du |de mon )?perimetre|sort (du|de mon|de son) (cadre|perimetre)|aucune donnee"
    r"|ne sont pas (couvert|disponible|inclus)|exclusivement|n'(ai|est|y a) pas")
# Années (2019) et numéros d'ordre (1., 2.) ne comptent pas comme des chiffres avancés.
_ANNEE = re.compile(r"^(19|20)\d\d$")


@dataclass
class Verification:
    attendu: str
    ok: bool


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, tirets et apostrophes typographiques unifiés."""
    t = re.sub(r"[’`]", "'", str(texte))
    t = re.sub(r"[-–—_/]", " ", t)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def extraire_nombres(texte: str) -> list[float]:
    """Nombres écrits à la française ou à l'anglaise : « 84,9 », « 434 624 », « 0.849 »."""
    nombres = []
    for brut in _NOMBRE.findall(texte):
        brut = re.sub(r"[   ]", "", brut).replace(",", ".")
        try:
            nombres.append(float(brut))
        except ValueError:
            pass
    return nombres


def contient_pourcentage(texte: str, taux: float) -> bool:
    """`taux` entre 0 et 1, cherché en pourcentage (84,9) ou en fraction (0,849)."""
    cible = 100 * taux
    return any(abs(x - cible) <= TOLERANCE_PCT or (x < 1.5 and abs(100 * x - cible) <= TOLERANCE_PCT)
               for x in extraire_nombres(texte))


def contient_nombre(texte: str, valeur: float) -> bool:
    nombres = extraire_nombres(texte)
    if any(abs(x - valeur) <= max(TOLERANCE_NOMBRE * abs(valeur), 0.05) for x in nombres):
        return True
    # « 434 600 trains » écrit « 434,6 milliers » / « 0,43 million » : tolérer les ordres de grandeur.
    t = normaliser(texte)
    for x in nombres:
        for mot, facteur in (("million", 1e6), ("milliers", 1e3), ("mille", 1e3)):
            if mot in t and abs(x * facteur - valeur) <= 0.01 * abs(valeur):
                return True
    return False


def contient_texte(texte: str, libelle: str) -> bool:
    """Un libellé de liaison « A → B » est trouvé si A et B apparaissent tous les deux."""
    t = normaliser(texte)
    return all(normaliser(partie) in t for partie in str(libelle).split("→") if partie.strip())


def est_un_refus(texte: str) -> bool:
    return bool(_REFUS.search(normaliser(texte)))


def chiffres_avances(texte: str) -> list[float]:
    """Valeurs chiffrées d'une réponse, hors années et petits entiers (énumérations, « 5 liaisons »)."""
    return [x for x in extraire_nombres(texte)
            if not _ANNEE.match(f"{x:g}") and not (x.is_integer() and 0 <= x <= 12)]


def _format_pct(x: float) -> str:
    return f"{100 * x:.1f} %".replace(".", ",")


def _format_nombre(x: float) -> str:
    return f"{x:,.1f}".replace(",", " ").replace(".", ",").removesuffix(",0")


def noter(verifs: dict, attendu: pd.DataFrame | None, reponse: str,
          nb_requetes_reussies: int | None = None) -> list[Verification]:
    """Liste des vérifications (une par valeur attendue). La question est réussie si toutes passent.

    Si `nb_requetes_reussies` est fourni, on vérifie aussi qu'aucun chiffre n'est avancé sans
    requête réussie : un chiffre qui ne vient pas des données est inventé."""
    resultats = []
    if nb_requetes_reussies == 0 and chiffres_avances(reponse):
        resultats.append(Verification("aucun chiffre sans requête", False))
    if verifs.get("refus"):
        return [Verification("refus (hors périmètre)", est_un_refus(reponse))] + resultats
    if attendu is None or attendu.empty:
        raise ValueError("Requête de référence sans résultat.")
    for _, ligne in attendu.iterrows():
        for col in verifs.get("texte", []):
            resultats.append(Verification(str(ligne[col]), contient_texte(reponse, ligne[col])))
        for col in verifs.get("pct", []):
            v = float(ligne[col])
            resultats.append(Verification(_format_pct(v), not math.isnan(v) and contient_pourcentage(reponse, v)))
        for col in verifs.get("nombre", []):
            v = float(ligne[col])
            resultats.append(Verification(_format_nombre(v), not math.isnan(v) and contient_nombre(reponse, v)))
    return resultats
