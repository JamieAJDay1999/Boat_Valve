"""
view_mpa_interactive.py
-------------------------------------------------------------------
Render 'caribbean_marine_polygons.shp' on an interactive Leaflet map
and write it to 'caribbean_mpa_map.html'.  Double-click the HTML file
(or the script will try to open it automatically).

Run:
    python view_mpa_interactive.py
"""

import geopandas as gpd
import folium
import webbrowser
import os, sys, json

# ─── Paths ─────────────────────────────────────────────────────────
MPA_PATH      = r"shapefiles/caribbean_MPA_shapefile/caribbean_marine_polygons.shp"
ORIGINAL_CRS  = "EPSG:4326"      # change if your file uses a different CRS
OUTPUT_HTML   = "caribbean_mpa_map.html"

# ─── 1  Read shapefile ─────────────────────────────────────────────
if not os.path.exists(MPA_PATH):
    sys.exit(f"❌  Shapefile not found: {MPA_PATH}")

gdf = gpd.read_file(MPA_PATH)

# Set CRS if missing
if gdf.crs is None:
    print(f"Shapefile has no CRS → assuming {ORIGINAL_CRS}")
    gdf.set_crs(ORIGINAL_CRS, inplace=True)

# Folium expects WGS-84 (EPSG:4326)
if gdf.crs.to_string().upper() != "EPSG:4326":
    print("Re-projecting to EPSG:4326 for web display …")
    gdf = gdf.to_crs("EPSG:4326")

# ─── 2  Build the Leaflet map ──────────────────────────────────────
# Use the centroid of all MPAs to centre the initial view
centroid = gdf.unary_union.centroid
m = folium.Map(location=[centroid.y, centroid.x],
               zoom_start=5,
               tiles="OpenStreetMap")

# Add the polygons
style = {
    "fillOpacity": 0.4,
    "color":       "blue",
    "weight":      1
}

folium.GeoJson(
    json.loads(gdf.to_json()),
    name="Caribbean MPAs",
    style_function=lambda _: style,
    tooltip=folium.GeoJsonTooltip(fields=list(gdf.columns),
                                  aliases=[f"{c} :" for c in gdf.columns],
                                  sticky=False)
).add_to(m)

folium.LayerControl().add_to(m)

# ─── 3  Save & open ────────────────────────────────────────────────
m.save(OUTPUT_HTML)
print(f"✔  Map written to {OUTPUT_HTML}")

try:
    webbrowser.open_new_tab(os.path.abspath(OUTPUT_HTML))
except Exception:
    pass
