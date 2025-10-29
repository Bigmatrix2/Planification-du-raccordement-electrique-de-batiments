import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

# --- 1) Chargement des données ---
path = "../fichiers/reseau_en_arbre.xlsx"
df = pd.read_excel(path)

# Contrôle de colonnes attendues
expected_cols = {"infra_id", "id_batiment", "nb_maisons", "infra_type", "longueur"}
missing = expected_cols - set(df.columns)
if missing:
    raise ValueError(f"Colonnes manquantes dans le fichier source: {missing}")

# Modèles orientés objet

@dataclass
class Infrastructure:
    infra_id: str
    infra_type: str  # "infra_intacte", "infra_a_remplacer", etc.
    longueur: float
    batiments: Set[str] = field(default_factory=set)
    n_bat_servis: int = 0
    diff_base: float = 0.0   # difficulté initiale (longueur / n_bat_servis), 0 si intacte
    diff_courante: float = 0.0 # évolue au fur et à mesure des réparations

    def set_n_bat_servis(self):
        self.n_bat_servis = max(1, len(self.batiments))  # garde-fou
        if self.infra_type == "infra_intacte":
            self.diff_base = 0.0
        else:
            self.diff_base = (self.longueur / self.n_bat_servis) if self.n_bat_servis > 0 else self.longueur
        self.diff_courante = self.diff_base

    def est_reparee(self) -> bool:
        return self.diff_courante == 0.0

    def reparer(self):
        self.diff_courante = 0.0

@dataclass
class Batiment:
    bat_id: str
    nb_maisons: int
    infrastructures: Set[str] = field(default_factory=set)
    diff_base: float = 0.0     # somme des diff_base des infras (0 si toutes intactes)
    diff_courante: float = 0.0 # somme des diff_courante restantes (évolue)
    etape: int = 0             # étape d'exécution dans le plan (0 = phase 0 si déjà raccordable)

    def maj_diff(self, infras: Dict[str, Infrastructure]):
        """
        Recalcule la difficulté courante depuis l'état courant des infras.
        """
        self.diff_courante = sum(infras[i].diff_courante for i in self.infrastructures)

    @property
    def score_simplicite(self) -> float:
        """
        Score priorité principal: difficulté par prise (plus petit = plus prioritaire).
        On protège par un min de 1 prise pour éviter division par zéro.
        """
        denom = max(1, self.nb_maisons)
        return self.diff_courante / denom

    def tri_tuple(self) -> Tuple[float, int, float, str]:
        """
        Tuple de tri: (score_simplicite, -nb_maisons, diff_courante, bat_id)
        -> favorise d'abord la simplicité, puis le gain de prises (beaucoup de prises),
           puis la difficulté brute (plus petite), puis identifiant pour stabilité.
        """
        return (self.score_simplicite, -self.nb_maisons, self.diff_courante, self.bat_id)

@dataclass
class Reseau:
    infras: Dict[str, Infrastructure] = field(default_factory=dict)
    bats: Dict[str, Batiment] = field(default_factory=dict)

    @staticmethod
    def construire(df: pd.DataFrame) -> "Reseau":
        infras: Dict[str, Infrastructure] = {}
        bats: Dict[str, Batiment] = {}

        # Création des objets et liens bidirectionnels
        for _, row in df.iterrows():
            iid = str(row["infra_id"])
            bid = str(row["id_batiment"])
            nbm = int(row["nb_maisons"])
            itype = str(row["infra_type"])
            lng = float(row["longueur"])

            if iid not in infras:
                infras[iid] = Infrastructure(iid, itype, lng)
            infras[iid].batiments.add(bid)

            if bid not in bats:
                bats[bid] = Batiment(bid, nbm)
            bats[bid].infrastructures.add(iid)

        # Calcul des difficultés de base
        for infra in infras.values():
            infra.set_n_bat_servis()

        # Difficultés initiales des bâtiments
        for bat in bats.values():
            bat.diff_base = sum(infras[i].diff_base for i in bat.infrastructures)
            bat.diff_courante = bat.diff_base

        return Reseau(infras=infras, bats=bats)

class Planificateur:
    """
    Exécute la stratégie:
    - Phase 0: bâtiments déjà raccordables (diff_courante == 0)
    - Boucle: choisir le batiment le plus simple (score_simplicite minimal puis tie-break)
              -> réparer toutes ses infrastructures -> maj de tout le monde -> append au plan
    """
    def __init__(self, reseau: Reseau):
        self.r = reseau
        self.plan: List[Tuple[int, str, int, float, float, List[str]]] = []
        self._etape = 0
        self._repare_infras: Set[str] = set()

    def run(self):
        # Phase 0
        phase0 = [b for b in self.r.bats.values() if b.diff_courante == 0.0]
        for b in sorted(phase0, key=lambda x: (-x.nb_maisons, x.bat_id)):
            self._etape += 1
            b.etape = self._etape
            self.plan.append((self._etape, b.bat_id, b.nb_maisons, b.diff_courante, b.score_simplicite, sorted(list(b.infrastructures))))

        # Ensemble des bâtiments restants (non traités en phase 0)
        restants: Set[str] = set(self.r.bats.keys()) - {b.bat_id for b in phase0}

        # Boucle principale
        while restants:
            # Recalcule pour sécurité (si on a réparé au tour précédent)
            for bid in restants:
                self.r.bats[bid].maj_diff(self.r.infras)

            # Choix du plus simple
            choix = min((self.r.bats[bid] for bid in restants), key=lambda b: b.tri_tuple())

            # Répare toutes ses infrastructures
            for iid in choix.infrastructures:
                if iid not in self._repare_infras:
                    self.r.infras[iid].reparer()
                    self._repare_infras.add(iid)

            # Met à jour toutes les difficultés des restants
            for bid in restants:
                self.r.bats[bid].maj_diff(self.r.infras)

            # Ajoute au plan
            self._etape += 1
            choix.etape = self._etape
            self.plan.append((self._etape, choix.bat_id, choix.nb_maisons, choix.diff_courante, choix.score_simplicite, sorted(list(choix.infrastructures))))

            # Retire du set restant
            restants.remove(choix.bat_id)

        return self

    # Extractions utiles
    def df_plan(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan, columns=["etape", "id_batiment", "nb_maisons", "diff_courante", "score_simplicite", "infrastructures"])

    def df_batiments(self) -> pd.DataFrame:
        rows = []
        for b in self.r.bats.values():
            rows.append({
                "id_batiment": b.bat_id,
                "nb_maisons": b.nb_maisons,
                "diff_base": b.diff_base,
                "diff_courante": b.diff_courante,
                "score_base": b.diff_base / max(1, b.nb_maisons),
                "etape": b.etape,
                "infrastructures": sorted(list(b.infrastructures))
            })
        out = pd.DataFrame(rows).sort_values(by=["etape", "score_base", "id_batiment"]).reset_index(drop=True)
        return out

    def df_infras(self) -> pd.DataFrame:
        rows = []
        for inf in self.r.infras.values():
            rows.append({
                "infra_id": inf.infra_id,
                "infra_type": inf.infra_type,
                "longueur": inf.longueur,
                "n_bat_servis": inf.n_bat_servis,
                "diff_base": inf.diff_base,
                "diff_courante": inf.diff_courante,
                "batiments": sorted(list(inf.batiments))
            })
        out = pd.DataFrame(rows).sort_values(by=["diff_courante", "diff_base", "infra_id"]).reset_index(drop=True)
        return out

# --- 3) Construction du réseau & exécution de l'algorithme ---
reseau = Reseau.construire(df)
planif = Planificateur(reseau).run()

# --- 4) Exports ---
df_infras = planif.df_infras()
df_bats   = planif.df_batiments()
df_plan   = planif.df_plan()

df_infras.to_excel("priorisation_infra_v1.xlsx", index=False)
df_bats.to_excel("priorisation_batiment_v1.xlsx", index=False)
df_plan.to_excel("plan_raccordement_v1.xlsx", index=False)
df_plan.to_csv("plan_raccordement_v1.csv", index=False)

print("✅ Fichiers exportés.")
