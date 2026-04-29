import pytest
from unittest.mock import patch
from update_places import get_week_percentage, fetch_place_data

# --- PERCENTAGE CALCULATION TESTS ---

def test_week_percentage_start():
    """Sunday 00:00 should be 0.0"""
    assert get_week_percentage(0, '0000') == 0.0

def test_week_percentage_end():
    """Saturday 23:59 should be high precision (99.9901)"""
    # ((6*24*60 + 23*60 + 59) / (24 * 7 * 60)) * 100 = 99.990079 -> 99.9901
    assert get_week_percentage(6, '2359') == 99.9901

def test_week_percentage_midweek():
    """Wednesday 12:00 should be exactly 50.0"""
    assert get_week_percentage(3, '1200') == 50.0

def test_week_percentage_spectrum():
    """Verify that days 0–2 are always < 50% and days 4–6 are always > 50%"""
    # Days before Wednesday (Sun, Mon, Tue)
    for day in [0, 1, 2]:
        for hour in range(24):
            pct = get_week_percentage(day, f"{hour:02}00")
            assert pct < 50.0, f"Day {day} at {hour:02}00 should be < 50%"

    # Days after Wednesday (Thu, Fri, Sat)
    for day in [4, 5, 6]:
        for hour in range(24):
            pct = get_week_percentage(day, f"{hour:02}00")
            assert pct > 50.0, f"Day {day} at {hour:02}00 should be > 50%"

def test_midnight_transition():
    """Test Monday midnight vs Sunday midnight"""
    sun_midnight = get_week_percentage(0, '0000')
    mon_midnight = get_week_percentage(1, '0000')
    assert sun_midnight == 0.0 # Start of week
    assert mon_midnight == 14.2857 # 1/7th of the way: (1440/10080)*100 ~ 1/7

@patch('update_places.gmaps.place')
def test_wrap_around_split(mock_place):
    """Verify Saturday night to Sunday morning split logic"""
    mock_place.return_value = {
        'status': 'OK',
        'result': {
            'name': 'Late Night Venue',
            'opening_hours': {
                'periods': [
                    {
                        'open': {'day': 6, 'time': '2200'},
                        'close': {'day': 0, 'time': '0200'}
                    }
                ]
            }
        }
    }

    result = fetch_place_data('dummy_id')
    intervals = result['percentage_periods']

    # We expect the Saturday night shift to be split into TWO intervals
    assert len(intervals) == 2
    # 1st interval should end with end of week
    assert intervals[0]['close'] == 100.0
    # 1st interval starts 2 hours before end of week:
    # 100 − (2 / (7 * 24 ) * 100) ~ 98.8095
    assert intervals[0]['close'] > 98.8
    # 2nd interval should start at the beginning of week
    assert intervals[1]['open'] == 0.0
    # 2nd interval starts 2 hour after the beginning of week:
    # 2 / (7 * 24 ) * 100 ~ 1.1905
    assert intervals[1]['close'] < 1.2

# --- VALIDATION TESTS ---

def test_invalid_day_index():
    """Should raise ValueError for day index 7"""
    with pytest.raises(ValueError):
        get_week_percentage(7, '1200')

def test_invalid_time_format():
    """Should raise ValueError for any string that isn't exactly HHMM"""
    with pytest.raises(ValueError):
        get_week_percentage(1, '900') # short
    with pytest.raises(ValueError):
        get_week_percentage(1, '9000') # 90 hours
    with pytest.raises(ValueError):
        get_week_percentage(1, 'ABCD') # not numeric

def test_valid_time_format():
    """Should complete without raising an error"""
    get_week_percentage(1, '0900')

# --- API RETURN TESTS ---

@patch('update_places.gmaps.place')
def test_incomplete_data_handling(mock_place):
    """Verify 'incomplete' error message is raised when 'close' is missing"""
    mock_place.return_value = {
        'status': 'OK',
        'result': {
            'name': 'Test Place',
            'opening_hours': {'periods': [{'open': {'day': 1, 'time': '0900'}}]}
        }
    }
    with pytest.raises(KeyError, match=r"(?i)incomplete"):
        fetch_place_data('dummy_id')

@patch('update_places.gmaps.place')
def test_fetch_place_api_error_message_passthrough(mock_place):
    """Verify the script uses Google's specific error message if provided"""
    google_reason = "Invalid 'place_id' parameter."

    mock_place.return_value = {
        'status': 'REQUEST_DENIED',
        'error_message': google_reason
    }

    with pytest.raises(ValueError) as excinfo:
        fetch_place_data('any_id')

    assert google_reason in str(excinfo.value)