select
    region,
    count(*)                       as nb_departements,
    string_agg(code_departement, ', ' order by code_departement) as departements
from {{ ref('ref_departements') }}
group by region
