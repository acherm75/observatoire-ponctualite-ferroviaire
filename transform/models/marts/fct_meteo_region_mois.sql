-- Météo mensuelle par région (moyenne des départements, chaque département pèse autant).
select
    d.region,
    m.mois,
    count(*)                         as nb_departements,
    sum(m.nb_stations)               as nb_stations,
    avg(m.precipitations_mm)         as precipitations_mm,
    avg(m.nb_jours_pluie_forte)      as nb_jours_pluie_forte,
    avg(m.temperature_moy_c)         as temperature_moy_c,
    avg(m.temperature_min_c)         as temperature_min_c,
    avg(m.temperature_max_c)         as temperature_max_c,
    avg(m.nb_jours_gel)              as nb_jours_gel,
    avg(m.nb_jours_chaleur)          as nb_jours_chaleur,
    avg(m.nb_jours_vent_fort)        as nb_jours_vent_fort
from {{ ref('int_meteo_departement_mois') }} m
join {{ ref('ref_departements') }} d using (code_departement)
group by all
