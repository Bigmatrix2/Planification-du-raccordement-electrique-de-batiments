# classe Planificateur avec contraintes & rolling

from typing import Dict, List, Tuple, Optional
import pandas as pd
from models import Reseau
from scoring import compute_normalizers, score_batiment
from config import PARAMS

WORKERS_PER_INFRA_MAX = PARAMS["WORKERS_PER_INFRA_MAX"]
HOPITAL_MAX_WALL_HOURS = PARAMS["HOPITAL_MAX_WALL_HOURS"]
WORKER_COST_EUR_PER_H = PARAMS["WORKER_COST_EUR_PER_H"]

def _wall_clock_for_infras(times_per_infra: List[float]) -> float:
    """Temps mur minimal si on exécute toutes ces infras en parallèle, borne WORKERS_PER_INFRA_MAX ouvriers/infra."""
    if not times_per_infra:
        return 0.0
    return max(t / WORKERS_PER_INFRA_MAX for t in times_per_infra)

class Planificateur:
    def __init__(self, reseau: Reseau):
        self.r = reseau
        self.plan_rows: List[Dict] = []
        self.norm = compute_normalizers(self.r.bats)
        # Cumuls (homme-heures)
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

    def _pick_hopital_first(self, restants: set) -> Tuple[Optional[str], Optional[Dict]]:
        """S'il existe un bâtiment 'hopital'/'hôpital' dans restants, le sélectionner en priorité."""
        cands = []
        for bid in restants:
            b = self.r.bats[bid]
            t = b.type_batiment.strip().lower()
            if t in {"hopital", "hôpital"}:
                s, parts = score_batiment(b, self.norm)
                cands.append((s, bid, b, parts))
        if not cands:
            return None, None
        cands.sort(key=lambda x: (x[0], x[2].bat_id))
        s, _, choix, parts = cands[0]
        return choix.bat_id, {"score": s, "parts": parts, "b": choix}

    def run(self):
        restants = set(self.r.bats.keys())
        step = 0

        # ----- Phase 0 : Hôpital (si présent) -----
        hop_id, info = self._pick_hopital_first(restants)
        if hop_id is not None:
            step += 1
            self._recompute_norm_if_needed(step)
            # Maj coûts/temps
            for bid in restants:
                self.r.bats[bid].maj(self.r.infras)

            choix = self.r.bats[hop_id]
            s = info["score"]; parts = info["parts"]

            cost_before = choix.cost_cur
            time_before = choix.time_cur_h
            prises_now  = choix.prises

            repaired = []
            step_cost = 0.0
            step_time = 0.0
            times_per_infra = []
            for iid in choix.infrastructures:
                inf = self.r.infras[iid]
                if inf.cost_cur > 0 or inf.time_cur_h > 0:
                    repaired.append(iid)
                    step_cost += inf.cost_cur
                    step_time += inf.time_cur_h
                    times_per_infra.append(inf.time_cur_h)

            # Si rien à réparer, saute l'étape
            if not repaired:
                restants.remove(choix.bat_id)
                step -= 1
                # on ne quitte pas la fonction: on laisse la boucle continuer
            else:
                # contraintes budget/temps si on applique
                next_cost_cum = self.cost_cum + step_cost
                next_time_cum = self.time_cum + step_time
                stop_on_budget = (self.max_budget is not None and next_cost_cum > float(self.max_budget))
                stop_on_hours  = (self.max_hours  is not None and next_time_cum > float(self.max_hours))
                if stop_on_budget or stop_on_hours:
                    self.plan_rows.append({
                        "etape": step, "phase": "0(hôpital)-ABANDON",
                        "id_batiment": None, "type_batiment": None, "is_uninhabited": None,
                        "prises": 0, "cost_before": 0.0, "time_before": 0.0,
                        "cat_score": None, "score": None,
                        "score_parts_cost_n": None, "score_parts_time_n": None, "score_parts_wall_n": None,
                        "score_parts_p_n": None, "score_parts_c_n": None, "score_penalty": None,
                        "infrastructures": [], "repaired_infras": [],
                        "step_cost": 0.0, "step_time": 0.0,
                        "labour_cost": 0.0, "wall_clock_step_h": 0.0,
                        "euro_per_prise_marginal": None,
                        "h_per_prise_marginal": None,
                        "cost_cum": self.cost_cum, "time_cum": self.time_cum, "prises_cum": self.prises_cum,
                        "note": "Arrêt sur contrainte AVANT hôpital",
                    })
                    return self


                # Appliquer réparation
                for iid in repaired: self.r.infras[iid].reparer()
                for bid in restants: self.r.bats[bid].maj(self.r.infras)

                self.cost_cum = next_cost_cum
                self.time_cum = next_time_cum
                self.prises_cum += prises_now

                wall_clock = _wall_clock_for_infras(times_per_infra)
                labour_cost = step_time * WORKER_COST_EUR_PER_H
                note = None
                euro_per_prise = (step_cost / prises_now) if prises_now > 0 else None
                h_per_prise = (step_time / prises_now) if prises_now > 0 else None
                if wall_clock > HOPITAL_MAX_WALL_HOURS:
                    note = (
                        f"⚠️ Hôpital : temps mur {wall_clock:.2f}h > seuil {HOPITAL_MAX_WALL_HOURS}h "
                        f"(autonomie 20h - marge 20%). Envisager: revoir barèmes, réduire périmètre, ou lever contrainte."
                    )

                self.plan_rows.append({
                    "etape": step,
                    "phase": "0(hôpital)",
                    "id_batiment": choix.bat_id,
                    "type_batiment": choix.type_batiment,
                    "is_uninhabited": choix.is_uninhabited,
                    "prises": prises_now,
                    "cost_before": cost_before,
                    "time_before": time_before,
                    "cat_score": choix.cat_score,
                    "score": s,
                    "score_parts_cost_n": parts.get("cost_n", None),
                    "score_parts_time_n": parts.get("time_n", None),
                    "score_parts_wall_n": parts.get("wall_n", None),
                    "score_parts_p_n": parts.get("p_n", None),
                    "score_parts_c_n": parts.get("c_n", None),
                    "score_penalty": parts.get("penalty", None),
                    "infrastructures": sorted(list(choix.infrastructures)),
                    "repaired_infras": repaired,
                    "step_cost": step_cost,
                    "step_time": step_time,
                    "euro_per_prise_marginal": euro_per_prise,
                    "h_per_prise_marginal": h_per_prise,
                    "labour_cost": labour_cost,
                    "wall_clock_step_h": wall_clock,
                    "cost_cum": self.cost_cum,
                    "time_cum": self.time_cum,
                    "prises_cum": self.prises_cum,
                    "note": note,
                })
                restants.remove(choix.bat_id)

        # ----- Phases suivantes : greedy standard -----
        while restants:
            step += 1
            self._recompute_norm_if_needed(step)
            for bid in restants: self.r.bats[bid].maj(self.r.infras)

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
            times_per_infra = []
            for iid in choix.infrastructures:
                inf = self.r.infras[iid]
                if inf.cost_cur > 0 or inf.time_cur_h > 0:
                    repaired.append(iid)
                    step_cost += inf.cost_cur
                    step_time += inf.time_cur_h
                    times_per_infra.append(inf.time_cur_h)

            # Si rien à réparer, saute l'étape
            if not repaired:
                restants.remove(choix.bat_id)
                step -= 1
                continue

            next_cost_cum = self.cost_cum + step_cost
            next_time_cum = self.time_cum + step_time
            stop_on_budget = (self.max_budget is not None and next_cost_cum > float(self.max_budget))
            stop_on_hours  = (self.max_hours  is not None and next_time_cum > float(self.max_hours))
            if stop_on_budget or stop_on_hours:
                self.plan_rows.append({
                    "etape": step, "phase": None,
                    "id_batiment": None, "type_batiment": None, "is_uninhabited": None,
                    "prises": 0, "cost_before": 0.0, "time_before": 0.0,
                    "cat_score": None, "score": None,
                    "score_parts_cost_n": None, "score_parts_time_n": None, "score_parts_wall_n": None,
                    "score_parts_p_n": None, "score_parts_c_n": None, "score_penalty": None,
                    "infrastructures": [], "repaired_infras": [],
                    "step_cost": 0.0, "step_time": 0.0,
                    "labour_cost": 0.0, "wall_clock_step_h": 0.0,
                    "euro_per_prise_marginal": None,
                    "h_per_prise_marginal": None,
                    "cost_cum": self.cost_cum, "time_cum": self.time_cum, "prises_cum": self.prises_cum,
                    "note": "Arrêt sur contrainte (budget/heure)",
                })
                break


            for iid in repaired: self.r.infras[iid].reparer()
            for bid in restants: self.r.bats[bid].maj(self.r.infras)

            self.cost_cum = next_cost_cum
            self.time_cum = next_time_cum
            self.prises_cum += prises_now

            wall_clock = _wall_clock_for_infras(times_per_infra)
            labour_cost = step_time * WORKER_COST_EUR_PER_H
            euro_per_prise = (step_cost / prises_now) if prises_now > 0 else None
            h_per_prise = (step_time / prises_now) if prises_now > 0 else None

            self.plan_rows.append({
                "etape": step,
                "phase": None,  # sera attribuée après coup
                "id_batiment": choix.bat_id,
                "type_batiment": choix.type_batiment,
                "is_uninhabited": choix.is_uninhabited,
                "prises": prises_now,
                "cost_before": cost_before,
                "time_before": time_before,
                "cat_score": choix.cat_score,
                "score": s,
                "score_parts_cost_n": parts.get("cost_n", None),
                "score_parts_time_n": parts.get("time_n", None),
                "score_parts_wall_n": parts.get("wall_n", None),
                "score_parts_p_n": parts.get("p_n", None),
                "score_parts_c_n": parts.get("c_n", None),
                "score_penalty": parts.get("penalty", None),
                "infrastructures": sorted(list(choix.infrastructures)),
                "repaired_infras": repaired,
                "step_cost": step_cost,
                "step_time": step_time,
                "euro_per_prise_marginal": euro_per_prise,
                "h_per_prise_marginal": h_per_prise,
                "labour_cost": labour_cost,
                "wall_clock_step_h": wall_clock,
                "cost_cum": self.cost_cum,
                "time_cum": self.time_cum,
                "prises_cum": self.prises_cum,
                "note": None,
            })

            restants.remove(choix.bat_id)

        # Attribution des phases 1..4 selon le coût restant (40% / 20 / 20 / 20)
        self._assign_phases_by_cost()

        return self

    def _assign_phases_by_cost(self):
        """Attribue phase=1..4 aux étapes (hors hôpital) en respectant 40%/20%/20%/20% du coût restant."""
        if not self.plan_rows:
            return
        # Sépare hôpital des autres
        steps = [r for r in self.plan_rows if r["phase"] != "0(hôpital)"]
        if not steps:
            return
        total_rest_cost = sum(r["step_cost"] for r in steps)
        if total_rest_cost <= 0:
            # rien à répartir
            for r in steps:
                r["phase"] = "1"
            return
        # Seuils cumulés
        p1, p2, p3, p4 = 0.40, 0.20, 0.20, 0.20
        t1 = total_rest_cost * p1
        t2 = t1 + total_rest_cost * p2
        t3 = t2 + total_rest_cost * p3
        t4 = t3 + total_rest_cost * p4  # = total_rest_cost

        cum = 0.0
        for r in steps:
            cum += r["step_cost"]
            if cum <= t1:
                r["phase"] = "1"
            elif cum <= t2:
                r["phase"] = "2"
            elif cum <= t3:
                r["phase"] = "3"
            else:
                r["phase"] = "4"

    def df_plan(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan_rows)
