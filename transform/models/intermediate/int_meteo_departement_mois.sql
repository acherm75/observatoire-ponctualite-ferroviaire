-- Moyenne des stations d'un département, par mois.
select
    code_departement,
    mois,
    count(*)                         as nb_stations,
    avg(precipitations_mm)           as precipitations_mm,
    avg(nb_jours_pluie_forte)        as nb_jours_pluie_forte,
    avg(temperature_moy_c)           as temperature_moy_c,
    avg(temperature_min_c)           as temperature_min_c,
    avg(temperature_max_c)           as temperature_max_c,
    avg(nb_jours_gel)                as nb_jours_gel,
    avg(nb_jours_chaleur)            as nb_jours_chaleur,
    avg(nb_jours_vent_fort)          as nb_jours_vent_fort
from {{ ref('stg_meteo_station_mois') }}
group by all
