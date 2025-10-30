import pandas as pd
import geopandas as gpd
import numpy as np
import folium
from shapely.geometry import Point, LineString, MultiLineString, MultiPoint

# -----------------------------
# CONFIG
# -----------------------------
COUT_PAR_TYPE = {"aerien": 500.0, "semi-aerien": 750.0, "fourreau": 900.0}
HEURE_PAR_M = {"aerien": 2.0, "semi-aerien": 4.0, "fourreau": 5.0}
HOURS_PER_DAY = 8.0
HORIZON_JOURS = 365

# Poids score (positif = favorisé, négatif = pénalisé)
WEIGHTS = {
    "prise": 0.5,             # positif (nombre de prises)
    "building_weight": 0.25,  # positif (importance type bâtiment)
    "cost": -0.1,             # pénalise coût
    "time": -0.08,            # pénalise temps
    "difficulte_infra": -0.07,# pénalise difficulté infra
    "difficulte_bat": -0.05   # pénalise difficulté bâtiment
}

# pondération par type de bâtiment (importance)
BUILDING_TYPE_WEIGHT = {"hopital": 5.0, "ecole": 2.0, "habitation": 1.0}

# refresh advanced:
REFRESH_RATE = 0.30              # base proportion of difficulty reduction (max)
HOSPITAL_REFRESH_BOOST = 1.5     # multiplier to refresh effect if repaired infra serves hospital
MIN_DIFFICULTE = 0.05            # plancher difficulté

# hospital priority bonus to score
HOSPITAL_SCORE_BONUS = 0.2

# paralellisation: number of teams
N_EQUIPEES = 3

# -----------------------------
# 1. Chargement & normalisation CRS
# -----------------------------
batiments = gpd.read_file("batiments.shp")
infras = gpd.read_file("infrastructures.shp")
reseau = pd.read_excel("reseau_en_arbre.xlsx")

if "id_bat" in batiments.columns and "id_batiment" not in batiments.columns:
    batiments.rename(columns={"id_bat": "id_batiment"}, inplace=True)

if batiments.crs is None:
    batiments.set_crs(epsg=4326, inplace=True)
if infras.crs is None:
    infras.set_crs(epsg=4326, inplace=True)

batiments = batiments.to_crs(epsg=4326)
infras = infras.to_crs(epsg=4326)

# -----------------------------
# 2. Merge geometry -> reseau
# -----------------------------
if "geometry" not in reseau.columns:
    reseau = reseau.merge(batiments[["id_batiment", "geometry"]], on="id_batiment", how="left")

# defaults
reseau["nb_maisons"] = reseau.get("nb_maisons", 1)
reseau["difficulte_bat"] = reseau.get("difficulte_bat", 1)
reseau["difficulte_infra"] = reseau.get("difficulte_infra", 1)
reseau["infra_type"] = reseau.get("infra_type", "infra_intacte")
reseau["longueur"] = reseau["longueur"].fillna(1)
reseau["nb_batiments"] = reseau.groupby("infra_id")["id_batiment"].transform("count")
reseau["temps_reparation"] = reseau.get("temps_reparation", np.nan)
reseau["prise"] = reseau["nb_batiments"] * reseau["nb_maisons"]

# join building type if available
if "type_batiment" in batiments.columns:
    reseau = reseau.merge(batiments[["id_batiment","type_batiment"]], on="id_batiment", how="left")
else:
    reseau["type_batiment"] = reseau.get("type_batiment", "habitation")

reseau["type_batiment"] = reseau["type_batiment"].fillna("habitation").str.lower()

# -----------------------------
# 3. Agrégation par infrastructure (infra_agg)
# -----------------------------
infra_agg = reseau.groupby("infra_id").agg({
    "longueur": "mean",
    "prise": "sum",
    "nb_batiments": "max",
}).reset_index()

# get infra_type from infras layer or reseau
if "infra_type" in infras.columns:
    infra_agg = infra_agg.merge(infras[["infra_id","infra_type"]], on="infra_id", how="left")
else:
    infra_agg = infra_agg.merge(reseau[["infra_id","infra_type"]].drop_duplicates(), on="infra_id", how="left")

# cost/time per m
infra_agg["cost_per_m"] = infra_agg["infra_type"].apply(lambda t: COUT_PAR_TYPE.get(str(t).lower(), np.mean(list(COUT_PAR_TYPE.values()))))
infra_agg["hours_per_m"] = infra_agg["infra_type"].apply(lambda t: HEURE_PAR_M.get(str(t).lower(), np.mean(list(HEURE_PAR_M.values()))))

infra_agg["cout_total"] = infra_agg["longueur"] * infra_agg["cost_per_m"]
infra_agg["heures_total"] = infra_agg["longueur"] * infra_agg["hours_per_m"]
infra_agg["jours_estimes"] = infra_agg["heures_total"] / HOURS_PER_DAY

# difficulté infra initiale (moyenne des lignes reseau reliées)
infra_agg = infra_agg.merge(reseau.groupby("infra_id")["difficulte_infra"].mean().reset_index(), on="infra_id", how="left")

# -----------------------------
# 4. Résumé bâtiments par infra (weighted prises, nb hopitaux)
# -----------------------------
b = reseau.copy()
b["type_weight"] = b["type_batiment"].map(lambda t: BUILDING_TYPE_WEIGHT.get(t.lower(), 1.0))
b["weighted_prises"] = b["nb_maisons"] * b["type_weight"]
bat_summary = b.groupby("infra_id").agg({
    "weighted_prises": "sum",
    "nb_maisons": "sum",
    "id_batiment": "nunique",
    "type_batiment": lambda s: list(s)  # list of types served
}).reset_index().rename(columns={"id_batiment":"nb_batiments_real","type_batiment":"types_served"})

infra_agg = infra_agg.merge(bat_summary, on="infra_id", how="left")
infra_agg[["weighted_prises","nb_maisons","nb_batiments_real"]] = infra_agg[["weighted_prises","nb_maisons","nb_batiments_real"]].fillna(0)

# flag if serves hospital
infra_agg["serves_hopital"] = infra_agg["types_served"].apply(lambda lst: any([str(x).lower()=="hopital" for x in (lst if isinstance(lst,list) else [])]))

# -----------------------------
# 5. Normalisation utilitaire
# -----------------------------
def safe_normalize(s):
    if s.max() == s.min():
        return pd.Series(1.0, index=s.index)
    return (s - s.min()) / (s.max() - s.min())

infra_agg["norm_prise"] = safe_normalize(infra_agg["prise"])
infra_agg["norm_weighted_prises"] = safe_normalize(infra_agg["weighted_prises"])
infra_agg["norm_cout"] = safe_normalize(infra_agg["cout_total"])
infra_agg["norm_jours"] = safe_normalize(infra_agg["jours_estimes"])
infra_agg["norm_difficulte_infra"] = safe_normalize(infra_agg["difficulte_infra"])

# -----------------------------
# 6. Score initial
# -----------------------------
pos = WEIGHTS["prise"] * infra_agg["norm_prise"] + WEIGHTS["building_weight"] * infra_agg["norm_weighted_prises"]
denom = 1.0 + (infra_agg["norm_cout"] * abs(WEIGHTS["cost"]) + infra_agg["norm_jours"] * abs(WEIGHTS["time"]) + infra_agg["norm_difficulte_infra"] * abs(WEIGHTS["difficulte_infra"]))
infra_agg["score"] = pos / (denom + 1e-9)
# hospital bonus
infra_agg.loc[infra_agg["serves_hopital"], "score"] *= (1.0 + HOSPITAL_SCORE_BONUS)

# -----------------------------
# 7. Préparer mapping infra -> bâtiments
# -----------------------------
infra_to_bats = reseau.groupby("infra_id")["id_batiment"].apply(lambda s: set(s.dropna())).to_dict()

# -----------------------------
# 8. Simulation parallèle (N_EQUIPEES)
# -----------------------------
infra_agg = infra_agg.set_index("infra_id")
infra_agg["reparee"] = False
infra_agg["jour_debut"] = np.nan
infra_agg["jour_fin"] = np.nan
infra_agg["ordre"] = np.nan

# équipe availability times (jours)
team_available = [0.0 for _ in range(N_EQUIPEES)]
repair_log = []
ordre = 1

# We'll run until all repaired or horizon
while not infra_agg["reparee"].all():
    remaining = infra_agg[~infra_agg["reparee"]].copy()
    if remaining.empty:
        break

    # recompute normalized metrics on remaining
    remaining["norm_prise"] = safe_normalize(remaining["prise"])
    remaining["norm_weighted_prises"] = safe_normalize(remaining["weighted_prises"])
    remaining["norm_cout"] = safe_normalize(remaining["cout_total"])
    remaining["norm_jours"] = safe_normalize(remaining["jours_estimes"])
    remaining["norm_difficulte_infra"] = safe_normalize(remaining["difficulte_infra"])

    pos = WEIGHTS["prise"] * remaining["norm_prise"] + WEIGHTS["building_weight"] * remaining["norm_weighted_prises"]
    denom = 1.0 + (remaining["norm_cout"] * abs(WEIGHTS["cost"]) + remaining["norm_jours"] * abs(WEIGHTS["time"]) + remaining["norm_difficulte_infra"] * abs(WEIGHTS["difficulte_infra"]))
    remaining["score"] = pos / (denom + 1e-9)
    # hospital bonus
    remaining.loc[remaining["serves_hopital"], "score"] *= (1.0 + HOSPITAL_SCORE_BONUS)

    # pick best (highest score)
    best_id = remaining["score"].idxmax()
    best = infra_agg.loc[best_id]

    # assign to earliest available team
    team_idx = int(np.argmin(team_available))
    start_day = team_available[team_idx]
    duration_days = infra_agg.at[best_id, "jours_estimes"]
    end_day = start_day + duration_days

    # record
    infra_agg.at[best_id, "jour_debut"] = start_day
    infra_agg.at[best_id, "jour_fin"] = end_day
    infra_agg.at[best_id, "ordre"] = ordre
    infra_agg.at[best_id, "reparee"] = True

    team_available[team_idx] = end_day  # team becomes free at end_day
    ordre += 1

    repair_log.append({
        "infra_id": best_id,
        "team": team_idx,
        "start_day": start_day,
        "end_day": end_day,
        "cout": infra_agg.at[best_id,"cout_total"],
        "jours": duration_days,
        "score": remaining.loc[best_id,"score"]
    })

    # REFRESH: reduce difficulty of other infra proportionally to shared buildings fraction
    bats_served = infra_to_bats.get(best_id, set())
    serves_hospital = infra_agg.at[best_id, "serves_hopital"]
    for other_id in infra_agg[~infra_agg["reparee"]].index:
        other_bats = infra_to_bats.get(other_id, set())
        if not other_bats:
            continue
        shared = len(bats_served.intersection(other_bats))
        if shared == 0:
            continue
        # fraction relative to smaller set to emphasize tight coupling
        denom_shared = max(1, min(len(bats_served), len(other_bats)))
        shared_frac = shared / denom_shared
        # refresh effect
        boost = HOSPITAL_REFRESH_BOOST if serves_hospital else 1.0
        reduction = REFRESH_RATE * shared_frac * boost
        new_diff = max(MIN_DIFFICULTE, infra_agg.at[other_id, "difficulte_infra"] * (1.0 - reduction))
        infra_agg.at[other_id, "difficulte_infra"] = new_diff

    # Break if horizon exceeded (safety)
    if min(team_available) > HORIZON_JOURS:
        print("Horizon dépassé, arrêt de la simulation.")
        break

# -----------------------------
# 9. Post-traitement : phases & export
# -----------------------------
infra_agg.reset_index(inplace=True)
# determine phases by ordre percentiles
infra_agg = infra_agg.sort_values("ordre")
n = len(infra_agg)
if n == 0:
    raise SystemExit("Aucune infrastructure trouvée.")

p20 = max(1, int(0.2*n))
p50 = max(1, int(0.5*n))

infra_agg["phase_planifiee"] = 2
infra_agg.loc[infra_agg.index[:p50], "phase_planifiee"] = 1
infra_agg.loc[infra_agg["infra_type"] == "infra_intacte", "phase_planifiee"] = 0

# attach info to reseau rows
reseau = reseau.merge(infra_agg[["infra_id","cout_total","jours_estimes","jour_debut","jour_fin","ordre","phase_planifiee"]], on="infra_id", how="left")

# export excel
out_cols = ["infra_id","infra_type","longueur","prise","weighted_prises","cout_total","heures_total","jours_estimes","difficulte_infra","jour_debut","jour_fin","ordre","phase_planifiee"]
infra_agg[out_cols].to_excel("plan_raccordement_priorise_parallel.xlsx", index=False)
print("Exporté : plan_raccordement_priorise_parallel.xlsx")

# summary
print(f"Coût total estimé: {infra_agg['cout_total'].sum():.2f} €")
print(f"Durée totale estimée (jours, séquentiel sum): {infra_agg['jours_estimes'].sum():.2f} jours")
print(f"Simulation finie: équipes disponibles jusqu'à {max(team_available):.2f} jours")

# -----------------------------
# 10. Folium : visualisation
# -----------------------------
infras_plot = infras.merge(infra_agg[["infra_id","phase_planifiee","jour_debut","jour_fin","ordre","cout_total"]], on="infra_id", how="left")
bat_plot = batiments.merge(reseau[['id_batiment','infra_id']], on='id_batiment', how='left')
bat_plot = bat_plot.merge(infra_agg[['infra_id','phase_planifiee','jour_debut','jour_fin']], on='infra_id', how='left')

phase_colors = {0:"#4daf4a", 1:"#b30000", 2:"#ff8c00"}
center = [batiments.geometry.y.mean(), batiments.geometry.x.mean()]
m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")

for _, infra in infras_plot.iterrows():
    geom = infra.geometry
    if geom is None:
        continue
    lines = []
    if isinstance(geom, LineString):
        lines = [[(y,x) for x,y in geom.coords]]
    elif isinstance(geom, MultiLineString):
        lines = [[(y,x) for x,y in line.coords] for line in geom]
    else:
        continue
    color = phase_colors.get(int(infra.get("phase_planifiee",2)), "#cccccc")
    tooltip = (f"Infra: {infra['infra_id']}<br>Type: {infra.get('infra_type','?')}<br>Phase: {int(infra.get('phase_planifiee',-1))}<br>"
               f"Jour début: {int(infra['jour_debut']) if not pd.isna(infra.get('jour_debut')) else 'N/A'}<br>Cout: {infra.get('cout_total',0):.0f} €")
    for line in lines:
        folium.PolyLine(line, color=color, weight=3+0.5*min(10, infra.get("prise",0)), opacity=0.9, tooltip=tooltip).add_to(m)

for _, bat in bat_plot.iterrows():
    geom = bat.geometry
    if geom is None:
        continue
    coords = None
    if isinstance(geom, Point):
        coords = [geom.y, geom.x]
    elif isinstance(geom, MultiPoint):
        coords = [geom[0].y, geom[0].x]
    else:
        continue
    phase = int(bat.get("phase_planifiee",2)) if not pd.isna(bat.get("phase_planifiee")) else 2
    color = phase_colors.get(phase, "#cccccc")
    popup = (f"Bâtiment: {bat['id_batiment']}<br>Infra: {bat.get('infra_id','N/A')}<br>Phase infra: {phase}<br>"
             f"Jour début infra: {int(bat['jour_debut']) if not pd.isna(bat.get('jour_debut')) else 'N/A'}")
    folium.CircleMarker(location=coords, radius=4, color=color, fill=True, fill_color=color, fill_opacity=0.9, popup=popup).add_to(m)

legend_html = """
<div style="position: fixed; bottom: 30px; left: 30px; background-color: white;
            border:2px solid grey; z-index:9999; font-size:14px; padding:10px;">
<b>Légende - Phase planifiée</b><br>
<i style="background:#4daf4a;width:10px;height:10px;display:inline-block;"></i> Bon état / Pas prioritaire<br>
<i style="background:#b30000;width:10px;height:10px;display:inline-block;"></i> À réparer en priorité (phase 1)<br>
<i style="background:#ff8c00;width:10px;height:10px;display:inline-block;"></i> Peut attendre (phase 2)
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

m.save("plan_raccordement_folium_parallel_refresh.html")
print("Carte Folium exportée : plan_raccordement_folium_parallel_refresh.html")
m