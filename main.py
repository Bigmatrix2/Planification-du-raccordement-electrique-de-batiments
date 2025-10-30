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

# Chargement CSV avec nettoyage des noms de colonnes
bat_info = pd.read_csv("batiments.csv")
bat_info.columns = [col.strip() for col in bat_info.columns]  # enlever espaces cachés

print("=" * 60)
print("DIAGNOSTIC - Contenu du CSV batiments.csv:")
print(bat_info.head(20))
print(f"\nNombre total de bâtiments dans le CSV: {len(bat_info)}")
print("\nRépartition des types de bâtiments:")
print(bat_info['type_batiment'].value_counts())
print("=" * 60)

# Vérif colonnes attendues
required_cols = {'id_batiment', 'type_batiment', 'nb_maisons'}
assert required_cols.issubset(bat_info.columns), \
    f"Le CSV doit contenir obligatoirement {required_cols}"

print("\nColonnes shapefile avant fusion:", batiments.columns.tolist())

# Fusion batiments avec infos CSV
batiments = batiments.merge(
    bat_info[['id_batiment', 'type_batiment', 'nb_maisons']],
    on='id_batiment',
    how='left',
    suffixes=('', '_csv')
)

# Gérer suffixe si nb_maisons existait déjà
if 'nb_maisons_csv' in batiments.columns:
    batiments['nb_maisons'] = batiments['nb_maisons_csv']
    batiments = batiments.drop(columns=['nb_maisons_csv'])

# S'assurer que la colonne existe et valeurs manquantes remplacées
if 'nb_maisons' not in batiments.columns:
    batiments['nb_maisons'] = 1
else:
    batiments['nb_maisons'] = batiments['nb_maisons'].fillna(1)

# Valeurs par défaut pour type_batiment
batiments['type_batiment'] = batiments['type_batiment'].fillna('habitation')

print("Colonnes shapefile après fusion:", batiments.columns.tolist())
print("\nExemple données fusionnées:")
print(batiments[['id_batiment', 'type_batiment', 'nb_maisons']].head(20))
print("\nRépartition des types après fusion:")
print(batiments['type_batiment'].value_counts())
print("=" * 60)


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
# Préparer la liste des colonnes à fusionner, s'assurer de la présence de nb_maisons
to_merge = ["id_batiment", "type_batiment", "geometry"]
if 'nb_maisons' in batiments.columns:
    to_merge.append('nb_maisons')
else:
    batiments['nb_maisons'] = 1
    to_merge.append('nb_maisons')

reseau = reseau.merge(
    batiments[to_merge],
    on="id_batiment",
    how="left"
)

# Valeurs par défaut pour colonnes manquantes
reseau['type_batiment'] = reseau['type_batiment'].fillna('habitation')
reseau['nb_maisons'] = reseau['nb_maisons'].fillna(1)
reseau["difficulte_bat"] = reseau.get("difficulte_bat", 1)
reseau["difficulte_infra"] = reseau.get("difficulte_infra", 1)
reseau["infra_type"] = reseau.get("infra_type", "infra_intacte")
reseau["longueur"] = reseau["longueur"].fillna(1)
reseau["nb_batiments"] = reseau.groupby("infra_id")["id_batiment"].transform("count")
reseau["temps_reparation"] = reseau.get("temps_reparation", 1.0)
reseau["prise"] = reseau["nb_batiments"] * reseau["nb_maisons"]

print("\nAprès fusion avec reseau:")
print(reseau[['id_batiment', 'type_batiment', 'nb_maisons', 'prise']].head(20))
print("\nRépartition des types dans reseau:")
print(reseau['type_batiment'].value_counts())
print("=" * 60)

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
            return 1 if row['score_phase'] >= reseau[reseau['infra_type']=="a_remplacer"]["score_phase"].quantile(0.5) else 2
    else:
        return 2

reseau["phase"] = reseau.apply(attribuer_phase, axis=1)

print("\nRépartition phase par type:")
print(reseau.groupby(['type_batiment', 'phase']).size())
print("=" * 60)

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
infra_phase = reseau.groupby('infra_id')[['phase','prise','jour_planifie','type_batiment']].agg({
    'phase': 'max',
    'prise': 'max',
    'jour_planifie': 'max',
    'type_batiment': lambda x: x.mode()[0] if not x.mode().empty else 'habitation'  # type dominant
}).reset_index()

infras_plot = infras.merge(infra_phase, on='infra_id', how='left')
infras_plot['type_batiment'] = infras_plot['type_batiment'].fillna('habitation')
infras_plot['color'] = infras_plot['type_batiment'].map(bat_colors).fillna("#cccccc")

print("\nRépartition des types dans infras_plot:")
print(infras_plot['type_batiment'].value_counts())
print("=" * 60)

# Fusion pour bat_plot
bat_plot = batiments.merge(
    reseau[['id_batiment','infra_id','phase','prise','jour_planifie']], 
    on='id_batiment', 
    how='left'
)

# Garder type_batiment et nb_maisons de batiments (déjà présents)
bat_plot['type_batiment'] = bat_plot['type_batiment'].fillna('habitation')
bat_plot['nb_maisons'] = bat_plot['nb_maisons'].fillna(1)
bat_plot['color'] = bat_plot['type_batiment'].map(bat_colors).fillna("#cccccc")

print("\nRépartition des types dans bat_plot:")
print(bat_plot['type_batiment'].value_counts())
print("\nRépartition des couleurs dans bat_plot:")
print(bat_plot['color'].value_counts())
print("=" * 60)

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
            color=infra['color'],
            weight=4,
            opacity=0.9,
            tooltip=f"Infrastructure {infra['infra_id']}<br>Type: {infra['type_batiment']}<br>Phase: {infra['phase']}<br>Jour: {infra['jour_planifie']:.0f}<br>Prise: {infra['prise']}"
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

    # Taille et style selon le type
    if bat['type_batiment'] == 'hopital':
        radius = 8
        weight = 2
    elif bat['type_batiment'] == 'ecole':
        radius = 6
        weight = 2
    else:
        radius = 4
        weight = 1

    folium.CircleMarker(
        location=coords,
        radius=radius,
        color=bat['color'],
        weight=weight,
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

# ---- Légende HTML ----
legend_html = """
<div style="position: fixed; bottom: 30px; left: 30px; background-color: white;
            border:2px solid grey; z-index:9999; font-size:14px; padding:10px;">
<b>Légende - Type de bâtiment</b><br>
<i style="background:#e41a1c;width:15px;height:15px;display:inline-block;border-radius:50%;"></i> Hôpital (Priorité MAX)<br>
<i style="background:#ff7f00;width:15px;height:15px;display:inline-block;border-radius:50%;"></i> École (Priorité HAUTE)<br>
<i style="background:#4daf4a;width:15px;height:15px;display:inline-block;border-radius:50%;"></i> Habitation<br>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# -----------------------------
# 9. Export
# -----------------------------
m.save("visualisation_folium_avec_types.html")
print("\n✅ Carte Folium exportée : visualisation_folium_avec_types.html")
print(f"\nStatistiques finales de priorisation:")
print(reseau.groupby(['type_batiment', 'phase']).size())
