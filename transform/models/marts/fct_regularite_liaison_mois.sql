-- Fait principal : régularité d'une liaison TGV / Intercités sur un mois,
-- enrichie de la météo moyenne des départements de départ et d'arrivée.
with l as (
    select * from {{ ref('int_regularite_liaison_mois') }}
),

gares as (
    select gare_id, code_departement from {{ ref('dim_gare') }}
),

meteo as (
    select * from {{ ref('int_meteo_departement_mois') }}
)

select
    l.liaison_id,
    l.mois,
    l.activite,
    l.gare_depart_id,
    l.gare_arrivee_id,
    l.nb_trains_prevus,
    l.nb_trains_annules,
    l.nb_trains_circules,
    l.nb_trains_retard_arrivee,
    l.nb_trains_retard_sup_15,
    l.nb_trains_retard_sup_30,
    l.nb_trains_retard_sup_60,
    l.retard_moyen_trains_retard_min,
    l.retard_moyen_tous_trains_min,
    case when l.nb_trains_circules > 0 and not l.est_incoherent
         then 1 - l.nb_trains_retard_arrivee / l.nb_trains_circules end   as taux_ponctualite,
    case when l.nb_trains_prevus > 0 and l.nb_trains_annules <= l.nb_trains_prevus
         then l.nb_trains_annules / l.nb_trains_prevus end                 as taux_annulation,
    l.est_incoherent,
    -- météo : moyenne des deux extrémités (une seule si l'autre est à l'étranger)
    (coalesce(md.precipitations_mm, ma.precipitations_mm) + coalesce(ma.precipitations_mm, md.precipitations_mm)) / 2 as meteo_precipitations_mm,
    (coalesce(md.nb_jours_pluie_forte, ma.nb_jours_pluie_forte) + coalesce(ma.nb_jours_pluie_forte, md.nb_jours_pluie_forte)) / 2 as meteo_jours_pluie_forte,
    (coalesce(md.temperature_moy_c, ma.temperature_moy_c) + coalesce(ma.temperature_moy_c, md.temperature_moy_c)) / 2 as meteo_temperature_moy_c,
    (coalesce(md.nb_jours_gel, ma.nb_jours_gel) + coalesce(ma.nb_jours_gel, md.nb_jours_gel)) / 2 as meteo_jours_gel,
    (coalesce(md.nb_jours_chaleur, ma.nb_jours_chaleur) + coalesce(ma.nb_jours_chaleur, md.nb_jours_chaleur)) / 2 as meteo_jours_chaleur,
    (coalesce(md.nb_jours_vent_fort, ma.nb_jours_vent_fort) + coalesce(ma.nb_jours_vent_fort, md.nb_jours_vent_fort)) / 2 as meteo_jours_vent_fort
from l
left join gares gd on gd.gare_id = l.gare_depart_id
left join gares ga on ga.gare_id = l.gare_arrivee_id
left join meteo md on md.code_departement = gd.code_departement and md.mois = l.mois
left join meteo ma on ma.code_departement = ga.code_departement and ma.mois = l.mois
