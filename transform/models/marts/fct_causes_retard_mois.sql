-- Répartition des causes de retard (TGV, trains en retard de plus de 15 min),
-- au format long : une ligne par liaison, mois et cause.
with tgv as (
    select
        'TGV' || case when type_service = 'International' then ' international' else '' end
        || ' | ' || {{ normalize_name('gare_depart_source') }} || ' > ' || {{ normalize_name('gare_arrivee_source') }} as liaison_id,
        mois,
        nb_trains_retard_sup_15,
        prct_cause_externe          as externe,
        prct_cause_infra            as infra,
        prct_cause_gestion_trafic   as gestion_trafic,
        prct_cause_materiel_roulant as materiel_roulant,
        prct_cause_gestion_gare     as gestion_gare,
        prct_cause_prise_en_charge_voyageurs as prise_en_charge_voyageurs
    from {{ ref('stg_tgv_regularite') }}
    where causes_renseignees
)

select
    liaison_id,
    mois,
    code_cause,
    part_cause / 100.0                                     as part_cause,
    nb_trains_retard_sup_15 * part_cause / 100.0           as nb_trains_retard_imputes
from tgv
unpivot (part_cause for code_cause in (
    externe, infra, gestion_trafic, materiel_roulant, gestion_gare, prise_en_charge_voyageurs))
