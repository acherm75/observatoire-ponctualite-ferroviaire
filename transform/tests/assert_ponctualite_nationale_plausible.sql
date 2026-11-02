-- Garde-fou métier : une ponctualité nationale mensuelle hors de [50 %, 100 %]
-- signale presque toujours un problème d'ingestion ou de jointure.
select * from {{ ref('mart_ponctualite_nationale_mois') }}
where taux_ponctualite < 0.5 or taux_ponctualite > 1
