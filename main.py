from flask import Flask, render_template, request, jsonify
import shapely.geometry as geom
from geopy.geocoders import Nominatim
import pandas as pd
from pyproj import Geod

app = Flask(__name__)

# Runoff coefficient (average for concrete roofs)
RUNOFF_COEFF = 0.8

# --- Load State Rainfall Data ---
def load_state_rainfall(filepath="district wise rainfall normal.csv"):
    df = pd.read_csv(filepath)

    # Clean column names
    df.columns = [col.strip().upper() for col in df.columns]

    # Group by state → average annual rainfall across districts
    state_rainfall = df.groupby("STATE_UT_NAME")["ANNUAL"].mean().to_dict()

    return state_rainfall

# --- Load Groundwater Data ---
def load_groundwater_data(filepath="groundwater_data.csv"):
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

# Load once at startup
RAIN_DATA = load_state_rainfall("district wise rainfall normal.csv")
GROUNDWATER_DATA = load_groundwater_data("groundwater_data.csv")

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

    # Apply alias mapping
    if state and state.upper() in STATE_ALIAS:
        state = STATE_ALIAS[state.upper()]

    # Fetch rainfall
    rainfall = RAIN_DATA.get(state.upper(), 0) if state else 0

    # Fetch groundwater data
    groundwater = GROUNDWATER_DATA.get(state.upper(), {}).get(district.upper(), {'aquifer': 'N/A', 'depth': 'N/A'})

    # Estimate water harvesting (litres/year)
    water_litres = area_m2 * rainfall * coeff / 1000

    # Domestic demand (135 litres/person/day × dwellers × 365 days)
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

    # Initialize with default values
    rainfall = 0
    groundwater = {'aquifer': 'N/A', 'depth': 'N/A'}

    # Safely check for state and city before using them to prevent crashes
    if state:
        # Apply alias mapping for state name
        state_key = STATE_ALIAS.get(state.upper(), state.upper())
        rainfall = RAIN_DATA.get(state_key, 0)
        
        # Only look for groundwater data if a city was also found
        if city:
            groundwater = GROUNDWATER_DATA.get(state_key, {}).get(city.upper(), {'aquifer': 'N/A', 'depth': 'N/A'})

    # Calculate potential water harvesting
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
