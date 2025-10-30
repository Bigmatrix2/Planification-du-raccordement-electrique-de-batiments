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

# Barèmes 
COST_PER_M = {"aerien": 500.0, "semi-aerien": 750.0, "fourreau": 900.0}
H_PER_M    = {"aerien": 2.0,   "semi-aerien": 4.0,   "fourreau": 5.0}

# Chargement & fusion

df = pd.read_excel("../fichiers/reseau_en_arbre.xlsx")
infra_meta = pd.read_csv("../fichiers/clientnv/infra.csv")
bats_meta  = pd.read_csv("../fichiers/clientnv/batiments.csv")

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

def unit_cost(row):
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    return COST_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

def unit_hours(row):
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    return H_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

df["cost_base"]   = df.apply(lambda r: unit_cost(r)  * float(r["longueur"]), axis=1)
df["time_base_h"] = df.apply(lambda r: unit_hours(r) * float(r["longueur"]), axis=1)


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
        self.time_cur_h = sum(infras[i].time_cur_h for i in self.infrastructures)

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


# 5) Planificateur (score unique)

class Planificateur:
    def __init__(self, reseau: Reseau):
        self.r = reseau
        self.plan_rows: List[Dict] = []
        self.norm = compute_normalizers(self.r.bats)

    def run(self):
        restants = set(self.r.bats.keys())

        # Phase 0: si tu veux explicitement sortir les "déjà raccordables"
        # tu peux les pousser en tête; ici le score les rendra quasi 0 de toute façon.
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
            s, _, choix, parts = scored[0]

            # snapshot "avant"
            cost_before = choix.cost_cur
            time_before = choix.time_cur_h
            prises_now  = choix.prises

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

            restants.remove(choix.bat_id)
        return self

    def df_plan(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan_rows)

# Exécution & exports

reseau = Reseau.construire(df)
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