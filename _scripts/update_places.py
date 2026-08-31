import datetime
import json
import logging
import re
from collections.abc import Iterable
from itertools import chain
from pathlib import Path

import click
import diskcache  # type: ignore [import-untyped]
from google.maps.places_v1 import GetPlaceRequest, PlacesClient
from google.maps.places_v1.types import Place
from tqdm import tqdm
from tqdm.contrib.logging import tqdm_logging_redirect

from utils import click_option_verbosity, get_places_client, logging_context, setup_logging


def fmt(x) -> str:
    match x:
        case Place.OpeningHours():
            return f"{fmt(x.periods)}; weekday_descriptions = {fmt(x.weekday_descriptions)}"

        case Place.OpeningHours.Period():
            return f"{fmt(x.open)} → {fmt(x.close)}"

        case Place.OpeningHours.Period.Point():
            weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][x.day]
            time = (
                ("[[" if x.truncated else "")
                + datetime.time(x.hour, x.minute).isoformat("minutes")
                + ("]]" if x.truncated else "")
            )
            date = "" if x.date is None else f"({datetime.date(x.date.year, x.date.month, x.date.day)}) "
            return f"{date}{weekday}: {time}"

        case str() | bytes():
            return str(x)

        case Iterable():
            return "[" + ", ".join(fmt(y) for y in x) + "]"

        case _:
            return str(x)


def format_happy_hours_line(line: str) -> str:
    """Format a single line of happy hours text with HTML spans for offer names and times."""

    # Lines starting with a capital letter are offer names
    if line and line[0].isupper():
        return f'<span class="offer-name">{line}</span>'

    # Lines matching time patterns (HH:mm–HH:mm or HH:mm–close)
    if re.search(r"^\d{1,2}:\d{2}–|–\d{1,2}:\d{2}$", line):
        return f'<span class="offer-time">{line}</span>'

    # Other lines
    return line


def format_happy_hours(happy_hours_text: str | None) -> str | None:
    if not happy_hours_text or happy_hours_text == "TODO":
        return None

    return "<br>".join(format_happy_hours_line(line) for line in happy_hours_text.splitlines())


def get_week_percentage(day_nmb: int, hours: int, minutes: int) -> float:
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
    percentage = (minutes_passed_in_week / total_week_minutes) * 100
    return round(percentage, 4)


def periods_to_percentages(weekday_periods: list[list[Place.OpeningHours.Period]]) -> list:
    """Transforms periods into percentage-of-week intervals."""

    pct_periods: list[dict] = []
    for p in chain.from_iterable(weekday_periods):
        # Standard percentage calculation
        open_pct = get_week_percentage(p.open.day, p.open.hour, p.open.minute)
        close_pct = get_week_percentage(p.close.day, p.close.hour, p.close.minute)

        # Week wraparound logic (period span from Sat to Sun split into two)
        if open_pct > close_pct:
            pct_periods.append({"open": open_pct, "close": 100.0})
            if close_pct > 0:
                pct_periods.insert(0, {"open": 0.0, "close": close_pct})
        else:
            pct_periods.append({"open": open_pct, "close": close_pct})

    # Ensure list is chronologically sorted by the 'open' percentage
    return sorted(pct_periods, key=lambda x: x["open"])


def calculate_day_sort_value(periods: list[Place.OpeningHours.Period]) -> dict | None:
    if not periods:
        return None

    # Find earliest opening and latest closing for this day
    min_open, max_close = None, None
    for p in periods:
        open_pct = get_week_percentage(p.open.day, p.open.hour, p.open.minute)
        close_pct = get_week_percentage(p.close.day, p.close.hour, p.close.minute)

        # Handle week wraparound: if open_pct > close_pct, the closing is next week
        # Instead of splitting like in periods_to_percentages, add 100 to close_pct
        if open_pct > close_pct:
            close_pct += 100

        min_open = open_pct if min_open is None else min(min_open, open_pct)
        max_close = close_pct if max_close is None else max(max_close, close_pct)

    return {"open": min_open, "close": max_close}


def extract_weekday_descriptions_en(opening_hours_obj: Place.OpeningHours) -> list[str | None]:
    return extract_weekday_descriptions(
        opening_hours_obj,
        days=["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
        closed="Closed",
    )


def extract_weekday_descriptions_sv(opening_hours_obj: Place.OpeningHours) -> list[str | None]:
    return extract_weekday_descriptions(
        opening_hours_obj,
        days=["söndag", "måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag"],
        closed="Stängt",
    )


def extract_weekday_descriptions(
    opening_hours_obj: Place.OpeningHours, days: list[str], closed: str
) -> list[str | None]:
    """Extracts text descriptions ordered Sunday to Saturday."""

    if not opening_hours_obj or not opening_hours_obj.weekday_descriptions:
        raise RuntimeError("No weekday descriptions available.")

    week_dict = {}
    for entry in list(opening_hours_obj.weekday_descriptions):
        if ": " in entry:
            day, hours = entry.split(": ", 1)
            hours = hours.strip()
            if hours == closed:
                hours = "Closed"
            week_dict[day.strip()] = hours

    # Create the ordered list
    ordered_hours_text = [week_dict.get(day, None) for day in days]

    # Check if any day came back as None
    if None in ordered_hours_text:
        missing_days = [days[i] for i, val in enumerate(ordered_hours_text) if val is None]
        raise RuntimeError(f"Missing data for {', '.join(missing_days)}: {fmt(opening_hours_obj.weekday_descriptions)}")

    return ordered_hours_text


def extract_weekday_periods(opening_hours_obj: Place.OpeningHours) -> list[list[Place.OpeningHours.Period]]:
    if not opening_hours_obj or not opening_hours_obj.periods:
        raise RuntimeError("No periods available.")

    weekday_periods: list[list[Place.OpeningHours.Period]] = [[] for _ in range(7)]

    for p in opening_hours_obj.periods:
        # Check for missing period boundaries
        # TODO: later update for the case of 24-hour venues, where Google omits 'close',
        #  otherwise both open and close should be present
        if "open_" not in p or "close" not in p:
            msg = "open time" if "open_" not in p else "close time (possibly 24h venue)"
            raise RuntimeError(f"Incomplete period data (missing {msg}): {fmt(p)}")

        weekday_periods[p.open.day].append(p)

    return weekday_periods


def process_irregular_hours(
    place: Place, place_24h: Place, irregular_hours: dict
) -> tuple[
    list[str | None],
    list[str | None],
    list[str | None],
    list[str | None],
    list[list[Place.OpeningHours.Period]],
    list[list[Place.OpeningHours.Period]],
]:
    current_time_texts = extract_weekday_descriptions_en(place.current_opening_hours)
    regular_time_texts = extract_weekday_descriptions_en(place.regular_opening_hours)
    current_time_texts_24h = extract_weekday_descriptions_sv(place_24h.current_opening_hours)
    regular_time_texts_24h = extract_weekday_descriptions_sv(place_24h.regular_opening_hours)
    current_weekday_periods = extract_weekday_periods(place.current_opening_hours)
    regular_weekday_periods = extract_weekday_periods(place.regular_opening_hours)

    today = datetime.date.today()
    for i in range(7):
        date = today + datetime.timedelta(days=i)
        weekday = date.isoweekday() % 7
        isoformat = date.isoformat()

        # assert that current_opening_hours returns 7 days starting from today
        sanity_check_period = current_weekday_periods[weekday]
        if sanity_check_period:
            sanity_check_date = sanity_check_period[0].open.date
            assert date == datetime.date(sanity_check_date.year, sanity_check_date.month, sanity_check_date.day)

        regular_time_text = regular_time_texts[weekday]
        regular_time_text_24h = regular_time_texts_24h[weekday]
        regular_periods = regular_weekday_periods[weekday]

        # today - use data from irregular_hours (if any) or regular
        if i == 0:
            if isoformat in irregular_hours:
                current_time_text = irregular_hours[isoformat]["time_text_sun_to_sat"]
                current_time_text_24h = irregular_hours[isoformat]["time_text_sun_to_sat_24h"]
                current_periods_dicts = irregular_hours[isoformat]["periods"]
                current_periods = [Place.OpeningHours.Period(p) for p in current_periods_dicts]

                # Warn if the API current hours differ
                api_current_time_text = current_time_texts[weekday]
                if current_time_text != api_current_time_text and not (
                    current_time_text is not None
                    and api_current_time_text is not None
                    and re.search(r"\b" + re.escape(current_time_text) + r"\b", api_current_time_text)
                    # the following is considered okay:
                    #   api_current_time_text: 12:00 – 2:00 am, 12:00 – 8:00 pm
                    #   current_time_text:                      12:00 – 8:00 pm
                ):
                    logging.warning(
                        "Using stored irregular %s, cf. current %s",
                        fmt(current_periods),
                        fmt(current_weekday_periods[weekday]),
                    )
            else:
                current_time_text = regular_time_text
                current_time_text_24h = regular_time_text_24h
                current_periods = regular_periods

        # neither today nor the last day - current hours won't be truncated, use them and persist
        elif 0 < i < 6:
            current_time_text = current_time_texts[weekday]
            current_time_text_24h = current_time_texts_24h[weekday]
            current_periods = current_weekday_periods[weekday]

            # persist to irregular_hours
            if regular_time_text == current_time_text:
                if isoformat in irregular_hours:
                    del irregular_hours[isoformat]
            else:
                current_periods_dicts = [
                    Place.OpeningHours.Period.to_dict(
                        p, preserving_proto_field_name=False, always_print_fields_with_no_presence=False
                    )
                    for p in current_periods
                ]
                irregular_hours[isoformat] = {
                    "time_text_sun_to_sat": current_time_text,
                    "time_text_sun_to_sat_24h": current_time_text_24h,
                    "periods": current_periods_dicts,
                }
                assert [Place.OpeningHours.Period(p) for p in current_periods_dicts] == current_periods

        # last day - always use regular as current might be truncated
        else:  # i == 6
            current_time_text = regular_time_text
            current_time_text_24h = regular_time_text_24h
            current_periods = regular_periods

        for p in regular_periods:
            assert not p.open.truncated
            assert not p.close.truncated

        for p in current_periods:
            assert not p.open.truncated
            assert not p.close.truncated
            if p.open.hour < 4:
                logging.warning("Open before 4am %s", fmt(current_periods))

        current_time_texts[weekday] = current_time_text
        current_time_texts_24h[weekday] = current_time_text_24h
        current_weekday_periods[weekday] = current_periods

    return (
        current_time_texts,
        regular_time_texts,
        current_time_texts_24h,
        regular_time_texts_24h,
        current_weekday_periods,
        regular_weekday_periods,
    )


def process_venue(client: PlacesClient, venue: dict, irregular_hours: dict):
    """
    Fetches opening hours AND GPS location from Google Places API (New). Maps the current opening hours to percentages within Sun-to-Sat week. Combines the hours and GPS with metadata (happy hours, URLs)
    """
    # Fetch 12-hour format (en-GB) + location
    request = GetPlaceRequest(name=f"places/{venue['place_id']}", language_code="en-GB")
    field_mask = "regularOpeningHours,currentOpeningHours,location"
    place = client.get_place(request=request, metadata=[("x-goog-fieldmask", field_mask)])

    # Fetch 24-hour format (sv for Swedish locale)
    request_24h = GetPlaceRequest(name=f"places/{venue['place_id']}", language_code="sv")
    field_mask_24h = "regularOpeningHours,currentOpeningHours"
    place_24h = client.get_place(request=request_24h, metadata=[("x-goog-fieldmask", field_mask_24h)])

    (
        current_time_texts,
        regular_time_texts,
        current_time_texts_24h,
        regular_time_texts_24h,
        current_periods,
        regular_periods,
    ) = process_irregular_hours(place=place, place_24h=place_24h, irregular_hours=irregular_hours)

    venue.update(
        happy_hours=[format_happy_hours(hh) for hh in venue["happy_hours"]],
        location={"lat": place.location.latitude, "lng": place.location.longitude} if place.location else None,
        keyframe_periods=periods_to_percentages(current_periods),
        day_sort_values=[calculate_day_sort_value(p) for p in current_periods],
        current_schedule={
            "time_text_sun_to_sat": current_time_texts,
            "time_text_sun_to_sat_24h": current_time_texts_24h,
        },
        regular_schedule={
            "time_text_sun_to_sat": regular_time_texts,
            "time_text_sun_to_sat_24h": regular_time_texts_24h,
        },
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
    default="_data/places.json",
    help="Output file",
    show_default=True,
)
@click.option(
    "--irregular-hours",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default="_data/irregular_hours.json",
    help="Output file",
    show_default=True,
)
@click.argument(
    "input",
    type=click.File(),
    default="_data/venue_metadata.json",
)
@click_option_verbosity()
def main(verbosity, input, output, irregular_hours: Path, no_cache: bool, cache_dir):
    """
    Load/update information about venues

    Input and Output structured as list of sections, each containing a list of venues:

        [{ "section": "Name", "venues": [{ "place_id": "…", … }, … ] }, … ]
    """
    setup_logging(verbosity)

    if cache_dir and not no_cache:
        cache = diskcache.Cache(cache_dir)
    else:
        cache = None

    client = get_places_client(cache=cache)

    sections = json.load(input)
    if not sections:
        raise RuntimeError("No data found in input JSON.")

    if irregular_hours.exists():
        with irregular_hours.open() as f:
            irregular_hours_dict = json.load(f)
    else:
        irregular_hours_dict = {}

    def process_section(venues):
        with tqdm(
            venues,
            disable=True if verbosity < 0 else None,
        ) as t:
            for venue in t:
                name = venue["place_name"]
                t.set_postfix(name=name)
                with logging_context(f"place_name={name}"):
                    process_venue(client=client, venue=venue, irregular_hours=irregular_hours_dict.setdefault(name, {}))

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

    with irregular_hours.open(mode="w") as f:
        json.dump(irregular_hours_dict, f, indent=4, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
