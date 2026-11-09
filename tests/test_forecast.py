"""Variables du modèle de prévision : aucune information du mois à prévoir ne doit fuiter."""
import numpy as np
import pandas as pd
import pytest

from ml.forecast import FEATURES, build_features


@pytest.fixture
def historique():
    rng = np.random.default_rng(0)
    lignes = []
    for lid, debut, activite in [("A", "2022-01-01", "TGV"), ("B", "2023-06-01", "Intercités")]:
        for m in pd.date_range(debut, "2024-12-01", freq="MS"):
            if lid == "A" and m == pd.Timestamp("2023-03-01"):
                continue  # mois manquant dans la source
            lignes.append({
                "liaison_id": lid, "mois": m, "activite": activite,
                "type_service": "National" if lid == "A" else None, "duree_moyenne_min": 120.0,
                "nb_trains_circules": rng.integers(50, 300), "taux_retard": rng.uniform(0.05, 0.3),
                "meteo_precipitations_mm": rng.uniform(0, 150), "meteo_jours_gel": rng.integers(0, 10),
                "meteo_jours_chaleur": rng.integers(0, 10),
            })
    return pd.DataFrame(lignes)


def test_grille_complete_et_mois_a_prevoir(historique):
    d = build_features(historique)
    a = d[d["liaison_id"] == "A"]
    assert a["mois"].tolist() == list(pd.date_range("2022-01-01", "2025-01-01", freq="MS"))
    assert a.set_index("mois").loc["2023-03-01", "taux_retard"] != a.set_index("mois").loc["2023-03-01", "taux_retard"]  # NaN
    futur = d[d["mois"] == "2025-01-01"]
    assert len(futur) == 2 and futur["taux_retard"].isna().all() and futur["lag_1"].notna().all()


def test_decalages(historique):
    d = build_features(historique).set_index(["liaison_id", "mois"])
    src = historique.set_index(["liaison_id", "mois"])["taux_retard"]
    m = pd.Timestamp("2024-06-01")
    assert d.loc[("A", m), "lag_1"] == src[("A", m - pd.DateOffset(months=1))]
    assert d.loc[("A", m), "lag_12"] == src[("A", m - pd.DateOffset(months=12))]
    assert d.loc[("A", pd.Timestamp("2023-04-01")), "lag_1"] != d.loc[("A", pd.Timestamp("2023-04-01")), "lag_1"]  # trou -> NaN


def test_les_liaisons_ne_se_melangent_pas(historique):
    d = build_features(historique)
    premier_b = d[d["liaison_id"] == "B"].iloc[0]
    assert np.isnan(premier_b["lag_1"]) and np.isnan(premier_b["moyenne_liaison"])
    assert (d.loc[d["liaison_id"] == "B", "est_tgv"] == 0).all()


@pytest.mark.parametrize("mois_cible", ["2023-01-01", "2024-07-01", "2024-12-01"])
def test_pas_de_fuite_du_futur(historique, mois_cible):
    """Modifier la cible et la météo d'un mois (et des suivants) ne doit changer aucune variable de ce mois."""
    mois_cible = pd.Timestamp(mois_cible)
    reference = build_features(historique)
    modifie = historique.copy()
    futur = modifie["mois"] >= mois_cible
    for col in ["taux_retard", "nb_trains_circules", "meteo_precipitations_mm", "meteo_jours_gel", "meteo_jours_chaleur"]:
        modifie.loc[futur, col] = modifie.loc[futur, col] * 7 + 3
    modifie = build_features(modifie)

    def variables(d):
        return d[d["mois"] == mois_cible].set_index("liaison_id")[FEATURES]

    pd.testing.assert_frame_equal(variables(reference), variables(modifie))


def test_normales_meteo_des_annees_precedentes_uniquement(historique):
    d = build_features(historique).set_index(["liaison_id", "mois"])
    src = historique.set_index(["liaison_id", "mois"])["meteo_precipitations_mm"]
    attendu = np.mean([src[("A", pd.Timestamp("2022-06-01"))], src[("A", pd.Timestamp("2023-06-01"))]])
    assert d.loc[("A", pd.Timestamp("2024-06-01")), "normale_pluie"] == pytest.approx(attendu)
