from collections import defaultdict
from unittest.mock import MagicMock

import google.api_core
import pytest
from google.maps.places_v1.types import Place

from update_places import (
    calculate_day_sort_values,
    fetch_place_data,
    format_happy_hours_line,
    get_week_percentage,
    periods_to_percentages,
    process_text,
)

# --- PERCENTAGE CALCULATION TESTS ---


def test_week_percentage_start():
    """Sunday 00:00 should be 0.0"""
    assert get_week_percentage(0, 0, 0) == 0.0


def test_week_percentage_end():
    """Saturday 23:59 should be high precision (99.9901)"""
    # ((6*24*60 + 23*60 + 59) / (24 * 7 * 60)) * 100 = 99.990079 -> 99.9901
    assert get_week_percentage(6, 23, 59) == 99.9901


def test_week_percentage_midweek():
    """Wednesday 12:00 should be exactly 50.0"""
    assert get_week_percentage(3, 12, 0) == 50.0


def test_week_percentage_spectrum():
    """Verify that days 0–2 are always < 50% and days 4–6 are always > 50%"""
    # Days before Wednesday (Sun, Mon, Tue)
    for day in [0, 1, 2]:
        for hour in range(24):
            pct = get_week_percentage(day, hour, 0)
            assert pct < 50.0, f"Day {day} at {hour:02}00 should be < 50%"

    # Days after Wednesday (Thu, Fri, Sat)
    for day in [4, 5, 6]:
        for hour in range(24):
            pct = get_week_percentage(day, hour, 0)
            assert pct > 50.0, f"Day {day} at {hour:02}00 should be > 50%"


def test_midnight_transition():
    """Test Monday midnight vs Sunday midnight"""
    sun_midnight = get_week_percentage(0, 0, 0)
    mon_midnight = get_week_percentage(1, 0, 0)
    assert sun_midnight == 0.0  # Start of week
    assert mon_midnight == 14.2857  # 1/7th of the way: (1440/10080)*100 ~ 1/7


def test_wraparound_split():
    opening_hours_obj = Place.OpeningHours(
        periods=[
            Place.OpeningHours.Period(
                open=Place.OpeningHours.Period.Point(day=6, hour=22, minute=0),
                close=Place.OpeningHours.Period.Point(day=0, hour=2, minute=0),
            )
        ]
    )

    intervals = periods_to_percentages(opening_hours_obj)
    assert len(intervals) == 2

    # 1st interval should start at the beginning of week
    assert intervals[0]["open"] == 0.0
    # 1st interval ends 2 hour after the beginning of week:
    # 2 / (7 * 24 ) * 100 ~ 1.1905
    assert intervals[0]["close"] < 1.2
    # last interval should end with end of week
    assert intervals[-1]["close"] == 100.0
    # last interval starts 2 hours before end of week:
    # 100 − (2 / (7 * 24 ) * 100) ~ 98.8095
    assert intervals[-1]["close"] > 98.8


def test_wraparound_split_eow():
    """Wraparound split doesn't emit a (0, 0) interval when a venue closes Saturday/Sunday midnight"""
    opening_hours_obj = Place.OpeningHours(
        periods=[
            Place.OpeningHours.Period(
                open=Place.OpeningHours.Period.Point(day=6, hour=12, minute=0),
                close=Place.OpeningHours.Period.Point(day=0, hour=0, minute=0),
            )
        ]
    )
    intervals = periods_to_percentages(opening_hours_obj)
    assert len(intervals) == 1


# --- DATA TRANSFORMATION TESTS ---


def test_weekday_text_ordering_and_format():
    """Verify raw text is split correctly and ordered Sunday to Saturday"""
    opening_hours_obj = Place.OpeningHours(
        weekday_descriptions=[
            "Monday: 4:00 PM – 12:00 AM",
            "Tuesday: 12:00 PM – 12:00 AM",
            "Wednesday: 12:00 PM – 12:00 AM",
            "Thursday: 12:00 PM – 1:00 AM",
            "Friday: 12:00 PM – 1:00 AM",
            "Saturday: 12:00 PM – 1:30 AM",
            "Sunday: 12:00 – 11:30 PM",
        ]
    )

    times = process_text(opening_hours_obj)

    # Verify Sunday is first (index 0)
    assert times[0] == "12:00 – 11:30 PM"
    # Verify Monday is second (index 1)
    assert times[1] == "4:00 PM – 12:00 AM"
    # Verify Saturday is last (index -1)
    assert times[-1] == "12:00 PM – 1:30 AM"
    # Verify the list length is exactly 7
    assert len(times) == 7


# --- VALIDATION TESTS ---


def test_invalid_day_index():
    """Should raise ValueError for day index 7"""
    with pytest.raises(ValueError):
        get_week_percentage(7, 12, 0)


def test_invalid_time_format():
    """Should raise ValueError for any string that isn't exactly HHMM"""
    with pytest.raises(ValueError):
        get_week_percentage(-1, 9, 0)  # minus days
    with pytest.raises(ValueError):
        get_week_percentage(7, 9, 0)  # day index 7
    with pytest.raises(ValueError):
        get_week_percentage(1, -9, 0)  # minus hours
    with pytest.raises(ValueError):
        get_week_percentage(1, 90, 0)  # 90 hours
    with pytest.raises(ValueError):
        get_week_percentage(1, 9, -30)  # - minutes
    with pytest.raises(ValueError):
        get_week_percentage(1, 9, 67)  # > 60 minutes


def test_valid_time_format():
    """Should complete without raising an error"""
    get_week_percentage(1, 9, 0)
    get_week_percentage(1, 9, 00)


def test_incomplete_weekday_text_error():
    """Verify an exception is issued if data is missing"""
    opening_hours_obj = Place.OpeningHours(weekday_descriptions=["Monday: 9:00 AM – 5:00 PM"])

    with pytest.raises(RuntimeError) as excinfo:
        process_text(opening_hours_obj)

    assert "Missing data for Sunday, Tuesday, Wednesday, Thursday, Friday, Saturday" == str(excinfo.value)


# --- API RETURN TESTS ---


def test_incomplete_period_handling(caplog):
    """Verify that a period missing a 'close' time doesn't crash the script"""

    opening_hours_obj = Place.OpeningHours(
        periods=[Place.OpeningHours.Period(open=Place.OpeningHours.Period.Point(day=1, hour=21, minute=0))]
    )

    # should be empty - it skipped the bad period instead of crashing
    assert periods_to_percentages(opening_hours_obj) == []
    assert "missing close time" in caplog.text


def test_midnight_not_mistaken_as_incomplete():
    """Verify that we don't mistake a falsy Place.OpeningHours.Period.Point object as unspecified"""
    opening_hours_obj = Place.OpeningHours(
        periods=[
            # Saturday noon to midnight
            Place.OpeningHours.Period(
                open=Place.OpeningHours.Period.Point(day=6, hour=12, minute=0),
                close=Place.OpeningHours.Period.Point(day=0, hour=0, minute=0),
            )
        ]
    )
    assert periods_to_percentages(opening_hours_obj) != []
    assert calculate_day_sort_values(opening_hours_obj)[6] is not None


def test_fetch_place_api_error_handling():
    """Verify the Google API exception propagates out of the function"""

    google_reason = "Invalid 'place_id' parameter."
    mock_client = MagicMock()
    mock_client.get_place.side_effect = google.api_core.exceptions.InvalidArgument(google_reason)

    with pytest.raises(google.api_core.exceptions.InvalidArgument) as excinfo:
        fetch_place_data(mock_client, "bad_id", defaultdict(str))

    assert google_reason in str(excinfo.value)


# --- HAPPY HOURS FORMATTING TESTS ---


def test_format_happy_hours_line_offer_name():
    """Lines starting with capital letters should be wrapped in offer-name span"""
    assert format_happy_hours_line("Taco Tuesday") == '<span class="offer-name">Taco Tuesday</span>'
    assert format_happy_hours_line("Wing Wednesday") == '<span class="offer-name">Wing Wednesday</span>'


def test_format_happy_hours_line_offer_time():
    """Lines matching time patterns should be wrapped in offer-time span"""
    assert format_happy_hours_line("17:00–close") == '<span class="offer-time">17:00–close</span>'
    assert format_happy_hours_line("12:00–19:00") == '<span class="offer-time">12:00–19:00</span>'
    assert format_happy_hours_line("6:00–20:00") == '<span class="offer-time">6:00–20:00</span>'


def test_format_happy_hours_line_other_text():
    """Lines not starting with capital or time pattern should be unchanged"""
    assert format_happy_hours_line("£3.50 pint cask") == "£3.50 pint cask"
    assert format_happy_hours_line("free pint when £10+ spent") == "free pint when £10+ spent"
    assert format_happy_hours_line("25% off wine bottles") == "25% off wine bottles"
