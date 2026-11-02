-- Relevés climatologiques mensuels par station Météo-France.
select
    departement                                             as code_departement,
    num_poste                                               as code_station,
    nom_usuel                                               as nom_station,
    cast(strptime(cast(aaaamm as varchar), '%Y%m') as date) as mois,
    rr                                                      as precipitations_mm,
    nbjrr10                                                 as nb_jours_pluie_forte,
    tm                                                      as temperature_moy_c,
    tn                                                      as temperature_min_c,
    tx                                                      as temperature_max_c,
    nbjgelee                                                as nb_jours_gel,
    nbjtx30                                                 as nb_jours_chaleur,
    nbjff16                                                 as nb_jours_vent_fort
from {{ source('raw', 'meteo_mensuelle') }}
