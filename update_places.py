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

def load_places_info_from_json(filename):
    """Loads info dictionary (ids, urls, and gname-mapping)."""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {filename} not found. Run your discovery script first.")
        return {}
    except Exception as e:
        print(f"Error: Could not read JSON: {e}")
        return {}

def get_week_percentage(day_nmb, time_str):
    """Calculates the percentage of the week elapsed (week: Sun 0000 to Sat 2359)."""
    #TODO: update to work for 24 hours opened venues
    # (Google returns open for the day of request 0000 truncated, close day in a week 2359 truncated)
    #TODO: fix for open before midnight yesterday and not closed yet at the time of request
    # (Google will split period in two days: truncated in this_day and truncated in this_day-1)

    # Input values validation
    if not isinstance(time_str, str) or len(time_str) != 4 or not time_str.isdigit():
        raise ValueError(f"Invalid time format received: '{time_str}'. Expected HHMM string.")

    if not (0 <= day_nmb <= 6):
        raise ValueError(f"Invalid day index: {day_nmb}. Google indices must be 0–6.")

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

def fetch_place_data(place_id, gname_mapping=None):
    """
    Fetches details from Google Maps API, maps the official gmaps_name
    back to your preferred place_name (as defined in excel_file), and converts opening periods into a list of week-percentage intervals (0.0 to 100.0).
    """
    fields = ['name', 'opening_hours']
    details = gmaps.place(place_id=place_id, fields=fields)

    # Validate API response status; Look for Google's error, if Google is silent use the alternative error message
    if details.get('status') != 'OK':
        error_msg = details.get('error_message', f'Missing some of the fields: {", ".join(fields)}.')
        raise ValueError(f"API Error: {details.get('status')} - {error_msg}")

    result = details.get('result', {})

    # Map the Google's name (key) to Excel Name (value)
    # If no mapping exists, use the gname as a fallback
    gname = result.get('name')
    if gname_mapping:
        place_name = gname_mapping.get(gname, gname)
    else:
        place_name = gname

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
            # if span from Saturday to Sunday, split into two periods
            percentage_periods.append({"open": open_pct, "close": 100.0})
            percentage_periods.append({"open": 0.0, "close": close_pct})
        else:
            percentage_periods.append({"open": open_pct, "close": close_pct})

    # Convert weekday_text to list of times only (without the name of day, ordered from Sun to Sat)
    days_order = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    weekday_text = opening_hours.get('weekday_text', [])
    week_dict = {}
    for entry in weekday_text:
        if ': ' in entry:
            day_name, times_text = entry.split(': ', 1)
            week_dict[day_name.strip()] = times_text.strip()

    try:
        weekday_times_list = [week_dict[day] for day in days_order]
    except KeyError as e:
        raise ValueError(f"Data Integrity Error: Google provided no opening times for {e}. "
                             "This venue may have incomplete business information.")

    return {
        "place_name": place_name,
        "time_text_sun_to_sat": weekday_times_list,
        "is_open_now": opening_hours.get('open_now'), # For testing color-coding
        "periods": raw_periods,    # Raw periods data
        "percentage_periods": percentage_periods,    # Periods data as percentage for color-coding
    }

def save_to_json(data_list):
    with open('places_data.json', 'w') as f:
        json.dump(data_list, f, indent=4)
    print("\n✅ Saved to places_data.json")


# RUN THE PROCESS
if __name__ == "__main__":
    # DEFINE YOUR INPUTS HERE (The Place IDs)
    # Input file structured as a nested dictionary:
    # {
    #   "place_ids": { "Place Name": "Google Place ID", ... },
    #   "map_urls":  { "Place Name": "Google Maps URL", ... },
    #   "gname_mapping":  { "Google Maps Name": "Place Name", ... }
    # }
    file_name = 'E17_brewery_ids_urls_gname-mapping.json'
    info_dict = load_places_info_from_json(file_name)

    if not info_dict:
        print("No data found to process.")
    else:
        place_ids = info_dict.get('place_ids', {})
        gname_mapping = info_dict.get('gname_mapping', {})

        all_places_outcome = []

        print(f"Fetching data for {len(place_ids)} places...")

        for place_name, bid in place_ids.items():
            try:
                # We pass name_mapping so fetch_place_data can translate the name
                place_outcome = fetch_place_data(bid, gname_mapping)
                all_places_outcome.append(place_outcome)
                print(f"Successfully fetched: {place_outcome['place_name']}")
            except Exception as e:
                print(f"Error fetching {place_name} ({bid}): {e}")

        save_to_json(all_places_outcome)

