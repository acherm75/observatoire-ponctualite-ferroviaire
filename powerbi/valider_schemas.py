"""Valide les fichiers JSON du projet Power BI contre les schémas officiels Microsoft.

    python -m powerbi.valider_schemas

Les schémas (et ceux qu'ils référencent) sont téléchargés depuis le dépôt public microsoft/json-schemas.
"""
from __future__ import annotations

import json
import sys
from functools import cache
from pathlib import Path

import referencing.jsonschema
import requests
from jsonschema import Draft7Validator, validators
from referencing import Registry, Resource

DOSSIER = Path(__file__).resolve().parent
PREFIXE = "https://developer.microsoft.com/json-schemas/"
MIROIR = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"


@cache
def _schema(uri: str) -> dict:
    r = requests.get(MIROIR + uri.removeprefix(PREFIXE).split("#")[0], timeout=30)
    r.raise_for_status()
    return r.json()


def _resource(uri: str) -> Resource:
    return Resource.from_contents(_schema(uri), default_specification=referencing.jsonschema.DRAFT7)


def fichiers() -> list[Path]:
    return sorted(p for p in DOSSIER.glob("Observatoire.*/**/*.json") if "StaticResources" not in p.parts) + \
        sorted(DOSSIER.glob("Observatoire.*/definition.pbi*")) + [DOSSIER / "Observatoire.pbip"]


def main() -> int:
    registre = Registry(retrieve=_resource)
    erreurs = 0
    liste = fichiers()
    for f in liste:
        doc = json.loads(f.read_text())
        schema = _schema(doc["$schema"])
        validateur = validators.validator_for(schema, default=Draft7Validator)(schema, registry=registre)
        for e in validateur.iter_errors(doc):
            erreurs += 1
            print(f"✗ {f.relative_to(DOSSIER)} → {'/'.join(map(str, e.absolute_path))} : {e.message[:200]}")
    print(f"{len(liste)} fichiers validés, {erreurs} erreur(s)")
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
