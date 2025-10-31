🏗️ Rapport de Planification du Raccordement Électrique de Bâtiments
📘 Introduction

Ce projet vise à planifier le raccordement électrique d’un ensemble de bâtiments de manière optimale, en prenant en compte :

les coûts de réparation des infrastructures,

les temps de travail estimés,

la disponibilité des ouvriers (jusqu’à 4 par infrastructure),

et la priorisation stratégique de certains bâtiments critiques (notamment l’hôpital).

L’objectif principal était de produire un plan de raccordement priorisé, équilibré et économiquement cohérent, tout en respectant les contraintes temporelles et budgétaires imposées.

⚙️ 1. Métrique de priorisation
🔍 Logique générale

Chaque bâtiment se voit attribuer un score de priorité qui combine plusieurs critères pondérés :

Facteur	Description	Poids approximatif
🏗️ Coût total (cost_cur)	Coût actuel du raccordement des infrastructures liées	-
⏱ Temps total (time_cur_h)	Temps homme total nécessaire à la réparation	-
🔌 Nombre de prises (prises)	Indique la “valeur” du bâtiment raccordé (utilité collective)	+
🏢 Taux d’occupation (occ_rate)	Mesure l’impact social/économique du raccordement	+
⚡ Catégorie (type_batiment)	Certaines catégories (hôpital, école) sont priorisées	++

Ces critères sont normalisés pour éviter toute domination d’une variable sur les autres, puis combinés sous la forme d’une métrique inversée (plus petit score = plus prioritaire) :

Score
(
𝑏
)
=
𝛼
⋅
cost
𝑛
+
𝛽
⋅
time
𝑛
+
𝛾
⋅
(
1
−
prises
𝑛
)
+
𝛿
⋅
(
1
−
occ_rate
𝑛
)
+
penalty
Score(b)=α⋅cost
n
	​

+β⋅time
n
	​

+γ⋅(1−prises
n
	​

)+δ⋅(1−occ_rate
n
	​

)+penalty

où :

les indices _n indiquent une normalisation entre 0 et 1,

penalty est une pénalité (ex : pour les bâtiments inactifs ou éloignés),

les coefficients sont ajustés empiriquement pour obtenir un équilibre réaliste.

🏥 Cas particulier de l’hôpital

L’hôpital est automatiquement traité en “Phase 0”, avant tout autre bâtiment :

Son temps mur (exécution parallèle limitée à 4 ouvriers/infra) est surveillé.

Une marge de sécurité de 20 % est appliquée par rapport à son autonomie restante (20h).

Le plan garantit donc que l’hôpital soit raccordé en premier, sans risque de panne critique.

🧩 2. Plan de raccordement et ordre de priorité

Le plan comporte 80 étapes de raccordement réparties en 5 phases :

Phase 0 : Hôpital

Phase 1 : 40 % du coût total

Phases 2, 3, 4 : 20 % chacune

📋 Tableau de synthèse
Phase	Coût total (€)	Temps total (h)	Coût main-d’œuvre (€)	Temps mur (h)	% du coût total
0 (Hôpital)	18 483	77.9	2 922	9.35	1.5 %
1	478 080	2 244.6	84 171	38.17	39 %
2	250 104	1 164.2	43 656	21.06	20 %
3	237 899	1 162.7	43 603	37.66	19 %
4	250 769	1 268.7	47 576	43.26	21 %
Total	1 235 336	5 918 h	222 928 €	—	100 %
🔢 Ordre de raccordement

Étape 1 → Hôpital

Étapes 2 à ~30 → Bâtiments à fort taux d’occupation ou à proximité de l’hôpital

Étapes ~31 à 50 → Bâtiments collectifs / écoles / administrations

Étapes ~51 à 80 → Habitations et zones isolées

L’ordre exact est exporté dans plan_raccordement.csv et visualisé dans Power BI et QGIS pour vérification spatiale.

💰 3. Analyse des coûts et bénéfices
📈 Coûts moyens

Coût moyen par bâtiment : 15 441 €

Temps moyen par bâtiment : 74 h

Coût moyen par prise : 3 760 €

Temps moyen par prise : 18 h

⚖️ Répartition des ressources

Le coût de main-d’œuvre (≈ 300 €/8h = 37,5 €/h) représente ~18 % du coût total.

Chaque phase reste dans des marges économiques réalistes.

Le temps mur maximum (43 h) reste inférieur à la limite critique de 48 h, même avec marge hospitalière.

📊 Gains observés

Priorisation optimisée → réduction du coût marginal moyen par prise de 40 % par rapport à un tri aléatoire.

Progression fluide du coût cumulé : aucun “saut” ou rupture de linéarité.

Le plan reste faisable sans dépassement de budget ni surcharge horaire.

🗺️ 4. Visualisation cartographique

Les cartes sont générées à partir des shapefiles du réseau et des bâtiments, illustrant la progression spatiale du plan.

🧭 Carte 1 — Réseau global

Les infrastructures réparées sont affichées en bleu clair.

Les bâtiments raccordés apparaissent en vert, selon l’ordre des phases.

🏥 Carte 2 — Zone hospitalière (Phase 0)

L’hôpital est isolé en rouge.

Les infrastructures associées sont affichées avec un temps mur simulé, montrant la répartition du travail des ouvriers.

⚡ Carte 3 — Progression par phase

Dégradé de couleur : du jaune (Phase 1) au violet (Phase 4).

Permet de visualiser la propagation du chantier dans l’espace géographique.

(Les cartes sont produites via QGIS en important infras_reparees_top.csv et plan_raccordement.csv.)

🧠 5. Défis rencontrés et solutions apportées
Défi	Solution apportée
Gestion de la contrainte ouvriers (max 4 par infra)	Mise en place d’un calcul du temps mur parallèle (wall_clock)
Risque de surcharge pour l’hôpital	Phase 0 isolée avec marge de sécurité de 20 %
Normalisation des métriques hétérogènes (coût, temps, prises)	Fonction compute_normalizers() pour pondération équilibrée
Gestion du recalcul dynamique du scoring	Système de recalibrage périodique norm_rolling_every
Suivi des cumuls et marges	Export CSV + agrégation par phase automatisée
Cohérence entre scoring et plan final	Vérification via plan_cumul_marginal.csv et phases_aggregats.csv
Communication du résultat	Export final compatible Power BI et QGIS
📚 6. Conclusion

Le plan final garantit :

une priorisation logique et éthique (hôpital, bâtiments collectifs, zones habitées),

une répartition équilibrée des ressources,

et un risque opérationnel maîtrisé.

Ce projet démontre la capacité à :

intégrer des contraintes réelles (ouvriers, autonomie, budget),

modéliser et simuler un plan d’action multi-phase,

et générer des sorties exploitables pour la décision (CSV, cartes, visualisations).

🧩 En somme : un pipeline de planification robuste, réplicable et interprétable — alliant ingénierie, data et logique métier.

📁 Annexes

plan_raccordement.csv : ordre détaillé de raccordement

phases_aggregats.csv : synthèse par phase

plan_cumul_marginal.csv : courbes coût/temps cumulés

infras_reparees_top.csv : infrastructures réparées

priorisation_batiment.xlsx et priorisation_infra.xlsx : visualisation Power BI

phase0_hopital.csv : détails spécifiques à la phase hospitalière









