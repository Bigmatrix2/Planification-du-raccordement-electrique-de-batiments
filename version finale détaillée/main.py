# point d’entrée (CLI)

import argparse
from config import PARAMS
from data_io import load_and_prepare
from models import Reseau
from planner import Planificateur
from exports import build_bats_df, build_infras_df, export_all

def parse_args():
    p = argparse.ArgumentParser(description="Planification de raccordement (greedy + mutualisation)")
    p.add_argument("--arbre", default="../../fichiers/reseau_en_arbre.xlsx", help="Chemin du fichier arbre Excel")
    p.add_argument("--infra", default="../../fichiers/clientnv/infra.csv", help="Chemin du CSV des infrastructures")
    p.add_argument("--bats",  default="../../fichiers/clientnv/batiments.csv", help="Chemin du CSV des bâtiments")
    p.add_argument("--max-budget", type=float, default=None, help="Budget plafond en euros (ex: 1200000)")
    p.add_argument("--max-hours",  type=float, default=None, help="Heures-homme plafond (ex: 2000)")
    p.add_argument("--rolling", type=int, default=None, help="Recalcul des normalisations toutes les N étapes (0=off)")
    return p.parse_args()

def main():
    args = parse_args()
    # Overrides optionnels
    if args.max_budget is not None:
        PARAMS["MAX_BUDGET"] = args.max_budget
    if args.max_hours is not None:
        PARAMS["MAX_HOURS"] = args.max_hours
    if args.rolling is not None:
        PARAMS["NORM_ROLLING_EVERY"] = int(args.rolling)

    df = load_and_prepare(args.arbre, args.infra, args.bats)
    reseau = Reseau.construire(df)
    planif = Planificateur(reseau).run()
    df_plan = planif.df_plan()
    df_bats = build_bats_df(reseau)
    df_infra = build_infras_df(reseau)
    export_all(df_plan, df_bats, df_infra)

if __name__ == "__main__":
    main()
