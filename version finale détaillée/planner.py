# classe Planificateur avec contraintes & rolling


from typing import Dict, List
import pandas as pd
from models import Reseau
from scoring import compute_normalizers, score_batiment

from config import PARAMS

class Planificateur:
    def __init__(self, reseau: Reseau):
        self.r = reseau
        self.plan_rows: List[Dict] = []
        self.norm = compute_normalizers(self.r.bats)
        # Cumuls
        self.cost_cum = 0.0
        self.time_cum = 0.0
        self.prises_cum = 0
        # Contraintes
        self.max_budget = PARAMS["MAX_BUDGET"]
        self.max_hours = PARAMS["MAX_HOURS"]
        self.norm_rolling_every = int(PARAMS["NORM_ROLLING_EVERY"] or 0)

    def _recompute_norm_if_needed(self, step: int):
        if self.norm_rolling_every > 0 and step > 1 and (step % self.norm_rolling_every == 1):
            self.norm = compute_normalizers(self.r.bats)

    def run(self):
        restants = set(self.r.bats.keys())
        step = 0

        while restants:
            step += 1
            self._recompute_norm_if_needed(step)

            for bid in restants:
                self.r.bats[bid].maj(self.r.infras)

            scored = []
            for bid in restants:
                b = self.r.bats[bid]
                s, parts = score_batiment(b, self.norm)
                scored.append((s, bid, b, parts))
            scored.sort(key=lambda x: (x[0], x[2].bat_id))
            s, _, choix, parts = scored[0]

            cost_before = choix.cost_cur
            time_before = choix.time_cur_h
            prises_now  = choix.prises

            repaired = []
            step_cost = 0.0
            step_time = 0.0
            for iid in choix.infrastructures:
                inf = self.r.infras[iid]
                if inf.cost_cur > 0 or inf.time_cur_h > 0:
                    repaired.append(iid)
                    step_cost += inf.cost_cur
                    step_time += inf.time_cur_h

            next_cost_cum = self.cost_cum + step_cost
            next_time_cum = self.time_cum + step_time
            stop_on_budget = (self.max_budget is not None and next_cost_cum > float(self.max_budget))
            stop_on_hours  = (self.max_hours  is not None and next_time_cum > float(self.max_hours))
            if stop_on_budget or stop_on_hours:
                self.plan_rows.append({
                    "etape": step,
                    "id_batiment": None,
                    "type_batiment": None,
                    "is_uninhabited": None,
                    "prises": 0,
                    "cost_before": 0.0,
                    "time_before": 0.0,
                    "cat_score": None,
                    "score": None,
                    "score_parts_cpp_n": None,
                    "score_parts_tpp_n": None,
                    "score_parts_p_n": None,
                    "score_parts_c_n": None,
                    "score_penalty": None,
                    "infrastructures": [],
                    "repaired_infras": [],
                    "step_cost": 0.0,
                    "step_time": 0.0,
                    "cost_cum": self.cost_cum,
                    "time_cum": self.time_cum,
                    "prises_cum": self.prises_cum,
                    "note": f"Arrêt sur contrainte : "
                            f"{'budget' if stop_on_budget else ''}"
                            f"{' & ' if stop_on_budget and stop_on_hours else ''}"
                            f"{'heures' if stop_on_hours else ''}",
                })
                break

            for iid in repaired:
                self.r.infras[iid].reparer()

            for bid in restants:
                self.r.bats[bid].maj(self.r.infras)

            self.cost_cum = next_cost_cum
            self.time_cum = next_time_cum
            self.prises_cum += prises_now
            euro_per_prise = (step_cost / prises_now) if prises_now > 0 else None
            h_per_prise = (step_time / prises_now) if prises_now > 0 else None

            self.plan_rows.append({
                "etape": step,
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
                "step_cost": step_cost,
                "step_time": step_time,
                "euro_per_prise_marginal": euro_per_prise,
                "h_per_prise_marginal": h_per_prise,
                "cost_cum": self.cost_cum,
                "time_cum": self.time_cum,
                "prises_cum": self.prises_cum,
                "note": None,
            })

            restants.remove(choix.bat_id)

        return self

    def df_plan(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan_rows)
