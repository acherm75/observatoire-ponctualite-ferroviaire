"""Observatoire de la ponctualité ferroviaire en France — application Streamlit.

Lit les tables exportées par le pipeline (data/marts/*.parquet).
Lancement local :  streamlit run app/streamlit_app.py
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

MARTS = Path(__file__).resolve().parents[1] / "data" / "marts"
COULEURS = {"TGV": "#2563eb", "TER": "#16a34a", "Intercités": "#d97706"}

st.set_page_config(page_title="Ponctualité ferroviaire", page_icon="🚆", layout="wide")


@st.cache_resource
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    for f in MARTS.glob("*.parquet"):
        c.execute(f"create view {f.stem} as select * from read_parquet('{f}')")
    return c


@st.cache_data
def q(sql: str) -> pd.DataFrame:
    return con().execute(sql).df()


def pct(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{100 * x:.1f} %".replace(".", ",")


# ---------------------------------------------------------------- en-tête
st.title("🚆 Observatoire de la ponctualité ferroviaire")
st.caption(
    "Données ouvertes SNCF (régularité TGV, TER, Intercités) croisées avec Météo-France. "
    "Une liaison est « à l'heure » si le train arrive avec moins de 5 min de retard "
    "(seuils AQST, plus larges pour les longs trajets)."
)

nat = q("select * from mart_ponctualite_nationale_mois order by mois")
dernier = nat.groupby("activite")["mois"].max()

cols = st.columns(3)
for col, act in zip(cols, ["TGV", "TER", "Intercités"]):
    m = dernier[act]
    cur = nat[(nat.activite == act) & (nat.mois == m)].taux_ponctualite.iloc[0]
    prev = nat[(nat.activite == act) & (nat.mois == m - pd.DateOffset(years=1))].taux_ponctualite
    delta = None if prev.empty else f"{100 * (cur - prev.iloc[0]):+.1f} pts vs N-1".replace(".", ",")
    col.metric(f"{act} · {m:%m/%Y}", pct(cur), delta)

onglets = st.tabs(["Tendance", "Liaisons", "Causes des retards", "Régions TER", "Effet météo", "Prévisions",
                   "🤖 Assistant IA"])

# ---------------------------------------------------------------- tendance
with onglets[0]:
    lisse = st.toggle("Moyenne glissante 12 mois", value=True)
    d = nat.copy()
    if lisse:
        d["taux_ponctualite"] = d.groupby("activite")["taux_ponctualite"].transform(
            lambda s: s.rolling(12, min_periods=12).mean())
    fig = px.line(d, x="mois", y="taux_ponctualite", color="activite", color_discrete_map=COULEURS,
                  labels={"mois": "", "taux_ponctualite": "Ponctualité", "activite": ""})
    fig.update_yaxes(tickformat=".0%")
    fig.add_vrect(x0="2020-03-01", x1="2021-06-01", fillcolor="grey", opacity=0.1, line_width=0,
                  annotation_text="Covid", annotation_position="top left")
    st.plotly_chart(fig, width="stretch")

    saison = q("""
        select n.activite, d.nom_mois, d.num_mois, avg(n.taux_ponctualite) as taux
        from mart_ponctualite_nationale_mois n join dim_date d using (mois)
        where not d.est_periode_covid group by all order by num_mois""")
    fig = px.line(saison, x="nom_mois", y="taux", color="activite", markers=True,
                  color_discrete_map=COULEURS, title="Saisonnalité (hors période Covid)",
                  labels={"nom_mois": "", "taux": "Ponctualité moyenne", "activite": ""})
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
    st.info("Les mois d'été et de fin d'automne sont les plus difficiles : chaleur, affluence, "
            "chute des feuilles et premières intempéries.")

# ---------------------------------------------------------------- liaisons
with onglets[1]:
    c1, c2, c3 = st.columns(3)
    act = c1.selectbox("Activité", ["TGV", "Intercités"])
    annees = sorted(q("select distinct year(mois) a from fct_regularite_liaison_mois").a, reverse=True)
    annee = c2.selectbox("Année", annees)
    min_trains = c3.slider("Trains minimum sur l'année", 100, 3000, 500, step=100)
    classement = q(f"""
        select l.libelle_liaison as liaison, sum(f.nb_trains_circules) as trains,
               1 - sum(f.nb_trains_retard_arrivee) / sum(f.nb_trains_circules) as ponctualite,
               sum(f.nb_trains_annules) / sum(f.nb_trains_prevus) as annulation
        from fct_regularite_liaison_mois f join dim_liaison l using (liaison_id)
        where f.activite = '{act}' and year(f.mois) = {annee} and not f.est_incoherent
        group by 1 having sum(f.nb_trains_circules) >= {min_trains}
        order by ponctualite""")
    a, b = st.columns(2)
    for col, titre, data in [(a, "Les 10 liaisons les moins ponctuelles", classement.head(10)),
                             (b, "Les 10 plus ponctuelles", classement.tail(10).iloc[::-1])]:
        col.subheader(titre)
        col.dataframe(data.style.format({"ponctualite": "{:.1%}", "annulation": "{:.1%}", "trains": "{:,.0f}"}),
                      hide_index=True, width="stretch")

    choix = st.selectbox("Détail d'une liaison", classement.liaison)
    if choix:
        det = q(f"""select f.mois, f.taux_ponctualite, f.retard_moyen_trains_retard_min
                    from fct_regularite_liaison_mois f join dim_liaison l using (liaison_id)
                    where l.libelle_liaison = '{choix.replace("'", "''")}' and f.activite = '{act}'
                    order by mois""")
        fig = px.line(det, x="mois", y="taux_ponctualite", labels={"mois": "", "taux_ponctualite": "Ponctualité"})
        fig.update_traces(line_color=COULEURS[act])
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- causes
with onglets[2]:
    st.caption("TGV uniquement : part de chaque cause dans les retards de plus de 15 minutes.")
    st.warning("Rupture de série en mai 2026 : la répartition change brutalement (probable changement "
               "de nomenclature d'imputation à la source). Comparer les années jusqu'en 2025.")
    causes = q("""
        select year(f.mois) as annee, c.libelle_cause as cause, c.responsable,
               sum(f.nb_trains_retard_imputes) as trains
        from fct_causes_retard_mois f join dim_cause c using (code_cause)
        group by all order by annee""")
    causes["part"] = causes.trains / causes.groupby("annee").trains.transform("sum")
    fig = px.bar(causes, x="annee", y="part", color="cause", labels={"annee": "", "part": "", "cause": ""})
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch")

    resp = causes.groupby("responsable").trains.sum().sort_values(ascending=False)
    st.markdown("**Qui est responsable ?** " + " · ".join(
        f"{r} : {pct(v / resp.sum())}" for r, v in resp.items()))

# ---------------------------------------------------------------- régions
with onglets[3]:
    reg = q("""select region, year(mois) as annee,
                      1 - sum(nb_trains_retard_arrivee) / sum(nb_trains_circules) as ponctualite
               from fct_regularite_ter_mois group by all""")
    pivot = reg.pivot(index="region", columns="annee", values="ponctualite")
    pivot = pivot.loc[pivot.mean(axis=1).sort_values().index]
    fig = px.imshow(pivot, color_continuous_scale="RdYlGn", aspect="auto", text_auto=".0%",
                    labels=dict(color="Ponctualité", x="", y=""))
    fig.update_layout(height=520)
    st.plotly_chart(fig, width="stretch")
    st.caption("Avant 2018, certaines régions actuelles ne sont couvertes que partiellement "
               "(données publiées par ancienne région).")

# ---------------------------------------------------------------- météo
with onglets[4]:
    st.caption("Chaque point = une région TER sur un mois. Météo : moyenne des stations Météo-France de la région.")
    var = st.radio("Indicateur météo", {
        "meteo_jours_gel": "Jours de gel", "meteo_jours_chaleur": "Jours ≥ 30 °C",
        "meteo_precipitations_mm": "Cumul de pluie (mm)", "meteo_jours_vent_fort": "Jours de vent fort"
    }.items(), format_func=lambda kv: kv[1], horizontal=True)[0]
    met = q(f"""select f.region, f.mois, f.taux_ponctualite, f.{var} as meteo
                from fct_regularite_ter_mois f join dim_date d using (mois)
                where not d.est_periode_covid and f.{var} is not null""")
    met["ecart"] = met.taux_ponctualite - met.groupby("region").taux_ponctualite.transform("mean")
    fig = px.scatter(met, x="meteo", y="ecart", trendline="ols", opacity=0.35, hover_data=["region", "mois"],
                     labels={"meteo": "", "ecart": "Écart à la ponctualité moyenne de la région"})
    fig.update_yaxes(tickformat="+.0%")
    st.plotly_chart(fig, width="stretch")
    r = met[["meteo", "ecart"]].corr().iloc[0, 1]
    st.metric("Corrélation", f"{r:+.2f}".replace(".", ","))
    st.caption("L'écart à la moyenne de la région neutralise les différences structurelles "
               "entre régions. Corrélation ≠ causalité : l'été cumule chaleur, travaux et affluence.")

# ---------------------------------------------------------------- prévisions
with onglets[5]:
    metrics_path = MARTS / "ml_metrics.json"
    if metrics_path.exists():
        m = json.loads(metrics_path.read_text())
        st.markdown(f"Modèle **XGBoost** testé sur {m['periode_test']} ({m['nb_observations_test']} liaisons-mois).")
        a, b, c = st.columns(3)
        a.metric("Erreur moyenne du modèle", f"{m['mae_xgboost_pts']} pts".replace(".", ","))
        b.metric("Référence « mois précédent »", f"{m['mae_mois_precedent_pts']} pts".replace(".", ","))
        gain = 1 - m["mae_xgboost_pts"] / m["mae_mois_precedent_pts"]
        c.metric("Gain", f"-{100 * gain:.0f} % d'erreur")

    prev = q("""select l.libelle_liaison as liaison, l.activite, p.mois,
                       p.taux_retard_prevu, p.taux_retard_mois_precedent, p.taux_retard_moyen_12_mois
                from ml_prevision_mois_suivant p join dim_liaison l using (liaison_id)
                order by taux_retard_prevu desc""")
    if not prev.empty:
        st.subheader(f"Taux de retard prévu pour {prev.mois.iloc[0]:%m/%Y}")
        st.dataframe(prev.drop(columns="mois").style.format({
            "taux_retard_prevu": "{:.1%}", "taux_retard_mois_precedent": "{:.1%}",
            "taux_retard_moyen_12_mois": "{:.1%}"}), hide_index=True, width="stretch")

# ---------------------------------------------------------------- assistant IA
def secret(nom: str, defaut=None):
    try:
        return st.secrets.get(nom, os.environ.get(nom, defaut))
    except Exception:  # pas de fichier secrets.toml
        return os.environ.get(nom, defaut)


@st.cache_resource
def assistant(fournisseurs: tuple):
    sys.path.insert(0, str(Path(__file__).parent))
    from agent import creer_assistant
    return creer_assistant(MARTS, list(fournisseurs))


@st.cache_resource
def compteur_global() -> dict:
    """Compteur partagé par tous les visiteurs (réinitialisé chaque jour ou au redémarrage)."""
    return {"jour": dt.date.today(), "n": 0}


EXEMPLES = [
    "Quelles sont les 5 liaisons TGV les moins ponctuelles en 2025 ?",
    "La ponctualité des TER en Bretagne s'améliore-t-elle depuis 2019 ?",
    "Quelle part des retards TGV est due au matériel roulant, année par année ?",
    "Les mois de canicule sont-ils moins ponctuels pour les TER ?",
]

with onglets[6]:
    fournisseur = secret("ASSISTANT_FOURNISSEUR", "gemini")
    cle = secret("ASSISTANT_CLE_API")
    quota_session = int(secret("ASSISTANT_QUESTIONS_PAR_SESSION", 10))
    quota_jour = int(secret("ASSISTANT_QUESTIONS_PAR_JOUR", 100))
    st.caption("Pose une question en français : l'IA écrit la requête SQL, l'exécute sur les données "
               "de l'observatoire (lecture seule), vérifie le résultat puis répond. Les requêtes sont affichées.")

    if not cle:
        st.info("L'assistant n'est pas configuré : ajoute `ASSISTANT_CLE_API` dans les secrets de l'app.")
    else:
        bot = assistant((
            (fournisseur, cle, secret("ASSISTANT_MODELE")),
            # Relais optionnel chez un autre fournisseur gratuit quand le premier est à court de quota
            (secret("ASSISTANT_SECOURS_FOURNISSEUR", "groq"), secret("ASSISTANT_SECOURS_CLE_API"),
             secret("ASSISTANT_SECOURS_MODELE")),
        ))
        ss = st.session_state
        ss.setdefault("chat", [])        # [{"question", "reponse"}]
        ss.setdefault("nb_questions", 0)

        cols = st.columns(len(EXEMPLES))
        clic = next((q for c, q in zip(cols, EXEMPLES) if c.button(q, width="stretch")), None)

        for echange in ss.chat:
            with st.chat_message("user"):
                st.markdown(echange["question"])
            with st.chat_message("assistant"):
                st.markdown(echange["reponse"].texte)
                for i, e in enumerate(echange["reponse"].etapes, 1):
                    with st.expander(f"Requête {i} · {e.objectif or 'SQL'}"):
                        st.code(e.sql, language="sql")
                        if e.erreur:
                            st.error(e.erreur)
                        elif e.resultat is not None:
                            st.dataframe(e.resultat, hide_index=True, width="stretch")

        saisie = st.chat_input("Ex. : quelle région TER est la plus ponctuelle en 2025 ?", max_chars=400)
        question = saisie or clic
        if question:
            g = compteur_global()
            if g["jour"] != dt.date.today():
                g.update(jour=dt.date.today(), n=0)
            if ss.nb_questions >= quota_session:
                st.warning(f"Limite de {quota_session} questions par visite atteinte (démo publique). "
                           "Recharge la page plus tard ou lance l'app en local.")
            elif g["n"] >= quota_jour:
                st.warning("Le quota quotidien de la démo est atteint. Reviens demain !")
            else:
                ss.nb_questions += 1
                g["n"] += 1
                historique = []
                for echange in ss.chat[-3:]:  # contexte court pour les questions de suivi
                    historique += [{"role": "user", "content": echange["question"]},
                                   {"role": "assistant", "content": echange["reponse"].texte}]
                with st.spinner("Analyse des données…"):
                    try:
                        rep = bot.repondre(question, historique)
                    except Exception as e:
                        import openai
                        from agent import QuotaEpuise
                        msg = ("Le quota gratuit du service d'IA est atteint pour le moment. Réessaie plus tard."
                               if isinstance(e, (QuotaEpuise, openai.RateLimitError, openai.APIConnectionError))
                               else "L'assistant a rencontré une erreur.")
                        st.error(msg)
                        rep = None
                if rep:
                    ss.chat.append({"question": question, "reponse": rep})
                    st.rerun()

        if ss.chat:
            st.caption(f"{ss.nb_questions}/{quota_session} questions utilisées pendant cette visite.")
            if st.button("Effacer la conversation"):
                ss.chat = []
                st.rerun()

st.divider()
st.caption("Sources : SNCF Open Data (ressources.data.sncf.com), Météo-France (meteo.data.gouv.fr). "
           "Pipeline : Python → DuckDB → dbt → XGBoost → Streamlit · Assistant IA : modèle gratuit (Gemini, Groq ou Mistral).")
