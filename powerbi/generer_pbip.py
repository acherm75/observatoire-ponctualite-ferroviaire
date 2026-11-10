"""Génère le rapport Power BI de l'observatoire au format projet (PBIP), sans Power BI Desktop.

    python -m powerbi.generer_pbip

Produit, à côté de ce script :
- Observatoire.pbip                    : fichier à ouvrir dans Power BI Desktop ;
- Observatoire.SemanticModel/          : modèle en étoile au format TMDL (tables chargées depuis les
                                         Parquet publiés sur GitHub, relations, mesures DAX) ;
- Observatoire.Report/                 : 7 pages au format PBIR (JSON), thème aux couleurs de l'app.

Le modèle est déduit du schéma réel des Parquet de data/marts ; les valeurs de contrôle affichées
dans la dernière page sont calculées ici avec DuckDB, par les mêmes requêtes que l'évaluation de
l'assistant, pour vérifier que Power BI retrouve exactement les chiffres de l'app et du README.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

RACINE = Path(__file__).resolve().parents[1]
MARTS = RACINE / "data" / "marts"
SORTIE = Path(__file__).resolve().parent
NOM = "Observatoire"
URL_DONNEES = "https://raw.githubusercontent.com/acherm75/observatoire-ponctualite-ferroviaire/main/data/marts/"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/"
V_VISUEL, V_PAGE, V_RAPPORT = "2.4.0", "2.0.0", "3.0.0"
LARGEUR, HAUTEUR = 1280, 720
PCT = "0.0 %"

# ============================================================================ modèle sémantique
TABLES = [
    "dim_date", "dim_liaison", "dim_gare", "dim_region", "dim_cause",
    "fct_regularite_liaison_mois", "fct_causes_retard_mois", "fct_regularite_ter_mois",
    "fct_meteo_region_mois", "mart_ponctualite_nationale_mois", "ml_prevision_mois_suivant", "ml_backtest",
]

TYPES = {"string": "string", "large_string": "string", "double": "double", "float": "double",
         "int64": "int64", "int32": "int64", "bool": "boolean", "date32[day]": "dateTime"}

# Propriétés particulières de certaines colonnes (format, tri, masquage).
COLONNES = {
    ("dim_date", "mois"): {"formatString": "mmm yyyy"},
    ("dim_date", "annee"): {"formatString": "0"},
    ("dim_date", "nom_mois"): {"sortByColumn": "num_mois"},
    ("dim_cause", "libelle_cause"): {"sortByColumn": "ordre"},
    ("ml_prevision_mois_suivant", "taux_retard_prevu"): {"formatString": PCT},
    ("ml_prevision_mois_suivant", "taux_retard_mois_precedent"): {"formatString": PCT},
    ("ml_prevision_mois_suivant", "taux_retard_moyen_12_mois"): {"formatString": PCT},
    ("ml_backtest", "mois"): {"formatString": "mmm yyyy"},
}
for _t in TABLES:
    for _c in ("taux_ponctualite", "taux_annulation", "part_cause"):
        COLONNES.setdefault((_t, _c), {"formatString": PCT})

RELATIONS = [  # (de, vers, actif)
    ("fct_regularite_liaison_mois.mois", "dim_date.mois", True),
    ("fct_regularite_liaison_mois.liaison_id", "dim_liaison.liaison_id", True),
    ("fct_causes_retard_mois.mois", "dim_date.mois", True),
    ("fct_causes_retard_mois.liaison_id", "dim_liaison.liaison_id", True),
    ("fct_causes_retard_mois.code_cause", "dim_cause.code_cause", True),
    ("fct_regularite_ter_mois.mois", "dim_date.mois", True),
    ("fct_regularite_ter_mois.region", "dim_region.region", True),
    ("fct_meteo_region_mois.mois", "dim_date.mois", True),
    ("fct_meteo_region_mois.region", "dim_region.region", True),
    ("mart_ponctualite_nationale_mois.mois", "dim_date.mois", True),
    ("dim_liaison.gare_depart_id", "dim_gare.gare_id", True),
    ("dim_liaison.gare_arrivee_id", "dim_gare.gare_id", False),  # via USERELATIONSHIP
    ("ml_prevision_mois_suivant.liaison_id", "dim_liaison.liaison_id", True),
    ("ml_backtest.liaison_id", "dim_liaison.liaison_id", True),
]

F, N, T, C = "fct_regularite_liaison_mois", "mart_ponctualite_nationale_mois", "fct_regularite_ter_mois", "fct_causes_retard_mois"
_COHERENT = f"{F}[est_incoherent] = FALSE ()"


def _decalage_n1(mesure: str) -> str:
    """Même mesure sur les mêmes mois, un an plus tôt (sans table de dates marquée : dim_date est mensuelle)."""
    return f"""VAR moisN1 = SELECTCOLUMNS ( VALUES ( dim_date[mois] ), "mois", EDATE ( dim_date[mois], -12 ) )
RETURN CALCULATE ( [{mesure}], REMOVEFILTERS ( dim_date ), TREATAS ( moisN1, dim_date[mois] ) )"""


def _ecart(mesure: str, mesure_n1: str) -> str:
    return f"""VAR n = [{mesure}]
VAR n1 = [{mesure_n1}]
RETURN IF ( NOT ISBLANK ( n ) && NOT ISBLANK ( n1 ), ( n - n1 ) * 100 )"""


ECART = "+0.0 \"pts\";-0.0 \"pts\";0.0 \"pts\""

# (table, nom, expression DAX, format, dossier, description)
MESURES = [
    # ---------------------------------------------------------------- liaisons TGV et Intercités
    (F, "Trains prévus", f"CALCULATE ( SUM ( {F}[nb_trains_prevus] ), {_COHERENT} )", "#,0", "Liaisons", None),
    (F, "Trains annulés", f"CALCULATE ( SUM ( {F}[nb_trains_annules] ), {_COHERENT} )", "#,0", "Liaisons", None),
    (F, "Trains circulés", f"CALCULATE ( SUM ( {F}[nb_trains_circules] ), {_COHERENT} )", "#,0", "Liaisons",
     "Trains ayant circulé, hors lignes incohérentes de la source (avril-juin 2020)."),
    (F, "Trains en retard", f"CALCULATE ( SUM ( {F}[nb_trains_retard_arrivee] ), {_COHERENT} )", "#,0", "Liaisons", None),
    (F, "Ponctualité", "DIVIDE ( [Trains circulés] - [Trains en retard], [Trains circulés] )", PCT, "Liaisons",
     "Recalculée à partir des sommes : jamais de moyenne de taux."),
    (F, "Taux d'annulation", "DIVIDE ( [Trains annulés], [Trains prévus] )", PCT, "Liaisons", None),
    (F, "Retard moyen des trains en retard (min)",
     f"""VAR lignes = FILTER ( {F}, NOT {F}[est_incoherent] && NOT ISBLANK ( {F}[retard_moyen_trains_retard_min] ) )
RETURN DIVIDE (
    SUMX ( lignes, {F}[retard_moyen_trains_retard_min] * {F}[nb_trains_retard_arrivee] ),
    SUMX ( lignes, {F}[nb_trains_retard_arrivee] ) )""", "0.0", "Liaisons",
     "Moyenne pondérée par le nombre de trains en retard de chaque liaison et de chaque mois."),
    (F, "Part des trains à plus de 60 min de retard",
     f"DIVIDE ( CALCULATE ( SUM ( {F}[nb_trains_retard_sup_60] ), {_COHERENT} ), [Trains circulés] )", PCT, "Liaisons", None),
    (F, "Ponctualité N-1", _decalage_n1("Ponctualité"), PCT, "Liaisons", None),
    (F, "Écart vs N-1", _ecart("Ponctualité", "Ponctualité N-1"), ECART, "Liaisons", "En points de pourcentage."),
    (F, "Ponctualité (gare d'arrivée)",
     "CALCULATE ( [Ponctualité], USERELATIONSHIP ( dim_liaison[gare_arrivee_id], dim_gare[gare_id] ) )", PCT, "Liaisons",
     "À utiliser avec dim_gare pour analyser les liaisons par gare d'arrivée."),

    # ---------------------------------------------------------------- national (TGV, TER, Intercités)
    (N, "Trains circulés (national)", f"SUM ( {N}[nb_trains_circules] )", "#,0", "National", None),
    (N, "Ponctualité nationale",
     f"DIVIDE ( SUM ( {N}[nb_trains_circules] ) - SUM ( {N}[nb_trains_retard_arrivee] ), SUM ( {N}[nb_trains_circules] ) )",
     PCT, "National", None),
    (N, "Taux d'annulation national", f"DIVIDE ( SUM ( {N}[nb_trains_annules] ), SUM ( {N}[nb_trains_prevus] ) )", PCT, "National", None),
    (N, "Ponctualité TGV", f"CALCULATE ( [Ponctualité nationale], {N}[activite] = \"TGV\" )", PCT, "National", None),
    (N, "Ponctualité TER", f"CALCULATE ( [Ponctualité nationale], {N}[activite] = \"TER\" )", PCT, "National", None),
    (N, "Ponctualité Intercités", f"CALCULATE ( [Ponctualité nationale], {N}[activite] = \"Intercités\" )", PCT, "National", None),
    (N, "Ponctualité nationale N-1", _decalage_n1("Ponctualité nationale"), PCT, "National", None),
    (N, "Écart TGV vs N-1", _ecart("Ponctualité TGV", "Ponctualité TGV N-1"), ECART, "National", None),
    (N, "Écart TER vs N-1", _ecart("Ponctualité TER", "Ponctualité TER N-1"), ECART, "National", None),
    (N, "Écart Intercités vs N-1", _ecart("Ponctualité Intercités", "Ponctualité Intercités N-1"), ECART, "National", None),
    (N, "Ponctualité TGV N-1", _decalage_n1("Ponctualité TGV"), PCT, "National", None),
    (N, "Ponctualité TER N-1", _decalage_n1("Ponctualité TER"), PCT, "National", None),
    (N, "Ponctualité Intercités N-1", _decalage_n1("Ponctualité Intercités"), PCT, "National", None),
    (N, "Ponctualité nationale 12 mois glissants",
     """VAR fin = MAX ( dim_date[mois] )
RETURN IF (
    NOT ISBLANK ( [Ponctualité nationale] ),
    CALCULATE ( [Ponctualité nationale], REMOVEFILTERS ( dim_date ),
        dim_date[mois] > EDATE ( fin, -12 ), dim_date[mois] <= fin ) )""", PCT, "National",
     "Lisse la saisonnalité : chaque point couvre les 12 mois qui se terminent à ce mois."),
    (N, "Dernier mois disponible",
     f"\"Données jusqu'à \" & FORMAT ( CALCULATE ( MAX ( {N}[mois] ), REMOVEFILTERS ( dim_date ) ), \"mmmm yyyy\" )",
     None, "National", None),

    # ---------------------------------------------------------------- TER par région
    (T, "Ponctualité TER (régions)",
     f"DIVIDE ( SUM ( {T}[nb_trains_circules] ) - SUM ( {T}[nb_trains_retard_arrivee] ), SUM ( {T}[nb_trains_circules] ) )",
     PCT, "TER", None),
    (T, "Taux d'annulation TER (régions)", f"DIVIDE ( SUM ( {T}[nb_trains_annules] ), SUM ( {T}[nb_trains_prevus] ) )", PCT, "TER", None),
    (T, "Jours de chaleur (moyenne)", f"AVERAGE ( {T}[meteo_jours_chaleur] )", "0.0", "Météo", None),
    (T, "Jours de gel (moyenne)", f"AVERAGE ( {T}[meteo_jours_gel] )", "0.0", "Météo", None),

    # ---------------------------------------------------------------- causes
    (C, "Retards imputés", f"SUM ( {C}[nb_trains_retard_imputes] )", "#,0", "Causes",
     "Trains TGV en retard de plus de 15 minutes, répartis entre les 6 causes."),
    (C, "Part de la cause", "DIVIDE ( [Retards imputés], CALCULATE ( [Retards imputés], REMOVEFILTERS ( dim_cause ) ) )", PCT, "Causes", None),

    # ---------------------------------------------------------------- prévision
    ("ml_backtest", "Taux de retard réel (moyenne des liaisons)", "AVERAGE ( ml_backtest[taux_retard] )", PCT, "Prévision", None),
    ("ml_backtest", "Taux de retard prévu (moyenne des liaisons)", "AVERAGE ( ml_backtest[taux_retard_prevu] )", PCT, "Prévision", None),
    ("ml_backtest", "Erreur absolue moyenne",
     "AVERAGEX ( ml_backtest, ABS ( ml_backtest[taux_retard] - ml_backtest[taux_retard_prevu] ) ) * 100",
     "0.00 \"pts\"", "Prévision", "Erreur moyenne de la prévision à M+1 sur la période de test, en points."),
]

# Contrôles : (nom de la mesure, expression DAX, format, requête DuckDB de référence, unité)
CONTROLES = [
    ("Contrôle · TGV 2025", "CALCULATE ( [Ponctualité TGV], dim_date[annee] = 2025 )", PCT,
     f"select 1 - sum(nb_trains_retard_arrivee) / sum(nb_trains_circules) from {N} where activite = 'TGV' and year(mois) = 2025", "pct"),
    ("Contrôle · TER 2025", "CALCULATE ( [Ponctualité TER], dim_date[annee] = 2025 )", PCT,
     f"select 1 - sum(nb_trains_retard_arrivee) / sum(nb_trains_circules) from {N} where activite = 'TER' and year(mois) = 2025", "pct"),
    ("Contrôle · Intercités 2025", "CALCULATE ( [Ponctualité Intercités], dim_date[annee] = 2025 )", PCT,
     f"select 1 - sum(nb_trains_retard_arrivee) / sum(nb_trains_circules) from {N} where activite = 'Intercités' and year(mois) = 2025", "pct"),
    ("Contrôle · Mâcon Loché → Paris 2025",
     "CALCULATE ( [Ponctualité], dim_date[annee] = 2025, dim_liaison[libelle_liaison] = \"Mâcon Loché → Paris Gare de Lyon\", "
     "dim_liaison[type_service] = \"National\" )", PCT,
     f"""select 1 - sum(f.nb_trains_retard_arrivee) / sum(f.nb_trains_circules) from {F} f join dim_liaison l using (liaison_id)
         where l.libelle_liaison = 'Mâcon Loché → Paris Gare de Lyon' and l.type_service = 'National'
           and year(f.mois) = 2025 and not f.est_incoherent""", "pct"),
    ("Contrôle · Retard moyen TGV 2025",
     f"CALCULATE ( [Retard moyen des trains en retard (min)], dim_date[annee] = 2025, {F}[activite] = \"TGV\" )", "0.0",
     f"""select sum(retard_moyen_trains_retard_min * nb_trains_retard_arrivee) / sum(nb_trains_retard_arrivee) from {F}
         where activite = 'TGV' and year(mois) = 2025 and not est_incoherent and retard_moyen_trains_retard_min is not null""", "min"),
    ("Contrôle · Part SNCF Réseau 2018-2026",
     "CALCULATE ( DIVIDE ( CALCULATE ( [Retards imputés], dim_cause[responsable] = \"SNCF Réseau\" ), [Retards imputés] ), "
     "dim_date[mois] < DATE ( 2026, 5, 1 ) )", PCT,
     f"""select sum(nb_trains_retard_imputes) filter (where c.responsable = 'SNCF Réseau') / sum(nb_trains_retard_imputes)
         from {C} f join dim_cause c using (code_cause) where f.mois < '2026-05-01'""", "pct"),
    ("Contrôle · TER Occitanie 2025",
     "CALCULATE ( [Ponctualité TER (régions)], dim_date[annee] = 2025, dim_region[region] = \"Occitanie\" )", PCT,
     f"select 1 - sum(nb_trains_retard_arrivee) / sum(nb_trains_circules) from {T} where region = 'Occitanie' and year(mois) = 2025", "pct"),
]


def _q(nom: str) -> str:
    """Nom TMDL : entre apostrophes s'il contient autre chose que lettres, chiffres et _."""
    return nom if nom.replace("_", "").isalnum() and nom.isascii() else "'" + nom.replace("'", "''") + "'"


def _expression(expr: str, indent: str) -> str:
    lignes = expr.strip("\n").split("\n")
    if len(lignes) == 1:
        return " " + lignes[0]
    return "\n" + "\n".join(indent + ligne for ligne in lignes)


def table_tmdl(table: str) -> str:
    schema = pq.read_schema(MARTS / f"{table}.parquet")
    sortie = [f"table {table}", ""]
    for nom, expr, fmt, dossier, desc in [(m[1], m[2], m[3], m[4], m[5]) for m in MESURES + _mesures_controle() if m[0] == table]:
        if desc:
            sortie.append(f"\t/// {desc}")
        sortie.append(f"\tmeasure {_q(nom)} ={_expression(expr, chr(9) * 3)}")
        if fmt:
            sortie.append(f"\t\tformatString: {fmt}")
        sortie.append(f"\t\tdisplayFolder: {dossier}")
        sortie.append("")
    for champ in schema:
        type_pa = str(champ.type)
        type_tmdl = "dateTime" if type_pa.startswith("timestamp") else TYPES[type_pa]
        props = COLONNES.get((table, champ.name), {})
        sortie.append(f"\tcolumn {_q(champ.name)}")
        sortie.append(f"\t\tdataType: {type_tmdl}")
        if "formatString" in props:
            sortie.append(f"\t\tformatString: {props['formatString']}")
        elif type_tmdl == "dateTime":
            sortie.append("\t\tformatString: dd/mm/yyyy")
        sortie.append("\t\tsummarizeBy: none")
        sortie.append(f"\t\tsourceColumn: {champ.name}")
        if "sortByColumn" in props:
            sortie.append(f"\t\tsortByColumn: {props['sortByColumn']}")
        if type_tmdl == "dateTime" and not type_pa.startswith("timestamp"):
            sortie += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
        sortie.append("")
    m = (f'let\n    Source = Parquet.Document ( Binary.Buffer ( Web.Contents ( UrlDonnees, '
         f'[ RelativePath = "{table}.parquet" ] ) ) )\nin\n    Source')
    sortie += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource =" + _expression(m, "\t" * 4), "",
               "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(sortie)


def _mesures_controle():
    return [(N, nom, expr, fmt, "Contrôle", "Doit être égal à la valeur affichée dans le titre de la page Contrôle.")
            for nom, expr, fmt, _, _ in CONTROLES]


def generer_modele(dossier: Path):
    d = dossier / "definition"
    (d / "tables").mkdir(parents=True)
    _json(dossier / "definition.pbism", {
        "$schema": SCHEMA + "item/semanticModel/definitionProperties/1.0.0/schema.json", "version": "4.2", "settings": {}})
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1600\n\n")
    (d / "model.tmdl").write_text("\n".join([
        "model Model", "\tculture: fr-FR", "\tdefaultPowerBIDataSourceVersion: powerBI_V3", "\tsourceQueryCulture: fr-FR",
        "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
        "annotation __PBI_TimeIntelligenceEnabled = 0", "",
        f"annotation PBI_QueryOrder = {json.dumps(['UrlDonnees'] + TABLES)}", "",
        *[f"ref table {t}" for t in TABLES], "", "ref cultureInfo fr-FR", ""]))
    (d / "expressions.tmdl").write_text(
        f'/// Dossier des Parquet publiés chaque jour par le pipeline (remplacer par un dossier local si besoin).\n'
        f'expression UrlDonnees = "{URL_DONNEES}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n\n'
        f'\tannotation PBI_ResultType = Text\n\n')
    rel = []
    for i, (de, vers, actif) in enumerate(RELATIONS, 1):
        rel += [f"relationship r{i:02d}_{de.split('.')[0]}_{vers.split('.')[0]}"]
        if not actif:
            rel.append("\tisActive: false")
        rel += [f"\tfromColumn: {de}", f"\ttoColumn: {vers}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rel))
    (d / "cultures").mkdir()
    (d / "cultures" / "fr-FR.tmdl").write_text("cultureInfo fr-FR\n\n")
    for t in TABLES:
        (d / "tables" / f"{t}.tmdl").write_text(table_tmdl(t))


# ============================================================================ rapport (PBIR)
def col(table, colonne):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": colonne}}


def mes(table, mesure):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": mesure}}


def _projection(champ, nom_affiche=None):
    cible = champ.get("Column") or champ.get("Measure")
    p = {"field": champ, "queryRef": f"{cible['Expression']['SourceRef']['Entity']}.{cible['Property']}",
         "nativeQueryRef": cible["Property"]}
    if nom_affiche:
        p["displayName"] = nom_affiche
    return p


def lit(valeur):
    return {"expr": {"Literal": {"Value": valeur}}}


def texte(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def visuel(nom, type_visuel, x, y, l, h, roles=None, titre=None, objets=None, tri=None, filtres=None, z=0):
    v = {"visualType": type_visuel}
    if roles:
        v["query"] = {"queryState": {role: {"projections": [_projection(*c) if isinstance(c, tuple) else _projection(c) for c in champs]}
                                     for role, champs in roles.items()}}
        if tri:
            champ, sens = tri
            v["query"]["sortDefinition"] = {"sort": [{"field": champ, "direction": sens}]}
    if objets:
        v["objects"] = objets
    if titre:
        v["visualContainerObjects"] = {"title": [{"properties": {"show": lit("true"), "text": lit(texte(titre))}}]}
    v["drillFilterOtherVisuals"] = True
    contenu = {"$schema": SCHEMA + f"item/report/definition/visualContainer/{V_VISUEL}/schema.json", "name": nom,
               "position": {"x": x, "y": y, "z": z, "width": l, "height": h, "tabOrder": z}, "visual": v}
    if filtres:
        contenu["filterConfig"] = {"filters": filtres}
    return contenu


def zone_texte(nom, x, y, l, h, lignes):
    """lignes : [(texte, taille en pt, gras, couleur)]"""
    paragraphes = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{taille}pt", "color": couleur,
                                                            **({"fontWeight": "bold"} if gras else {})}}]}
                   for t, taille, gras, couleur in lignes]
    return visuel(nom, "textbox", x, y, l, h, objets={"general": [{"properties": {"paragraphs": paragraphes}}]})


def entete(titre, sous_titre):
    return zone_texte("entete", 16, 8, 1000, 64, [(titre, 20, True, ENCRE), (sous_titre, 10, False, GRIS)])


def segment(nom, champ, x, y, l=180, h=64, valeur_defaut=None, liste_deroulante=True):
    """Segment (slicer) ; valeur_defaut : littéral Power BI déjà présélectionné (ex. '2025L')."""
    general = {}
    if valeur_defaut is not None:
        entite, propriete = champ["Column"]["Expression"]["SourceRef"]["Entity"], champ["Column"]["Property"]
        general["filter"] = {"filter": {
            "Version": 2, "From": [{"Name": "s", "Entity": entite, "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": propriete}}],
                                            "Values": [[{"Literal": {"Value": valeur_defaut}}]]}}}]}}
    objets = {"data": [{"properties": {"mode": lit("'Dropdown'" if liste_deroulante else "'Basic'")}}]}
    if general:
        objets["general"] = [{"properties": general}]
    return visuel(nom, "slicer", x, y, l, h, roles={"Values": [champ]}, objets=objets)


def carte(nom, mesure, x, y, l, h, titre=None):
    return visuel(nom, "card", x, y, l, h, roles={"Values": [mesure]}, titre=titre,
                  objets={"labels": [{"properties": {"fontSize": lit("24D"), "color": {"solid": {"color": lit(texte(ENCRE))}}}}]})


def filtre_mesure_min(nom, table, mesure, minimum):
    return {"name": nom, "field": mes(table, mesure), "type": "Advanced", "filter": {
        "Version": 2, "From": [{"Name": "m", "Entity": table, "Type": 0}],
        # ComparisonKind 2 = « supérieur ou égal »
        "Where": [{"Condition": {"Comparison": {
            "ComparisonKind": 2,
            "Left": {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": mesure}},
            "Right": {"Literal": {"Value": f"{minimum}D"}}}}}]}}


ENCRE, GRIS = "#1B2733", "#5B6B7B"
ANNEE = col("dim_date", "annee")


def pages(controles: list[tuple[str, str]]):
    """Renvoie [(nom, titre affiché, visuels, interactions)]."""
    sans_filtre = lambda source, *cibles: [{"source": source, "target": c, "type": "NoFilter"} for c in cibles]  # noqa: E731
    p = []

    # 1. Synthèse ---------------------------------------------------------------------------
    v = [entete("Ponctualité ferroviaire en France", "Données ouvertes SNCF · TGV, TER et Intercités · un train est en retard au-delà de 5 min"),
         segment("segment_annee", ANNEE, 1084, 12, valeur_defaut="2025L")]
    for i, (activite, mesure, ecart) in enumerate([("TGV", "Ponctualité TGV", "Écart TGV vs N-1"),
                                                   ("TER", "Ponctualité TER", "Écart TER vs N-1"),
                                                   ("Intercités", "Ponctualité Intercités", "Écart Intercités vs N-1")]):
        x = 16 + i * 316
        v.append(carte(f"carte_{activite.lower().replace('é', 'e')}", mes(N, mesure), x, 84, 300, 104, titre=f"Ponctualité {activite}"))
        v.append(carte(f"ecart_{activite.lower().replace('é', 'e')}", mes(N, ecart), x, 192, 300, 76, titre="Écart avec l'année précédente"))
    v.append(carte("carte_annulation", mes(N, "Taux d'annulation national"), 964, 84, 300, 104, titre="Trains annulés (toutes activités)"))
    v.append(carte("carte_fraicheur", mes(N, "Dernier mois disponible"), 964, 192, 300, 76, titre="Fraîcheur des données"))
    v.append(visuel("tendance", "lineChart", 16, 284, 760, 420,
                    roles={"Category": [col("dim_date", "mois")], "Y": [mes(N, "Ponctualité nationale 12 mois glissants")],
                           "Series": [col(N, "activite")]},
                    titre="Tendance de long terme : ponctualité sur 12 mois glissants (toutes années)"))
    v.append(visuel("par_annee", "clusteredColumnChart", 792, 284, 472, 420,
                    roles={"Category": [ANNEE], "Y": [mes(N, "Ponctualité nationale")], "Series": [col(N, "activite")]},
                    titre="Ponctualité par année et par activité", tri=(ANNEE, "Ascending")))
    p.append(("synthese", "Synthèse", v, sans_filtre("segment_annee", "tendance", "par_annee")))

    # 2. Liaisons -----------------------------------------------------------------------------
    v = [entete("Liaisons TGV et Intercités", "Classement des liaisons ; cliquer une ligne pour voir son évolution mensuelle"),
         segment("segment_annee", ANNEE, 704, 12, valeur_defaut="2025L"),
         segment("segment_activite", col("dim_liaison", "activite"), 892, 12),
         segment("segment_service", col("dim_liaison", "type_service"), 1080, 12)]
    v.append(visuel("classement", "tableEx", 16, 84, 780, 620,
                    roles={"Values": [(col("dim_liaison", "libelle_liaison"), "Liaison"), (col("dim_liaison", "activite"), "Activité"),
                                      (col("dim_liaison", "type_service"), "Service"), mes(F, "Trains circulés"), mes(F, "Ponctualité"), mes(F, "Écart vs N-1"),
                                      mes(F, "Taux d'annulation"), (mes(F, "Retard moyen des trains en retard (min)"), "Retard moyen (min)")]},
                    tri=(mes(F, "Ponctualité"), "Ascending"),
                    titre="Liaisons classées de la moins à la plus ponctuelle (au moins 500 trains sur la période)",
                    filtres=[filtre_mesure_min("au_moins_500_trains", F, "Trains circulés", 500)]))
    v.append(visuel("evolution", "lineChart", 812, 84, 452, 300,
                    roles={"Category": [col("dim_date", "mois")], "Y": [mes(F, "Ponctualité")]},
                    titre="Évolution mensuelle (toutes années)"))
    v.append(visuel("par_gare", "clusteredBarChart", 812, 396, 452, 308,
                    roles={"Category": [col("dim_gare", "nom_gare")], "Y": [mes(F, "Ponctualité")]},
                    tri=(mes(F, "Ponctualité"), "Ascending"), titre="Ponctualité par gare de départ"))
    p.append(("liaisons", "Liaisons", v, sans_filtre("segment_annee", "evolution")))

    # 3. Causes --------------------------------------------------------------------------------
    v = [entete("Causes des retards TGV", "Répartition des trains TGV en retard de plus de 15 minutes entre 6 causes"),
         segment("segment_annee", ANNEE, 1084, 12, valeur_defaut="2025L")]
    v.append(visuel("causes_par_annee", "hundredPercentStackedColumnChart", 16, 84, 820, 620,
                    roles={"Category": [ANNEE], "Y": [mes(C, "Retards imputés")], "Series": [col("dim_cause", "libelle_cause")]},
                    tri=(ANNEE, "Ascending"), titre="Répartition des causes par année (toutes années)"))
    v.append(visuel("par_responsable", "clusteredBarChart", 852, 84, 412, 360,
                    roles={"Category": [col("dim_cause", "responsable")], "Y": [mes(C, "Part de la cause")]},
                    tri=(mes(C, "Part de la cause"), "Descending"), titre="Part des retards par responsable (année choisie)"))
    v.append(zone_texte("note_rupture", 852, 460, 412, 244, [
        ("À savoir", 11, True, ENCRE),
        ("SNCF Réseau (infrastructure et gestion du trafic) porte environ 43 % des retards de 2018 à avril 2026.", 10, False, GRIS),
        ("Rupture en mai 2026 : la répartition change brutalement, probablement à cause d'un changement de nomenclature dans la source. "
         "Comparer 2026 aux années précédentes avec prudence.", 10, False, GRIS)]))
    p.append(("causes", "Causes des retards", v, sans_filtre("segment_annee", "causes_par_annee")))

    # 4. Régions TER --------------------------------------------------------------------------------
    v = [entete("TER par région", "Ponctualité des TER par région actuelle (13 régions), depuis 2013"),
         segment("segment_annee", ANNEE, 1084, 12, valeur_defaut="2025L")]
    v.append(visuel("matrice", "pivotTable", 16, 84, 820, 620,
                    roles={"Rows": [col("dim_region", "region")], "Columns": [ANNEE], "Values": [mes(T, "Ponctualité TER (régions)")]},
                    titre="Ponctualité TER par région et par année (toutes années)"))
    v.append(visuel("classement_regions", "clusteredBarChart", 852, 84, 412, 620,
                    roles={"Category": [col("dim_region", "region")], "Y": [mes(T, "Ponctualité TER (régions)")]},
                    tri=(mes(T, "Ponctualité TER (régions)"), "Ascending"), titre="Classement des régions (année choisie)"))
    p.append(("regions", "Régions TER", v, sans_filtre("segment_annee", "matrice")))

    # 5. Météo ------------------------------------------------------------------------------------
    v = [entete("Effet de la météo", "TER : ponctualité mensuelle et météo régionale (Météo-France)")]
    v.append(visuel("nuage_chaleur", "scatterChart", 16, 84, 620, 620,
                    roles={"Category": [col("dim_date", "annee_mois")], "X": [mes(T, "Jours de chaleur (moyenne)")],
                           "Y": [mes(T, "Ponctualité TER (régions)")], "Series": [col("dim_date", "saison")]},
                    titre="Chaque point est un mois : jours de chaleur et ponctualité TER"))
    v.append(visuel("saisonnalite", "clusteredColumnChart", 652, 84, 612, 300,
                    roles={"Category": [col("dim_date", "nom_mois")],
                           "Y": [(mes(T, "Ponctualité TER (régions)"), "TER"), (mes(F, "Ponctualité"), "TGV et Intercités")]},
                    tri=(col("dim_date", "nom_mois"), "Ascending"), titre="Saisonnalité : ponctualité moyenne par mois de l'année"))
    v.append(visuel("chaleur_par_mois", "clusteredColumnChart", 652, 400, 612, 304,
                    roles={"Category": [col("dim_date", "nom_mois")], "Y": [mes(T, "Jours de chaleur (moyenne)"), mes(T, "Jours de gel (moyenne)")]},
                    tri=(col("dim_date", "nom_mois"), "Ascending"), titre="Jours de chaleur et de gel par mois (moyenne régionale)"))
    p.append(("meteo", "Effet météo", v, []))

    # 6. Prévisions --------------------------------------------------------------------------------
    v = [entete("Prévision du mois suivant", "XGBoost : taux de retard prévu par liaison pour le prochain mois publié")]
    v.append(visuel("previsions", "tableEx", 16, 84, 780, 620,
                    roles={"Values": [(col("dim_liaison", "libelle_liaison"), "Liaison"),
                                      (col("ml_prevision_mois_suivant", "taux_retard_prevu"), "Retard prévu"),
                                      (col("ml_prevision_mois_suivant", "taux_retard_mois_precedent"), "Retard le mois précédent"),
                                      (col("ml_prevision_mois_suivant", "taux_retard_moyen_12_mois"), "Retard moyen sur 12 mois")]},
                    tri=(col("ml_prevision_mois_suivant", "taux_retard_prevu"), "Descending"),
                    titre="Liaisons au plus fort taux de retard prévu"))
    v.append(visuel("backtest", "lineChart", 812, 84, 452, 420,
                    roles={"Category": [col("ml_backtest", "mois")],
                           "Y": [(mes("ml_backtest", "Taux de retard réel (moyenne des liaisons)"), "Réel"),
                                 (mes("ml_backtest", "Taux de retard prévu (moyenne des liaisons)"), "Prévu")]},
                    titre="Test sur des mois jamais vus à l'entraînement : réel et prévu"))
    v.append(carte("erreur", mes("ml_backtest", "Erreur absolue moyenne"), 812, 520, 452, 184,
                   titre="Erreur absolue moyenne de la prévision (période de test)"))
    p.append(("previsions", "Prévisions", v, []))

    # 7. Contrôle ----------------------------------------------------------------------------------
    v = [entete("Contrôle des chiffres", "Chaque carte doit afficher la valeur attendue de son titre, calculée sur les mêmes données avec DuckDB")]
    for i, (nom, attendu) in enumerate(controles):
        x, y = 16 + (i % 4) * 316, 100 + (i // 4) * 200
        v.append(carte(f"controle_{i + 1}", mes(N, nom), x, y, 300, 180, titre=f"{nom.split(' · ')[1]} · attendu {attendu}"))
    v.append(zone_texte("note_controle", 16, 520, 1248, 120, [
        ("Si une carte diffère de la valeur attendue, le modèle ou une mesure DAX est faux : ne pas publier le rapport.", 10, False, GRIS),
        ("Les valeurs attendues sont recalculées à chaque génération du projet (python -m powerbi.generer_pbip).", 10, False, GRIS)]))
    p.append(("controle", "Contrôle", v, []))
    return p


def generer_rapport(dossier: Path, controles):
    d = dossier / "definition"
    (d / "pages").mkdir(parents=True)
    _json(dossier / "definition.pbir", {"$schema": SCHEMA + "item/report/definitionProperties/2.0.0/schema.json",
                                        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NOM}.SemanticModel"}}})
    _json(d / "version.json", {"$schema": SCHEMA + "item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    version_theme = {"visual": V_VISUEL, "page": V_PAGE, "report": V_RAPPORT}
    _json(d / "report.json", {
        "$schema": SCHEMA + f"item/report/definition/report/{V_RAPPORT}/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": version_theme, "type": "SharedResources"},
            "customTheme": {"name": "Observatoire.json", "reportVersionAtImport": version_theme, "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "Observatoire.json", "path": "Observatoire.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "exportDataMode": "AllowSummarized", "useEnhancedTooltips": True}})
    ressources = dossier / "StaticResources"
    (ressources / "SharedResources" / "BaseThemes").mkdir(parents=True)
    shutil.copy(SORTIE / "theme" / "CY24SU10.json", ressources / "SharedResources" / "BaseThemes" / "CY24SU10.json")
    (ressources / "RegisteredResources").mkdir()
    shutil.copy(SORTIE / "theme" / "Observatoire.json", ressources / "RegisteredResources" / "Observatoire.json")

    liste = pages(controles)
    _json(d / "pages" / "pages.json", {"$schema": SCHEMA + "item/report/definition/pagesMetadata/1.0.0/schema.json",
                                       "pageOrder": [nom for nom, *_ in liste], "activePageName": liste[0][0]})
    for nom, titre, visuels, interactions in liste:
        dp = d / "pages" / nom
        page = {"$schema": SCHEMA + f"item/report/definition/page/{V_PAGE}/schema.json", "name": nom, "displayName": titre,
                "displayOption": "FitToPage", "height": HAUTEUR, "width": LARGEUR}
        if interactions:
            page["visualInteractions"] = interactions
        _json(dp / "page.json", page)
        for z, v in enumerate(visuels):
            v["position"]["z"] = v["position"]["tabOrder"] = z * 1000
            _json(dp / "visuals" / v["name"] / "visual.json", v)


def _json(chemin: Path, contenu):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(contenu, indent=2, ensure_ascii=False) + "\n")


def valeurs_controle() -> list[tuple[str, str]]:
    con = duckdb.connect()
    for t in TABLES:
        con.execute(f"create view {t} as select * from read_parquet('{MARTS / (t + '.parquet')}')")
    sortie = []
    for nom, _, _, sql, unite in CONTROLES:
        v = con.execute(sql).fetchone()[0]
        sortie.append((nom, f"{100 * v:.1f} %".replace(".", ",") if unite == "pct" else f"{v:.1f} min".replace(".", ",")))
    return sortie


def main():
    for chemin in (SORTIE / f"{NOM}.SemanticModel", SORTIE / f"{NOM}.Report"):
        if chemin.exists():
            shutil.rmtree(chemin)
    controles = valeurs_controle()
    generer_modele(SORTIE / f"{NOM}.SemanticModel")
    generer_rapport(SORTIE / f"{NOM}.Report", controles)
    _json(SORTIE / f"{NOM}.pbip", {"$schema": SCHEMA + "pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
                                   "artifacts": [{"report": {"path": f"{NOM}.Report"}}], "settings": {"enableAutoRecovery": True}})
    print(f"Projet généré dans {SORTIE} : {len(TABLES)} tables, {len(MESURES) + len(CONTROLES)} mesures, "
          f"{len(RELATIONS)} relations, {len(pages(controles))} pages")
    for nom, attendu in controles:
        print(f"  {nom} : {attendu}")


if __name__ == "__main__":
    main()
