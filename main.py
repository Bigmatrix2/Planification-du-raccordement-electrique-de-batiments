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
COUT_OUVRIER_PAR_JOUR = 300.0
HOURS_PER_DAY = 8.0
MAX_OUVRIERS_PAR_INFRA = 4
N_OUVRIERS = 2000
HORIZON_JOURS = 365

WEIGHTS = {
    "prise": 0.5,
    "building_weight": 0.25,
    "cost": -0.1,
    "time": -0.08,
    "difficulte_infra": -0.07,
    "difficulte_bat": -0.05
}

BUILDING_TYPE_WEIGHT = {"hopital": 5.0, "ecole": 2.0, "habitation": 1.0}
REFRESH_RATE = 0.30
HOSPITAL_REFRESH_BOOST = 1.5
MIN_DIFFICULTE = 0.05
HOSPITAL_SCORE_BONUS = 0.2

AUTONOMIE_HOPITAL = 20.0
MARGE_SECU = 0.20
TEMPS_MAX_UTILISABLE = AUTONOMIE_HOPITAL / (1 + MARGE_SECU)

# -----------------------------
# 1. Chargement données
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

if "geometry" not in reseau.columns:
    reseau = reseau.merge(batiments[["id_batiment", "geometry"]], on="id_batiment", how="left")

# Defaults
reseau["nb_maisons"] = reseau.get("nb_maisons", 1)
reseau["difficulte_bat"] = reseau.get("difficulte_bat", 1)
reseau["difficulte_infra"] = reseau.get("difficulte_infra", 1)
reseau["infra_type"] = reseau.get("infra_type", "infra_intacte")
reseau["longueur"] = reseau["longueur"].fillna(1)
reseau["nb_batiments"] = reseau.groupby("infra_id")["id_batiment"].transform("count")
reseau["temps_reparation"] = reseau.get("temps_reparation", np.nan)
reseau["prise"] = reseau["nb_batiments"] * reseau["nb_maisons"]

if "type_batiment" in batiments.columns:
    reseau = reseau.merge(batiments[["id_batiment","type_batiment"]], on="id_batiment", how="left")
else:
    reseau["type_batiment"] = "habitation"
reseau["type_batiment"] = reseau["type_batiment"].fillna("habitation").str.lower()

# -----------------------------
# 2. Agrégation par infrastructure
# -----------------------------
infra_agg = reseau.groupby("infra_id").agg({
    "longueur": "mean",
    "prise": "sum",
    "nb_batiments": "max",
}).reset_index()

if "infra_type" in infras.columns:
    infra_agg = infra_agg.merge(infras[["infra_id","infra_type"]], on="infra_id", how="left")
else:
    infra_agg = infra_agg.merge(reseau[["infra_id","infra_type"]].drop_duplicates(), on="infra_id", how="left")

# -----------------------------
# 3. Résumé bâtiments
# -----------------------------
b = reseau.copy()
b["type_weight"] = b["type_batiment"].map(lambda t: BUILDING_TYPE_WEIGHT.get(t.lower(), 1.0))
b["weighted_prises"] = b["nb_maisons"] * b["type_weight"]
bat_summary = b.groupby("infra_id").agg({
    "weighted_prises": "sum",
    "nb_maisons": "sum",
    "id_batiment": "nunique",
    "type_batiment": lambda s: list(s)
}).reset_index().rename(columns={"id_batiment":"nb_batiments_real","type_batiment":"types_served"})
infra_agg = infra_agg.merge(bat_summary, on="infra_id", how="left")
infra_agg[["weighted_prises","nb_maisons","nb_batiments_real"]] = infra_agg[["weighted_prises","nb_maisons","nb_batiments_real"]].fillna(0)
infra_agg["serves_hopital"] = infra_agg["types_served"].apply(lambda lst: any([str(x).lower()=="hopital" for x in (lst if isinstance(lst,list) else [])]))

# -----------------------------
# 4. Normalisation utilitaire
# -----------------------------
def safe_normalize(s):
    if s.max() == s.min():
        return pd.Series(1.0, index=s.index)
    return (s - s.min()) / (s.max() - s.min())

infra_agg["norm_prise"] = safe_normalize(infra_agg["prise"])
infra_agg["norm_weighted_prises"] = safe_normalize(infra_agg["weighted_prises"])

# -----------------------------
# 5. Score initial
# -----------------------------
pos = WEIGHTS["prise"] * infra_agg["norm_prise"] + WEIGHTS["building_weight"] * infra_agg["norm_weighted_prises"]
denom = 1.0
infra_agg["score"] = pos / (denom + 1e-9)
infra_agg.loc[infra_agg["serves_hopital"], "score"] *= (1.0 + HOSPITAL_SCORE_BONUS)

# -----------------------------
# 6. Ajouter difficulte_infra moyenne
# -----------------------------
infra_agg = infra_agg.merge(
    reseau.groupby("infra_id")["difficulte_infra"].mean().reset_index(),
    on="infra_id",
    how="left"
)
infra_agg["difficulte_infra"] = infra_agg["difficulte_infra"].fillna(1.0)

# -----------------------------
# 7. Calcul durée et coût
# -----------------------------
def calc_duree_et_cout(row):
    h_total = row["longueur"] * HEURE_PAR_M.get(row["infra_type"].lower(), np.mean(list(HEURE_PAR_M.values())))
    h_par_ouvrier = h_total / min(MAX_OUVRIERS_PAR_INFRA, N_OUVRIERS)
    jours = h_par_ouvrier / HOURS_PER_DAY
    cout_mat = row["longueur"] * COUT_PAR_TYPE.get(row["infra_type"].lower(), np.mean(list(COUT_PAR_TYPE.values())))
    nb_ouvriers = min(MAX_OUVRIERS_PAR_INFRA, N_OUVRIERS)
    cout_ouvriers = nb_ouvriers * COUT_OUVRIER_PAR_JOUR * jours
    return pd.Series({"jours_estimes": jours, "heures_reelles": h_par_ouvrier, "cout_total": cout_mat + cout_ouvriers})

infra_agg[["jours_estimes", "heures_reelles", "cout_total"]] = infra_agg.apply(calc_duree_et_cout, axis=1)

# -----------------------------
# 8. Simulation refresh
# -----------------------------
infra_agg = infra_agg.set_index("infra_id")
infra_to_bats = reseau.groupby("infra_id")["id_batiment"].apply(lambda s: set(s.dropna())).to_dict()
repair_log = []

for infra_id, row in infra_agg.iterrows():
    repair_log.append({
        "infra_id": infra_id,
        "start_day": 0.0,
        "end_day": row["jours_estimes"],
        "cout": row["cout_total"],
        "jours": row["jours_estimes"],
        "score": row["score"]
    })
    infra_agg.at[infra_id, "reparee"] = True
    infra_agg.at[infra_id, "jour_fin"] = row["jours_estimes"]

    # REFRESH difficulté
    bats_served = infra_to_bats.get(infra_id, set())
    serves_hospital = row["serves_hopital"]
    for other_id in infra_agg.index:
        if other_id == infra_id:
            continue
        other_bats = infra_to_bats.get(other_id, set())
        shared = len(bats_served.intersection(other_bats))
        if shared == 0:
            continue
        denom_shared = max(1, min(len(bats_served), len(other_bats)))
        shared_frac = shared / denom_shared
        boost = HOSPITAL_REFRESH_BOOST if serves_hospital else 1.0
        reduction = REFRESH_RATE * shared_frac * boost
        new_diff = max(MIN_DIFFICULTE, infra_agg.at[other_id, "difficulte_infra"] * (1.0 - reduction))
        infra_agg.at[other_id, "difficulte_infra"] = new_diff

infra_agg.reset_index(inplace=True)

# -----------------------------
# 9. Vérification autonomie hôpital
# -----------------------------
infra_hopital = infra_agg[infra_agg["serves_hopital"]].copy()
infra_hopital["heures_reelles_par_infra"] = infra_hopital["heures_reelles"]
infra_danger = infra_hopital[infra_hopital["heures_reelles_par_infra"] > TEMPS_MAX_UTILISABLE]

if not infra_danger.empty:
    print("\n⚠️ Attention ! Certaines infrastructures hospitalières dépassent la marge de sécurité du générateur :")
    for _, row in infra_danger.iterrows():
        print(f"- Infra {row['infra_id']} : {row['heures_reelles_par_infra']:.1f} h (> {TEMPS_MAX_UTILISABLE:.1f} h)")
else:
    print("\n✅ Toutes les infrastructures hospitalières respectent la marge de sécurité du générateur (20% de marge).")

# -----------------------------
# 10. Attribution phases
# -----------------------------
infra_agg = infra_agg.sort_values("score", ascending=False)
n = len(infra_agg)
p50 = max(1, int(0.5*n))
infra_agg["phase_planifiee"] = 2
infra_agg.loc[infra_agg.index[:p50], "phase_planifiee"] = 1
infra_agg.loc[infra_agg["infra_type"] == "infra_intacte", "phase_planifiee"] = 0

# -----------------------------
# 11. Export Excel
# -----------------------------
reseau = reseau.merge(infra_agg[["infra_id","cout_total","jours_estimes","jour_fin","phase_planifiee"]], on="infra_id", how="left")
out_cols = ["infra_id","infra_type","longueur","prise","weighted_prises","cout_total","heures_reelles","jours_estimes","difficulte_infra","jour_fin","phase_planifiee"]
infra_agg[out_cols].to_excel("plan_raccordement_priorise_2000_ouvriers.xlsx", index=False)
print("Exporté : plan_raccordement_priorise_2000_ouvriers.xlsx")
print(f"Coût total estimé : {infra_agg['cout_total'].sum():.2f} €")
print(f"Durée totale estimée max (par infra) : {infra_agg['jours_estimes'].max():.2f} jours")

# -----------------------------
# 12. Carte Folium
# -----------------------------
infras_plot = infras.merge(infra_agg[["infra_id","phase_planifiee","jour_fin","cout_total","prise"]], on="infra_id", how="left")
bat_plot = batiments.merge(reseau[['id_batiment','infra_id']], on='id_batiment', how='left')
bat_plot = bat_plot.merge(infra_agg[['infra_id','phase_planifiee','jour_fin']], on='infra_id', how='left')

phase_colors = {0:"#4daf4a", 1:"#b30000", 2:"#ff8c00"}
center = [batiments.geometry.y.mean(), batiments.geometry.x.mean()]
m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")

# Tracer les infrastructures
for _, infra in infras_plot.iterrows():
    geom = infra.geometry
    if geom is None:
        continue

    # définir la couleur AVANT
    phase_val = int(infra.get("phase_planifiee", 2))
    color = phase_colors.get(phase_val, "#cccccc")

    # préparer les lignes
    lines = []
    if isinstance(geom, LineString):
        lines = [[(y, x) for x, y in geom.coords]]
    elif isinstance(geom, MultiLineString):
        lines = [[(y, x) for x, y in line.coords] for line in geom]
    else:
        continue

    tooltip = (f"Infra: {infra['infra_id']}<br>Type: {infra.get('infra_type','?')}<br>"
               f"Phase: {phase_val}<br>"
               f"Jour fin: {int(infra['jour_fin']) if not pd.isna(infra.get('jour_fin')) else 'N/A'}<br>"
               f"Cout: {infra.get('cout_total',0):.0f} €")
    for line in lines:
        folium.PolyLine(
            line,
            color=color,
            weight=3 + 0.5*min(10, infra.get("prise", 0)),
            opacity=0.9,
            tooltip=tooltip
        ).add_to(m)

# Tracer les bâtiments
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
    popup = (f"Bâtiment: {bat['id_batiment']}<br>Infra: {bat.get('infra_id','N/A')}<br>"
             f"Phase infra: {phase}<br>"
             f"Jour fin infra: {int(bat['jour_fin']) if not pd.isna(bat.get('jour_fin')) else 'N/A'}")
    folium.CircleMarker(
        location=coords,
        radius=4,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.9,
        popup=popup
    ).add_to(m)

# Légende
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

# Sauvegarde
m.save("plan_raccordement_folium_2000_ouvriers.html")
print("✅ Carte Folium exportée : plan_raccordement_folium_2000_ouvriers.html")