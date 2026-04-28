import os
import json
import csv
from dotenv import load_dotenv
import googlemaps

# LOAD API Key
load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
gmaps = googlemaps.Client(key=API_KEY)
print("dir(gmaps):")
print(dir(gmaps))

load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
if not API_KEY:
    raise ValueError("No API Key found! Check your .env file.")


# DEFINE YOUR INPUTS HERE (The Place IDs)
# Location: E17
places_ids = [
    'ChIJKVqfjZgddkgRPsLCEegdp_Y', # Signature Brew
    'ChIJn5s47P0ddkgRs97vifafiI0', # Exale Taproom
    # TODO: add remaining here
]

def fetch_place_data(place_id):
    fields = ['name', 'opening_hours']
    details = gmaps.place(place_id=place_id, fields=fields)

    if details.get('status') != 'OK':
        # This looks for Google's error, if Google is silent uses the alternative error message
        error_msg = details.get('error_message', f'The listing is missing some of the required fields: {", ".join(fields)}.')
        raise ValueError(f"API Error: {details.get('status')} - {error_msg}")

    result = details.get('result', {})
    opening_hours = result.get('opening_hours', {})
    # print(f"result: {result}")
    # if 'opening_hours' in result:
    #     if 'weekday_text' in result['opening_hours']:
    #         print('Opening hours:')
    #         for day in result['opening_hours']['weekday_text']:
    #             print(f'''       {day}''')

    return {
        "name": result.get('name'),
        "weekday_text": opening_hours.get('weekday_text', []),
        "is_open_now": opening_hours.get('open_now'), # For testing color-coding
        "periods": opening_hours.get('periods', [])    # Raw data for color-coding
    }

def save_to_json(data_list):
    with open('places_data.json', 'w') as f:
        json.dump(data_list, f, indent=4)
    print("✅ Saved to places_data.json")

# RUN THE PROCESS
if __name__ == "__main__":
    all_places_info = []

    print(f"Fetching data for {len(places_ids)} places...")
    for bid in places_ids:
        try:
            info = fetch_place_data(bid)
            all_places_info.append(info)
            print(f"Successfully fetched: {info['name']}")
        except Exception as e:
            print(f"Error fetching {bid}: {e}")

    # Save in both formats so you can choose!
    save_to_json(all_places_info)
