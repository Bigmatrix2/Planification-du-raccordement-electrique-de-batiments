import pandas as pd
import geopandas as gpd
import numpy as np
import folium
from shapely.geometry import Point, LineString, MultiLineString, MultiPoint

# -----------------------------
# 1. Chargement des données
# -----------------------------
batiments = gpd.read_file("batiments.shp")
infras = gpd.read_file("infrastructures.shp")
reseau = pd.read_excel("reseau_en_arbre.xlsx")
batiments.rename(columns={"id_bat": "id_batiment"}, inplace=True)

# -----------------------------
# 2. Harmonisation CRS (Folium = EPSG:4326)
# -----------------------------
if batiments.crs is None:
    batiments.set_crs(epsg=4326, inplace=True)
if infras.crs is None:
    infras.set_crs(epsg=4326, inplace=True)

batiments = batiments.to_crs(epsg=4326)
infras = infras.to_crs(epsg=4326)

# -----------------------------
# 3. Fusion et préparation des variables
# -----------------------------
reseau = reseau.merge(
    batiments[["id_batiment", "geometry"]],
    on="id_batiment",
    how="left"
)

reseau["nb_maisons"] = reseau.get("nb_maisons", 1)
reseau["difficulte_bat"] = reseau.get("difficulte_bat", 1)
reseau["difficulte_infra"] = reseau.get("difficulte_infra", 1)
reseau["infra_type"] = reseau.get("infra_type", "infra_intacte")
reseau["longueur"] = reseau["longueur"].fillna(1)
reseau["nb_batiments"] = reseau.groupby("infra_id")["id_batiment"].transform("count")
reseau["temps_reparation"] = reseau.get("temps_reparation", 1.0)
reseau["prise"] = reseau["nb_batiments"] * reseau["nb_maisons"]

# -----------------------------
# 4. Normalisation et score
# -----------------------------
def normaliser(col):
    return (col - col.min()) / (col.max() - col.min()) if col.max() != col.min() else 1

for col in ["nb_batiments", "nb_maisons", "longueur", "difficulte_infra", "difficulte_bat", "temps_reparation"]:
    reseau[f"norm_{col}"] = normaliser(reseau[col])

reseau["score_phase"] = reseau["prise"] * 0.6 + (1 - reseau["norm_temps_reparation"]) * 0.4

def attribuer_phase(row):
    if row['infra_type'] == "infra_intacte":
        return 0
    elif row['infra_type'] == "a_remplacer":
        return 1 if row['score_phase'] >= reseau[reseau['infra_type']=="a_remplacer"]["score_phase"].quantile(0.5) else 2
    else:
        return 2

reseau["phase"] = reseau.apply(attribuer_phase, axis=1)

# -----------------------------
# 5. Planification temporelle
# -----------------------------
max_jour = 30
phase2 = reseau[reseau['phase']==2].copy()
phase2 = phase2.sort_values("score_phase", ascending=False)
phase2["jour_planifie"] = np.linspace(2, max_jour, len(phase2))
reseau.loc[phase2.index, "jour_planifie"] = phase2["jour_planifie"]
reseau.loc[reseau['phase']==1, "jour_planifie"] = 1
reseau.loc[reseau['phase']==0, "jour_planifie"] = 0

# -----------------------------
# 6. Palette de couleur
# -----------------------------
phase_colors = {
    0: "#4daf4a",  # vert
    1: "#000000",  # noir
    2: "#1E90FF"   # bleu
}

# -----------------------------
# 7. Association batiments / infrastructures
# -----------------------------
infra_phase = reseau.groupby('infra_id')[['phase','prise','jour_planifie']].max().reset_index()
infras_plot = infras.merge(infra_phase, on='infra_id', how='left')

bat_plot = batiments.merge(reseau[['id_batiment','infra_id','phase','prise','jour_planifie']], on='id_batiment', how='left')
bat_plot = bat_plot.merge(infras_plot[['infra_id','phase']], on='infra_id', suffixes=('', '_infra'), how='left')
bat_plot['phase_finale'] = bat_plot['phase_infra'].fillna(bat_plot['phase'])
bat_plot['color'] = bat_plot['phase_finale'].map(phase_colors)

# Vérif : on a bien des géométries valides
bat_plot = bat_plot[bat_plot.geometry.notna()]
infras_plot = infras_plot[infras_plot.geometry.notna()]

# -----------------------------
# 8. Création carte Folium
# -----------------------------
center = [batiments.geometry.y.mean(), batiments.geometry.x.mean()]
m = folium.Map(location=center, zoom_start=15, tiles="CartoDB positron")

# ---- Ajout des infrastructures ----
for _, infra in infras_plot.iterrows():
    geom = infra.geometry
    if geom is None:
        continue

    if isinstance(geom, LineString):
        coords = [(y, x) for x, y in geom.coords]
        lines = [coords]
    elif isinstance(geom, MultiLineString):
        lines = [[(y, x) for x, y in line.coords] for line in geom]
    else:
        continue

    for line in lines:
        folium.PolyLine(
            line,
            color=phase_colors.get(infra['phase'], "#cccccc"),
            weight=3,
            opacity=0.9,
            tooltip=f"Infrastructure {infra['infra_id']}<br>Phase: {infra['phase']}<br>Jour: {infra['jour_planifie']:.0f}<br>Prise: {infra['prise']}"
        ).add_to(m)

# ---- Ajout des bâtiments ----
for _, bat in bat_plot.iterrows():
    geom = bat.geometry
    if geom is None:
        continue

    if isinstance(geom, Point):
        coords = [geom.y, geom.x]
    elif isinstance(geom, MultiPoint):
        coords = [geom[0].y, geom[0].x]
    else:
        continue

    folium.CircleMarker(
        location=coords,
        radius=4,
        color=bat['color'],
        fill=True,
        fill_color=bat['color'],
        fill_opacity=0.9,
        popup=(f"<b>Bâtiment:</b> {bat['id_batiment']}<br>"
               f"<b>Phase:</b> {int(bat['phase_finale']) if not pd.isna(bat['phase_finale']) else 'N/A'}<br>"
               f"<b>Jour:</b> {int(bat['jour_planifie']) if not pd.isna(bat['jour_planifie']) else 'N/A'}<br>"
               f"<b>Prise:</b> {bat['prise']}")
    ).add_to(m)

# ---- Légende HTML ----
legend_html = """
<div style="position: fixed; bottom: 30px; left: 30px; background-color: white;
            border:2px solid grey; z-index:9999; font-size:14px; padding:10px;">
<b>Légende - Phases de réparation</b><br>
<i style="background:#4daf4a;width:10px;height:10px;display:inline-block;"></i> Bon état (phase 0)<br>
<i style="background:#000000;width:10px;height:10px;display:inline-block;"></i> À réparer en priorité (phase 1)<br>
<i style="background:#1E90FF;width:10px;height:10px;display:inline-block;"></i> Peut attendre (phase 2)
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# -----------------------------
# 9. Export
# -----------------------------
m.save("visualisation_folium_corrigee.html")
print("Carte Folium exportée : visualisation_folium_corrigee.html")
m