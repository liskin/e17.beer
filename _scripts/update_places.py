import json
import logging
import re

import click
from google.maps.places_v1 import GetPlaceRequest, PlacesClient
from google.maps.places_v1.types import Place
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


def periods_to_percentages(opening_hours_obj: Place.OpeningHours) -> list:
    """Transforms periods into percentage-of-week intervals."""

    if not opening_hours_obj or not opening_hours_obj.periods:
        raise RuntimeError("No periods available.")

    pct_periods: list[dict] = []
    for p in opening_hours_obj.periods:
        # Check for missing period boundaries
        # TODO: later update for the case of 24-hour venues, where Google omits 'close',
        #  otherwise both open and close should be present
        if "open_" not in p or "close" not in p:
            msg = "open time" if "open_" not in p else "close time (possibly 24h venue)"
            logging.warning("Incomplete period data (missing %s): %s", msg, p)
            continue

        if p.open.truncated:
            logging.warning("Truncated open period: %s", p.open)
        if p.close.truncated:
            logging.warning("Truncated close period: %s", p.close)

        # Standard percentage calculation
        open_pct = get_week_percentage(p.open.day, p.open.hour, p.open.minute, p.open.truncated)
        close_pct = get_week_percentage(p.close.day, p.close.hour, p.close.minute, p.close.truncated)

        # Week wraparound logic (period span from Sat to Sun split into two)
        if open_pct > close_pct:
            pct_periods.append({"open": open_pct, "close": 100.0})
            if close_pct > 0:
                pct_periods.insert(0, {"open": 0.0, "close": close_pct})
        else:
            pct_periods.append({"open": open_pct, "close": close_pct})

    # Ensure list is chronologically sorted by the 'open' percentage
    return sorted(pct_periods, key=lambda x: x["open"])


def calculate_day_sort_values(opening_hours_obj: Place.OpeningHours) -> list:
    """Calculate earliest opening and latest closing percentages per day (Sun–Sat)."""

    if not opening_hours_obj or not opening_hours_obj.periods:
        raise RuntimeError("No periods available.")

    day_sort_values: list[dict | None] = [None] * 7
    for p in opening_hours_obj.periods:
        if "open_" not in p or "close" not in p:
            # no warning, already issued from periods_to_percentages()
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
        # Instead of splitting like in periods_to_percentages, add 100 to close_pct
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


def process_text(opening_hours_obj: Place.OpeningHours) -> list:
    """Extracts text descriptions ordered Sunday to Saturday."""

    if not opening_hours_obj or not opening_hours_obj.weekday_descriptions:
        raise RuntimeError("No weekday descriptions available.")

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
        raise RuntimeError(f"Missing data for {', '.join(missing_days)}")

    return ordered_hours_text


def process_venue(client: PlacesClient, venue: dict):
    """
    Fetches opening hours AND GPS location from Google Places API (New). Maps the current opening hours to percentages within Sun-to-Sat week. Combines the hours and GPS with metadata (happy hours, URLs)
    """
    place_id = venue["place_id"]
    request = GetPlaceRequest(name=f"places/{place_id}", language_code="en-GB")
    field_mask = "id,regularOpeningHours,currentOpeningHours,location"
    place = client.get_place(request=request, metadata=[("x-goog-fieldmask", field_mask)])

    # Verify the ID
    if place.id != place_id:
        raise RuntimeError(f"ID Mismatch! Requested place_id: {place_id}, got id: {place.id}")

    current_time_text = process_text(place.current_opening_hours)
    regular_time_text = process_text(place.regular_opening_hours)

    # Use regular_opening_hours for percentage calculations if descriptions match
    # (temporary fix for glitches when venues are open past midnight at the beginning/end of the 7 day window)
    if current_time_text == regular_time_text:
        opening_hours = place.regular_opening_hours
    else:
        opening_hours = place.current_opening_hours

    venue.update(
        happy_hours=[format_happy_hours(hh) for hh in venue["happy_hours"]],
        location={"lat": place.location.latitude, "lng": place.location.longitude} if place.location else None,
        keyframe_periods=periods_to_percentages(opening_hours),
        day_sort_values=calculate_day_sort_values(opening_hours),
        current_schedule={
            "time_text_sun_to_sat": current_time_text,
        },
        regular_schedule={
            "time_text_sun_to_sat": regular_time_text,
        },
    )


@click.command()
@click.option(
    "-o",
    "--output",
    type=click.File("w"),
    default="_data/places.json",
    help="Output file",
    show_default=True,
)
@click.argument(
    "input",
    type=click.File(),
    default="_data/venue_metadata.json",
)
@click_option_verbosity()
def main(verbosity, input, output):
    """
    Load/update information about venues

    Input and Output structured as list of sections, each containing a list of venues:

        [{ "section": "Name", "venues": [{ "place_id": "…", … }, … ] }, … ]
    """
    setup_logging(verbosity)
    client = get_places_client()

    sections = json.load(input)
    if not sections:
        raise RuntimeError("No data found in input JSON.")

    def process_section(venues):
        with tqdm_logging_redirect(
            venues,
            disable=True if verbosity < 0 else None,
        ) as t:
            for venue in t:
                t.set_postfix(name=venue["place_name"])
                with logging_context(f"place_name={venue['place_name']}"):
                    process_venue(client=client, venue=venue)

    with tqdm_logging_redirect(
        sections,
        desc=f"{input.name} → {output.name}",
        disable=True if verbosity < 0 else None,
    ) as t:
        for section in t:
            section_name = section["section"]
            t.set_postfix(name=section_name)
            with logging_context(f"section_name={section_name}"):
                process_section(section["venues"])

    json.dump(sections, output, indent=4, ensure_ascii=False)
    output.write("\n")


if __name__ == "__main__":
    main()
