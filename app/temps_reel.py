"""Temps réel SNCF (TGV, Intercités, TER, Transilien) depuis le Point d'accès national
transport.data.gouv.fr — flux SIRI Lite publics, sans clé d'API.

- EstimatedTimetable : horaires prévus / estimés de chaque arrêt des trains en circulation ;
- SituationExchange : messages de perturbation (travaux, incidents…).
"""
from __future__ import annotations

import datetime as dt
import html
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests

URL_HORAIRES = "https://proxy.transport.data.gouv.fr/resource/sncf-siri-lite-estimated-timetable"
URL_PERTURBATIONS = "https://proxy.transport.data.gouv.fr/resource/sncf-siri-lite-situation-exchange"
NS = {"s": "http://www.siri.org.uk/siri"}
SEUIL_RETARD_MIN = 5  # même définition que les statistiques mensuelles

# Catégories de produit SIRI -> libellé grand public
CATEGORIES = {
    "highSpeedRail": "TGV",
    "longDistance": "Intercités",
    "interregionalRail": "TER",
    "regionalRail": "TER",
    "regionalCoach": "TER",
    "tramTrain": "TER",
    "railReplacementCoach": "TER",
    "railShuttle": "TER",
    "suburbanRailway": "Transilien / RER",
}


def _telecharger(url: str) -> ET.Element:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return ET.fromstring(r.content)


def _heure(x: str | None) -> pd.Timestamp | None:
    return pd.Timestamp(x).tz_convert("Europe/Paris") if x else None


def _retard_min(prevu, estime) -> float | None:
    if prevu is None or estime is None:
        return None
    return (estime - prevu).total_seconds() / 60


def charger_trains() -> tuple[pd.DataFrame, pd.DataFrame, dt.datetime]:
    """Renvoie (trains, arrets, horodatage) :
    - trains : une ligne par train (origine, destination, retard au terminus, suppression) ;
    - arrets : une ligne par passage en gare (horaires prévus/estimés, quai, retard).
    """
    racine = _telecharger(URL_HORAIRES)
    horodatage = _heure(racine.findtext(".//s:ResponseTimestamp", None, NS))
    trains, arrets = [], []
    for j in racine.iter(f"{{{NS['s']}}}EstimatedVehicleJourney"):
        cat = (j.findtext("s:ProductCategoryRef", "", NS).split("::") + ["", ""])[1]
        numero = j.findtext("s:TrainNumbers/s:TrainNumberRef", "", NS)
        id_train = j.findtext("s:DatedVehicleJourneyRef", "", NS) or j.findtext(
            "s:FramedVehicleJourneyRef/s:DatedVehicleJourneyRef", "", NS)
        base = {
            "id_train": id_train or numero,
            "numero": numero,
            "categorie": CATEGORIES.get(cat, "Autre"),
            "ligne": j.findtext("s:PublishedLineName", "", NS),
            "origine": j.findtext("s:OriginName", "", NS),
            "destination": j.findtext("s:DestinationName", "", NS),
        }
        train_supprime = j.findtext("s:Cancellation", "", NS) == "true"
        appels = [(c, True) for c in j.iterfind("s:RecordedCalls/s:RecordedCall", NS)] + \
                 [(c, False) for c in j.iterfind("s:EstimatedCalls/s:EstimatedCall", NS)]
        for c, passe in appels:
            arr_p, arr_e = _heure(c.findtext("s:AimedArrivalTime", None, NS)), _heure(c.findtext("s:ExpectedArrivalTime", None, NS))
            dep_p, dep_e = _heure(c.findtext("s:AimedDepartureTime", None, NS)), _heure(c.findtext("s:ExpectedDepartureTime", None, NS))
            arrets.append({
                **base,
                "ordre": int(c.findtext("s:Order", "0", NS)),
                "gare": c.findtext("s:StopPointName", "", NS),
                "arrivee_prevue": arr_p, "depart_prevu": dep_p,
                "depart_estime": dep_e,
                "retard_arrivee_min": _retard_min(arr_p, arr_e),
                "retard_depart_min": _retard_min(dep_p, dep_e),
                "quai": c.findtext("s:DeparturePlatformName", None, NS) or c.findtext("s:ArrivalPlatformName", None, NS),
                "arret_supprime": train_supprime or c.findtext("s:Cancellation", "", NS) == "true",
                "deja_passe": passe,
            })
        if appels:
            dernier = arrets[-1]
            trains.append({
                **base,
                "depart_prevu": arrets[-len(appels)]["depart_prevu"],
                "arrivee_prevue": dernier["arrivee_prevue"],
                "retard_terminus_min": dernier["retard_arrivee_min"],
                # Terminus déjà passé : retard constaté et non plus estimé.
                "arrivee_constatee": dernier["deja_passe"],
                "supprime": train_supprime,
                "partiellement_supprime": not train_supprime and any(a["arret_supprime"] for a in arrets[-len(appels):]),
            })
    trains = pd.DataFrame(trains)
    if not trains.empty:
        trains["en_retard"] = trains["retard_terminus_min"].fillna(0) >= SEUIL_RETARD_MIN
    return trains, pd.DataFrame(arrets), horodatage


def _texte(e: ET.Element, balise: str) -> str:
    """Texte français d'une balise multilingue, débarrassé du HTML."""
    noeuds = e.findall(f"s:{balise}", NS)
    fr = next((n for n in noeuds if n.get("{http://www.w3.org/XML/1998/namespace}lang", "").upper() == "FR"), None)
    brut = (fr if fr is not None else (noeuds[0] if noeuds else None))
    if brut is None or not brut.text:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(brut.text))).strip()


def charger_perturbations() -> pd.DataFrame:
    """Messages de perturbation valides à l'instant présent."""
    racine = _telecharger(URL_PERTURBATIONS)
    maintenant = pd.Timestamp.now(tz="Europe/Paris")
    lignes = []
    for s in racine.iter(f"{{{NS['s']}}}PtSituationElement"):
        debut = _heure(s.findtext("s:ValidityPeriod/s:StartTime", None, NS))
        fin = _heure(s.findtext("s:ValidityPeriod/s:EndTime", None, NS))
        if (debut and debut > maintenant) or (fin and fin < maintenant):
            continue
        lignes.append({
            "gravite": s.findtext("s:Severity", "", NS),
            "resume": _texte(s, "Summary"),
            "description": _texte(s, "Description"),
            "debut": debut, "fin": fin,
        })
    return pd.DataFrame(lignes).drop_duplicates(["resume", "description"]) if lignes else pd.DataFrame(
        columns=["gravite", "resume", "description", "debut", "fin"])
