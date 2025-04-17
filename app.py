import geopandas as gpd
import os
import warnings
import random
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, abort, request
from flask_cors import CORS
import math

# Try importing geospatial libraries
try:
    import geopandas as gpd
    from shapely.geometry import Point, Polygon, MultiPolygon
    from shapely.errors import GEOSException
    GEOPANDAS_AVAILABLE = True
    EMPTY_GEOMETRY = MultiPolygon()
    print("GeoPandas and Shapely loaded successfully.")
except ImportError:
    GEOPANDAS_AVAILABLE = False
    print("\n***************************************************************")
    print("WARNING: GeoPandas not found. Cannot serve map data or perform zone checks.")
    print("Please install it: pip install geopandas")
    print("***************************************************************\n")
    Point = lambda *args: None # type: ignore
    class DummyGeom:
        def contains(self, other): return False
        @property
        def is_empty(self): return True
        def buffer(self, distance): return self
        def union_all(self): return self
    EMPTY_GEOMETRY = DummyGeom() # type: ignore
    MultiPolygon = None # type: ignore

# --- Configuration ---
# Assumes shapefiles are in: shapefiles/<country_code>_shapefiles/<filename>
# Example: shapefiles/uk_shapefiles/CTRY_DEC_2024_UK_BFC_simplified_100m.shp
# !! IMPORTANT: Verify filenames match your saved simplified/buffer files !!
COUNTRY_CONFIG = {
    "uk": {
        # No "subfolder" key needed, structure derived from country code
        "simplified_land_shp": "CTRY_DEC_2024_UK_BFC_simplified_100m.shp",
        "buffer_shp": "CTRY_DEC_2024_UK_BFC_buffer_3nm_simplified_100m.shp",
        "map_center": [54.5, -2.0],
        "map_zoom": 5,
        "target_buffer_crs": "EPSG:27700", # BNG
        "sea_boxes": [
            {"name": "North Sea", "min_lat": 53.0, "max_lat": 58.0, "min_lng": 1.0, "max_lng": 3.0},
            {"name": "English Channel E", "min_lat": 49.5, "max_lat": 50.5, "min_lng": -1.0, "max_lng": 1.0},
            {"name": "English Channel W", "min_lat": 49.0, "max_lat": 50.0, "min_lng": -6.0, "max_lng": -4.0},
            {"name": "Irish Sea", "min_lat": 52.5, "max_lat": 54.5, "min_lng": -5.5, "max_lng": -3.5},
        ]
    },
    "croatia": {
        "simplified_land_shp": "Croatia coastline CSR meters_simplified_1m.shp",
        "buffer_shp": "croatiacoast5556mbuffer.shp",
        "map_center": [44.5, 16.5],
        "map_zoom": 7,
        "target_buffer_crs": "EPSG:32633", # UTM 33N
        "sea_boxes": [
            {"name": "Adriatic N", "min_lat": 44.5, "max_lat": 45.5, "min_lng": 13.5, "max_lng": 14.5},
            {"name": "Adriatic Mid", "min_lat": 43.0, "max_lat": 44.0, "min_lng": 15.0, "max_lng": 16.0},
            {"name": "Adriatic S", "min_lat": 42.0, "max_lat": 43.0, "min_lng": 16.5, "max_lng": 17.5},
        ]
    },
    "svg": {
        # !! Replace these filenames with your actual SVG shapefile names !!
        "simplified_land_shp": "SVGcoast+.shp",
        "buffer_shp": "SVGcoast+1000mbuffer.shp",
        "map_center": [13.2, -61.2],
        "map_zoom": 10,
        "target_buffer_crs": "EPSG:32620", # UTM Zone 20N
        "sea_boxes": [
            {"name": "SVG Main", "min_lat": 13.05, "max_lat": 13.4, "min_lng": -61.3, "max_lng": -61.0},
            {"name": "Grenadines N", "min_lat": 12.8, "max_lat": 13.05, "min_lng": -61.35, "max_lng": -61.1},
            {"name": "Grenadines S", "min_lat": 12.5, "max_lat": 12.8, "min_lng": -61.5, "max_lng": -61.2},
        ]
    }
}

NUM_BOATS_PER_COUNTRY = 50
WGS84_CRS = "EPSG:4326"
SHAPEFILES_BASE_FOLDER = "shapefiles" # Base folder remains 'shapefiles'

# --- In-Memory Data Storage ---
APP_DATA = {
    "boats": {},
    "history": [],
    "buffer_geometries": {},
    "land_geometries": {}
}
NEXT_BOAT_ID = 301

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app)

# --- Helper Functions ---

def get_country_shapefile_folder(country_code):
    """Constructs the path to the specific country's shapefile folder."""
    # Creates path like "shapefiles/uk_shapefiles" or "shapefiles/svg_shapefiles"
    return os.path.join(SHAPEFILES_BASE_FOLDER, f"{country_code}_shapefiles")

def get_buffer_geometry(country_code):
    """Loads the pre-calculated buffer geometry for a country, caches it."""
    if not GEOPANDAS_AVAILABLE: return EMPTY_GEOMETRY
    if country_code not in COUNTRY_CONFIG: return EMPTY_GEOMETRY

    if country_code in APP_DATA["buffer_geometries"]:
        return APP_DATA["buffer_geometries"][country_code]

    print(f"Loading buffer geometry for {country_code}...")
    config = COUNTRY_CONFIG[country_code]
    # --- Path uses helper function ---
    country_folder = get_country_shapefile_folder(country_code)
    buffer_path = os.path.join(country_folder, config['buffer_shp'])

    try:
        if not os.path.exists(buffer_path):
            # Improved error message showing the expected folder structure
            print(f"ERROR: Buffer file not found for {country_code}.")
            print(f"       Expected at: {buffer_path}")
            print(f"       Ensure folder '{country_folder}' exists and contains the file.")
            APP_DATA["buffer_geometries"][country_code] = EMPTY_GEOMETRY
            return EMPTY_GEOMETRY

        gdf_buffer = gpd.read_file(buffer_path)
        if gdf_buffer.crs and gdf_buffer.crs != WGS84_CRS:
            print(f"Reprojecting buffer from {gdf_buffer.crs} to {WGS84_CRS}")
            gdf_buffer = gdf_buffer.to_crs(WGS84_CRS)
        elif not gdf_buffer.crs:
            print(f"Warning: Buffer CRS for {country_code} is undefined. Assuming {WGS84_CRS}.")
            gdf_buffer.set_crs(WGS84_CRS, inplace=True)

        print("Combining buffer geometries...")
        valid_geoms = gdf_buffer[gdf_buffer.geometry.is_valid]
        if not valid_geoms.empty:
             combined_geom = valid_geoms.geometry.buffer(0).union_all()
             print(f"Buffer geometry loaded and combined for {country_code}.")
        else:
             print(f"Warning: No valid geometries found in buffer file for {country_code}.")
             combined_geom = EMPTY_GEOMETRY

        APP_DATA["buffer_geometries"][country_code] = combined_geom
        return combined_geom

    except Exception as e:
        print(f"ERROR loading buffer geometry for {country_code}: {e}")
        APP_DATA["buffer_geometries"][country_code] = EMPTY_GEOMETRY
        return EMPTY_GEOMETRY

def get_land_geometry(country_code):
    """Loads the pre-calculated simplified land geometry for a country, caches it."""
    if not GEOPANDAS_AVAILABLE: return EMPTY_GEOMETRY
    if country_code not in COUNTRY_CONFIG: return EMPTY_GEOMETRY

    if country_code in APP_DATA["land_geometries"]:
        return APP_DATA["land_geometries"][country_code]

    print(f"Loading land geometry for {country_code}...")
    config = COUNTRY_CONFIG[country_code]
    # --- Path uses helper function ---
    country_folder = get_country_shapefile_folder(country_code)
    land_path = os.path.join(country_folder, config['simplified_land_shp'])

    try:
        if not os.path.exists(land_path):
            print(f"ERROR: Land file not found for {country_code}.")
            print(f"       Expected at: {land_path}")
            print(f"       Ensure folder '{country_folder}' exists and contains the file.")
            APP_DATA["land_geometries"][country_code] = EMPTY_GEOMETRY
            return EMPTY_GEOMETRY

        gdf_land = gpd.read_file(land_path)
        if gdf_land.crs and gdf_land.crs != WGS84_CRS:
            print(f"Reprojecting land from {gdf_land.crs} to {WGS84_CRS}")
            gdf_land = gdf_land.to_crs(WGS84_CRS)
        elif not gdf_land.crs:
            print(f"Warning: Land CRS for {country_code} is undefined. Assuming {WGS84_CRS}.")
            gdf_land.set_crs(WGS84_CRS, inplace=True)

        print("Combining land geometries...")
        valid_geoms = gdf_land[gdf_land.geometry.is_valid]
        if not valid_geoms.empty:
            combined_geom = valid_geoms.geometry.buffer(0).union_all()
            print(f"Land geometry loaded and combined for {country_code}.")
        else:
            print(f"Warning: No valid geometries found in land file for {country_code}.")
            combined_geom = EMPTY_GEOMETRY

        APP_DATA["land_geometries"][country_code] = combined_geom
        return combined_geom

    except Exception as e:
        print(f"ERROR loading land geometry for {country_code}: {e}")
        APP_DATA["land_geometries"][country_code] = EMPTY_GEOMETRY
        return EMPTY_GEOMETRY

def is_in_zone(lat, lng, buffer_geometry):
    """Checks if a point (lat, lng) is within the given buffer geometry."""
    if not GEOPANDAS_AVAILABLE or buffer_geometry is None or buffer_geometry.is_empty:
        return False
    try:
        point = Point(lng, lat)
        return buffer_geometry.contains(point)
    except GEOSException as e:
        print(f"Error during point-in-zone check (GEOSException): {e} for point ({lng}, {lat})")
        return False
    except Exception as e:
        print(f"Error during point-in-zone check: {e}")
        return False

def is_on_land(lat, lng, land_geometry):
    """Checks if a point (lat, lng) is within the given land geometry."""
    if not GEOPANDAS_AVAILABLE or land_geometry is None or land_geometry.is_empty:
        return False
    try:
        point = Point(lng, lat)
        return land_geometry.contains(point)
    except GEOSException as e:
        print(f"Error during point-on-land check (GEOSException): {e} for point ({lng}, {lat})")
        return False
    except Exception as e:
        print(f"Error during point-on-land check: {e}")
        return False

def generate_boats(country_code, num_boats, buffer_geometry, land_geometry):
    """Generates boats, aiming for 20% in buffer (water) & 80% outside (water)."""
    global NEXT_BOAT_ID
    if country_code not in COUNTRY_CONFIG: return []
    config = COUNTRY_CONFIG[country_code]
    if 'sea_boxes' not in config or not config['sea_boxes']:
        print(f"Warning: No sea_boxes defined for {country_code}. Cannot generate boats.")
        return []

    buffer_valid = GEOPANDAS_AVAILABLE and buffer_geometry and not buffer_geometry.is_empty
    land_valid = GEOPANDAS_AVAILABLE and land_geometry and not land_geometry.is_empty

    if not buffer_valid:
         print(f"Warning: Cannot perform accurate buffer zone checks for {country_code}.")
    if not land_valid:
         print(f"Warning: Cannot perform land checks for {country_code}.")

    percent_inside = 0.20
    num_inside_target = round(num_boats * percent_inside)
    num_outside_target = num_boats - num_inside_target
    print(f"Targeting {num_inside_target} boats inside zone (water), {num_outside_target} outside zone (water).")

    boats_inside, boats_outside = [], []
    base_names = ["Sea Eagle", "Adriatic Queen", "Dalmatian Dream", "Wave Runner", "Island Hopper", "Blue Fin", "Sun Seeker", "Coastal Voyager", "Neptune's Kiss", "Poseidon's Pride", "Channel Spirit", "Northern Light", "Southern Cross", "Mid-Sea Drifter", "Buffer Skimmer", "Zone Tester", "Caribbean Breeze", "Grenadine Ghost"]

    max_attempts_multiplier = 350
    max_attempts_inside = num_inside_target * max_attempts_multiplier
    max_attempts_outside = num_outside_target * max_attempts_multiplier
    attempts_inside, attempts_outside = 0, 0

    print(f"Generating boats INSIDE zone (water) (target: {num_inside_target})...")
    while len(boats_inside) < num_inside_target and attempts_inside < max_attempts_inside:
        attempts_inside += 1
        try:
            box = random.choice(config['sea_boxes'])
            lat, lng = random.uniform(box["min_lat"], box["max_lat"]), random.uniform(box["min_lng"], box["max_lng"])
        except KeyError as e:
             print(f"ERROR: Invalid sea_box definition: {e}"); continue

        point_is_in_zone = is_in_zone(lat, lng, buffer_geometry) if buffer_valid else False
        point_is_on_land = is_on_land(lat, lng, land_geometry) if land_valid else False

        if point_is_in_zone and not point_is_on_land:
            boats_inside.append({
                "id": NEXT_BOAT_ID, "name": f"{random.choice(base_names)} {random.randint(10, 999)} (InZone)",
                "lat": round(lat, 6), "lng": round(lng, 6), "valveOpen": random.choice([True, False]), "country": country_code })
            NEXT_BOAT_ID += 1

    print(f"Generating boats OUTSIDE zone (water) (target: {num_outside_target})...")
    while len(boats_outside) < num_outside_target and attempts_outside < max_attempts_outside:
        attempts_outside += 1
        try:
             box = random.choice(config['sea_boxes'])
             lat, lng = random.uniform(box["min_lat"], box["max_lat"]), random.uniform(box["min_lng"], box["max_lng"])
        except KeyError as e:
              print(f"ERROR: Invalid sea_box definition: {e}"); continue

        point_is_in_zone = is_in_zone(lat, lng, buffer_geometry) if buffer_valid else False
        point_is_on_land = is_on_land(lat, lng, land_geometry) if land_valid else False

        if not point_is_in_zone and not point_is_on_land:
            boats_outside.append({
                "id": NEXT_BOAT_ID, "name": f"{random.choice(base_names)} {random.randint(10, 999)}",
                "lat": round(lat, 6), "lng": round(lng, 6), "valveOpen": random.choice([True, False]), "country": country_code })
            NEXT_BOAT_ID += 1

    if len(boats_inside) < num_inside_target: print(f"WARNING: Only generated {len(boats_inside)}/{num_inside_target} boats INSIDE zone (water).")
    if len(boats_outside) < num_outside_target: print(f"WARNING: Only generated {len(boats_outside)}/{num_outside_target} boats OUTSIDE zone (water).")

    all_boats = boats_inside + boats_outside
    random.shuffle(all_boats)
    print(f"Generated {len(all_boats)} boats ({len(boats_inside)} in water/zone, {len(boats_outside)} out water/zone) for {country_code}.")
    return all_boats


# --- Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    print("Serving index.html")
    return render_template('index.html')

@app.route('/api/mapdata/<country>')
def get_map_data(country):
    """Serves land, buffer, boats, and map hints for a country."""
    print(f"\nReceived request for /api/mapdata/{country}")
    if not GEOPANDAS_AVAILABLE:
        abort(500, description="Geospatial library (GeoPandas) not available.")

    country_code = country.lower()
    if country_code not in COUNTRY_CONFIG:
        abort(404, description=f"Configuration for country '{country}' not found.")

    config = COUNTRY_CONFIG[country_code]
    # --- Paths use helper ---
    country_folder = get_country_shapefile_folder(country_code)
    simplified_land_path = os.path.join(country_folder, config['simplified_land_shp'])
    buffer_path = os.path.join(country_folder, config['buffer_shp'])

    land_geojson, buffer_geojson, boat_list = None, None, []
    error_messages = []

    # --- Load Land GeoJSON (for display) ---
    try:
        print(f"Loading land file for display: {simplified_land_path}")
        if not os.path.exists(simplified_land_path): raise FileNotFoundError(f"Land file not found: {simplified_land_path}")
        # Rest of loading/reprojection logic...
        gdf_land_display = gpd.read_file(simplified_land_path)
        if gdf_land_display.crs and gdf_land_display.crs != WGS84_CRS:
             print(f"Reprojecting land (display) from {gdf_land_display.crs} to {WGS84_CRS}")
             gdf_land_display = gdf_land_display.to_crs(WGS84_CRS)
        elif not gdf_land_display.crs:
             print(f"Warning: Land (display) CRS for {country_code} is undefined. Assuming {WGS84_CRS}.")
             gdf_land_display.set_crs(WGS84_CRS, inplace=True)
        land_geojson = gdf_land_display.to_json()
        print("Land GeoJSON generated for display.")
    except FileNotFoundError as e:
        msg = f"ERROR: Land file not found: {e}"; print(msg); error_messages.append(msg)
    except Exception as e:
        msg = f"ERROR processing land display file: {e}"; print(msg); error_messages.append(msg)

    # --- Load Buffer GeoJSON (for display) ---
    try:
        print(f"Loading buffer file for display: {buffer_path}")
        if not os.path.exists(buffer_path): raise FileNotFoundError(f"Buffer file not found: {buffer_path}")
        # Rest of loading/reprojection logic...
        gdf_buffer_display = gpd.read_file(buffer_path)
        if gdf_buffer_display.crs and gdf_buffer_display.crs != WGS84_CRS:
             print(f"Reprojecting buffer (display) from {gdf_buffer_display.crs} to {WGS84_CRS}")
             gdf_buffer_display = gdf_buffer_display.to_crs(WGS84_CRS)
        elif not gdf_buffer_display.crs:
             print(f"Warning: Buffer (display) CRS for {country_code} is undefined. Assuming {WGS84_CRS}.")
             gdf_buffer_display.set_crs(WGS84_CRS, inplace=True)
        buffer_geojson = gdf_buffer_display.to_json()
        print("Buffer GeoJSON generated for display.")
    except FileNotFoundError as e:
        msg = f"ERROR: Buffer file not found: {e}"; print(msg); error_messages.append(msg)
    except Exception as e:
        msg = f"ERROR processing buffer display file: {e}"; print(msg); error_messages.append(msg)

    # --- Load Geometries for Backend Checks ---
    buffer_geometry = get_buffer_geometry(country_code)
    land_geometry = get_land_geometry(country_code)

    # --- Generate or retrieve boats ---
    can_generate_safely = (buffer_geometry is not None and not buffer_geometry.is_empty and
                           land_geometry is not None and not land_geometry.is_empty)

    if country_code not in APP_DATA["boats"]:
         if can_generate_safely:
             print(f"Generating boats for {country_code} with land/buffer checks...")
             APP_DATA["boats"][country_code] = generate_boats(
                 country_code, NUM_BOATS_PER_COUNTRY, buffer_geometry, land_geometry
             )
         else:
             warning_msg = f"WARNING: Skipping boat generation for {country_code} due to missing/invalid backend geometry."
             print(warning_msg); error_messages.append(warning_msg)
             APP_DATA["boats"][country_code] = []
    else:
        print(f"Using existing boat data for {country_code}.")

    boat_list = APP_DATA["boats"].get(country_code, [])

    print(f"Returning data for {country}. Boats: {len(boat_list)}. Errors: {error_messages if error_messages else 'None'}")
    return jsonify({
        "land": land_geojson, "buffer": buffer_geojson, "boats": boat_list,
        "center": config['map_center'], "zoom": config['map_zoom'],
        "errors": error_messages if error_messages else None })

@app.route('/api/valve/toggle/<int:boat_id>', methods=['POST'])
def toggle_valve(boat_id):
    """Toggles valve status for a boat and logs opening events."""
    print(f"Received valve toggle request for boat ID: {boat_id}")
    target_boat = None
    country_code = None

    for c_code, boats in APP_DATA["boats"].items():
        for boat in boats:
            if boat['id'] == boat_id:
                target_boat = boat; country_code = c_code; break
        if target_boat: break

    if not target_boat or not country_code:
        abort(404, description=f"Boat ID {boat_id} not found.")

    target_boat['valveOpen'] = not target_boat['valveOpen']
    new_status = target_boat['valveOpen']
    print(f"Boat {boat_id} ({target_boat.get('name', 'N/A')}) valve status changed to: {new_status}")

    if new_status: # Log only on valve OPEN event
        print(f"Logging valve OPEN event for boat {boat_id}...")
        buffer_geometry = get_buffer_geometry(country_code)
        in_zone = False
        if buffer_geometry and not buffer_geometry.is_empty:
             in_zone = is_in_zone(target_boat['lat'], target_boat['lng'], buffer_geometry)
        else:
             print(f"Warning: Log event zone check failed - buffer geometry missing/invalid for {country_code}.")

        history_entry = {
            "boatId": target_boat['id'], "boatName": target_boat.get('name', 'Unknown Name'),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lat": target_boat['lat'], "lng": target_boat['lng'], "inZone": in_zone,
            "status": "Illegal Disposal (Opened in Zone)" if in_zone else "Opened Outside Zone",
            "country": country_code }
        APP_DATA["history"].append(history_entry)
        print(f"Log entry added: {history_entry}")

    return jsonify({ "boatId": target_boat['id'], "valveOpen": target_boat['valveOpen'],
                     "message": "Valve status updated successfully." })

@app.route('/api/history')
def get_history():
    """Returns the global valve opening history log."""
    print(f"Returning history log with {len(APP_DATA['history'])} entries.")
    return jsonify(sorted(APP_DATA["history"], key=lambda x: x.get('timestamp', ''), reverse=True))


# --- Run the App ---
if __name__ == '__main__':
    # --- Create base directories ---
    # Only ensure the base 'shapefiles' folder exists, not the country-specific ones
    os.makedirs(SHAPEFILES_BASE_FOLDER, exist_ok=True)
    print(f"Ensured base shapefile folder exists: '{SHAPEFILES_BASE_FOLDER}'")
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    print("Template and static folders ensured.")

    # --- Pre-load geometries ---
    if GEOPANDAS_AVAILABLE:
         print("\nPre-loading geometries (will report errors if files/folders missing)...")
         # Loop through configured countries and attempt to load data
         for code in COUNTRY_CONFIG.keys():
             print(f"-- Loading for: {code.upper()} --")
             get_buffer_geometry(code) # Load and cache buffer
             get_land_geometry(code)   # Load and cache land
         print("Geometry pre-loading complete.\n")
    else:
         print("\nSkipping geometry pre-loading as GeoPandas is not available.\n")

    print("Flask app starting...")
    # Updated message reflecting the correct expected structure
    print(f"Ensure your shapefiles exist in '{SHAPEFILES_BASE_FOLDER}/<country_code>_shapefiles/'")
    print("e.g., 'shapefiles/uk_shapefiles/CTRY_DEC_2024_UK_BFC_simplified_100m.shp'")
    print("Make sure the folder names (e.g., 'uk_shapefiles', 'svg_shapefiles') are correct.")
    print("Ensure filenames in COUNTRY_CONFIG match exactly what's in those folders.")
    print("CRS will be assumed/reprojected to WGS84 (EPSG:4326) for display and checks.")
    print(f"Access the app in your browser, usually at http://127.0.0.1:5000\n")

    app.run(debug=True, port=5000)