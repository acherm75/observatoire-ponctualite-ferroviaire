"""Garde-fous SQL et boucle de l'assistant, sans appel à un vrai modèle."""
import json
from types import SimpleNamespace

import httpx
import openai
import pandas as pd
import pytest

import agent
from agent import AssistantPonctualite, BaseLectureSeule, QuotaEpuise


# --------------------------------------------------------------------------- base SQL
@pytest.fixture
def dossier_marts(tmp_path):
    pd.DataFrame({"activite": ["TGV", "TER", "Intercités"], "taux": [0.85, 0.91, 0.84]}).to_parquet(
        tmp_path / "ponctualite.parquet")
    pd.DataFrame({"n": range(500)}).to_parquet(tmp_path / "grande.parquet")
    return tmp_path


@pytest.fixture
def base(dossier_marts):
    return BaseLectureSeule(dossier_marts)


def test_charge_les_parquet_et_decrit_le_schema(base):
    assert "ponctualite" in base.schema and "grande" in base.schema
    assert "activite varchar" in base.schema


@pytest.mark.parametrize("sql", [
    "select * from ponctualite",
    "with t as (select * from ponctualite) select activite from t",
    "select count(*) from ponctualite;",  # point-virgule final toléré
])
def test_lecture_autorisee(base, sql):
    assert not base.executer(sql).empty


@pytest.mark.parametrize("sql", [
    "insert into ponctualite values ('TER', 0.5)",
    "update ponctualite set taux = 1",
    "delete from ponctualite",
    "drop table ponctualite",
    "create table x as select 1",
    "attach 'autre.duckdb'",
    "set lock_configuration = false",
    "copy ponctualite to 'fuite.csv'",
    "pragma version",
])
def test_ecriture_et_administration_refusees(base, sql):
    with pytest.raises(ValueError, match="SELECT"):
        base.executer(sql)
    assert len(base.executer("select * from ponctualite")) == 3


def test_plusieurs_instructions_refusees(base):
    with pytest.raises(ValueError, match="Une seule instruction"):
        base.executer("select 1; drop table ponctualite")


def test_aucun_acces_disque_depuis_un_select(base, dossier_marts):
    # Un SELECT peut lire un fichier (read_parquet, read_csv…) : l'accès externe doit être coupé.
    with pytest.raises(Exception, match="(?i)external access|disabled"):
        base.executer(f"select * from read_parquet('{dossier_marts / 'grande.parquet'}')")


def test_configuration_verrouillee(base):
    with pytest.raises(Exception):
        base.con.execute("set enable_external_access = true")


def test_resultat_tronque_pour_le_modele(base):
    df = base.executer("select * from grande")
    assert len(df) == agent.MAX_LIGNES + 1  # une ligne de plus pour savoir qu'on a tronqué
    texte = agent._resultat_pour_modele(df)
    assert texte.startswith(f"{agent.MAX_LIGNES} ligne(s) (tronqué")
    assert len(json.loads(texte.split("\n", 1)[1])) == agent.MAX_LIGNES


def test_requete_trop_longue_interrompue(base, monkeypatch):
    monkeypatch.setattr(agent, "DELAI_SQL_S", 0.2)
    with pytest.raises(Exception, match="(?i)interrupt"):
        base.executer("select count(*) from range(100000000000) a")
    assert len(base.executer("select * from ponctualite")) == 3  # la base reste utilisable


# --------------------------------------------------------------------------- boucle de l'agent
def _message(texte=None, appels=()):
    tool_calls = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=nom, arguments=args))
                  for i, (nom, args) in enumerate(appels)] or None
    msg = SimpleNamespace(content=texte, tool_calls=tool_calls)
    msg.model_dump = lambda **_: {"role": "assistant", "content": texte}
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def _sql(sql, objectif="test"):
    return ("run_sql", json.dumps({"sql": sql, "objectif": objectif}))


class FauxClient:
    """Client OpenAI factice : renvoie une suite de réponses (ou d'exceptions) préparées."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.messages_recus = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **_):
        self.messages_recus.append(list(messages))
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _erreur(classe, status, message="erreur", body=None):
    reponse = httpx.Response(status, request=httpx.Request("POST", "https://exemple.test"))
    return classe(message, response=reponse, body=body)


def test_question_resolue_en_une_requete(base):
    client = FauxClient(
        _message(appels=[_sql("select activite, taux from ponctualite order by taux limit 1")]),
        _message("Intercités est la moins ponctuelle (84,0 %)."),
    )
    rep = AssistantPonctualite(base, [(client, "m1")]).repondre("Quelle activité est la moins ponctuelle ?")
    assert rep.texte.startswith("Intercités")
    assert rep.modele == "m1"
    assert len(rep.etapes) == 1 and rep.etapes[0].erreur is None
    assert rep.etapes[0].resultat["activite"].tolist() == ["Intercités"]
    assert (rep.tokens_entree, rep.tokens_sortie) == (20, 10)
    # Le résultat de la requête a bien été renvoyé au modèle.
    retour_outil = client.messages_recus[1][-1]
    assert retour_outil["role"] == "tool" and "Intercités" in retour_outil["content"]


def test_erreur_sql_renvoyee_au_modele_pour_correction(base):
    client = FauxClient(
        _message(appels=[_sql("select * from table_inexistante")]),
        _message(appels=[_sql("drop table ponctualite")]),
        _message(appels=[("autre_outil", "{}")]),
        _message("Corrigé."),
    )
    rep = AssistantPonctualite(base, [(client, "m1")]).repondre("?")
    assert rep.texte == "Corrigé."
    assert [e.erreur is not None for e in rep.etapes] == [True, True, True]
    assert "Outil inconnu" in rep.etapes[2].erreur
    assert client.messages_recus[1][-1]["content"].startswith("Erreur :")


def test_nombre_d_etapes_limite(base):
    client = FauxClient(*[_message(appels=[_sql("select 1")]) for _ in range(agent.MAX_TOURS)])
    rep = AssistantPonctualite(base, [(client, "m1")]).repondre("?")
    assert "nombre raisonnable d'étapes" in rep.texte
    assert len(rep.etapes) == agent.MAX_TOURS


@pytest.mark.parametrize("erreur", [
    _erreur(openai.RateLimitError, 429, body={"message": "quota journalier dépassé"}),
    _erreur(openai.InternalServerError, 503),
    _erreur(openai.AuthenticationError, 401),
    _erreur(openai.NotFoundError, 404),
    _erreur(openai.BadRequestError, 400, body={"code": "tool_use_failed"}),
])
def test_relais_vers_le_modele_suivant(base, erreur):
    epuise = FauxClient(erreur)
    secours = FauxClient(_message("Réponse du secours."))
    rep = AssistantPonctualite(base, [(epuise, "m1"), (secours, "m2")]).repondre("?")
    assert rep.texte == "Réponse du secours." and rep.modele == "m2"


def test_tous_les_modeles_epuises(base):
    chaine = [(FauxClient(_erreur(openai.InternalServerError, 503)), m) for m in ("m1", "m2")]
    with pytest.raises(QuotaEpuise):
        AssistantPonctualite(base, chaine).repondre("?")


def test_limite_par_minute_on_attend_puis_on_reessaie(base, monkeypatch):
    attentes = []
    monkeypatch.setattr(agent.time, "sleep", attentes.append)
    client = FauxClient(_erreur(openai.RateLimitError, 429, body="Please retry in 2.5s."), _message("OK"))
    rep = AssistantPonctualite(base, [(client, "m1")]).repondre("?")
    assert rep.texte == "OK" and attentes == [3.5]


def test_autre_requete_invalide_non_masquee(base):
    client = FauxClient(_erreur(openai.BadRequestError, 400, body={"message": "paramètre invalide"}))
    with pytest.raises(openai.BadRequestError):
        AssistantPonctualite(base, [(client, "m1"), (FauxClient(), "m2")]).repondre("?")


def test_creer_assistant_ignore_les_fournisseurs_sans_cle(dossier_marts):
    a = agent.creer_assistant(dossier_marts, [("gemini", "", None), ("groq", "cle", "a, b")])
    assert [m for _, m in a.chaine] == ["a", "b"]
    with pytest.raises(ValueError, match="Aucun fournisseur"):
        agent.creer_assistant(dossier_marts, [("gemini", "", None)])
