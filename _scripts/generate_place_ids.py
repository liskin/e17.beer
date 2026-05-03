import json
import os

import pandas as pd
from dotenv import load_dotenv
from google.maps import places_v1

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
client = places_v1.PlacesClient(client_options={"api_key": API_KEY})


def get_place_name_and_id(brewery_name):
    """Searches Google Places API (New) using the official client library. Returns an error if 	."""
    search_name = brewery_name if brewery_name != "Hackney Church" else brewery_name + " Blackhorse"
    search_query = f"{search_name} E17"

    print(f"search_query: {search_query}")

    # Define request parameters as a clean dictionary
    request_data = {
        "text_query": search_query,
        "location_bias": {
            "circle": {
                "center": {"latitude": 51.5886, "longitude": -0.0118},
                "radius": 5000.0,
            }
        },
    }

    # the dictionary directly to the 'request' argument
    response = client.search_text(
        request=request_data, metadata=[("x-goog-fieldmask", "places.id,places.displayName")]
    )

    places = list(response.places)  # Convert iterator to list

    if not places:
        print(f"No results for '{search_query}'.")
        return None

    # Match filtering
    strict_matches = [p for p in places if brewery_name.lower() in p.display_name.text.lower()]

    # If the search results were messy, but we found exactly one true match, use it.
    if len(strict_matches) == 1:
        return {
            "name": strict_matches[0].display_name.text,
            "place_id": strict_matches[0].id,
        }

    # If we have more than one STRICT match, ie result is ambiguous
    if len(strict_matches) > 1:
        candidate_names = [p.display_name.text for p in strict_matches]
        raise ValueError(
            f"Ambiguous result for '{search_query}': Found {len(strict_matches)} potential matches: "
            f"({', '.join(candidate_names)}). Please refine the search_name."
        )

    # If we have no STRICT match, but the API found something else
    if len(places) > 0:
        candidate_names = [p.display_name.text for p in places]
        raise ValueError(
            f"Ambiguous result for '{search_query}':⚠️ No strict match, but google identified {len(strict_matches)} potential matches: "
            f"({', '.join(candidate_names)}). Please refine the search_name."
        )

    # If there was no match at all
    if len(places) == 0:
        raise ValueError(f"No results for '{search_query}. Please refine the search_name.")

    return None


def run_discovery():
    sheet_id = "1YhJ2YD-W759uPHqMqIMBR14bq32Vxm0hQ1x0iEFrPB0"
    google_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    output_file = "E17_brewery_ids_urls_gname-mapping.json"

    try:
        df = pd.read_csv(
            google_sheet_url, skiprows=1
        )  # skiprows=1 ignores the note in the first row
    except Exception as e:
        print(f"Could not read Google Sheet: {e}")
        return

    # Take unique names from the first column
    brewery_names_raw = df.iloc[:, 0].dropna().unique()
    exclusions = ["near, but not beer mile:"]
    brewery_names = [
        name for name in brewery_names_raw if str(name).strip() not in exclusions and pd.notna(name)
    ]

    print(f"Processing {len(brewery_names)} breweries...")

    id_map = {}
    url_map = {}
    name_map = {}  # This will map "Google Name" -> "Data Place Name (from the spreadsheet)"
    for brewery_name in brewery_names:
        try:
            result = get_place_name_and_id(brewery_name)

            if result:
                name = result["name"]
                pid = result["place_id"]

                name_map[name] = brewery_name

                if pid:
                    id_map[brewery_name] = pid
                    print(f"✅ {brewery_name}: name= {name}, Place_ID= {pid}")
                    url_map[brewery_name] = (
                        f"https://www.google.com/maps/search/?api=1&query={name}&query_place_id={pid}"
                    )
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
        "place_ids": id_map,  # spreadsheet Name -> Place ID
        "map_urls": url_map,  # spreadsheet Name -> URL
        "gname_mapping": name_map,  # Google Name -> spreadsheet Name
    }

    # Save to JSON
    with open(output_file, "w") as f:
        json.dump(final_data, f, indent=4)

    print(f"\nDone! IDs,  URLs, and Google names saved to {output_file}.")


if __name__ == "__main__":
    run_discovery()
