-- Régularité TER : une ligne par région "source" et par mois.
select
    cast(date_trunc('month', date) as date)                as mois,
    region                                                  as region_source,
    nombre_de_trains_programmes                             as nb_trains_prevus,
    nombre_de_trains_ayant_circule                          as nb_trains_circules,
    nombre_de_trains_annules                                as nb_trains_annules,
    nombre_de_trains_en_retard_a_l_arrivee                  as nb_trains_retard_arrivee,
    taux_de_regularite / 100.0                              as taux_regularite_source,
    commentaires                                            as commentaire
from {{ source('raw', 'ter_regularite') }}
