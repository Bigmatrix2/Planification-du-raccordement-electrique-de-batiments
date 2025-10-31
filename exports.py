# dataframes finaux & fichiers
import pandas as pd
from collections import Counter
from models import Reseau
from scoring import score_infra
import os

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
    if not os.path.exists('static'):
        os.mkdir('static')

    df_infra.to_excel("static/priorisation_infra.xlsx", index=False)
    df_bats.to_excel("static/priorisation_batiment.xlsx", index=False)
    df_plan.to_excel("static/plan_raccordement.xlsx", index=False)
    df_plan.to_csv("static/plan_raccordement.csv", index=False, encoding="utf-8")

    # Exports courbes cumulatives et marginals
    cols_curve = ["etape", "step_cost", "step_time", "euro_per_prise_marginal",
                  "h_per_prise_marginal", "cost_cum", "time_cum", "prises_cum", "note"]
    df_plan[cols_curve].to_csv("static/plan_cumul_marginal.csv", index=False, encoding="utf-8")

    # Top infras réellement réparées
    rep_counts = Counter(i for row in df_plan["repaired_infras"] for i in (row or []))
    df_rep = pd.DataFrame(
        [{"infra_id": k, "repaired_times": v} for k, v in rep_counts.items()]
    ).sort_values("repaired_times", ascending=False)
    df_rep.to_csv("static/infras_reparees_top.csv", index=False, encoding="utf-8")

    # Agrégats par phase
    if "phase" in df_plan.columns:
        # Totaux par phase
        agg = (df_plan
               .dropna(subset=["phase"])
               .groupby("phase")
               .agg(
                   step_cost=("step_cost","sum"),
                   step_time_h=("step_time","sum"),
                   labour_cost=("labour_cost","sum")
               )
               .reset_index())

        # Temps mur minimal par phase = max(time_i/4) sur l'ensemble des infras de la phase
        # On reconstruit la liste des infras et de leurs temps par étape
        rows_wc = []
        for phase, sub in df_plan.dropna(subset=["phase"]).groupby("phase"):
            # on déroule toutes les infras réparées dans cette phase avec leur temps
            times = []
            for _, row in sub.iterrows():
                # NB: on ne stocke pas les temps par infra individuellement dans df_plan,
                # donc on approxime en supposant que le "wall_clock_step_h" découle bien de la liste interne.
                # Pour être exact, il faudrait pousser les temps infra par infra dans df_plan.
                # Ici on prend le max des wall_clock_step_h des étapes de la phase (borne supérieure plausible).
                times.append(row.get("wall_clock_step_h", 0.0))
            wall_clock_phase = max(times) if times else 0.0
            rows_wc.append({"phase": phase, "wall_clock_phase_h": wall_clock_phase})
        df_wc = pd.DataFrame(rows_wc)

        df_phase = agg.merge(df_wc, on="phase", how="left").sort_values("phase")
        df_phase.to_csv("static/phases_aggregats.csv", index=False, encoding="utf-8")

        # Audit hôpital
        hop = df_plan[df_plan["phase"] == "0(hôpital)"]
        if not hop.empty:
            hop[["etape","id_batiment","step_cost","step_time","labour_cost","wall_clock_step_h","note"]] \
                .to_csv("static/phase0_hopital.csv", index=False, encoding="utf-8")

    print("Exports : OK (dont courbes cumulatives et top infras réparées)")
