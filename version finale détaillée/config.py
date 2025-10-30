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
