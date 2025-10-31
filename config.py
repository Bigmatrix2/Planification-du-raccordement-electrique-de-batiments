# Paramètres du modèle

PARAMS = {
    # Poids de la métrique bâtiment
    "W_CAT": 1.0,
    "W_COST": 0.7,
    "W_TIME": 0.3,
    "W_GAIN": 0.2,
    "W_RES": 0.1,
    # Pénalité "non habité" (score *= 1+P_UNINHABITED)
    "P_UNINHABITED": 4.0,  # => x5 par défaut
    # Normalisation "rolling"
    "NORM_ROLLING_EVERY": 25,  # 0 = figée, sinon p.ex. 25
    # Contraintes d'arrêt (None = illimité)
    "MAX_BUDGET": None,       # en euros
    "MAX_HOURS": None,        # en heures
    # --- Main d'oeuvre & cadence ---
    "WORKER_COST_EUR_PER_H": 37.5,  # 300€/8h
    "WORKERS_PER_INFRA_MAX": 4,
    "HOPITAL_MAX_WALL_HOURS": 16.0,  # 20h avec 20% de marge => 16h
    # Poids du temps mur (wall-clock) par prise
    "W_WALL": 0.25,      # ajuste entre 0.15 et 0.40 selon ta sensibilité
    # Utiliser le coût économique (matériaux + main-d'œuvre) dans le coût/prise
    "INCLUDE_LABOUR_IN_COST": True,

}

# Catégories de bâtiment
CAT_MAP = {
    "hopital": 0.0, "hôpital": 0.0,
    "ecole": 0.5, "école": 0.5,
    "habitation": 1.0,
}

# Barèmes (€/m et h/m)
COST_PER_M = {"aerien": 500.0, "semi-aerien": 750.0, "fourreau": 900.0}
H_PER_M    = {"aerien": 2.0,   "semi-aerien": 4.0,   "fourreau": 5.0}

# Types d'infra attendus (pour validation)
EXPECTED_INFRA_TYPES = set(k.lower() for k in COST_PER_M.keys())
