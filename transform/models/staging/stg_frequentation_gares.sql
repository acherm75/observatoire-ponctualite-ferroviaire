-- Fréquentation annuelle des gares, passée du format large (une colonne par année) au format long.
-- Deux jeux SNCF : l'archive 2015-2024 et le jeu courant (années récentes). Les colonnes d'années sont
-- repérées par motif (total_voyageurs_AAAA, ou totalvoyageurs2017 dans l'archive) : une nouvelle année
-- publiée est prise en compte sans modifier ce modèle. Les colonnes « non_voyageurs » sont exclues.
{% set colonnes_annees = "columns('^total_?voyageurs_?[0-9]{4}$')" %}

with archive as (
    unpivot (
        select code_uic_complet, nom_gare, code_postal, segmentation_drg, {{ colonnes_annees }}
        from {{ source('raw', 'frequentation_gares') }}
    ) on {{ colonnes_annees }} into name colonne value nb_voyageurs
),

recent as (
    unpivot (
        select code_uic_complet, nom_gare, code_postal, segmentation_drg, {{ colonnes_annees }}
        from {{ source('raw', 'frequentation_gares_recent') }}
    ) on {{ colonnes_annees }} into name colonne value nb_voyageurs
),

tout as (
    select *, 1 as priorite from recent
    union all by name
    select *, 2 as priorite from archive
)

select
    code_uic_complet                                        as code_uic,
    nom_gare,
    code_postal,
    left(code_postal, 2)                                    as code_departement,
    segmentation_drg,
    cast(regexp_extract(colonne, '[0-9]{4}$') as integer)   as annee,
    nb_voyageurs
from tout
-- Si une année figure dans les deux jeux, le jeu courant fait foi.
qualify row_number() over (partition by code_uic_complet, annee order by priorite) = 1
