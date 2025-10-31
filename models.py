# dataclasses & construction du réseau

from dataclasses import dataclass, field
from typing import Dict, Set
import pandas as pd
from config import CAT_MAP

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
    # --- NOUVEAU : pour pénaliser les "longues" infras dans le scoring
    max_infra_time_h: float = 0.0
    sum_infra_time_h: float = 0.0

    def maj(self, infras: Dict[str, Infrastructure]):
        self.cost_cur   = 0.0
        self.time_cur_h = 0.0
        tmax = 0.0
        tsum = 0.0
        for i in self.infrastructures:
            inf = infras[i]
            self.cost_cur   += inf.cost_cur
            self.time_cur_h += inf.time_cur_h
            tmax = max(tmax, inf.time_cur_h)
            tsum += inf.time_cur_h
        self.max_infra_time_h = tmax
        self.sum_infra_time_h = tsum

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
