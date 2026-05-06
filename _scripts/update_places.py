import json
import warnings

import click
from google.maps import places_v1
from tqdm.contrib.logging import tqdm_logging_redirect

from utils import click_option_verbosity, get_places_client, setup_logging


def format_happy_hours_line(line: str) -> str:
    """
    Format a single line of happy hours text with HTML spans for offer names and times.

    - Lines starting with a capital letter are offer names: wrapped in <span class="offer_name">
    - Lines matching time patterns (HH:mm–HH:mm or HH:mm–close): wrapped in <span class="offer_time">
    - Other lines are returned as-is
    """
    import re

    line = line.strip()
    if not line:
        return line

    # Check if line matches time pattern (HH:mm–... with en dash)
    # Match HH:mm at the start followed by en dash
    if re.match(r"^\d{1,2}:\d{2}–", line):
        return f'<span class="offer_time">{line}</span>'

    # Check if line starts with a capital letter (offer name)
    if line[0].isupper():
        return f'<span class="offer_name">{line}</span>'

    return line


def format_happy_hours(happy_hours_text: str | None) -> str | None:
    """
    Format happy hours text by processing each line and applying formatting.
    Returns None if input is None, otherwise returns formatted text.
    """
    if happy_hours_text is None:
        return None

    lines = happy_hours_text.split("\n")
    formatted_lines = [format_happy_hours_line(line) for line in lines]
    return "\n".join(formatted_lines)


def get_week_percentage(day_nmb: int, hours: int, minutes: int, truncated: bool = False) -> float:
    """Calculates the percentage of the week elapsed (week: Sun 0000 to Sat 2359)."""
    # TODO: update to work for 24 hours opened venues

    # Input values validation
    if not all(isinstance(i, int) for i in [day_nmb, hours, minutes]):
        raise TypeError("day_nmb, hours, and minutes must be integers.")

    if not (0 <= day_nmb <= 6):
        raise ValueError(f"day_nmb {day_nmb} out of range (0–6).")
    if not (0 <= hours <= 23):
        raise ValueError(f"hours {hours} out of range (0–23).")
    if not (0 <= minutes <= 59):
        raise ValueError(f"minutes {minutes} out of range (0–59).")

    # Percentage calculation
    total_week_minutes = 7 * 24 * 60
    minutes_passed_in_day = (hours * 60) + minutes
    minutes_passed_in_week = (day_nmb * 1440) + minutes_passed_in_day

    # Workaround for open before midnight yesterday and not closed yet at the time of request
    # (Google will split period in two days: truncated in this_day with the close= 23h 59m and truncated in this_day-1 with open= 0h 0m)
    if truncated and (hours, minutes) == (23, 59):
        minutes_passed_in_week += 1

    percentage = (minutes_passed_in_week / total_week_minutes) * 100

    return round(percentage, 4)


def fetch_place_data(client: places_v1.PlacesClient, place_id: str, place_metadata: dict) -> dict:
    """
    Fetches opening hours AND GPS location from Google Places API (New). Maps the current opening hours to percentages within Sun-to-Sat week. Combines the hours and GPS with metadata (happy hours, URLs)
    """
    place_name = place_metadata.get("place_name", None)
    url = place_metadata.get("url", None)
    happy_hours_raw = place_metadata.get("happy_hours", None)

    # Format happy_hours list - apply formatting to each non-None entry
    happy_hours = None
    if happy_hours_raw is not None:
        happy_hours = [format_happy_hours(entry) if entry is not None else None for entry in happy_hours_raw]

    field_mask = "id,regularOpeningHours,currentOpeningHours,location"
    place = client.get_place(name=f"places/{place_id}", metadata=[("x-goog-fieldmask", field_mask)])

    # Verify the ID
    if place.id != place_id:
        raise ValueError(f"ID Mismatch! Requested place_id: {place_id}, got id: {place.id}")

    gps_location = {"lat": place.location.latitude, "lng": place.location.longitude} if place.location else None

    def extract_raw_periods(opening_hours_obj) -> dict:
        """Returns raw times structured by day number { "0": {"open": [...], "close": [...]}, ... }"""
        if not opening_hours_obj or not opening_hours_obj.periods:
            return None

        raw_data = {str(i): {"open": [], "close": []} for i in range(7)}
        for p in opening_hours_obj.periods:
            if not p.open or not p.close:
                continue
            day_key = str(p.open.day)
            raw_data[day_key]["open"].append([p.open.hour, p.open.minute])
            raw_data[day_key]["close"].append([p.close.hour, p.close.minute])
        return raw_data

    def periods_to_percentages(opening_hours_obj) -> list:
        """Transforms periods into percentage-of-week intervals."""
        pct_periods = []

        # Check for missing top-level data
        if not opening_hours_obj or not opening_hours_obj.periods:
            warnings.warn(f"⚠️ {place_name}: Missing all opening periods.", UserWarning)
            return pct_periods

        for p in opening_hours_obj.periods:
            # Check for missing period boundaries
            # TODO: later update for the case of 24-hour venues, where Google omits 'close',
            #  otherwise both open and close should be present
            if not p.open or not p.close:
                msg = "open time" if not p.open else "close time (possibly 24h venue)"
                warnings.warn(f"⚠️ {place_name}: Incomplete period data (missing {msg}).", UserWarning)
                continue

            # Standard percentage calculation
            open_pct = get_week_percentage(p.open.day, p.open.hour, p.open.minute, p.open.truncated)
            close_pct = get_week_percentage(p.close.day, p.close.hour, p.close.minute, p.close.truncated)

            # Week wraparound logic (period span from Sat to Sun split into two)
            if open_pct > close_pct:
                pct_periods.append({"open": open_pct, "close": 100.0})
                pct_periods.insert(0, {"open": 0.0, "close": close_pct})
            else:
                pct_periods.append({"open": open_pct, "close": close_pct})

        # Ensure list is chronologically sorted by the 'open' percentage
        return sorted(pct_periods, key=lambda x: x["open"])

    def process_text(opening_hours_obj) -> list:
        """Extracts text descriptions ordered Sunday to Saturday."""
        if not opening_hours_obj or not opening_hours_obj.weekday_descriptions:
            warnings.warn(f"{place_name}: No weekday descriptions available.", UserWarning)
            return ["N/A"] * 7

        days_order = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        desc_list = list(opening_hours_obj.weekday_descriptions)
        week_dict = {}

        for entry in desc_list:
            if ": " in entry:
                day, hours = entry.split(": ", 1)
                week_dict[day.strip()] = hours.strip()

        # Create the ordered list
        ordered_hours_text = [week_dict.get(day, None) for day in days_order]

        # Check if any day came back as None
        if None in ordered_hours_text:
            missing_days = [days_order[i] for i, val in enumerate(ordered_hours_text) if val is None]
            warnings.warn(f"{place_name}: Missing data for {', '.join(missing_days)}.", UserWarning)

        return ordered_hours_text

    # Hack: Handle East London Brewing not showing correct opening hours yet
    if place_name == "East London Brewing":
        current_time_text = ["?"] * 7
        regular_time_text = ["?"] * 7
        pct_periods = []
        raw_periods = {str(i): {"open": [], "close": []} for i in range(7)}
    else:
        current_time_text = process_text(place.current_opening_hours)
        regular_time_text = process_text(place.regular_opening_hours)
        pct_periods = periods_to_percentages(place.current_opening_hours)
        raw_periods = extract_raw_periods(place.current_opening_hours)

    return {
        "place_name": place_name,
        "place_id": place_id,
        "url": url,
        "location": gps_location,
        "happy_hours": happy_hours,
        "current_schedule": {
            "time_text_sun_to_sat": current_time_text,
            "percentage_periods": pct_periods,
            "periods": raw_periods,
        },
        "regular_schedule": {
            "time_text_sun_to_sat": regular_time_text,
        },
    }


@click.command()
@click.option(
    "-o",
    "--output",
    type=click.File("w"),
    default="../_data/places.json",
    help="Output file",
    show_default=True,
)
@click.argument(
    "input",
    type=click.File(),
    default="E17_BHMplus_data.json",
)
@click_option_verbosity()
def main(verbosity, input, output):
    """
    Load/update information about venues

    Input file structured as ID-keyed nested dictionary:

        { "PLACE_ID": { "place_name": "…", "url": "…", "happy_hours": […] }, … }
    """
    setup_logging(verbosity)
    client = get_places_client()

    input_dict = json.load(input)
    if not input_dict:
        raise RuntimeError("No data found in input JSON.")

    with tqdm_logging_redirect(
        input_dict.items(),
        desc=f"{input.name} → {output.name}",
        disable=True if verbosity < 0 else None,
    ) as t:

        def process(pid, metadata):
            t.set_postfix(name=metadata["place_name"])
            return fetch_place_data(client, pid, metadata)

        output_list = [process(pid, metadata) for pid, metadata in t]

    json.dump(output_list, output, indent=4)


if __name__ == "__main__":
    main()
