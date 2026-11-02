-- Dimension calendrier au grain mensuel (+12 mois pour les prévisions).
with mois as (
    select cast(unnest(generate_series(date '2013-01-01',
        cast(date_trunc('month', current_date) + interval 12 month as date), interval 1 month)) as date) as mois
)

select
    mois,
    year(mois)                                         as annee,
    month(mois)                                        as num_mois,
    strftime(mois, '%Y-%m')                            as annee_mois,
    quarter(mois)                                      as trimestre,
    ['janvier','février','mars','avril','mai','juin','juillet','août',
     'septembre','octobre','novembre','décembre'][month(mois)] as nom_mois,
    case when month(mois) in (12, 1, 2) then 'Hiver'
         when month(mois) in (3, 4, 5)  then 'Printemps'
         when month(mois) in (6, 7, 8)  then 'Été'
         else 'Automne' end                            as saison,
    month(mois) in (7, 8)                              as est_vacances_ete,
    mois between date '2020-03-01' and date '2021-06-01' as est_periode_covid
from mois
