import pandas as pd
import geopandas as gpd
import numpy as np
import folium
from shapely.geometry import Point, LineString, MultiLineString, MultiPoint

# -------------------------------------------------
# 1. Chargement et normalisation des données
# -------------------------------------------------
batiments = gpd.read_file("batiments.shp")
infras = gpd.read_file("infrastructures.shp")
reseau = pd.read_excel("reseau_en_arbre.xlsx")
batiments.rename(columns={"id_bat": "id_batiment"}, inplace=True)

bat_info = pd.read_csv("batiments.csv")
assert {'id_batiment', 'type_batiment', 'nb_maisons'}.issubset(bat_info.columns)

def normalize_type_bat(typ):
    if pd.isna(typ): return 'habitation'
    typ = typ.lower()
    typ = typ.replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a')
    typ = typ.replace('ù', 'u').replace('ô', 'o').replace('î', 'i').replace('û', 'u')
    typ = typ.replace('hôpital', 'hopital').replace('école', 'ecole')
    if typ not in ['hopital', 'ecole', 'habitation']:
        return 'habitation'
    return typ

bat_info['type_batiment'] = bat_info['type_batiment'].apply(normalize_type_bat)
bat_info_merged = bat_info.rename(columns={'nb_maisons': 'nb_maisons_csv'})
batiments = batiments.merge(bat_info_merged, on='id_batiment', how='left')
batiments['type_batiment'] = batiments['type_batiment'].fillna('habitation')
batiments['nb_maisons_csv'] = batiments['nb_maisons_csv'].fillna(1)

infra_types = pd.read_csv("infra.csv")  # id_infra,type_infra
infra_costs = {
    'aerien':   {'cout': 500,  'duree': 2,  'color': '#007fff'},
    'semi-aerien': {'cout': 750,  'duree': 4,  'color': '#996600'},
    'fourreau': {'cout': 900,  'duree': 5,  'color': '#ed1e79'}
}
for col in ["cout", "duree", "color"]:
    infra_types[col] = infra_types['type_infra'].map(lambda x: infra_costs.get(x, {}).get(col, None))

infras = infras.merge(infra_types, left_on="infra_id", right_on="id_infra", how="left")
infras['cout'] = infras['cout'].fillna(500)
infras['duree'] = infras['duree'].fillna(2)
infras['color'] = infras['color'].fillna("#cccccc")

# -------------------------------------------------
# 2. Harmonisation des projections
# -------------------------------------------------
if batiments.crs is None:
    batiments.set_crs(epsg=4326, inplace=True)
if infras.crs is None:
    infras.set_crs(epsg=4326, inplace=True)
batiments = batiments.to_crs(epsg=4326)
infras = infras.to_crs(epsg=4326)

# -------------------------------------------------
# 3. Fusion reseau/batiments et normalisation
# -------------------------------------------------
reseau = reseau.merge(
    batiments[["id_batiment", "type_batiment", "nb_maisons_csv", "geometry"]],
    on="id_batiment", how="left"
)
if 'nb_maisons' in reseau.columns:
    reseau['nb_maisons'] = reseau['nb_maisons_csv'].fillna(reseau['nb_maisons']).fillna(1)
else:
    reseau['nb_maisons'] = reseau['nb_maisons_csv'].fillna(1)
reseau = reseau.drop(columns=['nb_maisons_csv'])
reseau['type_batiment'] = reseau['type_batiment'].apply(normalize_type_bat)
reseau["difficulte_bat"] = reseau.get("difficulte_bat", 1)
reseau["difficulte_infra"] = reseau.get("difficulte_infra", 1)
reseau["infra_type"] = reseau.get("infra_type", "infra_intacte")
reseau["longueur"] = reseau["longueur"].fillna(1)
reseau["nb_batiments"] = reseau.groupby("infra_id")["id_batiment"].transform("count")
reseau["temps_reparation"] = reseau.get("temps_reparation", 1.0)
reseau["prise"] = reseau["nb_batiments"] * reseau["nb_maisons"]

priorite_map = {'hopital': 3.0, 'ecole': 2.0, 'habitation': 1.0}
reseau['poids_priorite'] = reseau['type_batiment'].map(priorite_map).fillna(1.0)

# -------------------------------------------------
# 4. Score, phase, planning et GROUPBY pour infras_plot incluant STATUT
# -------------------------------------------------
def normaliser(col):
    return (col - col.min()) / (col.max() - col.min()) if col.max() != col.min() else 1

for col in ["nb_batiments", "nb_maisons", "longueur", "difficulte_infra", "difficulte_bat", "temps_reparation"]:
    reseau[f"norm_{col}"] = normaliser(reseau[col])

reseau["score_phase"] = (
    reseau["prise"] * 0.5
    + (1 - reseau["norm_temps_reparation"]) * 0.3
    + reseau["poids_priorite"] * 0.2
)

def attribuer_phase(row):
    if row['infra_type'] == "infra_intacte":
        return 0
    elif row['infra_type'] == "a_remplacer":
        if row['type_batiment'] == 'hopital': return 1
        if row['type_batiment'] == 'ecole': return 1
        seuil = reseau[reseau['infra_type'] == "a_remplacer"]["score_phase"].quantile(0.5)
        return 1 if row["score_phase"] >= seuil else 2
    else:
        return 2

reseau["phase"] = reseau.apply(attribuer_phase, axis=1)

# -- Planification temporelle --
max_jour = 30
phase2 = reseau[reseau['phase'] == 2].copy().sort_values("score_phase", ascending=False)
phase2["jour_planifie"] = np.linspace(2, max_jour, len(phase2))
reseau.loc[phase2.index, "jour_planifie"] = phase2["jour_planifie"]
reseau.loc[reseau['phase'] == 1, "jour_planifie"] = 1
reseau.loc[reseau['phase'] == 0, "jour_planifie"] = 0
reseau["jour_planifie"] = reseau["jour_planifie"].fillna(max_jour)

# -- GROUPBY incluant infra_type (statut) --
infra_phase = reseau.groupby('infra_id')[['phase','prise','jour_planifie','type_batiment','infra_type']].agg({
    'phase': 'max',
    'prise': 'max',
    'jour_planifie': 'max',
    'type_batiment': lambda x: x.mode()[0] if not x.mode().empty else 'habitation',
    'infra_type': lambda x: x.mode()[0] if not x.mode().empty else 'infra_intacte'
}).reset_index()

infras_plot = infras.merge(infra_phase, on='infra_id', how='left')
infras_plot['type_batiment'] = infras_plot['type_batiment'].fillna('habitation')
infras_plot['color_bat'] = infras_plot['type_batiment'].map({
    'hopital': '#e41a1c', 'ecole': '#ff7f00', 'habitation': '#4daf4a'
}).fillna("#cccccc")

# -------------------------------------------------
# 5. Carte Folium infrastructure AVEC statut infra
# -------------------------------------------------
center = [batiments.geometry.y.mean(), batiments.geometry.x.mean()]
m = folium.Map(location=center, zoom_start=15, tiles="CartoDB positron")

for _, infra in infras_plot.iterrows():
    geom = infra.geometry
    if geom is None: continue
    color_infra = infra['color']
    infra_type = infra.get('type_infra', '')
    statut_infra = infra.get('infra_type', '')
    cout = infra['cout']
    duree = infra['duree']
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
            color=color_infra,
            weight=4,
            opacity=0.9,
            tooltip=f"<b>Infra:</b> {infra['infra_id']}<br>"
                    f"Type bat: {infra['type_batiment']}<br>"
                    f"Type infra: {infra_type}<br>"
                    f"<b>Statut infra:</b> {statut_infra}<br>"
                    f"Prix/m: {cout}€<br>"
                    f"Durée/m: {duree}h<br>"
                    f"Phase: {infra['phase']}<br>"
                    f"Jour: {infra['jour_planifie']}<br>"
                    f"Prise: {infra['prise']}"
        ).add_to(m)

# Légende points batiments
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

# Légende lignes infrastructures
legend_infra_html = """
<div style="position: fixed; bottom: 30px; left: 310px; background-color: white;
            border:2px solid grey; z-index:9999; font-size:14px; padding:10px;">
<b>Légende - Type d'infrastructure</b><br>
<i style="background:#007fff;width:15px;height:4px;display:inline-block;"></i> Aérien<br>
<i style="background:#996600;width:15px;height:4px;display:inline-block;"></i> Semi-aérien<br>
<i style="background:#ed1e79;width:15px;height:4px;display:inline-block;"></i> Fourreau<br>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_infra_html))

# -------------------------------------------------
# 6. Export et stats
# -------------------------------------------------
m.save("visualisation_folium_types_infra_statut.html")
print("Carte Folium exportée : visualisation_folium_types_infra_statut.html")
print("\nStatistiques de priorisation (batiments / phase):")
print(reseau.groupby(['type_batiment', 'phase']).size())
