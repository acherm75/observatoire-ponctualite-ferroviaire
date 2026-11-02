-- Régularité TER par région actuelle (découpage 2016) et par mois.
-- Les anciennes régions et les lots ouverts à la concurrence sont rattachés
-- à leur région actuelle. Attention : certaines périodes ne couvrent qu'une
-- partie de la région (voir nb_perimetres_source / perimetres_source).
with ter as (
    select t.*, r.region
    from {{ ref('stg_ter_regularite') }} t
    join {{ ref('ref_regions_ter') }} r using (region_source)
),

agg as (
    select
        region,
        mois,
        count(*)                                        as nb_perimetres_source,
        string_agg(region_source, ', ' order by region_source) as perimetres_source,
        sum(nb_trains_prevus)                           as nb_trains_prevus,
        sum(nb_trains_circules)                         as nb_trains_circules,
        sum(nb_trains_annules)                          as nb_trains_annules,
        sum(nb_trains_retard_arrivee)                   as nb_trains_retard_arrivee,
        string_agg(commentaire, ' | ')                  as commentaires
    from ter
    group by all
)

select
    a.*,
    case when nb_trains_circules > 0 then 1 - nb_trains_retard_arrivee / nb_trains_circules end as taux_ponctualite,
    case when nb_trains_prevus > 0 then nb_trains_annules / nb_trains_prevus end                as taux_annulation,
    m.precipitations_mm      as meteo_precipitations_mm,
    m.nb_jours_pluie_forte   as meteo_jours_pluie_forte,
    m.temperature_moy_c      as meteo_temperature_moy_c,
    m.nb_jours_gel           as meteo_jours_gel,
    m.nb_jours_chaleur       as meteo_jours_chaleur,
    m.nb_jours_vent_fort     as meteo_jours_vent_fort
from agg a
left join {{ ref('fct_meteo_region_mois') }} m using (region, mois)
