-- Régularité TGV : une ligne par liaison (gare départ -> gare arrivée) et par mois.
with src as (
    select * from {{ source('raw', 'tgv_regularite') }}
),

renamed as (
    select
        cast(date_trunc('month', date) as date)           as mois,
        'TGV'                                              as activite,
        service                                            as type_service,
        gare_depart                                        as gare_depart_source,
        gare_arrivee                                       as gare_arrivee_source,
        duree_moyenne                                      as duree_moyenne_min,
        nb_train_prevu                                     as nb_trains_prevus,
        nb_annulation                                      as nb_trains_annules,
        greatest(nb_train_prevu - nb_annulation, 0)        as nb_trains_circules,
        nb_train_depart_retard                             as nb_trains_retard_depart,
        nb_train_retard_arrivee                            as nb_trains_retard_arrivee,
        nb_train_retard_sup_15                             as nb_trains_retard_sup_15,
        nb_train_retard_sup_30                             as nb_trains_retard_sup_30,
        nb_train_retard_sup_60                             as nb_trains_retard_sup_60,
        retard_moyen_arrivee                               as retard_moyen_trains_retard_min,
        retard_moyen_tous_trains_arrivee                   as retard_moyen_tous_trains_min,
        prct_cause_externe, prct_cause_infra, prct_cause_gestion_trafic,
        prct_cause_materiel_roulant, prct_cause_gestion_gare,
        prct_cause_prise_en_charge_voyageurs,
        commentaire_annulation, commentaires_retard_arrivee
    from src
)

select
    *,
    -- 272 lignes ont toutes les causes à 0 : répartition inconnue, pas "0 %".
    (coalesce(prct_cause_externe, 0) + coalesce(prct_cause_infra, 0)
     + coalesce(prct_cause_gestion_trafic, 0) + coalesce(prct_cause_materiel_roulant, 0)
     + coalesce(prct_cause_gestion_gare, 0) + coalesce(prct_cause_prise_en_charge_voyageurs, 0)) > 0
        as causes_renseignees,
    -- Incohérences de la source (ex. avril 2020 : plus d'annulations que de trains prévus).
    (nb_trains_annules > nb_trains_prevus or nb_trains_retard_arrivee > nb_trains_circules)
        as est_incoherent
from renamed
