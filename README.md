# Planification-du-raccordement--lectrique-de-b-timents
Créer un plan de raccordement qui priorise les bâtiments les plus simples à raccorder (en minimisant les coûts) tout en maximisant le nombre de prises raccordées.

#Rédaction du rapport
# Métrique de Priorisation pour la Planification du Raccordement Électrique

## Objectif du Projet

À la suite d’intempéries ayant détruit une partie du réseau électrique d’une petite ville, la mission consiste à proposer une **planification optimale des travaux de raccordement** des bâtiments.  
L’objectif principal est double :

- 🔹 **Rétablir rapidement** la connexion électrique pour le **plus grand nombre d’habitants**.  
- 🔹 **Minimiser les coûts** et les temps d’intervention, tout en **mutualisant les lignes électriques** lorsque cela est possible.

Les données fournies comprennent :
- Un **shapefile des bâtiments** (emplacements et attributs)
- Un **shapefile des infrastructures** (lignes électriques à déployer)
- Un **fichier CSV décrivant l’arbre linéaire** du réseau (coûts, connexions, distances)

---

## Définition de la Métrique de Priorisation

Chaque bâtiment `b` reçoit un **score de priorité** `S_b` basé sur plusieurs critères économiques, techniques et humains :

\[
S_b = P(b) \times \left[
W_{cat} \cdot C_{cat} +
W_{cost} \cdot C_{cost} +
W_{time} \cdot C_{time} +
W_{wall} \cdot C_{wall} -
W_{gain} \cdot C_{gain} +
W_{res} \cdot C_{res}
\right]
\]

| Composante | Description | Normalisation | Pondération |
|-------------|-------------|----------------|--------------|
| `C_cat` | Criticité du bâtiment (école, hôpital, habitation…) | Valeur catégorielle (poids fixe) | `W_CAT` |
| `C_cost` | Coût par prise (avec ou sans main-d’œuvre) | Min-max | `W_COST` |
| `C_time` | Temps homme-heures par prise | Min-max | `W_TIME` |
| `C_wall` | Temps “mur” (4 ouvriers/infrastructure) par prise | Min-max | `W_WALL` |
| `C_gain` | Nombre de prises (bénéfice potentiel) | Min-max | `W_GAIN` (pondération négative) |
| `C_res` | Coût global résiduel (€) | Min-max | `W_RES` |

La pénalité `P(b)` reflète l’**occupation réelle du bâtiment** :

\[
P(b) =
\begin{cases}
1 + P_{uninhabited}, & \text{si le bâtiment est inhabité} \\
1, & \text{sinon}
\end{cases}
\]

---

## Normalisation et Pondération

Pour assurer une **comparabilité entre critères hétérogènes** (euros, heures, nombre de prises...), toutes les valeurs sont normalisées dans l’intervalle `[0, 1]` :

\[
C_n = \frac{X - X_{min}}{X_{max} - X_{min}}
\]

Les poids `W_x` sont définis empiriquement selon les priorités stratégiques :
- Accent sur la **réduction des coûts** (`W_COST`, `W_RES`)
- Importance du **nombre de bénéficiaires** (`W_GAIN`)
- Prise en compte du **temps de main-d’œuvre** (`W_TIME`, `W_WALL`)
- Légère pondération pour la **criticité sociale** (`W_CAT`)

---

## Contraintes Réelles Intégrées

| Paramètre | Description | Valeur indicative |
|------------|-------------|-------------------|
| `WORKERS_PER_INFRA_MAX` | Nombre maximal d’ouvriers par infrastructure | 4 |
| `WORKER_COST_EUR_PER_H` | Coût horaire moyen d’un ouvrier | 37.5 € |
| `INCLUDE_LABOUR_IN_COST` | Activation du coût de main-d’œuvre | {0,1} |

Ces contraintes permettent de relier le modèle à des **capacités opérationnelles réalistes** (temps, ressources, coûts humains).

---

## Score d’Infrastructure

Pour chaque ligne électrique `i`, un score spécifique `S_i` est également défini :

\[
S_i = \text{bonus}_{intact} + C_{cost}(i) + 0.5 \cdot T(i) - 0.3 \cdot N_{bâtiments\_desservis}
\]

Ce score favorise les **lignes intactes** ou **mutualisées** entre plusieurs bâtiments, ce qui soutient la logique de **réutilisation des infrastructures existantes**.

---

## Interprétation

- 🔹 **Score faible → haute priorité** → bâtiment rentable, rapide à raccorder, mutualisable.  
- 🔸 **Score élevé → faible priorité** → bâtiment coûteux, isolé ou peu stratégique.  

Le classement final selon `S_b` sert de **plan de raccordement optimisé**.

---

## Justification du Choix de la Métrique

Cette métrique a été conçue pour répondre directement aux **objectifs du cas d’utilisation** :  
maximiser le **nombre de citoyens reconnectés** tout en minimisant les **coûts et délais d’intervention**.

### 1. Approche multi-critères équilibrée
La métrique agrège plusieurs dimensions essentielles (coût, temps, bénéfice, criticité, ressources), permettant une **vue globale et objective** du contexte post-crise.  
Elle évite qu’un seul facteur — par exemple le coût — domine la décision, tout en assurant une priorisation juste entre bâtiments stratégiques (écoles, hôpitaux) et résidentiels.

### 2. Prise en compte de la mutualisation
En intégrant le **nombre de prises raccordées par infrastructure**, la métrique valorise la **mutualisation des lignes**, conformément à l’objectif de **maximisation du service rendu pour un coût minimal**.

### 3. Réalisme opérationnel
Les paramètres liés à la **main-d’œuvre** et à la **capacité d’intervention** (nombre d’ouvriers, temps “mur”) rendent la métrique **compatible avec les contraintes réelles** des équipes techniques.

### 4. Adaptabilité stratégique
Les **pondérations ajustables** permettent de faire évoluer la métrique selon la stratégie municipale :
- Urgence humanitaire → plus de poids sur `C_cat` et `C_time`
- Contraintes budgétaires → plus de poids sur `C_cost` et `C_res`
- Objectif social → pondération accrue sur `C_gain`

### 5. Traçabilité et transparence
Chaque score partiel étant calculé et normalisé séparément, la métrique reste **interprétable et auditée facilement**.  
Elle permet d’expliquer et de **justifier les décisions de priorisation** auprès des élus et des citoyens.

---

## Synthèse

| Avantage | Impact |
|-----------|--------|
| **Répond aux objectifs du cahier des charges** | Raccordement rapide et économique |
| **Favorise la mutualisation** | Réduction des coûts et des délais |
| **Intègre les contraintes humaines** | Réalisme opérationnel |
| **Modulable et traçable** | Transparence et adaptation stratégique |

---

## Conclusion

La **métrique de priorisation** développée agit comme un **levier de décision rationnel** pour planifier efficacement la reconstruction du réseau électrique.  
Elle garantit un **équilibre optimal entre équité, efficacité et faisabilité**, tout en servant de base solide à une éventuelle **modélisation prédictive** (IA) pour l’automatisation future des plans de raccordement.

---
