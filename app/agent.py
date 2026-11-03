"""Assistant « pose une question sur la ponctualité » (text-to-SQL, modèle gratuit).

Fonctionne avec toute API compatible OpenAI ; trois fournisseurs à offre gratuite sont
préconfigurés (Google Gemini, Groq, Mistral), au choix dans les secrets de l'app.

Principe : le modèle reçoit la description des tables, écrit une requête SQL DuckDB,
l'exécute via l'outil `run_sql` (lecture seule), lit le résultat, corrige si besoin,
puis répond en français en s'appuyant uniquement sur les chiffres obtenus.

Sécurité : base en mémoire, accès aux fichiers désactivé et configuration verrouillée
après chargement ; une seule instruction SELECT par appel ; résultat tronqué ; délai max.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import openai
import pandas as pd

MAX_TOURS = 6            # appels au modèle par question
MAX_LIGNES = 200         # lignes renvoyées au modèle par requête
DELAI_SQL_S = 10         # durée max d'une requête
ATTENTES_QUOTA_MAX = 3   # attentes autorisées quand la limite gratuite par minute est atteinte

# Fournisseurs à offre gratuite (API compatibles OpenAI). Le modèle reste modifiable dans les secrets.
FOURNISSEURS = {
    "gemini":  {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "modele": "gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3.5-flash"},
    "groq":    {"base_url": "https://api.groq.com/openai/v1", "modele": "openai/gpt-oss-120b,llama-3.3-70b-versatile"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "modele": "mistral-small-latest"},
}

NOTES_METIER = """\
Définitions et pièges à connaître :
- Ponctualité = 1 - trains en retard à l'arrivée / trains ayant circulé. Pour agréger plusieurs
  mois ou liaisons, recalculer à partir des sommes (ne jamais faire la moyenne des taux).
- Un train est « en retard » au-delà de 5 min (seuils AQST plus larges pour les longs trajets TGV).
- fct_regularite_liaison_mois : TGV (depuis 2018) et Intercités (depuis 2014), une ligne par liaison
  et par mois. Exclure `est_incoherent = true` des agrégats (lignes incohérentes de la source).
  `activite` vaut 'TGV' ou 'Intercités'. Les colonnes meteo_* sont la météo moyenne des
  départements de départ et d'arrivée.
- dim_liaison.libelle_liaison est lisible (« Paris Gare de Lyon → Lyon Part-Dieu ») ; type_service
  vaut 'National' ou 'International' (TGV). Chercher une gare avec ILIKE '%lyon%' plutôt qu'égalité.
- fct_causes_retard_mois : TGV uniquement, part de chaque cause dans les retards > 15 min.
  Pour une répartition, sommer nb_trains_retard_imputes. Rupture de nomenclature en mai 2026 :
  le signaler si la question porte sur l'évolution des causes en 2026.
- fct_regularite_ter_mois : TER par région actuelle (13 régions), depuis 2013. Avant 2018 certaines
  régions ne sont que partiellement couvertes (voir perimetres_source).
- mart_ponctualite_nationale_mois : totaux nationaux par activité (TGV, TER, Intercités) et par mois.
- Période Covid (mars 2020 – juin 2021) : dim_date.est_periode_covid ; souvent à exclure des tendances.
- ml_prevision_mois_suivant : prévision XGBoost du taux de RETARD (pas de ponctualité) du mois suivant.
- Les dernières données disponibles diffèrent selon l'activité : vérifier max(mois) avant de parler
  du « dernier mois ».
"""

SYSTEM_TEMPLATE = """\
Tu es l'assistant de l'Observatoire de la ponctualité ferroviaire, un projet construit sur les
données ouvertes SNCF (régularité TGV, TER, Intercités) et Météo-France.

Ta mission : répondre aux questions en français en interrogeant les données avec l'outil `run_sql`
(DuckDB, lecture seule). Règles :
- Appuie chaque chiffre de ta réponse sur un résultat de requête ; n'invente jamais de valeur.
- Si une requête échoue ou renvoie un résultat suspect (vide, taux hors de 0-100 %), corrige-la.
- Si la question sort du périmètre des données (horaires du jour, prix des billets, un train précis
  un jour donné...), dis-le simplement et propose une question proche à laquelle tu peux répondre.
- Réponse finale : courte (3 à 6 phrases ou une petite liste), pourcentages avec une décimale et
  virgule française (« 87,4 % »), en précisant la période couverte. Pas de SQL dans la réponse finale :
  il est affiché séparément.

{notes}

Tables disponibles (schéma `main`) :
{schema}
"""

OUTIL_SQL = {"type": "function", "function": {
    "name": "run_sql",
    "description": (
        "Exécute UNE requête SQL DuckDB en lecture seule (SELECT ou WITH ... SELECT) sur les tables "
        f"de l'observatoire et renvoie au plus {MAX_LIGNES} lignes au format JSON. "
        "Utilise des agrégats et LIMIT plutôt que de rapatrier des données brutes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "La requête SQL à exécuter."},
            "objectif": {"type": "string", "description": "En une phrase, ce que la requête cherche à mesurer."},
        },
        "required": ["sql", "objectif"],
    },
}}


# --------------------------------------------------------------------------- base SQL
class BaseLectureSeule:
    """Base DuckDB en mémoire, chargée depuis les Parquet puis verrouillée."""

    def __init__(self, dossier_marts: Path):
        self.con = duckdb.connect()
        for f in sorted(dossier_marts.glob("*.parquet")):
            self.con.execute(f"create table {f.stem} as select * from read_parquet('{f}')")
        # Plus aucun accès disque/réseau, et impossible de rétablir la configuration.
        self.con.execute("set enable_external_access = false")
        self.con.execute("set lock_configuration = true")
        self._verrou = threading.Lock()
        self.schema = self._decrire_schema()

    def _decrire_schema(self) -> str:
        cols = self.con.execute("""
            select table_name, string_agg(column_name || ' ' || lower(data_type), ', ' order by ordinal_position)
            from information_schema.columns where table_schema = 'main'
            group by table_name order by table_name""").fetchall()
        tailles = dict(self.con.execute(
            "select table_name, estimated_size from duckdb_tables() where schema_name = 'main'").fetchall())
        return "\n".join(f"- {t} (~{tailles.get(t, '?')} lignes) : {c}" for t, c in cols)

    def executer(self, sql: str) -> pd.DataFrame:
        instructions = self.con.extract_statements(sql)
        if len(instructions) != 1:
            raise ValueError("Une seule instruction SQL par appel.")
        if instructions[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Seules les requêtes de lecture (SELECT) sont autorisées.")
        with self._verrou:  # une connexion DuckDB n'est pas partagée entre threads en parallèle
            minuteur = threading.Timer(DELAI_SQL_S, self.con.interrupt)
            minuteur.start()
            try:
                return self.con.execute(sql).df().head(MAX_LIGNES + 1)
            finally:
                minuteur.cancel()


# --------------------------------------------------------------------------- agent
@dataclass
class Etape:
    objectif: str
    sql: str
    resultat: pd.DataFrame | None = None
    erreur: str | None = None


@dataclass
class Reponse:
    texte: str
    etapes: list[Etape] = field(default_factory=list)
    modele: str = ""
    tokens_entree: int = 0
    tokens_sortie: int = 0


def _resultat_pour_modele(df: pd.DataFrame) -> str:
    tronque = len(df) > MAX_LIGNES
    df = df.head(MAX_LIGNES)
    texte = df.to_json(orient="records", date_format="iso", force_ascii=False, double_precision=4)
    entete = f"{len(df)} ligne(s){' (tronqué à ' + str(MAX_LIGNES) + ')' if tronque else ''}. Colonnes : {list(df.columns)}\n"
    return entete + texte


class QuotaEpuise(Exception):
    """Le modèle ne peut plus répondre pour l'instant (quota du jour atteint ou service saturé)."""


class AssistantPonctualite:
    def __init__(self, base: BaseLectureSeule, chaine: list[tuple[openai.OpenAI, str]]):
        self.base = base
        # (client, modèle) par ordre de préférence, éventuellement chez plusieurs fournisseurs :
        # on passe au suivant si le quota est épuisé ou le service indisponible.
        self.chaine = chaine
        self.system = SYSTEM_TEMPLATE.format(notes=NOTES_METIER, schema=base.schema)

    @staticmethod
    def _appel(client: openai.OpenAI, modele: str, messages: list):
        """Un appel au modèle. Limite par minute : on attend. Quota du jour ou panne : QuotaEpuise."""
        for tentative in range(ATTENTES_QUOTA_MAX + 1):
            try:
                return client.chat.completions.create(
                    model=modele, messages=messages, tools=[OUTIL_SQL], temperature=0)
            except openai.RateLimitError as e:
                # Gemini : « retry in 7.5s » ; Groq : « try again in 7.5s » (ou « in 12m3s » pour le quota du jour).
                attente = re.search(r"(?:retry|try again) in ([\d.]+)s", str(e.body or e))
                if not attente or tentative == ATTENTES_QUOTA_MAX:
                    raise QuotaEpuise(modele) from e  # pas de délai court = quota du jour
                time.sleep(min(float(attente.group(1)) + 1, 30))
            except (openai.InternalServerError, openai.APITimeoutError, openai.APIConnectionError,
                    openai.NotFoundError, openai.AuthenticationError, openai.PermissionDeniedError) as e:
                raise QuotaEpuise(modele) from e  # modèle saturé, lent, retiré ou clé refusée
            except openai.BadRequestError as e:
                if "tool_use_failed" in str(e):  # Groq : appel d'outil mal formé par le modèle
                    raise QuotaEpuise(modele) from e
                raise

    def repondre(self, question: str, historique: list | None = None) -> Reponse:
        derniere_erreur = None
        for client, modele in self.chaine:
            try:
                rep = self._repondre_avec(client, modele, question, historique)
                rep.modele = modele
                return rep
            except QuotaEpuise as e:
                # On reprend la question depuis le début : les signatures internes d'un
                # modèle Gemini ne sont pas valables pour un autre.
                derniere_erreur = e
        raise derniere_erreur

    def _repondre_avec(self, client: openai.OpenAI, modele: str, question: str, historique: list | None) -> Reponse:
        messages = ([{"role": "system", "content": self.system}] + list(historique or [])
                    + [{"role": "user", "content": question}])
        rep = Reponse(texte="")
        for _ in range(MAX_TOURS):
            r = self._appel(client, modele, messages)
            if r.usage:
                rep.tokens_entree += r.usage.prompt_tokens or 0
                rep.tokens_sortie += r.usage.completion_tokens or 0
            choix = r.choices[0]
            msg = choix.message
            appels = msg.tool_calls or []
            if not appels:
                rep.texte = (msg.content or "").strip() or "Je n'ai pas de réponse à proposer."
                if choix.finish_reason == "length":
                    rep.texte += "\n\n_(réponse tronquée)_"
                return rep

            # Message renvoyé tel quel : Gemini 3 y place une `thought_signature` (champ
            # extra_content) qu'il exige de retrouver à l'appel suivant, sinon erreur 400.
            messages.append(msg.model_dump(exclude_none=True))
            for appel in appels:
                etape = Etape(objectif="", sql="")
                try:
                    if appel.function.name != "run_sql":
                        raise ValueError(f"Outil inconnu : {appel.function.name}")
                    entree = json.loads(appel.function.arguments or "{}")
                    etape.objectif, etape.sql = entree.get("objectif", ""), entree.get("sql", "")
                    if not etape.sql:
                        raise ValueError("Paramètre `sql` manquant.")
                    df = self.base.executer(etape.sql)
                    etape.resultat = df.head(MAX_LIGNES)
                    contenu = _resultat_pour_modele(df)
                except Exception as e:  # erreur renvoyée au modèle pour qu'il corrige
                    etape.erreur = str(e).split("\n")[0][:500]
                    contenu = f"Erreur : {etape.erreur}"
                rep.etapes.append(etape)
                messages.append({"role": "tool", "tool_call_id": appel.id, "content": contenu})

        rep.texte = ("Je n'ai pas réussi à aboutir en un nombre raisonnable d'étapes. "
                     "Essaie de reformuler la question plus précisément.")
        return rep


def _chaine(fournisseur: str, cle: str, modeles: str | None) -> list[tuple[openai.OpenAI, str]]:
    conf = FOURNISSEURS[fournisseur]
    # Pas de nouvelle tentative automatique du SDK : on gère nous-mêmes les quotas.
    client = openai.OpenAI(api_key=cle, base_url=conf["base_url"], max_retries=0, timeout=60)
    return [(client, m.strip()) for m in (modeles or conf["modele"]).split(",") if m.strip()]


def creer_assistant(dossier_marts: Path, fournisseurs: list[tuple[str, str, str | None]]) -> AssistantPonctualite:
    """`fournisseurs` : [(nom, clé, modèles)] par ordre de préférence ; `modèles` est un nom ou une
    liste séparée par des virgules (None = modèles par défaut du fournisseur)."""
    chaine = [lien for nom, cle, modeles in fournisseurs if cle for lien in _chaine(nom, cle, modeles)]
    if not chaine:
        raise ValueError("Aucun fournisseur d'IA configuré.")
    return AssistantPonctualite(BaseLectureSeule(dossier_marts), chaine)
