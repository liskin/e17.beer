import json
import os

import click
import pandas as pd
from dotenv import load_dotenv
from google.maps import places_v1

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
client = places_v1.PlacesClient(client_options={"api_key": API_KEY})


def get_place_data_from_api(place_name):
    """
    Searches Google Places API (New) using the official client library. Returns ID and URL.
    """
    # Specific search overrides for accuracy
    if place_name == "Hackney Church":
        search_name = place_name + " Blackhorse"
    elif place_name == "Borough Wines":
        search_name = place_name + " Taproom"
    else:
        search_name = place_name

    search_query = f"{search_name} E17"

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
        request=request_data, metadata=[("x-goog-fieldmask", "places.id,places.displayName,places.googleMapsUri")]
    )

    places = list(response.places)  # Convert iterator to list

    # If there was no match at all
    if not places:
        raise ValueError(f"No results for '{search_query}'. Please refine the search_name.")

    # Match filtering
    strict_matches = [p for p in places if place_name.lower() in p.display_name.text.lower()]

    # If the search results were messy, but we found exactly one true match, use it.
    if len(strict_matches) == 1:
        return {"place_id": strict_matches[0].id, "url": strict_matches[0].google_maps_uri}

    # If we have more than one STRICT match, ie result is ambiguous
    if len(strict_matches) > 1:
        candidates = [p.display_name.text for p in strict_matches]
        raise ValueError(
            f"Ambiguous result for '{search_query}'. Found {len(strict_matches)} potential matches: "
            f"({', '.join(candidates)}). Please refine the search_name."
        )

    # If we have no STRICT match, but the API found something else
    if len(places) > 0:
        candidates = [p.display_name.text for p in places]
        raise ValueError(
            f"No strict match for '{search_query}'. Google identified {len(strict_matches)} potential match(es): "
            f"({', '.join(candidates)}). Please refine the search_name."
        )


@click.command()
@click.option(
    "-o",
    "--output",
    type=click.File("w"),
    default="E17_BHMplus_data.json",
    help="Output file",
    show_default=True,
)
def main(output):
    sheet_id = "1YhJ2YD-W759uPHqMqIMBR14bq32Vxm0hQ1x0iEFrPB0"
    google_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

    try:
        df = pd.read_csv(google_sheet_url, skiprows=1)  # skiprows=1 ignores the note in the first row
    except Exception as e:
        print(f"Could not read Google Sheet: {e}")
        return

    row_exclusions = ["near, but not beer mile:"]
    days_ordered = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    # Clean DataFrame (filter out rows where the first column is NaN or in row_exclusions)
    clean_df = df[df.iloc[:, 0].notna() & ~df.iloc[:, 0].str.strip().isin(row_exclusions)].copy()

    print(f"Processing {len(clean_df)} places...")

    final_data = {}

    # Iterate over the clean DataFrame
    for _, row in clean_df.iterrows():
        place_name = row.iloc[0]

        try:
            result = get_place_data_from_api(place_name)

            if result:
                # Extract Happy Hours: ordered Sun -> Sat
                happy_hours = [str(row.get(day)) if pd.notna(row.get(day)) else None for day in days_ordered]

                # Map data to the Place ID key
                final_data[result["place_id"]] = {
                    "place_name": place_name,
                    "url": result["url"],
                    "happy_hours": happy_hours,
                }

                print(f"✅ Linked '{place_name}' to ID.")
            else:
                print(f"❌ '{place_name}': No results found.")

        except ValueError as e:
            print(f"⚠️ '{place_name}': {e}")
        except Exception as e:
            print(f"🔥 '{place_name}': Unexpected error: {e}")

    # Save to JSON
    json.dump(final_data, output, indent=4)

    print(f"\nDone! Data linked to IDs saved to {output.name}.")


if __name__ == "__main__":
    main()
