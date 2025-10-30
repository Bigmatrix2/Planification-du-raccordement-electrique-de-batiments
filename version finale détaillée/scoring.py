# normalisation & fonctions de score

from typing import Dict
from models import Batiment, Infrastructure
from config import PARAMS

W_CAT = PARAMS["W_CAT"]; W_COST = PARAMS["W_COST"]; W_TIME = PARAMS["W_TIME"]
W_GAIN = PARAMS["W_GAIN"]; W_RES = PARAMS["W_RES"]; P_UNINHABITED = PARAMS["P_UNINHABITED"]

def min_max(x_min, x_max, x):
    if x_max <= x_min: return 0.0
    return (x - x_min) / (x_max - x_min)

def compute_normalizers(bats: Dict[str, Batiment]):
    costs_pp, times_pp, prises, costs = [], [], [], []
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

    penalty = (1.0 + P_UNINHABITED) if b.is_uninhabited == 1 else 1.0
    return base * penalty, {"cpp_n": cpp_n, "tpp_n": tpp_n, "p_n": p_n, "c_n": c_n, "penalty": penalty}

def score_infra(i: Infrastructure, n_bat_servis: int) -> float:
    big = 1_000_000 if i.is_intact == 1 else 0
    return big + i.cost_cur + 0.5 * i.time_cur_h - 0.3 * n_bat_servis
