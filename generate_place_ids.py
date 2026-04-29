import pandas as pd
import googlemaps
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
gmaps = googlemaps.Client(key=API_KEY)

def get_place_name_and_id(brewery_name):
    """Searches Google for brewery_name + E17. Error if results are ambiguous."""
    search_query = f"{brewery_name} E17"
    URL = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={search_query}&key={API_KEY}"

    payload={}
    headers = {}
    response = requests.request("GET", URL, headers=headers, data=payload)
    data = response.json()
    print("data")
    print(data)

    nmb_candidates = len(data['results'])

    if nmb_candidates == 0:
        print(f"No results for '{search_query}'.")
        return None

    if nmb_candidates > 1:
        candidate_names = [c.get('name') for c in data['results']]
        raise ValueError(
            f"Ambiguous result for '{brewery_name}': Found {nmb_candidates} candidates "
            f"({'\n'.join(candidate_names)}). Please be more specific in the Excel file."
        )

    print("data['results'][0]")
    print(data['results'][0])

    print("output:")
    print({
        "name": data['results'][0]['name'],
        "place_id": data['results'][0]['place_id']
    })

    return {
        "name": data['results'][0]['name'],
        "place_id": data['results'][0]['place_id'],
    }

def run_discovery():
    excel_file = 'BlackhorseBeerMile_HappyHours.xlsx'
    output_file = 'E17_brewery_ids_urls_gname-mapping.json'

    try:
        df = pd.read_excel(excel_file, skiprows=1)  # skiprows=1 ignores the note in the first row
    except Exception as e:
        print(f"Could not read Excel: {e}")
        return

    # Take unique names from the first column
    brewery_names_raw = df.iloc[:, 0].dropna().unique()
    EXCLUSIONS = ['near, but not beer mile:']
    brewery_names = [
        name for name in brewery_names_raw
        if str(name).strip() not in EXCLUSIONS and pd.notna(name)
    ]

    print(f"Processing {len(brewery_names)} breweries...")

    id_map = {}
    url_map = {}
    name_map = {} # This will map "Google Name" -> "Data Place Name (from the excel_file)"
    for brewery_name in brewery_names:

        try:
            result = get_place_name_and_id(brewery_name)

            if result:
                name = result['name']
                pid = result['place_id']

                name_map[name] = brewery_name

                if pid:
                    id_map[brewery_name] = pid
                    print(f"✅ {brewery_name}: name= {name}, Place_ID= {pid}")
                    url_map[brewery_name] = \
                        f"https://www.google.com/maps/search/?api=1&query=google&query_place_id={pid}"
                else:
                    print(f"❌ {brewery_name}: Google found the place, but it has no Place ID.")

            else:
                print(f"❌ {brewery_name}: No results found for this search.")

        except ValueError as e:
            # This catches "Ambiguous result" error specifically
            print(f"⚠️ {brewery_name}: {e}")
        except Exception as e:
            # This catches everything else (Internet down, API key expired, etc.)
            print(f"🔥 {brewery_name}: Unexpected error: {e}")

    final_data = {
        "place_ids": id_map,       # Excel Name -> Place ID
        "map_urls": url_map,       # Excel Name -> URL
        "gname_mapping": name_map   # Google Name -> Excel Name
    }

    # Save to JSON
    with open(output_file, 'w') as f:
        json.dump(final_data, f, indent=4)

    print(f"\nDone! IDs and URLs saved to {output_file}")

if __name__ == "__main__":
    run_discovery()