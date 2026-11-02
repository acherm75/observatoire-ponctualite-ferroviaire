select
    liaison_id,
    activite,
    any_value(type_service)                                     as type_service,
    gare_depart_id,
    gare_arrivee_id,
    gd.nom_gare || ' → ' || ga.nom_gare                         as libelle_liaison,
    arg_max(duree_moyenne_min, mois)                            as duree_moyenne_min,
    min(mois)                                                   as premier_mois,
    max(mois)                                                   as dernier_mois
from {{ ref('int_regularite_liaison_mois') }} l
left join {{ ref('dim_gare') }} gd on gd.gare_id = l.gare_depart_id
left join {{ ref('dim_gare') }} ga on ga.gare_id = l.gare_arrivee_id
group by liaison_id, activite, gare_depart_id, gare_arrivee_id, gd.nom_gare, ga.nom_gare
