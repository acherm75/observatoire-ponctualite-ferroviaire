# Rapport Power BI

Le rapport s'appuie directement sur les fichiers Parquet de `data/marts/`, c'est-à-dire le même modèle
en étoile que l'app Streamlit.

> Power BI Desktop ne fonctionne que sous Windows. Sur Mac : machine virtuelle (Parallels, UTM), PC de
> l'école ou Windows 365. Le fichier `.pbix` final se publie ensuite sur Power BI Service, et une capture
> d'écran ou un PDF peut aller dans `docs/`.

## 1. Import

*Obtenir les données → Parquet* pour chaque fichier (ou *Dossier* sur `data/marts`, puis filtrer) :

`dim_date`, `dim_liaison`, `dim_gare`, `dim_region`, `dim_cause`,
`fct_regularite_liaison_mois`, `fct_causes_retard_mois`, `fct_regularite_ter_mois`, `fct_meteo_region_mois`,
`ml_prevision_mois_suivant`.

Astuce : pour pointer vers le dépôt GitHub (données mises à jour chaque jour par la CI), utiliser la source
*Web* avec l'URL brute `https://raw.githubusercontent.com/<compte>/<repo>/main/data/marts/<table>.parquet`.

## 2. Relations (vue Modèle)

| De (plusieurs) | Vers (un) | Clé |
|---|---|---|
| fct_regularite_liaison_mois | dim_date | mois |
| fct_regularite_liaison_mois | dim_liaison | liaison_id |
| fct_causes_retard_mois | dim_date | mois |
| fct_causes_retard_mois | dim_liaison | liaison_id |
| fct_causes_retard_mois | dim_cause | code_cause |
| fct_regularite_ter_mois | dim_date | mois |
| fct_regularite_ter_mois | dim_region | region |
| fct_meteo_region_mois | dim_date | mois |
| fct_meteo_region_mois | dim_region | region |
| dim_liaison | dim_gare | gare_depart_id → gare_id (relation active) |
| ml_prevision_mois_suivant | dim_liaison | liaison_id |

Marquer `dim_date` comme table de dates (colonne `mois`).

## 3. Mesures DAX

```dax
Trains circulés = SUM ( fct_regularite_liaison_mois[nb_trains_circules] )
Trains en retard = SUM ( fct_regularite_liaison_mois[nb_trains_retard_arrivee] )
Ponctualité =
    DIVIDE ( [Trains circulés] - [Trains en retard], [Trains circulés] )
Taux d'annulation =
    DIVIDE ( SUM ( fct_regularite_liaison_mois[nb_trains_annules] ),
             SUM ( fct_regularite_liaison_mois[nb_trains_prevus] ) )
Ponctualité N-1 =
    CALCULATE ( [Ponctualité], SAMEPERIODLASTYEAR ( dim_date[mois] ) )
Écart vs N-1 (pts) = ( [Ponctualité] - [Ponctualité N-1] ) * 100
Ponctualité 12 mois glissants =
    CALCULATE ( [Ponctualité],
        DATESINPERIOD ( dim_date[mois], MAX ( dim_date[mois] ), -12, MONTH ) )

Ponctualité TER =
    DIVIDE (
        SUM ( fct_regularite_ter_mois[nb_trains_circules] ) - SUM ( fct_regularite_ter_mois[nb_trains_retard_arrivee] ),
        SUM ( fct_regularite_ter_mois[nb_trains_circules] ) )

Retards imputés = SUM ( fct_causes_retard_mois[nb_trains_retard_imputes] )
Part de la cause =
    DIVIDE ( [Retards imputés], CALCULATE ( [Retards imputés], ALL ( dim_cause ) ) )
```

## 4. Pages proposées

1. **Synthèse** : cartes (ponctualité TGV / TER / Intercités, écart N-1), courbe 12 mois glissants, segment activité / année.
2. **Liaisons** : tableau classé par ponctualité avec mise en forme conditionnelle, filtre « trains circulés > 500 », info-bulle avec la courbe mensuelle de la liaison.
3. **Causes** : histogramme empilé 100 % par année (`dim_cause[libelle_cause]`), regroupement par `responsable`, note sur la rupture de mai 2026.
4. **Régions TER** : matrice région × année avec échelle de couleurs, carte (Azure Maps ou carte remplie) sur `dim_region`.
5. **Météo** : nuage de points `fct_regularite_ter_mois` (ponctualité vs jours de chaleur), segment saison.
6. **Prévisions** : tableau de `ml_prevision_mois_suivant` avec le taux prévu comparé à la moyenne sur 12 mois.
