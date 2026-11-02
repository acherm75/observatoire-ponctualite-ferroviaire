"""Prévision du taux de retard d'une liaison pour le mois suivant (XGBoost).

Cible : taux de retard à l'arrivée = 1 - taux de ponctualité, par liaison et par mois.
Variables : retards passés (t-1, t-2, t-3, t-12), moyennes glissantes, saisonnalité,
niveau historique de la liaison, normales météo du mois (moyenne des années passées,
car la météo réelle du mois à prévoir est inconnue au moment de la prévision).

Évaluation : découpage temporel (entraînement < 2025, test >= 2025), comparé à deux
références simples : "même valeur que le mois dernier" et "moyenne des 3 derniers mois".
"""
import json
import logging

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor

from ingestion.config import DATA_DIR, DUCKDB_PATH

log = logging.getLogger(__name__)
TEST_START = pd.Timestamp("2025-01-01")
FEATURES = [
    "lag_1", "lag_2", "lag_3", "lag_12", "roll_3", "roll_12", "delta_1",
    "num_mois", "est_tgv", "est_international", "moyenne_liaison",
    "normale_pluie", "normale_gel", "normale_chaleur", "duree_moyenne_min", "log_trains",
]


def load() -> pd.DataFrame:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    df = con.execute("""
        select f.liaison_id, f.mois, f.activite, l.type_service, l.duree_moyenne_min,
               f.nb_trains_circules, 1 - f.taux_ponctualite as taux_retard,
               f.meteo_precipitations_mm, f.meteo_jours_gel, f.meteo_jours_chaleur
        from marts.fct_regularite_liaison_mois f
        join marts.dim_liaison l using (liaison_id)
        order by liaison_id, mois
    """).df()
    con.close()
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    # Grille complète liaison x mois (+1 mois à prévoir) pour des décalages fiables.
    last = df["mois"].max()
    frames = []
    for lid, g in df.groupby("liaison_id"):
        idx = pd.date_range(g["mois"].min(), last + pd.offsets.MonthBegin(1), freq="MS")
        g = g.set_index("mois").reindex(idx)
        g.index.name = "mois"
        g["liaison_id"] = lid
        for c in ["activite", "type_service", "duree_moyenne_min"]:
            g[c] = g[c].ffill().bfill()
        frames.append(g.reset_index())
    d = pd.concat(frames, ignore_index=True)

    s = d.groupby("liaison_id")["taux_retard"]
    for k in (1, 2, 3, 12):
        d[f"lag_{k}"] = s.shift(k)
    d["roll_3"] = s.transform(lambda x: x.shift(1).rolling(3, min_periods=2).mean())
    d["roll_12"] = s.transform(lambda x: x.shift(1).rolling(12, min_periods=6).mean())
    d["delta_1"] = d["lag_1"] - d["lag_2"]
    d["moyenne_liaison"] = s.transform(lambda x: x.shift(1).expanding(min_periods=3).mean())
    d["log_trains"] = np.log1p(d.groupby("liaison_id")["nb_trains_circules"].shift(1))
    d["num_mois"] = d["mois"].dt.month
    d["est_tgv"] = (d["activite"] == "TGV").astype(int)
    d["est_international"] = (d["type_service"] == "International").astype(int)

    # Normales météo : moyenne, pour la liaison et le mois calendaire, des années précédentes.
    d["annee"] = d["mois"].dt.year
    for src, dst in [("meteo_precipitations_mm", "normale_pluie"),
                     ("meteo_jours_gel", "normale_gel"), ("meteo_jours_chaleur", "normale_chaleur")]:
        d[dst] = (d.sort_values("mois").groupby(["liaison_id", "num_mois"])[src]
                  .transform(lambda x: x.shift(1).expanding().mean()))
    return d


def run() -> dict:
    d = build_features(load())
    hist = d[d["taux_retard"].notna() & d["lag_1"].notna()]
    train, test = hist[hist["mois"] < TEST_START], hist[hist["mois"] >= TEST_START]

    model = XGBRegressor(n_estimators=400, max_depth=4, learning_rate=0.04, subsample=0.8,
                         colsample_bytree=0.8, min_child_weight=5, random_state=42)
    model.fit(train[FEATURES], train["taux_retard"])
    pred = model.predict(test[FEATURES])

    metrics = {
        "periode_test": f"{test['mois'].min():%Y-%m} → {test['mois'].max():%Y-%m}",
        "nb_observations_test": int(len(test)),
        "mae_xgboost_pts": round(100 * mean_absolute_error(test["taux_retard"], pred), 2),
        "mae_mois_precedent_pts": round(100 * mean_absolute_error(test["taux_retard"], test["lag_1"]), 2),
        "mae_moyenne_3_mois_pts": round(100 * mean_absolute_error(
            test["taux_retard"], test["roll_3"].fillna(test["lag_1"])), 2),
        "importance_variables": dict(sorted(
            ((f, round(float(v), 3)) for f, v in zip(FEATURES, model.feature_importances_)),
            key=lambda kv: -kv[1])),
    }
    log.info("ML : %s", {k: v for k, v in metrics.items() if k != "importance_variables"})

    # Ré-entraînement sur tout l'historique puis prévision du mois suivant.
    model.fit(hist[FEATURES], hist["taux_retard"])
    next_month = d["mois"].max()
    fut = d[(d["mois"] == next_month) & d["lag_1"].notna()].copy()
    fut["taux_retard_prevu"] = np.clip(model.predict(fut[FEATURES]), 0, 1)
    out = fut[["liaison_id", "mois", "taux_retard_prevu", "lag_1", "roll_12"]].rename(
        columns={"lag_1": "taux_retard_mois_precedent", "roll_12": "taux_retard_moyen_12_mois"})
    # Backtest conservé pour l'app (réel vs prévu sur la période de test).
    backtest = test[["liaison_id", "mois", "taux_retard"]].assign(taux_retard_prevu=pred)

    con = duckdb.connect(str(DUCKDB_PATH))
    con.execute("create schema if not exists marts")
    con.execute("create or replace table marts.ml_prevision_mois_suivant as select * from out")
    con.execute("create or replace table marts.ml_backtest as select * from backtest")
    con.close()
    (DATA_DIR / "marts").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "marts" / "ml_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    log.info("ML : %d prévisions pour %s", len(out), f"{next_month:%Y-%m}")
    return metrics


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(json.dumps(run(), indent=2, ensure_ascii=False))
