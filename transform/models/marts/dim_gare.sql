-- Gares desservies par les liaisons TGV / Intercités suivies.
with gares as (
    select
        {{ normalize_name('nom_source') }} as gare_id,
        nom_gare, code_departement, pays,
        row_number() over (partition by {{ normalize_name('nom_source') }} order by nom_source) as rn
    from {{ ref('ref_gares') }}
),

frequentation as (
    select {{ normalize_name('nom_gare') }} as nom_norm, max(nb_voyageurs) as nb_voyageurs_2024
    from {{ ref('stg_frequentation_gares') }}
    where annee = 2024
    group by 1
)

select
    g.gare_id,
    g.nom_gare,
    g.code_departement,
    d.region,
    g.pays,
    g.pays <> 'France'       as est_etranger,
    f.nb_voyageurs_2024
from gares g
left join {{ ref('ref_departements') }} d using (code_departement)
left join frequentation f on f.nom_norm = {{ normalize_name('g.nom_gare') }}
where g.rn = 1
