"""Archivage du temps réel : fusion des captures, clôture des journées, agrégats (sans réseau)."""
import pandas as pd
import pytest

import temps_reel
from scripts import archiver_temps_reel as arch

PARIS = "Europe/Paris"


def _t(h):
    return pd.Timestamp(f"2026-11-10 {h}", tz=PARIS)


def _trains(*lignes):
    """Lignes (numero, categorie, départ, retard, supprimé, arrivée constatée)."""
    return pd.DataFrame([{
        "id_train": f"id-{n}", "numero": n, "categorie": cat, "ligne": "", "origine": "A", "destination": "B",
        "depart_prevu": _t(dep), "arrivee_prevue": _t(dep) + pd.Timedelta(hours=1),
        "retard_terminus_min": retard, "supprime": supprime, "partiellement_supprime": False,
        "arrivee_constatee": constatee, "en_retard": retard >= 5,
    } for n, cat, dep, retard, supprime, constatee in lignes])


@pytest.fixture
def flux(monkeypatch):
    """Faux flux : chaque appel renvoie la capture suivante."""
    captures = []
    monkeypatch.setattr(temps_reel, "charger_trains", lambda: captures.pop(0))
    return captures


def test_observation_ecarte_les_trains_non_suivis():
    obs = arch.observation(_trains(("1", "TGV", "08:00", 0, False, False), ("2", "Autre", "08:00", 0, False, False)), _t("08:30"))
    assert obs["numero"].tolist() == ["1"] and obs["jour"].tolist() == ["2026-11-10"]


def test_jour_de_service_selon_le_depart_prevu_heure_de_paris():
    # Départ à 23 h 50 heure de Paris = 22 h 50 UTC : rattaché au 10 novembre, pas au 11.
    t = _trains(("1", "TER", "23:50", 0, False, False))
    assert arch.observation(t, _t("23:55"))["jour"].tolist() == ["2026-11-10"]


def test_fusion_garde_la_derniere_observation(tmp_path, flux):
    flux += [
        (_trains(("1", "TGV", "08:00", 0, False, False)), None, _t("07:30")),
        (_trains(("1", "TGV", "08:00", 12, False, False), ("2", "TER", "09:00", 0, False, False)), None, _t("07:45")),
    ]
    arch.capturer(tmp_path)
    arch.capturer(tmp_path)
    etat = pd.read_parquet(tmp_path / arch.FICHIER_ETAT).set_index("numero")
    assert etat.loc["1", "retard_terminus_min"] == 12 and etat.loc["1", "nb_obs"] == 2
    assert etat.loc["1", "premiere_obs"] == _t("07:30") and etat.loc["1", "derniere_obs"] == _t("07:45")
    assert etat.loc["2", "nb_obs"] == 1


def test_arrivee_constatee_jamais_remplacee_par_une_estimation(tmp_path, flux):
    flux += [
        (_trains(("1", "TGV", "08:00", 7, False, True)), None, _t("09:05")),
        (_trains(("1", "TGV", "08:00", 2, False, False)), None, _t("09:20")),  # incohérence du flux
    ]
    arch.capturer(tmp_path)
    arch.capturer(tmp_path)
    etat = pd.read_parquet(tmp_path / arch.FICHIER_ETAT).iloc[0]
    assert etat["retard_terminus_min"] == 7 and etat["arrivee_constatee"] and etat["nb_obs"] == 2


def test_capture_du_meme_horodatage_ignoree(tmp_path, flux):
    t = _trains(("1", "TGV", "08:00", 0, False, False))
    flux += [(t, None, _t("07:30")), (t, None, _t("07:30"))]
    assert arch.capturer(tmp_path)[0] == 1
    assert arch.capturer(tmp_path)[0] == 0
    assert pd.read_parquet(tmp_path / arch.FICHIER_ETAT)["nb_obs"].tolist() == [1]
    assert len(pd.read_parquet(tmp_path / arch.FICHIER_CAPTURES)) == 1


def test_cloture_seulement_des_journees_terminees(tmp_path, flux):
    flux += [(_trains(("1", "TGV", "08:00", 0, False, True)), None, _t("09:10"))]
    arch.capturer(tmp_path / "etat")
    # Le 11 à 11 h 59, les trains de nuit du 10 peuvent encore rouler : rien n'est clôturé.
    assert arch.cloturer(tmp_path / "etat", tmp_path / "sortie", pd.Timestamp("2026-11-11 11:59", tz=PARIS)) == []
    assert arch.cloturer(tmp_path / "etat", tmp_path / "sortie", pd.Timestamp("2026-11-11 12:00", tz=PARIS)) == ["2026-11-10"]
    assert (tmp_path / "sortie" / "trains_2026-11-10.parquet").exists()
    assert pd.read_parquet(tmp_path / "etat" / arch.FICHIER_ETAT).empty  # journée retirée de l'état
    # Une seconde clôture ne refait rien.
    assert arch.cloturer(tmp_path / "etat", tmp_path / "sortie", pd.Timestamp("2026-11-12", tz=PARIS)) == []


def test_agregats_du_jour():
    trains = arch.observation(_trains(
        ("1", "TGV", "08:00", 0, False, True),
        ("2", "TGV", "09:00", 4.9, False, True),
        ("3", "TGV", "10:00", 5, False, True),
        ("4", "TGV", "11:00", 25, False, False),
        ("5", "TGV", "12:00", 0, True, False),     # supprimé : ni à l'heure ni en retard
        ("6", "TER", "12:00", 0, False, True),
    ), _t("13:00")).drop(columns="jour")
    captures = pd.DataFrame({"horodatage": [_t("08:00"), _t("08:15"), pd.Timestamp("2026-11-11 00:05", tz=PARIS)]})
    a = arch.agreger(trains, captures, "2026-11-10").set_index("categorie")
    tgv = a.loc["TGV"]
    assert (tgv["nb_trains"], tgv["nb_trains_supprimes"], tgv["nb_trains_circules"], tgv["nb_trains_retard"]) == (5, 1, 4, 2)
    assert tgv["taux_ponctualite"] == 0.5
    assert tgv["retard_moyen_trains_retard_min"] == 15
    assert tgv["part_arrivees_constatees"] == 0.75
    assert tgv["nb_captures"] == 2  # la capture du 11 ne compte pas pour le 10
    assert tgv["couverture"] == pytest.approx(2 / 96)
    assert a.loc["TER", "taux_ponctualite"] == 1


def test_recloture_d_une_journee_remplace_ses_agregats(tmp_path):
    sortie = tmp_path / "sortie"
    sortie.mkdir()
    ancien = pd.DataFrame({"jour": ["2026-11-09", "2026-11-10"], "categorie": ["TGV", "TGV"], "taux_ponctualite": [0.9, 0.1]})
    ancien.to_parquet(sortie / arch.FICHIER_JOURS)
    etat = tmp_path / "etat"
    etat.mkdir()
    arch.observation(_trains(("1", "TGV", "08:00", 0, False, True)), _t("09:00")).to_parquet(etat / arch.FICHIER_ETAT)
    arch.cloturer(etat, sortie, pd.Timestamp("2026-11-12", tz=PARIS))
    jours = pd.read_parquet(sortie / arch.FICHIER_JOURS)
    assert jours["jour"].tolist() == ["2026-11-09", "2026-11-10"]
    assert jours.set_index("jour").loc["2026-11-10", "taux_ponctualite"] == 1
