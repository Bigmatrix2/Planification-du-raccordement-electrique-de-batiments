# Centraliser les petites fonctions utilitaires, réutilisées partout.

import pandas as pd

def parse_bool_like(x):
    if pd.isna(x): return None
    s = str(x).strip().lower()
    if s in {"1","true","vrai","yes","oui","y"}: return True
    if s in {"0","false","faux","no","non","n"}: return False
    return None

def warn_unknown_occupation(df):
    df["_occ_unknown"] = df["taux_occupation"].isna() & df["est_habite"].isna()
    n_unknown = int(df["_occ_unknown"].sum())
    if n_unknown > 0:
        print(f"⚠️  {n_unknown} bâtiments sans info d'occupation -> occ_rate=1.0 par défaut.")
    df.drop(columns=["_occ_unknown"], errors="ignore", inplace=True)
