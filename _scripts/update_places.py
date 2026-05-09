import json
import logging
import re

import click
from google.maps import places_v1
from tqdm.contrib.logging import tqdm_logging_redirect

from utils import click_option_verbosity, get_places_client, logging_context, setup_logging


def format_happy_hours_line(line: str) -> str:
    """Format a single line of happy hours text with HTML spans for offer names and times."""

    # Lines starting with a capital letter are offer names
    if line and line[0].isupper():
        return f'<span class="offer-name">{line}</span>'

    # Lines matching time patterns (HH:mm–HH:mm or HH:mm–close)
    if re.match(r"^\d{1,2}:\d{2}–", line):
        return f'<span class="offer-time">{line}</span>'

    # Other lines
    return line


def format_happy_hours(happy_hours_text: str | None) -> str | None:
    if not happy_hours_text or happy_hours_text == "TODO":
        return None

    return "<br>".join(format_happy_hours_line(line) for line in happy_hours_text.splitlines())


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


def periods_to_percentages(opening_hours_obj) -> list:
    """Transforms periods into percentage-of-week intervals."""
    pct_periods: list[dict] = []

    # Check for missing top-level data
    if not opening_hours_obj or not opening_hours_obj.periods:
        logging.warning("Missing all opening periods.")
        return pct_periods

    for p in opening_hours_obj.periods:
        # Check for missing period boundaries
        # TODO: later update for the case of 24-hour venues, where Google omits 'close',
        #  otherwise both open and close should be present
        if not p.open or not p.close:
            msg = "open time" if not p.open else "close time (possibly 24h venue)"
            logging.warning("Incomplete period data (missing %s)", msg)
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


def calculate_day_sort_values(opening_hours_obj) -> list:
    """Calculate earliest opening and latest closing percentages per day (Sun–Sat)."""
    day_sort_values: list[dict | None] = [None] * 7

    if not opening_hours_obj or not opening_hours_obj.periods:
        logging.warning("Missing all opening periods.")
        return day_sort_values

    for p in opening_hours_obj.periods:
        if not p.open or not p.close:
            continue

        # Skip truncated intervals (e.g., Saturday late openings returned as Sunday morning)
        # TODO: Preprocess periods from current, regular and saved opening hours to get rid of truncated intervals
        if p.open.truncated:
            if p.close.hour >= 4:
                logging.warning("Skipping truncated interval closing after 4am (%s – %s)", p.open, p.close)
            continue

        open_day = p.open.day

        # Use get_week_percentage for consistent calculation
        open_pct = get_week_percentage(p.open.day, p.open.hour, p.open.minute, p.open.truncated)
        close_pct = get_week_percentage(p.close.day, p.close.hour, p.close.minute, p.close.truncated)

        # Handle week wraparound: if open_pct > close_pct, the closing is next week
        # Instead of splitting like in percentage_periods, add 100 to close_pct
        if open_pct > close_pct:
            close_pct += 100

        # Update the opening day entry
        if day_sort_values[open_day] is None:
            day_sort_values[open_day] = {"open": open_pct, "close": close_pct}
        else:
            # Track earliest opening and latest closing for this day
            day_sort_values[open_day]["open"] = min(day_sort_values[open_day]["open"], open_pct)
            day_sort_values[open_day]["close"] = max(day_sort_values[open_day]["close"], close_pct)

    return day_sort_values


def process_text(opening_hours_obj) -> list:
    """Extracts text descriptions ordered Sunday to Saturday."""
    if not opening_hours_obj or not opening_hours_obj.weekday_descriptions:
        logging.warning("No weekday descriptions available.")
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
        logging.warning("Missing data for %s", ", ".join(missing_days))

    return ordered_hours_text


def fetch_place_data(client: places_v1.PlacesClient, place_id: str, place_metadata: dict) -> dict:
    """
    Fetches opening hours AND GPS location from Google Places API (New). Maps the current opening hours to percentages within Sun-to-Sat week. Combines the hours and GPS with metadata (happy hours, URLs)
    """
    place_name = place_metadata.get("place_name")
    with logging_context(f"place_name={place_name}"):
        url = place_metadata.get("url")
        happy_hours = place_metadata.get("happy_hours")
        if happy_hours:
            happy_hours = [format_happy_hours(hh) for hh in happy_hours]

        field_mask = "id,regularOpeningHours,currentOpeningHours,location"
        place = client.get_place(name=f"places/{place_id}", metadata=[("x-goog-fieldmask", field_mask)])

        # Verify the ID
        if place.id != place_id:
            raise ValueError(f"ID Mismatch! Requested place_id: {place_id}, got id: {place.id}")

        gps_location = {"lat": place.location.latitude, "lng": place.location.longitude} if place.location else None

        current_time_text = process_text(place.current_opening_hours)
        regular_time_text = process_text(place.regular_opening_hours)
        pct_periods = periods_to_percentages(place.current_opening_hours)
        day_sort_values = calculate_day_sort_values(place.current_opening_hours)

    return {
        "place_name": place_name,
        "place_id": place_id,
        "url": url,
        "location": gps_location,
        "happy_hours": happy_hours,
        "current_schedule": {
            "time_text_sun_to_sat": current_time_text,
            "percentage_periods": pct_periods,
            "day_sort_values": day_sort_values,
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

    json.dump(output_list, output, indent=4, ensure_ascii=False)
    output.write("\n")


if __name__ == "__main__":
    main()
