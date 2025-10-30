# dataframes finaux & fichiers


import pandas as pd
from collections import Counter
from models import Reseau
from scoring import score_infra

def build_bats_df(reseau: Reseau) -> pd.DataFrame:
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
    return pd.DataFrame(rows_b)

def build_infras_df(reseau: Reseau) -> pd.DataFrame:
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
    return df_infra

def export_all(df_plan: pd.DataFrame, df_bats: pd.DataFrame, df_infra: pd.DataFrame):
    # Excel/CSV principaux
    df_infra.to_excel("priorisation_infra.xlsx", index=False)
    df_bats.to_excel("priorisation_batiment.xlsx", index=False)
    df_plan.to_excel("plan_raccordement.xlsx", index=False)
    df_plan.to_csv("plan_raccordement.csv", index=False, encoding="utf-8")

    # Exports courbes cumulatives et marginals
    cols_curve = ["etape", "step_cost", "step_time", "euro_per_prise_marginal",
                  "h_per_prise_marginal", "cost_cum", "time_cum", "prises_cum", "note"]
    df_plan[cols_curve].to_csv("plan_cumul_marginal.csv", index=False, encoding="utf-8")

    # Top infras réellement réparées
    rep_counts = Counter(i for row in df_plan["repaired_infras"] for i in (row or []))
    df_rep = pd.DataFrame(
        [{"infra_id": k, "repaired_times": v} for k, v in rep_counts.items()]
    ).sort_values("repaired_times", ascending=False)
    df_rep.to_csv("infras_reparees_top.csv", index=False, encoding="utf-8")

    print("✅ Exports : OK (dont courbes cumulatives et top infras réparées)")
