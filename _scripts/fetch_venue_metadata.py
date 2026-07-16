import json
import logging
import pprint
import textwrap

import click
import diskcache  # type: ignore [import-untyped]
import pandas as pd
from google.maps.places_v1 import PlacesClient, SearchTextRequest
from google.maps.places_v1.types import Circle
from google.type.latlng_pb2 import LatLng  # type: ignore [import-untyped]
from tqdm import tqdm
from tqdm.contrib.logging import tqdm_logging_redirect

from utils import click_option_verbosity, get_places_client, logging_context, setup_logging


def get_place_data_from_api(client: PlacesClient, place_name: str) -> dict:
    """
    Searches Google Places API (New) using the official client library. Returns ID and URL.
    """
    # Specific search overrides for accuracy (TODO: move to the spreadsheet)
    search_name = place_name
    search_type = None

    if place_name == "Hackney Church":
        search_name = place_name + " Blackhorse"
    elif place_name == "Borough Wines":
        search_name = place_name + " Taproom"

    if place_name == "Ferry Boat Inn":
        search_type = "pub"

    if place_name == "Pressure Drop":
        search_query = f"{search_name} N17"
    else:
        search_query = f"{search_name} E17"

    search_kwargs: dict = {}
    if search_type:
        search_kwargs |= {
            "included_type": search_type,
        }

    request = SearchTextRequest(
        text_query=search_query,
        location_bias=SearchTextRequest.LocationBias(
            circle=Circle(
                center=LatLng(latitude=51.587, longitude=-0.041),
                radius=5000.0,
            ),
        ),
        **search_kwargs,
    )
    response = client.search_text(
        request=request,
        metadata=[("x-goog-fieldmask", "places.id,places.displayName,places.googleMapsUri")],
    )

    places = list(response.places)  # Convert iterator to list

    # If there was no match at all
    if not places:
        raise RuntimeError(f"No results for '{search_query}'. Please refine the search_name.")

    # Match filtering
    strict_matches = [p for p in places if place_name.lower() in p.display_name.text.lower()]

    logging.debug(
        "get_place_data_from_api('%s'): places=\n%s",
        place_name,
        textwrap.indent(pprint.pformat(places, indent=2), "  "),
    )
    logging.debug(
        "get_place_data_from_api('%s'): strict_matches=\n%s",
        place_name,
        textwrap.indent(pprint.pformat(strict_matches, indent=2), "  "),
    )

    # If the search results were messy, but we found exactly one true match, use it.
    if len(strict_matches) == 1:
        return {"place_id": strict_matches[0].id, "url": strict_matches[0].google_maps_uri}

    # If we have more than one STRICT match, ie result is ambiguous
    elif len(strict_matches) > 1:
        candidates = [p.display_name.text for p in strict_matches]
        raise RuntimeError(
            f"Ambiguous result for '{search_query}'. Found {len(strict_matches)} potential matches: "
            f"({', '.join(candidates)}). Please refine the search_name."
        )

    # If we have no STRICT match, but the API found something else
    else:
        candidates = [p.display_name.text for p in places]
        raise RuntimeError(
            f"No strict match for '{search_query}'. Google identified {len(strict_matches)} potential match(es): "
            f"({', '.join(candidates)}). Please refine the search_name."
        )


@click.command()
@click.option(
    "-C",
    "--no-cache",
    is_flag=True,
    show_default=True,
)
@click.option(
    "-c",
    "--cache-dir",
    type=click.Path(file_okay=False),
    default="_data/_cache",
    help="Cache directory",
    show_default=True,
)
@click.option(
    "-o",
    "--output",
    type=click.File("w"),
    default="_data/venue_metadata.json",
    help="Output file",
    show_default=True,
)
@click_option_verbosity()
def main(verbosity, output, no_cache, cache_dir):
    """
    Fetch venue metadata from Google Sheet, find Place IDs and other metadata, and output as JSON.

    Output structured as list of sections, each containing a list of venues:

        [{ "section": "Name", "venues": [{ "place_id": "…", … }, … ] }, … ]
    """
    setup_logging(verbosity)

    if cache_dir and not no_cache:
        cache = diskcache.Cache(cache_dir)
    else:
        cache = None

    client = get_places_client(cache=cache)

    sheet_id = "1YhJ2YD-W759uPHqMqIMBR14bq32Vxm0hQ1x0iEFrPB0"
    google_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

    try:
        df = pd.read_csv(google_sheet_url, skiprows=1)  # skiprows=1 ignores the note in the first row
    except Exception as e:
        raise RuntimeError("Could not read Google Sheet CSV") from e

    separator = "near, but not beer mile:"
    days_ordered = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    # Find the separator row
    separator_indices = df[df.iloc[:, 0].notna() & (df.iloc[:, 0].str.strip() == separator)].index.tolist()

    if len(separator_indices) != 1:
        raise RuntimeError(f"Exactly 1 separator row expected, found: {len(separator_indices)}")

    # Venues before separator are beer mile, after are nearby
    separator_idx = separator_indices[0]
    sections = [
        {
            "section": "Blackhorse Beer Mile",
            "df": df[:separator_idx][df[:separator_idx].iloc[:, 0].notna()].copy(),
        },
        {
            "section": "nearby",
            "df": df[separator_idx + 1 :][df[separator_idx + 1 :].iloc[:, 0].notna()].copy(),
        },
    ]

    def process_section(df):
        with tqdm(
            list(df.iterrows()),
            disable=True if verbosity < 0 else None,
        ) as t:

            def process_row(row):
                place_name = row.iloc[0]
                t.set_postfix(name=place_name)
                with logging_context(f"place_name={place_name}"):
                    api_result = get_place_data_from_api(client, place_name)
                    return {
                        "place_id": api_result["place_id"],
                        "place_name": place_name,
                        "url": api_result["url"],
                        "happy_hours": [str(row.get(day)) if pd.notna(row.get(day)) else None for day in days_ordered],
                    }

            return [process_row(row) for _, row in t]

    with tqdm_logging_redirect(
        sections,
        desc=f"Google Sheet CSV → {output.name}",
        disable=True if verbosity < 0 else None,
    ) as t:
        for section in t:
            section_name = section["section"]
            t.set_postfix(name=section_name)
            with logging_context(f"section_name={section_name}"):
                section["venues"] = process_section(section["df"])
                del section["df"]

    json.dump(sections, output, indent=4, ensure_ascii=False)
    output.write("\n")


if __name__ == "__main__":
    main()
