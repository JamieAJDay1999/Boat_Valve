import os
import random
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, abort, request
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Optional geospatial libraries (GeoPandas + Shapely)
# ---------------------------------------------------------------------------
try:
    import geopandas as gpd
    from shapely.geometry import Point, MultiPolygon
    from shapely.errors import GEOSException

    GEOPANDAS_AVAILABLE = True
    EMPTY_GEOMETRY = MultiPolygon()
    print("GeoPandas and Shapely loaded successfully.")
except ImportError:
    GEOPANDAS_AVAILABLE = False
    print("\n***************************************************************")
    print("WARNING: GeoPandas not found. Map display still works but all "
          "zone/land checks will be skipped. "
          "Install with:  pip install geopandas shapely fiona pyproj rtree")
    print("***************************************************************\n")

    # Dummy fall‑backs so code keeps running without GeoPandas
    Point = lambda *args, **kwargs: None               # type: ignore
    class _DummyGeom:                                  # type: ignore
        def contains(self, *_): return False
        @property
        def is_empty(self): return True
        def buffer(self, *_): return self
        def union_all(self): return self
    EMPTY_GEOMETRY = _DummyGeom()                      # type: ignore

# ---------------------------------------------------------------------------
# Configuration – add / edit country blocks here
# ---------------------------------------------------------------------------
COUNTRY_CONFIG = {
    "uk": {
        "simplified_land_shp": "CTRY_DEC_2024_UK_BFC_simplified_100m.shp",
        "buffer_shp":          "CTRY_DEC_2024_UK_BFC_buffer_3nm_simplified_100m.shp",
        "map_center": [54.5, -2.0],
        "map_zoom":   5,
        "sea_boxes": [
            {"name": "North Sea",        "min_lat": 53.0, "max_lat": 58.0, "min_lng":  1.0, "max_lng":  3.0},
            {"name": "English Channel E","min_lat": 49.5, "max_lat": 50.5, "min_lng": -1.0, "max_lng":  1.0},
            {"name": "English Channel W","min_lat": 49.0, "max_lat": 50.0, "min_lng": -6.0, "max_lng": -4.0},
            {"name": "Irish Sea",        "min_lat": 52.5, "max_lat": 54.5, "min_lng": -5.5, "max_lng": -3.5},
        ]
    },
    "croatia": {
        "simplified_land_shp": "Croatia coastline CSR meters_simplified_1m.shp",
        "buffer_shp":          "croatiacoast5556mbuffer.shp",
        "map_center": [44.5, 16.5],
        "map_zoom":   7,
        "sea_boxes": [
            {"name": "Adriatic N",   "min_lat": 44.5, "max_lat": 45.5, "min_lng": 13.5, "max_lng": 14.5},
            {"name": "Adriatic Mid", "min_lat": 43.0, "max_lat": 44.0, "min_lng": 15.0, "max_lng": 16.0},
            {"name": "Adriatic S",   "min_lat": 42.0, "max_lat": 43.0, "min_lng": 16.5, "max_lng": 17.5},
        ]
    },
    "svg": {
        "simplified_land_shp": "SVGcoast+.shp",
        "buffer_shp":          "SVGcoast+1000mbuffer.shp",
        "map_center": [13.2, -61.2],
        "map_zoom":   10,
        "sea_boxes": [
            {"name": "SVG Main",       "min_lat": 13.05, "max_lat": 13.40, "min_lng": -61.30, "max_lng": -61.00},
            {"name": "Grenadines N",   "min_lat": 12.80, "max_lat": 13.05, "min_lng": -61.35, "max_lng": -61.10},
            {"name": "Grenadines S",   "min_lat": 12.50, "max_lat": 12.80, "min_lng": -61.50, "max_lng": -61.20},
        ]
    }
}

SHAPEFILES_BASE_FOLDER = "shapefiles"
WGS84_CRS               = "EPSG:4326"
NUM_BOATS_PER_COUNTRY   = 50

# ---------------------------------------------------------------------------
# In‑memory store
# ---------------------------------------------------------------------------
APP_DATA = {
    "boats":             {},   # {country_code: [boat, …]}
    "history":           [],   # list of valve‑opening log entries
    "buffer_geometries": {},   # {country_code: geometry}
    "land_geometries":   {},   # {country_code: geometry}
}
NEXT_BOAT_ID = 301

# ---------------------------------------------------------------------------
# Flask setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Helper – file paths
# ---------------------------------------------------------------------------
def get_country_folder(code: str) -> str:
    """
    Returns e.g.  "shapefiles/uk_shapefiles"
    """
    return os.path.join(SHAPEFILES_BASE_FOLDER, f"{code}_shapefiles")

# ---------------------------------------------------------------------------
# Helpers – load geometries (cached)
# ---------------------------------------------------------------------------
def _load_geometry(path: str, assume_wgs84_msg: str):
    """
    Internal helper: read a shapefile, re‑project to WGS84, return GeoSeries.
    """
    gdf = gpd.read_file(path)
    if gdf.crs and gdf.crs != WGS84_CRS:
        gdf = gdf.to_crs(WGS84_CRS)
    elif not gdf.crs:
        print(assume_wgs84_msg)
        gdf.set_crs(WGS84_CRS, inplace=True)
    return gdf[gdf.geometry.is_valid].geometry.buffer(0).union_all()

def get_buffer_geometry(code: str):
    if not GEOPANDAS_AVAILABLE:           return EMPTY_GEOMETRY
    if code in APP_DATA["buffer_geometries"]:
        return APP_DATA["buffer_geometries"][code]

    config     = COUNTRY_CONFIG[code]
    country_fp = get_country_folder(code)
    shp_path   = os.path.join(country_fp, config["buffer_shp"])
    if not os.path.exists(shp_path):
        print(f"[WARN] Buffer file not found: {shp_path}")
        APP_DATA["buffer_geometries"][code] = EMPTY_GEOMETRY
        return EMPTY_GEOMETRY

    geom = _load_geometry(
        shp_path, f"[WARN] Buffer CRS undefined for {code}. Assuming WGS84."
    )
    APP_DATA["buffer_geometries"][code] = geom
    return geom

def get_land_geometry(code: str):
    if not GEOPANDAS_AVAILABLE:           return EMPTY_GEOMETRY
    if code in APP_DATA["land_geometries"]:
        return APP_DATA["land_geometries"][code]

    config     = COUNTRY_CONFIG[code]
    country_fp = get_country_folder(code)
    shp_path   = os.path.join(country_fp, config["simplified_land_shp"])
    if not os.path.exists(shp_path):
        print(f"[WARN] Land file not found: {shp_path}")
        APP_DATA["land_geometries"][code] = EMPTY_GEOMETRY
        return EMPTY_GEOMETRY

    geom = _load_geometry(
        shp_path, f"[WARN] Land CRS undefined for {code}. Assuming WGS84."
    )
    APP_DATA["land_geometries"][code] = geom
    return geom

# ---------------------------------------------------------------------------
# Point‑in‑polygon helpers
# ---------------------------------------------------------------------------
def is_in_zone(lat, lng, buf_geom):
    if not GEOPANDAS_AVAILABLE or buf_geom.is_empty:
        return False
    try:            return buf_geom.contains(Point(lng, lat))
    except Exception as e:
        print(f"[ERR] zone check: {e}")
        return False

def is_on_land(lat, lng, land_geom):
    if not GEOPANDAS_AVAILABLE or land_geom.is_empty:
        return False
    try:            return land_geom.contains(Point(lng, lat))
    except Exception as e:
        print(f"[ERR] land check: {e}")
        return False

# ---------------------------------------------------------------------------
# Boat generator  – **valve closed if inside buffer**
# ---------------------------------------------------------------------------
def generate_boats(code, n, buf_geom, land_geom):
    global NEXT_BOAT_ID
    cfg = COUNTRY_CONFIG[code]

    inside_target  = round(n * 0.20)
    outside_target = n - inside_target
    boats_in, boats_out = [], []

    # shorten lookups
    buf_valid  = GEOPANDAS_AVAILABLE and not buf_geom.is_empty
    land_valid = GEOPANDAS_AVAILABLE and not land_geom.is_empty

    base_names = [
        "Sea Eagle","Adriatic Queen","Dalmatian Dream","Wave Runner","Island Hopper",
        "Blue Fin","Sun Seeker","Coastal Voyager","Neptune's Kiss","Poseidon's Pride",
        "Channel Spirit","Northern Light","Southern Cross","Mid‑Sea Drifter",
        "Buffer Skimmer","Zone Tester","Caribbean Breeze","Grenadine Ghost"
    ]

    # ---- create inside‑buffer boats (valve CLOSED) -------------------------
    attempts = 0
    while len(boats_in) < inside_target and attempts < inside_target * 500:
        attempts += 1
        box = random.choice(cfg["sea_boxes"])
        lat = random.uniform(box["min_lat"], box["max_lat"])
        lng = random.uniform(box["min_lng"], box["max_lng"])

        if buf_valid  and not is_in_zone(lat, lng, buf_geom):  continue
        if land_valid and     is_on_land(lat, lng, land_geom): continue

        boats_in.append({
            "id":        NEXT_BOAT_ID,
            "name":      f"{random.choice(base_names)} {random.randint(10,999)} (InZone)",
            "lat":       round(lat, 6),
            "lng":       round(lng, 6),
            "valveOpen": False,           # <-- closed in buffer
            "country":   code
        })
        NEXT_BOAT_ID += 1

    # ---- create outside‑buffer boats (valve random) ------------------------
    attempts = 0
    while len(boats_out) < outside_target and attempts < outside_target * 500:
        attempts += 1
        box = random.choice(cfg["sea_boxes"])
        lat = random.uniform(box["min_lat"], box["max_lat"])
        lng = random.uniform(box["min_lng"], box["max_lng"])

        if buf_valid  and is_in_zone(lat, lng, buf_geom):   continue
        if land_valid and is_on_land(lat, lng, land_geom):  continue

        boats_out.append({
            "id":        NEXT_BOAT_ID,
            "name":      f"{random.choice(base_names)} {random.randint(10,999)}",
            "lat":       round(lat, 6),
            "lng":       round(lng, 6),
            "valveOpen": random.choice([True, False]),
            "country":   code
        })
        NEXT_BOAT_ID += 1

    boats = boats_in + boats_out
    random.shuffle(boats)
    return boats

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/mapdata/<country>')
def get_map_data(country):
    """
    Returns land polygons, buffer polygons, boat list, map defaults and any
    server‑side warnings for <country>.
    """
    code = country.lower()
    if code not in COUNTRY_CONFIG:
        abort(404, description=f"Unknown country '{country}'")

    # ---- load geometries ---------------------------------------------------
    buffer_geom = get_buffer_geometry(code)
    land_geom   = get_land_geometry(code)

    # ---- prepare GeoJSON for map display (safe even without GeoPandas) ----
    land_geojson = buffer_geojson = None
    errors = []

    if GEOPANDAS_AVAILABLE and not land_geom.is_empty:
        land_geojson = gpd.GeoSeries([land_geom], crs=WGS84_CRS).to_json()
    elif GEOPANDAS_AVAILABLE:
        errors.append("Land geometry missing or invalid.")

    if GEOPANDAS_AVAILABLE and not buffer_geom.is_empty:
        buffer_geojson = gpd.GeoSeries([buffer_geom], crs=WGS84_CRS).to_json()
    elif GEOPANDAS_AVAILABLE:
        errors.append("Buffer geometry missing or invalid.")

    # ---- make / cache boats -----------------------------------------------
    if code not in APP_DATA["boats"]:
        if not buffer_geom.is_empty and not land_geom.is_empty:
            APP_DATA["boats"][code] = generate_boats(
                code, NUM_BOATS_PER_COUNTRY, buffer_geom, land_geom
            )
        else:
            APP_DATA["boats"][code] = []
            errors.append("Boat generation skipped – geometry unavailable.")

    return jsonify({
        "land":   land_geojson,
        "buffer": buffer_geojson,
        "boats":  APP_DATA["boats"][code],
        "center": COUNTRY_CONFIG[code]["map_center"],
        "zoom":   COUNTRY_CONFIG[code]["map_zoom"],
        "errors": errors or None
    })


@app.route('/api/valve/toggle/<int:boat_id>', methods=['POST'])
def toggle_valve(boat_id):
    """Toggle a boat’s valve and add a history entry when it opens."""
    target = None
    code   = None
    for c, boats in APP_DATA["boats"].items():
        for b in boats:
            if b["id"] == boat_id:
                target, code = b, c
                break
        if target:
            break
    if not target:
        abort(404, description=f"Boat {boat_id} not found.")

    target["valveOpen"] = not target["valveOpen"]

    # log only when valve just opened
    if target["valveOpen"]:
        in_zone = is_in_zone(target["lat"], target["lng"],
                             get_buffer_geometry(code))
        APP_DATA["history"].append({
            "boatId":   target["id"],
            "boatName": target["name"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lat":      target["lat"],
            "lng":      target["lng"],
            "inZone":   in_zone,
            "status":   ("Illegal Disposal (Opened in Zone)"
                         if in_zone else "Opened Outside Zone"),
            "country":  code
        })

    return jsonify({
        "boatId":    target["id"],
        "valveOpen": target["valveOpen"],
        "message":   "Valve status updated."
    })


@app.route('/api/history')
def get_history():
    """Return history entries newest‑first."""
    return jsonify(sorted(APP_DATA["history"],
                          key=lambda x: x["timestamp"], reverse=True))


# ---------------------------------------------------------------------------
# NEW – randomise all boats for a country
# ---------------------------------------------------------------------------
@app.route('/api/boats/randomise/<country>', methods=['POST'])
def randomise_boats(country):
    code = country.lower()
    if code not in COUNTRY_CONFIG:
        abort(404, description=f"Unknown country '{country}'")

    buf = get_buffer_geometry(code)
    land = get_land_geometry(code)
    if buf.is_empty or land.is_empty:
        abort(500, description="Required geometries missing/invalid.")

    APP_DATA["boats"][code] = generate_boats(code, NUM_BOATS_PER_COUNTRY, buf, land)
    return jsonify({
        "boats":   APP_DATA["boats"][code],
        "message": "Boat locations randomised."
    })

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    # Ensure folders exist
    os.makedirs(SHAPEFILES_BASE_FOLDER, exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static',    exist_ok=True)

    # Pre‑load geometries (optional but speeds first request)
    if GEOPANDAS_AVAILABLE:
        for c in COUNTRY_CONFIG:
            get_buffer_geometry(c)
            get_land_geometry(c)

    print("Starting Flask on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
