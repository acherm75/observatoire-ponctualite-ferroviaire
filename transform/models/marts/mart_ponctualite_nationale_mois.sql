-- Vue synthétique : ponctualité nationale par activité et par mois (pour l'app et le ML).
with liaisons as (
    select activite, mois,
        sum(nb_trains_prevus) as nb_trains_prevus, sum(nb_trains_circules) as nb_trains_circules,
        sum(nb_trains_annules) as nb_trains_annules, sum(nb_trains_retard_arrivee) as nb_trains_retard_arrivee
    from {{ ref('fct_regularite_liaison_mois') }}
    where not est_incoherent
    group by all
),

ter as (
    select 'TER' as activite, mois,
        sum(nb_trains_prevus) as nb_trains_prevus, sum(nb_trains_circules) as nb_trains_circules,
        sum(nb_trains_annules) as nb_trains_annules, sum(nb_trains_retard_arrivee) as nb_trains_retard_arrivee
    from {{ ref('fct_regularite_ter_mois') }}
    group by all
)

select
    *,
    case when nb_trains_circules > 0 then 1 - nb_trains_retard_arrivee / nb_trains_circules end as taux_ponctualite,
    case when nb_trains_prevus > 0 then nb_trains_annules / nb_trains_prevus end                as taux_annulation
from (select * from liaisons union all by name select * from ter)
