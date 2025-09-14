from flask import Flask, render_template, request, jsonify
import shapely.geometry as geom
from geopy.geocoders import Nominatim
import pandas as pd
from pyproj import Geod
import os # <-- 1. IMPORT THE OS MODULE

app = Flask(__name__)

# --- Get the absolute path to the directory where this script is located ---
# This makes file paths reliable whether run locally or on a server.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Runoff coefficient (average for concrete roofs)
RUNOFF_COEFF = 0.8

# --- Load State Rainfall Data ---
def load_state_rainfall(filepath): # The filepath will now be an absolute path
    df = pd.read_csv(filepath)

    # Clean column names
    df.columns = [col.strip().upper() for col in df.columns]

    # Group by state → average annual rainfall across districts
    state_rainfall = df.groupby("STATE_UT_NAME")["ANNUAL"].mean().to_dict()

    return state_rainfall

# --- Load Groundwater Data ---
def load_groundwater_data(filepath): # The filepath will now be an absolute path
    df = pd.read_csv(filepath)
    df.columns = [col.strip().upper() for col in df.columns]
    
    # Create a dictionary for quick lookup by state and district
    groundwater_dict = {}
    for _, row in df.iterrows():
        state = row['STATE'].upper()
        if state not in groundwater_dict:
            groundwater_dict[state] = {}
        groundwater_dict[state][row['DISTRICT'].upper()] = {
            'aquifer': row['AQUIFER'],
            'depth': row['GROUNDWATER_DEPTH_M']
        }
    return groundwater_dict

# --- 2. CONSTRUCT ABSOLUTE PATHS TO YOUR DATA FILES ---
rainfall_csv_path = os.path.join(BASE_DIR, "district wise rainfall normal.csv")
groundwater_csv_path = os.path.join(BASE_DIR, "groundwater_data.csv")


# --- 3. LOAD DATA USING THE NEW, RELIABLE PATHS ---
RAIN_DATA = load_state_rainfall(rainfall_csv_path)
GROUNDWATER_DATA = load_groundwater_data(groundwater_csv_path)


# --- Alias for renamed/split states ---
STATE_ALIAS = {
    "TELANGANA": "ANDHRA PRADESH"
}

# Initialize geolocator
geolocator = Nominatim(user_agent="rainwater_app")

def get_location_details(lat, lng):
    """Return city/state from coordinates using reverse geocoding"""
    try:
        location = geolocator.reverse((lat, lng), language="en")
        if not location:
            return None, None
        address = location.raw.get("address", {})

        # Try to fetch both city and state
        city = address.get("city") or address.get("town") or address.get("village")
        state = address.get("state")
        return city, state
    except Exception as e:
        print("Geocoding error:", e)
        return None, None

def calculate_area_m2(coords):
    """
    Calculates the area of a polygon defined by lat/lng coordinates in square meters.
    Uses a geodesic algorithm to account for Earth's curvature.
    """
    geod = Geod(ellps='WGS84')
    lons = [c[1] for c in coords]
    lats = [c[0] for c in coords]
    area, perimeter = geod.polygon_area_perimeter(lons, lats)
    return abs(area)

# (The rest of your Flask routes remain exactly the same)

@app.route('/map.html')
def map_page():
    return render_template('map.html')

@app.route('/calculate.html')
def calculate_page():
    return render_template('calculate.html')

@app.route("/manual-calculate", methods=["POST"])
def manual_calculate():
    data = request.get_json()

    state = data.get("state")
    district = data.get("district")
    area_m2 = float(data.get("area_m2", 0))
    coeff = float(data.get("coefficient", 0.8))
    dwellers = int(data.get("dwellers", 1))
    open_space = float(data.get("open_space", 0))

    if state and state.upper() in STATE_ALIAS:
        state = STATE_ALIAS[state.upper()]

    rainfall = RAIN_DATA.get(state.upper(), 0) if state else 0
    groundwater = GROUNDWATER_DATA.get(state.upper(), {}).get(district.upper(), {'aquifer': 'N/A', 'depth': 'N/A'})
    water_litres = area_m2 * rainfall * coeff / 1000
    domestic_demand = dwellers * 135 * 365
    sufficiency_percent = (water_litres / domestic_demand * 100) if domestic_demand else 0
    feasible = "Feasible" if area_m2 >= 20 and rainfall > 200 else "Not Feasible"

    return jsonify({
        "state": state,
        "district": district,
        "area_m2": round(area_m2, 2),
        "rainfall_mm_per_year": round(rainfall, 2),
        "water_litres": round(water_litres, 2),
        "dwellers": dwellers,
        "domestic_demand": round(domestic_demand, 2),
        "sufficiency_percent": round(sufficiency_percent, 2),
        "feasible": feasible,
        "aquifer": groundwater['aquifer'],
        "groundwater_depth": groundwater['depth']
    })

@app.route('/report.html')
def report_page():
    return render_template('report.html')

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/index.html")
def home_new():
    return render_template("index.html")

@app.route('/about.html')
def about_page():
    return render_template('about.html')

@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.get_json()
    coords = data["coordinates"]

    area_m2 = calculate_area_m2(coords)
    lat, lng = coords[0]
    city, state = get_location_details(lat, lng)

    rainfall = 0
    groundwater = {'aquifer': 'N/A', 'depth': 'N/A'}

    if state:
        state_key = STATE_ALIAS.get(state.upper(), state.upper())
        rainfall = RAIN_DATA.get(state_key, 0)
        
        if city:
            groundwater = GROUNDWATER_DATA.get(state_key, {}).get(city.upper(), {'aquifer': 'N/A', 'depth': 'N/A'})

    water_litres = area_m2 * rainfall * RUNOFF_COEFF / 1000

    return jsonify({
        "coordinates": coords,
        "city": city,
        "state": state,
        "area_m2": round(area_m2, 2),
        "rainfall_mm_per_year": round(rainfall, 2),
        "water_litres": round(water_litres, 2),
        "aquifer": groundwater['aquifer'],
        "groundwater_depth": groundwater['depth']
    })

if __name__ == "__main__":
    app.run(debug=True)
