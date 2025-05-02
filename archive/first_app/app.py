import math
import random
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
import io # Needed for reading GeoJSON string with GeoPandas

# Try importing geospatial libraries
try:
    import geopandas as gpd
    from shapely.geometry import Point, Polygon, MultiPolygon
    from shapely.errors import GEOSException
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    print("WARNING: GeoPandas not found. Zone calculation and checking will be disabled.")
    # Define dummy types if import fails to avoid runtime errors later
    Point = lambda x,y: None
    MultiPolygon = type('obj', (object,), {'contains': lambda self, other: False})()


# --- Configuration ---
NUM_BOATS = 100
ZONE_RADIUS_METERS = 5556 # 3 Nautical Miles in Meters
TARGET_CRS = "EPSG:4326" # WGS84 Lat/Lng for Leaflet output
BUFFER_CRS = "EPSG:32633" # UTM Zone 33N suitable for Split area buffering in meters

# --- Simplified Coastline Data (APPROXIMATION - REPLACE WITH REAL DATA) ---
# This is a placeholder demonstrating the structure. Get accurate GeoJSON data for real use.
# Coordinates are [longitude, latitude] as per GeoJSON spec.
SIMPLIFIED_COASTLINE_GEOJSON = {
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {"name": "MainlandSplit"},
      "geometry": {
        "type": "LineString",
        "coordinates": [ # Rough trace Trogir -> Omis
          [16.23, 43.52], [16.30, 43.55], [16.40, 43.54], [16.43, 43.52],
          [16.44, 43.50], [16.47, 43.49], [16.52, 43.48], [16.58, 43.46],
          [16.65, 43.44], [16.70, 43.44]
        ]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": "CiovoIsland"},
      "geometry": {
        "type": "Polygon", # Closed ring for islands
        "coordinates": [[ # Rough trace
          [16.20, 43.48], [16.20, 43.46], [16.25, 43.45], [16.33, 43.45],
          [16.37, 43.48], [16.35, 43.50], [16.28, 43.51], [16.23, 43.51],
          [16.20, 43.48] # Close the ring
        ]]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": "SoltaIsland"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[ # Rough trace
          [16.19, 43.40], [16.19, 43.37], [16.23, 43.34], [16.30, 43.32],
          [16.37, 43.33], [16.38, 43.36], [16.34, 43.40], [16.28, 43.41],
          [16.22, 43.41], [16.19, 43.40] # Close the ring
        ]]
      }
    },
    {
      "type": "Feature",
      "properties": {"name": "BracIsland"},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[ # Rough trace
          [16.42, 43.39], [16.44, 43.33], [16.48, 43.28], [16.60, 43.26],
          [16.75, 43.28], [16.83, 43.33], [16.78, 43.38], [16.65, 43.42],
          [16.55, 43.41], [16.47, 43.40], [16.42, 43.39] # Close the ring
        ]]
      }
    }
  ]
}

# --- Global variables for calculated zone ---
BUFFER_GEOJSON_STRING = None
BUFFER_GEOMETRY_WGS84 = None # Shapely geometry object for checking

# --- Geospatial Calculation Function ---
def calculate_buffer_zone():
    """Loads coastline, calculates buffer, stores result."""
    global BUFFER_GEOJSON_STRING, BUFFER_GEOMETRY_WGS84
    if not GEOPANDAS_AVAILABLE:
        print("GeoPandas not available, skipping buffer calculation.")
        BUFFER_GEOJSON_STRING = '{"type": "FeatureCollection", "features": []}' # Empty GeoJSON
        BUFFER_GEOMETRY_WGS84 = MultiPolygon() # Empty geometry
        return

    try:
        print("Loading coastline data...")
        # Use io.StringIO to read the dictionary as if it were a file
        coastline_gdf = gpd.GeoDataFrame.from_features(SIMPLIFIED_COASTLINE_GEOJSON["features"], crs=TARGET_CRS)

        print(f"Reprojecting coastline to {BUFFER_CRS} for buffering...")
        coastline_gdf_proj = coastline_gdf.to_crs(BUFFER_CRS)

        print(f"Calculating {ZONE_RADIUS_METERS}m buffer...")
        # Calculate buffer, resolution affects smoothness (higher means more points)
        # Use dissolve to merge overlapping buffers into one geometry per original feature type
        buffer_gdf_proj = coastline_gdf_proj.buffer(ZONE_RADIUS_METERS, resolution=16)
        buffer_gdf_proj = gpd.GeoDataFrame(geometry=buffer_gdf_proj).dissolve() # Merge all buffers


        print(f"Reprojecting buffer zone back to {TARGET_CRS}...")
        buffer_gdf_wgs84 = buffer_gdf_proj.to_crs(TARGET_CRS)

        print("Storing buffer zone GeoJSON and Shapely geometry...")
        BUFFER_GEOJSON_STRING = buffer_gdf_wgs84.to_json()

        # Store the combined Shapely geometry for efficient point-in-polygon tests
        # .iloc[0] assumes dissolve resulted in a single MultiPolygon or Polygon
        BUFFER_GEOMETRY_WGS84 = buffer_gdf_wgs84.geometry.iloc[0]

        print("Buffer zone calculation complete.")

    except GEOSException as e:
         print(f"ERROR during geospatial calculation: {e}")
         print("Falling back to empty zone.")
         BUFFER_GEOJSON_STRING = '{"type": "FeatureCollection", "features": []}'
         BUFFER_GEOMETRY_WGS84 = MultiPolygon()
    except Exception as e:
        print(f"Unexpected ERROR during geospatial calculation: {e}")
        print("Falling back to empty zone.")
        BUFFER_GEOJSON_STRING = '{"type": "FeatureCollection", "features": []}'
        BUFFER_GEOMETRY_WGS84 = MultiPolygon()


# --- Point-in-Zone Check (Using Shapely) ---
def is_in_zone(lat, lng):
    """Check if coordinate is within the calculated buffer zone."""
    if not GEOPANDAS_AVAILABLE or BUFFER_GEOMETRY_WGS84 is None:
        return False # Cannot perform check if buffer wasn't calculated

    try:
        # Create a Shapely Point object (lon, lat order)
        point = Point(lng, lat)
        # Check if the point is contained within the buffer geometry
        return BUFFER_GEOMETRY_WGS84.contains(point)
    except Exception as e:
        print(f"Error during point-in-zone check: {e}")
        return False


# --- Initialize Flask App ---
app = Flask(__name__)
CORS(app)

# --- In-Memory Data Storage (Unchanged) ---
boats_data = []
valve_history = []

# --- Sea Area Bounding Boxes (Unchanged) ---
SEA_BOXES = [
    {"min_lat": 43.35, "max_lat": 43.52, "min_lng": 16.05, "max_lng": 16.19},
    {"min_lat": 43.40, "max_lat": 43.52, "min_lng": 16.27, "max_lng": 16.42},
    {"min_lat": 43.28, "max_lat": 43.38, "min_lng": 16.25, "max_lng": 16.45},
    {"min_lat": 43.35, "max_lat": 43.55, "min_lng": 16.50, "max_lng": 16.70},
    {"min_lat": 43.20, "max_lat": 43.30, "min_lng": 16.20, "max_lng": 16.60},
]

# --- Boat Generation (Unchanged, but uses the new is_in_zone) ---
def generate_boats():
    global boats_data; boats_data = []
    boat_names = ["Sea Eagle", "Adriatic Queen", "Dalmatian Dream", "Split Runner", "Island Hopper", "Blue Wave", "Sun Seeker", "Coastal Voyager"]
    attempts = 0; max_attempts = NUM_BOATS * 5
    print("Generating boats...")
    while len(boats_data) < NUM_BOATS and attempts < max_attempts:
        attempts += 1; box = random.choice(SEA_BOXES)
        lat = random.uniform(box["min_lat"], box["max_lat"])
        lng = random.uniform(box["min_lng"], box["max_lng"])

        # Optional: check if generated point accidentally falls *inside* the complex buffer zone
        # This check might be slow if run for every boat generation attempt.
        # if is_in_zone(lat, lng):
        #      continue # Skip points generated inside the zone (optional)

        boats_data.append({
            "id": 201 + len(boats_data),
            "name": f"{random.choice(boat_names)} {random.choice(['I', 'II', 'III', 'IV', 'V', ''])}".strip(),
            "lat": round(lat, 6), "lng": round(lng, 6),
            "valveOpen": random.choice([True, False])
        })
    if len(boats_data) < NUM_BOATS: print(f"Warning: Only generated {len(boats_data)} boats.")
    else: print(f"Successfully generated {len(boats_data)} boats.")


# --- API Endpoints ---
@app.route('/api/boats', methods=['GET'])
def get_boats():
    if not boats_data: generate_boats()
    return jsonify(boats_data)

@app.route('/api/zone-definition', methods=['GET'])
def get_zone_definition():
    """Returns the calculated buffer zone as a GeoJSON string."""
    if BUFFER_GEOJSON_STRING:
        return jsonify({"type": "geojson", "data": BUFFER_GEOJSON_STRING})
    else:
        # Fallback if calculation failed
        return jsonify({"type": "error", "message": "Zone calculation failed on backend."}), 500

@app.route('/api/valve/open', methods=['POST'])
def log_valve_open():
    data = request.get_json()
    if not data or 'boatId' not in data or 'lat' not in data or 'lng' not in data: return jsonify({"error": "Missing data"}), 400
    boat_id = data['boatId']; lat = data['lat']; lng = data['lng']
    boat_found = False
    for boat in boats_data:
        if boat['id'] == boat_id: boat['valveOpen'] = True; boat_found = True; break
    if not boat_found: return jsonify({"error": f"Boat ID {boat_id} not found"}), 404

    # Use the accurate point-in-polygon check
    in_zone = is_in_zone(lat, lng)

    history_entry = {"boatId": boat_id, "timestamp": datetime.now(timezone.utc).isoformat(), "lat": lat, "lng": lng, "inZone": in_zone}
    valve_history.append(history_entry); print(f"Logged valve open: {history_entry}")
    return jsonify({"message": "Valve opening logged", "log": history_entry}), 201

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(sorted(valve_history, key=lambda x: x['timestamp'], reverse=True))

# --- Run ---
if __name__ == '__main__':
    print("Starting backend server...")
    calculate_buffer_zone() # Calculate zone on startup
    if GEOPANDAS_AVAILABLE and not BUFFER_GEOJSON_STRING:
         print("WARNING: Buffer calculation may have failed, zone will be empty.")
    generate_boats()
    app.run(debug=True, port=5000)