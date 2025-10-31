# chargement, fusion, contrôles
# Toute ta partie “Chargement & fusion” + calcul occ_rate + validations + cost_base/time_base_h

import pandas as pd
from config import COST_PER_M, H_PER_M, EXPECTED_INFRA_TYPES
from utils import parse_bool_like, warn_unknown_occupation

def _compute_occ_rate(row):
    to = row.get("taux_occupation")
    if pd.notna(to):
        try:
            val = float(to)
            return min(max(val, 0.0), 1.0)
        except:
            pass
    eh = parse_bool_like(row.get("est_habite"))
    if eh is True:  return 1.0
    if eh is False: return 0.0
    return 1.0  # défaut prudent

def _unit_cost(row):
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    return COST_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

def _unit_hours(row):
    if str(row["infra_type"]).strip().lower() == "infra_intacte": return 0.0
    return H_PER_M.get(str(row["type_infra"]).strip().lower(), 0.0)

def load_and_prepare(
    path_arbre: str,
    path_infra_csv: str,
    path_bats_csv: str,
) -> pd.DataFrame:
    # Chargement
    df = pd.read_excel(path_arbre)
    infra_meta = pd.read_csv(path_infra_csv, encoding="utf-8")
    bats_meta  = pd.read_csv(path_bats_csv,  encoding="utf-8")

    # Nettoyage colonnes
    infra_meta.columns = [c.strip() for c in infra_meta.columns]
    bats_meta.columns  = [c.strip() for c in bats_meta.columns]

    # Colonnes manquantes → création vide
    if "est_habite" not in bats_meta.columns: bats_meta["est_habite"] = None
    if "taux_occupation" not in bats_meta.columns: bats_meta["taux_occupation"] = None

    # Jointures
    df = df.merge(infra_meta.rename(columns={"id_infra":"infra_id"}), on="infra_id", how="left")
    df = df.merge(
        bats_meta[["id_batiment","type_batiment","nb_maisons","est_habite","taux_occupation"]],
        on="id_batiment", how="left", suffixes=("","_from_bats")
    )

    # nb_maisons : priorité aux métadonnées
    if "nb_maisons_from_bats" in df.columns:
        df["nb_maisons"] = df["nb_maisons_from_bats"].fillna(df["nb_maisons"])
        df.drop(columns=["nb_maisons_from_bats"], inplace=True)

    df["nb_maisons"] = df["nb_maisons"].fillna(1)
    if (df["nb_maisons"] < 0).any():
        raise ValueError("nb_maisons ne doit pas être négatif.")
    df["nb_maisons"] = df["nb_maisons"].astype(int)

    # Defaults
    df["type_batiment"] = df["type_batiment"].fillna("habitation")

    # Occupation
    df["occ_rate"] = df.apply(_compute_occ_rate, axis=1)
    warn_unknown_occupation(df)

    # Flags
    df["is_uninhabited"] = (df["occ_rate"] <= 0.0).astype(int)

    # Schéma requis
    required = {"infra_id","id_batiment","longueur","infra_type","type_infra","nb_maisons",
                "type_batiment","occ_rate","is_uninhabited"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes après fusion: {missing}")

    # Coût et temps par infra
    df["cost_base"]   = df.apply(lambda r: _unit_cost(r)  * float(r["longueur"]), axis=1)
    df["time_base_h"] = df.apply(lambda r: _unit_hours(r) * float(r["longueur"]), axis=1)

    # Validation type_infra
    unknown_types = (
        set(df.loc[df["infra_type"].str.strip().str.lower() != "infra_intacte", "type_infra"]
              .dropna().str.strip().str.lower())
        - EXPECTED_INFRA_TYPES
    )
    if unknown_types:
        raise ValueError(
            f"type_infra inconnus: {sorted(unknown_types)}. "
            f"Ajoute leurs barèmes dans COST_PER_M et H_PER_M."
        )

    return df
