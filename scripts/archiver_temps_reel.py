"""Archivage du flux temps réel SNCF pour mesurer la ponctualité jour par jour.

Le flux SIRI Lite est une fenêtre glissante : un train y apparaît environ une heure avant son
départ et disparaît une dizaine de minutes après son arrivée. On le capture donc souvent
(toutes les 15 minutes via GitHub Actions) et on garde, pour chaque train, sa dernière
observation : le retard constaté au terminus s'il a été vu arrivé, sinon le dernier retard estimé.

    python -m scripts.archiver_temps_reel capturer --etat DOSSIER      # une capture, fusionnée dans l'état
    python -m scripts.archiver_temps_reel cloturer --etat DOSSIER --sortie DOSSIER

`cloturer` traite les journées terminées (jour de départ prévu, clôturé le lendemain à midi
pour laisser arriver les trains de nuit) : détail train par train dans `trains_AAAA-MM-JJ.parquet`
(publié en asset de release, hors du dépôt) et agrégats ajoutés à `ponctualite_jour.parquet`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import temps_reel  # noqa: E402

FUSEAU = "Europe/Paris"
CAPTURES_PAR_JOUR = 96          # une toutes les 15 minutes
HEURE_CLOTURE = pd.Timedelta(hours=36)  # jour J clôturé à J+1 12 h
CLE = ["jour", "id_train"]
COLONNES = ["jour", "id_train", "numero", "categorie", "origine", "destination", "depart_prevu",
            "arrivee_prevue", "retard_terminus_min", "supprime", "partiellement_supprime",
            "arrivee_constatee", "premiere_obs", "derniere_obs", "nb_obs"]
FICHIER_ETAT, FICHIER_CAPTURES, FICHIER_JOURS = "trains_en_cours.parquet", "captures.parquet", "ponctualite_jour.parquet"


# --------------------------------------------------------------------------- capture
def observation(trains: pd.DataFrame, horodatage: pd.Timestamp) -> pd.DataFrame:
    """Trains d'une capture, au format de l'état (activités suivies seulement)."""
    t = trains[trains["categorie"] != "Autre"].copy()
    if t.empty:
        return pd.DataFrame(columns=COLONNES)
    t["jour"] = t["depart_prevu"].dt.tz_convert(FUSEAU).dt.date.astype(str)
    t["premiere_obs"] = t["derniere_obs"] = horodatage
    t["nb_obs"] = 1
    return t[COLONNES]


def fusionner(etat: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par train : valeurs de la dernière observation, sauf qu'une arrivée constatée
    n'est jamais remplacée par une estimation plus récente."""
    if etat.empty:
        return obs.reset_index(drop=True)
    tout = pd.concat([etat, obs], ignore_index=True)
    premiere = tout.groupby(CLE)["premiere_obs"].min()
    nb = tout.groupby(CLE)["nb_obs"].sum()
    garde = (tout.sort_values(["arrivee_constatee", "derniere_obs"], kind="stable")
             .drop_duplicates(CLE, keep="last").set_index(CLE))
    garde["premiere_obs"], garde["nb_obs"] = premiere, nb
    return garde.reset_index()[COLONNES].sort_values(CLE, ignore_index=True)


def capturer(dossier_etat: Path) -> tuple[int, pd.Timestamp]:
    trains, _, horodatage = temps_reel.charger_trains()
    horodatage = horodatage or pd.Timestamp.now(tz=FUSEAU)
    dossier_etat.mkdir(parents=True, exist_ok=True)
    captures = _lire(dossier_etat / FICHIER_CAPTURES, ["horodatage", "nb_trains"])
    if (pd.to_datetime(captures["horodatage"], utc=True) == horodatage).any():
        return 0, horodatage  # flux pas encore rafraîchi depuis la capture précédente
    etat = _lire(dossier_etat / FICHIER_ETAT, COLONNES)
    obs = observation(trains, horodatage)
    fusionner(etat, obs).to_parquet(dossier_etat / FICHIER_ETAT, index=False)
    nouvelle = pd.DataFrame({"horodatage": [horodatage], "nb_trains": [len(obs)]})
    (nouvelle if captures.empty else pd.concat([captures, nouvelle], ignore_index=True)).to_parquet(
        dossier_etat / FICHIER_CAPTURES, index=False)
    return len(obs), horodatage


# --------------------------------------------------------------------------- clôture
def agreger(trains: pd.DataFrame, captures: pd.DataFrame, jour: str) -> pd.DataFrame:
    """Ponctualité d'une journée par activité, avec les indicateurs de fiabilité de la mesure."""
    debut = pd.Timestamp(jour, tz=FUSEAU)
    h = pd.to_datetime(captures["horodatage"], utc=True).dt.tz_convert(FUSEAU)
    nb_captures = int(((h >= debut) & (h < debut + pd.Timedelta(days=1))).sum())
    t = trains.assign(en_retard=lambda x: ~x["supprime"] & (x["retard_terminus_min"].fillna(0) >= temps_reel.SEUIL_RETARD_MIN))
    lignes = []
    for cat, g in t.groupby("categorie"):
        circules = g[~g["supprime"]]
        lignes.append({
            "jour": jour, "categorie": cat,
            "nb_trains": len(g), "nb_trains_supprimes": int(g["supprime"].sum()),
            "nb_trains_circules": len(circules), "nb_trains_retard": int(circules["en_retard"].sum()),
            "taux_ponctualite": 1 - circules["en_retard"].mean() if len(circules) else float("nan"),
            "retard_moyen_trains_retard_min": circules.loc[circules["en_retard"], "retard_terminus_min"].mean(),
            "part_arrivees_constatees": circules["arrivee_constatee"].mean() if len(circules) else float("nan"),
            "nb_captures": nb_captures, "couverture": min(nb_captures / CAPTURES_PAR_JOUR, 1.0),
        })
    return pd.DataFrame(lignes)


def cloturer(dossier_etat: Path, dossier_sortie: Path, maintenant: pd.Timestamp | None = None) -> list[str]:
    """Clôture les journées terminées ; renvoie la liste des journées traitées."""
    maintenant = maintenant or pd.Timestamp.now(tz=FUSEAU)
    etat = _lire(dossier_etat / FICHIER_ETAT, COLONNES)
    captures = _lire(dossier_etat / FICHIER_CAPTURES, ["horodatage", "nb_trains"])
    jours = sorted(j for j in etat["jour"].unique() if pd.Timestamp(j, tz=FUSEAU) + HEURE_CLOTURE <= maintenant)
    if not jours:
        return []
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    chemin_jours = dossier_sortie / FICHIER_JOURS
    historique = _lire(chemin_jours, [])
    for jour in jours:
        trains = etat[etat["jour"] == jour].drop(columns="jour").sort_values("depart_prevu")
        trains.to_parquet(dossier_sortie / f"trains_{jour}.parquet", index=False)
        nouveau = agreger(trains, captures, jour)
        historique = nouveau if historique.empty else pd.concat(
            [historique[historique["jour"] != jour], nouveau], ignore_index=True)
    historique.sort_values(["jour", "categorie"]).to_parquet(chemin_jours, index=False)

    # L'état ne garde que les journées en cours ; les captures de plus de 3 jours sont inutiles.
    etat[~etat["jour"].isin(jours)].to_parquet(dossier_etat / FICHIER_ETAT, index=False)
    h = pd.to_datetime(captures["horodatage"], utc=True)
    captures[h >= maintenant.tz_convert("UTC") - pd.Timedelta(days=3)].to_parquet(dossier_etat / FICHIER_CAPTURES, index=False)
    return jours


def _lire(chemin: Path, colonnes: list[str]) -> pd.DataFrame:
    return pd.read_parquet(chemin) if chemin.exists() else pd.DataFrame(columns=colonnes)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["capturer", "cloturer"])
    p.add_argument("--etat", type=Path, required=True, help="dossier de l'état de la journée (cache CI)")
    p.add_argument("--sortie", type=Path, help="dossier des journées clôturées (cloturer)")
    args = p.parse_args()
    if args.action == "capturer":
        n, h = capturer(args.etat)
        print(f"Capture du {h:%Y-%m-%d %H:%M} : {n} trains")
    else:
        if not args.sortie:
            p.error("--sortie est requis pour cloturer")
        for jour in cloturer(args.etat, args.sortie):
            print(jour)  # lu par le workflow pour publier les fichiers


if __name__ == "__main__":
    main()
