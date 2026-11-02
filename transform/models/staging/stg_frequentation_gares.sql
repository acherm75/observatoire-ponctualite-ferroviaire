-- Fréquentation annuelle des gares, passée du format large (une colonne par année) au format long.
with src as (
    select
        code_uic_complet as code_uic,
        nom_gare,
        code_postal,
        segmentation_drg,
        total_voyageurs_2015 as "2015", total_voyageurs_2016 as "2016",
        totalvoyageurs2017   as "2017", total_voyageurs_2018 as "2018",
        total_voyageurs_2019 as "2019", total_voyageurs_2020 as "2020",
        total_voyageurs_2021 as "2021", total_voyageurs_2022 as "2022",
        total_voyageurs_2023 as "2023", total_voyageurs_2024 as "2024"
    from {{ source('raw', 'frequentation_gares') }}
)

select
    code_uic,
    nom_gare,
    code_postal,
    left(code_postal, 2)        as code_departement,
    segmentation_drg,
    cast(annee as integer)      as annee,
    nb_voyageurs
from src
unpivot (nb_voyageurs for annee in ("2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024"))
