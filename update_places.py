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
    #TODO: update to work for 24 hours opened venues
    # (Google returns open for the day of request 0000 truncated, close day in a week 2359 truncated)
    #TODO: fix for open before midnight yesterday and not closed yet at the time of request
    # (Google will split period in two days: truncated in this_day and truncated in this_day-1)

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
    """
    Fetches details from Google Maps API and converts opening periods
    into a list of week-percentage intervals (0.0 to 100.0).
    Splits overnight Saturday-Sunday periods into two separate intervals.
    """
    fields = ['name', 'opening_hours']
    details = gmaps.place(place_id=place_id, fields=fields)

    # Validate API response status; Look for Google's error, if Google is silent use the alternative error message
    if details.get('status') != 'OK':
        error_msg = details.get('error_message', f'Missing some of the required fields: {", ".join(fields)}.')
        raise ValueError(f"API Error: {details.get('status')} - {error_msg}")

    result = details.get('result', {})
    opening_hours = result.get('opening_hours', {})
    raw_periods = opening_hours.get('periods', [])

    percentage_periods = []

    for p in raw_periods:
        # Check for presence of both open and close keys
        # TODO: later update for the case of 24-hour venues, where Google omits 'close' for 24-hour venues,
        #  otherwise both open and close should be present
        if 'open' not in p or 'close' not in p:
            raise KeyError(f"⚠️ Incomplete period data for {result.get('name')}: 'open' or 'close' data is missing.")

        # Convert HHMM time and day index to week percentage
        open_pct = get_week_percentage(p['open']['day'], p['open']['time'])
        close_pct = get_week_percentage(p['close']['day'], p['close']['time'])

        # Wrap-around logic (e.g., Opens Saturday 22:00, Closes Sunday 02:00)
        # If open_pct is 98.0 and close_pct is 1.2, we split it.
        if open_pct > close_pct:
            # Part at the end of week: From Saturday opening to the absolute end of the week (100%)
            percentage_periods.append({
                "open": open_pct,
                "close": 100.0
            })
            # Part at the beginning of week: From the start of the week (0%) to Sunday morning closing
            percentage_periods.append({
                "open": 0.0,
                "close": close_pct
            })
        else:
            # Standard case: Interval exists entirely within the same week cycle
            percentage_periods.append({
                "open": open_pct,
                "close": close_pct
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
