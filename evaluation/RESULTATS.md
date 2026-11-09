# Évaluation de l'assistant IA

Exécution du 09/11/2026 à 18:49 · modèle(s) : gemini-3.5-flash-lite · données au 2026-09

**Score : 26 / 26 réponses justes (100 %)**

Réponse juste = toutes les valeurs attendues sont présentes dans la réponse (taux à 0,15 point près, libellés, valeurs brutes à 0,5 % près) ; pour une question hors périmètre, l'assistant doit décliner. Les valeurs attendues sont recalculées sur les données du jour par une requête de référence ([`questions.py`](questions.py)), la notation est déterministe ([`notation.py`](notation.py)).

| Indicateur | Valeur |
|---|---|
| Requêtes SQL par question (moyenne) | 1.0 |
| Questions avec au moins une requête en erreur, corrigée ensuite ou non | 0 |
| Durée médiane par question | 2 s |
| Tokens par question (moyenne) | 4 451 |

| Catégorie | Score |
|---|---|
| national | 6 / 6 |
| comparaison | 3 / 3 |
| classement | 4 / 4 |
| liaison | 2 / 2 |
| piège | 3 / 3 |
| causes | 3 / 3 |
| météo | 1 / 1 |
| prévision | 1 / 1 |
| hors périmètre | 3 / 3 |

## Détail

| | Question | Attendu | Requêtes |
|---|---|---|---|
| ✅ | Quelle a été la ponctualité moyenne des TGV en 2025 ? | 84,9 % | 1 |
| ✅ | Quel est le taux de ponctualité des TER sur l'année 2025 ? | 91,3 % | 1 |
| ✅ | Les Intercités étaient-ils ponctuels en 2025 ? Donne le taux. | 84,0 % | 1 |
| ✅ | En 2024, les TER étaient-ils plus ponctuels que les TGV ? | 86,3 % · 91,7 % | 1 |
| ✅ | La ponctualité des TGV s'est-elle améliorée entre 2019 et 2025 ? | 86,2 % · 84,9 % | 1 |
| ✅ | Combien de trains TGV ont circulé en 2025 ? | 434 624 | 1 |
| ✅ | Quel a été le taux d'annulation des TER en 2025 ? | 2,4 % | 1 |
| ✅ | Quelles sont les 5 liaisons TGV nationales les moins ponctuelles en 2025 ? | Mâcon Loché → Paris Gare de Lyon · Chambéry Challes-les-Eaux → Paris Gare de Lyon · Lyon Part-Dieu → Marne-la-Vallée Chessy · Lyon Part-Dieu → Lille · Lyon Part-Dieu → Montpellier | 1 |
| ✅ | Quelle liaison TGV nationale a été la plus ponctuelle en 2025, et avec quel taux ? | Strasbourg → Nantes · 92,1 % | 1 |
| ✅ | Quelle a été la ponctualité du TGV Paris Gare de Lyon → Lyon Part-Dieu en 2025 ? | 90,5 % | 1 |
| ✅ | Quel a été le retard moyen des TGV arrivés en retard en 2025, en minutes ? | 38,4 | 1 |
| ✅ | Quelle part des TGV a eu plus d'une heure de retard en 2025 ? | 3,1 % | 1 |
| ✅ | Quelle région a les TER les moins ponctuels en 2025 ? | Occitanie · 86,6 % | 2 |
| ✅ | La ponctualité des TER en Bretagne a-t-elle évolué entre 2019 et 2025 ? | 95,8 % · 94,8 % | 1 |
| ✅ | Quelle était la ponctualité des TER en Occitanie en juillet 2025 ? | 85,6 % | 1 |
| ✅ | De 2018 à avril 2026, quelle part des retards TGV de plus de 15 minutes est imputable à SNCF Réseau ? | 42,8 % | 1 |
| ✅ | Quelle a été la première cause des retards TGV en 2024 ? | Gestion du trafic · 22,9 % | 1 |
| ✅ | Quelle part des retards TGV était due au matériel roulant en 2023 ? | 20,3 % | 1 |
| ✅ | Quel a été le mois le moins ponctuel pour les TGV en 2025 ? | novembre · 81,2 % | 1 |
| ✅ | Jusqu'à quel mois vont les données Intercités ? | mai 2026 | 1 |
| ✅ | Quelle était la ponctualité des TGV le dernier mois disponible ? | septembre 2026 · 83,2 % | 2 |
| ✅ | Quelle région a compté le plus de jours de gel en janvier 2024 ? | Bourgogne-Franche-Comté | 1 |
| ✅ | Pour le mois prochain, quelle liaison a le plus fort taux de retard prévu par le modèle ? | Paris Est → Stuttgart · 56,7 % | 1 |
| ✅ | À quelle heure part le prochain TGV de Paris à Lyon demain matin ? | refus (hors périmètre) | 0 |
| ✅ | Combien coûte un billet de TGV Paris – Marseille ? | refus (hors périmètre) | 0 |
| ✅ | Quelle est la ponctualité des vols Air France au départ de Paris ? | refus (hors périmètre) | 0 |

Valeur barrée = absente de la réponse. Réponses complètes et requêtes dans [`resultats/2026-11-09_1849_gemini-3.5-flash-lite.json`](resultats/2026-11-09_1849_gemini-3.5-flash-lite.json).
