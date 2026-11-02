-- TGV + Intercités dans un format commun, avec identifiants de gares normalisés.
with tgv as (
    select
        mois, activite, type_service, gare_depart_source, gare_arrivee_source,
        duree_moyenne_min, nb_trains_prevus, nb_trains_annules, nb_trains_circules,
        nb_trains_retard_arrivee, nb_trains_retard_sup_15, nb_trains_retard_sup_30,
        nb_trains_retard_sup_60, retard_moyen_trains_retard_min, retard_moyen_tous_trains_min,
        est_incoherent
    from {{ ref('stg_tgv_regularite') }}
),

intercites as (
    select
        mois, activite, type_service, gare_depart_source, gare_arrivee_source,
        null::bigint as duree_moyenne_min, nb_trains_prevus, nb_trains_annules, nb_trains_circules,
        nb_trains_retard_arrivee, null::bigint, null::bigint, null::bigint, null::double, null::double,
        nb_trains_retard_arrivee > nb_trains_circules as est_incoherent
    from {{ ref('stg_intercites_regularite') }}
),

unioned as (
    select * from tgv
    union all by name
    select * from intercites
)

select
    activite || case when type_service = 'International' then ' international' else '' end
        || ' | ' || {{ normalize_name('gare_depart_source') }} || ' > ' || {{ normalize_name('gare_arrivee_source') }}
        as liaison_id,
    {{ normalize_name('gare_depart_source') }}  as gare_depart_id,
    {{ normalize_name('gare_arrivee_source') }} as gare_arrivee_id,
    *
from unioned
