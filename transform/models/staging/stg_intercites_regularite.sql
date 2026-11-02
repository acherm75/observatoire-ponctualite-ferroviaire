-- Régularité Intercités. La source contient parfois deux lignes pour un même
-- couple de gares et un même mois (ex. Paris-Toulouse jour + nuit) sans colonne
-- pour les distinguer : on les additionne et on recalcule le taux.
with src as (
    select * from {{ source('raw', 'intercites_regularite') }}
)

select
    cast(date_trunc('month', date) as date)               as mois,
    'Intercités'                                           as activite,
    'National'                                             as type_service,
    depart                                                 as gare_depart_source,
    arrivee                                                as gare_arrivee_source,
    sum(nombre_de_trains_programmes)                       as nb_trains_prevus,
    sum(nombre_de_trains_annules)                          as nb_trains_annules,
    sum(nombre_de_trains_ayant_circule)                    as nb_trains_circules,
    sum(nombre_de_trains_en_retard_a_l_arrivee)            as nb_trains_retard_arrivee,
    count(*)                                               as nb_lignes_source
from src
group by all
