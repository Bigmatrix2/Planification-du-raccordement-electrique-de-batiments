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
# 1.b Ajout des infos type_batiment
# -----------------------------
bat_info = pd.read_csv("batiments.csv")
# Vérif colonnes
assert {'id_batiment', 'type_batiment', 'nb_maisons'}.issubset(bat_info.columns), \
    "Le CSV doit contenir id_batiment, type_batiment, nb_maisons"

# Renommer nb_maisons pour éviter conflit lors fusion
bat_info_merged = bat_info.rename(columns={'nb_maisons': 'nb_maisons_csv'})
batiments = batiments.merge(bat_info_merged, on='id_batiment', how='left')

# Mettre valeurs par défaut si manquantes
batiments['type_batiment'] = batiments['type_batiment'].fillna('habitation')
batiments['nb_maisons_csv'] = batiments['nb_maisons_csv'].fillna(1)


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
    batiments[["id_batiment", "type_batiment", "nb_maisons_csv", "geometry"]],
    on="id_batiment",
    how="left"
)

# Utiliser nb_maisons_csv en priorité, sinon garder l'ancienne valeur
if 'nb_maisons' in reseau.columns:
    reseau['nb_maisons'] = reseau['nb_maisons_csv'].fillna(reseau['nb_maisons']).fillna(1)
else:
    reseau['nb_maisons'] = reseau['nb_maisons_csv'].fillna(1)

# Supprimer la colonne temporaire
reseau = reseau.drop(columns=['nb_maisons_csv'])

# Valeurs par défaut pour les colonnes manquantes
reseau['type_batiment'] = reseau['type_batiment'].fillna('habitation')

# ------------- Normalisation des types -------------
# Uniformisation des valeurs pour éviter doublons avec accents et casse
def normalize_type_bat(typ):
    if pd.isna(typ):
        return 'habitation'
    typ = typ.lower()
    typ = typ.replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a')
    typ = typ.replace('ù', 'u').replace('ô', 'o').replace('î', 'i').replace('û', 'u')
    typ = typ.replace('hôpital', 'hopital').replace('école', 'ecole')
    if typ not in ['hopital', 'ecole', 'habitation']:
        return 'habitation'
    return typ

reseau['type_batiment'] = reseau['type_batiment'].apply(normalize_type_bat)

# ----------------------------------------------------

reseau["difficulte_bat"] = reseau.get("difficulte_bat", 1)
reseau["difficulte_infra"] = reseau.get("difficulte_infra", 1)
reseau["infra_type"] = reseau.get("infra_type", "infra_intacte")
reseau["longueur"] = reseau["longueur"].fillna(1)
reseau["nb_batiments"] = reseau.groupby("infra_id")["id_batiment"].transform("count")
reseau["temps_reparation"] = reseau.get("temps_reparation", 1.0)
reseau["prise"] = reseau["nb_batiments"] * reseau["nb_maisons"]

# Poids de priorité selon le type de bâtiment
priorite_map = {
    'hopital': 3.0,
    'ecole': 2.0,
    'habitation': 1.0
}
reseau['poids_priorite'] = reseau['type_batiment'].map(priorite_map).fillna(1.0)


# -----------------------------
# 4. Normalisation et score
# -----------------------------
def normaliser(col):
    return (col - col.min()) / (col.max() - col.min()) if col.max() != col.min() else 1

for col in ["nb_batiments", "nb_maisons", "longueur", "difficulte_infra", "difficulte_bat", "temps_reparation"]:
    reseau[f"norm_{col}"] = normaliser(reseau[col])

# Score ajusté avec poids de priorité
reseau["score_phase"] = (
    reseau["prise"] * 0.5
    + (1 - reseau["norm_temps_reparation"]) * 0.3
    + reseau["poids_priorite"] * 0.2
)

def attribuer_phase(row):
    if row['infra_type'] == "infra_intacte":
        return 0
    elif row['infra_type'] == "a_remplacer":
        # Priorité absolue pour hôpitaux et écoles
        if row['type_batiment'] == 'hopital':
            return 1
        elif row['type_batiment'] == 'ecole':
            return 1
        else:
            seuil = reseau[reseau['infra_type']=="a_remplacer"]["score_phase"].quantile(0.5)
            return 1 if row['score_phase'] >= seuil else 2
    else:
        return 2

reseau["phase"] = reseau.apply(attribuer_phase, axis=1)


# -----------------------------
# 5. Planification temporelle
# -----------------------------
max_jour = 30
phase2 = reseau[reseau['phase'] == 2].copy()
phase2 = phase2.sort_values("score_phase", ascending=False)
phase2["jour_planifie"] = np.linspace(2, max_jour, len(phase2))
reseau.loc[phase2.index, "jour_planifie"] = phase2["jour_planifie"]
reseau.loc[reseau['phase'] == 1, "jour_planifie"] = 1
reseau.loc[reseau['phase'] == 0, "jour_planifie"] = 0


# -----------------------------
# 6. Palette de couleur selon type de bâtiment
# -----------------------------
bat_colors = {
    'hopital': '#e41a1c',     # rouge
    'ecole': '#ff7f00',       # orange
    'habitation': '#4daf4a'   # vert
}


# -----------------------------
# 7. Association batiments / infrastructures
# -----------------------------
infra_phase = reseau.groupby('infra_id')[['phase', 'prise', 'jour_planifie', 'type_batiment']].agg({
    'phase': 'max',
    'prise': 'max',
    'jour_planifie': 'max',
    'type_batiment': lambda x: x.mode()[0] if not x.mode().empty else 'habitation'  # type dominant
}).reset_index()

infras_plot = infras.merge(infra_phase, on='infra_id', how='left')
infras_plot['type_batiment'] = infras_plot['type_batiment'].fillna('habitation')
infras_plot['color'] = infras_plot['type_batiment'].map(bat_colors).fillna("#cccccc")

# Inclure nb_maisons dans fusion bat_plot
bat_plot = batiments.merge(
    reseau[['id_batiment', 'infra_id', 'phase', 'prise', 'jour_planifie', 'type_batiment', 'nb_maisons']],
    on='id_batiment',
    how='left',
    suffixes=('_bat', '_reseau')
)

# Gérer les suffixes éventuels
if 'type_batiment_reseau' in bat_plot.columns:
    bat_plot['type_batiment'] = bat_plot['type_batiment_reseau'].fillna(bat_plot.get('type_batiment_bat', 'habitation'))
    bat_plot = bat_plot.drop(columns=['type_batiment_bat', 'type_batiment_reseau'], errors='ignore')

if 'nb_maisons_reseau' in bat_plot.columns:
    bat_plot['nb_maisons'] = bat_plot['nb_maisons_reseau'].fillna(bat_plot.get('nb_maisons_bat', 1))
    bat_plot = bat_plot.drop(columns=['nb_maisons_bat', 'nb_maisons_reseau'], errors='ignore')

bat_plot['type_batiment'] = bat_plot['type_batiment'].fillna('habitation')
bat_plot['nb_maisons'] = bat_plot['nb_maisons'].fillna(1)
bat_plot['color'] = bat_plot['type_batiment'].map(bat_colors).fillna("#cccccc")

# Vérif géométries valides
bat_plot = bat_plot[bat_plot.geometry.notna()]
infras_plot = infras_plot[infras_plot.geometry.notna()]


# -----------------------------
# 8. Création carte Folium
# -----------------------------
center = [batiments.geometry.y.mean(), batiments.geometry.x.mean()]
m = folium.Map(location=center, zoom_start=15, tiles="CartoDB positron")

# Ajout des infrastructures
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
            color=infra['color'],
            weight=3,
            opacity=0.9,
            tooltip=f"Infrastructure {infra['infra_id']}<br>Type: {infra['type_batiment']}<br>Phase: {infra['phase']}<br>Jour: {infra['jour_planifie']:.0f}<br>Prise: {infra['prise']}"
        ).add_to(m)

# Ajout des bâtiments
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
        radius=5 if bat['type_batiment'] != 'habitation' else 4,
        color=bat['color'],
        fill=True,
        fill_color=bat['color'],
        fill_opacity=0.9,
        popup=(f"<b>Bâtiment:</b> {bat['id_batiment']}<br>"
               f"<b>Type:</b> {bat['type_batiment']}<br>"
               f"<b>Phase:</b> {int(bat['phase']) if not pd.isna(bat['phase']) else 'N/A'}<br>"
               f"<b>Jour:</b> {int(bat['jour_planifie']) if not pd.isna(bat['jour_planifie']) else 'N/A'}<br>"
               f"<b>Nb maisons:</b> {int(bat['nb_maisons'])}<br>"
               f"<b>Prise:</b> {bat['prise']}")
    ).add_to(m)

# Légende HTML
legend_html = """
<div style="position: fixed; bottom: 30px; left: 30px; background-color: white;
            border:2px solid grey; z-index:9999; font-size:14px; padding:10px;">
<b>Légende - Type de bâtiment</b><br>
<i style="background:#e41a1c;width:10px;height:10px;display:inline-block;"></i> Hôpital (Priorité MAX)<br>
<i style="background:#ff7f00;width:10px;height:10px;display:inline-block;"></i> École (Priorité HAUTE)<br>
<i style="background:#4daf4a;width:10px;height:10px;display:inline-block;"></i> Habitation<br>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))


# -----------------------------
# 9. Export
# -----------------------------
m.save("visualisation_folium_avec_types.html")
print("Carte Folium exportée : visualisation_folium_avec_types.html")

