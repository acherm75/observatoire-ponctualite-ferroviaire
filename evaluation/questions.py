"""Jeu de questions de l'évaluation de l'assistant.

Chaque question a une requête SQL de référence, exécutée sur les données du jour : la réponse
attendue suit donc automatiquement les mises à jour du pipeline. `verifs` dit ce que la réponse
de l'assistant doit contenir, pour CHAQUE ligne du résultat de référence :
- "pct"    : colonnes de taux (0-1), à retrouver en pourcentage à 0,15 point près ;
- "texte"  : colonnes de libellés (liaison, région, mois…) à retrouver dans la réponse ;
- "nombre" : colonnes de valeurs brutes, à 0,5 % près ;
- "refus"  : question hors périmètre, l'assistant doit dire qu'il ne peut pas répondre.

Plusieurs questions contiennent un piège connu (moyenne de taux au lieu d'un recalcul à partir
des sommes, lignes incohérentes, rupture de nomenclature, dernier mois différent selon l'activité).
"""

# Ponctualité recalculée à partir des sommes, comme l'exigent les règles métier de l'agent.
_PONCT = "1 - sum(nb_trains_retard_arrivee) / sum(nb_trains_circules)"

QUESTIONS = [
    # ---------------------------------------------------------------- valeurs nationales
    {"id": "q01", "categorie": "national",
     "question": "Quelle a été la ponctualité moyenne des TGV en 2025 ?",
     "sql": f"select {_PONCT} as ponctualite from mart_ponctualite_nationale_mois where activite = 'TGV' and year(mois) = 2025",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q02", "categorie": "national",
     "question": "Quel est le taux de ponctualité des TER sur l'année 2025 ?",
     "sql": f"select {_PONCT} as ponctualite from mart_ponctualite_nationale_mois where activite = 'TER' and year(mois) = 2025",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q03", "categorie": "national",
     "question": "Les Intercités étaient-ils ponctuels en 2025 ? Donne le taux.",
     "sql": f"select {_PONCT} as ponctualite from mart_ponctualite_nationale_mois where activite = 'Intercités' and year(mois) = 2025",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q04", "categorie": "comparaison",
     "question": "En 2024, les TER étaient-ils plus ponctuels que les TGV ?",
     "sql": f"select activite, {_PONCT} as ponctualite from mart_ponctualite_nationale_mois where activite in ('TER', 'TGV') and year(mois) = 2024 group by 1",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q05", "categorie": "comparaison",
     "question": "La ponctualité des TGV s'est-elle améliorée entre 2019 et 2025 ?",
     "sql": f"select year(mois) as annee, {_PONCT} as ponctualite from mart_ponctualite_nationale_mois where activite = 'TGV' and year(mois) in (2019, 2025) group by 1",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q06", "categorie": "national",
     "question": "Combien de trains TGV ont circulé en 2025 ?",
     "sql": "select sum(nb_trains_circules) as trains from mart_ponctualite_nationale_mois where activite = 'TGV' and year(mois) = 2025",
     "verifs": {"nombre": ["trains"]}},
    {"id": "q07", "categorie": "national",
     "question": "Quel a été le taux d'annulation des TER en 2025 ?",
     "sql": "select sum(nb_trains_annules) / sum(nb_trains_prevus) as annulation from mart_ponctualite_nationale_mois where activite = 'TER' and year(mois) = 2025",
     "verifs": {"pct": ["annulation"]}},

    # ---------------------------------------------------------------- liaisons
    {"id": "q08", "categorie": "classement",
     "question": "Quelles sont les 5 liaisons TGV nationales les moins ponctuelles en 2025 ?",
     "sql": f"""select l.libelle_liaison, {_PONCT} as ponctualite
                from fct_regularite_liaison_mois f join dim_liaison l using (liaison_id)
                where f.activite = 'TGV' and l.type_service = 'National' and year(f.mois) = 2025 and not f.est_incoherent
                group by 1 order by 2 limit 5""",
     "verifs": {"texte": ["libelle_liaison"]}},
    {"id": "q09", "categorie": "classement",
     "question": "Quelle liaison TGV nationale a été la plus ponctuelle en 2025, et avec quel taux ?",
     "sql": f"""select l.libelle_liaison, {_PONCT} as ponctualite
                from fct_regularite_liaison_mois f join dim_liaison l using (liaison_id)
                where f.activite = 'TGV' and l.type_service = 'National' and year(f.mois) = 2025 and not f.est_incoherent
                group by 1 order by 2 desc limit 1""",
     "verifs": {"texte": ["libelle_liaison"], "pct": ["ponctualite"]}},
    {"id": "q10", "categorie": "liaison",
     "question": "Quelle a été la ponctualité du TGV Paris Gare de Lyon → Lyon Part-Dieu en 2025 ?",
     "sql": f"""select {_PONCT} as ponctualite from fct_regularite_liaison_mois f join dim_liaison l using (liaison_id)
                where l.libelle_liaison = 'Paris Gare de Lyon → Lyon Part-Dieu' and year(f.mois) = 2025 and not f.est_incoherent""",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q11", "categorie": "piège",
     "question": "Quel a été le retard moyen des TGV arrivés en retard en 2025, en minutes ?",
     # Piège : moyenne pondérée par le nombre de trains en retard, pas moyenne simple des liaisons.
     "sql": """select sum(retard_moyen_trains_retard_min * nb_trains_retard_arrivee) / sum(nb_trains_retard_arrivee) as minutes
               from fct_regularite_liaison_mois
               where activite = 'TGV' and year(mois) = 2025 and not est_incoherent and retard_moyen_trains_retard_min is not null""",
     "verifs": {"nombre": ["minutes"]}},
    {"id": "q12", "categorie": "national",
     "question": "Quelle part des TGV a eu plus d'une heure de retard en 2025 ?",
     "sql": """select sum(nb_trains_retard_sup_60) / sum(nb_trains_circules) as part
               from fct_regularite_liaison_mois where activite = 'TGV' and year(mois) = 2025 and not est_incoherent""",
     "verifs": {"pct": ["part"]}},

    # ---------------------------------------------------------------- TER par région
    {"id": "q13", "categorie": "classement",
     "question": "Quelle région a les TER les moins ponctuels en 2025 ?",
     "sql": f"select region, {_PONCT} as ponctualite from fct_regularite_ter_mois where year(mois) = 2025 group by 1 order by 2 limit 1",
     "verifs": {"texte": ["region"], "pct": ["ponctualite"]}},
    {"id": "q14", "categorie": "comparaison",
     "question": "La ponctualité des TER en Bretagne a-t-elle évolué entre 2019 et 2025 ?",
     "sql": f"select year(mois) as annee, {_PONCT} as ponctualite from fct_regularite_ter_mois where region = 'Bretagne' and year(mois) in (2019, 2025) group by 1",
     "verifs": {"pct": ["ponctualite"]}},
    {"id": "q15", "categorie": "liaison",
     "question": "Quelle était la ponctualité des TER en Occitanie en juillet 2025 ?",
     "sql": "select taux_ponctualite as ponctualite from fct_regularite_ter_mois where region = 'Occitanie' and mois = '2025-07-01'",
     "verifs": {"pct": ["ponctualite"]}},

    # ---------------------------------------------------------------- causes
    {"id": "q16", "categorie": "causes",
     "question": "De 2018 à avril 2026, quelle part des retards TGV de plus de 15 minutes est imputable à SNCF Réseau ?",
     "sql": """select sum(nb_trains_retard_imputes) filter (where c.responsable = 'SNCF Réseau') / sum(nb_trains_retard_imputes) as part
               from fct_causes_retard_mois f join dim_cause c using (code_cause) where f.mois < '2026-05-01'""",
     "verifs": {"pct": ["part"]}},
    {"id": "q17", "categorie": "causes",
     "question": "Quelle a été la première cause des retards TGV en 2024 ?",
     "sql": """select split_part(c.libelle_cause, ' (', 1) as cause,
                      sum(nb_trains_retard_imputes) / sum(sum(nb_trains_retard_imputes)) over () as part
               from fct_causes_retard_mois f join dim_cause c using (code_cause) where year(f.mois) = 2024
               group by 1 order by 2 desc limit 1""",
     "verifs": {"texte": ["cause"], "pct": ["part"]}},
    {"id": "q18", "categorie": "causes",
     "question": "Quelle part des retards TGV était due au matériel roulant en 2023 ?",
     "sql": """select sum(nb_trains_retard_imputes) filter (where code_cause = 'materiel_roulant') / sum(nb_trains_retard_imputes) as part
               from fct_causes_retard_mois where year(mois) = 2023""",
     "verifs": {"pct": ["part"]}},

    # ---------------------------------------------------------------- calendrier et fraîcheur
    {"id": "q19", "categorie": "classement",
     "question": "Quel a été le mois le moins ponctuel pour les TGV en 2025 ?",
     "sql": """select d.nom_mois, n.taux_ponctualite as ponctualite from mart_ponctualite_nationale_mois n join dim_date d using (mois)
               where n.activite = 'TGV' and d.annee = 2025 order by 2 limit 1""",
     "verifs": {"texte": ["nom_mois"], "pct": ["ponctualite"]}},
    {"id": "q20", "categorie": "piège",
     "question": "Jusqu'à quel mois vont les données Intercités ?",
     # Piège : le dernier mois diffère selon l'activité.
     "sql": """select d.nom_mois || ' ' || d.annee as dernier_mois from dim_date d
               where d.mois = (select max(mois) from mart_ponctualite_nationale_mois where activite = 'Intercités')""",
     "verifs": {"texte": ["dernier_mois"]}},
    {"id": "q21", "categorie": "piège",
     "question": "Quelle était la ponctualité des TGV le dernier mois disponible ?",
     "sql": """select d.nom_mois || ' ' || d.annee as mois, n.taux_ponctualite as ponctualite
               from mart_ponctualite_nationale_mois n join dim_date d using (mois)
               where n.activite = 'TGV' order by n.mois desc limit 1""",
     "verifs": {"texte": ["mois"], "pct": ["ponctualite"]}},

    # ---------------------------------------------------------------- météo et prévision
    {"id": "q22", "categorie": "météo",
     "question": "Quelle région a compté le plus de jours de gel en janvier 2024 ?",
     "sql": "select region from fct_meteo_region_mois where mois = '2024-01-01' order by nb_jours_gel desc limit 1",
     "verifs": {"texte": ["region"]}},
    {"id": "q23", "categorie": "prévision",
     "question": "Pour le mois prochain, quelle liaison a le plus fort taux de retard prévu par le modèle ?",
     "sql": """select l.libelle_liaison, p.taux_retard_prevu as taux from ml_prevision_mois_suivant p join dim_liaison l using (liaison_id)
               order by p.taux_retard_prevu desc limit 1""",
     "verifs": {"texte": ["libelle_liaison"], "pct": ["taux"]}},

    # ---------------------------------------------------------------- hors périmètre
    {"id": "q24", "categorie": "hors périmètre",
     "question": "À quelle heure part le prochain TGV de Paris à Lyon demain matin ?",
     "sql": None, "verifs": {"refus": True}},
    {"id": "q25", "categorie": "hors périmètre",
     "question": "Combien coûte un billet de TGV Paris – Marseille ?",
     "sql": None, "verifs": {"refus": True}},
    {"id": "q26", "categorie": "hors périmètre",
     "question": "Quelle est la ponctualité des vols Air France au départ de Paris ?",
     "sql": None, "verifs": {"refus": True}},
]
