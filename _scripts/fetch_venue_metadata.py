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

from utils import CacheWrapper, click_option_verbosity, get_places_client, logging_context, setup_logging


def get_place_data_from_api(client: PlacesClient, place_name: str, search_query: str) -> dict:
    """
    Searches Google Places API (New) using the official client library. Returns ID and URL.
    """
    search_query, *search_kwargs_lines = search_query.splitlines()
    search_kwargs: dict = {}
    for l in search_kwargs_lines:
        match l.partition("="):
            case (k, "=", v):
                search_kwargs[k] = v
            case _:
                raise RuntimeError(f"Cannot parse search_query line: {l}")

    logging.debug(
        "get_place_data_from_api: place_name=%s search_query=%s search_kwargs=%s",
        place_name,
        search_query,
        search_kwargs,
    )
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
        "get_place_data_from_api: places=\n%s",
        textwrap.indent(pprint.pformat(places, indent=2), "  "),
    )
    logging.debug(
        "get_place_data_from_api: strict_matches=\n%s",
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
            f"({', '.join(candidates)}).\n"
            f"Perhaps the place changed name? Investigate and update the spreadsheet."
        )


class Spreadsheet:
    def fetch(self, sheet_id: str, gid: str, **pd_read_csv_kwargs):
        google_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

        try:
            return pd.read_csv(google_sheet_url, **pd_read_csv_kwargs)
        except Exception as e:
            raise RuntimeError("Could not read Google Sheet CSV") from e


def row_days(row) -> list[str | None]:
    return [
        str(row.get(day)) if pd.notna(row.get(day)) else None
        for day in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    ]


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
def main(verbosity, output, no_cache: bool, cache_dir):
    """
    Fetch venue metadata from Google Sheet, find Place IDs and other metadata, and output as JSON.

    Output structured as list of sections, each containing a list of venues:

        [{ "section": "Name", "venues": [{ "place_id": "…", … }, … ] }, … ]
    """
    setup_logging(verbosity)

    cache = diskcache.Cache(cache_dir)
    client = get_places_client(cache=cache, expire=5 * 3600, tag="places_client_search", delete=no_cache)

    # skiprows=1 ignores the note in the first row
    spreadsheet = CacheWrapper(wrapped=Spreadsheet(), cache=cache, expire=1 * 3600, tag="spreadsheet", delete=no_cache)
    hours = spreadsheet.fetch("1YhJ2YD-W759uPHqMqIMBR14bq32Vxm0hQ1x0iEFrPB0", gid="0", skiprows=1, index_col=0)
    metadata = spreadsheet.fetch(
        "1YhJ2YD-W759uPHqMqIMBR14bq32Vxm0hQ1x0iEFrPB0", gid="1967915400", skiprows=1, index_col=0
    )

    if not hours.index.is_unique:
        raise RuntimeError(f"Spreadsheet index not unique: {hours.index}")
    if not metadata.index.is_unique:
        raise RuntimeError(f"Spreadsheet index not unique: {metadata.index}")

    # Venues before separator are beer mile, after are nearby
    separator_idx = hours.index.get_loc("near, but not beer mile:")
    sections = [
        {
            "section": "Blackhorse Beer Mile",
            "df": hours.iloc[:separator_idx].copy(),
        },
        {
            "section": "nearby",
            "df": hours.iloc[separator_idx + 1 :].copy(),
        },
    ]

    def process_section(df):
        with tqdm(
            list(df.iterrows()),
            disable=True if verbosity < 0 else None,
        ) as t:

            def process_row(place_name, row):
                metadata_row = metadata.loc[place_name]
                search_query = metadata_row.get("search")
                t.set_postfix(name=place_name)
                with logging_context(f"place_name={place_name}"):
                    api_result = get_place_data_from_api(
                        client=client, place_name=place_name, search_query=search_query
                    )
                    return {
                        "place_id": api_result["place_id"],
                        "place_name": place_name,
                        "url": api_result["url"],
                        "happy_hours": row_days(row),
                    }

            return [process_row(place_name, row) for place_name, row in t]

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
