# Rapport Power BI

Le rapport est versionné au **format projet Power BI (PBIP)** dans [`powerbi/`](../powerbi/) : le modèle en
TMDL et les pages en JSON (PBIR), lisibles et comparables dans Git comme du code. Il est entièrement produit
par un script, [`powerbi/generer_pbip.py`](../powerbi/generer_pbip.py), à partir du schéma réel des Parquet
de `data/marts/`.

## Contenu

**Modèle** (même modèle en étoile que l'app Streamlit) : 12 tables chargées directement depuis les Parquet
publiés chaque jour sur GitHub (paramètre `UrlDonnees`), 14 relations (dont la gare d'arrivée en relation
inactive, utilisée via `USERELATIONSHIP`) et 42 mesures DAX rangées par dossier :

| Dossier | Exemples | Règle métier appliquée |
|---|---|---|
| Liaisons | `Ponctualité`, `Écart vs N-1`, `Retard moyen des trains en retard (min)` | Lignes incohérentes de la source exclues ; taux recalculé à partir des sommes ; retard moyen pondéré |
| National | `Ponctualité TGV / TER / Intercités`, `Ponctualité nationale 12 mois glissants` | N-1 par décalage de 12 mois (`TREATAS`), sans table de dates journalière |
| TER, Météo | `Ponctualité TER (régions)`, `Jours de chaleur (moyenne)` | |
| Causes | `Part de la cause` | Part calculée sur les 6 causes (`REMOVEFILTERS ( dim_cause )`) |
| Prévision | `Erreur absolue moyenne` | Backtest XGBoost |
| Contrôle | `Contrôle · TGV 2025`… | Voir ci-dessous |

**7 pages** : Synthèse (cartes par activité, écart N-1, tendance sur 12 mois glissants), Liaisons (classement,
évolution mensuelle au clic, ponctualité par gare), Causes des retards, Régions TER (matrice région × année),
Effet météo, Prévisions, et **Contrôle**.

**Page Contrôle** : 7 cartes recalculent dans Power BI des chiffres déjà connus (TGV 2025, Mâcon Loché → Paris,
retard moyen pondéré, part de SNCF Réseau…). La valeur attendue, calculée avec DuckDB au moment de la génération,
est écrite dans le titre de chaque carte : si une carte diffère de son titre, une mesure est fausse.

## Ouvrir le rapport (Windows)

Power BI Desktop ne fonctionne que sous Windows (sur Mac : Parallels ou UTM avec Windows 11, ou un PC de l'école).

1. Installer **Power BI Desktop** (gratuit, Microsoft Store).
2. Copier le dossier `powerbi/` du dépôt (ou cloner le dépôt) puis ouvrir **`powerbi/Observatoire.pbip`**.
   Si Desktop signale un format non pris en charge : *Fichier → Options → Fonctionnalités en préversion*, cocher
   « Power BI Project (.pbip) », « Store semantic model using TMDL format » et « Store reports using enhanced
   metadata format (PBIR) », puis redémarrer.
3. **Actualiser** (ruban Accueil). À la première actualisation, Power BI demande comment se connecter à
   `raw.githubusercontent.com` : choisir **Anonyme**, puis niveau de confidentialité **Public**.
4. Aller sur la page **Contrôle** et vérifier que chaque carte affiche la valeur de son titre.
5. Retoucher la mise en page si besoin, puis :
   - *Fichier → Enregistrer sous* → `.pbix` pour un fichier unique à partager ;
   - *Fichier → Exporter → PDF* et quelques captures pour `docs/` et le README ;
   - *Publier* vers Power BI Service si tu as un compte professionnel ou école.

Données hors ligne : remplacer la valeur du paramètre `UrlDonnees` (*Transformer les données → Gérer les
paramètres*) par un dossier local, par exemple `C:\observatoire\data\marts\` (les requêtes utilisent alors
`File.Contents` : remplacer `Web.Contents ( UrlDonnees, [ RelativePath = "x.parquet" ] )` par
`File.Contents ( UrlDonnees & "x.parquet" )`).

## Régénérer le projet

```bash
python -m powerbi.generer_pbip
```

Le script réécrit `powerbi/Observatoire.SemanticModel` et `powerbi/Observatoire.Report` : les modifications
faites à la main dans Power BI Desktop sur ces dossiers sont alors perdues. Soit on modifie le script (source de
vérité), soit on arrête de régénérer une fois le rapport retouché dans Desktop.

## Vérifications automatiques

Sans Power BI Desktop, on vérifie tout ce qui peut l'être :

- **Schémas Microsoft** : les 58 fichiers JSON du rapport sont valides au regard des schémas officiels
  ([microsoft/json-schemas](https://github.com/microsoft/json-schemas/tree/main/fabric/item/report)) ;
- **Cohérence** ([`tests/test_powerbi.py`](../tests/test_powerbi.py)) : chaque champ cité par un visuel et
  chaque référence DAX existe dans le modèle, les colonnes correspondent exactement aux Parquet, les relations
  reposent sur des clés uniques ;
- **Chiffres** : la page Contrôle, à vérifier à l'ouverture.

Ce qui ne peut être vérifié qu'en ouvrant le rapport : l'exécution des mesures DAX par le moteur et le rendu
des visuels (tailles, couleurs, lisibilité).
