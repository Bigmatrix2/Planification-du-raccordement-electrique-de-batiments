import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

# --- 1) Chargement et fusion avec les nouvelles données 
df = pd.read_excel("../fichiers/reseau_en_arbre.xlsx")   # database de base
infra_meta = pd.read_csv("../fichiers/clientnv/infra.csv")        # id_infra, type_infra
bats_meta  = pd.read_csv("../fichiers/clientnv/batiments.csv")    # id_batiment, type_batiment, nb_maisons

# Normalisation des noms de colonnes potentiels - effacer les espaces
bats_meta.columns = [c.strip() for c in bats_meta.columns]
infra_meta.columns = [c.strip() for c in infra_meta.columns]

# Ajout des colonnes souhaitées pour éviter les erreurs
if "est_habite" not in bats_meta.columns:
    bats_meta["est_habite"] = None  # inconnu
if "taux_occupation" not in bats_meta.columns:
    bats_meta["taux_occupation"] = None  # inconnu

# join type_infra sur infra_id
df = df.merge(infra_meta.rename(columns={"id_infra":"infra_id"}), on="infra_id", how="left")

# join type_batiment, nb_maisons (de bats_meta prioritaire), est_habite, taux_occupation
df = df.merge(
    bats_meta[["id_batiment","type_batiment","nb_maisons","est_habite","taux_occupation"]],
    on="id_batiment", how="left", suffixes=("","_from_bats")
)

# nb_maisons: on prend d'abord la valeur provenant de bats_meta si dispo
df["nb_maisons"] = df["nb_maisons"].fillna(df.get("nb_maisons_from_bats"))  # au cas où le nom d'origine diffère
if "nb_maisons_from_bats" in df.columns:
    df["nb_maisons"] = df["nb_maisons_from_bats"].fillna(df["nb_maisons"])
    df.drop(columns=["nb_maisons_from_bats"], inplace=True)
df["nb_maisons"] = df["nb_maisons"].astype(int)

# Defaults sur type_batiment & occupation
df["type_batiment"] = df["type_batiment"].fillna("habitation")

# une fonction utilitaire (helper) conçue pour nettoyer et uniformiser des valeurs booléennes (vrai/faux) venant de sources de données parfois incohérentes.
def _parse_bool_like(x):
    if pd.isna(x): return None
    if isinstance(x, (int, float)):
        if x == 1: return True
        if x == 0: return False
    s = str(x).strip().lower()
    if s in {"1","true","vrai","yes","oui","y"}: return True
    if s in {"0","false","faux","no","non","n"}: return False
    return None

# On calcule un taux_occupation unifié sur [0,1]
def compute_occ_rate(row):
    # priorité au taux_occupation s'il est fourni
    to = row.get("taux_occupation")
    eh = row.get("est_habite")
    if pd.notna(to):
        try:
            val = float(to)
            if val < 0: val = 0.0
            if val > 1: val = 1.0
            return val
        except:
            pass
    # sinon, on essaie est_habite
    eh_parsed = _parse_bool_like(eh)
    if eh_parsed is True:
        return 1.0
    if eh_parsed is False:
        return 0.0
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

# Barèmes (annexe)
COST_PER_M = {"aerien": 500.0, "semi-aerien": 750.0, "fourreau": 900.0}
H_PER_M    = {"aerien": 2.0,   "semi-aerien": 4.0,   "fourreau": 5.0}

def unit_cost(row):
    if row["infra_type"] == "infra_intacte":
        return 0.0
    return COST_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

def unit_hours(row):
    if row["infra_type"] == "infra_intacte":
        return 0.0
    return H_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

df["cost_base"]   = df.apply(lambda r: unit_cost(r)  * float(r["longueur"]), axis=1)
df["time_base_h"] = df.apply(lambda r: unit_hours(r) * float(r["longueur"]), axis=1)

# Modèles orientés objet

@dataclass
class Infrastructure:
    infra_id: str
    infra_type_state: str   # 'infra_intacte' | 'a_remplacer'
    type_infra: str         # 'aerien' | 'semi-aerien' | 'fourreau' | ''
    longueur: float
    batiments: Set[str] = field(default_factory=set)
    n_bat_servis: int = 0
    cost_base: float = 0.0
    time_base_h: float = 0.0
    cost_cur: float = 0.0
    time_cur_h: float = 0.0

    def finalize(self):
        self.n_bat_servis = max(1, len(self.batiments))
        if self.infra_type_state == "infra_intacte":
            self.cost_base = 0.0
            self.time_base_h = 0.0
        self.cost_cur   = self.cost_base
        self.time_cur_h = self.time_base_h

    def reparer(self):
        self.cost_cur = 0.0
        self.time_cur_h = 0.0

@dataclass
class Batiment:
    bat_id: str
    nb_maisons: int
    type_batiment: str = "habitation"
    occ_rate: float = 1.0            # 1 si habité (ou inconnu), 0 si non habité, sinon 0..1
    is_uninhabited: int = 0          # 0 habité, 1 non habité (sert au tri)
    infrastructures: Set[str] = field(default_factory=set)

    cost_base: float = 0.0
    time_base_h: float = 0.0
    cost_cur: float = 0.0
    time_cur_h: float = 0.0
    etape: int = 0

    def maj(self, infras: Dict[str, Infrastructure]):
        self.cost_cur   = sum(infras[i].cost_cur   for i in self.infrastructures)
        self.time_cur_h = sum(infras[i].time_cur_h for i in self.infrastructures)

    @property
    def prises(self) -> int:
        # Prises "effectives" = nb_maisons * taux d'occupation (arrondi), min 1 pour éviter /0
        eff = int(round(self.nb_maisons * float(self.occ_rate)))
        return max(1, eff)

    @property
    def cost_per_prise(self) -> float:
        return self.cost_cur / self.prises

    @property
    def time_per_prise(self) -> float:
        return self.time_cur_h / self.prises

    @property
    def cat_priority(self) -> int:
        m = {"hopital": 0, "hôpital": 0, "ecole": 1, "école": 1, "habitation": 2}
        return m.get(self.type_batiment.strip().lower(), 2)

    def tri_tuple(self) -> Tuple[int, int, float, float, int, float, str]:
        # >>> is_uninhabited EN PREMIER pour envoyer les non habités en dernier globalement
        # Clé lexicographique:
        #  (is_uninhabited, cat_priority, cost_per_prise, time_per_prise, -prises, cost_cur, id)
        return (self.is_uninhabited, self.cat_priority, self.cost_per_prise,
                self.time_per_prise, -self.prises, self.cost_cur, self.bat_id)

@dataclass
class Reseau:
    infras: Dict[str, Infrastructure] = field(default_factory=dict)
    bats: Dict[str, Batiment] = field(default_factory=dict)

    @staticmethod
    def construire(df: pd.DataFrame) -> "Reseau":
        infras: Dict[str, Infrastructure] = {}
        bats: Dict[str, Batiment] = {}

        for _, r in df.iterrows():
            iid = str(r["infra_id"])
            bid = str(r["id_batiment"])

            if iid not in infras:
                infras[iid] = Infrastructure(
                    infra_id=iid,
                    infra_type_state=str(r["infra_type"]),
                    type_infra=str(r["type_infra"]) if pd.notna(r["type_infra"]) else "",
                    longueur=float(r["longueur"]),
                    cost_base=float(r["cost_base"]),
                    time_base_h=float(r["time_base_h"]),
                )
            infras[iid].batiments.add(bid)

            if bid not in bats:
                bats[bid] = Batiment(
                    bat_id=bid,
                    nb_maisons=int(r["nb_maisons"]),
                    type_batiment=str(r["type_batiment"]),
                    occ_rate=float(r["occ_rate"]),
                    is_uninhabited=int(r["is_uninhabited"]),
                )
            bats[bid].infrastructures.add(iid)

        for inf in infras.values():
            inf.finalize()

        for b in bats.values():
            b.cost_base   = sum(infras[i].cost_base   for i in b.infrastructures)
            b.time_base_h = sum(infras[i].time_base_h for i in b.infrastructures)
            b.cost_cur    = b.cost_base
            b.time_cur_h  = b.time_base_h

        return Reseau(infras=infras, bats=bats)

# l'algorithme de planification

class Planificateur:
    def __init__(self, reseau: Reseau):
        self.r = reseau
        self.plan: List[Tuple[int, str, str, int, float, float, float, float, int, List[str]]] = []
        self._etape = 0
        self._repare_infras: Set[str] = set()

    def run(self):
        # Phase 0 : déjà raccordables (coût+temps == 0)
        phase0 = [b for b in self.r.bats.values() if (b.cost_cur + b.time_cur_h) == 0.0]
        # On applique AUSSI l'ordre "habité d'abord" dans la phase 0
        phase0_sorted = sorted(phase0, key=lambda x: (x.is_uninhabited, x.cat_priority, -x.prises, x.bat_id))
        for b in phase0_sorted:
            self._etape += 1
            b.etape = self._etape
            self.plan.append((
                self._etape, b.bat_id, b.type_batiment, b.prises,
                b.cost_cur, b.time_cur_h, b.cost_per_prise, b.time_per_prise,
                b.is_uninhabited, sorted(list(b.infrastructures))
            ))

        restants: Set[str] = set(self.r.bats.keys()) - {b.bat_id for b in phase0_sorted}

        # Boucle principale
        while restants:
            # Mise à jour dynamique des coûts/temps courants
            for bid in restants:
                self.r.bats[bid].maj(self.r.infras)

            # Choix selon la clé lexicographique complète
            choix = min((self.r.bats[bid] for bid in restants), key=lambda b: b.tri_tuple())

            # Réparer toutes ses infrastructures
            for iid in choix.infrastructures:
                if iid not in self._repare_infras:
                    self.r.infras[iid].reparer()
                    self._repare_infras.add(iid)

            # Mise à jour après réparation
            for bid in restants:
                self.r.bats[bid].maj(self.r.infras)

            self._etape += 1
            choix.etape = self._etape
            self.plan.append((
                self._etape, choix.bat_id, choix.type_batiment, choix.prises,
                choix.cost_cur, choix.time_cur_h, choix.cost_per_prise, choix.time_per_prise,
                choix.is_uninhabited, sorted(list(choix.infrastructures))
            ))
            restants.remove(choix.bat_id)

        return self

    def df_plan(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan, columns=[
            "etape","id_batiment","type_batiment","prises",
            "cost_cur","time_cur_h","cost_per_prise","time_per_prise",
            "is_uninhabited","infrastructures"
        ])

    def df_batiments(self) -> pd.DataFrame:
        rows = []
        for b in self.r.bats.values():
            rows.append({
                "id_batiment": b.bat_id,
                "type_batiment": b.type_batiment,
                "is_uninhabited": b.is_uninhabited,
                "occ_rate": b.occ_rate,
                "prises": b.prises,
                "cost_base": b.cost_base,
                "time_base_h": b.time_base_h,
                "cost_cur": b.cost_cur,
                "time_cur_h": b.time_cur_h,
                "cost_per_prise_base": b.cost_base / b.prises,
                "time_per_prise_base": b.time_base_h / b.prises,
                "etape": b.etape,
                "infrastructures": sorted(list(b.infrastructures)),
            })
        return pd.DataFrame(rows).sort_values(by=["is_uninhabited","etape","type_batiment","id_batiment"]).reset_index(drop=True)

    def df_infras(self) -> pd.DataFrame:
        rows = []
        for inf in self.r.infras.values():
            rows.append({
                "infra_id": inf.infra_id,
                "type_infra": inf.type_infra,
                "state": inf.infra_type_state,
                "longueur": inf.longueur,
                "n_bat_servis": inf.n_bat_servis,
                "cost_base": inf.cost_base,
                "time_base_h": inf.time_base_h,
                "cost_cur": inf.cost_cur,
                "time_cur_h": inf.time_cur_h,
                "batiments": sorted(list(inf.batiments)),
            })
        return pd.DataFrame(rows).sort_values(by=["cost_cur","time_cur_h","infra_id"]).reset_index(drop=True)

# --- 4) Construction & exécution ---
reseau = Reseau.construire(df)
planif = Planificateur(reseau).run()

# --- 5) Exports ---
planif.df_infras().to_excel("priorisation_infra_v2.xlsx", index=False)
planif.df_batiments().to_excel("priorisation_batiment_v2.xlsx", index=False)
planif.df_plan().to_excel("plan_raccordement_v2.xlsx", index=False)
planif.df_plan().to_csv("plan_raccordement_v2.csv", index=False)

print("✅ Exports v2 OK.")
