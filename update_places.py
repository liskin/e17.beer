import os
import json
from dotenv import load_dotenv
import googlemaps

# LOAD API Key
load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
if not API_KEY:
    raise ValueError("No API Key found! Check your .env file.")

gmaps = googlemaps.Client(key=API_KEY)

def load_places_from_json(filename):
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        return list(data['place_ids'].values())

    except FileNotFoundError:
        print(f"Error: {filename} not found. Run your discovery script first.")
        return []
    except KeyError:
        print(f"Error: JSON structure is incorrect. Could not find 'place_ids'.")
        return []


def get_week_percentage(day_nmb, time_str):
    """
    Calculates the percentage of the week elapsed.
    Week Start: Sunday (0) at 0000.
    Week End: Saturday (6) at 2359.
    """
    #TODO: update to work for 24 hours opened venues (returns open the day when asked 0000 truncated, close day in a week 2359 truncated)
    #TODO: fix for open before midnight yesterday and not closed yet at the time of request (will have truncated in this day and day in week before today)
    # Input values validation
    if not isinstance(time_str, str) or len(time_str) != 4 or not time_str.isdigit():
        raise ValueError(f"Invalid time format received: '{time_str}'. Expected HHMM string.")

    if not (0 <= day_nmb <= 6):
        raise ValueError(f"Invalid day index: {day_nmb}. Google indices must be 0-6.")

    hours = int(time_str[:2])
    minutes = int(time_str[2:])

    if not (0 <= hours <= 23) or not (0 <= minutes <= 59):
        raise ValueError(f"Time out of range: '{time_str}'.")

    # Percentage calculation
    total_week_minutes = 7 * 24 * 60
    minutes_passed_in_day = (hours * 60) + minutes
    minutes_passed_in_week = (day_nmb * 1440) + minutes_passed_in_day

    percentage = (minutes_passed_in_week / total_week_minutes) * 100

    return round(percentage, 4)


def fetch_place_data(place_id):
    fields = ['name', 'opening_hours']
    details = gmaps.place(place_id=place_id, fields=fields)

    if details.get('status') != 'OK':
        # This looks for Google's error, if Google is silent uses the alternative error message
        error_msg = details.get('error_message', f'Missing some of the required fields: {", ".join(fields)}.')
        raise ValueError(f"API Error: {details.get('status')} - {error_msg}")

    result = details.get('result', {})
    opening_hours = result.get('opening_hours', {})
    raw_periods = opening_hours.get('periods', [])

    percentage_periods = []
    for p in raw_periods:
        if 'open' not in p or 'close' not in p:
            raise KeyError(f"The listing for {result.get('name')} is incomplete: 'open' or 'close' data is missing.")
            # see TODOs in get_week_percentage()

        percentage_periods.append({
            "open": get_week_percentage(p['open']['day'], p['open']['time']),
            "close": get_week_percentage(p['close']['day'], p['close']['time'])
        })

    return {
        "name": result.get('name'),
        "weekday_text": opening_hours.get('weekday_text', []),
        "is_open_now": opening_hours.get('open_now'), # For testing color-coding
        "periods": raw_periods,    # Raw periods data
        "percentage_periods": percentage_periods,    # Periods data as percentage for color-coding
    }

def save_to_json(data_list):
    with open('places_data.json', 'w') as f:
        json.dump(data_list, f, indent=4)
    print("✅ Saved to places_data.json")

# RUN THE PROCESS
if __name__ == "__main__":
    # DEFINE YOUR INPUTS HERE (The Place IDs)
    # Input file structured as a nested dictionary:
    # {
    #   "place_ids": { "Place Name": "Google Place ID", ... },
    #   "map_urls":  { "Place Name": "Google Maps URL", ... }
    # }
    file_name = 'E17_brewery_ids_urls.json'
    places_ids = load_places_from_json(file_name)
    print(places_ids)

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
