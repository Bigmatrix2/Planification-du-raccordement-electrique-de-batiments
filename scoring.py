# normalisation & fonctions de score

# scoring.py
# -*- coding: utf-8 -*-
from typing import Dict
from models import Batiment, Infrastructure
from config import PARAMS

# Raccourcis poids
W_CAT = PARAMS["W_CAT"]
W_COST = PARAMS["W_COST"]
W_TIME = PARAMS["W_TIME"]
W_GAIN = PARAMS["W_GAIN"]
W_RES = PARAMS["W_RES"]
P_UNINHABITED = PARAMS["P_UNINHABITED"]
W_WALL = PARAMS["W_WALL"]

# Contraintes/valeurs terrain
WORKERS_PER_INFRA_MAX   = PARAMS["WORKERS_PER_INFRA_MAX"]
WORKER_COST_EUR_PER_H   = PARAMS["WORKER_COST_EUR_PER_H"]
INCLUDE_LABOUR_IN_COST  = PARAMS["INCLUDE_LABOUR_IN_COST"]

def min_max(x_min, x_max, x):
    if x_max <= x_min:
        return 0.0
    return (x - x_min) / (x_max - x_min)

def compute_normalizers(bats: Dict[str, Batiment]):
    costs_pp, times_pp, prises, costs = [], [], [], []
    walls_pp = []   # (max_infra_time_h / 4) / prises
    econ_pp  = []   # (cost_cur + time_cur_h * 37.5) / prises

    for b in bats.values():
        p = b.prises
        # homme-heures par prise (comme avant)
        cpp = b.cost_cur
        tpp = b.time_cur_h
        # wall-clock par prise (4 ouvriers/infra)
        wall_per_prise = (b.max_infra_time_h / float(WORKERS_PER_INFRA_MAX)) / p
        # coût économique (optionnel)
        econ_cost = b.cost_cur + b.time_cur_h * WORKER_COST_EUR_PER_H
        econ_per_prise = econ_cost / p

        costs_pp.append(cpp / p)
        times_pp.append(tpp / p)
        prises.append(p)
        costs.append(b.cost_cur)
        walls_pp.append(wall_per_prise)
        econ_pp.append(econ_per_prise)

    return {
        "cpp_min": min(costs_pp) if costs_pp else 0.0,
        "cpp_max": max(costs_pp) if costs_pp else 1.0,
        "tpp_min": min(times_pp) if times_pp else 0.0,
        "tpp_max": max(times_pp) if times_pp else 1.0,
        "p_min": min(prises) if prises else 1,
        "p_max": max(prises) if prises else 1,
        "c_min": min(costs) if costs else 0.0,
        "c_max": max(costs) if costs else 1.0,
        # nouveaux normalisateurs
        "wall_min": min(walls_pp) if walls_pp else 0.0,
        "wall_max": max(walls_pp) if walls_pp else 1.0,
        "econ_min": min(econ_pp) if econ_pp else 0.0,
        "econ_max": max(econ_pp) if econ_pp else 1.0,
    }

def score_batiment(b: Batiment, norm):
    p = b.prises

    # --- Coûts par prise ---
    if INCLUDE_LABOUR_IN_COST:
        cost_eff_per_prise = (b.cost_cur + b.time_cur_h * WORKER_COST_EUR_PER_H) / p
        cost_n = min_max(norm["econ_min"], norm["econ_max"], cost_eff_per_prise)
    else:
        cost_per_prise = b.cost_cur / p
        cost_n = min_max(norm["cpp_min"], norm["cpp_max"], cost_per_prise)

    # --- Homme-heures par prise (inchangé) ---
    time_per_prise = b.time_cur_h / p
    time_n = min_max(norm["tpp_min"], norm["tpp_max"], time_per_prise)

    # --- Wall-clock (borné par 4 ouvriers/infra) par prise ---
    wall_per_prise = (b.max_infra_time_h / float(WORKERS_PER_INFRA_MAX)) / p
    wall_n = min_max(norm["wall_min"], norm["wall_max"], wall_per_prise)

    # --- Autres composantes ---
    p_n = min_max(norm["p_min"], norm["p_max"], p)
    c_n = min_max(norm["c_min"], norm["c_max"], b.cost_cur)

    base = (
        (W_CAT  * b.cat_score)
        + (W_COST * cost_n)
        + (W_TIME * time_n)
        + (W_WALL * wall_n)
        - (W_GAIN * p_n)
        + (W_RES  * c_n)
    )

    penalty = (1.0 + P_UNINHABITED) if b.is_uninhabited == 1 else 1.0
    return base * penalty, {
        "cost_n": cost_n,
        "time_n": time_n,
        "wall_n": wall_n,
        "p_n": p_n,
        "c_n": c_n,
        "penalty": penalty
    }

def score_infra(i: Infrastructure, n_bat_servis: int) -> float:
    big = 1_000_000 if i.is_intact == 1 else 0
    return big + i.cost_cur + 0.5 * i.time_cur_h - 0.3 * n_bat_servis
