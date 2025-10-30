import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

# Hyperparamètres ajustables

W_CAT   = 1.0
W_COST  = 0.7
W_TIME  = 0.3
W_GAIN  = 0.2
W_RES   = 0.1
P_UNINHABITED = 4.0  # score *= (1 + P_UNINHABITED) pour les non habités (donc *5 par défaut)

CAT_MAP = {"hopital": 0.0, "hôpital": 0.0, "ecole": 0.5, "école": 0.5, "habitation": 1.0}

# Barèmes matériaux et main d'œuvre
COST_PER_M = {"aerien": 500.0, "semi-aerien": 750.0, "fourreau": 900.0}  # Coût matériel €/m
H_PER_M    = {"aerien": 2.0,   "semi-aerien": 4.0,   "fourreau": 5.0}     # Heures/m par ouvrier
WORKER_COST_PER_H = 300.0 / 8.0  # 300€ pour 8h = 37.5€/h par ouvrier
MAX_WORKERS_PER_INFRA = 4  # Maximum 4 ouvriers par infrastructure
HOSPITAL_TIME_MARGIN = 0.2  # 20% de marge pour l'hôpital (16h sur 20h disponibles)
HOSPITAL_MAX_TIME = 20.0 * (1.0 - HOSPITAL_TIME_MARGIN)  # 16h maximum

# Chargement & fusion

df = pd.read_excel("./fichiers/reseau_en_arbre.xlsx")
infra_meta = pd.read_csv("./fichiers/infra.csv")
bats_meta  = pd.read_csv("./fichiers/batiments.csv")

# Normalisation des noms de colonnes potentiels - effacer les espaces
infra_meta.columns = [c.strip() for c in infra_meta.columns]
bats_meta.columns  = [c.strip() for c in bats_meta.columns]

# Ajout des colonnes souhaitées pour éviter les erreurs
if "est_habite" not in bats_meta.columns: bats_meta["est_habite"] = None
if "taux_occupation" not in bats_meta.columns: bats_meta["taux_occupation"] = None

# join type_infra sur infra_id
df = df.merge(infra_meta.rename(columns={"id_infra":"infra_id"}), on="infra_id", how="left")
# join type_batiment, nb_maisons (de bats_meta prioritaire), est_habite, taux_occupation
df = df.merge(bats_meta[["id_batiment","type_batiment","nb_maisons","est_habite","taux_occupation"]],
              on="id_batiment", how="left", suffixes=("","_from_bats"))

# nb_maisons: on prend d'abord la valeur provenant de bats_meta si dispo
if "nb_maisons_from_bats" in df.columns:
    df["nb_maisons"] = df["nb_maisons_from_bats"].fillna(df["nb_maisons"])
    df.drop(columns=["nb_maisons_from_bats"], inplace=True)
df["nb_maisons"] = df["nb_maisons"].astype(int)
# Defaults sur type_batiment & occupation
df["type_batiment"] = df["type_batiment"].fillna("habitation")

# une fonction utilitaire (helper) conçue pour nettoyer et uniformiser des valeurs booléennes (vrai/faux) venant de sources de données parfois incohérentes.
def _parse_bool_like(x):
    if pd.isna(x): return None
    s = str(x).strip().lower()
    if s in {"1","true","vrai","yes","oui","y"}: return True
    if s in {"0","false","faux","no","non","n"}: return False
    return None

# On calcule un taux_occupation unifié sur [0,1]
def compute_occ_rate(row):
    # priorité au taux_occupation s'il est fourni
    to = row.get("taux_occupation")
    if pd.notna(to):
        try:
            val = float(to);  return min(max(val, 0.0), 1.0)
        except: pass
    # sinon, on essaie est_habite
    eh = _parse_bool_like(row.get("est_habite"))
    if eh is True:  return 1.0
    if eh is False: return 0.0
    # défaut: inconnu -> considérer comme habité pour ne pas sous-estimer l'impact
    return 1.0

df["occ_rate"] = df.apply(compute_occ_rate, axis=1)
# Flag pour envoyer les non habités en dernier (1 = non habité, 0 = habité)
df["is_uninhabited"] = (df["occ_rate"] <= 0.0).astype(int)

# Contrôle de schéma
required = {"infra_id","id_batiment","longueur","infra_type","type_infra","nb_maisons","type_batiment","occ_rate","is_uninhabited"}
missing = required - set(df.columns)
if missing:
    raise ValueError(f"Colonnes manquantes après fusion: {missing}")


# 2) Coût & temps par infra

def unit_cost_material(row):
    """Coût du matériel par mètre"""
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    return COST_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

def unit_hours_per_worker(row):
    """Heures de travail par mètre pour un ouvrier"""
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    return H_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

def calculate_total_cost(row):
    """Calcule le coût total (matériel + main d'œuvre) avec parallélisme"""
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    
    longueur = float(row["longueur"])
    
    # Coût matériel
    cost_material = unit_cost_material(row) * longueur
    
    # Temps de travail avec parallélisme (4 ouvriers max)
    hours_per_worker = unit_hours_per_worker(row) * longueur
    actual_hours = hours_per_worker / MAX_WORKERS_PER_INFRA  # Temps réel avec 4 ouvriers
    
    # Coût main d'œuvre (4 ouvriers pendant actual_hours)
    cost_labor = MAX_WORKERS_PER_INFRA * actual_hours * WORKER_COST_PER_H
    
    return cost_material + cost_labor

def calculate_actual_time(row):
    """Calcule le temps réel avec parallélisme des ouvriers"""
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    
    longueur = float(row["longueur"])
    hours_per_worker = unit_hours_per_worker(row) * longueur
    
    # Temps réel avec 4 ouvriers maximum
    return hours_per_worker / MAX_WORKERS_PER_INFRA

df["cost_base"]   = df.apply(calculate_total_cost, axis=1)
df["time_base_h"] = df.apply(calculate_actual_time, axis=1)


# Modèles orientés objet

@dataclass
class Infrastructure:
    infra_id: str
    infra_type_state: str
    type_infra: str
    longueur: float
    cost_base: float
    time_base_h: float
    batiments: Set[str] = field(default_factory=set)
    cost_cur: float = 0.0
    time_cur_h: float = 0.0

    def finalize(self):
        if self.infra_type_state == "infra_intacte":
            self.cost_base = 0.0
            self.time_base_h = 0.0
        self.cost_cur   = self.cost_base
        self.time_cur_h = self.time_base_h

    def reparer(self):
        self.cost_cur = 0.0
        self.time_cur_h = 0.0

    @property
    def is_intact(self) -> int:
        return 1 if self.infra_type_state == "infra_intacte" else 0

@dataclass
class Batiment:
    bat_id: str
    nb_maisons: int
    type_batiment: str
    occ_rate: float
    is_uninhabited: int
    infrastructures: Set[str] = field(default_factory=set)

    cost_cur: float = 0.0
    time_cur_h: float = 0.0
    cat_score: float = 0.0  # 0 hôpital, 0.5 école, 1 habitation

    def maj(self, infras: Dict[str, Infrastructure]):
        self.cost_cur   = sum(infras[i].cost_cur   for i in self.infrastructures)
        # TEMPS = MAX (parallélisme entre infrastructures), pas somme !
        self.time_cur_h = max((infras[i].time_cur_h for i in self.infrastructures), default=0.0)

    @property
    def prises(self) -> int:
        return max(1, int(round(self.nb_maisons * float(self.occ_rate))))

@dataclass
class Reseau:
    infras: Dict[str, Infrastructure] = field(default_factory=dict)
    bats: Dict[str, Batiment] = field(default_factory=dict)

    @staticmethod
    def construire(df: pd.DataFrame) -> "Reseau":
        r = Reseau()
        for _, row in df.iterrows():
            iid, bid = str(row["infra_id"]), str(row["id_batiment"])
            if iid not in r.infras:
                r.infras[iid] = Infrastructure(
                    infra_id=iid,
                    infra_type_state=str(row["infra_type"]),
                    type_infra=str(row["type_infra"]) if pd.notna(row["type_infra"]) else "",
                    longueur=float(row["longueur"]),
                    cost_base=float(row["cost_base"]),
                    time_base_h=float(row["time_base_h"]),
                )
            r.infras[iid].batiments.add(bid)
            if bid not in r.bats:
                r.bats[bid] = Batiment(
                    bat_id=bid,
                    nb_maisons=int(row["nb_maisons"]),
                    type_batiment=str(row["type_batiment"]),
                    occ_rate=float(row["occ_rate"]),
                    is_uninhabited=int(row["is_uninhabited"]),
                )
            r.bats[bid].infrastructures.add(iid)
        for i in r.infras.values(): i.finalize()
        for b in r.bats.values():
            b.maj(r.infras)
            b.cat_score = CAT_MAP.get(b.type_batiment.strip().lower(), 1.0)
        return r

# 4) Normalisations (figées)

def min_max(x_min, x_max, x):
    if x_max <= x_min: return 0.0
    return (x - x_min) / (x_max - x_min)

def compute_normalizers(bats: Dict[str, Batiment]):
    # basés sur l'état initial (stables)
    costs_pp = []
    times_pp = []
    prises   = []
    costs    = []
    for b in bats.values():
        p = b.prises
        costs_pp.append(b.cost_cur / p)
        times_pp.append(b.time_cur_h / p)
        prises.append(p)
        costs.append(b.cost_cur)
    return {
        "cpp_min": min(costs_pp) if costs_pp else 0.0,
        "cpp_max": max(costs_pp) if costs_pp else 1.0,
        "tpp_min": min(times_pp) if times_pp else 0.0,
        "tpp_max": max(times_pp) if times_pp else 1.0,
        "p_min": min(prises) if prises else 1,
        "p_max": max(prises) if prises else 1,
        "c_min": min(costs) if costs else 0.0,
        "c_max": max(costs) if costs else 1.0,
    }

def score_batiment(b: Batiment, norm):
    p = b.prises
    cpp = b.cost_cur / p
    tpp = b.time_cur_h / p

    cpp_n = min_max(norm["cpp_min"], norm["cpp_max"], cpp)
    tpp_n = min_max(norm["tpp_min"], norm["tpp_max"], tpp)
    p_n   = min_max(norm["p_min"],   norm["p_max"],   p)
    c_n   = min_max(norm["c_min"],   norm["c_max"],   b.cost_cur)

    base = (W_CAT  * b.cat_score) \
         + (W_COST * cpp_n) \
         + (W_TIME * tpp_n) \
         - (W_GAIN * p_n) \
         + (W_RES  * c_n)

    # pénalise fortement le non habité (en dernier)
    penalty = (1.0 + P_UNINHABITED) if b.is_uninhabited == 1 else 1.0
    return base * penalty, {"cpp_n": cpp_n, "tpp_n": tpp_n, "p_n": p_n, "c_n": c_n, "penalty": penalty}

def score_infra(i: Infrastructure, n_bat_servis: int) -> float:
    # intacte -> énorme bonus de "dépriorisation"
    big = 1_000_000 if i.is_intact == 1 else 0
    # on préfère: coût/temps résiduels faibles, mais un grand nb de bâtiments servis
    return big + i.cost_cur + 0.5 * i.time_cur_h - 0.3 * n_bat_servis


# 5) Planificateur avec priorité hôpital et phases

def check_hospital_feasibility(reseau: Reseau) -> Tuple[bool, float, str]:
    """Vérifie si l'hôpital peut être raccordé dans les temps avec marge"""
    for bat_id, bat in reseau.bats.items():
        if bat.type_batiment.strip().lower() in ["hopital", "hôpital"]:
            print(f"\n=== DÉTAIL HÔPITAL {bat_id} ===")
            print(f"Nombre d'infrastructures: {len(bat.infrastructures)}")
            
            # Calculer le temps maximum parmi toutes ses infrastructures (parallélisme)
            temps_par_infra = []
            for infra_id in bat.infrastructures:
                infra = reseau.infras[infra_id]
                print(f"Infra {infra_id}: {infra.type_infra} - {infra.longueur}m - {infra.time_cur_h:.1f}h")
                temps_par_infra.append(infra.time_cur_h)
            
            max_time = max(temps_par_infra) if temps_par_infra else 0.0
            sum_time = sum(temps_par_infra)
            
            print(f"Temps par infra: {[f'{t:.1f}h' for t in temps_par_infra]}")
            print(f"Somme (INCORRECT): {sum_time:.1f}h")
            print(f"Maximum (CORRECT): {max_time:.1f}h")
            print(f"Temps utilisé dans le code: {bat.time_cur_h:.1f}h")
            
            feasible = max_time <= HOSPITAL_MAX_TIME
            return feasible, max_time, bat_id
    
    return True, 0.0, ""  # Pas d'hôpital trouvé

class Planificateur:
    def __init__(self, reseau: Reseau):
        self.r = reseau
        self.plan_rows: List[Dict] = []
        self.norm = compute_normalizers(self.r.bats)
        self.phase_costs = []  # Pour suivre les coûts par phase
        self.current_phase = 0

    def run(self):
        # Vérification préalable de l'hôpital
        feasible, hospital_time, hospital_id = check_hospital_feasibility(self.r)
        if not feasible:
            print(f"\u26a0\ufe0f ALERTE: L'hôpital {hospital_id} ne peut pas être raccordé dans les temps!")
            print(f"   Temps requis: {hospital_time:.1f}h, Limite: {HOSPITAL_MAX_TIME:.1f}h")
        else:
            print(f"\u2705 Hôpital vérifié: {hospital_time:.1f}h <= {HOSPITAL_MAX_TIME:.1f}h")
        
        restants = set(self.r.bats.keys())
        
        # Phase 0: PRIORITÉ ABSOLUE pour l'hôpital
        hospital_processed = False
        for bat_id in list(restants):
            bat = self.r.bats[bat_id]
            if bat.type_batiment.strip().lower() in ["hopital", "hôpital"]:
                print(f"\n=== PHASE 0: PRIORITÉ HÔPITAL {bat_id} ===")
                self._process_batiment(bat_id, restants, phase=0)
                hospital_processed = True
                break
        
        if hospital_processed:
            print(f"\u2705 Hôpital traité en priorité absolue")
        
        # Phases 1-4: Répartition par coût
        self._process_remaining_phases(restants)
        
        return self
    
    def _process_batiment(self, bat_id: str, restants: set, phase: int):
        """Traite un bâtiment spécifique"""
        # maj
        for bid in restants:
            self.r.bats[bid].maj(self.r.infras)
        
        choix = self.r.bats[bat_id]
        
        # snapshot "avant"
        cost_before = choix.cost_cur
        time_before = choix.time_cur_h
        prises_now = choix.prises
        
        # Calculer le score pour information
        s, parts = score_batiment(choix, self.norm)
        
        # réparer ses infras
        repaired = []
        for iid in choix.infrastructures:
            inf = self.r.infras[iid]
            if inf.cost_cur > 0 or inf.time_cur_h > 0:
                repaired.append(iid)
            inf.reparer()
        
        # maj après
        for bid in restants:
            self.r.bats[bid].maj(self.r.infras)
        
        self.plan_rows.append({
            "etape": len(self.plan_rows) + 1,
            "phase": phase,
            "id_batiment": choix.bat_id,
            "type_batiment": choix.type_batiment,
            "is_uninhabited": choix.is_uninhabited,
            "prises": prises_now,
            "cost_before": cost_before,
            "time_before": time_before,
            "cat_score": choix.cat_score,
            "score": s,
            "score_parts_cpp_n": parts["cpp_n"],
            "score_parts_tpp_n": parts["tpp_n"],
            "score_parts_p_n": parts["p_n"],
            "score_parts_c_n": parts["c_n"],
            "score_penalty": parts["penalty"],
            "infrastructures": sorted(list(choix.infrastructures)),
            "repaired_infras": repaired,
        })
        
        restants.remove(bat_id)
    
    def _process_remaining_phases(self, restants: set):
        """Traite les phases 1-4 avec répartition par coût"""
        if not restants:
            return
        
        # Calculer le coût total restant
        total_cost = 0.0
        for bid in restants:
            self.r.bats[bid].maj(self.r.infras)
            total_cost += self.r.bats[bid].cost_cur
        
        print(f"\nCoût total restant: {total_cost:.0f}\u20ac")
        
        # Définir les seuils de phases
        phase_thresholds = {
            1: 0.40 * total_cost,  # 40%
            2: 0.20 * total_cost,  # 20%
            3: 0.20 * total_cost,  # 20%
            4: 0.20 * total_cost,  # 20%
        }
        
        current_phase = 1
        phase_cost_accumulated = 0.0
        phase_target = phase_thresholds[current_phase]
        
        print(f"\n=== PHASE {current_phase}: Objectif {phase_target:.0f}\u20ac (40%) ===")
        
        while restants:
            # maj
            for bid in restants:
                self.r.bats[bid].maj(self.r.infras)
            
            # scores
            scored = []
            for bid in restants:
                b = self.r.bats[bid]
                s, parts = score_batiment(b, self.norm)
                scored.append((s, bid, b, parts))
            scored.sort(key=lambda x: (x[0], x[2].bat_id))
            s, bat_id, choix, parts = scored[0]
            
            # Vérifier si on doit changer de phase
            if (phase_cost_accumulated + choix.cost_cur > phase_target and 
                current_phase < 4 and len(restants) > 1):
                
                current_phase += 1
                phase_cost_accumulated = 0.0
                phase_target = phase_thresholds[current_phase]
                print(f"\n=== PHASE {current_phase}: Objectif {phase_target:.0f}\u20ac (20%) ===")
            
            # Traiter le bâtiment
            self._process_batiment(bat_id, restants, phase=current_phase)
            phase_cost_accumulated += choix.cost_cur
        
        # Boucle principale pour les bâtiments restants
        while restants:
            pass  # Cette boucle est maintenant gérée par _process_remaining_phases

    def df_plan(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan_rows)

# Exécution & exports

print("=== CONSTRUCTION DU RÉSEAU ===")
reseau = Reseau.construire(df)
print(f"Réseau construit: {len(reseau.infras)} infrastructures, {len(reseau.bats)} bâtiments")

print("\n=== PLANIFICATION AVEC NOUVELLES CONTRAINTES ===")
print(f"- Coût main d'œuvre: {WORKER_COST_PER_H:.1f}€/h par ouvrier")
print(f"- Maximum {MAX_WORKERS_PER_INFRA} ouvriers par infrastructure")
print(f"- Marge hôpital: {HOSPITAL_TIME_MARGIN*100:.0f}% (max {HOSPITAL_MAX_TIME:.0f}h)")

planif = Planificateur(reseau).run()
df_plan = planif.df_plan()

# Bâtiments (état final après plan)
rows_b = []
for b in reseau.bats.values():
    rows_b.append({
        "id_batiment": b.bat_id,
        "type_batiment": b.type_batiment,
        "is_uninhabited": b.is_uninhabited,
        "occ_rate": b.occ_rate,
        "prises_effectives": b.prises,
        "cost_residuel": b.cost_cur,
        "time_residuel": b.time_cur_h,
        "cat_score": b.cat_score,
    })
df_bats = pd.DataFrame(rows_b)

# Infrastructures (priorisation lisible: intactes en dernier)
rows_i = []
for i in reseau.infras.values():
    n_serv = len(i.batiments)
    rows_i.append({
        "infra_id": i.infra_id,
        "infra_type_state": i.infra_type_state,
        "type_infra": i.type_infra,
        "is_intact": i.is_intact,
        "n_bat_servis": n_serv,
        "cost_cur": i.cost_cur,
        "time_cur_h": i.time_cur_h,
        "score_infra": score_infra(i, n_serv),
        "batiments": sorted(list(i.batiments)),
    })
df_infra = pd.DataFrame(rows_i).sort_values(
    by=["score_infra", "infra_id"], ascending=[True, True]
).reset_index(drop=True)

# Exports
df_infra.to_excel("priorisation_infra.xlsx", index=False)
df_bats.to_excel("priorisation_batiment.xlsx", index=False)
df_plan.to_excel("plan_raccordement.xlsx", index=False)
df_plan.to_csv("plan_raccordement.csv", index=False)

print("✅ Exports : OK")