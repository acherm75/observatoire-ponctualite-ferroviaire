-- Test singulier : quand les causes sont renseignées, leur somme doit faire ~100 %.
-- Tolérance de 2 points (arrondis de la source). Sévérité warn : quelques lignes
-- de la source sont à 85-99 %, on veut les voir sans bloquer le pipeline.
{{ config(severity='warn') }}
select liaison_id, mois, sum(part_cause) as total
from {{ ref('fct_causes_retard_mois') }}
group by all
having abs(sum(part_cause) - 1) > 0.02
