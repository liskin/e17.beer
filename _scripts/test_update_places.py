from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions
from update_places import fetch_place_data, get_week_percentage


@pytest.fixture
def mock_place():
    def _create_mock_place(
        name="Test Brewery", place_id="dummy_id", periods=None, descriptions=None
    ):
        # Create the main object
        place = MagicMock()
        place.display_name.text = name
        place.id = place_id

        # Setup periods (default to empty list if None)
        if periods is None:
            periods = []

        # Setup descriptions (default to 7 empty days if None)
        if descriptions is None:
            descriptions = [""] * 7

        place.regular_opening_hours.periods = periods
        place.regular_opening_hours.weekday_descriptions = descriptions

        place.current_opening_hours.periods = periods
        place.current_opening_hours.weekday_descriptions = descriptions

        return place

    return _create_mock_place


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


@patch("update_places.client.get_place")
def test_wraparound_split(mock_get_place, mock_place):
    period = MagicMock()
    period.open.day, period.open.hour, period.open.minute = 6, 22, 0
    period.close.day, period.close.hour, period.close.minute = 0, 2, 0

    mock_get_place.return_value = mock_place(periods=[period])

    result = fetch_place_data("dummy_id", {"name": "Late Night Venue"})
    intervals = result["current_schedule"]["percentage_periods"]

    assert len(intervals) == 2
    # 1st interval should end with end of week
    assert intervals[0]["close"] == 100.0
    # 1st interval starts 2 hours before end of week:
    # 100 − (2 / (7 * 24 ) * 100) ~ 98.8095
    assert intervals[0]["close"] > 98.8
    # 2nd interval should start at the beginning of week
    assert intervals[1]["open"] == 0.0
    # 2nd interval starts 2 hour after the beginning of week:
    # 2 / (7 * 24 ) * 100 ~ 1.1905
    assert intervals[1]["close"] < 1.2


# --- DATA TRANSFORMATION TESTS ---


@patch("update_places.client.get_place")
def test_weekday_text_ordering_and_format(mock_get_place, mock_place):
    """Verify raw text is split correctly and ordered Sunday to Saturday"""

    descriptions = [
        "Monday: 4:00 PM – 12:00 AM",
        "Tuesday: 12:00 PM – 12:00 AM",
        "Wednesday: 12:00 PM – 12:00 AM",
        "Thursday: 12:00 PM – 1:00 AM",
        "Friday: 12:00 PM – 1:00 AM",
        "Saturday: 12:00 PM – 1:30 AM",
        "Sunday: 12:00 – 11:30 PM",
    ]

    mock_get_place.return_value = mock_place(name="Test Brewery", descriptions=descriptions)

    result = fetch_place_data("dummy_id", {"name": "Test Brewery"})

    times = result["current_schedule"]["time_text_sun_to_sat"]

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


@patch("update_places.client.get_place")
def test_incomplete_weekday_text_warning(mock_get_place, mock_place):
    """Verify a warning is issued and 'N/A' is returned if data is missing"""

    broken_descriptions = ["Monday: 9:00 AM – 5:00 PM"]

    mock_get_place.return_value = mock_place(
        name="Broken Data Pub", descriptions=broken_descriptions
    )

    with pytest.warns(UserWarning, match=r"Missing data for Sunday*"):
        result = fetch_place_data("dummy_id", {"name": "Broken Data Pub"})

    times = result["current_schedule"]["time_text_sun_to_sat"]

    assert len(times) == 7
    assert times[0] is None or times[0] == "N/A"  # Sunday is missing
    assert times[1] == "9:00 AM – 5:00 PM"  # Monday is present


# --- API RETURN TESTS ---


@patch("update_places.client.get_place")
def test_incomplete_period_handling(mock_get_place, mock_place):
    """Verify that a period missing a 'close' time doesn't crash the script"""

    incomplete_period = MagicMock()
    incomplete_period.open.day = 1
    incomplete_period.open.hour = 21
    incomplete_period.open.minute = 0
    incomplete_period.close = None

    mock_get_place.return_value = mock_place(
        name="Incomplete Data Bar", periods=[incomplete_period]
    )

    # Expect no error
    result = fetch_place_data("dummy_id", {"name": "Incomplete Data Bar"})

    # percentage_periods should be empty
    percentages = result["current_schedule"]["percentage_periods"]

    assert isinstance(percentages, list)
    assert len(percentages) == 0  # It skipped the bad period instead of crashing


@patch("update_places.client.get_place")
def test_fetch_place_api_error_handling(mock_get_place):
    """Verify the Google API exception propagates out of the function"""

    google_reason = "Invalid 'place_id' parameter."
    mock_get_place.side_effect = exceptions.InvalidArgument(google_reason)

    with pytest.raises(exceptions.InvalidArgument) as excinfo:
        fetch_place_data("bad_id", {"name": "Test Brewery"})

    assert google_reason in str(excinfo.value)
