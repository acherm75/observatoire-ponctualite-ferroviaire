"""Évaluation de l'assistant IA sur le jeu de questions de référence.

    python -m evaluation.lancer                      # toutes les questions, chaîne de modèles de l'app
    python -m evaluation.lancer --ids q01 q08        # quelques questions
    python -m evaluation.lancer --modele gemini-3.5-flash --pause 8

Clés lues dans .streamlit/secrets.toml (comme l'app) ou dans les variables d'environnement.
Écrit le détail dans evaluation/resultats/<date>_<modèle>.json et le résumé dans evaluation/RESULTATS.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "app"))

from agent import BaseLectureSeule, QuotaEpuise, creer_assistant  # noqa: E402

from evaluation.notation import noter  # noqa: E402
from evaluation.questions import QUESTIONS  # noqa: E402

MARTS = RACINE / "data" / "marts"
DOSSIER = Path(__file__).resolve().parent


def secrets() -> dict:
    fichier = RACINE / ".streamlit" / "secrets.toml"
    valeurs = tomllib.loads(fichier.read_text()) if fichier.exists() else {}
    return {**valeurs, **{k: v for k, v in os.environ.items() if k.startswith("ASSISTANT_")}}


def fournisseurs(s: dict, modele: str | None) -> list[tuple[str, str, str | None]]:
    principal = (s.get("ASSISTANT_FOURNISSEUR", "gemini"), s.get("ASSISTANT_CLE_API"), modele or s.get("ASSISTANT_MODELE"))
    if modele:  # un seul modèle imposé : pas de relais, pour mesurer CE modèle
        return [principal]
    secours = (s.get("ASSISTANT_SECOURS_FOURNISSEUR", "groq"), s.get("ASSISTANT_SECOURS_CLE_API"), s.get("ASSISTANT_SECOURS_MODELE"))
    return [principal, secours]


def evaluer_question(assistant, base: BaseLectureSeule, q: dict) -> dict:
    attendu = base.executer(q["sql"]) if q["sql"] else None
    debut = time.monotonic()
    try:
        rep = assistant.repondre(q["question"])
    except QuotaEpuise as e:
        return {"id": q["id"], "categorie": q["categorie"], "question": q["question"], "statut": "non évalué",
                "erreur": f"quota épuisé ({e})"}
    verifs = noter(q["verifs"], attendu, rep.texte, sum(e.erreur is None for e in rep.etapes))
    return {
        "id": q["id"], "categorie": q["categorie"], "question": q["question"],
        "statut": "réussi" if all(v.ok for v in verifs) else "échoué",
        "verifications": [{"attendu": v.attendu, "ok": v.ok} for v in verifs],
        "reponse": rep.texte, "modele": rep.modele,
        "requetes": [{"sql": e.sql, "erreur": e.erreur} for e in rep.etapes],
        "nb_requetes": len(rep.etapes), "nb_erreurs_sql": sum(e.erreur is not None for e in rep.etapes),
        "tokens": rep.tokens_entree + rep.tokens_sortie, "duree_s": round(time.monotonic() - debut, 1),
    }


def resume_markdown(resultats: list[dict], meta: dict) -> str:
    evalues = [r for r in resultats if r["statut"] != "non évalué"]
    reussis = [r for r in evalues if r["statut"] == "réussi"]
    lignes = [
        "# Évaluation de l'assistant IA",
        "",
        f"Exécution du {meta['date']} · modèle(s) : {', '.join(meta['modeles']) or '—'} · "
        f"données au {meta['donnees']}",
        "",
        f"**Score : {len(reussis)} / {len(evalues)} réponses justes "
        f"({100 * len(reussis) / max(len(evalues), 1):.0f} %)**"
        + (f" · {len(resultats) - len(evalues)} question(s) non évaluée(s) (quota)" if len(evalues) < len(resultats) else ""),
        "",
        "Réponse juste = toutes les valeurs attendues sont présentes dans la réponse (taux à 0,15 point près, "
        "libellés, valeurs brutes à 0,5 % près) ; pour une question hors périmètre, l'assistant doit décliner. "
        "Les valeurs attendues sont recalculées sur les données du jour par une requête de référence "
        "([`questions.py`](questions.py)), la notation est déterministe ([`notation.py`](notation.py)).",
        "",
    ]
    if evalues:
        lignes += [
            "| Indicateur | Valeur |", "|---|---|",
            f"| Requêtes SQL par question (moyenne) | {statistics.mean(r['nb_requetes'] for r in evalues):.1f} |",
            f"| Questions avec au moins une requête en erreur, corrigée ensuite ou non | "
            f"{sum(r['nb_erreurs_sql'] > 0 for r in evalues)} |",
            f"| Durée médiane par question | {statistics.median(r['duree_s'] for r in evalues):.0f} s |",
            f"| Tokens par question (moyenne) | {statistics.mean(r['tokens'] for r in evalues):,.0f} |".replace(",", " "),
            "",
            "| Catégorie | Score |", "|---|---|",
        ]
        par_cat = defaultdict(list)
        for r in evalues:
            par_cat[r["categorie"]].append(r["statut"] == "réussi")
        lignes += [f"| {c} | {sum(v)} / {len(v)} |" for c, v in par_cat.items()]
    lignes += ["", "## Détail", "", "| | Question | Attendu | Requêtes |", "|---|---|---|---|"]
    for r in resultats:
        icone = {"réussi": "✅", "échoué": "❌"}.get(r["statut"], "⏸️")
        attendu = " · ".join(("" if v["ok"] else "~~") + v["attendu"] + ("" if v["ok"] else "~~")
                             for v in r.get("verifications", [])) or r.get("erreur", "")
        lignes.append(f"| {icone} | {r['question']} | {attendu} | {r.get('nb_requetes', '')} |")
    lignes += ["", "Valeur barrée = absente de la réponse. Réponses complètes et requêtes dans "
               f"[`resultats/{meta['fichier']}`](resultats/{meta['fichier']})."]
    return "\n".join(lignes) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", nargs="*", help="identifiants des questions (défaut : toutes)")
    p.add_argument("--modele", help="imposer un modèle du fournisseur principal (sans relais)")
    p.add_argument("--pause", type=float, default=5, help="secondes entre deux questions (quotas gratuits)")
    p.add_argument("--sans-resume", action="store_true", help="ne pas réécrire RESULTATS.md")
    args = p.parse_args()

    questions = [q for q in QUESTIONS if not args.ids or q["id"] in args.ids]
    assistant = creer_assistant(MARTS, fournisseurs(secrets(), args.modele))
    base = BaseLectureSeule(MARTS)  # base séparée pour les requêtes de référence

    resultats = []
    for i, q in enumerate(questions):
        if i:
            time.sleep(args.pause)
        r = evaluer_question(assistant, base, q)
        resultats.append(r)
        icone = {"réussi": "✅", "échoué": "❌"}.get(r["statut"], "⏸️")
        manquant = [v["attendu"] for v in r.get("verifications", []) if not v["ok"]]
        print(f"{icone} {q['id']} {q['question'][:70]:<70} {r.get('modele', '')}"
              + (f"  manque : {', '.join(manquant)}" if manquant else ""), flush=True)

    modeles = sorted({r["modele"] for r in resultats if r.get("modele")})
    donnees = base.executer("select max(mois) from mart_ponctualite_nationale_mois").iloc[0, 0]
    date = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    nom = f"{date}_{(args.modele or Counter(r.get('modele') for r in resultats).most_common(1)[0][0] or 'inconnu').replace('/', '-')}.json"
    (DOSSIER / "resultats").mkdir(exist_ok=True)
    (DOSSIER / "resultats" / nom).write_text(json.dumps(resultats, indent=2, ensure_ascii=False))
    meta = {"date": dt.datetime.strptime(date, "%Y-%m-%d_%H%M").strftime("%d/%m/%Y à %H:%M"), "modeles": modeles, "donnees": f"{donnees:%Y-%m}", "fichier": nom}
    resume = resume_markdown(resultats, meta)
    if not args.sans_resume and not args.ids:
        (DOSSIER / "RESULTATS.md").write_text(resume)
    print("\n" + resume.split("\n")[4])


if __name__ == "__main__":
    main()
