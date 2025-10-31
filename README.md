# Planification du Raccordement Électrique de Bâtiments

## Introduction

Ce projet vise à **planifier le raccordement électrique d’un ensemble de bâtiments** de manière optimale, en prenant en compte :

- les **coûts de réparation des infrastructures**,
- les **temps de travail estimés**,
- la **disponibilité des ouvriers** (jusqu’à 4 par infrastructure),
- et la **priorisation stratégique** de certains bâtiments critiques (notamment l’hôpital).

L’objectif principal était de produire un **plan de raccordement priorisé, équilibré et économiquement cohérent**, tout en respectant les contraintes temporelles et budgétaires imposées.

---

## 1. Métrique de priorisation

### Logique générale

Chaque bâtiment reçoit un **score de priorité** basé sur plusieurs critères pondérés :

| Facteur | Description | Poids approximatif |
|----------|-------------|--------------------|
|  Coût total (`cost_cur`) | Coût actuel du raccordement des infrastructures liées | - |
|  Temps total (`time_cur_h`) | Temps homme total nécessaire à la réparation | - |
|  Nombre de prises (`prises`) | Mesure la "valeur" du bâtiment raccordé (utilité collective) | + |
|  Taux d’occupation (`occ_rate`) | Impact social/économique du raccordement | + |
|  Catégorie (`type_batiment`) | Certaines catégories (hôpital, école) sont priorisées | ++ |

Les critères sont **normalisés** (entre 0 et 1) puis combinés dans une formule de score inversée  
(plus petit score = plus prioritaire) :

<img width="1242" height="80" alt="image" src="https://github.com/user-attachments/assets/ed0322ae-5dce-43e6-8340-7f47dedfa7ff" />


où :
- `penalty` = pénalités (ex : bâtiments inactifs, isolés, ou peu rentables)
- les coefficients sont ajustés empiriquement pour équilibrer le modèle

###  Cas particulier de l’hôpital

L’hôpital est **automatiquement traité en "Phase 0"**, avant tout autre bâtiment :

- Son **temps mur** (temps minimal en exécution parallèle avec 4 ouvriers max/infra) est contrôlé.
- Une **marge de sécurité de 20 %** est appliquée par rapport à son autonomie restante (20h).
- Le plan garantit donc que l’hôpital soit **raccordé en premier, sans risque de panne critique**.

---

##  2. Plan de raccordement et ordre de priorité

Le plan comporte **80 étapes de raccordement** réparties en **5 phases** :

- **Phase 0 :** Hôpital  
- **Phase 1 :** 40 % du coût total  
- **Phases 2, 3, 4 :** 20 % chacune  

###  Tableau de synthèse

| Phase | Coût total (€) | Temps total (h) | Coût main-d’œuvre (€) | Temps mur (h) | % du coût total |
|-------|----------------:|----------------:|----------------------:|---------------:|----------------:|
| 0 (Hôpital) | 18 483 | 77.9 | 2 922 | 9.35 | 1.5 % |
| 1 | 478 080 | 2 244.6 | 84 171 | 38.17 | 39 % |
| 2 | 250 104 | 1 164.2 | 43 656 | 21.06 | 20 % |
| 3 | 237 899 | 1 162.7 | 43 603 | 37.66 | 19 % |
| 4 | 250 769 | 1 268.7 | 47 576 | 43.26 | 21 % |
| **Total** | **1 235 336** | **5 918 h** | **222 928 €** | — | **100 %** |

###  Ordre de raccordement

- Étape 1 → Hôpital  
- Étapes 2 à ~30 → Bâtiments à fort taux d’occupation ou proches de l’hôpital  
- Étapes ~31 à 50 → Bâtiments collectifs / écoles / administrations  
- Étapes ~51 à 80 → Habitations et zones isolées  

L’ordre complet est disponible dans le fichier `plan_raccordement.csv`.

---

##  3. Analyse des coûts et bénéfices

###  Coûts moyens

- **Coût moyen par bâtiment :** 15 441 €  
- **Temps moyen par bâtiment :** 74 h  
- **Coût moyen par prise :** 3 760 €  
- **Temps moyen par prise :** 18 h  

###  Répartition des ressources

- Le **coût de main-d’œuvre** (≈ 37,5 €/h) représente **~18 % du coût total**.  
- Chaque phase reste dans des marges économiques réalistes.  
- Le **temps mur maximum (43 h)** reste **inférieur à la limite critique (48 h)** avec la marge hospitalière.

###  Gains observés

- La priorisation a permis de **réduire le coût marginal moyen par prise de ~40 %** par rapport à un tri aléatoire.  
- La progression du coût cumulé est **linéaire et stable** → pas de rupture ni de blocage.  
- Le plan complet respecte **toutes les contraintes budgétaires et temporelles**.

---

##  4. Visualisation cartographique

Les cartes sont générées à partir des shapefiles (réseau et bâtiments) dans QGIS.

###  Carte 1 — Réseau global
<img width="990" height="726" alt="image" src="https://github.com/user-attachments/assets/1ea80150-613b-461e-85ef-cdbfbabaca8f" />

- Infrastructures : intacte en gris et à replacer en rouge.

  <img width="958" height="669" alt="image" src="https://github.com/user-attachments/assets/7475aff7-36d8-4366-9c69-33a70db5f827" />
  <img width="334" height="162" alt="image" src="https://github.com/user-attachments/assets/c75c9fcb-0e35-47a9-a76c-51e2a62aa0fd" />

- Bâtiments : phase 0 (hopital) en rouge 

###  Carte 2 — Zone hospitalière

<img width="741" height="632" alt="image" src="https://github.com/user-attachments/assets/5de3c078-f259-41a8-93a6-c720f6e9b966" />

- Hôpital → **rouge**
- Infrastructures associées à réparer 


*(Les shapefiles proviennent des exports `infras_reparees_top.csv` et `plan_raccordement.csv`.)*

---

##  5. Défis rencontrés et solutions apportées

| Défi | Solution apportée |
|------|-------------------|
| Limitation à 4 ouvriers par infrastructure | Calcul du **temps mur** (_wall_clock_) |
| Risque de surcharge pour l’hôpital | Phase 0 isolée + marge de sécurité 20 % |
| Normalisation des variables hétérogènes | Fonction `compute_normalizers()` |
| Recalibrage dynamique du scoring | Paramètre `norm_rolling_every` |
| Suivi des cumuls et marges | Exports CSV + agrégation automatique |
| Cohérence scoring / plan final | Vérification via `plan_cumul_marginal.csv` |
| Communication des résultats | Exports compatibles **Power BI** et **QGIS** |

---

##  6. Conclusion

Le plan garantit :
- une **priorisation logique et éthique** (hôpital, écoles, zones habitées),
- une **répartition équilibrée des ressources**,
- un **risque opérationnel maîtrisé** (aucune surcharge).

Ce projet démontre la capacité à :
- intégrer des contraintes réelles (ouvriers, autonomie, budget),
- modéliser et simuler un plan multi-phase,
- et générer des exports décisionnels exploitables.

>  En somme : un pipeline de planification robuste, réplicable et interprétable — alliant ingénierie, data et logique métier.

---

##  Annexes

- `plan_raccordement.csv` → Ordre détaillé des raccordements  
- `phases_aggregats.csv` → Synthèse par phase  
- `plan_cumul_marginal.csv` → Courbes coût/temps cumulés  
- `infras_reparees_top.csv` → Infrastructures réparées  
- `priorisation_batiment.xlsx` et `priorisation_infra.xlsx` → Visualisation Power BI  
- `phase0_hopital.csv` → Détails de la phase hospitalière









